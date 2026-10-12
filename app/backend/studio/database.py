from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import Project, Settings, StudioError, uid


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "studio.sqlite3"
        (self.root / "assets").mkdir(exist_ok=True)
        (self.root / "work").mkdir(exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(project_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(project_id,revision));
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, type TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, hash TEXT NOT NULL, path TEXT NOT NULL, mime TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, metadata TEXT NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS asset_hash ON assets(hash);
                CREATE TABLE IF NOT EXISTS budgets(project_id TEXT PRIMARY KEY, demo_limit INTEGER NOT NULL DEFAULT 20000000, total_limit INTEGER NOT NULL DEFAULT 100000000, cognitive_limit INTEGER NOT NULL DEFAULT 0, include_demo INTEGER NOT NULL DEFAULT 1, paused INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, kind TEXT NOT NULL, target_id TEXT, input_hash TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0, owner TEXT, external_id TEXT, UNIQUE(project_id,idempotency_key));
                CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state,lease_until,created);
                CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, project_id TEXT NOT NULL, category TEXT NOT NULL, phase TEXT NOT NULL, reserved INTEGER NOT NULL, settled INTEGER, settlement_kind TEXT, state TEXT NOT NULL, usage TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(project_id TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(project_id,key));
                CREATE TABLE IF NOT EXISTS workers(id TEXT PRIMARY KEY, pid INTEGER NOT NULL, heartbeat REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS secrets(id TEXT PRIMARY KEY, encrypted BLOB NOT NULL, version INTEGER NOT NULL DEFAULT 1);
            """)
        os.chmod(self.path, 0o600)

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=15, isolation_level=None, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def settings(self, c: sqlite3.Connection | None = None) -> Settings:
        if c is None:
            with self.connect() as c:
                return self.settings(c)
        row = c.execute("SELECT value FROM meta WHERE key='settings'").fetchone()
        return Settings.model_validate_json(row[0]) if row else Settings()

    def save_settings(self, s: Settings, c: sqlite3.Connection):
        previous=c.execute("SELECT value FROM meta WHERE key='settings'").fetchone()
        s.revision=(json.loads(previous[0]).get('revision',1)+1) if previous else 1
        c.execute("INSERT INTO meta VALUES('settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (s.model_dump_json(),))

    def get_project(self, project_id: str, c: sqlite3.Connection | None = None) -> Project:
        if c is None:
            with self.connect() as c:
                return self.get_project(project_id, c)
        row = c.execute("SELECT document FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise StudioError("作品不存在", "not_found", 404)
        return Project.model_validate_json(row[0])

    def projects(self) -> list[dict]:
        with self.connect() as c:
            return [json.loads(r[0]) for r in c.execute("SELECT document FROM projects ORDER BY rowid DESC")]

    def save_project(self, p: Project, c: sqlite3.Connection, *, expected: int | None = None):
        row = c.execute("SELECT revision FROM projects WHERE id=?", (p.id,)).fetchone()
        if row:
            if expected is not None and row[0] != expected:
                raise StudioError("作品已更新，请载入最新版本后再应用修改", "revision_conflict", 409)
            p.revision = row[0] + 1
        p.updated_at = time.time()
        document = p.model_dump_json()
        c.execute("INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document", (p.id, p.revision, document))
        c.execute("INSERT INTO revisions VALUES(?,?,?,?)", (p.id, p.revision, document, time.time()))
        c.execute("INSERT OR IGNORE INTO budgets(project_id) VALUES(?)", (p.id,))

    def event(self, c: sqlite3.Connection, project_id: str | None, kind: str, data: dict):
        c.execute("INSERT INTO events(project_id,type,data,created) VALUES(?,?,?,?)", (project_id, kind, dumps(data), time.time()))

    def events(self, after: int = 0, project_id: str | None = None) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM events WHERE id>? AND (? IS NULL OR project_id=?) ORDER BY id LIMIT 200", (after, project_id, project_id)).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    def job(self, job_id: str, c: sqlite3.Connection | None = None) -> dict:
        if c is None:
            with self.connect() as c:
                return self.job(job_id, c)
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise StudioError("任务不存在", "not_found", 404)
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def jobs(self, project_id: str) -> list[dict]:
        with self.connect() as c:
            rows = c.execute("SELECT id FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 100", (project_id,)).fetchall()
            return [self.job(row[0], c) for row in rows]

    def heartbeat(self, owner: str):
        with self.connect() as c:
            c.execute("INSERT INTO workers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET pid=excluded.pid,heartbeat=excluded.heartbeat", (owner, os.getpid(), time.time()))

    def worker_status(self) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM workers WHERE heartbeat>?", (time.time()-20,))]

    def claim(self, owner: str, lease_seconds: float = 120) -> dict | None:
        now = time.time()
        with self.transaction() as c:
            # A crash during an external submit never becomes a fresh request.
            expired = c.execute("SELECT * FROM jobs WHERE (state='submitting' OR (state='cancel_requested' AND external_id IS NULL)) AND lease_until<?", (now,)).fetchall()
            for job in expired:
                if job['kind']=='transcribe' and job['state']=='cancel_requested':
                    settle(c,self,job['id'],0,'local',{})
                    c.execute("UPDATE jobs SET state='cancelled',owner=NULL,lease_until=0,updated=? WHERE id=?",(now,job['id']))
                    self.event(c,job['project_id'],'job_cancelled',{'job_id':job['id']})
                    continue
                c.execute("UPDATE jobs SET state='unknown',error=?,updated=?,owner=NULL WHERE id=?", ("提交中断，供应商可能已接收；请查询原任务或明确对账", now, job["id"]))
                self.event(c, job["project_id"], "submission_unknown", {"job_id": job["id"]})
            row = c.execute("SELECT id FROM jobs WHERE ((state='queued' AND lease_until<?) OR ((state IN ('submitted','running','downloading') OR (state='cancel_requested' AND external_id IS NOT NULL)) AND lease_until<?)) AND (kind!='transcribe' OR NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind='transcribe' AND j.owner IS NOT NULL AND j.lease_until>? AND j.state IN ('queued','running'))) ORDER BY created LIMIT 1", (now, now, now)).fetchone()
            if not row:
                return None
            c.execute("UPDATE jobs SET owner=?,lease_until=?,updated=? WHERE id=?", (owner, now+lease_seconds, now, row[0]))
            return self.job(row[0], c)

    def touch(self, job_id: str, owner: str, lease_seconds: float = 120):
        with self.connect() as c:
            c.execute("UPDATE jobs SET lease_until=? WHERE id=? AND owner=?", (time.time()+lease_seconds, job_id, owner))

    def set_job_state(self, job_id: str, state: str, *, external_id: str | None = None, result: Any = None, error: str | None = None):
        with self.transaction() as c:
            job = self.job(job_id, c)
            if job['state'] == 'cancelled':
                raise StudioError('任务已取消', 'cancelled', 409)
            if job['state'] == 'cancel_requested' and state in {'submitting','submitted','running','downloading'}:
                state = 'cancel_requested'
            c.execute("UPDATE jobs SET state=?,external_id=COALESCE(?,external_id),result=COALESCE(?,result),error=?,updated=? WHERE id=?", (state, external_id, dumps(result) if result is not None else None, error, time.time(), job_id))
            self.event(c, job["project_id"], "job_state", {"job_id": job_id, "state": state, "error": error})

    def asset(self, asset_id: str, c: sqlite3.Connection | None = None) -> dict:
        if c is None:
            with self.connect() as c:
                return self.asset(asset_id, c)
        row = c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise StudioError("素材不存在", "not_found", 404)
        return {**dict(row), "metadata": json.loads(row["metadata"])}


def budget_snapshot(c: sqlite3.Connection, project_id: str) -> dict:
    budget = c.execute("SELECT * FROM budgets WHERE project_id=?", (project_id,)).fetchone()
    if not budget:
        raise StudioError("预算未初始化")
    data = dict(budget)
    rows = c.execute("SELECT * FROM attempts WHERE project_id=? ORDER BY created DESC", (project_id,)).fetchall()
    def sums(category: str, phase: str | None = None):
        selected = [r for r in rows if r["category"] == category and (phase is None or r["phase"] == phase)]
        return {"spent": sum(r["settled"] or 0 for r in selected), "reserved": sum(r["reserved"] for r in selected if r["state"] == "reserved")}
    data["demo"] = sums("media", "demo")
    data["media"] = sums("media", None if budget["include_demo"] else "formal")
    data["cognitive"] = sums("cognitive")
    data["attempts"] = [{**dict(r), "usage": json.loads(r["usage"]) if r["usage"] else None} for r in rows]
    tokens={'input':0,'output':0,'cached_input':0,'total':0,'calls_with_usage':0,'calls_missing_usage':0}
    for row in rows:
        if row['category']!='cognitive' or row['state']=='reserved':continue
        usage=json.loads(row['usage']) if row['usage'] else []
        records=usage.get('records',[]) if isinstance(usage,dict) else usage
        if not records:tokens['calls_missing_usage']+=1
        for record in records:
            current=(record.get('token_usage') or {}).get('last') if record.get('billing')=='codex_subscription' else record
            if not current or not any(k in current for k in ['input_tokens','prompt_tokens']):tokens['calls_missing_usage']+=1;continue
            inp=current.get('input_tokens',current.get('prompt_tokens',0));out=current.get('output_tokens',current.get('completion_tokens',0))
            tokens['input']+=inp;tokens['output']+=out;tokens['total']+=current.get('total_tokens',inp+out)
            tokens['cached_input']+=current.get('cached_input_tokens',current.get('input_tokens_details',{}).get('cached_tokens',0));tokens['calls_with_usage']+=1
    data['tokens']=tokens
    data['subscription_equivalent']={'micros':0,'missing_calls':0}
    for entry in data['attempts']:
        usage=entry.get('usage') or {}
        if isinstance(usage,dict):
            if 'api_equivalent_micros' in usage:
                data['subscription_equivalent']['micros']+=usage.get('api_equivalent_micros',0)
                data['subscription_equivalent']['missing_calls']+=usage.get('api_equivalent_missing',0)
            else:
                # Legacy records keep their cash ledger intact; current official rates
                # may provide an explicitly retrospective subscription comparison.
                from .models import Settings
                from .pricing import usage_cost
                settings_row=c.execute("SELECT value FROM meta WHERE key='settings'").fetchone()
                known=Settings.model_validate_json(settings_row[0]) if settings_row else Settings()
                for i,record in enumerate(usage.get('records',[])):
                    if record.get('billing')!='codex_subscription':continue
                    prices=usage.get('prices',[]);mid=prices[i].get('id') if i<len(prices) else None
                    model=next((m for m in known.models if m.id==mid),None)
                    value=usage_cost(model,record) if model else None
                    if value is None:data['subscription_equivalent']['missing_calls']+=1
                    else:data['subscription_equivalent']['micros']+=value
    return data


def reserve_job(c: sqlite3.Connection, db: Database, p: Project, *, key: str, request_hash: str, kind: str,
                target_id: str | None, input_hash: str, payload: dict, amount: int = 0,
                category: str = "media", phase: str = "formal") -> dict:
    existing = c.execute("SELECT id,request_hash FROM jobs WHERE project_id=? AND idempotency_key=?", (p.id, key)).fetchone()
    if existing:
        if existing["request_hash"] != request_hash:
            raise StudioError("相同请求键不能用于不同任务", "idempotency_conflict", 409)
        return db.job(existing["id"], c)
    if amount < 0:
        raise StudioError("费用不能为负数")
    b = budget_snapshot(c, p.id)
    if b["paused"]:
        raise StudioError("预算已暂停，请先对账", "budget_paused", 409)
    pool = b["cognitive"] if category == "cognitive" else b["media"]
    limit = b["cognitive_limit"] if category == "cognitive" else b["total_limit"]
    if category == "media" and phase == "demo" and not b["include_demo"]:
        pool, limit = b["demo"], b["demo_limit"]
    if pool["spent"] + pool["reserved"] + amount > limit:
        raise StudioError("本次费用超出剩余授权，请调整方案或明确增加预算", "budget_exceeded", 409)
    if category == "media" and phase == "demo" and b["demo"]["spent"] + b["demo"]["reserved"] + amount > b["demo_limit"]:
        raise StudioError("关键帧探索 / Demo 累计超出阶段上限", "demo_budget_exceeded", 409)
    job_id = uid()
    now = time.time()
    c.execute("INSERT INTO jobs(id,project_id,idempotency_key,request_hash,kind,target_id,input_hash,state,payload,created,updated) VALUES(?,?,?,?,?,?,?,'queued',?,?,?)", (job_id, p.id, key, request_hash, kind, target_id, input_hash, dumps(payload), now, now))
    c.execute("INSERT INTO attempts(id,job_id,project_id,category,phase,reserved,state,created) VALUES(?,?,?,?,?,?,'reserved',?)", (uid(), job_id, p.id, category, phase, amount, now))
    db.event(c, p.id, "budget_reserved", {"job_id": job_id, "micros": amount, "phase": phase, "category": category})
    return db.job(job_id, c)


def settle(c: sqlite3.Connection, db: Database, job_id: str, amount: int, kind: str = "usage", usage: Any = None):
    row = c.execute("SELECT * FROM attempts WHERE job_id=?", (job_id,)).fetchone()
    if not row or row["state"] != "reserved":
        return
    if amount < 0:
        raise StudioError("结算金额无效")
    c.execute("UPDATE attempts SET settled=?,state='settled',settlement_kind=?,usage=? WHERE job_id=?", (amount, kind, dumps(usage) if usage else None, job_id))
    if amount > row["reserved"]:
        c.execute("UPDATE budgets SET paused=1 WHERE project_id=?", (row["project_id"],))
        db.event(c, row["project_id"], "billing_overage", {"job_id": job_id, "reserved": row["reserved"], "actual": amount})
    db.event(c, row["project_id"], "budget_settled", {"job_id": job_id, "micros": amount, "kind": kind})

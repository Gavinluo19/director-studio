from __future__ import annotations

import asyncio
import io
import json
import os
import secrets
import time
import zipfile
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError
from urllib.parse import urlparse

from . import __version__
from .adapters import Adapters, check_url, safe_error
from .assets import Assets, media_environment
from .catalog import preset_catalog, clip_hash, get_model, deployment_hash
from .database import Database, budget_snapshot, dumps, settle
from .models import Command, Project, Settings, StudioError, render_hash, creative_hash, route_hash, anchor_hash, selected_candidate, uid
from .service import StudioService
from .vault import Vault
from .pricing import PriceBook
from .configuration import guide, upgrade_presets


def default_root() -> Path:
    return Path(os.environ.get("DIRECTOR_STUDIO_DATA", str(Path.home()/"Library"/"Application Support"/"DirectorStudio")))


def public_job(job: dict) -> dict:
    result = dict(job.get("result") or {})
    result.pop("download_urls",None)
    models=[{'id':x['model']['id'],'name':x['model']['name'],'api_model':x['model']['api_model']} for x in job.get('payload',{}).get('models',[])]
    return {k:job.get(k) for k in ["id","project_id","kind","target_id","state","error","created","updated","external_id"]} | {"result":result,"models":models}


def create_app(data_dir: Path | None = None, *, testing: bool = False, serve_frontend: bool = True) -> FastAPI:
    db = Database(data_dir or default_root())
    vault = Vault(db,use_keychain=not testing)
    assets, service = Assets(db), StudioService(db)
    adapters = Adapters(assets,vault)
    with db.transaction() as c:
        if not db.settings(c).connections:
            db.save_settings(preset_catalog(),c)
    pricebook=PriceBook(db)
    if not testing:
        with db.transaction() as c:
            settings=pricebook.bind(upgrade_presets(db.settings(c)))
            db.save_settings(settings,c)
    session_token, csrf_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    codex = None
    login_task = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        if login_task:login_task.cancel()
        if codex:await codex.close()

    app = FastAPI(title="片场 · 本地制作服务",version=__version__,lifespan=lifespan)
    app.state.db,app.state.vault,app.state.service = db,vault,service

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        host=request.headers.get("host", "").split(":")[0]
        if host not in ({"127.0.0.1","localhost","testserver"} if testing else {"127.0.0.1","localhost"}):
            return JSONResponse({"message":"仅允许本地访问"},status_code=403)
        origin=request.headers.get("origin")
        allowed={"http://127.0.0.1:8766","http://localhost:8766","http://127.0.0.1:8768","http://localhost:8768"}
        if host in {'127.0.0.1','localhost'}:allowed.add(f"http://{request.headers.get('host')}")
        if origin and origin not in allowed:
            return JSONResponse({"message":"请求来源不允许"},status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/bootstrap","/api/health"}:
            if request.cookies.get("studio_session")!=session_token:
                return JSONResponse({"code":"session_required","message":"请重新打开工作台建立本地会话"},status_code=401)
            if request.method not in {"GET","HEAD","OPTIONS"} and not secrets.compare_digest(request.headers.get("x-studio-csrf",""),csrf_token):
                return JSONResponse({"code":"csrf_required","message":"本地操作令牌已失效，请刷新"},status_code=403)
        response=await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"]="no-store"
            response.headers["X-Content-Type-Options"]="nosniff"
        return response

    @app.exception_handler(StudioError)
    async def studio_error(request, exc):
        return JSONResponse({"code":exc.code,"message":str(exc)},status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def validation_error(request,exc):
        return JSONResponse({'code':'validation','message':'；'.join(str(e.get('msg','输入无效')) for e in exc.errors())[:800]},status_code=422)

    @app.get("/api/capabilities")
    def capability_catalog():
        from .skills import capabilities
        return capabilities(db)

    @app.get("/api/health")
    def health():
        return {"version":__version__,"backend":True,"workers":db.worker_status(),**media_environment()}

    @app.get("/api/bootstrap")
    def bootstrap():
        with db.connect() as c:cursor=c.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        response=JSONResponse({"version":__version__,"csrf":csrf_token,"data_dir":str(db.root),"vault":vault.mode,"mode":"live","event_cursor":cursor})
        response.set_cookie("studio_session",session_token,httponly=True,samesite="strict",path="/")
        return response

    @app.get("/api/settings")
    def settings():
        s=db.settings()
        for connection in s.connections:
            connection.credential_version=vault.version(connection.id)
            connection.has_key=bool(connection.credential_version)
        return s.model_dump(mode="json")

    @app.get('/api/configuration-guide')
    def configuration_guide():return guide(pricebook.bind(db.settings()),pricebook.read())

    @app.post('/api/prices/refresh')
    async def refresh_prices():
        result=await pricebook.refresh()
        return {'sources':result['refresh_status'],'guide':guide(pricebook.bind(db.settings()),result)}

    @app.put("/api/settings")
    def save_settings(incoming: Settings):
        if len({c.id for c in incoming.connections})!=len(incoming.connections) or len({m.id for m in incoming.models})!=len(incoming.models):
            raise StudioError("连接或模型配置 ID 重复")
        if any(m.connection_id not in {c.id for c in incoming.connections} for m in incoming.models):
            raise StudioError("模型引用了不存在的连接")
        with db.transaction() as c:
            old=db.settings(c)
            if incoming.revision!=old.revision:
                raise StudioError('模型配置已有更新，请刷新后重新保存','settings_conflict',409)
            for conn in incoming.connections:
                previous=next((x for x in old.connections if x.id==conn.id),None)
                conn.has_key=bool(vault.version(conn.id))
                conn.credential_version=vault.version(conn.id)
                conn.status="configured" if conn.has_key else "unconfigured"
                conn.error="";conn.checked_at=None
                if previous and (previous.base_url,previous.auth,previous.region)==(conn.base_url,conn.auth,conn.region):
                    conn.status=previous.status;conn.error=previous.error;conn.checked_at=previous.checked_at
                if conn.auth=="codex" and conn.base_url:
                    raise StudioError("Codex 订阅通道不使用外部 API 地址")
                if conn.auth!='codex' and conn.base_url:
                    url=urlparse(conn.base_url)
                    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password:raise StudioError('服务地址必须为 HTTP(S)，不能在 URL 内嵌入凭据')
            if not testing:incoming=pricebook.bind(incoming)
            db.save_settings(incoming,c)
            db.event(c,None,"settings_saved",{"models":len(incoming.models),"connections":len(incoming.connections)})
        return incoming.model_dump(mode="json")

    @app.put("/api/connections/{connection_id}/key")
    async def put_key(connection_id: str, request: Request):
        body=await request.json()
        with db.transaction() as c:
            s=db.settings(c);conn=next((x for x in s.connections if x.id==connection_id),None)
            if not conn or conn.auth=="codex":raise StudioError("请选择普通 API 服务连接")
            if body.get('expected_url')!=conn.base_url:raise StudioError('连接地址已有变化，请重新确认凭据对应服务','settings_conflict',409)
            vault.put(connection_id,str(body.get("key", "")),c)
            conn.has_key=True;conn.status="configured";conn.error=""
            conn.credential_version=vault.version(conn.id,c)
            db.save_settings(s,c)
        return {"saved":True,"vault":vault.mode}

    async def codex_client():
        nonlocal codex
        if codex is None:
            from openai_codex import AsyncCodex,CodexConfig
            codex=AsyncCodex(CodexConfig(config_overrides=('forced_login_method="chatgpt"',)))
            await codex.__aenter__()
        return codex

    @app.get("/api/codex/status")
    async def codex_status():
        try:
            client=await codex_client()
            account=(await client.account()).model_dump(mode="json")
            model_data=(await client.models()).model_dump(mode="json")["data"]
            logged_in=bool(account.get("account") and account["account"].get("type")=="chatgpt")
            with db.transaction() as c:
                s=db.settings(c)
                connection=next((x for x in s.connections if x.auth=="codex"),None)
                if connection:
                    connection.status="ready" if logged_in else "unconfigured";connection.checked_at=time.time()
                    db.save_settings(s,c)
            return {"logged_in":logged_in,"billing":"codex_subscription","models":[{"id":m["model"],"name":m.get("display_name",m["model"]),"modalities":m.get("input_modalities",[])} for m in model_data]}
        except Exception as exc:
            return {"logged_in":False,"billing":"codex_subscription","models":[],"error":safe_error(exc)}

    @app.post("/api/codex/login")
    async def codex_login():
        nonlocal login_task
        client=await codex_client()
        if login_task and not login_task.done():raise StudioError("已有登录等待完成，请继续原浏览器登录")
        handle=await client.login_chatgpt()
        login_task=asyncio.create_task(handle.wait())
        return {"auth_url":handle.auth_url}

    @app.post("/api/connections/{connection_id}/validate")
    async def validate_connection(connection_id: str):
        s=db.settings();conn=next((x for x in s.connections if x.id==connection_id),None)
        if not conn:raise StudioError("连接不存在")
        if conn.auth=="codex":return await codex_status()
        try:
            response=await adapters.request("GET",conn,"models")
            data=response.json()
            conn.status="ready";conn.error=""
            models=[{"id":m.get("id",m.get("model", ""))} for m in data.get("data",[]) if isinstance(m,dict)]
        except StudioError as exc:
            # Some media providers do not expose a read-only model-list route.
            conn.status="configured" if conn.has_key and exc.code=="provider_rejected" else "unconfigured"
            conn.error="该服务未通过通用只读模型列表验证；配置已保存，首次有上限任务仍需实测。" if conn.status=="configured" else str(exc)
            models=[]
        conn.checked_at=time.time()
        with db.transaction() as c:
            latest=db.settings(c);current=next(x for x in latest.connections if x.id==connection_id)
            if (current.base_url,current.auth,current.credential_version)!=(conn.base_url,conn.auth,conn.credential_version):
                raise StudioError('连接在检查期间已有变化，请重新检查','settings_conflict',409)
            current.status=conn.status;current.error=conn.error;current.checked_at=conn.checked_at
            db.save_settings(latest,c)
        return {"connection":conn.model_dump(mode="json"),"models":models}

    @app.get("/api/projects")
    def projects():return [project_view(Project.model_validate(p)) for p in db.projects()]

    def project_view(p: Project):
        frames={a.id:bool(selected_candidate(a) and a.approved_hash==anchor_hash(p,s,a)) for s in p.shots for a in s.anchors}
        clips={s.id:False for s in p.shots}
        route_current=bool(p.creative_approved_hash==creative_hash(p) and p.route.approved_hash==route_hash(p))
        settings=db.settings()
        for item in p.route.items:
            shot=next((s for s in p.shots if s.id==item.shot_id),None)
            if shot:clips[shot.id]=bool(shot.clip_asset_id and shot.clip_input_hash==clip_hash(p,shot.id,item))
            if item.method=='generate':
                try:
                    model,conn=get_model(settings,item.model_id,'video')
                    if deployment_hash(model,conn)!=item.deployment_hash:route_current=False
                except StudioError:route_current=False
        return p.model_dump(mode='json')|{"_computed":{"frames":frames,"clips":clips,"creative_current":p.creative_approved_hash==creative_hash(p),"route_current":route_current,"render_current":bool(p.preview_asset_id and p.render_hash==render_hash(p)),"final_current":bool(p.preview_asset_id and p.final_approved_hash==render_hash(p))}}

    @app.post("/api/projects")
    async def new_project(request: Request):
        data=await request.json()
        return service.create_project(str(data.get("name","新的作品")),data.get("category","commerce"),data.get("region","cn")).model_dump(mode="json")

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):return project_view(db.get_project(project_id))

    @app.post("/api/projects/{project_id}/commands")
    def command(project_id: str, body: Command):return service.command(project_id,body)

    @app.get("/api/projects/{project_id}/budget")
    def budget(project_id: str):
        with db.connect() as c:return budget_snapshot(c,project_id)

    @app.get("/api/projects/{project_id}/jobs")
    def jobs(project_id: str):return [public_job(j) for j in db.jobs(project_id)]

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        with db.transaction() as c:
            job=db.job(job_id,c)
            if job["state"]=="queued":
                c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=?",(time.time(),job_id))
                settle(c,db,job_id,0,"not_submitted")
            elif job["state"] in {"submitting","submitted","running","downloading"}:
                c.execute("UPDATE jobs SET state='cancel_requested',updated=? WHERE id=?",(time.time(),job_id))
            else:raise StudioError("当前任务不能直接取消；结果不明时请先对账")
            db.event(c,job["project_id"],"cancel_requested",{"job_id":job_id,"note":"已提交的服务商任务不保证停止或退款"})
        return {"requested":True}

    @app.post("/api/jobs/{job_id}/reconcile")
    async def reconcile(job_id: str, request: Request):
        body=await request.json()
        with db.transaction() as c:
            job=db.job(job_id,c)
            if job["state"] not in {"unknown","failed","cancel_requested","succeeded","superseded","cancelled"}:raise StudioError("任务仍在执行，不能提前释放费用；请等待结果或查询原任务")
            if body.get("external_id") and job["kind"]=="generate_shot":
                if job['state'] in {'succeeded','superseded','cancelled'}:
                    raise StudioError('已完成任务不能重新关联远程任务')
                c.execute("UPDATE jobs SET external_id=?,state='submitted',error=NULL,lease_until=0,owner=NULL,updated=? WHERE id=?",(str(body["external_id"]),time.time(),job_id))
            elif body.get("explicit_confirmation") and "actual_micros" in body:
                amount=int(body["actual_micros"])
                if amount<0:raise StudioError("费用不能为负数")
                row=c.execute("SELECT state,settled,reserved FROM attempts WHERE job_id=?",(job_id,)).fetchone()
                if row["state"]=="reserved":settle(c,db,job_id,amount,"user_reconciled")
                else:c.execute("UPDATE attempts SET settled=?,settlement_kind='user_reconciled' WHERE job_id=?",(amount,job_id))
                if job['state'] not in {'succeeded','superseded','cancelled'}:
                    c.execute("UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?",("用户完成对账；如需再次生成，请创建新的有预算任务",time.time(),job_id))
                db.event(c,job['project_id'],'billing_adjusted',{'job_id':job_id,'previous_settled':row['settled'],'previous_reserved':row['reserved'],'actual_micros':amount,'actor':'local_user'})
                budget=budget_snapshot(c,job['project_id'])
                if any(budget[pool]['spent']+budget[pool]['reserved']>budget[limit] for pool,limit in [('demo','demo_limit'),('media','total_limit'),('cognitive','cognitive_limit')]):
                    c.execute('UPDATE budgets SET paused=1 WHERE project_id=?',(job['project_id'],))
            else:raise StudioError("提供原供应商任务 ID，或明确确认账单实际费用")
            db.event(c,job["project_id"],"job_reconciled",{"job_id":job_id,"note":str(body.get("note", ""))[:500]})
        return {"updated":True}

    @app.get("/api/assets")
    def asset_list():return assets.list()

    @app.post("/api/assets")
    async def upload(file: UploadFile=File(...)):
        data=await file.read(assets.MAX_BYTES+1)
        return await asyncio.to_thread(assets.ingest,data,file.filename or "asset",file.content_type or "")

    @app.get("/api/assets/{asset_id}/file")
    def file(asset_id: str):
        info=db.asset(asset_id)
        return FileResponse(assets.path(asset_id),media_type=info["mime"],filename=info["name"],content_disposition_type="inline")

    @app.get("/api/events")
    async def events(request: Request, after: int=0, project_id: str | None=None):
        async def stream():
            try:cursor=max(after,int(request.headers.get('last-event-id','0')))
            except ValueError:cursor=after
            while not await request.is_disconnected():
                rows=await asyncio.to_thread(db.events,cursor,project_id)
                for event in rows:
                    cursor=event["id"]
                    yield "id: "+str(cursor)+"\ndata: "+dumps(event)+"\n\n"
                if not rows:yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})

    @app.get("/api/projects/{project_id}/export")
    def export(project_id: str):
        p=db.get_project(project_id)
        if not p.preview_asset_id or p.final_approved_hash!=render_hash(p):raise StudioError("先确认当前成片版本，再导出")
        return FileResponse(assets.path(p.preview_asset_id),filename=p.name+".mp4",media_type="video/mp4")

    @app.get("/api/projects/{project_id}/revisions")
    def revisions(project_id: str):
        db.get_project(project_id)
        with db.connect() as c:
            return [{"revision":r[0],"created":r[1],"shots":len(json.loads(r[2]).get('shots',[]))} for r in c.execute('SELECT revision,created,document FROM revisions WHERE project_id=? ORDER BY revision DESC LIMIT 50',(project_id,))]

    @app.get("/api/projects/{project_id}/archive")
    def archive(project_id: str):
        p=db.get_project(project_id)
        archive_path=db.root/"work"/(p.id+"-archive.zip")
        with zipfile.ZipFile(archive_path,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json",p.model_dump_json(indent=2))
            manifest=[]
            for asset_id in set(p.asset_ids):
                info=db.asset(asset_id);path=assets.path(asset_id)
                name="assets/"+asset_id+path.suffix
                z.write(path,name)
                manifest.append({"id":asset_id,"entry":name,"hash":info["hash"],"name":info["name"],"mime":info["mime"],"metadata":info["metadata"]})
            z.writestr("assets.json",dumps(manifest))
            with db.connect() as c:
                z.writestr("budget.json",dumps(budget_snapshot(c,p.id)))
                history=[json.loads(r[0]) for r in c.execute('SELECT document FROM revisions WHERE project_id=? ORDER BY revision DESC LIMIT 50',(p.id,))]
                z.writestr('revisions.json',dumps(history))
            z.writestr("README.txt","本地项目备份，含真实素材与过程文件。不含 API Key、Codex 登录凭据或服务连接配置。\n")
        return FileResponse(archive_path,filename=p.name+"-项目包.zip",media_type="application/zip")

    @app.post('/api/import-archive')
    async def import_archive(file: UploadFile=File(...)):
        data=await file.read(assets.MAX_BYTES+1)
        if len(data)>assets.MAX_BYTES:raise StudioError('项目包过大')
        try:
            z=zipfile.ZipFile(io.BytesIO(data))
            info=z.infolist()
            if len(info)>2000 or sum(i.file_size for i in info)>1_000_000_000 or any(i.file_size>assets.MAX_BYTES for i in info):raise StudioError('项目包超出解压限制')
            if any(i.filename.startswith('/') or '..' in Path(i.filename).parts or '\\' in i.filename for i in info):raise StudioError('项目包包含不安全路径')
            raw=json.loads(z.read('project.json'))
            original=Project.model_validate(raw)
            manifest=json.loads(z.read('assets.json'))
            if not isinstance(manifest,list):raise StudioError('素材清单格式错误')
            verified=[]
            for item in manifest:
                if not item['entry'].startswith('assets/'):raise StudioError('素材路径不在项目包目录内')
                blob=z.read(item['entry'])
                if hashlib.sha256(blob).hexdigest()!=item['hash']:raise StudioError('项目包素材校验失败')
                verified.append((item,blob))
            history=json.loads(z.read('revisions.json')) if 'revisions.json' in z.namelist() else []
            if not isinstance(history,list) or len(history)>50:raise StudioError('历史版本格式无效')
            for entry in history:Project.model_validate(entry)
            old_budget=json.loads(z.read('budget.json')) if 'budget.json' in z.namelist() else {}
            rows=old_budget.get('attempts',[])
            for row in rows:
                if row.get('category') not in {'media','cognitive'} or row.get('phase') not in {'demo','formal'}:raise StudioError('费用记录分类无效')
                if row.get('state') not in {'reserved','settled'}:raise StudioError('费用记录状态无效')
                if any(not isinstance(row.get(k,0),int) or not 0<=row.get(k,0)<=1_000_000_000_000 for k in ['reserved']):raise StudioError('费用记录金额无效')
                if row.get('settled') is not None and (not isinstance(row['settled'],int) or not 0<=row['settled']<=1_000_000_000_000):raise StudioError('费用记录金额无效')
        except StudioError:raise
        except Exception:raise StudioError('项目包损坏或不是片场导出的格式')
        mapping={}
        for item,blob in verified:
            created=await asyncio.to_thread(assets.ingest,blob,item['name'],item['mime'],item.get('metadata',{}))
            mapping[item['id']]=created['id']
        asset_fields={'source_asset_id','asset_id','asset_ids','source_video_id','source_generated_asset_id','clip_asset_id','preview_asset_id','music_asset_id','narration_asset_id','reference_asset_ids','evidence_asset_ids'}
        def remap(node):
            if isinstance(node,dict):
                for key,value in node.items():
                    if key in asset_fields:
                        if isinstance(value,list):
                            if any(x not in mapping for x in value):raise StudioError('项目包缺少引用的素材')
                            node[key]=[mapping[x] for x in value]
                        elif isinstance(value,str):
                            if value not in mapping:raise StudioError('项目包缺少引用的素材')
                            node[key]=mapping[value]
                    else:remap(value)
            elif isinstance(node,list):
                for value in node:remap(value)
        remap(raw)
        for entry in history:remap(entry)
        p=Project.model_validate(raw);old_id=p.id;p.id=uid();p.revision=1;p.name+=' · 恢复副本';p.created_at=time.time();p.stage='create'
        p.creative_approved_hash=None;p.route.approved_hash=None;p.final_approved_hash=None
        for shot in p.shots:
            for anchor in shot.anchors:
                anchor.approved_hash=None
                for candidate in anchor.candidates:candidate.asset_hash=db.asset(candidate.asset_id)['hash']
        with db.transaction() as c:
            for entry in history:
                restored=Project.model_validate(entry);restored.id=p.id
                c.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)',(p.id,restored.revision,restored.model_dump_json(),restored.updated_at))
            p.revision=max([int(e['revision']) for e in history]+[0])+1
            db.save_project(p,c)
            for row in rows:
                jid=uid();reserved=row['state']=='reserved'
                if reserved:
                    c.execute("INSERT INTO jobs(id,project_id,idempotency_key,request_hash,kind,input_hash,state,payload,error,created,updated) VALUES(?,?,?,?,?,'','unknown',?,?,?,?)",(jid,p.id,jid,jid,'imported',dumps({'project':p.model_dump(mode='json'),'models':[]}),'从备份导入的在途费用，需要先核对原服务商任务；不会自动再次提交',time.time(),time.time()))
                c.execute("INSERT INTO attempts(id,job_id,project_id,category,phase,reserved,settled,settlement_kind,state,created) VALUES(?,?,?,?,?,?,?,?,?,?)",(uid(),jid,p.id,row['category'],row['phase'],row['reserved'],None if reserved else row.get('settled',0),'imported_history','reserved' if reserved else 'settled',time.time()))
            db.event(c,p.id,'archive_imported',{'source_project_id':old_id,'note':'采用图与制作批准需要在本机重新确认；历史费用保留'})
        return project_view(p)

    @app.get('/api/projects/{project_id}/subtitles')
    def subtitles(project_id: str):
        p=db.get_project(project_id)
        def stamp(seconds):
            ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
            return f'{h:02}:{m:02}:{s:02},{ms:03}'
        text='\n\n'.join(f'{i+1}\n{stamp(c.start)} --> {stamp(c.start+c.duration)}\n{c.text}' for i,c in enumerate(p.audio.subtitles))+'\n'
        return Response(text,media_type='text/plain; charset=utf-8',headers={'Content-Disposition':'attachment; filename="subtitles.srt"'})

    if serve_frontend:
        dist=Path(__file__).resolve().parents[2]/"frontend"/"dist"
        if dist.exists():
            @app.get('/b0')
            def legacy_frontend():return FileResponse(dist/'index.html')
            app.mount("/",StaticFiles(directory=dist,html=True),name="frontend")
    return app

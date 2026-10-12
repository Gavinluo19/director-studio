from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

from .adapters import Adapters, MediaSubmission, UnknownSubmission, safe_error
from .assets import Assets
from .catalog import clip_hash, deployment_hash, get_model
from .cognition import Cognition
from .database import Database, dumps, settle
from .media import Media
from .models import Candidate, Connection, ModelProfile, Project, ReviewIssue, StudioError, ScriptBlock, Shot, AudioCue, Transcript, EditProposal, VideoCandidate, anchor_hash, digest, render_hash, uid
from .service import anchor_for, narration_hash, shot_for
from .vault import Vault


class Worker:
    def __init__(self, db: Database, vault: Vault, adapters: Adapters | None = None):
        self.db, self.assets = db, Assets(db)
        self.adapters = adapters or Adapters(self.assets, vault)
        self.cognition = Cognition(self.adapters)
        self.media = Media(self.assets)
        self.owner = uid()
        self.active: dict[str, asyncio.Task] = {}
        self.stopping = False

    def deployments(self, job: dict):
        return [(ModelProfile.model_validate(x["model"]), Connection.model_validate(x["connection"])) for x in job["payload"].get("models", [])]

    def mark_submitting(self, job_id: str):
        with self.db.transaction() as c:
            row = self.db.job(job_id, c)
            if row["state"] in {"cancelled", "cancel_requested"}:
                raise StudioError("任务已请求停止", "cancelled", 409)
            c.execute("UPDATE jobs SET state='submitting',updated=? WHERE id=?", (time.time(), job_id))
            self.db.event(c, row["project_id"], "job_state", {"job_id": job_id, "state": "submitting"})

    async def store_media(self, submission: MediaSubmission, job: dict, name: str, conn: Connection | None = None) -> dict:
        if submission.data is not None:
            return await asyncio.to_thread(self.assets.ingest, submission.data, name, submission.mime, {"job_id": job["id"], "provider": conn.name if conn else "local"})
        if not submission.urls:
            raise StudioError("生成任务没有返回产物", "empty_provider_result", 409)
        self.db.set_job_state(job["id"], "downloading", result={"download_urls": submission.urls, "usage": submission.usage or {}, "name": name})
        data, mime = await self.adapters.download(submission.urls[0], allow_local=bool(conn and conn.allow_local))
        return await asyncio.to_thread(self.assets.ingest, data, name, mime, {"job_id": job["id"], "provider": conn.name if conn else "local"})

    async def run_job(self, job: dict):
        payload = job["payload"]
        p = Project.model_validate(payload["project"])
        work = self.db.root/"work"/job["id"]
        work.mkdir(parents=True, exist_ok=True)
        deployments = self.deployments(job)
        result: dict = {}
        usage: list[dict] = []
        try:
            if self.db.job(job["id"])["state"] == "cancelled":
                return
            # An edited endpoint/price cannot be used under an old approval.
            settings = self.db.settings()
            for index, (model, connection) in enumerate(deployments):
                current_model, current_connection = get_model(settings, model.id)
                if payload['models'][index].get('approval_hash',deployment_hash(model, connection)) != deployment_hash(current_model, current_connection):
                    raise StudioError("任务创建后模型配置或价格发生变化，请重新确认", "configuration_changed", 409)
            kind = job["kind"]
            if job["state"] == "downloading" and (job.get("result") or {}).get("download_urls"):
                saved = job["result"]
                conn = deployments[0][1] if deployments else None
                asset = await self.store_media(MediaSubmission(urls=saved["download_urls"]), job, saved.get("name", "产物.mp4"), conn)
                result = {"asset_id": asset["id"]}
                if kind == "generate_shot":
                    shot = shot_for(p, job["target_id"])
                    normalized = await asyncio.to_thread(self.media.normalize_video, asset["id"], p, shot, payload["route_item"]["resolution"], work)
                    result["asset_id"] = normalized["id"]
                    result["source_asset_id"] = asset["id"]
            elif kind == 'transcribe':
                import fcntl
                # Process-wide file lock protects the GPU even if a stale job lease is recovered.
                lock_dir=Path.home()/'Library/Caches/DirectorStudio'
                lock_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
                lock=(lock_dir/'transcribe.lock').open('a+')
                try:
                    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:
                        with self.db.transaction() as c:
                            c.execute('UPDATE jobs SET owner=NULL,lease_until=? WHERE id=?',(time.time()+2,job['id']))
                        return
                    self.db.set_job_state(job['id'],'running')
                    output=work/'transcript.json'
                    source=self.assets.path(job['target_id'])
                    with (work/'transcription.log').open('wb') as log:
                        proc=await asyncio.create_subprocess_exec(sys.executable,'-m','studio.transcription',str(source),str(output),payload['request'].get('language','auto'),stdout=log,stderr=log)
                        started=time.monotonic()
                        try:
                            while proc.returncode is None:
                                if time.monotonic()-started>1800:raise StudioError('本地转写超过 30 分钟，可缩短素材后重试','transcription_timeout',409)
                                if self.db.job(job['id'])['state'] in {'cancelled','cancel_requested'}:
                                    proc.terminate();await proc.wait()
                                    self.complete(job,{},[]);return
                                try:await asyncio.wait_for(proc.wait(),timeout=.5)
                                except asyncio.TimeoutError:continue
                            if proc.returncode!=0:raise StudioError('本地转写失败，请检查转写依赖与录音；任务日志已保存','transcription_failed',409)
                        finally:
                            if proc.returncode is None:
                                proc.terminate();await proc.wait()
                    result=json.loads(output.read_text())
                finally:lock.close()
            elif kind in {"director", "plan_content", "refine_shot", "refine_transcript", "ai_review"}:
                self.mark_submitting(job["id"])
                if kind == "director":
                    result, usage = await self.cognition.director(p, payload["request"].get("message", p.brief), *deployments[0],selection={k:v for k,v in payload['request'].items() if k in {'shot_id','anchor_id','transcript_id'}},skip_visual=payload.get('skip_visual',False))
                elif kind == "plan_content":
                    result, usage = await self.cognition.plan(p, deployments, job["id"],reuse_script=bool(payload["request"].get("reuse_script")))
                elif kind == "refine_shot":
                    instruction=payload['request'].get('instruction','改善镜头表达与图片提示词')
                    if payload['request'].get('skill_id'):
                        from .skills import instructions
                        instruction=instructions(payload['request']['skill_id'])+'\n'+instruction
                    result, usage = await self.cognition.refine_shot(p, job["target_id"], instruction, *deployments[0])
                elif kind == 'refine_transcript':
                    result,usage=await self.cognition.refine_transcript(p,job['target_id'],payload['request'].get('instruction','保留完整观点，去掉明确重复'),*deployments[0])
                else:
                    duration = sum(s.duration for s in p.shots)
                    frame_ids = [await asyncio.to_thread(self.assets.frame, p.preview_asset_id, duration*fraction, work) for fraction in [.1,.35,.6,.85]]
                    result, usage = await self.cognition.review(p, *deployments[0], frame_ids)
                    result["evidence_asset_ids"] = frame_ids
            elif kind == "generate_image":
                self.mark_submitting(job["id"])
                model, connection = deployments[0]
                sub = await self.adapters.image(model, connection, payload["prompt"], payload["reference_asset_ids"])
                asset = await self.store_media(sub, job, "关键帧候选.png", connection)
                result = {"asset_id": asset["id"]}; usage = [sub.usage or {}]
            elif kind == "generate_shot":
                shot = shot_for(p, job["target_id"])
                item = payload["route_item"]
                if item["method"] in {"local", "reuse"}:
                    self.db.set_job_state(job["id"], "running")
                    asset = await asyncio.to_thread(self.media.local_clip, p, shot, item["resolution"], work, item.get("local_motion","none"))
                    result = {"asset_id": asset["id"]}
                else:
                    model, connection = deployments[0]
                    external_id = job["external_id"]
                    if not external_id:
                        refs = [(item["anchor_usage"].get(a.id, "review"), a) for a in shot.anchors]
                        images = [(role, next(c.asset_id for c in a.candidates if c.id == a.selected_id)) for role,a in refs if role != "review" and a.selected_id]
                        self.mark_submitting(job["id"])
                        sub = await self.adapters.video_submit(model, connection, p.global_style+"\n"+shot.visual+"\n"+shot.motion, images, item["native_duration"], item["resolution"], p.aspect)
                        external_id = sub.external_id
                        self.db.set_job_state(job["id"], "submitted", external_id=external_id)
                    poll = await self.adapters.video_poll(model, connection, external_id)
                    if poll["state"] == "failed":
                        raise StudioError("供应商任务失败；已保留任务ID和费用记录，请核对账单后决定重试", "remote_task_failed", 409)
                    if poll["state"] != "succeeded":
                        if time.time()-job["created"] > 3600:
                            raise UnknownSubmission("视频任务已等待超过一小时，保留原任务等待对账")
                        with self.db.transaction() as c:
                            c.execute("UPDATE jobs SET state=CASE WHEN state='cancel_requested' THEN state ELSE 'running' END,owner=NULL,lease_until=?,updated=? WHERE id=?", (time.time()+5,time.time(),job["id"]))
                        return
                    raw = await self.store_media(MediaSubmission(urls=poll["urls"]), job, "原始生成视频.mp4", connection)
                    asset = await asyncio.to_thread(self.media.normalize_video, raw["id"], p, shot, item["resolution"], work)
                    result = {"asset_id": asset["id"], "source_asset_id": raw["id"]}; usage = [poll.get("usage",{})]
            elif kind == "generate_tts":
                model, connection = deployments[0]
                cue_assets = list((job.get("result") or {}).get("cue_assets", []))
                for cue in p.audio.narration:
                    if not cue.text.strip() or any(i[0] == cue.id for i in cue_assets):
                        continue
                    self.mark_submitting(job["id"])
                    sub = await self.adapters.audio(model, connection, text=cue.text, duration=cue.duration, voice=p.audio.voice)
                    asset = await self.store_media(sub, job, "旁白片段.mp3", connection)
                    cue_assets.append((cue.id,asset["id"])); usage.append(sub.usage or {})
                    self.db.set_job_state(job["id"], "running", result={"cue_assets":cue_assets})
                asset = await asyncio.to_thread(self.media.stitch_narration,p,cue_assets,work)
                result = {"asset_id":asset["id"], "cue_assets":cue_assets}
            elif kind == "generate_music":
                model, connection = deployments[0]
                self.mark_submitting(job["id"])
                sub = await self.adapters.audio(model,connection,text=p.audio.music_prompt,duration=p.target_duration,voice="")
                asset = await self.store_media(sub,job,"背景音乐.mp3",connection)
                result = {"asset_id":asset["id"]}; usage=[sub.usage or {}]
            elif kind == "render":
                self.db.set_job_state(job["id"], "running")
                asset = await asyncio.to_thread(self.media.render,p,work)
                result = {"asset_id":asset["id"], "technical_checks":asset["metadata"]}
            else:
                raise StudioError("任务类型未实现")
            self.complete(job,result,usage)
        except UnknownSubmission as exc:
            self.db.set_job_state(job["id"], "unknown", error=str(exc))
        except Exception as exc:
            error = safe_error(exc)
            latest = self.db.job(job["id"])
            if latest.get("external_id") and isinstance(exc, StudioError) and exc.code in {"network_error", "quota_or_rate_limit", "authentication", "configuration_changed", "connection_unconfigured"}:
                self.db.set_job_state(job["id"], "unknown", error="原视频任务仍可能执行，保留费用待核对。"+error)
                return
            if isinstance(exc, StudioError) and exc.code == "download_failed":
                # Keep a paid result address and allow download recovery without resubmission.
                with self.db.transaction() as c:
                    c.execute("UPDATE jobs SET state='downloading',error=?,owner=NULL,lease_until=?,updated=? WHERE id=?", (error,time.time()+15,time.time(),job["id"]))
                return
            with self.db.transaction() as c:
                current = self.db.job(job["id"],c)
                attempt = c.execute("SELECT * FROM attempts WHERE job_id=?",(job["id"],)).fetchone()
                # Before submission: release. After a potentially paid call: retain a
                # clearly labelled conservative charge, never pretend it cost zero.
                if current['state'] == 'cancelled':
                    return
                charged = current["state"] not in {"queued","cancelled"} and bool(deployments)
                if len(deployments)==1 and isinstance(exc,StudioError) and (exc.code=='input_budget_exceeded' or getattr(exc,'definitely_unbilled',False)):
                    charged=False # Local input validation happened before any provider request.

                saved_usage=(current.get('result') or {}).get('usage_records',usage)
                amount=attempt['reserved'] if charged else 0;billing='ceiling_estimate' if charged else 'not_submitted'
                if len(saved_usage)==len(deployments) and deployments:
                    from .pricing import usage_cost
                    values=[usage_cost(model,entry) for (model,_),entry in zip(deployments,saved_usage)]
                    if all(v is not None for v in values):
                        amount=sum(v for v,(model,_) in zip(values,deployments) if model.adapter!='codex');billing='usage_estimate'
                settle(c,self.db,job["id"],amount,billing,{'records':saved_usage,'note':'保留已返回的模型用量；不足时仍按保守估计记账'})
                c.execute("UPDATE jobs SET state='failed',error=?,owner=NULL,lease_until=0,updated=? WHERE id=?",(error,time.time(),job["id"]))
                self.db.event(c,job["project_id"],"job_failed",{"job_id":job["id"],"error":error})

    def complete(self, job: dict, result: dict, usage: list[dict]):
        with self.db.transaction() as c:
            current_job = self.db.job(job["id"],c)
            if current_job["state"] in {"succeeded","superseded","cancelled"}:
                return
            p = self.db.get_project(job["project_id"],c)
            original = Project.model_validate(job["payload"]["project"])
            state = "succeeded"
            kind = job["kind"]
            if current_job["state"] == "cancel_requested":
                state = "cancelled"
            elif kind == 'transcribe':
                from .editing import validate_range
                from .models import SourceRange
                t=Transcript(asset_id=job['target_id'],engine='mlx-whisper-0.4.3',job_id=job['id'],**result)
                for seg in t.segments:validate_range(self.db,c,p,SourceRange(asset_id=t.asset_id,start=seg.start,end=seg.end))
                if not any(t.job_id==job['id'] for t in p.transcripts):p.transcripts.append(t)
                result['transcript_id']=t.id
            elif kind in {'refine_shot','refine_transcript'}:
                from .editing import signature, transcript_for, transcript_signature
                if kind=='refine_shot':
                    original_shot=shot_for(original,job['target_id'])
                    e=EditProposal(kind='shot',target_id=original_shot.id,source_hash=signature(original_shot),
                                   changes={k:result[k] for k in ['visual','motion','prompts']},summary=result.get('explanation','镜头修改建议'),
                                   impacts=['仅选中镜头及相关关键帧待复核','其余采用素材保留；生成另行核价'])
                else:
                    t=transcript_for(original,job['target_id'])
                    e=EditProposal(kind='transcript',target_id=t.id,source_hash=transcript_signature(t),
                                   changes={'keep_ids':result['keep_ids']},summary=result['explanation'],impacts=['仅修改段落保留状态','应用到剪辑前可以继续调整，原片不变'])
                e.skill_id=job['payload']['request'].get('skill_id');e.skill_version=job['payload']['request'].get('skill_version')
                p.edit_proposals.append(e);result['proposal_id']=e.id
            elif kind == "generate_image":
                try:
                    shot, anchor = anchor_for(p,job["target_id"])
                    model = self.deployments(job)[0][0]
                    anchor.candidates.append(Candidate(asset_id=result["asset_id"],asset_hash=self.db.asset(result['asset_id'],c)['hash'],prompt=job["payload"]["prompt"],prompt_hash=job["input_hash"],model_id=model.id,model_name=model.name,api_model=model.api_model,task_id=job["id"]))
                    if anchor_hash(p,shot,anchor) != job["input_hash"]:
                        state = "superseded"
                except StudioError:
                    state = "superseded"
            elif kind == "generate_shot":
                item = next((i for i in p.route.items if i.shot_id==job["target_id"]),None)
                from .editing import shot_design, seed_candidates
                shot=next((s for s in p.shots if s.id==job['target_id']),None)
                seed_candidates(p)
                candidate=None
                if shot:
                    before=shot_for(original,shot.id)
                    candidate=VideoCandidate(asset_id=result['asset_id'],source_asset_id=result.get('source_asset_id'),task_id=job['id'],
                                             model_id=job['payload']['route_item'].get('model_id') or 'local',input_hash=job['input_hash'],
                                             source_interval=next((r.model_dump() for r in original.source_ranges if r.id==before.source_range_id),None),
                                             design=shot_design(before),route=job['payload']['route_item'])
                    shot.video_candidates.append(candidate);result['candidate_id']=candidate.id
                if item and clip_hash(p,job["target_id"],item)==job["input_hash"]:
                    if original.workbench_version<2 or item.method in {'local','reuse'}:
                        shot.clip_asset_id=result["asset_id"];shot.clip_input_hash=job["input_hash"]
                        shot.source_generated_asset_id=result.get('source_asset_id');shot.selected_video_id=candidate.id
                else:
                    state="superseded"
            elif kind == "generate_tts":
                if narration_hash(p)==job["input_hash"]:
                    p.audio.narration_asset_id=result["asset_id"];p.audio.narration_hash=job["input_hash"];p.final_approved_hash=None
                else: state="superseded"
            elif kind == "generate_music":
                if digest(p.audio.music_prompt)==job["input_hash"]:
                    p.audio.music_asset_id=result["asset_id"];p.final_approved_hash=None
                else: state="superseded"
            elif kind == "render":
                if render_hash(p)==job["input_hash"]:
                    p.preview_asset_id=result["asset_id"];p.render_hash=job["input_hash"];p.final_approved_hash=None;p.stage="review"
                else: state="superseded"
            elif kind == "director":
                p.messages.append({"id":uid(),"role":"assistant","text":result["message"],"question":result.get("question", ""),"job_id":job["id"],"models":[m.name for m,_ in self.deployments(job)]})
                if result.get("proposal") and p.proposal==original.proposal and p.brief==original.brief:
                    p.proposal=result["proposal"];p.proposal_approved_hash=None
            elif kind=='plan_content' and not p.blocks and p.brief==original.brief and p.proposal==original.proposal:
                p.blocks=[ScriptBlock.model_validate(b) for b in result['blocks']]
                p.shots=[Shot.model_validate(s) for s in result['shots']]
                p.audio.narration=[AudioCue.model_validate(a) for a in result['narration']]
                p.audio.subtitles=[AudioCue.model_validate(a) for a in result['subtitles']]
                p=Project.model_validate(p.model_dump())
                p.stage='create';p.creative_approved_hash=None;p.route.approved_hash=None;p.final_approved_hash=None
                result['auto_applied']=True
            elif kind == "ai_review":
                if p.render_hash==original.render_hash:
                    for issue in result.get("issues",[]):
                        p.review_issues.append(ReviewIssue(**issue,source="ai",evidence_asset_ids=result.get("evidence_asset_ids",[])))
                    p.messages.append({"id":uid(),"role":"assistant","text":result["summary"]+"\n覆盖限制："+result["coverage_limit"],"job_id":job["id"]})
                    p.final_approved_hash=None
                else:state="superseded"
            # Only an untouched empty draft is populated automatically. Existing
            # scripts and refined prompts require a later adoption command.
            for asset_id in [result.get("asset_id"),result.get("source_asset_id"),*result.get("evidence_asset_ids",[]),*[x[1] for x in result.get("cue_assets",[])]]:
                if asset_id and asset_id not in p.asset_ids:
                    p.asset_ids.append(asset_id)
            from .editing import expire_proposals
            expire_proposals(p)
            self.db.save_project(p,c)
            attempt=c.execute("SELECT * FROM attempts WHERE job_id=?",(job["id"],)).fetchone()
            billing="local" if not self.deployments(job) else "codex_subscription" if all(m.adapter=="codex" for m,_ in self.deployments(job)) else "ceiling_estimate"
            prices=[m.model_dump(mode='json',include={'id','api_model','price_unit','price_cny','price_currency','price_native','fx_rate','fx_date','price_source'}) for m,_ in self.deployments(job)]
            from .pricing import usage_cost
            from datetime import datetime,timezone
            values=[];equivalent=0;equivalent_missing=0
            for i,(model,_) in enumerate(self.deployments(job)):
                calculated=usage_cost(model,usage[i] if i<len(usage) else {},at=datetime.fromtimestamp(job['created'],timezone.utc))
                values.append(calculated)
                if model.adapter=='codex':
                    if calculated is None:equivalent_missing+=1
                    else:equivalent+=calculated
            amount=attempt['reserved']
            if kind in {'director','plan_content','refine_shot','refine_transcript','ai_review'} and values and all(v is not None for v in values):
                amount=sum(v for v,(model,_) in zip(values,self.deployments(job)) if model.adapter!='codex')
                billing='codex_subscription' if all(m.adapter=='codex' for m,_ in self.deployments(job)) else 'usage_estimate'
            price_records=[m.pricing.model_dump(mode='json') if m.pricing else None for m,_ in self.deployments(job)]
            settle(c,self.db,job["id"],amount,billing,{'records':usage,'prices':prices,'official_price_snapshots':price_records,'api_equivalent_micros':equivalent,'api_equivalent_missing':equivalent_missing})
            c.execute("UPDATE jobs SET state=?,result=?,error=NULL,owner=NULL,lease_until=0,updated=? WHERE id=?",(state,dumps(result),time.time(),job["id"]))
            self.db.event(c,p.id,"job_completed",{"job_id":job["id"],"state":state,"revision":p.revision})

    async def run(self):
        async def beat():
            while not self.stopping:
                self.db.heartbeat(self.owner)
                for job_id in list(self.active):
                    self.db.touch(job_id,self.owner)
                await asyncio.sleep(5)
        heartbeat=asyncio.create_task(beat())
        try:
            while not self.stopping:
                for job_id, task in list(self.active.items()):
                    if task.done():
                        try:task.result()
                        except Exception:pass
                        del self.active[job_id]
                if len(self.active)<2:
                    job=self.db.claim(self.owner)
                    if job:self.active[job["id"]]=asyncio.create_task(self.run_job(job))
                await asyncio.sleep(.25)
        finally:
            self.stopping=True;heartbeat.cancel()
            for task in self.active.values():task.cancel()
            await asyncio.gather(*self.active.values(),return_exceptions=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--data-dir",type=Path,required=True)
    args=parser.parse_args()
    os.environ["LANGSMITH_TRACING"]="false";os.environ["LANGCHAIN_TRACING_V2"]="false"
    db=Database(args.data_dir);worker=Worker(db,Vault(db))
    async def run():
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGTERM,signal.SIGINT):loop.add_signal_handler(sig,lambda:setattr(worker,"stopping",True))
        await worker.run()
    asyncio.run(run())


if __name__=="__main__":main()

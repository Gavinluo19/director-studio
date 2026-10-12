from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

from .assets import Assets
from .catalog import clip_hash, deployment_hash, generation_hash, estimate, get_model, suggest_route, choose_cognitive_model, local_compatible
from .database import Database, budget_snapshot, dumps, reserve_job
from .models import (Anchor, AudioCue, Candidate, Command, Project, ReviewIssue, RoutePlan, SoundEffect,
                     ScriptBlock, Shot, StudioError, anchor_hash, creative_hash, digest,
                     render_hash, route_hash, selected_candidate, uid)



def validate_video_route(shot, item, m):
    if shot.requirements.audio=='native_dialogue':
        raise StudioError('当前视频适配器未接通原生对白，不能以无声视频替代','capability_mismatch',409)
    if item.resolution not in m.resolutions:
        raise StudioError("所选模型不支持该原生规格")
    if m.durations and item.native_duration not in m.durations:
        raise StudioError("计费时长不是模型支持的时长")
    if not m.min_duration<=item.native_duration<=m.max_duration:
        raise StudioError("计费时长超过当前模型声明的范围")
    if item.native_duration < shot.duration:
        raise StudioError("生成时长不能小于镜头时长")
    if item.native_duration != int(item.native_duration):
        raise StudioError('当前视频适配器需要整数秒计费时长')
    known = {a.id for a in shot.anchors}
    if set(item.anchor_usage) - known:
        raise StudioError('路线引用了其他镜头的关键帧')
    selected = [(item.anchor_usage.get(a.id, 'review'), a) for a in shot.anchors]
    active = [(role, a) for role, a in selected if role != 'review']
    if any(role == 'reference' for role, _ in active):
        raise StudioError('当前视频适配器只接入首帧或首尾帧；额外状态用于审片，不可声称为生成硬控制')
    if sum(role == 'first' for role, _ in active) != 1 or sum(role == 'last' for role, _ in active) > 1:
        raise StudioError('视频路线必须有且仅有一个首帧，至多一个尾帧')
    if len(active) > m.max_reference_images or any(not a.selected_id for _, a in active):
        raise StudioError('路线图像输入超过模型上限，或尚未采用候选图')
    if any(role == 'last' for role, _ in active) and (not m.first_last or m.adapter != 'ark_video'):
        raise StudioError('所选适配器尚未接通尾帧控制')
    for anchor in shot.anchors:
        use = item.anchor_usage.get(anchor.id, 'review')
        if anchor.control_required and (use not in {'first','last'} or (anchor.role=='start' and use!='first') or (anchor.role=='end' and use!='last') or anchor.role in {'action','reference'}):
            raise StudioError('此关键帧要求精确控制，当前路线不能用首尾帧替代镜头中间状态')

def shot_for(p: Project, shot_id: str) -> Shot:
    found = next((s for s in p.shots if s.id == shot_id), None)
    if not found:
        raise StudioError("镜头不存在", "not_found", 404)
    return found


def anchor_for(p: Project, anchor_id: str) -> tuple[Shot, Anchor]:
    for shot in p.shots:
        for anchor in shot.anchors:
            if anchor.id == anchor_id:
                return shot, anchor
    raise StudioError("关键帧位置不存在", "not_found", 404)


def narration_hash(p: Project) -> str:
    return digest({"cues": [n.model_dump() for n in p.audio.narration], "voice": p.audio.voice})


def required_frames_ready(p: Project):
    for shot in p.shots:
        if shot.source_video_id:
            continue
        if not shot.anchors:
            raise StudioError(f"{shot.title} 需要至少一个候选图位置")
        for anchor in shot.anchors:
            if anchor.required and (not selected_candidate(anchor) or anchor.approved_hash != anchor_hash(p, shot, anchor)):
                raise StudioError(f"{shot.title} 还有未选定、未确认或已变化的关键帧", "frames_unconfirmed", 409)


def invalidate(p: Project):
    p.creative_approved_hash = None
    p.route.approved_hash = None
    p.final_approved_hash = None
    if p.stage not in {"idea", "create"}:
        p.stage = "create"


class StudioService:
    def __init__(self, db: Database):
        self.db, self.assets = db, Assets(db)

    def create_project(self, name: str, category: str = "commerce", region: str = "cn") -> Project:
        p = Project(name=name, category=category, region=region, workbench_version=2)
        with self.db.transaction() as c:
            self.db.save_project(p, c)
            self.db.event(c, p.id, "project_created", {"name": name})
        return p

    def command(self, project_id: str, command: Command) -> dict:
        with self.db.transaction() as c:
            request_hash = digest(command.model_dump(exclude={"idempotency_key"}))
            previous = c.execute("SELECT * FROM commands WHERE project_id=? AND key=?", (project_id, command.idempotency_key)).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    raise StudioError("重复请求键对应的操作已改变", "idempotency_conflict", 409)
                return json.loads(previous["response"])
            p = self.db.get_project(project_id, c)
            if p.revision != command.expected_revision:
                raise StudioError("作品已经更新，请先刷新再确认修改", "revision_conflict", 409)
            data, kind = command.payload, command.type
            settings = self.db.settings(c)
            result: dict[str, Any] = {}
            job = None

            from . import editing
            if kind == 'run_skill':
                from .skills import resolve_skill
                skill = resolve_skill(data['skill_id'], data.get('action'))
                data = {**data, 'skill_version': skill['version']}
                kind = skill['command']
                command = command.model_copy(update={'type':kind,'payload':data})
                result['skill_id']=skill['id']
            if kind in editing.COMMANDS:
                result.update(editing.execute(self.db,c,p,kind,data))
            elif kind == "update_brief":
                for field in ["name", "brief", "audience", "target_duration", "aspect", "region", "category"]:
                    if field in data:
                        setattr(p, field, data[field])
                p.proposal_approved_hash = None
                invalidate(p); p.stage = "idea"
            elif kind == "update_proposal":
                p.proposal = str(data["text"])
                p.proposal_approved_hash = None; invalidate(p)
            elif kind == "approve_proposal":
                if not p.proposal.strip():
                    raise StudioError("先完成导演提案")
                p.proposal_approved_hash = digest(p.proposal); p.stage = "create"
            elif kind == "add_block":
                p.blocks.append(ScriptBlock(title=data.get("title", "新段落"), text=data.get("text", "")))
                invalidate(p); p.stage = "create"
            elif kind == "update_block":
                block = next((b for b in p.blocks if b.id == data["block_id"]), None)
                if not block:
                    raise StudioError("脚本段落不存在")
                for field in ["title", "text", "purpose"]:
                    if field in data:
                        setattr(block, field, str(data[field]))
                invalidate(p)
            elif kind == "remove_block":
                block_id = data["block_id"]
                removed = {s.id for s in p.shots if s.block_id == block_id}
                p.blocks = [b for b in p.blocks if b.id != block_id]
                p.shots = [s for s in p.shots if s.id not in removed]
                for cue in p.audio.narration+p.audio.subtitles:
                    cue.shot_ids = [s for s in cue.shot_ids if s not in removed]
                invalidate(p)
            elif kind == "add_shot":
                if data["block_id"] not in {b.id for b in p.blocks}:
                    raise StudioError("先创建脚本段落")
                count = int(data.get("count", 1))
                if count < 1 or count > 10:
                    raise StudioError("每次增加 1–10 个镜头，可继续添加")
                for _ in range(count):
                    p.shots.append(Shot(block_id=data["block_id"], title="新镜头", duration=float(data.get("duration", 5))))
                invalidate(p)
            elif kind == "update_shot":
                shot = shot_for(p, data["shot_id"])
                if 'requirements' in data:
                    from .models import ShotRequirements
                    shot.requirements=ShotRequirements.model_validate(data['requirements'])
                for field in ["title", "visual", "motion", "duration", "difficulty", "continuity_group", "block_id"]:
                    if field in data:
                        setattr(shot, field, data[field])
                if "source_video_id" in data:
                    asset_id = data["source_video_id"]
                    if asset_id:
                        asset = self.db.asset(asset_id, c)
                        if not asset["mime"].startswith(("video/", "audio/")) or asset_id not in p.asset_ids:
                            raise StudioError("先把原始视频加入当前项目")
                    shot.source_video_id = asset_id
                    shot.source_range_id = None
                invalidate(p)
            elif kind == "remove_shot":
                shot_id = data["shot_id"]
                p.shots = [s for s in p.shots if s.id != shot_id]
                for cue in p.audio.narration+p.audio.subtitles:
                    cue.shot_ids = [s for s in cue.shot_ids if s != shot_id]
                invalidate(p)
            elif kind == "reorder_shots":
                ids = data["shot_ids"]
                if len(ids) != len(set(ids)) or set(ids) != {s.id for s in p.shots}:
                    raise StudioError("排序需要包含每个镜头且不重复")
                p.shots = [shot_for(p, i) for i in ids]; invalidate(p)
            elif kind == "add_anchor":
                shot = shot_for(p, data["shot_id"])
                if len(shot.anchors) >= 12:
                    raise StudioError("一个镜头最多 12 个设计位置，复杂剪辑建议拆镜头")
                shot.anchors.append(Anchor(role=data.get("role", "action"), at_seconds=data.get("at_seconds", shot.duration/2), prompt=data.get("prompt", shot.visual)))
                invalidate(p)
            elif kind == "update_anchor":
                _, anchor = anchor_for(p, data["anchor_id"])
                for field in ["role", "at_seconds", "prompt", "required", "control_required", "reference_asset_ids"]:
                    if field in data:
                        setattr(anchor, field, data[field])
                if not set(anchor.reference_asset_ids) <= set(p.asset_ids):
                    raise StudioError("参考图必须来自当前项目的素材")
                invalidate(p)
            elif kind == "remove_anchor":
                shot, anchor = anchor_for(p, data["anchor_id"])
                shot.anchors = [a for a in shot.anchors if a.id != anchor.id]; invalidate(p)
            elif kind == "attach_asset":
                self.db.asset(data["asset_id"], c)
                if data["asset_id"] not in p.asset_ids:
                    p.asset_ids.append(data["asset_id"])
            elif kind=='crop_candidate':
                shot,anchor=anchor_for(p,data['anchor_id']);source=data['asset_id']
                if source not in p.asset_ids:raise StudioError('只能裁剪当前项目的素材')
                asset=self.assets.crop(source,data['crop'],connection=c)
                if asset['id'] not in p.asset_ids:p.asset_ids.append(asset['id'])
                candidate=Candidate(asset_id=asset['id'],asset_hash=asset['hash'],prompt=anchor.prompt,prompt_hash=anchor_hash(p,shot,anchor),model_id='local_crop',model_name='原图局部 · 本地处理')
                anchor.candidates.append(candidate);result['candidate_id']=candidate.id;result['asset_id']=asset['id']
            elif kind == "candidate_from_asset":
                shot, anchor = anchor_for(p, data["anchor_id"])
                asset_id = data["asset_id"]
                asset = self.db.asset(asset_id, c)
                if asset_id not in p.asset_ids or not asset["mime"].startswith("image/"):
                    raise StudioError("先把图片加入当前项目")
                candidate = Candidate(asset_id=asset_id,asset_hash=asset['hash'], prompt=anchor.prompt, prompt_hash=anchor_hash(p, shot, anchor))
                anchor.candidates.append(candidate)
                result["candidate_id"] = candidate.id
            elif kind == "select_candidate":
                _, anchor = anchor_for(p, data["anchor_id"])
                if data["candidate_id"] not in {i.id for i in anchor.candidates}:
                    raise StudioError("候选图片不存在")
                anchor.selected_id = data["candidate_id"]; anchor.approved_hash = None; invalidate(p)
            elif kind == "approve_anchor":
                shot, anchor = anchor_for(p, data["anchor_id"])
                selected = selected_candidate(anchor)
                if not selected:
                    raise StudioError("先选择采用图")
                current = anchor_hash(p, shot, anchor)
                if selected.prompt_hash != current and not data.get("accept_existing"):
                    raise StudioError("图片对应的画面需求已变化，请明确选择沿用或重新生成", "candidate_stale", 409)
                anchor.approved_hash = current; invalidate(p)
            elif kind == "update_style":
                p.global_style = str(data["text"]); invalidate(p)
            elif kind == "update_audio":
                before_narration=[x.model_dump() for x in p.audio.narration]
                previous_creative=p.creative_approved_hash==creative_hash(p)
                previous_route=previous_creative and p.route.approved_hash==route_hash(p)
                for field in ["voice", "music_prompt", "music_gain", "mute_native_audio", "allow_silent", "duck_music"]:
                    if field in data:
                        setattr(p.audio, field, data[field])
                for field in ["narration", "subtitles"]:
                    if field in data:
                        setattr(p.audio, field, [AudioCue.model_validate(x) for x in data[field]])
                if 'effects' in data:
                    effects=[SoundEffect.model_validate(e) for e in data['effects']]
                    for effect in effects:
                        if effect.asset_id not in p.asset_ids or not self.db.asset(effect.asset_id,c)['mime'].startswith('audio/'):raise StudioError('音效必须来自当前项目的音频素材')
                        if effect.start+effect.duration>sum(s.duration for s in p.shots)+.1:raise StudioError('音效时间超出成片长度')
                    p.audio.effects=effects
                for field in ["music_asset_id", "narration_asset_id"]:
                    if field in data:
                        asset_id = data[field]
                        if asset_id and (asset_id not in p.asset_ids or not self.db.asset(asset_id, c)["mime"].startswith("audio/")):
                            raise StudioError("先将所需音频加入当前项目")
                        setattr(p.audio, field, asset_id)
                        if field == "narration_asset_id":
                            p.audio.narration_hash = narration_hash(p) if asset_id else None
                if "narration" in data and before_narration!=[x.model_dump() for x in p.audio.narration]:
                    if data.get('confirm_visuals_unchanged') and previous_creative:
                        p.creative_approved_hash=creative_hash(p)
                        p.route.creative_hash=p.creative_approved_hash
                        if previous_route:p.route.approved_hash=route_hash(p)
                        self.db.event(c,p.id,'narration_change_confirmed',{'scope':'用户确认画面含义不变，保留视频，更新声音与字幕'})
                    else:
                        p.creative_approved_hash=None;p.route.approved_hash=None
                p.final_approved_hash = None
            elif kind == "approve_creative":
                if not p.blocks or not p.shots or any(not b.text.strip() for b in p.blocks) or any(not s.visual.strip() for s in p.shots):
                    raise StudioError("完整脚本与镜头画面要求还没有填写完")
                if abs(sum(s.duration for s in p.shots)-p.target_duration) > 0.1:
                    raise StudioError("镜头总时长与目标时长不一致，请调整后确认", "duration_mismatch", 409)
                required_frames_ready(p)
                p.creative_approved_hash = creative_hash(p); p.stage = "route"
            elif kind == "suggest_route":
                if p.creative_approved_hash != creative_hash(p):
                    raise StudioError("先确认当前脚本与画面创作包", "creative_unapproved", 409)
                budget=budget_snapshot(c,p.id)
                remaining=budget['total_limit']-budget['media']['spent']-budget['media']['reserved']
                p.route, result["warnings"] = suggest_route(p, settings, data.get("mode", "balanced"), data.get("resolution", "720"), remaining=remaining)
            elif kind == "update_route":
                route = RoutePlan.model_validate(data["route"])
                if {i.shot_id for i in route.items} != {s.id for s in p.shots} or len(route.items) != len(p.shots):
                    raise StudioError("制作方案必须覆盖当前镜头且不重复")
                for item in route.items:
                    shot = shot_for(p, item.shot_id)
                    if item.method == "generate":
                        m, conn = get_model(settings, item.model_id, "video")
                        validate_video_route(shot, item, m)
                        item.estimated_micros = estimate(m, duration=item.native_duration,resolution=item.resolution,aspect=p.aspect)
                        item.deployment_hash = deployment_hash(m, conn)
                        item.generation_hash = generation_hash(m,conn)
                    else:
                        if item.method=='local' and not local_compatible(shot):raise StudioError('这个镜头承诺了动作或多个画面状态，不能静默改成单张静态图；请先调整内容或使用视频路线')
                        if item.method=='reuse' and not shot.source_video_id:raise StudioError('请先给镜头选择已有视频')
                        item.estimated_micros = 0; item.model_id = ""; item.deployment_hash = ""
                route.creative_hash = creative_hash(p); route.approved_hash = None
                p.route = route; p.final_approved_hash = None
            elif kind == "approve_route":
                self._require_creative(p)
                if len(p.route.items) != len(p.shots) or {i.shot_id for i in p.route.items} != {s.id for s in p.shots}:
                    raise StudioError("先为每个镜头选择制作路线")
                if p.route.creative_hash != creative_hash(p):
                    raise StudioError("创作包已变化，请重新计算制作方案", "route_stale", 409)
                for item in p.route.items:
                    if item.method == "generate":
                        m, conn = get_model(settings, item.model_id, "video")
                        validate_video_route(shot_for(p,item.shot_id),item,m)
                        if item.deployment_hash != deployment_hash(m, conn):
                            raise StudioError("模型配置或价格已变化，请重新计算路线", "route_stale", 409)
                p.route.approved_hash = route_hash(p); p.route.approved_at = time.time(); p.stage = "video"
            elif kind == "set_budget":
                if not data.get("explicit_authorization"):
                    raise StudioError("需要明确的预算授权")
                before = budget_snapshot(c, p.id)
                values = {name: int(data.get(name, before[name])) for name in ["demo_limit", "total_limit", "cognitive_limit", "include_demo"]}
                if any(values[n] < 0 or values[n] > 1_000_000_000_000 for n in ["demo_limit", "total_limit", "cognitive_limit"]):
                    raise StudioError("预算金额无效")
                c.execute("UPDATE budgets SET demo_limit=?,total_limit=?,cognitive_limit=?,include_demo=? WHERE project_id=?", (*[values[n] for n in ["demo_limit", "total_limit", "cognitive_limit", "include_demo"]], p.id))
                after = budget_snapshot(c, p.id)
                for pool, limit in [("demo", "demo_limit"), ("media", "total_limit"), ("cognitive", "cognitive_limit")]:
                    if after[pool]["spent"]+after[pool]["reserved"] > after[limit]:
                        raise StudioError("新上限不能低于已发生和在途金额")
                c.execute("UPDATE budgets SET paused=0 WHERE project_id=?",(p.id,))
            elif kind == "set_stage":
                target = data["stage"]
                if p.workbench_version < 2 and target in {"route", "video", "audio", "review"}:
                    self._require_creative(p)
                if p.workbench_version < 2 and target in {"video", "audio", "review"}:
                    self._require_route(p)
                p.stage = target
            elif kind == "add_review_issue":
                p.review_issues.append(ReviewIssue.model_validate(data)); p.final_approved_hash = None
            elif kind == "resolve_review_issue":
                issue = next((x for x in p.review_issues if x.id == data["issue_id"]), None)
                if not issue:
                    raise StudioError("审片问题不存在")
                if data.get("status") not in {"resolved", "accepted", "open"}:
                    raise StudioError("问题状态无效")
                issue.status = data["status"]; issue.resolution_note = str(data.get("note", ""))
                p.final_approved_hash = None
            elif kind == "approve_final":
                if not p.preview_asset_id or p.render_hash != render_hash(p):
                    raise StudioError("先合成当前版本的完整声画预览")
                if any(i.status == "open" and i.severity != "note" for i in p.review_issues):
                    raise StudioError("还有未处理的审片问题")
                p.final_approved_hash = p.render_hash
            elif kind == "accept_existing_clip":
                self._require_route(p)
                if not data.get('explicit_confirmation'):raise StudioError('需要明确验看并确认沿用现有视频')
                shot=shot_for(p,data['shot_id'])
                if not shot.clip_asset_id:raise StudioError('没有现有视频可沿用')
                item=next(i for i in p.route.items if i.shot_id==shot.id)
                asset=self.db.asset(shot.clip_asset_id,c)
                from .media import dimensions
                width,height=dimensions(item.resolution,p.aspect)
                if asset['metadata'].get('duration',0)+.1<shot.duration or (asset['metadata'].get('width'),asset['metadata'].get('height'))!=(width,height):
                    raise StudioError('原视频与当前时长或输出规格不匹配，不能直接沿用')
                shot.clip_input_hash=clip_hash(p,shot.id,item);p.final_approved_hash=None
            elif kind == 'recover_script':
                job=self.db.job(data['job_id'],c)
                if job['project_id']!=p.id or job['kind']!='plan_content' or job['state']!='failed':raise StudioError('没有可恢复的失败规划任务')
                if p.blocks and not data.get('replace_existing'):raise StudioError('恢复将替换现有脚本，请明确确认')
                original=Project.model_validate(job['payload']['project'])
                if original.brief!=p.brief or original.proposal!=p.proposal:raise StudioError('需求或提案已改变，请先比较旧草稿')
                from .cognition import saved_script
                p.blocks=[ScriptBlock.model_validate(b) for b in saved_script(self.db,job)]
                p.shots=[];p.audio.narration=[];p.audio.subtitles=[]
                invalidate(p);p.stage='create'
            elif kind == "adopt_plan":
                job = self.db.job(data["job_id"],c)
                if job["project_id"] != p.id or job["kind"] != "plan_content" or job["state"] != "succeeded":
                    raise StudioError("没有可采用的脚本分镜方案")
                old = Project.model_validate(job["payload"]["project"])
                if old.brief != p.brief or old.proposal != p.proposal:
                    raise StudioError("需求或提案已改变，请重新生成方案", "plan_stale", 409)
                if p.blocks and not data.get("replace_existing"):
                    raise StudioError("采用新方案会替换当前脚本和分镜，需要明确确认", "replace_confirmation", 409)
                p.blocks = [ScriptBlock.model_validate(x) for x in job["result"]["blocks"]]
                p.shots = [Shot.model_validate(x) for x in job["result"]["shots"]]
                p.audio.narration = [AudioCue.model_validate(x) for x in job["result"]["narration"]]
                p.audio.subtitles = [AudioCue.model_validate(x) for x in job["result"]["subtitles"]]
                invalidate(p);p.stage="create"
            elif kind == "apply_suggestion":
                job = self.db.job(data["job_id"],c)
                if job["project_id"] != p.id or job["state"] != "succeeded":
                    raise StudioError("建议不存在或尚未完成")
                if job["kind"] == "refine_shot":
                    shot = shot_for(p,job["target_id"])
                    old = shot_for(Project.model_validate(job["payload"]["project"]),shot.id)
                    if shot.visual != old.visual or shot.motion != old.motion or [(a.id,a.prompt) for a in shot.anchors] != [(a.id,a.prompt) for a in old.anchors]:
                        raise StudioError("镜头已经被修改，请重新比较后再采用建议", "suggestion_stale", 409)
                    shot.visual=job["result"]["visual"];shot.motion=job["result"]["motion"]
                    for item in job["result"]["prompts"]:
                        target=next((a for a in shot.anchors if a.id==item.get("anchor_id")),None)
                        if target:target.prompt=item["prompt"]
                elif job["kind"] == "director":
                    index=int(data["index"])
                    changes=job["result"].get("changes",[])
                    if index<0 or index>=len(changes):raise StudioError("建议索引无效")
                    change=changes[index];field=change["field"]
                    original=Project.model_validate(job["payload"]["project"])
                    if change["target_kind"]=="block" and field in {"text","title"}:
                        target=next((b for b in p.blocks if b.id==change["target_id"]),None)
                        old=next((b for b in original.blocks if b.id==change["target_id"]),None)
                    elif change["target_kind"]=="shot" and field in {"title","visual","motion"}:
                        target=shot_for(p,change["target_id"]);old=shot_for(original,change["target_id"])
                    elif change["target_kind"]=="anchor" and field=="prompt":
                        _,target=anchor_for(p,change["target_id"]);_,old=anchor_for(original,change["target_id"])
                    else:raise StudioError("该建议包含未授权字段")
                    if target is None or old is None or getattr(target,field)!=getattr(old,field):raise StudioError("目标已有编辑，请重新比较", "suggestion_stale",409)
                    setattr(target,field,change["value"])
                else:raise StudioError("这个任务没有可采用的编辑建议")
                invalidate(p)
            elif kind in {"director", "plan_content", "refine_shot", "refine_transcript", "transcribe", "generate_image", "generate_shot", "generate_tts", "generate_music", "render", "ai_review"}:
                job = self._create_job(c, p, settings, command, request_hash)
                result["job_id"] = job["id"]
                if kind=="director":
                    p.messages.append({"id":uid(),"role":"user","text":data.get("message",p.brief),"job_id":job["id"]})
            else:
                raise StudioError("不支持这个操作", "unknown_command")

            editing.expire_proposals(p)
            # Validate mutations before committing, including reference integrity.
            p = Project.model_validate(p.model_dump())
            self.db.save_project(p, c, expected=command.expected_revision)
            self.db.event(c, p.id, kind, {"revision": p.revision, "target": data.get("shot_id", data.get("anchor_id")), **result})
            response = {"project": p.model_dump(mode="json"), **result}
            c.execute("INSERT INTO commands VALUES(?,?,?,?)", (p.id, command.idempotency_key, request_hash, dumps(response)))
            return response

    def _require_creative(self, p: Project):
        if p.creative_approved_hash != creative_hash(p):
            raise StudioError("当前创作包未确认或已变化", "creative_unapproved", 409)

    def _require_route(self, p: Project):
        self._require_creative(p)
        if p.route.approved_hash != route_hash(p):
            raise StudioError("当前制作路线未确认或已变化", "route_unapproved", 409)

    def _create_job(self, c, p, settings, command, request_hash):
        data, kind = command.payload, command.type
        payload: dict = {"project": p.model_dump(mode="json"), "request": data}
        category, phase, target, amount = "media", "formal", None, 0
        source_hash = ""
        model_ids = []
        if kind == 'transcribe':
            from .transcription import readiness
            from .editing import validate_range
            from .models import SourceRange
            target=data['asset_id'];asset=self.db.asset(target,c)
            validate_range(self.db,c,p,SourceRange(asset_id=target,start=0,end=asset['metadata'].get('duration',0)))
            if not readiness()['ready']:raise StudioError(readiness()['note'],'asr_unavailable',409)
            source_hash=digest({'asset':asset['hash'],'language':data.get('language','auto'),'engine':'whisper-large-v3-turbo'})
        elif kind in {"director", "plan_content", "refine_shot", "refine_transcript", "ai_review"}:
            category = "cognitive"
            role = "director" if kind == "director" else "writer" if kind in {"plan_content", "refine_transcript"} else "shot_designer" if kind == "refine_shot" else "reviewer"
            if kind=='plan_content' and data.get('reuse_script'):
                if not p.blocks:raise StudioError('先恢复或保存完整脚本，再只重做分镜')
                role='shot_designer'
            if kind=='director' and any(word in data.get('message','') for word in ['系统怎么用','这一步怎么操作','费用明细','剩余预算','模型配置说明']):role='executor'
            has_visual=any(self.db.asset(i,c)['mime'].startswith(('image/','video/')) for i in p.asset_ids)
            needs_vision=kind=='ai_review' or (role!='executor' and has_visual and (kind in {'director','refine_shot'} or (kind=='plan_content' and data.get('reuse_script'))))
            if role=='executor':payload['skip_visual']=True
            model_id = choose_cognitive_model(settings,p,role,vision=needs_vision,explicit=data.get('model_id'))
            model_ids = [model_id]
            if kind == "plan_content":
                if p.proposal_approved_hash != digest(p.proposal):
                    raise StudioError("先确认导演提案，再展开完整脚本")
                if not data.get('reuse_script'):model_ids.append(choose_cognitive_model(settings,p,'shot_designer',vision=has_visual))
            if kind == "ai_review" and not p.preview_asset_id:
                raise StudioError("先生成完整预览再做 AI 审片")
            if kind == "refine_shot":
                target = data["shot_id"]; shot_for(p, target)
            if kind == 'refine_transcript':
                from .editing import transcript_for, transcript_signature
                target=data['transcript_id'];source_hash=transcript_signature(transcript_for(p,target))
            else:
                source_hash = digest({"brief": p.brief, "proposal": p.proposal, "blocks": [b.model_dump() for b in p.blocks], "shot": shot_for(p, target).model_dump() if target else None, "render": p.render_hash})
            source_hash=digest({'input':source_hash,'instruction':data.get('instruction',''),'message':data.get('message',''),'selection':{k:data.get(k) for k in ('shot_id','anchor_id','transcript_id')},'skill':data.get('skill_id'),'skill_version':data.get('skill_version')})
        elif kind == "generate_image":
            shot, anchor = anchor_for(p, data["anchor_id"]); target = anchor.id
            if not anchor.prompt.strip() or not shot.visual.strip():
                raise StudioError("先写好镜头画面要求和本帧图片提示词")
            model_ids = [data.get("model_id") or settings.defaults.image]
            source_hash = anchor_hash(p, shot, anchor); phase = "demo"
            payload["prompt"] = p.global_style+"\n镜头要求："+shot.visual+"\n本帧："+anchor.prompt
            payload["reference_asset_ids"] = anchor.reference_asset_ids
            m, _ = get_model(settings, model_ids[0], "image")
            if anchor.reference_asset_ids and not m.image_edit:
                raise StudioError("当前图像模型未声明图生图 / 编辑能力")
            if len(anchor.reference_asset_ids) > m.max_reference_images:
                raise StudioError("参考图数量超过当前模型支持范围")
        elif kind == "generate_shot":
            self._require_route(p); target = data["shot_id"]
            shot = shot_for(p, target)
            item = next(i for i in p.route.items if i.shot_id == target)
            if item.method=='reuse' and shot.requirements.audio=='native_dialogue':
                if not shot.source_video_id or not self.db.asset(shot.source_video_id,c)['metadata'].get('has_audio'):
                    raise StudioError('原片没有音轨，不能满足原生对白要求','capability_mismatch',409)
            payload["route_item"] = item.model_dump(mode="json")
            source_hash = clip_hash(p, target, item)
            if shot.clip_asset_id and shot.clip_input_hash == source_hash and not data.get("regenerate"):
                raise StudioError("已有相同输入的可用视频，可以直接复用", "already_available", 409)
            if item.method == "generate":
                m, conn = get_model(settings, item.model_id, "video")
                validate_video_route(shot,item,m)
                if item.deployment_hash != deployment_hash(m, conn):
                    raise StudioError("模型参数或价格已经改变，请重新确认制作路线", "route_stale", 409)
                model_ids = [item.model_id]; amount = estimate(m, duration=item.native_duration,resolution=item.resolution,aspect=p.aspect)
        elif kind == "generate_tts":
            self._require_route(p)
            text = "\n".join(n.text for n in p.audio.narration).strip()
            if not text:
                raise StudioError("先准备旁白内容，或上传自己的录音")
            model_ids = [data.get("model_id") or settings.defaults.tts]
            payload["text"] = text; source_hash = narration_hash(p)
        elif kind == "generate_music":
            self._require_route(p)
            model_ids = [data.get("model_id") or settings.defaults.music]
            source_hash = digest(p.audio.music_prompt)
        elif kind == "render":
            self._require_route(p)
            if not p.shots:
                raise StudioError("没有可合成的镜头")
            for shot in p.shots:
                item = next(i for i in p.route.items if i.shot_id == shot.id)
                if not shot.clip_asset_id or shot.clip_input_hash != clip_hash(p, shot.id, item):
                    raise StudioError(f"{shot.title} 的当前视频还未完成", "clip_missing", 409)
            if p.audio.narration and (not p.audio.narration_asset_id or p.audio.narration_hash != narration_hash(p)):
                raise StudioError("旁白还没有生成 / 上传，或与当前台词不匹配", "narration_missing", 409)
            if p.audio.mute_native_audio and any(s.requirements.audio=='native_dialogue' for s in p.shots):
                raise StudioError('镜头要求原生对白，合成时必须保留原片声音','capability_mismatch',409)
            native=not p.audio.mute_native_audio and any(s.source_video_id and self.db.asset(s.source_video_id,c)['metadata'].get('has_audio') for s in p.shots)
            if not p.audio.allow_silent and not (p.audio.narration_asset_id or p.audio.music_asset_id or p.audio.effects or native):
                raise StudioError("请配置声音或明确选择无声作品")
            source_hash = render_hash(p)
        models = []
        for model_id in model_ids:
            m, conn = get_model(settings, model_id)
            if kind == "ai_review" and not m.vision:
                raise StudioError("审片模型必须具备视觉输入能力")
            if category == "cognitive" and m.kind != "text":
                raise StudioError("认知任务必须选择文本 / 多模态理解模型")
            expected_kind = {"generate_image": "image", "generate_tts": "tts", "generate_music": "music"}.get(kind)
            if expected_kind and m.kind != expected_kind:
                raise StudioError("模型类型不匹配")
            if kind != "generate_shot":
                if kind == "generate_tts":
                    amount += sum(estimate(m, characters=len(cue.text),duration=cue.duration) for cue in p.audio.narration if cue.text.strip())
                else:
                    amount += estimate(m, duration=p.target_duration, characters=len(payload.get("text", "")),references=len(payload.get("reference_asset_ids",[])))
            models.append({"model": m.model_dump(mode="json"), "connection": conn.model_dump(mode="json"),"approval_hash":deployment_hash(m,conn)})
        payload["models"] = models
        existing = c.execute("SELECT id FROM jobs WHERE project_id=? AND kind=? AND COALESCE(target_id,'')=COALESCE(?,'') AND input_hash=? AND state IN ('queued','submitting','submitted','running','downloading','unknown','cancel_requested')", (p.id, kind, target, source_hash)).fetchone()
        if existing:
            raise StudioError("相同内容已有在途或结果不明的任务，请先处理原任务", "task_inflight", 409)
        return reserve_job(c, self.db, p, key=command.idempotency_key, request_hash=request_hash, kind=kind, target_id=target,
                           input_hash=source_hash, payload=payload, amount=amount, category=category, phase=phase)

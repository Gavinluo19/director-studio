from __future__ import annotations

import json
import asyncio
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from .adapters import Adapters
from .models import Anchor, AudioCue, Connection, Contract, ModelProfile, Project, ScriptBlock, Shot, StudioError


class ChangeSuggestion(Contract):
    target_kind: Literal["block", "shot", "anchor"]
    target_id: str
    field: Literal["text", "title", "visual", "motion", "prompt"]
    value: str
    reason: str


class ActionSuggestion(Contract):
    kind: Literal['plan_content','refine_shot','generate_image','suggest_route','render','ai_review']
    target_id: str
    instruction: str
    reason: str


class DirectorReply(Contract):
    message: str
    proposal: str
    question: str
    changes: list[ChangeSuggestion]
    actions: list[ActionSuggestion] = Field(default_factory=list)


class BlockDesign(Contract):
    title: str
    text: str
    purpose: str


class ScriptDraft(Contract):
    blocks: list[BlockDesign] = Field(min_length=1, max_length=30)


class AnchorDesign(Contract):
    role: Literal['start','action','end','reference']
    at_seconds: float = Field(description="相对本镜头的秒数。起始必须填0；结束填本镜头duration；禁止填全片时间。")
    prompt: str
    reference_asset_ids: list[str]


class ShotDesign(Contract):
    block_index: int = Field(ge=0)
    title: str
    duration: float
    visual: str
    motion: str
    difficulty: Literal['static','simple','complex']
    anchors: list[AnchorDesign]


class CueDesign(Contract):
    text: str
    start: float
    duration: float


class ShotDraft(Contract):
    shots: list[ShotDesign] = Field(min_length=1, max_length=100)
    narration: list[CueDesign]
    subtitles: list[CueDesign]


class ReviewFinding(Contract):
    start: float
    end: float
    category: str
    severity: Literal["blocker", "warning", "note"]
    description: str


class ReviewReply(Contract):
    summary: str
    issues: list[ReviewFinding]
    coverage_limit: str


class RefinedPrompt(Contract):
    anchor_id: str
    prompt: str


class RefinedShot(Contract):
    visual: str
    motion: str
    prompts: list[RefinedPrompt]
    explanation: str


class CreativeState(TypedDict, total=False):
    project: dict
    script: dict
    design: dict
    usage: list[dict]


class Cognition:
    def __init__(self, adapters: Adapters):
        self.adapters = adapters

    def compact_context(self, p: Project, selection: dict | None=None) -> dict:
        selection=selection or {}
        selected=[s for s in p.shots if s.id==selection.get('shot_id') or any(a.id==selection.get('anchor_id') for a in s.anchors)]
        detailed=selected or p.shots
        return {"name": p.name, "brief": p.brief, "audience": p.audience, "target_duration": p.target_duration,
                "project_context":p.context_notes,
                "requirements":[{"shot_id":s.id,**s.requirements.model_dump()} for s in detailed],
                "aspect": p.aspect, "style": p.global_style, "proposal": p.proposal,
                "blocks": [b.model_dump() for b in p.blocks],
                "shots": [{"id": s.id, "block_id": s.block_id, "visual": s.visual, "motion": s.motion,
                           "duration": s.duration, "anchors": [{"id": a.id, "prompt": a.prompt, "role": a.role} for a in s.anchors]} for s in detailed],
                "shot_index":[{"id":s.id,"title":s.title,"purpose":s.visual[:100]} for s in p.shots] if selected else [],
                "transcripts":[{"id":t.id,"segments":[s.model_dump() for s in t.segments]} for t in p.transcripts if t.id==selection.get('transcript_id')],
                "selected_scope":selection,"recent_messages": p.messages[-8:]}

    async def refine_transcript(self, p, transcript_id, instruction, model, connection):
        from .editing import transcript_for
        from .skills import instructions
        class CutReply(Contract):
            keep_ids: list[str]
            explanation: str
        t=transcript_for(p,transcript_id)
        prompt=instructions('ip-rough-cut')+'\n项目要求：'+p.context_notes+'\n本次要求：'+instruction+'\n原片段落：'+json.dumps([s.model_dump() for s in t.segments],ensure_ascii=False)
        r=await self.adapters.text(model,connection,prompt,CutReply.model_json_schema(),work=self.adapters.assets.db.root/'work'/p.id)
        out=CutReply.model_validate(r.data)
        if not out.keep_ids or len(set(out.keep_ids))!=len(out.keep_ids) or set(out.keep_ids)-{s.id for s in t.segments}:
            raise StudioError('粗剪建议没有引用有效原片段落','invalid_proposal',409)
        return out.model_dump(),[r.usage]

    def images(self, p: Project, model: ModelProfile, selection: dict | None=None) -> list[str]:
        if not model.vision:
            return []
        selection=selection or {};preferred=[]
        for shot in p.shots:
            if shot.id==selection.get('shot_id') or any(a.id==selection.get('anchor_id') for a in shot.anchors):
                for a in shot.anchors:
                    candidate=next((c for c in a.candidates if c.id==a.selected_id),None)
                    if candidate:preferred.append(candidate.asset_id)
                    preferred.extend(a.reference_asset_ids)
        images=[i for i in dict.fromkeys(preferred+p.asset_ids) if self.adapters.assets.db.asset(i)['mime'].startswith('image/')][:4]
        if not images:
            videos=[i for i in p.asset_ids if self.adapters.assets.db.asset(i)['mime'].startswith('video/')][:1]
            work=self.adapters.assets.db.root/'work'/p.id/'analysis';work.mkdir(parents=True,exist_ok=True)
            for video in videos:
                duration=self.adapters.assets.db.asset(video)['metadata'].get('duration',0)
                for fraction in [.2,.5,.8]:images.append(self.adapters.assets.frame(video,duration*fraction,work))
        return images

    async def director(self, p: Project, message: str, model: ModelProfile, connection: Connection, selection: dict | None=None, skip_visual: bool=False):
        visual_ids=[] if skip_visual else await asyncio.to_thread(self.images,p,model,selection)
        context_data=self.compact_context(p,selection)
        context_data['image_order']=[{'asset_id':i,'name':self.adapters.assets.db.asset(i)['name'],'metadata':self.adapters.assets.db.asset(i)['metadata']} for i in visual_ids]
        from .database import budget_snapshot
        with self.adapters.assets.db.connect() as c:budget=budget_snapshot(c,p.id)
        context_data['budget_cny']={'media_spent':budget['media']['spent']/1e6,'media_reserved':budget['media']['reserved']/1e6,'media_remaining':(budget['total_limit']-budget['media']['spent']-budget['media']['reserved'])/1e6,'demo_remaining':(budget['demo_limit']-budget['demo']['spent']-budget['demo']['reserved'])/1e6}
        context = json.dumps(context_data, ensure_ascii=False)
        prompt = "你是这部作品的导演。理解用户真实意图，给出有针对性的叙事与画面建议。不要把所有需求套成商品广告或固定六镜头。\n" \
                 "未知商品事实、健康主张、人物身份不能补造。每轮最多问一个关键问题。用户要求提案时，proposal 给出可编辑完整提案；其余时候为空。\n" \
                 "修改已有内容时把建议放入changes，必须引用现有ID，不直接执行。绝不代替用户批准、付费、选图或提高预算。\n" \
                 "用户请求下一步操作时，可以在actions中提出有明确目标的动作，界面会展示真实作用与费用，由用户点击后执行。未执行的动作不能说成已经完成。\n" \
                 "上下文："+context+"\n用户本次消息："+message
        result = await self.adapters.text(model, connection, prompt, DirectorReply.model_json_schema(), images=visual_ids, work=self.adapters.assets.db.root/"work"/p.id)
        data = DirectorReply.model_validate(result.data)
        return data.model_dump(), [result.usage]

    def record_plan_call(self, job_id, stage, result):
        db=self.adapters.assets.db
        work=db.root/'work'/job_id;work.mkdir(parents=True,exist_ok=True)
        (work/(stage+'-response.json')).write_text(json.dumps({'data':result.data,'usage':result.usage},ensure_ascii=False,indent=2))
        with db.transaction() as c:
            job=db.job(job_id,c);saved=job.get('result') or {}
            saved.setdefault('drafts',{})[stage]=result.data
            saved.setdefault('usage_records',[]).append(result.usage)
            c.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(saved,ensure_ascii=False),job_id))

    async def plan(self, p: Project, models: list[tuple[ModelProfile, Connection]], job_id: str, reuse_script: bool=False):
        async def writer(state: CreativeState) -> CreativeState:
            model, conn = models[0]
            prompt = "你是编剧。根据已经确认的提案写完整脚本，按叙事段落组织。只输出创作内容，程序分配 ID。\n" \
                     "ScriptBlock 是叙事段落，不是镜头。不要把每个镜头拆成一段，不要把声音设计、字幕列表、规格和执行说明另列为脚本段落。\n" \
                     "用户明确要求两个叙事段落时，必须恰好输出两个 blocks。text写完整叙事正文与可用口播，具体机位、镜头时间和图片提示词交给镜头设计师。不要虚构素材没有支持的产品事实。\n" \
                     +json.dumps(self.compact_context(p), ensure_ascii=False)
            result = await self.adapters.text(model, conn, prompt, ScriptDraft.model_json_schema(), work=self.adapters.assets.db.root/"work"/p.id)
            self.record_plan_call(job_id,'writer',result)
            draft = ScriptDraft.model_validate(result.data)
            return {"script": {'blocks':[ScriptBlock(**b.model_dump()).model_dump(mode='json') for b in draft.blocks]}, "usage": [result.usage]}

        async def designer(state: CreativeState) -> CreativeState:
            model, conn = models[-1]
            visual_ids=await asyncio.to_thread(self.images,p,model)
            prompt = "你是镜头设计师。为完整脚本按需设计镜头，每个段落建议1到3个镜头，允许不同段落采用不同数量。镜头总时长必须等于目标时长。\n" \
                     "一个镜头可以有起始、动作、结束等多个关键帧位置，每个位置写可直接打磨的图片提示词。block_index引用下方段落的零起始序号。\n" \
                     "at_seconds 是镜头内相对时间，不是全片时间。每个镜头的start帧必须at_seconds=0，end帧必须等于该镜头duration。全片5秒开始的第二个镜头，其首帧仍为0。\n" \
                     "静态图片写某一时刻的状态，连续动作写入motion。只设计内容，不填写文件、审核状态或生成产物。\n" \
                     "旁白与字幕是独立时间轨，可以跨镜头，不要求每个镜头都有旁白。开始与时长不能超出总时长。\n" \
                     "产品准确展示适合static；环境运动可simple；手物接触、复杂连续性为complex。只用当前已有素材ID作为参考。\n" \
                     +json.dumps({"approved_proposal":p.proposal,"brief":p.brief,"blocks": [{**{k:v for k,v in b.items() if k!='id'},'index':i} for i,b in enumerate(state['script']['blocks'])], "target_duration": p.target_duration, "aspect": p.aspect, "style": p.global_style, "reference_asset_ids": visual_ids}, ensure_ascii=False)
            result = await self.adapters.text(model, conn, prompt, ShotDraft.model_json_schema(), images=visual_ids, work=self.adapters.assets.db.root/"work"/p.id)
            self.record_plan_call(job_id,'shot_designer',result)
            design = ShotDraft.model_validate(result.data)
            corrections=normalize_anchor_times(design)
            if any(s.block_index>=len(state['script']['blocks']) for s in design.shots):raise StudioError('镜头引用的脚本段落无效','invalid_model_output',409)
            shots=[Shot(block_id=state['script']['blocks'][s.block_index]['id'],**s.model_dump(exclude={'block_index','anchors'}),anchors=[Anchor(**a.model_dump()) for a in s.anchors]) for s in design.shots]
            for shot in shots:
                for anchor in shot.anchors:
                    anchor.candidates = []; anchor.selected_id = None; anchor.approved_hash = None
                    anchor.reference_asset_ids = [i for i in anchor.reference_asset_ids if i in p.asset_ids]
            if abs(sum(s.duration for s in design.shots)-p.target_duration) > .1:
                raise StudioError("镜头设计总时长未满足目标；请保留草稿并调整，未自动追加模型调用", "plan_duration_invalid", 409)
            starts=[];start=0
            for shot in shots:starts.append((shot.id,start,start+shot.duration));start+=shot.duration
            def cues(items):
                return [AudioCue(**cue.model_dump(),shot_ids=[sid for sid,begin,end in starts if begin<cue.start+cue.duration and end>cue.start]).model_dump(mode='json') for cue in items]
            normalized={'shots':[s.model_dump(mode='json') for s in shots],'narration':cues(design.narration),'subtitles':cues(design.subtitles),'normalization_notes':corrections}
            return {"design": normalized, "usage": state.get("usage", [])+[result.usage]}

        graph = StateGraph(CreativeState)
        graph.add_node("writer", writer); graph.add_node("shot_designer", designer)
        if reuse_script:graph.add_edge(START,'shot_designer')
        else:graph.add_edge(START,'writer');graph.add_edge('writer','shot_designer')
        graph.add_edge('shot_designer',END)
        async with AsyncSqliteSaver.from_conn_string(str(self.adapters.assets.db.root/"cognition.sqlite3")) as saver:
            workflow = graph.compile(checkpointer=saver)
            initial={"project":{"id":p.id},"usage":[]}
            if reuse_script:initial['script']={'blocks':[b.model_dump(mode='json') for b in p.blocks]}
            state = await workflow.ainvoke(initial, {"configurable": {"thread_id": job_id}, "recursion_limit": 5})
        return {"blocks": state["script"]["blocks"], **state["design"]}, state["usage"]

    async def refine_shot(self, p: Project, shot_id: str, instruction: str, model: ModelProfile, conn: Connection):
        shot = next(s for s in p.shots if s.id == shot_id)
        scoped=self.compact_context(p,{'shot_id':shot_id})
        prompt = "你是镜头设计师。打磨这个镜头，保持用户锁定的主体与叙事含义；返回建议，不生成图片。prompts每项只包含anchor_id与prompt，引用已有关键帧ID。\n"+json.dumps({"block": next(b.model_dump() for b in p.blocks if b.id == shot.block_id), "shot": scoped['shots'][0], "style": p.global_style, "instruction": instruction}, ensure_ascii=False)
        visual_ids=await asyncio.to_thread(self.images,p,model,{'shot_id':shot_id})
        r = await self.adapters.text(model, conn, prompt, RefinedShot.model_json_schema(), images=visual_ids, work=self.adapters.assets.db.root/"work"/p.id)
        return RefinedShot.model_validate(r.data).model_dump(), [r.usage]

    async def review(self, p: Project, model: ModelProfile, conn: Connection, frame_ids: list[str]):
        prompt = "你是独立审片员。对照已批准脚本与抽样画面，输出带时间段的具体问题和覆盖限制。\n" \
                 "这些是抽样帧，不可声称已检查全部运动、口型或听过未提供的音轨。不凭评分放行。\n"+json.dumps({"script": [b.model_dump() for b in p.blocks], "shots": [{"id": s.id, "visual": s.visual, "duration": s.duration} for s in p.shots], "samples": [self.adapters.assets.db.asset(i)["metadata"] for i in frame_ids]}, ensure_ascii=False)
        r = await self.adapters.text(model, conn, prompt, ReviewReply.model_json_schema(), images=frame_ids, work=self.adapters.assets.db.root/"work"/p.id)
        return ReviewReply.model_validate(r.data).model_dump(), [r.usage]


def normalize_anchor_times(design: ShotDraft):
    """Start/end coordinates are deterministic; never clamp an ambiguous action time."""
    notes=[];offset=0
    for shot in design.shots:
        for anchor in shot.anchors:
            before=anchor.at_seconds
            if anchor.role=='start':anchor.at_seconds=0
            elif anchor.role=='end':anchor.at_seconds=shot.duration
            elif anchor.at_seconds>shot.duration and offset<=anchor.at_seconds<=offset+shot.duration:
                anchor.at_seconds-=offset
            if anchor.at_seconds!=before:notes.append(f'{shot.title}：{anchor.role} 从 {before:g}s 换算为镜头内 {anchor.at_seconds:g}s')
        offset+=shot.duration
    return notes


def saved_script(db,job):
    raw=(job.get('result') or {}).get('drafts',{}).get('writer')
    if raw:return raw['blocks']
    from langgraph.checkpoint.sqlite import SqliteSaver
    with SqliteSaver.from_conn_string(str(db.root/'cognition.sqlite3')) as saver:
        record=saver.get_tuple({'configurable':{'thread_id':job['id']}})
        script=record.checkpoint.get('channel_values',{}).get('script',{}) if record else {}
        if script.get('blocks'):return script['blocks']
    raise StudioError('这个任务没有已保存的编剧草稿','draft_missing',409)

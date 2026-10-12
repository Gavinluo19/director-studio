from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return uuid4().hex


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid",allow_inf_nan=False,validate_default=True)


class Connection(Contract):
    id: str = Field(default_factory=uid)
    name: str
    base_url: str = ""
    auth: Literal["bearer", "api-key", "x-api-key", "xi-api-key", "codex", "none"] = "bearer"
    region: Literal["cn", "global"] = "cn"
    allow_local: bool = False
    status: str = "unconfigured"
    has_key: bool = False
    error: str = ""
    checked_at: float | None = None
    credential_version: int = 0


class PriceSnapshot(Contract):
    key: str
    provider: str
    model: str
    label: str
    unit: Literal['tokens','image','video_tokens','video_clip','second','1000_characters','image_tokens','tts_tokens']
    currency: Literal['CNY','USD'] = 'CNY'
    rates: dict[str, Decimal]
    long_rates: dict[str, Decimal] = Field(default_factory=dict)
    promo_rates: dict[str, Decimal] = Field(default_factory=dict)
    promo_until: str = ''
    source_url: str
    fetched_at: str
    notes: str = ''
    fx_rate: Decimal = Decimal('1')
    fx_date: str = ''
    fx_source: str = ''

    @model_validator(mode='after')
    def rates_valid(self):
        if any(not v.is_finite() or v < 0 for d in [self.rates,self.long_rates,self.promo_rates] for v in d.values()):
            raise ValueError('官方价格必须是有限非负数')
        if not self.fx_rate.is_finite() or self.fx_rate <= 0:raise ValueError('汇率必须为正数')
        return self


class ModelProfile(Contract):
    id: str = Field(default_factory=uid)
    name: str
    api_model: str
    connection_id: str
    kind: Literal["text", "image", "video", "tts", "music"]
    adapter: Literal["chat", "responses", "messages", "codex", "ark_image", "openai_image", "minimax_image", "ark_video", "runway_video", "minimax_video", "openai_tts", "minimax_tts", "eleven_music"]
    tier: Literal["primary", "economy", "quality"] = "primary"
    enabled: bool = False
    vision: bool = False
    image_edit: bool = False
    first_last: bool = False
    references: bool = False
    resolutions: list[str] = Field(default_factory=lambda: ["720", "1080"])
    durations: list[int] = Field(default_factory=list)
    min_duration: float = Field(1,ge=1,le=300)
    max_duration: float = Field(15,ge=1,le=300)
    max_reference_images: int = Field(1, ge=0, le=16)
    pricing: PriceSnapshot | None = None
    pricing_model: str = ''
    price_mode: Literal['auto','manual'] = 'auto'
    max_input_tokens: int = Field(32768,ge=1024,le=1048576)
    price_unit: Literal["call", "image", "second", "1000_characters"] = "call"
    price_cny: Decimal | None = Field(None, ge=0)
    price_currency: Literal['CNY','USD','JPY','SGD'] = 'CNY'
    price_native: Decimal | None = Field(None,ge=0)
    fx_rate: Decimal = Field(Decimal('1'),gt=0)
    fx_date: str = ''
    price_confirmed: bool = False
    price_source: str = ""
    max_output_tokens: int = Field(4096, ge=128, le=16384)
    params: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode='after')
    def adapter_contract(self):
        compatible={'text':{'chat','responses','messages','codex'},'image':{'ark_image','openai_image','minimax_image'},'video':{'ark_video','runway_video','minimax_video'},'tts':{'openai_tts','minimax_tts'},'music':{'eleven_music'}}
        if self.adapter not in compatible[self.kind]:raise ValueError('协议适配器与模型能力类型不匹配')
        if self.min_duration>self.max_duration:raise ValueError('最短时长不能超过最长时长')
        def secrets(node):
            if isinstance(node,dict):
                for key,value in node.items():
                    if any(word in key.lower() for word in ['api_key','apikey','authorization','secret','password']):raise ValueError('不要把凭据写入模型参数，请使用服务连接的 Key 输入框')
                    secrets(value)
            elif isinstance(node,list):
                for value in node:secrets(value)
        secrets(self.params)
        if self.price_currency!='CNY':
            if self.price_native is not None:self.price_cny=self.price_native*self.fx_rate
            if self.price_confirmed:
                if self.price_native is None or not self.fx_date:raise ValueError('外币报价需要原币单价、人民币换算汇率及日期')
                from datetime import date
                try:date.fromisoformat(self.fx_date)
                except ValueError:raise ValueError('汇率日期请使用 YYYY-MM-DD')
        return self


class Defaults(Contract):
    region: Literal["cn", "global"] = "cn"
    director: str = ""
    writer: str = ""
    shot_designer: str = ""
    executor: str = ""
    reviewer: str = ""
    image: str = ""
    tts: str = ""
    music: str = ""
    video: str = ""


class Settings(Contract):
    revision: int = 1
    connections: list[Connection] = Field(default_factory=list)
    models: list[ModelProfile] = Field(default_factory=list)
    defaults: Defaults = Field(default_factory=Defaults)


class ScriptBlock(Contract):
    id: str = Field(default_factory=uid)
    title: str = "新段落"
    text: str = ""
    purpose: str = ""


class Candidate(Contract):
    id: str = Field(default_factory=uid)
    asset_id: str
    asset_hash: str = ""
    prompt_hash: str
    prompt: str
    model_id: str = "uploaded"
    model_name: str = "用户素材"
    api_model: str = ""
    task_id: str = ""
    created_at: float = Field(default_factory=time.time)


class Anchor(Contract):
    id: str = Field(default_factory=uid)
    role: Literal["start", "action", "end", "reference"] = "start"
    at_seconds: float = Field(0, ge=0)
    prompt: str = ""
    required: bool = True
    control_required: bool = False
    reference_asset_ids: list[str] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    selected_id: str | None = None
    approved_hash: str | None = None


class ShotRequirements(Contract):
    product_fidelity: bool = False
    identity: bool = False
    action: str = ""
    audio: Literal["post", "native_dialogue"] = "post"
    notes: str = ""


class SourceRange(Contract):
    id: str = Field(default_factory=uid)
    asset_id: str
    start: float = Field(0, ge=0)
    end: float = Field(gt=0)
    label: str = "可用片段"
    status: Literal["pending", "usable", "rejected"] = "pending"

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end <= self.start:
            raise ValueError("片段结束必须晚于开始")
        return self


class VideoCandidate(Contract):
    id: str = Field(default_factory=uid)
    asset_id: str
    source_asset_id: str | None = None
    task_id: str = ""
    model_id: str = "local"
    input_hash: str = ""
    source_interval: dict[str, Any] | None = None
    design: dict[str, Any] = Field(default_factory=dict)
    route: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class TranscriptSegment(Contract):
    id: str = Field(default_factory=uid)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    original_text: str
    text: str
    included: bool = True

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end <= self.start:
            raise ValueError("转写段落时间无效")
        return self


class Transcript(Contract):
    id: str = Field(default_factory=uid)
    asset_id: str
    language: str = "auto"
    engine: str = "imported"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    applied_hash: str | None = None
    job_id: str = ""
    created_at: float = Field(default_factory=time.time)


class EditProposal(Contract):
    id: str = Field(default_factory=uid)
    kind: Literal["shot", "transcript"]
    target_id: str
    source_hash: str
    changes: dict[str, Any]
    summary: str
    impacts: list[str] = Field(default_factory=list)
    status: Literal["proposed", "applied", "rejected", "stale"] = "proposed"
    skill_id: str | None = None
    skill_version: str | None = None
    created_at: float = Field(default_factory=time.time)


class Shot(Contract):
    id: str = Field(default_factory=uid)
    block_id: str
    title: str = "新镜头"
    duration: float = Field(5, ge=.05, le=300)
    visual: str = ""
    motion: str = ""
    difficulty: Literal["static", "simple", "complex"] = "simple"
    continuity_group: str = ""
    anchors: list[Anchor] = Field(default_factory=lambda: [Anchor()])
    source_video_id: str | None = None
    source_generated_asset_id: str | None = None
    clip_asset_id: str | None = None
    clip_input_hash: str | None = None
    source_range_id: str | None = None
    transcript_segment_id: str | None = None
    requirements: ShotRequirements = Field(default_factory=ShotRequirements)
    video_candidates: list[VideoCandidate] = Field(default_factory=list)
    selected_video_id: str | None = None

    @model_validator(mode="after")
    def anchors_in_time(self):
        if any(a.at_seconds > self.duration for a in self.anchors):
            raise ValueError("关键帧时间不能超过镜头时长")
        if len({a.id for a in self.anchors}) != len(self.anchors):
            raise ValueError("关键帧 ID 重复")
        return self


class AudioCue(Contract):
    id: str = Field(default_factory=uid)
    text: str = ""
    start: float = Field(0, ge=0)
    duration: float = Field(5, gt=0)
    shot_ids: list[str] = Field(default_factory=list)


class SoundEffect(Contract):
    id: str = Field(default_factory=uid)
    asset_id: str
    start: float = Field(0,ge=0)
    duration: float = Field(1,gt=0)
    gain: float = Field(1,ge=0,le=3)


class AudioPlan(Contract):
    narration: list[AudioCue] = Field(default_factory=list)
    subtitles: list[AudioCue] = Field(default_factory=list)
    voice: str = "alloy"
    narration_asset_id: str | None = None
    narration_hash: str | None = None
    music_asset_id: str | None = None
    music_prompt: str = "克制、温暖的纯音乐，无人声，适合自然叙述。"
    music_gain: float = Field(0.16, ge=0, le=1)
    mute_native_audio: bool = True
    allow_silent: bool = False
    effects: list[SoundEffect] = Field(default_factory=list)
    duck_music: bool = True


class RouteItem(Contract):
    shot_id: str
    method: Literal["local", "reuse", "generate"] = "local"
    model_id: str = ""
    native_duration: float = Field(5, gt=0)
    resolution: Literal["480", "720", "1080"] = "720"
    local_motion: Literal['none','push_in'] = 'none'
    anchor_usage: dict[str, Literal["first", "last", "reference", "review"]] = Field(default_factory=dict)
    reason: str = ""
    estimated_micros: int = Field(0, ge=0)
    deployment_hash: str = ""
    generation_hash: str = ""
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    exclusions: list[dict[str, str]] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


class RoutePlan(Contract):
    mode: Literal["economy", "balanced", "quality"] = "balanced"
    resolution: Literal["480", "720", "1080"] = "720"
    items: list[RouteItem] = Field(default_factory=list)
    creative_hash: str = ""
    approved_hash: str | None = None
    approved_at: float | None = None


class ReviewIssue(Contract):
    id: str = Field(default_factory=uid)
    start: float = Field(0, ge=0)
    end: float = Field(0, ge=0)
    shot_id: str | None = None
    category: str = "creative"
    severity: Literal["blocker", "warning", "note"] = "warning"
    description: str
    evidence_asset_ids: list[str] = Field(default_factory=list)
    status: Literal["open", "resolved", "accepted"] = "open"
    source: str = "human"
    resolution_note: str = ""


class Project(Contract):
    id: str = Field(default_factory=uid)
    name: str = "新的作品"
    revision: int = 1
    category: Literal["commerce", "creator"] = "commerce"
    region: Literal["cn", "global"] = "cn"
    brief: str = ""
    audience: str = ""
    target_duration: float = Field(30, ge=.05, le=300)
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    proposal: str = ""
    proposal_approved_hash: str | None = None
    blocks: list[ScriptBlock] = Field(default_factory=list)
    shots: list[Shot] = Field(default_factory=list)
    audio: AudioPlan = Field(default_factory=AudioPlan)
    asset_ids: list[str] = Field(default_factory=list)
    global_style: str = "自然真实的画面，主体一致，光线克制，信息清晰。"
    creative_approved_hash: str | None = None
    route: RoutePlan = Field(default_factory=RoutePlan)
    stage: Literal["idea", "create", "route", "video", "audio", "review"] = "idea"
    preview_asset_id: str | None = None
    render_hash: str | None = None
    final_approved_hash: str | None = None
    review_issues: list[ReviewIssue] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    workbench_version: int = 1
    context_notes: str = ""
    source_ranges: list[SourceRange] = Field(default_factory=list)
    transcripts: list[Transcript] = Field(default_factory=list)
    edit_proposals: list[EditProposal] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_valid(self):
        blocks = {b.id for b in self.blocks}
        shots = {s.id for s in self.shots}
        if len(blocks) != len(self.blocks) or len(shots) != len(self.shots):
            raise ValueError("段落或镜头 ID 重复")
        anchors = [a.id for s in self.shots for a in s.anchors]
        if len(anchors) != len(set(anchors)):
            raise ValueError("关键帧 ID 必须在项目内唯一")
        if any(s.block_id not in blocks for s in self.shots):
            raise ValueError("镜头引用的脚本段落不存在")
        if any(not set(c.shot_ids) <= shots for c in self.audio.narration + self.audio.subtitles):
            raise ValueError("声音时间轨引用的镜头不存在")
        ranges = {r.id: r for r in self.source_ranges}
        if len(ranges) != len(self.source_ranges):
            raise ValueError("源区间 ID 重复")
        if any(s.source_range_id and s.source_range_id not in ranges for s in self.shots):
            raise ValueError("源区间不存在")
        for shot in self.shots:
            if shot.source_range_id:
                r = ranges[shot.source_range_id]
                if r.asset_id != shot.source_video_id or abs(r.end-r.start-shot.duration) > .001:
                    raise ValueError("镜头时长与源区间不一致")
            if shot.selected_video_id and shot.selected_video_id not in {v.id for v in shot.video_candidates}:
                raise ValueError("采用的视频候选不存在")
        ids = [t.id for t in self.transcripts]
        if len(ids) != len(set(ids)):
            raise ValueError("转写 ID 重复")
        for t in self.transcripts:
            if len({s.id for s in t.segments}) != len(t.segments):
                raise ValueError("转写段落 ID 重复")
        return self


class Command(Contract):
    type: str
    expected_revision: int
    idempotency_key: str = Field(default_factory=uid)
    payload: dict[str, Any] = Field(default_factory=dict)


class StudioError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def selected_candidate(anchor: Anchor) -> Candidate | None:
    return next((c for c in anchor.candidates if c.id == anchor.selected_id), None)


def anchor_hash(project: Project, shot: Shot, anchor: Anchor) -> str:
    return digest({"style": project.global_style, "visual": shot.visual, "role": anchor.role,
                   "prompt": anchor.prompt, "refs": anchor.reference_asset_ids})


def creative_hash(p: Project) -> str:
    material = {"blocks": [b.model_dump() for b in p.blocks], "style": p.global_style, "aspect": p.aspect, "target_duration": p.target_duration,
                   "shots": [{"id": s.id, "block": s.block_id, "visual": s.visual, "motion": s.motion, "duration": s.duration,
                              "anchors": [{"id": a.id, "role": a.role, "time": a.at_seconds, "prompt": a.prompt,
                                           "selected": a.selected_id, "approved": a.approved_hash} for a in s.anchors],
                              "source_video": s.source_video_id} for s in p.shots],
                   "narration": [c.model_dump() for c in p.audio.narration]}
    extra = [{"id": s.id, "range": source_interval(p,s), "requirements": s.requirements.model_dump()} for s in p.shots
             if s.source_range_id or s.requirements != ShotRequirements()]
    if extra: material["v12"] = extra
    if p.context_notes: material["context_notes"] = p.context_notes
    return digest(material)


def route_hash(p: Project) -> str:
    return digest({"creative": creative_hash(p), "mode": p.route.mode, "resolution": p.route.resolution,
                   "items": [i.model_dump(exclude={"alternatives","exclusions","checks"}) for i in p.route.items]})


def source_interval(p: Project, shot: Shot) -> dict | None:
    r = next((r for r in p.source_ranges if r.id == shot.source_range_id), None)
    return r.model_dump(include={"asset_id","start","end"}) if r else None


def render_hash(p: Project) -> str:
    material={"clips": [(s.id, s.duration, s.clip_asset_id) for s in p.shots], "audio": p.audio.model_dump(),
              "resolution": p.route.resolution, "aspect": p.aspect}
    if p.workbench_version>=2 or any(s.source_range_id for s in p.shots):
        material['content']=creative_hash(p)
        material['native_sources']=[(s.source_video_id,s.source_generated_asset_id,source_interval(p,s)) for s in p.shots]
    return digest(material)

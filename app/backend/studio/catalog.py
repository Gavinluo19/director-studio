from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from .models import Connection, ModelProfile, Project, RouteItem, RoutePlan, Settings, StudioError, creative_hash, digest, selected_candidate, source_interval, ShotRequirements


def preset_catalog() -> Settings:
    connections = [
        Connection(id="zhipu", name="智谱", base_url="https://open.bigmodel.cn/api/paas/v4"),
        Connection(id="kimi", name="Kimi", base_url="https://api.moonshot.cn/v1"),
        Connection(id="deepseek", name="DeepSeek", base_url="https://api.deepseek.com"),
        Connection(id="qwen", name="通义千问", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"),
        Connection(id="ark", name="火山方舟 · 生图与视频", base_url="https://ark.cn-beijing.volces.com/api/v3"),
        Connection(id="minimax", name="MiniMax · 视频与语音", base_url="https://api.minimaxi.com/v1"),
        Connection(id="codex", name="ChatGPT / Codex 订阅", auth="codex", region="global"),
        Connection(id="openai", name="OpenAI API", base_url="https://api.openai.com/v1", region="global"),
        Connection(id="runway", name="Runway · 视频", base_url="https://api.dev.runwayml.com/v1", region="global"),
        Connection(id="eleven", name="ElevenLabs · 音乐", base_url="https://api.elevenlabs.io/v1", auth="xi-api-key", region="global"),
    ]
    models = [
        ModelProfile(id="glm", name="GLM-5.3", api_model="glm-5.3", connection_id="zhipu", kind="text", adapter="chat", params={"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
        ModelProfile(id="k3", name="K3", api_model="kimi-k3", connection_id="kimi", kind="text", adapter="chat", vision=True, params={"reasoning_effort": "high"}),
        ModelProfile(id="glm-flash", name="GLM-5.3-Flash", api_model="glm-5.3-flash", connection_id="zhipu", kind="text", adapter="chat", tier="economy", vision=True, params={"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
        ModelProfile(id="ds-vision", name="DeepSeek-V4-Flash-Vision-Exp", api_model="deepseek-v4-flash-vision-exp", connection_id="deepseek", kind="text", adapter="chat", tier="economy", vision=True, notes="实验性视觉模型，不作为关键商品事实的唯一验收依据。"),
        ModelProfile(id="ds-flash", name="DeepSeek-V4-Flash", api_model="deepseek-v4-flash", connection_id="deepseek", kind="text", adapter="chat", tier="economy"),
        ModelProfile(id="ds-pro", name="DeepSeek-V4-Pro", api_model="deepseek-v4-pro", connection_id="deepseek", kind="text", adapter="chat"),
        ModelProfile(id="qwen-custom", name="Qwen · 填入精确型号", api_model="", connection_id="qwen", kind="text", adapter="chat", tier="economy", notes="先填写你的账户可用精确型号并测试。"),
        ModelProfile(id="seedream", name="Seedream 5.0 Pro · 高质量关键帧", api_model="", pricing_model="doubao-seedream-5-0-pro", connection_id="ark", kind="image", adapter="ark_image", tier="quality", image_edit=True, references=True, max_reference_images=4, price_unit="image", params={"size": "2K"}, notes="填写方舟已开通模型 ID 或推理接入点；确认单张价格。支持文字与多图参考生成。"),
        ModelProfile(id="gpt-image", name="GPT Image · 高质量关键帧", api_model="gpt-image-2", connection_id="openai", kind="image", adapter="openai_image", tier="quality", image_edit=True, references=True, max_reference_images=4, price_unit="call", params={"size": "1024x1536", "quality": "high"}, notes="Token 计价可能随输入图变化；这里填写本次规格的保守单次费用上限并核对账单。"),
        ModelProfile(id="seedance-standard", name="Seedance 2.0 Mini · 常规镜头", api_model="", pricing_model="doubao-seedance-2.0-mini", connection_id="ark", kind="video", adapter="ark_video", tier="economy", first_last=True, references=True, max_reference_images=2, resolutions=["480", "720"], price_unit="second", notes="填入实际模型 ID；能力和价格需按该版本核验，不能将不同 Seedance 版本混用。"),
        ModelProfile(id="seedance-quality", name="Seedance 2.0 · 复杂动作", api_model="", pricing_model="doubao-seedance-2.0", connection_id="ark", kind="video", adapter="ark_video", tier="quality", first_last=True, references=True, max_reference_images=2, price_unit="second", notes="复杂动作候选，只有真实测试通过才可启用。"),
        ModelProfile(id="runway-quality", name="Runway · Gen-4.5", api_model="gen4.5", connection_id="runway", kind="video", adapter="runway_video", tier="quality", durations=[5,10], resolutions=["720"], price_unit="second", notes="生成与计费按账户支持规格；1080 输出需明确允许后期处理，不冒充原生1080。"),
        ModelProfile(id="minimax-video", name="MiniMax 海螺 2.3 Fast", api_model="MiniMax-Hailuo-2.3-Fast", connection_id="minimax", kind="video", adapter="minimax_video", tier="economy", durations=[6,10], resolutions=["720", "1080"], price_unit="second", notes="填写账户可用 Hailuo/H3 精确型号和原生规格。"),
        ModelProfile(id="openai-tts", name="OpenAI 配音", api_model="gpt-4o-mini-tts", connection_id="openai", kind="tts", adapter="openai_tts", price_unit="call", params={"voice": "alloy"}),
        ModelProfile(id="minimax-tts", name="MiniMax Speech 2.8 HD", api_model="speech-2.8-hd", connection_id="minimax", kind="tts", adapter="minimax_tts", price_unit="1000_characters", params={"voice_id": "male-qn-qingse"}, notes="音色与精确语音型号需按账户验证。"),
        ModelProfile(id="eleven-music", name="Eleven Music · 纯音乐", api_model="music_v1", connection_id="eleven", kind="music", adapter="eleven_music", price_unit="second"),
    ]
    models.append(ModelProfile(id='minimax-image',name='MiniMax Image-01 · 概念画面',api_model='image-01',connection_id='minimax',kind='image',adapter='minimax_image',tier='quality',max_reference_images=0,image_edit=False,price_unit='image',params={'width':1152,'height':2048},notes='文生图备用路线，用于概念画面；当前条目不用于商品参考图编辑，商品精准还原优先 Seedream / GPT Image。'))
    for model, tier in [("gpt-6-astra", "primary"), ("gpt-5.6-sol", "primary"), ("gpt-5.6-terra", "economy"), ("gpt-5.6-luna", "economy"), ("gpt-5.5", "primary"), ("gpt-5.4-mini", "economy")]:
        for channel, adapter in [("codex", "codex"), ("openai", "responses")]:
            models.append(ModelProfile(id=channel+":"+model, name=model.replace("gpt-", "GPT-")+(" · 订阅" if channel == "codex" else " · API"), api_model=model, connection_id=channel, kind="text", adapter=adapter, tier=tier, vision=True, notes="实际可用性以账户与运行时返回为准。"))
    return Settings(connections=connections, models=models)


def get_model(s: Settings, model_id: str, kind: str | None = None, *, require_ready: bool = True) -> tuple[ModelProfile, Connection]:
    model = next((m for m in s.models if m.id == model_id), None)
    if model is None:
        raise StudioError("先配置并选择对应的模型", "model_missing", 409)
    connection = next((c for c in s.connections if c.id == model.connection_id), None)
    if connection is None:
        raise StudioError("模型对应的服务连接不存在", "connection_missing", 409)
    if kind and model.kind != kind:
        raise StudioError("模型能力与任务类型不匹配", "capability_mismatch", 409)
    if not model.enabled or not model.api_model:
        raise StudioError("模型尚未启用或没有精确型号", "model_unconfigured", 409)
    if require_ready and connection.status not in {"ready", "configured"}:
        raise StudioError("对应服务未配置或验证失效", "connection_unconfigured", 409)
    return model, connection


def choose_cognitive_model(settings: Settings, project: Project, role: str, *, vision: bool, explicit: str | None=None) -> str:
    preferred=explicit or getattr(settings.defaults,role) or settings.defaults.director
    if preferred:
        try:
            m,c=get_model(settings,preferred,'text')
            if not vision or m.vision:return m.id
            if explicit:raise StudioError("所选模型不能读取本次视觉素材，请选择多模态模型", "capability_mismatch",409)
        except StudioError:
            if explicit:raise
    target_tier='economy' if role=='executor' else 'primary'
    for model in settings.models:
        if model.kind!='text' or model.tier!=target_tier or (vision and not model.vision):continue
        try:
            m,c=get_model(settings,model.id,'text')
            return m.id
        except StudioError:continue
    raise StudioError("本次任务需要已配置的"+('多模态主力' if vision else '创作')+"模型，请在模型池中启用对应能力", "cognition_unconfigured",409)


def estimate(model: ModelProfile, *, duration: float = 1, characters: int = 0, count: int = 1, resolution: str = '720', aspect: str = '9:16', references: int = 0) -> int:
    if model.adapter == "codex":
        return 0
    if model.price_mode=='auto' and model.pricing:
        from .pricing import auto_estimate
        return auto_estimate(model,duration=duration,characters=characters,count=count,resolution=resolution,aspect=aspect,references=references)
    if not model.price_confirmed or model.price_cny is None:
        raise StudioError("先确认该模型当前规格的价格或单次费用上限", "price_required", 409)
    units = Decimal(str(duration)) if model.price_unit == "second" else Decimal(characters)/1000 if model.price_unit == "1000_characters" else Decimal(count)
    return int((model.price_cny * units * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


def deployment_hash(model: ModelProfile, connection: Connection) -> str:
    pricing=model.pricing.model_dump(exclude={'source_url','fetched_at','notes','label','fx_source','fx_date'}) if model.pricing else None
    if pricing:
        from .pricing import effective_rates
        pricing['effective_rates']=effective_rates(model.pricing,reserve=True)
    return digest({"model": {**model.model_dump(exclude={"name","notes","price_source","tier","enabled","pricing","fx_date","evidence"}),'pricing':pricing}, "connection": {"id": connection.id, "url": connection.base_url, "auth": connection.auth, "region": connection.region,"credential_version":connection.credential_version}})


def generation_hash(model: ModelProfile, connection: Connection) -> str:
    return digest({"id":model.id,"api_model":model.api_model,"adapter":model.adapter,"params":model.params,"url":connection.base_url})


def local_compatible(shot) -> bool:
    images={(selected_candidate(a).asset_hash or selected_candidate(a).asset_id) for a in shot.anchors if a.required and a.role!='reference' and selected_candidate(a)}
    return shot.difficulty=='static' and not shot.requirements.action and shot.requirements.audio!='native_dialogue' and len(images)<=1 and not any(a.control_required and a.role in {'action','end'} for a in shot.anchors)


def clip_hash(p: Project, shot_id: str, item: RouteItem) -> str:
    shot = next(s for s in p.shots if s.id == shot_id)
    material={"visual": shot.visual, "motion": shot.motion, "duration": shot.duration, "aspect": p.aspect,
                   "selected": [{"id":a.id,"role":a.role,"at":a.at_seconds,"usage":item.anchor_usage.get(a.id),"image":(selected_candidate(a).asset_hash or selected_candidate(a).asset_id) if selected_candidate(a) else None} for a in shot.anchors], "source": shot.source_video_id,
                   "method": item.method, "model": item.model_id, "native_duration": item.native_duration,
                   "resolution": item.resolution, "generation_hash": item.generation_hash}
    if p.workbench_version>=2:material['global_style']=p.global_style
    if item.method=='local':material['local_motion']=item.local_motion
    interval=source_interval(p,shot)
    if interval:material["source_interval"]=interval
    if shot.requirements!=ShotRequirements():material["requirements"]=shot.requirements.model_dump()
    return digest(material)


def suggest_route(p: Project, settings: Settings, mode: str, resolution: str, *, remaining: int | None = None) -> tuple[RoutePlan, list[str]]:
    result = RoutePlan(mode=mode, resolution=resolution, creative_hash=creative_hash(p))
    warnings = []
    for shot in p.shots:
        item = RouteItem(shot_id=shot.id, native_duration=shot.duration, resolution=resolution)
        if shot.source_video_id:
            item.method = "reuse"; item.reason = "已提供原始视频，优先复用并保留主体真实性。"
            item.checks=["原声与画面按相同源区间裁切", "需审阅原片是否包含所要求的动作、主体和声音"]
        elif local_compatible(shot):
            item.method = "local"; item.reason = "静态主体与文字表达，用已选候选图本地合成，省去视频生成调用。"
            if any(word in shot.motion for word in ['推近','推进']) and not any(word in shot.motion for word in ['不推近','不要推近','禁止推近','不推进','固定定版']):item.local_motion='push_in';item.reason+=' 采用原图缓慢推近，保留包装文字。'
        else:
            candidates = []
            for m in settings.models:
                if m.kind != "video":
                    continue
                try:
                    _, c = get_model(settings, m.id, "video")
                    if resolution not in m.resolutions:raise StudioError("不支持此原生分辨率")
                    if m.max_reference_images<1:raise StudioError("当前图生视频路线需要首帧输入")
                    if shot.requirements.audio=="native_dialogue":raise StudioError("当前视频适配器未接通原生对白")
                    if any(a.control_required and a.role in {"action", "reference"} for a in shot.anchors):
                        raise StudioError("未接通镜头中间状态的精确控制")
                    if any(a.control_required and a.role == "end" for a in shot.anchors) and (not m.first_last or m.adapter!='ark_video' or m.max_reference_images<2):
                        raise StudioError("未接通所需尾帧控制")
                    native = next((d for d in sorted(m.durations) if d >= shot.duration), None) if m.durations else max(m.min_duration,__import__('math').ceil(shot.duration))
                    if native is None or native>m.max_duration:
                        raise StudioError("原生时长不能覆盖该镜头")
                    cost = estimate(m, duration=native,resolution=resolution,aspect=p.aspect)
                    preferred = "quality" if mode == "quality" or shot.difficulty == "complex" or shot.requirements.product_fidelity or shot.requirements.identity or shot.requirements.action else "economy"
                    if remaining is not None and cost>remaining:raise StudioError("单次费用超过项目剩余授权")
                    candidates.append((m.tier != preferred, cost, m, c, native))
                except StudioError as exc:
                    item.exclusions.append({"model_id":m.id,"name":m.name,"reason":str(exc)})
                    continue
            if candidates:
                _, cost, m, c, native = sorted(candidates, key=lambda x: (x[0], x[1]))[0]
                item.alternatives=[{"model_id":v[2].id,"name":v[2].name,"cost_micros":v[1],"native_duration":v[4],"evidence":v[2].evidence} for v in sorted(candidates,key=lambda x:(x[0],x[1]))[1:3]]
                item.checks=["已按账户、接口与规格过滤", "性能仍需项目样片审阅"]
                if shot.requirements.product_fidelity:item.checks.append("商品文字/外观需复核，图生视频不保证像素不变")
                if shot.requirements.identity:item.checks.append("使用已选人物参考并复核跨镜头身份")
                if shot.continuity_group:item.checks.append("连续性组："+shot.continuity_group+"；需对照同组采用画面")
                item.method = "generate"; item.model_id = m.id; item.native_duration = native; item.estimated_micros = cost; item.deployment_hash = deployment_hash(m, c)
                item.generation_hash = generation_hash(m,c)
                item.reason = ("复杂动作按已配置的质量档位优先推荐；实际效果需先试拍。" if shot.difficulty == "complex" else "在已配置能力、规格和官方价格内选择匹配的运动模型。")
                chosen=sorted([a for a in shot.anchors if a.selected_id and a.role!='reference'],key=lambda a:a.at_seconds)
                first=next((a for a in chosen if a.role=='start'),chosen[0] if chosen else None)
                last=next((a for a in reversed(chosen) if a.role=='end' and a is not first),None)
                for anchor in shot.anchors:
                    item.anchor_usage[anchor.id] = "first" if anchor is first else "last" if anchor is last and m.first_last and m.adapter=='ark_video' and m.max_reference_images>=2 else "review"
                if any(v == "review" for v in item.anchor_usage.values()):
                    warnings.append(f"{shot.title} 的部分关键帧仅用于验收，不是接口的精确时间控制。")
            else:
                item.method = "generate"; item.reason = "没有满足规格、能力与价格条件的已配置视频模型，请先配置或调整路线。"
                warnings.append(f"{shot.title} 尚无可执行视频模型。")
        result.items.append(item)
    return result, warnings

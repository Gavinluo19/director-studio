"""Role recommendations describe choices; users retain model and budget authority."""
from .models import Settings
from .pricing import PriceBook, quote_view

ROLES = [
    ('director','导演 / 方案策划','text','required','必配','强大脑先理解意图、提出方案。纯文本优先 GLM；复杂视觉选 K3；已有 ChatGPT 订阅可用 Astra / Sol。',['glm','k3','codex:gpt-6-astra','codex:gpt-5.6-sol','openai:gpt-6-astra']),
    ('shot_designer','镜头设计 / 图片理解','text','required','必配','有商品图或人物图时必须具备视觉理解；负责分镜画面与关键帧提示词。',['k3','codex:gpt-5.6-sol','openai:gpt-6-astra']),
    ('executor','经济执行 / 日常问答','text','required','必配 · 节省成本','轻量解释、内容整理与日常问答使用经济模型，避免每步都调用强大脑。',['glm-flash','ds-vision','ds-flash','codex:gpt-5.6-luna','openai:gpt-5.6-luna']),
    ('image','高质量关键帧 / 图生图','image','required','必配','共创区直接生成候选图；优先保留商品与人物一致性。首次配置后重复使用。',['seedream','gpt-image']),
    ('writer','专业编剧','text','optional','选填 · 可共用导演','需要不同写作风格时单独选择；留空沿用导演模型。',['glm','k3','codex:gpt-5.6-sol','openai:gpt-6-astra']),
    ('reviewer','视觉审片','text','optional','选填 · 可共用视觉主力','对照脚本检查抽样画面；最终由人确认成片。留空自动选择已配置视觉主力。',['k3','codex:gpt-5.6-sol','openai:gpt-6-astra']),
    ('video','视频制作候选','video','conditional','生成视频前必配','简单运动优先 Mini / 海螺 Fast；复杂动作优先 Seedance 2.0 / Runway Gen-4.5。已有视频或静态本地合成可不配。',['seedance-standard','minimax-video','seedance-quality','runway-quality']),
    ('tts','旁白 / 配音','tts','conditional','使用 AI 配音时必配','中文旁白优先 MiniMax HD；多语言可选 OpenAI。上传自己的录音可不配。',['minimax-tts','openai-tts']),
    ('music','背景音乐','music','optional','选填','需要原创音乐时选择 Eleven Music；使用已有授权音乐或无配乐则不用配置。',['eleven-music']),
]

def guide(settings: Settings,book):
    models={m.id:m for m in settings.models};connections={c.id:c for c in settings.connections}
    def ready(mid):
        m=models.get(mid);c=connections.get(m.connection_id) if m else None
        return bool(m and m.enabled and m.api_model and c and c.status in {'configured','ready'} and (m.adapter=='codex' or m.price_confirmed))
    rows=[]
    for role,label,kind,requirement,badge,reason,recommended in ROLES:
        current=getattr(settings.defaults,role)
        ids=[i for i in recommended if i in models]
        visual=role in {'shot_designer','reviewer'}
        options=[m.id for m in settings.models if m.kind==kind and (not visual or m.vision)]
        m=models.get(current);connection=connections.get(m.connection_id) if m else None
        missing=[]
        if m:
            if not m.api_model:missing.append('模型 ID / 接入点')
            if not m.enabled:missing.append('启用模型')
            if connection and connection.status not in {'configured','ready'}:missing.append('ChatGPT 登录' if m.adapter=='codex' else 'API Key 或连接验证')
            if m.adapter!='codex' and not m.price_confirmed:missing.append('精确型号的官方报价')
        state='已配置' if ready(current) else '待补齐：'+'、'.join(missing) if current else '尚未选择'
        rows.append({'role':role,'label':label,'kind':kind,'requirement':requirement,'badge':badge,'reason':reason,'recommended_ids':[i for i in ids if i in options],'option_ids':options,'selected':current,'ready':ready(current),'status':state})
    views={m.id:quote_view(m) for m in settings.models}
    return {'roles':rows,'required_ready':sum(r['ready'] for r in rows if r['requirement']=='required'),'required_total':sum(r['requirement']=='required' for r in rows),'prices':views,'fx':book['fx'],'subscriptions':book['subscriptions'],'refresh_status':book.get('refresh_status',[])}

def upgrade_presets(settings: Settings):
    """Attach family identity to unconfigured legacy placeholders, never replace credentials."""
    if not any(m.id=='minimax-image' for m in settings.models):
        from .catalog import preset_catalog
        settings.models.append(next(m for m in preset_catalog().models if m.id=='minimax-image'))
    defaults={'seedream':('doubao-seedream-5-0-pro','Seedream 5.0 Pro · 高质量关键帧'), 'seedance-standard':('doubao-seedance-2.0-mini','Seedance 2.0 Mini · 常规镜头'), 'seedance-quality':('doubao-seedance-2.0','Seedance 2.0 · 复杂动作')}
    for m in settings.models:
        if m.id in defaults and not m.api_model and not m.pricing_model:
            m.pricing_model,m.name=defaults[m.id]
            if m.id=='seedance-standard':m.resolutions=['480','720']
        if m.id=='minimax-video' and not m.api_model:m.api_model='MiniMax-Hailuo-2.3-Fast';m.name='MiniMax 海螺 2.3 Fast'
        if m.id=='minimax-tts' and not m.api_model:m.api_model='speech-2.8-hd';m.name='MiniMax Speech 2.8 HD'
    for m in settings.models:
        if m.notes.startswith('填写方舟已开通模型 ID'):m.notes='填写方舟已开通模型 ID 或推理接入点；按实际绑定型号自动采用官方价格。支持文字与多图参考生成。'
    return settings

"""Internal recipes with a closed command allowlist, never arbitrary executables."""
from pathlib import Path
from .models import StudioError

SKILLS = (
    {"id":"brand-shot", "name":"品牌镜头设计", "version":"1.0.0", "command":"refine_shot",
     "input":"选中镜头、已采用参考、品牌与保留项", "output":"可审阅修改提案", "file":"brand-shot.md"},
    {"id":"ip-rough-cut", "name":"个人 IP 粗剪", "version":"1.0.0", "command":"refine_transcript",
     "input":"选中转写及原片时间", "output":"保留/删除段落提案", "file":"ip-rough-cut.md"},
)

def resolve_skill(skill_id, action=None):
    s=next((s for s in SKILLS if s['id']==skill_id),None)
    if not s or (action is not None and action!=s['command']):
        raise StudioError("此 Skill 或工具不在已注册白名单内", "skill_not_allowed",403)
    return dict(s)

def instructions(skill_id):
    s=resolve_skill(skill_id)
    return (Path(__file__).parent/'recipes'/s['file']).read_text()

def capabilities(db):
    from .transcription import readiness
    settings=db.settings();models=[];adoptions={}
    for raw in db.projects():
        for shot in raw.get('shots',[]):
            candidate=next((v for v in shot.get('video_candidates',[]) if v['id']==shot.get('selected_video_id')),None)
            if candidate:
                adoptions.setdefault(candidate['model_id'],{})[candidate['asset_id']]={'project':raw['name'],'shot':shot['title'],'asset_id':candidate['asset_id'],'task_id':candidate.get('task_id','')}

    for m in settings.models:
        connection=next((c for c in settings.connections if c.id==m.connection_id),None)
        models.append({"id":m.id,"name":m.name,"kind":m.kind,"api_model":m.api_model,
                       "enabled":m.enabled,"connection_status":connection.status if connection else 'missing',
                       "checked_at":connection.checked_at if connection else None,
                       "vision":m.vision,"resolutions":m.resolutions,"durations":m.durations,
                       "first_last":m.first_last and m.adapter=='ark_video',
                       "native_dialogue":False,"evidence":m.evidence,
                       "adoption_samples":list(adoptions.get(m.id,{}).values()),"boundary":"配置/连接状态不代表样片质量已通过；采用记录不等同于人工质检通过"})
    return {"asr":readiness(),"models":models,
            "skills":[{k:v for k,v in s.items() if k!='file'} | {"tools":[s['command']],
                       "permissions":"仅提案；使用已配置认知模型并经过统一预算；无任意终端/网络权限"} for s in SKILLS]}

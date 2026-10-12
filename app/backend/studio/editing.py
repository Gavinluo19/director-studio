"""Versioned, deterministic editing commands. No provider calls or budget overrides."""
from __future__ import annotations

import re
from .models import (AudioCue, EditProposal, Project, RouteItem, ScriptBlock, Shot,
                     ShotRequirements, SourceRange, StudioError, Transcript,
                     TranscriptSegment, VideoCandidate, digest, uid)

COMMANDS = {"restore_content_revision", "upgrade_workbench", "update_context", "save_source_range", "import_transcript",
            "update_transcript_segment", "reorder_transcript", "apply_transcript",
            "adopt_video_candidate", "propose_edit", "apply_edit", "reject_edit"}


def shot_design(s: Shot) -> dict:
    return s.model_dump(exclude={"video_candidates","selected_video_id","clip_asset_id","clip_input_hash"})


def signature(s: Shot) -> str:
    d=shot_design(s)
    d["anchors"]=[{"id":a.id,"prompt":a.prompt,"selected_id":a.selected_id,"role":a.role,
                   "time":a.at_seconds,"refs":a.reference_asset_ids} for a in s.anchors]
    return digest(d)


def transcript_signature(t: Transcript) -> str:
    return digest(t.model_dump(include={"asset_id","segments"}))


def transcript_for(p: Project, tid: str) -> Transcript:
    t=next((t for t in p.transcripts if t.id==tid),None)
    if not t:raise StudioError("转写不存在", "not_found",404)
    return t


def validate_range(db, c, p, r):
    if r.asset_id not in p.asset_ids:raise StudioError("先把源素材加入项目")
    a=db.asset(r.asset_id,c)
    if not a['mime'].startswith(('video/','audio/')):raise StudioError("源区间需要视频或录音")
    duration=a['metadata'].get('duration',0)
    if r.end > duration+.001:raise StudioError("源区间超出素材时长", "range_out_of_bounds",409)


def parse_srt(text: str) -> list[TranscriptSegment]:
    def seconds(t):
        h,m,s=re.split(':',t.replace(',','.'));return int(h)*3600+int(m)*60+float(s)
    out=[]
    for part in re.split(r'\n\s*\n',text.strip().replace('\r','')):
        m=re.search(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})[^\n]*\n([\s\S]+)',part)
        if not m:raise StudioError("字幕格式错误，请导入含时间戳的 SRT")
        line=m[3].strip()
        if line:out.append(TranscriptSegment(start=seconds(m[1]),end=seconds(m[2]),original_text=line,text=line))
    if not out:raise StudioError("字幕没有有效段落")
    return out


def invalidate_content(p):
    p.creative_approved_hash=None;p.route.approved_hash=None;p.final_approved_hash=None


def apply_transcript(p, t, replace_existing=False):
    active=[s for s in t.segments if s.included]
    if not active:raise StudioError("至少保留一段内容")
    if p.shots and any(s.transcript_segment_id not in {s.id for s in t.segments} for s in p.shots) and not replace_existing:
        raise StudioError("这会替换当前剪辑；请明确确认，旧版将保留在历史中", "replace_confirmation",409)
    previous={s.id:s for s in p.shots}
    blocks=[];shots=[];cues=[];offset=0
    for seg in active:
        rid='range-'+seg.id;bid='block-'+seg.id;sid='shot-'+seg.id
        r=SourceRange(id=rid,asset_id=t.asset_id,start=seg.start,end=seg.end,label=seg.text[:32],status='usable')
        p.source_ranges=[x for x in p.source_ranges if x.id!=rid]+[r]
        blocks.append(ScriptBlock(id=bid,title=f'段落 {len(blocks)+1}',text=seg.text))
        shot=previous.get(sid) or Shot(id=sid,block_id=bid,title=f'原片 · {seg.text[:18]}',anchors=[],visual='保留原片与原声',difficulty='static')
        shot.duration=seg.end-seg.start;shot.source_video_id=t.asset_id;shot.source_range_id=rid;shot.transcript_segment_id=seg.id
        shots.append(shot)
        cues.append(AudioCue(id='subtitle-'+seg.id,text=seg.text,start=offset,duration=shot.duration,shot_ids=[sid]))
        offset+=shot.duration
    p.blocks=blocks;p.shots=shots;p.target_duration=offset
    p.audio.subtitles=cues;p.audio.narration=[];p.audio.narration_asset_id=None;p.audio.narration_hash=None
    p.audio.mute_native_audio=False;p.audio.allow_silent=False
    t.applied_hash=transcript_signature(t)
    invalidate_content(p);p.stage='create'


def seed_candidates(p):
    for s in p.shots:
        if s.clip_asset_id and not s.video_candidates:
            item=next((i for i in p.route.items if i.shot_id==s.id),None)
            v=VideoCandidate(asset_id=s.clip_asset_id,source_asset_id=s.source_generated_asset_id,model_id=item.model_id if item and item.model_id else 'local',
                             input_hash=s.clip_input_hash or '',source_interval=next((r.model_dump() for r in p.source_ranges if r.id==s.source_range_id),None),design=shot_design(s),route=item.model_dump() if item else {})
            s.video_candidates.append(v);s.selected_video_id=v.id


def apply_changes(shot, changes):
    allowed={'title','visual','motion','duration','requirements','prompts'}
    if not changes or set(changes)-allowed:raise StudioError("修改包含不允许的字段", "edit_scope",409)
    for k,v in changes.items():
        if k=='prompts':
            for entry in v:
                a=next((a for a in shot.anchors if a.id==entry.get('anchor_id')),None)
                if not a:raise StudioError("提示词不属于选中镜头", "edit_scope",409)
                a.prompt=str(entry['prompt']);a.approved_hash=None
        elif k=='requirements':shot.requirements=ShotRequirements.model_validate(v)
        else:setattr(shot,k,v)


def expire_proposals(p):
    for proposal in p.edit_proposals:
        if proposal.status!='proposed':continue
        if proposal.kind=='shot':
            target=next((s for s in p.shots if s.id==proposal.target_id),None)
            current=signature(target) if target else None
        else:
            target=next((t for t in p.transcripts if t.id==proposal.target_id),None)
            current=transcript_signature(target) if target else None
        if current!=proposal.source_hash:proposal.status='stale'


def execute(db,c,p,kind,data):
    from .service import shot_for
    from .catalog import clip_hash
    result={}
    if kind=='restore_content_revision':
        row=c.execute('SELECT document FROM revisions WHERE project_id=? AND revision=?',(p.id,int(data['revision']))).fetchone()
        if not row:raise StudioError('历史版本不存在','not_found',404)
        previous=Project.model_validate_json(row[0])
        for field in ['brief','proposal','context_notes','global_style','aspect','target_duration','blocks','shots','audio','source_ranges','transcripts','route']:
            setattr(p,field,getattr(previous,field))
        p.asset_ids=list(dict.fromkeys(p.asset_ids+previous.asset_ids))
        p.edit_proposals=[];p.proposal_approved_hash=None
        invalidate_content(p);p.stage='create'
    elif kind=='upgrade_workbench':
        from .models import render_hash
        if p.workbench_version<2:
            previous_render=render_hash(p)
            valid={s.id:s.clip_input_hash for s in p.shots for i in p.route.items if i.shot_id==s.id and s.clip_asset_id and s.clip_input_hash==clip_hash(p,s.id,i)}
            seed_candidates(p);p.workbench_version=2
            for s in p.shots:
                if s.id not in valid:continue
                item=next(i for i in p.route.items if i.shot_id==s.id)
                current=clip_hash(p,s.id,item);s.clip_input_hash=current
                for v in s.video_candidates:
                    if v.input_hash==valid[s.id]:v.input_hash=current
            if p.render_hash==previous_render:p.render_hash=render_hash(p)
            if p.final_approved_hash==previous_render:p.final_approved_hash=render_hash(p)
    elif kind=='update_context':
        p.context_notes=str(data.get('text',''));invalidate_content(p)
    elif kind=='save_source_range':
        old=next((x for x in p.source_ranges if x.id==data.get('range',{}).get('id')),None)
        r=SourceRange.model_validate(data['range']);validate_range(db,c,p,r)
        seed_candidates(p)
        if r.status=='rejected' and data.get('shot_id'):raise StudioError('不可采用已拒绝区间')
        p.source_ranges=[x for x in p.source_ranges if x.id!=r.id]+[r]
        affected=[s for s in p.shots if s.source_range_id==r.id or s.id==data.get('shot_id')]
        for s in affected:
            if r.status=='rejected':raise StudioError('已采用区间不可直接标记拒绝，请先替换片段')
            s.source_range_id=r.id;s.source_video_id=r.asset_id;s.duration=r.end-r.start
            for a in s.anchors:
                if a.at_seconds>s.duration:a.at_seconds=s.duration;a.approved_hash=None
        if affected and (old is None or old.model_dump(include={'asset_id','start','end'})!=r.model_dump(include={'asset_id','start','end'}) or any(s.source_range_id!=r.id for s in affected)):invalidate_content(p)
        result['range_id']=r.id
    elif kind=='import_transcript':
        segments=parse_srt(data['srt'])
        t=Transcript(asset_id=data['asset_id'],segments=segments)
        for s in segments:validate_range(db,c,p,SourceRange(asset_id=t.asset_id,start=s.start,end=s.end))
        p.transcripts.append(t);result['transcript_id']=t.id
    elif kind in {'update_transcript_segment','reorder_transcript','apply_transcript'}:
        t=transcript_for(p,data['transcript_id'])
        if kind=='update_transcript_segment':
            seg=next((s for s in t.segments if s.id==data['segment_id']),None)
            if not seg:raise StudioError("段落不存在")
            if 'text' in data:
                seg.text=str(data['text']).strip()
                if not seg.text:raise StudioError("段落文字不能为空；要剪除原片请使用保留开关")
                # Caption-only correction never changes the source interval or audio.
                for cue in p.audio.subtitles:
                    if cue.id=='subtitle-'+seg.id:cue.text=seg.text;p.final_approved_hash=None
                for b in p.blocks:
                    if b.id=='block-'+seg.id:b.text=seg.text;invalidate_content(p)
            if 'start' in data or 'end' in data:
                interval=SourceRange(asset_id=t.asset_id,start=data.get('start',seg.start),end=data.get('end',seg.end))
                validate_range(db,c,p,interval)
                seg.start=interval.start;seg.end=interval.end
            if 'included' in data:
                if not isinstance(data['included'],bool):raise StudioError("保留状态需要布尔值")
                seg.included=data['included']
        elif kind=='reorder_transcript':
            ids=data['segment_ids']
            if len(ids)!=len(t.segments) or set(ids)!={s.id for s in t.segments}:raise StudioError("排序必须包含全部段落且不重复")
            t.segments=sorted(t.segments,key=lambda s:ids.index(s.id))
        else:apply_transcript(p,t,bool(data.get('replace_existing')))
    elif kind=='adopt_video_candidate':
        s=shot_for(p,data['shot_id']);v=next((v for v in s.video_candidates if v.id==data['candidate_id']),None)
        if not v:raise StudioError("视频候选不存在")
        item=next((i for i in p.route.items if i.shot_id==s.id),None)
        if data.get('restore_design'):
            restored=Shot.model_validate({**v.design,'video_candidates':[x.model_dump() for x in s.video_candidates]})
            if v.source_interval:
                r=SourceRange.model_validate({**v.source_interval,'id':uid()});validate_range(db,c,p,r)
                p.source_ranges.append(r);restored.source_range_id=r.id
            index=p.shots.index(s);p.shots[index]=restored;s=restored
            if v.route:
                item=RouteItem.model_validate(v.route)
                p.route.items=[x for x in p.route.items if x.shot_id!=s.id]+[item]
            invalidate_content(p)
        elif not item or clip_hash(p,s.id,item)!=v.input_hash:
            raise StudioError("候选属于旧设计，可使用“恢复镜头并采用”", "candidate_stale",409)
        db.asset(v.asset_id,c)
        s.clip_asset_id=v.asset_id;s.source_generated_asset_id=v.source_asset_id
        s.clip_input_hash=clip_hash(p,s.id,item) if item else v.input_hash;s.selected_video_id=v.id
        p.final_approved_hash=None
    elif kind=='propose_edit':
        s=shot_for(p,data['shot_id']);changes=data['changes']
        check=s.model_copy(deep=True);apply_changes(check,changes);Shot.model_validate(check.model_dump())
        e=EditProposal(kind='shot',target_id=s.id,source_hash=signature(s),changes=changes,
                       summary=data.get('summary','修改选中镜头'),impacts=[s.title,'相关关键帧/镜头需要复核；其余采用素材保留','新生成另行核价'])
        p.edit_proposals.append(e);result['proposal_id']=e.id
    elif kind in {'apply_edit','reject_edit'}:
        e=next((e for e in p.edit_proposals if e.id==data['proposal_id']),None)
        if e and e.status=='stale':raise StudioError(('镜头' if e.kind=='shot' else '文稿')+'已变化，请重新生成提案','proposal_stale',409)
        if not e or e.status!='proposed':raise StudioError("提案不存在或已处理")
        if kind=='reject_edit':e.status='rejected'
        elif e.kind=='shot':
            s=shot_for(p,e.target_id)
            if signature(s)!=e.source_hash:raise StudioError("镜头已变化，请重新生成提案", "proposal_stale",409)
            seed_candidates(p);apply_changes(s,e.changes);invalidate_content(p);e.status='applied'
        else:
            t=transcript_for(p,e.target_id)
            if transcript_signature(t)!=e.source_hash:raise StudioError("文稿已变化，请重新生成提案", "proposal_stale",409)
            keep=e.changes['keep_ids']
            if not keep or len(set(keep))!=len(keep) or set(keep)-{s.id for s in t.segments}:raise StudioError("提案引用了无效段落")
            for seg in t.segments:seg.included=seg.id in keep
            e.status='applied'
    return result

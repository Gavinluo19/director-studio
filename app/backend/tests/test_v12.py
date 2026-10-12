"""V1.2 regressions use isolated data; no network or paid providers."""
import asyncio
import io
import subprocess
import wave
import numpy as np
import pytest
from pydantic import ValidationError
from studio.assets import Assets
from studio.catalog import clip_hash, deployment_hash
from studio.models import StudioError
from studio.worker import Worker
from studio.database import reserve_job
from test_studio import studio, cmd, prepared


def source(studio):
    db,s,_=studio
    rate=16000;t=np.arange(rate*10)/rate
    samples=(12000*np.sin(2*np.pi*(300*t+30*t*t))).astype('<i2')
    b=io.BytesIO()
    with wave.open(b,'wb') as w:w.setparams((1,2,rate,len(samples),'NONE',''));w.writeframes(samples.tobytes())
    return Assets(db).ingest(b.getvalue(),'test-source.wav')


def transcript(studio):
    db,s,_=studio;p=s.create_project('个人 IP',category='creator');a=source(studio)
    cmd(s,p.id,'attach_asset',asset_id=a['id'])
    r=cmd(s,p.id,'import_transcript',asset_id=a['id'],srt='1\n00:00:01,000 --> 00:00:03,000\n保留第一观点\n\n2\n00:00:04,000 --> 00:00:06,000\n这是重复部分\n\n3\n00:00:07,000 --> 00:00:09,000\n保留限定条件')
    return db.get_project(p.id),r['transcript_id']


def run_local(studio,p,kind,**payload):
    db,s,v=studio;r=cmd(s,p.id,kind,**payload);w=Worker(db,v);job=db.claim(w.owner)
    assert job['id']==r['job_id']
    asyncio.run(w.run_job(job));done=db.job(job['id'])
    assert done['state']=='succeeded',done.get('error')
    return done


def test_range_validation(studio):
    db,s,_=studio;p=prepared(studio,durations=(4,));a=source(studio);cmd(s,p.id,'attach_asset',asset_id=a['id'])
    for start,end in [(7,3),(3,3),(-1,3),(3,11)]:
        with pytest.raises((StudioError,ValidationError)):
            cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={'asset_id':a['id'],'start':start,'end':end})
    cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={'asset_id':a['id'],'start':3,'end':7,'status':'usable'})
    p=db.get_project(p.id);assert p.shots[0].duration==4
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route')
    p=db.get_project(p.id);assert p.route.items[0].method=='reuse'
    run_local(studio,p,'generate_shot',shot_id=p.shots[0].id)
    cmd(s,p.id,'update_audio',mute_native_audio=False)
    done=run_local(studio,p,'render');path=Assets(db).path(done['result']['asset_id'])
    out=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar','16000','-'])
    audio=np.frombuffer(out,dtype='<f4');window=audio[8000:16000]
    peak=np.fft.rfftfreq(len(window),1/16000)[np.argmax(abs(np.fft.rfft(window)))];assert 490<peak<550


def test_transcript_caption_and_reorder(studio):
    db,s,_=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid)
    p=db.get_project(p.id);segments=p.transcripts[0].segments;before=[(r.start,r.end) for r in p.source_ranges]
    cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=segments[0].id,text='人工修订的字幕')
    p=db.get_project(p.id);assert [(r.start,r.end) for r in p.source_ranges]==before
    assert p.audio.subtitles[0].text=='人工修订的字幕';assert p.transcripts[0].segments[0].original_text=='保留第一观点'
    cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=segments[1].id,included=False)
    assert len(db.get_project(p.id).shots)==3
    cmd(s,p.id,'reorder_transcript',transcript_id=tid,segment_ids=[x.id for x in reversed(segments)])
    cmd(s,p.id,'apply_transcript',transcript_id=tid);p=db.get_project(p.id)
    assert p.target_duration==4 and [c.start for c in p.audio.subtitles]==[0,2]
    assert [next(r.start for r in p.source_ranges if r.id==sh.source_range_id) for sh in p.shots]==[7,1]
    assert not p.audio.mute_native_audio


def test_scoped_proposal_and_stale_guard(studio):
    db,s,_=studio;p=prepared(studio);keep=p.shots[1].model_dump()
    r=cmd(s,p.id,'propose_edit',shot_id=p.shots[0].id,changes={'motion':'轻微推近'})
    cmd(s,p.id,'apply_edit',proposal_id=r['proposal_id']);p=db.get_project(p.id)
    assert p.shots[1].model_dump()==keep and p.shots[0].motion=='轻微推近'
    r=cmd(s,p.id,'propose_edit',shot_id=p.shots[0].id,changes={'motion':'平移'})
    cmd(s,p.id,'update_shot',shot_id=p.shots[0].id,visual='新的画面')
    with pytest.raises(StudioError,match='镜头已变化'):cmd(s,p.id,'apply_edit',proposal_id=r['proposal_id'])


def test_candidate_interval_restore_and_other_clip(studio):
    db,s,_=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid)
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route');p=db.get_project(p.id)
    for shot in p.shots:run_local(studio,p,'generate_shot',shot_id=shot.id)
    p=db.get_project(p.id);old=p.shots[0].video_candidates[0];keep=p.shots[1].clip_asset_id
    r=next(r for r in p.source_ranges if r.id==p.shots[0].source_range_id)
    cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={**r.model_dump(),'start':2,'end':4})
    with pytest.raises(StudioError,match='旧设计'):cmd(s,p.id,'adopt_video_candidate',shot_id=p.shots[0].id,candidate_id=old.id)
    cmd(s,p.id,'adopt_video_candidate',shot_id=p.shots[0].id,candidate_id=old.id,restore_design=True)
    p=db.get_project(p.id);assert p.shots[1].clip_asset_id==keep
    assert next(r.start for r in p.source_ranges if r.id==p.shots[0].source_range_id)==1
    item=next(i for i in p.route.items if i.shot_id==p.shots[0].id)
    assert p.shots[0].clip_input_hash==clip_hash(p,p.shots[0].id,item)


def test_skill_allowlist_and_paid_budget(studio):
    db,s,_=studio;p=prepared(studio)
    for skill,action in [('evil','refine_shot'),('brand-shot','generate_shot'),('brand-shot','terminal')]:
        with pytest.raises(StudioError,match='白名单'):cmd(s,p.id,'run_skill',skill_id=skill,action=action,shot_id=p.shots[0].id)
    with pytest.raises(StudioError,match='预算|额度'):cmd(s,p.id,'run_skill',skill_id='brand-shot',shot_id=p.shots[0].id)
    assert not db.jobs(p.id)


def test_one_asr_lease(studio):
    db,s,_=studio;p=s.create_project('ASR 队列')
    with db.transaction() as c:
        for i in range(2):reserve_job(c,db,p,key=str(i),request_hash=str(i),kind='transcribe',target_id=str(i),input_hash=str(i),payload={})
    assert db.claim('worker-one') is not None
    assert db.claim('worker-two') is None


def test_metadata_does_not_invalidate(studio):
    db,s,_=studio;p=prepared(studio);cmd(s,p.id,'approve_creative');before=db.get_project(p.id).creative_approved_hash
    settings=db.settings();m=settings.models[0];conn=next(c for c in settings.connections if c.id==m.connection_id)
    old=deployment_hash(m,conn);m.evidence=[{'source':'内部样片','sample_count':1,'verified':False}]
    assert deployment_hash(m,conn)==old
    assert db.get_project(p.id).creative_approved_hash==before


def test_stage_navigation_is_not_execution_authority(studio):
    db,s,_=studio;p=s.create_project('阶段只是导航')
    cmd(s,p.id,'set_stage',stage='review');assert db.get_project(p.id).stage=='review'
    with pytest.raises(StudioError):cmd(s,p.id,'render')


def test_video_picture_and_audio_share_range(studio):
    from studio.media import Media
    db,s,_=studio;p=prepared(studio,durations=(4,));a=source(studio);assets=Assets(db)
    path=db.root/'ten-seconds.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=red:s=320x240:r=30:d=10','-i',str(assets.path(a['id'])),'-vf',"drawbox=color=green:t=fill:enable='gte(t,3)',drawbox=color=blue:t=fill:enable='gte(t,7)'",'-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(path)],check=True)
    video=assets.ingest_path(path,'三段色卡与连续音调.mp4');cmd(s,p.id,'attach_asset',asset_id=video['id'])
    cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={'asset_id':video['id'],'start':3,'end':7,'status':'usable'})
    cmd(s,p.id,'update_audio',mute_native_audio=False);cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route')
    run_local(studio,p,'generate_shot',shot_id=p.shots[0].id);done=run_local(studio,p,'render');path=assets.path(done['result']['asset_id'])
    for at in [.1,2,3.9]:
        raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(at),'-i',str(path),'-frames:v','1','-vf','crop=2:2:(iw-2)/2:(ih-2)/2','-f','rawvideo','-pix_fmt','rgb24','-'])
        rgb=np.frombuffer(raw,dtype='uint8').reshape(-1,3).mean(axis=0);assert rgb[1]>70 and rgb[0]<10 and rgb[2]<10
    audio=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar','16000','-']),dtype='<f4')
    w=audio[8000:16000];peak=np.fft.rfftfreq(len(w),1/16000)[np.argmax(abs(np.fft.rfft(w)))];assert 490<peak<550


def test_history_restore_and_archive_roundtrip(studio):
    import json
    from fastapi.testclient import TestClient
    from studio.api import create_app
    db,s,_=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid);p=db.get_project(p.id);rev=p.revision
    cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=p.transcripts[0].segments[0].id,included=False)
    cmd(s,p.id,'apply_transcript',transcript_id=tid);assert len(db.get_project(p.id).shots)==2
    cmd(s,p.id,'restore_content_revision',revision=rev);assert len(db.get_project(p.id).shots)==3
    with TestClient(create_app(db.root,testing=True,serve_frontend=False)) as client:
        client.headers['x-studio-csrf']=client.get('/api/bootstrap').json()['csrf']
        archive=client.get(f'/api/projects/{p.id}/archive');assert archive.status_code==200
        result=client.post('/api/import-archive',files={'file':('project.zip',archive.content,'application/zip')});assert result.status_code==200,result.text
        restored=result.json();assert len(restored['source_ranges'])==3 and restored['transcripts'][0]['segments'][0]['included']
        versions=client.get(f"/api/projects/{restored['id']}/revisions").json();assert len(versions)>3


def test_render_becomes_stale_after_source_change(studio):
    from studio.models import render_hash
    db,s,_=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid);p=db.get_project(p.id)
    old=render_hash(p);r=p.source_ranges[0]
    cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={**r.model_dump(),'start':2,'end':4})
    assert render_hash(db.get_project(p.id))!=old


def test_reordered_media_audio_and_caption_timing(studio):
    db,s,_=studio;p,tid=transcript(studio);segs=p.transcripts[0].segments
    cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=segs[1].id,included=False)
    cmd(s,p.id,'reorder_transcript',transcript_id=tid,segment_ids=[x.id for x in reversed(segs)])
    cmd(s,p.id,'apply_transcript',transcript_id=tid);cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route')
    p=db.get_project(p.id)
    for shot in p.shots:run_local(studio,p,'generate_shot',shot_id=shot.id)
    result=run_local(studio,p,'render');path=Assets(db).path(result['result']['asset_id'])
    audio=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar','16000','-']),dtype='<f4')
    peaks=[]
    for offset in [.5,2.5]:
        w=audio[int(offset*16000):int((offset+.3)*16000)]
        peaks.append(np.fft.rfftfreq(len(w),1/16000)[np.argmax(abs(np.fft.rfft(w)))])
    assert 740<peaks[0]<780 and 380<peaks[1]<420
    p=db.get_project(p.id);assert [x.start for x in p.audio.subtitles]==[0,2]


def test_segment_boundary_edit_is_staged(studio):
    db,s,_=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid);p=db.get_project(p.id);seg=p.transcripts[0].segments[0]
    cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=seg.id,start=1.2,end=2.8)
    assert db.get_project(p.id).shots[0].duration==2
    cmd(s,p.id,'apply_transcript',transcript_id=tid);assert db.get_project(p.id).shots[0].duration==pytest.approx(1.6)
    with pytest.raises(StudioError):cmd(s,p.id,'update_transcript_segment',transcript_id=tid,segment_id=seg.id,end=30)


def test_old_job_finishes_as_candidate_without_overwriting(studio):
    db,s,v=studio;p,tid=transcript(studio);cmd(s,p.id,'apply_transcript',transcript_id=tid);cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route');p=db.get_project(p.id)
    r=cmd(s,p.id,'generate_shot',shot_id=p.shots[0].id);w=Worker(db,v);job=db.claim(w.owner)
    source_range=next(x for x in p.source_ranges if x.id==p.shots[0].source_range_id)
    cmd(s,p.id,'save_source_range',shot_id=p.shots[0].id,range={**source_range.model_dump(),'start':2,'end':4})
    asyncio.run(w.run_job(job));done=db.job(r['job_id']);assert done['state']=='superseded'
    p=db.get_project(p.id);assert p.shots[0].clip_asset_id is None and len(p.shots[0].video_candidates)==1


def test_local_cancel_recovers_without_unknown_charge(studio):
    import time
    db,s,_=studio;p=s.create_project('本地任务取消恢复')
    with db.transaction() as c:
        job=reserve_job(c,db,p,key='asr',request_hash='asr',kind='transcribe',target_id='asset',input_hash='asr',payload={})
        c.execute("UPDATE jobs SET state='cancel_requested',lease_until=? WHERE id=?",(time.time()-1,job['id']))
    assert db.claim('new-worker') is None and db.job(job['id'])['state']=='cancelled'


def test_fractional_cuts_do_not_accumulate_video_drift(studio):
    from studio.models import Shot,ScriptBlock,SourceRange,Project
    from studio.media import Media
    db,s,_=studio;assets=Assets(db);a=source(studio);path=db.root/'colors.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=green:s=320x240:r=30:d=10','-i',str(assets.path(a['id'])),'-vf',"drawbox=color=blue:t=fill:enable='gte(t,7)'",'-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(path)],check=True)
    video=assets.ingest_path(path,'色卡.mp4');block=ScriptBlock(text='非整帧剪辑')
    ranges=[SourceRange(asset_id=video['id'],start=3,end=3.07) for _ in range(12)]+[SourceRange(asset_id=video['id'],start=7,end=7.5)]
    p=Project(name='帧边界',aspect='16:9',blocks=[block],source_ranges=ranges,asset_ids=[video['id']],shots=[Shot(block_id=block.id,source_video_id=video['id'],source_range_id=r.id,duration=r.end-r.start) for r in ranges])
    p.route.resolution='480';p.audio.mute_native_audio=False;media=Media(assets)
    for i,shot in enumerate(p.shots):shot.clip_asset_id=media.local_clip(p,shot,'480',db.root/f'clip-{i}')['id']
    result=media.render(p,db.root/'render-fractional')
    # The blue interval starts at .84s. Rounding each source clip independently would put it at 1.2s.
    raw=subprocess.check_output(['ffmpeg','-v','error','-ss','0.95','-i',str(assets.path(result['id'])),'-frames:v','1','-vf','crop=2:2:(iw-2)/2:(ih-2)/2','-f','rawvideo','-pix_fmt','rgb24','-'])
    rgb=np.frombuffer(raw,dtype='uint8').reshape(-1,3).mean(axis=0);assert rgb[2]>150 and rgb[1]<10


def test_style_is_part_of_v12_generation_input(studio):
    db,s,_=studio;p=prepared(studio);cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');p=db.get_project(p.id)
    before=clip_hash(p,p.shots[0].id,p.route.items[0]);p.global_style+='新的光线'
    assert clip_hash(p,p.shots[0].id,p.route.items[0])!=before


def test_upgrade_legacy_keeps_current_clips(studio):
    db,s,_=studio;p=prepared(studio,durations=(1,))
    with db.transaction() as c:p.workbench_version=1;db.save_project(p,c)
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='480');cmd(s,p.id,'approve_route')
    run_local(studio,p,'generate_shot',shot_id=p.shots[0].id);before=db.get_project(p.id).shots[0].clip_asset_id
    cmd(s,p.id,'upgrade_workbench');p=db.get_project(p.id)
    assert p.workbench_version==2 and p.shots[0].clip_asset_id==before
    assert p.shots[0].clip_input_hash==clip_hash(p,p.shots[0].id,p.route.items[0])

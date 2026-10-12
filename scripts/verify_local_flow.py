"""Exercise the real HTTP server, independent worker and FFmpeg with local fixtures.
No provider account or paid model is used. Run with app/backend/.venv/bin/python.
"""
from __future__ import annotations
import io
import json
import math
import socket
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
from studio import __version__

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'app'/'verification'
OUT.mkdir(parents=True,exist_ok=True)
DATA=OUT/'local-runtime'
PORT=8878
with socket.socket() as s:
    s.bind(('127.0.0.1',PORT))
log=(OUT/'local-flow.log').open('w')
server=None

def launch():
    global server
    server=subprocess.Popen([sys.executable,'-m','studio.launcher','--port',str(PORT),'--data-dir',str(DATA)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if server.poll() is not None:raise RuntimeError('Supervisor stopped; inspect local-flow.log')
        try:
            if httpx.get(f'http://127.0.0.1:{PORT}/api/health',timeout=.5).json().get('workers'):return
        except (httpx.HTTPError,ValueError):pass
        time.sleep(.2)
    raise TimeoutError('HTTP/worker startup timeout')

def stop():
    if server and server.poll() is None:
        server.terminate()
        try:server.wait(timeout=20)
        except subprocess.TimeoutExpired:server.kill();server.wait()

def session():
    c=httpx.Client(base_url=f'http://127.0.0.1:{PORT}',timeout=10)
    b=c.get('/api/bootstrap');b.raise_for_status()
    c.headers['x-studio-csrf']=b.json()['csrf']
    return c

try:
    launch();c=session()
    assert c.get('/').status_code==200 and c.get('/b0').status_code==200
    p=c.post('/api/projects',json={'name':'V1 本地管线验收（测试素材）'}).json();pid=p['id']
    def project():return c.get('/api/projects/'+pid).json()
    def command(kind,**payload):
        current=project()
        r=c.post('/api/projects/'+pid+'/commands',json={'type':kind,'expected_revision':current['revision'],'payload':payload})
        r.raise_for_status();return r.json()
    def upload(data,name,mime):
        r=c.post('/api/assets',files={'file':(name,data,mime)});r.raise_for_status();asset=r.json()
        command('attach_asset',asset_id=asset['id']);return asset['id']
    def wait_job(jid):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            j=next(j for j in c.get('/api/projects/'+pid+'/jobs').json() if j['id']==jid)
            if j['state']=='succeeded':return j
            if j['state'] in {'failed','unknown','cancelled','superseded'}:raise RuntimeError(j)
            time.sleep(.25)
        raise TimeoutError(jid)
    command('update_brief',brief='本地声画管线技术验收，不是 AI 生成作品。',target_duration=6,aspect='16:9')
    command('add_block',title='一个完整段落',text='用本地测试画面核对两段镜头、中文字幕和声音轨道。')
    bid=project()['blocks'][0]['id']
    command('add_shot',block_id=bid,duration=2)
    command('add_shot',block_id=bid,duration=4)
    im=Image.new('RGB',(960,540),'#e9e4d8');draw=ImageDraw.Draw(im)
    draw.rectangle((80,80,880,460),outline='#ad684b',width=4)
    draw.text((110,150),'LOCAL PIPELINE TEST - NOT AI GENERATED',fill='#25231f',font_size=24)
    buf=io.BytesIO();im.save(buf,'PNG');picture=upload(buf.getvalue(),'local-test.png','image/png')
    for i,shot in enumerate(project()['shots']):
        command('update_shot',shot_id=shot['id'],title=f'本地测试镜头 {i+1}',visual='静态测试卡，保持内容与布局',difficulty='static')
        if i==0:command('add_anchor',shot_id=shot['id'],role='end',at_seconds=2)
        for anchor in next(s for s in project()['shots'] if s['id']==shot['id'])['anchors']:
            command('update_anchor',anchor_id=anchor['id'],prompt='保留原始测试卡，作为该时刻画面')
            r=command('candidate_from_asset',anchor_id=anchor['id'],asset_id=picture)
            command('select_candidate',anchor_id=anchor['id'],candidate_id=r['candidate_id'])
            command('approve_anchor',anchor_id=anchor['id'])
    unconfigured=c.post('/api/projects/'+pid+'/commands',json={'type':'generate_image','expected_revision':project()['revision'],'payload':{'anchor_id':project()['shots'][0]['anchors'][0]['id']}})
    assert unconfigured.status_code>=400
    command('approve_creative');command('suggest_route',resolution='480');command('approve_route')
    jobs=[command('generate_shot',shot_id=s['id'])['job_id'] for s in project()['shots']]
    for job in jobs:wait_job(job)
    command('set_stage',stage='audio')
    audio=io.BytesIO()
    with wave.open(audio,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000)
        w.writeframes(b''.join(struct.pack('<h',int(1200*math.sin(2*math.pi*330*i/16000))) for i in range(6*16000)))
    sound=upload(audio.getvalue(),'local-test-tone.wav','audio/wav')
    command('update_audio',music_asset_id=sound,music_gain=.25,subtitles=[{'text':'本地管线验收 · 测试素材','start':0,'duration':3},{'text':'独立声音与中文字幕','start':3,'duration':3}],effects=[{'asset_id':sound,'start':4,'duration':1,'gain':.1}])
    assert c.get('/api/projects/'+pid+'/export').status_code>=400
    render=wait_job(command('render')['job_id'])
    command('add_review_issue',start=1,end=2,description='技术验收问题标记',severity='warning')
    blocked=c.post('/api/projects/'+pid+'/commands',json={'type':'approve_final','expected_revision':project()['revision'],'payload':{}})
    assert blocked.status_code>=400
    issue=project()['review_issues'][0]['id']
    command('resolve_review_issue',issue_id=issue,status='resolved',note='测试声音和字幕检查通过')
    command('approve_final')
    output=c.get('/api/projects/'+pid+'/export');output.raise_for_status();(OUT/'local-pipeline-test.mp4').write_bytes(output.content)
    srt=c.get('/api/projects/'+pid+'/subtitles');srt.raise_for_status();(OUT/'local-pipeline-test.srt').write_text(srt.text)
    archive=c.get('/api/projects/'+pid+'/archive');archive.raise_for_status();(OUT/'local-pipeline-test.zip').write_bytes(archive.content)
    budget=c.get('/api/projects/'+pid+'/budget').json()
    assert budget['media']['spent']==0 and budget['media']['reserved']==0
    c.close();stop();launch();c=session()
    restored_original=project();assert restored_original['final_approved_hash']
    restored=c.post('/api/import-archive',files={'file':('project.zip',archive.content,'application/zip')});restored.raise_for_status()
    assert restored.json()['final_approved_hash'] is None and len(restored.json()['shots'])==2
    proof={'project_id':pid,'version':__version__,'blocks':1,'shots':2,'anchors':3,'duration_seconds':6,'resolution':'480','aspect':'16:9','real_model_calls':0,'media_spent_rmb':0,'checks':['HTTP frontend','independent worker','unconfigured image rejected','local video files','audio and Chinese subtitles','unreviewed export rejected','review issue blocks approval','MP4 and SRT export','project archive','supervisor restart persistence','restore requires fresh approvals'],'render':render['result']['technical_checks']}
    (OUT/'local-flow-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False))
finally:
    stop();log.close()

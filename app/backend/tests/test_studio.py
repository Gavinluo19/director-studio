from __future__ import annotations

import io
import time
import wave
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from studio.adapters import Adapters, UnknownSubmission
from studio.api import create_app
from studio.assets import Assets
from studio.catalog import preset_catalog
from studio.database import Database, budget_snapshot, reserve_job
from studio.models import Command, Project, StudioError, digest
from studio.service import StudioService
from studio.vault import Vault
from studio.worker import Worker


@pytest.fixture
def studio(tmp_path):
    db=Database(tmp_path)
    s=preset_catalog()
    for conn in s.connections:conn.status="configured";conn.auth="none"
    for m in s.models:
        m.enabled=True;m.api_model=m.api_model or "test-model";m.price_cny=Decimal("0.1");m.price_confirmed=True
    s=type(s).model_validate(s.model_dump())
    s.defaults.image="seedream";s.defaults.director="glm";s.defaults.writer="glm";s.defaults.shot_designer="k3"
    with db.transaction() as c:db.save_settings(s,c)
    return db,StudioService(db),Vault(db,use_keychain=False)


def cmd(service,pid,kind,**payload):
    p=service.db.get_project(pid)
    return service.command(pid,Command(type=kind,expected_revision=p.revision,payload=payload))


def png():
    buffer=io.BytesIO();Image.new("RGB",(320,240),(220,205,180)).save(buffer,"PNG");return buffer.getvalue()


def prepared(studio, durations=(1,2)):
    db,service,_=studio;p=service.create_project("测试短片")
    cmd(service,p.id,"update_brief",target_duration=sum(durations))
    cmd(service,p.id,"add_block",text="完整脚本，一个段落对应多个镜头。")
    p=db.get_project(p.id);bid=p.blocks[0].id
    for d in durations:cmd(service,p.id,"add_shot",block_id=bid,duration=d)
    a=Assets(db).ingest(png(),"参考.png")
    cmd(service,p.id,"attach_asset",asset_id=a["id"])
    for shot in db.get_project(p.id).shots:
        cmd(service,p.id,"update_shot",shot_id=shot.id,visual="固定构图展示主体",difficulty="static")
        anchor=shot.anchors[0]
        cmd(service,p.id,"update_anchor",anchor_id=anchor.id,prompt="主体在画面中央")
        r=cmd(service,p.id,"candidate_from_asset",anchor_id=anchor.id,asset_id=a["id"])
        cmd(service,p.id,"select_candidate",anchor_id=anchor.id,candidate_id=r["candidate_id"])
        cmd(service,p.id,"approve_anchor",anchor_id=anchor.id)
    return db.get_project(p.id)


def test_dynamic_shots_and_anchors(studio):
    db,s,_=studio;p=s.create_project("动态分镜")
    cmd(s,p.id,"add_block",text="第一段")
    bid=db.get_project(p.id).blocks[0].id
    for count in [1,2,3]:cmd(s,p.id,"add_shot",block_id=bid,count=count)
    p=db.get_project(p.id);assert len(p.blocks)==1 and len(p.shots)==6
    for role,t in [("action",2.5),("end",5)]:cmd(s,p.id,"add_anchor",shot_id=p.shots[0].id,role=role,at_seconds=t)
    assert len(db.get_project(p.id).shots[0].anchors)==3
    cmd(s,p.id,"remove_shot",shot_id=p.shots[-1].id)
    assert len(db.get_project(p.id).shots)==5


def test_revision_and_idempotency(studio):
    db,s,_=studio;p=s.create_project("幂等")
    c=Command(type="add_block",expected_revision=p.revision,payload={"text":"一段"})
    a=s.command(p.id,c);b=s.command(p.id,c)
    assert a==b and len(db.get_project(p.id).blocks)==1
    with pytest.raises(StudioError,match="已经更新"):s.command(p.id,Command(type="add_block",expected_revision=p.revision,payload={"text":"其他"}))


def test_image_exploration_before_creative_approval(studio):
    db,s,_=studio;p=prepared(studio)
    aid=p.shots[0].anchors[0].id
    r=cmd(s,p.id,"generate_image",anchor_id=aid)
    assert db.job(r["job_id"])["state"]=="queued"
    with db.connect() as c:
        b=budget_snapshot(c,p.id)
        assert b["demo"]["reserved"]==100000
    with pytest.raises(StudioError,match="创作包"):cmd(s,p.id,"suggest_route")


def test_parallel_budget_reservations(studio):
    db,s,_=studio;p=s.create_project("预算")
    def reserve(index):
        try:
            with db.transaction() as c:
                return reserve_job(c,db,p,key=str(index),request_hash=str(index),kind="image",target_id=str(index),input_hash=str(index),payload={},amount=9_000_000,phase="demo")["id"]
        except StudioError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(reserve,range(8)))
    assert len([r for r in result if r])==2
    with db.connect() as c:assert budget_snapshot(c,p.id)["demo"]["reserved"]==18_000_000


def test_worker_lease_does_not_double_claim(studio):
    db,s,_=studio;p=s.create_project("租约")
    with db.transaction() as c:reserve_job(c,db,p,key="k",request_hash="k",kind="render",target_id=None,input_hash="x",payload={})
    with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(lambda i:db.claim(str(i)),range(5)))
    assert len([r for r in results if r])==1


def test_crash_in_submit_becomes_unknown(studio):
    db,s,_=studio;p=s.create_project("未知提交")
    with db.transaction() as c:
        j=reserve_job(c,db,p,key="k",request_hash="k",kind="image",target_id=None,input_hash="x",payload={},amount=1_000_000,phase="demo")
        c.execute("UPDATE jobs SET state='submitting',lease_until=? WHERE id=?",(time.time()-1,j["id"]))
    assert db.claim("new") is None
    assert db.job(j["id"])["state"]=="unknown"
    with db.connect() as c:assert budget_snapshot(c,p.id)["demo"]["reserved"]==1_000_000


def test_image_asset_dedup_and_path(studio):
    db,_,_=studio;a=Assets(db)
    first=a.ingest(png(),"a.png");second=a.ingest(png(),"b.png")
    assert first["id"]==second["id"]
    assert a.path(first["id"]).is_relative_to(db.root/"assets")


def test_frame_change_keeps_unrelated_approval(studio):
    db,s,_=studio;p=prepared(studio)
    keep=p.shots[1].anchors[0].approved_hash
    cmd(s,p.id,"update_anchor",anchor_id=p.shots[0].anchors[0].id,prompt="改变光线")
    p=db.get_project(p.id)
    assert p.shots[1].anchors[0].approved_hash==keep
    with pytest.raises(StudioError,match="未选定|已变化"):cmd(s,p.id,"approve_creative")


def test_unselected_candidate_keeps_creative_approval(studio):
    db,s,_=studio;p=prepared(studio)
    cmd(s,p.id,"approve_creative");before=db.get_project(p.id).creative_approved_hash
    cmd(s,p.id,"candidate_from_asset",anchor_id=p.shots[0].anchors[0].id,asset_id=p.asset_ids[0])
    assert db.get_project(p.id).creative_approved_hash==before


def test_unpriced_model_cannot_spend(studio):
    db,s,_=studio;p=prepared(studio)
    with db.transaction() as c:
        settings=db.settings(c);settings.models[7].price_confirmed=False;db.save_settings(settings,c)
    with pytest.raises(StudioError,match="价格"):cmd(s,p.id,"generate_image",anchor_id=p.shots[0].anchors[0].id)


def test_cognition_routes_visual_input_to_primary_vision(studio):
    from studio.catalog import choose_cognitive_model
    db,s,_=studio;p=prepared(studio);settings=db.settings()
    assert choose_cognitive_model(settings,p,'director',vision=False)=='glm'
    assert choose_cognitive_model(settings,p,'director',vision=True)=='k3'
    with pytest.raises(StudioError):choose_cognitive_model(settings,p,'director',vision=True,explicit='glm')


def test_price_or_credential_change_does_not_invalidate_pixels(studio):
    from studio.catalog import deployment_hash,generation_hash
    db,_,_=studio;settings=db.settings();m=next(m for m in settings.models if m.id=='seedance-standard');c=next(c for c in settings.connections if c.id==m.connection_id)
    old_quote=deployment_hash(m,c);old_pixels=generation_hash(m,c)
    m.price_cny=Decimal('0.25');c.credential_version+=1
    assert deployment_hash(m,c)!=old_quote
    assert generation_hash(m,c)==old_pixels
    m.params={'seed':42}
    assert generation_hash(m,c)!=old_pixels


def test_complex_shot_cannot_silently_become_static(studio):
    db,s,_=studio;p=prepared(studio)
    shot=p.shots[0]
    cmd(s,p.id,'update_shot',shot_id=shot.id,difficulty='complex')
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route',resolution='720')
    p=db.get_project(p.id);route=p.route.model_dump(mode='json');route['items'][0]['method']='local'
    with pytest.raises(StudioError,match='不能静默'):cmd(s,p.id,'update_route',route=route)


def test_settings_revision_and_secret_not_returned(tmp_path):
    with TestClient(create_app(tmp_path,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        settings=client.get('/api/settings').json()
        assert client.put('/api/settings',json=settings).status_code==200
        assert client.put('/api/settings',json=settings).status_code==409
        conn=next(c for c in settings['connections'] if c['id']=='ark')
        bad=client.put('/api/connections/ark/key',json={'key':'fixture-secret','expected_url':'https://wrong.example'})
        assert bad.status_code==409
        good=client.put('/api/connections/ark/key',json={'key':'fixture-secret','expected_url':conn['base_url']})
        assert good.status_code==200
        result=client.get('/api/settings')
        assert 'fixture-secret' not in result.text
        saved=next(c for c in result.json()['connections'] if c['id']=='ark')
        assert saved['has_key'] and saved['credential_version']==1


def test_model_kind_and_credential_fields_rejected():
    from studio.models import ModelProfile
    from pydantic import ValidationError
    with pytest.raises(ValidationError):ModelProfile(name='wrong',api_model='x',connection_id='c',kind='video',adapter='chat')
    with pytest.raises(ValidationError):ModelProfile(name='secret',api_model='x',connection_id='c',kind='text',adapter='chat',params={'api_key':'fixture-secret'})


@pytest.mark.asyncio
async def test_image_http_contract_mocktransport_and_late_candidate(studio):
    db,s,vault=studio;p=prepared(studio)
    async def handler(request):
        assert request.url.path.endswith('/images/generations')
        body=__import__('json').loads(request.content)
        assert body['sequential_image_generation']=='disabled'
        return httpx.Response(200,json={"data":[{"b64_json":__import__('base64').b64encode(png()).decode()}]})
    adapters=Adapters(Assets(db),vault,transport=httpx.MockTransport(handler))
    r=cmd(s,p.id,"generate_image",anchor_id=p.shots[0].anchors[0].id)
    cmd(s,p.id,"update_anchor",anchor_id=p.shots[0].anchors[0].id,prompt="新版本")
    worker=Worker(db,vault,adapters);job=db.claim(worker.owner)
    await worker.run_job(job)
    assert db.job(r['job_id'])['state']=='superseded'
    assert len(db.get_project(p.id).shots[0].anchors[0].candidates)==2


@pytest.mark.asyncio
async def test_paid_timeout_preserves_reservation(studio):
    db,s,vault=studio;p=prepared(studio)
    async def handler(request):raise httpx.ReadTimeout('timeout')
    worker=Worker(db,vault,Adapters(Assets(db),vault,transport=httpx.MockTransport(handler)))
    r=cmd(s,p.id,"generate_image",anchor_id=p.shots[0].anchors[0].id)
    await worker.run_job(db.claim(worker.owner))
    assert db.job(r['job_id'])['state']=='unknown'
    with db.connect() as c:assert budget_snapshot(c,p.id)['demo']['reserved']>0


def test_local_api_session_and_csrf(tmp_path):
    with TestClient(create_app(tmp_path,testing=True,serve_frontend=False)) as client:
        assert client.get('/api/settings').status_code==401
        boot=client.get('/api/bootstrap').json()
        assert client.post('/api/projects',json={'name':'作品'}).status_code==403
        assert client.post('/api/projects',json={'name':'作品'},headers={'x-studio-csrf':boot['csrf']}).status_code==200
        assert client.get('/api/settings',headers={'Origin':'https://evil.example'}).status_code==403


def test_codex_strict_schema_requires_nested_ids():
    from studio.adapters import strict_schema
    from studio.cognition import ScriptDraft, ShotDraft, RefinedShot
    for model in [ScriptDraft,ShotDraft,RefinedShot]:
        schema=strict_schema(model.model_json_schema())
        def check(node):
            if isinstance(node,dict):
                if node.get('type')=='object' and 'properties' in node:
                    assert set(node['required'])==set(node['properties'])
                    assert node['additionalProperties'] is False
                assert 'default' not in node
                for value in node.values():check(value)
            elif isinstance(node,list):
                for value in node:check(value)
        check(schema)


@pytest.mark.asyncio
async def test_local_picture_audio_subtitle_export(studio):
    db,s,vault=studio;p=prepared(studio)
    cmd(s,p.id,"approve_creative");cmd(s,p.id,"suggest_route",resolution='480');cmd(s,p.id,"approve_route")
    worker=Worker(db,vault)
    for shot in db.get_project(p.id).shots:
        r=cmd(s,p.id,"generate_shot",shot_id=shot.id)
        await worker.run_job(db.claim(worker.owner))
        assert db.job(r['job_id'])['state']=='succeeded', db.job(r['job_id'])['error']
    buf=io.BytesIO()
    with wave.open(buf,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x00\x00'*48000)
    audio=Assets(db).ingest(buf.getvalue(),'测试音轨.wav','audio/wav')
    cmd(s,p.id,'attach_asset',asset_id=audio['id'])
    cmd(s,p.id,'update_audio',music_asset_id=audio['id'],narration_asset_id=audio['id'],duck_music=True,effects=[{'asset_id':audio['id'],'start':1,'duration':1,'gain':0.1}],subtitles=[{'text':'中文测试字幕','start':0,'duration':2,'shot_ids':[]}])
    r=cmd(s,p.id,'render')
    await worker.run_job(db.claim(worker.owner))
    job=db.job(r['job_id']);assert job['state']=='succeeded',job['error']
    p=db.get_project(p.id);meta=db.asset(p.preview_asset_id)['metadata']
    assert abs(meta['duration']-3)<.25 and meta['has_audio']
    cmd(s,p.id,'approve_final')
    assert db.get_project(p.id).final_approved_hash is not None


def test_archive_roundtrip_preserves_assets_and_clears_approvals(studio,tmp_path):
    db,s,_=studio;p=prepared(studio)
    cmd(s,p.id,'approve_creative')
    with TestClient(create_app(db.root,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        package=client.get('/api/projects/'+p.id+'/archive')
        assert package.status_code==200
    target=tmp_path/'restored'
    with TestClient(create_app(target,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        response=client.post('/api/import-archive',files={'file':('project.zip',package.content,'application/zip')})
        assert response.status_code==200,response.text
        restored=response.json()
        assert restored['id']!=p.id and restored['creative_approved_hash'] is None
        assert len(restored['blocks'])==len(p.blocks) and len(restored['shots'])==len(p.shots)
        assert restored['shots'][0]['anchors'][0]['candidates'][0]['asset_hash']
        assert not restored['_computed']['frames'][restored['shots'][0]['anchors'][0]['id']]


def test_archive_rejects_path_traversal(tmp_path):
    import zipfile
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../private.txt','not allowed')
    with TestClient(create_app(tmp_path,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        response=client.post('/api/import-archive',files={'file':('bad.zip',b.getvalue(),'application/zip')})
        assert response.status_code==400


def test_route_rejects_silently_dropped_keyframes(studio):
    db,s,_=studio;p=prepared(studio)
    cmd(s,p.id,'update_shot',shot_id=p.shots[0].id,difficulty='simple')
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route')
    route=db.get_project(p.id).route.model_dump(mode='json')
    item=route['items'][0];item['anchor_usage'][p.shots[0].anchors[0].id]='reference'
    with pytest.raises(StudioError,match='尚未|只接入'):cmd(s,p.id,'update_route',route=route)
    item['anchor_usage']={'nonexistent':'first'}
    with pytest.raises(StudioError,match='其他镜头'):cmd(s,p.id,'update_route',route=route)


@pytest.mark.asyncio
async def test_poll_timeout_after_first_submit_keeps_remote_id_and_funds(studio):
    db,s,vault=studio;p=prepared(studio)
    cmd(s,p.id,'update_shot',shot_id=p.shots[0].id,difficulty='simple')
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route');cmd(s,p.id,'approve_route')
    posts=[]
    async def handler(request):
        if request.method=='POST':
            posts.append(request);return httpx.Response(200,json={'id':'remote-created'})
        raise httpx.ReadTimeout('poll unavailable')
    r=cmd(s,p.id,'generate_shot',shot_id=p.shots[0].id)
    worker=Worker(db,vault,Adapters(Assets(db),vault,transport=httpx.MockTransport(handler)))
    await worker.run_job(db.claim(worker.owner))
    job=db.job(r['job_id'])
    assert len(posts)==1 and job['external_id']=='remote-created' and job['state']=='unknown'
    with db.connect() as c:assert budget_snapshot(c,p.id)['media']['reserved']>0


@pytest.mark.asyncio
async def test_cancelled_claim_never_creates_local_output(studio):
    db,s,vault=studio;p=prepared(studio)
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route');cmd(s,p.id,'approve_route')
    r=cmd(s,p.id,'generate_shot',shot_id=p.shots[0].id)
    worker=Worker(db,vault);claimed=db.claim(worker.owner)
    with TestClient(create_app(db.root,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        assert client.post('/api/jobs/'+r['job_id']+'/cancel').status_code==200
    await worker.run_job(claimed)
    assert db.job(r['job_id'])['state']=='cancelled'
    assert db.get_project(p.id).shots[0].clip_asset_id is None


def test_cancel_requested_remote_task_is_recoverable_and_not_overwritten(studio):
    db,s,_=studio;p=s.create_project('取消恢复')
    with db.transaction() as c:
        job=reserve_job(c,db,p,key='cancel',request_hash='cancel',kind='generate_shot',target_id=None,input_hash='x',payload={},amount=1_000_000)
        c.execute("UPDATE jobs SET state='cancel_requested',external_id='remote',lease_until=0 WHERE id=?",(job['id'],))
    claimed=db.claim('worker')
    assert claimed['id']==job['id']
    db.set_job_state(job['id'],'running')
    assert db.job(job['id'])['state']=='cancel_requested'


def test_foreign_currency_requires_explicit_conversion():
    from studio.models import ModelProfile
    from pydantic import ValidationError
    args=dict(name='image',api_model='id',connection_id='c',kind='image',adapter='openai_image',price_currency='USD',price_native='0.1',fx_rate='7.2',price_confirmed=True)
    with pytest.raises(ValidationError):ModelProfile(**args)
    model=ModelProfile(**args,fx_date='2026-09-09')
    assert model.price_cny==Decimal('0.72')


def test_reconciled_success_preserves_artifact_and_records_audit(studio):
    from studio.database import settle
    db,s,_=studio;p=s.create_project('账单复核')
    with db.transaction() as c:
        job=reserve_job(c,db,p,key='bill',request_hash='bill',kind='generate_image',target_id=None,input_hash='x',payload={},amount=1_000_000)
        settle(c,db,job['id'],1_000_000,'ceiling_estimate')
        c.execute("UPDATE jobs SET state='succeeded',result=? WHERE id=?",('{"asset_id":"kept"}',job['id']))
    with TestClient(create_app(db.root,testing=True,serve_frontend=False)) as client:
        boot=client.get('/api/bootstrap').json();client.headers['x-studio-csrf']=boot['csrf']
        r=client.post('/api/jobs/'+job['id']+'/reconcile',json={'explicit_confirmation':True,'actual_micros':700000})
        assert r.status_code==200,r.text
    assert db.job(job['id'])['state']=='succeeded' and db.job(job['id'])['result']['asset_id']=='kept'
    with db.connect() as c:
        assert budget_snapshot(c,p.id)['media']['spent']==700000
        assert c.execute("SELECT COUNT(*) FROM events WHERE type='billing_adjusted'").fetchone()[0]==1


def test_model_defaults_keep_same_approval_hash_after_json_roundtrip():
    from studio.models import ModelProfile,Connection
    from studio.catalog import deployment_hash
    settings=preset_catalog()
    for model in settings.models:
        conn=next(c for c in settings.connections if c.id==model.connection_id)
        restored_model=ModelProfile.model_validate_json(model.model_dump_json())
        restored_connection=Connection.model_validate_json(conn.model_dump_json())
        assert deployment_hash(model,conn)==deployment_hash(restored_model,restored_connection),model.id


def test_file_vault_remains_readable_when_keychain_later_available(tmp_path,monkeypatch):
    import keyring
    db=Database(tmp_path);vault=Vault(db,use_keychain=False);vault.put('fixture','fixture-only-key')
    def forbidden(*args):raise AssertionError('must not switch storage mechanism')
    monkeypatch.setattr(keyring,'get_password',forbidden)
    later=Vault(db,use_keychain=True)
    assert later.mode=='encrypted_file' and later.get('fixture')=='fixture-only-key'


def test_missing_vault_key_is_not_silently_replaced(tmp_path):
    db=Database(tmp_path);vault=Vault(db,use_keychain=False);vault.put('fixture','fixture-only-key')
    (db.root/'.vault-key').unlink()
    with pytest.raises(StudioError,match='原凭据主密钥'):Vault(db,use_keychain=False)
    assert not (db.root/'.vault-key').exists()


def test_locked_keychain_does_not_fallback_to_a_different_key(tmp_path,monkeypatch):
    import keyring
    from cryptography.fernet import Fernet
    key=Fernet.generate_key().decode()
    monkeypatch.setattr(keyring,'get_password',lambda *args:key)
    db=Database(tmp_path);vault=Vault(db);vault.put('fixture','fixture-only-key')
    def locked(*args):raise RuntimeError('locked')
    monkeypatch.setattr(keyring,'get_password',locked)
    with pytest.raises(StudioError,match='解锁'):Vault(db)
    assert not (db.root/'.vault-key').exists()


@pytest.mark.asyncio
async def test_minimax_image_is_real_adapter_with_single_candidate(studio):
    from studio.models import ModelProfile
    db,s,vault=studio
    model=ModelProfile(id='minimax-image',name='MiniMax',api_model='image-01',connection_id='minimax',kind='image',adapter='minimax_image',enabled=True,price_confirmed=True,price_cny='.025',price_unit='image',max_reference_images=0)
    with db.transaction() as c:
        settings=db.settings(c);settings.models=[m for m in settings.models if m.id!=model.id]+[model];db.save_settings(settings,c)
    p=prepared(studio)
    async def handler(request):
        body=__import__('json').loads(request.content)
        assert request.url.path.endswith('/image_generation')
        assert body['n']==1 and body['response_format']=='base64'
        return httpx.Response(200,json={'data':{'image_base64':[__import__('base64').b64encode(png()).decode()]},'base_resp':{'status_code':0},'metadata':{'success_count':1}})
    worker=Worker(db,vault,Adapters(Assets(db),vault,transport=httpx.MockTransport(handler)))
    result=cmd(s,p.id,'generate_image',anchor_id=p.shots[0].anchors[0].id,model_id=model.id)
    await worker.run_job(db.claim(worker.owner))
    assert db.job(result['job_id'])['state']=='succeeded'
    assert db.get_project(p.id).shots[0].anchors[0].candidates[-1].model_id==model.id


def test_minimax_business_rejection_is_not_success_or_a_bill(studio):
    db,_,vault=studio;adapter=Adapters(Assets(db),vault)
    with pytest.raises(StudioError) as exc:adapter.minimax_response({'base_resp':{'status_code':1008}})
    assert exc.value.definitely_unbilled and '余额' in str(exc.value)


@pytest.mark.asyncio
async def test_failed_plan_keeps_raw_draft_and_can_redesign_without_writer(studio):
    from studio.adapters import TextResult
    from studio.models import ScriptBlock
    db,s,vault=studio;p=s.create_project('规划恢复')
    cmd(s,p.id,'update_brief',target_duration=3)
    cmd(s,p.id,'update_proposal',text='一个叙事段落，三秒商品定版')
    cmd(s,p.id,'approve_proposal');cmd(s,p.id,'set_budget',cognitive_limit=1_000_000,explicit_authorization=True)
    calls=[]
    class Fake(Adapters):
        async def text(self,model,conn,prompt,schema,**kwargs):
            calls.append(model.id)
            if len(calls)==1:data={'blocks':[{'title':'正文','text':'今天从容开始。','purpose':'开场'}]}
            else:
                data={'shots':[{'block_index':0,'title':'镜头','duration':3,'visual':'商品原图','motion':'固定','difficulty':'static','anchors':[{'role':'action' if len(calls)==2 else 'start','at_seconds':99 if len(calls)==2 else 9,'prompt':'原图','reference_asset_ids':[]}]}],'narration':[],'subtitles':[]}
            return TextResult(data,{'input_tokens':1000,'output_tokens':100},'')
    worker=Worker(db,vault,Fake(Assets(db),vault))
    first=cmd(s,p.id,'plan_content')['job_id'];await worker.run_job(db.claim(worker.owner))
    failed=db.job(first);assert failed['state']=='failed'
    assert set(failed['result']['drafts'])=={'writer','shot_designer'} and len(failed['result']['usage_records'])==2
    cmd(s,p.id,'recover_script',job_id=first)
    assert db.get_project(p.id).blocks[0].text=='今天从容开始。'
    second=cmd(s,p.id,'plan_content',reuse_script=True)['job_id'];await worker.run_job(db.claim(worker.owner))
    result=db.job(second)
    assert result['state']=='succeeded',result['error']
    assert calls==['glm','k3','k3']
    assert result['result']['shots'][0]['anchors'][0]['at_seconds']==0
    assert result['result']['normalization_notes']


def test_local_motion_changes_only_local_pixels(studio):
    from studio.catalog import clip_hash
    db,s,_=studio;p=prepared(studio)
    cmd(s,p.id,'approve_creative');cmd(s,p.id,'suggest_route')
    p=db.get_project(p.id);a,b=p.route.items
    before_a=clip_hash(p,a.shot_id,a);before_b=clip_hash(p,b.shot_id,b)
    a.local_motion='push_in'
    assert clip_hash(p,a.shot_id,a)!=before_a
    assert clip_hash(p,b.shot_id,b)==before_b


def test_local_crop_keeps_source_and_creates_zero_cost_candidate(studio):
    db,s,_=studio;p=prepared(studio);source=p.asset_ids[0];asset=db.asset(source)
    r=cmd(s,p.id,'crop_candidate',anchor_id=p.shots[0].anchors[0].id,asset_id=source,crop={'x':.25,'y':.25,'width':.5,'height':.5})
    derived=db.asset(r['asset_id'])
    assert derived['metadata']['width']==160 and derived['metadata']['height']==120
    assert derived['metadata']['source_asset_id']==source
    assert db.asset(source)['hash']==asset['hash']
    with db.connect() as c:assert budget_snapshot(c,p.id)['media']=={'spent':0,'reserved':0}
    with pytest.raises(StudioError):cmd(s,p.id,'crop_candidate',anchor_id=p.shots[0].anchors[0].id,asset_id=source,crop={'x':.7,'y':0,'width':.5,'height':1})

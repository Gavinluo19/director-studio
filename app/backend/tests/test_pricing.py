from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from studio.api import create_app
from studio.catalog import preset_catalog, choose_cognitive_model, suggest_route, deployment_hash, generation_hash
from studio.configuration import guide,upgrade_presets
from studio.database import Database
from studio.models import Project,ScriptBlock,Shot,StudioError
from studio.pricing import PriceBook,auto_estimate,effective_rates,quote_view,token_cost,parsed_prices,usage_cost

@pytest.fixture
def configured(tmp_path):
    db=Database(tmp_path);book=PriceBook(db);settings=book.bind(preset_catalog())
    for c in settings.connections:c.status='configured'
    for m in settings.models:m.enabled=True
    return db,book,settings


def test_exact_flash_and_fast_prices_do_not_match_parent_models(configured):
    _,_,s=configured
    flash=next(m for m in s.models if m.id=='glm-flash')
    fast=next(m for m in s.models if m.id=='minimax-video')
    assert flash.pricing.key=='zhipu:glm-5.3-flash'
    assert flash.pricing.rates['input']==Decimal('.8')
    assert fast.pricing.key=='minimax:MiniMax-Hailuo-2.3-Fast'
    assert auto_estimate(fast,duration=6,resolution='720')==1_350_000
    assert auto_estimate(fast,duration=6,resolution='1080')==2_310_000
    with pytest.raises(StudioError):auto_estimate(fast,duration=10,resolution='1080')


def test_flash_discount_expires_automatically(configured):
    _,_,s=configured;q=next(m for m in s.models if m.id=='glm-flash').pricing
    before=datetime(2026,9,9,15,59,tzinfo=timezone.utc)
    after=datetime(2026,9,9,16,0,tzinfo=timezone.utc)
    assert effective_rates(q,before)['input']==Decimal('.4')
    assert effective_rates(q,after)['input']==Decimal('.8')
    assert token_cost(q,10000,2000,at=before)==6800
    assert token_cost(q,10000,2000,at=after)==13600


def test_codex_equivalent_counts_tokens_without_cash_debit(configured):
    _,_,s=configured;m=next(m for m in s.models if m.id=='codex:gpt-6-astra')
    usage={'billing':'codex_subscription','token_usage':{'last':{'input_tokens':10000,'cached_input_tokens':2000,'output_tokens':2000}}}
    expected=token_cost(m.pricing,10000,2000,2000)
    assert usage_cost(m,usage)==expected>0
    from studio.catalog import estimate
    assert estimate(m)==0
    assert usage_cost(m,{'billing':'codex_subscription'}) is None


def test_ark_image_counts_resolution_and_reference_surcharge(configured):
    _,_,s=configured;m=next(m for m in s.models if m.id=='seedream')
    assert auto_estimate(m,references=4)==660000
    m.params['size']='1536x1024'
    assert auto_estimate(m,references=1)==300000


def test_quote_refresh_metadata_does_not_invalidate_approval(configured):
    _,_,s=configured;m=next(m for m in s.models if m.id=='glm');c=next(c for c in s.connections if c.id==m.connection_id)
    original=deployment_hash(m,c);pixels=generation_hash(m,c)
    m.pricing.fetched_at='2026-09-10T00:00:00Z';m.pricing.source_url+='?ref=refresh'
    assert deployment_hash(m,c)==original
    m.pricing.rates['input']=Decimal('9')
    assert deployment_hash(m,c)!=original and generation_hash(m,c)==pixels


def test_cross_origin_cognitive_and_video_routing(configured):
    _,_,s=configured;p=Project(region='cn')
    for m in s.models:m.enabled=m.id in {'codex:gpt-5.6-sol','runway-quality'}
    assert choose_cognitive_model(s,p,'director',vision=True)=='codex:gpt-5.6-sol'
    block=ScriptBlock(text='test');p.blocks=[block];p.shots=[Shot(block_id=block.id,difficulty='complex',duration=5)]
    route,_=suggest_route(p,s,'quality','720')
    assert route.items[0].model_id=='runway-quality'


def test_guide_has_recommendations_and_explicit_requirements(configured):
    _,book,s=configured;g=guide(s,book.read())
    assert g['required_total']==4
    assert {r['requirement'] for r in g['roles']}=={'required','optional','conditional'}
    for r in g['roles']:
        assert r['recommended_ids'] and r['reason']
    assert next(r for r in g['roles'] if r['role']=='director')['option_ids'].__contains__('codex:gpt-6-astra')
    assert not g['prices']['qwen-custom']['known']


def test_refresh_parser_rejects_empty_or_changed_public_page(configured):
    _,book,_=configured;q=[p for p in book.read()['prices'] if p['provider']=='zhipu']
    with pytest.raises(ValueError):parsed_prices('zhipu','<html><body>loading</body></html>',q)


def test_official_price_binds_on_server_and_credentials_survive(tmp_path):
    # Production initialization applies the local verified pricebook without network calls.
    with TestClient(create_app(tmp_path,testing=True,serve_frontend=False)) as c:
        b=c.get('/api/bootstrap').json();c.headers['x-studio-csrf']=b['csrf']
        db=c.app.state.db;book=PriceBook(db)
        with db.transaction() as conn:
            s=book.bind(upgrade_presets(db.settings(conn)));db.save_settings(s,conn)
        g=c.get('/api/configuration-guide').json()
        assert g['prices']['glm']['rates_cny']['input']=='8'
        assert g['prices']['glm-flash']['rates_cny']['input'] in {'.4','0.4','0.8'}


def test_custom_quote_not_labeled_as_official_or_subscription(configured):
    _,_,s=configured;m=next(m for m in s.models if m.id=='glm')
    m.price_mode='manual';m.price_cny=Decimal('1.2');m.price_unit='call';m.price_confirmed=True
    view=quote_view(m)
    assert view['billing']=='manual' and view['sample_micros']==1_200_000
    assert not view.get('source_url')


@pytest.mark.asyncio
async def test_local_text_budget_rejection_does_not_book_a_charge(configured):
    from studio.models import Command
    from studio.service import StudioService
    from studio.worker import Worker
    from studio.vault import Vault
    from studio.database import budget_snapshot
    db,_,s=configured
    model=next(m for m in s.models if m.id=='glm');model.max_input_tokens=1024
    s.defaults.director='glm'
    with db.transaction() as c:db.save_settings(s,c)
    service=StudioService(db);p=service.create_project('输入检查')
    def command(kind,**payload):
        current=db.get_project(p.id)
        return service.command(p.id,Command(type=kind,expected_revision=current.revision,payload=payload))
    command('set_budget',explicit_authorization=True,cognitive_limit=1_000_000)
    result=command('director',message='说明一下这个计划')
    worker=Worker(db,Vault(db,use_keychain=False));await worker.run_job(db.claim(worker.owner))
    job=db.job(result['job_id']);assert job['state']=='failed' and '预算' in job['error']
    with db.connect() as c:
        b=budget_snapshot(c,p.id);assert b['cognitive']['spent']==0 and b['cognitive']['reserved']==0

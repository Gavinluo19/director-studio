"""Official public price snapshots, bounded fetchers, and transparent CNY estimates.
No credentials or project content are sent when refreshing prices.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from .models import ModelProfile, PriceSnapshot, Settings, StudioError

BUNDLE = Path(__file__).with_name('data')/'prices.json'
SOURCES = {
    'zhipu': 'https://docs.bigmodel.cn/cn/guide/start/pricing.md',
    'kimi': 'https://platform.kimi.com/docs/pricing/chat-k3.md',
    'openai': 'https://developers.openai.com/api/docs/pricing.md',
    'deepseek': 'https://api-docs.deepseek.com/quick_start/pricing/',
    'minimax': 'https://platform.minimaxi.com/docs/guides/pricing-paygo.md',
    'runway': 'https://docs.dev.runwayml.com/guides/pricing/',
    'eleven': 'https://elevenlabs.io/pricing/api',
    'ark': 'https://docs.volcengine.com/docs/82379/1544106?lang=zh',
}
FX_URL = 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
HOSTS = {
    'open.bigmodel.cn':'zhipu','api.moonshot.cn':'kimi','api.moonshot.ai':'kimi',
    'api.deepseek.com':'deepseek','api.openai.com':'openai',
    'ark.cn-beijing.volces.com':'ark','api.minimaxi.com':'minimax',
    'api.minimax.io':'minimax','api.dev.runwayml.com':'runway','api.elevenlabs.io':'eleven',
}

def utcnow(): return datetime.now(timezone.utc)
def stamp(): return utcnow().isoformat()
def num(s):
    match=re.search(r'\d+(?:\.\d+)?',s.replace(',',''))
    if not match:raise ValueError('missing price number')
    return str(Decimal(match.group()))

class TextTableParser(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style'}:self.skip+=1
        if not self.skip and tag in {'tr','p','h1','h2','h3','li'}:self.parts.append('\n')
        if not self.skip and tag in {'td','th'}:self.parts.append(' | ')
    def handle_endtag(self,tag):
        if tag in {'script','style'}:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)

def plain(text):
    if '<html' not in text.lower():return text
    parser=TextTableParser();parser.feed(text);return ''.join(parser.parts)

def row(text,name):
    for line in text.splitlines():
        cells=[re.sub(r'<[^>]*>','',x).strip(' `*\u200b') for x in line.split('|') if x.strip()]
        if cells and (cells[0].lower()==name.lower() or cells[0].lower().startswith(name.lower()+' (')):return cells
    raise ValueError('official model row missing: '+name)

def parse_fx(text):
    root=ElementTree.fromstring(text)
    rates={e.get('currency'):Decimal(e.get('rate')) for e in root.iter() if e.get('currency')}
    day=next(e.get('time') for e in root.iter() if e.get('time'))
    rate=rates['CNY']/rates['USD']
    if not Decimal('1')<rate<Decimal('20'):raise ValueError('unexpected FX rate')
    return {'rate':str(rate),'date':day,'source':FX_URL,'fetched_at':stamp()}

def parsed_prices(provider,text,existing):
    """Fail closed on unrecognized structure, rather than relabeling stale data fresh."""
    out=[];text=plain(text)
    for original in existing:
        q=copy.deepcopy(original);name=q['model'];rates=dict(q['rates']);found=False
        if provider=='openai' and q['unit']=='tokens':
            cells=row(text.split('Batch')[0],name)
            if len(cells)>=9:
                rates={'input':num(cells[1]),'cached':num(cells[2]),'output':num(cells[4])}
                if cells[3]!='-':rates['write']=num(cells[3])
                if cells[5]!='-':q['long_rates']={'input':num(cells[5]),'cached':num(cells[6]),'output':num(cells[8])}
                found=True
        elif provider=='openai' and q['unit'] in {'image_tokens','tts_tokens'}:
            # Same model has one row for each modality. Restrict to Standard sections.
            candidates=[l for l in text.splitlines() if l.strip().startswith('| '+name+' |')]
            for line in candidates[:2]:
                cells=[x.strip() for x in line.strip('|').split('|')]
                if cells[1]=='Text':rates['input']=num(cells[2]);found=True
                if cells[1]=='Image':rates.update(image_input=num(cells[2]),image_cached=num(cells[3]),output=num(cells[4]));found=True
                if cells[1]=='Audio':rates['output']=num(cells[4]);found=True
        elif provider=='zhipu':
            cells=row(text,name);q['promo_rates']={};q['promo_until']=''
            rates={}
            for key,index in [('input',2),('output',3),('cached',5)]:
                numbers=re.findall(r'\d+(?:\.\d+)?',cells[index])
                rates[key]=str(max(map(Decimal,numbers)))
                if len(numbers)>1:q['promo_rates'][key]=numbers[0]
            if q['promo_rates']:
                date=re.search(r'活动截止\s*(\d{4})\s*年\s*(\d+)\s*月\s*(\d+)\s*日\s*24:00',text)
                if not date:raise ValueError('promotion expiry missing')
                from datetime import timedelta
                day=datetime(*map(int,date.groups()),tzinfo=timezone(timedelta(hours=8)))+timedelta(days=1)
                q['promo_until']=day.isoformat()
            found=True
        elif provider=='kimi':
            match=re.search(r'\["kimi-k3",\s*"1M tokens",\s*"¥([\d.]+)",\s*"¥([\d.]+)",\s*"¥([\d.]+)"',text)
            if match:rates={'cached':match[1],'input':match[2],'output':match[3]};found=True
        elif provider=='deepseek':
            # DeepSeek uses a horizontal model matrix. Validate all three numeric columns.
            peak=[re.findall(r'\$([\d.]+)',l) for l in text.splitlines() if 'PEAK' in l and 'OFF-PEAK' not in l]
            off=[re.findall(r'\$([\d.]+)',l) for l in text.splitlines() if 'OFF-PEAK' in l and '$' in l]
            index=1 if name=='deepseek-v4-pro' else 2 if 'vision' in name else 0
            if len(peak)==3 and len(off)==3 and all(len(x)>=3 for x in peak+off):
                rates={k:peak[i][index] for i,k in enumerate(['cached','input','output'])}
                rates.update({k+'_offpeak':off[i][index] for i,k in enumerate(['cached','input','output'])});found=True
        elif provider=='runway':
            cells=row(text,name);match=re.search(r'(\d+(?:\.\d+)?) credits per second',cells[1])
            if match and '$0.01 per credit' in text:rates={'per_second':str(Decimal(match[1])*Decimal('.01'))};found=True
        elif provider=='minimax' and q['unit']=='image':
            line=next((line for line in text.splitlines() if 'image-01' in line and '|' in line),None)
            if line:rates={'per_image':num(line.split('|')[-2])};found=True
        elif provider=='minimax' and q['unit']=='1000_characters':
            lines=[l for l in text.splitlines() if name in l and 'T2A ' in l]
            if lines:
                # The speech table is CNY per ten thousand characters.
                cells=[x.strip() for x in lines[0].strip('| ').split('|')]
                rates={'per_1000':str(Decimal(num(cells[-1]))/10)};found=True
        elif provider=='minimax' and q['unit']=='video_clip':
            lines=[l for l in text.splitlines() if name in l and re.search(r'(768|1080)P',l)]
            updated={}
            for l in lines:
                m=re.search(r'(768|1080)P\s*(\d+)s',l)
                if m:updated[m[1]+'_'+m[2]]=num(l.split('|')[-2])
            if updated:rates=updated;found=True
        elif provider=='eleven':
            m=re.search(r'Eleven Music\s*\$([\d.]+)\s*per minute',text)
            if m:rates={'per_second':str(Decimal(m[1])/60)};found=True
        elif provider=='ark':
            # The public page may be a JS shell. Never treat an empty HTML response as a price update.
            raise ValueError('官网动态正文未返回，保留最近一次官方核价快照')
        if not found:raise ValueError('official pricing layout was not recognized for '+name)
        q['rates']=rates;q['fetched_at']=stamp();PriceSnapshot.model_validate(q);out.append(q)
    return out

class PriceBook:
    def __init__(self,db):self.db=db
    def read(self):
        with self.db.connect() as c:record=c.execute("SELECT value FROM meta WHERE key='price_book'").fetchone()
        bundled=json.loads(BUNDLE.read_text())
        if not record:return bundled
        current=json.loads(record[0]);known={p['key'] for p in current['prices']}
        current['prices'] += [p for p in bundled['prices'] if p['key'] not in known]
        return current
    def save(self,book,c):c.execute("INSERT INTO meta VALUES('price_book',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(book,ensure_ascii=False),))
    def bind(self,settings: Settings,book=None):
        book=book or self.read();fx=book['fx'];index={p['key']:p for p in book['prices']}
        for model in settings.models:
            if model.price_mode=='manual':continue
            conn=next((c for c in settings.connections if c.id==model.connection_id),None)
            provider='openai' if model.adapter=='codex' else HOSTS.get(urlparse(conn.base_url).hostname,'') if conn else ''
            # Family price binding is explicit, needed for account-specific Ark endpoint IDs.
            model_name=model.api_model
            family=None if provider+':'+model_name in index else next((p['model'] for p in sorted(book['prices'],key=lambda p:len(p['model']),reverse=True) if p['provider']==provider and model_name.startswith(p['model']+'-')),None)
            model_name=family or model_name
            if provider+':'+model_name not in index:model_name=model.pricing_model or model_name
            q=index.get(provider+':'+model_name)
            if not q:
                model.pricing=None
                # Preserve legacy, user-confirmed custom quotes; new auto models remain unpriced.
                if model.price_source.startswith('官网自动'):model.price_confirmed=False;model.price_cny=None
                continue
            q=copy.deepcopy(q)
            q.update(fx_rate=fx['rate'] if q['currency']=='USD' else '1',fx_date=fx['date'],fx_source=fx['source'])
            model.pricing=PriceSnapshot.model_validate(q);model.price_confirmed=True
            model.price_currency='CNY';model.price_native=None
            model.price_cny=Decimal(auto_estimate(model,duration=model.durations[0] if model.durations else 5,characters=1000))/1_000_000
            model.price_source='官网自动 · '+q['source_url'];model.fx_rate=Decimal(q['fx_rate']);model.fx_date=q['fx_date']
        return settings
    async def refresh(self):
        book=self.read();statuses=[];updates={}
        async def fetch(provider,url):
            try:
                async with httpx.AsyncClient(timeout=12,follow_redirects=False,headers={'Accept':'text/markdown,text/html,application/xml'}) as client:
                    async with client.stream('GET',url) as response:
                        response.raise_for_status();body=b''
                        async for piece in response.aiter_bytes():
                            body+=piece
                            if len(body)>3_000_000:raise ValueError('source too large')
                raw=body.decode('utf-8')
                if provider=='fx':updates['fx']=parse_fx(raw)
                else:updates[provider]=parsed_prices(provider,raw,[q for q in book['prices'] if q['provider']==provider])
                statuses.append({'provider':provider,'ok':True,'at':stamp()})
            except Exception as exc:
                statuses.append({'provider':provider,'ok':False,'at':stamp(),'message':'动态正文未返回，保留上次核价' if provider=='ark' else '未取得可验证的新价格，保留上次核价','error_type':type(exc).__name__})
        await asyncio.gather(*(fetch(k,v) for k,v in SOURCES.items()),fetch('fx',FX_URL))
        # Merge only price data into the newest settings, retaining concurrent key/config edits.
        with self.db.transaction() as c:
            newest=self.read()
            for provider,rows in updates.items():
                if provider=='fx':newest['fx']=rows
                else:newest['prices']=[q for q in newest['prices'] if q['provider']!=provider]+rows
            newest['refresh_status']=statuses;self.save(newest,c)
            settings=self.bind(self.db.settings(c),newest);self.db.save_settings(settings,c)
            self.db.event(c,None,'prices_refreshed',{'sources':statuses})
        return newest

def effective_rates(q,at=None,*,reserve=False):
    now=at or utcnow();rates=dict(q.rates)
    if q.promo_until and now<datetime.fromisoformat(q.promo_until):rates.update(q.promo_rates)
    if q.provider=='deepseek' and not reserve:
        t=now.astimezone(timezone.utc)
        if not(t.weekday()<5 and (1<=t.hour<4 or 6<=t.hour<10)):
            rates.update({k:rates[k+'_offpeak'] for k in ['input','cached','output'] if k+'_offpeak' in rates})
    return rates

def micros(value):return int((value*1_000_000).to_integral_value(rounding=ROUND_CEILING))

def token_cost(q,input_tokens,output_tokens,cached=0,writes=0,at=None,reserve=False):
    rates=effective_rates(q,at,reserve=reserve)
    if input_tokens>272000 and q.long_rates:rates.update(q.long_rates)
    cached=min(input_tokens,max(0,cached));writes=min(input_tokens-cached,max(0,writes))
    amount=(Decimal(input_tokens-cached-writes)*rates['input']+Decimal(cached)*rates.get('cached',rates['input'])+Decimal(writes)*rates.get('write',rates['input'])+Decimal(output_tokens)*rates['output'])/1_000_000
    return micros(amount*q.fx_rate)

def auto_estimate(model,*,duration=1,characters=0,count=1,resolution='720',aspect='9:16',references=0,input_tokens=None,output_tokens=None,at=None):
    q=model.pricing
    if q is None:raise StudioError('尚未匹配该型号的官方价格','price_required',409)
    r=effective_rates(q,at,reserve=True)
    if q.unit=='tokens':return token_cost(q,input_tokens or model.max_input_tokens,output_tokens if output_tokens is not None else model.max_output_tokens,reserve=True,at=at)
    if q.unit=='image':
        value=r.get('per_image',r.get('large_image',Decimal('0')))
        if 'large_image' in r:
            size=str(model.params.get('size','2K')).lower();pixels=math.prod(map(int,size.split('x'))) if 'x' in size else 4_194_304 if size in {'2k','4k','auto'} else 2_359_296
            value=r['large_image'] if pixels>2_610_000 else r['per_image']
        value=value*count+max(0,references-int(r.get('free_references',0)))*r.get('reference_image',Decimal(0))
    elif q.unit=='1000_characters':value=r['per_1000']*Decimal(characters)/1000
    elif q.unit=='second':value=r['per_second']*Decimal(str(duration))
    elif q.unit=='video_clip':
        native='768' if resolution=='720' else resolution
        key=native+'_'+str(int(duration))
        if key not in r:raise StudioError('该型号没有当前分辨率与时长的公开报价','price_spec_missing',409)
        value=r[key]
    elif q.unit=='video_tokens':
        rate=r.get(resolution)
        if rate is None:raise StudioError('该视频规格暂无官方报价','price_spec_missing',409)
        # Published token formula. Fixed ratio and no input video are enforced by the adapter.
        short=int(resolution);a,b=map(int,aspect.split(':'));pixels=Decimal(short*math.ceil(short*max(a,b)/min(a,b)/16)*16)
        value=rate*Decimal(str(duration))*pixels*24/1024/1_000_000
    elif q.unit=='tts_tokens':
        # Official token rates, conservative planning allocation; actual usage when returned.
        value=(Decimal(max(characters*3,1))*r['input']+Decimal(str(duration))*50*r['output'])/1_000_000
    elif q.unit=='image_tokens':
        # Allocation, not a published fixed per-image price. Never lower the user's quality.
        size=str(model.params.get('size','1024x1536'))
        pixels=math.prod(map(int,size.split('x'))) if 'x' in size else 8_294_400
        output_budget=Decimal(math.ceil(pixels/256)) # explicitly labelled budget assumption
        value=(Decimal(4096)*r['input']+Decimal(references*8192)*r['image_input']+output_budget*r['output'])/1_000_000
    else:raise StudioError('未实现该计费单位')
    return micros(value*q.fx_rate)

def usage_cost(model,usage,at=None):
    q=model.pricing
    if not q:return None
    data=(usage.get('token_usage') or {}).get('last') if usage.get('billing')=='codex_subscription' else usage
    if not data:return None
    if q.unit=='tokens':
        inp=data.get('input_tokens',data.get('prompt_tokens'));out=data.get('output_tokens',data.get('completion_tokens'))
        if inp is None or out is None:return None
        cached=data.get('cached_input_tokens',data.get('prompt_cache_hit_tokens',(data.get('input_tokens_details') or data.get('prompt_tokens_details') or {}).get('cached_tokens',0)))
        return token_cost(q,inp,out,cached,data.get('cache_write_input_tokens',0),at=at)
    if q.unit=='video_tokens' and data.get('completion_tokens') is not None:
        return None # resolution belongs to the job snapshot; handled by caller's conservative quote
    return None

def quote_view(model):
    if model.price_mode=='manual':
        if not model.price_confirmed or model.price_cny is None:return {'known':False,'message':'自定义报价尚未确认'}
        key={'call':'per_call','image':'per_image','second':'per_second','1000_characters':'per_1000'}[model.price_unit]
        multiplier=5 if model.price_unit=='second' else 1
        return {'known':True,'unit':model.price_unit,'rates_cny':{key:str(model.price_cny)},'currency':'CNY','sample_micros':micros(model.price_cny*multiplier),'sample_duration':5,'billing':'manual','notes':model.price_source or '用户自定义合同报价，不是官网自动价格'}
    if not model.pricing:return {'known':False,'message':'尚未匹配官方精确型号；保留可配置项，不将未知价格写成免费'}
    q=model.pricing;rates=effective_rates(q)
    sample_duration=model.durations[0] if model.durations else 5
    try:sample=auto_estimate(model,duration=sample_duration,characters=1000,input_tokens=10000,output_tokens=2000)
    except StudioError:sample=None
    return {'known':True,'source_url':q.source_url,'fetched_at':q.fetched_at,'unit':q.unit,'currency':q.currency,'rates':{k:str(v) for k,v in rates.items()},'rates_cny':{k:str(v*q.fx_rate) for k,v in rates.items()},'promo_until':q.promo_until,'promo_active':bool(q.promo_until and utcnow()<datetime.fromisoformat(q.promo_until)),'fx_rate':str(q.fx_rate),'fx_date':q.fx_date,'sample_micros':sample,'sample_duration':sample_duration,'notes':q.notes,'billing':'subscription' if model.adapter=='codex' else 'api'}

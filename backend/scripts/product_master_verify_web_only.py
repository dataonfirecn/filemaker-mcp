#!/usr/bin/env python3
"""Web-only acceptance for the whole active source (or an explicit product subset).

Reads every product through the real route handlers and re-downloads every COS object
verifying size + SHA-256, with FileMaker clients replaced by fail-on-call sentinels and
a low-level network guard that allows only GET/HEAD to the configured COS host. The DB
pool is forced read-only.

--baseline + --expected-new: total must equal baseline + new, and every baseline product
must keep its version, locator/mod id and exact asset set (proof nothing was rewritten).
--expected: plain total expectation (legacy). --product-file: restrict product/asset
checks to the listed UUIDs (pilot acceptance); baseline checks always cover the whole source.
"""
import argparse,asyncio,hashlib,json,requests
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from uuid import UUID,uuid4
import asyncpg
import httpx
from fastapi import HTTPException
from app.core.config import get_settings
from app.services.product_master.store import ProductStore,dumps
from app.services.product_master.schema import ProductSchema
from app.services.cos_storage import COSStorageService
from app.api.product_master import get_product,products,download,editor_controls,editor_customers

def read_uuids(path):
    return [str(UUID(l.strip())) for l in Path(path).read_text().splitlines() if l.strip() and not l.strip().startswith('#')]

async def run(args):
    s=get_settings();s.product_master_web_only=True;s.product_master_preview_enabled=True
    schema=ProductSchema.load(args.schema);store=ProductStore(s.audit_database_url,args.source);await store.init()
    initial=store.pool
    # Force every later read through a read-only pool.
    store.pool=await asyncpg.create_pool(s.audit_database_url,min_size=1,max_size=8,
        server_settings={'default_transaction_read_only':'on','application_name':'pm_verify_readonly'})
    await initial.close()
    storage=COSStorageService(s)
    report={'source':args.source,'mode':'subset' if args.product_file else 'full','products':0,'assets':0,
            'assetVersions':0,'verifiedObjects':0,'failures':[],'filemakerCalls':0,'blockedNetworkCalls':0}
    class NoFileMaker:
        def __getattr__(self,name):
            report['filemakerCalls']+=1
            raise AssertionError('Unexpected FileMaker dependency: '+name)
    # Block every non-COS HTTP request, even if some code bypasses the sentinel clients.
    cos_host=f'{s.cos_bucket}.cos.{s.cos_region}.myqcloud.com'
    original_request=requests.Session.request
    def guarded_request(session,method,url,*a,**kw):
        if urlparse(url).hostname!=cos_host or method.upper() not in {'GET','HEAD'}:
            report['blockedNetworkCalls']+=1
            raise AssertionError('Non-COS or mutating HTTP request forbidden')
        return original_request(session,method,url,*a,**kw)
    async def blocked_async(*a,**kw):
        report['blockedNetworkCalls']+=1
        raise AssertionError('External async HTTP forbidden')
    requests.Session.request=guarded_request
    httpx.AsyncHTTPTransport.handle_async_request=blocked_async
    try:
      state=SimpleNamespace(settings=s,product_master_schema=schema,product_master_preview_store=store,cos_storage_service=storage,filemaker_client=NoFileMaker(),filemaker_odata_client=NoFileMaker())
      request=SimpleNamespace(app=SimpleNamespace(state=state));context={'access':{'canViewProducts':True,'canViewPrice':True}}
      allowed={f['name'] for f in schema.fields.values() if f['result']!='container'}
      subset=set(read_uuids(args.product_file)) if args.product_file else None
      where_prod=' AND id=ANY($2::uuid[])' if subset else ''
      where_asset=' AND product_id=ANY($2::uuid[])' if subset else ''
      rows=await store.pool.fetch('SELECT id,fields,assets FROM pm_product WHERE source=$1'+where_prod,args.source,*([list(subset)] if subset else []))
      bindings=await store.pool.fetch('''SELECT a.product_id,v.id::text AS id,a.field,a.repetition
          FROM pm_product_asset a JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
          WHERE a.source=$1'''+(' AND a.product_id=ANY($2::uuid[])' if subset else ''),args.source,*([list(subset)] if subset else []))
      by_product={}
      for b in bindings:by_product.setdefault(str(b['product_id']),set()).add((b['id'],b['field'],b['repetition']))
      for r in rows:
        f=json.loads(r['fields']);assert set(f)==allowed,(r['id'],'field coverage')
        assert json.loads(r['assets'])==[], 'main table still contains assets'
        got=await get_product(str(r['id']),request,context)
        assert str(got['id'])==str(r['id'])
        got_set={(a['id'],a['field'],a['repetition']) for a in got['assets']}
        assert got_set==by_product.get(str(r['id']),set()), (r['id'],'asset set mismatch')
        report['products']+=1
      versions=await store.pool.fetch('SELECT * FROM pm_asset_version WHERE source=$1'+where_asset,args.source,*([list(subset)] if subset else []))
      report['assetVersions']=len(versions)
      report['assets']=await store.pool.fetchval('SELECT count(*) FROM pm_product_asset WHERE source=$1'+where_asset,args.source,*([list(subset)] if subset else []))
      role_rows=await store.pool.fetch('''SELECT a.field,a.role,v.mime_type FROM pm_product_asset a
          JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
          WHERE a.source=$1'''+(' AND a.product_id=ANY($2::uuid[])' if subset else ''),args.source,*([list(subset)] if subset else []))
      roles,mimes,main=Counter(),Counter(),0
      for a in role_rows:
        roles[a['role']]+=1;mimes[a['mime_type']]+=1
        if a['field']=='image_main':main+=1
      report['roleStats']=dict(roles);report['mimeStats']=dict(mimes);report['mainImages']=main
      if subset is None:
        report['productsWithoutMainImage']=await store.pool.fetchval("SELECT count(*) FROM pm_product p WHERE p.source=$1 AND NOT EXISTS(SELECT 1 FROM pm_product_asset a WHERE a.source=p.source AND a.product_id=p.id AND a.field='image_main')",args.source)
      else:
        report['productsWithoutMainImage']=await store.pool.fetchval("SELECT count(*) FROM pm_product p WHERE p.source=$1 AND p.id=ANY($2::uuid[]) AND NOT EXISTS(SELECT 1 FROM pm_product_asset a WHERE a.source=p.source AND a.product_id=p.id AND a.field='image_main')",args.source,list(subset))
      sem=asyncio.Semaphore(args.cos_concurrency)
      async def check(v):
        async with sem:
          try:
            data=await asyncio.to_thread(storage.get_object_bytes,v['object_key'],max_bytes=v['size'])
            if len(data)!=v['size'] or hashlib.sha256(data).hexdigest()!=v['sha256']:raise ValueError('COS content mismatch')
            report['verifiedObjects']+=1
          except Exception as exc:report['failures'].append({'id':str(v['id']),'error':type(exc).__name__})
      await asyncio.gather(*(check(v) for v in versions))
      await products(request,offset=0,context=context)
      await editor_controls(request,context)
      await editor_customers(request,q='',offset=0,context=context)
      try:await get_product(str(uuid4()),request,context)
      except HTTPException as e:assert e.status_code==404
      else:raise AssertionError('Unknown product must not load')
      if versions:await download(versions[0]['product_id'],versions[0]['id'],request,context)
      report['emptySKU']=await store.pool.fetchval("SELECT count(*) FROM pm_product WHERE source=$1 AND trim(coalesce(fields->>'product_sku',''))=''",args.source)
      report['duplicateSKU']=await store.pool.fetchval("SELECT count(*) FROM (SELECT lower(trim(fields->>'product_sku')) FROM pm_product WHERE source=$1 GROUP BY 1 HAVING count(*)>1) d",args.source)
      baseline_ok=True
      if args.baseline:
        doc=json.loads(Path(args.baseline).read_text());b=doc['products'];b_assets=doc['assets']
        all_ids={str(r['id']) for r in await store.pool.fetch('SELECT id FROM pm_product WHERE source=$1',args.source)}
        changes=[]
        for pid,before in b.items():
          if pid not in all_ids:changes.append({'id':pid,'error':'baseline product missing'});continue
          row=await store.pool.fetchrow('SELECT version,fm_mod_id FROM pm_product WHERE source=$1 AND id=$2',args.source,pid)
          cur=await store.pool.fetch('''SELECT v.id::text AS id,a.field,a.repetition,v.asset_id::text AS asset_id,
              v.object_key,v.size,v.sha256,v.mime_type
              FROM pm_product_asset a JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
              WHERE a.source=$1 AND a.product_id=$2''',args.source,pid)
          diff=[]
          if row['version']!=before['version']:diff.append('version:'+str(before['version'])+'->'+str(row['version']))
          if str(row['fm_mod_id'] or '')!=str(before.get('fmModId') or ''):diff.append('fmModId changed')
          before_set={tuple(a[k] for k in ('id','field','repetition','assetId','objectKey','size','sha256','mimeType')) for a in b_assets.get(pid,[])}
          after_set={(x['id'],x['field'],x['repetition'],x['asset_id'],x['object_key'],x['size'],x['sha256'],x['mime_type']) for x in cur}
          if before_set!=after_set:diff.append('assets:removed='+str(len(before_set-after_set))+',added='+str(len(after_set-before_set)))
          if diff:changes.append({'id':pid,'diff':diff})
        added=sorted(all_ids-set(b))
        report['baseline']={'products':len(b),'addedCount':len(added),'addedThisImport':added,'changes':changes}
        baseline_ok=not changes
        if subset is None:
          expected_total=len(b)+args.expected_new
          if len(rows)!=expected_total:
            report['failures'].append({'id':'total','error':'product count %d != baseline %d + expected-new %d'%(len(rows),len(b),args.expected_new)})
      else:
        if subset is not None:
          if len(rows)!=len(subset):report['failures'].append({'id':'subset','error':'missing %d of %d listed products'%(len(subset)-len(rows),len(subset))})
        elif len(rows)!=args.expected:
          report['failures'].append({'id':'total','error':'product count %d != expected %d'%(len(rows),args.expected)})
      report['complete']=not report['failures'] and report['filemakerCalls']==0 and report['blockedNetworkCalls']==0 and baseline_ok
      Path(args.report).write_text(dumps(report));print(dumps(report),flush=True)
      if not report['complete']:raise SystemExit(1)
    finally:await store.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--schema',default='config/product_master_web_schema.json');p.add_argument('--report',required=True)
    p.add_argument('--expected',type=int,default=0);p.add_argument('--baseline');p.add_argument('--expected-new',type=int,default=0);p.add_argument('--product-file')
    p.add_argument('--cos-concurrency',type=int,choices=range(2,33),default=6)
    args=p.parse_args()
    if not args.baseline and not args.expected and not args.product_file:p.error('one of --expected, --baseline or --product-file is required')
    asyncio.run(run(args))

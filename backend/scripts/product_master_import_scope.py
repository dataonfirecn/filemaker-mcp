#!/usr/bin/env python3
"""Import products into the active Web source; FileMaker is read-only.

Exactly one scope:
  --privilege CODE   scan privilege == CODE and import those not yet in Web
  --full             scan every layout record; new set = FM UUIDs - Web UUIDs
  --uuid-file PATH   import exactly the listed UUIDs (one per line, # comments)
  --refs-file PATH   import toAddRefs from a product_master_scan_source.py report

Products already in Web are counted and never rewritten (idempotent re-runs).
--limit caps how many NEW products are imported per run (existing are counted).
Exit code: 0 = no failures (partial/limited allowed), 1 = failures or identity issues.
"""
import argparse,asyncio,json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.cos_storage import COSStorageService
from app.services.product_master.store import ProductStore,dumps,source_fingerprint
from app.services.product_master.schema import ProductSchema
from app.services.product_master.importer import import_product
from app.services.product_master.options import native_controls,customer_options
from app.services.product_master.scan import scan_layout,resolve_uuids

def read_uuids(path):
    values=[]
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        try:values.append(str(UUID(line)))
        except ValueError:raise ValueError('Invalid UUID in '+path+': '+line[:60])
    if len(set(values))!=len(values):raise ValueError('Duplicate UUIDs in '+path)
    return values

async def run(args):
    s=get_settings();s.product_master_source=args.source;s.product_master_web_only=False
    schema=ProductSchema.load(args.schema);fm=FileMakerClient(s);odata=FileMakerODataClient(s)
    store=ProductStore(s.audit_database_url,args.source,source_fingerprint(s));await store.init(max_size=max(5,args.concurrency+1));cos=COSStorageService(s)
    mode='scope' if args.privilege else 'full' if args.full else 'uuid-file' if args.uuid_file else 'refs-file'
    report={'source':args.source,'mode':mode,'privilege':args.privilege,'complete':False,'partial':bool(args.limit),
            'expected':0,'scanned':0,'existing':0,'toAdd':0,'imported':0,'newImports':0,'assets':0,
            'locatorChanges':[],'identityIssues':{},'failures':[],'missingIds':[],'extraIds':None}
    def output():Path(args.report).write_text(dumps(report))
    try:
      output()
      schema.validate_layout(await fm.get_layout_metadata(s.product_master_layout))
      web={str(r['id']):r['fm_record_id'] for r in await store.pool.fetch('SELECT id,fm_record_id FROM pm_product WHERE source=$1',args.source)}
      if mode=='full' or mode=='scope':
        refs,issues=await scan_layout(fm,s.product_master_layout,privilege=args.privilege)
        report['identityIssues']=issues
        report['privilegeDistribution']=dict(Counter(r['privilege'] for r in refs))
      elif mode=='uuid-file':
        wanted=read_uuids(args.uuid_file)
        refs,problems=await resolve_uuids(fm,s.product_master_layout,wanted)
        report['identityIssues']={'resolveProblems':problems}
        if problems:raise ValueError('Explicit UUID set has unresolved identities; aborting: '+dumps(problems)[:400])
      else:
        doc=json.loads(Path(args.refs_file).read_text())
        refs=[{'id':str(UUID(r['id'])),'recordId':str(r['recordId']),'privilege':r.get('privilege')} for r in doc['toAddRefs']]
      report['scanned']=len(refs)
      known={r['id'] for r in refs}
      report['existing']=len(known&set(web));report['toAdd']=len(known-set(web))
      report['expected']=len(refs)
      for r in refs:
        saved=web.get(r['id'])
        if saved is not None and saved and str(saved)!=r['recordId']:
          report['locatorChanges'].append({'id':r['id'],'webRecordId':saved,'scanRecordId':r['recordId']})
      output()
      targets=[r for r in refs if r['id'] not in web]
      if args.limit:targets=targets[:args.limit]
      async def one(ref):
        pid,locator=ref['id'],ref['recordId']
        error=None
        for attempt in range(3):
          try:
            old=await store.get(pid)
            if old:
              if str(old['fm_record_id'] or '')!=locator:
                report['locatorChanges'].append({'id':pid,'webRecordId':str(old['fm_record_id']),'scanRecordId':locator})
              report['imported']+=1;report['assets']+=len(old['assets']);break
            row=(await fm.get_record(s.product_master_layout,locator))[0]
            if str(UUID(row['fieldData']['ID']))!=pid:raise ValueError('Source identity changed')
            if mode=='scope' and row['fieldData'].get('privilege')!=args.privilege:raise ValueError('Source identity or scope changed')
            saved=await import_product(store,schema,fm,cos,s,row)
            report['imported']+=1;report['newImports']+=1;report['assets']+=len(saved['assets']);break
          except Exception as exc:
            # Never log signed container URLs or credentials.
            error=type(exc).__name__+': '+str(exc).split('http')[0][:130]
            if attempt<2:await asyncio.sleep(1)
        else:report['failures'].append({'id':pid,'recordId':locator,'error':error})
        if (report['imported']+len(report['failures']))%10==0:
          output();print(dumps({k:report[k] for k in ('expected','existing','toAdd','imported','newImports','assets')}),flush=True)
      semaphore=asyncio.Semaphore(args.concurrency)
      async def limited(ref):
        async with semaphore:await one(ref)
      await asyncio.gather(*(limited(ref) for ref in targets))
      state=SimpleNamespace(settings=s,filemaker_client=fm,filemaker_odata_client=odata)
      req=SimpleNamespace(app=SimpleNamespace(state=state))
      for name,payload in [('controls',await native_controls(req)),('customers',await customer_options(req))]:
        if name=='controls':payload={k:v for k,v in payload.items() if k in schema.fields}
        async with store.pool.acquire() as c, c.transaction():
          await c.fetchrow('SELECT payload FROM pm_reference WHERE source=$1 AND name=$2 FOR UPDATE',args.source,name)
          if name=='customers' and await c.fetchval("SELECT to_regclass('public.pm_customer_sync')"):
            if await c.fetchval('SELECT 1 FROM pm_customer_sync WHERE source=$1 LIMIT 1',args.source):
              continue  # Dedicated customer sync owns the expanded directory after cutover.
          await c.execute('INSERT INTO pm_reference(source,name,payload) VALUES($1,$2,$3::jsonb) ON CONFLICT(source,name) DO UPDATE SET payload=EXCLUDED.payload,updated_at=now()',args.source,name,dumps(payload))
      actual={str(r['id']) for r in await store.pool.fetch('SELECT id FROM pm_product WHERE source=$1',args.source)}
      report['missingIds']=sorted(known-actual)
      if mode in ('full','scope'):report['extraIds']=sorted(actual-known)
      clean=not report['failures'] and not report['missingIds'] and not report['identityIssues'].get('resolveProblems')\
        and not report['identityIssues'].get('duplicateUuid') and not report['identityIssues'].get('invalidUuid')
      report['complete']=clean and not report['extraIds'] and not args.limit and mode in ('full','scope')
      output();print(dumps({k:v for k,v in report.items() if k not in ('missingIds','extraIds','locatorChanges')}),flush=True)
      if not clean or report['extraIds']:raise SystemExit(1)
    finally:await store.close();await fm.close();await odata.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True)
    scope=p.add_mutually_exclusive_group(required=True)
    scope.add_argument('--privilege');scope.add_argument('--full',action='store_true');scope.add_argument('--uuid-file');scope.add_argument('--refs-file')
    p.add_argument('--schema',default='config/product_master_web_schema.json');p.add_argument('--report',required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--concurrency',type=int,choices=range(1,9),default=3)
    asyncio.run(run(p.parse_args()))

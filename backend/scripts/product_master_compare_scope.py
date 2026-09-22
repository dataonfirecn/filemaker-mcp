#!/usr/bin/env python3
"""Read-only comparison of FileMaker (full / privilege / explicit UUID set) to the Web source.

With --baseline (manifest from product_master_snapshot_baseline.py) the report also separates
  - addedThisImport: Web UUIDs not in the baseline (new since the pre-import snapshot)
  - baselineChanges / baselineMissing: proof that pre-existing products/assets were untouched
"""
import argparse,asyncio,json
from pathlib import Path
from uuid import UUID
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.product_master.store import ProductStore,dumps
from app.services.product_master.schema import ProductSchema
from app.services.product_master.worker import value_at,canonical
from app.services.product_master.scan import scan_layout,resolve_uuids

def read_uuids(path):
    values=[]
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        values.append(str(UUID(line)))
    return values

async def run(args):
    s=get_settings();fm=FileMakerClient(s);store=ProductStore(s.audit_database_url,args.source);await store.init();schema=ProductSchema.load(args.schema)
    mode='scope' if args.privilege else 'full' if args.full else 'uuid-file'
    report={'source':args.source,'mode':mode,'privilege':args.privilege,'complete':False,'filemakerCount':0,'webCount':0,
            'missing':[],'extra':[],'fieldDifferences':[],'slotDifferences':[],'changedSinceImport':[],'canonicalFailures':[]}
    baseline=None
    if args.baseline:
      baseline=json.loads(Path(args.baseline).read_text())
      report['baseline']={'products':len(baseline.get('products',{})),'assets':len([a for v in baseline.get('assets',{}).values() for a in v]),
                          'addedThisImport':[],'baselineChanges':[],'baselineMissing':[]}
    try:
      Path(args.report).write_text(dumps(report))
      schema.validate_layout(await fm.get_layout_metadata(s.product_master_layout))
      known={str(r['id']) for r in await store.pool.fetch('SELECT id FROM pm_product WHERE source=$1',args.source)}
      if mode=='full' or mode=='scope':
        refs,issues=await scan_layout(fm,s.product_master_layout,privilege=args.privilege,keep_data=True)
        report['identityIssues']=issues
      else:
        refs,problems=await resolve_uuids(fm,s.product_master_layout,read_uuids(args.uuid_file))
        report['identityIssues']={'resolveProblems':problems}
        if problems:raise ValueError('Unresolved UUIDs in compare set: '+dumps(problems)[:300])
      seen=set()
      for ref in refs:
        row={'fieldData':ref['data'],'modId':ref['modId'],'recordId':ref['recordId']}
        pid=ref['id'];seen.add(pid);saved=await store.get(pid)
        if not saved:report['missing'].append(pid);continue
        if str(row['modId'])!=str(saved['fm_mod_id'] or ''):report['changedSinceImport'].append({'id':pid,'fmModId':str(row['modId']),'webModId':str(saved['fm_mod_id'])})
        diffs=[]
        for name,f in schema.fields.items():
          if f['result']=='container':continue
          remote=row['fieldData'].get(name)
          if name=='ID':remote=pid
          local=saved['fields'].get(name)
          if remote==local:continue
          try:
            r=canonical(remote,f['result']);l=canonical(local,f['result'])
          except Exception as exc:
            # Unparseable source values are reported, never fatal: compare is read-only verification.
            r='\x00'+repr(remote)[:200];l='\x00'+repr(local)[:200]
            report['canonicalFailures'].append({'id':pid,'field':name,'result':f['result'],
                'error':type(exc).__name__+': '+str(exc)[:120],'remote':repr(remote)[:200],'local':repr(local)[:200]})
          if r!=l:diffs.append(name)
        if diffs:report['fieldDifferences'].append({'id':pid,'fields':diffs})
        slots={(f['name'],i) for f in schema.fields.values() if f['result']=='container' and f.get('managed',True) for i in range(1,int(f.get('maxRepeat',1))+1) if value_at(row['fieldData'],f['name'],i)}
        actual={(a['field'],a['repetition']) for a in saved['assets']}
        if slots!=actual:report['slotDifferences'].append({'id':pid,'missing':sorted(slots-actual),'extra':sorted(actual-slots)})
      report['filemakerCount']=len(seen)
      report['extra']=sorted(known-seen) if mode in ('full','scope') else None
      if baseline is not None:
        b=baseline['products'];b_assets=baseline.get('assets',{})
        report['baseline']['addedThisImport']=sorted(known-set(b))
        report['baseline']['baselineMissing']=sorted(set(b)-known)
        for pid in sorted(set(b)&known):
          saved=await store.get(pid)
          before=b[pid]
          changes=[]
          if saved['version']!=before['version']:changes.append({'version':{'before':before['version'],'after':saved['version']}})
          if str(saved['fm_mod_id'] or '')!=str(before.get('fmModId') or ''):changes.append({'fmModId':{'before':before.get('fmModId'),'after':str(saved['fm_mod_id'])}})
          before_assets={tuple(a[k] for k in ('id','field','repetition','assetId','objectKey','size','sha256','mimeType')) for a in b_assets.get(pid,[])}
          after_assets={tuple(a[k] for k in ('id','field','repetition','assetId','objectKey','size','sha256','mimeType')) for a in saved['assets']}
          if before_assets!=after_assets:changes.append({'assets':{'removed':len(before_assets-after_assets),'added':len(after_assets-before_assets)}})
          if changes:report['baseline']['baselineChanges'].append({'id':pid,'changes':changes})
      report['webCount']=len(known)
      report['complete']=not any(report[k] for k in ('missing','fieldDifferences','slotDifferences','changedSinceImport','canonicalFailures'))\
        and not (report['extra'] or []) and not report['identityIssues'].get('duplicateUuid') and not report['identityIssues'].get('invalidUuid')\
        and (baseline is None or not report['baseline']['baselineChanges'] and not report['baseline']['baselineMissing'])
      Path(args.report).write_text(dumps(report));print(dumps(report),flush=True)
    finally:await store.close();await fm.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--schema',default='config/product_master_web_schema.json');p.add_argument('--report',required=True)
    scope=p.add_mutually_exclusive_group(required=True)
    scope.add_argument('--privilege');scope.add_argument('--full',action='store_true');scope.add_argument('--uuid-file')
    p.add_argument('--baseline')
    asyncio.run(run(p.parse_args()))

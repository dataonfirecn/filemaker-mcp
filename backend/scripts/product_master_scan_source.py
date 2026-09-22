#!/usr/bin/env python3
"""Read-only full scan of the FileMaker product layout vs the active Web source.

Writes a manifest: totals, privilege distribution, invalid/duplicate UUIDs, SKU quality,
toAddRefs (FM UUIDs not yet in Web, with container slot profile), existing locator
mismatches, and webOnly UUIDs (in Web but invisible to this FileMaker account).
No FileMaker writes; the database pool is forced read-only.
"""
import argparse,asyncio
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
import asyncpg
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import dumps,source_fingerprint
from app.services.product_master.scan import scan_layout
from app.services.product_master.worker import value_at

async def run(args):
    s=get_settings();fm=FileMakerClient(s)
    schema=ProductSchema.load(args.schema)
    report={'source':args.source,'layout':s.product_master_layout,'fingerprint':source_fingerprint(s),
            'scannedAt':datetime.now(timezone.utc).isoformat(),'complete':False}
    try:
      Path(args.report).write_text(dumps(report))
      schema.validate_layout(await fm.get_layout_metadata(s.product_master_layout))
      pool=await asyncpg.create_pool(s.audit_database_url,min_size=1,max_size=2,
          server_settings={'default_transaction_read_only':'on','application_name':'pm_scan_readonly'})
      try:
        web={str(r['id']):(r['fm_record_id'],r['fm_mod_id']) for r in await pool.fetch('SELECT id,fm_record_id,fm_mod_id FROM pm_product WHERE source=$1',args.source)}
      finally:await pool.close()
      refs,issues=await scan_layout(fm,s.product_master_layout,keep_data=True)
      containers=[f for f in schema.fields.values() if f['result']=='container' and f.get('managed',True)]
      def profile(field_data):
        slots,roles,images,specs,packages=0,Counter(),0,0,0
        for f in containers:
          for rep in range(1,int(f.get('maxRepeat',1))+1):
            if not value_at(field_data,f['name'],rep):continue
            slots+=1;roles[f.get('role','attachment')]+=1
            role=f.get('role')
            if role=='product_image':images+=1
            elif role=='product_specification':specs+=1
            elif role=='packaging_reference':packages+=1
        return slots,dict(roles),images,specs,packages
      to_add,existing=[],[]
      sku_groups={}
      empty_sku=0
      for r in refs:
        data=r['data']
        slots,roles,images,specs,packages=profile(data)
        sku=str(data.get('product_sku') or '').strip()
        if not sku:empty_sku+=1
        else:sku_groups.setdefault(sku.lower(),[]).append(r['id'])
        entry={'id':r['id'],'recordId':r['recordId'],'privilege':data.get('privilege'),'sku':sku,
               'mainImage':bool(value_at(data,'image_main',1)),'imageSlots':images,'specSlots':specs,
               'packageSlots':packages,'totalSlots':slots}
        if r['id'] in web:
          fm_rec,fm_mod=web[r['id']]
          if str(fm_rec or '')!=r['recordId']:
            entry['locatorMismatch']={'webRecordId':str(fm_rec),'scanRecordId':r['recordId']}
          entry['webModId']=fm_mod
          existing.append(entry)
        else:to_add.append(entry)
      report.update(scanned=len(refs),webCount=len(web),toAddCount=len(to_add),existingCount=len(existing),
          webOnly=sorted(set(web)-{r['id'] for r in refs}),
          privilegeDistribution=dict(Counter(r['privilege'] for r in refs)),
          toAddPrivilegeDistribution=dict(Counter(e['privilege'] for e in to_add)),
          toAddEmptySku=empty_sku,
          toAddDuplicateSkus={k:v for k,v in sku_groups.items() if len(v)>1},
          locatorMismatches=[e for e in existing if 'locatorMismatch' in e],
          toAddRefs=to_add,existingRefs=existing,
          identityIssues=issues)
      report['complete']=not issues['invalidUuid'] and not issues['duplicateUuid'] and not report['webOnly']
      Path(args.report).write_text(dumps(report))
      print(dumps({k:v for k,v in report.items() if k not in ('toAddRefs','existingRefs','webOnly','locatorMismatches')}),flush=True)
    finally:await fm.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--schema',default='config/product_master_web_schema.json');p.add_argument('--report',required=True)
    asyncio.run(run(p.parse_args()))

#!/usr/bin/env python3
"""Read-only pre-import manifest of the active Web source.

Saves every product's version, FileMaker locator/mod id, full field set, and every asset
binding (version id, asset id, field, repetition, object key, size, sha256, mime, role).
Used to prove that pre-existing products and assets are not rewritten by a later import.
The database pool is forced read-only.
"""
import argparse,asyncio,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import asyncpg
from app.core.config import get_settings
from app.services.product_master.store import dumps,source_fingerprint

async def run(args):
    s=get_settings()
    pool=await asyncpg.create_pool(s.audit_database_url,min_size=1,max_size=2,
        server_settings={'default_transaction_read_only':'on','application_name':'pm_baseline_readonly'})
    report={'source':args.source,'fingerprint':source_fingerprint(s),
            'createdAt':datetime.now(timezone.utc).isoformat()}
    try:
      products=await pool.fetch('SELECT id,version,fm_record_id,fm_mod_id,fields,assets FROM pm_product WHERE source=$1 ORDER BY id',args.source)
      assets=await pool.fetch('''SELECT a.product_id,a.field,a.repetition,a.sort_order,a.role,
          v.id,v.asset_id,v.object_key,v.filename,v.mime_type,v.size,v.sha256
          FROM pm_product_asset a JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
          WHERE a.source=$1 ORDER BY a.product_id,a.sort_order''',args.source)
      bad_json=[str(r['id']) for r in products if json.loads(r['assets'])!=[]]
      by_product,roles={},Counter()
      for a in assets:
        by_product.setdefault(str(a['product_id']),[]).append(
            {'id':str(a['id']),'assetId':str(a['asset_id']),'field':a['field'],'repetition':a['repetition'],
             'sortOrder':a['sort_order'],'role':a['role'],'objectKey':a['object_key'],'filename':a['filename'],
             'mimeType':a['mime_type'],'size':a['size'],'sha256':a['sha256']})
        roles[a['role']]+=1
      for r in products:
        f=json.loads(r['fields'])
        by_product.setdefault(str(r['id']),[])
        report.setdefault('products',{})[str(r['id'])]={
            'version':r['version'],'fmRecordId':str(r['fm_record_id']) if r['fm_record_id'] else None,
            'fmModId':str(r['fm_mod_id']) if r['fm_mod_id'] else None,'fields':f}
      report.update(productCount=len(products),assetCount=len(assets),roles=dict(roles),
          assetsNonEmptyJsonb=bad_json,assets=by_product)
      Path(args.report).write_text(dumps(report))
      print(dumps({k:v for k,v in report.items() if k not in ('products','assets')}),flush=True)
    finally:await pool.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--report',required=True)
    asyncio.run(run(p.parse_args()))

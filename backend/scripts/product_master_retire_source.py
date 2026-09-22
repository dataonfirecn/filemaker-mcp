#!/usr/bin/env python3
"""Remove a retired product dataset only after switching to a verified replacement and making a backup."""
import argparse,asyncio,json
from pathlib import Path
import asyncpg
from app.core.config import get_settings

async def run(args):
 s=get_settings()
 if not s.product_master_web_only or s.product_master_source!=args.replacement or args.source==args.replacement:
  raise ValueError('Replacement must already be the active Web-only source')
 verified=json.loads(Path(args.verification).read_text());comparison=json.loads(Path(args.comparison).read_text())
 if verified.get('source')!=args.replacement or not verified.get('complete') or not comparison.get('complete'):
  raise ValueError('Successful source and COS verification reports required')
 if not Path(args.backup).is_file() or Path(args.backup).stat().st_size<1000:
  raise ValueError('A current backup is required')
 c=await asyncpg.connect(s.audit_database_url)
 try:
  async with c.transaction():
   before=await c.fetchval('SELECT count(*) FROM pm_product WHERE source=$1',args.source)
   current=await c.fetchval('SELECT count(*) FROM pm_product WHERE source=$1',args.replacement)
   if current!=verified['products']:raise ValueError('Replacement changed since verification')
   for table in ('pm_product_asset','pm_asset_version','pm_reference','pm_consumer','pm_publication','pm_drift','pm_job','pm_revision','pm_upload','pm_product','pm_scan','pm_source'):
    await c.execute(f'DELETE FROM {table} WHERE source=$1',args.source)
  print(json.dumps({'retiredSource':args.source,'removedProducts':before,'activeSource':args.replacement,'activeProducts':current,'cosDeleted':False}))
 finally:await c.close()

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','replacement','verification','comparison','backup'):p.add_argument('--'+name,required=True)
 asyncio.run(run(p.parse_args()))

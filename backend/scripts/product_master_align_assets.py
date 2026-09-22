#!/usr/bin/env python3
"""Append an audited revision when imported attachment roles/order differ from the reviewed UI schema."""
import argparse,asyncio
from uuid import uuid4
from app.core.config import get_settings
from app.services.product_master.store import ProductStore
from app.services.product_master.schema import ProductSchema
async def run(args):
 s=get_settings();store=ProductStore(s.audit_database_url,args.source);await store.init();schema=ProductSchema.load(args.schema)
 rank={n:i for i,n in enumerate(schema.fields)};changed=0
 try:
  for r in await store.pool.fetch('SELECT id FROM pm_product WHERE source=$1',args.source):
   p=await store.get(r['id']);ordered=sorted(p['assets'],key=lambda a:(rank[a['field']],a['repetition']))
   if ordered==p['assets'] and all(a['role']==schema.fields[a['field']].get('role','attachment') for a in ordered):continue
   await store.save(product_id=p['id'],expected_version=p['version'],request_id=uuid4(),changes={},assets=[{'id':a['id'],'field':a['field'],'repetition':a['repetition']} for a in ordered],actor={'account':'migration-ui-alignment'},schema=schema,permissions={},origin='migration-ui-alignment',imported={'recordId':p['fm_record_id'],'modId':p['fm_mod_id']})
   changed+=1
  print({'alignedProducts':changed})
 finally:await store.close()
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--schema',default='config/product_master_web_schema.json');asyncio.run(run(p.parse_args()))

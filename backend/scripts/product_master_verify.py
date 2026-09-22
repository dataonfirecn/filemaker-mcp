#!/usr/bin/env python3
"""Verify every referenced historical asset; report failures without deleting anything."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from app.core.config import get_settings
from app.services.product_master.store import ProductStore, unpack
from app.services.cos_storage import COSStorageService


async def verify(full):
    settings=get_settings();store=ProductStore(settings.audit_database_url,settings.product_master_source)
    await store.init();storage=COSStorageService(settings)
    report={'products':0,'revisions':0,'assetsChecked':0,'failures':[]}
    try:
        report['products']=await store.pool.fetchval('SELECT count(*) FROM pm_product WHERE source=$1',store.source)
        report['revisions']=await store.pool.fetchval('SELECT count(*) FROM pm_revision WHERE source=$1',store.source)
        rows=await store.pool.fetch('''SELECT DISTINCT a.value AS metadata FROM pm_revision r,
            jsonb_array_elements(r.after_data->'assets') a WHERE source=$1''',store.source)
        for row in rows:
            asset=json.loads(row['metadata'])
            try:
                meta=await asyncio.to_thread(storage.head_object,asset['objectKey'])
                if meta.content_length!=asset['size']:raise ValueError('size mismatch')
                if full:
                    content=await asyncio.to_thread(storage.get_object_bytes,asset['objectKey'],max_bytes=settings.product_master_max_file_bytes)
                    if hashlib.sha256(content).hexdigest()!=asset['sha256']:raise ValueError('checksum mismatch')
                report['assetsChecked']+=1
            except Exception as exc:
                report['failures'].append({'assetId':asset['id'],'error':type(exc).__name__})
        report['pendingJobs']=await store.pool.fetchval("SELECT count(*) FROM pm_job WHERE source=$1 AND status NOT IN ('synced','superseded')",store.source)
        report['unresolvedDrift']=await store.pool.fetchval('SELECT count(*) FROM pm_drift WHERE source=$1 AND NOT resolved',store.source)
        report['complete']=not report['failures']
        return report
    finally:await store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sha256',action='store_true');parser.add_argument('--report',default='product-master-verification.json')
    args=parser.parse_args();report=asyncio.run(verify(args.sha256))
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['complete']:raise SystemExit(1)

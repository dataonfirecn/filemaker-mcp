"""Copy missing image_main files into the existing Web catalog, preserving all other data.

Optional backup DB access only supplies reusable object keys and asset identities;
FileMaker bytes are freshly read and COS bytes verified before any binding is saved.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote
from uuid import UUID, uuid5, NAMESPACE_URL

import asyncpg
from app.core.config import get_settings
from app.services.cos_storage import COSStorageService
from app.services.filemaker_client import FileMakerClient
from app.services.product_image_fields import MAIN_IMAGE_FIELD
from app.services.product_master.importer import content_type, legacy_slots, asset_identity
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import ProductStore, dumps
from app.services.product_master.worker import download_container, value_at


async def run(args):
    settings = get_settings()
    if settings.product_master_enabled or settings.product_master_write_enabled:
        raise ValueError('Pause product writes before backfill')
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    await store.init(max_size=args.concurrency+1)
    fm = FileMakerClient(settings)
    cos = COSStorageService(settings)
    schema = ProductSchema.load(settings.product_master_schema_path)
    report = {'source': store.source, 'checked': 0, 'expectedMainImages': 0, 'added': 0,
              'alreadyPresent': 0, 'reusedCOS': 0, 'failures': [], 'complete': False}
    backup_files = {}
    try:
        Path(args.report).write_text(dumps(report))
        schema.validate_layout(await fm.get_layout_metadata(settings.product_master_layout))
        if args.reuse_database:
            u = urlsplit(settings.audit_database_url)
            backup = await asyncpg.connect(urlunsplit((u.scheme,u.netloc,'/'+args.reuse_database,u.query,u.fragment)))
            try:
                for row in await backup.fetch("SELECT product_id,metadata FROM pm_upload WHERE ready AND metadata->>'field' IN ('檔案 1 | 容器','image_main')"):
                    backup_files.setdefault(row['product_id'], []).append(json.loads(row['metadata']))
            finally:
                await backup.close()
        products = await store.pool.fetch('SELECT id,fm_record_id FROM pm_product WHERE source=$1 ORDER BY id',store.source)
        report['products'] = len(products)
        semaphore = asyncio.Semaphore(args.concurrency)

        async def one(ref):
            async with semaphore:
                pid = ref['id']
                try:
                    product = await store.get(pid)
                    row = (await fm.get_record(settings.product_master_layout, ref['fm_record_id']))[0]
                    if UUID(row['fieldData']['ID']) != pid or row['fieldData'].get('privilege') != '008':
                        raise ValueError('Product identity or scope changed')
                    url = value_at(row['fieldData'], MAIN_IMAGE_FIELD, 1)
                    if not url:
                        return
                    report['expectedMainImages'] += 1
                    if any(a['field'] == MAIN_IMAGE_FIELD for a in product['assets']):
                        report['alreadyPresent'] += 1
                        return
                    content, header = await download_container(fm, url, settings.product_master_max_file_bytes)
                    sha = hashlib.sha256(content).hexdigest()
                    candidates = backup_files.get(pid, [])
                    identities = {m['assetId'] for m in candidates if m.get('assetId')}
                    if len(identities) == 1:
                        aid = next(iter(identities))
                    else:
                        rows, offset = [], 1
                        while True:
                            page = await fm.find_records('ProductAssets', {'source_record_id': '=='+str(ref['fm_record_id'])}, limit=200, offset=offset)
                            rows.extend(page['data']);offset += len(page['data'])
                            if offset > page['foundCount'] or not page['data']:
                                break
                        aid = asset_identity(legacy_slots(rows), ref['fm_record_id'], MAIN_IMAGE_FIELD, 1, str(pid))
                    uid = uuid5(NAMESPACE_URL, f'{store.source}:{aid}:{sha}')
                    key = f'product-master/{store.source}/{pid}/{uid}/{sha}'
                    reused = False
                    for metadata in candidates:
                        if metadata.get('sha256') != sha or metadata.get('size') != len(content):
                            continue
                        try:
                            data = await asyncio.to_thread(cos.get_object_bytes, metadata['objectKey'], max_bytes=len(content))
                            if len(data) == len(content) and hashlib.sha256(data).hexdigest() == sha:
                                key = metadata['objectKey'];reused = True;break
                        except Exception:
                            continue
                    if not reused:
                        await asyncio.to_thread(cos.put_object, object_key=key, content=content, content_type=content_type(content,header))
                        checked = await asyncio.to_thread(cos.get_object_bytes,key,max_bytes=len(content))
                        if len(checked) != len(content) or hashlib.sha256(checked).hexdigest() != sha:
                            raise ValueError('COS verification failed')
                    check = (await fm.get_record(settings.product_master_layout, ref['fm_record_id']))[0]
                    if check['modId'] != row['modId']:
                        raise ValueError('Source changed while copying image')
                    metadata = {'assetId':aid,'objectKey':key,'sha256':sha,'size':len(content),
                                'mimeType':content_type(content,header),'filename':unquote(Path(urlsplit(url).path).name) or 'main-image',
                                'field':MAIN_IMAGE_FIELD,'repetition':1}
                    async with store.pool.acquire() as connection, connection.transaction():
                        await connection.execute('INSERT INTO pm_upload(source,id,product_id,request_id,actor,metadata,ready) VALUES($1,$2,$3,$2,$4,$5::jsonb,true) ON CONFLICT(source,id) DO NOTHING',store.source,uid,pid,'main-image-backfill',dumps(metadata))
                        await store.save(product_id=pid,expected_version=product['version'],request_id=uuid5(uid,'main-image-backfill'),
                            changes={},assets=[{'id':str(uid),'field':MAIN_IMAGE_FIELD,'repetition':1},*product['assets']],
                            actor={'account':'main-image-backfill'},schema=schema,permissions={},origin='main-image-backfill',connection=connection,
                            imported={'recordId':product['fm_record_id'],'modId':product['fm_mod_id']})
                    report['added'] += 1
                    report['reusedCOS'] += int(reused)
                except Exception as exc:
                    report['failures'].append({'id':str(pid),'error':type(exc).__name__+': '+str(exc).split('http')[0][:100]})
                finally:
                    report['checked'] += 1
                    if report['checked'] % 25 == 0:
                        Path(args.report).write_text(dumps(report))
                        print(dumps(report),flush=True)
        await asyncio.gather(*(one(ref) for ref in products))
        report['complete'] = not report['failures'] and report['added']+report['alreadyPresent']==report['expectedMainImages']
        Path(args.report).write_text(dumps(report));print(dumps(report),flush=True)
        if not report['complete']:
            raise SystemExit(1)
    finally:
        await store.close();await fm.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-database')
    parser.add_argument('--concurrency',type=int,choices=range(1,17),default=8)
    parser.add_argument('--report',required=True)
    asyncio.run(run(parser.parse_args()))

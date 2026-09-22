"""Copy a complete FileMaker product into immutable Web storage, never write FM."""
import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, unquote
from uuid import UUID, uuid5, NAMESPACE_URL

from PIL import Image, UnidentifiedImageError
from .store import dumps
from app.services.product_image_fields import canonical_container_field
from .worker import download_container, value_at


def legacy_slots(rows):
    slots = {}
    for row in rows:
        fields = row['fieldData']
        key = (str(fields.get('source_record_id') or ''), canonical_container_field(str(fields.get('legacy_source_field') or '')), 1)
        if not all(key[:2]) or not fields.get('id_asset'):
            continue
        slots.setdefault(key, set()).add(str(fields['id_asset']))
    return slots


def asset_identity(slots, record_id, field, repetition, identity):
    candidates = slots.get((str(record_id), field, repetition), set())
    if len(candidates) > 1:
        raise ValueError(f'旧资产关联冲突：{field} [{repetition}]，需核对 {len(candidates)} 个资产标识')
    return next(iter(candidates)) if candidates else str(uuid5(UUID(identity), f'{field}:{repetition}'))


def content_type(content, header):
    if content.startswith(b'%PDF-'):
        return 'application/pdf'
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
            return Image.MIME.get(image.format, 'application/octet-stream')
    except (UnidentifiedImageError, OSError, ValueError):
        # Unknown files are downloads; never trust an active content type from FM.
        return 'application/octet-stream'


async def import_product(store, schema, fm, storage, settings, row, legacy=None):
    identity = str(UUID(row['fieldData']['ID']))
    # Coordinate bulk migration and foreground loading across processes.
    async with store.pool.acquire() as connection:
        lock = 'pm-import:' + store.source + ':' + identity
        await connection.execute('SELECT pg_advisory_lock(hashtextextended($1,0))', lock)
        try:
            existing = await store.get(identity, connection)
            if existing:
                if existing['fm_record_id'] != str(row['recordId']):
                    raise ValueError('Existing UUID changed locator')
                return existing
            if legacy is None and not any(value_at(row['fieldData'], f['name'], rep)
                    for f in schema.fields.values() if f['result']=='container' and f.get('managed',True)
                    for rep in range(1,int(f.get('maxRepeat',1))+1)):
                legacy = {}
            if legacy is None:
                rows, offset = [], 1
                while True:
                    page = await fm.find_records('ProductAssets', {'source_record_id': '==' + str(row['recordId'])}, limit=200, offset=offset)
                    rows.extend(page['data']); offset += len(page['data'])
                    if offset > page['foundCount'] or not page['data']:
                        break
                legacy = legacy_slots(rows)
            attachments = []
            for field in schema.fields.values():
                if field['result'] != 'container' or not field.get('managed',True):
                    continue
                for repetition in range(1, int(field.get('maxRepeat', 1)) + 1):
                    url = value_at(row['fieldData'], field['name'], repetition)
                    if not url:
                        continue
                    aid = asset_identity(legacy, row['recordId'], field['name'], repetition, identity)
                    content, header = await download_container(fm, url, settings.product_master_max_file_bytes)
                    mime = content_type(content, header)
                    digest = hashlib.sha256(content).hexdigest()
                    uid = uuid5(NAMESPACE_URL, f'{store.source}:{aid}:{digest}')
                    key = f'product-master/{store.source}/{identity}/{uid}/{digest}'
                    filename = unquote(Path(urlparse(url).path).name) or 'attachment'
                    metadata = {'assetId': aid, 'objectKey': key, 'filename': filename, 'mimeType': mime,
                                'size': len(content), 'sha256': digest, 'field': field['name'], 'repetition': repetition}
                    ready = await connection.fetchval('SELECT ready FROM pm_upload WHERE source=$1 AND id=$2', store.source, uid)
                    if not ready:
                        # Reuse only immutable COS bytes proven identical to the freshly downloaded FM file.
                        # Old product values are never reused. This also avoids unnecessary cross-region uploads.
                        reused = False
                        candidates = await connection.fetch("""SELECT metadata->>'objectKey' AS key FROM pm_upload
                            WHERE ready AND metadata->>'sha256'=$1 AND metadata->>'size'=$2
                            AND metadata ? 'objectKey' LIMIT 3""", digest, str(len(content)))
                        for candidate in candidates:
                            try:
                                previous = await asyncio.to_thread(storage.get_object_bytes, candidate['key'], max_bytes=len(content))
                                if hashlib.sha256(previous).hexdigest() == digest:
                                    key = candidate['key']; metadata['objectKey'] = key
                                    reused = True
                                    break
                            except Exception:
                                continue
                        if not reused:
                            await asyncio.to_thread(storage.put_object, object_key=key, content=content, content_type=mime)
                        checked = await asyncio.to_thread(storage.get_object_bytes, key, max_bytes=len(content))
                        if hashlib.sha256(checked).hexdigest() != digest:
                            raise ValueError('COS verification failed')
                        await connection.execute('''INSERT INTO pm_upload(source,id,product_id,request_id,actor,metadata,ready)
                            VALUES($1,$2,$3,$2,'migration',$4::jsonb,true) ON CONFLICT(source,id) DO NOTHING''',
                            store.source, uid, UUID(identity), dumps(metadata))
                    attachments.append({'id': str(uid), 'field': field['name'], 'repetition': repetition})
            check = (await fm.get_record(settings.product_master_layout, row['recordId']))[0]
            if check['modId'] != row['modId']:
                raise ValueError('产品在文件校验期间发生变化，请重新加载')
            fields = {k: v for k, v in row['fieldData'].items() if k in schema.fields and schema.fields[k]['result'] != 'container'}
            return await store.save(product_id=identity, expected_version=0, request_id=uuid5(UUID(identity), 'initial-import'),
                changes=fields, assets=attachments, actor={'account': 'migration'}, schema=schema,
                permissions={}, origin='migration', imported=row, connection=connection)
        finally:
            await connection.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', lock)

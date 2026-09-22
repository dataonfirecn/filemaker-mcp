"""Compatibility adapter for existing PDA photo clients after Web ownership cutover."""
from uuid import UUID, uuid5
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app.api.product_master import presign_impl, complete_upload, commit, UploadBody, SaveBody
from app.models.mobile_products import ProductPhotoPresignResponse, ProductPhotoUploadResponse
from .store import unpack
from app.services.product_image_fields import product_image_field, product_image_slot, canonical_container_field


def context(operator):
    return {'operator': {'account': operator.account, 'name': operator.name},
            'sessionId': operator.session_id, 'access': operator.permissions or {}}


async def create(request, sku, body, operator):
    store = request.app.state.product_master_store
    if not body.mime_type.startswith('image/'):
        raise HTTPException(415,'PDA 补图仅支持图片')
    product = await store.get(sku)
    if not product: raise HTTPException(404, '产品尚未迁入 Web 主库')
    pid = UUID(str(product['id']))
    rid = uuid5(pid, f'pda:{operator.account}:{body.session_id}:{body.sha256}')
    async with store.pool.acquire() as c:
        key = f'pm-pda:{store.source}:{pid}'
        await c.execute('SELECT pg_advisory_lock(hashtextextended($1,0))', key)
        try:
            existing = unpack(await c.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND request_id=$2', store.source, rid))
            if existing:
                slot = product_image_slot(existing['metadata']['field'])
            else:
                active = await c.fetch('''SELECT metadata FROM pm_upload WHERE source=$1 AND product_id=$2
                    AND created_at>now()-interval '2 hours' ''', store.source, pid)
                used = []
                for row in active:
                    m = unpack(row)['metadata']
                    if 'pdaSession' in m:
                        if m['pdaSession'] != body.session_id or m['pdaActor'] != operator.account:
                            raise HTTPException(409, '另一个补图会话正在处理此产品')
                        used.append(canonical_container_field(m['field']))
                if not used and any(1 <= (product_image_slot(a['field']) or 999) <= 10 for a in product['assets']):
                    raise HTTPException(409, '该产品已有照片，请使用产品编辑器管理')
                if len(used) >= 6: raise HTTPException(409, '每个补图会话最多 6 张')
                slot = next(i for i in range(1,7) if product_image_field(i) not in used)
            signed = await presign_impl(pid, UploadBody(requestId=rid,filename=body.filename,mimeType=body.mime_type,size=body.file_size,sha256=body.sha256,field=product_image_field(slot)), request, context(operator), connection=c)
            await c.execute("UPDATE pm_upload SET metadata=metadata || $3::jsonb WHERE source=$1 AND id=$2", store.source, UUID(signed['id']), __import__('json').dumps({'pdaSession':body.session_id,'pdaActor':operator.account}))
        finally:
            await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)
    row = unpack(await store.pool.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND id=$2', store.source, UUID(signed['id'])))
    return ProductPhotoPresignResponse(uploadId=signed['id'],objectKey=row['metadata']['stagingKey'],slot=slot,uploadUrl=signed['url'],headers=signed['headers'],expiresAt=datetime.now(timezone.utc)+timedelta(seconds=request.app.state.settings.cos_presign_ttl_seconds))


async def finish(request, sku, upload_id, operator, body=None):
    store = request.app.state.product_master_store
    row = unpack(await store.pool.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND id=$2', store.source, UUID(upload_id)))
    product = await store.get(sku)
    if not row or not product or str(row['product_id']) != str(product['id']) or row['actor'] != operator.account:
        raise HTTPException(404, '上传不存在')
    m = row['metadata']
    m['field'] = canonical_container_field(m['field'])
    if body:
        if body.sha256 != m['sha256'] or body.file_size != m['size']:
            raise HTTPException(422, '上传摘要不一致')
    if body or row['ready']:
        asset = await complete_upload(row['product_id'], UUID(upload_id), request, context(operator))
        for attempt in range(3):
            product=await store.get(sku)
            if any(a['id']==upload_id for a in product['assets']):break
            if any(a['field']==m['field'] and a['repetition']==m['repetition'] for a in product['assets']):
                raise HTTPException(409, '目标图片位置已被修改')
            try:
                await commit(request, context(operator), row['product_id'], SaveBody(requestId=uuid5(UUID(upload_id),'pda-save'),expectedVersion=product['version'],assets=[*product['assets'], asset]),origin='pda')
                break
            except HTTPException as exc:
                if exc.status_code!=409 or attempt==2:raise
    product = await store.get(sku)
    present = any(a['id']==upload_id for a in product['assets'])
    jobs = await store.jobs(product['id'])
    job = next((j for j in jobs if j['version']==product['version']), {})
    state = 'SYNCED' if present and job.get('status')=='synced' else 'UPLOADED' if present else 'PENDING'
    return ProductPhotoUploadResponse(uploadId=upload_id,productSku=sku,objectKey=m['objectKey'],slot=product_image_slot(m['field']),status=state,createdAt=row['created_at'],uploadedAt=row['created_at'] if row['ready'] else None,lastError=job.get('error'))

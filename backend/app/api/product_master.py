"""Authenticated Web product editor and source-bound DMS publication API."""
import asyncio
import hashlib
import hmac
import json
from io import BytesIO
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from typing import Literal
from pydantic import BaseModel, Field
from PIL import Image
from app.services.dependencies import get_webviewer_session_context
from app.services.product_master.store import Conflict, ProductLocked, LOCKED_MESSAGE, dumps, unpack, connection_for, request_digest
from app.services.product_master.schema import ProductValidationError, SKUValidationError
from app.services.product_image_fields import canonical_container_field

router = APIRouter(prefix='/product-master', tags=['product-master'])


class SaveBody(BaseModel):
    requestId: UUID
    expectedVersion: int = Field(ge=0)
    changes: dict = Field(default_factory=dict)
    assets: list[dict] | None = None


class UploadBody(BaseModel):
    requestId: UUID
    filename: str = Field(min_length=1, max_length=255)
    mimeType: str = Field(min_length=1, max_length=100, pattern=r'^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$')
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    field: str
    repetition: int = Field(default=1, ge=1)


class ReviewBody(BaseModel):
    requestId: UUID
    expectedVersion: int = Field(ge=1)
    status: Literal['已審核', '未審核']


class ActionBody(BaseModel):
    requestId: UUID
    reason: str = Field(min_length=1, max_length=1000)


def runtime(request):
    store = getattr(request.app.state, 'product_master_store', None)
    if not store:
        raise HTTPException(503, '产品主库尚未启用')
    return store, request.app.state.product_master_schema


def preview_only(request):
    return (getattr(request.app.state.settings, 'product_master_preview_enabled', False)
            and not getattr(request.app.state, 'product_master_store', None))


def access(context, permission):
    permissions = context.get('access', {})
    if not permissions.get(permission):
        raise HTTPException(403, '没有产品操作权限')
    return permissions


def actor(context):
    return {'account': context.get('operator', {}).get('account', 'unknown'), 'name': context.get('operator', {}).get('name', 'unknown'), 'sessionId': context.get('sessionId', '')}


def filtered(snapshot, schema, permissions):
    result = dict(snapshot)
    result['fields'] = schema.filter_fields(snapshot.get('fields', {}), permissions)
    for name in ('RMB成本', '美金成本'):
        result['fields'].pop(name, None)
    visible = {f['name'] for f in schema.visible(permissions)}
    result['assets'] = [a for a in snapshot.get('assets', []) if a['field'] in visible]
    return result


@router.get('/schema')
async def schema_info(request: Request, context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    if preview_only(request):
        schema = request.app.state.product_master_schema
        return {'fields': schema.visible(permissions), 'previewMode': True,
                'permissions': {**permissions, 'canEditProducts': False,
                                'canEditProductPrices': False, 'canManageProductSync': False}}
    _, schema = runtime(request)
    return {'fields': schema.visible(permissions), 'permissions': permissions}


@router.get('/editor-controls')
async def editor_controls(request: Request, context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    from app.services.product_master.options import native_controls
    try:
        controls = await native_controls(request)
    except Exception as exc:
        raise HTTPException(503, '原生选项读取失败，请稍后重新打开页面。') from exc
    visible = {f['name'] for f in request.app.state.product_master_schema.visible(permissions)}
    return {'controls': {name: {**control, 'searchable': len(control['options']) > 100,
            'options': control['options'] if len(control['options']) <= 100 else []}
            for name, control in controls.items() if name in visible}}


@router.get('/customers')
async def editor_customers(request: Request, q: str = Query('', max_length=80),
                           offset: int = Query(0, ge=0), context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    visible = {f['name'] for f in request.app.state.product_master_schema.visible(permissions)}
    if not {'Client', 'id_client'} <= visible:
        raise HTTPException(403, '没有客户字段读取权限')
    from app.services.product_master.options import customer_options
    try:
        rows = await customer_options(request)
    except Exception as exc:
        raise HTTPException(503, '客户列表读取失败，请稍后重试。') from exc
    rows = [o for o in rows if q.casefold() in (o['name']+' '+o['code']+' '+o['value']).casefold()]
    return {'rows': rows[offset:offset+50], 'total': len(rows)}


@router.get('/editor-options/{field}')
async def editor_options(field: str, request: Request, q: str = Query('', max_length=80),
                         offset: int = Query(0, ge=0), context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    visible = {f['name'] for f in request.app.state.product_master_schema.visible(permissions)}
    if field not in visible:
        raise HTTPException(403, '没有字段读取权限')
    from app.services.product_master.options import native_controls
    try:
        control = (await native_controls(request)).get(field)
    except Exception as exc:
        raise HTTPException(503, '选项读取失败，请重试。') from exc
    if not control:
        raise HTTPException(404, '字段没有原生选项')
    rows = [o for o in control['options'] if q.casefold() in (o['value']+' '+o['label']).casefold()]
    return {'rows': rows[offset:offset+50], 'total': len(rows)}


@router.get('/products')
async def products(request: Request, q: str = '', offset: int = Query(0, ge=0), context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    if preview_only(request):
        store = request.app.state.product_master_preview_store
        schema = request.app.state.product_master_schema
    else:
        store, schema = runtime(request)
    return {'rows': [filtered(r, schema, permissions) for r in await store.list(q, offset=offset)]}


@router.get('/products/{product_id}/costs')
async def product_costs(product_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    access(context, 'canViewProducts')
    access(context, 'canViewPrice')
    store = getattr(request.app.state, 'product_master_store', None) or getattr(request.app.state, 'product_master_preview_store', None)
    if not store:
        raise HTTPException(503, '产品主库尚未启用')
    product = await store.get(product_id)
    if not product:
        raise HTTPException(404, '产品不存在')
    from app.services.product_master.finance import read_costs
    from fastapi.responses import JSONResponse
    try:
        result = await read_costs(request.app.state.product_finance_filemaker, product)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, '实时成本读取失败，请稍后点击刷新成本重试。') from exc


async def finance_detail(snapshot, store, schema, permissions):
    result = filtered(snapshot, schema, permissions)
    if permissions.get('canViewPrice') and any(f.get('externalSource') for f in schema.fields.values()):
        from app.services.product_master.finance import load_snapshot
        baseline = await load_snapshot(store.pool, store.source, snapshot['id'])
        result['financeIssues'] = baseline.get('issues', {}) if baseline else {}
        result['financeImported'] = bool(baseline)
        result['financePriceBound'] = bool(baseline and baseline.get('price'))
    return result


@router.get('/products/{ref}')
async def get_product(ref: str, request: Request, context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    if preview_only(request):
        try:
            product_id = UUID(ref)
        except ValueError:
            raise HTTPException(400, '迁移预览仅支持产品 UUID')
        schema = request.app.state.product_master_schema
        preview_store = getattr(request.app.state, 'product_master_preview_store', None)
        if preview_store:
            saved = await preview_store.get(product_id)
            if saved:
                return {**await finance_detail(saved, preview_store, schema, permissions), 'previewMode': True, 'pendingAssetFields': []}
        if getattr(request.app.state.settings, 'product_master_web_only', False):
            raise HTTPException(404, '当前 Web 测试库不包含此产品')
        rows = (await request.app.state.filemaker_client.find_records(
            request.app.state.settings.product_master_layout,
            {'ID': f'=={product_id}'}, limit=2))['data']
        if not rows:
            raise HTTPException(404, '产品不存在')
        if len(rows) != 1 or UUID(rows[0]['fieldData']['ID']) != product_id:
            raise HTTPException(409, '产品身份不唯一，暂不能显示')
        import_error = None
        if preview_store:
            from app.services.product_master.importer import import_product
            try:
                saved = await import_product(preview_store, schema, request.app.state.filemaker_client,
                    request.app.state.cos_storage_service, request.app.state.settings, rows[0])
                return {**await finance_detail(saved, preview_store, schema, permissions), 'previewMode': True, 'pendingAssetFields': []}
            except Exception:
                import_error = '当前产品的附件复制或校验未完成，请重试；原文件仍保留。'
        fields = schema.filter_fields(rows[0]['fieldData'], permissions)
        containers = {f['name'] for f in schema.visible(permissions) if f['result'] == 'container'}
        return {'id': str(product_id), 'version': 0, 'previewMode': True,
                'fields': {k: v for k, v in fields.items() if k not in containers},
                'assets': [], 'assetImportError': import_error, 'pendingAssetFields': [k for k in containers if fields.get(k)]}
    store, schema = runtime(request)
    result = await store.get(ref)
    if not result:
        raise HTTPException(404, '产品不存在')
    return await finance_detail(result, store, schema, permissions)


async def check_filemaker_sku(request, sku, product_id):
    # Until the complete Web replica is certified, also check unmigrated products.
    try:
        rows = (await request.app.state.filemaker_client.find_records(
            request.app.state.settings.product_master_layout,
            {'product_sku': '==' + sku}, limit=2))['data']
        if any(UUID(str(row['fieldData'].get('ID') or '')) != product_id for row in rows):
            raise SKUValidationError('SKU_DUPLICATE', 'SKU 已被其他产品使用，请修改后保存。')
    except SKUValidationError:
        raise
    except Exception as exc:
        raise HTTPException(503, {'code': 'SKU_CHECK_UNAVAILABLE', 'field': 'product_sku',
            'message': '暂时无法完成 SKU 重复校验，本次未保存，请稍后重试。'}) from exc


async def commit(request, context, product_id, body, origin='web', connection=None, command=None, permission='canEditProducts', defaults=None, check_sku=True):
    store, schema = runtime(request)
    permissions = access(context, permission)
    access(context, 'canViewProducts')
    try:
        value = await store.save(product_id=product_id, expected_version=body.expectedVersion,
            request_id=body.requestId, changes=body.changes, assets=body.assets,
            actor=actor(context), schema=schema, permissions=permissions, origin=origin, connection=connection, command=command,
            sku_validator=(lambda sku, pid: check_filemaker_sku(request, sku, pid)) if check_sku else None, defaults=defaults)
        return await finance_detail(value, store, schema, permissions)
    except SKUValidationError as exc:
        raise HTTPException(422, {'code': exc.code, 'field': 'product_sku', 'message': str(exc)}) from exc
    except Conflict as exc:
        # The snapshot carries UUID/datetime values that a plain JSON response cannot encode.
        raise HTTPException(409, jsonable_encoder({'message': str(exc), 'current': filtered(exc.current or {}, schema, permissions)})) from exc
    except ProductLocked as exc:
        raise HTTPException(423, str(exc)) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, str(exc)) from exc


async def command_replay(request,context,product_id,request_id,origin,command):
    store,schema=runtime(request)
    row=unpack(await store.pool.fetchrow('SELECT * FROM pm_revision WHERE source=$1 AND request_id=$2',store.source,request_id))
    if row is None:return None
    digest=request_digest(product_id,None,None,None,actor(context),origin,command)
    if row['request_hash']!=digest:raise HTTPException(409,'幂等标识已用于其他操作')
    return filtered(row['after_data'],schema,context.get('access',{}))


@router.post('/products')
async def create_product(body: SaveBody, request: Request, context=Depends(get_webviewer_session_context)):
    store, schema = runtime(request)
    if body.expectedVersion != 0:
        raise HTTPException(422, '新产品版本必须为 0')
    # Generated on the server, repeatable only for the same create request.
    product_id = uuid5(NAMESPACE_URL, f'{store.source}:product:{body.requestId}')
    # FileMaker's auto-enter gave new products 未審核; the Web store has to do the same because 审核 is not editable in the form.
    defaults = {'審核': '未審核'} if '審核' in schema.fields else None
    return await commit(request, context, product_id, body, defaults=defaults)


@router.patch('/products/{product_id}')
async def save_product(product_id: UUID, body: SaveBody, request: Request, context=Depends(get_webviewer_session_context)):
    store,_=runtime(request)
    if body.expectedVersion<1 or not await store.get(product_id): raise HTTPException(404,'请使用新建接口由 Web 生成产品 UUID')
    return await commit(request, context, product_id, body)


@router.post('/products/{product_id}/review')
async def review_product(product_id: UUID, body: ReviewBody, request: Request, context=Depends(get_webviewer_session_context)):
    """Approve (or withdraw approval of) a saved product. Needs canApproveProducts, not canEditProducts."""
    store, schema = runtime(request)
    access(context, 'canApproveProducts')
    if '審核' not in schema.fields:
        raise HTTPException(404, '此产品库没有审核字段')
    if not await store.get(product_id):
        raise HTTPException(404, '产品不存在')
    command = {'operation': 'review', 'status': body.status, 'expectedVersion': body.expectedVersion}
    replay = await command_replay(request, context, product_id, body.requestId, 'review', command)
    if replay is not None:
        return replay
    save = SaveBody(requestId=body.requestId, expectedVersion=body.expectedVersion, changes={'審核': body.status}, assets=None)
    return await commit(request, context, product_id, save, origin='review', command=command, permission='canApproveProducts', check_sku=False)


@router.get('/products/{product_id}/history')
async def history(product_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    store, schema = runtime(request)
    permissions = access(context, 'canViewProducts')
    rows = await store.history(product_id)
    for row in rows:
        row['before_data'] = filtered(row['before_data'], schema, permissions)
        row['after_data'] = filtered(row['after_data'], schema, permissions)
    return {'rows': rows}


@router.post('/products/{product_id}/restore/{version}')
async def restore(product_id: UUID, version: int, body: SaveBody, request: Request, context=Depends(get_webviewer_session_context)):
    store, schema = runtime(request)
    permissions = access(context, 'canEditProducts')
    command={'operation':'restore','version':version,'expectedVersion':body.expectedVersion}
    replay=await command_replay(request,context,product_id,body.requestId,f'restore:{version}',command)
    if replay is not None:return replay
    rows = await store.history(product_id)
    target = next((r['after_data'] for r in rows if r['version'] == version), None)
    if not target:
        raise HTTPException(404, '历史版本不存在')
    current = await store.get(product_id)
    # Restore is a new transaction. Protected fields cannot be restored indirectly.
    body.changes = {k: v for k, v in target['fields'].items() if schema.editable(k) and schema.fields[k]['result'] != 'container' and current['fields'].get(k) != v
                    and permissions.get(schema.fields[k].get('writePermission', 'canEditProducts'), False)}
    body.assets = target['assets']
    return await commit(request, context, product_id, body, origin=f'restore:{version}',command=command)


async def presign_impl(product_id, body, request, context, connection=None):
    store, schema = runtime(request)
    permissions = access(context, 'canEditProducts')
    try:
        schema.slot(body.field, body.repetition, permissions)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    product = await store.get(product_id, connection)
    if not product:
        raise HTTPException(404, '请先保存产品，再上传附件')
    if product['fields'].get('審核') == '已審核':
        raise HTTPException(423, LOCKED_MESSAGE)
    settings = request.app.state.settings
    if body.size > settings.product_master_max_file_bytes:
        raise HTTPException(413, '文件超过大小限制')
    account = actor(context)['account']
    upload_id = uuid5(product_id, str(body.requestId))
    previous_asset = next((a for a in product['assets'] if a['field'] == body.field and a['repetition'] == body.repetition), {})
    metadata = {'assetId': previous_asset.get('assetId') or str(upload_id), 'filename': body.filename, 'mimeType': body.mimeType, 'size': body.size, 'sha256': body.sha256,
                'field': body.field, 'repetition': body.repetition,
                'stagingKey': f'product-master/{store.source}/staging/{upload_id}',
                'objectKey': f'product-master/{store.source}/{product_id}/{upload_id}/{body.sha256}'}
    async with connection_for(store, connection) as c, c.transaction():
        await c.execute('''INSERT INTO pm_upload(source,id,product_id,request_id,actor,metadata)
            VALUES($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT(source,request_id) DO NOTHING''', store.source, upload_id, product_id, body.requestId, account, dumps(metadata))
        existing = unpack(await c.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND request_id=$2', store.source, body.requestId))
        if {k: v for k, v in existing['metadata'].items() if k not in {'pdaSession', 'pdaActor'}} != metadata or existing['actor'] != account or existing['product_id'] != product_id:
            raise HTTPException(409, '上传幂等标识已用于其他请求')
    signed = await asyncio.to_thread(request.app.state.cos_storage_service.create_presigned_upload, object_key=metadata['stagingKey'], content_type=body.mimeType)
    return {'id': str(upload_id), 'url': signed.upload_url, 'headers': signed.headers}


@router.post('/products/{product_id}/uploads')
async def presign(product_id: UUID, body: UploadBody, request: Request, context=Depends(get_webviewer_session_context)):
    return await presign_impl(product_id,body,request,context)


@router.post('/products/{product_id}/uploads/{upload_id}/complete')
async def complete_upload(product_id: UUID, upload_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    store, schema = runtime(request)
    permissions = access(context, 'canEditProducts')
    row = unpack(await store.pool.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND id=$2 AND product_id=$3', store.source, upload_id, product_id))
    if not row or row['actor'] != actor(context)['account']:
        raise HTTPException(404, '上传不存在')
    m = row['metadata']; schema.slot(m['field'], m['repetition'], permissions)
    storage = request.app.state.cos_storage_service
    if not row['ready']:
        content = await asyncio.to_thread(storage.get_object_bytes, m['stagingKey'], max_bytes=request.app.state.settings.product_master_max_file_bytes)
        if len(content) != m['size'] or hashlib.sha256(content).hexdigest() != m['sha256']:
            raise HTTPException(422, '文件大小或摘要不一致')
        try:
            if m['mimeType'].startswith('image/'):
                with Image.open(BytesIO(content)) as im:
                    if Image.MIME.get(im.format) != m['mimeType']:
                        raise ValueError('Image MIME mismatch')
                    im.verify()
            elif m['mimeType'] == 'application/pdf' and not content.startswith(b'%PDF-'):
                raise ValueError('Invalid PDF')
        except Exception as exc:
            raise HTTPException(422, '文件内容与格式不匹配') from exc
        # Upload URL only grants access to staging; saved immutable bytes cannot be overwritten.
        await asyncio.to_thread(storage.put_object, object_key=m['objectKey'], content=content, content_type=m['mimeType'])
        verified = await asyncio.to_thread(storage.get_object_bytes, m['objectKey'], max_bytes=m['size'])
        if hashlib.sha256(verified).hexdigest() != m['sha256']:
            raise HTTPException(502, 'COS 文件校验失败')
        await store.pool.execute('UPDATE pm_upload SET ready=true WHERE source=$1 AND id=$2', store.source, upload_id)
    return {'id': str(upload_id), **{k: v for k, v in m.items() if k != 'stagingKey'}}


@router.get('/products/{product_id}/assets/{upload_id}')
async def download(product_id: UUID, upload_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    permissions = access(context, 'canViewProducts')
    if preview_only(request):
        store = getattr(request.app.state, 'product_master_preview_store', None)
        schema = request.app.state.product_master_schema
        if not store:
            raise HTTPException(503, '附件副本尚未就绪')
    else:
        store, schema = runtime(request)
    # Includes historical attachments, but never unattached staged uploads.
    version = await store.pool.fetchrow('SELECT * FROM pm_asset_version WHERE source=$1 AND id=$2 AND product_id=$3',store.source,upload_id,product_id)
    rows = await store.history(product_id)
    binding = next((a for r in rows for a in r['after_data']['assets'] if a['id'] == str(upload_id)), None)
    found = ({**binding, 'objectKey':version['object_key'], 'mimeType':version['mime_type'], 'filename':version['filename']}
             if version and binding else binding)
    if not found or canonical_container_field(found['field']) not in {f['name'] for f in schema.visible(permissions)}:
        raise HTTPException(404, '附件不存在')
    content = await asyncio.to_thread(request.app.state.cos_storage_service.get_object_bytes, found['objectKey'], max_bytes=request.app.state.settings.product_master_max_file_bytes)
    inline = found['mimeType'] in {'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'application/pdf'}
    return Response(content, media_type=found['mimeType'], headers={'Content-Disposition': f'{"inline" if inline else "attachment"}; filename*=UTF-8\'\'{quote(found["filename"])}', 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store', 'Content-Security-Policy': "sandbox"})


@router.get('/products/{product_id}/status')
async def sync_status(product_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    access(context, 'canViewProducts')
    if preview_only(request):
        return {'previewMode': True, 'writeEnabled': False, 'filemaker': [], 'dms': []}
    store, _ = runtime(request)
    consumers = await store.pool.fetch('''SELECT consumer,cursor,updated_at FROM pm_consumer WHERE source=$1''', store.source)
    sequence = await store.pool.fetchval('SELECT max(sequence) FROM pm_publication WHERE source=$1 AND product_id=$2', store.source, product_id)
    drift = [unpack(r) for r in await store.pool.fetch('SELECT * FROM pm_drift WHERE source=$1 AND product_id=$2 AND NOT resolved ORDER BY id DESC LIMIT 20', store.source, product_id)]
    return {'writeEnabled': getattr(request.app.state.settings,'product_master_write_enabled',False), 'drift': drift, 'filemaker': await store.jobs(product_id), 'dms': [{**dict(c), 'synced': c['cursor'] >= (sequence or 0)} for c in consumers]}


@router.post('/products/{product_id}/retry/{version}')
async def retry(product_id: UUID, version: int, body: ActionBody, request: Request, context=Depends(get_webviewer_session_context)):
    access(context, 'canManageProductSync'); store, _ = runtime(request)
    # Conflict resolution is a separate audited action. No unaudited force flag.
    async with store.pool.acquire() as c, c.transaction():
        await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))','pm-action:'+store.source+str(body.requestId))
        previous=unpack(await c.fetchrow("SELECT * FROM pm_drift WHERE source=$1 AND observed->>'requestId'=$2",store.source,str(body.requestId)))
        if previous:
            observed=previous['observed']
            if previous['product_id']!=product_id or observed.get('version')!=version or observed.get('reason')!=body.reason or observed.get('actor',{}).get('account')!=actor(context)['account']:
                raise HTTPException(409,'幂等标识已用于其他操作')
            return {'status':'pending'}
        row = await c.fetchrow('SELECT * FROM pm_job WHERE source=$1 AND product_id=$2 AND version=$3 FOR UPDATE', store.source, product_id, version)
        if not row:
            raise HTTPException(404, '任务不存在')
        if row['status'] == 'synced':
            return {'status': 'synced'}
        await c.execute('INSERT INTO pm_drift(source,product_id,observed,resolved) VALUES($1,$2,$3::jsonb,true)', store.source, product_id, dumps({'requestId': str(body.requestId), 'actor': actor(context), 'action': 'retry-web-version', 'reason': body.reason, 'version': version}))
        await c.execute("UPDATE pm_job SET status='pending',steps=$4::jsonb,next_attempt_at=now(),error=NULL WHERE source=$1 AND product_id=$2 AND version=$3", store.source, product_id, version, dumps({'force': True}))
    return {'status': 'pending'}


def consumer_auth(request):
    # Publishing the read-only Web store must not enable editing or FM writeback.
    store = getattr(request.app.state, 'product_master_store', None)
    if store is None and request.app.state.settings.product_master_web_only:
        store = getattr(request.app.state, 'product_master_preview_store', None)
    if store is None:
        raise HTTPException(503, '产品主库尚未启用')
    schema = request.app.state.product_master_schema
    settings = request.app.state.settings
    consumers = json.loads(settings.product_master_consumers_json)
    consumer = request.headers.get('X-Product-Consumer', '')
    supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
    entry = consumers.get(consumer, '')
    expected = entry.get('token', '') if isinstance(entry, dict) else entry
    if not expected or len(expected) < 32 or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, 'Invalid product consumer')
    if request.headers.get('X-Product-Source') != store.source:
        raise HTTPException(403, 'Product source mismatch')
    return store, schema, consumer


@router.get('/changes')
async def changes(request: Request, cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    store, schema, consumer = consumer_auth(request)
    maximum=await store.pool.fetchval('SELECT coalesce(max(sequence),0) FROM pm_publication WHERE source=$1',store.source)
    if cursor>maximum: raise HTTPException(422,'发布游标超出范围')
    rows = await store.feed(cursor, limit=limit)
    allowed = {f['name'] for f in schema.fields.values() if f.get('publish', False)}
    for row in rows:
        payload = row['payload']
        payload['fields'] = {k: v for k, v in payload['fields'].items() if k in allowed}
        from datetime import datetime
        payload['sortValues']={}
        for name,value in payload['fields'].items():
            if schema.fields[name]['result'] in {'date','timestamp'} and value:
                for pattern in ('%m/%d/%Y %H:%M:%S','%m/%d/%Y','%Y-%m-%dT%H:%M:%S','%Y-%m-%d'):
                    try: payload['sortValues'][name]=datetime.strptime(str(value),pattern).isoformat();break
                    except ValueError: pass
        payload['fieldPermissions'] = {name: schema.fields[name].get('readPermission','canViewProducts') for name in allowed}
        payload['assets'] = [{k: v for k, v in a.items() if k != 'stagingKey'} for a in payload['assets'] if a['field'] in allowed]
    entry = json.loads(request.app.state.settings.product_master_consumers_json).get(consumer)
    if isinstance(entry, dict) and entry.get('profile') == 'dms-catalog':
        from app.services.product_catalog_contract import catalog_snapshot
        for row in rows:
            row['payload'] = catalog_snapshot(row['payload'])
    fingerprint = hashlib.sha256((request.app.state.settings.filemaker_host.rstrip('/').lower() + '|' + request.app.state.settings.filemaker_database).encode()).hexdigest()
    return {'source': store.source, 'fingerprint': fingerprint, 'events': rows, 'caughtUp': len(rows) < limit, 'cursor': rows[-1]['sequence'] if rows else cursor}


@router.post('/changes/ack')
async def acknowledge(request: Request, cursor: int = Query(ge=0)):
    store, _, consumer = consumer_auth(request)
    maximum = await store.pool.fetchval('SELECT coalesce(max(sequence),0) FROM pm_publication WHERE source=$1', store.source)
    if cursor > maximum:
        raise HTTPException(422, 'Invalid cursor')
    await store.pool.execute('''INSERT INTO pm_consumer(source,consumer,cursor) VALUES($1,$2,$3)
      ON CONFLICT(source,consumer) DO UPDATE SET cursor=greatest(pm_consumer.cursor,EXCLUDED.cursor),updated_at=now()''', store.source, consumer, cursor)
    return {'cursor': cursor}

class AdoptBody(ActionBody):
    fields: list[str] = Field(min_length=1)
    expectedVersion: int = Field(ge=1)


@router.post('/products/{product_id}/adopt-filemaker')
async def adopt_filemaker(product_id: UUID, body: AdoptBody, request: Request, context=Depends(get_webviewer_session_context)):
    """Explicitly copy selected native changes into a NEW Web revision, preserving originals."""
    from app.services.product_master.worker import download_container, value_at
    store, schema = runtime(request)
    permissions = access(context, 'canManageProductSync')
    access(context, 'canEditProducts')
    command={'operation':'adopt','fields':body.fields,'expectedVersion':body.expectedVersion,'reason':body.reason}
    replay=await command_replay(request,context,product_id,body.requestId,'adopt-filemaker: '+body.reason,command)
    if replay is not None:return replay
    current = await store.get(product_id)
    if not current: raise HTTPException(404, '产品不存在')
    rows = (await request.app.state.filemaker_client.find_records(request.app.state.settings.product_master_layout, {'ID':f'=={product_id}'},limit=2))['data']
    if len(rows)!=1 or str(rows[0]['recordId'])!=current['fm_record_id']:
        raise HTTPException(409, 'FileMaker 产品身份不一致')
    remote = rows[0]; updates={}; attachments=list(current['assets'])
    for name in body.fields:
        field=schema.fields.get(name)
        if not field or not schema.editable(name): raise HTTPException(422, '所选字段不可编辑')
        if field['result']!='container':
            updates[name]=remote['fieldData'].get(name,'')
            continue
        for repetition in range(1,int(field.get('maxRepeat',1))+1):
            schema.slot(name,repetition,permissions)
            url=value_at(remote['fieldData'],name,repetition)
            previous=next((a for a in attachments if a['field']==name and a['repetition']==repetition),{})
            attachments=[a for a in attachments if a['field']!=name or a['repetition']!=repetition]
            if not url: continue
            content,mime=await download_container(request.app.state.filemaker_client,url,request.app.state.settings.product_master_max_file_bytes)
            sha=hashlib.sha256(content).hexdigest();uid=uuid5(body.requestId,f'{name}:{repetition}:{sha}')
            key=f'product-master/{store.source}/{product_id}/{uid}/{sha}'
            storage=request.app.state.cos_storage_service
            await asyncio.to_thread(storage.put_object,object_key=key,content=content,content_type=mime)
            checked=await asyncio.to_thread(storage.get_object_bytes,key,max_bytes=len(content))
            if hashlib.sha256(checked).hexdigest()!=sha:raise HTTPException(502,'COS 校验失败')
            metadata={'assetId':previous.get('assetId',str(uid)),'objectKey':key,'filename':previous.get('filename',name),'mimeType':mime,'sha256':sha,'size':len(content)}
            await store.pool.execute('''INSERT INTO pm_upload(source,id,product_id,request_id,actor,metadata,ready)
                VALUES($1,$2,$3,$2,$4,$5::jsonb,true) ON CONFLICT(source,id) DO NOTHING''',store.source,uid,product_id,actor(context)['account'],dumps(metadata))
            attachments.append({'id':str(uid),'field':name,'repetition':repetition})
    check=(await request.app.state.filemaker_client.get_record(request.app.state.settings.product_master_layout,current['fm_record_id']))[0]
    if str(check['modId'])!=str(remote['modId']):raise HTTPException(409,'FileMaker 在导入期间发生修改，请重试')
    return await commit(request,context,product_id,SaveBody(requestId=body.requestId,expectedVersion=body.expectedVersion,changes=updates,assets=attachments),origin='adopt-filemaker: '+body.reason,command=command)


@router.post('/products/{product_id}/rewrite-filemaker')
async def rewrite_filemaker(product_id: UUID, body: ActionBody, request: Request, context=Depends(get_webviewer_session_context)):
    access(context,'canManageProductSync')
    store,schema=runtime(request)
    current=await store.get(product_id)
    if not current:raise HTTPException(404,'产品不存在')
    command={'operation':'rewrite','reason':body.reason}
    replay=await command_replay(request,context,product_id,body.requestId,'rewrite-filemaker: '+body.reason,command)
    async with store.pool.acquire() as c:
        key=f'pm-worker:{store.source}:{product_id}'
        await c.execute('SELECT pg_advisory_lock(hashtextextended($1,0))',key)
        try:
            rows=await c.fetch('SELECT product_id,version,request_id FROM pm_revision WHERE source=$1 AND request_id=$2',store.source,body.requestId)
            if rows:
                if rows[0]['product_id']!=product_id: raise HTTPException(409,'幂等标识已用于其他产品')
                version=rows[0]['version']
            else:
                result=await commit(request,context,product_id,SaveBody(requestId=body.requestId,expectedVersion=current['version']),origin='rewrite-filemaker: '+body.reason,connection=c,command=command)
                version=result['version']
            async with c.transaction():
                await c.execute("UPDATE pm_job SET status='superseded' WHERE source=$1 AND product_id=$2 AND version<$3 AND status<>'synced'",store.source,product_id,version)
                await c.execute("UPDATE pm_job SET status='pending',steps='{" + '"force":true' + "}'::jsonb,next_attempt_at=now(),error=NULL WHERE source=$1 AND product_id=$2 AND version=$3 AND status<>'synced'",store.source,product_id,version)
                await c.execute('UPDATE pm_drift SET resolved=true WHERE source=$1 AND product_id=$2',store.source,product_id)
            return {'status':'pending','version':version}
        finally:
            await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)

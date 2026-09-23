"""Internal group quote maintenance, independent of product synchronization."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from app.api.product_master import access, actor
from app.services.dependencies import get_webviewer_session_context
from app.services.product_master.options import customer_options
from app.services.product_master.quotes import QuoteStore
from app.services.product_master.store import Conflict

router = APIRouter(prefix='/product-master', tags=['product-quotes'])


class QuoteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: UUID
    expectedVersion: int = Field(ge=0, strict=True)
    title: StrictStr = Field(min_length=1, max_length=200)
    amount: StrictStr = Field(min_length=1, max_length=80)
    currency: StrictStr
    enabled: StrictBool = True
    customerIds: list[StrictStr] = Field(min_length=1, max_length=5000)


async def quote_runtime(request, context, product_id, *, write=False):
    # Use the same administrator boundary as /webviewer/admin/* endpoints.
    access(context, 'canManageAccounts')
    access(context, 'canViewProducts')
    access(context, 'canViewPrice')
    if write:
        access(context, 'canEditProductPrices')
        if not getattr(request.app.state.settings, 'product_quote_write_enabled', False):
            raise HTTPException(403, '客户群报价尚未开放保存')
    store = getattr(request.app.state, 'product_master_store', None)
    if not store:
        store = getattr(request.app.state, 'product_master_preview_store', None)
    if not store:
        raise HTTPException(503, '产品主库尚未启用')
    # UUID-only lookup: no SKU/record-id aliases for write targets.
    if not await store.pool.fetchval('SELECT 1 FROM pm_product WHERE source=$1 AND id=$2', store.source, product_id):
        raise HTTPException(404, '产品不存在')
    return QuoteStore(store)


@router.get('/products/{product_id}/quotes')
async def list_quotes(product_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    store = await quote_runtime(request, context, product_id)
    writable = bool(request.app.state.settings.product_quote_write_enabled
                    and context.get('access', {}).get('canEditProductPrices'))
    return {'rows': await store.list(product_id), 'writeEnabled': writable}


@router.get('/products/{product_id}/quotes/{quote_id}/history')
async def quote_history(product_id: UUID, quote_id: UUID, request: Request, context=Depends(get_webviewer_session_context)):
    store = await quote_runtime(request, context, product_id)
    try:
        return {'rows': await store.history(product_id, quote_id)}
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


async def write_quote(product_id, quote_id, body, request, context):
    store = await quote_runtime(request, context, product_id, write=True)
    try:
        directory = await customer_options(request)
    except Exception as exc:
        raise HTTPException(503, '客户目录读取失败，请稍后重试') from exc
    try:
        return await store.save(product_id=product_id, quote_id=quote_id, expected_version=body.expectedVersion,
                                request_id=body.requestId, data=body.model_dump(exclude={'requestId', 'expectedVersion'}),
                                actor=actor(context), directory=directory)
    except Conflict as exc:
        raise HTTPException(409, {'message': str(exc), 'current': exc.current}) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/products/{product_id}/quotes', status_code=201)
async def create_quote(product_id: UUID, body: QuoteBody, request: Request, context=Depends(get_webviewer_session_context)):
    return await write_quote(product_id, None, body, request, context)


@router.patch('/products/{product_id}/quotes/{quote_id}')
async def update_quote(product_id: UUID, quote_id: UUID, body: QuoteBody, request: Request, context=Depends(get_webviewer_session_context)):
    return await write_quote(product_id, quote_id, body, request, context)

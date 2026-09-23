"""Administrator-only, read-only customer profiles from the Web snapshot."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from app.services.dependencies import get_webviewer_session_context
from app.services.product_master.customer_sync import FIELDS
from app.services.product_master.quotes import decode

router = APIRouter(prefix='/admin/customers', tags=['customer-directory'])


async def runtime(request, context, response):
    response.headers['Cache-Control'] = 'no-store'
    if not context.get('access', {}).get('canManageAccounts'):
        raise HTTPException(403, '仅管理员可查看客户资料', headers={'Cache-Control': 'no-store'})
    store = getattr(request.app.state, 'product_master_store', None) or getattr(request.app.state, 'product_master_preview_store', None)
    if not store or not await store.pool.fetchval("SELECT to_regclass('public.pm_customer')"):
        raise HTTPException(503, '客户资料尚未导入')
    return store


def summary(row):
    f = decode(row['fields'])
    issues = decode(row['issues'])
    name = next((str(value).strip() for value in (f.get('客戶公司簡稱'), f.get('公司'), f.get('客戶代號'), row['id'])
                 if value is not None and str(value).strip()), row['id'])
    return {'id': row['id'], 'code': f.get('客戶代號'),
            'name': name,
            'company': f.get('公司'), 'country': f.get('國家/地區'), 'owner': f.get('業務負責人'),
            'status': 'missing' if row['source_missing'] else 'incomplete' if issues else 'ready',
            'issues': issues, 'updatedAt': row['updated_at'], 'version': row['version']}


@router.get('')
async def list_customers(request: Request, response: Response, q: str = Query('', max_length=100),
                         status: Literal['all', 'ready', 'incomplete', 'missing'] = 'all',
                         page: int = Query(1, ge=1, le=100000), context=Depends(get_webviewer_session_context)):
    store = await runtime(request, context, response)
    where = """source=$1 AND ($2='' OR strpos(lower(concat_ws(' ',id,fields->>'客戶代號',
       fields->>'客戶公司簡稱',fields->>'公司',fields->>'國家/地區',fields->>'業務負責人')),$2)>0)
       AND ($3='all' OR ($3='missing' AND source_missing)
       OR ($3='ready' AND NOT source_missing AND issues='[]'::jsonb)
       OR ($3='incomplete' AND NOT source_missing AND issues<>'[]'::jsonb))"""
    async with store.pool.acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
        args = (store.source, q.strip().lower(), status)
        total = await c.fetchval('SELECT count(*) FROM pm_customer WHERE '+where, *args)
        rows = await c.fetch('SELECT * FROM pm_customer WHERE '+where+" ORDER BY fields->>'客戶代號',id LIMIT 50 OFFSET $4", *args, (page-1)*50)
        last_sync = await c.fetchval('SELECT max(created_at) FROM pm_customer_sync WHERE source=$1', store.source)
    return {'rows': [summary(r) for r in rows], 'total': total, 'page': page, 'pageSize': 50, 'lastSyncAt': last_sync}


@router.get('/{customer_id}')
async def customer_detail(customer_id: str, request: Request, response: Response, context=Depends(get_webviewer_session_context)):
    store = await runtime(request, context, response)
    row = await store.pool.fetchrow('SELECT * FROM pm_customer WHERE source=$1 AND id=$2', store.source, customer_id)
    if not row:
        raise HTTPException(404, '客户不存在')
    fields = decode(row['fields'])
    last_sync = await store.pool.fetchval('SELECT max(created_at) FROM pm_customer_sync WHERE source=$1', store.source)
    return {**summary(row), 'fields': {f: fields.get(f) for f in FIELDS}, 'lastSyncAt': last_sync}

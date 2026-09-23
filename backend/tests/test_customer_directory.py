from types import SimpleNamespace
from uuid import uuid4
import os
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api.customer_directory import router
from app.services.dependencies import get_webviewer_session_context
from app.services.product_master.store import ProductStore, dumps
from app.services.product_master.customer_sync import DDL, FIELDS


def application(store, access):
    app = FastAPI(); app.include_router(router, prefix='/api')
    app.state.product_master_preview_store = store
    app.dependency_overrides[get_webviewer_session_context] = lambda: {'access': access}
    return app


@pytest.mark.asyncio
async def test_non_admin_denied_before_data_lookup():
    app = application(None, {'canViewProducts': True, 'canViewPrice': True})
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as c:
        for path in ('/api/admin/customers', '/api/admin/customers/CU1'):
            r = await c.get(path)
            assert r.status_code == 403 and r.headers['cache-control'] == 'no-store'


@pytest_asyncio.fixture
async def store():
    url = os.environ.get('PRODUCT_MASTER_TEST_DATABASE_URL')
    if not url: pytest.skip('Requires isolated test database')
    s = ProductStore(url, 'customer-page-' + str(uuid4()), 'f'); await s.init(); await s.pool.execute(DDL)
    for i in range(52):
        f = {k: '' for k in FIELDS}; f.update({'客戶代號': f'{i:03}', '客戶公司簡稱': f'客户{i}', '公司': 'ACME 100%' if i == 0 else '公司', '聯絡人郵件': 'private@example.test', 'unexpected': 'hidden'})
        await s.pool.execute('INSERT INTO pm_customer(source,id,fields,issues,source_missing,version) VALUES($1,$2,$3::jsonb,$4::jsonb,$5,1)',s.source,f'CU{i}',dumps(f),dumps(['简称缺失'] if i == 1 else []),i == 2)
    yield s
    await s.pool.execute('DELETE FROM pm_customer WHERE source=$1',s.source)
    await s.pool.execute('DELETE FROM pm_source WHERE source=$1',s.source)
    await s.close()


@pytest.mark.asyncio
async def test_admin_pagination_literal_search_filters_and_private_detail(store):
    async with AsyncClient(transport=ASGITransport(application(store, {'canManageAccounts': True})), base_url='http://test') as c:
        r = await c.get('/api/admin/customers')
        assert r.status_code == 200 and r.headers['cache-control'] == 'no-store'
        assert r.json()['total'] == 52 and len(r.json()['rows']) == 50
        assert 'private@example.test' not in r.text and 'unexpected' not in r.text
        assert len((await c.get('/api/admin/customers?page=2')).json()['rows']) == 2
        assert (await c.get('/api/admin/customers?q=%25')).json()['total'] == 1
        assert (await c.get('/api/admin/customers?status=incomplete')).json()['total'] == 1
        assert (await c.get('/api/admin/customers?status=missing')).json()['total'] == 1
        assert (await c.get('/api/admin/customers?status=ready')).json()['total'] == 50
        detail = (await c.get('/api/admin/customers/CU0')).json()
        assert len(detail['fields']) == 19 and detail['fields']['聯絡人郵件'] == 'private@example.test'
        assert 'unexpected' not in detail['fields']
        assert (await c.get('/api/admin/customers/missing')).status_code == 404
        assert (await c.get('/api/admin/customers?page=0')).status_code == 422
        assert (await c.post('/api/admin/customers',json={})).status_code == 405


@pytest.mark.asyncio
async def test_customers_are_isolated_by_source(store):
    other = SimpleNamespace(pool=store.pool, source='other-source')
    async with AsyncClient(transport=ASGITransport(application(other, {'canManageAccounts': True})), base_url='http://test') as c:
        assert (await c.get('/api/admin/customers')).json()['total'] == 0
        assert (await c.get('/api/admin/customers/CU0')).status_code == 404


@pytest.mark.asyncio
async def test_anonymous_denied():
    app = FastAPI(); app.include_router(router, prefix='/api'); app.state.settings = SimpleNamespace()
    async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as c:
        for path in ('/api/admin/customers', '/api/admin/customers/CU0'):
            assert (await c.get(path)).status_code == 401

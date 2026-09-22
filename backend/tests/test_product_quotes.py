import asyncio
import json
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.product_quotes import router
from app.services.dependencies import get_webviewer_session_context
from app.services.product_master.quote_import import preflight, scan_quotes
from app.services.product_master.quotes import QuoteStore, amount_text
from app.services.product_master.store import ProductStore, Conflict, dumps

CUSTOMERS = [{'value': 'customer-a', 'name': '客户甲', 'code': '001'}, {'value': 'customer-b', 'name': '客户乙', 'code': '002'}]
DATA = {'title': '经销商组', 'amount': '0.123456789012', 'currency': 'USD', 'enabled': True, 'customerIds': ['customer-a']}
PERMISSIONS = {'canViewProducts': True, 'canViewPrice': True, 'canEditProductPrices': True}


@pytest_asyncio.fixture
async def runtime():
    url = os.environ.get('PRODUCT_MASTER_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requires an isolated PRODUCT_MASTER_TEST_DATABASE_URL')
    product_store = ProductStore(url, 'quote-test-' + str(uuid4()))
    await product_store.init()
    pid = uuid4()
    await product_store.pool.execute('INSERT INTO pm_product(source,id,version,fields) VALUES($1,$2,1,$3::jsonb)',
                                    product_store.source, pid, dumps({'product_sku': 'SKU'}))
    await product_store.pool.execute("INSERT INTO pm_reference(source,name,payload) VALUES($1,'customers',$2::jsonb)", product_store.source, dumps(CUSTOMERS))
    yield product_store, QuoteStore(product_store), pid
    for table in ('pm_quote_revision', 'pm_quote_customer', 'pm_quote', 'pm_reference', 'pm_product', 'pm_source'):
        await product_store.pool.execute(f'DELETE FROM {table} WHERE source=$1', product_store.source)
    await product_store.close()


async def save(store, pid, row=None, data=None, rid=None, **extra):
    return await store.save(product_id=pid, quote_id=row['id'] if row else None,
                            expected_version=row['version'] if row else 0, request_id=rid or uuid4(),
                            data=data or DATA, actor={'account': 'tester'}, directory=CUSTOMERS, **extra)


@pytest.mark.parametrize('value', ['', ' ', '-1', 'NaN', 'Infinity', '1e9999999', '1e-9999999', '1.0000000000001', 0.1, None, True])
def test_rejects_invalid_or_imprecise_amounts(value):
    with pytest.raises(ValueError):
        amount_text(value)


@pytest.mark.asyncio
async def test_exact_amount_members_history_and_no_publication(runtime):
    products, store, pid = runtime
    row = await save(store, pid)
    updated = await save(store, pid, row, {**DATA, 'amount': '12.0001', 'currency': 'CNY',
                                         'enabled': False, 'customerIds': ['customer-b']})
    assert updated['amount'] == '12.0001' and not updated['enabled']
    assert updated['customers'] == [{'id': 'customer-b', 'name': '客户乙', 'code': '002'}]
    history = await store.history(pid, row['id'])
    assert len(history) == 2 and history[0]['before']['amount'] == '0.123456789012'
    assert history[0]['after'] == updated
    for table in ('pm_revision', 'pm_job', 'pm_publication'):
        assert await products.pool.fetchval(f'SELECT count(*) FROM {table} WHERE source=$1', products.source) == 0


@pytest.mark.asyncio
async def test_retries_concurrent_create_and_payload_reuse(runtime):
    _, store, pid = runtime
    rid = uuid4()
    one, two = await asyncio.gather(save(store, pid, rid=rid), save(store, pid, rid=rid))
    assert one == two and len(await store.list(pid)) == 1
    await save(store, pid, one, {**DATA, 'amount': '9'})
    assert await save(store, pid, rid=rid) == one  # exact original response, not latest data
    with pytest.raises(ValueError):
        await save(store, pid, rid=rid, data={**DATA, 'amount': '5'})


@pytest.mark.asyncio
async def test_parallel_update_and_member_rollback(runtime):
    _, store, pid = runtime
    row = await save(store, pid)
    result = await asyncio.gather(save(store, pid, row, {**DATA, 'amount': '2'}),
                                  save(store, pid, row, {**DATA, 'amount': '3'}), return_exceptions=True)
    assert sum(isinstance(r, Conflict) for r in result) == 1
    current = (await store.list(pid))[0]
    with pytest.raises(ValueError):
        await save(store, pid, current, {**DATA, 'customerIds': ['missing']})
    assert (await store.list(pid))[0] == current
    assert len(await store.history(pid, row['id'])) == 2


@pytest.mark.asyncio
async def test_cross_product_and_source_access(runtime):
    products, store, pid = runtime
    row = await save(store, pid)
    other = uuid4()
    await products.pool.execute("INSERT INTO pm_product(source,id,version,fields) VALUES($1,$2,1,'{}')", products.source, other)
    with pytest.raises(LookupError):
        await save(store, other, row)
    with pytest.raises(LookupError):
        await store.history(other, row['id'])
    isolated = QuoteStore(SimpleNamespace(pool=products.pool, source='another-source'))
    assert await isolated.list(pid) == []


@pytest.mark.asyncio
async def test_import_cannot_overwrite_web_edit(runtime):
    _, store, pid = runtime
    sid = str(uuid4())
    original = await save(store, pid, source_id=sid, source_data={'fields': {'status': 'updated @2023'}})
    changed = await save(store, pid, original, {**DATA, 'amount': '100'})
    with pytest.raises(ValueError, match='已导入'):
        await save(store, pid, source_id=sid, source_data={})
    assert (await store.list(pid))[0] == changed
    assert changed['sourceData']['fields']['status'] == 'updated @2023'


@pytest.mark.asyncio
async def test_overlapping_active_quotes_are_serialized(runtime):
    _, store, pid = runtime
    results = await asyncio.gather(save(store, pid), save(store, pid), return_exceptions=True)
    assert sum(isinstance(r, ValueError) for r in results) == 1
    original = (await store.list(pid))[0]
    await save(store, pid, data={**DATA, 'currency': 'TWD'})
    await save(store, pid, original, {**DATA, 'enabled': False})
    await save(store, pid)
    assert len(await store.list(pid)) == 3


@pytest.mark.asyncio
async def test_routes_permissions_switch_and_history(runtime):
    products, _, pid = runtime
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.state.product_master_store = products
    app.state.settings = SimpleNamespace(product_quote_write_enabled=True, product_master_web_only=True)
    context = {'access': dict(PERMISSIONS), 'operator': {'account': 'tester'}}
    app.dependency_overrides[get_webviewer_session_context] = lambda: context
    body = {**DATA, 'requestId': str(uuid4()), 'expectedVersion': 0}
    path = f'/api/product-master/products/{pid}/quotes'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for permission in ('canViewProducts', 'canViewPrice', 'canEditProductPrices'):
            context['access'] = {**PERMISSIONS, permission: False}
            assert (await client.post(path, json=body)).status_code == 403
        context['access'] = dict(PERMISSIONS)
        app.state.settings.product_quote_write_enabled = False
        assert (await client.post(path, json=body)).status_code == 403
        assert not (await client.get(path)).json()['writeEnabled']
        app.state.settings.product_quote_write_enabled = True
        assert (await client.post(path, json={**body, 'amount': 1.2})).status_code == 422
        created = await client.post(path, json=body)
        assert created.status_code == 201, created.text
        qid = created.json()['id']
        context['access']['canViewPrice'] = False
        assert (await client.get(path)).status_code == 403
        assert (await client.get(f'{path}/{qid}/history')).status_code == 403
        context['access'] = dict(PERMISSIONS)
        conflict = await client.patch(f'{path}/{qid}', json={**body, 'requestId': str(uuid4())})
        assert conflict.status_code == 409 and conflict.json()['detail']['current']['id'] == qid
        assert (await client.get(f'{path}/{qid}/history')).json()['rows'][0]['after']['id'] == qid


def source_fixture():
    sid, pid = str(uuid4()), str(uuid4())
    quotes = [{'recordId': '1', 'modId': '1', 'fieldData': {'ID': sid, 'product_id': 'SKU', 'title': 'Group',
               'price': '1.234567890123', 'currency': 'RMB', 'customer': '["001"]', 'status': 'updated @2023'}}]
    members = [{'recordId': '2', 'fieldData': {'ProductPriceID': sid.upper(), 'code': '001', 'name': '旧名称'}}]
    products = [{'id': pid, 'fields': {'product_sku': 'SKU'}}]
    return quotes, members, products


def test_preflight_exact_keys_original_values_and_currency():
    quotes, members, products = source_fixture()
    result = preflight(quotes, members, products, CUSTOMERS)
    assert not result['issues']
    row = result['rows'][0]
    assert row['productId'] == products[0]['id'] and row['data']['currency'] == 'CNY'
    assert row['data']['customerIds'] == ['customer-a']
    assert row['sourceData']['fields'] == quotes[0]['fieldData']
    assert row['sourceData']['members'] == members


@pytest.mark.parametrize('case', ['orphan', 'missing_currency', 'missing_product', 'duplicate_product', 'duplicate_quote',
                                 'duplicate_member', 'missing_customer', 'inconsistent_members', 'overlap'])
def test_preflight_reports_all_ambiguous_data(case):
    quotes, members, products = source_fixture()
    customers = list(CUSTOMERS)
    if case == 'orphan':
        members[0]['fieldData']['ProductPriceID'] = str(uuid4())
    elif case == 'missing_currency':
        quotes[0]['fieldData']['currency'] = ''
    elif case == 'missing_product':
        products = []
    elif case == 'duplicate_product':
        products *= 2
    elif case == 'duplicate_quote':
        quotes *= 2
    elif case == 'duplicate_member':
        members *= 2
    elif case == 'missing_customer':
        customers = []
    elif case == 'inconsistent_members':
        quotes[0]['fieldData']['customer'] = '["002"]'
    elif case == 'overlap':
        sid = str(uuid4())
        quotes.append({'recordId': '3', 'fieldData': {**quotes[0]['fieldData'], 'ID': sid}})
        members.append({'recordId': '4', 'fieldData': {**members[0]['fieldData'], 'ProductPriceID': sid}})
    assert preflight(quotes, members, products, customers)['issues']


@pytest.mark.asyncio
async def test_scan_detects_incomplete_page():
    class FM:
        async def find_records(self, *args, **kwargs):
            return {'foundCount': 2, 'data': []}
    with pytest.raises(ValueError, match='不完整'):
        await scan_quotes(FM(), '@ProductPrice')


@pytest.mark.asyncio
async def test_import_command_preview_apply_verify_and_rerun(runtime, monkeypatch):
    from scripts import product_quotes_import as command
    from app.services.product_master.store import source_fingerprint
    products, store, pid = runtime
    quotes, members, _ = source_fixture()
    settings = SimpleNamespace(product_quote_write_enabled=False, audit_database_url=products.url,
                               product_master_source=products.source, filemaker_host='https://test.invalid', filemaker_database='test')
    await products.pool.execute('INSERT INTO pm_source(source,fingerprint) VALUES($1,$2)', products.source, source_fingerprint(settings))
    class FM:
        def __init__(self, settings): pass
        async def find_records(self, layout, **kwargs):
            rows = quotes if layout == '@ProductPrice' else members
            return {'foundCount': len(rows), 'data': rows}
        async def close(self): pass
    monkeypatch.setattr(command, 'get_settings', lambda: settings)
    monkeypatch.setattr(command, 'ExactFileMakerClient', FM)
    preview = await command.run(SimpleNamespace(apply=False))
    assert not preview['issues'] and not await store.list(pid)
    with pytest.raises(ValueError, match='摘要不一致'):
        await command.run(SimpleNamespace(apply=True, expected_digest='invalid'))
    args = SimpleNamespace(apply=True, expected_digest=preview['digest'])
    result = await command.run(args)
    assert result['complete'] and result['applied'] == result['verified'] == 1
    original = (await store.list(pid))[0]
    edited = await save(store, pid, original, {**DATA, 'amount': '200'})
    rerun = await command.run(args)
    assert rerun['complete'] and rerun['alreadyImported'] == 1 and rerun['applied'] == 0
    assert (await store.list(pid))[0] == edited
    quotes[0]['fieldData']['price'] = '2'
    newer = await command.run(SimpleNamespace(apply=False))
    result = await command.run(SimpleNamespace(apply=True, expected_digest=newer['digest']))
    assert not result['complete'] and '禁止覆盖' in result['issues'][0]['error']
    assert (await store.list(pid))[0] == edited

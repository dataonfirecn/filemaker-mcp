import copy
import json
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.services.product_master.finance import (
    COST_FIELDS, PRICE_FIELDS, FinanceFileMakerClient, amount, cost_snapshot, price_snapshot,
    sync_prices, validate_binding,
)
from app.services.product_master.schema import ProductSchema, ProductValidationError
from app.services.product_master.worker import DriftError


def sample():
    product = {'id': str(uuid4()), 'fm_record_id': '12', 'fields': {'product_sku': 'SKU', '系統產品編號': 'SYSTEM'}}
    price = {'recordId': '31', 'modId': '4', 'fieldData': {'產品編號': 'SYSTEM', 'Price': '1.123456789012', '台灣售價': '32', 'RMB售價': '7', '售價備註': 'preserve'}}
    native = {'recordId': '12', 'modId': '8', 'fieldData': {**product['fields'], '產品 BOM::產品成本': '7.0001', '產品 BOM::計算美金': '1.0002', **{'產品售價::' + k: v for k, v in price['fieldData'].items() if k in PRICE_FIELDS.values()}}}
    return product, native, price


def test_live_costs_use_native_results_and_do_not_include_sale_prices():
    product, native, price = sample()
    product['fields']['opencost'] = '999'
    snapshot = cost_snapshot(product, native)
    assert snapshot['fields'] == {'RMB成本':'7.0001', '美金成本':'1.0002'}
    assert snapshot['calculatedAt']
    native['fieldData']['產品 BOM::計算美金'] = '?'
    snapshot = cost_snapshot(product, native)
    assert snapshot['fields']['美金成本'] == '' and snapshot['issues']['美金成本']
    assert not set(COST_FIELDS) & price_snapshot(product,[price])['fields'].keys()


@pytest.mark.parametrize('bad', ['?', 'NaN', 'Infinity', '-1', '1e999999999', '1e-999999999', True])
def test_invalid_amounts_never_become_zero(bad):
    with pytest.raises(ValueError): amount(bad)
    assert amount('') == '' and amount(0) == '0'


@pytest.mark.parametrize('mode', ['duplicate', 'identity', 'missing', 'relation'])
def test_import_rejects_ambiguous_or_incomplete_binding(mode):
    product, native, price = sample(); rows = [price]
    if mode == 'duplicate':
        rows.append(copy.deepcopy(price))
        with pytest.raises(ValueError): price_snapshot(product, rows)
    elif mode == 'relation':
        price['fieldData']['產品編號']='OTHER'
        with pytest.raises(ValueError): price_snapshot(product, rows)
    else:
        if mode == 'identity': native['recordId']='other'
        if mode == 'missing': del native['fieldData']['產品 BOM::產品成本']
        with pytest.raises(ValueError): cost_snapshot(product,native)


def test_registry_permissions_and_calculated_costs():
    schema = ProductSchema.load('backend/config/product_master_web_schema.json')
    perms = {'canViewPrice': True, 'canEditProductPrices': True}
    for name in COST_FIELDS:
        with pytest.raises(ProductValidationError): schema.validate({name:'9'}, perms)
    with pytest.raises(ProductValidationError): schema.validate({'EX-Price':'9'}, {})
    schema.validate({'EX-Price':'9'}, perms)
    assert not set(PRICE_FIELDS) & schema.filter_fields({'EX-Price':'9'}, {}).keys()
    # Related aliases do not become required fields in the base product API layout.
    schema.validate_layout({'fieldMetaData':[f for f in schema.fields.values() if not f.get('externalSource')]})


class Connection:
    def __init__(self, baseline): self.baseline = copy.deepcopy(baseline)
    async def fetchval(self, query, *args):
        if query.startswith('SELECT EXISTS'): return False
        return json.dumps(self.baseline) if self.baseline else None
    async def execute(self, query, *args): self.baseline = json.loads(args[2])
    @asynccontextmanager
    async def transaction(self): yield


class FM:
    def __init__(self, row): self.row = copy.deepcopy(row); self.writes = []; self.duplicate = False; self.calculated = False; self.timeout = False
    async def find_records(self, *args, **kwargs):
        return {'foundCount': 2 if self.duplicate else 1, 'data':[copy.deepcopy(self.row)]}
    async def get_layout_metadata(self, layout):
        return {'fieldMetaData':[{'name': n, 'result':'number', 'type':'calculation' if self.calculated else 'normal'} for n in PRICE_FIELDS.values()]}
    async def request(self, path, *, method, json_body):
        assert method == 'PATCH' and json_body['modId'] == self.row['modId']
        assert set(json_body['fieldData']) <= set(PRICE_FIELDS.values())
        self.writes.append(json_body); self.row['fieldData'].update(json_body['fieldData']); self.row['modId'] = '5'
        if self.timeout: raise TimeoutError()
        return {'messages':[{'code':'0'}]}
    async def get_record(self, *args): return [copy.deepcopy(self.row)]


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ok','concurrent','duplicate','calculated','timeout'])
async def test_writeback_cas_and_recovery(mode):
    product, native, price = sample(); baseline = price_snapshot(product, [price])
    c, fm, steps = Connection(baseline), FM(price), {}
    before = {**product['fields'], **baseline['fields']}; after = {**before, 'EX-Price':'2.123456789012'}
    checkpoints = []
    async def checkpoint(): checkpoints.append(copy.deepcopy(steps))
    if mode == 'concurrent': fm.row['modId'] = '6'
    if mode == 'duplicate': fm.duplicate = True
    if mode == 'calculated': fm.calculated = True
    if mode in ('concurrent','duplicate','calculated'):
        with pytest.raises(DriftError): await sync_prices(fm,c,'source',product['id'],before,after,steps,checkpoint)
        assert fm.writes == []
        return
    if mode == 'timeout':
        fm.timeout = True
        with pytest.raises(TimeoutError): await sync_prices(fm,c,'source',product['id'],before,after,steps,checkpoint)
        fm.timeout = False
    await sync_prices(fm,c,'source',product['id'],before,after,steps,checkpoint)
    assert len(fm.writes) == 1
    assert fm.writes[0]['fieldData'] == {'Price':'2.123456789012'}
    assert steps['relatedPrices'] and 'relatedPriceIntent' not in steps
    assert c.baseline['price']['modId'] == '5'
    assert fm.row['fieldData']['售價備註'] == 'preserve'
    await sync_prices(fm,c,'source',product['id'],before,after,steps,checkpoint)
    assert len(fm.writes) == 1


@pytest.mark.asyncio
async def test_missing_source_and_identifier_edits_rejected():
    product,native,price=sample(); c=Connection(None)
    with pytest.raises(ValueError): await validate_binding(c,'s',product['id'],{'EX-Price':'3'},product['fields'])
    c.baseline=price_snapshot(product,[price])
    with pytest.raises(ValueError): await validate_binding(c,'s',product['id'],{'product_sku':'OTHER'},product['fields'])


def test_client_keeps_decimal_precision_before_json_rounding():
    response=httpx.Response(200,content=b'{"price":0.123456789012345678901234}')
    value=FinanceFileMakerClient._decode_json(None,response)
    assert value['price']==Decimal('0.123456789012345678901234')

from test_product_master import store, PERMISSIONS
from app.services.product_master.finance import store_snapshot
from app.services.product_master.worker import ProductWorker


@pytest.mark.asyncio
async def test_database_revision_worker_routes_prices_to_their_own_record(store):
    product, native, price = sample(); pid = uuid4(); product['id'] = str(pid)
    baseline = price_snapshot(product, [price])
    registered = ProductSchema.load('backend/config/product_master_web_schema.json')
    names = ['ID', 'product_sku', '系統產品編號', *PRICE_FIELDS, *COST_FIELDS]
    schema = ProductSchema({'fields':[registered.fields[n] for n in names]})
    before = {**product['fields'], **baseline['fields']}
    await store.save(product_id=pid,expected_version=0,request_id=uuid4(),changes=before,assets=None,
        actor={'account':'import'},schema=schema,permissions={},imported={'recordId':'12','modId':'8'})
    await store_snapshot(store.pool,store.source,pid,baseline)
    await store.save(product_id=pid,expected_version=1,request_id=uuid4(),changes={'EX-Price':'8.765432109876'},assets=None,
        actor={'account':'editor'},schema=schema,permissions=PERMISSIONS)
    class RoutedFM(FM):
        def __init__(self):
            super().__init__(price)
            self.base={'recordId':'12','modId':'8','fieldData':{'ID':str(pid),**product['fields']}}
            self.base_writes=[]
        async def find_records(self,layout,*args,**kwargs):
            if layout=='@products_web_api':return {'data':[copy.deepcopy(self.base)],'foundCount':1}
            return await super().find_records(layout,*args,**kwargs)
        async def request(self,path,**kwargs):
            if path.endswith('/records/12'):
                assert not set(kwargs['json_body']['fieldData']) & set(PRICE_FIELDS)
                self.base_writes.append(kwargs['json_body']);self.base['modId']='9'
                self.base['fieldData'].update(kwargs['json_body']['fieldData'])
                return {'response':{'modId':'9'}}
            return await super().request(path,**kwargs)
        async def get_record(self,layout,*args):
            return [copy.deepcopy(self.base)] if layout=='@products_web_api' else await super().get_record(layout,*args)
    fm=RoutedFM(); settings=SimpleNamespace(product_master_layout='@products_web_api',product_master_write_enabled=True)
    await ProductWorker(store,schema,fm,None,settings).tick()
    assert all(j['status']=='synced' for j in await store.jobs(pid))
    assert fm.row['fieldData']['Price']=='8.765432109876'
    assert fm.base['fieldData'].get('EX-Price') is None
    assert fm.base_writes == []
    saved=await store.get(pid)
    assert 'RMB成本' not in saved['fields']
    assert (await store.history(pid))[0]['actor']['account']=='editor'

from app.services.product_master.finance import scan_finance_sources, NATIVE_LAYOUT


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['stable','changed','duplicate','truncated'])
async def test_full_scan_requires_two_identical_complete_passes(mode):
    product,native,price=sample()
    native['fieldData']['image_main']='https://private.invalid/container'
    native['portalData']={'unrelated':[{'x':'private'}]}
    class Reader:
        def __init__(self):self.calls={}
        async def finance_page(self,layout,offset):
            self.calls[layout]=self.calls.get(layout,0)+1
            row=copy.deepcopy(native if layout==NATIVE_LAYOUT else price)
            if mode=='changed' and self.calls[layout]>1:row['modId']='changed'
            if mode=='duplicate':return {'foundCount':2,'data':[row,row]}
            if mode=='truncated':return {'foundCount':2,'data':[row] if offset==1 else []}
            return {'foundCount':1,'data':[row]}
    reader=Reader()
    if mode!='stable':
        with pytest.raises(ValueError):await scan_finance_sources(reader)
    else:
        prices=await scan_finance_sources(reader)
        assert NATIVE_LAYOUT not in reader.calls
        assert len(prices)==1 and sum(reader.calls.values())==2


@pytest.mark.asyncio
async def test_finance_diagnostics_are_not_read_for_users_without_price_permission():
    from app.api.product_master import finance_detail
    class ForbiddenDB:
        async def fetchval(self,*args):raise AssertionError('Finance source must not be read')
    schema=ProductSchema.load('backend/config/product_master_web_schema.json')
    snapshot={'id':str(uuid4()),'fields':{'product_sku':'A','RMB成本':'secret'},'assets':[]}
    result=await finance_detail(snapshot,SimpleNamespace(pool=ForbiddenDB()),schema,{'canViewProducts':True})
    assert 'financeIssues' not in result and 'RMB成本' not in result['fields']

@pytest.mark.asyncio
async def test_cost_endpoint_is_live_read_only_uncached_and_permission_checked():
    from fastapi import FastAPI
    from app.api.product_master import router
    from app.services.dependencies import get_webviewer_session_context
    product,native,_=sample();pid=product['id'];calls=[];allowed=True;offline=False
    class Reader:
        async def get_record(self,layout,record_id):
            assert layout==NATIVE_LAYOUT and record_id=='12'
            if offline: raise RuntimeError('private upstream detail')
            calls.append(record_id)
            value=copy.deepcopy(native);value['fieldData']['產品 BOM::產品成本']=str(len(calls))
            return [value]
    class Store:
        async def get(self,ref): assert str(ref)==pid; return product
        async def save(self,**kwargs): raise AssertionError('Costs must never be persisted')
    app=FastAPI();app.include_router(router)
    app.state.product_master_preview_store=Store();app.state.product_finance_filemaker=Reader()
    app.dependency_overrides[get_webviewer_session_context]=lambda:{'access':{'canViewProducts':True,'canViewPrice':allowed}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        for expected in ('1','2'):
            response=await client.get(f'/product-master/products/{pid}/costs')
            assert response.status_code==200 and response.headers['cache-control']=='no-store'
            assert response.json()['fields']['RMB成本']==expected
        allowed=False
        assert (await client.get(f'/product-master/products/{pid}/costs')).status_code==403
        assert len(calls)==2
        allowed=True;offline=True
        response=await client.get(f'/product-master/products/{pid}/costs')
        assert response.status_code==503 and 'private upstream detail' not in response.text

import asyncio
import hashlib
import os
from types import SimpleNamespace
from uuid import uuid4, UUID

import pytest
import pytest_asyncio

from app.services.product_master.schema import ProductSchema, ProductValidationError
from app.services.product_master.store import ProductStore, Conflict, dumps
from app.services.product_master.worker import ProductWorker
from app.services.product_image_fields import product_image_field

SCHEMA = ProductSchema({'fields':[
 {'name':'ID','result':'text','writable':False},
 {'name':'product_sku','result':'text','writable':True,'required':True},
 {'name':'product_name','result':'text','writable':True},
 {'name':'price','result':'number','writable':True,'writePermission':'canEditProductPrices','readPermission':'canViewPrice'},
 {'name':'stock','result':'number','writable':False},
 {'name':'说明书','result':'container','writable':True,'maxRepeat':2},
]})
PERMISSIONS = {'canEditProducts':True,'canViewProducts':True,'canEditProductPrices':True,'canViewPrice':True}


@pytest.mark.asyncio
async def test_migration_preview_filters_prices_urls_and_never_enables_writes():
    from fastapi import HTTPException
    from app.api.product_master import get_product, schema_info, runtime
    pid = uuid4()
    class Reader:
        async def find_records(self, layout, query, limit):
            assert layout == '@products_web_api' and query == {'ID': f'=={pid}'} and limit == 2
            return {'data': [{'fieldData': {'ID': str(pid), 'product_sku': 'A',
                    'price': 123, '说明书': 'https://private-container/temporary'}}]}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(product_master_preview_enabled=True, product_master_layout='@products_web_api'),
        product_master_schema=SCHEMA, filemaker_client=Reader())))
    context = {'access': {**PERMISSIONS, 'canViewPrice': False}}
    result = await get_product(str(pid), request, context)
    assert result['previewMode'] and result['assets'] == []
    assert 'price' not in result['fields'] and '说明书' not in result['fields']
    assert result['pendingAssetFields'] == ['说明书']
    assert not (await schema_info(request, context))['permissions']['canEditProducts']
    with pytest.raises(HTTPException) as error:
        runtime(request)
    assert error.value.status_code == 503


@pytest_asyncio.fixture
async def store():
    url=os.environ.get('PRODUCT_MASTER_TEST_DATABASE_URL')
    if not url: pytest.skip('Set PRODUCT_MASTER_TEST_DATABASE_URL to an isolated PostgreSQL database')
    value=ProductStore(url, 'test-'+str(uuid4()))
    await value.init()
    yield value
    async with value.pool.acquire() as c:
        for table in ('pm_product_asset','pm_asset_version','pm_reference','pm_consumer','pm_publication','pm_drift','pm_job','pm_revision','pm_upload','pm_product','pm_scan','pm_source'):
            await c.execute(f'DELETE FROM {table} WHERE source=$1',value.source)
    await value.close()


async def save(store, pid=None, version=0, rid=None, changes=None, assets=None, permissions=None, imported=None):
    return await store.save(product_id=pid or uuid4(),expected_version=version,request_id=rid or uuid4(),changes=changes or {'product_sku':'SKU-1'},assets=assets,actor={'account':'alice'},schema=SCHEMA,permissions=permissions or PERMISSIONS,imported=imported)


def test_schema_protects_identity_calculations_and_price():
    for changes in ({'ID':str(uuid4())},{'stock':1},{'unregistered':'x'},{'price':'NaN'},{'说明书':'url'}):
        with pytest.raises(ProductValidationError): SCHEMA.validate(changes,PERMISSIONS)
    with pytest.raises(ProductValidationError): SCHEMA.validate({'price':10},{'canEditProducts':True})
    with pytest.raises(ProductValidationError): SCHEMA.slot('说明书',3,PERMISSIONS)


@pytest.mark.asyncio
async def test_atomic_revision_and_idempotency(store):
    pid,rid=uuid4(),uuid4()
    first=await save(store,pid,rid=rid)
    assert await save(store,pid,rid=rid)==first
    assert len(await store.history(pid))==1
    assert len(await store.jobs(pid))==1
    assert len(await store.feed(0))==1
    with pytest.raises(ValueError): await save(store,pid,rid=rid,changes={'product_sku':'other'})
    with pytest.raises(Conflict): await save(store,pid)
    assert (await store.get(pid))['version']==1


@pytest.mark.asyncio
async def test_parallel_save_only_one_wins(store):
    pid=uuid4();await save(store,pid)
    result=await asyncio.gather(save(store,pid,1,changes={'product_name':'A'}),save(store,pid,1,changes={'product_name':'B'}),return_exceptions=True)
    assert sum(isinstance(x,Conflict) for x in result)==1
    assert len(await store.history(pid))==2
    assert len(await store.feed(0))==2


@pytest.mark.asyncio
async def test_unverified_asset_rolls_back_entire_save(store):
    pid=uuid4();await save(store,pid)
    with pytest.raises(ValueError):
        await save(store,pid,1,assets=[{'id':str(uuid4()),'field':'说明书','repetition':1}])
    assert (await store.get(pid))['version']==1
    assert len(await store.feed(0))==1


async def asset(store,pid):
    uid=uuid4();metadata={'objectKey':str(uid),'sha256':hashlib.sha256(b'%PDF-1.7 test').hexdigest(),'filename':'manual.pdf','mimeType':'application/pdf','size':13}
    await store.pool.execute('INSERT INTO pm_upload(source,id,product_id,request_id,actor,metadata,ready) VALUES($1,$2,$3,$2,$4,$5::jsonb,true)',store.source,uid,pid,'alice',dumps(metadata))
    return {'id':str(uid),'field':'说明书','repetition':1}


@pytest.mark.asyncio
async def test_remove_and_restore_keeps_original_files(store):
    pid=uuid4();await save(store,pid)
    a=await asset(store,pid)
    await save(store,pid,1,assets=[a])
    await save(store,pid,2,assets=[])
    assert (await store.get(pid))['assets']==[]
    history=await store.history(pid)
    assert history[1]['after_data']['assets'][0]['id']==a['id']
    await save(store,pid,3,assets=[a])
    assert (await store.get(pid))['assets'][0]['id']==a['id']
    assert await store.pool.fetchval('SELECT ready FROM pm_upload WHERE source=$1 AND id=$2',store.source,UUID(a['id']))


@pytest.mark.asyncio
async def test_assets_cannot_cross_products_or_duplicate_slots(store):
    a,b=uuid4(),uuid4();await save(store,a);await save(store,b,changes={'product_sku':'SKU-2'})
    image=await asset(store,a)
    with pytest.raises(ValueError):await save(store,b,1,assets=[image])
    with pytest.raises(ValueError):await save(store,a,1,assets=[image,image])


@pytest.mark.asyncio
async def test_source_isolation(store):
    pid=uuid4();await save(store,pid)
    other=ProductStore(store.url,'different-source');other.pool=store.pool
    assert await other.get(pid) is None
    assert await other.feed(0)==[]


class FakeFileMaker:
    def __init__(self,pid,mod='1'):
        self.record={'recordId':'10','modId':mod,'fieldData':{'ID':str(pid),'product_sku':'SKU-1'}}
        self.writes=0;self.offline=False
    async def find_records(self,*args,**kwargs):
        if self.offline:raise ConnectionError()
        return {'data':[self.record]}
    async def request(self,*args,**kwargs):
        self.writes+=1;self.record['fieldData'].update(kwargs['json_body']['fieldData']);self.record['modId']=str(int(self.record['modId'])+1)
        return {'response':{'modId':self.record['modId']}}
    async def get_record(self,*args,**kwargs):return [self.record]


def worker(store,fm):
    return ProductWorker(store,SCHEMA,fm,None,SimpleNamespace(product_master_layout='@products_web',product_master_write_enabled=True,product_master_max_file_bytes=10000))


@pytest.mark.asyncio
async def test_native_modification_is_conflict_not_web_overwrite(store):
    pid=uuid4();await save(store,pid,imported={'recordId':'10','modId':'1'})
    await save(store,pid,1,changes={'product_name':'Web name'})
    fm=FakeFileMaker(pid,mod='2');await worker(store,fm).tick()
    assert (await store.jobs(pid))[0]['status']=='conflict'
    assert (await store.get(pid))['fields']['product_name']=='Web name'
    assert fm.writes==0


@pytest.mark.asyncio
async def test_offline_save_and_restart_resume(store):
    pid=uuid4();await save(store,pid,imported={'recordId':'10','modId':'1'})
    await save(store,pid,1,changes={'product_name':'New'})
    fm=FakeFileMaker(pid);fm.offline=True
    await worker(store,fm).tick()
    assert (await store.jobs(pid))[0]['status']=='retry'
    assert (await store.get(pid))['fields']['product_name']=='New'
    fm.offline=False
    await store.pool.execute('UPDATE pm_job SET next_attempt_at=now() WHERE source=$1',store.source)
    await worker(store,fm).tick()
    assert (await store.jobs(pid))[0]['status']=='synced'
    assert fm.record['fieldData']['product_name']=='New'


@pytest.mark.asyncio
async def test_ordered_jobs_and_two_workers(store):
    pid=uuid4();await save(store,pid,imported={'recordId':'10','modId':'1'})
    await save(store,pid,1,changes={'product_name':'v2'})
    await save(store,pid,2,changes={'product_name':'v3'})
    fm=FakeFileMaker(pid)
    await asyncio.gather(worker(store,fm).tick(),worker(store,fm).tick())
    await worker(store,fm).tick()
    assert fm.record['fieldData']['product_name']=='v3'
    assert fm.writes==2
    assert all(j['status']=='synced' for j in await store.jobs(pid))

from fastapi import FastAPI
import httpx
from app.api.product_master import router
from app.services.dependencies import get_webviewer_session_context


class MemoryCOS:
    def __init__(self): self.files={}
    def get_object_bytes(self,key,max_bytes=None):
        value=self.files[key]
        if max_bytes and len(value)>max_bytes:raise ValueError('oversize')
        return value
    def put_object(self,*,object_key,content,content_type):self.files[object_key]=content
    def create_presigned_upload(self,*,object_key,content_type):
        return SimpleNamespace(upload_url='https://upload.invalid/'+object_key,headers={'Content-Type':content_type})


@pytest_asyncio.fixture
async def api(store):
    app=FastAPI();app.include_router(router,prefix='/api')
    app.state.product_master_store=store;app.state.product_master_schema=SCHEMA
    class SKUReader:
        async def find_records(self, layout, query, limit): return {'data': []}
    app.state.filemaker_client=SKUReader()
    app.state.cos_storage_service=MemoryCOS()
    app.state.settings=SimpleNamespace(product_master_max_file_bytes=10000,product_master_consumers_json='{"dms":"'+('s'*32)+'"}',filemaker_host='https://fm.test',filemaker_database='Products',product_master_layout='@products_web_api')
    app.dependency_overrides[get_webviewer_session_context]=lambda:{'operator':{'account':'alice','name':'Alice'},'sessionId':'session','access':PERMISSIONS}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        yield client,app


@pytest.mark.asyncio
async def test_api_new_uuid_audit_and_replayed_create(api,store):
    client,app=api
    body={'requestId':str(uuid4()),'expectedVersion':0,'changes':{'product_sku':'Web-created'}}
    first=await client.post('/api/product-master/products',json=body)
    assert first.status_code==200,first.text
    again=await client.post('/api/product-master/products',json=body)
    assert again.json()==first.json()
    history=await store.history(first.json()['id'])
    assert history[0]['actor']['account']=='alice'
    body['changes']['ID']=str(uuid4());body['requestId']=str(uuid4())
    assert (await client.post('/api/product-master/products',json=body)).status_code==422


@pytest.mark.asyncio
async def test_upload_checksum_and_immutable_staging(api,store):
    client,app=api;pid=uuid4();await save(store,pid)
    content=b'%PDF-1.7 test';sha=hashlib.sha256(content).hexdigest()
    body={'requestId':str(uuid4()),'filename':'manual.pdf','mimeType':'application/pdf','size':len(content),'sha256':sha,'field':'说明书','repetition':2}
    path=f'/api/product-master/products/{pid}'
    response=await client.post(path+'/uploads',json=body)
    assert response.status_code==200,response.text
    uid=response.json()['id']
    row=await store.pool.fetchrow('SELECT metadata FROM pm_upload WHERE source=$1 AND id=$2',store.source,UUID(uid))
    import json
    metadata=json.loads(row['metadata']);cos=app.state.cos_storage_service
    cos.files[metadata['stagingKey']]=b'bad'
    assert (await client.post(path+f'/uploads/{uid}/complete')).status_code==422
    cos.files[metadata['stagingKey']]=content
    checked=await client.post(path+f'/uploads/{uid}/complete')
    assert checked.status_code==200,checked.text
    cos.files[metadata['stagingKey']]=b'overwritten staging'
    saved=await client.patch(path,json={'requestId':str(uuid4()),'expectedVersion':1,'assets':[checked.json()]})
    assert saved.status_code==200,saved.text
    downloaded=await client.get(path+f'/assets/{uid}')
    assert downloaded.content==content
    assert 'stagingKey' not in saved.json()['assets'][0]


@pytest.mark.asyncio
async def test_consumer_source_and_auth_fail_closed(api,store):
    client,app=api;await save(store)
    assert (await client.get('/api/product-master/changes')).status_code==401
    headers={'Authorization':'Bearer '+'s'*32,'X-Product-Consumer':'dms','X-Product-Source':'wrong'}
    assert (await client.get('/api/product-master/changes',headers=headers)).status_code==403
    headers['X-Product-Source']=store.source
    response=await client.get('/api/product-master/changes',headers=headers)
    assert response.status_code==200
    assert len(response.json()['events'])==1
    assert len(response.json()['fingerprint'])==64


@pytest.mark.asyncio
async def test_api_permissions_hide_price_and_block_writes(api,store):
    client,app=api;pid=uuid4();await save(store,pid,changes={'product_sku':'P','price':99})
    app.dependency_overrides[get_webviewer_session_context]=lambda:{'operator':{'account':'reader'},'access':{'canViewProducts':True}}
    detail=await client.get(f'/api/product-master/products/{pid}')
    assert 'price' not in detail.json()['fields']
    history=(await client.get(f'/api/product-master/products/{pid}/history')).json()
    assert 'price' not in history['rows'][0]['after_data']['fields']
    assert (await client.patch(f'/api/product-master/products/{pid}',json={'requestId':str(uuid4()),'expectedVersion':1,'changes':{'product_sku':'X'}})).status_code==403

from app.services.product_master.worker import wire_fields, fields_match


def test_repeating_fields_use_explicit_filemaker_indices():
    schema=ProductSchema({'fields':[{'name':'ID','result':'text','writable':False},{'name':'labels','result':'text','writable':True,'maxRepeat':3},{'name':'date','result':'date','writable':True}]})
    wire=wire_fields({'labels':['one','two'],'date':'2026-09-20'},schema)
    assert wire=={'labels(1)':'one','labels(2)':'two','labels(3)':'','date':'09/20/2026'}
    assert fields_match({'labels':['one','two',''],'date':'09/20/2026'},{'labels':['one','two'],'date':'2026-09-20'},schema)


@pytest.mark.asyncio
async def test_timeout_after_fields_write_recovers_without_second_write(store):
    pid=uuid4();await save(store,pid,imported={'recordId':'10','modId':'1'})
    await save(store,pid,1,changes={'product_name':'new'})
    fm=FakeFileMaker(pid)
    original=fm.request
    async def timeout(*args,**kwargs):
        await original(*args,**kwargs)
        raise TimeoutError()
    fm.request=timeout
    await worker(store,fm).tick()
    assert fm.writes==1
    assert (await store.jobs(pid))[0]['status']=='retry'
    fm.request=original
    await store.pool.execute('UPDATE pm_job SET next_attempt_at=now() WHERE source=$1',store.source)
    await worker(store,fm).tick()
    assert fm.writes==1
    assert (await store.jobs(pid))[0]['status']=='synced'


@pytest.mark.asyncio
async def test_new_product_timeout_is_found_by_web_uuid(store):
    pid=uuid4();await save(store,pid)
    fm=FakeFileMaker(pid);fm.created=False;fm.creates=0
    async def find(*args,**kwargs):return {'data':[fm.record] if fm.created else []}
    async def create(layout,fields):
        fm.creates+=1;fm.created=True;fm.record['fieldData']=fields
        raise TimeoutError()
    fm.find_records=find;fm.create_record=create
    await worker(store,fm).tick()
    assert fm.creates==1
    await store.pool.execute('UPDATE pm_job SET next_attempt_at=now() WHERE source=$1',store.source)
    await worker(store,fm).tick()
    assert fm.creates==1
    assert (await store.get(pid))['fm_record_id']=='10'
    assert all(j['status']=='synced' for j in await store.jobs(pid))


@pytest.mark.asyncio
async def test_restore_command_replay_does_not_create_extra_revision(api,store):
    client,_=api;pid=uuid4();await save(store,pid)
    body={'requestId':str(uuid4()),'expectedVersion':1}
    url=f'/api/product-master/products/{pid}/restore/1'
    first=await client.post(url,json=body)
    assert first.status_code==200,first.text
    second=await client.post(url,json=body)
    assert second.json()==first.json()
    assert len(await store.history(pid))==2


@pytest.mark.asyncio
async def test_patch_cannot_supply_new_product_uuid(api):
    client,_=api
    response=await client.patch(f'/api/product-master/products/{uuid4()}',json={'requestId':str(uuid4()),'expectedVersion':0,'changes':{'product_sku':'new'}})
    assert response.status_code==404


@pytest.mark.asyncio
async def test_source_fingerprint_cannot_be_rebound(store):
    first=ProductStore(store.url,store.source,'fingerprint-a');await first.init()
    second=ProductStore(store.url,store.source,'fingerprint-b')
    try:
        with pytest.raises(ValueError):await second.init()
    finally:
        await first.close()
        if second.pool:await second.close()


@pytest.mark.asyncio
async def test_hidden_attachments_are_not_removed_by_partial_editor(store):
    pid=uuid4();await save(store,pid)
    a=await asset(store,pid)
    hidden=ProductSchema({'fields':[*SCHEMA.fields.values()]})
    hidden.fields['说明书']={**hidden.fields['说明书'],'readPermission':'canViewPrice','writePermission':'canEditProductPrices'}
    await store.save(product_id=pid,expected_version=1,request_id=uuid4(),changes={},assets=[a],actor={'account':'alice'},schema=hidden,permissions=PERMISSIONS)
    await store.save(product_id=pid,expected_version=2,request_id=uuid4(),changes={'product_name':'safe'},assets=[],actor={'account':'reader-editor'},schema=hidden,permissions={'canViewProducts':True,'canEditProducts':True})
    assert (await store.get(pid))['assets'][0]['id']==a['id']


@pytest.mark.asyncio
async def test_pda_uses_master_versions_and_keeps_legacy_response(api,store):
    from app.services.product_master import mobile
    from app.models.mobile_products import ProductPhotoPresignRequest,ProductPhotoCompleteRequest
    from app.services.audit_log import OperatorContext
    from starlette.requests import Request
    from PIL import Image
    from io import BytesIO
    _,app=api;pid=uuid4();await save(store,pid)
    app.state.product_master_schema=ProductSchema({'fields':[*SCHEMA.fields.values(),*({'name':product_image_field(i),'result':'container','writable':True,'role':'product_image'} for i in range(1,7))]})
    app.state.settings.cos_presign_ttl_seconds=900
    request=Request({'type':'http','app':app})
    operator=OperatorContext(session_id='mobile',account='alice',name='Alice',permissions=PERMISSIONS)
    buffer=BytesIO();Image.new('RGB',(2,2)).save(buffer,format='JPEG');content=buffer.getvalue();sha=hashlib.sha256(content).hexdigest()
    body=ProductPhotoPresignRequest(sessionId='session-001',filename='photo.jpg',mimeType='image/jpeg',fileSize=len(content),sha256=sha)
    first=await mobile.create(request,'SKU-1',body,operator)
    second=await mobile.create(request,'SKU-1',body,operator)
    assert first.upload_id==second.upload_id
    assert first.slot==1
    app.state.cos_storage_service.files[first.object_key]=content
    finished=await mobile.finish(request,'SKU-1',first.upload_id,operator,ProductPhotoCompleteRequest(etag='test',fileSize=len(content),sha256=sha))
    assert finished.status=='UPLOADED'
    current=await store.get(pid);assert current['version']==2
    assert current['assets'][0]['role']=='product_image'
    await mobile.finish(request,'SKU-1',first.upload_id,operator)
    assert (await store.get(pid))['version']==2


def test_price_edit_permission_metadata_is_not_a_financial_value():
    from app.services.webviewer_account_access import sanitize_price_data
    assert sanitize_price_data({'canEditProductPrices':True,'price':99})=={'canEditProductPrices':True}


@pytest.mark.asyncio
async def test_filemaker_auto_defaults_fill_missing_fields_without_overwriting_web(store):
    pid=uuid4();await save(store,pid,imported={'recordId':'10','modId':'1'})
    fm=FakeFileMaker(pid);fm.record['fieldData'].update({'product_name':'Auto-entered name','stock':12,'product_sku':'native-other'})
    w=worker(store,fm)
    current=await store.get(pid)
    await w.refresh_derived(current,fm.record)
    current=await store.get(pid)
    assert current['fields']['product_name']=='Auto-entered name'
    assert current['fields']['stock']==12
    assert current['fields']['product_sku']=='SKU-1'


def test_legacy_conflict_is_local_and_preserves_asset_identity():
    from app.services.product_master.importer import legacy_slots, asset_identity
    pid = str(uuid4())
    slots = legacy_slots([{'fieldData': {'source_record_id': '10', 'legacy_source_field': 'photo', 'id_asset': 'first'}},
                          {'fieldData': {'source_record_id': '10', 'legacy_source_field': 'photo', 'id_asset': 'second'}},
                          {'fieldData': {'source_record_id': '11', 'legacy_source_field': 'photo', 'id_asset': 'keep-me'}}])
    with pytest.raises(ValueError, match='旧资产关联冲突'):
        asset_identity(slots, '10', 'photo', 1, pid)
    assert asset_identity(slots, '11', 'photo', 1, pid) == 'keep-me'
    assert asset_identity(slots, '12', 'photo', 1, pid) == asset_identity(slots, '12', 'photo', 1, pid)


@pytest.mark.asyncio
async def test_preview_prefers_durable_snapshot_even_without_filemaker(store):
    from fastapi import HTTPException
    from app.api.product_master import get_product, runtime
    pid = uuid4()
    await save(store, pid, changes={'product_sku': 'COPY', 'price': 10}, imported={'recordId': '12', 'modId': '3'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(product_master_preview_enabled=True), product_master_schema=SCHEMA,
        product_master_preview_store=store)))
    result = await get_product(str(pid), request, {'access': {**PERMISSIONS, 'canViewPrice': False}})
    assert result['previewMode'] and result['fields']['product_sku'] == 'COPY'
    assert 'price' not in result['fields'] and result['pendingAssetFields'] == []
    with pytest.raises(HTTPException) as error:
        runtime(request)
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_import_verifies_every_repeated_container_and_reuses_snapshot(store, monkeypatch):
    from app.services.product_master import importer
    pid = str(uuid4()); calls = []
    row = {'recordId': '123', 'modId': '5', 'fieldData': {'ID': pid, 'product_sku': 'TEST', '说明书': ['one', 'two']}}
    class FM:
        async def get_record(self, layout, record_id): return [row]
    class COS:
        def __init__(self): self.objects = {}
        def put_object(self, *, object_key, content, content_type): self.objects[object_key] = content
        def get_object_bytes(self, key, max_bytes): return self.objects[key]
    async def download(fm, url, max_bytes):
        calls.append(url); return b'%PDF-' + url.encode(), 'application/octet-stream'
    monkeypatch.setattr(importer, 'download_container', download)
    settings = SimpleNamespace(product_master_max_file_bytes=1000, product_master_layout='api')
    result = await importer.import_product(store, SCHEMA, FM(), COS(), settings, row, {})
    assert calls == ['one', 'two'] and len(result['assets']) == 2
    assert {a['repetition'] for a in result['assets']} == {1, 2}
    assert all(a['mimeType'] == 'application/pdf' for a in result['assets'])
    existing = await importer.import_product(store, SCHEMA, None, None, settings, row, {})
    assert existing['fields'] == result['fields'] and existing['assets'] == result['assets']
    assert existing['version'] == result['version'] == 1
    assert len(await store.history(pid)) == 1


@pytest.mark.asyncio
async def test_container_redirects_follow_only_the_same_origin(monkeypatch):
    import httpx
    from app.services.product_master import worker
    real_client = httpx.AsyncClient
    urls = []
    destination = '/Streaming/image.png?Redirect'
    def handler(request):
        urls.append(str(request.url))
        if 'Redirect' not in request.url.query.decode():
            return httpx.Response(302, headers={'Location': destination})
        return httpx.Response(200, content=b'image', headers={'Content-Type':'image/png'})
    monkeypatch.setattr(worker.httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    class FM:
        settings = SimpleNamespace(filemaker_host='https://fm.example:8443', filemaker_ssl_verify=True)
        async def get_token(self): return 'test-only'
    assert await worker.download_container(FM(), 'https://fm.example:8443/Streaming/image.png', 50) == (b'image', 'image/png')
    assert len(urls) == 2
    destination = 'https://other.example/steal'
    urls.clear()
    with pytest.raises(ValueError, match='Untrusted'):
        await worker.download_container(FM(), 'https://fm.example:8443/Streaming/image.png', 50)
    assert len(urls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('sku', ['', '  ', '\t\n', None])
async def test_api_rejects_empty_sku_without_new_revision(api, store, sku):
    client, _ = api
    pid = uuid4(); await save(store, pid)
    response = await client.patch(f'/api/product-master/products/{pid}', json={
        'requestId': str(uuid4()), 'expectedVersion': 1, 'changes': {'product_sku': sku}})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'SKU_REQUIRED'
    assert response.json()['detail']['field'] == 'product_sku'
    assert len(await store.history(pid)) == 1


@pytest.mark.asyncio
async def test_sku_duplicates_are_case_insensitive_and_exclude_current_product(store):
    from app.services.product_master.schema import SKUValidationError
    first = uuid4(); await save(store, first, changes={'product_sku': ' Example-01 '})
    assert (await store.get(first))['fields']['product_sku'] == 'Example-01'
    await save(store, first, 1, changes={'product_sku': 'example-01'})
    with pytest.raises(SKUValidationError, match='已被其他产品使用'):
        await save(store, changes={'product_sku': '  EXAMPLE-01\t'})
    assert len(await store.list()) == 1


@pytest.mark.asyncio
async def test_concurrent_products_cannot_claim_the_same_sku(store):
    from app.services.product_master.schema import SKUValidationError
    results = await asyncio.gather(save(store, changes={'product_sku': 'SAME'}),
        save(store, changes={'product_sku': ' same '}), return_exceptions=True)
    assert sum(isinstance(r, SKUValidationError) for r in results) == 1
    assert len(await store.list()) == len(await store.feed(0)) == 1


@pytest.mark.asyncio
async def test_unmigrated_filemaker_sku_blocks_save_and_lookup_failure_is_explicit(api, store):
    client, app = api
    class Existing:
        async def find_records(self, layout, query, limit):
            assert query == {'product_sku': '==REMOTE'}
            return {'data': [{'fieldData': {'ID': str(uuid4())}}]}
    app.state.filemaker_client = Existing()
    body = {'requestId':str(uuid4()),'expectedVersion':0,'changes':{'product_sku':'REMOTE'}}
    response = await client.post('/api/product-master/products', json=body)
    assert response.status_code == 422 and response.json()['detail']['code'] == 'SKU_DUPLICATE'
    class Offline:
        async def find_records(self, *args, **kwargs): raise RuntimeError('offline')
    app.state.filemaker_client = Offline()
    response = await client.post('/api/product-master/products', json=body)
    assert response.status_code == 503 and response.json()['detail']['code'] == 'SKU_CHECK_UNAVAILABLE'
    assert await store.list() == [] and await store.feed(0) == []


@pytest.mark.asyncio
async def test_complete_locked_web_catalog_does_not_require_filemaker_for_sku(store):
    await store.pool.execute('INSERT INTO pm_source(source,fingerprint,initial_import_complete) VALUES($1,$2,true)',store.source,'test')
    schema = ProductSchema({**SCHEMA.document, 'nativeEditingLocked':True})
    async def offline(*args): raise AssertionError('FileMaker must not be needed after full cutover')
    result = await store.save(product_id=uuid4(),expected_version=0,request_id=uuid4(),changes={'product_sku':'OFFLINE'},
        assets=[],actor={'account':'test'},schema=schema,permissions=PERMISSIONS,sku_validator=offline)
    assert result['fields']['product_sku'] == 'OFFLINE'


@pytest.mark.asyncio
async def test_historical_duplicate_skus_remain_importable_but_cannot_be_saved_unchanged(store):
    from app.services.product_master.schema import SKUValidationError
    first, second = uuid4(), uuid4()
    await save(store,first,changes={'product_sku':'OLD'},imported={'recordId':'101','modId':'1'})
    await save(store,second,changes={'product_sku':' old '},imported={'recordId':'102','modId':'1'})
    with pytest.raises(SKUValidationError):
        await save(store,second,1,changes={'product_name':'Changed'})
    await save(store,second,1,changes={'product_sku':'NEW'})
    assert (await store.get(second))['version'] == 2


@pytest.mark.asyncio
async def test_native_editor_controls_filter_and_page_without_mutation():
    from app.api.product_master import editor_controls, editor_options
    class Reader:
        calls = 0
        async def get_layout_metadata(self, layout):
            self.calls += 1
            assert layout in ('产品报价','產品 資料_業務')
            return {'fieldMetaData': [
                {'name': 'product_sku', 'displayType': 'popupList', 'valueList': 'products'},
                {'name': 'price', 'displayType': 'popupMenu', 'valueList': 'private'},
                {'name': 'related::status', 'displayType': 'popupList', 'valueList': 'private'}],
                'valueLists': [{'name': 'products', 'values': [{'value': str(i), 'displayValue': f'Product {i}'} for i in range(120)]},
                               {'name': 'private', 'values': [{'value': 'secret'}]}]}
    reader = Reader()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(product_master_schema=SCHEMA,filemaker_client=reader)))
    context = {'access': {'canViewProducts': True}}
    result = await editor_controls(request, context)
    assert set(result['controls']) == {'product_sku'}
    assert result['controls']['product_sku']['searchable']
    assert result['controls']['product_sku']['options'] == []
    page = await editor_options('product_sku',request,q='Product 1',offset=0,context=context)
    assert page['total'] == 31 and page['rows'][0]['value'] == '1'
    assert reader.calls == 1


@pytest.mark.asyncio
async def test_customer_picker_uses_internal_key_and_all_pages():
    from app.api.product_master import editor_customers
    class Reader:
        async def records(self, table, **kwargs):
            assert table == '客戶' and 'ID' not in kwargs['select']
            if kwargs['skip'] == 0:
                return {'rows':[{'@id':"https://example/客戶('CU339','036')",'客戶公司簡稱':'Enjoy Smile Co.','客戶代號':'036'}], 'foundCount':2,'nextLink':'next'}
            return {'rows':[{'@id':"https://example/客戶('CU340','037')",'客戶公司簡稱':'Other','客戶代號':'037'}], 'foundCount':2}
    schema = ProductSchema({'fields':[{'name':'ID'}, {'name':'Client'}, {'name':'id_client'}]})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(product_master_schema=schema,filemaker_odata_client=Reader())))
    context = {'access': {'canViewProducts':True}}
    result = await editor_customers(request,q='036',offset=0,context=context)
    assert result['total']==1
    assert result['rows'][0] == {'value':'CU339','name':'Enjoy Smile Co.','label':'Enjoy Smile Co.','code':'036'}
    assert (await editor_customers(request,q='CU340',offset=0,context=context))['rows'][0]['code']=='037'


@pytest.mark.asyncio
async def test_eighteen_photo_and_spec_import_preserves_exact_slots_and_skips_qrcode(store, monkeypatch):
    from app.services.product_master import importer
    fields = [dict(f) for f in SCHEMA.fields.values() if f['result'] != 'container']
    photos = [product_image_field(i) for i in range(1,19)] + ['產品規格書','產品規格書2']
    fields += [{'name':name,'result':'container','writable':True,'maxRepeat':1} for name in photos]
    fields += [{'name':name,'result':'container','writable':False,'managed':False} for name in ['qrcode']]
    schema=ProductSchema({'fields':fields})
    row={'recordId':'123','modId':'1','fieldData':{'ID':str(uuid4()),'product_sku':'six',**{name:name for name in photos},'qrcode':'never-download'}}
    calls=[]
    class FM:
        async def get_record(self,*args):return [row]
    class COS:
        def __init__(self):self.objects={}
        def put_object(self,*,object_key,content,content_type):self.objects[object_key]=content
        def get_object_bytes(self,key,max_bytes):return self.objects[key]
    async def download(fm,url,max_bytes):calls.append(url);return b'%PDF-'+url.encode(),'application/pdf'
    monkeypatch.setattr(importer,'download_container',download)
    result=await importer.import_product(store,schema,FM(),COS(),SimpleNamespace(product_master_max_file_bytes=1000,product_master_layout='api'),row,{})
    assert calls==photos
    assert {(a['field'],a['repetition']) for a in result['assets']}=={(name,1) for name in photos}
    assert all(f['name']!='qrcode' for f in schema.visible(PERMISSIONS))
    with pytest.raises(ProductValidationError):schema.slot('qrcode',1,PERMISSIONS)


@pytest.mark.asyncio
async def test_business_controls_keep_native_choices_and_override_quote_layout():
    from app.services.product_master.options import native_controls
    class Reader:
        async def get_layout_metadata(self, layout):
            assert layout == '产品报价'
            return {'fieldMetaData':[{'name':'類別','displayType':'popupList','valueList':'old'}],
                    'valueLists':[{'name':'old','values':[{'value':'wrong-layout'}]}]}
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(filemaker_client=Reader())))
    controls=await native_controls(request)
    assert any(o['value']=='轮胎' for o in controls['類別']['options'])
    assert not any(o['value']=='wrong-layout' for o in controls['類別']['options'])
    ratios=[o['value'] for o in controls['車子比例']['options']]
    assert '1/8' in ratios and '1/10' in ratios and ratios.count('1/24')==1
    assert controls['ShowStock']['type']=='checkBox'
    assert '關聯編號' not in controls


@pytest.mark.asyncio
async def test_relational_assets_survive_replace_and_live_json_is_empty(store):
    pid=uuid4();a=await asset(store,pid)
    await save(store,pid,assets=[{'id':a['id'],'field':'说明书','repetition':1}])
    assert await store.pool.fetchval('SELECT assets FROM pm_product WHERE source=$1 AND id=$2',store.source,pid)=='[]'
    assert await store.pool.fetchval('SELECT count(*) FROM pm_product_asset WHERE source=$1',store.source)==1
    assert await store.pool.fetchval('SELECT count(*) FROM pm_asset_version WHERE source=$1',store.source)==1
    await save(store,pid,1,assets=[])
    assert (await store.get(pid))['assets']==[]
    assert await store.pool.fetchval('SELECT count(*) FROM pm_asset_version WHERE source=$1',store.source)==1


@pytest.mark.asyncio
async def test_web_only_load_and_options_never_call_filemaker(store):
    from app.api.product_master import get_product,products
    from app.services.product_master.options import native_controls,customer_options
    from fastapi import HTTPException
    class NoFileMaker:
        def __getattr__(self,name):raise AssertionError('FileMaker must not be called')
    pid=uuid4();await save(store,pid)
    state=SimpleNamespace(settings=SimpleNamespace(product_master_preview_enabled=True,product_master_web_only=True),product_master_preview_store=store,product_master_schema=SCHEMA,filemaker_client=NoFileMaker(),filemaker_odata_client=NoFileMaker())
    request=SimpleNamespace(app=SimpleNamespace(state=state));context={'access':PERMISSIONS}
    assert (await get_product(str(pid),request,context))['fields']['product_sku']=='SKU-1'
    assert len((await products(request,offset=0,context=context))['rows'])==1
    with pytest.raises(HTTPException) as error:await get_product(str(uuid4()),request,context)
    assert error.value.status_code==404
    await store.pool.execute("INSERT INTO pm_reference(source,name,payload) VALUES($1,'controls','{}'),($1,'customers','[]')",store.source)
    assert await native_controls(request)=={}
    assert await customer_options(request)==[]


@pytest.mark.asyncio
async def test_business_catalog_uses_web_preview_store_without_filemaker(store):
    from app.api.business_products import list_business_products,get_business_product
    class NoFM:
        def __getattr__(self,name):raise AssertionError('No FileMaker fallback allowed')
    class Audit:
        async def record(self,**kwargs):pass
    pid=uuid4();await save(store,pid)
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(product_master_web_only=True),product_master_preview_store=store,product_master_schema=SCHEMA)))
    operator=SimpleNamespace(permissions=PERMISSIONS)
    result=await list_business_products(q='',page=1,page_size=20,category='',model='',audit='',client_name='',filemaker=NoFM(),audit_log=Audit(),operator=operator,request=request)
    assert len(result.rows)==1
    detail=await get_business_product(str(pid),filemaker=NoFM(),audit_log=Audit(),operator=operator,request=request)
    assert detail.product.product_sku=='SKU-1'


def test_large_cos_upload_uses_bounded_parts_and_removes_local_temporary_file():
    from app.services.cos_storage import COSStorageService
    from pathlib import Path
    content=b'a'*(1024*1024+1);seen={}
    class COS:
        def upload_file(self,**kwargs):
            seen.update(kwargs)
            assert Path(kwargs['LocalFilePath']).read_bytes()==content
            assert kwargs['PartSize']==1 and kwargs['MAXThread']==3 and kwargs['EnableMD5']
            return {'ETag':'"etag"'}
    storage=COSStorageService(SimpleNamespace(cos_bucket='test',cos_configured=True));storage._client=COS()
    assert storage.put_object(object_key='immutable',content=content,content_type='image/png')=='etag'
    assert not Path(seen['LocalFilePath']).exists()


@pytest.mark.asyncio
async def test_import_reuses_cos_only_when_fresh_source_bytes_match(store,monkeypatch):
    from app.services.product_master import importer
    class COS:
        def __init__(self):self.objects={};self.puts=0
        def put_object(self,*,object_key,content,content_type):self.puts+=1;self.objects[object_key]=content
        def get_object_bytes(self,key,max_bytes):return self.objects[key]
    class FM:
        async def get_record(self,*args):return [self.row]
    fm=FM();cos=COS()
    async def fetch(fm,url,max_bytes):return url.encode(),'application/pdf'
    monkeypatch.setattr(importer,'download_container',fetch)
    async def ingest(content,sku):
        fm.row={'recordId':str(uuid4()),'modId':'1','fieldData':{'ID':str(uuid4()),'product_sku':sku,'说明书':content}}
        return await importer.import_product(store,SCHEMA,fm,cos,SimpleNamespace(product_master_layout='api',product_master_max_file_bytes=1000),fm.row,{})
    first=await ingest('%PDF-original','old')
    second=await ingest('%PDF-original','fresh')
    assert second['fields']['product_sku']=='fresh' and cos.puts==1
    assert first['assets'][0]['objectKey']==second['assets'][0]['objectKey']
    assert first['assets'][0]['id']!=second['assets'][0]['id']
    third=await ingest('%PDF-changed','new')
    assert cos.puts==2 and third['assets'][0]['objectKey']!=first['assets'][0]['objectKey']

MAIN_SCHEMA = ProductSchema({'fields': [
    *SCHEMA.document['fields'],
    {'name': 'image_main', 'result': 'container', 'writable': True, 'role': 'product_image'},
    {'name': '檔案 2 | 容器', 'result': 'container', 'writable': True, 'role': 'product_image'},
]})


@pytest.mark.asyncio
async def test_old_main_binding_migration_preserves_files_and_history(store):
    from scripts.product_master_rename_main_image import rename_main_image
    pid = uuid4()
    upload = await asset(store, pid)
    a = {**upload, 'field': 'image_main'}
    await store.save(product_id=pid, expected_version=0, request_id=uuid4(),
        changes={'product_sku': 'MAIN'}, assets=[a], actor={'account': 'migration'},
        schema=MAIN_SCHEMA, permissions={}, imported={'recordId': '10', 'modId': '1'})
    # Simulate the persisted pre-rename catalog without rewriting history during migration.
    await store.pool.execute('UPDATE pm_product_asset SET field=$2 WHERE source=$1', store.source, '檔案 1 | 容器')
    snapshot = (await store.history(pid))[0]['after_data']
    snapshot['assets'][0]['field'] = '檔案 1 | 容器'
    await store.pool.execute('UPDATE pm_revision SET after_data=$2::jsonb WHERE source=$1', store.source, dumps(snapshot))
    before = (await store.get(pid))['assets'][0]
    assert (await rename_main_image(store, MAIN_SCHEMA))['renamedProducts'] == 1
    after = (await store.get(pid))['assets'][0]
    assert after['field'] == 'image_main'
    assert {k:v for k,v in before.items() if k!='field'} == {k:v for k,v in after.items() if k!='field'}
    history = await store.history(pid)
    assert history[1]['after_data'] == snapshot
    assert history[0]['before_data']['assets'][0]['field'] == '檔案 1 | 容器'
    assert history[0]['after_data']['assets'][0]['field'] == 'image_main'
    assert (await rename_main_image(store, MAIN_SCHEMA))['renamedProducts'] == 0
    assert await store.pool.fetchval('SELECT count(*) FROM pm_asset_version WHERE source=$1',store.source)==1


@pytest.mark.asyncio
async def test_legacy_main_job_writes_explicit_image_main_not_first_asset(store, monkeypatch):
    import app.services.product_master.worker as worker_module
    pid = uuid4()
    await store.save(product_id=pid, expected_version=0, request_id=uuid4(),
        changes={'product_sku': 'SKU-1'}, assets=[], actor={'account': 'migration'},
        schema=MAIN_SCHEMA, permissions={}, imported={'recordId': '10', 'modId': '1'})
    main, second = await asset(store,pid), await asset(store,pid)
    await store.save(product_id=pid, expected_version=1, request_id=uuid4(), changes={},
        assets=[{**second,'field':'檔案 2 | 容器'},{**main,'field':'檔案 1 | 容器'}],
        actor={'account':'alice'}, schema=MAIN_SCHEMA, permissions=PERMISSIONS)
    # Historical queued jobs may still contain the original name.
    snapshot = (await store.history(pid))[0]['after_data']
    snapshot['assets'][1]['field'] = '檔案 1 | 容器'
    await store.pool.execute('UPDATE pm_revision SET after_data=$2::jsonb WHERE source=$1 AND version=2',store.source,dumps(snapshot))
    class FM(FakeFileMaker):
        def __init__(self,pid):super().__init__(pid);self.targets=[]
        async def upload_container(self,layout,record_id,name,content,filename,mime_type,**kwargs):
            self.targets.append(name)
            self.record['fieldData'][name]='https://fm.test/'+name
            self.record['modId']=str(int(self.record['modId'])+1)
            return {'modId':self.record['modId']}
    async def downloaded(*args):return b'%PDF-1.7 test','application/pdf'
    monkeypatch.setattr(worker_module,'download_container',downloaded)
    fm=FM(pid);cos=MemoryCOS()
    for a in (await store.get(pid))['assets']:cos.files[a['objectKey']]=b'%PDF-1.7 test'
    w=ProductWorker(store,MAIN_SCHEMA,fm,cos,SimpleNamespace(product_master_layout='@products_web',product_master_write_enabled=True,product_master_max_file_bytes=10000))
    await w.tick()
    assert set(fm.targets)=={'image_main','檔案 2 | 容器'}
    assert all(j['status']=='synced' for j in await store.jobs(pid))
    assert (await store.get(pid))['assets'][1]['field']=='image_main'


def test_main_mapping_preserves_legacy_asset_identity():
    from app.services.product_image_fields import product_image_field,product_image_slot
    from app.services.product_master.importer import legacy_slots,asset_identity
    aid,pid=uuid4(),uuid4()
    slots=legacy_slots([{'fieldData':{'source_record_id':'10','legacy_source_field':'檔案 1 | 容器','id_asset':str(aid)}}])
    assert asset_identity(slots,'10','image_main',1,str(pid))==str(aid)
    assert product_image_field(1)=='image_main'
    assert product_image_field(2)=='檔案 2 | 容器'
    assert product_image_slot('image_main')==product_image_slot('檔案 1 | 容器')==1


def test_missing_renamed_container_cannot_be_reported_as_empty():
    metadata={'fieldMetaData':[dict(f) for f in MAIN_SCHEMA.fields.values()]}
    MAIN_SCHEMA.validate_layout(metadata)
    metadata['fieldMetaData']=[f for f in metadata['fieldMetaData'] if f['name']!='image_main']
    with pytest.raises(ProductValidationError,match='image_main'):
        MAIN_SCHEMA.validate_layout(metadata)

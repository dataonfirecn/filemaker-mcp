import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.product_master import changes, consumer_auth
from app.services.product_master.schema import ProductSchema


@pytest.mark.asyncio
async def test_readonly_web_consumer_filters_finance_without_enabling_writes():
    fields=[{'name':n,'result':r,'publish':True} for n,r in [('ID','text'),('privilege','text'),('product_sku','text'),('price','number'),('image_main','container'),('quote','container')]]
    schema=ProductSchema({'fields':fields})
    store=SimpleNamespace(source='web',pool=SimpleNamespace(fetchval=AsyncMock(return_value=1)),feed=AsyncMock(return_value=[{'sequence':1,'payload':{'id':'p','version':1,'fields':{'ID':'p','privilege':'008','product_sku':'A','price':99},'assets':[{'id':'main','field':'image_main','mimeType':'image/png','stagingKey':'private'}, {'id':'quote','field':'quote','mimeType':'image/png'}]}}]))
    settings=SimpleNamespace(product_master_web_only=True,product_master_consumers_json=json.dumps({'dms':{'token':'s'*32,'profile':'dms-catalog'}}),filemaker_host='https://fm',filemaker_database='db')
    request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(product_master_preview_store=store,product_master_schema=schema,settings=settings)),headers={'X-Product-Consumer':'dms','X-Product-Source':'web','Authorization':'Bearer '+'s'*32})
    result=await changes(request,cursor=0,limit=100)
    assert result['caughtUp']
    payload=result['events'][0]['payload']
    assert 'price' not in payload['fields']
    assert len(payload['assets'])==1 and 'stagingKey' not in payload['assets'][0]
    request.headers['X-Product-Source']='wrong'
    with pytest.raises(Exception) as error: consumer_auth(request)
    assert error.value.status_code==403


@pytest.mark.asyncio
async def test_repair_preserves_product_version_and_advances_identity_sequence(monkeypatch):
    import importlib.util
    import os
    from uuid import uuid4
    from app.services.product_master.store import ProductStore
    url=os.environ.get('PRODUCT_MASTER_TEST_DATABASE_URL')
    if not url: pytest.skip('isolated PostgreSQL required')
    spec=importlib.util.spec_from_file_location('catalog_repair','backend/scripts/product_catalog_publication.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source='repair-test-'+str(uuid4());store=ProductStore(url,source);await store.init()
    monkeypatch.setattr(module,'get_settings',lambda:SimpleNamespace(audit_database_url=url,product_master_source=source))
    pid=uuid4()
    schema=ProductSchema({'fields':[{'name':'ID','result':'text'}, {'name':'product_sku','result':'text','writable':True}]})
    try:
        await store.save(product_id=pid,expected_version=0,request_id=uuid4(),changes={'product_sku':'A','privilege':'008'},assets=[],actor={'account':'test'},schema=schema,permissions={},imported={'recordId':'1'})
        first=(await store.feed(0))[0]['sequence']
        await store.pool.execute("UPDATE pm_publication SET payload=jsonb_set(payload,'{fields,product_sku}', '\"OLD\"'::jsonb) WHERE source=$1",source)
        assert (await module.run())['mismatches']==1
        result=await module.run(True)
        assert result['repaired']==1 and result['complete']
        assert (await store.get(pid))['version']==1
        events=await store.feed(first)
        assert len(events)==1 and events[0]['payload']['fields']['product_sku']=='A'
        assert (await module.run())['mismatches']==0
    finally:
        for table in ('pm_job','pm_revision','pm_publication','pm_product','pm_source'):
            await store.pool.execute(f'DELETE FROM {table} WHERE source=$1',source)
        await store.close()

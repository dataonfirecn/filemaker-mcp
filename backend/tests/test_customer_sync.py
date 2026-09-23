import os
from uuid import uuid4
import pytest
import pytest_asyncio
from app.services.product_master import customer_sync as sync
from app.services.product_master.store import ProductStore, dumps


def fields(code='001', name='客户甲'):
    return {**{f: '' for f in sync.FIELDS}, '客戶代號': code, '客戶公司簡稱': name, '公司': '公司全称', '聯絡人郵件': 'private@example.test'}


def test_field_whitelist_fallback_duplicates_and_no_contact_leak():
    native = {'CU1': fields(), 'CU2': fields('002', ''), 'CU3': fields('001', '另一个客户')}
    before = {'masters': {}, 'directory': []}
    report = sync.plan(native, before, 'fingerprint', 'source')
    assert report['nativeCount'] == 3 and report['selectableCount'] == 0
    assert report['after']['masters']['CU2']['fields']['客戶公司簡稱'] == ''
    choices = {c['value']: c for c in report['after']['directory']}
    assert choices['CU2']['name'] == '公司全称' and '待完善' in choices['CU2']['label']
    assert choices['CU1']['code'] == '001'
    assert 'private@example.test' not in dumps(choices)
    assert '訂單已收款總金額' not in sync.FIELDS and 'privilege' not in sync.FIELDS


def test_missing_source_retained_and_unchanged_versions_stable():
    original = sync.plan({'CU1': fields(), 'CU2': fields('002')}, {'directory': [], 'masters': {}}, 'f', 's')
    same = sync.plan({'CU1': fields(), 'CU2': fields('002')}, original['after'], 'f', 's')
    assert same['changedCount'] == 0
    removed = sync.plan({'CU1': fields()}, original['after'], 'f', 's')
    assert removed['after']['masters']['CU1']['version'] == 1
    assert removed['after']['masters']['CU2']['sourceMissing'] is True
    assert removed['after']['masters']['CU2']['version'] == 2
    assert removed['directoryCount'] == 2
    assert removed['after']['directory'][1]['selectable'] is False


@pytest.mark.asyncio
async def test_scan_rejects_duplicate_and_missing_columns():
    class Client:
        async def records(self, *args, **kwargs):
            assert '"電話 1"' in kwargs['select'] and '"國家/地區"' in kwargs['select']
            return {'foundCount': 2, 'rows': [{'ID': 'CU1', **fields()}, {'ID': 'CU1', **fields()}]}
    with pytest.raises(ValueError, match='ID'):
        await sync.scan(Client())
    class Missing:
        async def records(self, *args, **kwargs):
            return {'foundCount': 1, 'rows': [{'ID': 'CU1'}]}
    with pytest.raises(ValueError, match='字段缺失'):
        await sync.scan(Missing())


@pytest.mark.asyncio
async def test_metadata_rejects_calculations_even_with_text_result():
    class Client:
        async def get_layout_metadata(self, layout):
            return {'fieldMetaData': [{'name': f, 'type': 'calculation' if f == '公司' else 'normal', 'result': 'text', 'global': False} for f in sync.FIELDS]}
    with pytest.raises(ValueError, match='公司'):
        await sync.verify_fields(Client())


@pytest_asyncio.fixture
async def store():
    url = os.environ.get('PRODUCT_MASTER_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Requires isolated PRODUCT_MASTER_TEST_DATABASE_URL')
    s = ProductStore(url, 'customer-test-' + str(uuid4()), 'f')
    await s.init()
    await s.pool.execute(sync.DDL)
    await s.pool.execute("INSERT INTO pm_reference VALUES($1,'customers','[]',now())", s.source)
    yield s
    for table in ('pm_customer_sync', 'pm_customer', 'pm_reference', 'pm_source'):
        await s.pool.execute(f'DELETE FROM {table} WHERE source=$1', s.source)
    await s.close()


@pytest.mark.asyncio
async def test_atomic_apply_retry_conflict_and_no_product_jobs(store):
    async with store.pool.acquire() as c:
        before = await sync.baseline(c, store.source)
    report = sync.plan({'CU1': fields()}, before, 'f', store.source)
    assert await sync.apply(store.pool, report) == 'applied'
    assert await sync.apply(store.pool, report) == 'alreadyApplied'
    async with store.pool.acquire() as c:
        after = await sync.baseline(c, store.source)
    assert after == report['after']
    update = sync.plan({'CU1': fields(name='新名称')}, after, 'f', store.source)
    await store.pool.execute("UPDATE pm_reference SET payload='[]' WHERE source=$1", store.source)
    with pytest.raises(ValueError, match='改变'):
        await sync.apply(store.pool, update)
    assert await store.pool.fetchval('SELECT version FROM pm_customer WHERE source=$1', store.source) == 1
    assert await store.pool.fetchval('SELECT count(*) FROM pm_customer_sync WHERE source=$1', store.source) == 1
    for table in ('pm_revision','pm_publication','pm_job'):
        assert await store.pool.fetchval(f'SELECT count(*) FROM {table} WHERE source=$1',store.source) == 0


@pytest.mark.asyncio
async def test_concurrent_snapshots_only_one_commits(store):
    import asyncio
    async with store.pool.acquire() as c:
        before = await sync.baseline(c, store.source)
    reports = [sync.plan({'CU1': fields(name=n)}, before, 'f', store.source) for n in ('甲', '乙')]
    results = await asyncio.gather(*(sync.apply(store.pool, r) for r in reports), return_exceptions=True)
    assert results.count('applied') == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert await store.pool.fetchval('SELECT count(*) FROM pm_customer_sync WHERE source=$1', store.source) == 1


@pytest.mark.asyncio
async def test_command_preview_digest_guard_apply_rerun(store, monkeypatch):
    from types import SimpleNamespace
    from scripts import product_customers_sync as command
    settings = SimpleNamespace(audit_database_url=os.environ['PRODUCT_MASTER_TEST_DATABASE_URL'], product_master_source=store.source)
    class Client:
        def __init__(self, settings): pass
        async def close(self): pass
        async def get_layout_metadata(self, layout):
            return {'fieldMetaData': [{'name': f, 'type': 'normal', 'result': 'text', 'global': False} for f in sync.FIELDS]}
        async def records(self, *args, **kwargs):
            return {'foundCount': 1, 'rows': [{'ID': 'CU1', **fields()}]}
    monkeypatch.setattr(command, 'get_settings', lambda: settings)
    monkeypatch.setattr(command, 'source_fingerprint', lambda s: 'f')
    monkeypatch.setattr(command, 'FileMakerClient', Client)
    monkeypatch.setattr(command, 'FileMakerODataClient', Client)
    args = SimpleNamespace(apply=False, expected_digest=None)
    preview = await command.run(args)
    assert preview['result'] == 'preview'
    assert await store.pool.fetchval('SELECT count(*) FROM pm_customer WHERE source=$1', store.source) == 0
    args.apply, args.expected_digest = True, 'wrong'
    with pytest.raises(ValueError, match='摘要'):
        await command.run(args)
    args.expected_digest = preview['digest']
    assert (await command.run(args))['result'] == 'applied'
    assert (await command.run(args))['result'] == 'alreadyApplied'
    assert await store.pool.fetchval('SELECT count(*) FROM pm_customer WHERE source=$1', store.source) == 1

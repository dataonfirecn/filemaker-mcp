"""Read-only verification of main-image completion and preservation of pre-existing files."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from app.core.config import get_settings
from app.api.product_master import get_product, download
from app.services.cos_storage import COSStorageService
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import ProductStore, dumps


class NoFileMaker:
    def __getattr__(self, name):
        raise AssertionError('Unexpected FileMaker call: '+name)


async def run(args):
    settings = get_settings()
    assert settings.product_master_web_only and not settings.product_master_write_enabled
    before = json.loads(Path(args.baseline).read_text())
    backfill = json.loads(Path(args.backfill).read_text())
    assert before['source'] == backfill['source'] == settings.product_master_source
    assert backfill['complete'] and not backfill['failures']
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    await store.init()
    schema = ProductSchema.load(settings.product_master_schema_path)
    assert 'image_main' in schema.fields and '檔案 1 | 容器' not in schema.fields
    assert len([f for f in schema.fields.values() if f.get('role')=='product_image']) == 18
    try:
        originals = [dict(r) for r in await store.pool.fetch("""SELECT v.id,v.asset_id,v.product_id,v.object_key,v.filename,v.mime_type,v.size,v.sha256
            FROM pm_asset_version v JOIN pm_product_asset a ON a.source=v.source AND a.asset_version_id=v.id
            WHERE a.source=$1 AND a.field<>'image_main' ORDER BY v.id""", store.source)]
        digest = hashlib.sha256(json.dumps(originals,sort_keys=True,default=str).encode()).hexdigest()
        assert len(originals) == before['assets'] and digest == before['assetMetadataHash'], 'Original asset metadata changed'
        main = await store.pool.fetch("""SELECT v.*,a.sort_order FROM pm_product_asset a
            JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
            WHERE a.source=$1 AND a.field='image_main' ORDER BY v.size""",store.source)
        assert len(main) == backfill['expectedMainImages'] and all(a['sort_order']==0 for a in main)
        old = await store.pool.fetchval("SELECT count(*) FROM pm_product_asset WHERE source=$1 AND field='檔案 1 | 容器'",store.source)
        assert old == 0
        products = await store.pool.fetch('SELECT id FROM pm_product WHERE source=$1',store.source)
        assert len(products) == backfill['products'] == backfill['checked']
        state = SimpleNamespace(settings=settings,product_master_schema=schema,product_master_preview_store=store,
            cos_storage_service=COSStorageService(settings),filemaker_client=NoFileMaker(),filemaker_odata_client=NoFileMaker())
        request = SimpleNamespace(app=SimpleNamespace(state=state));context={'access':{'canViewProducts':True,'canViewPrice':True}}
        for product in products:
            snapshot = await get_product(str(product['id']),request,context)
            assert all(a['field'] in schema.fields for a in snapshot['assets'])
        samples = [main[0]] if main else []
        if len(main)>1:samples.append(main[-1])
        for a in samples:
            response = await download(a['product_id'],a['id'],request,context)
            assert len(response.body)==a['size'] and hashlib.sha256(response.body).hexdigest()==a['sha256']
        total = await store.pool.fetchval('SELECT count(*) FROM pm_product_asset WHERE source=$1',store.source)
        assert total==len(originals)+len(main)
        report={'complete':True,'source':store.source,'products':len(products),'mainImages':len(main),
            'totalAssets':total,'originalAssetsUnchanged':len(originals),'legacyMainBindings':old,
            'filemakerCalls':0,'sampledCOSDownloads':len(samples)}
        Path(args.report).write_text(dumps(report));print(dumps(report))
    finally:
        await store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='/data/main-image-before.json')
    parser.add_argument('--backfill',default='/data/product-main-image-backfill.json')
    parser.add_argument('--report',default='/data/product-main-image-verification.json')
    asyncio.run(run(parser.parse_args()))

"""Append audited image_main bindings without changing asset IDs, COS objects or old revisions."""
import argparse
import asyncio
from uuid import uuid5, UUID

from app.core.config import get_settings
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import ProductStore
from app.services.product_image_fields import LEGACY_MAIN_IMAGE_FIELD, MAIN_IMAGE_FIELD, canonical_assets


async def rename_main_image(store, schema):
    if MAIN_IMAGE_FIELD not in schema.fields or LEGACY_MAIN_IMAGE_FIELD in schema.fields:
        raise ValueError('The schema must use image_main exclusively')
    changed = 0
    async with store.pool.acquire() as connection, connection.transaction():
        pending = await connection.fetchval("SELECT count(*) FROM pm_job WHERE source=$1 AND status NOT IN ('synced','superseded')", store.source)
        if pending:
            raise ValueError('Resolve pending writeback jobs before migrating field bindings')
        rows = await connection.fetch('SELECT DISTINCT product_id FROM pm_product_asset WHERE source=$1 AND field=$2', store.source, LEGACY_MAIN_IMAGE_FIELD)
        for row in rows:
            product = await store.get(row['product_id'], connection)
            await store.save(
                product_id=product['id'], expected_version=product['version'],
                request_id=uuid5(UUID(str(product['id'])), f'image-main-rename:{product["version"]}'),
                changes={}, assets=canonical_assets(product['assets']),
                actor={'account': 'schema-migration'}, schema=schema, permissions={},
                origin='rename-main-image', connection=connection,
                imported={'recordId': product['fm_record_id'], 'modId': product['fm_mod_id']},
            )
            changed += 1
    return {'renamedProducts': changed, 'field': MAIN_IMAGE_FIELD, 'filesChanged': False}


async def run(args):
    settings = get_settings()
    if settings.product_master_enabled or settings.product_master_write_enabled:
        raise ValueError('Pause product writes and worker before changing bindings')
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    await store.init()
    try:
        print(await rename_main_image(store, ProductSchema.load(args.schema)))
    finally:
        await store.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema', default='config/product_master_web_schema.json')
    asyncio.run(run(parser.parse_args()))

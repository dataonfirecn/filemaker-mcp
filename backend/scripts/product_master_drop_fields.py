"""Remove retired fields' stored values from the current Web product snapshots.

Dry run by default: only counts the rows that still carry a value.
Pass --apply (with product writes paused) to strip them from pm_product.fields.
Revision history and the DMS publication feed are audit records and are never rewritten.
The FileMaker fields themselves are not touched.
"""
import argparse
import asyncio
import json

from app.core.config import get_settings
from app.services.product_master.store import ProductStore

RETIRED = ['報價紀錄', '應課稅', '關聯編號_Price']


async def run(args):
    settings = get_settings()
    if args.apply and (settings.product_master_enabled or settings.product_master_write_enabled):
        raise ValueError('Pause product writes before dropping fields')
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    await store.init(max_size=2)
    report = {'source': store.source, 'fields': args.field, 'applied': bool(args.apply), 'rows': {}}
    try:
        async with store.pool.acquire() as c, c.transaction():
            for name in args.field:
                report['rows'][name] = await c.fetchval('SELECT count(*) FROM pm_product WHERE source=$1 AND fields ? $2', store.source, name)
            if args.apply:
                for name in args.field:
                    await c.execute('UPDATE pm_product SET fields=fields-$2::text WHERE source=$1 AND fields ? $2', store.source, name)
                report['remaining'] = {name: await c.fetchval('SELECT count(*) FROM pm_product WHERE source=$1 AND fields ? $2', store.source, name) for name in args.field}
    finally:
        await store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--field', action='append', default=None, help='field to strip; defaults to the retired quote-record fields')
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    a.field = a.field or RETIRED
    asyncio.run(run(a))

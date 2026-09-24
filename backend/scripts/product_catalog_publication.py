#!/usr/bin/env python3
"""Audit active Web products against latest publication; --repair refreshes missing or stale snapshots.

Never reads FileMaker or alters products. Repair locks product writes while comparing,
then republishes events at existing versions with new sequence numbers. Run before bootstrapping a fresh consumer.
The manifest hashes UUID, version, allowed fields and current image associations.
"""
import argparse
import asyncio
import hashlib
import json
from collections import Counter

import asyncpg
from app.core.config import get_settings
from app.services.product_master.store import ProductStore, unpack, dumps
from app.services.product_catalog_contract import catalog_snapshot


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def public_value(product):
    item = catalog_snapshot(product)
    return {k: item[k] for k in ('id', 'version', 'fields', 'assets')}


async def run(repair=False):
    settings = get_settings()
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    store.pool = await asyncpg.create_pool(store.url, min_size=1, max_size=1)
    try:
        async with store.pool.acquire() as c, c.transaction():
            if repair:
                await c.execute('LOCK TABLE pm_product IN SHARE MODE')
                await c.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", 'pm-feed:'+store.source)
            else:
                await c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            products = await c.fetch('SELECT * FROM pm_product WHERE source=$1 ORDER BY id', store.source)
            latest = {str(r['product_id']): unpack(r)['payload'] for r in await c.fetch('''
                SELECT DISTINCT ON(product_id) product_id,payload FROM pm_publication
                WHERE source=$1 ORDER BY product_id,sequence DESC''', store.source)}
            values=[]; issues=[]; scopes=Counter(); images=0
            for row in products:
                product=await store.hydrate(unpack(row),c)
                snapshot={'id':str(product['id']),'version':product['version'],'fields':product['fields'],
                          'assets':product['assets'],'filemakerRecordId':product['fm_record_id']}
                value=public_value(snapshot); values.append(value); images+=len(value['assets'])
                for scope in set(str(value['fields'].get('privilege') or '').replace('\r','\n').split('\n')):
                    if scope.strip(): scopes[scope.strip()]+=1
                previous=latest.get(value['id'])
                if previous is None or canonical(public_value(previous)) != canonical(value):
                    issues.append(value['id'])
                    if repair:
                        # One event per product/version is enforced by the existing schema.
                        # Move a repaired event beyond all consumer cursors; business data
                        # and immutable revision history remain untouched.
                        await c.execute('''INSERT INTO pm_publication(source,product_id,version,payload)
                            VALUES($1,$2,$3,$4::jsonb)
                            ON CONFLICT(source,product_id,version) DO UPDATE SET
                            sequence=DEFAULT,payload=EXCLUDED.payload''',
                            store.source,product['id'],product['version'],dumps(snapshot))
            orphaned=sorted(set(latest)-{v['id'] for v in values})
            if orphaned and repair:
                raise RuntimeError('Publication includes removed products; refusing repair without a withdrawal policy')
            return {'source':store.source,'products':len(values),'images':images,'scopes':dict(scopes),
                    'manifestSha256':hashlib.sha256(canonical(values).encode()).hexdigest(),
                    'mismatches':len(issues),'orphaned':len(orphaned),'repaired':len(issues) if repair else 0,
                    'complete':not orphaned and (repair or not issues)}
    finally:
        await store.pool.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repair',action='store_true');args=parser.parse_args()
    result=asyncio.run(run(args.repair));print(canonical(result))
    raise SystemExit(0 if result['complete'] else 1)

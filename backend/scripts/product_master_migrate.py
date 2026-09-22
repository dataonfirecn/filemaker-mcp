#!/usr/bin/env python3
"""Read-only preflight by default; --apply imports immutable files and snapshots.
Use the dedicated full-product layout; never writes FileMaker records or containers.
"""
import argparse
import asyncio
import hashlib
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, unquote, quote
from uuid import UUID, uuid5, NAMESPACE_URL

from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.cos_storage import COSStorageService
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import ProductStore, dumps, source_fingerprint
from app.services.product_master.importer import import_product, legacy_slots


async def run(args):
    settings = get_settings(); fm = FileMakerClient(settings); store = None
    report = {'products': 0, 'imported': 0, 'alreadyImported': 0, 'assets': 0, 'failures': [], 'missingFields': [], 'complete': False}
    try:
        schema = ProductSchema.load(settings.product_master_schema_path)
        meta = (await fm.request('/layouts/' + quote(args.layout, safe='')))['response']['fieldMetaData']
        available = {f['name'] for f in meta if '::' not in f['name']}
        base = set(json.loads(Path(args.base_fields).read_text())) if args.base_fields else set()
        report['baseTableVerified'] = bool(base)
        report['missingFields'] = sorted(base - available)
        report['unregisteredFields'] = sorted(available - set(schema.fields))
        report['containers'] = [{'name': f['name'], 'repetitions': f.get('maxRepeat',1), 'type': f['type']} for f in meta if f['result'] == 'container']
        identities, locators, records = set(), set(), []
        offset, total = 1, None
        while True:
            page = await fm.find_records(args.layout, limit=200, offset=offset)
            if total is None: total = page['foundCount']
            if page['foundCount'] != total: raise ValueError('Record count changed during scan; retry')
            for row in page['data']:
                identity = str(UUID(str(row['fieldData'].get('ID') or '')))
                if identity in identities or row['recordId'] in locators: raise ValueError('Duplicate product identity')
                identities.add(identity); locators.add(row['recordId']); records.append(row)
            offset += len(page['data'])
            if len(records) >= total: break
            if not page['data']: raise ValueError('Incomplete product scan')
        report['products'] = len(records)
        if not args.apply:
            return report
        if not base or report['missingFields'] or report['unregisteredFields']:
            raise ValueError('Complete base-field manifest and matching schema are required for import')
        store = ProductStore(settings.audit_database_url, settings.product_master_source, source_fingerprint(settings)); await store.init()
        storage = COSStorageService(settings)
        # Conflicting legacy identities block their product, never the whole migration.
        legacy_rows = []; asset_offset = 1
        while True:
            page = await fm.find_records('ProductAssets', limit=200, offset=asset_offset)
            legacy_rows.extend(page['data'])
            asset_offset += len(page['data'])
            if asset_offset > page['foundCount'] or not page['data']: break
        legacy = legacy_slots(legacy_rows)
        for row in records:
            identity = str(UUID(row['fieldData']['ID']))
            try:
                existing = await store.get(identity)
                if existing:
                    if existing['fm_record_id'] != row['recordId']: raise ValueError('Existing UUID changed locator')
                    report['alreadyImported'] += 1; continue
                imported = await import_product(store, schema, fm, storage, settings, row, legacy)
                report['imported'] += 1; report['assets'] += len(imported['assets'])
                if report['imported'] % 25 == 0:
                    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))
                    print(json.dumps({k:report[k] for k in ('products','imported','alreadyImported','assets')}) , flush=True)
            except Exception as exc:
                report['failures'].append({'productId':identity,'error':type(exc).__name__ + ': ' + str(exc)[:200]})
        report['complete'] = not report['failures'] and report['imported'] + report['alreadyImported'] == report['products']
        if report['complete']:
            await store.pool.execute('UPDATE pm_source SET initial_import_complete=true WHERE source=$1', store.source)
        return report
    finally:
        if store: await store.close()
        await fm.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', default='@products_web')
    parser.add_argument('--base-fields', help='JSON array of all field names exported from the actual products base table')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', default='product-master-preflight.json')
    args = parser.parse_args()
    result = asyncio.run(run(args))
    Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.apply and not result['complete']: raise SystemExit(1)

#!/usr/bin/env python3
"""Read native related prices; dry-run by default, resume without overwriting Web edits."""
import argparse
import asyncio
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

import asyncpg
from app.core.config import get_settings
from app.services.product_master.finance import read_snapshot, load_snapshot, store_snapshot, FINANCE_FIELDS, FinanceFileMakerClient, scan_finance_sources, price_snapshot
from app.services.product_master.schema import ProductSchema
from app.services.product_master.store import ProductStore, source_fingerprint, dumps, unpack


async def run(args):
    settings = get_settings()
    schema = ProductSchema.load(settings.product_master_schema_path)
    if not FINANCE_FIELDS <= schema.fields.keys():
        raise ValueError('请先部署包含关联售价的字段注册表')
    pool = await asyncpg.create_pool(settings.audit_database_url, min_size=1, max_size=2)
    fm = FinanceFileMakerClient(settings)
    store = ProductStore(settings.audit_database_url, settings.product_master_source)
    store.pool = pool
    report = {'source': store.source, 'fingerprint': source_fingerprint(settings), 'scanned': 0, 'applied': 0, 'unchanged': 0, 'issues': [], 'rows': []}
    output = Path(args.report)
    output.touch(mode=0o600, exist_ok=True)
    def persist():
        output.write_text(dumps(report) + '\n')
    persist()
    try:
        if await pool.fetchval('SELECT fingerprint FROM pm_source WHERE source=$1', store.source) != source_fingerprint(settings):
            raise ValueError('Web 与 FileMaker 数据源不一致')
        products = await pool.fetch('''SELECT * FROM pm_product WHERE source=$1
            AND ($2::text IS NULL OR fields->>'product_sku'=$2) ORDER BY id''', store.source, args.sku)
        if args.sku and len(products) != 1:
            raise ValueError('SKU 在 Web 中不存在或不唯一')
        owners = defaultdict(set)
        all_products = await pool.fetch('SELECT id,fields FROM pm_product WHERE source=$1', store.source)
        for row in all_products:
            item = unpack(row)
            for key in ('product_sku', '系統產品編號'):
                if item['fields'].get(key): owners[str(item['fields'][key])].add(str(item['id']))
        selected = products[args.offset:args.offset + args.limit] if args.limit else products[args.offset:]
        report['selected'] = len(selected)
        price_rows, price_index = None, defaultdict(list)
        if args.bulk or not args.sku:
            def progress(layout, done, total):
                if done % 1000 == 0 or done == total: print(f'{layout}: {done}/{total}', flush=True)
            price_rows = await scan_finance_sources(fm, progress)
            for row in price_rows.values(): price_index[str(row['fieldData'].get('產品編號') or '')].append(row)
        for row in selected:
            product = unpack(row); pid = product['id']; report['scanned'] += 1
            try:
                baseline = await load_snapshot(pool, store.source, pid)
                if baseline and not args.refresh:
                    report['unchanged'] += 1
                    continue
                if price_rows is not None:
                    keys = {str(product['fields'].get(k) or '') for k in ('product_sku', '系統產品編號')} - {''}
                    prices = [r for key in keys for r in price_index[key]]
                    first = price_snapshot(product, prices)
                else:
                    first = await read_snapshot(fm, product)
                    second = await read_snapshot(fm, product)
                    if dumps(first) != dumps(second):
                        raise ValueError('扫描期间关联数据发生变化，请重试')
                if first.get('price') and len(owners[str(first['price']['fieldData']['產品編號'])]) != 1:
                    raise ValueError('售价关联编号匹配多个 Web 产品，禁止导入')
                digest = hashlib.sha256(dumps(first).encode()).hexdigest()
                report['rows'].append({'productId': str(pid), 'sku': product['fields'].get('product_sku'),
                    'snapshot': first, 'digest': digest})
                if first['issues']:
                    report['issues'].append({'productId': str(pid), 'fields': first['issues'], 'error': '源售价异常；保留为空，不作为零'})
                if not args.apply:
                    continue
                async with pool.acquire() as c, c.transaction():
                    await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', store.source + str(pid))
                    current = await store.hydrate(unpack(await c.fetchrow(
                        'SELECT * FROM pm_product WHERE source=$1 AND id=$2', store.source, pid)), c)
                    pending = await c.fetchval("SELECT EXISTS(SELECT 1 FROM pm_job WHERE source=$1 AND product_id=$2 AND status NOT IN ('synced','superseded'))", store.source, pid)
                    if pending:
                        raise ValueError('产品存在待同步任务，暂不导入关联价格')
                    if current['version'] != product['version']:
                        raise ValueError('扫描期间 Web 产品已修改，请重试')
                    fresh_baseline = await load_snapshot(c, store.source, pid)
                    if dumps(fresh_baseline) != dumps(baseline):
                        raise ValueError('关联来源版本已改变，请重试')
                    if baseline:
                        if any(current['fields'].get(k, '') != baseline['fields'].get(k, '') for k in FINANCE_FIELDS):
                            raise ValueError('Web 售价已修改，禁止自动覆盖')
                        # External price changes require review before replacing the saved baseline.
                        if dumps(first.get('price')) != dumps(baseline.get('price')):
                            raise ValueError('FileMaker 售价来源已改变，需人工核对差异')
                    elif any(k in current['fields'] for k in FINANCE_FIELDS):
                        raise ValueError('Web 已有无来源的关联字段，禁止覆盖')
                    changes = {k:v for k,v in first['fields'].items() if current['fields'].get(k) != v}
                    if changes:
                        saved = await store.save(product_id=pid, expected_version=current['version'], request_id=uuid4(),
                            changes=changes, assets=None, actor={'account':'product-finance-import'}, schema=schema,
                            permissions={}, origin='filemaker-finance-import',
                            imported={'recordId':current['fm_record_id'],'modId':current['fm_mod_id']}, connection=c)
                        if any(saved['fields'].get(k) != v for k,v in first['fields'].items()):
                            raise ValueError('Web 关联字段保存核验失败')
                    await store_snapshot(c, store.source, pid, first)
                    report['applied'] += 1
            except Exception as exc:
                report['issues'].append({'productId':str(pid),'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__})
            finally:
                if report['scanned'] % 1000 == 0 or len(selected) < 100:
                    persist()
                    print(f'Products: {report["scanned"]}/{report["selected"]}, applied={report["applied"]}, issues={len(report["issues"])}', flush=True)
        report['complete'] = not report['issues'] and report['scanned'] == report['selected']
        persist()
        print(dumps({k:v for k,v in report.items() if k not in ('rows','issues')}))
        print('Issues:',len(report['issues']))
    finally:
        await fm.close(); await pool.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--sku')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=0, help='0 = all Web products')
    parser.add_argument('--bulk', action='store_true', help='read the stored sale price layout twice; never imports calculated costs')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='recheck saved prices; refuse changed Web values or source')
    args = parser.parse_args()
    if args.offset < 0 or args.limit < 0:
        parser.error('offset / limit cannot be negative')
    result = asyncio.run(run(args))
    if not result['complete']:
        raise SystemExit(1)

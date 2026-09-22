#!/usr/bin/env python3
"""Preview by default. --apply --expected-digest DIGEST applies a verified snapshot.

Never writes FileMaker; never overwrites an imported quote, including Web edits.
"""
import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

import asyncpg

from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.product_master.quote_import import scan_quotes, preflight, manifest_digest
from app.services.product_master.quotes import DDL, QuoteStore, decode
from app.services.product_master.store import ProductStore, source_fingerprint, dumps


class ExactFileMakerClient(FileMakerClient):
    def _safe_json(self, response):
        return json.loads(response.text, parse_float=Decimal)


async def run(args):
    settings = get_settings()
    if settings.product_quote_write_enabled:
        raise ValueError('导入期间必须关闭 PRODUCT_QUOTE_WRITE_ENABLED')
    fm = ExactFileMakerClient(settings)
    pool = await asyncpg.create_pool(settings.audit_database_url, min_size=1, max_size=2)
    try:
        fingerprint = source_fingerprint(settings)
        source = settings.product_master_source
        if await pool.fetchval('SELECT fingerprint FROM pm_source WHERE source=$1', source) != fingerprint:
            raise ValueError('FileMaker 数据源与 Web 产品主库不一致')
        products = [dict(p) for p in await pool.fetch('SELECT id,fields FROM pm_product WHERE source=$1 ORDER BY id', source)]
        for p in products:
            p['fields'] = decode(p['fields'])
        raw = await pool.fetchval("SELECT payload FROM pm_reference WHERE source=$1 AND name='customers'", source)
        if raw is None:
            raise ValueError('请先导入并核对 Web 客户目录')
        customers = decode(raw)
        quotes = await scan_quotes(fm, '@ProductPrice')
        members = await scan_quotes(fm, '@ProductPriceCustomer')
        # A second pass detects edits/deletions while the two related tables were scanned.
        for layout, original in [('@ProductPrice', quotes), ('@ProductPriceCustomer', members)]:
            again = await scan_quotes(fm, layout)
            signature = lambda rows: sorted((r['recordId'], str(r.get('modId')), dumps(r['fieldData'])) for r in rows)
            if signature(original) != signature(again):
                raise ValueError('扫描期间报价或客户成员改变，请暂停原生修改后重试')
        report = preflight(quotes, members, products, customers)
        report['digest'] = manifest_digest(report, fingerprint, customers)
        report.update(source=source, fingerprint=fingerprint, applied=0, alreadyImported=0, verified=0, complete=False)
        if not args.apply:
            return report
        if not args.expected_digest or args.expected_digest != report['digest']:
            raise ValueError('预览摘要不一致；请重新预览并核对后使用 --expected-digest')
        if report['issues']:
            return report
        await pool.execute(DDL)
        product_store = ProductStore(settings.audit_database_url, source)
        product_store.pool = pool
        store = QuoteStore(product_store)
        for row in report['rows']:
            existing = await pool.fetchrow('SELECT * FROM pm_quote WHERE source=$1 AND source_id=$2', source, row['sourceId'])
            if existing:
                if str(existing['product_id']) != row['productId'] or decode(existing['source_data']) != json.loads(dumps(row['sourceData'])):
                    report['issues'].append({'sourceId': row['sourceId'], 'error': '已导入来源发生变化；禁止覆盖'})
                    continue
                report['alreadyImported'] += 1
            else:
                await store.save(product_id=row['productId'], quote_id=None, expected_version=0,
                                 request_id=uuid5(NAMESPACE_URL, f'{source}:quote-import:{row["sourceId"]}'),
                                 data=row['data'], actor={'account': 'quote-import', 'name': 'FileMaker 报价导入'},
                                 directory=customers, source_id=row['sourceId'], source_data=row['sourceData'])
                report['applied'] += 1
            saved = await pool.fetchrow('SELECT id FROM pm_quote WHERE source=$1 AND source_id=$2', source, row['sourceId'])
            original = decode(await pool.fetchval('SELECT after_data FROM pm_quote_revision WHERE source=$1 AND quote_id=$2 AND version=1', source, saved['id']))
            expected = row['data']
            if (original and original['productId'] == row['productId'] and original['title'] == expected['title']
                    and Decimal(original['amount']) == Decimal(expected['amount']) and original['currency'] == expected['currency']
                    and sorted(m['id'] for m in original['customers']) == expected['customerIds']):
                report['verified'] += 1
            else:
                report['issues'].append({'sourceId': row['sourceId'], 'error': '首次导入版本核验不一致'})
        report['complete'] = not report['issues'] and report['verified'] == report['quoteCount']
        return report
    finally:
        await pool.close()
        await fm.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        # Do not expose connection strings or raw upstream errors in a report.
        result = {'complete': False, 'issues': [{'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}]}
    output = Path(args.report)
    output.touch(mode=0o600, exist_ok=True)
    output.write_text(dumps(result)+'\n')
    print(dumps({k: v for k, v in result.items() if k not in ('rows', 'issues')}))
    print(f'Issues: {len(result.get("issues", []))}; report: {output}')
    if result.get('issues') or (args.apply and not result.get('complete')):
        raise SystemExit(1)

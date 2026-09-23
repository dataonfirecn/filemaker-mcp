#!/usr/bin/env python3
"""Preview FileMaker customers; apply only the exact reviewed digest. Never write FM."""
import argparse
import asyncio
import os
from pathlib import Path
import asyncpg
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.product_master import customer_sync as sync
from app.services.product_master.store import dumps, source_fingerprint


async def run(args):
    settings = get_settings()
    fm, odata = FileMakerClient(settings), FileMakerODataClient(settings)
    pool = await asyncpg.create_pool(settings.audit_database_url, min_size=1, max_size=2)
    try:
        source = settings.product_master_source
        fingerprint = source_fingerprint(settings)
        async with pool.acquire() as c:
            if await c.fetchval('SELECT fingerprint FROM pm_source WHERE source=$1', source) != fingerprint:
                raise ValueError('客户 FileMaker 来源与产品主库不一致')
            if args.apply and args.expected_digest and await c.fetchval("SELECT to_regclass('public.pm_customer_sync')"):
                if await c.fetchval('SELECT 1 FROM pm_customer_sync WHERE source=$1 AND digest=$2', source, args.expected_digest):
                    return {'source': source, 'digest': args.expected_digest, 'result': 'alreadyApplied'}
            before = await sync.baseline(c, source)
        await sync.verify_fields(fm)
        native = await sync.scan(odata)
        if native != await sync.scan(odata):
            raise ValueError('扫描期间客户资料改变，请重试')
        report = sync.plan(native, before, fingerprint, source)
        report['result'] = 'preview'
        if args.apply:
            if not args.expected_digest or args.expected_digest != report['digest']:
                raise ValueError('客户同步预览摘要改变，请重新核对')
            await pool.execute(sync.DDL)
            report['result'] = await sync.apply(pool, report)
        return report
    finally:
        await pool.close()
        await fm.close()
        await odata.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-digest')
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        result = {'result': 'failed', 'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    # Report includes customer contact data: keep owner-only and never print full contents.
    path = Path(args.report)
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(dumps(result) + '\n')
    print(dumps({k: v for k, v in result.items() if k not in ('before', 'after', 'issues')}))
    if result['result'] == 'failed':
        raise SystemExit(1)

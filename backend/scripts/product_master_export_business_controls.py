#!/usr/bin/env python3
"""Refresh the product business layout's control snapshot; never modifies FileMaker."""
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient

FIELDS = {'車子比例', '車款', '產品分類', '類別', '審核', '有現貨', 'ShowStock'}

async def run(output):
    settings = get_settings()
    settings.filemaker_timeout_seconds = 600
    fm = FileMakerClient(settings)
    try:
        metadata = await fm.get_layout_metadata('產品 資料_業務')
        fields = [f for f in metadata.get('fieldMetaData', []) if f['name'] in FIELDS]
        missing = FIELDS - {f['name'] for f in fields}
        if missing:
            raise ValueError(f'Missing native controls: {sorted(missing)}')
        used = {f.get('valueList') for f in fields}
        lists = [v for v in metadata.get('valueLists', []) if v['name'] in used]
        if used - {v['name'] for v in lists}:
            raise ValueError('Incomplete native value lists')
        result = {'sourceLayout': '產品 資料_業務', 'verifiedAt': datetime.now(timezone.utc).isoformat(),
                  'fieldMetaData': fields, 'valueLists': lists}
        target = Path(output)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(target)
        print(json.dumps({v['name']: len(v.get('values', [])) for v in lists}, ensure_ascii=False))
    finally:
        await fm.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='config/product_master_business_controls.json')
    asyncio.run(run(parser.parse_args().output))

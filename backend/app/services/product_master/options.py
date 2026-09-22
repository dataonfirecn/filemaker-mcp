"""Read native product controls; never infer choices from existing product values."""
import asyncio
import json
from pathlib import Path
from time import monotonic


async def native_controls(request):
    state = request.app.state
    if getattr(getattr(state, 'settings', None), 'product_master_web_only', False):
        from .store import unpack
        store = getattr(state, 'product_master_preview_store', None) or state.product_master_store
        row = await store.pool.fetchrow('SELECT payload FROM pm_reference WHERE source=$1 AND name=$2', store.source, 'controls')
        if not row:
            raise ValueError('Web 字段选项未导入')
        return json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
    if not hasattr(state, 'product_controls_lock'):
        state.product_controls_lock = asyncio.Lock()
    async with state.product_controls_lock:
        cached = getattr(state, 'product_controls_cache', None)
        if cached and monotonic() - cached[0] < 300:
            return cached[1]
        controls = {}
        # Business layout snapshot avoids fetching its multi-megabyte unrelated value lists per page.
        # Refresh using product_master_export_business_controls.py after native option changes.
        # Business controls win for shared fields; value lists stay scoped to their layout.
        for layout in ('产品报价', '產品 資料_業務'):
            if layout == '產品 資料_業務':
                metadata = json.loads((Path(__file__).resolve().parents[3] / 'config/product_master_business_controls.json').read_text())
            else:
                metadata = await state.filemaker_client.get_layout_metadata(layout)
            lists = {item['name']: item.get('values', []) for item in metadata.get('valueLists', [])}
            for field in metadata.get('fieldMetaData', []):
                if '::' in field['name'] or field.get('displayType', 'editText') == 'editText':
                    continue
                options = {}
                for item in lists.get(field.get('valueList'), []):
                    value = str(item.get('value', ''))
                    if value and value not in options:
                        options[value] = {'value': value, 'label': str(item.get('displayValue', value))}
                controls[field['name']] = {'type': field['displayType'], 'options': list(options.values())}
        state.product_controls_cache = (monotonic(), controls)
        return controls


async def customer_options(request):
    # ID is part of FileMaker's compound OData key, not a selectable column.
    from app.services.part_creation import _customer_id_from_odata_row
    state = request.app.state
    if getattr(getattr(state, 'settings', None), 'product_master_web_only', False):
        store = getattr(state, 'product_master_preview_store', None) or state.product_master_store
        row = await store.pool.fetchrow('SELECT payload FROM pm_reference WHERE source=$1 AND name=$2', store.source, 'customers')
        if not row:
            raise ValueError('Web 客户目录未导入')
        return json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
    if not hasattr(state, 'product_customers_lock'):
        state.product_customers_lock = asyncio.Lock()
    async with state.product_customers_lock:
        cached = getattr(state, 'product_customers_cache', None)
        if cached and monotonic() - cached[0] < 300:
            return cached[1]
        rows = []
        offset = 0
        while True:
            page = await state.filemaker_odata_client.records('客戶',
                select=['客戶代號', '客戶公司簡稱'], top=200, skip=offset, count=True)
            batch = page.get('rows', [])
            for item in batch:
                identity = _customer_id_from_odata_row(item)
                name = str(item.get('客戶公司簡稱') or '').strip()
                if identity and name:
                    rows.append({'value': identity, 'name': name, 'label': name,
                                 'code': str(item.get('客戶代號') or '')})
            offset += len(batch)
            if offset >= int(page.get('foundCount') or 0) and not page.get('nextLink'):
                break
            if not batch or offset > 100000:
                raise ValueError('Customer directory scan incomplete')
        state.product_customers_cache = (monotonic(), rows)
        return rows

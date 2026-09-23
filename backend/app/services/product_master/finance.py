"""Product-owned finance slots backed by native related records, never inferred sums."""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from .store import dumps

PRICE_LAYOUT = '@產品售價'
NATIVE_LAYOUT = '产品报价'
PRICE_FIELDS = {'EX-Price': 'Price', '台幣出廠': '台灣售價', 'RMB出廠': 'RMB售價'}
COST_FIELDS = {'RMB成本': '產品 BOM::產品成本', '美金成本': '產品 BOM::計算美金'}
FINANCE_FIELDS = set(PRICE_FIELDS)


from app.services.filemaker_client import FileMakerClient


class FinanceFileMakerClient(FileMakerClient):
    def _decode_json(self, response):
        import json
        return json.loads(response.text, parse_float=Decimal)

    async def get_record(self, layout, record_id):
        if layout != NATIVE_LAYOUT:
            return await super().get_record(layout, record_id)
        response = await self.request(f'/layouts/{quote(layout, safe="")}/records/{quote(str(record_id), safe="")}',
                                      params={'portal': '[]'})
        return response.get('response', {}).get('data', [])

    async def finance_page(self, layout, offset):
        response = await self.request(f'/layouts/{quote(layout, safe="")}/records',
                                      params={'_limit': 500, '_offset': offset, 'portal': '[]'})
        body = response.get('response', {})
        info = body.get('dataInfo', {})
        if 'foundCount' not in info or 'data' not in body:
            raise ValueError('关联数据分页响应不完整')
        return {'data': body['data'], 'foundCount': int(info['foundCount'])}



def reference_name(product_id):
    return 'product-finance:' + str(product_id)


def decode(value):
    import json
    return json.loads(value) if isinstance(value, str) else value


def amount(value):
    if value in ('', None):
        return ''
    if isinstance(value, bool) or len(str(value)) > 128:
        raise ValueError('无效金额')
    try:
        number = Decimal(str(value))
        if (not number.is_finite() or number < 0 or number.adjusted() > 30
                or number.as_tuple().exponent < -64 or len(number.as_tuple().digits) > 96):
            raise InvalidOperation()
        return format(number, 'f')
    except InvalidOperation as exc:
        raise ValueError('FileMaker 金额或计算结果无效') from exc


def same_amount(left, right):
    a, b = amount(left), amount(right)
    return a == b if '' in (a, b) else Decimal(a) == Decimal(b)


def validate_native(product, native):
    fields = native['fieldData']
    if str(native['recordId']) != str(product['fm_record_id']):
        raise ValueError('产品原生布局 recordId 与 Web 来源不一致')
    for key in ('product_sku', '系統產品編號'):
        if str(fields.get(key) or '') != str(product['fields'].get(key) or ''):
            raise ValueError('FileMaker 产品编号已改变，请先核对产品资料')


def cost_snapshot(product, native):
    validate_native(product, native)
    values, issues = {}, {}
    for name, field in COST_FIELDS.items():
        if field not in native['fieldData']:
            raise ValueError('原产品报价布局缺少关联成本字段：' + field)
        try:
            values[name] = amount(native['fieldData'][field])
        except ValueError:
            values[name] = ''
            issues[name] = 'FileMaker BOM 计算异常，请核对原成本及汇率'
    from datetime import datetime, timezone
    return {'fields':values, 'issues':issues, 'calculatedAt':datetime.now(timezone.utc).isoformat()}


async def read_costs(fm, product):
    if not product.get('fm_record_id'):
        raise ValueError('产品尚未关联 FileMaker，无法读取实时成本')
    rows = await fm.get_record(NATIVE_LAYOUT, str(product['fm_record_id']))
    if len(rows) != 1:
        raise ValueError('原产品记录不存在或不唯一')
    return cost_snapshot(product, rows[0])


def price_snapshot(product, price_rows):
    identifiers = {str(product['fields'].get(k) or '') for k in ('product_sku', '系統產品編號')} - {''}
    if len(price_rows) > 1:
        raise ValueError('产品匹配多条售价记录，禁止任选一条')
    price = price_rows[0] if price_rows else None
    if price and str(price['fieldData'].get('產品編號') or '') not in identifiers:
        raise ValueError('售价关联编号不一致')
    values = {}
    for name, field in PRICE_FIELDS.items():
        if price and field not in price['fieldData']:
            raise ValueError('布局缺少售价字段：' + field)
        values[name] = amount(price['fieldData'][field] if price else '')
    return {'fields':values, 'issues':{}, 'price':price,
            'productRecordId':str(product['fm_record_id']), 'identifiers':sorted(identifiers)}


async def read_snapshot(fm, product):
    identifiers = sorted({str(product['fields'].get(k) or '') for k in ('product_sku', '系統產品編號')} - {''})
    if not identifiers or not product.get('fm_record_id'):
        raise ValueError('产品缺少可核对的 FileMaker 来源')
    result = await fm.find_records(PRICE_LAYOUT, [{'產品編號': '==' + key} for key in identifiers], limit=3)
    if result['foundCount'] != len(result['data']) or result['foundCount'] > 1:
        raise ValueError('产品匹配多条售价记录，需先核对')
    return price_snapshot(product, result['data'])


async def load_snapshot(c, source, product_id):
    value = await c.fetchval('SELECT payload FROM pm_reference WHERE source=$1 AND name=$2', source, reference_name(product_id))
    return decode(value) if value else None


async def store_snapshot(c, source, product_id, snapshot):
    await c.execute('''INSERT INTO pm_reference(source,name,payload) VALUES($1,$2,$3::jsonb)
        ON CONFLICT(source,name) DO UPDATE SET payload=EXCLUDED.payload,updated_at=now()''',
        source, reference_name(product_id), dumps(snapshot))


async def validate_binding(c, source, product_id, changes, old_fields):
    selected = set(changes) & set(PRICE_FIELDS)
    identity_changed = any(k in changes and changes[k] != old_fields.get(k) for k in ('product_sku', '系統產品編號'))
    if not selected and not identity_changed:
        return
    snapshot = await load_snapshot(c, source, product_id)
    if identity_changed and snapshot and snapshot.get('price'):
        raise ValueError('产品已有独立售价关联，需先核对关联后再修改产品编号')
    if selected:
        if not snapshot or not snapshot.get('price'):
            raise ValueError('尚未绑定唯一的 FileMaker 售价记录，请先同步售价')
        key = str(snapshot['price']['fieldData']['產品編號'])
        duplicates = await c.fetchval("SELECT EXISTS(SELECT 1 FROM pm_product WHERE source=$1 AND id<>$2 AND (fields->>'product_sku'=$3 OR fields->>'系統產品編號'=$3))", source, product_id, key)
        if duplicates:
            raise ValueError('售价关联编号匹配多个 Web 产品，禁止保存')
        for name in selected:
            amount(changes[name])


async def sync_prices(fm, c, source, product_id, before, after, steps, checkpoint):
    """CAS + durable in-flight intent: retries verify actual values before acknowledging."""
    from .worker import DriftError
    changed = {name: after[name] for name in PRICE_FIELDS
               if name in after and not same_amount(before.get(name), after[name])}
    if not changed or steps.get('relatedPrices'):
        return
    baseline = await load_snapshot(c, source, product_id)
    if not baseline or not baseline.get('price'):
        raise DriftError('售价来源未绑定，停止关联表回写')
    bound = baseline['price']
    key = str(bound['fieldData']['產品編號'])
    if key not in {str(after.get(k) or '') for k in ('product_sku', '系統產品編號')}:
        raise DriftError('产品编号与售价来源不一致')
    result = await fm.find_records(PRICE_LAYOUT, {'產品編號': '==' + key}, limit=2)
    if result['foundCount'] != 1 or len(result['data']) != 1:
        raise DriftError('FileMaker 售价记录缺失或不唯一')
    remote = result['data'][0]
    if str(remote['recordId']) != str(bound['recordId']):
        raise DriftError('FileMaker 售价记录定位改变')
    # Validate source field definitions before ever sending a related-table write.
    metadata = await fm.get_layout_metadata(PRICE_LAYOUT)
    meta = {f['name']: f for f in metadata['fieldMetaData']}
    for target in (PRICE_FIELDS[n] for n in changed):
        field = meta.get(target, {})
        if field.get('type') != 'normal' or field.get('result') != 'number' or field.get('global') or int(field.get('maxRepeat', 1)) != 1:
            raise DriftError('售价字段定义变化，禁止回写')
    expected = {PRICE_FIELDS[name]: amount(value) for name, value in changed.items()}
    def matches(row):
        return all(k in row['fieldData'] and same_amount(row['fieldData'][k], v) for k, v in expected.items())
    intent = steps.get('relatedPriceIntent')
    if str(remote['modId']) != str(bound['modId']):
        if not intent or intent != {'recordId': str(bound['recordId']), 'fields': expected} or not matches(remote):
            raise DriftError('FileMaker 售价版本发生变化，请核对后再同步')
    else:
        steps['relatedPriceIntent'] = {'recordId': str(bound['recordId']), 'fields': expected}
        await checkpoint()
        response = await fm.request(f'/layouts/{quote(PRICE_LAYOUT, safe="")}/records/{remote["recordId"]}',
            method='PATCH', json_body={'fieldData': expected, 'modId': str(remote['modId'])})
        if any(str(m.get('code')) != '0' for m in response.get('messages', [])):
            raise DriftError('FileMaker 拒绝售价回写，请核对版本和字段权限')
        checked = await fm.get_record(PRICE_LAYOUT, str(remote['recordId']))
        if len(checked) != 1:
            raise DriftError('售价回读记录不唯一')
        remote = checked[0]
    if str(remote['fieldData'].get('產品編號')) != key or not matches(remote):
        raise DriftError('售价回读结果不一致')
    # Both updates must commit together; the worker caller supplies a transaction here.
    async with c.transaction():
        baseline['price'] = remote
        baseline['fields'].update(changed)
        await store_snapshot(c, source, product_id, baseline)
        steps['relatedPrices'] = True
        steps.pop('relatedPriceIntent', None)
        await checkpoint()


async def scan_finance_sources(fm, progress=None):
    """Scan only stored sale prices twice. Costs are fetched live, never imported."""
    async def scan():
        rows, total, offset = {}, None, 1
        while True:
            page = await fm.finance_page(PRICE_LAYOUT, offset)
            if total is None: total = page['foundCount']
            if total != page['foundCount']: raise ValueError('扫描期间记录数量变化')
            for row in page['data']:
                rid = str(row['recordId'])
                if rid in rows: raise ValueError('扫描遇到重复记录')
                rows[rid] = {'recordId':rid, 'modId':str(row['modId']), 'fieldData':row['fieldData']}
            if progress: progress(PRICE_LAYOUT, len(rows), total)
            if len(rows) == total: return rows
            if not page['data'] or len(rows) > total: raise ValueError('扫描不完整')
            offset += len(page['data'])
    prices = await scan()
    if dumps(await scan()) != dumps(prices):
        raise ValueError('扫描期间售价发生变化，请重新预览')
    return prices

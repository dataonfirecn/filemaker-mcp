"""Deterministic preflight for the verified ProductPrice / ProductPriceCustomer layouts."""
import hashlib
import json
from collections import Counter, defaultdict
from uuid import UUID

from .quotes import validate_quote
from .store import dumps


def quote_source_id(value):
    return str(UUID(str(value)))


async def scan_quotes(fm, layout):
    records, locators = [], set()
    total, offset = None, 1
    while True:
        page = await fm.find_records(layout, limit=200, offset=offset)
        if total is None:
            total = int(page['foundCount'])
        if int(page['foundCount']) != total:
            raise ValueError(f'{layout}: 扫描期间数量改变，请重试')
        for row in page['data']:
            if row['recordId'] in locators:
                raise ValueError(f'{layout}: 重复 recordId')
            locators.add(row['recordId'])
            records.append(row)
        offset += len(page['data'])
        if len(records) == total:
            return records
        if not page['data'] or len(records) > total:
            raise ValueError(f'{layout}: 扫描不完整')


def preflight(quotes, members, products, customers):
    """ProductPrice.product_id is SKU; member.code is customer code (not customer UUID)."""
    product_index, customer_index, links = defaultdict(list), defaultdict(list), defaultdict(list)
    for p in products:
        product_index[str(p['fields'].get('product_sku', ''))].append(str(p['id']))
    for c in customers:
        customer_index[str(c.get('code', ''))].append(c)
    issues, rows, seen = [], [], set()
    for member in members:
        try:
            key = quote_source_id(member['fieldData'].get('ProductPriceID'))
            links[key].append(member)
        except (ValueError, TypeError, AttributeError):
            issues.append({'memberRecordId': member['recordId'], 'error': '无效报价关联 ID'})
    ids = []
    for row in quotes:
        try:
            ids.append(quote_source_id(row['fieldData'].get('ID')))
        except (ValueError, TypeError, AttributeError):
            ids.append(None)
    counts = Counter(ids)
    for row, sid in zip(quotes, ids):
        f = row['fieldData']
        if sid:
            seen.add(sid)
        try:
            if not sid or counts[sid] != 1:
                raise ValueError('报价 ID 无效或重复')
            targets = product_index.get(str(f.get('product_id', '')), [])
            if len(targets) != 1:
                raise ValueError('产品 SKU 未找到或匹配多条产品')
            member_rows = links.get(sid, [])
            codes = [str(m['fieldData'].get('code') or '') for m in member_rows]
            if not codes or '' in codes or len(set(codes)) != len(codes):
                raise ValueError('客户群为空或包含重复／空客户代码')
            raw_customer = f.get('customer')
            if raw_customer not in (None, ''):
                try:
                    declared = json.loads(raw_customer)
                except (TypeError, ValueError) as exc:
                    raise ValueError('customer 字段不是有效 JSON 客户代码数组') from exc
                if (not isinstance(declared, list) or any(not isinstance(x, str) for x in declared)
                        or len(set(declared)) != len(declared) or set(declared) != set(codes)):
                    raise ValueError('报价 customer 列表与客户关联表不一致')
            resolved = []
            for code in codes:
                matches = customer_index.get(code, [])
                if len(matches) != 1:
                    raise ValueError(f'客户代码 {code} 未找到或不唯一')
                if matches[0].get('selectable') is False:
                    raise ValueError(f'客户代码 {code} 资料待完善，不能自动关联报价')
                resolved.append(matches[0]['value'])
            currency = str(f.get('currency') or '').strip().upper()
            currency = {'RMB': 'CNY', 'NTD': 'TWD'}.get(currency, currency)
            data = validate_quote({'title': f.get('title') or '', 'amount': str(f.get('price', '')),
                                   'currency': currency, 'enabled': True, 'customerIds': resolved})
            # status is an old update log, not a Web enabled/disabled flag.
            rows.append({'sourceId': sid, 'productId': targets[0], 'data': data,
                         'sourceData': {'layout': '@ProductPrice', 'recordId': row['recordId'],
                                        'modId': row.get('modId'), 'fields': f, 'members': member_rows}})
        except ValueError as exc:
            issues.append({'sourceId': sid, 'recordId': row['recordId'], 'sku': f.get('product_id'), 'error': str(exc)})
    for sid in links.keys() - seen:
        issues.append({'sourceId': sid, 'error': '客户关联指向不存在的报价',
                       'memberRecordIds': [m['recordId'] for m in links[sid]]})
    # Conflicting active prices for a customer must be reconciled before cutover.
    applicability = defaultdict(list)
    for row in rows:
        for customer in row['data']['customerIds']:
            applicability[(row['productId'], customer, row['data']['currency'])].append(row['sourceId'])
    for (pid, customer, currency), group in applicability.items():
        if len(group) > 1:
            issues.append({'productId': pid, 'customerId': customer, 'currency': currency,
                           'sourceIds': group, 'error': '同一产品客户币种存在多条报价，需核对'})
    return {'quoteCount': len(quotes), 'memberCount': len(members), 'validCount': len(rows),
            'issues': issues, 'rows': rows}


def manifest_digest(report, fingerprint, customers):
    return hashlib.sha256(dumps([fingerprint, report, customers]).encode()).hexdigest()

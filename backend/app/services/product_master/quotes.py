"""Independent customer-group quotes. Never enqueue product publications or FM jobs."""
import hashlib
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from .store import Conflict, dumps

DDL = '''
CREATE TABLE IF NOT EXISTS pm_quote (
 source text NOT NULL, id uuid NOT NULL, product_id uuid NOT NULL,
 version bigint NOT NULL, title text NOT NULL, amount numeric NOT NULL CHECK(amount >= 0),
 currency text NOT NULL CHECK(currency IN ('USD','CNY','TWD')), enabled boolean NOT NULL,
 source_id text, source_data jsonb NOT NULL DEFAULT '{}',
 updated_by jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source,id), UNIQUE(source,source_id),
 FOREIGN KEY(source,product_id) REFERENCES pm_product(source,id)
);
CREATE INDEX IF NOT EXISTS pm_quote_product ON pm_quote(source,product_id);
CREATE TABLE IF NOT EXISTS pm_quote_customer (
 source text NOT NULL, quote_id uuid NOT NULL, customer_id text NOT NULL,
 name text NOT NULL, code text NOT NULL, PRIMARY KEY(source,quote_id,customer_id),
 FOREIGN KEY(source,quote_id) REFERENCES pm_quote(source,id)
);
CREATE TABLE IF NOT EXISTS pm_quote_revision (
 source text NOT NULL, quote_id uuid NOT NULL, version bigint NOT NULL,
 request_id uuid NOT NULL, request_hash text NOT NULL, actor jsonb NOT NULL,
 before_data jsonb, after_data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source,quote_id,version), UNIQUE(source,request_id),
 FOREIGN KEY(source,quote_id) REFERENCES pm_quote(source,id)
);
'''


def amount_text(value):
    # JSON callers must use a decimal string: binary floats cannot preserve intent.
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValueError('请输入有效金额（十进制文本）')
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('金额格式错误') from exc
    if not amount.is_finite() or amount < 0 or amount.adjusted() > 19 or amount.as_tuple().exponent < -12:
        raise ValueError('金额必须是非负有限数字，最多 20 位整数、12 位小数')
    return format(amount, 'f')


def validate_quote(data):
    title = data.get('title', '').strip()
    if not title or len(title) > 200:
        raise ValueError('报价名称不能为空且不能超过 200 字')
    currency = data.get('currency')
    if currency not in ('USD', 'CNY', 'TWD'):
        raise ValueError('币种仅支持 USD、CNY、TWD')
    ids = data.get('customerIds', [])
    if not ids or len(ids) > 5000 or any(not isinstance(x, str) or not x.strip() for x in ids):
        raise ValueError('请选择有效客户')
    if len(set(ids)) != len(ids):
        raise ValueError('客户不能重复')
    if not isinstance(data.get('enabled'), bool):
        raise ValueError('启用状态无效')
    return dict(title=title, amount=amount_text(data.get('amount')), currency=currency,
                enabled=data['enabled'], customerIds=sorted(ids))


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


class QuoteStore:
    def __init__(self, product_store):
        self.pool, self.source = product_store.pool, product_store.source

    async def snapshot(self, c, row):
        if row is None:
            return None
        members = await c.fetch('''SELECT customer_id AS id,name,code FROM pm_quote_customer
            WHERE source=$1 AND quote_id=$2 ORDER BY customer_id''', self.source, row['id'])
        return {'id': str(row['id']), 'productId': str(row['product_id']), 'version': row['version'],
                'title': row['title'], 'amount': str(row['amount']), 'currency': row['currency'],
                'enabled': row['enabled'], 'sourceId': row['source_id'], 'sourceData': decode(row['source_data']),
                'customers': [dict(m) for m in members], 'updatedBy': decode(row['updated_by']),
                'updatedAt': row['updated_at'].isoformat()}

    async def list(self, product_id):
        async with self.pool.acquire() as c, c.transaction(isolation='repeatable_read', readonly=True):
            rows = await c.fetch('SELECT * FROM pm_quote WHERE source=$1 AND product_id=$2 ORDER BY title,id',
                                 self.source, UUID(str(product_id)))
            return [await self.snapshot(c, row) for row in rows]

    async def history(self, product_id, quote_id):
        rows = await self.pool.fetch('''SELECT r.* FROM pm_quote_revision r JOIN pm_quote q
            ON q.source=r.source AND q.id=r.quote_id
            WHERE r.source=$1 AND q.product_id=$2 AND q.id=$3 ORDER BY r.version DESC''',
            self.source, UUID(str(product_id)), UUID(str(quote_id)))
        if not rows:
            raise LookupError('报价不存在')
        return [{'version': r['version'], 'actor': decode(r['actor']), 'createdAt': r['created_at'].isoformat(),
                 'before': decode(r['before_data']), 'after': decode(r['after_data'])} for r in rows]

    async def save(self, *, product_id, quote_id, expected_version, request_id, data, actor,
                   directory, source_id=None, source_data=None):
        data = validate_quote(data)
        pid = UUID(str(product_id))
        qid = UUID(str(quote_id)) if quote_id else uuid4()
        rid = UUID(str(request_id))
        digest = hashlib.sha256(dumps([str(pid), str(quote_id), expected_version, data,
                                      actor.get('account'), source_id, source_data]).encode()).hexdigest()
        async with self.pool.acquire() as c, c.transaction():
            # Serialize retries even when the request tries another product/quote.
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', self.source+':quote:'+str(rid))
            previous = await c.fetchrow('SELECT * FROM pm_quote_revision WHERE source=$1 AND request_id=$2', self.source, rid)
            if previous:
                if previous['request_hash'] != digest:
                    raise ValueError('requestId 已用于不同报价请求')
                return decode(previous['after_data'])
            if not await c.fetchval('SELECT 1 FROM pm_product WHERE source=$1 AND id=$2', self.source, pid):
                raise LookupError('产品不存在')
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', self.source+':quote-product:'+str(pid))
            if source_id:
                await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', self.source+':quote-import:'+source_id)
                if await c.fetchval('SELECT 1 FROM pm_quote WHERE source=$1 AND source_id=$2', self.source, source_id):
                    raise ValueError('来源报价已导入，禁止覆盖')
            row = await c.fetchrow('SELECT * FROM pm_quote WHERE source=$1 AND id=$2 FOR UPDATE', self.source, qid)
            if quote_id and (not row or row['product_id'] != pid):
                raise LookupError('报价不存在')
            before = await self.snapshot(c, row)
            if expected_version != (row['version'] if row else 0):
                raise Conflict(before)
            # Retained members can still be removed/edited if the directory no longer lists them.
            known = {m['id']: m for m in (before or {}).get('customers', [])}
            directory_ids = set()
            for member in directory:
                key = member['value']
                if key in directory_ids:
                    raise ValueError('客户目录标识重复')
                directory_ids.add(key)
                known[key] = {'id': key, 'name': member.get('name', member.get('label', '')),
                              'code': member.get('code', '')}
            if any(key not in known for key in data['customerIds']):
                raise ValueError('客户目录中不存在所选客户，请刷新后重试')
            if data['enabled'] and await c.fetchval('''SELECT 1 FROM pm_quote q JOIN pm_quote_customer m
                ON q.source=m.source AND q.id=m.quote_id WHERE q.source=$1 AND q.product_id=$2
                AND q.id<>$3 AND q.enabled AND q.currency=$4 AND m.customer_id=ANY($5::text[]) LIMIT 1''',
                self.source, pid, qid, data['currency'], data['customerIds']):
                raise ValueError('所选客户在此产品和币种下已有启用报价，请先修改或停用原报价')
            version = expected_version + 1
            if row:
                await c.execute('''UPDATE pm_quote SET version=$3,title=$4,amount=$5,currency=$6,enabled=$7,
                    updated_by=$8::jsonb,updated_at=now() WHERE source=$1 AND id=$2''',
                    self.source, qid, version, data['title'], Decimal(data['amount']), data['currency'], data['enabled'], dumps(actor))
            else:
                await c.execute('''INSERT INTO pm_quote(source,id,product_id,version,title,amount,currency,enabled,
                    source_id,source_data,updated_by) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb)''',
                    self.source, qid, pid, version, data['title'], Decimal(data['amount']), data['currency'], data['enabled'],
                    source_id, dumps(source_data or {}), dumps(actor))
            await c.execute('DELETE FROM pm_quote_customer WHERE source=$1 AND quote_id=$2', self.source, qid)
            await c.executemany('INSERT INTO pm_quote_customer VALUES($1,$2,$3,$4,$5)',
                                [(self.source, qid, key, known[key]['name'], known[key]['code']) for key in data['customerIds']])
            after = await self.snapshot(c, await c.fetchrow('SELECT * FROM pm_quote WHERE source=$1 AND id=$2', self.source, qid))
            await c.execute('''INSERT INTO pm_quote_revision(source,quote_id,version,request_id,request_hash,actor,before_data,after_data)
                VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb)''', self.source, qid, version, rid, digest,
                dumps(actor), dumps(before) if before else None, dumps(after))
            return after

"""Read-only FileMaker customer snapshots; independent of product/quote writes."""
import hashlib
from collections import Counter
from .store import dumps
from .quotes import decode
from app.services.part_creation import _customer_id_from_odata_row

# All fields below were verified as normal, non-global fields in 客户资料_Edit.
FIELDS = ('客戶代號', '客戶公司簡稱', '公司', '客戶分類', '國家/地區', '地區',
          '業務負責人', '業務負責人2', '業務負責人3', '業務負責人4', 'currency',
          '聯絡人', '聯絡人郵件', '電話 1', '電話 2', '網站', '出貨地址', '辦公地址', '客戶備註')
DDL = '''
CREATE TABLE IF NOT EXISTS pm_customer (
 source text NOT NULL REFERENCES pm_source(source), id text NOT NULL,
 fields jsonb NOT NULL, issues jsonb NOT NULL, source_missing boolean NOT NULL DEFAULT false,
 version bigint NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,id)
);
CREATE TABLE IF NOT EXISTS pm_customer_sync (
 source text NOT NULL REFERENCES pm_source(source), digest text NOT NULL,
 before_data jsonb NOT NULL, after_data jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,digest)
);
'''


def digest(data):
    return hashlib.sha256(dumps(data).encode()).hexdigest()


async def scan(client):
    result, offset, expected = {}, 0, None
    while True:
        # FileMaker requires quoted identifiers for names such as 電話 1 and 國家/地區.
        selected = ['"' + name.replace('"', '""') + '"' for name in FIELDS]
        page = await client.records('客戶', select=selected, top=200, skip=offset, count=True)
        count = page.get('foundCount')
        if count is None or (expected is not None and int(count) != expected):
            raise ValueError('客户扫描数量不稳定，请重试')
        expected = int(count)
        batch = page.get('rows', [])
        for row in batch:
            identity = _customer_id_from_odata_row(row)
            if not identity or identity in result:
                raise ValueError('客户原生 ID 缺失或重复，停止同步')
            if any(field not in row for field in FIELDS):
                raise ValueError('客户来源字段缺失，停止同步')
            fields = {field: row[field] for field in FIELDS}
            if any(value is not None and not isinstance(value, str) for value in fields.values()):
                raise ValueError('客户来源字段类型改变，停止同步')
            result[identity] = fields
        offset += len(batch)
        if offset == expected and not page.get('nextLink'):
            break
        if not batch or offset >= expected or offset > 100000:
            raise ValueError('客户扫描不完整，停止同步')
    return result


async def verify_fields(client):
    metadata = await client.get_layout_metadata('客户资料_Edit')
    fields = {f['name']: f for f in metadata.get('fieldMetaData', [])}
    for name in FIELDS:
        f = fields.get(name, {})
        if f.get('type') != 'normal' or f.get('global') or f.get('result') != 'text':
            raise ValueError('客户字段定义改变，停止同步：' + name)


async def baseline(connection, source):
    raw = await connection.fetchval("SELECT payload FROM pm_reference WHERE source=$1 AND name='customers'", source)
    if raw is None:
        raise ValueError('Web 客户目录不存在')
    masters = {}
    if await connection.fetchval("SELECT to_regclass('public.pm_customer')"):
        for row in await connection.fetch('SELECT id,fields,issues,source_missing,version FROM pm_customer WHERE source=$1 ORDER BY id', source):
            masters[row['id']] = {'fields': decode(row['fields']), 'issues': decode(row['issues']),
                                  'sourceMissing': row['source_missing'], 'version': row['version']}
    return {'directory': decode(raw), 'masters': masters}


def plan(native, before, fingerprint, source):
    if not native:
        raise ValueError('来源客户目录为空，停止同步')
    identities = [row['value'] for row in before['directory']]
    if len(identities) != len(set(identities)):
        raise ValueError('Web 客户目录 ID 重复，停止同步')
    codes = Counter(str(f.get('客戶代號') or '').strip() for f in native.values())
    masters, directory, issues = {}, [], []
    for identity, fields in sorted(native.items()):
        code = str(fields.get('客戶代號') or '').strip()
        name = str(fields.get('客戶公司簡稱') or '').strip()
        problems = []
        if not name: problems.append('简称缺失')
        if not code: problems.append('代码缺失')
        elif codes[code] > 1: problems.append('代码重复')
        display = name or str(fields.get('公司') or '').strip() or code or identity
        item = {'value': identity, 'code': code, 'name': display, 'label': display,
                'selectable': not problems, 'issues': problems}
        if problems:
            item['label'] = display + '（待完善：' + '、'.join(problems) + '）'
            issues.append({'id': identity, 'code': code, 'issues': problems})
        directory.append(item)
        masters[identity] = {'fields': fields, 'issues': problems, 'sourceMissing': False}
    # Missing source records are retained for relationships and explicitly quarantined.
    for item in before['directory']:
        identity = item['value']
        if identity not in native:
            directory.append({**item, 'selectable': False, 'issues': ['来源记录缺失'],
                              'label': item['name'] + '（来源记录缺失）'})
            issues.append({'id': identity, 'code': item.get('code'), 'issues': ['来源记录缺失']})
    for identity, old in before['masters'].items():
        if identity not in native:
            masters[identity] = {'fields': old['fields'], 'issues': ['来源记录缺失'], 'sourceMissing': True}
    changes = []
    for identity, item in masters.items():
        old = before['masters'].get(identity)
        changed = old is None or any(old[k] != item[k] for k in item)
        item['version'] = (old['version'] if old else 0) + int(changed)
        if changed: changes.append(identity)
    after = {'masters': masters, 'directory': sorted(directory, key=lambda r: r['value'])}
    report = {'source': source, 'nativeCount': len(native), 'directoryCount': len(directory),
              'changedCount': len(changes), 'issues': issues,
              'selectableCount': sum(r.get('selectable', True) for r in directory),
              'before': before, 'after': after}
    report['digest'] = digest([fingerprint, source, before, after])
    return report


async def apply(pool, report):
    source = report['source']
    async with pool.acquire() as c, c.transaction():
        # Serialize with legacy pm_reference updates as well as other customer syncs.
        await c.fetchrow("SELECT payload FROM pm_reference WHERE source=$1 AND name='customers' FOR UPDATE", source)
        if await c.fetchval('SELECT 1 FROM pm_customer_sync WHERE source=$1 AND digest=$2', source, report['digest']):
            return 'alreadyApplied'
        if await baseline(c, source) != report['before']:
            raise ValueError('Web 客户目录在预览后改变，请重新预览')
        if report['after'] == report['before']:
            return 'unchanged'
        for identity, item in report['after']['masters'].items():
            if item == report['before']['masters'].get(identity):
                continue
            await c.execute('''INSERT INTO pm_customer(source,id,fields,issues,source_missing,version)
                VALUES($1,$2,$3::jsonb,$4::jsonb,$5,$6) ON CONFLICT(source,id) DO UPDATE
                SET fields=EXCLUDED.fields,issues=EXCLUDED.issues,source_missing=EXCLUDED.source_missing,
                    version=EXCLUDED.version,updated_at=now()''', source, identity, dumps(item['fields']),
                            dumps(item['issues']), item['sourceMissing'], item['version'])
        await c.execute("UPDATE pm_reference SET payload=$2::jsonb,updated_at=now() WHERE source=$1 AND name='customers'",
                        source, dumps(report['after']['directory']))
        await c.execute('INSERT INTO pm_customer_sync(source,digest,before_data,after_data) VALUES($1,$2,$3::jsonb,$4::jsonb)',
                        source, report['digest'], dumps(report['before']), dumps(report['after']))
    return 'applied'

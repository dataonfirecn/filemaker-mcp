"""PostgreSQL transactions couple snapshots, audit, publications and writeback jobs."""
import json
import hashlib
import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
import asyncpg
from .schema import SKUValidationError, validate_sku
from app.services.product_image_fields import canonical_assets

DDL = '''
CREATE TABLE IF NOT EXISTS pm_source (source text PRIMARY KEY, fingerprint text NOT NULL);
ALTER TABLE pm_source ADD COLUMN IF NOT EXISTS initial_import_complete boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS pm_scan (source text PRIMARY KEY, last_id uuid, due_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS pm_product (
 source text NOT NULL, id uuid NOT NULL, version bigint NOT NULL,
 fields jsonb NOT NULL, assets jsonb NOT NULL DEFAULT '[]',
 fm_record_id text, fm_mod_id text, fm_version bigint NOT NULL DEFAULT 0,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,id),
 UNIQUE(source,fm_record_id)
);
CREATE INDEX IF NOT EXISTS pm_product_sku ON pm_product(source,(fields->>'product_sku'));
CREATE TABLE IF NOT EXISTS pm_revision (
 source text NOT NULL, product_id uuid NOT NULL, version bigint NOT NULL,
 request_id uuid NOT NULL, request_hash text NOT NULL, actor jsonb NOT NULL,
 before_data jsonb NOT NULL, after_data jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source,product_id,version), UNIQUE(source,request_id),
 FOREIGN KEY(source,product_id) REFERENCES pm_product(source,id)
);
CREATE TABLE IF NOT EXISTS pm_upload (
 source text NOT NULL, id uuid NOT NULL, product_id uuid NOT NULL,
 request_id uuid NOT NULL, actor text NOT NULL, metadata jsonb NOT NULL,
 ready boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source,id), UNIQUE(source,request_id)
);
CREATE TABLE IF NOT EXISTS pm_asset_version (
 source text NOT NULL, id uuid NOT NULL, asset_id uuid NOT NULL, product_id uuid NOT NULL,
 object_key text NOT NULL, filename text NOT NULL, mime_type text NOT NULL,
 size bigint NOT NULL CHECK(size>=0), sha256 text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,id),
 UNIQUE(source,id,product_id), FOREIGN KEY(source,id) REFERENCES pm_upload(source,id)
);
CREATE INDEX IF NOT EXISTS pm_asset_history ON pm_asset_version(source,asset_id,created_at);
CREATE TABLE IF NOT EXISTS pm_product_asset (
 source text NOT NULL, product_id uuid NOT NULL, field text NOT NULL,
 repetition integer NOT NULL CHECK(repetition>0), asset_version_id uuid NOT NULL,
 sort_order integer NOT NULL, role text NOT NULL,
 PRIMARY KEY(source,product_id,field,repetition), UNIQUE(source,product_id,asset_version_id),
 FOREIGN KEY(source,product_id) REFERENCES pm_product(source,id),
 FOREIGN KEY(source,asset_version_id,product_id) REFERENCES pm_asset_version(source,id,product_id)
);
CREATE TABLE IF NOT EXISTS pm_reference (
 source text NOT NULL, name text NOT NULL, payload jsonb NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,name)
);
CREATE TABLE IF NOT EXISTS pm_job (
 source text NOT NULL, product_id uuid NOT NULL, version bigint NOT NULL,
 status text NOT NULL DEFAULT 'pending', steps jsonb NOT NULL DEFAULT '{}',
 attempts int NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 error text, PRIMARY KEY(source,product_id,version),
 FOREIGN KEY(source,product_id,version) REFERENCES pm_revision(source,product_id,version)
);
CREATE TABLE IF NOT EXISTS pm_publication (
 sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 source text NOT NULL, product_id uuid NOT NULL, version bigint NOT NULL,
 payload jsonb NOT NULL, UNIQUE(source,product_id,version)
);
CREATE TABLE IF NOT EXISTS pm_consumer (
 source text NOT NULL, consumer text NOT NULL, cursor bigint NOT NULL DEFAULT 0,
 updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source,consumer)
);
CREATE TABLE IF NOT EXISTS pm_drift (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, source text NOT NULL,
 product_id uuid NOT NULL, observed jsonb NOT NULL, resolved boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT now()
);
'''


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def source_fingerprint(settings):
    return hashlib.sha256((settings.filemaker_host.rstrip('/').lower()+'|'+settings.filemaker_database).encode()).hexdigest()


def request_digest(product_id, expected_version, changes, assets, actor, origin, command=None):
    payload = command if command is not None else [expected_version,changes,assets]
    return hashlib.sha256(dumps([str(product_id),actor.get('account',''),origin,payload]).encode()).hexdigest()


def unpack(row):
    if row is None:
        return None
    value = dict(row)
    for key in ('fields', 'assets', 'metadata', 'steps', 'payload', 'actor', 'before_data', 'after_data', 'observed'):
        if isinstance(value.get(key), str) and not (key == 'actor' and 'metadata' in value):
            value[key] = json.loads(value[key])
    return value


@asynccontextmanager
async def connection_for(store, connection=None):
    if connection is not None:
        yield connection
    else:
        async with store.pool.acquire() as acquired:
            yield acquired


class Conflict(ValueError):
    def __init__(self, current):
        self.current = current
        super().__init__('版本冲突，请比较当前记录后重新保存')


class ProductStore:
    def __init__(self, url, source, fingerprint=None):
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', source):
            raise ValueError('PRODUCT_MASTER_SOURCE must be a stable ASCII source identifier')
        self.url, self.source, self.pool = url, source, None
        self.fingerprint = fingerprint

    async def init(self, max_size=5):
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=max_size)
        async with self.pool.acquire() as c:
            await c.execute(DDL)
            from .quotes import DDL as QUOTE_DDL
            await c.execute(QUOTE_DDL)
            if self.fingerprint:
                await c.execute('INSERT INTO pm_source(source,fingerprint) VALUES($1,$2) ON CONFLICT DO NOTHING',self.source,self.fingerprint)
                saved=await c.fetchval('SELECT fingerprint FROM pm_source WHERE source=$1',self.source)
                if saved!=self.fingerprint:raise ValueError('Product source is already bound to another FileMaker database')

    async def close(self):
        await self.pool.close()

    async def get(self, ref, connection=None):
        c = connection or self.pool
        rows = await c.fetch('''SELECT * FROM pm_product WHERE source=$1
            AND (id::text=$2 OR fm_record_id=$2 OR fields->>'product_sku'=$2) LIMIT 2''', self.source, str(ref))
        if len(rows) > 1:
            raise ValueError('产品标识不唯一，请使用 UUID')
        return await self.hydrate(unpack(rows[0]), c) if rows else None

    async def list(self, query='', limit=50, offset=0):
        rows = await self.pool.fetch('''SELECT * FROM pm_product WHERE source=$1
          AND ($2='' OR strpos(lower(concat_ws(' ',fields->>'product_sku',fields->>'product_name',fields->>'產品名稱_中文',fields->>'系統產品編號')),lower($2))>0)
          ORDER BY id LIMIT $3 OFFSET $4''', self.source, query, limit, offset)
        return [await self.hydrate(unpack(r), self.pool) for r in rows]

    async def hydrate(self, product, connection):
        if product is None:
            return None
        rows = await connection.fetch("""SELECT v.id::text AS id,v.asset_id::text AS "assetId",
            v.object_key AS "objectKey",v.filename,v.mime_type AS "mimeType",v.size,v.sha256,
            a.field,a.repetition,a.sort_order AS "sortOrder",a.role
            FROM pm_product_asset a JOIN pm_asset_version v ON v.source=a.source AND v.id=a.asset_version_id
            WHERE a.source=$1 AND a.product_id=$2 ORDER BY a.sort_order""",self.source,UUID(str(product['id'])))
        # Legacy JSON is read only until that source is explicitly archived/replaced.
        if rows or not product.get('assets'):
            product['assets'] = [dict(row) for row in rows]
        return product

    async def bind_assets(self, connection, pid, assets):
        await connection.execute('DELETE FROM pm_product_asset WHERE source=$1 AND product_id=$2',self.source,pid)
        for a in assets:
            await connection.execute("""INSERT INTO pm_asset_version(source,id,asset_id,product_id,object_key,filename,mime_type,size,sha256)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) ON CONFLICT(source,id) DO NOTHING""",
                self.source,UUID(a['id']),UUID(a.get('assetId') or a['id']),pid,a['objectKey'],a['filename'],a['mimeType'],a['size'],a['sha256'])
            await connection.execute("""INSERT INTO pm_product_asset(source,product_id,field,repetition,asset_version_id,sort_order,role)
                VALUES($1,$2,$3,$4,$5,$6,$7)""",self.source,pid,a['field'],a['repetition'],UUID(a['id']),a['sortOrder'],a['role'])

    async def save(self, *, product_id, expected_version, request_id, changes, assets,
                   actor, schema, permissions, origin='web', imported=None, connection=None, command=None, sku_validator=None):
        pid, rid = UUID(str(product_id)), UUID(str(request_id))
        digest = request_digest(pid,expected_version,changes,assets,actor,origin,command)
        async with connection_for(self, connection) as c, c.transaction():
            # Serializes idempotency across products, including new UUID creation requests.
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', self.source + str(rid))
            old_request = await c.fetchrow('SELECT * FROM pm_revision WHERE source=$1 AND request_id=$2', self.source, rid)
            if old_request:
                if old_request['request_hash'] != digest:
                    raise ValueError('幂等标识已用于不同请求')
                return unpack(old_request)['after_data']
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', self.source + str(pid))
            old = unpack(await c.fetchrow('SELECT * FROM pm_product WHERE source=$1 AND id=$2 FOR UPDATE', self.source, pid))
            old = await self.hydrate(old, c)
            if (old['version'] if old else 0) != expected_version:
                raise Conflict(old)
            if not imported:
                schema.validate(changes, permissions)
                from .finance import validate_binding
                await validate_binding(c, self.source, pid, changes, old['fields'] if old else {})
            fields = {**(old['fields'] if old else {}), **changes, 'ID': str(pid)}
            if not imported:
                schema.validate_complete(fields)
            if 'product_sku' in schema.fields:
                sku = str(fields.get('product_sku') or '').strip()
                # Historical imports retain their original data, including conflicts.
                # All imports and writes share the same lock to prevent a race.
                if sku:
                    await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                                    'pm-sku:' + self.source + ':' + sku.lower())
                if not imported:
                    sku = validate_sku(fields.get('product_sku'))
                    duplicate = await c.fetchval("""SELECT 1 FROM pm_product WHERE source=$1 AND id<>$2
                        AND lower(regexp_replace(coalesce(fields->>'product_sku',''),
                        '^[[:space:]]+|[[:space:]]+$','','g'))=$3 LIMIT 1""", self.source, pid, sku.lower())
                    if duplicate:
                        raise SKUValidationError('SKU_DUPLICATE', 'SKU 已被其他产品使用，请修改后保存。')
                    if sku_validator and (not schema.document.get('nativeEditingLocked') or not await c.fetchval(
                        'SELECT initial_import_complete FROM pm_source WHERE source=$1', self.source)):
                        await sku_validator(sku, pid)
                    fields['product_sku'] = sku
            current_assets = old['assets'] if old else []
            result_assets = current_assets if assets is None else []
            if assets is not None:
                # Old revisions remain immutable; restored bindings use the current FM field.
                assets = canonical_assets(assets)
            if assets is not None and not imported:
                # Keep attachments invisible to this account; never delete them by omission.
                visible = {f['name'] for f in schema.visible(permissions)}
                assets = list(assets) + [a for a in current_assets if a['field'] not in visible]
                incoming = {(a['field'], a.get('repetition', 1)): a for a in assets}
                for previous in current_assets:
                    slot = (previous['field'], previous['repetition'])
                    if incoming.get(slot, {}).get('id') != previous['id']:
                        schema.slot(*slot, permissions)
            seen_slots, seen_ids = set(), set()
            for position, attachment in enumerate(assets or []):
                name, repetition = attachment['field'], attachment.get('repetition', 1)
                unchanged = any(a['id'] == attachment['id'] and a['field'] == name and a['repetition'] == repetition for a in current_assets)
                if not imported and not unchanged:
                    schema.slot(name, repetition, permissions)
                slot = (name, repetition)
                if slot in seen_slots or attachment['id'] in seen_ids:
                    raise ValueError('同一容器位置或附件不能重复绑定')
                seen_slots.add(slot); seen_ids.add(attachment['id'])
                upload = unpack(await c.fetchrow('SELECT * FROM pm_upload WHERE source=$1 AND id=$2 AND product_id=$3 AND ready', self.source, UUID(attachment['id']), pid))
                if not upload:
                    raise ValueError('附件尚未完成校验或不属于此产品')
                result_assets.append({**{k:v for k,v in upload['metadata'].items() if k not in {'stagingKey', 'pdaSession', 'pdaActor'}}, 'id': attachment['id'], 'field': name,
                                      'repetition': repetition, 'sortOrder': position, 'role': schema.fields[name].get('role','attachment')})
            version = expected_version + 1
            snapshot = {'id': str(pid), 'version': version, 'fields': fields, 'assets': result_assets, 'filemakerRecordId': (old or {}).get('fm_record_id') or (imported or {}).get('recordId')}
            await c.execute('''INSERT INTO pm_product(source,id,version,fields,assets,fm_record_id,fm_mod_id,fm_version)
                VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8)
                ON CONFLICT(source,id) DO UPDATE SET version=EXCLUDED.version,fields=EXCLUDED.fields,
                assets=EXCLUDED.assets,fm_version=CASE WHEN $9 THEN EXCLUDED.fm_version ELSE pm_product.fm_version END,updated_at=now()''', self.source, pid, version, dumps(fields), dumps([]),
                imported.get('recordId') if imported else None, imported.get('modId') if imported else None, version if imported else 0, bool(imported))
            await self.bind_assets(c, pid, result_assets)
            await c.execute('''INSERT INTO pm_revision(source,product_id,version,request_id,request_hash,actor,before_data,after_data)
              VALUES($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb)''', self.source, pid, version, rid, digest,
              dumps({**actor, 'origin': origin}), dumps({'fields': old['fields'], 'assets': current_assets, 'version': old['version']} if old else {}), dumps(snapshot))
            await c.execute('INSERT INTO pm_job(source,product_id,version,status) VALUES($1,$2,$3,$4)', self.source, pid, version, 'synced' if imported else 'pending')
            # Source lock ensures sequence order is also commit order (no skipped late commits).
            await c.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'pm-feed:' + self.source)
            await c.execute('INSERT INTO pm_publication(source,product_id,version,payload) VALUES($1,$2,$3,$4::jsonb)', self.source, pid, version, dumps(snapshot))
            return snapshot

    async def history(self, product_id):
        return [unpack(r) for r in await self.pool.fetch('SELECT * FROM pm_revision WHERE source=$1 AND product_id=$2 ORDER BY version DESC', self.source, UUID(str(product_id)))]

    async def jobs(self, product_id):
        return [unpack(r) for r in await self.pool.fetch('SELECT * FROM pm_job WHERE source=$1 AND product_id=$2 ORDER BY version DESC', self.source, UUID(str(product_id)))]

    async def feed(self, cursor, limit=100):
        return [unpack(r) for r in await self.pool.fetch('SELECT sequence,payload FROM pm_publication WHERE source=$1 AND sequence>$2 ORDER BY sequence LIMIT $3', self.source, cursor, limit)]

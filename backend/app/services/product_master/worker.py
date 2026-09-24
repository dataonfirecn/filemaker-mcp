"""Durable ordered jobs. Session locks protect each product across worker processes."""
import asyncio
import hashlib
import logging
from urllib.parse import urlparse, quote, urljoin
from uuid import UUID
import httpx
from .store import dumps, unpack
from app.services.product_image_fields import canonical_assets, canonical_container_field

logger = logging.getLogger(__name__)


class DriftError(RuntimeError):
    pass


async def download_container(client, url, max_bytes):
    host = urlparse(client.settings.filemaker_host)
    # FileMaker may redirect to the same secured container with a Redirect flag.
    # Validate every hop before sending the bearer token; cross-origin is rejected.
    async with httpx.AsyncClient(verify=client.settings.filemaker_ssl_verify, timeout=60) as session:
        for _ in range(4):
            target = urlparse(url)
            if target.scheme != 'https' or target.hostname != host.hostname or target.port != host.port or target.username or target.password:
                raise ValueError('Untrusted FileMaker container URL')
            async with session.stream('GET', url, headers={'Authorization': 'Bearer ' + await client.get_token()}, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get('location')
                    if not location:
                        raise ValueError('FileMaker container redirect has no target')
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > max_bytes:
                        raise ValueError('Container exceeds maximum size')
                return bytes(content), response.headers.get('content-type', 'application/octet-stream').split(';')[0]
        raise ValueError('Too many FileMaker container redirects')


def field_key(name, repetition):
    return name if repetition == 1 else f'{name}({repetition})'


def value_at(fields, name, repetition):
    value = fields.get(name, fields.get(f'{name}(1)', ''))
    if isinstance(value, list):
        return value[repetition - 1] if len(value) >= repetition else ''
    return fields.get(field_key(name, repetition), '') if repetition > 1 else value


def canonical(value, result):
    if value in ('',None): return ''
    from datetime import datetime
    from decimal import Decimal
    # 用定点写法：normalize() 会把 500 变成 5E+2 再发给 FileMaker。
    if result=='number': return format(Decimal(str(value)).normalize(),'f')
    formats={'date':['%Y-%m-%d','%m/%d/%Y'], 'timestamp':['%Y-%m-%dT%H:%M:%S','%Y-%m-%d %H:%M:%S','%m/%d/%Y %H:%M:%S'],'time':['%H:%M','%H:%M:%S']}
    if result in formats:
        for pattern in formats[result]:
            try: return datetime.strptime(str(value),pattern).strftime({'date':'%m/%d/%Y','timestamp':'%m/%d/%Y %H:%M:%S','time':'%H:%M:%S'}[result])
            except ValueError: pass
    return str(value)


def wire_fields(values, schema):
    result={}
    for name,value in values.items():
        field=schema.fields[name]
        if int(field.get('maxRepeat',1))>1:
            repeats=value if isinstance(value,list) else [value]
            for index in range(int(field['maxRepeat'])):
                result[f'{name}({index+1})']=canonical(repeats[index] if index<len(repeats) else '',field['result'])
        else: result[name]=canonical(value,field['result'])
    return result


def fields_match(remote, expected, schema):
    for name,value in expected.items():
        field=schema.fields[name];count=int(field.get('maxRepeat',1))
        repeats=value if isinstance(value,list) else [value]
        for i in range(count):
            if canonical(value_at(remote,name,i+1),field['result'])!=canonical(repeats[i] if i<len(repeats) else '',field['result']):return False
    return True


class ProductWorker:
    def __init__(self, store, schema, filemaker, storage, settings):
        self.store, self.schema, self.fm, self.storage, self.settings = store, schema, filemaker, storage, settings
        self.task = None
        self.stop_event = asyncio.Event()

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.stop_event.set()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self):
        while not self.stop_event.is_set():
            try:
                if self.settings.product_master_write_enabled:
                    await self.tick()
                await self.reconcile_batch()
            except Exception:
                logger.exception('Product writeback worker failed')
            try:
                await asyncio.wait_for(self.stop_event.wait(), 5)
            except asyncio.TimeoutError:
                pass

    async def tick(self):
        jobs = await self.store.pool.fetch('''SELECT j.* FROM pm_job j WHERE source=$1
          AND status IN ('pending','retry') AND next_attempt_at<=now()
          AND NOT EXISTS(SELECT 1 FROM pm_job earlier WHERE earlier.source=j.source
            AND earlier.product_id=j.product_id AND earlier.version<j.version AND earlier.status NOT IN ('synced','superseded'))
          ORDER BY next_attempt_at LIMIT 10''', self.store.source)
        for job in jobs:
            async with self.store.pool.acquire() as c:
                key = f'pm-worker:{self.store.source}:{job["product_id"]}'
                locked = await c.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key)
                if not locked:
                    continue
                try:
                    current = unpack(await c.fetchrow('SELECT * FROM pm_job WHERE source=$1 AND product_id=$2 AND version=$3', self.store.source, job['product_id'], job['version']))
                    if current['status'] not in ('pending', 'retry'):
                        continue
                    await self.sync(c, current)
                except Exception as exc:
                    status = 'conflict' if isinstance(exc, DriftError) else 'retry'
                    # Do not expose container URLs, credentials or upstream response bodies.
                    error = str(exc) if isinstance(exc, DriftError) else type(exc).__name__
                    await c.execute('''UPDATE pm_job SET status=$4,attempts=attempts+1,error=$5,
                        next_attempt_at=now()+least(900, power(2,least(attempts,8))*5)*interval '1 second'
                        WHERE source=$1 AND product_id=$2 AND version=$3''', self.store.source, job['product_id'], job['version'], status, error)
                finally:
                    await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))', key)

    async def sync(self, c, job):
        source, pid, version = self.store.source, job['product_id'], job['version']
        revision = unpack(await c.fetchrow('SELECT * FROM pm_revision WHERE source=$1 AND product_id=$2 AND version=$3', source, pid, version))
        desired = revision['after_data']
        desired['assets'] = canonical_assets(desired['assets'])
        revision['before_data']['assets'] = canonical_assets(revision['before_data'].get('assets', []))
        product = unpack(await c.fetchrow('SELECT * FROM pm_product WHERE source=$1 AND id=$2', source, pid))
        steps = job['steps']
        # Resume pre-rename jobs against the explicit main container, including checkpoints.
        for key in list(steps):
            if key.startswith('container:檔案 1 | 容器:'):
                steps[key.replace('檔案 1 | 容器', 'image_main')] = steps.pop(key)
        if steps.get('inFlight', {}).get('kind') == 'container':
            steps['inFlight']['field'] = canonical_container_field(steps['inFlight']['field'])
        layout = self.settings.product_master_layout
        result = await self.fm.find_records(layout, {'ID': f'=={pid}'}, limit=2)
        if len(result['data']) > 1:
            raise DriftError('FileMaker UUID 重复')
        writable = {k: v for k, v in desired['fields'].items() if self.schema.editable(k) and self.schema.fields[k]['result'] != 'container' and not self.schema.fields[k].get('externalSource')}
        if not result['data']:
            if product['fm_record_id']:
                raise DriftError('FileMaker 来源记录已消失，Web 数据保持不变')
            created = await self.fm.create_record(layout, {**wire_fields(writable,self.schema), 'ID': str(pid)})
            if created.get('recordId'):
                await c.execute('UPDATE pm_product SET fm_record_id=$3 WHERE source=$1 AND id=$2', source, pid, str(created['recordId']))
            result = await self.fm.find_records(layout, {'ID': f'=={pid}'}, limit=2)
            if len(result['data']) != 1:
                raise DriftError('新建记录 UUID 回读不一致，停止自动创建以防重复')
            steps['fields'] = True
        remote = result['data'][0]
        record_id = str(remote['recordId'])
        if str(remote['fieldData'].get('ID', '')).lower() != str(pid):
            raise DriftError('FileMaker 产品身份不一致')
        if product['fm_record_id'] and record_id != product['fm_record_id']:
            raise DriftError('FileMaker 记录定位发生变化')
        expected_mod = steps.get('modId', product['fm_mod_id'])
        if expected_mod and str(remote.get('modId')) != str(expected_mod):
            # Conservatively stop on ambiguous writes; explicit resolution is audited.
            recovered=False
            in_flight=steps.get('inFlight',{})
            if in_flight.get('kind')=='fields' and fields_match(remote['fieldData'],writable,self.schema):
                steps['fields']=True;recovered=True
            elif in_flight.get('kind')=='container':
                name,rep=in_flight['field'],in_flight['repetition']
                asset=next((a for a in desired['assets'] if a['field']==name and a['repetition']==rep),None)
                url=value_at(remote['fieldData'],name,rep)
                if asset and url:
                    content,_=await download_container(self.fm,url,self.settings.product_master_max_file_bytes)
                    recovered=hashlib.sha256(content).hexdigest()==asset['sha256']
                else:recovered=not asset and not url
                if recovered:steps[f'container:{name}:{rep}']=True
            if recovered:
                steps.pop('inFlight',None);steps['modId']=str(remote['modId'])
            if not recovered and not steps.get('force'):

                await c.execute('INSERT INTO pm_drift(source,product_id,observed) VALUES($1,$2,$3::jsonb)', source, pid, dumps({'recordId': record_id, 'modId': remote.get('modId'), 'expectedModId': expected_mod}))
                raise DriftError('FileMaker 版本发生变化，请核对后重新回写')
        async def checkpoint():
            await c.execute('UPDATE pm_job SET steps=$4::jsonb WHERE source=$1 AND product_id=$2 AND version=$3', source, pid, version, dumps(steps))
        steps['modId'] = str(remote['modId'])
        await checkpoint()
        # A price-only edit must not touch the product record or trigger its auto-enter fields.
        from .finance import PRICE_FIELDS
        before_fields = revision['before_data'].get('fields', {})
        price_only = any(desired['fields'].get(k) != before_fields.get(k) for k in PRICE_FIELDS) and all(
            before_fields.get(k) == v for k, v in writable.items())
        if price_only and fields_match(remote['fieldData'], writable, self.schema):
            steps['fields'] = True
        if not steps.get('fields'):
            # Imported legacy values can be readable but rejected on re-entry.
            # Compare after the modId guard, and retain full-snapshot readback below.
            changed = {name: value for name, value in writable.items()
                       if not fields_match(remote['fieldData'], {name: value}, self.schema)}
            if changed:
                steps['inFlight']={'kind':'fields'}
                await checkpoint()
                response = await self.fm.request(f'/layouts/{quote(layout,safe="")}/records/{record_id}', method='PATCH',
                    json_body={'fieldData': wire_fields(changed,self.schema), 'modId': str(remote['modId'])})
                steps['modId'] = response.get('response', {}).get('modId')
            steps['fields'] = True
            steps.pop('inFlight',None)
            await checkpoint()
        desired_slots = {(a['field'], a['repetition']): a for a in desired['assets']}
        old_slots = {(a['field'], a['repetition']): a for a in revision['before_data'].get('assets', [])}
        slots = set(desired_slots) | set(old_slots)
        if steps.get('force'):
            slots |= {(f['name'],i) for f in self.schema.fields.values() if f['result']=='container' and self.schema.editable(f['name']) for i in range(1,int(f.get('maxRepeat',1))+1)}
        for slot in sorted(slots):
            name, repetition = slot
            if not self.schema.fields.get(name, {}).get('managed', True):
                continue
            attachment = desired_slots.get(slot)
            step = f'container:{name}:{repetition}'
            if steps.get(step):
                continue
            if attachment and old_slots.get(slot, {}).get('sha256') == attachment['sha256'] and not steps.get('force'):
                continue
            steps['inFlight']={'kind':'container','field':name,'repetition':repetition}
            await checkpoint()
            if attachment:
                content = await asyncio.to_thread(self.storage.get_object_bytes, attachment['objectKey'], max_bytes=self.settings.product_master_max_file_bytes)
                if hashlib.sha256(content).hexdigest() != attachment['sha256']:
                    raise RuntimeError('Stored asset checksum mismatch')
                response = await self.fm.upload_container(layout, record_id, name, content, attachment['filename'], attachment['mimeType'], repetition=repetition, mod_id=steps['modId'])
                steps['modId'] = response.get('modId')
            else:
                response = await self.fm.request(f'/layouts/{quote(layout,safe="")}/records/{record_id}', method='PATCH', json_body={'fieldData': {field_key(name,repetition): ''}, 'modId':steps['modId']})
                steps['modId'] = response.get('response', {}).get('modId')
            # Confirm the bytes now in the container, not merely an HTTP success.
            check = (await self.fm.get_record(layout, record_id))[0]
            url = value_at(check['fieldData'], name, repetition)
            if attachment:
                actual, _ = await download_container(self.fm, url, self.settings.product_master_max_file_bytes)
                if hashlib.sha256(actual).hexdigest() != attachment['sha256']:
                    raise RuntimeError('FileMaker container verification failed')
            elif url:
                raise RuntimeError('FileMaker container clear verification failed')
            steps[step] = True
            steps.pop('inFlight',None)
            steps['modId'] = str(check['modId'])
            await checkpoint()
        checked = (await self.fm.get_record(layout, record_id))[0]
        if not fields_match(checked['fieldData'],writable,self.schema):
            raise DriftError('FileMaker 字段回读不一致')
        from .finance import sync_prices
        await sync_prices(self.fm, c, source, pid, revision['before_data'].get('fields', {}), desired['fields'], steps, checkpoint, product_record_id=record_id)
        async with c.transaction():
            await c.execute('UPDATE pm_product SET fm_record_id=$3,fm_mod_id=$4,fm_version=$5 WHERE source=$1 AND id=$2', source, pid, record_id, str(checked['modId']), version)
            await c.execute("UPDATE pm_job SET status='synced',error=NULL WHERE source=$1 AND product_id=$2 AND version=$3", source, pid, version)
        current = await self.store.get(pid, connection=c)
        if current['version'] == version:
            await self.refresh_derived(current, checked, publish_locator=not desired.get('filemakerRecordId'), connection=c)


    async def reconcile_batch(self):
        """Daily resumable scan: derived fields may flow back, managed fields never do."""
        source = self.store.source
        async with self.store.pool.acquire() as c:
            key = 'pm-scan:' + source
            if not await c.fetchval('SELECT pg_try_advisory_lock(hashtextextended($1,0))', key):
                return
            try:
                await c.execute('INSERT INTO pm_scan(source) VALUES($1) ON CONFLICT DO NOTHING', source)
                scan = await c.fetchrow('SELECT * FROM pm_scan WHERE source=$1 AND due_at<=now()', source)
                if not scan: return
                rows = await c.fetch('''SELECT * FROM pm_product p WHERE source=$1
                    AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT 10''', source, scan['last_id'])
                for row in rows:
                    product = unpack(row)
                    pid = product['id']
                    pending = await c.fetchval("SELECT EXISTS(SELECT 1 FROM pm_job WHERE source=$1 AND product_id=$2 AND status NOT IN ('synced','superseded'))", source, pid)
                    if not pending and product['fm_record_id']:
                        remote = await self.fm.find_records(self.settings.product_master_layout, {'ID':f'=={pid}'},limit=2)
                        records = remote['data']
                        if len(records)!=1 or str(records[0]['recordId'])!=product['fm_record_id'] or str(records[0]['modId'])!=product['fm_mod_id']:
                            observed = {'recordId': records[0]['recordId'] if len(records)==1 else None, 'modId': records[0].get('modId') if len(records)==1 else None, 'reason':'FileMaker source changed; Web retained'}
                            exists = await c.fetchval('SELECT EXISTS(SELECT 1 FROM pm_drift WHERE source=$1 AND product_id=$2 AND NOT resolved AND observed=$3::jsonb)',source,pid,dumps(observed))
                            if not exists: await c.execute('INSERT INTO pm_drift(source,product_id,observed) VALUES($1,$2,$3::jsonb)',source,pid,dumps(observed))
                        else:
                            await self.refresh_derived(product,records[0],connection=c)
                    await c.execute('UPDATE pm_scan SET last_id=$2 WHERE source=$1',source,pid)
                if len(rows)<10:
                    await c.execute("UPDATE pm_scan SET last_id=NULL,due_at=now()+interval '1 day' WHERE source=$1",source)
            finally:
                await c.execute('SELECT pg_advisory_unlock(hashtextextended($1,0))',key)

    async def refresh_derived(self, product, remote, *, publish_locator=False, connection=None):
        derived = {name: remote['fieldData'].get(name) for name,f in self.schema.fields.items()
                   if (not self.schema.editable(name) or name not in product['fields']) and name!='ID' and f['result']!='container'
                   and name in remote['fieldData'] and product['fields'].get(name)!=remote['fieldData'][name]}
        if not derived and not publish_locator: return
        from uuid import uuid4
        from .store import Conflict
        try:
            await self.store.save(product_id=product['id'],expected_version=product['version'],request_id=uuid4(),
                changes=derived,assets=None,actor={'account':'filemaker-derived-worker'},schema=self.schema,permissions={},origin='filemaker-derived',imported=remote,connection=connection)
        except Conflict:
            pass  # A newer Web edit wins; next scan refreshes calculated values.

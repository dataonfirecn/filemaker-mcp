"""Read-only FileMaker scope scanning shared by import and comparison scripts."""
from uuid import UUID


async def scan_layout(fm, layout, privilege=None, keep_data=False):
    """Enumerate a layout (optionally filtered by exact privilege) into (refs, issues).

    refs: [{'id': uuid, 'recordId': str, 'privilege': value(, 'data': fieldData)}] in scan
    order; 'data' is only present when keep_data=True (full enumeration already returns it).
    issues: {'invalidUuid': [...], 'duplicateUuid': {uuid: [recordId, ...]}, 'countChanges': [...]}
    Raises ValueError when the source count changes mid-scan or the scan is incomplete.
    """
    query = {'privilege': '==' + privilege} if privilege else None
    refs, seen = [], {}
    issues = {'invalidUuid': [], 'duplicateUuid': {}, 'countChanges': []}
    offset, total = 1, None
    while True:
        page = await fm.find_records(layout, query, limit=100, offset=offset)
        if total is None:
            total = page['foundCount']
        if total != page['foundCount']:
            issues['countChanges'].append({'offset': offset, 'expected': total, 'found': page['foundCount']})
            raise ValueError('Source count changed during scan')
        if not page['data']:
            break
        for row in page['data']:
            raw = row['fieldData'].get('ID')
            try:
                pid = str(UUID(raw))
            except (TypeError, ValueError):
                issues['invalidUuid'].append({'recordId': str(row['recordId']), 'id': raw})
                continue
            if pid in seen:
                issues['duplicateUuid'].setdefault(pid, []).append(str(row['recordId']))
                continue
            seen[pid] = str(row['recordId'])
            ref = {'id': pid, 'recordId': str(row['recordId']), 'privilege': row['fieldData'].get('privilege'),
                   'modId': str(row.get('modId'))}
            if keep_data:
                ref['data'] = row['fieldData']
            refs.append(ref)
        offset += len(page['data'])
        if offset - 1 >= total:
            break
    if offset - 1 < total:
        raise ValueError('Incomplete scope scan')
    return refs, issues


async def resolve_uuids(fm, layout, uuids):
    """Look up explicit UUIDs by ID; each must match exactly one record.

    Returns (refs, problems); problems entries carry NOT_FOUND_IN_SOURCE,
    MULTIPLE_MATCHES or IDENTITY_MISMATCH so callers can fail loudly.
    """
    refs, problems = [], []
    for pid in uuids:
        page = await fm.find_records(layout, {'ID': '==' + pid}, limit=2)
        rows = page['data']
        if not rows:
            problems.append({'id': pid, 'error': 'NOT_FOUND_IN_SOURCE'})
            continue
        if len(rows) > 1:
            problems.append({'id': pid, 'error': 'MULTIPLE_MATCHES', 'recordIds': [str(r['recordId']) for r in rows]})
            continue
        row = rows[0]
        try:
            matched = str(UUID(row['fieldData']['ID']))
        except (TypeError, ValueError):
            matched = None
        if matched != pid:
            problems.append({'id': pid, 'error': 'IDENTITY_MISMATCH', 'recordId': str(row['recordId'])})
            continue
        refs.append({'id': pid, 'recordId': str(row['recordId']), 'privilege': row['fieldData'].get('privilege'),
                     'modId': str(row.get('modId')), 'data': row['fieldData']})
    return refs, problems

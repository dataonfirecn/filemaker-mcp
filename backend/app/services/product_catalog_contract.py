"""Explicit customer catalog contract. Never publish arbitrary product fields."""
CATALOG_FIELDS = frozenset({
    'ID', 'privilege', 'product_sku', 'product_name', '產品名稱_中文',
    '系統產品編號', 'created_at', 'updated_at', '車款', '車子比例', '類別',
    'stock', 'BOM計數', '產品庫存::出庫數量總合', '下單數量', '審核',
})
IMAGE_FIELDS = frozenset({'image_main', '檔案 1 | 容器'} | {f'檔案 {i} | 容器' for i in range(2, 21)})


def catalog_snapshot(snapshot):
    permissions = snapshot.get('fieldPermissions', {})
    fields = {k: v for k, v in snapshot.get('fields', {}).items()
              if k in CATALOG_FIELDS and permissions.get(k) != 'canViewPrice'}
    assets = [dict(a) for a in snapshot.get('assets', [])
              if a.get('field') in IMAGE_FIELDS
              and a.get('mimeType', '').startswith('image/')
              and permissions.get(a.get('field')) != 'canViewPrice']
    for asset in assets:
        if asset['field'] == '檔案 1 | 容器':
            asset['field'] = 'image_main'
        asset['role'] = 'product_image'
        asset.pop('stagingKey', None)
    assets.sort(key=lambda a: (a['field'] != 'image_main', a.get('sortOrder', 0), a['id']))
    return {**snapshot, 'fields': fields, 'assets': assets,
            'sortValues': {k: v for k, v in snapshot.get('sortValues', {}).items() if k in fields},
            'fieldPermissions': {k: 'canViewProducts' for k in fields | {a['field']: None for a in assets}}}

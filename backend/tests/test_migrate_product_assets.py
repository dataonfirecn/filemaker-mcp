import pytest

from scripts.migrate_product_assets import AssetSpec, _copy_asset


class FakeFileMaker:
    def __init__(self):
        self.updated = []

    async def update_record(self, layout, record_id, data):
        self.updated.append((layout, record_id, data))
        return {"recordId": record_id}


@pytest.mark.asyncio
async def test_existing_packaging_asset_metadata_is_corrected_without_copy():
    client = FakeFileMaker()
    existing = {
        "recordId": "asset-11",
        "fieldData": {
            "asset_type": "product_image",
            "visibility": "customer",
            "legacy_source_field": "檔案 11 | 容器",
            "sort_order": 11,
            "is_primary": 0,
            "migration_status": "copied",
            "asset_file": "https://filemaker.example/asset-11.jpg",
        },
    }

    outcome, updated = await _copy_asset(
        client,
        None,
        source_record={
            "recordId": "product-1",
            "modId": "2",
            "fieldData": {"product_sku": "SKU-1"},
        },
        spec=AssetSpec(
            source_field="檔案 11 | 容器",
            asset_type="packaging_reference",
            sort_order=1,
            is_primary=0,
            visibility="internal",
        ),
        url="https://filemaker.example/source-11.jpg",
        existing=existing,
        max_file_bytes=1024,
    )

    assert outcome == "metadata_updated"
    assert updated["fieldData"]["asset_type"] == "packaging_reference"
    assert client.updated == [
        (
            "ProductAssets",
            "asset-11",
            {
                "asset_type": "packaging_reference",
                "visibility": "internal",
                "legacy_source_field": "檔案 11 | 容器",
                "sort_order": 1,
                "is_primary": 0,
                "updated_by": "codex_product_asset_migration",
            },
        )
    ]


def test_main_rename_keeps_legacy_migration_identity():
    from scripts.migrate_product_assets import _migration_key, PRODUCT_IMAGE_SPECS
    assert PRODUCT_IMAGE_SPECS[0].source_field == 'image_main'
    assert _migration_key('100','image_main') == _migration_key('100','檔案 1 | 容器')

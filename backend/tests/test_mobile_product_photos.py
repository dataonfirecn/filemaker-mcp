from datetime import datetime, timezone

import pytest

from app.api.mobile_products import (
    _is_product_photo_asset,
    _product_has_photos,
    _sync_product_photo,
)
from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.product_photo_upload_store import ProductPhotoUploadRecord


class FakeFileMaker:
    def __init__(self, *, assets=None):
        self.assets = assets or []
        self.created = []
        self.updated = []
        self.uploaded = []

    async def find_records(self, layout, **kwargs):
        if layout == "@products":
            return {
                "data": [
                    {
                        "recordId": "100",
                        "modId": "7",
                        "fieldData": {
                            "product_sku": "PI0019694",
                            "系統產品編號": "SYS-100",
                            "id_client": "CLIENT-1",
                        },
                    }
                ]
            }
        if layout == "ProductAssets":
            query = kwargs.get("query", {})
            if "migration_key" in query:
                return {"data": []}
            return {"data": self.assets}
        raise AssertionError(f"Unexpected layout {layout}")

    async def create_record(self, layout, field_data):
        self.created.append((layout, field_data))
        return {"recordId": "asset-200"}

    async def update_record(self, layout, record_id, field_data):
        self.updated.append((layout, record_id, field_data))
        return {"recordId": record_id}

    async def upload_container(
        self,
        layout,
        record_id,
        field_name,
        content,
        filename,
        content_type,
    ):
        self.uploaded.append(
            (layout, record_id, field_name, content, filename, content_type)
        )
        return {}


class FakeStorage:
    def get_object_bytes(self, object_key, *, max_bytes=None):
        assert object_key == "products/pimg-1.jpg"
        assert max_bytes
        return b"jpeg-bytes"


class FakeUploadStore:
    def __init__(self):
        self.statuses = []

    async def mark_synced(self, upload_id, *, asset_record_id):
        self.statuses.append(("SYNCED", upload_id, asset_record_id))

    async def mark_failed(self, upload_id, *, error):
        self.statuses.append(("FAILED", upload_id, error))


class FakeAuditLog:
    def __init__(self):
        self.entries = []

    async def record(self, **kwargs):
        self.entries.append(kwargs)


def _upload_record():
    return ProductPhotoUploadRecord(
        upload_id="pimg_11111111222243338444555555555555",
        session_id="session-a",
        product_sku="PI0019694",
        product_record_id="100",
        source_mod_id="7",
        slot=1,
        object_key="products/pimg-1.jpg",
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        file_size=10,
        sha256="sha",
        source="camera",
        operator_account="pda",
        status="UPLOADED",
        etag="etag",
        asset_record_id=None,
        last_error=None,
        created_at=datetime.now(timezone.utc),
        uploaded_at=datetime.now(timezone.utc),
        synced_at=None,
    )


@pytest.mark.asyncio
async def test_sync_product_photo_writes_asset_and_legacy_product_container():
    filemaker = FakeFileMaker()
    upload_store = FakeUploadStore()
    audit_log = FakeAuditLog()

    await _sync_product_photo(
        record=_upload_record(),
        operator=OperatorContext(
            session_id="session-1",
            account="pda",
            name="PDA 测试用户",
            permissions={"canViewOrders": True},
        ),
        settings=Settings(),
        storage=FakeStorage(),
        filemaker=filemaker,
        upload_store=upload_store,
        audit_log=audit_log,
    )

    assert filemaker.created[0][0] == "ProductAssets"
    asset_fields = filemaker.created[0][1]
    assert "id_asset" not in asset_fields
    assert asset_fields["asset_type"] == "product_image"
    assert asset_fields["legacy_source_field"] == "檔案 1 | 容器"
    assert asset_fields["is_primary"] == 1
    assert [
        (layout, record_id, field_name)
        for layout, record_id, field_name, *_rest in filemaker.uploaded
    ] == [
        ("ProductAssets", "asset-200", "asset_file"),
        ("@products", "100", "檔案 1 | 容器"),
    ]
    assert upload_store.statuses[-1] == (
        "SYNCED",
        "pimg_11111111222243338444555555555555",
        "asset-200",
    )
    assert audit_log.entries[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_product_has_photos_ignores_packaging_reference_asset():
    product = {
        "recordId": "100",
        "fieldData": {"product_sku": "PI0019694"},
    }
    filemaker = FakeFileMaker(
        assets=[
            {
                "recordId": "asset-1",
                "fieldData": {
                    "asset_type": "product_image",
                    "legacy_source_field": "檔案 11 | 容器",
                    "migration_status": "copied",
                },
            }
        ]
    )

    assert await _product_has_photos(filemaker, product) is False


@pytest.mark.asyncio
async def test_product_has_photos_ignores_pending_upload_asset():
    product = {
        "recordId": "100",
        "fieldData": {"product_sku": "PI0019694"},
    }
    filemaker = FakeFileMaker(
        assets=[
            {
                "recordId": "asset-pending",
                "fieldData": {
                    "asset_type": "product_image",
                    "legacy_source_field": "檔案 1 | 容器",
                    "migration_status": "pending_upload",
                },
            }
        ]
    )

    assert await _product_has_photos(filemaker, product) is False


def test_product_photo_asset_recognizes_only_legacy_slots_one_to_ten():
    assert _is_product_photo_asset(
        {
            "asset_type": "product_image",
            "legacy_source_field": "檔案 6 | 容器",
        }
    )
    assert not _is_product_photo_asset(
        {
            "asset_type": "product_image",
            "legacy_source_field": "檔案 11 | 容器",
        }
    )

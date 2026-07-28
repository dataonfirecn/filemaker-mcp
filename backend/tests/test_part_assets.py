from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings
from app.services.cos_storage import COSStorageService
from app.services.part_asset_upload_store import (
    PartAssetUploadRecord,
    PartAssetUploadStore,
)
from app.services.part_assets import (
    PartAssetError,
    bind_part_asset_upload,
    find_primary_part_asset,
    require_bindable_part_asset_upload,
)
from scripts.migrate_part_assets import (
    ASSET_SPECS,
    EXCLUDED_BARCODE_FIELDS,
    _download,
    _failure_reason,
)


def _upload_record(*, status: str = "UPLOADED") -> PartAssetUploadRecord:
    now = datetime.now(timezone.utc)
    return PartAssetUploadRecord(
        upload_id="asset_12345678",
        draft_id="part_draft_123",
        object_key="starrc/parts/original/2026/07/draft/asset.jpg",
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        file_size=4,
        sha256="a" * 64,
        asset_type="part_image",
        asset_role="primary",
        visibility="customer",
        source="file_picker",
        operator_account="amy",
        status=status,
        etag="etag",
        part_id=None,
        part_number=None,
        part_record_id=None,
        asset_record_id=None,
        created_at=now,
        uploaded_at=now,
        bound_at=None,
    )


class FakeFileMaker:
    def __init__(self):
        self.created = []
        self.find_calls = []

    async def create_record(self, layout, data):
        self.created.append((layout, data))
        return {"recordId": "91", "modId": "0"}

    async def find_records(self, layout, query=None, limit=100, sort=None):
        self.find_calls.append((layout, query, limit, sort))
        if query.get("asset_type") == "==drawing_2d":
            return {
                "data": [
                    {
                        "recordId": "92",
                        "fieldData": {
                            "object_key": "starrc/parts/drawing.jpg",
                            "visibility": "customer",
                        },
                    }
                ]
            }
        return {"data": []}


@pytest.mark.asyncio
async def test_bind_uploaded_asset_creates_partassets_record_once() -> None:
    store = PartAssetUploadStore("memory://part-assets")
    await store.create(_upload_record())
    filemaker = FakeFileMaker()
    settings = Settings(
        filemaker_part_assets_enabled=True,
        filemaker_part_asset_layout="PartAssets",
        cos_bucket="bucket-123",
        cos_region="ap-guangzhou",
    )

    bound = await bind_part_asset_upload(
        filemaker=filemaker,
        settings=settings,
        store=store,
        upload_id="asset_12345678",
        operator_account="amy",
        part_id="part-1",
        part_number="P-001",
        part_record_id="7",
    )
    repeated = await bind_part_asset_upload(
        filemaker=filemaker,
        settings=settings,
        store=store,
        upload_id="asset_12345678",
        operator_account="amy",
        part_id="part-1",
        part_number="P-001",
        part_record_id="7",
    )

    assert bound.status == "BOUND"
    assert repeated.status == "BOUND"
    assert len(filemaker.created) == 1
    layout, payload = filemaker.created[0]
    assert layout == "PartAssets"
    assert payload["part_id_fk"] == "part-1"
    assert payload["object_key"].startswith("starrc/parts/")
    assert payload["status"] == "READY"
    assert payload["visibility"] == "customer"
    assert payload["source_kind"] == "user"


@pytest.mark.asyncio
async def test_bind_recovers_existing_filemaker_asset_without_duplicate() -> None:
    class ExistingFileMaker(FakeFileMaker):
        async def find_records(self, layout, query=None, limit=100, sort=None):
            if query.get("id_asset") == "==asset_12345678":
                return {
                    "data": [
                        {
                            "recordId": "91",
                            "fieldData": {
                                "part_id_fk": "part-1",
                                "object_key": (
                                    "starrc/parts/original/2026/07/draft/asset.jpg"
                                ),
                            },
                        }
                    ]
                }
            return await super().find_records(layout, query, limit, sort)

    store = PartAssetUploadStore("memory://part-assets-existing")
    await store.create(_upload_record())
    filemaker = ExistingFileMaker()
    settings = Settings(filemaker_part_assets_enabled=True)

    bound = await bind_part_asset_upload(
        filemaker=filemaker,
        settings=settings,
        store=store,
        upload_id="asset_12345678",
        operator_account="amy",
        part_id="part-1",
        part_number="P-001",
        part_record_id="7",
    )

    assert bound.status == "BOUND"
    assert bound.asset_record_id == "91"
    assert filemaker.created == []


@pytest.mark.asyncio
async def test_preflight_rejects_upload_before_part_creation() -> None:
    store = PartAssetUploadStore("memory://part-assets-pending")
    await store.create(_upload_record(status="PENDING"))
    settings = Settings(filemaker_part_assets_enabled=True)

    with pytest.raises(PartAssetError) as caught:
        await require_bindable_part_asset_upload(
            settings=settings,
            store=store,
            upload_id="asset_12345678",
            operator_account="amy",
        )

    assert getattr(caught.value, "code", "") == "PART_ASSET_NOT_UPLOADED"


@pytest.mark.asyncio
async def test_primary_asset_falls_back_from_photo_to_customer_drawing() -> None:
    filemaker = FakeFileMaker()
    settings = Settings(filemaker_part_assets_enabled=True)

    result = await find_primary_part_asset(
        filemaker,
        settings,
        part_id="part-1",
        customer_visible_only=True,
    )

    assert result["recordId"] == "92"
    assert filemaker.find_calls[0][1]["asset_type"] == "==part_image"
    assert filemaker.find_calls[1][1]["asset_type"] == "==drawing_2d"
    assert filemaker.find_calls[1][1]["visibility"] == "==customer"


def test_part_asset_object_key_is_safe() -> None:
    settings = Settings()
    storage = COSStorageService(settings)

    key = storage.create_part_asset_object_key(
        draft_id="../../part 中文",
        upload_id="asset_123",
        mime_type="image/webp",
        original_filename="unsafe.exe",
        now=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert key == "starrc/parts/original/2026/07/part/asset_123.webp"
    assert (
        storage.create_migrated_part_asset_object_key(
            part_id="../../part 中文",
            asset_id="legacy_123",
            mime_type="application/octet-stream",
            original_filename="drawing.dwg",
        )
        == "starrc/parts/original/migration/part/legacy_123.dwg"
    )


def test_migration_excludes_barcode_and_generated_label_containers() -> None:
    selected = {spec.source_field for spec in ASSET_SPECS}

    assert EXCLUDED_BARCODE_FIELDS == {
        "qrcode_image",
        "barcode_image",
        "發料收料標籤貼紙",
        "零件標籤貼紙",
    }
    assert not (selected & EXCLUDED_BARCODE_FIELDS)
    assert len(selected) == 26


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        ("Container download failed: HTTP 401", "source_http_401"),
        ("Container download failed: HTTP 404", "source_http_404"),
        (
            "Container URL does not belong to the FileMaker host",
            "external_container_host",
        ),
        ("Container is 104857601 bytes, over 104857600", "over_size_limit"),
        ("Container exceeds 104857600 bytes", "over_size_limit"),
        ("COS object size verification failed", "other"),
    ],
)
def test_migration_classifies_failure_reasons(
    error: str,
    expected: str,
) -> None:
    assert _failure_reason(error) == expected


@pytest.mark.asyncio
async def test_migration_rejects_advertised_oversized_container_before_read() -> None:
    class DownloadFileMaker:
        settings = SimpleNamespace(filemaker_host="https://filemaker.example.test")

        async def get_token(self):
            return "token"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "Content-Length": "101",
                "Content-Type": "image/jpeg",
            },
            content=b"",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transfer:
        with pytest.raises(RuntimeError, match="101 bytes"):
            await _download(
                DownloadFileMaker(),
                transfer,
                "https://filemaker.example.test/container/photo.jpg",
                max_file_bytes=100,
            )

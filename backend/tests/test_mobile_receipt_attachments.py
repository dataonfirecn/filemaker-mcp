from datetime import datetime, timezone

import pytest

from app.api.mobile_receipts import (
    complete_attachment_upload,
    create_attachment_presign,
)
from app.core.config import Settings
from app.models.mobile_receipts import (
    AttachmentCompleteRequest,
    AttachmentPresignRequest,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import (
    COSObjectMetadata,
    COSPresignedUpload,
    COSStorageService,
)
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)


def test_cos_object_key_is_scoped_and_does_not_use_original_filename() -> None:
    storage = COSStorageService(
        Settings(
            cos_enabled=True,
            cos_secret_id="test-id",
            cos_secret_key="test-key",
            cos_bucket="starrc-1252872963",
            cos_region="ap-guangzhou",
        )
    )

    key = storage.create_object_key(
        draft_id="draft/../../unsafe",
        shipment_id="PI 0019171/../../unsafe",
        attachment_id="att_123",
        mime_type="image/jpeg",
        now=datetime(2026, 7, 25, tzinfo=timezone.utc),
    )

    assert key == (
        "starrc/receipts/2026/07/"
        "PI-0019171-----unsafe/draft-----unsafe/att_123.jpg"
    )
    assert ".." not in key.split("/")


def test_cos_configuration_requires_private_credentials() -> None:
    settings = Settings(
        cos_enabled=True,
        cos_bucket="starrc-1252872963",
        cos_region="ap-guangzhou",
    )

    assert not settings.cos_configured


@pytest.mark.asyncio
async def test_receipt_attachment_store_enforces_per_draft_count() -> None:
    store = ReceiptAttachmentStore("memory://attachments")
    await store.init()
    record = ReceiptAttachmentRecord(
        attachment_id="att_123",
        draft_id="draft-1",
        shipment_id="shipment-1",
        pi_number="PI0019171",
        line_id=None,
        object_key="starrc/receipts/2026/07/shipment-1/draft-1/att_123.jpg",
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        file_size=128,
        sha256="a" * 64,
        source="camera",
        operator_account="warehouse",
        status="PENDING",
        etag=None,
        created_at=datetime.now(timezone.utc),
        uploaded_at=None,
    )

    await store.create(record)

    assert await store.count_active("draft-1", "warehouse") == 1
    assert await store.count_active("draft-1", "someone-else") == 0
    assert await store.get("att_123") == record

    uploaded = await store.mark_uploaded("att_123", etag="etag-123")
    assert uploaded is not None
    assert uploaded.status == "UPLOADED"
    assert uploaded.etag == "etag-123"


class FakeCOSStorage:
    configured = True

    def create_object_key(
        self,
        *,
        draft_id: str,
        shipment_id: str,
        attachment_id: str,
        mime_type: str,
    ) -> str:
        return f"starrc/receipts/2026/07/{shipment_id}/{draft_id}/{attachment_id}.jpg"

    def create_presigned_upload(
        self,
        *,
        object_key: str,
        content_type: str,
    ) -> COSPresignedUpload:
        return COSPresignedUpload(
            object_key=object_key,
            upload_url=f"https://cos.example/{object_key}?signature=test",
            headers={"Content-Type": content_type},
            expires_at=datetime(2026, 7, 25, 12, 10, tzinfo=timezone.utc),
        )

    def head_object(self, object_key: str) -> COSObjectMetadata:
        return COSObjectMetadata(
            content_length=128,
            content_type="image/jpeg",
            etag="etag-123",
        )


@pytest.mark.asyncio
async def test_presign_and_complete_attachment_flow() -> None:
    settings = Settings(
        cos_enabled=True,
        cos_secret_id="test-id",
        cos_secret_key="test-key",
        cos_bucket="starrc-1252872963",
        cos_region="ap-guangzhou",
    )
    store = ReceiptAttachmentStore("memory://attachment-flow")
    await store.init()
    audit_log = AuditLogStore("memory://audit")
    await audit_log.init()
    operator = OperatorContext(
        session_id="session-1",
        account="warehouse",
        name="仓库",
        permissions={"canViewOrders": True},
    )
    body = AttachmentPresignRequest(
        shipmentId="shipment-1",
        piNumber="PI0019171",
        filename="photo.jpg",
        mimeType="image/jpeg",
        fileSize=128,
        sha256="a" * 64,
        source="camera",
    )

    presigned = await create_attachment_presign(
        body=body,
        draft_id="draft-1",
        operator=operator,
        settings=settings,
        storage=FakeCOSStorage(),
        attachment_store=store,
        audit_log=audit_log,
    )

    assert presigned.method == "PUT"
    assert presigned.headers == {"Content-Type": "image/jpeg"}
    pending = await store.get(presigned.attachment_id)
    assert pending is not None
    assert pending.status == "PENDING"

    completed = await complete_attachment_upload(
        body=AttachmentCompleteRequest(
            etag='"etag-123"',
            fileSize=128,
            sha256="a" * 64,
        ),
        draft_id="draft-1",
        attachment_id=presigned.attachment_id,
        operator=operator,
        settings=settings,
        storage=FakeCOSStorage(),
        attachment_store=store,
        audit_log=audit_log,
    )

    assert completed.status == "UPLOADED"
    assert completed.etag == "etag-123"

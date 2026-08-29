from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


AttachmentSource = Literal["camera", "photo_library"]
AttachmentStatus = Literal["PENDING", "UPLOADED", "BOUND", "FAILED", "ORPHAN"]
ReceiptSubmissionStatus = Literal["partial", "sealed"]
ReceiptRoutingMode = Literal["order_receipt", "supplemental_inbound", "split"]


class AttachmentPresignRequest(BaseModel):
    shipment_id: str = Field(alias="shipmentId", min_length=1, max_length=160)
    pi_number: str = Field(alias="piNumber", min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=100)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    source: AttachmentSource
    line_id: str | None = Field(default=None, alias="lineId", max_length=160)

    model_config = {"populate_by_name": True}

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return normalized

    @field_validator("mime_type")
    @classmethod
    def normalize_mime_type(cls, value: str) -> str:
        return value.strip().lower()


class AttachmentPresignResponse(BaseModel):
    attachment_id: str = Field(alias="attachmentId")
    object_key: str = Field(alias="objectKey")
    upload_url: str = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class AttachmentCompleteRequest(BaseModel):
    etag: str = Field(min_length=1, max_length=255)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)

    model_config = {"populate_by_name": True}

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return normalized


class AttachmentResponse(BaseModel):
    attachment_id: str = Field(alias="attachmentId")
    draft_id: str = Field(alias="draftId")
    shipment_id: str = Field(alias="shipmentId")
    pi_number: str = Field(alias="piNumber")
    line_id: str | None = Field(default=None, alias="lineId")
    object_key: str = Field(alias="objectKey")
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    sha256: str
    etag: str | None = None
    source: AttachmentSource
    status: AttachmentStatus
    created_at: datetime = Field(alias="createdAt")
    uploaded_at: datetime | None = Field(default=None, alias="uploadedAt")

    model_config = {"populate_by_name": True}


class AttachmentDownloadResponse(BaseModel):
    download_url: str = Field(alias="downloadUrl")
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class ReceiptSubmissionLine(BaseModel):
    line_id: str = Field(alias="lineId", min_length=1, max_length=160)
    record_id: str = Field(alias="recordId", min_length=1, max_length=80)
    sku: str = Field(min_length=1, max_length=160)
    received_quantity: int = Field(alias="receivedQuantity", gt=0)
    expected_quantity: int = Field(alias="expectedQuantity", ge=0)
    remark: str = Field(default="", max_length=2000)
    attachment_ids: list[str] = Field(
        default_factory=list,
        alias="attachmentIds",
        max_length=6,
    )

    model_config = {"populate_by_name": True}


class ReceiptSubmissionRequest(BaseModel):
    draft_id: str = Field(alias="draftId", min_length=1, max_length=160)
    shipment_id: str = Field(alias="shipmentId", min_length=1, max_length=160)
    document_number: str = Field(alias="documentNumber", max_length=160)
    pi_number: str = Field(alias="piNumber", max_length=160)
    receipt_remark: str = Field(default="", alias="receiptRemark", max_length=4000)
    shipment_attachment_ids: list[str] = Field(
        default_factory=list,
        alias="shipmentAttachmentIds",
        max_length=1,
    )
    lines: list[ReceiptSubmissionLine] = Field(min_length=1, max_length=500)
    audit_log: list[dict] = Field(default_factory=list, alias="auditLog", max_length=5000)
    submitted_at: datetime = Field(alias="submittedAt")

    model_config = {"populate_by_name": True}

    @field_validator("lines")
    @classmethod
    def validate_unique_lines(
        cls,
        value: list[ReceiptSubmissionLine],
    ) -> list[ReceiptSubmissionLine]:
        line_ids = [line.line_id for line in value]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("lines must not contain duplicate lineId values")
        return value


class ReceiptSubmissionLineResponse(BaseModel):
    line_id: str = Field(alias="lineId")
    receipt_id: str = Field(alias="receiptId")
    quantity: int
    status: str
    received_at: datetime = Field(alias="receivedAt")
    received_by: str = Field(alias="receivedBy")
    already_received: bool = Field(default=False, alias="alreadyReceived")
    trace_sync_status: str = Field(default="synced", alias="traceSyncStatus")
    trace_sync_error: str | None = Field(default=None, alias="traceSyncError")
    routing_mode: ReceiptRoutingMode = Field(
        default="order_receipt",
        alias="routingMode",
    )
    order_receipt_quantity: int = Field(default=0, alias="orderReceiptQuantity")
    supplemental_quantity: int = Field(default=0, alias="supplementalQuantity")
    inbound_order_id: str = Field(default="", alias="inboundOrderId")
    inbound_order_line_id: str = Field(default="", alias="inboundOrderLineId")

    model_config = {"populate_by_name": True}


class ReceiptSubmissionResponse(BaseModel):
    receipt_id: str = Field(alias="receiptId")
    status: ReceiptSubmissionStatus
    sealed_at: datetime = Field(alias="sealedAt")
    all_lines_received: bool = Field(alias="allLinesReceived")
    received_line_count: int = Field(alias="receivedLineCount")
    total_line_count: int = Field(alias="totalLineCount")
    lines: list[ReceiptSubmissionLineResponse]

    model_config = {"populate_by_name": True}


class ConfirmedReceiptSummary(BaseModel):
    receipt_document_id: str = Field(alias="receiptDocumentId")
    shipment_id: str = Field(alias="shipmentId")
    document_number: str = Field(alias="documentNumber")
    pi_number: str = Field(alias="piNumber")
    receipt_id: str = Field(alias="receiptId")
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    confirmed_at: datetime = Field(alias="confirmedAt")
    all_lines_received: bool = Field(alias="allLinesReceived")
    received_line_count: int = Field(alias="receivedLineCount")
    total_line_count: int = Field(alias="totalLineCount")
    submitted_line_count: int = Field(alias="submittedLineCount")
    total_quantity: int = Field(alias="totalQuantity")
    shipment_photo_count: int = Field(alias="shipmentPhotoCount")

    model_config = {"populate_by_name": True}


class ConfirmedReceiptLine(BaseModel):
    line_id: str = Field(alias="lineId")
    record_id: str = Field(alias="recordId")
    sku: str
    received_quantity: int = Field(alias="receivedQuantity")
    expected_quantity: int = Field(alias="expectedQuantity")
    remark: str = ""
    attachment_count: int = Field(alias="attachmentCount")
    receipt_id: str = Field(alias="receiptId")
    status: str
    received_at: datetime = Field(alias="receivedAt")
    received_by: str = Field(alias="receivedBy")
    routing_mode: ReceiptRoutingMode = Field(
        default="order_receipt",
        alias="routingMode",
    )
    order_receipt_quantity: int = Field(default=0, alias="orderReceiptQuantity")
    supplemental_quantity: int = Field(default=0, alias="supplementalQuantity")
    inbound_order_id: str = Field(default="", alias="inboundOrderId")
    inbound_order_line_id: str = Field(default="", alias="inboundOrderLineId")

    model_config = {"populate_by_name": True}


class ConfirmedReceiptDetail(ConfirmedReceiptSummary):
    receipt_remark: str = Field(alias="receiptRemark")
    lines: list[ConfirmedReceiptLine]


class ConfirmedReceiptListResponse(BaseModel):
    receipts: list[ConfirmedReceiptSummary]
    total: int
    limit: int
    offset: int

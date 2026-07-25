from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.mobile_receipts import (
    AttachmentCompleteRequest,
    AttachmentDownloadResponse,
    AttachmentPresignRequest,
    AttachmentPresignResponse,
    AttachmentResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import COSStorageError, COSStorageService, new_attachment_id
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_operator_context,
    get_receipt_attachment_store,
    get_settings,
)
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)


router = APIRouter(prefix="/mobile/v1/receipts", tags=["mobile-receipts"])
DraftID = Path(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")


@router.post(
    "/{draft_id}/attachments/presign",
    response_model=AttachmentPresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attachment_presign(
    body: AttachmentPresignRequest,
    draft_id: str = DraftID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> AttachmentPresignResponse:
    _require_cos(settings, storage)
    if body.mime_type not in settings.cos_allowed_content_type_set:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "message": "不支持此图片格式。",
                "allowedContentTypes": sorted(settings.cos_allowed_content_type_set),
            },
        )
    if body.file_size > settings.cos_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "message": "图片超过上传大小限制。",
                "maxBytes": settings.cos_max_upload_bytes,
            },
        )
    active_count = await attachment_store.count_active(draft_id, operator.account)
    if active_count >= settings.cos_max_attachments_per_receipt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "当前到货单照片数量已达到上限。",
                "maximum": settings.cos_max_attachments_per_receipt,
            },
        )

    attachment_id = new_attachment_id()
    object_key = storage.create_object_key(
        draft_id=draft_id,
        shipment_id=body.shipment_id,
        attachment_id=attachment_id,
        mime_type=body.mime_type,
    )
    try:
        presigned = await run_in_threadpool(
            storage.create_presigned_upload,
            object_key=object_key,
            content_type=body.mime_type,
        )
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc

    record = ReceiptAttachmentRecord(
        attachment_id=attachment_id,
        draft_id=draft_id,
        shipment_id=body.shipment_id,
        pi_number=body.pi_number,
        line_id=body.line_id,
        object_key=object_key,
        original_filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
        sha256=body.sha256,
        source=body.source,
        operator_account=operator.account,
        status="PENDING",
        etag=None,
        created_at=datetime.now(timezone.utc),
        uploaded_at=None,
    )
    await attachment_store.create(record)
    await audit_log.record(
        operator=operator,
        action_type="RECEIPT_ATTACHMENT_PRESIGN",
        status="success",
        order_id=body.pi_number,
        request_payload={
            "draftId": draft_id,
            "shipmentId": body.shipment_id,
            "lineId": body.line_id,
            "mimeType": body.mime_type,
            "fileSize": body.file_size,
            "source": body.source,
        },
        response_payload={
            "attachmentId": attachment_id,
            "objectKey": object_key,
            "expiresAt": presigned.expires_at.isoformat(),
        },
    )
    return AttachmentPresignResponse(
        attachmentId=attachment_id,
        objectKey=object_key,
        uploadUrl=presigned.upload_url,
        headers=presigned.headers,
        expiresAt=presigned.expires_at,
    )


@router.post(
    "/{draft_id}/attachments/{attachment_id}/complete",
    response_model=AttachmentResponse,
)
async def complete_attachment_upload(
    body: AttachmentCompleteRequest,
    draft_id: str = DraftID,
    attachment_id: str = Path(min_length=5, max_length=80),
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> AttachmentResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        attachment_store,
        draft_id=draft_id,
        attachment_id=attachment_id,
        operator_account=operator.account,
    )
    if record.status == "UPLOADED":
        return _response(record)
    if record.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": f"附件当前状态不能完成上传：{record.status}"},
        )
    if body.file_size != record.file_size or body.sha256 != record.sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "上传完成信息与申请上传时不一致。"},
        )

    try:
        metadata = await run_in_threadpool(storage.head_object, record.object_key)
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc)},
        ) from exc
    if metadata.content_length != record.file_size:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的文件大小与申请上传时不一致。"},
        )
    if metadata.content_type != record.mime_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的文件类型与申请上传时不一致。"},
        )
    request_etag = body.etag.strip().strip('"').lower()
    if request_etag and request_etag != metadata.etag.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 返回的 ETag 与客户端上传结果不一致。"},
        )

    updated = await attachment_store.mark_uploaded(
        attachment_id,
        etag=metadata.etag,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "附件记录不存在。"},
        )
    await audit_log.record(
        operator=operator,
        action_type="RECEIPT_ATTACHMENT_UPLOADED",
        status="success",
        order_id=record.pi_number,
        request_payload={
            "draftId": draft_id,
            "attachmentId": attachment_id,
            "fileSize": body.file_size,
        },
        response_payload={
            "objectKey": record.object_key,
            "etag": metadata.etag,
        },
    )
    return _response(updated)


@router.get(
    "/{draft_id}/attachments/{attachment_id}/download-url",
    response_model=AttachmentDownloadResponse,
)
async def get_attachment_download_url(
    draft_id: str = DraftID,
    attachment_id: str = Path(min_length=5, max_length=80),
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
) -> AttachmentDownloadResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        attachment_store,
        draft_id=draft_id,
        attachment_id=attachment_id,
        operator_account=operator.account,
    )
    if record.status not in {"UPLOADED", "BOUND"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "附件尚未上传完成。"},
        )
    try:
        url, expires_at = await run_in_threadpool(
            storage.create_presigned_download,
            record.object_key,
        )
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc
    return AttachmentDownloadResponse(downloadUrl=url, expiresAt=expires_at)


def _require_cos(settings: Settings, storage: COSStorageService) -> None:
    if not settings.cos_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 附件上传尚未启用。"},
        )
    if not storage.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 密钥或存储桶配置不完整。"},
        )


async def _owned_record(
    store: ReceiptAttachmentStore,
    *,
    draft_id: str,
    attachment_id: str,
    operator_account: str,
) -> ReceiptAttachmentRecord:
    record = await store.get(attachment_id)
    if (
        not record
        or record.draft_id != draft_id
        or record.operator_account != operator_account
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "附件记录不存在。"},
        )
    return record


def _response(record: ReceiptAttachmentRecord) -> AttachmentResponse:
    return AttachmentResponse(
        attachmentId=record.attachment_id,
        draftId=record.draft_id,
        shipmentId=record.shipment_id,
        piNumber=record.pi_number,
        lineId=record.line_id,
        objectKey=record.object_key,
        mimeType=record.mime_type,
        fileSize=record.file_size,
        sha256=record.sha256,
        etag=record.etag,
        source=record.source,
        status=record.status,
        createdAt=record.created_at,
        uploadedAt=record.uploaded_at,
    )

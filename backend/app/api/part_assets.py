from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.part_assets import (
    PartAssetBindRequest,
    PartAssetCompleteRequest,
    PartAssetPresignRequest,
    PartAssetPresignResponse,
    PartAssetResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_filemaker_client,
    get_operator_context,
    get_part_asset_upload_store,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.part_asset_upload_store import (
    PartAssetUploadRecord,
    PartAssetUploadStore,
)
from app.services.part_assets import (
    PartAssetError,
    bind_part_asset_upload,
)


router = APIRouter(prefix="/part-assets", tags=["part-assets"])
UploadID = Path(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")


@router.post(
    "/uploads/presign",
    response_model=PartAssetPresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_part_asset_presign(
    body: PartAssetPresignRequest,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    store: PartAssetUploadStore = Depends(get_part_asset_upload_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> PartAssetPresignResponse:
    _require_enabled(settings, storage)
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

    upload_id = f"asset_{uuid.uuid4().hex}"
    object_key = storage.create_part_asset_object_key(
        draft_id=body.draft_id,
        upload_id=upload_id,
        mime_type=body.mime_type,
        original_filename=body.filename,
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

    record = PartAssetUploadRecord(
        upload_id=upload_id,
        draft_id=body.draft_id,
        object_key=object_key,
        original_filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
        sha256=body.sha256,
        asset_type=body.asset_type,
        asset_role=body.asset_role,
        visibility=body.visibility,
        source=body.source,
        operator_account=operator.account,
        status="PENDING",
        etag=None,
        part_id=None,
        part_number=None,
        part_record_id=None,
        asset_record_id=None,
        created_at=datetime.now(timezone.utc),
        uploaded_at=None,
        bound_at=None,
    )
    await store.create(record)
    await audit_log.record(
        operator=operator,
        action_type="PART_ASSET_PRESIGN",
        status="success",
        request_payload={
            "draftId": body.draft_id,
            "mimeType": body.mime_type,
            "fileSize": body.file_size,
            "assetType": body.asset_type,
            "visibility": body.visibility,
        },
        response_payload={
            "uploadId": upload_id,
            "objectKey": object_key,
            "expiresAt": presigned.expires_at.isoformat(),
        },
    )
    return PartAssetPresignResponse(
        uploadId=upload_id,
        objectKey=object_key,
        uploadUrl=presigned.upload_url,
        headers=presigned.headers,
        expiresAt=presigned.expires_at,
    )


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=PartAssetResponse,
)
async def complete_part_asset_upload(
    body: PartAssetCompleteRequest,
    upload_id: str = UploadID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    store: PartAssetUploadStore = Depends(get_part_asset_upload_store),
) -> PartAssetResponse:
    _require_enabled(settings, storage)
    record = await _owned_upload(store, upload_id, operator.account)
    if record.status in {"UPLOADED", "BOUND"}:
        return _response(record)
    if record.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": f"图片当前状态不能完成上传：{record.status}"},
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
            detail={"message": "COS 中的文件大小不一致。"},
        )
    if metadata.content_type != record.mime_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的文件类型不一致。"},
        )
    request_etag = body.etag.strip().strip('"').lower()
    if request_etag and request_etag != metadata.etag.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 返回的 ETag 不一致。"},
        )
    updated = await store.mark_uploaded(upload_id, etag=metadata.etag)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "图片上传记录不存在。"},
        )
    return _response(updated)


@router.post(
    "/uploads/{upload_id}/bind",
    response_model=PartAssetResponse,
)
async def bind_part_asset(
    body: PartAssetBindRequest,
    upload_id: str = UploadID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    store: PartAssetUploadStore = Depends(get_part_asset_upload_store),
) -> PartAssetResponse:
    try:
        part_records = await filemaker.get_record(
            settings.filemaker_part_write_layout,
            body.part_record_id,
        )
        part_record = part_records[0] if isinstance(part_records, list) and part_records else {}
        part_fields = part_record.get("fieldData") or {}
        if (
            str(part_fields.get("part_id") or "").strip() != body.part_id
            or str(part_fields.get(settings.filemaker_part_number_field) or "").strip()
            != body.part_number
        ):
            raise PartAssetError(
                "零件资料与图片绑定请求不一致。",
                code="PART_ASSET_PART_MISMATCH",
                status_code=409,
            )
        record = await bind_part_asset_upload(
            filemaker=filemaker,
            settings=settings,
            store=store,
            upload_id=upload_id,
            operator_account=operator.account,
            part_id=body.part_id,
            part_number=body.part_number,
            part_record_id=body.part_record_id,
        )
    except PartAssetError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc)},
        ) from exc
    return _response(record)


def _require_enabled(settings: Settings, storage: COSStorageService) -> None:
    if not settings.filemaker_part_assets_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "零件资产上传尚未启用。"},
        )
    if not storage.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 配置不完整。"},
        )


async def _owned_upload(
    store: PartAssetUploadStore,
    upload_id: str,
    operator_account: str,
) -> PartAssetUploadRecord:
    record = await store.get(upload_id)
    if not record or record.operator_account != operator_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "图片上传记录不存在。"},
        )
    return record


def _response(record: PartAssetUploadRecord) -> PartAssetResponse:
    return PartAssetResponse(
        uploadId=record.upload_id,
        assetId=record.upload_id if record.status == "BOUND" else "",
        assetRecordId=record.asset_record_id or "",
        objectKey=record.object_key,
        filename=record.original_filename,
        mimeType=record.mime_type,
        fileSize=record.file_size,
        sha256=record.sha256,
        assetType=record.asset_type,
        assetRole=record.asset_role,
        visibility=record.visibility,
        status=record.status,
        # 原始素材保存在私有 bucket；读取时由受权 API 签发短时 URL。
        publicUrl="",
        createdAt=record.created_at,
        uploadedAt=record.uploaded_at,
    )

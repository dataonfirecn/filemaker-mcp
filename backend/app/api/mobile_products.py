from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.mobile_products import (
    ProductPhotoCompleteRequest,
    ProductPhotoPresignRequest,
    ProductPhotoPresignResponse,
    ProductPhotoUploadResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_filemaker_client,
    get_operator_context,
    get_product_photo_upload_store,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.product_photo_upload_store import (
    ProductPhotoSessionConflict,
    ProductPhotoSessionFull,
    ProductPhotoUploadRecord,
    ProductPhotoUploadStore,
)


router = APIRouter(prefix="/mobile/v1/products", tags=["mobile-products"])
ProductSKU = Path(min_length=1, max_length=160)
UploadID = Path(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9._-]+$")
PRODUCT_LAYOUT = "@products"
PRODUCT_ASSET_LAYOUT = "ProductAssets"
PRODUCT_CONTAINER_LIMIT = 10
PDA_PHOTO_LIMIT = 6


@router.post(
    "/{product_sku}/photos/presign",
    response_model=ProductPhotoPresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_photo_presign(
    body: ProductPhotoPresignRequest,
    product_sku: str = ProductSKU,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    upload_store: ProductPhotoUploadStore = Depends(get_product_photo_upload_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ProductPhotoPresignResponse:
    _require_cos(settings, storage)
    normalized_sku = product_sku.strip()
    if body.mime_type not in settings.cos_allowed_content_type_set:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "message": "不支持此产品照片格式。",
                "allowedContentTypes": sorted(settings.cos_allowed_content_type_set),
            },
        )
    if body.file_size > settings.cos_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "message": "产品照片超过上传大小限制。",
                "maxBytes": settings.cos_max_upload_bytes,
            },
        )

    product = await _find_product(filemaker, normalized_sku)
    session_exists = await upload_store.has_session(
        product_sku=normalized_sku,
        operator_account=operator.account,
        session_id=body.session_id,
    )
    if not session_exists and await _product_has_photos(filemaker, product):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "该产品已经有产品照片，PDA 只能为完全无图的产品补拍。",
                "code": "PRODUCT_ALREADY_HAS_IMAGES",
            },
        )

    upload_id = f"pimg_{uuid.uuid4().hex}"
    record_id = str(product.get("recordId") or "")
    fields = _fields(product)
    try:
        record = await upload_store.claim_slot(
            upload_id=upload_id,
            session_id=body.session_id,
            product_sku=normalized_sku,
            product_record_id=record_id,
            source_mod_id=str(product.get("modId") or ""),
            object_key=f"pending/{upload_id}",
            original_filename=body.filename,
            mime_type=body.mime_type,
            file_size=body.file_size,
            sha256=body.sha256,
            source=body.source,
            operator_account=operator.account,
        )
    except ProductPhotoSessionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "code": "PHOTO_SESSION_CONFLICT"},
        ) from exc
    except ProductPhotoSessionFull as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "code": "PHOTO_SESSION_FULL",
                "maximum": PDA_PHOTO_LIMIT,
            },
        ) from exc

    asset_record_id = ""
    try:
        created = await filemaker.create_record(
            PRODUCT_ASSET_LAYOUT,
            _asset_target_data(
                record,
                fields,
                product_record_id=record_id,
                migration_status="pending_upload",
            ),
        )
        asset_record_id = str(created.get("recordId") or "")
        if not asset_record_id:
            raise RuntimeError("FileMaker 未返回 ProductAssets 记录 ID。")
        asset_rows = await filemaker.get_record(
            PRODUCT_ASSET_LAYOUT,
            asset_record_id,
        )
        asset_fields = _fields(asset_rows[0]) if asset_rows else {}
        asset_id = _text(asset_fields.get("id_asset"))
        if not asset_id:
            raise RuntimeError("FileMaker 未生成 ProductAssets UUID。")
        object_key = storage.create_migrated_product_asset_object_key(
            source_record_id=record_id,
            asset_id=asset_id,
            mime_type=body.mime_type,
            original_filename=body.filename,
        )
        bound = await upload_store.bind_asset(
            upload_id,
            object_key=object_key,
            asset_record_id=asset_record_id,
        )
        if not bound or bound.object_key != object_key:
            raise RuntimeError("产品补图记录未能绑定 FileMaker Asset。")
        record = bound
        presigned = await run_in_threadpool(
            storage.create_presigned_upload,
            object_key=object_key,
            content_type=body.mime_type,
        )
    except (COSStorageError, FileMakerAPIError, RuntimeError) as exc:
        await upload_store.mark_failed(upload_id, error=str(exc))
        if asset_record_id:
            try:
                await filemaker.update_record(
                    PRODUCT_ASSET_LAYOUT,
                    asset_record_id,
                    {
                        "migration_status": "upload_failed",
                        "updated_by": operator.account,
                    },
                )
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type="PDA_PRODUCT_PHOTO_PRESIGN",
        status="success",
        target_layout=PRODUCT_ASSET_LAYOUT,
        target_record_id=asset_record_id,
        request_payload={
            "productSku": normalized_sku,
            "sessionId": body.session_id,
            "slot": record.slot,
            "mimeType": body.mime_type,
            "fileSize": body.file_size,
        },
        response_payload={
            "uploadId": upload_id,
            "objectKey": object_key,
            "expiresAt": presigned.expires_at.isoformat(),
        },
    )
    return ProductPhotoPresignResponse(
        uploadId=upload_id,
        objectKey=object_key,
        slot=record.slot,
        uploadUrl=presigned.upload_url,
        headers=presigned.headers,
        expiresAt=presigned.expires_at,
    )


@router.post(
    "/{product_sku}/photos/{upload_id}/complete",
    response_model=ProductPhotoUploadResponse,
)
async def complete_product_photo_upload(
    body: ProductPhotoCompleteRequest,
    background_tasks: BackgroundTasks,
    product_sku: str = ProductSKU,
    upload_id: str = UploadID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    upload_store: ProductPhotoUploadStore = Depends(get_product_photo_upload_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ProductPhotoUploadResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        upload_store,
        upload_id=upload_id,
        product_sku=product_sku,
        operator_account=operator.account,
    )
    if record.status == "SYNCED":
        return _response(record)
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
            detail={"message": "COS 中的产品照片大小不一致。"},
        )
    if metadata.content_type != record.mime_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的产品照片类型不一致。"},
        )
    request_etag = body.etag.strip().strip('"').lower()
    if request_etag and request_etag != metadata.etag.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 返回的 ETag 与客户端上传结果不一致。"},
        )

    if record.status != "SYNCING":
        claimed = await upload_store.claim_syncing(
            upload_id,
            etag=metadata.etag,
        )
        if claimed:
            record = claimed
            background_tasks.add_task(
                _sync_product_photo,
                record=record,
                operator=operator,
                settings=settings,
                storage=storage,
                filemaker=filemaker,
                upload_store=upload_store,
                audit_log=audit_log,
            )
        else:
            refreshed = await upload_store.get(upload_id)
            if not refreshed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"message": "产品补图记录不存在。"},
                )
            record = refreshed

    return _response(record)


@router.get(
    "/{product_sku}/photos/{upload_id}",
    response_model=ProductPhotoUploadResponse,
)
async def get_product_photo_upload(
    background_tasks: BackgroundTasks,
    product_sku: str = ProductSKU,
    upload_id: str = UploadID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    upload_store: ProductPhotoUploadStore = Depends(get_product_photo_upload_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ProductPhotoUploadResponse:
    record = await _owned_record(
        upload_store,
        upload_id=upload_id,
        product_sku=product_sku,
        operator_account=operator.account,
    )
    if record.status == "UPLOADED":
        claimed = await upload_store.claim_syncing(upload_id)
        if claimed:
            record = claimed
            background_tasks.add_task(
                _sync_product_photo,
                record=record,
                operator=operator,
                settings=settings,
                storage=storage,
                filemaker=filemaker,
                upload_store=upload_store,
                audit_log=audit_log,
            )
    return _response(record)


async def _sync_product_photo(
    *,
    record: ProductPhotoUploadRecord,
    operator: OperatorContext,
    settings: Settings,
    storage: COSStorageService,
    filemaker: FileMakerClient,
    upload_store: ProductPhotoUploadStore,
    audit_log: AuditLogStore,
) -> None:
    asset_record_id = ""
    try:
        content = await run_in_threadpool(
            storage.get_object_bytes,
            record.object_key,
            max_bytes=settings.cos_max_upload_bytes,
        )
        product = await _find_product(filemaker, record.product_sku)
        product_fields = _fields(product)
        product_record_id = str(product.get("recordId") or record.product_record_id)
        legacy_field = f"檔案 {record.slot} | 容器"
        target_data = _asset_target_data(
            record,
            product_fields,
            product_record_id=product_record_id,
            migration_status="uploading",
            source_mod_id=str(product.get("modId") or ""),
        )
        existing = await filemaker.find_records(
            PRODUCT_ASSET_LAYOUT,
            query={"migration_key": f"==pda:{record.upload_id}"},
            limit=1,
        )
        existing_rows = _records(existing)
        if existing_rows:
            asset_record_id = str(existing_rows[0].get("recordId") or "")
            await filemaker.update_record(
                PRODUCT_ASSET_LAYOUT,
                asset_record_id,
                target_data,
            )
        else:
            created = await filemaker.create_record(
                PRODUCT_ASSET_LAYOUT,
                target_data,
            )
            asset_record_id = str(created.get("recordId") or "")
        if not asset_record_id:
            raise RuntimeError("FileMaker 未返回 ProductAssets 记录 ID。")

        await filemaker.upload_container(
            PRODUCT_ASSET_LAYOUT,
            asset_record_id,
            "asset_file",
            content,
            record.original_filename,
            record.mime_type,
        )
        await filemaker.upload_container(
            PRODUCT_LAYOUT,
            product_record_id,
            legacy_field,
            content,
            record.original_filename,
            record.mime_type,
        )
        await filemaker.update_record(
            PRODUCT_ASSET_LAYOUT,
            asset_record_id,
            {
                "migration_status": "copied",
                "updated_by": record.operator_account,
            },
        )
        await upload_store.mark_synced(
            record.upload_id,
            asset_record_id=asset_record_id,
        )
        await audit_log.record(
            operator=operator,
            action_type="PDA_PRODUCT_PHOTO_SYNCED",
            status="success",
            target_layout=PRODUCT_ASSET_LAYOUT,
            target_record_id=asset_record_id,
            request_payload={
                "productSku": record.product_sku,
                "uploadId": record.upload_id,
                "slot": record.slot,
            },
            response_payload={
                "productRecordId": product_record_id,
                "legacyField": legacy_field,
                "objectKey": record.object_key,
            },
        )
    except Exception as exc:
        if asset_record_id:
            try:
                await filemaker.update_record(
                    PRODUCT_ASSET_LAYOUT,
                    asset_record_id,
                    {
                        "migration_status": "sync_failed",
                        "updated_by": record.operator_account,
                    },
                )
            except Exception:
                pass
        await upload_store.mark_failed(record.upload_id, error=str(exc))
        await audit_log.record(
            operator=operator,
            action_type="PDA_PRODUCT_PHOTO_SYNCED",
            status="failed",
            target_layout=PRODUCT_ASSET_LAYOUT,
            target_record_id=asset_record_id or None,
            request_payload={
                "productSku": record.product_sku,
                "uploadId": record.upload_id,
                "slot": record.slot,
            },
            error_message=str(exc),
        )


async def _find_product(
    filemaker: FileMakerClient,
    product_sku: str,
) -> dict[str, Any]:
    try:
        result = await filemaker.find_records(
            PRODUCT_LAYOUT,
            query={"product_sku": f"=={product_sku}"},
            limit=1,
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc
    records = _records(result)
    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"找不到产品：{product_sku}"},
        )
    return records[0]


async def _product_has_photos(
    filemaker: FileMakerClient,
    product: dict[str, Any],
) -> bool:
    fields = _fields(product)
    if any(
        _container_present(fields.get(f"檔案 {slot} | 容器"))
        for slot in range(1, PRODUCT_CONTAINER_LIMIT + 1)
    ):
        return True
    source_record_id = str(product.get("recordId") or "")
    if not source_record_id:
        return False
    result = await filemaker.find_records(
        PRODUCT_ASSET_LAYOUT,
        query={"source_record_id": f"=={source_record_id}"},
        limit=100,
    )
    for asset in _records(result):
        asset_fields = _fields(asset)
        if _text(asset_fields.get("migration_status")) in {
            "pending_upload",
            "upload_failed",
            "sync_failed",
        }:
            continue
        if _is_product_photo_asset(asset_fields):
            return True
    return False


def _is_product_photo_asset(fields: dict[str, Any]) -> bool:
    legacy_field = _text(fields.get("legacy_source_field"))
    match = re.fullmatch(r"檔案\s+(\d+)\s+\|\s+容器", legacy_field)
    if match:
        return 1 <= int(match.group(1)) <= PRODUCT_CONTAINER_LIMIT
    return _text(fields.get("asset_type")) == "product_image"


def _container_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(bool(_text(value.get(key))) for key in ("url", "data", "value"))
    return bool(value)


async def _owned_record(
    store: ProductPhotoUploadStore,
    *,
    upload_id: str,
    product_sku: str,
    operator_account: str,
) -> ProductPhotoUploadRecord:
    record = await store.get(upload_id)
    if (
        not record
        or record.product_sku != product_sku.strip()
        or record.operator_account != operator_account
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "产品补图记录不存在。"},
        )
    return record


def _require_cos(settings: Settings, storage: COSStorageService) -> None:
    if not settings.cos_enabled or not storage.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 产品照片上传尚未启用或配置不完整。"},
        )


def _response(record: ProductPhotoUploadRecord) -> ProductPhotoUploadResponse:
    return ProductPhotoUploadResponse(
        uploadId=record.upload_id,
        productSku=record.product_sku,
        objectKey=record.object_key,
        slot=record.slot,
        status=record.status,
        assetRecordId=record.asset_record_id,
        lastError=record.last_error,
        createdAt=record.created_at,
        uploadedAt=record.uploaded_at,
        syncedAt=record.synced_at,
    )


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData") if isinstance(record, dict) else {}
    return fields if isinstance(fields, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _asset_target_data(
    record: ProductPhotoUploadRecord,
    product_fields: dict[str, Any],
    *,
    product_record_id: str,
    migration_status: str,
    source_mod_id: str | None = None,
) -> dict[str, Any]:
    return {
        "product_sku_fk": record.product_sku,
        "system_product_number_fk": _text(
            product_fields.get("系統產品編號")
        ),
        "id_client_snapshot": _text(product_fields.get("id_client")),
        "asset_type": "product_image",
        "visibility": "internal",
        "title": f"PDA 产品照片 {record.slot}",
        "description": "由 PDA 为无图产品补拍",
        "legacy_source_field": f"檔案 {record.slot} | 容器",
        "source_record_id": product_record_id,
        "source_mod_id": (
            source_mod_id
            if source_mod_id is not None
            else record.source_mod_id
        ),
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "migration_key": f"pda:{record.upload_id}",
        "migration_status": migration_status,
        "created_by": record.operator_account,
        "updated_by": record.operator_account,
        "sort_order": record.slot,
        "is_primary": 1 if record.slot == 1 else 0,
        "file_size": record.file_size,
    }

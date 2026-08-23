from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings
from app.models.part_creation import (
    PartCreationCacheStatus,
    PartCreationOptionsResponse,
    PartCreationRequest,
    PartCreationResponse,
    PartVendorSearchResponse,
    PartValidationResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
    get_part_asset_upload_store,
    get_part_creation_options_cache,
    get_settings,
    get_webviewer_access,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient, FileMakerODataError
from app.services.part_creation import (
    PartCreationError,
    create_part,
    part_creation_audit_payload,
    search_part_vendors,
    validate_part_creation,
)
from app.services.part_creation_options_cache import PartCreationOptionsCache
from app.services.part_asset_upload_store import PartAssetUploadStore
from app.services.part_assets import (
    PartAssetError,
    bind_part_asset_upload,
    require_bindable_part_asset_upload,
)

router = APIRouter(prefix="/part-creation", tags=["part-creation"])


@router.get("/options", response_model=PartCreationOptionsResponse)
async def get_part_creation_options(
    cache: PartCreationOptionsCache = Depends(get_part_creation_options_cache),
    _: OperatorContext = Depends(get_operator_context),
) -> PartCreationOptionsResponse:
    try:
        return await cache.get()
    except FileMakerAPIError as exc:
        raise _filemaker_http_error(exc) from exc


@router.get("/cache/status", response_model=PartCreationCacheStatus)
async def get_part_creation_cache_status(
    cache: PartCreationOptionsCache = Depends(get_part_creation_options_cache),
    _: OperatorContext = Depends(get_operator_context),
) -> PartCreationCacheStatus:
    return PartCreationCacheStatus.model_validate(cache.status())


@router.post("/cache/refresh", response_model=PartCreationCacheStatus)
async def refresh_part_creation_cache(
    cache: PartCreationOptionsCache = Depends(get_part_creation_options_cache),
    access: dict[str, bool] = Depends(get_webviewer_access),
    operator: OperatorContext = Depends(get_operator_context),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> PartCreationCacheStatus:
    if not access.get("canManageAccounts", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "只有 DMS 管理员可以手动刷新 FileMaker 选项缓存。",
                "permission": "canManageAccounts",
            },
        )
    try:
        await cache.refresh(reason=f"manual:{operator.account}")
    except FileMakerAPIError as exc:
        await audit_log.record(
            operator=operator,
            action_type="REFRESH_PART_CREATION_CACHE",
            status="failed",
            error_message=str(exc),
        )
        raise _filemaker_http_error(exc) from exc
    await audit_log.record(
        operator=operator,
        action_type="REFRESH_PART_CREATION_CACHE",
        status="success",
        response_payload=cache.status(),
    )
    return PartCreationCacheStatus.model_validate(cache.status())


@router.get("/vendors", response_model=PartVendorSearchResponse)
async def get_part_vendors(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=40, ge=1, le=50),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    _: OperatorContext = Depends(get_operator_context),
) -> PartVendorSearchResponse:
    try:
        return await search_part_vendors(filemaker, q, limit=limit)
    except FileMakerAPIError as exc:
        raise _filemaker_http_error(exc) from exc


@router.post("/validate", response_model=PartValidationResponse)
async def validate_new_part(
    body: PartCreationRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    settings: Settings = Depends(get_settings),
    cache: PartCreationOptionsCache = Depends(get_part_creation_options_cache),
    _: OperatorContext = Depends(get_operator_context),
) -> PartValidationResponse:
    try:
        return await validate_part_creation(
            filemaker,
            settings,
            body,
            odata=odata,
            options=await cache.get(),
        )
    except FileMakerAPIError as exc:
        raise _filemaker_http_error(exc) from exc
    except FileMakerODataError as exc:
        raise _odata_http_error(exc) from exc


@router.post(
    "",
    response_model=PartCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_part(
    body: PartCreationRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    part_asset_store: PartAssetUploadStore = Depends(get_part_asset_upload_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> PartCreationResponse:
    audit_payload = part_creation_audit_payload(body)
    try:
        if body.photo_upload_id.strip():
            await require_bindable_part_asset_upload(
                settings=settings,
                store=part_asset_store,
                upload_id=body.photo_upload_id.strip(),
                operator_account=operator.account,
            )
        response = await create_part(
            filemaker,
            settings,
            body,
            odata=odata,
            created_by=operator.account,
        )
    except PartCreationError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_PART_WEBVIEWER",
            status="failed",
            target_layout=settings.filemaker_part_write_layout,
            request_payload=audit_payload,
            response_payload={"code": exc.code, "errors": exc.errors},
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "code": exc.code,
                "message": str(exc),
                "errors": exc.errors,
                "warnings": exc.warnings,
            },
        ) from exc
    except FileMakerAPIError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_PART_WEBVIEWER",
            status="failed",
            target_layout=settings.filemaker_part_write_layout,
            request_payload=audit_payload,
            error_message=str(exc),
        )
        raise _filemaker_http_error(exc) from exc
    except FileMakerODataError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_PART_WEBVIEWER",
            status="failed",
            target_layout=settings.filemaker_part_write_layout,
            request_payload=audit_payload,
            error_message=str(exc),
        )
        raise _odata_http_error(exc) from exc
    except PartAssetError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_PART_WEBVIEWER",
            status="failed",
            target_layout=settings.filemaker_part_asset_layout,
            request_payload=audit_payload,
            response_payload={"code": exc.code},
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc

    if body.photo_upload_id.strip():
        try:
            asset = await bind_part_asset_upload(
                filemaker=filemaker,
                settings=settings,
                store=part_asset_store,
                upload_id=body.photo_upload_id.strip(),
                operator_account=operator.account,
                part_id=response.part_id,
                part_number=response.part_number,
                part_record_id=response.record_id,
            )
            response = response.model_copy(
                update={
                    "photo_uploaded": True,
                    "photo_asset_id": asset.upload_id,
                }
            )
        except (PartAssetError, FileMakerAPIError) as exc:
            response = response.model_copy(
                update={
                    "photo_uploaded": False,
                    "warnings": [
                        *response.warnings,
                        f"零件已建立，但照片绑定失败，可稍后重试：{exc}",
                    ],
                }
            )

    await audit_log.record(
        operator=operator,
        action_type="CREATE_PART_WEBVIEWER",
        status="success",
        target_layout=settings.filemaker_part_write_layout,
        target_record_id=response.record_id,
        request_payload=audit_payload,
        response_payload=response.model_dump(by_alias=True),
    )
    return response


def _filemaker_http_error(exc: FileMakerAPIError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": str(exc), "payload": exc.payload},
    )


def _odata_http_error(exc: FileMakerODataError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": str(exc), "payload": exc.payload},
    )

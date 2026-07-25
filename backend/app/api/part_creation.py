from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings
from app.models.part_creation import (
    PartCreationOptionsResponse,
    PartCreationRequest,
    PartCreationResponse,
    PartValidationResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_operator_context,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.part_creation import (
    PartCreationError,
    create_part,
    load_part_creation_options,
    part_creation_audit_payload,
    validate_part_creation,
)

router = APIRouter(prefix="/part-creation", tags=["part-creation"])


@router.get("/options", response_model=PartCreationOptionsResponse)
async def get_part_creation_options(
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    _: OperatorContext = Depends(get_operator_context),
) -> PartCreationOptionsResponse:
    try:
        return await load_part_creation_options(filemaker, settings)
    except FileMakerAPIError as exc:
        raise _filemaker_http_error(exc) from exc


@router.post("/validate", response_model=PartValidationResponse)
async def validate_new_part(
    body: PartCreationRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    _: OperatorContext = Depends(get_operator_context),
) -> PartValidationResponse:
    try:
        return await validate_part_creation(filemaker, settings, body)
    except FileMakerAPIError as exc:
        raise _filemaker_http_error(exc) from exc


@router.post(
    "",
    response_model=PartCreationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_part(
    body: PartCreationRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> PartCreationResponse:
    audit_payload = part_creation_audit_payload(body)
    try:
        response = await create_part(filemaker, settings, body)
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

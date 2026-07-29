from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import Settings
from app.models.material_ids import (
    MaterialIdGenerationRequest,
    MaterialIdGenerationResponse,
    MaterialIdOptionsResponse,
    RelatedPartSearchResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_operator_context,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.material_id_generator import (
    PART_LAYOUT,
    MaterialIdGenerationError,
    generate_material_id,
)
from app.services.material_id_options import (
    load_material_id_options,
    search_related_parts,
)
from app.services.webviewer_session import (
    WebViewerSessionError,
    operator_from_session,
    verify_external_context,
)

router = APIRouter(prefix="/material-ids", tags=["material-ids"])


@router.get("/options", response_model=MaterialIdOptionsResponse)
async def get_material_id_options(
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    _: OperatorContext = Depends(get_operator_context),
) -> MaterialIdOptionsResponse:
    try:
        return await load_material_id_options(
            filemaker,
            cache_ttl_seconds=settings.filemaker_material_options_cache_ttl_seconds,
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc


@router.get("/related-parts", response_model=RelatedPartSearchResponse)
async def get_related_parts(
    query: str = Query(default="", max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    _: OperatorContext = Depends(get_operator_context),
) -> RelatedPartSearchResponse:
    try:
        return await search_related_parts(filemaker, query, limit=limit)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc


@router.post("/generate", response_model=MaterialIdGenerationResponse)
async def generate_material_id_preview(
    body: MaterialIdGenerationRequest,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> MaterialIdGenerationResponse:
    return await _generate_and_audit(
        body=body,
        filemaker=filemaker,
        audit_log=audit_log,
        operator=operator,
        action_type="COMPARE_MATERIAL_ID",
    )


@router.get("/filemaker-generate", response_model=MaterialIdGenerationResponse)
async def generate_material_id_for_filemaker(
    ctx: str = Query(min_length=1),
    sig: str = Query(min_length=1),
    material: str = Query(default="", max_length=80),
    customer: str = Query(default="", max_length=80),
    serial: str = Query(default="", max_length=20),
    manufacture: str = Query(default="", max_length=80),
    color: str = Query(default="", max_length=80),
    other: str = Query(default="", max_length=120),
    script_part_number: str = Query(
        default="",
        alias="scriptPartNumber",
        max_length=320,
    ),
    settings: Settings = Depends(get_settings),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> MaterialIdGenerationResponse:
    """Generate a part number for a native FileMaker script.

    FileMaker signs the request with the existing StarRC_WebViewerURL custom
    function, but this endpoint does not create a WebViewer session. It only
    reads existing part numbers through the Data API and returns JSON.
    """
    try:
        context = verify_external_context(ctx, sig, settings)
    except WebViewerSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid FileMaker request signature"},
        ) from exc

    body = MaterialIdGenerationRequest(
        material=material,
        customer=customer,
        serial=serial,
        manufacture=manufacture,
        color=color,
        other=other,
        scriptPartNumber=script_part_number,
    )
    operator = operator_from_session(
        {
            "sessionId": "filemaker-direct-api",
            "operator": context.get("operator") or {},
        }
    )
    return await _generate_and_audit(
        body=body,
        filemaker=filemaker,
        audit_log=audit_log,
        operator=operator,
        action_type="GENERATE_MATERIAL_ID_FILEMAKER_API",
    )


async def _generate_and_audit(
    *,
    body: MaterialIdGenerationRequest,
    filemaker: FileMakerClient,
    audit_log: AuditLogStore,
    operator: OperatorContext,
    action_type: str,
) -> MaterialIdGenerationResponse:
    try:
        response = await generate_material_id(filemaker, body)
    except MaterialIdGenerationError as exc:
        await audit_log.record(
            operator=operator,
            action_type=action_type,
            status="failed",
            target_layout=PART_LAYOUT,
            request_payload=_audit_request(body),
            error_message=str(exc),
            response_payload={"code": exc.code},
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type=action_type,
        status="success",
        target_layout=PART_LAYOUT,
        request_payload=_audit_request(body),
        response_payload={
            "partNumber": response.part_number,
            "serial": response.serial,
            "autoSerial": response.auto_serial,
            "matchesScript": response.matches_script,
            "scannedCount": response.scanned_count,
        },
    )
    return response


def _audit_request(body: MaterialIdGenerationRequest) -> dict[str, str]:
    return {
        "material": body.material.strip(),
        "customer": body.customer.strip(),
        "serial": body.serial.strip(),
        "manufacture": body.manufacture.strip(),
        "color": body.color.strip(),
        "other": body.other.strip(),
        "scriptPartNumber": body.script_part_number.strip(),
    }

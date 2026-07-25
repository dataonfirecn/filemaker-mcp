from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.odata import (
    ODataCascadeRequest,
    ODataCascadeResponse,
    ODataMetadataResponse,
    ODataRecordsResponse,
    ODataRelationshipQueryRequest,
    ODataRelationshipQueryResponse,
    ODataRelationshipsResponse,
    ODataStatusResponse,
    ODataTablesResponse,
)
from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.dependencies import get_filemaker_odata_client, get_operator_context, get_settings
from app.services.filemaker_odata_client import FileMakerODataClient, FileMakerODataError
from app.services.odata_relationship_registry import ODataRelationshipExecutor, ODataRelationshipRegistry

router = APIRouter(prefix="/odata", tags=["odata"])


def odata_error_response(exc: FileMakerODataError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": str(exc), "payload": exc.payload},
    )


@router.get("/status", response_model=ODataStatusResponse)
async def get_odata_status(
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataStatusResponse:
    return ODataStatusResponse(**client.status())


@router.get("/metadata", response_model=ODataMetadataResponse)
async def get_odata_metadata(
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataMetadataResponse:
    try:
        schema = await client.metadata_schema()
        return ODataMetadataResponse(**schema.to_dict())
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc


@router.get("/tables", response_model=ODataTablesResponse)
async def list_odata_tables(
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataTablesResponse:
    try:
        tables = await client.tables()
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc
    if q:
        needle = q.casefold()
        tables = [item for item in tables if needle in item["name"].casefold()]
    return ODataTablesResponse(tables=tables[:limit])


@router.get("/tables/{table}/records", response_model=ODataRecordsResponse)
async def get_odata_records(
    table: str,
    select: list[str] | None = Query(default=None),
    filter_expr: str | None = Query(default=None, alias="filter"),
    expand: list[str] | None = Query(default=None),
    orderby: str | None = Query(default=None),
    top: int = Query(default=10, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    count: bool = Query(default=True),
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataRecordsResponse:
    try:
        result = await client.records(
            table,
            select=select,
            filter_expr=filter_expr,
            expand=expand,
            orderby=orderby,
            top=top,
            skip=skip,
            count=count,
        )
        return ODataRecordsResponse(**result)
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc


@router.get("/relationships", response_model=ODataRelationshipsResponse)
async def list_odata_relationships(
    _operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
) -> ODataRelationshipsResponse:
    registry = _relationship_registry(settings)
    return _relationships_response(registry)


@router.post("/relationships/reload", response_model=ODataRelationshipsResponse)
async def reload_odata_relationships(
    _operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
) -> ODataRelationshipsResponse:
    return _relationships_response(_relationship_registry(settings))


@router.post("/relationships/{relationship_name}/query", response_model=ODataRelationshipQueryResponse)
async def query_odata_relationship(
    relationship_name: str,
    body: ODataRelationshipQueryRequest,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
    settings: Settings = Depends(get_settings),
) -> ODataRelationshipQueryResponse:
    relationship_registry = _relationship_registry(settings)
    relationship = relationship_registry.get(relationship_name)
    if relationship is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"Unknown OData relationship: {relationship_name}"},
        )
    try:
        result = await ODataRelationshipExecutor(client, relationship_registry).query(
            relationship,
            value=body.value,
            top=body.top,
            include_target_rows=body.include_target_rows,
        )
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc
    return ODataRelationshipQueryResponse(**result)


def _relationship_registry(settings: Settings) -> ODataRelationshipRegistry:
    return ODataRelationshipRegistry.from_mapping_path(settings.semantic_mapping_path)


def _relationships_response(registry: ODataRelationshipRegistry) -> ODataRelationshipsResponse:
    return ODataRelationshipsResponse(
        **registry.metadata(),
        relationships=[item.to_dict() for item in registry.list()],
    )


@router.get("/tables/{table}/records/{key}/related/{related}", response_model=ODataRecordsResponse)
async def get_odata_related_records(
    table: str,
    key: str,
    related: str,
    select: list[str] | None = Query(default=None),
    filter_expr: str | None = Query(default=None, alias="filter"),
    orderby: str | None = Query(default=None),
    top: int = Query(default=10, ge=1, le=100),
    skip: int = Query(default=0, ge=0),
    count: bool = Query(default=True),
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataRecordsResponse:
    try:
        result = await client.related_records(
            table,
            key,
            related,
            select=select,
            filter_expr=filter_expr,
            orderby=orderby,
            top=top,
            skip=skip,
            count=count,
        )
        return ODataRecordsResponse(**result)
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc


@router.post("/cascade", response_model=ODataCascadeResponse)
async def get_odata_cascade_records(
    body: ODataCascadeRequest,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> ODataCascadeResponse:
    try:
        result = await client.cascade_related_records(
            body.table,
            body.key,
            body.path,
            top=body.top,
            count=body.count,
        )
        return ODataCascadeResponse(**result)
    except FileMakerODataError as exc:
        raise odata_error_response(exc) from exc

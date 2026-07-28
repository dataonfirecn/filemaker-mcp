from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.services.cos_storage import COSStorageService
from app.services.dependencies import (
    get_cos_storage_service,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
)
from app.services.part_directory import (
    PartTimeField,
    get_part_directory_detail,
    get_part_directory_section,
    list_part_directory,
)


router = APIRouter(prefix="/part-directory", tags=["part-directory"])


@router.get("/options")
async def get_part_directory_options(
    _: object = Depends(get_operator_context),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
) -> dict:
    try:
        metadata = await filemaker.get_layout_metadata("新增零件资料")
    except FileMakerAPIError as exc:
        raise _filemaker_error(exc) from exc
    value_lists = {
        str(item.get("name") or ""): item.get("values") or []
        for item in metadata.get("valueLists", [])
        if isinstance(item, dict)
    }
    return {
        "materialCategories": _value_list(value_lists.get("零件性質")),
        "partCategories": _value_list(value_lists.get("零件品種")),
        "lifecycleStatuses": _value_list(value_lists.get("狀態")),
        "departmentDivisions": _value_list(value_lists.get("零件狀態")),
        "warehouseDivisions": _value_list(value_lists.get("倉庫分工")),
        "warehouseCodes": _value_list(value_lists.get("倉庫")),
        "auditStatuses": [
            {"value": "已審核", "label": "已审核"},
            {"value": "未審核", "label": "未审核"},
        ],
        "sourceLayout": "新增零件资料",
    }


@router.get("")
async def get_part_directory(
    q: str = Query(default="", max_length=80),
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=10, ge=1, le=50, alias="pageSize"),
    material_category: str = Query(default="", max_length=120, alias="materialCategory"),
    part_category: str = Query(default="", max_length=120, alias="partCategory"),
    lifecycle_status: str = Query(default="", max_length=80, alias="lifecycleStatus"),
    audit_status: str = Query(default="", max_length=80, alias="auditStatus"),
    manufacturer: str = Query(default="", max_length=160),
    department: str = Query(default="", max_length=80),
    warehouse_division: str = Query(
        default="", max_length=80, alias="warehouseDivision"
    ),
    warehouse_code: str = Query(default="", max_length=120, alias="warehouseCode"),
    time_field: PartTimeField = Query(default="updated", alias="timeField"),
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    _: object = Depends(get_operator_context),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> dict:
    if date_from and date_to and date_to < date_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "结束日期不能早于开始日期。"},
        )
    try:
        return await list_part_directory(
            odata=odata,
            storage=storage,
            query=q,
            page=page,
            page_size=page_size,
            material_category=material_category,
            part_category=part_category,
            lifecycle_status=lifecycle_status,
            audit_status=audit_status,
            manufacturer=manufacturer,
            department=department,
            warehouse_division=warehouse_division,
            warehouse_code=warehouse_code,
            time_field=time_field,
            date_from=date_from,
            date_to=date_to,
        )
    except FileMakerODataError as exc:
        raise _odata_error(exc) from exc


@router.get("/{identifier}/sections/{section}")
async def get_part_section(
    identifier: str,
    section: Literal["procurement", "specifications", "quality", "inventory", "records"],
    _: object = Depends(get_operator_context),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> dict:
    try:
        result = await get_part_directory_section(
            odata=odata,
            identifier=identifier,
            section=section,
        )
    except FileMakerODataError as exc:
        raise _odata_error(exc) from exc
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"找不到零件：{identifier}"},
        )
    return result


@router.get("/{identifier}")
async def get_part_detail(
    identifier: str,
    _: object = Depends(get_operator_context),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> dict:
    try:
        result = await get_part_directory_detail(
            odata=odata,
            storage=storage,
            identifier=identifier,
        )
    except FileMakerODataError as exc:
        raise _odata_error(exc) from exc
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"找不到零件：{identifier}"},
        )
    return result


def _value_list(raw: object) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        label = str(item.get("displayValue") or value).strip()
        values.append({"value": value, "label": label or value})
    return values


def _odata_error(exc: FileMakerODataError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": "FileMaker OData 读取失败，请稍后重试。"},
    )


def _filemaker_error(exc: FileMakerAPIError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": "FileMaker 选项读取失败，请稍后重试。"},
    )

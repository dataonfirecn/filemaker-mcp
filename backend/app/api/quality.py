from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from string import ascii_uppercase
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.core.config import Settings
from app.models.quality import (
    CreateQualityInspectionRequest,
    QualityArrivalBatch,
    QualityCheckItem,
    QualityInspection,
    QualityInspectionAdminDetail,
    QualityInspectionAdminListResponse,
    QualityScanResolution,
    QualityScanResolveRequest,
    QualitySpecVersion,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
    get_quality_inspection_store,
    get_settings,
    get_webviewer_access,
    get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient, FileMakerODataError
from app.services.quality_inspection_store import QualityInspectionStore
from app.services.quality_standards import PART_STANDARD_FIELDS, dimension_check_items


router = APIRouter(
    tags=["quality"],
    dependencies=[Depends(get_webviewer_session_context)],
)

PURCHASE_LINE_TABLE = "採購單資料"
ARRIVAL_TABLE = "採購單資料到貨"
SPEC_TABLE = "品檢規範"
QUALITY_PERMISSION = "canViewQuality"
SHANGHAI = ZoneInfo("Asia/Shanghai")

PURCHASE_LINE_FIELDS = (
    "id",
    "ID_採購單",
    "零件編號",
    "零件名稱",
    "廠商編號",
    "廠商名稱",
    "內部訂單編號",
    "需要品檢",
    "品檢狀況",
)
ARRIVAL_FIELDS = (
    "ID",
    "ID_採購單資料",
    "到貨數量",
    "到貨日期",
    "倉庫數量",
    "入庫日期",
    "品檢日期",
    "退貨數量",
    "QC檢查員",
    "狀態",
    "到貨狀態",
)
SPEC_FIELDS = (
    "ID",
    "零件編號",
    "零件品名",
    "品檢注意事項",
    "審核",
    *(f"品檢規範 {index}" for index in range(1, 11)),
)

_arrival_locks: dict[str, asyncio.Lock] = {}
_arrival_locks_guard = asyncio.Lock()


@router.post("/scan/resolve", response_model=QualityScanResolution)
async def resolve_quality_scan(
    body: QualityScanResolveRequest,
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    quality_store: QualityInspectionStore = Depends(get_quality_inspection_store),
    access: dict[str, bool] = Depends(get_webviewer_access),
    settings: Settings = Depends(get_settings),
) -> QualityScanResolution:
    _require_quality_permission(access)
    resource, identifier = _parse_scan_code(body.code)
    try:
        if resource == "arrival":
            arrival = await _find_one(
                odata,
                ARRIVAL_TABLE,
                field="ID",
                value=identifier,
                select=ARRIVAL_FIELDS,
            )
            if not arrival:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="找不到这个到货批次。",
                )
            purchase_line_id = _text(arrival.get("ID_採購單資料"))
            purchase_line = await _purchase_line(odata, purchase_line_id)
            arrivals = [arrival]
        else:
            purchase_line_id = identifier
            purchase_line = await _purchase_line(odata, purchase_line_id)
            arrivals = await _arrival_rows(
                odata,
                purchase_line_id,
                max_rows=settings.filemaker_quality_max_arrivals,
            )
    except HTTPException:
        raise
    except FileMakerODataError as exc:
        raise _odata_http_error(exc) from exc

    if not purchase_line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到这个采购明细。",
        )
    if not arrivals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="采购明细还没有可用的到货批次。",
        )

    inspection_by_arrival = await quality_store.catalog_by_arrival_ids(
        [_text(row.get("ID")) for row in arrivals]
    )
    return _resolution(
        purchase_line,
        arrivals,
        inspection_by_arrival=inspection_by_arrival,
    )


@router.post(
    "/qc/inspections",
    response_model=QualityInspection,
    status_code=status.HTTP_201_CREATED,
)
async def create_quality_inspection(
    body: CreateQualityInspectionRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=240),
    operator: OperatorContext = Depends(get_operator_context),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    quality_store: QualityInspectionStore = Depends(get_quality_inspection_store),
    access: dict[str, bool] = Depends(get_webviewer_access),
    settings: Settings = Depends(get_settings),
) -> QualityInspection:
    _require_quality_permission(access)
    if not settings.quality_write_enabled:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="网站数据库的来料品检写入尚未启用。",
        )

    arrival_id = body.arrival_batch_id.strip()
    canonical_key = f"quality-inspection-{arrival_id}"
    if idempotency_key.strip() != canonical_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="幂等键与到货批次不匹配，请重新扫码后再试。",
        )

    lock = await _arrival_lock(arrival_id)
    async with lock:
        try:
            arrival = await _find_one(
                odata,
                ARRIVAL_TABLE,
                field="ID",
                value=arrival_id,
                select=ARRIVAL_FIELDS,
            )
            if not arrival:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="找不到这个到货批次。",
                )
            purchase_line_id = _text(arrival.get("ID_採購單資料"))
            purchase_line = await _purchase_line(odata, purchase_line_id)
            if not purchase_line:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="到货批次对应的采购明细不存在。",
                )

            available_quantity = _available_quantity(arrival)
            if available_quantity <= 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="这个到货批次已经没有可品检数量。",
                )

            inspection_method = "抽檢"
            sample_quantity = min(10, available_quantity)
            spec_version, check_items = await _quality_spec(
                odata,
                filemaker=filemaker,
                part_number=_text(purchase_line.get("零件編號")),
                measurement_count=min(10, sample_quantity),
                part_layout=settings.filemaker_quality_part_layout,
            )
            now = datetime.now(SHANGHAI)
            inspection_id = _inspection_id(arrival_id)
            request_payload = {
                "endpoint": "/api/qc/inspections",
                "arrivalBatchID": arrival_id,
                "idempotencyKey": canonical_key,
                "client": {
                    "channel": request.headers.get("X-Client-Channel", ""),
                    "appBuild": request.headers.get("X-App-Build", ""),
                    "appVersion": request.headers.get("X-App-Version", ""),
                    "userAgent": request.headers.get("User-Agent", ""),
                    "remoteAddress": request.client.host if request.client else "",
                },
            }
            source_snapshot = {
                "schema": "starrc.quality-source-snapshot.v1",
                "capturedAt": now.isoformat(),
                "sourceSystem": "FileMaker",
                "database": settings.filemaker_database,
                "purchaseLine": {
                    "table": PURCHASE_LINE_TABLE,
                    "keyField": "id",
                    "keyValue": purchase_line_id,
                    "fields": dict(purchase_line),
                },
                "arrivalBatch": {
                    "table": ARRIVAL_TABLE,
                    "keyField": "ID",
                    "keyValue": arrival_id,
                    "fields": dict(arrival),
                },
            }
            record, created = await quality_store.create_or_get(
                record={
                    "id": inspection_id,
                    "purchaseLineID": purchase_line_id,
                    "arrivalBatchID": arrival_id,
                    "inspectionRound": 1,
                    "idempotencyKey": canonical_key,
                    "purchaseOrderNumber": _text(purchase_line.get("ID_採購單")),
                    "nbNumber": _text(purchase_line.get("內部訂單編號")),
                    "partNumber": _text(purchase_line.get("零件編號")),
                    "partName": _text(purchase_line.get("零件名稱")),
                    "supplierName": _text(purchase_line.get("廠商名稱")),
                    "arrivalDate": _text(arrival.get("到貨日期")),
                    "arrivalQuantity": _integer(arrival.get("到貨數量")),
                    "returnedQuantity": _integer(arrival.get("退貨數量")),
                    "warehousedQuantity": _integer(arrival.get("倉庫數量")),
                    "availableQuantity": available_quantity,
                    "inspectionMethod": inspection_method,
                    "sampleQuantity": sample_quantity,
                    "status": "检查中",
                    "conclusion": "",
                    "specVersion": spec_version.model_dump(mode="json", by_alias=True),
                    "checkItems": [
                        item.model_dump(mode="json", by_alias=True)
                        for item in check_items
                    ],
                    "sourceSnapshot": source_snapshot,
                    "requestPayload": request_payload,
                    "createdAt": now.isoformat(),
                    "updatedAt": now.isoformat(),
                },
                operator=operator,
                event_payload={
                    "request": request_payload,
                    "sourceReferences": {
                        "purchaseLineID": purchase_line_id,
                        "arrivalBatchID": arrival_id,
                    },
                    "specVersion": spec_version.model_dump(mode="json", by_alias=True),
                },
            )
        except HTTPException:
            raise
        except FileMakerODataError as exc:
            raise _odata_http_error(exc) from exc

        response = _inspection_from_record(record)
        await audit_log.record(
            operator=operator,
            action_type=(
                "MOBILE_INCOMING_QUALITY_CREATE"
                if created
                else "MOBILE_INCOMING_QUALITY_IDEMPOTENT_REPLAY"
            ),
            status="success",
            target_table="quality_inspection",
            target_record_id=response.id,
            order_id=_text(purchase_line.get("ID_採購單")),
            request_payload={
                "arrivalBatchID": arrival_id,
                "purchaseLineID": purchase_line_id,
                "idempotencyKey": canonical_key,
            },
            response_payload={
                **response.model_dump(mode="json", by_alias=True),
                "created": created,
                "persistence": "PostgreSQL",
            },
        )
        return response


@router.get(
    "/webviewer/admin/quality-inspections",
    response_model=QualityInspectionAdminListResponse,
)
async def list_quality_inspections_for_admin(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    q: str = Query(default="", max_length=200),
    inspection_status: str = Query(default="", alias="status", max_length=80),
    quality_store: QualityInspectionStore = Depends(get_quality_inspection_store),
    access: dict[str, bool] = Depends(get_webviewer_access),
) -> QualityInspectionAdminListResponse:
    _require_admin_permission(access)
    records, total = await quality_store.list_inspections(
        limit=page_size,
        offset=(page - 1) * page_size,
        query=q,
        status=inspection_status,
    )
    return QualityInspectionAdminListResponse(
        items=records,
        total=total,
        page=page,
        pageSize=page_size,
        totalPages=max(1, (total + page_size - 1) // page_size),
    )


@router.get(
    "/webviewer/admin/quality-inspections/{inspection_id}",
    response_model=QualityInspectionAdminDetail,
)
async def get_quality_inspection_for_admin(
    inspection_id: str,
    quality_store: QualityInspectionStore = Depends(get_quality_inspection_store),
    access: dict[str, bool] = Depends(get_webviewer_access),
) -> QualityInspectionAdminDetail:
    _require_admin_permission(access)
    record = await quality_store.get_inspection(inspection_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到这个来料品检记录。",
        )
    return QualityInspectionAdminDetail.model_validate(record)


def _require_quality_permission(access: dict[str, bool]) -> None:
    if not access.get(QUALITY_PERMISSION, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有来料品检权限。",
        )


def _require_admin_permission(access: dict[str, bool]) -> None:
    if not access.get("canManageAccounts", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前账号没有系统管理权限。",
        )


def _parse_scan_code(code: str) -> tuple[str, str]:
    text = code.strip()
    parts = [part.strip() for part in text.split("|")]
    if len(parts) == 2 and parts[0] == "4" and parts[1]:
        return "purchase_line", parts[1]
    if (
        len(parts) == 4
        and parts[0].upper() == "STARRC"
        and parts[1] == "1"
        and parts[2].upper() == "ARRIVAL"
        and parts[3]
    ):
        return "arrival", parts[3]
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="这不是来料品检二维码，请扫描 4|采购明细ID 或到货批次二维码。",
    )


async def _purchase_line(
    odata: FileMakerODataClient,
    purchase_line_id: str,
) -> dict:
    if not purchase_line_id:
        return {}
    return await _find_one(
        odata,
        PURCHASE_LINE_TABLE,
        field="id",
        value=purchase_line_id,
        select=PURCHASE_LINE_FIELDS,
    )


async def _arrival_rows(
    odata: FileMakerODataClient,
    purchase_line_id: str,
    *,
    max_rows: int,
) -> list[dict]:
    rows: list[dict] = []
    skip = 0
    page_size = max(1, min(odata.settings.filemaker_odata_max_top, max_rows))
    while len(rows) < max_rows:
        result = await odata.records(
            ARRIVAL_TABLE,
            select=_select(ARRIVAL_FIELDS),
            filter_expr=f'{_field("ID_採購單資料")} eq {_literal(purchase_line_id)}',
            orderby="到貨日期 desc",
            top=min(page_size, max_rows - len(rows)),
            skip=skip,
        )
        page = result.get("rows") if isinstance(result.get("rows"), list) else []
        rows.extend(row for row in page if isinstance(row, dict))
        if len(page) < page_size:
            break
        skip += len(page)
    return rows[:max_rows]


async def _find_one(
    odata: FileMakerODataClient,
    table: str,
    *,
    field: str,
    value: str,
    select: tuple[str, ...],
) -> dict:
    result = await odata.records(
        table,
        select=_select(select),
        filter_expr=f"{_field(field)} eq {_literal(value)}",
        top=2,
    )
    rows = result.get("rows") if isinstance(result.get("rows"), list) else []
    return dict(rows[0]) if rows and isinstance(rows[0], dict) else {}


async def _quality_spec(
    odata: FileMakerODataClient,
    *,
    filemaker: FileMakerClient | None = None,
    part_number: str,
    measurement_count: int = 10,
    part_layout: str = "@零件",
) -> tuple[QualitySpecVersion, list[QualityCheckItem]]:
    part = await _part_standard_row(
        odata,
        filemaker=filemaker,
        part_number=part_number,
        part_layout=part_layout,
    )
    dimension_items = dimension_check_items(part, sample_count=measurement_count)
    row = await _find_one(
        odata,
        SPEC_TABLE,
        field="零件編號",
        value=part_number,
        select=SPEC_FIELDS,
    )
    raw_items = [
        _text(row.get(f"品檢規範 {index}"))
        for index in range(1, 11)
    ]
    raw_items = [item for item in raw_items if item]
    if not raw_items:
        attention = _text(row.get("品檢注意事項"))
        raw_items = [attention] if attention else []

    check_items = dimension_items + [
        QualityCheckItem(
            id=f"SPEC-{index + 1}" if dimension_items else ascii_uppercase[index],
            code=f"规{index + 1}" if dimension_items else ascii_uppercase[index],
            title=(
                "品检注意事项"
                if len(raw_items) == 1 and _text(row.get("品檢注意事項")) == instructions
                else f"品检规范 {index + 1}"
            ),
            instructions=instructions,
            inputType="result",
            unit="",
            required=True,
            sampleCount=1,
        )
        for index, instructions in enumerate(raw_items[:10])
    ]
    version_source = {
        "id": _text(row.get("ID")) or part_number,
        "partNumber": part_number,
        "approvedBy": _text(row.get("審核")),
        "items": [item.model_dump(by_alias=True) for item in check_items],
    }
    digest = hashlib.sha256(
        json.dumps(
            version_source,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:8].upper()
    return (
        QualitySpecVersion(
            id=version_source["id"],
            version=f"FM-{digest}",
            approvedBy=version_source["approvedBy"],
            effectiveAt="",
        ),
        check_items,
    )


async def _part_standard_row(
    odata: FileMakerODataClient,
    *,
    filemaker: FileMakerClient | None = None,
    part_number: str,
    part_layout: str = "@零件",
) -> dict:
    """Read A–L standards while preserving legacy mixed field values.

    Some tolerance fields are declared as Number but contain text such as
    ``贯穿``. OData coerces that content to null; the Data API preserves it.
    """
    if filemaker is not None and hasattr(filemaker, "find_records"):
        try:
            found = await filemaker.find_records(
                part_layout,
                {"part_number": f"=={part_number}"},
                limit=2,
            )
            rows = found.get("data") if isinstance(found, dict) else []
            if isinstance(rows, list) and rows:
                field_data = rows[0].get("fieldData")
                if isinstance(field_data, dict):
                    return {
                        field: field_data.get(field)
                        for field in PART_STANDARD_FIELDS
                    }
        except FileMakerAPIError:
            pass

    # Keep OData as the read-only fallback and split the selection so the
    # encoded request stays under the FileMaker/IIS URL limit.
    result: dict = {}
    dimension_fields = PART_STANDARD_FIELDS[1:]
    for start in range(0, len(dimension_fields), 6):
        fields = ("part_number", *dimension_fields[start : start + 6])
        row = await _find_one(
            odata,
            "零件",
            field="part_number",
            value=part_number,
            select=fields,
        )
        if not row:
            return {}
        result.update(row)
    return result


def _resolution(
    purchase_line: dict,
    arrivals: list[dict],
    *,
    inspection_by_arrival: dict[str, dict[str, str]],
) -> QualityScanResolution:
    purchase_line_id = _text(purchase_line.get("id"))
    nb_number = _text(purchase_line.get("內部訂單編號"))
    pt_number = _text(purchase_line.get("ID_採購單"))
    return QualityScanResolution(
        purchaseLineID=purchase_line_id,
        purchaseOrderNumber=pt_number,
        partNumber=_text(purchase_line.get("零件編號")),
        partName=_text(purchase_line.get("零件名稱")),
        supplierName=_text(purchase_line.get("廠商名稱")),
        arrivals=[
            QualityArrivalBatch(
                id=_text(row.get("ID")),
                purchaseLineID=purchase_line_id,
                arrivalDate=_text(row.get("到貨日期")),
                arrivalQuantity=_integer(row.get("到貨數量")),
                returnedQuantity=_integer(row.get("退貨數量")),
                warehousedQuantity=_integer(row.get("倉庫數量")),
                qcStatus=_qc_status(
                    row,
                    inspection_status=(
                        inspection_by_arrival.get(_text(row.get("ID")), {}).get("status")
                    ),
                ),
                nbNumber=nb_number,
                ptNumber=pt_number,
                inspectionID=(
                    inspection_by_arrival.get(_text(row.get("ID")), {}).get("id")
                ),
            )
            for row in arrivals
            if _text(row.get("ID"))
        ],
    )


def _inspection_from_record(record: dict) -> QualityInspection:
    return QualityInspection(
        id=_text(record.get("id")),
        arrivalBatchID=_text(record.get("arrivalBatchID")),
        status=_text(record.get("status")) or "检查中",
        inspectionMethod=_text(record.get("inspectionMethod")) or "抽檢",
        sampleQuantity=_integer(record.get("sampleQuantity")),
        specVersion=QualitySpecVersion.model_validate(record.get("specVersion") or {}),
        checkItems=[
            QualityCheckItem.model_validate(item)
            for item in record.get("checkItems") or []
            if isinstance(item, dict)
        ],
    )


def _inspection_id(arrival_id: str) -> str:
    value = uuid5(NAMESPACE_URL, f"starrc:pda-quality:{arrival_id}")
    return f"PDAQC-{str(value).upper()}"


async def _arrival_lock(arrival_id: str) -> asyncio.Lock:
    async with _arrival_locks_guard:
        lock = _arrival_locks.get(arrival_id)
        if lock is None:
            lock = asyncio.Lock()
            _arrival_locks[arrival_id] = lock
        return lock


def _available_quantity(row: dict) -> int:
    return max(
        _integer(row.get("到貨數量"))
        - _integer(row.get("退貨數量"))
        - _integer(row.get("倉庫數量")),
        0,
    )


def _qc_status(row: dict, *, inspection_status: str | None) -> str:
    if inspection_status:
        return inspection_status
    if _text(row.get("品檢日期")):
        return "已完成"
    arrival_status = _text(row.get("到貨狀態"))
    if "退" in arrival_status:
        return arrival_status
    return "待品检"


def _select(fields: tuple[str, ...]) -> list[str]:
    return [_field(name) for name in fields]


def _field(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _integer(value: object) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _odata_http_error(exc: FileMakerODataError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="FileMaker 品检数据访问失败，请稍后重试。",
    )

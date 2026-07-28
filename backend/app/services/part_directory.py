from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
)


PART_TABLE = "零件"
ASSET_TABLE = "PartAssets"
COST_TABLE = "成本"
PURCHASE_HISTORY_TABLE = "採購紀錄明細"
INVENTORY_TABLE = "存貨交易"
PART_PRODUCT_TABLE = "零件关联产品"
PART_PART_TABLE = "零件关联零件"
PRODUCT_TABLE = "產品"
MODIFICATION_TABLE = "修改紀錄"
DESIGN_CHANGE_TABLE = "設計修改單資料 零件連結"

PartSection = Literal["procurement", "specifications", "quality", "inventory", "records"]
PartTimeField = Literal["created", "updated", "drawing"]

PART_TIME_FIELDS: dict[PartTimeField, tuple[str, str]] = {
    "created": ("created_at", "datetime"),
    "updated": ("updated_at", "datetime"),
    "drawing": ("圖面修改日期", "date"),
}
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

PART_LIST_FIELDS = [
    "part_number",
    "part_id",
    "part_name_internal",
    "part_name_external",
    "stock_on_hand_qty",
    "safety_stock_qty",
    "part_lifecycle_status",
    "material_category",
    "part_category",
    "material_spec",
    "warehouse_location_primary",
    "warehouse_location_secondary",
    "製造商",
    "部門分工",
    "倉庫分工",
    "審核",
    "status",
    "turnover_time",
    "unit_price_twd",
    "已下單數量",
    "created_at",
    "updated_at",
    "圖面修改日期",
    "warehouse_code",
]

PART_DETAIL_FIELDS = [
    *PART_LIST_FIELDS,
    "material_properties",
    "重量",
    "材料尺寸",
    "加工類",
    "供應狀況",
    "exclusive_customer_name",
    "customer_id",
    "customer_part_number",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
    "MOQ1",
    "MOQ2",
    "MOQ3",
    "生產週期",
    "最低訂購量",
    "建議下單數量1",
    "預估剩下或欠料零件",
    "使用部門",
    "purchasing_notes",
    "圖面修改日期",
    "barcode",
    "warehouse_code",
    "詢價廠商",
    "外加工廠商",
    "實際塑膠型號",
    "估算塑膠型號",
    "統計分類",
]

ASSET_FIELDS = [
    "id_asset",
    "part_id_fk",
    "part_number_snapshot",
    "asset_type",
    "asset_role",
    "visibility",
    "title",
    "description",
    "legacy_source_field",
    "original_filename",
    "mime_type",
    "object_key",
    "file_size",
    "status",
    "sort_order",
    "is_primary",
    "updated_at",
]

SEARCH_FIELDS = (
    "part_name_internal",
    "part_name_external",
)


def odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_part_filter(
    *,
    query: str = "",
    material_category: str = "",
    part_category: str = "",
    lifecycle_status: str = "",
    audit_status: str = "",
    manufacturer: str = "",
    department: str = "",
    warehouse_division: str = "",
    warehouse_code: str = "",
    time_field: PartTimeField = "updated",
    date_from: date | None = None,
    date_to: date | None = None,
) -> str:
    clauses: list[str] = []
    normalized_query = query.strip()[:80]
    if normalized_query:
        literal = odata_literal(normalized_query)
        clauses.append(
            "("
            + " or ".join(
                [
                    f"startswith(part_number,{literal})",
                    f"startswith(part_id,{literal})",
                    *(f"contains({field},{literal})" for field in SEARCH_FIELDS),
                ]
            )
            + ")"
        )
    if material_category.strip():
        clauses.append(
            f"material_category eq {odata_literal(material_category.strip())}"
        )
    if part_category.strip():
        clauses.append(f"part_category eq {odata_literal(part_category.strip())}")
    if lifecycle_status.strip():
        clauses.append(
            f"part_lifecycle_status eq {odata_literal(lifecycle_status.strip())}"
        )
    if audit_status.strip():
        clauses.append(f"審核 eq {odata_literal(audit_status.strip())}")
    if manufacturer.strip():
        clauses.append(f"contains(製造商,{odata_literal(manufacturer.strip())})")
    if department.strip():
        clauses.append(f"部門分工 eq {odata_literal(department.strip())}")
    if warehouse_division.strip():
        clauses.append(
            f"倉庫分工 eq {odata_literal(warehouse_division.strip())}"
        )
    if warehouse_code.strip():
        clauses.append(f"warehouse_code eq {odata_literal(warehouse_code.strip())}")
    clauses.extend(
        _time_filter_clauses(
            time_field=time_field,
            date_from=date_from,
            date_to=date_to,
        )
    )
    return " and ".join(clauses)


def _time_filter_clauses(
    *,
    time_field: PartTimeField,
    date_from: date | None,
    date_to: date | None,
) -> list[str]:
    if date_from is None and date_to is None:
        return []
    field_name, field_type = PART_TIME_FIELDS[time_field]
    clauses: list[str] = []
    if field_type == "date":
        if date_from is not None:
            clauses.append(f"{field_name} ge {date_from.isoformat()}")
        if date_to is not None:
            clauses.append(f"{field_name} lt {(date_to + timedelta(days=1)).isoformat()}")
        return clauses
    if date_from is not None:
        clauses.append(
            f"{field_name} ge {_shanghai_day_boundary(date_from).isoformat().replace('+00:00', 'Z')}"
        )
    if date_to is not None:
        next_day = date_to + timedelta(days=1)
        clauses.append(
            f"{field_name} lt {_shanghai_day_boundary(next_day).isoformat().replace('+00:00', 'Z')}"
        )
    return clauses


def _shanghai_day_boundary(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=SHANGHAI_TZ).astimezone(
        timezone.utc
    )


async def list_part_directory(
    *,
    odata: FileMakerODataClient,
    storage: COSStorageService,
    query: str,
    page: int,
    page_size: int,
    material_category: str,
    part_category: str,
    lifecycle_status: str,
    audit_status: str,
    manufacturer: str,
    department: str,
    warehouse_division: str,
    warehouse_code: str,
    time_field: PartTimeField,
    date_from: date | None,
    date_to: date | None,
) -> dict[str, Any]:
    filter_expr = build_part_filter(
        query=query,
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
    filters = {
        "materialCategory": material_category.strip(),
        "partCategory": part_category.strip(),
        "lifecycleStatus": lifecycle_status.strip(),
        "auditStatus": audit_status.strip(),
        "manufacturer": manufacturer.strip(),
        "department": department.strip(),
        "warehouseDivision": warehouse_division.strip(),
        "warehouseCode": warehouse_code.strip(),
        "timeField": time_field,
        "dateFrom": date_from.isoformat() if date_from else "",
        "dateTo": date_to.isoformat() if date_to else "",
    }
    if not filter_expr:
        return {
            "rows": [],
            "foundCount": 0,
            "returnedCount": 0,
            "totalCount": None,
            "page": page,
            "pageSize": page_size,
            "totalPages": 1,
            "query": "",
            "filters": filters,
            "requiresFilter": True,
            "sourceTables": [PART_TABLE, ASSET_TABLE],
        }
    result = await odata.records(
        PART_TABLE,
        select=PART_LIST_FIELDS,
        filter_expr=filter_expr or None,
        orderby="part_number asc",
        top=page_size,
        skip=(page - 1) * page_size,
        count=True,
    )
    source_rows = _rows(result)
    asset_map = await _asset_map(
        odata=odata,
        storage=storage,
        part_ids=[_text(row.get("part_id")) for row in source_rows],
    )
    rows = [
        _part_row(row, assets=asset_map.get(_text(row.get("part_id")), []))
        for row in source_rows
    ]
    found_count = int(result.get("foundCount") or 0)
    return {
        "rows": rows,
        "foundCount": found_count,
        "returnedCount": len(rows),
        "totalCount": None,
        "page": page,
        "pageSize": page_size,
        "totalPages": max(1, (found_count + page_size - 1) // page_size),
        "query": query.strip(),
        "filters": filters,
        "requiresFilter": False,
        "sourceTables": [PART_TABLE, ASSET_TABLE],
    }


async def get_part_directory_detail(
    *,
    odata: FileMakerODataClient,
    storage: COSStorageService,
    identifier: str,
) -> dict[str, Any] | None:
    core = await _find_part(odata, identifier)
    if not core:
        return None
    assets = await _assets_for_part(
        odata=odata,
        storage=storage,
        part_id=_text(core.get("part_id")),
    )
    return {
        "part": _part_row(core, assets=assets),
        "assets": assets,
        "groups": _overview_groups(core, assets),
        "sourceTables": [PART_TABLE, ASSET_TABLE],
    }


async def get_part_directory_section(
    *,
    odata: FileMakerODataClient,
    identifier: str,
    section: PartSection,
) -> dict[str, Any] | None:
    core = await _find_part(odata, identifier)
    if not core:
        return None
    if section == "procurement":
        return await _procurement_section(odata, core)
    if section == "specifications":
        return _specifications_section(core)
    if section == "quality":
        return await _quality_section(odata, core)
    if section == "inventory":
        return await _inventory_section(odata, core)
    return await _records_section(odata, core)


async def _find_part(
    odata: FileMakerODataClient,
    identifier: str,
) -> dict[str, Any] | None:
    normalized = identifier.strip()
    if not normalized:
        return None
    literal = odata_literal(normalized)
    result = await odata.records(
        PART_TABLE,
        select=PART_DETAIL_FIELDS,
        filter_expr=f"part_id eq {literal} or part_number eq {literal}",
        top=1,
        count=False,
    )
    rows = _rows(result)
    return rows[0] if rows else None


async def _asset_map(
    *,
    odata: FileMakerODataClient,
    storage: COSStorageService,
    part_ids: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    normalized_ids = list(dict.fromkeys(item.strip() for item in part_ids if item.strip()))
    if not normalized_ids:
        return {}
    id_filter = " or ".join(
        f"part_id_fk eq {odata_literal(part_id)}" for part_id in normalized_ids
    )
    result = await _safe_records(
        odata,
        ASSET_TABLE,
        select=ASSET_FIELDS,
        filter_expr=f"({id_filter}) and status eq 'READY'",
        orderby="part_id_fk asc,is_primary desc,sort_order asc",
        top=min(100, max(20, len(normalized_ids) * 10)),
        count=False,
    )
    mapped: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(result):
        part_id = _text(row.get("part_id_fk"))
        if not part_id:
            continue
        mapped.setdefault(part_id, []).append(
            await _asset_payload(storage=storage, row=row)
        )
    return mapped


async def _assets_for_part(
    *,
    odata: FileMakerODataClient,
    storage: COSStorageService,
    part_id: str,
) -> list[dict[str, Any]]:
    return (
        await _asset_map(
            odata=odata,
            storage=storage,
            part_ids=[part_id],
        )
    ).get(part_id, [])


async def _asset_payload(
    *,
    storage: COSStorageService,
    row: dict[str, Any],
) -> dict[str, Any]:
    object_key = _text(row.get("object_key"))
    url = ""
    expires_at = ""
    if object_key and storage.configured:
        try:
            url, expiry = await run_in_threadpool(
                storage.create_presigned_download,
                object_key,
            )
            expires_at = expiry.isoformat()
        except COSStorageError:
            url = ""
    asset_type = _text(row.get("asset_type")) or "part_image"
    mime_type = _text(row.get("mime_type")) or "application/octet-stream"
    return {
        "id": _text(row.get("id_asset")),
        "partId": _text(row.get("part_id_fk")),
        "partNumber": _text(row.get("part_number_snapshot")),
        "type": asset_type,
        "category": _asset_category(asset_type, mime_type),
        "role": _text(row.get("asset_role")) or "reference",
        "visibility": _text(row.get("visibility")),
        "title": (
            _text(row.get("title"))
            or _asset_title(asset_type, _text(row.get("legacy_source_field")))
        ),
        "description": _text(row.get("description")),
        "filename": _text(row.get("original_filename")),
        "mimeType": mime_type,
        "fileSize": _number(row.get("file_size")),
        "objectKey": object_key,
        "url": url,
        "urlExpiresAt": expires_at,
        "isPrimary": _truthy(row.get("is_primary")),
        "sortOrder": int(_number(row.get("sort_order")) or 0),
        "updatedAt": _text(row.get("updated_at")),
        "source": "cos",
    }


def _part_row(
    row: dict[str, Any],
    *,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    photos = [item for item in assets if item["category"] == "photo"]
    drawings = [item for item in assets if item["category"] == "drawing"]
    thumbnail = next(
        (
            item
            for item in photos
            if item["url"] and item["mimeType"].startswith("image/") and item["isPrimary"]
        ),
        None,
    ) or next(
        (
            item
            for item in photos
            if item["url"] and item["mimeType"].startswith("image/")
        ),
        None,
    )
    return {
        "id": _text(row.get("part_id")) or _text(row.get("part_number")),
        "partId": _text(row.get("part_id")),
        "partNumber": _text(row.get("part_number")),
        "nameInternal": _text(row.get("part_name_internal")),
        "nameExternal": _text(row.get("part_name_external")),
        "lifecycleStatus": _text(row.get("part_lifecycle_status")),
        "materialCategory": _text(row.get("material_category")),
        "partCategory": _text(row.get("part_category")),
        "materialSpec": _text(row.get("material_spec")),
        "materialProperties": _text(row.get("material_properties")),
        "stock": _number(row.get("stock_on_hand_qty")) or 0,
        "safetyStock": _number(row.get("safety_stock_qty")) or 0,
        "orderedQuantity": _number(row.get("已下單數量")) or 0,
        "turnoverDays": _number(row.get("turnover_time")),
        "unitPriceTwd": _number(row.get("unit_price_twd")),
        "manufacturer": _text(row.get("製造商")),
        "department": _text(row.get("部門分工")),
        "warehouseDivision": _text(row.get("倉庫分工")),
        "warehouseCode": _text(row.get("warehouse_code")),
        "locationPrimary": _text(row.get("warehouse_location_primary")),
        "locationSecondary": _text(row.get("warehouse_location_secondary")),
        "auditStatus": _text(row.get("審核")),
        "status": _text(row.get("status")),
        "updatedAt": _text(row.get("updated_at")),
        "assetCount": len(assets),
        "photoCount": len(photos),
        "drawingCount": len(drawings),
        "thumbnailUrl": thumbnail["url"] if thumbnail else "",
    }


def _overview_groups(
    core: dict[str, Any],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        _group(
            "基础资料",
            "零件主表的核心识别与分类字段",
            [
                _field("零件编号", core.get("part_number")),
                _field("系统 ID", core.get("part_id"), note="关系主键"),
                _field("内部名称", core.get("part_name_internal")),
                _field("对外名称", core.get("part_name_external")),
                _field("材料分类", core.get("material_category")),
                _field("零件品种", core.get("part_category")),
                _field("材料属性", core.get("material_properties")),
                _field("专属客户", core.get("exclusive_customer_name")),
            ],
        ),
        _group(
            "库存与位置",
            "零件主表中的实时库存摘要",
            [
                _field(
                    "当前库存",
                    _quantity(core.get("stock_on_hand_qty")),
                    accent=_stock_accent(core),
                ),
                _field("安全库存", _quantity(core.get("safety_stock_qty"))),
                _field("已下单数量", _quantity(core.get("已下單數量"))),
                _field("主要仓位", core.get("warehouse_location_primary")),
                _field("次要仓位", core.get("warehouse_location_secondary")),
                _field("仓库", core.get("warehouse_code")),
                _field("库存周转", _days(core.get("turnover_time"))),
                _field("COS 资产", f"{len(assets)} 个文件"),
            ],
        ),
        _group(
            "责任与状态",
            "采购、仓库与审核状态",
            [
                _field("生命周期", core.get("part_lifecycle_status")),
                _field("供应状况", core.get("供應狀況")),
                _field("审核状态", core.get("審核")),
                _field("制造商", core.get("製造商")),
                _field("部门分工", core.get("部門分工")),
                _field("仓库分工", core.get("倉庫分工")),
                _field("创建日期", core.get("created_at")),
                _field("最后修改", core.get("updated_at")),
            ],
        ),
    ]


async def _procurement_section(
    odata: FileMakerODataClient,
    core: dict[str, Any],
) -> dict[str, Any]:
    part_number = _text(core.get("part_number"))
    part_id = _text(core.get("part_id"))
    identity_filter = _identity_filter(
        "零件 ID 相符欄位",
        part_number=part_number,
        part_id=part_id,
    )
    cost_result, history_result = await asyncio.gather(
        _safe_records(
            odata,
            COST_TABLE,
            select=[
                "單位成本",
                "ID_零件",
                "存貨值",
                "第二廠商報價",
                "第三廠商報價",
                "詢價廠商",
                "詢價價格",
                "台幣成本單價",
                "模具成本",
                "實際成本",
                "內部估價",
                "規格書修改人",
                "規格書修改日期",
                "updated_at",
                "updated_by",
            ],
            filter_expr=f"ID_零件 eq {odata_literal(part_number)}",
            top=1,
            count=False,
        ),
        _safe_records(
            odata,
            PURCHASE_HISTORY_TABLE,
            select=["零件 ID 相符欄位", "日期", "紀錄明細", "紀錄帳戶"],
            filter_expr=identity_filter,
            orderby="日期 desc",
            top=20,
            count=False,
        ),
    )
    cost = _first_row(cost_result)
    history = _rows(history_result)
    return {
        "section": "procurement",
        "groups": [
            _group(
                "主要供应商",
                "零件主表中的供应与交付条件",
                [
                    _field("制造商", core.get("製造商")),
                    _field("询价厂商", core.get("詢價廠商")),
                    _field("外加工厂商", core.get("外加工廠商")),
                    _field("最新台币单价", _money(core.get("unit_price_twd"), "TWD")),
                    _field("最低订购量", _quantity(core.get("最低訂購量"))),
                    _field("生产周期", _days(core.get("生產週期"))),
                    _field("最近核价", cost.get("updated_at")),
                    _field("采购备注", core.get("purchasing_notes")),
                ],
            ),
            _group(
                "比价与成本",
                "成本表按零件编号独立读取",
                [
                    _field("单位成本", _money(cost.get("單位成本"))),
                    _field("询价价格", _money(cost.get("詢價價格"))),
                    _field("第二厂商报价", _money(cost.get("第二廠商報價"))),
                    _field("第三厂商报价", _money(cost.get("第三廠商報價"))),
                    _field("台币成本单价", _money(cost.get("台幣成本單價"), "TWD")),
                    _field("实际成本", _money(cost.get("實際成本"))),
                    _field("内部估价", _money(cost.get("內部估價"))),
                    _field("存货值", _money(cost.get("存貨值"))),
                ],
            ),
            _group(
                "采购策略",
                "主表中的补货参数",
                [
                    _field("建议下单数量", core.get("建議下單數量1")),
                    _field("已下单数量", _quantity(core.get("已下單數量"))),
                    _field("预估余量 / 欠料", core.get("預估剩下或欠料零件")),
                    _field("MOQ 1", core.get("MOQ1")),
                    _field("MOQ 2", core.get("MOQ2")),
                    _field("MOQ 3", core.get("MOQ3")),
                    _field("库存周转", _days(core.get("turnover_time"))),
                    _field("成本更新人", cost.get("updated_by")),
                ],
            ),
        ],
        "recordGroups": [
            {
                "title": "采购记录",
                "description": "採購紀錄明細表",
                "items": [
                    {
                        "id": f"purchase-{index}",
                        "title": _text(item.get("紀錄明細")) or "采购记录",
                        "subtitle": _text(item.get("紀錄帳戶")),
                        "meta": _text(item.get("日期")),
                        "status": "",
                    }
                    for index, item in enumerate(history)
                ],
            }
        ],
        "sourceTables": [PART_TABLE, COST_TABLE, PURCHASE_HISTORY_TABLE],
    }


def _specifications_section(core: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": "specifications",
        "groups": [
            _group(
                "零件规格",
                "只选择零件主表中的规格字段",
                [
                    _field("材料分类", core.get("material_category")),
                    _field("材料规格", core.get("material_spec")),
                    _field("材料属性", core.get("material_properties")),
                    _field("材料尺寸", core.get("材料尺寸")),
                    _field("重量", _grams(core.get("重量"))),
                    _field("实际塑胶型号", core.get("實際塑膠型號")),
                    _field("估算塑胶型号", core.get("估算塑膠型號")),
                    _field("加工分类", core.get("加工類")),
                ],
            ),
            _group(
                "仓储与使用",
                "仓库、位置和使用部门",
                [
                    _field("仓库", core.get("warehouse_code")),
                    _field("主要位置", core.get("warehouse_location_primary")),
                    _field("次要位置", core.get("warehouse_location_secondary")),
                    _field("仓库分工", core.get("倉庫分工")),
                    _field("部门分工", core.get("部門分工")),
                    _field("使用部门", core.get("使用部門")),
                    _field("统计分类", core.get("統計分類")),
                    _field("客户零件号", core.get("customer_part_number")),
                ],
            ),
            _group(
                "标识与追踪",
                "条码保留在零件主表",
                [
                    _field("条码", core.get("barcode")),
                    _field("系统 ID", core.get("part_id")),
                    _field("客户 ID", core.get("customer_id")),
                    _field("专属客户", core.get("exclusive_customer_name")),
                    _field("创建人", core.get("created_by")),
                    _field("创建时间", core.get("created_at")),
                    _field("修改人", core.get("updated_by")),
                    _field("修改时间", core.get("updated_at")),
                ],
            ),
        ],
        "recordGroups": [],
        "sourceTables": [PART_TABLE],
    }


async def _quality_section(
    odata: FileMakerODataClient,
    core: dict[str, Any],
) -> dict[str, Any]:
    part_number = _text(core.get("part_number"))
    part_id = _text(core.get("part_id"))
    modification_filter = " or ".join(
        [
            f"零件編號 eq {odata_literal(part_number)}",
            f"零件 ID 相符欄位 eq {odata_literal(part_number)}",
            f"零件 ID 相符欄位 eq {odata_literal(part_id)}",
            f"ID_零件 eq {odata_literal(part_id)}",
        ]
    )
    design_filter = " or ".join(
        [
            f"修改零件 eq {odata_literal(part_number)}",
            f"ID_零件 eq {odata_literal(part_id)}",
        ]
    )
    modification_result, design_result = await asyncio.gather(
        _safe_records(
            odata,
            MODIFICATION_TABLE,
            select=[
                "零件編號",
                "零件品名",
                "審核",
                "零件修改主旨1",
                "零件修改內容1",
                "零件修改主旨2",
                "零件修改內容2",
                "零件修改時間",
                *[f"零件加工流程{index}名稱" for index in range(1, 11)],
            ],
            filter_expr=modification_filter,
            orderby="零件修改時間 desc",
            top=20,
            count=False,
        ),
        _safe_records(
            odata,
            DESIGN_CHANGE_TABLE,
            select=[
                "修改單 ID 相符欄",
                "修改內容",
                "留言時間",
                "部門",
                "修改零件",
                "修改零件名稱",
                "修改時間",
                "修改主旨",
            ],
            filter_expr=design_filter,
            orderby="修改時間 desc",
            top=20,
            count=False,
        ),
    )
    modifications = _rows(modification_result)
    design_changes = _rows(design_result)
    latest = modifications[0] if modifications else {}
    process_fields = [
        _field(f"{index:02d}", latest.get(f"零件加工流程{index}名稱"))
        for index in range(1, 11)
        if _text(latest.get(f"零件加工流程{index}名稱"))
    ] or [_field("生产流程", None)]
    return {
        "section": "quality",
        "groups": [
            _group(
                "图面与审核",
                "零件主表与修改记录的受控状态",
                [
                    _field("图面修改日期", core.get("圖面修改日期")),
                    _field("审核状态", core.get("審核")),
                    _field("生命周期", core.get("part_lifecycle_status")),
                    _field("状态", core.get("status")),
                    _field("最近修改时间", latest.get("零件修改時間")),
                    _field(
                        "最近修改主题",
                        latest.get("零件修改主旨1") or latest.get("零件修改主旨2"),
                    ),
                    _field(
                        "最近修改内容",
                        latest.get("零件修改內容1") or latest.get("零件修改內容2"),
                    ),
                    _field("修改记录审核", latest.get("審核")),
                ],
            ),
            _group("生产流程", "修改紀錄表中的工序名称", process_fields),
        ],
        "recordGroups": [
            {
                "title": "设计修改记录",
                "description": "設計修改單資料 零件連結",
                "items": [
                    {
                        "id": f"design-{index}",
                        "title": _text(item.get("修改主旨")) or "设计修改",
                        "subtitle": _text(item.get("修改內容")),
                        "meta": " · ".join(
                            value
                            for value in (
                                _text(item.get("修改時間")),
                                _text(item.get("部門")),
                                _text(item.get("修改單 ID 相符欄")),
                            )
                            if value
                        ),
                        "status": "",
                    }
                    for index, item in enumerate(design_changes)
                ],
            }
        ],
        "sourceTables": [PART_TABLE, MODIFICATION_TABLE, DESIGN_CHANGE_TABLE],
    }


async def _inventory_section(
    odata: FileMakerODataClient,
    core: dict[str, Any],
) -> dict[str, Any]:
    part_number = _text(core.get("part_number"))
    part_id = _text(core.get("part_id"))
    inventory_result = await _safe_records(
        odata,
        INVENTORY_TABLE,
        select=[
            "零件 ID 相符欄位",
            "日期",
            "描述",
            "入庫數量",
            "出庫數量",
            "批號",
            "供貨廠商",
            "內部編號",
            "交易時間",
            "修改人",
        ],
        filter_expr=_identity_filter(
            "零件 ID 相符欄位",
            part_number=part_number,
            part_id=part_id,
        ),
        orderby="交易時間 desc",
        top=20,
        count=False,
    )
    return {
        "section": "inventory",
        "groups": [],
        "recordGroups": [
            {
                "title": "最近库存交易",
                "description": "存貨交易表（最近 20 条）",
                "items": [
                    {
                        "id": f"inventory-{index}",
                        "title": (
                            _text(item.get("描述"))
                            or _text(item.get("內部編號"))
                            or "库存交易"
                        ),
                        "subtitle": " · ".join(
                            value
                            for value in (
                                f"入库 {_quantity(item.get('入庫數量'))}"
                                if item.get("入庫數量") not in (None, "")
                                else "",
                                f"出库 {_quantity(item.get('出庫數量'))}"
                                if item.get("出庫數量") not in (None, "")
                                else "",
                                _text(item.get("供貨廠商")),
                            )
                            if value
                        ),
                        "meta": _text(item.get("交易時間"))
                        or _text(item.get("日期")),
                        "status": _text(item.get("批號")),
                    }
                    for index, item in enumerate(_rows(inventory_result))
                ],
            },
        ],
        "sourceTables": [INVENTORY_TABLE],
    }


async def _records_section(
    odata: FileMakerODataClient,
    core: dict[str, Any],
) -> dict[str, Any]:
    part_number = _text(core.get("part_number"))
    part_id = _text(core.get("part_id"))
    product_links_result, part_links_result = await asyncio.gather(
        _safe_records(
            odata,
            PART_PRODUCT_TABLE,
            select=["ID", "ID_零件", "ID_产品", "修改时间戳", "修改人"],
            filter_expr=f"ID_零件 eq {odata_literal(part_number)}",
            orderby="修改时间戳 desc",
            top=20,
            count=False,
        ),
        _safe_records(
            odata,
            PART_PART_TABLE,
            select=["ID", "ID_零件", "ID_關聯零件", "修改时间戳", "修改人"],
            filter_expr=f"ID_零件 eq {odata_literal(part_number)}",
            orderby="修改时间戳 desc",
            top=20,
            count=False,
        ),
    )
    product_ids = list(
        dict.fromkeys(
            _text(row.get("ID_产品"))
            for row in _rows(product_links_result)
            if _text(row.get("ID_产品"))
        )
    )
    related_part_ids = list(
        dict.fromkeys(
            _text(row.get("ID_關聯零件"))
            for row in _rows(part_links_result)
            if _text(row.get("ID_關聯零件"))
        )
    )
    product_result, related_part_result = await asyncio.gather(
        _safe_records(
            odata,
            PRODUCT_TABLE,
            select=[
                "product_sku",
                "系統產品編號",
                "product_name",
                "產品名稱_中文",
                "stock",
            ],
            filter_expr=_or_filter(("product_sku", "系統產品編號"), product_ids),
            top=max(1, len(product_ids)),
            count=False,
        )
        if product_ids
        else _empty_result(PRODUCT_TABLE),
        _safe_records(
            odata,
            PART_TABLE,
            select=[
                "part_number",
                "part_id",
                "part_name_internal",
                "stock_on_hand_qty",
            ],
            filter_expr=_or_filter(("part_number",), related_part_ids),
            top=max(1, len(related_part_ids)),
            count=False,
        )
        if related_part_ids
        else _empty_result(PART_TABLE),
    )
    products_by_id: dict[str, dict[str, Any]] = {}
    for row in _rows(product_result):
        for key in ("product_sku", "系統產品編號"):
            value = _text(row.get(key))
            if value:
                products_by_id[value] = row
    parts_by_number = {
        _text(row.get("part_number")): row
        for row in _rows(related_part_result)
        if _text(row.get("part_number"))
    }
    return {
        "section": "records",
        "groups": [],
        "recordGroups": [
            {
                "title": "关联产品",
                "description": "零件关联产品 → 產品",
                "items": [
                    {
                        "id": f"product-{product_id}",
                        "title": product_id,
                        "subtitle": (
                            _text(products_by_id.get(product_id, {}).get("product_name"))
                            or _text(
                                products_by_id.get(product_id, {}).get("產品名稱_中文")
                            )
                        ),
                        "meta": _quantity(
                            products_by_id.get(product_id, {}).get("stock")
                        ),
                        "status": "",
                    }
                    for product_id in product_ids
                ],
            },
            {
                "title": "关联零件",
                "description": "零件关联零件 → 零件",
                "items": [
                    {
                        "id": f"part-{related_id}",
                        "title": related_id,
                        "subtitle": _text(
                            parts_by_number.get(related_id, {}).get("part_name_internal")
                        ),
                        "meta": _quantity(
                            parts_by_number.get(related_id, {}).get("stock_on_hand_qty")
                        ),
                        "status": "",
                    }
                    for related_id in related_part_ids
                ],
            },
        ],
        "sourceTables": [
            PART_PRODUCT_TABLE,
            PRODUCT_TABLE,
            PART_PART_TABLE,
            PART_TABLE,
        ],
    }


async def _safe_records(
    odata: FileMakerODataClient,
    table: str,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        return await odata.records(table, **kwargs)
    except FileMakerODataError as exc:
        return {
            "table": table,
            "rows": [],
            "foundCount": 0,
            "returnedCount": 0,
            "warning": str(exc),
        }


async def _empty_result(table: str) -> dict[str, Any]:
    return {"table": table, "rows": [], "foundCount": 0, "returnedCount": 0}


def _identity_filter(
    field: str,
    *,
    part_number: str,
    part_id: str,
) -> str:
    values = list(dict.fromkeys(value for value in (part_number, part_id) if value))
    return " or ".join(f"{field} eq {odata_literal(value)}" for value in values)


def _or_filter(fields: Iterable[str], values: Iterable[str]) -> str:
    return " or ".join(
        f"{field} eq {odata_literal(value)}"
        for value in values
        for field in fields
    )


def _group(
    title: str,
    description: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    return {"title": title, "description": description, "fields": fields}


def _field(
    label: str,
    value: Any,
    *,
    note: str = "",
    accent: str = "",
) -> dict[str, Any]:
    return {
        "label": label,
        "value": _display(value),
        "note": note,
        "accent": accent,
    }


def _display(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return str(value).strip() or "—"


def _quantity(value: Any, unit: str = "") -> str:
    number = _number(value)
    if number is None:
        return "—"
    formatted = f"{number:,.2f}".rstrip("0").rstrip(".")
    return f"{formatted} {unit}".strip()


def _money(value: Any, currency: str = "CNY") -> str:
    number = _number(value)
    if number is None:
        return "—"
    symbol = "¥" if currency in {"CNY", "TWD"} else currency
    suffix = " TWD" if currency == "TWD" else ""
    return f"{symbol} {number:,.2f}{suffix}"


def _days(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:,.0f} 天"


def _grams(value: Any) -> str:
    number = _number(value)
    return (
        "—"
        if number is None
        else f"{number:,.2f}".rstrip("0").rstrip(".") + " g"
    )


def _stock_accent(core: dict[str, Any]) -> str:
    stock = _number(core.get("stock_on_hand_qty")) or 0
    safety = _number(core.get("safety_stock_qty")) or 0
    if safety > 0 and stock < safety:
        return "warning"
    return "positive" if stock > 0 else "muted"


def _asset_category(asset_type: str, mime_type: str) -> str:
    normalized = asset_type.casefold()
    if "drawing" in normalized or mime_type == "application/pdf":
        return "drawing"
    if "package" in normalized:
        return "package"
    if any(value in normalized for value in ("process", "sample", "laser", "cad", "qc")):
        return "process"
    return "photo"


def _asset_title(asset_type: str, legacy_field: str) -> str:
    if legacy_field:
        return legacy_field
    return {
        "part_image": "零件照片",
        "drawing_2d": "工程图面",
        "sample_image": "打样资料",
        "process_file": "工艺文件",
        "package_image": "包装资料",
    }.get(asset_type, "零件资产")


def _truthy(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows")
    return (
        [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )


def _first_row(result: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(result)
    return rows[0] if rows else {}

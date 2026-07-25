from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.models.inventory import (
    InventorySummary,
    InventoryTransactionRow,
    InventoryTrendPoint,
    ProductInventoryResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import get_audit_log_store, get_filemaker_client, get_operator_context
from app.services.filemaker_client import FileMakerClient
from app.services.product_api import PRODUCT_LAYOUT, PRODUCT_STOCK_FIELD

router = APIRouter(prefix="/products", tags=["inventory"])

INVENTORY_LAYOUT = "產品庫存_TRANSACTION"
INVENTORY_PRODUCT_FIELD = "ID_產品編號"


@router.get("/{product_sku}/inventory-transactions", response_model=ProductInventoryResponse)
async def get_product_inventory(
    product_sku: str,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> ProductInventoryResponse:
    sku = product_sku.strip()
    inventory_result, product_result = await asyncio.gather(
        filemaker.find_records(
            INVENTORY_LAYOUT,
            query={INVENTORY_PRODUCT_FIELD: f"=={sku}"},
            limit=500,
            offset=1,
        ),
        filemaker.find_records(
            PRODUCT_LAYOUT,
            query={"product_sku": f"=={sku}"},
            limit=1,
            offset=1,
        ),
    )
    response = build_inventory_response(sku, inventory_result, product_result)
    await audit_log.record(
        operator=operator,
        action_type="READ_PRODUCT_INVENTORY",
        status="success",
        target_layout=INVENTORY_LAYOUT,
        product_sku=sku or None,
        request_payload={"productSku": sku, "limit": 500},
        response_payload={
            "foundCount": response.found_count,
            "returnedCount": response.returned_count,
            "currentStock": response.summary.current_stock,
        },
    )
    return response


def build_inventory_response(
    product_sku: str,
    inventory_result: dict[str, Any],
    product_result: dict[str, Any],
) -> ProductInventoryResponse:
    source_rows = inventory_result.get("data") or []
    chronological = sorted(
        (record for record in source_rows if isinstance(record, dict)),
        key=_transaction_sort_key,
    )
    inbound_total = sum(_number(_fields(record).get("入庫數量")) for record in chronological)
    outbound_total = sum(_number(_fields(record).get("出庫數量")) for record in chronological)
    net_change = inbound_total - outbound_total
    current_stock = _current_stock(product_result, fallback=net_change)
    opening_balance = current_stock - net_change
    balance = opening_balance
    trend: list[InventoryTrendPoint] = []
    rows: list[InventoryTransactionRow] = []

    for record in chronological:
        values = _fields(record)
        inbound_qty = _number(values.get("入庫數量"))
        outbound_qty = _number(values.get("出庫數量"))
        signed_qty = inbound_qty - outbound_qty
        balance += signed_qty
        date = _iso_date(values.get("日期"))
        movement_type = "in" if signed_qty >= 0 else "out"
        rows.append(
            InventoryTransactionRow(
                recordId=str(record.get("recordId") or ""),
                date=date,
                year=_year(date),
                type=movement_type,
                orderBatchNo=_first_text(
                    values,
                    "批號",
                    "ID_出貨單資料",
                    "ID_出貨單資料入庫",
                    "ID_出貨單資料出庫",
                ),
                description=_text(values.get("描述")),
                inboundQty=inbound_qty,
                outboundQty=outbound_qty,
                signedQty=signed_qty,
                balance=balance,
                operator=_first_text(values, "記錄人", "紀錄人", "操作員"),
            )
        )
        trend.append(InventoryTrendPoint(date=date, balance=balance))

    rows.reverse()
    return ProductInventoryResponse(
        productSku=product_sku,
        layout=INVENTORY_LAYOUT,
        rows=rows,
        trend=trend,
        summary=InventorySummary(
            currentStock=current_stock,
            inboundTotal=inbound_total,
            outboundTotal=outbound_total,
            netChange=net_change,
        ),
        foundCount=int(inventory_result.get("foundCount") or len(rows)),
        returnedCount=int(inventory_result.get("returnedCount") or len(rows)),
        readOnly=True,
    )


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    values = record.get("fieldData")
    return values if isinstance(values, dict) else {}


def _current_stock(product_result: dict[str, Any], *, fallback: float) -> float:
    products = product_result.get("data") or []
    if not products or not isinstance(products[0], dict):
        return fallback
    value = _fields(products[0]).get(PRODUCT_STOCK_FIELD)
    return _number(value) if value not in (None, "") else fallback


def _transaction_sort_key(record: dict[str, Any]) -> tuple[datetime, int, str]:
    values = _fields(record)
    date = _parse_date(values.get("日期")) or datetime.min
    record_id = str(record.get("recordId") or "")
    try:
        numeric_record_id = int(record_id)
    except ValueError:
        numeric_record_id = 0
    return date, numeric_record_id, record_id


def _parse_date(value: Any) -> datetime | None:
    text = _text(value)
    for date_format in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def _iso_date(value: Any) -> str:
    parsed = _parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else _text(value)


def _year(value: str) -> int:
    try:
        return int(value[:4])
    except (TypeError, ValueError):
        return 0


def _number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _first_text(values: dict[str, Any], *names: str) -> str:
    for name in names:
        value = _text(values.get(name))
        if value:
            return value
    return ""

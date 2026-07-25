import asyncio
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient


class InternalOrderMergeError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


_merge_lock = asyncio.Lock()


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    return data if isinstance(data, list) else []


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData")
    return fields if isinstance(fields, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any) -> Decimal:
    normalized = _text(value).replace(",", "")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise InternalOrderMergeError(f"订单明细数量无效：{value!s}", status_code=422) from exc


def _filemaker_number(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


async def _find_by_values(
    client: FileMakerClient,
    *,
    layout: str,
    field: str,
    values: list[str],
    limit: int,
) -> dict[str, Any]:
    if not values:
        return {"data": [], "foundCount": 0, "returnedCount": 0}
    return await client.find_records(
        layout,
        query=[{field: f"=={value}"} for value in values],
        limit=limit,
    )


def _now(settings: Settings) -> datetime:
    try:
        timezone = ZoneInfo(settings.natural_query_timezone)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    return datetime.now(timezone)


def _now_for_filemaker(settings: Settings) -> str:
    return _now(settings).strftime(settings.filemaker_web_merge_date_format)


def _merge_log_text(
    *,
    settings: Settings,
    request_id: str,
    customer_id: str,
    customer_name: str,
    operator_account: str,
    operator_name: str,
    new_order_id: str,
    new_internal_order_no: str,
    source_internal_order_nos: list[str],
    source_item_count: int,
    merged_items: list[dict[str, str]],
) -> str:
    operator_label = operator_name.strip() or operator_account.strip() or "WebViewer 用户"
    if operator_account.strip() and operator_account.strip() != operator_label:
        operator_label = f"{operator_label} ({operator_account.strip()})"
    detail_lines = [
        "{}. {} | {} | 数量 {}".format(
            index,
            item.get("productNo") or "未填写产品编号",
            item.get("productName") or "未填写产品名称",
            item.get("quantity") or "0",
        )
        for index, item in enumerate(merged_items, start=1)
    ]
    return "\n".join(
        [
            "[Web Data API 内部订单合并]",
            f"时间：{_now(settings).strftime('%Y-%m-%d %H:%M:%S')}",
            f"操作人：{operator_label}",
            f"客户：{customer_name or '未填写客户名称'} ({customer_id})",
            f"新内部订单：{new_internal_order_no}",
            f"内部业务ID：{new_order_id}",
            f"来源内部订单：{'、'.join(source_internal_order_nos)}",
            (
                f"来源订单数：{len(source_internal_order_nos)}；"
                f"原始明细数：{source_item_count}；合并后明细数：{len(merged_items)}"
            ),
            "合并出货明细：",
            *detail_lines,
            f"请求ID：{request_id}",
        ]
    )


async def _rollback_created_records(
    client: FileMakerClient,
    settings: Settings,
    *,
    header_record_id: str,
    detail_record_ids: list[str],
) -> list[str]:
    errors: list[str] = []
    for record_id in reversed(detail_record_ids):
        try:
            await client.delete_record(settings.filemaker_web_merge_item_layout, record_id)
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"明细 {record_id}: {exc}")
    if header_record_id:
        try:
            await client.delete_record(settings.filemaker_web_merge_order_create_layout, header_record_id)
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"订单 {header_record_id}: {exc}")
    return errors


async def _prepare_internal_order_merge(
    *,
    client: FileMakerClient,
    settings: Settings,
    customer_id: str,
    order_ids: list[str],
) -> dict[str, Any]:
    normalized_order_ids = list(dict.fromkeys(_text(order_id) for order_id in order_ids if _text(order_id)))
    if len(normalized_order_ids) < 2:
        raise InternalOrderMergeError("至少选择两张订单才能合并", status_code=422)
    if len(normalized_order_ids) > settings.filemaker_web_merge_max_orders:
        raise InternalOrderMergeError(
            f"一次最多合并 {settings.filemaker_web_merge_max_orders} 张订单",
            status_code=422,
        )
    if not customer_id:
        raise InternalOrderMergeError("WebViewer 缺少当前客户 ID，不能执行 Web 合并", status_code=400)

    source_orders = await _find_by_values(
        client,
        layout=settings.filemaker_web_merge_order_layout,
        field=settings.filemaker_web_merge_order_id_field,
        values=normalized_order_ids,
        limit=settings.filemaker_web_merge_max_orders + 1,
    )
    source_records = _records(source_orders)
    source_by_id = {
        _text(_fields(record).get(settings.filemaker_web_merge_order_id_field)): record
        for record in source_records
    }
    missing_order_ids = [order_id for order_id in normalized_order_ids if order_id not in source_by_id]
    if missing_order_ids:
        raise InternalOrderMergeError(
            "部分订单不存在或 Data API 布局不可见",
            status_code=404,
            details={"orderIds": missing_order_ids},
        )

    mismatched_order_ids = [
        order_id
        for order_id, record in source_by_id.items()
        if _text(_fields(record).get(settings.filemaker_web_merge_customer_id_field)) != customer_id
    ]
    if mismatched_order_ids:
        raise InternalOrderMergeError(
            "所选订单不全部属于当前客户，已拒绝合并",
            status_code=403,
            details={"orderIds": mismatched_order_ids},
        )

    source_internal_order_nos = [
        _text(
            _fields(source_by_id[order_id]).get(
                settings.filemaker_web_merge_internal_order_no_field
            )
        )
        for order_id in normalized_order_ids
    ]
    invalid_internal_numbers = [
        normalized_order_ids[index]
        for index, number in enumerate(source_internal_order_nos)
        if not number.upper().startswith("NB")
    ]
    if invalid_internal_numbers:
        raise InternalOrderMergeError(
            "部分来源订单缺少 NB 内部订单编号，不能生成合并追溯日志",
            status_code=422,
            details={"orderIds": invalid_internal_numbers},
        )

    source_items = await _find_by_values(
        client,
        layout=settings.filemaker_web_merge_item_layout,
        field=settings.filemaker_web_merge_item_order_id_field,
        values=normalized_order_ids,
        limit=settings.filemaker_web_merge_max_items + 1,
    )
    if int(source_items.get("foundCount") or 0) > settings.filemaker_web_merge_max_items:
        raise InternalOrderMergeError(
            f"所选订单明细超过 {settings.filemaker_web_merge_max_items} 条安全上限",
            status_code=422,
        )
    item_records = _records(source_items)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    product_names: dict[str, str] = {}
    for record in item_records:
        fields = _fields(record)
        product_no = _text(fields.get(settings.filemaker_web_merge_item_product_field))
        if not product_no:
            raise InternalOrderMergeError("订单明细缺少产品编号，不能安全合并", status_code=422)
        totals[product_no] += _decimal(fields.get(settings.filemaker_web_merge_item_quantity_field))
        product_name = (
            _text(fields.get("product_name"))
            or _text(fields.get("中文產品名稱"))
            or _text(fields.get("中文名稱"))
            or _text(fields.get("產品名稱"))
        )
        if product_name and not product_names.get(product_no):
            product_names[product_no] = product_name
    if not totals:
        raise InternalOrderMergeError("所选订单没有可合并的产品明细", status_code=422)

    products = await _find_by_values(
        client,
        layout=settings.filemaker_web_merge_product_layout,
        field=settings.filemaker_web_merge_product_sku_field,
        values=sorted(totals),
        limit=len(totals) + 1,
    )
    for record in _records(products):
        fields = _fields(record)
        product_no = _text(fields.get(settings.filemaker_web_merge_product_sku_field))
        product_name = _text(fields.get(settings.filemaker_web_merge_product_name_field))
        if product_no and product_name:
            product_names[product_no] = product_name

    merged_items = [
        {
            "productNo": product_no,
            "productName": product_names.get(product_no, ""),
            "quantity": _filemaker_number(totals[product_no]),
        }
        for product_no in sorted(totals)
    ]
    return {
        "orderIds": normalized_order_ids,
        "sourceInternalOrderNos": source_internal_order_nos,
        "itemRecords": item_records,
        "totals": totals,
        "mergedItems": merged_items,
    }


async def preview_internal_orders_via_data_api(
    *,
    client: FileMakerClient,
    settings: Settings,
    customer_id: str,
    order_ids: list[str],
) -> dict[str, Any]:
    prepared = await _prepare_internal_order_merge(
        client=client,
        settings=settings,
        customer_id=customer_id,
        order_ids=order_ids,
    )
    return {
        "ok": True,
        "sourceOrderCount": len(prepared["orderIds"]),
        "sourceItemCount": len(prepared["itemRecords"]),
        "mergedItemCount": len(prepared["totals"]),
        "items": prepared["mergedItems"],
    }


async def merge_internal_orders_via_data_api(
    *,
    client: FileMakerClient,
    settings: Settings,
    customer_id: str,
    customer_name: str,
    order_ids: list[str],
    request_id: str,
    operator_account: str = "",
    operator_name: str = "",
) -> dict[str, Any]:
    async with _merge_lock:
        prepared = await _prepare_internal_order_merge(
            client=client,
            settings=settings,
            customer_id=customer_id,
            order_ids=order_ids,
        )
        normalized_order_ids: list[str] = prepared["orderIds"]
        item_records: list[dict[str, Any]] = prepared["itemRecords"]
        totals: dict[str, Decimal] = prepared["totals"]

        header_identity_data = {settings.filemaker_web_merge_customer_id_field: customer_id}
        header_create_data: dict[str, str] = {}
        date_field = settings.filemaker_web_merge_order_date_field.strip()
        if date_field:
            header_create_data[date_field] = _now_for_filemaker(settings)
        order_type_field = settings.filemaker_web_merge_order_type_field.strip()
        if order_type_field:
            header_create_data[order_type_field] = settings.filemaker_web_merge_order_type_value
        order_category_field = settings.filemaker_web_merge_order_category_field.strip()
        if order_category_field:
            header_create_data[order_category_field] = settings.filemaker_web_merge_order_category_value

        header_record_id = ""
        detail_record_ids: list[str] = []
        try:
            header_result = await client.create_record(
                settings.filemaker_web_merge_order_create_layout,
                header_create_data,
            )
            header_record_id = _text(header_result.get("recordId"))
            if not header_record_id:
                raise FileMakerAPIError("Data API 创建订单后未返回 recordId")

            await client.update_record(
                settings.filemaker_web_merge_order_layout,
                header_record_id,
                header_identity_data,
            )

            created_header = await client.get_record(
                settings.filemaker_web_merge_order_layout,
                header_record_id,
            )
            created_records = created_header if isinstance(created_header, list) else []
            created_fields = _fields(created_records[0]) if created_records else {}
            new_order_id = _text(created_fields.get(settings.filemaker_web_merge_order_id_field))
            if not new_order_id:
                raise FileMakerAPIError("新订单没有生成业务订单 ID")
            new_internal_order_no = _text(
                created_fields.get(settings.filemaker_web_merge_internal_order_no_field)
            )
            if not new_internal_order_no.upper().startswith("NB"):
                raise FileMakerAPIError("新订单没有生成 NB 内部订单编号")

            merge_log = _merge_log_text(
                settings=settings,
                request_id=request_id,
                customer_id=customer_id,
                customer_name=customer_name,
                operator_account=operator_account,
                operator_name=operator_name,
                new_order_id=new_order_id,
                new_internal_order_no=new_internal_order_no,
                source_internal_order_nos=prepared["sourceInternalOrderNos"],
                source_item_count=len(item_records),
                merged_items=prepared["mergedItems"],
            )
            await client.update_record(
                settings.filemaker_web_merge_order_layout,
                header_record_id,
                {settings.filemaker_web_merge_log_field: merge_log},
            )

            for product_no in sorted(totals):
                detail_result = await client.create_record(
                    settings.filemaker_web_merge_item_layout,
                    {
                        settings.filemaker_web_merge_item_order_id_field: new_order_id,
                        settings.filemaker_web_merge_item_product_field: product_no,
                        settings.filemaker_web_merge_item_quantity_field: _filemaker_number(totals[product_no]),
                    },
                )
                detail_record_id = _text(detail_result.get("recordId"))
                if not detail_record_id:
                    raise FileMakerAPIError(f"产品 {product_no} 的新明细未返回 recordId")
                detail_record_ids.append(detail_record_id)
        except Exception as exc:
            rollback_errors = await _rollback_created_records(
                client,
                settings,
                header_record_id=header_record_id,
                detail_record_ids=detail_record_ids,
            )
            if rollback_errors:
                raise InternalOrderMergeError(
                    "Web 合并失败，且补偿删除未完全成功，请立即人工检查",
                    status_code=500,
                    details={"rollbackErrors": rollback_errors, "cause": str(exc)},
                ) from exc
            raise

        return {
            "ok": True,
            "mode": "web",
            "duplicate": False,
            "requestId": request_id,
            "newOrderId": new_order_id,
            "newInternalOrderNo": new_internal_order_no,
            "headerRecordId": header_record_id,
            "headerCreateLayout": settings.filemaker_web_merge_order_create_layout,
            "detailRecordIds": detail_record_ids,
            "customerId": customer_id,
            "customerName": customer_name,
            "sourceOrderCount": len(normalized_order_ids),
            "sourceInternalOrderNos": prepared["sourceInternalOrderNos"],
            "sourceItemCount": len(item_records),
            "mergedItemCount": len(totals),
            "mergedItems": prepared["mergedItems"],
            "logWritten": True,
        }

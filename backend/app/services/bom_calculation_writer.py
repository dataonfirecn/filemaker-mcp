import asyncio
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config import Settings
from app.models.bom_calculation_write import BomCalculationWriteLine
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient


class BomCalculationWriteError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


_bom_write_lock = asyncio.Lock()
_NUMBER_TOLERANCE = Decimal("0.000001")
ORDER_ID_FIELD = "id"


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData") if isinstance(record, dict) else {}
    return fields if isinstance(fields, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any, *, label: str) -> Decimal:
    normalized = _text(value).replace(",", "")
    try:
        result = Decimal(normalized)
    except (InvalidOperation, ValueError) as exc:
        raise BomCalculationWriteError(f"{label}不是有效数字：{value!s}", 422) from exc
    if not result.is_finite():
        raise BomCalculationWriteError(f"{label}不是有限数字", 422)
    return result


def _filemaker_number(value: Decimal) -> str:
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


async def _find_exact(
    client: FileMakerClient,
    *,
    layout: str,
    field: str,
    value: str,
    limit: int = 1,
) -> dict[str, Any]:
    return await client.find_records(
        layout,
        query={field: f"=={value}"},
        limit=limit,
    )


async def _find_by_values(
    client: FileMakerClient,
    *,
    layout: str,
    field: str,
    values: list[str],
    limit: int,
) -> dict[str, Any]:
    unique_values = list(dict.fromkeys(value for value in values if value))
    if not unique_values:
        return {"data": [], "foundCount": 0, "returnedCount": 0}
    return await client.find_records(
        layout,
        query=[{field: f"=={value}"} for value in unique_values],
        limit=limit,
    )


async def _existing_result(
    *,
    client: FileMakerClient,
    settings: Settings,
    request_id: str,
    order_id: str,
    header_record: dict[str, Any],
    order_write_record: dict[str, Any],
) -> dict[str, Any]:
    header_record_id = _text(header_record.get("recordId"))
    bom_calculation_id = _text(_fields(header_record).get("id"))
    if not header_record_id or not bom_calculation_id:
        raise BomCalculationWriteError(
            "已存在的 BOM 计算单缺少记录 ID 或业务 ID，请人工检查",
            409,
        )

    detail_result = await _find_exact(
        client,
        layout=settings.filemaker_bom_detail_layout,
        field="ID_BOM計算單",
        value=bom_calculation_id,
        limit=settings.filemaker_bom_max_detail_records + 1,
    )
    nonrepeat_result = await _find_exact(
        client,
        layout=settings.filemaker_bom_nonrepeat_layout,
        field="ID_BOM計算單",
        value=bom_calculation_id,
        limit=settings.filemaker_bom_max_detail_records + 1,
    )
    detail_records = _records(detail_result)
    nonrepeat_records = _records(nonrepeat_result)
    if not detail_records or not nonrepeat_records:
        raise BomCalculationWriteError(
            "该订单已有一张未完成的 BOM 计算单，请先人工核对，系统不会重复创建",
            409,
            {
                "bomCalculationId": bom_calculation_id,
                "detailCount": len(detail_records),
                "partCount": len(nonrepeat_records),
            },
        )

    order_record_id = _text(order_write_record.get("recordId"))
    linked_id = _text(_fields(order_write_record).get("ID_BOM計算"))
    if linked_id and linked_id != bom_calculation_id:
        raise BomCalculationWriteError(
            "出货单已关联另一张 BOM 计算单，请人工检查",
            409,
            {
                "linkedBomCalculationId": linked_id,
                "existingBomCalculationId": bom_calculation_id,
            },
        )
    if not linked_id:
        await client.update_record(
            settings.filemaker_bom_order_write_layout,
            order_record_id,
            {"ID_BOM計算": bom_calculation_id},
        )

    return {
        "ok": True,
        "mode": "web-data-api",
        "duplicate": True,
        "requestId": request_id,
        "orderId": order_id,
        "bomCalculationId": bom_calculation_id,
        "headerRecordId": header_record_id,
        "detailRecordIds": [
            _text(record.get("recordId")) for record in detail_records if record.get("recordId")
        ],
        "nonrepeatRecordIds": [
            _text(record.get("recordId"))
            for record in nonrepeat_records
            if record.get("recordId")
        ],
        "detailCount": len(detail_records),
        "partCount": len(nonrepeat_records),
        "orderLinked": True,
    }


async def _rollback_created_records(
    *,
    client: FileMakerClient,
    settings: Settings,
    order_record_id: str,
    order_linked: bool,
    header_record_id: str,
    detail_record_ids: list[str],
    nonrepeat_record_ids: list[str],
) -> list[str]:
    errors: list[str] = []
    if order_linked and order_record_id:
        try:
            await client.update_record(
                settings.filemaker_bom_order_write_layout,
                order_record_id,
                {"ID_BOM計算": ""},
            )
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"清空出货单 BOM 关联失败：{exc}")
    for record_id in reversed(nonrepeat_record_ids):
        try:
            await client.delete_record(settings.filemaker_bom_nonrepeat_layout, record_id)
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"删除汇总明细 {record_id} 失败：{exc}")
    for record_id in reversed(detail_record_ids):
        try:
            await client.delete_record(settings.filemaker_bom_detail_layout, record_id)
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"删除产品明细 {record_id} 失败：{exc}")
    if header_record_id:
        try:
            await client.delete_record(settings.filemaker_bom_header_layout, header_record_id)
        except Exception as exc:  # pragma: no cover - best-effort compensation
            errors.append(f"删除 BOM 计算单 {header_record_id} 失败：{exc}")
    return errors


async def create_bom_calculation_via_data_api(
    *,
    client: FileMakerClient,
    settings: Settings,
    request_id: str,
    order_id: str,
    lines: list[BomCalculationWriteLine],
) -> dict[str, Any]:
    normalized_order_id = order_id.strip()
    if not normalized_order_id:
        raise BomCalculationWriteError("缺少出货单 ID", 400)
    if not lines:
        raise BomCalculationWriteError("BOM 计算单至少需要一条明细", 422)
    if len(lines) > settings.filemaker_bom_max_detail_records:
        raise BomCalculationWriteError(
            f"BOM 明细超过 {settings.filemaker_bom_max_detail_records} 条安全上限",
            422,
        )

    async with _bom_write_lock:
        order_result = await _find_exact(
            client,
            layout=settings.filemaker_bom_order_read_layout,
            field=ORDER_ID_FIELD,
            value=normalized_order_id,
        )
        order_records = _records(order_result)
        if not order_records:
            raise BomCalculationWriteError(f"找不到出货单：{normalized_order_id}", 404)
        order_fields = _fields(order_records[0])

        order_write_result = await _find_exact(
            client,
            layout=settings.filemaker_bom_order_write_layout,
            field=ORDER_ID_FIELD,
            value=normalized_order_id,
        )
        order_write_records = _records(order_write_result)
        if not order_write_records:
            raise BomCalculationWriteError(
                "专用订单写入布局找不到当前出货单，已停止写入",
                409,
                {"layout": settings.filemaker_bom_order_write_layout},
            )
        order_write_record = order_write_records[0]
        order_record_id = _text(order_write_record.get("recordId"))
        if not order_record_id:
            raise BomCalculationWriteError("专用订单写入布局没有返回 recordId", 409)

        existing_header_result = await _find_exact(
            client,
            layout=settings.filemaker_bom_header_layout,
            field="ID_出庫單",
            value=normalized_order_id,
        )
        existing_headers = _records(existing_header_result)
        if existing_headers:
            return await _existing_result(
                client=client,
                settings=settings,
                request_id=request_id,
                order_id=normalized_order_id,
                header_record=existing_headers[0],
                order_write_record=order_write_record,
            )

        linked_bom_id = _text(_fields(order_write_record).get("ID_BOM計算"))
        if linked_bom_id:
            linked_header_result = await _find_exact(
                client,
                layout=settings.filemaker_bom_header_layout,
                field="id",
                value=linked_bom_id,
            )
            linked_headers = _records(linked_header_result)
            if linked_headers:
                return await _existing_result(
                    client=client,
                    settings=settings,
                    request_id=request_id,
                    order_id=normalized_order_id,
                    header_record=linked_headers[0],
                    order_write_record=order_write_record,
                )
            raise BomCalculationWriteError(
                "出货单已保存 BOM 计算单 ID，但找不到对应计算单，请人工检查",
                409,
                {"linkedBomCalculationId": linked_bom_id},
            )

        item_result = await _find_exact(
            client,
            layout=settings.filemaker_bom_order_item_layout,
            field="ID_出貨單",
            value=normalized_order_id,
            limit=settings.filemaker_bom_max_detail_records + 1,
        )
        item_records = _records(item_result)
        items_by_id = {
            _text(_fields(record).get("ID")): _fields(record)
            for record in item_records
            if _text(_fields(record).get("ID"))
        }
        if not items_by_id:
            raise BomCalculationWriteError("当前出货单没有可写入的产品明细", 422)

        part_nos = [line.part_no.strip() for line in lines]
        part_result = await _find_by_values(
            client,
            layout=settings.filemaker_bom_part_layout,
            field="part_number",
            values=part_nos,
            limit=len(set(part_nos)) + 1,
        )
        existing_part_nos = {
            _text(_fields(record).get("part_number")) for record in _records(part_result)
        }
        missing_part_nos = sorted(set(part_nos) - existing_part_nos)
        if missing_part_nos:
            raise BomCalculationWriteError(
                "部分零件不存在于 FileMaker 零件库，已停止写入",
                422,
                {"partNos": missing_part_nos},
            )

        product_skus = list(dict.fromkeys(line.product_sku.strip() for line in lines))
        bom_fields_by_source: dict[tuple[str, str], dict[str, Any]] = {}
        for product_sku in product_skus:
            bom_result = await _find_exact(
                client,
                layout=settings.filemaker_bom_product_layout,
                field="ID_產品編號",
                value=product_sku,
                limit=500,
            )
            for record in _records(bom_result):
                fields = _fields(record)
                part_no = _text(fields.get("零件編號"))
                if part_no:
                    bom_fields_by_source[(product_sku, part_no)] = fields

        normalized_lines: list[dict[str, Any]] = []
        seen_source_lines: set[tuple[str, str]] = set()
        for line in lines:
            order_item_id = line.order_item_id.strip()
            product_sku = line.product_sku.strip()
            part_no = line.part_no.strip()
            original_part_no = line.original_part_no.strip()
            item_fields = items_by_id.get(order_item_id)
            if not item_fields:
                raise BomCalculationWriteError(
                    "提交内容包含不属于当前出货单的产品明细",
                    422,
                    {"orderItemId": order_item_id},
                )
            actual_product_sku = _text(item_fields.get("產品編號"))
            if actual_product_sku != product_sku:
                raise BomCalculationWriteError(
                    "提交的产品编号与出货单明细不一致",
                    422,
                    {
                        "orderItemId": order_item_id,
                        "submitted": product_sku,
                        "actual": actual_product_sku,
                    },
                )
            actual_product_qty = _decimal(
                item_fields.get("數量"),
                label=f"产品 {product_sku} 的订单数量",
            )
            if abs(actual_product_qty - line.product_qty) > _NUMBER_TOLERANCE:
                raise BomCalculationWriteError(
                    "提交的产品数量与出货单明细不一致",
                    422,
                    {
                        "orderItemId": order_item_id,
                        "submitted": _filemaker_number(line.product_qty),
                        "actual": _filemaker_number(actual_product_qty),
                    },
                )
            if (product_sku, original_part_no) not in bom_fields_by_source:
                raise BomCalculationWriteError(
                    "原始零件不属于该产品的 FileMaker BOM",
                    422,
                    {"productSku": product_sku, "partNo": original_part_no},
                )
            replacement_reason = line.replacement_reason.strip()
            if part_no != original_part_no and len(replacement_reason) < 2:
                raise BomCalculationWriteError("更换零件时必须填写至少 2 个字的原因", 422)
            source_key = (order_item_id, original_part_no)
            if source_key in seen_source_lines:
                raise BomCalculationWriteError(
                    "同一订单产品与原始零件被重复提交",
                    422,
                    {"orderItemId": order_item_id, "partNo": original_part_no},
                )
            seen_source_lines.add(source_key)
            normalized_lines.append(
                {
                    "partNo": part_no,
                    "originalPartNo": original_part_no,
                    "ratedQty": line.rated_qty,
                    "quantity": line.quantity,
                    "productSku": product_sku,
                    "productQty": line.product_qty,
                    "orderItemId": order_item_id,
                    "replacementReason": replacement_reason,
                }
            )

        customer = _text(order_fields.get("公司"))
        if not customer:
            rich_item_result = await _find_exact(
                client,
                layout=settings.filemaker_bom_order_rich_item_layout,
                field="ID_出貨單",
                value=normalized_order_id,
            )
            rich_item_records = _records(rich_item_result)
            rich_fields = _fields(rich_item_records[0]) if rich_item_records else {}
            customer = (
                _text(rich_fields.get("買貨客戶"))
                or _text(rich_fields.get("公司名稱"))
            )

        header_data = {
            "ID_出庫單": normalized_order_id,
            "客戶": customer,
            "車款": _text(order_fields.get("訂單概要中文")),
            "訂單日期": _text(order_fields.get("日期")),
            "訂單編號": _text(order_fields.get("internal_id")),
        }
        aggregate_quantities: dict[str, Decimal] = defaultdict(Decimal)
        aggregate_mold_fields: dict[str, dict[str, Any]] = {}
        for line in normalized_lines:
            aggregate_quantities[line["partNo"]] += line["quantity"]
            source_bom_fields = bom_fields_by_source.get(
                (line["productSku"], line["partNo"]),
                {},
            )
            if _text(source_bom_fields.get("加工類")) == "模具":
                aggregate_mold_fields.setdefault(
                    line["partNo"],
                    {
                        "加工類Local": "模具",
                        "塑膠用料型號": _text(source_bom_fields.get("塑膠用料型號")),
                        "塑膠一模產品重量Local": _text(
                            source_bom_fields.get("塑膠料一模重量")
                        ),
                    },
                )

        header_record_id = ""
        bom_calculation_id = ""
        detail_record_ids: list[str] = []
        nonrepeat_record_ids: list[str] = []
        order_linked = False
        try:
            header_result = await client.create_record(
                settings.filemaker_bom_header_layout,
                header_data,
            )
            header_record_id = _text(header_result.get("recordId"))
            if not header_record_id:
                raise FileMakerAPIError("创建 BOM 计算单后没有返回 recordId")
            created_header = await client.get_record(
                settings.filemaker_bom_header_layout,
                header_record_id,
            )
            created_header_records = (
                created_header if isinstance(created_header, list) else []
            )
            created_header_fields = (
                _fields(created_header_records[0]) if created_header_records else {}
            )
            bom_calculation_id = _text(created_header_fields.get("id"))
            if not bom_calculation_id:
                raise FileMakerAPIError("新 BOM 计算单没有生成业务 ID")

            for line in normalized_lines:
                detail_result = await client.create_record(
                    settings.filemaker_bom_detail_layout,
                    {
                        "ID_BOM計算單": bom_calculation_id,
                        "id_零件": line["partNo"],
                        "額定數量": _filemaker_number(line["ratedQty"]),
                        "數量": _filemaker_number(line["quantity"]),
                        "ID_Product": line["productSku"],
                        "product_qty": _filemaker_number(line["productQty"]),
                        "ID_出貨單資料": line["orderItemId"],
                    },
                )
                detail_record_id = _text(detail_result.get("recordId"))
                if not detail_record_id:
                    raise FileMakerAPIError(
                        f"零件 {line['partNo']} 的 BOM 明细没有返回 recordId"
                    )
                detail_record_ids.append(detail_record_id)

            for part_no in sorted(aggregate_quantities):
                nonrepeat_data = {
                    "ID_BOM計算單": bom_calculation_id,
                    "id_零件": part_no,
                    "數量": _filemaker_number(aggregate_quantities[part_no]),
                }
                nonrepeat_data.update(aggregate_mold_fields.get(part_no, {}))
                nonrepeat_result = await client.create_record(
                    settings.filemaker_bom_nonrepeat_layout,
                    nonrepeat_data,
                )
                nonrepeat_record_id = _text(nonrepeat_result.get("recordId"))
                if not nonrepeat_record_id:
                    raise FileMakerAPIError(
                        f"零件 {part_no} 的汇总明细没有返回 recordId"
                    )
                nonrepeat_record_ids.append(nonrepeat_record_id)

            await client.update_record(
                settings.filemaker_bom_order_write_layout,
                order_record_id,
                {"ID_BOM計算": bom_calculation_id},
            )
            order_linked = True
        except Exception as exc:
            rollback_errors = await _rollback_created_records(
                client=client,
                settings=settings,
                order_record_id=order_record_id,
                order_linked=order_linked,
                header_record_id=header_record_id,
                detail_record_ids=detail_record_ids,
                nonrepeat_record_ids=nonrepeat_record_ids,
            )
            if rollback_errors:
                raise BomCalculationWriteError(
                    "BOM 计算单写入失败，且补偿删除未完全成功，请立即人工检查",
                    500,
                    {"cause": str(exc), "rollbackErrors": rollback_errors},
                ) from exc
            raise

        return {
            "ok": True,
            "mode": "web-data-api",
            "duplicate": False,
            "requestId": request_id,
            "orderId": normalized_order_id,
            "bomCalculationId": bom_calculation_id,
            "headerRecordId": header_record_id,
            "detailRecordIds": detail_record_ids,
            "nonrepeatRecordIds": nonrepeat_record_ids,
            "detailCount": len(detail_record_ids),
            "partCount": len(nonrepeat_record_ids),
            "orderLinked": True,
        }

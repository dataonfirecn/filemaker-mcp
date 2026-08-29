import asyncio
import re
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.bom_calculation_write import (
    CreateBomCalculationRequest,
    CreateBomCalculationResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.bom_calculation_writer import (
    BomCalculationWriteError,
    create_bom_calculation_via_data_api,
)
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
    get_settings,
    get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
)
from app.services.filemaker_timestamps import (
    FILEMAKER_TIMEZONE,
    format_filemaker_timestamp,
    parse_filemaker_timestamp,
)
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.internal_order_merge import (
    InternalOrderMergeError,
    merge_internal_orders_via_data_api,
    preview_internal_orders_via_data_api,
)
from app.services.mobile_receipt_trace import parse_mobile_receipt_trace
from app.services.product_api import PRODUCT_LAYOUT, PRODUCT_STOCK_FIELD, enrich_product_record
from app.services.part_assets import (
    asset_fields as part_asset_fields,
    find_primary_part_asset,
)

router = APIRouter(prefix="/orders", tags=["orders"])

ORDER_LAYOUT = "@出貨單"
ORDER_ID_FIELD = "id"
ORDER_INTERNAL_ID_FIELD = "internal_id"
ORDER_ITEM_LAYOUT = "@出貨單資料"
ORDER_ITEM_QTY_LAYOUT = "出貨單資料_List_業務"
PART_LAYOUT = "零件 資料_業務"
INTERNAL_ORDER_LIST_LAYOUT = "訂單 清單_業務"
INTERNAL_ORDER_SUMMARY_LAYOUT = "訂單 清單"
INTERNAL_ORDER_CATEGORY = "内部订单"
ORDER_LIST_PAGE_SIZE = 500
ORDER_LIST_MAX_RECORDS = 5000
ORDER_JOIN_BATCH_SIZE = 200
PRODUCT_ASSET_LAYOUT = "ProductAssets"
PRODUCT_ASSET_BATCH_SIZE = 200
PRODUCT_PACKAGING_LAYOUT = "產品 資料_包裝"
PART_ASSET_SOURCE_LAYOUT = "@零件"
INBOUND_ORDER_TABLE = "入庫單"
INBOUND_ORDER_LINE_TABLE = "入庫單資料"
SUPPLEMENTAL_INBOUND_SUMMARY_PREFIX = "PDA追加成品入库"


class PartDetailsRequest(BaseModel):
    part_nos: list[str] = Field(alias="partNos", max_length=500)

    model_config = {"populate_by_name": True}


class InternalOrderWebMergeRequest(BaseModel):
    order_ids: list[str] = Field(alias="orderIds", min_length=2, max_length=200)
    request_id: str = Field(
        alias="requestId",
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    model_config = {"populate_by_name": True}


class InternalOrderMergePreviewRequest(BaseModel):
    order_ids: list[str] = Field(alias="orderIds", min_length=2, max_length=200)

    model_config = {"populate_by_name": True}


async def _find_all_order_records(
    client: FileMakerClient,
    layout: str,
    query: dict[str, Any],
    *,
    sort: list[dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    offset = 1
    source_found_count = 0
    while len(records) < ORDER_LIST_MAX_RECORDS:
        page_limit = min(ORDER_LIST_PAGE_SIZE, ORDER_LIST_MAX_RECORDS - len(records))
        result = await client.find_records(
            layout,
            query=query,
            limit=page_limit,
            offset=offset,
            sort=sort,
        )
        page = _records(result)
        if not page:
            break
        records.extend(page)
        found_count = int(result.get("foundCount") or 0)
        source_found_count = max(source_found_count, found_count)
        if found_count and len(records) >= min(found_count, ORDER_LIST_MAX_RECORDS):
            break
        if not found_count and len(page) < page_limit:
            break
        offset += len(page)
    return records, source_found_count or len(records)


async def _find_orders_by_internal_number(
    client: FileMakerClient,
    layout: str,
    internal_numbers: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for start in range(0, len(internal_numbers), ORDER_JOIN_BATCH_SIZE):
        batch = internal_numbers[start : start + ORDER_JOIN_BATCH_SIZE]
        result = await client.find_records(
            layout,
            query=[{ORDER_INTERNAL_ID_FIELD: f"=={number}"} for number in batch],
            limit=ORDER_LIST_PAGE_SIZE,
        )
        records.extend(_records(result))
    return records


@router.get("/internal")
async def get_internal_orders(
    session_context: dict[str, Any] = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
    scope: Literal["internal", "all"] = "internal",
) -> dict[str, Any]:
    customer_name = _text(session_context.get("customerName"))
    customer_id = _text(session_context.get("customerId"))
    if not customer_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "WebViewer 缺少 customerName，无法限定当前客户"},
        )

    try:
        rich_query = {
            "出貨單_客戶::客戶名稱": f"=={customer_name}",
        }
        if scope == "internal":
            rich_query["訂單分類"] = f"=={INTERNAL_ORDER_CATEGORY}"

        rich_records, source_found_count = await _find_all_order_records(
            client,
            INTERNAL_ORDER_LIST_LAYOUT,
            query=rich_query,
            sort=[{"fieldName": ORDER_INTERNAL_ID_FIELD, "sortOrder": "descend"}],
        )
        internal_numbers = list(
            dict.fromkeys(
                _text(_fields(record).get(ORDER_INTERNAL_ID_FIELD))
                for record in rich_records
                if _text(_fields(record).get(ORDER_INTERNAL_ID_FIELD))
            )
        )
        shipment_records = await _find_orders_by_internal_number(client, ORDER_LAYOUT, internal_numbers)
        summary_records = await _find_orders_by_internal_number(
            client,
            INTERNAL_ORDER_SUMMARY_LAYOUT,
            internal_numbers,
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    shipments = {
        _text(_fields(record).get(ORDER_INTERNAL_ID_FIELD)): _fields(record)
        for record in shipment_records
    }
    summaries = {
        _text(_fields(record).get(ORDER_INTERNAL_ID_FIELD)): _fields(record)
        for record in summary_records
    }
    rows: list[dict[str, Any]] = []
    for record in rich_records:
        fields = _fields(record)
        internal_order_no = _text(fields.get(ORDER_INTERNAL_ID_FIELD))
        shipment = shipments.get(internal_order_no, {})
        summary = summaries.get(internal_order_no, {})
        order_id = _text(shipment.get(ORDER_ID_FIELD))
        if not order_id:
            continue
        rows.append(
            {
                "orderId": order_id,
                "recordId": str(record.get("recordId") or ""),
                "internalOrderNo": internal_order_no,
                "piNo": _text(shipment.get("出貨單 PI")),
                "customerPo": _text(shipment.get("訂單 PO")),
                "orderDate": _text(summary.get("日期")) or _text(shipment.get("修改日期")),
                "amount": _number(fields.get("貨款總和")) or _number(summary.get("總和")),
                "summary": _text(fields.get("訂單概要中文")),
                "orderCategory": _text(fields.get("訂單分類")),
                "orderConfirmation": _text(fields.get("訂單確認")),
                "tags": list(
                    dict.fromkeys(
                        value
                        for value in (
                            _text(fields.get("訂單分類")),
                            _text(fields.get("訂單確認")),
                        )
                        if value
                    )
                ),
                "packagingStatus": _text(fields.get("包裝狀態")) or _text(shipment.get("包裝狀態")),
                "paymentStatus": _text(summary.get("付款狀態")),
                "elapsedDays": _text(fields.get("已過天數")) or _text(summary.get("已過天數")),
                "customerName": _text(fields.get("出貨單_客戶::客戶名稱")) or customer_name,
            }
        )

    await audit_log.record(
        operator=operator,
        action_type="READ_INTERNAL_ORDERS" if scope == "internal" else "READ_CUSTOMER_ORDERS",
        status="success",
        target_layout=INTERNAL_ORDER_LIST_LAYOUT,
        request_payload={"customerId": customer_id, "customerName": customer_name, "scope": scope},
        response_payload={
            "foundCount": len(rows),
            "sourceFoundCount": source_found_count,
            "unmergeableCount": len(rich_records) - len(rows),
        },
    )
    return {
        "customerId": customer_id,
        "customerName": customer_name,
        "currency": _text(session_context.get("currency")),
        "scope": scope,
        "rows": rows,
        "foundCount": len(rows),
        "returnedCount": len(rows),
        "sourceFoundCount": source_found_count,
        "unmergeableCount": len(rich_records) - len(rows),
        "truncated": source_found_count > len(rich_records),
        "layout": INTERNAL_ORDER_LIST_LAYOUT,
        "readOnly": True,
        "webMergeEnabled": settings.filemaker_web_merge_enabled,
    }


@router.post("/internal/merge/preview")
async def preview_internal_orders_web(
    body: InternalOrderMergePreviewRequest,
    session_context: dict[str, Any] = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    customer_id = _text(session_context.get("customerId"))
    customer_name = _text(session_context.get("customerName"))
    audit_request = {
        "customerId": customer_id,
        "customerName": customer_name,
        "orderIds": body.order_ids,
        "mode": "web-data-api-preview",
    }
    try:
        result = await preview_internal_orders_via_data_api(
            client=client,
            settings=settings,
            customer_id=customer_id,
            order_ids=body.order_ids,
        )
    except InternalOrderMergeError as exc:
        await audit_log.record(
            operator=operator,
            action_type="PREVIEW_INTERNAL_ORDER_MERGE",
            status="failed",
            target_layout=settings.filemaker_web_merge_item_layout,
            request_payload=audit_request,
            response_payload=exc.details,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": str(exc), "details": exc.details},
        ) from exc
    except FileMakerAPIError as exc:
        await audit_log.record(
            operator=operator,
            action_type="PREVIEW_INTERNAL_ORDER_MERGE",
            status="failed",
            target_layout=settings.filemaker_web_merge_item_layout,
            request_payload=audit_request,
            response_payload=exc.payload,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type="PREVIEW_INTERNAL_ORDER_MERGE",
        status="success",
        target_layout=settings.filemaker_web_merge_item_layout,
        request_payload=audit_request,
        response_payload={
            "sourceOrderCount": result["sourceOrderCount"],
            "sourceItemCount": result["sourceItemCount"],
            "mergedItemCount": result["mergedItemCount"],
        },
    )
    return result


@router.post("/internal/merge/web")
async def merge_internal_orders_web(
    body: InternalOrderWebMergeRequest,
    session_context: dict[str, Any] = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    if not settings.filemaker_web_merge_enabled:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "message": "Web Data API 合并尚未启用；请先配置专用布局并设置 FILEMAKER_WEB_MERGE_ENABLED=true。"
            },
        )

    customer_id = _text(session_context.get("customerId"))
    customer_name = _text(session_context.get("customerName"))
    audit_request = {
        "requestId": body.request_id,
        "customerId": customer_id,
        "customerName": customer_name,
        "orderIds": body.order_ids,
        "mode": "web-data-api",
    }
    claim_owned = False
    try:
        claim = await audit_log.claim_web_merge_request(
            request_id=body.request_id,
            customer_id=customer_id,
            source_order_ids=body.order_ids,
        )
        claim_status = _text(claim.get("status"))
        if claim_status == "duplicate":
            result = dict(claim.get("result") or {})
            result["duplicate"] = True
            await audit_log.record(
                operator=operator,
                action_type="WEB_MERGE_INTERNAL_ORDERS",
                status="success",
                target_layout=settings.filemaker_web_merge_order_layout,
                target_record_id=_text(result.get("headerRecordId")),
                order_id=_text(result.get("newOrderId")),
                request_payload=audit_request,
                response_payload=result,
            )
            return result
        if claim_status == "conflict":
            raise InternalOrderMergeError(
                "requestId 已被其他客户或其他订单组合使用",
                status_code=409,
            )
        if claim_status == "in_progress":
            raise InternalOrderMergeError(
                "同一 Web 合并请求正在处理中，请勿重复提交",
                status_code=409,
            )
        if claim_status != "claimed":
            raise RuntimeError(f"未知的 Web 合并幂等状态：{claim_status}")
        claim_owned = True
        result = await merge_internal_orders_via_data_api(
            client=client,
            settings=settings,
            customer_id=customer_id,
            customer_name=customer_name,
            order_ids=body.order_ids,
            request_id=body.request_id,
            operator_account=operator.account,
            operator_name=operator.name,
        )
        # FileMaker records now exist. If this persistence step fails, keep the
        # claim pending so a retry is blocked instead of risking a duplicate.
        claim_owned = False
        await audit_log.complete_web_merge_request(
            request_id=body.request_id,
            response_payload=result,
        )
    except InternalOrderMergeError as exc:
        if claim_owned:
            await audit_log.fail_web_merge_request(
                request_id=body.request_id,
                error_message=str(exc),
            )
        await audit_log.record(
            operator=operator,
            action_type="WEB_MERGE_INTERNAL_ORDERS",
            status="failed",
            target_layout=settings.filemaker_web_merge_order_layout,
            request_payload=audit_request,
            response_payload=exc.details,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": str(exc), "details": exc.details},
        ) from exc
    except FileMakerAPIError as exc:
        if claim_owned:
            await audit_log.fail_web_merge_request(
                request_id=body.request_id,
                error_message=str(exc),
            )
        await audit_log.record(
            operator=operator,
            action_type="WEB_MERGE_INTERNAL_ORDERS",
            status="failed",
            target_layout=settings.filemaker_web_merge_order_layout,
            request_payload=audit_request,
            response_payload=exc.payload,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc
    except Exception as exc:
        if claim_owned:
            await audit_log.fail_web_merge_request(
                request_id=body.request_id,
                error_message=str(exc),
            )
        await audit_log.record(
            operator=operator,
            action_type="WEB_MERGE_INTERNAL_ORDERS",
            status="failed",
            target_layout=settings.filemaker_web_merge_order_layout,
            request_payload=audit_request,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Web Data API 合并失败，请检查审计日志", "error": str(exc)},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type="WEB_MERGE_INTERNAL_ORDERS",
        status="success",
        target_layout=settings.filemaker_web_merge_order_layout,
        target_record_id=_text(result.get("headerRecordId")),
        order_id=_text(result.get("newOrderId")),
        request_payload=audit_request,
        response_payload=result,
    )
    return result


@router.post(
    "/{order_id}/bom-calculations",
    response_model=CreateBomCalculationResponse,
)
async def create_order_bom_calculation(
    order_id: str,
    body: CreateBomCalculationRequest,
    session_context: dict[str, Any] = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
) -> CreateBomCalculationResponse:
    if not settings.filemaker_bom_write_enabled:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "message": (
                    "BOM Data API 写入尚未启用；请先检查专用布局并设置 "
                    "FILEMAKER_BOM_WRITE_ENABLED=true。"
                )
            },
        )

    normalized_order_id = order_id.strip()
    context_order_id = _text(session_context.get("orderId"))
    if context_order_id and context_order_id != normalized_order_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "当前 WebViewer 会话不属于这张出货单"},
        )

    audit_request = {
        "requestId": body.request_id,
        "orderId": normalized_order_id,
        "lineCount": len(body.lines),
        "lines": [
            line.model_dump(mode="json", by_alias=True) for line in body.lines
        ],
        "mode": "web-data-api",
    }
    try:
        result = await create_bom_calculation_via_data_api(
            client=client,
            settings=settings,
            request_id=body.request_id,
            order_id=normalized_order_id,
            lines=body.lines,
        )
    except BomCalculationWriteError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_ORDER_BOM_CALCULATION",
            status="failed",
            target_layout=settings.filemaker_bom_header_layout,
            order_id=normalized_order_id,
            request_payload=audit_request,
            response_payload=exc.details,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": str(exc), "details": exc.details},
        ) from exc
    except FileMakerAPIError as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_ORDER_BOM_CALCULATION",
            status="failed",
            target_layout=settings.filemaker_bom_header_layout,
            order_id=normalized_order_id,
            request_payload=audit_request,
            response_payload=exc.payload,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc
    except Exception as exc:
        await audit_log.record(
            operator=operator,
            action_type="CREATE_ORDER_BOM_CALCULATION",
            status="failed",
            target_layout=settings.filemaker_bom_header_layout,
            order_id=normalized_order_id,
            request_payload=audit_request,
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "BOM Data API 写入失败，请检查审计日志"},
        ) from exc

    await audit_log.record(
        operator=operator,
        action_type="CREATE_ORDER_BOM_CALCULATION",
        status="success",
        target_layout=settings.filemaker_bom_header_layout,
        target_record_id=_text(result.get("headerRecordId")),
        order_id=normalized_order_id,
        bom_calc_id=_text(result.get("bomCalculationId")),
        request_payload=audit_request,
        response_payload=result,
    )
    return CreateBomCalculationResponse(**result)


@router.post("/parts/details")
async def get_order_part_details(
    body: PartDetailsRequest,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, Any]:
    part_nos = list(dict.fromkeys(item.strip() for item in body.part_nos if item.strip()))[:500]
    if not part_nos:
        return {"rows": [], "foundCount": 0}
    try:
        result = await client.find_records(
            PART_LAYOUT,
            query=[{"part_number": f"=={part_no}"} for part_no in part_nos],
            limit=500,
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc
    rows = [_part_payload(_fields(record)) for record in _records(result)]
    return {"rows": rows, "foundCount": len(rows)}


@router.get("/parts/{part_no}/image")
async def get_order_part_image(
    part_no: str,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> RedirectResponse:
    try:
        result = await client.find_records(
            PART_LAYOUT,
            query={"part_number": f"=={part_no.strip()}"},
            limit=1,
        )
        records = _records(result)
        fields = _fields(records[0]) if records else {}
        part_id = _text(fields.get("part_id"))
        if part_id:
            try:
                asset = await find_primary_part_asset(
                    client,
                    settings,
                    part_id=part_id,
                )
            except FileMakerAPIError:
                asset = None
            object_key = _text(part_asset_fields(asset).get("object_key"))
            try:
                asset_url, _expires_at = (
                    await run_in_threadpool(storage.create_presigned_download, object_key)
                    if object_key
                    else ("", None)
                )
            except COSStorageError:
                asset_url = ""
            if asset_url:
                return RedirectResponse(
                    asset_url,
                    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                    headers={"Cache-Control": "private, max-age=300"},
                )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "零件没有已同步到 COS 的图片"},
        )
    except HTTPException:
        raise
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc


@router.get("/products/{product_sku}/image")
async def get_order_product_image(
    product_sku: str,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> RedirectResponse:
    normalized_sku = product_sku.strip()
    if not normalized_sku:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Missing productSku"},
        )
    try:
        image_catalog = await _product_cos_image_catalog(
            client,
            storage,
            [normalized_sku],
            primary_only=True,
        )
        image_url = _text(image_catalog.get(normalized_sku, {}).get("mainImageUrl"))
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "产品没有已迁移到 COS 的图片"},
            )
        return RedirectResponse(
            image_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Cache-Control": "private, max-age=300"},
        )
    except HTTPException:
        raise
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc


@router.get("/products/{product_sku}/detail")
async def get_order_product_detail(
    product_sku: str,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> dict[str, Any]:
    normalized_sku = product_sku.strip()
    if not normalized_sku:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "Missing productSku"})
    try:
        result, packaging_result = await asyncio.gather(
            client.find_records(
                PRODUCT_LAYOUT,
                query={"product_sku": f"=={normalized_sku}"},
                limit=1,
            ),
            client.find_records(
                PRODUCT_PACKAGING_LAYOUT,
                query={"product_sku": f"=={normalized_sku}"},
                limit=1,
            ),
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc
    records = _records(result)
    if not records:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": f"找不到产品：{normalized_sku}"})
    enriched = await enrich_product_record(client, records[0])
    packaging_records = _records(packaging_result)
    packaging_record = packaging_records[0] if packaging_records else {}
    packaging_fields = _fields(packaging_record)
    bom_rows = _packaging_bom_rows(packaging_record)
    part_image_catalog = await _part_cos_image_catalog(
        client,
        storage,
        [_text(item.get("產品 BOM::零件編號")) for item in bom_rows],
    )
    image_catalog = await _product_cos_image_catalog(
        client,
        storage,
        [normalized_sku],
    )
    images = image_catalog.get(normalized_sku, {})
    payload = _product_payload(
        _fields(enriched),
        normalized_sku,
        main_image_url=_text(images.get("mainImageUrl")),
        image_urls=[
            _text(item.get("url"))
            for item in images.get("images", [])
            if _text(item.get("url"))
        ],
    )
    payload.update(
        {
            "productRecordId": str(
                packaging_record.get("recordId")
                or records[0].get("recordId")
                or ""
            ),
            "canAddProductPhotos": (
                not images.get("images")
                and not any(
                    _container_present(
                        packaging_fields.get(f"檔案 {slot} | 容器")
                    )
                    for slot in range(1, 11)
                )
            ),
            "packagingImageUrls": [
                _text(item.get("url"))
                for item in images.get("packagingImages", [])
                if _text(item.get("url"))
            ],
            "productLocation": _text(packaging_fields.get("產品位置")),
            "labelSpecificationBack": _text(
                packaging_fields.get("標籤規格後")
            ),
            "packagingTimePerPackage": _number(
                packaging_fields.get("包裝工時單包")
            ),
            "preparationTimePerPackage": _number(
                packaging_fields.get("準備工時單包")
            ),
            "preparationQuantity": _number(
                packaging_fields.get("準備工時數量")
            ),
            "preparationMinutes": _number(
                packaging_fields.get("準備工時分")
            ),
            "preparationSeconds": _number(
                packaging_fields.get("準備工時秒")
            ),
            "packagingMinutes": _number(
                packaging_fields.get("包裝工時分")
            ),
            "packagingSeconds": _number(
                packaging_fields.get("包裝工時秒")
            ),
            "packagingCheck": _text(packaging_fields.get("包裝檢查")),
            "bomDate": (
                _text(packaging_fields.get("產品 BOM::日期"))
                or _text(payload.get("bomDate"))
            ),
            "bom": [
                _packaging_bom_payload(
                    row,
                    image_url=part_image_catalog.get(
                        _text(row.get("產品 BOM::零件編號")),
                        "",
                    ),
                )
                for row in bom_rows
            ],
        }
    )
    return payload


@router.get("/{order_id}")
async def get_order_detail(
    order_id: str,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> dict[str, Any]:
    normalized_order_id = order_id.strip()
    if not normalized_order_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "Missing orderId"})

    try:
        order_result = await client.find_records(
            ORDER_LAYOUT,
            query={ORDER_ID_FIELD: normalized_order_id},
            limit=1,
        )
        rich_items_result = await client.find_records(
            ORDER_ITEM_LAYOUT,
            query={"ID_出貨單": normalized_order_id},
            limit=500,
        )
        qty_items_result = await client.find_records(
            ORDER_ITEM_QTY_LAYOUT,
            query={"ID_出貨單": normalized_order_id},
            limit=500,
        )
        bom_link_result = (
            await client.find_records(
                settings.filemaker_bom_order_write_layout,
                query={ORDER_ID_FIELD: f"=={normalized_order_id}"},
                limit=1,
            )
            if settings.filemaker_bom_write_enabled
            else {"data": []}
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    order_records = _records(order_result)
    if not order_records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"找不到出貨單：{normalized_order_id}"},
        )

    order_fields = _fields(order_records[0])
    bom_link_records = _records(bom_link_result)
    bom_calculation_id = (
        _text(_fields(bom_link_records[0]).get("ID_BOM計算"))
        if bom_link_records
        else ""
    )
    rich_items = _records(rich_items_result)
    qty_by_id = {
        _text(_fields(record).get("ID")): _fields(record)
        for record in _records(qty_items_result)
        if _text(_fields(record).get("ID"))
    }

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(rich_items, start=1):
        fields = _fields(record)
        item_id = _text(fields.get("ID")) or str(record.get("recordId") or index)
        qty_fields = qty_by_id.get(item_id, {})
        seen_ids.add(item_id)
        items.append(_item_payload(record, fields, qty_fields, {}, index))

    for item_id, qty_fields in qty_by_id.items():
        if item_id in seen_ids:
            continue
        items.append(_item_payload({}, qty_fields, qty_fields, {}, len(items) + 1))

    image_catalog = await _product_cos_image_catalog(
        client,
        storage,
        [_text(item.get("sku")) for item in items],
        primary_only=True,
    )
    for item in items:
        product = image_catalog.get(_text(item.get("sku")), {})
        item["mainImageUrl"] = _text(product.get("mainImageUrl"))
        if not _text(item.get("name")):
            item["name"] = _text(product.get("name"))
        if not _text(item.get("englishName")):
            item["englishName"] = _text(product.get("englishName"))

    try:
        receipt_catalog = await _order_receipt_catalog(
            odata,
            [_text(item.get("id")) for item in items],
            line_skus={
                _text(item.get("id")): _text(item.get("sku"))
                for item in items
                if _text(item.get("id"))
            },
            shipment_id=normalized_order_id,
        )
    except FileMakerODataError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": "读取产品入库时间失败。", "payload": exc.payload},
        ) from exc
    for item in items:
        item["receipt"] = receipt_catalog.get(_text(item.get("id")))

    first_item_fields = _fields(rich_items[0]) if rich_items else {}
    customer = (
        _text(first_item_fields.get("買貨客戶"))
        or _text(first_item_fields.get("公司名稱"))
        or _text(order_fields.get("出貨單_客戶::ID_出貨公司"))
    )

    return {
        "order": {
            "orderId": _text(order_fields.get(ORDER_ID_FIELD)) or normalized_order_id,
            "internalOrderNo": _text(order_fields.get(ORDER_INTERNAL_ID_FIELD)),
            "piNo": _text(order_fields.get("出貨單 PI")),
            "customerPo": _text(order_fields.get("訂單 PO")),
            "customer": customer,
            "orderDate": _text(order_fields.get("修改日期")),
            "shipDate": "",
            "salesOwner": _text(first_item_fields.get("業務員")),
            "status": _text(order_fields.get("包裝狀態")) or "处理中",
            "notes": (
                _text(order_fields.get("shipping_notes"))
                or _text(order_fields.get("客戶備註"))
                or _text(order_fields.get("order_remarks_for_client_only"))
            ),
            "bomCalculationId": bom_calculation_id,
        },
        "items": items,
        "foundCount": len(items),
        "layout": ORDER_LAYOUT,
    }


def _item_payload(
    record: dict[str, Any],
    fields: dict[str, Any],
    qty_fields: dict[str, Any],
    product_fields: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    return {
        "id": _text(fields.get("ID")) or str(record.get("recordId") or index),
        "recordId": str(record.get("recordId") or ""),
        "sku": _text(fields.get("產品編號")) or _text(qty_fields.get("產品編號")),
        "name": (
            _text(fields.get("中文產品名稱"))
            or _text(fields.get("中文名稱"))
            or _text(fields.get("產品名稱"))
            or _text(product_fields.get("產品名稱_中文"))
        ),
        "englishName": (
            _text(fields.get("英文產品名稱"))
            or _text(fields.get("English Name"))
            or _text(fields.get("product_name"))
            or _text(product_fields.get("product_name"))
        ),
        "hasImage": bool(_text(product_fields.get("檔案 1 | 容器"))),
        "client": _text(product_fields.get("Client")),
        "stock": _number(product_fields.get(PRODUCT_STOCK_FIELD)),
        "unitPrice": _number(product_fields.get("產品售價::Price")),
        "systemProductSku": _text(product_fields.get("系統產品編號")),
        "scale": _text(product_fields.get("車子比例")),
        "category": _text(product_fields.get("類別")),
        "auditStatus": _text(product_fields.get("審核")),
        "availability": _text(product_fields.get("有現貨")),
        "moq": _number(product_fields.get("MOQ")),
        "bomCount": _number(product_fields.get("BOM計數")),
        "bomDate": _text(product_fields.get("產品 BOM::日期")),
        "barcode": _text(product_fields.get("條形碼")),
        "labelSpec": _text(product_fields.get("標籤規格")),
        "salesNotes": _text(product_fields.get("銷售紀錄")),
        "vendor": _text(product_fields.get("產品 BOM::廠商")),
        "specification": _text(fields.get("SC編號")) or _text(fields.get("分類包")),
        "quantity": _number(qty_fields.get("數量")),
        "unit": "件",
        "shipDate": "",
    }


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData") if isinstance(record, dict) else {}
    return fields if isinstance(fields, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


async def _order_receipt_catalog(
    odata: FileMakerODataClient,
    line_ids: list[str],
    *,
    line_skus: dict[str, str] | None = None,
    shipment_id: str = "",
) -> dict[str, dict[str, Any]]:
    normalized_ids = list(dict.fromkeys(line_id for line_id in line_ids if line_id))
    rows_by_line = await asyncio.gather(
        *(_completed_receipt_rows(odata, line_id) for line_id in normalized_ids)
    )
    supplemental_catalog = (
        await _supplemental_receipt_catalog(
            odata,
            shipment_id=shipment_id,
            line_ids=normalized_ids,
            line_skus=line_skus or {},
        )
        if shipment_id
        else {}
    )
    catalog: dict[str, dict[str, Any]] = {}
    for line_id, rows in zip(normalized_ids, rows_by_line):
        supplemental_history = supplemental_catalog.get(line_id, [])
        if not rows and not supplemental_history:
            continue
        sorted_receipts = sorted(
            rows,
            key=lambda row: _receipt_timestamp(row.get("创建时间戳")),
            reverse=True,
        )
        order_history = await asyncio.gather(
            *(_receipt_history_item(odata, receipt) for receipt in sorted_receipts)
        )
        history = sorted(
            [*order_history, *supplemental_history],
            key=lambda item: _receipt_timestamp(item.get("receivedAt")),
            reverse=True,
        )
        latest = history[0]
        received_quantity = sum(_number(row.get("數量")) for row in rows)
        catalog[line_id] = {
            "receiptId": latest["receiptId"],
            "quantity": received_quantity,
            "status": latest["status"],
            "receivedAt": latest["receivedAt"],
            "receivedBy": latest["receivedBy"],
            "history": history,
        }
    return catalog


async def _supplemental_receipt_catalog(
    odata: FileMakerODataClient,
    *,
    shipment_id: str,
    line_ids: list[str],
    line_skus: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    escaped_shipment_id = shipment_id.replace("'", "''")
    header_rows = await _paged_odata_rows(
        odata,
        INBOUND_ORDER_TABLE,
        filter_expr=f"對應需求單 eq '{escaped_shipment_id}'",
    )
    headers = [
        row
        for row in header_rows
        if isinstance(row, dict)
        and _text(row.get("概要")).startswith(
            SUPPLEMENTAL_INBOUND_SUMMARY_PREFIX
        )
        and _text(row.get("採購單_ID")).startswith("PDA:")
    ]
    if not headers:
        return {}

    header_by_id = {
        _text(header.get("ID")): header
        for header in headers
        if _text(header.get("ID"))
    }
    details_by_header = await asyncio.gather(
        *(
            _supplemental_inbound_lines(odata, header_id)
            for header_id in header_by_id
        )
    )
    valid_line_ids = set(line_ids)
    catalog: dict[str, list[dict[str, Any]]] = {}
    for header_id, details in zip(header_by_id, details_by_header):
        header = header_by_id[header_id]
        for detail in details:
            source_reference = _text(detail.get("ID_採購單資料"))
            source_line_id = (
                source_reference.removeprefix("PDA:")
                if source_reference.startswith("PDA:")
                else ""
            )
            if source_line_id not in valid_line_ids:
                matching_ids = [
                    line_id
                    for line_id, sku in line_skus.items()
                    if sku and sku == _text(detail.get("零件編號"))
                ]
                source_line_id = matching_ids[0] if len(matching_ids) == 1 else ""
            if source_line_id not in valid_line_ids:
                continue
            catalog.setdefault(source_line_id, []).append(
                await _supplemental_history_item(
                    odata,
                    header=header,
                    detail=detail,
                    source_line_id=source_line_id,
                )
            )
    return catalog


async def _supplemental_inbound_lines(
    odata: FileMakerODataClient,
    inbound_order_id: str,
) -> list[dict[str, Any]]:
    escaped = inbound_order_id.replace("'", "''")
    return await _paged_odata_rows(
        odata,
        INBOUND_ORDER_LINE_TABLE,
        filter_expr=f"ID_入庫單 eq '{escaped}'",
    )


async def _supplemental_history_item(
    odata: FileMakerODataClient,
    *,
    header: dict[str, Any],
    detail: dict[str, Any],
    source_line_id: str,
) -> dict[str, Any]:
    inbound_order_id = _text(header.get("ID"))
    inbound_order_line_id = _text(detail.get("ID"))
    marker = f"PDA_INBOUND_LINE={inbound_order_line_id}"
    escaped_line_id = source_line_id.replace("'", "''")
    inventory_rows = await _paged_odata_rows(
        odata,
        "產品庫存",
        filter_expr=f"ID_出貨單資料 eq '{escaped_line_id}'",
    )
    inventory_row = next(
        (
            row
            for row in inventory_rows
            if marker in _text(row.get("描述"))
        ),
        {},
    )
    description = _text(inventory_row.get("描述"))
    routing_trace = _supplemental_routing_trace(
        description,
        fallback_quantity=_number(detail.get("數量")),
    )
    description = _supplemental_display_remark(description)
    quantity = _number(detail.get("數量"))
    routing_batch_id = _text(header.get("採購單_ID")).removeprefix("PDA:")
    return {
        "receiptId": inbound_order_id,
        "quantity": quantity,
        "status": "追加入库单",
        "receivedAt": format_filemaker_timestamp(header.get("日期")),
        "receivedBy": _text(header.get("修改人")),
        "documentNumber": _text(inventory_row.get("批號")),
        "remark": description or _text(header.get("概要")),
        "routingMode": "supplemental_inbound",
        "orderReceiptQuantity": 0,
        "supplementalQuantity": quantity,
        "inboundOrderId": inbound_order_id,
        "inboundOrderLineId": inbound_order_line_id,
        "routingBatchId": routing_batch_id,
        **routing_trace,
    }


async def _receipt_history_item(
    odata: FileMakerODataClient,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    receipt_id = _text(receipt.get("ID"))
    escaped_receipt_id = receipt_id.replace("'", "''")
    inventory = await odata.records(
        "產品庫存",
        filter_expr=f"ID_出貨單資料入庫 eq '{escaped_receipt_id}'",
        top=10,
        count=False,
    )
    inventory_rows = [
        row for row in inventory.get("rows", []) if isinstance(row, dict)
    ]
    inventory_row = next(
        (
            row
            for row in inventory_rows
            if _text(row.get("ID_出貨單資料入庫")) == receipt_id
        ),
        inventory_rows[0] if inventory_rows else {},
    )
    trace = parse_mobile_receipt_trace(receipt.get("log") or receipt.get("Log"))
    identifiers = (
        trace.get("identifiers")
        if trace and isinstance(trace.get("identifiers"), dict)
        else {}
    )
    routing = (
        trace.get("routing")
        if trace and isinstance(trace.get("routing"), dict)
        else {}
    )
    receipt_quantity = _number(receipt.get("數量"))
    return {
        "receiptId": receipt_id,
        "quantity": receipt_quantity,
        "status": _text(receipt.get("狀態")),
        "receivedAt": format_filemaker_timestamp(receipt.get("创建时间戳")),
        "receivedBy": (
            _text(inventory_row.get("記錄人"))
            or _text(receipt.get("创建人"))
        ),
        "documentNumber": _text(inventory_row.get("批號")),
        "remark": _text(inventory_row.get("描述")),
        "routingMode": "order_receipt",
        "orderReceiptQuantity": receipt_quantity,
        "supplementalQuantity": 0,
        "inboundOrderId": "",
        "inboundOrderLineId": "",
        "routingBatchId": _text(identifiers.get("draftId")),
        "submittedQuantity": _number(
            routing.get("submittedQuantity")
        ) or receipt_quantity,
        "splitOrderReceiptQuantity": _number(
            routing.get("orderReceiptQuantity")
        ) or receipt_quantity,
        "splitSupplementalQuantity": _number(
            routing.get("supplementalQuantity")
        ),
    }


def _supplemental_routing_trace(
    description: str,
    *,
    fallback_quantity: float,
) -> dict[str, float]:
    def marker_value(name: str) -> float:
        match = re.search(rf"(?:^| · ){re.escape(name)}=([0-9]+(?:\.[0-9]+)?)", description)
        return _number(match.group(1)) if match else 0

    supplemental = marker_value("PDA_SUPPLEMENTAL") or fallback_quantity
    submitted = marker_value("PDA_SUBMITTED") or supplemental
    order = marker_value("PDA_ORDER")
    return {
        "submittedQuantity": submitted,
        "splitOrderReceiptQuantity": order,
        "splitSupplementalQuantity": supplemental,
    }


def _supplemental_display_remark(description: str) -> str:
    parts = [part.strip() for part in description.split(" · ") if part.strip()]
    visible = [
        part
        for part in parts
        if not part.startswith(
            (
                "PDA_INBOUND_LINE=",
                "PDA_DRAFT=",
                "PDA_SUBMITTED=",
                "PDA_ORDER=",
                "PDA_SUPPLEMENTAL=",
            )
        )
        and not part.startswith("原始录入 ")
    ]
    return " · ".join(visible)


def _receipt_timestamp(value: Any) -> datetime:
    return parse_filemaker_timestamp(value) or datetime.min.replace(
        tzinfo=FILEMAKER_TIMEZONE
    )


async def _paged_odata_rows(
    odata: FileMakerODataClient,
    table: str,
    *,
    filter_expr: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        result = await odata.records(
            table,
            filter_expr=filter_expr,
            top=10,
            skip=skip,
            count=True,
        )
        page = [row for row in result.get("rows", []) if isinstance(row, dict)]
        rows.extend(page)
        found_count = int(result.get("foundCount") or 0)
        if (
            not page
            or len(page) < 10
            or (found_count > 0 and len(rows) >= found_count)
        ):
            return rows
        skip += len(page)


async def _completed_receipt_rows(
    odata: FileMakerODataClient,
    line_id: str,
) -> list[dict[str, Any]]:
    escaped_line_id = line_id.replace("'", "''")
    filter_expr = (
        f"ID_出庫單資料 eq '{escaped_line_id}' and 狀態 eq '已入庫'"
    )
    rows: list[dict[str, Any]] = []
    skip = 0
    while True:
        result = await odata.records(
            "出貨單資料入庫",
            filter_expr=filter_expr,
            top=10,
            skip=skip,
            count=True,
        )
        page = [
            row for row in result.get("rows", []) if isinstance(row, dict)
        ]
        rows.extend(page)
        found_count = int(result.get("foundCount") or 0)
        if (
            not page
            or len(page) < 10
            or (found_count > 0 and len(rows) >= found_count)
        ):
            return rows
        skip += len(page)


def _product_payload(
    fields: dict[str, Any],
    fallback_sku: str = "",
    *,
    main_image_url: str = "",
    image_urls: list[str] | None = None,
) -> dict[str, Any]:
    resolved_image_urls = image_urls or []
    return {
        "sku": _text(fields.get("product_sku")) or fallback_sku,
        "name": _text(fields.get("產品名稱_中文")),
        "englishName": _text(fields.get("product_name")),
        "hasImage": bool(main_image_url),
        "mainImageUrl": main_image_url,
        "imageUrls": resolved_image_urls,
        "client": _text(fields.get("Client")),
        "stock": _number(fields.get(PRODUCT_STOCK_FIELD)),
        "unitPrice": _number(fields.get("產品售價::Price")),
        "systemProductSku": _text(fields.get("系統產品編號")),
        "scale": _text(fields.get("車子比例")),
        "category": _text(fields.get("類別")),
        "auditStatus": _text(fields.get("審核")),
        "availability": _text(fields.get("有現貨")),
        "moq": _number(fields.get("MOQ")),
        "bomCount": _number(fields.get("BOM計數")),
        "bomDate": _text(fields.get("產品 BOM::日期")),
        "barcode": _text(fields.get("條形碼")),
        "labelSpec": _text(fields.get("標籤規格")),
        "salesNotes": _text(fields.get("銷售紀錄")),
        "vendor": _text(fields.get("產品 BOM::廠商")),
    }


async def _product_cos_image_catalog(
    client: FileMakerClient,
    storage: COSStorageService,
    product_skus: list[str],
    *,
    primary_only: bool = False,
) -> dict[str, dict[str, Any]]:
    """Return signed COS URLs without reading FileMaker container bytes."""
    normalized_skus = list(
        dict.fromkeys(_text(value) for value in product_skus if _text(value))
    )
    if not normalized_skus or not storage.configured:
        return {}

    products: list[dict[str, Any]] = []
    for start in range(0, len(normalized_skus), PRODUCT_ASSET_BATCH_SIZE):
        batch = normalized_skus[start : start + PRODUCT_ASSET_BATCH_SIZE]
        result = await client.find_records(
            PRODUCT_LAYOUT,
            query=[{"product_sku": f"=={sku}"} for sku in batch],
            limit=max(len(batch) * 2, 20),
        )
        products.extend(_records(result))

    source_to_sku: dict[str, str] = {}
    product_summaries: dict[str, dict[str, str]] = {}
    for record in products:
        source_record_id = str(record.get("recordId") or "").strip()
        fields = _fields(record)
        sku = _text(fields.get("product_sku"))
        if source_record_id and sku and sku not in source_to_sku.values():
            source_to_sku[source_record_id] = sku
            product_summaries[sku] = {
                "name": _text(fields.get("產品名稱_中文")),
                "englishName": _text(fields.get("product_name")),
            }
    if not source_to_sku:
        return {}

    asset_records: list[dict[str, Any]] = []
    source_record_ids = list(source_to_sku)
    for start in range(0, len(source_record_ids), PRODUCT_ASSET_BATCH_SIZE):
        batch = source_record_ids[start : start + PRODUCT_ASSET_BATCH_SIZE]
        result = await client.find_records(
            PRODUCT_ASSET_LAYOUT,
            query=[
                {
                    "source_record_id": f"=={source_record_id}",
                    "asset_type": f"=={asset_type}",
                    "migration_status": "==copied",
                }
                for source_record_id in batch
                for asset_type in ("product_image", "packaging_reference")
            ],
            limit=max(len(batch) * 30, 100),
        )
        asset_records.extend(_records(result))

    candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in asset_records:
        fields = _fields(record)
        source_record_id = _text(fields.get("source_record_id"))
        sku = source_to_sku.get(source_record_id, "")
        asset_id = _text(fields.get("id_asset"))
        if not sku or not asset_id:
            continue
        category = _product_asset_category(fields)
        if not category:
            continue
        candidates.setdefault(
            sku,
            {"images": [], "packagingImages": []},
        )[category].append(
            {
                "assetId": asset_id,
                "sourceRecordId": source_record_id,
                "filename": _text(fields.get("original_filename")),
                "mimeType": _text(fields.get("mime_type")) or "image/jpeg",
                "isPrimary": _truthy(fields.get("is_primary")),
                "sortOrder": int(_number(fields.get("sort_order"))),
                "category": category,
            }
        )

    catalog: dict[str, dict[str, Any]] = {
        sku: {
            "mainImageUrl": "",
            "images": [],
            "packagingImages": [],
            "name": summary["name"],
            "englishName": summary["englishName"],
        }
        for sku, summary in product_summaries.items()
    }
    sign_jobs: list[tuple[str, dict[str, Any], Any]] = []
    for sku, categorized in candidates.items():
        product_images = categorized["images"]
        product_images.sort(
            key=lambda item: (
                not item["isPrimary"],
                item["sortOrder"],
                item["assetId"],
            )
        )
        packaging_images = categorized["packagingImages"]
        packaging_images.sort(
            key=lambda item: (item["sortOrder"], item["assetId"])
        )
        selected = (
            product_images[:1]
            if primary_only
            else [*product_images, *packaging_images]
        )
        for image in selected:
            object_key = storage.create_migrated_product_asset_object_key(
                source_record_id=image["sourceRecordId"],
                asset_id=image["assetId"],
                mime_type=image["mimeType"],
                original_filename=image["filename"],
            )
            sign_jobs.append(
                (
                    sku,
                    image,
                    _verified_cos_download(storage, object_key),
                )
            )

    signed_results = await asyncio.gather(
        *(job[2] for job in sign_jobs),
        return_exceptions=True,
    )
    for (sku, image, _job), result in zip(sign_jobs, signed_results):
        if isinstance(result, Exception):
            continue
        url, expires_at = result
        payload = {
            "assetId": image["assetId"],
            "url": url,
            "filename": image["filename"],
            "isPrimary": image["isPrimary"],
            "sortOrder": image["sortOrder"],
            "expiresAt": expires_at.isoformat(),
        }
        entry = catalog.setdefault(
            sku,
            {
                "mainImageUrl": "",
                "images": [],
                "packagingImages": [],
                "name": "",
                "englishName": "",
            },
        )
        entry[image["category"]].append(payload)
        if image["category"] == "images" and not entry["mainImageUrl"]:
            entry["mainImageUrl"] = url
    return catalog


async def _verified_cos_download(
    storage: COSStorageService,
    object_key: str,
) -> tuple[str, Any]:
    await run_in_threadpool(storage.head_object, object_key)
    return await run_in_threadpool(storage.create_presigned_download, object_key)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"1", "true", "yes", "y", "是"}


def _product_asset_category(fields: dict[str, Any]) -> str:
    asset_type = _text(fields.get("asset_type"))
    if asset_type == "packaging_reference":
        return "packagingImages"
    legacy_field = _text(fields.get("legacy_source_field"))
    match = re.fullmatch(r"檔案\s+(\d+)\s+\|\s+容器", legacy_field)
    if match:
        slot = int(match.group(1))
        if 1 <= slot <= 10:
            return "images"
        if 11 <= slot <= 15:
            return "packagingImages"
        return ""
    return "images" if asset_type in {"", "product_image"} else ""


def _packaging_bom_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    portal_data = record.get("portalData") if isinstance(record, dict) else {}
    rows = portal_data.get("產品 BOM") if isinstance(portal_data, dict) else []
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _packaging_bom_payload(
    row: dict[str, Any],
    *,
    image_url: str,
) -> dict[str, Any]:
    return {
        "id": str(row.get("recordId") or ""),
        "partNumber": _text(row.get("產品 BOM::零件編號")),
        "partName": _text(row.get("产品BOM_零件::part_name_internal")),
        "requiredQuantity": _number(row.get("產品 BOM::需求數量")),
        "warehouseLocation": _text(
            row.get("产品BOM_零件::warehouse_location_primary")
        ),
        "stock": _number(row.get("产品BOM_零件::stock_on_hand_qty")),
        "subPackage": _text(row.get("產品 BOM::分包")),
        "imageUrl": image_url,
    }


async def _part_cos_image_catalog(
    client: FileMakerClient,
    storage: COSStorageService,
    part_numbers: list[str],
) -> dict[str, str]:
    normalized = list(
        dict.fromkeys(_text(value) for value in part_numbers if _text(value))
    )
    if not normalized or not storage.configured:
        return {}
    parts: list[dict[str, Any]] = []
    for start in range(0, len(normalized), PRODUCT_ASSET_BATCH_SIZE):
        batch = normalized[start : start + PRODUCT_ASSET_BATCH_SIZE]
        result = await client.find_records(
            PART_ASSET_SOURCE_LAYOUT,
            query=[{"part_number": f"=={part_number}"} for part_number in batch],
            limit=max(len(batch) * 2, 20),
        )
        parts.extend(_records(result))
    part_id_to_number: dict[str, str] = {}
    for part in parts:
        fields = _fields(part)
        part_id = _text(fields.get("part_id"))
        part_number = _text(fields.get("part_number"))
        if part_id and part_number:
            part_id_to_number[part_id] = part_number
    if not part_id_to_number:
        return {}

    assets: list[dict[str, Any]] = []
    part_ids = list(part_id_to_number)
    for start in range(0, len(part_ids), PRODUCT_ASSET_BATCH_SIZE):
        batch = part_ids[start : start + PRODUCT_ASSET_BATCH_SIZE]
        result = await client.find_records(
            "PartAssets",
            query=[
                {
                    "part_id_fk": f"=={part_id}",
                    "asset_type": "==part_image",
                    "status": "==READY",
                }
                for part_id in batch
            ],
            limit=max(len(batch) * 10, 100),
            sort=[
                {"fieldName": "is_primary", "sortOrder": "descend"},
                {"fieldName": "sort_order", "sortOrder": "ascend"},
            ],
        )
        assets.extend(_records(result))

    candidates: dict[str, dict[str, Any]] = {}
    for asset in assets:
        fields = _fields(asset)
        part_id = _text(fields.get("part_id_fk"))
        object_key = _text(fields.get("object_key"))
        if not part_id or not object_key or part_id in candidates:
            continue
        candidates[part_id] = {
            "objectKey": object_key,
            "isPrimary": _truthy(fields.get("is_primary")),
            "sortOrder": int(_number(fields.get("sort_order"))),
        }

    jobs = [
        (part_id, _verified_cos_download(storage, item["objectKey"]))
        for part_id, item in candidates.items()
    ]
    results = await asyncio.gather(
        *(job[1] for job in jobs),
        return_exceptions=True,
    )
    catalog: dict[str, str] = {}
    for (part_id, _job), result in zip(jobs, results):
        if isinstance(result, Exception):
            continue
        url, _expires_at = result
        catalog[part_id_to_number[part_id]] = url
    return catalog


def _container_present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_text(value.get(key)) for key in ("url", "data", "value"))
    return bool(value)


def _part_payload(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "partNo": _text(fields.get("part_number")),
        "partName": _text(fields.get("part_name")),
        "englishName": _text(fields.get("English Name")),
        "externalName": _text(fields.get("part_name_對外")),
        "stock": _number(fields.get("current_stock")),
        "supplyStatus": _text(fields.get("供應狀況")),
        "status": _text(fields.get("狀態")),
        "auditStatus": _text(fields.get("審核")),
        "partType": _text(fields.get("零件性質")),
        "supplier": _text(fields.get("零件_S廠商::廠商名稱")),
        "buyer": _text(fields.get("採購員")),
        "warehouseDivision": _text(fields.get("倉庫分工")),
        "department": _text(fields.get("部門分工")),
        "customer": _text(fields.get("專屬客戶")) or _text(fields.get("零件_客戶::客戶公司簡稱")),
        "turnoverTime": _number(fields.get("Turnover Time")),
        "position1": _text(fields.get("位置")),
        "position2": _text(fields.get("位置2")),
        "hasImage": bool(_text(fields.get("影像 | 容器")) or _text(fields.get("圖面 | 容器"))),
    }

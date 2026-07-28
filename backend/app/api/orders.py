from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, Response
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
    get_operator_context,
    get_settings,
    get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.internal_order_merge import (
    InternalOrderMergeError,
    merge_internal_orders_via_data_api,
    preview_internal_orders_via_data_api,
)
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
) -> Response:
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
        image_url = _text(fields.get("影像 | 容器")) or _text(fields.get("圖面 | 容器"))
        if not image_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "零件没有图片"})
        content, content_type = await _download_container(client, image_url)
        return Response(
            content=content,
            media_type=content_type or "image/jpeg",
            headers={"Cache-Control": "private, max-age=1800"},
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
) -> Response:
    try:
        product_result = await client.find_records(
            PRODUCT_LAYOUT,
            query={"product_sku": f"=={product_sku.strip()}"},
            limit=1,
        )
        product_records = _records(product_result)
        image_url = _text(_fields(product_records[0]).get("檔案 1 | 容器")) if product_records else ""
        if not image_url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "产品没有图片"})
        content, content_type = await _download_container(client, image_url)
        return Response(
            content=content,
            media_type=content_type or "image/jpeg",
            headers={"Cache-Control": "private, max-age=1800"},
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
) -> dict[str, Any]:
    normalized_sku = product_sku.strip()
    if not normalized_sku:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "Missing productSku"})
    try:
        result = await client.find_records(
            PRODUCT_LAYOUT,
            query={"product_sku": f"=={normalized_sku}"},
            limit=1,
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
    return _product_payload(_fields(enriched), normalized_sku)


@router.get("/{order_id}")
async def get_order_detail(
    order_id: str,
    _operator: OperatorContext = Depends(get_operator_context),
    client: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
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


def _product_payload(fields: dict[str, Any], fallback_sku: str = "") -> dict[str, Any]:
    return {
        "sku": _text(fields.get("product_sku")) or fallback_sku,
        "name": _text(fields.get("產品名稱_中文")),
        "englishName": _text(fields.get("product_name")),
        "hasImage": bool(_text(fields.get("檔案 1 | 容器"))),
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


async def _download_container(client: FileMakerClient, url: str) -> tuple[bytes, str]:
    source_host = urlparse(client.settings.filemaker_host).hostname
    target_host = urlparse(url).hostname
    if not source_host or target_host != source_host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"message": "无效的图片地址"})

    token = await client.get_token()
    async with httpx.AsyncClient(
        timeout=client.settings.filemaker_timeout_seconds,
        verify=client.settings.filemaker_ssl_verify,
        follow_redirects=True,
    ) as image_client:
        response = await image_client.get(url, headers={"Authorization": f"Bearer {token}"})
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": f"FileMaker 图片读取失败：HTTP {response.status_code}"},
        )
    return response.content, response.headers.get("content-type", "image/jpeg").split(";", 1)[0]

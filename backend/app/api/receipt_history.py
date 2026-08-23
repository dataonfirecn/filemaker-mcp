from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.concurrency import run_in_threadpool

from app.api.orders import _product_cos_image_catalog
from app.models.receipt_history import (
    ReceiptHistoryEntry,
    ReceiptHistoryInventoryMovement,
    ReceiptHistoryLine,
    ReceiptHistoryPhoto,
    ReceiptHistoryResponse,
    ReceiptHistorySummary,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
    get_receipt_attachment_store,
    get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
    odata_key_literal,
)
from app.services.filemaker_timestamps import (
    FILEMAKER_TIMEZONE,
    format_filemaker_timestamp,
    parse_filemaker_timestamp,
)
from app.services.mobile_receipt_trace import parse_mobile_receipt_trace
from app.services.product_api import PRODUCT_LAYOUT, PRODUCT_STOCK_FIELD
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)


router = APIRouter(prefix="/orders/receipt-history", tags=["receipt-history"])

SOURCE_TABLE = "出貨單資料"
RECEIPT_TABLE = "出貨單資料入庫"
INVENTORY_TABLE = "產品庫存"
ORDER_LAYOUT = "@出貨單"
COMPLETED_STATUS = "已入庫"


@router.get("/{line_id}", response_model=ReceiptHistoryResponse)
async def get_receipt_history(
    line_id: str = Path(min_length=1, max_length=160),
    session_context: dict = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    attachments: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    storage: COSStorageService = Depends(get_cos_storage_service),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ReceiptHistoryResponse:
    normalized_line_id = line_id.strip()
    bound_line_id = _text(session_context.get("lineId"))
    if bound_line_id and bound_line_id != normalized_line_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "当前 WebViewer 会话不能查看其他出货单明细。"},
        )

    source = await _source_record(odata, normalized_line_id)
    order_id = _text(source.get("ID_出貨單"))
    product_sku = _text(source.get("產品編號"))

    order_result, product_result, receipt_rows, inventory_rows, photo_rows = (
        await asyncio.gather(
            _find_optional(
                filemaker,
                ORDER_LAYOUT,
                {"id": f"=={order_id}"},
            ),
            _find_optional(
                filemaker,
                PRODUCT_LAYOUT,
                {"product_sku": f"=={product_sku}"},
            ),
            _odata_rows(
                odata,
                RECEIPT_TABLE,
                f"ID_出庫單資料 eq '{_odata_text(normalized_line_id)}'",
                top=100,
            ),
            _odata_rows(
                odata,
                INVENTORY_TABLE,
                f"ID_出貨單資料 eq '{_odata_text(normalized_line_id)}'",
                top=200,
            ),
            attachments.list_for_history(
                line_id=normalized_line_id,
                shipment_id=order_id,
                limit=100,
            ),
        )
    )

    order_fields = _first_fields(order_result)
    product_fields = _first_fields(product_result)
    image_catalog = await _safe_product_image_catalog(
        filemaker,
        storage,
        product_sku,
    )
    product_images = image_catalog.get(product_sku, {})

    photos = await _photo_payloads(photo_rows, storage)
    movements = [_inventory_payload(row) for row in inventory_rows]
    movements_by_receipt: dict[str, list[ReceiptHistoryInventoryMovement]] = (
        defaultdict(list)
    )
    for movement in movements:
        movements_by_receipt[movement.receipt_id].append(movement)

    receipt_entries = [
        _receipt_payload(row, movements_by_receipt.get(_text(row.get("ID")), []))
        for row in receipt_rows
    ]
    receipt_entries.sort(key=lambda item: _timestamp(item.received_at), reverse=True)

    completed = [
        entry for entry in receipt_entries if entry.status == COMPLETED_STATUS
    ]
    order_reference_quantity = _number(source.get("數量"))
    official_received_quantity = sum(item.quantity for item in completed)
    current_received_quantity = _number(source.get("實際包裝數量"))
    line = ReceiptHistoryLine(
        lineId=normalized_line_id,
        orderId=order_id,
        documentNumber=_text(order_fields.get("internal_id")),
        piNumber=(
            _text(order_fields.get("出貨單 PI"))
            or _text(order_fields.get("id"))
            or order_id
        ),
        customerPo=_text(order_fields.get("訂單 PO")),
        customer=(
            _text(source.get("公司名稱"))
            or _text(order_fields.get("出貨單_客戶::ID_出貨公司"))
        ),
        salesOwner=_text(source.get("業務員")),
        productSku=product_sku,
        productName=(
            _text(source.get("中文產品名稱"))
            or _text(source.get("中文名稱"))
            or _text(source.get("產品名稱"))
            or _text(product_fields.get("產品名稱_中文"))
            or _text(product_images.get("name"))
        ),
        englishName=(
            _text(product_fields.get("product_name"))
            or _text(product_images.get("englishName"))
        ),
        mainImageUrl=_text(product_images.get("mainImageUrl")),
        orderReferenceQuantity=order_reference_quantity,
        currentReceivedQuantity=current_received_quantity,
        currentStock=_number(product_fields.get(PRODUCT_STOCK_FIELD)),
        packagingStatus=_text(source.get("包裝進度")),
        packagingOperator=_text(source.get("包裝員")),
        sourceCreatedAt=_text(source.get("created_at")),
        sourceUpdatedAt=_text(source.get("updated_at")),
    )
    summary = ReceiptHistorySummary(
        receiptCount=len(receipt_entries),
        completedReceiptCount=len(completed),
        officialReceivedQuantity=official_received_quantity,
        orderReferenceQuantity=order_reference_quantity,
        differenceFromOrder=official_received_quantity - order_reference_quantity,
        inventoryMovementCount=len(movements),
        photoCount=len(photos),
        fullyTraceable=bool(completed) and all(item.traceable for item in completed),
    )
    response = ReceiptHistoryResponse(
        line=line,
        summary=summary,
        receipts=receipt_entries,
        photos=photos,
        readOnly=True,
    )
    await audit_log.record(
        operator=operator,
        action_type="READ_PDA_RECEIPT_HISTORY",
        status="success",
        target_layout=RECEIPT_TABLE,
        order_id=order_id or None,
        product_sku=product_sku or None,
        request_payload={"lineId": normalized_line_id},
        response_payload={
            "receiptCount": summary.receipt_count,
            "inventoryMovementCount": summary.inventory_movement_count,
            "photoCount": summary.photo_count,
            "fullyTraceable": summary.fully_traceable,
        },
    )
    return response


async def _source_record(
    odata: FileMakerODataClient,
    line_id: str,
) -> dict[str, Any]:
    path = (
        f"/{quote(SOURCE_TABLE, safe='')}"
        f"({odata_key_literal(line_id)})"
    )
    try:
        payload = await odata.request(path)
    except FileMakerODataError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "找不到这条出货单资料。"},
            ) from exc
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": "无法读取出货单资料。", "payload": exc.payload},
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "FileMaker 返回的出货单资料格式不正确。"},
        )
    return payload


async def _find_optional(
    filemaker: FileMakerClient,
    layout: str,
    query: dict[str, Any],
) -> dict[str, Any]:
    try:
        return await filemaker.find_records(layout, query=query, limit=1)
    except FileMakerAPIError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return {"data": []}
        raise


async def _odata_rows(
    odata: FileMakerODataClient,
    table: str,
    filter_expr: str,
    *,
    top: int,
) -> list[dict[str, Any]]:
    try:
        result = await odata.records(
            table,
            filter_expr=filter_expr,
            top=top,
            count=False,
        )
    except FileMakerODataError as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return []
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": f"无法读取 {table}。", "payload": exc.payload},
        ) from exc
    return [row for row in result.get("rows", []) if isinstance(row, dict)]


async def _safe_product_image_catalog(
    filemaker: FileMakerClient,
    storage: COSStorageService,
    product_sku: str,
) -> dict[str, dict[str, Any]]:
    if not product_sku:
        return {}
    try:
        return await _product_cos_image_catalog(
            filemaker,
            storage,
            [product_sku],
            primary_only=True,
        )
    except (FileMakerAPIError, COSStorageError):
        return {}


async def _photo_payloads(
    rows: list[ReceiptAttachmentRecord],
    storage: COSStorageService,
) -> list[ReceiptHistoryPhoto]:
    payloads: list[ReceiptHistoryPhoto] = []
    for row in rows:
        url = ""
        if storage.configured and row.status in {"UPLOADED", "BOUND"}:
            try:
                url, _expires_at = await run_in_threadpool(
                    storage.create_presigned_download,
                    row.object_key,
                )
            except COSStorageError:
                url = ""
        payloads.append(
            ReceiptHistoryPhoto(
                attachmentId=row.attachment_id,
                draftId=row.draft_id,
                scope="product" if row.line_id else "shipment",
                source=row.source,
                filename=row.original_filename,
                mimeType=row.mime_type,
                fileSize=row.file_size,
                status=row.status,
                uploadedAt=(row.uploaded_at or row.created_at).isoformat(),
                operatorAccount=row.operator_account,
                url=url,
            )
        )
    return payloads


def _inventory_payload(row: dict[str, Any]) -> ReceiptHistoryInventoryMovement:
    return ReceiptHistoryInventoryMovement(
        recordKey=_odata_record_key(row),
        receiptId=_text(row.get("ID_出貨單資料入庫")),
        lineId=_text(row.get("ID_出貨單資料")),
        productSku=_text(row.get("ID_產品編號")),
        date=_text(row.get("日期")),
        batchNumber=_text(row.get("批號")),
        description=_text(row.get("描述")),
        inboundQuantity=_number(row.get("入庫數量")),
        outboundQuantity=_number(row.get("出庫數量")),
        operator=_text(row.get("記錄人")),
    )


def _receipt_payload(
    row: dict[str, Any],
    movements: list[ReceiptHistoryInventoryMovement],
) -> ReceiptHistoryEntry:
    received_by = next((item.operator for item in movements if item.operator), "")
    trace = parse_mobile_receipt_trace(row.get("log") or row.get("Log"))
    identifiers = (
        trace.get("identifiers")
        if trace and isinstance(trace.get("identifiers"), dict)
        else {}
    )
    source = (
        trace.get("source")
        if trace and isinstance(trace.get("source"), dict)
        else {}
    )
    trace_operator = (
        trace.get("operator")
        if trace and isinstance(trace.get("operator"), dict)
        else {}
    )
    trace_attachments = (
        trace.get("attachments")
        if trace and isinstance(trace.get("attachments"), dict)
        else {}
    )
    inventory_traceable = any(
        item.receipt_id == _text(row.get("ID"))
        and item.line_id == _text(row.get("ID_出庫單資料"))
        for item in movements
    )
    return ReceiptHistoryEntry(
        receiptId=_text(row.get("ID")),
        status=_text(row.get("狀態")),
        quantity=_number(row.get("數量")),
        receivedAt=(
            format_filemaker_timestamp(row.get("创建时间戳"))
            or _text(row.get("日期"))
        ),
        receivedBy=received_by or _text(row.get("创建人")),
        createdBy=_text(row.get("创建人")),
        modifiedAt=format_filemaker_timestamp(row.get("修改时间戳")),
        modifiedBy=_text(row.get("修改人")),
        logAvailable=trace is not None,
        sourceChannel=_text(source.get("channel")),
        sourceApplication=_text(source.get("application")),
        appVersion=_text(source.get("appVersion")),
        appBuild=_text(source.get("appBuild")),
        draftId=_text(identifiers.get("draftId")),
        operatorAccount=_text(trace_operator.get("account")),
        operatorName=_text(trace_operator.get("name")),
        operatorPrivilege=_text(trace_operator.get("privilege")),
        linePhotoCount=int(_number(trace_attachments.get("linePhotoCount"))),
        shipmentPhotoCount=int(_number(
            trace_attachments.get("shipmentPhotoCount")
        )),
        traceLog=trace,
        traceable=inventory_traceable and trace is not None,
        inventoryMovements=movements,
    )


def _first_fields(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("data") if isinstance(result, dict) else []
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return {}
    fields = rows[0].get("fieldData")
    return fields if isinstance(fields, dict) else {}


def _odata_record_key(row: dict[str, Any]) -> str:
    raw = _text(row.get("@id") or row.get("@editLink"))
    match = re.search(r"\(([^()]*)\)$", raw)
    if not match:
        return ""
    return match.group(1).strip("'")


def _odata_text(value: str) -> str:
    return value.replace("'", "''")


def _timestamp(value: str) -> datetime:
    return parse_filemaker_timestamp(value) or datetime.min.replace(
        tzinfo=FILEMAKER_TIMEZONE
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float:
    try:
        return float(str(value or 0).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0

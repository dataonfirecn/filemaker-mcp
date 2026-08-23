import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.mobile_receipts import (
    AttachmentCompleteRequest,
    AttachmentDownloadResponse,
    AttachmentPresignRequest,
    AttachmentPresignResponse,
    AttachmentResponse,
    ReceiptSubmissionLine,
    ReceiptSubmissionLineResponse,
    ReceiptSubmissionRequest,
    ReceiptSubmissionResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.cos_storage import COSStorageError, COSStorageService, new_attachment_id
from app.services.dependencies import (
    get_audit_log_store,
    get_cos_storage_service,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_operator_context,
    get_receipt_attachment_store,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
)
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)


router = APIRouter(prefix="/mobile/v1/receipts", tags=["mobile-receipts"])
DraftID = Path(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
ORDER_LAYOUT = "@出貨單"
ORDER_ITEM_LAYOUT = "@出貨單資料"
RECEIPT_TABLE = "出貨單資料入庫"
INVENTORY_TABLE = "產品庫存"
ORDER_ITEM_TABLE = "出貨單資料"
RECEIPT_COMPLETE_STATUS = "已入庫"
RECEIPT_PENDING_STATUS = "未入庫"
_receipt_line_locks: dict[str, asyncio.Lock] = {}
_receipt_line_locks_guard = asyncio.Lock()


@router.post(
    "/{draft_id}/attachments/presign",
    response_model=AttachmentPresignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_attachment_presign(
    body: AttachmentPresignRequest,
    draft_id: str = DraftID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> AttachmentPresignResponse:
    _require_cos(settings, storage)
    if body.mime_type not in settings.cos_allowed_content_type_set:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "message": "不支持此图片格式。",
                "allowedContentTypes": sorted(settings.cos_allowed_content_type_set),
            },
        )
    if body.file_size > settings.cos_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "message": "图片超过上传大小限制。",
                "maxBytes": settings.cos_max_upload_bytes,
            },
        )
    line_limit = 6 if body.line_id else 1
    line_active_count = await attachment_store.count_active_for_line(
        draft_id,
        operator.account,
        body.line_id,
    )
    if line_active_count >= line_limit:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "每个产品最多上传 6 张收货图片。"
                    if body.line_id
                    else "每张入库记录最多上传 1 张出货照片。"
                ),
                "maximum": line_limit,
            },
        )
    active_count = await attachment_store.count_active(draft_id, operator.account)
    if active_count >= settings.cos_max_attachments_per_receipt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "当前到货单照片数量已达到上限。",
                "maximum": settings.cos_max_attachments_per_receipt,
            },
        )

    attachment_id = new_attachment_id()
    object_key = storage.create_object_key(
        draft_id=draft_id,
        shipment_id=body.shipment_id,
        attachment_id=attachment_id,
        mime_type=body.mime_type,
    )
    try:
        presigned = await run_in_threadpool(
            storage.create_presigned_upload,
            object_key=object_key,
            content_type=body.mime_type,
        )
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc

    record = ReceiptAttachmentRecord(
        attachment_id=attachment_id,
        draft_id=draft_id,
        shipment_id=body.shipment_id,
        pi_number=body.pi_number,
        line_id=body.line_id,
        object_key=object_key,
        original_filename=body.filename,
        mime_type=body.mime_type,
        file_size=body.file_size,
        sha256=body.sha256,
        source=body.source,
        operator_account=operator.account,
        status="PENDING",
        etag=None,
        created_at=datetime.now(timezone.utc),
        uploaded_at=None,
    )
    await attachment_store.create(record)
    await audit_log.record(
        operator=operator,
        action_type="RECEIPT_ATTACHMENT_PRESIGN",
        status="success",
        order_id=body.pi_number,
        request_payload={
            "draftId": draft_id,
            "shipmentId": body.shipment_id,
            "lineId": body.line_id,
            "mimeType": body.mime_type,
            "fileSize": body.file_size,
            "source": body.source,
        },
        response_payload={
            "attachmentId": attachment_id,
            "objectKey": object_key,
            "expiresAt": presigned.expires_at.isoformat(),
        },
    )
    return AttachmentPresignResponse(
        attachmentId=attachment_id,
        objectKey=object_key,
        uploadUrl=presigned.upload_url,
        headers=presigned.headers,
        expiresAt=presigned.expires_at,
    )


@router.post(
    "/{draft_id}/attachments/{attachment_id}/complete",
    response_model=AttachmentResponse,
)
async def complete_attachment_upload(
    body: AttachmentCompleteRequest,
    draft_id: str = DraftID,
    attachment_id: str = Path(min_length=5, max_length=80),
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> AttachmentResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        attachment_store,
        draft_id=draft_id,
        attachment_id=attachment_id,
        operator_account=operator.account,
    )
    if record.status == "UPLOADED":
        return _response(record)
    if record.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": f"附件当前状态不能完成上传：{record.status}"},
        )
    if body.file_size != record.file_size or body.sha256 != record.sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "上传完成信息与申请上传时不一致。"},
        )

    try:
        metadata = await run_in_threadpool(storage.head_object, record.object_key)
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc)},
        ) from exc
    if metadata.content_length != record.file_size:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的文件大小与申请上传时不一致。"},
        )
    if metadata.content_type != record.mime_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 中的文件类型与申请上传时不一致。"},
        )
    request_etag = body.etag.strip().strip('"').lower()
    if request_etag and request_etag != metadata.etag.lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "COS 返回的 ETag 与客户端上传结果不一致。"},
        )

    updated = await attachment_store.mark_uploaded(
        attachment_id,
        etag=metadata.etag,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "附件记录不存在。"},
        )
    await audit_log.record(
        operator=operator,
        action_type="RECEIPT_ATTACHMENT_UPLOADED",
        status="success",
        order_id=record.pi_number,
        request_payload={
            "draftId": draft_id,
            "attachmentId": attachment_id,
            "fileSize": body.file_size,
        },
        response_payload={
            "objectKey": record.object_key,
            "etag": metadata.etag,
        },
    )
    return _response(updated)


@router.get(
    "/{draft_id}/attachments/{attachment_id}/download-url",
    response_model=AttachmentDownloadResponse,
)
async def get_attachment_download_url(
    draft_id: str = DraftID,
    attachment_id: str = Path(min_length=5, max_length=80),
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
) -> AttachmentDownloadResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        attachment_store,
        draft_id=draft_id,
        attachment_id=attachment_id,
        operator_account=operator.account,
    )
    if record.status not in {"UPLOADED", "BOUND"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "附件尚未上传完成。"},
        )
    try:
        url, expires_at = await run_in_threadpool(
            storage.create_presigned_download,
            record.object_key,
        )
    except COSStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": str(exc)},
        ) from exc
    return AttachmentDownloadResponse(downloadUrl=url, expiresAt=expires_at)


@router.post(
    "/{draft_id}/submit",
    response_model=ReceiptSubmissionResponse,
)
async def submit_receipt_lines(
    body: ReceiptSubmissionRequest,
    draft_id: str = DraftID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ReceiptSubmissionResponse:
    if not settings.filemaker_mobile_receipt_write_enabled:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={"message": "PDA 成品入库写入尚未启用。"},
        )
    if body.draft_id != draft_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "提交内容的 draftId 与地址不一致。"},
        )

    source_records, all_source_records = await _validated_source_records(
        filemaker,
        body,
    )
    await _validate_submission_attachments(
        attachment_store,
        body=body,
        draft_id=draft_id,
        operator=operator,
    )

    line_results: list[ReceiptSubmissionLineResponse] = []
    for line in body.lines:
        lock = await _line_lock(line.line_id)
        async with lock:
            line_results.append(
                await _write_or_repair_line_receipt(
                    odata,
                    line=line,
                    source_record=source_records[line.line_id],
                    body=body,
                    operator=operator,
                )
            )
        for attachment_id in line.attachment_ids:
            await attachment_store.mark_bound(attachment_id)

    for attachment_id in body.shipment_attachment_ids:
        await attachment_store.mark_bound(attachment_id)

    receipt_catalog = await _receipt_catalog(
        odata,
        [_field_data(record).get("ID", "") for record in all_source_records],
    )
    total_line_count = len(all_source_records)
    received_line_count = len(receipt_catalog)
    all_lines_received = total_line_count > 0 and received_line_count == total_line_count
    completed_at = datetime.now(timezone.utc)
    aggregate_receipt_id = (
        line_results[0].receipt_id
        if len(line_results) == 1
        else f"receipt-{draft_id}"
    )

    await audit_log.record(
        operator=operator,
        action_type="MOBILE_FINISHED_GOODS_RECEIPT",
        status="success",
        order_id=body.shipment_id,
        request_payload={
            "draftId": draft_id,
            "shipmentId": body.shipment_id,
            "documentNumber": body.document_number,
            "lines": [
                {
                    "lineId": line.line_id,
                    "recordId": line.record_id,
                    "sku": line.sku,
                    "quantity": line.received_quantity,
                }
                for line in body.lines
            ],
        },
        response_payload={
            "receiptIds": [line.receipt_id for line in line_results],
            "receivedLineCount": received_line_count,
            "totalLineCount": total_line_count,
            "allLinesReceived": all_lines_received,
        },
    )
    return ReceiptSubmissionResponse(
        receiptId=aggregate_receipt_id,
        status="sealed" if all_lines_received else "partial",
        sealedAt=completed_at,
        allLinesReceived=all_lines_received,
        receivedLineCount=received_line_count,
        totalLineCount=total_line_count,
        lines=line_results,
    )


def _require_cos(settings: Settings, storage: COSStorageService) -> None:
    if not settings.cos_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 附件上传尚未启用。"},
        )
    if not storage.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "COS 密钥或存储桶配置不完整。"},
        )


async def _owned_record(
    store: ReceiptAttachmentStore,
    *,
    draft_id: str,
    attachment_id: str,
    operator_account: str,
) -> ReceiptAttachmentRecord:
    record = await store.get(attachment_id)
    if (
        not record
        or record.draft_id != draft_id
        or record.operator_account != operator_account
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "附件记录不存在。"},
        )
    return record


def _response(record: ReceiptAttachmentRecord) -> AttachmentResponse:
    return AttachmentResponse(
        attachmentId=record.attachment_id,
        draftId=record.draft_id,
        shipmentId=record.shipment_id,
        piNumber=record.pi_number,
        lineId=record.line_id,
        objectKey=record.object_key,
        mimeType=record.mime_type,
        fileSize=record.file_size,
        sha256=record.sha256,
        etag=record.etag,
        source=record.source,
        status=record.status,
        createdAt=record.created_at,
        uploadedAt=record.uploaded_at,
    )


async def _validated_source_records(
    filemaker: FileMakerClient,
    body: ReceiptSubmissionRequest,
) -> tuple[dict[str, dict], list[dict]]:
    try:
        order_result, requested_result, all_result = await asyncio.gather(
            filemaker.find_records(
                ORDER_LAYOUT,
                query={"id": f"=={body.shipment_id}"},
                limit=1,
            ),
            filemaker.find_records(
                ORDER_ITEM_LAYOUT,
                query=[{"ID": f"=={line.line_id}"} for line in body.lines],
                limit=len(body.lines),
            ),
            filemaker.find_records(
                ORDER_ITEM_LAYOUT,
                query={"ID_出貨單": f"=={body.shipment_id}"},
                limit=500,
            ),
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": str(exc), "payload": exc.payload},
        ) from exc

    if not order_result.get("data"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": f"找不到出货单：{body.shipment_id}"},
        )

    requested_records = requested_result.get("data") or []
    records_by_id = {
        _text(_field_data(record).get("ID")): record
        for record in requested_records
        if _text(_field_data(record).get("ID"))
    }
    for line in body.lines:
        record = records_by_id.get(line.line_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": f"找不到产品明细：{line.line_id}"},
            )
        fields = _field_data(record)
        if _text(fields.get("ID_出貨單")) != body.shipment_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": f"{line.sku} 不属于当前出货单。"},
            )
        if str(record.get("recordId") or "") != line.record_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": f"{line.sku} 的 FileMaker recordId 已变化，请重新扫码。"},
            )
        if _text(fields.get("產品編號")) != line.sku:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": f"{line.line_id} 的 SKU 已变化，请重新扫码。"},
            )

    all_records = all_result.get("data") or []
    return records_by_id, all_records


async def _validate_submission_attachments(
    store: ReceiptAttachmentStore,
    *,
    body: ReceiptSubmissionRequest,
    draft_id: str,
    operator: OperatorContext,
) -> None:
    expected_lines = {
        attachment_id: line.line_id
        for line in body.lines
        for attachment_id in line.attachment_ids
    }
    expected_lines.update(
        {attachment_id: None for attachment_id in body.shipment_attachment_ids}
    )
    for attachment_id, expected_line_id in expected_lines.items():
        record = await store.get(attachment_id)
        if (
            not record
            or record.draft_id != draft_id
            or record.shipment_id != body.shipment_id
            or record.operator_account != operator.account
            or record.line_id != expected_line_id
            or record.status not in {"UPLOADED", "BOUND"}
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": f"附件尚未上传或不属于当前产品：{attachment_id}"},
            )


async def _write_or_repair_line_receipt(
    odata: FileMakerODataClient,
    *,
    line: ReceiptSubmissionLine,
    source_record: dict,
    body: ReceiptSubmissionRequest,
    operator: OperatorContext,
) -> ReceiptSubmissionLineResponse:
    existing_rows = await _line_receipts(odata, line.line_id)
    completed = _latest_receipt(existing_rows, RECEIPT_COMPLETE_STATUS)
    if completed:
        return await _receipt_response(
            odata,
            completed,
            line=line,
            already_received=True,
        )

    pending = _latest_receipt(existing_rows, RECEIPT_PENDING_STATUS)
    receipt_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    if pending:
        receipt_id = _text(pending.get("ID"))
        await odata.update_record(
            RECEIPT_TABLE,
            receipt_id,
            {
                "數量": line.received_quantity,
                "日期": receipt_date,
            },
        )
    else:
        created = await odata.create_record(
            RECEIPT_TABLE,
            {
                "ID_出庫單資料": line.line_id,
                "日期": receipt_date,
                "數量": line.received_quantity,
                "狀態": RECEIPT_PENDING_STATUS,
            },
        )
        receipt_id = _text(created.get("ID"))
        if not receipt_id:
            pending_rows = await _line_receipts(odata, line.line_id)
            pending = _latest_receipt(pending_rows, RECEIPT_PENDING_STATUS)
            receipt_id = _text((pending or {}).get("ID"))
        if not receipt_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": f"{line.sku} 入库记录已创建，但没有返回 ID。"},
            )

    previous_quantity = _field_data(source_record).get("實際包裝數量")
    try:
        await odata.update_record(
            ORDER_ITEM_TABLE,
            line.line_id,
            {"實際包裝數量": line.received_quantity},
        )
        inventory_rows = await _inventory_rows(odata, receipt_id)
        if not inventory_rows:
            description = " · ".join(
                value
                for value in (
                    line.remark.strip(),
                    body.receipt_remark.strip(),
                )
                if value
            )
            await odata.create_record(
                INVENTORY_TABLE,
                {
                    "ID_出貨單資料": line.line_id,
                    "ID_出貨單資料入庫": receipt_id,
                    "批號": body.document_number,
                    "描述": description,
                    "ID_產品編號": line.sku,
                    "入庫數量": line.received_quantity,
                    "日期": receipt_date,
                    "記錄人": operator.name or operator.account,
                },
            )
        verified_inventory = await _inventory_rows(odata, receipt_id)
        if not any(
            _text(row.get("ID_出貨單資料")) == line.line_id
            and _text(row.get("ID_產品編號")) == line.sku
            and _integer(row.get("入庫數量")) == line.received_quantity
            for row in verified_inventory
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": f"{line.sku} 库存流水回读验证失败。"},
            )
        await odata.update_record(
            RECEIPT_TABLE,
            receipt_id,
            {"狀態": RECEIPT_COMPLETE_STATUS},
        )
    except (FileMakerODataError, HTTPException) as exc:
        try:
            await odata.update_record(
                ORDER_ITEM_TABLE,
                line.line_id,
                {"實際包裝數量": previous_quantity or ""},
            )
        except FileMakerODataError:
            pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": f"{line.sku} 入库写入失败。", "payload": exc.payload},
        ) from exc

    completed_rows = await _line_receipts(odata, line.line_id)
    completed = next(
        (
            row
            for row in completed_rows
            if _text(row.get("ID")) == receipt_id
            and _text(row.get("狀態")) == RECEIPT_COMPLETE_STATUS
        ),
        None,
    )
    if not completed:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": f"{line.sku} 入库状态回读验证失败。"},
        )
    return await _receipt_response(
        odata,
        completed,
        line=line,
        already_received=False,
    )


async def _receipt_catalog(
    odata: FileMakerODataClient,
    line_ids: list[object],
) -> dict[str, dict]:
    normalized_ids = [_text(value) for value in line_ids if _text(value)]
    rows_by_line = await asyncio.gather(
        *(_line_receipts(odata, line_id) for line_id in normalized_ids)
    )
    catalog: dict[str, dict] = {}
    for line_id, rows in zip(normalized_ids, rows_by_line):
        completed = _latest_receipt(rows, RECEIPT_COMPLETE_STATUS)
        if completed:
            catalog[line_id] = completed
    return catalog


async def _line_receipts(
    odata: FileMakerODataClient,
    line_id: str,
) -> list[dict]:
    escaped = line_id.replace("'", "''")
    try:
        result = await odata.records(
            RECEIPT_TABLE,
            filter_expr=f"ID_出庫單資料 eq '{escaped}'",
            top=10,
            count=False,
        )
    except FileMakerODataError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail={"message": "无法读取产品入库状态。", "payload": exc.payload},
        ) from exc
    return [row for row in result.get("rows", []) if isinstance(row, dict)]


async def _inventory_rows(
    odata: FileMakerODataClient,
    receipt_id: str,
) -> list[dict]:
    escaped = receipt_id.replace("'", "''")
    result = await odata.records(
        INVENTORY_TABLE,
        filter_expr=f"ID_出貨單資料入庫 eq '{escaped}'",
        top=10,
        count=False,
    )
    return [row for row in result.get("rows", []) if isinstance(row, dict)]


async def _receipt_response(
    odata: FileMakerODataClient,
    receipt: dict,
    *,
    line: ReceiptSubmissionLine,
    already_received: bool,
) -> ReceiptSubmissionLineResponse:
    receipt_id = _text(receipt.get("ID"))
    inventory_rows = await _inventory_rows(odata, receipt_id)
    received_by = next(
        (
            _text(row.get("記錄人"))
            for row in inventory_rows
            if _text(row.get("記錄人"))
        ),
        "",
    ) or _text(receipt.get("创建人"))
    return ReceiptSubmissionLineResponse(
        lineId=line.line_id,
        receiptId=receipt_id,
        quantity=_integer(receipt.get("數量")),
        status=_text(receipt.get("狀態")),
        receivedAt=_timestamp(receipt.get("创建时间戳")),
        receivedBy=received_by,
        alreadyReceived=already_received,
    )


async def _line_lock(line_id: str) -> asyncio.Lock:
    async with _receipt_line_locks_guard:
        lock = _receipt_line_locks.get(line_id)
        if lock is None:
            lock = asyncio.Lock()
            _receipt_line_locks[line_id] = lock
        return lock


def _latest_receipt(rows: list[dict], status_value: str) -> dict | None:
    matching = [
        row for row in rows if _text(row.get("狀態")) == status_value
    ]
    return max(
        matching,
        key=lambda row: _timestamp(row.get("创建时间戳")),
        default=None,
    )


def _timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raw = _text(value)
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _field_data(record: dict) -> dict:
    fields = record.get("fieldData") if isinstance(record, dict) else {}
    return fields if isinstance(fields, dict) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _integer(value: object) -> int:
    try:
        return int(float(str(value or 0).replace(",", "")))
    except (TypeError, ValueError):
        return 0

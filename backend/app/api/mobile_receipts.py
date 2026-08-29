import asyncio
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.models.mobile_receipts import (
    AttachmentCompleteRequest,
    AttachmentDownloadResponse,
    AttachmentPresignRequest,
    AttachmentPresignResponse,
    AttachmentResponse,
    ConfirmedReceiptDetail,
    ConfirmedReceiptLine,
    ConfirmedReceiptListResponse,
    ConfirmedReceiptSummary,
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
    get_webviewer_access,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import (
    FileMakerODataClient,
    FileMakerODataError,
)
from app.services.filemaker_timestamps import parse_filemaker_timestamp
from app.services.mobile_receipt_trace import (
    TRACE_SCHEMA,
    TRACE_SCHEMA_VERSION,
    append_bound_attachment,
    build_mobile_receipt_trace,
    parse_mobile_receipt_trace,
    serialize_mobile_receipt_trace,
)
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)


router = APIRouter(prefix="/mobile/v1/receipts", tags=["mobile-receipts"])
DraftID = Path(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
ReceiptDocumentID = Path(
    min_length=1,
    max_length=160,
    pattern=r"^[A-Za-z0-9._-]+$",
)
ORDER_LAYOUT = "@出貨單"
ORDER_ITEM_LAYOUT = "@出貨單資料"
RECEIPT_TABLE = "出貨單資料入庫"
INBOUND_ORDER_TABLE = "入庫單"
INBOUND_ORDER_LINE_TABLE = "入庫單資料"
INVENTORY_TABLE = "產品庫存"
ORDER_ITEM_TABLE = "出貨單資料"
RECEIPT_COMPLETE_STATUS = "已入庫"
RECEIPT_PENDING_STATUS = "未入庫"
SUPPLEMENTAL_INBOUND_SUMMARY_PREFIX = "PDA追加成品入库"
COMPLETED_RECEIPT_PERMISSION = "canAddCompletedReceipts"
_receipt_line_locks: dict[str, asyncio.Lock] = {}
_receipt_line_locks_guard = asyncio.Lock()


@router.get(
    "/confirmed",
    response_model=ConfirmedReceiptListResponse,
)
async def list_confirmed_receipts(
    limit: int = Query(default=5, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str = "",
    operator: OperatorContext = Depends(get_operator_context),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ConfirmedReceiptListResponse:
    rows, total = await audit_log.list_confirmed_mobile_receipts(
        operator_account=operator.account,
        limit=limit,
        offset=offset,
        search=search.strip()[:160],
    )
    return ConfirmedReceiptListResponse(
        receipts=[_confirmed_receipt_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/confirmed/{receipt_document_id}",
    response_model=ConfirmedReceiptDetail,
)
async def get_confirmed_receipt(
    receipt_document_id: str = ReceiptDocumentID,
    operator: OperatorContext = Depends(get_operator_context),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> ConfirmedReceiptDetail:
    row = await audit_log.get_confirmed_mobile_receipt(
        request_id=receipt_document_id,
        operator_account=operator.account,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到这张已确认验收单。"},
        )
    return _confirmed_receipt_detail(row)


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
                    "每个产品最多上传 6 张出货图片（选填）。"
                    if body.line_id
                    else "每张入库记录最多上传 1 张出货照片（选填）。"
                ),
                "maximum": line_limit,
            },
        )
    active_count = await attachment_store.count_active(draft_id, operator.account)
    if active_count >= settings.cos_max_attachments_per_receipt:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "当前入库批次的出货图片数量已达到上限。",
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
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> AttachmentResponse:
    _require_cos(settings, storage)
    record = await _owned_record(
        attachment_store,
        draft_id=draft_id,
        attachment_id=attachment_id,
        operator_account=operator.account,
    )
    if record.status == "BOUND":
        return _response(record)
    if record.status == "UPLOADED":
        return _response(
            await _bind_attachment_to_confirmed_receipt(
                record,
                operator=operator,
                settings=settings,
                odata=odata,
                attachment_store=attachment_store,
                audit_log=audit_log,
            )
        )
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
    return _response(
        await _bind_attachment_to_confirmed_receipt(
            updated,
            operator=operator,
            settings=settings,
            odata=odata,
            attachment_store=attachment_store,
            audit_log=audit_log,
        )
    )


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
    request: Request = None,
    draft_id: str = DraftID,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
    attachment_store: ReceiptAttachmentStore = Depends(get_receipt_attachment_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    access: dict[str, bool] = Depends(get_webviewer_access),
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
    attachment_records = await _validate_submission_attachments(
        attachment_store,
        body=body,
        draft_id=draft_id,
        operator=operator,
    )
    client_trace = _client_trace(request)

    request_identity = _receipt_request_identity(body)
    claim = await audit_log.claim_mobile_receipt_request(
        request_id=draft_id,
        shipment_id=body.shipment_id,
        operator_account=operator.account,
        operator_name=operator.name,
        request_payload=request_identity,
    )
    claim_status = _text(claim.get("status"))
    if claim_status == "duplicate":
        duplicate_payload = dict(claim.get("result") or {})
        duplicate_payload["lines"] = [
            {
                **line,
                "receivedAt": _timestamp(line.get("receivedAt")),
                "alreadyReceived": True,
            }
            for line in duplicate_payload.get("lines", [])
            if isinstance(line, dict)
        ]
        return ReceiptSubmissionResponse.model_validate(duplicate_payload)
    if claim_status == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "同一批次编号已用于不同的入库内容，请重新扫码后提交。"},
        )
    if claim_status == "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "同一批次正在处理中，请稍后重试。"},
        )
    if claim_status != "claimed":
        raise RuntimeError(f"未知的成品入库幂等状态：{claim_status}")

    claim_owned = True
    wrote_completed_receipt = False
    supplemental_batch: dict[str, str] = {}
    try:
        line_results: list[ReceiptSubmissionLineResponse] = []
        for line in body.lines:
            lock = await _line_lock(line.line_id)
            async with lock:
                line_results.append(
                    await _write_routed_line_receipt(
                        odata,
                        line=line,
                        source_record=source_records[line.line_id],
                        body=body,
                        operator=operator,
                        settings=settings,
                        attachments=attachment_records,
                        client_trace=client_trace,
                        audit_log=audit_log,
                        allow_completed_receipt=(
                            isinstance(access, dict)
                            and access.get(COMPLETED_RECEIPT_PERMISSION, False)
                        ),
                        supplemental_batch=supplemental_batch,
                    )
                )
            wrote_completed_receipt = True
            for attachment_id in line.attachment_ids:
                await attachment_store.mark_bound(attachment_id)

        for attachment_id in body.shipment_attachment_ids:
            await attachment_store.mark_bound(attachment_id)

        receipt_catalog = await _receipt_quantity_catalog(
            odata,
            [_field_data(record).get("ID", "") for record in all_source_records],
        )
        expected_by_line = {
            _text(_field_data(record).get("ID")): _integer(
                _field_data(record).get("數量")
            )
            for record in all_source_records
            if _text(_field_data(record).get("ID"))
        }
        for line in body.lines:
            if expected_by_line.get(line.line_id, 0) <= 0:
                expected_by_line[line.line_id] = line.expected_quantity
        total_line_count = len(all_source_records)
        received_line_count = sum(
            1
            for line_id, expected_quantity in expected_by_line.items()
            if (
                receipt_catalog.get(line_id, 0) >= expected_quantity
                if expected_quantity > 0
                else receipt_catalog.get(line_id, 0) > 0
            )
        )
        all_lines_received = (
            total_line_count > 0
            and received_line_count == total_line_count
        )
        completed_at = datetime.now(timezone.utc)
        aggregate_receipt_id = (
            line_results[0].receipt_id
            if len(line_results) == 1
            else f"receipt-{draft_id}"
        )
        response = ReceiptSubmissionResponse(
            receiptId=aggregate_receipt_id,
            status="sealed" if all_lines_received else "partial",
            sealedAt=completed_at,
            allLinesReceived=all_lines_received,
            receivedLineCount=received_line_count,
            totalLineCount=total_line_count,
            lines=line_results,
        )

        # FileMaker records already exist at this point. Keep the claim pending
        # if this persistence step fails so a retry cannot create duplicates.
        claim_owned = False
        await audit_log.complete_mobile_receipt_request(
            request_id=draft_id,
            response_payload=response.model_dump(mode="json", by_alias=True),
        )
    except Exception as exc:
        if claim_owned and not wrote_completed_receipt:
            await audit_log.fail_mobile_receipt_request(
                request_id=draft_id,
                error_message=str(exc),
            )
        raise

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
                    "routingMode": result.routing_mode,
                    "orderReceiptQuantity": result.order_receipt_quantity,
                    "supplementalQuantity": result.supplemental_quantity,
                    "inboundOrderId": result.inbound_order_id,
                    "inboundOrderLineId": result.inbound_order_line_id,
                }
                for line, result in zip(body.lines, response.lines)
            ],
        },
        response_payload=response.model_dump(mode="json", by_alias=True),
    )
    return response


def _receipt_request_identity(body: ReceiptSubmissionRequest) -> dict:
    """Stable receipt content; retry timestamps and client audit entries are excluded."""
    return {
        "shipmentId": body.shipment_id,
        "documentNumber": body.document_number,
        "piNumber": body.pi_number,
        "receiptRemark": body.receipt_remark,
        "shipmentAttachmentIds": body.shipment_attachment_ids,
        "lines": [
            {
                "lineId": line.line_id,
                "recordId": line.record_id,
                "sku": line.sku,
                "receivedQuantity": line.received_quantity,
                "expectedQuantity": line.expected_quantity,
                "remark": line.remark,
                "attachmentIds": line.attachment_ids,
            }
            for line in body.lines
        ],
    }


def _client_trace(request: Request | None) -> dict[str, str]:
    if request is None:
        return {"channel": "ios-pda"}
    return {
        "channel": request.headers.get("X-Client-Channel", "") or "ios-pda",
        "appVersion": request.headers.get("X-App-Version", ""),
        "appBuild": request.headers.get("X-App-Build", ""),
        "userAgent": request.headers.get("User-Agent", "")[:512],
    }


def _confirmed_receipt_summary(row: dict) -> ConfirmedReceiptSummary:
    request_payload = dict(row.get("requestPayload") or {})
    response_payload = dict(row.get("responsePayload") or {})
    lines = [line for line in request_payload.get("lines", []) if isinstance(line, dict)]
    return ConfirmedReceiptSummary(
        receiptDocumentId=_text(row.get("requestId")),
        shipmentId=_text(row.get("shipmentId")),
        documentNumber=_text(request_payload.get("documentNumber")),
        piNumber=_text(request_payload.get("piNumber")),
        receiptId=_text(response_payload.get("receiptId")),
        operatorAccount=_text(row.get("operatorAccount")),
        operatorName=(
            _text(row.get("operatorName")) or _text(row.get("operatorAccount"))
        ),
        confirmedAt=row.get("updatedAt"),
        allLinesReceived=bool(response_payload.get("allLinesReceived")),
        receivedLineCount=_integer(response_payload.get("receivedLineCount")),
        totalLineCount=_integer(response_payload.get("totalLineCount")),
        submittedLineCount=len(lines),
        totalQuantity=sum(_integer(line.get("receivedQuantity")) for line in lines),
        shipmentPhotoCount=len(request_payload.get("shipmentAttachmentIds") or []),
    )


def _confirmed_receipt_detail(row: dict) -> ConfirmedReceiptDetail:
    summary = _confirmed_receipt_summary(row)
    request_payload = dict(row.get("requestPayload") or {})
    response_payload = dict(row.get("responsePayload") or {})
    result_by_line = {
        _text(line.get("lineId")): line
        for line in response_payload.get("lines", [])
        if isinstance(line, dict)
    }
    lines: list[ConfirmedReceiptLine] = []
    for request_line in request_payload.get("lines", []):
        if not isinstance(request_line, dict):
            continue
        line_id = _text(request_line.get("lineId"))
        result_line = result_by_line.get(line_id, {})
        lines.append(
            ConfirmedReceiptLine(
                lineId=line_id,
                recordId=_text(request_line.get("recordId")),
                sku=_text(request_line.get("sku")),
                receivedQuantity=_integer(request_line.get("receivedQuantity")),
                expectedQuantity=_integer(request_line.get("expectedQuantity")),
                remark=_text(request_line.get("remark")),
                attachmentCount=len(request_line.get("attachmentIds") or []),
                receiptId=_text(result_line.get("receiptId")),
                status=_text(result_line.get("status")),
                receivedAt=(
                    _timestamp(result_line.get("receivedAt"))
                    if result_line.get("receivedAt")
                    else summary.confirmed_at
                ),
                receivedBy=(
                    _text(result_line.get("receivedBy")) or summary.operator_name
                ),
                routingMode=(
                    _text(result_line.get("routingMode")) or "order_receipt"
                ),
                orderReceiptQuantity=(
                    _integer(result_line.get("orderReceiptQuantity"))
                    if "orderReceiptQuantity" in result_line
                    else _integer(request_line.get("receivedQuantity"))
                ),
                supplementalQuantity=_integer(
                    result_line.get("supplementalQuantity")
                ),
                inboundOrderId=_text(result_line.get("inboundOrderId")),
                inboundOrderLineId=_text(
                    result_line.get("inboundOrderLineId")
                ),
            )
        )
    return ConfirmedReceiptDetail(
        **summary.model_dump(),
        receiptRemark=_text(request_payload.get("receiptRemark")),
        lines=lines,
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


async def _bind_attachment_to_confirmed_receipt(
    record: ReceiptAttachmentRecord,
    *,
    operator: OperatorContext,
    settings: Settings,
    odata: FileMakerODataClient,
    attachment_store: ReceiptAttachmentStore,
    audit_log: AuditLogStore,
) -> ReceiptAttachmentRecord:
    confirmed = await audit_log.get_confirmed_mobile_receipt(
        request_id=record.draft_id,
        operator_account=operator.account,
    )
    if not confirmed:
        return record

    did_append = await audit_log.append_confirmed_mobile_receipt_attachment(
        request_id=record.draft_id,
        operator_account=operator.account,
        line_id=record.line_id,
        attachment_id=record.attachment_id,
    )
    if not did_append:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "图片已上传到 COS，但无法绑定到原验收单；"
                    "请保留本机图片并联系管理员。"
                )
            },
        )
    bound = await attachment_store.mark_bound(record.attachment_id)
    if not bound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "附件记录不存在。"},
        )
    trace_sync_count = 0
    trace_sync_error = ""
    try:
        trace_sync_count = await _sync_bound_attachment_to_filemaker_trace(
            record=bound,
            confirmed=confirmed,
            operator=operator,
            settings=settings,
            odata=odata,
        )
    except (FileMakerODataError, HTTPException, ValueError) as exc:
        # The photo is already safely stored and bound in the Web database.
        # A FileMaker trace synchronization issue must not make the iPad repeat
        # the upload or block the operator from continuing.
        trace_sync_error = str(exc)
        await audit_log.record(
            operator=operator,
            action_type="RECEIPT_FILEMAKER_TRACE_SYNC",
            status="error",
            order_id=record.pi_number,
            request_payload={
                "draftId": record.draft_id,
                "attachmentId": record.attachment_id,
                "lineId": record.line_id,
            },
            error_message=trace_sync_error,
        )
    await audit_log.record(
        operator=operator,
        action_type="RECEIPT_ATTACHMENT_BOUND_AFTER_CONFIRMATION",
        status="success",
        order_id=record.pi_number,
        request_payload={
            "draftId": record.draft_id,
            "attachmentId": record.attachment_id,
            "lineId": record.line_id,
        },
        response_payload={
            "objectKey": record.object_key,
            "status": "BOUND",
            "fileMakerTraceRecordsUpdated": trace_sync_count,
            "fileMakerTraceSyncError": trace_sync_error or None,
        },
    )
    return bound


async def _sync_bound_attachment_to_filemaker_trace(
    *,
    record: ReceiptAttachmentRecord,
    confirmed: dict,
    operator: OperatorContext,
    settings: Settings,
    odata: FileMakerODataClient,
) -> int:
    log_field = settings.filemaker_mobile_receipt_log_field.strip()
    if not log_field:
        return 0
    request_payload = dict(confirmed.get("requestPayload") or {})
    response_payload = dict(confirmed.get("responsePayload") or {})
    request_lines = [
        item
        for item in request_payload.get("lines", [])
        if isinstance(item, dict)
    ]
    response_by_line = {
        _text(item.get("lineId")): item
        for item in response_payload.get("lines", [])
        if isinstance(item, dict)
    }
    target_lines = (
        [item for item in request_lines if _text(item.get("lineId")) == record.line_id]
        if record.line_id
        else request_lines
    )
    updated_count = 0
    now = datetime.now(timezone.utc)
    for request_line in target_lines:
        line_id = _text(request_line.get("lineId"))
        result_line = response_by_line.get(line_id, {})
        if _text(result_line.get("routingMode")) == "supplemental_inbound":
            # 入庫單資料 has no configured JSON trace field. The full trace
            # remains in the Web audit record and the COS attachment binding.
            continue
        receipt_id = _text(result_line.get("receiptId"))
        if not receipt_id:
            continue
        current = await odata.get_record(RECEIPT_TABLE, receipt_id)
        trace = parse_mobile_receipt_trace(current.get(log_field))
        if trace is None:
            trace = _stored_receipt_trace(
                confirmed=confirmed,
                request_line=request_line,
                result_line=result_line,
                operator=operator,
                updated_at=now,
            )
        updated_trace = append_bound_attachment(
            trace,
            record=record,
            operator=operator,
            updated_at=now,
        )
        await odata.update_record(
            RECEIPT_TABLE,
            receipt_id,
            {
                log_field: serialize_mobile_receipt_trace(
                    updated_trace,
                    max_characters=(
                        settings.filemaker_mobile_receipt_log_max_characters
                    ),
                )
            },
        )
        updated_count += 1
    return updated_count


def _stored_receipt_trace(
    *,
    confirmed: dict,
    request_line: dict,
    result_line: dict,
    operator: OperatorContext,
    updated_at: datetime,
) -> dict:
    request_payload = dict(confirmed.get("requestPayload") or {})
    return {
        "schema": TRACE_SCHEMA,
        "schemaVersion": TRACE_SCHEMA_VERSION,
        "event": "finished_goods_receipt.confirmed",
        "identifiers": {
            "draftId": _text(confirmed.get("requestId")),
            "receiptId": _text(result_line.get("receiptId")),
            "shipmentId": _text(confirmed.get("shipmentId")),
            "documentNumber": _text(request_payload.get("documentNumber")),
            "piNumber": _text(request_payload.get("piNumber")),
            "lineId": _text(request_line.get("lineId")),
            "sourceRecordId": _text(request_line.get("recordId")),
            "sku": _text(request_line.get("sku")),
        },
        "source": {
            "channel": "ios-pda",
            "application": "StarRC PDA",
            "api": "mobile/v1/receipts",
            "path": "iPad -> Web API -> FileMaker OData",
        },
        "operator": {
            "account": _text(confirmed.get("operatorAccount")) or operator.account,
            "name": _text(confirmed.get("operatorName")) or operator.name,
            "privilege": operator.privilege,
        },
        "operation": {
            "status": _text(result_line.get("status")) or RECEIPT_COMPLETE_STATUS,
            "submittedAt": "",
            "processedAt": updated_at.isoformat(),
            "timeZone": "Asia/Shanghai",
            "lineRemark": _text(request_line.get("remark")),
            "receiptRemark": _text(request_payload.get("receiptRemark")),
        },
        "quantities": {
            "expected": _integer(request_line.get("expectedQuantity")),
            "thisReceipt": _integer(request_line.get("receivedQuantity")),
        },
        "attachments": {
            "hasAny": False,
            "totalCount": 0,
            "linePhotoCount": 0,
            "shipmentPhotoCount": 0,
            "linePhotos": [],
            "shipmentPhotos": [],
        },
        "clientAudit": {
            "total": 0,
            "relevant": 0,
            "included": 0,
            "truncated": False,
            "eventCounts": {},
            "entries": [],
        },
        "serverEvents": [],
        "updatedAt": updated_at.isoformat(),
        "reconstructed": True,
    }


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
) -> dict[str, ReceiptAttachmentRecord]:
    expected_lines = {
        attachment_id: line.line_id
        for line in body.lines
        for attachment_id in line.attachment_ids
    }
    expected_lines.update(
        {attachment_id: None for attachment_id in body.shipment_attachment_ids}
    )
    records: dict[str, ReceiptAttachmentRecord] = {}
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
        records[attachment_id] = record
    return records


async def _write_routed_line_receipt(
    odata: FileMakerODataClient,
    *,
    line: ReceiptSubmissionLine,
    source_record: dict,
    body: ReceiptSubmissionRequest,
    operator: OperatorContext,
    settings: Settings,
    attachments: dict[str, ReceiptAttachmentRecord],
    client_trace: dict[str, str],
    audit_log: AuditLogStore,
    allow_completed_receipt: bool,
    supplemental_batch: dict[str, str],
) -> ReceiptSubmissionLineResponse:
    """Route one submitted line without letting extra stock change the order.

    The portion still owed by the source order keeps the existing
    出貨單資料入庫 flow. Any quantity beyond that balance is written to one
    shared 入庫單 for this PDA batch and receives its own 入庫單資料 row.
    """
    existing_rows = await _line_receipts(odata, line.line_id)
    completed_quantity = sum(
        _integer(row.get("數量"))
        for row in existing_rows
        if _text(row.get("狀態")) == RECEIPT_COMPLETE_STATUS
    )
    expected_quantity = _integer(_field_data(source_record).get("數量"))
    if expected_quantity <= 0:
        expected_quantity = line.expected_quantity

    if expected_quantity > 0:
        remaining_quantity = max(expected_quantity - completed_quantity, 0)
        order_receipt_quantity = min(line.received_quantity, remaining_quantity)
        supplemental_quantity = max(
            line.received_quantity - order_receipt_quantity,
            0,
        )
    else:
        order_receipt_quantity = line.received_quantity
        supplemental_quantity = 0

    if supplemental_quantity > 0 and not allow_completed_receipt:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    f"{line.sku} 本次有 {supplemental_quantity} 件需要走追加入库单；"
                    "当前账号没有追加成品库存流水的权限。"
                ),
                "permission": COMPLETED_RECEIPT_PERMISSION,
                "lineId": line.line_id,
                "supplementalQuantity": supplemental_quantity,
            },
        )
    if supplemental_quantity > 0 and not (
        line.remark.strip() or body.receipt_remark.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": f"{line.sku} 的追加入库需要填写原因或整单备注。",
                "lineId": line.line_id,
                "supplementalQuantity": supplemental_quantity,
            },
        )

    order_result: ReceiptSubmissionLineResponse | None = None
    if order_receipt_quantity > 0:
        order_line = line.model_copy(
            update={"received_quantity": order_receipt_quantity}
        )
        order_result = await _write_or_repair_line_receipt(
            odata,
            line=order_line,
            source_record=source_record,
            body=body,
            operator=operator,
            settings=settings,
            attachments=attachments,
            client_trace=client_trace,
            audit_log=audit_log,
            allow_completed_receipt=False,
        )

    supplemental_result: ReceiptSubmissionLineResponse | None = None
    if supplemental_quantity > 0:
        supplemental_line = line.model_copy(
            update={"received_quantity": supplemental_quantity}
        )
        supplemental_result = await _write_supplemental_inbound_line(
            odata,
            line=supplemental_line,
            source_record=source_record,
            body=body,
            operator=operator,
            supplemental_batch=supplemental_batch,
            submitted_quantity=line.received_quantity,
            order_receipt_quantity=order_receipt_quantity,
        )

    if order_result and supplemental_result:
        return ReceiptSubmissionLineResponse(
            lineId=line.line_id,
            receiptId=order_result.receipt_id,
            quantity=line.received_quantity,
            status=RECEIPT_COMPLETE_STATUS,
            receivedAt=max(
                order_result.received_at,
                supplemental_result.received_at,
            ),
            receivedBy=operator.name or operator.account,
            alreadyReceived=False,
            traceSyncStatus=order_result.trace_sync_status,
            traceSyncError=order_result.trace_sync_error,
            routingMode="split",
            orderReceiptQuantity=order_receipt_quantity,
            supplementalQuantity=supplemental_quantity,
            inboundOrderId=supplemental_result.inbound_order_id,
            inboundOrderLineId=supplemental_result.inbound_order_line_id,
        )
    if supplemental_result:
        return supplemental_result
    if order_result:
        return order_result.model_copy(
            update={
                "routing_mode": "order_receipt",
                "order_receipt_quantity": order_receipt_quantity,
                "supplemental_quantity": 0,
            }
        )
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"message": f"{line.sku} 没有可写入的入库数量。"},
    )


async def _write_or_repair_line_receipt(
    odata: FileMakerODataClient,
    *,
    line: ReceiptSubmissionLine,
    source_record: dict,
    body: ReceiptSubmissionRequest,
    operator: OperatorContext,
    settings: Settings,
    attachments: dict[str, ReceiptAttachmentRecord],
    client_trace: dict[str, str],
    audit_log: AuditLogStore,
    allow_completed_receipt: bool,
) -> ReceiptSubmissionLineResponse:
    existing_rows = await _line_receipts(odata, line.line_id)
    pending = _latest_receipt(existing_rows, RECEIPT_PENDING_STATUS)
    if pending:
        pending_id = _text(pending.get("ID"))
        try:
            fresh_pending = await odata.get_record(RECEIPT_TABLE, pending_id)
        except FileMakerODataError as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                fresh_pending = {}
            else:
                raise HTTPException(
                    status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
                    detail={
                        "message": "无法确认待处理入库记录的最新状态。",
                        "payload": exc.payload,
                    },
                ) from exc
        existing_rows = [
            fresh_pending if _text(row.get("ID")) == pending_id else row
            for row in existing_rows
            if _text(row.get("ID")) != pending_id or fresh_pending
        ]
        pending = (
            fresh_pending
            if _text(fresh_pending.get("狀態")) == RECEIPT_PENDING_STATUS
            else None
        )

    completed_quantity = sum(
        _integer(row.get("數量"))
        for row in existing_rows
        if _text(row.get("狀態")) == RECEIPT_COMPLETE_STATUS
    )
    expected_quantity = _integer(_field_data(source_record).get("數量"))
    if expected_quantity <= 0:
        expected_quantity = line.expected_quantity
    if (
        expected_quantity > 0
        and completed_quantity >= expected_quantity
        and not allow_completed_receipt
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    f"{line.sku} 已完成订单数量入库；"
                    "当前账号没有追加成品库存流水的权限。"
                ),
                "permission": COMPLETED_RECEIPT_PERMISSION,
                "lineId": line.line_id,
            },
        )

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
    cumulative_quantity = completed_quantity + line.received_quantity
    try:
        await odata.update_record(
            ORDER_ITEM_TABLE,
            line.line_id,
            {"實際包裝數量": cumulative_quantity},
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
        completed_at = datetime.now(timezone.utc)
        await odata.update_record(
            RECEIPT_TABLE,
            receipt_id,
            {"狀態": RECEIPT_COMPLETE_STATUS},
        )
        trace_sync_status, trace_sync_error = await _sync_receipt_trace(
            odata,
            body=body,
            line=line,
            receipt_id=receipt_id,
            operator=operator,
            settings=settings,
            attachments=attachments,
            historical_quantity=completed_quantity,
            receipt_date=receipt_date,
            client_trace=client_trace,
            completed_at=completed_at,
            audit_log=audit_log,
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
        trace_sync_status=trace_sync_status,
        trace_sync_error=trace_sync_error,
    )


async def _write_supplemental_inbound_line(
    odata: FileMakerODataClient,
    *,
    line: ReceiptSubmissionLine,
    source_record: dict,
    body: ReceiptSubmissionRequest,
    operator: OperatorContext,
    supplemental_batch: dict[str, str],
    submitted_quantity: int,
    order_receipt_quantity: int,
) -> ReceiptSubmissionLineResponse:
    receipt_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    received_at = datetime.now(timezone.utc)
    inbound_order_id = await _ensure_supplemental_inbound_order(
        odata,
        body=body,
        operator=operator,
        receipt_date=receipt_date,
        supplemental_batch=supplemental_batch,
    )
    inbound_order_line_id = _stable_filemaker_uuid(
        f"supplemental-inbound-line:{body.draft_id}:{line.line_id}"
    )
    existing_line = await _optional_odata_record(
        odata,
        INBOUND_ORDER_LINE_TABLE,
        inbound_order_line_id,
    )
    source_fields = _field_data(source_record)
    product_name = next(
        (
            _text(source_fields.get(field))
            for field in (
                "中文產品名稱",
                "產品名稱",
                "英文產品名稱",
                "English Name",
            )
            if _text(source_fields.get(field))
        ),
        line.sku,
    )
    line_payload = {
        "ID": inbound_order_line_id,
        "ID_入庫單": inbound_order_id,
        "零件編號": line.sku,
        "零件名稱": product_name,
        "數量": line.received_quantity,
        "審核": "已審核",
        "ID_採購單資料": f"PDA:{line.line_id}",
        "倉庫日期": receipt_date,
        "到貨數量": line.received_quantity,
        "到貨日期": receipt_date,
    }
    if existing_line:
        if not _supplemental_line_matches(existing_line, line_payload):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"{line.sku} 的追加入库单明细与原批次内容不一致。",
                    "lineId": line.line_id,
                    "inboundOrderLineId": inbound_order_line_id,
                },
            )
    else:
        created_line = await odata.create_record(
            INBOUND_ORDER_LINE_TABLE,
            line_payload,
        )
        created_line_id = _text(created_line.get("ID"))
        if created_line_id and created_line_id != inbound_order_line_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": f"{line.sku} 追加入库单明细 ID 回读不一致。"},
            )

    inventory_marker = f"PDA_INBOUND_LINE={inbound_order_line_id}"
    routing_markers = (
        f"PDA_DRAFT={body.draft_id}",
        f"PDA_SUBMITTED={submitted_quantity}",
        f"PDA_ORDER={order_receipt_quantity}",
        f"PDA_SUPPLEMENTAL={line.received_quantity}",
    )
    existing_inventory = await _supplemental_inventory_rows(
        odata,
        line_id=line.line_id,
        marker=inventory_marker,
    )
    description = " · ".join(
        value
        for value in (
            inventory_marker,
            *routing_markers,
            (
                f"原始录入 {submitted_quantity}；"
                f"订单入库 {order_receipt_quantity}；"
                f"追加入库 {line.received_quantity}"
            ),
            "追加入库",
            line.remark.strip(),
            body.receipt_remark.strip(),
        )
        if value
    )
    if existing_inventory:
        if not any(
            _text(row.get("ID_產品編號")) == line.sku
            and _integer(row.get("入庫數量")) == line.received_quantity
            for row in existing_inventory
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": f"{line.sku} 的追加入库库存流水与原批次内容不一致。",
                    "lineId": line.line_id,
                    "inboundOrderLineId": inbound_order_line_id,
                },
            )
    else:
        await odata.create_record(
            INVENTORY_TABLE,
            {
                "ID_出貨單資料": line.line_id,
                "批號": body.document_number,
                "描述": description,
                "ID_產品編號": line.sku,
                "入庫數量": line.received_quantity,
                "日期": receipt_date,
                "記錄人": operator.name or operator.account,
            },
        )
        verified_inventory = await _supplemental_inventory_rows(
            odata,
            line_id=line.line_id,
            marker=inventory_marker,
        )
        if not any(
            _text(row.get("ID_產品編號")) == line.sku
            and _integer(row.get("入庫數量")) == line.received_quantity
            for row in verified_inventory
        ):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": f"{line.sku} 追加入库库存流水回读验证失败。"},
            )

    return ReceiptSubmissionLineResponse(
        lineId=line.line_id,
        receiptId=inbound_order_id,
        quantity=line.received_quantity,
        status=RECEIPT_COMPLETE_STATUS,
        receivedAt=received_at,
        receivedBy=operator.name or operator.account,
        alreadyReceived=False,
        traceSyncStatus="audit_only",
        routingMode="supplemental_inbound",
        orderReceiptQuantity=0,
        supplementalQuantity=line.received_quantity,
        inboundOrderId=inbound_order_id,
        inboundOrderLineId=inbound_order_line_id,
    )


async def _ensure_supplemental_inbound_order(
    odata: FileMakerODataClient,
    *,
    body: ReceiptSubmissionRequest,
    operator: OperatorContext,
    receipt_date: str,
    supplemental_batch: dict[str, str],
) -> str:
    cached_id = supplemental_batch.get("inbound_order_id", "")
    if cached_id:
        return cached_id
    inbound_order_id = _stable_filemaker_uuid(
        f"supplemental-inbound-order:{body.draft_id}"
    )
    existing = await _optional_odata_record(
        odata,
        INBOUND_ORDER_TABLE,
        inbound_order_id,
    )
    summary = (
        f"{SUPPLEMENTAL_INBOUND_SUMMARY_PREFIX} · "
        f"{body.document_number or body.shipment_id}"
    )
    header_payload = {
        "ID": inbound_order_id,
        "修改人": operator.name or operator.account,
        "概要": summary,
        "類型": "入庫單",
        "日期": receipt_date,
        "核對狀態": "未核對",
        "採購單_ID": f"PDA:{body.draft_id}",
        "對應需求單": body.shipment_id,
    }
    if existing:
        if (
            _text(existing.get("對應需求單")) != body.shipment_id
            or _text(existing.get("採購單_ID")) != f"PDA:{body.draft_id}"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "追加入库单批次 ID 已用于其他来源单据。"},
            )
    else:
        created = await odata.create_record(INBOUND_ORDER_TABLE, header_payload)
        created_id = _text(created.get("ID"))
        if created_id and created_id != inbound_order_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"message": "追加入库单建立后返回了不同的单据 ID。"},
            )
    supplemental_batch["inbound_order_id"] = inbound_order_id
    return inbound_order_id


async def _optional_odata_record(
    odata: FileMakerODataClient,
    table: str,
    key: str,
) -> dict:
    # 入庫單 and 入庫單資料 expose a numeric OData entity key even though
    # their business `ID` field contains text/UUID values. FileMaker also
    # treats bare ID as a reserved expression token, so it must be quoted.
    escaped_key = key.replace("'", "''")
    result = await odata.records(
        table,
        filter_expr=f'"ID" eq \'{escaped_key}\'',
        top=2,
        count=False,
    )
    rows = [row for row in result.get("rows", []) if isinstance(row, dict)]
    if len(rows) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"{table} 中存在重复的业务 ID，无法安全继续写入。",
                "businessId": key,
            },
        )
    return rows[0] if rows else {}


def _supplemental_line_matches(existing: dict, expected: dict) -> bool:
    return (
        _text(existing.get("ID_入庫單")) == _text(expected.get("ID_入庫單"))
        and _text(existing.get("零件編號")) == _text(expected.get("零件編號"))
        and _integer(existing.get("數量")) == _integer(expected.get("數量"))
        and _text(existing.get("ID_採購單資料"))
        == _text(expected.get("ID_採購單資料"))
    )


async def _supplemental_inventory_rows(
    odata: FileMakerODataClient,
    *,
    line_id: str,
    marker: str,
) -> list[dict]:
    escaped = line_id.replace("'", "''")
    rows: list[dict] = []
    skip = 0
    while True:
        result = await odata.records(
            INVENTORY_TABLE,
            filter_expr=f"ID_出貨單資料 eq '{escaped}'",
            top=10,
            skip=skip,
            count=True,
        )
        page = [row for row in result.get("rows", []) if isinstance(row, dict)]
        rows.extend(page)
        if any(marker in _text(row.get("描述")) for row in page):
            break
        found_count = _integer(result.get("foundCount"))
        if (
            not page
            or len(page) < 10
            or (found_count > 0 and len(rows) >= found_count)
        ):
            break
        skip += len(page)
    return [row for row in rows if marker in _text(row.get("描述"))]


def _stable_filemaker_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"starrc:{value}")).upper()


async def _sync_receipt_trace(
    odata: FileMakerODataClient,
    *,
    body: ReceiptSubmissionRequest,
    line: ReceiptSubmissionLine,
    receipt_id: str,
    operator: OperatorContext,
    settings: Settings,
    attachments: dict[str, ReceiptAttachmentRecord],
    historical_quantity: int,
    receipt_date: str,
    client_trace: dict[str, str],
    completed_at: datetime,
    audit_log: AuditLogStore,
) -> tuple[str, str | None]:
    """Write and verify the FileMaker JSON trace without duplicating intake.

    FileMaker can accept a PATCH while omitting an unavailable/non-editable
    field from the stored record. A successful HTTP response alone therefore
    does not prove that the audit trace exists. Read the record back and retry
    briefly before returning a visible per-line failure status to the client.
    """
    log_field = settings.filemaker_mobile_receipt_log_field.strip()
    if not log_field:
        return "disabled", "服务器未配置 FileMaker 追溯日志字段"

    trace = build_mobile_receipt_trace(
        body=body,
        line=line,
        receipt_id=receipt_id,
        operator=operator,
        attachments=attachments,
        historical_quantity=historical_quantity,
        receipt_date=receipt_date,
        client=client_trace,
        processed_at=completed_at,
        max_audit_entries=settings.filemaker_mobile_receipt_log_audit_entries,
    )
    serialized_trace = serialize_mobile_receipt_trace(
        trace,
        max_characters=settings.filemaker_mobile_receipt_log_max_characters,
    )
    last_error = ""
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            await odata.update_record(
                RECEIPT_TABLE,
                receipt_id,
                {log_field: serialized_trace},
            )
            stored = await odata.get_record(RECEIPT_TABLE, receipt_id)
            stored_trace = parse_mobile_receipt_trace(stored.get(log_field))
            stored_receipt_id = _text(
                (stored_trace or {}).get("identifiers", {}).get("receiptId")
            )
            if stored_receipt_id != receipt_id:
                raise ValueError(
                    f"FileMaker 字段 {log_field} 写入后回读为空或内容不完整"
                )
            return "synced", None
        except (FileMakerODataError, ValueError) as exc:
            last_error = str(exc)
            if attempt < attempts:
                await asyncio.sleep(0.15 * attempt)

    # The receipt and inventory movement have already completed. Keep that
    # primary operation successful, but make the trace failure observable to
    # both the Web audit database and the iPad response.
    try:
        await audit_log.record(
            operator=operator,
            action_type="MOBILE_RECEIPT_FILEMAKER_TRACE_SYNC",
            status="error",
            target_table=RECEIPT_TABLE,
            target_record_id=receipt_id,
            product_sku=line.sku,
            order_id=body.shipment_id,
            request_payload={
                "draftId": body.draft_id,
                "lineId": line.line_id,
                "field": log_field,
                "attempts": attempts,
                "traceCharacters": len(serialized_trace),
            },
            error_message=last_error,
        )
    except Exception:
        pass
    return "failed", last_error or "FileMaker 追溯日志写入失败"


async def _receipt_quantity_catalog(
    odata: FileMakerODataClient,
    line_ids: list[object],
) -> dict[str, int]:
    normalized_ids = [_text(value) for value in line_ids if _text(value)]
    rows_by_line = await asyncio.gather(
        *(_line_receipts(odata, line_id) for line_id in normalized_ids)
    )
    catalog: dict[str, int] = {}
    for line_id, rows in zip(normalized_ids, rows_by_line):
        completed_quantity = sum(
            _integer(row.get("數量"))
            for row in rows
            if _text(row.get("狀態")) == RECEIPT_COMPLETE_STATUS
        )
        if completed_quantity > 0:
            catalog[line_id] = completed_quantity
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
            top=500,
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
    trace_sync_status: str = "synced",
    trace_sync_error: str | None = None,
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
        traceSyncStatus=trace_sync_status,
        traceSyncError=trace_sync_error,
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
    return parse_filemaker_timestamp(value) or datetime.now(timezone.utc)


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

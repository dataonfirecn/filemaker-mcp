from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from app.models.mobile_receipts import ReceiptSubmissionLine, ReceiptSubmissionRequest
from app.services.audit_log import OperatorContext
from app.services.receipt_attachment_store import ReceiptAttachmentRecord


TRACE_SCHEMA = "starrc.finished-goods-receipt"
TRACE_SCHEMA_VERSION = 1
DEFAULT_SOURCE_CHANNEL = "ios-pda"
DEFAULT_MAX_AUDIT_ENTRIES = 100
DEFAULT_MAX_CHARACTERS = 200_000
_REDACTED_KEYS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
)


def build_mobile_receipt_trace(
    *,
    body: ReceiptSubmissionRequest,
    line: ReceiptSubmissionLine,
    receipt_id: str,
    operator: OperatorContext,
    attachments: dict[str, ReceiptAttachmentRecord],
    historical_quantity: int,
    receipt_date: str,
    client: dict[str, str] | None = None,
    processed_at: datetime | None = None,
    max_audit_entries: int = DEFAULT_MAX_AUDIT_ENTRIES,
) -> dict[str, Any]:
    now = processed_at or datetime.now(timezone.utc)
    line_photos = [
        _attachment_payload(attachments[item], bound=True)
        for item in line.attachment_ids
        if item in attachments
    ]
    shipment_photos = [
        _attachment_payload(attachments[item], bound=True)
        for item in body.shipment_attachment_ids
        if item in attachments
    ]
    cumulative_quantity = historical_quantity + line.received_quantity
    remaining_quantity = max(line.expected_quantity - cumulative_quantity, 0)
    overage_quantity = max(cumulative_quantity - line.expected_quantity, 0)
    audit = _audit_payload(
        body.audit_log,
        line_id=line.line_id,
        max_entries=max_audit_entries,
    )
    client_payload = {
        "channel": DEFAULT_SOURCE_CHANNEL,
        "application": "StarRC PDA",
        "api": "mobile/v1/receipts",
        "path": "iPad -> Web API -> FileMaker OData",
        **{key: value for key, value in (client or {}).items() if value},
    }
    return {
        "schema": TRACE_SCHEMA,
        "schemaVersion": TRACE_SCHEMA_VERSION,
        "event": "finished_goods_receipt.confirmed",
        "identifiers": {
            "draftId": body.draft_id,
            "receiptId": receipt_id,
            "shipmentId": body.shipment_id,
            "documentNumber": body.document_number,
            "piNumber": body.pi_number,
            "lineId": line.line_id,
            "sourceRecordId": line.record_id,
            "sku": line.sku,
        },
        "source": client_payload,
        "operator": {
            "account": operator.account,
            "name": operator.name or operator.account,
            "privilege": operator.privilege,
        },
        "operation": {
            "status": "已入庫",
            "submittedAt": body.submitted_at.isoformat(),
            "processedAt": now.isoformat(),
            "receiptDate": receipt_date,
            "timeZone": "Asia/Shanghai",
            "lineRemark": line.remark,
            "receiptRemark": body.receipt_remark,
        },
        "quantities": {
            "expected": line.expected_quantity,
            "historicalBefore": historical_quantity,
            "thisReceipt": line.received_quantity,
            "cumulativeAfter": cumulative_quantity,
            "remainingAfter": remaining_quantity,
            "overageAfter": overage_quantity,
        },
        "attachments": _attachments_payload(line_photos, shipment_photos),
        "clientAudit": audit,
        "serverEvents": [
            {
                "event": "finished_goods_receipt.confirmed",
                "at": now.isoformat(),
                "operatorAccount": operator.account,
            }
        ],
        "updatedAt": now.isoformat(),
    }


def append_bound_attachment(
    trace: dict[str, Any],
    *,
    record: ReceiptAttachmentRecord,
    operator: OperatorContext,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return an updated trace after an optional photo is bound later."""
    payload = deepcopy(trace)
    now = updated_at or datetime.now(timezone.utc)
    attachments = payload.get("attachments")
    if not isinstance(attachments, dict):
        attachments = {}
    line_photos = _dict_list(attachments.get("linePhotos"))
    shipment_photos = _dict_list(attachments.get("shipmentPhotos"))
    target = line_photos if record.line_id else shipment_photos
    item = _attachment_payload(record, bound=True)
    existing_index = next(
        (
            index
            for index, existing in enumerate(target)
            if str(existing.get("attachmentId") or "") == record.attachment_id
        ),
        None,
    )
    if existing_index is None:
        target.append(item)
    else:
        target[existing_index] = item
    payload["attachments"] = _attachments_payload(line_photos, shipment_photos)
    events = _dict_list(payload.get("serverEvents"))
    events.append(
        {
            "event": "receipt_attachment.bound_after_confirmation",
            "at": now.isoformat(),
            "attachmentId": record.attachment_id,
            "scope": "line" if record.line_id else "shipment",
            "operatorAccount": operator.account,
        }
    )
    payload["serverEvents"] = events[-100:]
    payload["updatedAt"] = now.isoformat()
    return payload


def parse_mobile_receipt_trace(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        payload = decoded if isinstance(decoded, dict) else None
    else:
        payload = None
    if not payload or payload.get("schema") != TRACE_SCHEMA:
        return None
    return payload


def serialize_mobile_receipt_trace(
    payload: dict[str, Any],
    *,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> str:
    """Serialize Unicode JSON and trim only client audit entries if necessary."""
    safe_limit = max(10_000, int(max_characters))
    candidate = deepcopy(payload)
    while True:
        encoded = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        if len(encoded) <= safe_limit:
            return encoded
        audit = candidate.get("clientAudit")
        entries = audit.get("entries") if isinstance(audit, dict) else None
        if isinstance(entries, list) and entries:
            entries.pop(0)
            audit["included"] = len(entries)
            audit["truncated"] = True
            continue
        # Core trace data is deliberately small. This final fallback retains
        # identifiers, actor, quantities and attachment references.
        candidate.pop("clientAudit", None)
        operation = candidate.get("operation")
        if isinstance(operation, dict):
            operation["lineRemark"] = _text(operation.get("lineRemark"))[:500]
            operation["receiptRemark"] = _text(
                operation.get("receiptRemark")
            )[:500]
        candidate["logTruncated"] = True
        encoded = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )
        if len(encoded) <= safe_limit:
            return encoded
        minimal = {
            "schema": candidate.get("schema"),
            "schemaVersion": candidate.get("schemaVersion"),
            "identifiers": candidate.get("identifiers"),
            "source": candidate.get("source"),
            "operator": candidate.get("operator"),
            "quantities": candidate.get("quantities"),
            "attachments": candidate.get("attachments"),
            "updatedAt": candidate.get("updatedAt"),
            "logTruncated": True,
        }
        return json.dumps(
            minimal,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )


def _attachments_payload(
    line_photos: list[dict[str, Any]],
    shipment_photos: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "hasAny": bool(line_photos or shipment_photos),
        "totalCount": len(line_photos) + len(shipment_photos),
        "linePhotoCount": len(line_photos),
        "shipmentPhotoCount": len(shipment_photos),
        "linePhotos": line_photos,
        "shipmentPhotos": shipment_photos,
    }


def _attachment_payload(
    record: ReceiptAttachmentRecord,
    *,
    bound: bool,
) -> dict[str, Any]:
    return {
        "attachmentId": record.attachment_id,
        "scope": "line" if record.line_id else "shipment",
        "lineId": record.line_id,
        "source": record.source,
        "filename": record.original_filename,
        "mimeType": record.mime_type,
        "fileSize": record.file_size,
        "sha256": record.sha256,
        "objectKey": record.object_key,
        "status": "BOUND" if bound else record.status,
        "uploadedAt": (
            record.uploaded_at or record.created_at
        ).isoformat(),
    }


def _audit_payload(
    entries: Iterable[dict[str, Any]],
    *,
    line_id: str,
    max_entries: int,
) -> dict[str, Any]:
    rows = [entry for entry in entries if isinstance(entry, dict)]
    relevant = [
        entry
        for entry in rows
        if not _text(entry.get("lineId"))
        or _text(entry.get("lineId")) == line_id
    ]
    safe_max = max(0, int(max_entries))
    selected = relevant[-safe_max:] if safe_max else []
    event_counts = Counter(_text(item.get("event")) or "unknown" for item in relevant)
    return {
        "total": len(rows),
        "relevant": len(relevant),
        "included": len(selected),
        "truncated": len(selected) < len(relevant),
        "eventCounts": dict(sorted(event_counts.items())),
        "entries": [_sanitize(item) for item in selected],
    }


def _sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if any(part in key.casefold() for part in _REDACTED_KEYS):
        return "<redacted>"
    if depth >= 8:
        return "<max-depth>"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(
                item_value,
                key=str(item_key),
                depth=depth + 1,
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2_000]


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _text(value: object) -> str:
    return str(value or "").strip()

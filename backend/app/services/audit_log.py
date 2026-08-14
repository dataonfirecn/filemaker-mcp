import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg


@dataclass(frozen=True)
class OperatorContext:
    session_id: str
    account: str
    name: str
    privilege: str = ""
    persistent_id: str = ""
    permissions: dict[str, bool] | None = None
    part_permissions: dict[str, bool] | None = None


class AuditLogStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_rows: list[dict[str, Any]] = []
        self._memory_next_id = 1
        self._memory_web_merge_requests: dict[str, dict[str, Any]] = {}
        self._web_merge_lock = asyncio.Lock()
        self._memory_mobile_receipt_requests: dict[str, dict[str, Any]] = {}
        self._mobile_receipt_lock = asyncio.Lock()

    async def init(self) -> None:
        if self.database_url.startswith("memory://"):
            return
        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    event_id UUID NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    operator_privilege TEXT NOT NULL DEFAULT '',
                    action_type TEXT NOT NULL,
                    target_table TEXT,
                    target_layout TEXT,
                    target_record_id TEXT,
                    product_sku TEXT,
                    order_id TEXT,
                    bom_calc_id TEXT,
                    change_batch_id TEXT,
                    change_item_id TEXT,
                    before_data JSONB,
                    after_data JSONB,
                    request_payload JSONB,
                    response_payload JSONB,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
                    ON audit_log (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_log_product_sku
                    ON audit_log (product_sku);
                CREATE INDEX IF NOT EXISTS idx_audit_log_bom_calc_id
                    ON audit_log (bom_calc_id);
                CREATE INDEX IF NOT EXISTS idx_audit_log_session_id
                    ON audit_log (session_id);

                CREATE TABLE IF NOT EXISTS web_merge_request (
                    request_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    source_order_ids JSONB NOT NULL,
                    status TEXT NOT NULL,
                    response_payload JSONB,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_web_merge_request_updated_at
                    ON web_merge_request (updated_at DESC);

                CREATE TABLE IF NOT EXISTS mobile_receipt_request (
                    request_id TEXT PRIMARY KEY,
                    shipment_id TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL DEFAULT '',
                    request_payload JSONB NOT NULL,
                    status TEXT NOT NULL,
                    response_payload JSONB,
                    error_message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_mobile_receipt_request_updated_at
                    ON mobile_receipt_request (updated_at DESC);
                ALTER TABLE mobile_receipt_request
                    ADD COLUMN IF NOT EXISTS operator_name TEXT NOT NULL DEFAULT '';
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def record(
        self,
        *,
        operator: OperatorContext,
        action_type: str,
        status: str = "success",
        target_table: str | None = None,
        target_layout: str | None = None,
        target_record_id: str | None = None,
        product_sku: str | None = None,
        order_id: str | None = None,
        bom_calc_id: str | None = None,
        change_batch_id: str | None = None,
        change_item_id: str | None = None,
        before_data: Any = None,
        after_data: Any = None,
        request_payload: Any = None,
        response_payload: Any = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        if self.database_url.startswith("memory://"):
            return self._record_memory(
                operator=operator,
                action_type=action_type,
                status=status,
                target_table=target_table,
                target_layout=target_layout,
                target_record_id=target_record_id,
                product_sku=product_sku,
                order_id=order_id,
                bom_calc_id=bom_calc_id,
                change_batch_id=change_batch_id,
                change_item_id=change_item_id,
                request_payload=request_payload,
                response_payload=response_payload,
                error_message=error_message,
            )
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")

        event_id = uuid.uuid4()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO audit_log (
                    event_id,
                    session_id,
                    operator_account,
                    operator_name,
                    operator_privilege,
                    action_type,
                    target_table,
                    target_layout,
                    target_record_id,
                    product_sku,
                    order_id,
                    bom_calc_id,
                    change_batch_id,
                    change_item_id,
                    before_data,
                    after_data,
                    request_payload,
                    response_payload,
                    status,
                    error_message
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15::jsonb, $16::jsonb,
                    $17::jsonb, $18::jsonb, $19, $20
                )
                RETURNING id, event_id, created_at
                """,
                event_id,
                operator.session_id,
                operator.account,
                operator.name,
                operator.privilege,
                action_type,
                target_table,
                target_layout,
                target_record_id,
                product_sku,
                order_id,
                bom_calc_id,
                change_batch_id,
                change_item_id,
                self._json_or_none(before_data),
                self._json_or_none(after_data),
                self._json_or_none(request_payload),
                self._json_or_none(response_payload),
                status,
                error_message,
            )
        return {
            "id": row["id"],
            "eventId": str(row["event_id"]),
            "createdAt": row["created_at"].isoformat(),
        }

    async def claim_web_merge_request(
        self,
        *,
        request_id: str,
        customer_id: str,
        source_order_ids: list[str],
    ) -> dict[str, Any]:
        """Atomically reserve an idempotency key without using FileMaker sync fields."""
        normalized_order_ids = sorted(set(source_order_ids))
        if self.database_url.startswith("memory://"):
            async with self._web_merge_lock:
                existing = self._memory_web_merge_requests.get(request_id)
                if not existing:
                    self._memory_web_merge_requests[request_id] = {
                        "customerId": customer_id,
                        "sourceOrderIds": normalized_order_ids,
                        "status": "pending",
                        "responsePayload": None,
                        "errorMessage": None,
                    }
                    return {"status": "claimed"}
                return self._resolve_web_merge_claim(
                    existing=existing,
                    customer_id=customer_id,
                    source_order_ids=normalized_order_ids,
                    retry_failed=True,
                )
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")

        source_order_ids_json = self._json_or_none(normalized_order_ids)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO web_merge_request (
                        request_id, customer_id, source_order_ids, status
                    )
                    VALUES ($1, $2, $3::jsonb, 'pending')
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id
                    """,
                    request_id,
                    customer_id,
                    source_order_ids_json,
                )
                if inserted:
                    return {"status": "claimed"}

                row = await conn.fetchrow(
                    """
                    SELECT customer_id, source_order_ids, status, response_payload, error_message
                    FROM web_merge_request
                    WHERE request_id = $1
                    FOR UPDATE
                    """,
                    request_id,
                )
                existing = {
                    "customerId": row["customer_id"],
                    "sourceOrderIds": list(self._decoded_json(row["source_order_ids"]) or []),
                    "status": row["status"],
                    "responsePayload": self._decoded_json(row["response_payload"]),
                    "errorMessage": row["error_message"],
                }
                resolution = self._resolve_web_merge_claim(
                    existing=existing,
                    customer_id=customer_id,
                    source_order_ids=normalized_order_ids,
                    retry_failed=False,
                )
                if resolution["status"] == "retry":
                    await conn.execute(
                        """
                        UPDATE web_merge_request
                        SET status = 'pending', response_payload = NULL,
                            error_message = NULL, updated_at = now()
                        WHERE request_id = $1
                        """,
                        request_id,
                    )
                    return {"status": "claimed"}
                return resolution

    async def complete_web_merge_request(
        self,
        *,
        request_id: str,
        response_payload: dict[str, Any],
    ) -> None:
        if self.database_url.startswith("memory://"):
            async with self._web_merge_lock:
                existing = self._memory_web_merge_requests.get(request_id)
                if not existing:
                    raise RuntimeError(f"Web merge request was not claimed: {request_id}")
                existing.update(
                    status="success",
                    responsePayload=response_payload,
                    errorMessage=None,
                )
                return
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE web_merge_request
                SET status = 'success', response_payload = $2::jsonb,
                    error_message = NULL, updated_at = now()
                WHERE request_id = $1 AND status = 'pending'
                """,
                request_id,
                self._json_or_none(response_payload),
            )
        if result != "UPDATE 1":
            raise RuntimeError(f"Web merge request was not pending: {request_id}")

    async def fail_web_merge_request(self, *, request_id: str, error_message: str) -> None:
        if self.database_url.startswith("memory://"):
            async with self._web_merge_lock:
                existing = self._memory_web_merge_requests.get(request_id)
                if existing and existing["status"] == "pending":
                    existing.update(status="failed", errorMessage=error_message)
                return
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE web_merge_request
                SET status = 'failed', error_message = $2, updated_at = now()
                WHERE request_id = $1 AND status = 'pending'
                """,
                request_id,
                error_message,
            )

    async def claim_mobile_receipt_request(
        self,
        *,
        request_id: str,
        shipment_id: str,
        operator_account: str,
        operator_name: str,
        request_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically reserve one PDA receipt batch idempotency key."""
        if self.database_url.startswith("memory://"):
            async with self._mobile_receipt_lock:
                existing = self._memory_mobile_receipt_requests.get(request_id)
                if not existing:
                    self._memory_mobile_receipt_requests[request_id] = {
                        "shipmentId": shipment_id,
                        "operatorAccount": operator_account,
                        "operatorName": operator_name,
                        "requestPayload": request_payload,
                        "status": "pending",
                        "responsePayload": None,
                        "errorMessage": None,
                        "createdAt": datetime.now(timezone.utc),
                        "updatedAt": datetime.now(timezone.utc),
                    }
                    return {"status": "claimed"}
                return self._resolve_mobile_receipt_claim(
                    existing=existing,
                    shipment_id=shipment_id,
                    operator_account=operator_account,
                    request_payload=request_payload,
                    retry_failed=True,
                )
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")

        request_payload_json = self._json_or_none(request_payload)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    """
                    INSERT INTO mobile_receipt_request (
                        request_id, shipment_id, operator_account, operator_name,
                        request_payload, status
                    )
                    VALUES ($1, $2, $3, $4, $5::jsonb, 'pending')
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id
                    """,
                    request_id,
                    shipment_id,
                    operator_account,
                    operator_name,
                    request_payload_json,
                )
                if inserted:
                    return {"status": "claimed"}

                row = await conn.fetchrow(
                    """
                    SELECT shipment_id, operator_account, operator_name,
                           request_payload, status, response_payload, error_message
                    FROM mobile_receipt_request
                    WHERE request_id = $1
                    FOR UPDATE
                    """,
                    request_id,
                )
                existing = {
                    "shipmentId": row["shipment_id"],
                    "operatorAccount": row["operator_account"],
                    "operatorName": row["operator_name"],
                    "requestPayload": self._decoded_json(row["request_payload"]),
                    "status": row["status"],
                    "responsePayload": self._decoded_json(row["response_payload"]),
                    "errorMessage": row["error_message"],
                }
                resolution = self._resolve_mobile_receipt_claim(
                    existing=existing,
                    shipment_id=shipment_id,
                    operator_account=operator_account,
                    request_payload=request_payload,
                    retry_failed=False,
                )
                if resolution["status"] == "retry":
                    await conn.execute(
                        """
                        UPDATE mobile_receipt_request
                        SET status = 'pending', response_payload = NULL,
                            error_message = NULL, updated_at = now()
                        WHERE request_id = $1
                        """,
                        request_id,
                    )
                    return {"status": "claimed"}
                return resolution

    async def complete_mobile_receipt_request(
        self,
        *,
        request_id: str,
        response_payload: dict[str, Any],
    ) -> None:
        if self.database_url.startswith("memory://"):
            async with self._mobile_receipt_lock:
                existing = self._memory_mobile_receipt_requests.get(request_id)
                if not existing:
                    raise RuntimeError(
                        f"Mobile receipt request was not claimed: {request_id}"
                    )
                existing.update(
                    status="success",
                    responsePayload=response_payload,
                    errorMessage=None,
                    updatedAt=datetime.now(timezone.utc),
                )
                return
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE mobile_receipt_request
                SET status = 'success', response_payload = $2::jsonb,
                    error_message = NULL, updated_at = now()
                WHERE request_id = $1 AND status = 'pending'
                """,
                request_id,
                self._json_or_none(response_payload),
            )
        if result != "UPDATE 1":
            raise RuntimeError(f"Mobile receipt request was not pending: {request_id}")

    async def append_confirmed_mobile_receipt_attachment(
        self,
        *,
        request_id: str,
        operator_account: str,
        line_id: str | None,
        attachment_id: str,
    ) -> bool:
        """Bind a late optional photo to an already confirmed PDA receipt."""
        if self.database_url.startswith("memory://"):
            async with self._mobile_receipt_lock:
                existing = self._memory_mobile_receipt_requests.get(request_id)
                if (
                    not existing
                    or existing["status"] != "success"
                    or existing["operatorAccount"] != operator_account
                ):
                    return False
                updated_payload = self._with_mobile_receipt_attachment(
                    existing["requestPayload"],
                    line_id=line_id,
                    attachment_id=attachment_id,
                )
                if updated_payload is None:
                    return False
                existing["requestPayload"] = updated_payload
                return True
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT request_payload
                    FROM mobile_receipt_request
                    WHERE request_id = $1 AND status = 'success'
                      AND operator_account = $2
                    FOR UPDATE
                    """,
                    request_id,
                    operator_account,
                )
                if not row:
                    return False
                updated_payload = self._with_mobile_receipt_attachment(
                    self._decoded_json(row["request_payload"]),
                    line_id=line_id,
                    attachment_id=attachment_id,
                )
                if updated_payload is None:
                    return False
                await conn.execute(
                    """
                    UPDATE mobile_receipt_request
                    SET request_payload = $3::jsonb
                    WHERE request_id = $1 AND operator_account = $2
                    """,
                    request_id,
                    operator_account,
                    self._json_or_none(updated_payload),
                )
                return True

    async def fail_mobile_receipt_request(
        self,
        *,
        request_id: str,
        error_message: str,
    ) -> None:
        if self.database_url.startswith("memory://"):
            async with self._mobile_receipt_lock:
                existing = self._memory_mobile_receipt_requests.get(request_id)
                if existing and existing["status"] == "pending":
                    existing.update(
                        status="failed",
                        errorMessage=error_message,
                        updatedAt=datetime.now(timezone.utc),
                    )
                return
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE mobile_receipt_request
                SET status = 'failed', error_message = $2, updated_at = now()
                WHERE request_id = $1 AND status = 'pending'
                """,
                request_id,
                error_message,
            )

    async def list_confirmed_mobile_receipts(
        self,
        *,
        operator_account: str,
        limit: int,
        offset: int,
        search: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_search = search.strip()
        if self.database_url.startswith("memory://"):
            rows = [
                {"requestId": request_id, **row}
                for request_id, row in self._memory_mobile_receipt_requests.items()
                if row["status"] == "success"
                and row["operatorAccount"] == operator_account
            ]
            if normalized_search:
                folded_search = normalized_search.casefold()
                rows = [
                    row
                    for row in rows
                    if folded_search
                    in "\n".join(
                        (
                            str(row.get("requestId") or ""),
                            str(row.get("shipmentId") or ""),
                            str(row.get("operatorName") or ""),
                            str((row.get("requestPayload") or {}).get("documentNumber") or ""),
                            str((row.get("requestPayload") or {}).get("piNumber") or ""),
                            str((row.get("responsePayload") or {}).get("receiptId") or ""),
                        )
                    ).casefold()
                ]
            rows.sort(key=lambda row: row["updatedAt"], reverse=True)
            return rows[offset : offset + limit], len(rows)
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT count(*)
                FROM mobile_receipt_request
                WHERE status = 'success' AND operator_account = $1
                  AND (
                      $2 = ''
                      OR request_id ILIKE '%' || $2 || '%'
                      OR shipment_id ILIKE '%' || $2 || '%'
                      OR operator_name ILIKE '%' || $2 || '%'
                      OR COALESCE(request_payload->>'documentNumber', '')
                         ILIKE '%' || $2 || '%'
                      OR COALESCE(request_payload->>'piNumber', '')
                         ILIKE '%' || $2 || '%'
                      OR COALESCE(response_payload->>'receiptId', '')
                         ILIKE '%' || $2 || '%'
                  )
                """,
                operator_account,
                normalized_search,
            )
            records = await conn.fetch(
                """
                SELECT request_id, shipment_id, operator_account, operator_name,
                       request_payload, response_payload, created_at, updated_at
                FROM mobile_receipt_request
                WHERE status = 'success' AND operator_account = $1
                  AND (
                      $2 = ''
                      OR request_id ILIKE '%' || $2 || '%'
                      OR shipment_id ILIKE '%' || $2 || '%'
                      OR operator_name ILIKE '%' || $2 || '%'
                      OR COALESCE(request_payload->>'documentNumber', '')
                         ILIKE '%' || $2 || '%'
                      OR COALESCE(request_payload->>'piNumber', '')
                         ILIKE '%' || $2 || '%'
                      OR COALESCE(response_payload->>'receiptId', '')
                         ILIKE '%' || $2 || '%'
                  )
                ORDER BY updated_at DESC
                LIMIT $3 OFFSET $4
                """,
                operator_account,
                normalized_search,
                limit,
                offset,
            )
        return [self._mobile_receipt_record(row) for row in records], int(total or 0)

    async def get_confirmed_mobile_receipt(
        self,
        *,
        request_id: str,
        operator_account: str,
    ) -> dict[str, Any] | None:
        if self.database_url.startswith("memory://"):
            row = self._memory_mobile_receipt_requests.get(request_id)
            if (
                not row
                or row["status"] != "success"
                or row["operatorAccount"] != operator_account
            ):
                return None
            return {"requestId": request_id, **row}
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT request_id, shipment_id, operator_account, operator_name,
                       request_payload, response_payload, created_at, updated_at
                FROM mobile_receipt_request
                WHERE request_id = $1 AND status = 'success'
                  AND operator_account = $2
                """,
                request_id,
                operator_account,
            )
        return self._mobile_receipt_record(row) if row else None

    def _mobile_receipt_record(self, row: Any) -> dict[str, Any]:
        return {
            "requestId": row["request_id"],
            "shipmentId": row["shipment_id"],
            "operatorAccount": row["operator_account"],
            "operatorName": row["operator_name"],
            "requestPayload": self._decoded_json(row["request_payload"]),
            "responsePayload": self._decoded_json(row["response_payload"]),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _resolve_mobile_receipt_claim(
        self,
        *,
        existing: dict[str, Any],
        shipment_id: str,
        operator_account: str,
        request_payload: dict[str, Any],
        retry_failed: bool,
    ) -> dict[str, Any]:
        if (
            existing["shipmentId"] != shipment_id
            or existing["operatorAccount"] != operator_account
            or existing["requestPayload"] != request_payload
        ):
            return {"status": "conflict"}
        if existing["status"] == "success":
            return {"status": "duplicate", "result": existing["responsePayload"]}
        if existing["status"] == "pending":
            return {"status": "in_progress"}
        if retry_failed:
            existing.update(status="pending", responsePayload=None, errorMessage=None)
            return {"status": "claimed"}
        return {"status": "retry"}

    @staticmethod
    def _with_mobile_receipt_attachment(
        request_payload: dict[str, Any],
        *,
        line_id: str | None,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        payload = dict(request_payload or {})
        if line_id is None:
            attachment_ids = list(payload.get("shipmentAttachmentIds") or [])
            if attachment_id not in attachment_ids:
                if len(attachment_ids) >= 1:
                    return None
                attachment_ids.append(attachment_id)
            payload["shipmentAttachmentIds"] = attachment_ids
            return payload

        updated_lines: list[dict[str, Any]] = []
        found_line = False
        for value in payload.get("lines") or []:
            if not isinstance(value, dict):
                continue
            line = dict(value)
            if str(line.get("lineId") or "") == line_id:
                found_line = True
                attachment_ids = list(line.get("attachmentIds") or [])
                if attachment_id not in attachment_ids:
                    if len(attachment_ids) >= 6:
                        return None
                    attachment_ids.append(attachment_id)
                line["attachmentIds"] = attachment_ids
            updated_lines.append(line)
        if not found_line:
            return None
        payload["lines"] = updated_lines
        return payload

    def _resolve_web_merge_claim(
        self,
        *,
        existing: dict[str, Any],
        customer_id: str,
        source_order_ids: list[str],
        retry_failed: bool,
    ) -> dict[str, Any]:
        if (
            existing["customerId"] != customer_id
            or existing["sourceOrderIds"] != source_order_ids
        ):
            return {"status": "conflict"}
        if existing["status"] == "success":
            return {"status": "duplicate", "result": existing["responsePayload"]}
        if existing["status"] == "pending":
            return {"status": "in_progress"}
        if retry_failed:
            existing.update(status="pending", responsePayload=None, errorMessage=None)
            return {"status": "claimed"}
        return {"status": "retry"}

    async def list_logs(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        product_sku: str | None = None,
        bom_calc_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.database_url.startswith("memory://"):
            rows = list(reversed(self._memory_rows))
            if product_sku:
                rows = [row for row in rows if row["productSku"] == product_sku]
            if bom_calc_id:
                rows = [row for row in rows if row["bomCalcId"] == bom_calc_id]
            if session_id:
                rows = [row for row in rows if row["sessionId"] == session_id]
            return rows[offset : offset + limit]
        if not self._pool:
            raise RuntimeError("AuditLogStore is not initialized")

        conditions: list[str] = []
        values: list[Any] = []
        if product_sku:
            values.append(product_sku)
            conditions.append(f"product_sku = ${len(values)}")
        if bom_calc_id:
            values.append(bom_calc_id)
            conditions.append(f"bom_calc_id = ${len(values)}")
        if session_id:
            values.append(session_id)
            conditions.append(f"session_id = ${len(values)}")

        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])
        limit_index = len(values) - 1
        offset_index = len(values)
        query = f"""
            SELECT
                id,
                event_id,
                session_id,
                operator_account,
                operator_name,
                operator_privilege,
                action_type,
                target_table,
                target_layout,
                target_record_id,
                product_sku,
                order_id,
                bom_calc_id,
                change_batch_id,
                change_item_id,
                request_payload,
                response_payload,
                status,
                error_message,
                created_at
            FROM audit_log
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ${limit_index}
            OFFSET ${offset_index}
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *values)
        return [self._row_to_dict(row) for row in rows]

    def _row_to_dict(self, row: asyncpg.Record) -> dict[str, Any]:
        return {
            "id": row["id"],
            "eventId": str(row["event_id"]),
            "sessionId": row["session_id"],
            "operatorAccount": row["operator_account"],
            "operatorName": row["operator_name"],
            "operatorPrivilege": row["operator_privilege"],
            "actionType": row["action_type"],
            "targetTable": row["target_table"],
            "targetLayout": row["target_layout"],
            "targetRecordId": row["target_record_id"],
            "productSku": row["product_sku"],
            "orderId": row["order_id"],
            "bomCalcId": row["bom_calc_id"],
            "changeBatchId": row["change_batch_id"],
            "changeItemId": row["change_item_id"],
            "requestPayload": row["request_payload"],
            "responsePayload": row["response_payload"],
            "status": row["status"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"].isoformat(),
        }

    def _json_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, default=str)

    def _decoded_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    def _record_memory(
        self,
        *,
        operator: OperatorContext,
        action_type: str,
        status: str,
        target_table: str | None,
        target_layout: str | None,
        target_record_id: str | None,
        product_sku: str | None,
        order_id: str | None,
        bom_calc_id: str | None,
        change_batch_id: str | None,
        change_item_id: str | None,
        request_payload: Any,
        response_payload: Any,
        error_message: str | None,
    ) -> dict[str, Any]:
        event_id = uuid.uuid4()
        created_at = datetime.now(tz=timezone.utc).isoformat()
        row = {
            "id": self._memory_next_id,
            "eventId": str(event_id),
            "sessionId": operator.session_id,
            "operatorAccount": operator.account,
            "operatorName": operator.name,
            "operatorPrivilege": operator.privilege,
            "actionType": action_type,
            "targetTable": target_table,
            "targetLayout": target_layout,
            "targetRecordId": target_record_id,
            "productSku": product_sku,
            "orderId": order_id,
            "bomCalcId": bom_calc_id,
            "changeBatchId": change_batch_id,
            "changeItemId": change_item_id,
            "requestPayload": request_payload,
            "responsePayload": response_payload,
            "status": status,
            "errorMessage": error_message,
            "createdAt": created_at,
        }
        self._memory_next_id += 1
        self._memory_rows.append(row)
        return {"id": row["id"], "eventId": row["eventId"], "createdAt": created_at}

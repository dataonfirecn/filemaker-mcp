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


class AuditLogStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_rows: list[dict[str, Any]] = []
        self._memory_next_id = 1

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

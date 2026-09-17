from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import asyncpg

from app.services.audit_log import OperatorContext


class QualityInspectionStore:
    """Durable source of truth for PDA incoming-quality inspections."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_records: dict[str, dict[str, Any]] = {}
        self._memory_events: dict[str, list[dict[str, Any]]] = {}
        self._memory_lock = asyncio.Lock()

    async def init(self) -> None:
        if self.database_url.startswith("memory://"):
            return
        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_inspection (
                    inspection_id TEXT PRIMARY KEY,
                    purchase_line_id TEXT NOT NULL,
                    arrival_batch_id TEXT NOT NULL,
                    inspection_round INTEGER NOT NULL DEFAULT 1,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    purchase_order_number TEXT NOT NULL DEFAULT '',
                    nb_number TEXT NOT NULL DEFAULT '',
                    part_number TEXT NOT NULL DEFAULT '',
                    part_name TEXT NOT NULL DEFAULT '',
                    supplier_name TEXT NOT NULL DEFAULT '',
                    arrival_date TEXT NOT NULL DEFAULT '',
                    arrival_quantity INTEGER NOT NULL DEFAULT 0,
                    returned_quantity INTEGER NOT NULL DEFAULT 0,
                    warehoused_quantity INTEGER NOT NULL DEFAULT 0,
                    available_quantity INTEGER NOT NULL DEFAULT 0,
                    inspection_method TEXT NOT NULL,
                    sample_quantity INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    conclusion TEXT NOT NULL DEFAULT '',
                    spec_version JSONB NOT NULL,
                    check_items JSONB NOT NULL,
                    source_snapshot JSONB NOT NULL,
                    request_payload JSONB NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    operator_privilege TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE (arrival_batch_id, inspection_round)
                );
                CREATE TABLE IF NOT EXISTS quality_inspection_event (
                    id BIGSERIAL PRIMARY KEY,
                    event_id UUID NOT NULL UNIQUE,
                    inspection_id TEXT NOT NULL
                        REFERENCES quality_inspection(inspection_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    from_status TEXT NOT NULL DEFAULT '',
                    to_status TEXT NOT NULL DEFAULT '',
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    operator_privilege TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_created_at
                    ON quality_inspection (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_arrival
                    ON quality_inspection (arrival_batch_id, inspection_round DESC);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_purchase_line
                    ON quality_inspection (purchase_line_id);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_part
                    ON quality_inspection (part_number);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_status
                    ON quality_inspection (status);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_operator
                    ON quality_inspection (operator_account);
                CREATE INDEX IF NOT EXISTS idx_quality_inspection_event_history
                    ON quality_inspection_event (inspection_id, created_at, id);
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def create_or_get(
        self,
        *,
        record: dict[str, Any],
        operator: OperatorContext,
        event_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        normalized = self._normalize_record(record, operator=operator)
        if self.database_url.startswith("memory://"):
            async with self._memory_lock:
                existing = self._memory_existing(
                    idempotency_key=normalized["idempotencyKey"],
                    arrival_batch_id=normalized["arrivalBatchID"],
                    inspection_round=normalized["inspectionRound"],
                )
                if existing:
                    replay_event = self._new_event(
                        inspection_id=existing["id"],
                        event_type="IDEMPOTENT_REPLAY",
                        from_status=existing["status"],
                        to_status=existing["status"],
                        operator=operator,
                        payload=event_payload,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self._memory_events.setdefault(existing["id"], []).append(replay_event)
                    return copy.deepcopy(existing), False
                self._memory_records[normalized["id"]] = copy.deepcopy(normalized)
                event = self._new_event(
                    inspection_id=normalized["id"],
                    event_type="INSPECTION_CREATED",
                    from_status="",
                    to_status=normalized["status"],
                    operator=operator,
                    payload=event_payload,
                    created_at=normalized["createdAt"],
                )
                self._memory_events[normalized["id"]] = [event]
                return copy.deepcopy(normalized), True

        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO quality_inspection (
                        inspection_id, purchase_line_id, arrival_batch_id,
                        inspection_round, idempotency_key, purchase_order_number,
                        nb_number, part_number, part_name, supplier_name,
                        arrival_date, arrival_quantity, returned_quantity,
                        warehoused_quantity, available_quantity, inspection_method,
                        sample_quantity, status, conclusion, spec_version,
                        check_items, source_snapshot, request_payload,
                        operator_account, operator_name, operator_privilege,
                        session_id, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14, $15, $16, $17, $18, $19,
                        $20::jsonb, $21::jsonb, $22::jsonb, $23::jsonb,
                        $24, $25, $26, $27, $28, $29
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING *
                    """,
                    normalized["id"],
                    normalized["purchaseLineID"],
                    normalized["arrivalBatchID"],
                    normalized["inspectionRound"],
                    normalized["idempotencyKey"],
                    normalized["purchaseOrderNumber"],
                    normalized["nbNumber"],
                    normalized["partNumber"],
                    normalized["partName"],
                    normalized["supplierName"],
                    normalized["arrivalDate"],
                    normalized["arrivalQuantity"],
                    normalized["returnedQuantity"],
                    normalized["warehousedQuantity"],
                    normalized["availableQuantity"],
                    normalized["inspectionMethod"],
                    normalized["sampleQuantity"],
                    normalized["status"],
                    normalized["conclusion"],
                    self._json(normalized["specVersion"]),
                    self._json(normalized["checkItems"]),
                    self._json(normalized["sourceSnapshot"]),
                    self._json(normalized["requestPayload"]),
                    normalized["operatorAccount"],
                    normalized["operatorName"],
                    normalized["operatorPrivilege"],
                    normalized["sessionId"],
                    self._datetime(normalized["createdAt"]),
                    self._datetime(normalized["updatedAt"]),
                )
                if not row:
                    row = await conn.fetchrow(
                        """
                        SELECT * FROM quality_inspection
                        WHERE idempotency_key = $1
                           OR (arrival_batch_id = $2 AND inspection_round = $3)
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        normalized["idempotencyKey"],
                        normalized["arrivalBatchID"],
                        normalized["inspectionRound"],
                    )
                    if not row:
                        raise RuntimeError("Quality inspection conflict could not be resolved")
                    replay_event = self._new_event(
                        inspection_id=row["inspection_id"],
                        event_type="IDEMPOTENT_REPLAY",
                        from_status=row["status"],
                        to_status=row["status"],
                        operator=operator,
                        payload=event_payload,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    )
                    await self._insert_event(conn, replay_event)
                    return self._record_from_row(row), False

                event = self._new_event(
                    inspection_id=normalized["id"],
                    event_type="INSPECTION_CREATED",
                    from_status="",
                    to_status=normalized["status"],
                    operator=operator,
                    payload=event_payload,
                    created_at=normalized["createdAt"],
                )
                await self._insert_event(conn, event)
                return self._record_from_row(row), True

    async def get_by_arrival(self, arrival_batch_id: str) -> dict[str, Any] | None:
        if self.database_url.startswith("memory://"):
            matches = [
                record
                for record in self._memory_records.values()
                if record["arrivalBatchID"] == arrival_batch_id
            ]
            if not matches:
                return None
            latest = max(
                matches,
                key=lambda item: (item["inspectionRound"], item["createdAt"]),
            )
            return copy.deepcopy(latest)

        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM quality_inspection
                WHERE arrival_batch_id = $1
                ORDER BY inspection_round DESC, created_at DESC
                LIMIT 1
                """,
                arrival_batch_id,
            )
        return self._record_from_row(row) if row else None

    async def catalog_by_arrival_ids(
        self,
        arrival_batch_ids: list[str],
    ) -> dict[str, dict[str, str]]:
        normalized = list(dict.fromkeys(item for item in arrival_batch_ids if item))
        if not normalized:
            return {}
        if self.database_url.startswith("memory://"):
            result: dict[str, dict[str, str]] = {}
            for arrival_id in normalized:
                record = await self.get_by_arrival(arrival_id)
                if record:
                    result[arrival_id] = {
                        "id": record["id"],
                        "status": record["status"],
                    }
            return result

        pool = self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (arrival_batch_id)
                    arrival_batch_id, inspection_id, status
                FROM quality_inspection
                WHERE arrival_batch_id = ANY($1::text[])
                ORDER BY arrival_batch_id, inspection_round DESC, created_at DESC
                """,
                normalized,
            )
        return {
            row["arrival_batch_id"]: {
                "id": row["inspection_id"],
                "status": row["status"],
            }
            for row in rows
        }

    async def list_inspections(
        self,
        *,
        limit: int,
        offset: int,
        query: str = "",
        status: str = "",
    ) -> tuple[list[dict[str, Any]], int]:
        query = query.strip().lower()
        status = status.strip()
        if self.database_url.startswith("memory://"):
            records = list(self._memory_records.values())
            if status:
                records = [item for item in records if item["status"] == status]
            if query:
                searchable = (
                    "id", "purchaseLineID", "arrivalBatchID",
                    "purchaseOrderNumber", "nbNumber", "partNumber",
                    "partName", "supplierName", "operatorAccount", "operatorName",
                )
                records = [
                    item for item in records
                    if any(query in str(item.get(key) or "").lower() for key in searchable)
                ]
            records.sort(key=lambda item: item["createdAt"], reverse=True)
            return copy.deepcopy(records[offset : offset + limit]), len(records)

        pool = self._require_pool()
        pattern = f"%{query}%"
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT COUNT(*) FROM quality_inspection
                WHERE ($1 = '' OR status = $1)
                  AND ($2 = '' OR lower(concat_ws(' ',
                        inspection_id, purchase_line_id, arrival_batch_id,
                        purchase_order_number, nb_number, part_number,
                        part_name, supplier_name, operator_account, operator_name
                      )) LIKE $3)
                """,
                status,
                query,
                pattern,
            )
            rows = await conn.fetch(
                """
                SELECT * FROM quality_inspection
                WHERE ($1 = '' OR status = $1)
                  AND ($2 = '' OR lower(concat_ws(' ',
                        inspection_id, purchase_line_id, arrival_batch_id,
                        purchase_order_number, nb_number, part_number,
                        part_name, supplier_name, operator_account, operator_name
                      )) LIKE $3)
                ORDER BY created_at DESC, inspection_id DESC
                LIMIT $4 OFFSET $5
                """,
                status,
                query,
                pattern,
                limit,
                offset,
            )
        return [self._record_from_row(row) for row in rows], int(total or 0)

    async def get_inspection(self, inspection_id: str) -> dict[str, Any] | None:
        if self.database_url.startswith("memory://"):
            record = self._memory_records.get(inspection_id)
            if not record:
                return None
            result = copy.deepcopy(record)
            result["events"] = copy.deepcopy(self._memory_events.get(inspection_id, []))
            return result

        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM quality_inspection WHERE inspection_id = $1",
                inspection_id,
            )
            if not row:
                return None
            event_rows = await conn.fetch(
                """
                SELECT * FROM quality_inspection_event
                WHERE inspection_id = $1
                ORDER BY created_at, id
                """,
                inspection_id,
            )
        result = self._record_from_row(row)
        result["events"] = [self._event_from_row(item) for item in event_rows]
        return result

    def _memory_existing(
        self,
        *,
        idempotency_key: str,
        arrival_batch_id: str,
        inspection_round: int,
    ) -> dict[str, Any] | None:
        return next(
            (
                record
                for record in self._memory_records.values()
                if record["idempotencyKey"] == idempotency_key
                or (
                    record["arrivalBatchID"] == arrival_batch_id
                    and record["inspectionRound"] == inspection_round
                )
            ),
            None,
        )

    @staticmethod
    def _normalize_record(
        record: dict[str, Any],
        *,
        operator: OperatorContext,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            **copy.deepcopy(record),
            "inspectionRound": int(record.get("inspectionRound") or 1),
            "conclusion": str(record.get("conclusion") or ""),
            "operatorAccount": operator.account,
            "operatorName": operator.name,
            "operatorPrivilege": operator.privilege,
            "sessionId": operator.session_id,
            "createdAt": str(record.get("createdAt") or now),
            "updatedAt": str(record.get("updatedAt") or now),
        }

    @staticmethod
    def _new_event(
        *,
        inspection_id: str,
        event_type: str,
        from_status: str,
        to_status: str,
        operator: OperatorContext,
        payload: dict[str, Any],
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "eventId": str(uuid4()),
            "inspectionID": inspection_id,
            "eventType": event_type,
            "fromStatus": from_status,
            "toStatus": to_status,
            "operatorAccount": operator.account,
            "operatorName": operator.name,
            "operatorPrivilege": operator.privilege,
            "sessionId": operator.session_id,
            "payload": copy.deepcopy(payload),
            "createdAt": created_at,
        }

    @staticmethod
    def _record_from_row(row: asyncpg.Record) -> dict[str, Any]:
        return {
            "id": row["inspection_id"],
            "purchaseLineID": row["purchase_line_id"],
            "arrivalBatchID": row["arrival_batch_id"],
            "inspectionRound": row["inspection_round"],
            "idempotencyKey": row["idempotency_key"],
            "purchaseOrderNumber": row["purchase_order_number"],
            "nbNumber": row["nb_number"],
            "partNumber": row["part_number"],
            "partName": row["part_name"],
            "supplierName": row["supplier_name"],
            "arrivalDate": row["arrival_date"],
            "arrivalQuantity": row["arrival_quantity"],
            "returnedQuantity": row["returned_quantity"],
            "warehousedQuantity": row["warehoused_quantity"],
            "availableQuantity": row["available_quantity"],
            "inspectionMethod": row["inspection_method"],
            "sampleQuantity": row["sample_quantity"],
            "status": row["status"],
            "conclusion": row["conclusion"],
            "specVersion": QualityInspectionStore._json_object(row["spec_version"]),
            "checkItems": QualityInspectionStore._json_list(row["check_items"]),
            "sourceSnapshot": QualityInspectionStore._json_object(row["source_snapshot"]),
            "requestPayload": QualityInspectionStore._json_object(row["request_payload"]),
            "operatorAccount": row["operator_account"],
            "operatorName": row["operator_name"],
            "operatorPrivilege": row["operator_privilege"],
            "sessionId": row["session_id"],
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
        }

    @staticmethod
    def _event_from_row(row: asyncpg.Record) -> dict[str, Any]:
        return {
            "eventId": str(row["event_id"]),
            "inspectionID": row["inspection_id"],
            "eventType": row["event_type"],
            "fromStatus": row["from_status"],
            "toStatus": row["to_status"],
            "operatorAccount": row["operator_account"],
            "operatorName": row["operator_name"],
            "operatorPrivilege": row["operator_privilege"],
            "sessionId": row["session_id"],
            "payload": QualityInspectionStore._json_object(row["payload"]),
            "createdAt": row["created_at"].isoformat(),
        }

    def _require_pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("QualityInspectionStore is not initialized")
        return self._pool

    async def _insert_event(
        self,
        conn: asyncpg.Connection,
        event: dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO quality_inspection_event (
                event_id, inspection_id, event_type, from_status,
                to_status, operator_account, operator_name,
                operator_privilege, session_id, payload, created_at
            ) VALUES (
                $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                $10::jsonb, $11
            )
            """,
            event["eventId"],
            event["inspectionID"],
            event["eventType"],
            event["fromStatus"],
            event["toStatus"],
            event["operatorAccount"],
            event["operatorName"],
            event["operatorPrivilege"],
            event["sessionId"],
            self._json(event["payload"]),
            self._datetime(event["createdAt"]),
        )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return list(value)
        if isinstance(value, str):
            parsed = json.loads(value)
            return list(parsed) if isinstance(parsed, list) else []
        return []

    @staticmethod
    def _datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

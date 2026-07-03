import json
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from app.services.audit_log import OperatorContext


class BomDocumentStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_documents: dict[str, dict[str, Any]] = {}

    async def init(self) -> None:
        if self.database_url.startswith("memory://"):
            return
        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bom_calc_document (
                    id UUID PRIMARY KEY,
                    document_no TEXT NOT NULL UNIQUE,
                    product_sku TEXT NOT NULL,
                    product_name TEXT NOT NULL DEFAULT '',
                    product_name_cn TEXT NOT NULL DEFAULT '',
                    generate_qty NUMERIC NOT NULL,
                    status TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    operator_privilege TEXT NOT NULL DEFAULT '',
                    line_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS bom_calc_line (
                    id UUID PRIMARY KEY,
                    document_id UUID NOT NULL REFERENCES bom_calc_document(id) ON DELETE CASCADE,
                    line_no INTEGER NOT NULL,
                    source_bom_record_id TEXT,
                    part_no TEXT NOT NULL,
                    part_name TEXT NOT NULL DEFAULT '',
                    bom_qty NUMERIC NOT NULL,
                    calculated_qty NUMERIC NOT NULL,
                    actual_qty NUMERIC,
                    warehouse TEXT NOT NULL DEFAULT '',
                    position1 TEXT NOT NULL DEFAULT '',
                    position2 TEXT NOT NULL DEFAULT '',
                    stock_snapshot NUMERIC,
                    issue_time TIMESTAMPTZ,
                    raw JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_bom_calc_document_product_sku
                    ON bom_calc_document (product_sku);
                CREATE INDEX IF NOT EXISTS idx_bom_calc_line_document_id
                    ON bom_calc_line (document_id, line_no);
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def confirm_document(
        self,
        *,
        document_id: str | None = None,
        product: dict[str, Any],
        generate_qty: float,
        lines: list[dict[str, Any]],
        operator: OperatorContext,
    ) -> dict[str, Any]:
        document_id = document_id or str(uuid.uuid4())
        document_no = self._document_no()
        now = datetime.now(tz=timezone.utc)
        document = {
            "id": document_id,
            "documentNo": document_no,
            "productSku": str(product.get("productSku") or ""),
            "productName": str(product.get("productName") or ""),
            "productNameCn": str(product.get("productNameCn") or ""),
            "generateQty": generate_qty,
            "status": "confirmed",
            "operatorAccount": operator.account,
            "operatorName": operator.name,
            "operatorPrivilege": operator.privilege,
            "lineCount": len(lines),
            "createdAt": now.isoformat(),
            "lines": [],
        }
        normalized_lines = [
            self._normalize_line(line, document_id=document_id, line_no=index + 1, now=now)
            for index, line in enumerate(lines)
        ]
        document["lines"] = normalized_lines

        if self.database_url.startswith("memory://"):
            self._memory_documents[document_id] = document
            return document

        if not self._pool:
            raise RuntimeError("BomDocumentStore is not initialized")

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO bom_calc_document (
                        id,
                        document_no,
                        product_sku,
                        product_name,
                        product_name_cn,
                        generate_qty,
                        status,
                        operator_account,
                        operator_name,
                        operator_privilege,
                        line_count,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    """,
                    uuid.UUID(document_id),
                    document_no,
                    document["productSku"],
                    document["productName"],
                    document["productNameCn"],
                    generate_qty,
                    "confirmed",
                    operator.account,
                    operator.name,
                    operator.privilege,
                    len(normalized_lines),
                    now,
                )
                await conn.executemany(
                    """
                    INSERT INTO bom_calc_line (
                        id,
                        document_id,
                        line_no,
                        source_bom_record_id,
                        part_no,
                        part_name,
                        bom_qty,
                        calculated_qty,
                        actual_qty,
                        warehouse,
                        position1,
                        position2,
                        stock_snapshot,
                        issue_time,
                        raw,
                        created_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9,
                        $10, $11, $12, $13, $14, $15::jsonb, $16
                    )
                    """,
                    [
                        (
                            uuid.UUID(line["id"]),
                            uuid.UUID(document_id),
                            line["lineNo"],
                            line.get("sourceBomRecordId") or None,
                            line["partNo"],
                            line["partName"],
                            line["bomQty"],
                            line["calculatedQty"],
                            line.get("actualQty"),
                            line["warehouse"],
                            line["position1"],
                            line["position2"],
                            line.get("stockSnapshot"),
                            None,
                            json.dumps(line.get("raw") or {}, ensure_ascii=False, default=str),
                            now,
                        )
                        for line in normalized_lines
                    ],
                )
        return document

    async def get_document(self, document_id: str) -> dict[str, Any] | None:
        if self.database_url.startswith("memory://"):
            return self._memory_documents.get(document_id)
        if not self._pool:
            raise RuntimeError("BomDocumentStore is not initialized")

        async with self._pool.acquire() as conn:
            document_row = await conn.fetchrow(
                """
                SELECT
                    id,
                    document_no,
                    product_sku,
                    product_name,
                    product_name_cn,
                    generate_qty,
                    status,
                    operator_account,
                    operator_name,
                    operator_privilege,
                    line_count,
                    created_at
                FROM bom_calc_document
                WHERE id = $1
                """,
                uuid.UUID(document_id),
            )
            if not document_row:
                return None
            line_rows = await conn.fetch(
                """
                SELECT
                    id,
                    line_no,
                    source_bom_record_id,
                    part_no,
                    part_name,
                    bom_qty,
                    calculated_qty,
                    actual_qty,
                    warehouse,
                    position1,
                    position2,
                    stock_snapshot,
                    issue_time,
                    raw,
                    created_at
                FROM bom_calc_line
                WHERE document_id = $1
                ORDER BY line_no
                """,
                uuid.UUID(document_id),
            )
        return {
            "id": str(document_row["id"]),
            "documentNo": document_row["document_no"],
            "productSku": document_row["product_sku"],
            "productName": document_row["product_name"],
            "productNameCn": document_row["product_name_cn"],
            "generateQty": float(document_row["generate_qty"]),
            "status": document_row["status"],
            "operatorAccount": document_row["operator_account"],
            "operatorName": document_row["operator_name"],
            "operatorPrivilege": document_row["operator_privilege"],
            "lineCount": document_row["line_count"],
            "createdAt": document_row["created_at"].isoformat(),
            "lines": [self._db_line_to_dict(row) for row in line_rows],
        }

    def _normalize_line(
        self,
        line: dict[str, Any],
        *,
        document_id: str,
        line_no: int,
        now: datetime,
    ) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "documentId": document_id,
            "lineNo": line_no,
            "sourceBomRecordId": str(line.get("sourceBomRecordId") or ""),
            "partNo": str(line.get("partNo") or ""),
            "partName": str(line.get("partName") or ""),
            "bomQty": self._number(line.get("bomQty")),
            "calculatedQty": self._number(line.get("calculatedQty")),
            "actualQty": self._optional_number(line.get("actualQty")),
            "warehouse": str(line.get("warehouse") or ""),
            "position1": str(line.get("position1") or ""),
            "position2": str(line.get("position2") or ""),
            "stockSnapshot": self._optional_number(line.get("stockSnapshot")),
            "issueTime": line.get("issueTime") or "",
            "raw": line.get("raw") or {},
            "createdAt": now.isoformat(),
        }

    def _db_line_to_dict(self, row: asyncpg.Record) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "lineNo": row["line_no"],
            "sourceBomRecordId": row["source_bom_record_id"] or "",
            "partNo": row["part_no"],
            "partName": row["part_name"],
            "bomQty": float(row["bom_qty"]),
            "calculatedQty": float(row["calculated_qty"]),
            "actualQty": float(row["actual_qty"]) if row["actual_qty"] is not None else None,
            "warehouse": row["warehouse"],
            "position1": row["position1"],
            "position2": row["position2"],
            "stockSnapshot": (
                float(row["stock_snapshot"]) if row["stock_snapshot"] is not None else None
            ),
            "issueTime": row["issue_time"].isoformat() if row["issue_time"] else "",
            "raw": row["raw"] or {},
            "createdAt": row["created_at"].isoformat(),
        }

    def _document_no(self) -> str:
        return "BOM-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6].upper()

    def _number(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _optional_number(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        return self._number(value)

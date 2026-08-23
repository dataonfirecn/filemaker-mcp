from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import aiosqlite


@dataclass(frozen=True)
class ReceiptAttachmentRecord:
    attachment_id: str
    draft_id: str
    shipment_id: str
    pi_number: str
    line_id: str | None
    object_key: str
    original_filename: str
    mime_type: str
    file_size: int
    sha256: str
    source: str
    operator_account: str
    status: str
    etag: str | None
    created_at: datetime
    uploaded_at: datetime | None


class ReceiptAttachmentStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._memory_rows: dict[str, ReceiptAttachmentRecord] = {}

    @property
    def _is_memory(self) -> bool:
        return self.database_path.startswith("memory://")

    async def init(self) -> None:
        if self._is_memory:
            return
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS receipt_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    shipment_id TEXT NOT NULL,
                    pi_number TEXT NOT NULL,
                    line_id TEXT,
                    object_key TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    status TEXT NOT NULL,
                    etag TEXT,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_receipt_attachments_draft
                ON receipt_attachments (draft_id, operator_account, status)
                """
            )
            await db.commit()

    async def create(self, record: ReceiptAttachmentRecord) -> None:
        if self._is_memory:
            self._memory_rows[record.attachment_id] = record
            return
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO receipt_attachments (
                    attachment_id, draft_id, shipment_id, pi_number, line_id,
                    object_key, original_filename, mime_type, file_size, sha256,
                    source, operator_account, status, etag, created_at, uploaded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _record_values(record),
            )
            await db.commit()

    async def get(self, attachment_id: str) -> ReceiptAttachmentRecord | None:
        if self._is_memory:
            return self._memory_rows.get(attachment_id)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM receipt_attachments WHERE attachment_id = ?",
                (attachment_id,),
            )
            row = await cursor.fetchone()
        return _from_row(dict(row)) if row else None

    async def list_for_history(
        self,
        *,
        line_id: str,
        shipment_id: str = "",
        limit: int = 100,
    ) -> list[ReceiptAttachmentRecord]:
        active_statuses = {"UPLOADED", "BOUND"}
        safe_limit = max(1, min(int(limit), 500))
        if self._is_memory:
            rows = [
                row
                for row in self._memory_rows.values()
                if row.status in active_statuses
                and (
                    row.line_id == line_id
                    or (
                        shipment_id
                        and row.line_id is None
                        and row.shipment_id == shipment_id
                    )
                )
            ]
            return sorted(
                rows,
                key=lambda row: row.uploaded_at or row.created_at,
                reverse=True,
            )[:safe_limit]

        clauses = ["line_id = ?"]
        parameters: list[object] = [line_id]
        if shipment_id:
            clauses.append("(line_id IS NULL AND shipment_id = ?)")
            parameters.append(shipment_id)
        parameters.append(safe_limit)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT * FROM receipt_attachments
                WHERE status IN ('UPLOADED', 'BOUND')
                  AND ({' OR '.join(clauses)})
                ORDER BY COALESCE(uploaded_at, created_at) DESC
                LIMIT ?
                """,
                tuple(parameters),
            )
            rows = await cursor.fetchall()
        return [_from_row(dict(row)) for row in rows]

    async def count_active(self, draft_id: str, operator_account: str) -> int:
        active_statuses = {"PENDING", "UPLOADED", "BOUND"}
        if self._is_memory:
            return sum(
                1
                for row in self._memory_rows.values()
                if row.draft_id == draft_id
                and row.operator_account == operator_account
                and row.status in active_statuses
            )
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM receipt_attachments
                WHERE draft_id = ? AND operator_account = ?
                  AND status IN ('PENDING', 'UPLOADED', 'BOUND')
                """,
                (draft_id, operator_account),
            )
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def count_active_for_line(
        self,
        draft_id: str,
        operator_account: str,
        line_id: str | None,
    ) -> int:
        active_statuses = {"PENDING", "UPLOADED", "BOUND"}
        if self._is_memory:
            return sum(
                1
                for row in self._memory_rows.values()
                if row.draft_id == draft_id
                and row.operator_account == operator_account
                and row.line_id == line_id
                and row.status in active_statuses
            )
        line_predicate = "line_id IS NULL" if line_id is None else "line_id = ?"
        parameters: tuple[str, ...] = (
            (draft_id, operator_account)
            if line_id is None
            else (draft_id, operator_account, line_id)
        )
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                f"""
                SELECT COUNT(*) FROM receipt_attachments
                WHERE draft_id = ? AND operator_account = ?
                  AND {line_predicate}
                  AND status IN ('PENDING', 'UPLOADED', 'BOUND')
                """,
                parameters,
            )
            row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def mark_uploaded(
        self,
        attachment_id: str,
        *,
        etag: str,
        uploaded_at: datetime | None = None,
    ) -> ReceiptAttachmentRecord | None:
        existing = await self.get(attachment_id)
        if not existing:
            return None
        updated = ReceiptAttachmentRecord(
            **{
                **asdict(existing),
                "status": "UPLOADED",
                "etag": etag,
                "uploaded_at": uploaded_at or datetime.now(timezone.utc),
            }
        )
        if self._is_memory:
            self._memory_rows[attachment_id] = updated
            return updated
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE receipt_attachments
                SET status = 'UPLOADED', etag = ?, uploaded_at = ?
                WHERE attachment_id = ?
                """,
                (updated.etag, updated.uploaded_at.isoformat(), attachment_id),
            )
            await db.commit()
        return updated

    async def mark_bound(self, attachment_id: str) -> ReceiptAttachmentRecord | None:
        existing = await self.get(attachment_id)
        if not existing:
            return None
        updated = ReceiptAttachmentRecord(
            **{
                **asdict(existing),
                "status": "BOUND",
            }
        )
        if self._is_memory:
            self._memory_rows[attachment_id] = updated
            return updated
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE receipt_attachments
                SET status = 'BOUND'
                WHERE attachment_id = ?
                """,
                (attachment_id,),
            )
            await db.commit()
        return updated


def _record_values(record: ReceiptAttachmentRecord) -> tuple:
    return (
        record.attachment_id,
        record.draft_id,
        record.shipment_id,
        record.pi_number,
        record.line_id,
        record.object_key,
        record.original_filename,
        record.mime_type,
        record.file_size,
        record.sha256,
        record.source,
        record.operator_account,
        record.status,
        record.etag,
        record.created_at.isoformat(),
        record.uploaded_at.isoformat() if record.uploaded_at else None,
    )


def _from_row(row: dict) -> ReceiptAttachmentRecord:
    return ReceiptAttachmentRecord(
        attachment_id=str(row["attachment_id"]),
        draft_id=str(row["draft_id"]),
        shipment_id=str(row["shipment_id"]),
        pi_number=str(row["pi_number"]),
        line_id=str(row["line_id"]) if row.get("line_id") else None,
        object_key=str(row["object_key"]),
        original_filename=str(row["original_filename"]),
        mime_type=str(row["mime_type"]),
        file_size=int(row["file_size"]),
        sha256=str(row["sha256"]),
        source=str(row["source"]),
        operator_account=str(row["operator_account"]),
        status=str(row["status"]),
        etag=str(row["etag"]) if row.get("etag") else None,
        created_at=datetime.fromisoformat(str(row["created_at"])),
        uploaded_at=(
            datetime.fromisoformat(str(row["uploaded_at"]))
            if row.get("uploaded_at")
            else None
        ),
    )

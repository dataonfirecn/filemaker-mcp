from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import aiosqlite


@dataclass(frozen=True)
class PartAssetUploadRecord:
    upload_id: str
    draft_id: str
    object_key: str
    original_filename: str
    mime_type: str
    file_size: int
    sha256: str
    asset_type: str
    asset_role: str
    visibility: str
    source: str
    operator_account: str
    status: str
    etag: str | None
    part_id: str | None
    part_number: str | None
    part_record_id: str | None
    asset_record_id: str | None
    created_at: datetime
    uploaded_at: datetime | None
    bound_at: datetime | None


class PartAssetUploadStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._memory_rows: dict[str, PartAssetUploadRecord] = {}

    @property
    def _is_memory(self) -> bool:
        return self.database_path.startswith("memory://")

    async def init(self) -> None:
        if self._is_memory:
            return
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS part_asset_uploads (
                    upload_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    asset_role TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    source TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    status TEXT NOT NULL,
                    etag TEXT,
                    part_id TEXT,
                    part_number TEXT,
                    part_record_id TEXT,
                    asset_record_id TEXT,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    bound_at TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_part_asset_uploads_owner
                ON part_asset_uploads (operator_account, draft_id, status)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_part_asset_uploads_part
                ON part_asset_uploads (part_id, status)
                """
            )
            await db.commit()

    async def create(self, record: PartAssetUploadRecord) -> None:
        if self._is_memory:
            self._memory_rows[record.upload_id] = record
            return
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO part_asset_uploads (
                    upload_id, draft_id, object_key, original_filename,
                    mime_type, file_size, sha256, asset_type, asset_role,
                    visibility, source, operator_account, status, etag,
                    part_id, part_number, part_record_id, asset_record_id,
                    created_at, uploaded_at, bound_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _record_values(record),
            )
            await db.commit()

    async def get(self, upload_id: str) -> PartAssetUploadRecord | None:
        if self._is_memory:
            return self._memory_rows.get(upload_id)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM part_asset_uploads WHERE upload_id = ?",
                (upload_id,),
            )
            row = await cursor.fetchone()
        return _from_row(dict(row)) if row else None

    async def mark_uploaded(
        self,
        upload_id: str,
        *,
        etag: str,
        uploaded_at: datetime | None = None,
    ) -> PartAssetUploadRecord | None:
        return await self._update(
            upload_id,
            status="UPLOADED",
            etag=etag,
            uploaded_at=uploaded_at or datetime.now(timezone.utc),
        )

    async def mark_bound(
        self,
        upload_id: str,
        *,
        part_id: str,
        part_number: str,
        part_record_id: str,
        asset_record_id: str,
        bound_at: datetime | None = None,
    ) -> PartAssetUploadRecord | None:
        return await self._update(
            upload_id,
            status="BOUND",
            part_id=part_id,
            part_number=part_number,
            part_record_id=part_record_id,
            asset_record_id=asset_record_id,
            bound_at=bound_at or datetime.now(timezone.utc),
        )

    async def _update(self, upload_id: str, **changes) -> PartAssetUploadRecord | None:
        existing = await self.get(upload_id)
        if not existing:
            return None
        updated = PartAssetUploadRecord(**{**asdict(existing), **changes})
        if self._is_memory:
            self._memory_rows[upload_id] = updated
            return updated
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE part_asset_uploads
                SET status = ?, etag = ?, part_id = ?, part_number = ?,
                    part_record_id = ?, asset_record_id = ?, uploaded_at = ?, bound_at = ?
                WHERE upload_id = ?
                """,
                (
                    updated.status,
                    updated.etag,
                    updated.part_id,
                    updated.part_number,
                    updated.part_record_id,
                    updated.asset_record_id,
                    _iso(updated.uploaded_at),
                    _iso(updated.bound_at),
                    upload_id,
                ),
            )
            await db.commit()
        return updated


def _record_values(record: PartAssetUploadRecord) -> tuple:
    return (
        record.upload_id,
        record.draft_id,
        record.object_key,
        record.original_filename,
        record.mime_type,
        record.file_size,
        record.sha256,
        record.asset_type,
        record.asset_role,
        record.visibility,
        record.source,
        record.operator_account,
        record.status,
        record.etag,
        record.part_id,
        record.part_number,
        record.part_record_id,
        record.asset_record_id,
        record.created_at.isoformat(),
        _iso(record.uploaded_at),
        _iso(record.bound_at),
    )


def _from_row(row: dict) -> PartAssetUploadRecord:
    return PartAssetUploadRecord(
        upload_id=str(row["upload_id"]),
        draft_id=str(row["draft_id"]),
        object_key=str(row["object_key"]),
        original_filename=str(row["original_filename"]),
        mime_type=str(row["mime_type"]),
        file_size=int(row["file_size"]),
        sha256=str(row["sha256"]),
        asset_type=str(row["asset_type"]),
        asset_role=str(row["asset_role"]),
        visibility=str(row["visibility"]),
        source=str(row["source"]),
        operator_account=str(row["operator_account"]),
        status=str(row["status"]),
        etag=str(row["etag"]) if row.get("etag") else None,
        part_id=str(row["part_id"]) if row.get("part_id") else None,
        part_number=str(row["part_number"]) if row.get("part_number") else None,
        part_record_id=str(row["part_record_id"]) if row.get("part_record_id") else None,
        asset_record_id=(
            str(row["asset_record_id"]) if row.get("asset_record_id") else None
        ),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        uploaded_at=_datetime(row.get("uploaded_at")),
        bound_at=_datetime(row.get("bound_at")),
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None

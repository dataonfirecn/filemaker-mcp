from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite


ACTIVE_SESSION_TTL = timedelta(hours=2)
MAX_PRODUCT_PHOTOS_PER_SESSION = 6


class ProductPhotoUploadStoreError(RuntimeError):
    pass


class ProductPhotoSessionConflict(ProductPhotoUploadStoreError):
    pass


class ProductPhotoSessionFull(ProductPhotoUploadStoreError):
    pass


@dataclass(frozen=True)
class ProductPhotoUploadRecord:
    upload_id: str
    session_id: str
    product_sku: str
    product_record_id: str
    source_mod_id: str
    slot: int
    object_key: str
    original_filename: str
    mime_type: str
    file_size: int
    sha256: str
    source: str
    operator_account: str
    status: str
    etag: str | None
    asset_record_id: str | None
    last_error: str | None
    created_at: datetime
    uploaded_at: datetime | None
    synced_at: datetime | None


class ProductPhotoUploadStore:
    def __init__(self, database_path: str):
        self.database_path = database_path

    async def init(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS product_photo_uploads (
                    upload_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    product_sku TEXT NOT NULL,
                    product_record_id TEXT NOT NULL,
                    source_mod_id TEXT NOT NULL DEFAULT '',
                    slot INTEGER NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    original_filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    status TEXT NOT NULL,
                    etag TEXT,
                    asset_record_id TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    synced_at TEXT,
                    UNIQUE(session_id, slot)
                )
                """
            )
            await connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_product_photo_uploads_session
                ON product_photo_uploads(product_sku, operator_account, session_id)
                """
            )
            # A SYNCING row only has an in-process FastAPI background task behind
            # it. If the process restarted, there is no task left to finish it.
            await connection.execute(
                """
                UPDATE product_photo_uploads
                SET status = 'UPLOADED'
                WHERE status = 'SYNCING'
                """
            )
            await connection.commit()

    async def has_session(
        self,
        *,
        product_sku: str,
        operator_account: str,
        session_id: str,
    ) -> bool:
        cutoff = _iso(datetime.now(timezone.utc) - ACTIVE_SESSION_TTL)
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                SELECT 1
                FROM product_photo_uploads
                WHERE product_sku = ?
                  AND operator_account = ?
                  AND session_id = ?
                  AND created_at >= ?
                LIMIT 1
                """,
                (product_sku, operator_account, session_id, cutoff),
            )
            return await cursor.fetchone() is not None

    async def claim_slot(
        self,
        *,
        upload_id: str,
        session_id: str,
        product_sku: str,
        product_record_id: str,
        source_mod_id: str,
        object_key: str,
        original_filename: str,
        mime_type: str,
        file_size: int,
        sha256: str,
        source: str,
        operator_account: str,
    ) -> ProductPhotoUploadRecord:
        now = datetime.now(timezone.utc)
        cutoff = _iso(now - ACTIVE_SESSION_TTL)
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                """
                SELECT session_id, operator_account
                FROM product_photo_uploads
                WHERE product_sku = ?
                  AND created_at >= ?
                  AND status != 'ORPHAN'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (product_sku, cutoff),
            )
            active = await cursor.fetchone()
            if active and (
                str(active["session_id"]) != session_id
                or str(active["operator_account"]) != operator_account
            ):
                await connection.rollback()
                raise ProductPhotoSessionConflict(
                    "该产品已有另一个补图会话，请稍后刷新产品资料。"
                )

            cursor = await connection.execute(
                """
                SELECT COUNT(*)
                FROM product_photo_uploads
                WHERE product_sku = ?
                  AND session_id = ?
                  AND status != 'ORPHAN'
                """,
                (product_sku, session_id),
            )
            count = int((await cursor.fetchone())[0])
            if count >= MAX_PRODUCT_PHOTOS_PER_SESSION:
                await connection.rollback()
                raise ProductPhotoSessionFull("每个无图产品最多补拍 6 张照片。")
            slot = count + 1
            await connection.execute(
                """
                INSERT INTO product_photo_uploads (
                    upload_id, session_id, product_sku, product_record_id,
                    source_mod_id, slot, object_key, original_filename,
                    mime_type, file_size, sha256, source, operator_account,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    upload_id,
                    session_id,
                    product_sku,
                    product_record_id,
                    source_mod_id,
                    slot,
                    object_key,
                    original_filename,
                    mime_type,
                    file_size,
                    sha256,
                    source,
                    operator_account,
                    _iso(now),
                ),
            )
            await connection.commit()
        record = await self.get(upload_id)
        if not record:
            raise ProductPhotoUploadStoreError("补图上传记录保存失败。")
        return record

    async def get(self, upload_id: str) -> ProductPhotoUploadRecord | None:
        async with aiosqlite.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = await connection.execute(
                "SELECT * FROM product_photo_uploads WHERE upload_id = ?",
                (upload_id,),
            )
            row = await cursor.fetchone()
        return _record(row) if row else None

    async def bind_asset(
        self,
        upload_id: str,
        *,
        object_key: str,
        asset_record_id: str,
    ) -> ProductPhotoUploadRecord | None:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                UPDATE product_photo_uploads
                SET object_key = ?, asset_record_id = ?
                WHERE upload_id = ? AND status = 'PENDING'
                """,
                (object_key, asset_record_id, upload_id),
            )
            await connection.commit()
        return await self.get(upload_id)

    async def mark_uploaded(
        self,
        upload_id: str,
        *,
        etag: str,
    ) -> ProductPhotoUploadRecord | None:
        return await self._update(
            upload_id,
            status="UPLOADED",
            etag=etag,
            uploaded_at=_iso(datetime.now(timezone.utc)),
            last_error=None,
        )

    async def claim_syncing(
        self,
        upload_id: str,
        *,
        etag: str | None = None,
    ) -> ProductPhotoUploadRecord | None:
        """Atomically claim one uploaded object for FileMaker synchronization."""
        now = _iso(datetime.now(timezone.utc))
        updates = [
            "status = 'SYNCING'",
            "last_error = NULL",
            "uploaded_at = COALESCE(uploaded_at, ?)",
        ]
        values: list[object] = [now]
        if etag is not None:
            updates.append("etag = ?")
            values.append(etag)
        values.append(upload_id)
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                f"""
                UPDATE product_photo_uploads
                SET {", ".join(updates)}
                WHERE upload_id = ?
                  AND status IN ('PENDING', 'UPLOADED', 'FAILED')
                """,
                values,
            )
            await connection.commit()
            claimed = cursor.rowcount > 0
        return await self.get(upload_id) if claimed else None

    async def mark_synced(
        self,
        upload_id: str,
        *,
        asset_record_id: str,
    ) -> ProductPhotoUploadRecord | None:
        return await self._update(
            upload_id,
            status="SYNCED",
            asset_record_id=asset_record_id,
            synced_at=_iso(datetime.now(timezone.utc)),
            last_error=None,
        )

    async def mark_failed(
        self,
        upload_id: str,
        *,
        error: str,
    ) -> ProductPhotoUploadRecord | None:
        return await self._update(
            upload_id,
            status="FAILED",
            last_error=error[:1000],
        )

    async def _update(
        self,
        upload_id: str,
        *,
        status: str,
        etag: str | None = None,
        asset_record_id: str | None = None,
        last_error: str | None = None,
        uploaded_at: str | None = None,
        synced_at: str | None = None,
    ) -> ProductPhotoUploadRecord | None:
        updates = ["status = ?", "last_error = ?"]
        values: list[object] = [status, last_error]
        if etag is not None:
            updates.append("etag = ?")
            values.append(etag)
        if asset_record_id is not None:
            updates.append("asset_record_id = ?")
            values.append(asset_record_id)
        if uploaded_at is not None:
            updates.append("uploaded_at = ?")
            values.append(uploaded_at)
        if synced_at is not None:
            updates.append("synced_at = ?")
            values.append(synced_at)
        values.append(upload_id)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                f"UPDATE product_photo_uploads SET {', '.join(updates)} "
                "WHERE upload_id = ?",
                values,
            )
            await connection.commit()
        return await self.get(upload_id)


def _record(row: sqlite3.Row) -> ProductPhotoUploadRecord:
    return ProductPhotoUploadRecord(
        upload_id=str(row["upload_id"]),
        session_id=str(row["session_id"]),
        product_sku=str(row["product_sku"]),
        product_record_id=str(row["product_record_id"]),
        source_mod_id=str(row["source_mod_id"] or ""),
        slot=int(row["slot"]),
        object_key=str(row["object_key"]),
        original_filename=str(row["original_filename"]),
        mime_type=str(row["mime_type"]),
        file_size=int(row["file_size"]),
        sha256=str(row["sha256"]),
        source=str(row["source"]),
        operator_account=str(row["operator_account"]),
        status=str(row["status"]),
        etag=str(row["etag"]) if row["etag"] else None,
        asset_record_id=(
            str(row["asset_record_id"]) if row["asset_record_id"] else None
        ),
        last_error=str(row["last_error"]) if row["last_error"] else None,
        created_at=_datetime(row["created_at"]),
        uploaded_at=_datetime(row["uploaded_at"]) if row["uploaded_at"] else None,
        synced_at=_datetime(row["synced_at"]) if row["synced_at"] else None,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)

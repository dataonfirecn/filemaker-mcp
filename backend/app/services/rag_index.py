from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite

from app.core.config import Settings
from app.services.metadata_semantics import (
    build_layout_semantic_profile,
    fallback_layout_semantic_profile,
    semantic_priority_fields,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.rag_embeddings import (
    RagEmbeddingClient,
    RagEmbeddingError,
    cosine_from_normalized,
    embedding_content_hash,
    pack_vector,
)
from app.services.rag_semantic_registry import RagEntity, RagSemanticRegistry

logger = logging.getLogger(__name__)

_STOCK_FIELD_PRIORITY = (
    "stock_on_hand_qty",
    "current_stock",
    "Stock",
    "stock",
    "stockQty",
    "stock_qty",
    "零件_BOM::current_stock",
    "库存",
    "庫存",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refresh_wait_seconds(settings: Settings) -> float:
    schedule_time = settings.rag_index_refresh_schedule_time.strip()
    if not schedule_time:
        return max(60, settings.rag_index_refresh_interval_seconds)

    try:
        tz = ZoneInfo(settings.rag_index_refresh_schedule_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return _seconds_until_daily_time(datetime.now(tz), schedule_time)


def _seconds_until_daily_time(now: datetime, schedule_time: str) -> float:
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", schedule_time.strip())
    if not match:
        return 24 * 60 * 60

    hour = int(match.group(1))
    minute = int(match.group(2))
    target = datetime.combine(now.date(), time(hour=hour, minute=minute), tzinfo=now.tzinfo)
    if target <= now:
        target += timedelta(days=1)
    return max(60.0, (target - now).total_seconds())


@dataclass
class RagRecordChunk:
    layout: str
    record_id: str
    mod_id: str
    title: str
    content: str
    fields: dict[str, Any]
    updated_at: str
    score: float = 0
    snippet: str = ""


@dataclass
class RagRecordResult:
    records: list[RagRecordChunk]
    found_count: int


@dataclass(frozen=True)
class LayoutDateFields:
    created_field: str = ""
    updated_field: str = ""
    source: str = ""


class RagIndexStore:
    def __init__(self, database_path: str, *, settings: Settings | None = None):
        self.database_path = database_path
        self.fts_enabled = False
        self.settings = settings
        self.embedding_client = RagEmbeddingClient(settings) if settings else None

    async def init(self) -> None:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_index_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    error TEXT,
                    layouts_indexed INTEGER NOT NULL DEFAULT 0,
                    records_indexed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_layout_profiles (
                    layout TEXT PRIMARY KEY,
                    field_count INTEGER NOT NULL DEFAULT 0,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    indexed_count INTEGER NOT NULL DEFAULT 0,
                    created_field TEXT NOT NULL DEFAULT '',
                    updated_field TEXT NOT NULL DEFAULT '',
                    field_source TEXT NOT NULL DEFAULT '',
                    fields_json TEXT NOT NULL DEFAULT '[]',
                    sample_json TEXT NOT NULL DEFAULT '[]',
                    semantic_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    run_id INTEGER
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_record_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    layout TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    mod_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    field_data_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL,
                    run_id INTEGER NOT NULL,
                    UNIQUE(layout, record_id)
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_record_chunks_layout
                ON rag_record_chunks(layout)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_record_chunks_run
                ON rag_record_chunks(run_id)
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_record_embeddings (
                    layout TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (layout, record_id, model)
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_record_embeddings_model
                ON rag_record_embeddings(model, layout)
                """
            )
            try:
                await db.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS rag_record_fts
                    USING fts5(layout, record_id, title, content, tokenize='unicode61')
                    """
                )
                self.fts_enabled = True
            except aiosqlite.Error:
                self.fts_enabled = False
                logger.exception("SQLite FTS5 is unavailable; RAG search will use LIKE fallback")
            await self._ensure_profile_columns(db)
            await self._ensure_chunk_columns(db)
            await self._backfill_content_hashes(db)
            await db.commit()

    async def _ensure_profile_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(rag_layout_profiles)")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        migrations = {
            "created_field": "ALTER TABLE rag_layout_profiles ADD COLUMN created_field TEXT NOT NULL DEFAULT ''",
            "updated_field": "ALTER TABLE rag_layout_profiles ADD COLUMN updated_field TEXT NOT NULL DEFAULT ''",
            "field_source": "ALTER TABLE rag_layout_profiles ADD COLUMN field_source TEXT NOT NULL DEFAULT ''",
            "semantic_json": "ALTER TABLE rag_layout_profiles ADD COLUMN semantic_json TEXT NOT NULL DEFAULT '{}'",
        }
        for column, statement in migrations.items():
            if column not in columns:
                await db.execute(statement)

    async def _ensure_chunk_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(rag_record_chunks)")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        if "content_hash" not in columns:
            await db.execute(
                "ALTER TABLE rag_record_chunks "
                "ADD COLUMN content_hash TEXT NOT NULL DEFAULT ''"
            )

    async def _backfill_content_hashes(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute(
            "SELECT id, content FROM rag_record_chunks WHERE content_hash = ''"
        )
        rows = await cursor.fetchall()
        if rows:
            await db.executemany(
                "UPDATE rag_record_chunks SET content_hash = ? WHERE id = ?",
                [
                    (embedding_content_hash(str(content or "")), int(row_id))
                    for row_id, content in rows
                ],
            )

    async def start_run(self, reason: str) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO rag_index_runs (status, reason, started_at)
                VALUES ('running', ?, ?)
                """,
                (reason, utc_iso()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def finish_run(self, run_id: int, *, layouts_indexed: int, records_indexed: int) -> None:
        await self._execute(
            """
            UPDATE rag_index_runs
            SET status = 'success',
                completed_at = ?,
                layouts_indexed = ?,
                records_indexed = ?,
                error = NULL
            WHERE id = ?
            """,
            (utc_iso(), layouts_indexed, records_indexed, run_id),
        )

    async def update_run_progress(
        self,
        run_id: int,
        *,
        layouts_indexed: int,
        records_indexed: int,
    ) -> None:
        await self._execute(
            """
            UPDATE rag_index_runs
            SET layouts_indexed = ?, records_indexed = ?
            WHERE id = ? AND status = 'running'
            """,
            (layouts_indexed, records_indexed, run_id),
        )

    async def fail_run(self, run_id: int, error: str) -> None:
        await self._execute(
            """
            UPDATE rag_index_runs
            SET status = 'failed',
                completed_at = ?,
                error = ?
            WHERE id = ?
            """,
            (utc_iso(), error, run_id),
        )

    async def status(self, *, enabled: bool, refresh_interval_seconds: int, running: bool) -> dict[str, Any]:
        embedding_model = self.embedding_client.model if self.embedding_client else ""
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            layout_cursor = await db.execute("SELECT COUNT(*) AS count FROM rag_layout_profiles")
            layout_count = int((await layout_cursor.fetchone())["count"])
            record_cursor = await db.execute("SELECT COUNT(*) AS count FROM rag_record_chunks")
            record_count = int((await record_cursor.fetchone())["count"])
            latest_cursor = await db.execute(
                """
                SELECT *
                FROM rag_index_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )
            latest_row = await latest_cursor.fetchone()
            embedding_count = 0
            embedding_pending = 0
            if embedding_model:
                embedding_cursor = await db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM rag_record_embeddings
                    WHERE model = ?
                    """,
                    (embedding_model,),
                )
                embedding_count = int((await embedding_cursor.fetchone())["count"])
                pending_cursor = await db.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM rag_record_chunks c
                    LEFT JOIN rag_record_embeddings e
                      ON e.layout = c.layout
                     AND e.record_id = c.record_id
                     AND e.model = ?
                    WHERE e.record_id IS NULL OR e.content_hash != c.content_hash
                    """,
                    (embedding_model,),
                )
                embedding_pending = int((await pending_cursor.fetchone())["count"])

        return {
            "enabled": enabled,
            "ftsEnabled": self.fts_enabled,
            "databasePath": self.database_path,
            "layoutCount": layout_count,
            "recordCount": record_count,
            "refreshIntervalSeconds": refresh_interval_seconds,
            "latestRun": self._run_to_dict(latest_row) if latest_row else None,
            "running": running,
            "profiledLayouts": layout_count,
            "embeddingEnabled": bool(
                self.embedding_client and self.embedding_client.configured
            ),
            "embeddingModel": embedding_model,
            "embeddingCount": embedding_count,
            "embeddingPending": embedding_pending,
        }

    async def get_layout_profile(self, layout: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM rag_layout_profiles
                WHERE layout = ?
                LIMIT 1
                """,
                (layout,),
            )
            row = await cursor.fetchone()

        if not row:
            return None

        try:
            fields = json.loads(row["fields_json"])
        except (json.JSONDecodeError, TypeError):
            fields = []
        try:
            samples = json.loads(row["sample_json"])
        except (json.JSONDecodeError, TypeError):
            samples = []
        try:
            semantic_profile = json.loads(row["semantic_json"])
        except (json.JSONDecodeError, TypeError):
            semantic_profile = {}

        return {
            "layout": row["layout"],
            "fieldCount": row["field_count"],
            "recordCount": row["record_count"],
            "indexedCount": row["indexed_count"],
            "createdField": row["created_field"],
            "updatedField": row["updated_field"],
            "fieldSource": row["field_source"],
            "fields": fields if isinstance(fields, list) else [],
            "samples": samples if isinstance(samples, list) else [],
            "semanticProfile": semantic_profile if isinstance(semantic_profile, dict) else {},
            "updatedAt": row["updated_at"],
            "runId": row["run_id"],
        }

    async def upsert_layout_profile(
        self,
        *,
        layout: str,
        field_count: int,
        record_count: int,
        indexed_count: int,
        fields: list[dict[str, Any]],
        samples: list[dict[str, Any]],
        date_fields: LayoutDateFields,
        semantic_profile: dict[str, Any] | None = None,
        run_id: int,
    ) -> None:
        await self._execute(
            """
            INSERT INTO rag_layout_profiles (
                layout, field_count, record_count, indexed_count,
                created_field, updated_field, field_source,
                fields_json, sample_json, semantic_json, updated_at, run_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(layout) DO UPDATE SET
                field_count = excluded.field_count,
                record_count = excluded.record_count,
                indexed_count = excluded.indexed_count,
                created_field = excluded.created_field,
                updated_field = excluded.updated_field,
                field_source = excluded.field_source,
                fields_json = excluded.fields_json,
                sample_json = excluded.sample_json,
                semantic_json = excluded.semantic_json,
                updated_at = excluded.updated_at,
                run_id = excluded.run_id
            """,
            (
                layout,
                field_count,
                record_count,
                indexed_count,
                date_fields.created_field,
                date_fields.updated_field,
                date_fields.source,
                json.dumps(fields, ensure_ascii=False),
                json.dumps(samples, ensure_ascii=False),
                json.dumps(semantic_profile or {}, ensure_ascii=False),
                utc_iso(),
                run_id,
            ),
        )

    async def update_layout_semantic_profile(
        self,
        *,
        layout: str,
        semantic_profile: dict[str, Any],
    ) -> None:
        await self._execute(
            """
            UPDATE rag_layout_profiles
            SET semantic_json = ?,
                updated_at = ?
            WHERE layout = ?
            """,
            (json.dumps(semantic_profile, ensure_ascii=False), utc_iso(), layout),
        )

    async def upsert_record_chunk(
        self,
        *,
        layout: str,
        record_id: str,
        mod_id: str,
        title: str,
        content: str,
        fields: dict[str, Any],
        run_id: int,
    ) -> None:
        await self.upsert_record_chunks(
            [
                RagRecordChunk(
                    layout=layout,
                    record_id=record_id,
                    mod_id=mod_id,
                    title=title,
                    content=content,
                    fields=fields,
                    updated_at=utc_iso(),
                )
            ],
            run_id=run_id,
        )

    async def upsert_record_chunks(
        self,
        chunks: list[RagRecordChunk],
        *,
        run_id: int,
    ) -> None:
        if not chunks:
            return
        updated_at = utc_iso()
        async with aiosqlite.connect(self.database_path) as db:
            await db.executemany(
                """
                INSERT INTO rag_record_chunks (
                    layout, record_id, mod_id, title, content,
                    content_hash, field_data_json, updated_at, run_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(layout, record_id) DO UPDATE SET
                    mod_id = excluded.mod_id,
                    title = excluded.title,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    field_data_json = excluded.field_data_json,
                    updated_at = excluded.updated_at,
                    run_id = excluded.run_id
                """,
                [
                    (
                        chunk.layout,
                        chunk.record_id,
                        chunk.mod_id,
                        chunk.title,
                        chunk.content,
                        embedding_content_hash(chunk.content),
                        json.dumps(chunk.fields, ensure_ascii=False),
                        updated_at,
                        run_id,
                    )
                    for chunk in chunks
                ],
            )
            if self.fts_enabled:
                chunk_by_key = {
                    (chunk.layout, chunk.record_id): chunk
                    for chunk in chunks
                }
                row_ids: list[tuple[int, RagRecordChunk]] = []
                layouts = {chunk.layout for chunk in chunks}
                for layout in layouts:
                    record_ids = [
                        chunk.record_id
                        for chunk in chunks
                        if chunk.layout == layout
                    ]
                    placeholders = ",".join("?" for _ in record_ids)
                    cursor = await db.execute(
                        f"""
                        SELECT id, layout, record_id
                        FROM rag_record_chunks
                        WHERE layout = ? AND record_id IN ({placeholders})
                        """,
                        [layout, *record_ids],
                    )
                    for row_id, row_layout, record_id in await cursor.fetchall():
                        chunk = chunk_by_key.get((str(row_layout), str(record_id)))
                        if chunk:
                            row_ids.append((int(row_id), chunk))
                await db.executemany(
                    "DELETE FROM rag_record_fts WHERE rowid = ?",
                    [(row_id,) for row_id, _ in row_ids],
                )
                await db.executemany(
                    """
                    INSERT INTO rag_record_fts(rowid, layout, record_id, title, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (row_id, chunk.layout, chunk.record_id, chunk.title, chunk.content)
                        for row_id, chunk in row_ids
                    ],
                )
            await db.commit()

    async def delete_stale_layout_records(self, *, layout: str, run_id: int) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM rag_record_chunks
                WHERE layout = ? AND run_id != ?
                """,
                (layout, run_id),
            )
            stale_count = int((await cursor.fetchone())[0])
            if self.fts_enabled and stale_count:
                await db.execute(
                    """
                    DELETE FROM rag_record_fts
                    WHERE rowid IN (
                        SELECT id FROM rag_record_chunks
                        WHERE layout = ? AND run_id != ?
                    )
                    """,
                    (layout, run_id),
                )
            if stale_count:
                await db.execute(
                    """
                    DELETE FROM rag_record_embeddings
                    WHERE layout = ?
                      AND record_id IN (
                          SELECT record_id FROM rag_record_chunks
                          WHERE layout = ? AND run_id != ?
                      )
                    """,
                    (layout, layout, run_id),
                )
            await db.execute(
                """
                DELETE FROM rag_record_chunks
                WHERE layout = ? AND run_id != ?
                """,
                (layout, run_id),
            )
            await db.commit()
        return stale_count

    async def prune_layouts(self, allowed_layouts: list[str]) -> dict[str, int]:
        """Remove profiles and chunks that are outside the configured RAG scope."""
        allowed = list(dict.fromkeys(layout for layout in allowed_layouts if layout))
        if not allowed:
            return {"layouts": 0, "records": 0}
        placeholders = ",".join("?" for _ in allowed)
        async with aiosqlite.connect(self.database_path) as db:
            record_cursor = await db.execute(
                f"SELECT COUNT(*) FROM rag_record_chunks WHERE layout NOT IN ({placeholders})",
                allowed,
            )
            record_count = int((await record_cursor.fetchone())[0])
            profile_cursor = await db.execute(
                f"SELECT COUNT(*) FROM rag_layout_profiles WHERE layout NOT IN ({placeholders})",
                allowed,
            )
            profile_count = int((await profile_cursor.fetchone())[0])
            if self.fts_enabled and record_count:
                await db.execute(
                    f"""
                    DELETE FROM rag_record_fts
                    WHERE rowid IN (
                        SELECT id FROM rag_record_chunks
                        WHERE layout NOT IN ({placeholders})
                    )
                    """,
                    allowed,
                )
            if record_count:
                await db.execute(
                    f"DELETE FROM rag_record_embeddings WHERE layout NOT IN ({placeholders})",
                    allowed,
                )
            await db.execute(
                f"DELETE FROM rag_record_chunks WHERE layout NOT IN ({placeholders})",
                allowed,
            )
            await db.execute(
                f"DELETE FROM rag_layout_profiles WHERE layout NOT IN ({placeholders})",
                allowed,
            )
            await db.commit()
        return {"layouts": profile_count, "records": record_count}

    async def find_cached_records(
        self,
        *,
        layout: str,
        query: list[dict[str, Any]],
        limit: int,
        sort: list[dict[str, str]] | None = None,
    ) -> RagRecordResult:
        chunks = await self._layout_chunks(layout)
        if not chunks:
            return RagRecordResult(records=[], found_count=0)

        matched = [
            chunk
            for chunk in chunks
            if _record_matches_any_query(chunk.fields, query)
        ]
        matched = _sort_chunks(matched, sort or [])
        return RagRecordResult(records=matched[:limit], found_count=len(matched))

    async def sync_embeddings(self) -> dict[str, int | str]:
        """Embed only new or content-changed chunks for the configured model."""
        client = self.embedding_client
        if not client or not client.configured:
            return {"embedded": 0, "pending": 0, "model": ""}

        max_records = max(1, self.settings.rag_embedding_max_records_per_run)  # type: ignore[union-attr]
        batch_size = min(
            max_records,
            max(1, self.settings.rag_embedding_batch_size),  # type: ignore[union-attr]
        )
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT c.*
                FROM rag_record_chunks c
                LEFT JOIN rag_record_embeddings e
                  ON e.layout = c.layout
                 AND e.record_id = c.record_id
                 AND e.model = ?
                WHERE e.record_id IS NULL OR e.content_hash != c.content_hash
                ORDER BY c.updated_at ASC
                LIMIT ?
                """,
                (client.model, max_records),
            )
            candidates = await cursor.fetchall()

        embedded = 0
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            vectors = await client.embed_documents(
                [str(row["content"] or "") for row in batch]
            )
            async with aiosqlite.connect(self.database_path) as db:
                await db.executemany(
                    """
                    INSERT INTO rag_record_embeddings (
                        layout, record_id, model, content_hash,
                        dimensions, vector, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(layout, record_id, model) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        dimensions = excluded.dimensions,
                        vector = excluded.vector,
                        updated_at = excluded.updated_at
                    """,
                    [
                        (
                            str(row["layout"]),
                            str(row["record_id"]),
                            client.model,
                            str(row["content_hash"]),
                            len(vector),
                            pack_vector(vector),
                            utc_iso(),
                        )
                        for row, vector in zip(batch, vectors, strict=True)
                    ],
                )
                await db.commit()
            embedded += len(batch)

        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM rag_record_chunks c
                LEFT JOIN rag_record_embeddings e
                  ON e.layout = c.layout
                 AND e.record_id = c.record_id
                 AND e.model = ?
                WHERE e.record_id IS NULL OR e.content_hash != c.content_hash
                """,
                (client.model,),
            )
            pending = int((await cursor.fetchone())[0])
        return {"embedded": embedded, "pending": pending, "model": client.model}

    async def search(self, query: str, *, limit: int, layout: str | None = None) -> list[RagRecordChunk]:
        normalized = query.strip()
        if not normalized:
            return []

        lexical_task = asyncio.create_task(
            self._lexical_search(normalized, limit=max(limit * 2, limit), layout=layout)
        )
        vector_task: asyncio.Task[list[RagRecordChunk]] | None = None
        if (
            self.embedding_client
            and self.embedding_client.configured
            and self.settings
            and self.settings.rag_embedding_query_enabled
        ):
            vector_task = asyncio.create_task(
                self._vector_search(normalized, limit=max(limit * 3, limit), layout=layout)
            )
        lexical_hits = await lexical_task
        vector_hits = await vector_task if vector_task else []
        return _merge_hybrid_hits(lexical_hits, vector_hits, limit=limit)

    async def _lexical_search(
        self,
        query: str,
        *,
        limit: int,
        layout: str | None,
    ) -> list[RagRecordChunk]:
        normalized = query.strip()

        hits: list[RagRecordChunk] = []
        seen: set[tuple[str, str]] = set()
        if self.fts_enabled:
            fts_query = _build_fts_query(normalized)
            if fts_query:
                try:
                    hits.extend(await self._fts_search(fts_query, limit=limit, layout=layout))
                    seen.update((hit.layout, hit.record_id) for hit in hits)
                except aiosqlite.Error:
                    logger.exception("RAG FTS search failed; falling back to LIKE")

        if len(hits) < limit:
            fallback_hits = await self._like_search(
                normalized,
                limit=limit - len(hits),
                layout=layout,
                seen=seen,
            )
            hits.extend(fallback_hits)
        return hits[:limit]

    async def _vector_search(
        self,
        query: str,
        *,
        limit: int,
        layout: str | None,
    ) -> list[RagRecordChunk]:
        client = self.embedding_client
        if not client:
            return []
        try:
            query_vector = await client.embed_query(query)
        except RagEmbeddingError as exc:
            logger.warning("RAG query embedding unavailable; using lexical search: %s", exc)
            return []

        params: list[Any] = [client.model, len(query_vector)]
        layout_filter = ""
        if layout:
            layout_filter = "AND c.layout = ?"
            params.append(layout)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT c.*, e.vector
                FROM rag_record_embeddings e
                JOIN rag_record_chunks c
                  ON c.layout = e.layout AND c.record_id = e.record_id
                WHERE e.model = ? AND e.dimensions = ?
                {layout_filter}
                """,
                params,
            )
            rows = await cursor.fetchall()

        scored = await asyncio.to_thread(_score_vector_rows, query_vector, rows)
        hits: list[RagRecordChunk] = []
        for score, row in scored[:limit]:
            if score < 0.2:
                continue
            hits.append(
                self._chunk_from_row(
                    row,
                    score=score,
                    snippet=str(row["title"] or ""),
                )
            )
        return hits

    async def _layout_chunks(self, layout: str) -> list[RagRecordChunk]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM rag_record_chunks
                WHERE layout = ?
                """,
                (layout,),
            )
            rows = await cursor.fetchall()
        return [self._chunk_from_row(row) for row in rows]

    async def _fts_search(self, fts_query: str, *, limit: int, layout: str | None) -> list[RagRecordChunk]:
        params: list[Any] = [fts_query]
        layout_filter = ""
        if layout:
            layout_filter = "AND c.layout = ?"
            params.append(layout)
        params.append(limit)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT c.*, bm25(rag_record_fts, 0.0, 0.0, 8.0, 1.0) AS rank,
                       snippet(rag_record_fts, 3, '', '', '...', 14) AS snippet
                FROM rag_record_fts
                JOIN rag_record_chunks c ON c.id = rag_record_fts.rowid
                WHERE rag_record_fts MATCH ?
                {layout_filter}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [
            self._chunk_from_row(row, score=-float(row["rank"] or 0), snippet=str(row["snippet"] or ""))
            for row in rows
        ]

    async def _like_search(
        self,
        query: str,
        *,
        limit: int,
        layout: str | None,
        seen: set[tuple[str, str]],
    ) -> list[RagRecordChunk]:
        if limit <= 0:
            return []
        terms = _search_terms(query)
        if not terms:
            terms = [query]
        clauses = []
        params: list[Any] = []
        for term in terms[:6]:
            clauses.append("(title LIKE ? OR content LIKE ?)")
            value = f"%{term}%"
            params.extend([value, value])
        where = " OR ".join(clauses)
        if layout:
            where = f"layout = ? AND ({where})"
            params.insert(0, layout)
        params.append(limit * 3)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT *
                FROM rag_record_chunks
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()

        hits: list[RagRecordChunk] = []
        for row in rows:
            key = (str(row["layout"]), str(row["record_id"]))
            if key in seen:
                continue
            chunk = self._chunk_from_row(row, score=0.1, snippet=_snippet(str(row["content"]), terms))
            hits.append(chunk)
            seen.add(key)
            if len(hits) >= limit:
                break
        return hits

    async def _execute(self, query: str, params: tuple[Any, ...]) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(query, params)
            await db.commit()

    def _run_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "status": row["status"],
            "reason": row["reason"],
            "startedAt": row["started_at"],
            "completedAt": row["completed_at"],
            "error": row["error"],
            "layoutsIndexed": row["layouts_indexed"],
            "recordsIndexed": row["records_indexed"],
        }

    def _chunk_from_row(self, row: aiosqlite.Row, *, score: float = 0, snippet: str = "") -> RagRecordChunk:
        try:
            fields = json.loads(row["field_data_json"])
        except (TypeError, json.JSONDecodeError):
            fields = {}
        return RagRecordChunk(
            layout=str(row["layout"]),
            record_id=str(row["record_id"]),
            mod_id=str(row["mod_id"] or ""),
            title=str(row["title"] or ""),
            content=str(row["content"] or ""),
            fields=fields if isinstance(fields, dict) else {},
            updated_at=str(row["updated_at"]),
            score=score,
            snippet=snippet or str(row["title"] or ""),
        )


class RagIndexWorker:
    def __init__(
        self,
        *,
        store: RagIndexStore,
        filemaker_client: FileMakerClient,
        settings: Settings,
    ):
        self.store = store
        self.filemaker_client = filemaker_client
        self.settings = settings
        self.semantic_registry = RagSemanticRegistry.from_mapping_path(
            settings.semantic_mapping_path
        )
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._refresh_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()

    @property
    def running(self) -> bool:
        return self._refresh_lock.locked()

    def start(self) -> None:
        if not self.settings.rag_index_enabled:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="rag-index-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        self._refresh_event.set()
        if self._task:
            await self._task

    def request_refresh(self) -> bool:
        if not self.settings.rag_index_enabled:
            return False
        self._refresh_event.set()
        return True

    async def refresh_now(self, reason: str = "manual") -> None:
        async with self._refresh_lock:
            run_id = await self.store.start_run(reason)
            layouts_indexed = 0
            records_indexed = 0
            try:
                layouts = await self._target_layouts()
                for layout in layouts:
                    if self._stop_event.is_set():
                        break
                    indexed = await self._index_layout(layout, run_id)
                    layouts_indexed += 1
                    records_indexed += indexed
                    await self.store.update_run_progress(
                        run_id,
                        layouts_indexed=layouts_indexed,
                        records_indexed=records_indexed,
                    )
                if not self._stop_event.is_set() and layouts_indexed == len(layouts):
                    pruned = await self.store.prune_layouts(layouts)
                    if pruned["layouts"] or pruned["records"]:
                        logger.info(
                            "Pruned RAG data outside configured layout scope; layouts=%s records=%s",
                            pruned["layouts"],
                            pruned["records"],
                        )
                await self.store.finish_run(
                    run_id,
                    layouts_indexed=layouts_indexed,
                    records_indexed=records_indexed,
                )
                try:
                    embedding_result = await self.store.sync_embeddings()
                    if embedding_result["model"]:
                        logger.info(
                            "RAG embedding sync complete; model=%s embedded=%s pending=%s",
                            embedding_result["model"],
                            embedding_result["embedded"],
                            embedding_result["pending"],
                        )
                except RagEmbeddingError:
                    logger.exception(
                        "RAG index refresh succeeded but incremental embedding sync failed"
                    )
                logger.info(
                    "RAG index refresh complete; layouts=%s records=%s",
                    layouts_indexed,
                    records_indexed,
                )
            except Exception as exc:
                await self.store.fail_run(run_id, str(exc))
                logger.exception("RAG index refresh failed")

    async def _run(self) -> None:
        logger.info("RAG index worker started")
        if self.settings.rag_index_refresh_on_startup:
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(0, self.settings.rag_index_startup_delay_seconds),
                )
            except asyncio.TimeoutError:
                await self.refresh_now("startup")

        while not self._stop_event.is_set():
            try:
                wait_task = asyncio.create_task(self._stop_event.wait())
                refresh_task = asyncio.create_task(self._refresh_event.wait())
                done, pending = await asyncio.wait(
                    {wait_task, refresh_task},
                    timeout=_refresh_wait_seconds(self.settings),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if wait_task in done and self._stop_event.is_set():
                    break
                reason = "manual" if refresh_task in done and self._refresh_event.is_set() else "scheduled"
                self._refresh_event.clear()
                await self.refresh_now(reason)
            except Exception:
                logger.exception("RAG index worker loop failed")
                await asyncio.sleep(30)

        logger.info("RAG index worker stopped")

    async def _target_layouts(self) -> list[str]:
        layouts = await self.filemaker_client.list_layouts()
        prefix = self.settings.rag_index_layout_prefix.strip()
        includes = _csv_set(self.settings.rag_index_layout_include)
        excludes = _csv_set(self.settings.rag_index_layout_exclude)
        if prefix:
            layouts = [layout for layout in layouts if layout.startswith(prefix)]
        if includes:
            layouts = [layout for layout in layouts if layout in includes]
        if excludes:
            layouts = [layout for layout in layouts if layout not in excludes]
        layouts = list(dict.fromkeys(layouts))
        priority_layouts = [
            layout
            for entity in self.semantic_registry.entities
            for layout in entity.layouts
        ]
        priority = {layout: index for index, layout in enumerate(priority_layouts)}
        original_order = {layout: index for index, layout in enumerate(layouts)}
        layouts.sort(
            key=lambda layout: (
                0 if layout in priority else 1,
                priority.get(layout, original_order[layout]),
            )
        )
        max_layouts = self.settings.rag_index_max_layouts
        if max_layouts > 0:
            layouts = layouts[:max_layouts]
        return layouts

    async def _index_layout(self, layout: str, run_id: int) -> int:
        logger.info("Indexing FileMaker layout for RAG: %s", layout)
        entity = self.semantic_registry.entity_for_layout(layout)
        source_fields = await self._safe_layout_fields(layout)
        allowed_profile_fields = _allowed_index_fields(source_fields, entity=entity)
        allowed_record_fields = (
            set(entity.record_cache_fields)
            if entity and entity.cache_fields
            else allowed_profile_fields
        )
        excluded_fields = set(entity.exclude_fields) if entity else set()
        fields = _filter_profile_fields(
            source_fields,
            allowed_fields=allowed_profile_fields,
            excluded_fields=excluded_fields,
        )
        date_fields = _detect_layout_date_fields(fields)
        semantic_profile = fallback_layout_semantic_profile(layout=layout, fields=fields)
        page_size = min(500, max(1, self.settings.rag_index_page_size))
        max_records = (
            entity.max_records
            if entity and entity.max_records is not None
            else self.settings.rag_index_max_records_per_layout
        )
        max_semantic_samples = max(0, self.settings.rag_index_semantic_sample_records)
        offset = 1
        indexed = 0
        found_count = 0
        samples: list[dict[str, Any]] = []
        semantic_samples: list[dict[str, Any]] = []
        observed_field_names: list[str] = []
        observed_field_seen: set[str] = set()
        fetch_failed = False

        while not self._stop_event.is_set():
            limit = page_size
            if max_records > 0:
                remaining = max_records - indexed
                if remaining <= 0:
                    break
                limit = min(limit, remaining)

            try:
                result = await self._find_records_with_retry(
                    layout,
                    limit=limit,
                    offset=offset,
                )
            except FileMakerAPIError as exc:
                logger.warning("Skipping RAG layout %s after FileMaker error: %s", layout, exc)
                fetch_failed = True
                break

            rows = result.get("data") or []
            found_count = int(result.get("foundCount") or found_count or len(rows))
            if not rows:
                break

            page_chunks: list[RagRecordChunk] = []
            for record in rows:
                if len(semantic_samples) < max_semantic_samples:
                    sample_fields = record.get("fieldData") or {}
                    if isinstance(sample_fields, dict):
                        semantic_samples.append(
                            _clean_fields(
                                sample_fields,
                                max_fields=self.settings.rag_index_max_fields_per_record,
                                value_max_length=min(80, self.settings.rag_index_value_max_length),
                                priority_fields=entity.index_fields if entity else [],
                                allowed_fields=allowed_profile_fields,
                                excluded_fields=excluded_fields,
                            )
                        )
                chunk = _record_to_chunk(
                    layout=layout,
                    record=record,
                    max_fields=self.settings.rag_index_max_fields_per_record,
                    value_max_length=self.settings.rag_index_value_max_length,
                    priority_fields=[
                        *(entity.index_fields if entity else []),
                        date_fields.created_field,
                        date_fields.updated_field,
                        *_STOCK_FIELD_PRIORITY,
                        *semantic_priority_fields(semantic_profile),
                    ],
                    allowed_fields=allowed_record_fields,
                    excluded_fields=excluded_fields,
                )
                if not chunk:
                    continue
                if not date_fields.created_field or not date_fields.updated_field:
                    date_fields = _merge_date_fields(
                        date_fields,
                        _detect_layout_date_fields([{"name": name} for name in chunk.fields]),
                    )
                page_chunks.append(chunk)
                for field_name in chunk.fields:
                    if field_name not in observed_field_seen:
                        observed_field_seen.add(field_name)
                        observed_field_names.append(field_name)
                if len(samples) < 3:
                    samples.append({"recordId": chunk.record_id, "title": chunk.title})

            await self.store.upsert_record_chunks(page_chunks, run_id=run_id)
            indexed += len(page_chunks)

            if len(rows) < limit:
                break
            offset += len(rows)

        if fetch_failed:
            logger.warning(
                "Retaining the previous RAG profile and stale records after an incomplete scan: %s",
                layout,
            )
            return indexed
        await self.store.delete_stale_layout_records(layout=layout, run_id=run_id)
        profile_fields = fields or [{"name": field_name} for field_name in observed_field_names]
        semantic_profile = await self._semantic_profile_for_layout(
            layout,
            profile_fields,
            sample_records=semantic_samples,
        )
        semantic_profile.update(self.semantic_registry.context_for_layout(layout))
        await self.store.upsert_layout_profile(
            layout=layout,
            field_count=len(profile_fields),
            record_count=found_count,
            indexed_count=indexed,
            fields=profile_fields,
            samples=samples,
            date_fields=date_fields,
            semantic_profile=semantic_profile,
            run_id=run_id,
        )
        return indexed

    async def _find_records_with_retry(
        self,
        layout: str,
        *,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        last_error: FileMakerAPIError | None = None
        for attempt in range(3):
            try:
                return await self.filemaker_client.find_records(
                    layout,
                    limit=limit,
                    offset=offset,
                )
            except FileMakerAPIError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(attempt + 1)
        assert last_error is not None
        raise last_error

    async def _semantic_profile_for_layout(
        self,
        layout: str,
        fields: list[dict[str, Any]],
        *,
        sample_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not fields:
            return fallback_layout_semantic_profile(
                layout=layout,
                fields=fields,
                sample_records=sample_records or [],
            )
        try:
            return await build_layout_semantic_profile(
                layout=layout,
                fields=fields,
                sample_records=sample_records or [],
                settings=self.settings,
            )
        except Exception:
            logger.exception("Unable to build semantic profile for RAG layout %s", layout)
            return fallback_layout_semantic_profile(
                layout=layout,
                fields=fields,
                sample_records=sample_records or [],
            )

    async def _safe_layout_fields(self, layout: str) -> list[dict[str, Any]]:
        if not self.settings.rag_index_read_layout_fields:
            return []
        try:
            fields = await asyncio.wait_for(
                self.filemaker_client.get_layout_fields(layout),
                timeout=max(1.0, self.settings.rag_index_layout_fields_timeout_seconds),
            )
        except asyncio.TimeoutError:
            logger.info("Timed out reading fields for RAG layout %s; continuing with record samples", layout)
            return []
        except FileMakerAPIError:
            logger.info("Unable to read fields for RAG layout %s; continuing with records only", layout)
            return []
        return [field for field in fields if isinstance(field, dict)]


def _score_vector_rows(
    query_vector: list[float],
    rows: list[aiosqlite.Row],
) -> list[tuple[float, aiosqlite.Row]]:
    scored = [
        (cosine_from_normalized(query_vector, bytes(row["vector"])), row)
        for row in rows
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored


def _merge_hybrid_hits(
    lexical_hits: list[RagRecordChunk],
    vector_hits: list[RagRecordChunk],
    *,
    limit: int,
) -> list[RagRecordChunk]:
    if not vector_hits:
        return lexical_hits[:limit]
    if not lexical_hits:
        return vector_hits[:limit]

    hits: dict[tuple[str, str], RagRecordChunk] = {}
    scores: dict[tuple[str, str], float] = {}
    for rank, hit in enumerate(lexical_hits):
        key = (hit.layout, hit.record_id)
        hits[key] = hit
        scores[key] = scores.get(key, 0.0) + 2.0 / (60 + rank)
    for rank, hit in enumerate(vector_hits):
        key = (hit.layout, hit.record_id)
        hits.setdefault(key, hit)
        scores[key] = (
            scores.get(key, 0.0)
            + 1.0 / (60 + rank)
            + max(0.0, hit.score) / 100.0
        )
    ordered = sorted(hits, key=lambda key: scores[key], reverse=True)
    result: list[RagRecordChunk] = []
    for key in ordered[:limit]:
        hit = hits[key]
        hit.score = scores[key]
        result.append(hit)
    return result


def _record_to_chunk(
    *,
    layout: str,
    record: dict[str, Any],
    max_fields: int,
    value_max_length: int,
    priority_fields: list[str] | None = None,
    allowed_fields: set[str] | None = None,
    excluded_fields: set[str] | None = None,
) -> RagRecordChunk | None:
    fields = record.get("fieldData") or {}
    if not isinstance(fields, dict):
        return None
    cleaned = _clean_fields(
        fields,
        max_fields=max_fields,
        value_max_length=value_max_length,
        priority_fields=priority_fields or [],
        allowed_fields=allowed_fields,
        excluded_fields=excluded_fields or set(),
    )
    if not cleaned:
        return None
    record_id = str(record.get("recordId") or "")
    if not record_id:
        return None
    title = _record_title(cleaned, fallback=record_id)
    lines = [f"布局: {layout}", f"记录ID: {record_id}", f"标题: {title}"]
    lines.extend(f"{key}: {value}" for key, value in cleaned.items())
    return RagRecordChunk(
        layout=layout,
        record_id=record_id,
        mod_id=str(record.get("modId") or ""),
        title=title,
        content="\n".join(lines),
        fields=cleaned,
        updated_at=utc_iso(),
    )


def _clean_fields(
    fields: dict[str, Any],
    *,
    max_fields: int,
    value_max_length: int,
    priority_fields: list[str],
    allowed_fields: set[str] | None = None,
    excluded_fields: set[str] | None = None,
) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    excluded_fields = excluded_fields or set()
    ordered_keys = [key for key in priority_fields if key and key in fields]
    ordered_keys.extend(key for key in fields if key not in ordered_keys)
    for key in ordered_keys:
        if len(cleaned) >= max_fields:
            break
        key_name = str(key)
        if allowed_fields is not None and key_name not in allowed_fields:
            continue
        if key_name in excluded_fields or _is_noisy_field(key_name, fields.get(key)):
            continue
        value = fields.get(key)
        if value in (None, "", []):
            continue
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        cleaned[key_name] = text[:value_max_length]
    return cleaned


def _record_title(fields: dict[str, Any], *, fallback: str) -> str:
    preferred_fields = [
        "product_sku",
        "系統產品編號",
        "產品名稱_中文",
        "product_name",
        "part_number",
        "零件ID",
        "part_name_en",
        "part_name",
        "English Name",
        "ID_產品編號",
        "零件編號",
        "零件名稱",
        "ID_零件",
        "ID_产品",
        "ID_關聯零件",
        "ID",
        "訂單編號",
        "订单号",
        "名稱",
        "name",
    ]
    values = [str(fields[field]) for field in preferred_fields if fields.get(field)]
    if values:
        return " / ".join(values[:3])
    return next(iter(fields.values()), fallback)


def _record_matches_any_query(fields: dict[str, Any], query: list[dict[str, Any]]) -> bool:
    if not query:
        return True
    return any(_record_matches_criteria(fields, criteria) for criteria in query if criteria)


def _record_matches_criteria(fields: dict[str, Any], criteria: dict[str, Any]) -> bool:
    for field, pattern in criteria.items():
        if not _value_matches(fields.get(field), str(pattern)):
            return False
    return True


def _value_matches(value: Any, pattern: str) -> bool:
    text = "" if value is None else str(value)
    if pattern == "*":
        return bool(text)
    if pattern.startswith("=="):
        return text == pattern[2:]
    if "..." in pattern:
        start, _, end = pattern.partition("...")
        return _range_matches(text, start, end)
    if pattern.startswith("*") and pattern.endswith("*") and len(pattern) >= 2:
        return pattern.strip("*").casefold() in text.casefold()
    return pattern.casefold() in text.casefold()


def _range_matches(value: str, start: str, end: str) -> bool:
    normalized_value = _sortable_value(value)
    normalized_start = _sortable_value(start)
    normalized_end = _sortable_value(end)
    return normalized_start <= normalized_value <= normalized_end


def _sortable_value(value: str) -> str:
    value = value.strip()
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?", value)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return (
            f"{int(year):04d}-{int(month):02d}-{int(day):02d} "
            f"{int(hour or 0):02d}:{int(minute or 0):02d}:{int(second or 0):02d}"
        )
    match = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?", value)
    if not match:
        return value
    month, day, year, hour, minute, second = match.groups()
    return (
        f"{int(year):04d}-{int(month):02d}-{int(day):02d} "
        f"{int(hour or 0):02d}:{int(minute or 0):02d}:{int(second or 0):02d}"
    )


def _detect_layout_date_fields(fields: list[dict[str, Any]]) -> LayoutDateFields:
    names = [str(field.get("name") or "") for field in fields if isinstance(field, dict) and field.get("name")]
    created = _best_date_field(names, _CREATED_FIELD_SCORES)
    updated = _best_date_field(names, _UPDATED_FIELD_SCORES)
    source = "metadata" if fields and (created or updated) else ("sample" if created or updated else "")
    return LayoutDateFields(created_field=created, updated_field=updated, source=source)


def _merge_date_fields(current: LayoutDateFields, fallback: LayoutDateFields) -> LayoutDateFields:
    return LayoutDateFields(
        created_field=current.created_field or fallback.created_field,
        updated_field=current.updated_field or fallback.updated_field,
        source=current.source or fallback.source,
    )


_CREATED_FIELD_SCORES = [
    (100, ("date created", "createdat", "created_at", "creation date")),
    (95, ("创建日期", "創建日期", "建立日期", "建檔日期", "建档日期", "新增日期")),
    (80, ("创建时间", "創建時間", "建立時間", "新增時間", "新增时间")),
    (60, ("created", "creation", "建檔", "建档", "新增", "建立")),
]

_UPDATED_FIELD_SCORES = [
    (100, ("updatedat", "updated_at", "modified at", "last modified")),
    (95, ("修改日期", "更新日期", "修改時間", "修改时间", "更新時間", "更新时间")),
    (80, ("零件修改時間", "零件修改时间")),
    (60, ("modified", "updated", "修改", "更新")),
]


def _best_date_field(names: list[str], score_groups: list[tuple[int, tuple[str, ...]]]) -> str:
    best_name = ""
    best_score = 0
    for index, name in enumerate(names):
        normalized = _normalize_field_name(name)
        score = 0
        for group_score, terms in score_groups:
            if any(term in normalized for term in terms):
                score = max(score, group_score)
        if "::" in name and score:
            score -= 8
        score -= min(index, 50)
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def _normalize_field_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _sort_chunks(chunks: list[RagRecordChunk], sort: list[dict[str, str]]) -> list[RagRecordChunk]:
    if not sort:
        return chunks
    first = sort[0]
    field = first.get("fieldName") or ""
    reverse = first.get("sortOrder") == "descend"
    if not field:
        return chunks
    return sorted(chunks, key=lambda chunk: _sortable_value(str(chunk.fields.get(field) or "")), reverse=reverse)


def _search_terms(value: str) -> list[str]:
    raw_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]{2,}", value)
    terms: list[str] = []
    cjk_stop_terms = {"查询", "查找", "寻找", "资料", "信息", "产品", "產品", "零件"}
    for term in raw_terms:
        if not re.fullmatch(r"[\u4e00-\u9fff]+", term):
            terms.append(term)
            continue
        if len(term) <= 4:
            terms.append(term)
            continue
        terms.append(term)
        terms.extend(
            token
            for token in (term[index : index + 2] for index in range(len(term) - 1))
            if token not in cjk_stop_terms
        )
    return list(dict.fromkeys(terms))


def _build_fts_query(value: str) -> str:
    terms = _search_terms(value)
    quoted = [
        f'"{term.replace(chr(34), chr(34) + chr(34))}"'
        + ("*" if re.fullmatch(r"[\u4e00-\u9fff]+", term) else "")
        for term in terms[:8]
    ]
    return " OR ".join(quoted)


def _snippet(content: str, terms: list[str]) -> str:
    for term in terms:
        index = content.casefold().find(term.casefold())
        if index >= 0:
            start = max(0, index - 28)
            end = min(len(content), index + len(term) + 48)
            return content[start:end].replace("\n", " ")
    return content[:100].replace("\n", " ")


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _allowed_index_fields(
    fields: list[dict[str, Any]],
    *,
    entity: RagEntity | None,
) -> set[str] | None:
    if entity:
        return set(entity.index_fields)
    if not fields:
        return None
    return {
        str(field.get("name") or "")
        for field in fields
        if isinstance(field, dict)
        and field.get("name")
        and not _is_container_metadata(field)
        and not _is_noisy_field(str(field.get("name") or ""), None)
    }


def _filter_profile_fields(
    fields: list[dict[str, Any]],
    *,
    allowed_fields: set[str] | None,
    excluded_fields: set[str],
) -> list[dict[str, Any]]:
    return [
        field
        for field in fields
        if isinstance(field, dict)
        and field.get("name")
        and (allowed_fields is None or str(field.get("name")) in allowed_fields)
        and str(field.get("name")) not in excluded_fields
        and not _is_container_metadata(field)
        and not _is_noisy_field(str(field.get("name")), None)
    ]


def _is_container_metadata(field: dict[str, Any]) -> bool:
    metadata = " ".join(
        str(field.get(key) or "").casefold()
        for key in ("result", "type", "fieldType", "displayType")
    )
    return "container" in metadata or "容器" in metadata


def _is_noisy_field(field_name: str, value: Any) -> bool:
    normalized = field_name.strip().casefold()
    if any(
        term in normalized
        for term in ("暫存區", "暂存区", "qrcode", "qr_code", "sync_response")
    ):
        return True
    if "容器" in normalized or "container" in normalized:
        return True
    if isinstance(value, str):
        normalized_value = value.strip().casefold()
        if normalized_value.startswith("http") and "streaming/maindb" in normalized_value:
            return True
    return False

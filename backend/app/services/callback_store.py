import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


@dataclass
class CallbackEvent:
    id: int
    source: str
    event_id: str
    status: str
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    last_error: str | None
    filemaker_result: Any
    created_at: str
    updated_at: str
    next_attempt_at: str | None


class CallbackStore:
    def __init__(self, database_path: str):
        self.database_path = database_path

    async def init(self) -> None:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS callback_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 8,
                    last_error TEXT,
                    filemaker_result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_attempt_at TEXT,
                    UNIQUE(source, event_id)
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_callback_status_next_attempt
                ON callback_events(status, next_attempt_at)
                """
            )
            await db.commit()

    async def create_event(
        self,
        *,
        source: str,
        event_id: str,
        payload: dict[str, Any],
        max_attempts: int,
    ) -> tuple[CallbackEvent, bool]:
        now = utc_iso()
        try:
            async with aiosqlite.connect(self.database_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO callback_events (
                        source, event_id, status, payload_json, max_attempts,
                        created_at, updated_at, next_attempt_at
                    )
                    VALUES (?, ?, 'received', ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        event_id,
                        json.dumps(payload, ensure_ascii=False),
                        max_attempts,
                        now,
                        now,
                        now,
                    ),
                )
                await db.commit()
                created_id = cursor.lastrowid
            event = await self.get_event(created_id)
            if event is None:
                raise RuntimeError("Callback event was not created")
            return event, False
        except aiosqlite.IntegrityError:
            event = await self.get_event_by_source_event_id(source, event_id)
            if event is None:
                raise
            return event, True

    async def claim_due_event(self) -> CallbackEvent | None:
        now = utc_iso()
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT *
                FROM callback_events
                WHERE status IN ('received', 'retrying')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None

            await db.execute(
                """
                UPDATE callback_events
                SET status = 'processing',
                    attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, row["id"]),
            )
            await db.commit()

        return await self.get_event(row["id"])

    async def mark_success(self, event_id: int, result: Any) -> None:
        now = utc_iso()
        await self._execute(
            """
            UPDATE callback_events
            SET status = 'success',
                filemaker_result_json = ?,
                last_error = NULL,
                updated_at = ?,
                next_attempt_at = NULL
            WHERE id = ?
            """,
            (json.dumps(result, ensure_ascii=False), now, event_id),
        )

    async def mark_failure(self, event: CallbackEvent, error: str) -> None:
        now = utc_now()
        if event.attempt_count >= event.max_attempts:
            status = "dead"
            next_attempt_at = None
        else:
            status = "retrying"
            delay_seconds = min(3600, 60 * (2 ** max(event.attempt_count - 1, 0)))
            next_attempt_at = utc_iso(now + timedelta(seconds=delay_seconds))

        await self._execute(
            """
            UPDATE callback_events
            SET status = ?,
                last_error = ?,
                updated_at = ?,
                next_attempt_at = ?
            WHERE id = ?
            """,
            (status, error, utc_iso(now), next_attempt_at, event.id),
        )

    async def list_events(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[CallbackEvent]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT *
                FROM callback_events
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [self._row_to_event(row) for row in rows]

    async def get_event(self, id_: int) -> CallbackEvent | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM callback_events WHERE id = ?",
                (id_,),
            )
            row = await cursor.fetchone()
        return self._row_to_event(row) if row else None

    async def get_event_by_source_event_id(
        self,
        source: str,
        event_id: str,
    ) -> CallbackEvent | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM callback_events
                WHERE source = ? AND event_id = ?
                """,
                (source, event_id),
            )
            row = await cursor.fetchone()
        return self._row_to_event(row) if row else None

    async def _execute(self, query: str, params: tuple[Any, ...]) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(query, params)
            await db.commit()

    def _row_to_event(self, row: aiosqlite.Row) -> CallbackEvent:
        result_json = row["filemaker_result_json"]
        result = None
        if result_json:
            try:
                result = json.loads(result_json)
            except json.JSONDecodeError:
                result = result_json

        return CallbackEvent(
            id=row["id"],
            source=row["source"],
            event_id=row["event_id"],
            status=row["status"],
            payload=json.loads(row["payload_json"]),
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
            last_error=row["last_error"],
            filemaker_result=result,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            next_attempt_at=row["next_attempt_at"],
        )

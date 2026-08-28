from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.core.config import Settings
from app.models.part_creation import PartCreationDefaults, PartCreationOptionsResponse
from app.services.filemaker_client import FileMakerClient
from app.services.part_creation import DEFAULTS, load_part_creation_options

logger = logging.getLogger(__name__)

CACHE_KEY = "part-creation-options"
CACHE_SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return value.isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class _CacheEntry:
    response: PartCreationOptionsResponse
    refreshed_at: datetime


class PartCreationOptionsCache:
    """Persistent, shared cache for FileMaker reference data used by WebViewer."""

    def __init__(
        self,
        *,
        database_path: str,
        filemaker: FileMakerClient,
        settings: Settings,
    ):
        self.database_path = database_path
        self.filemaker = filemaker
        self.settings = settings
        self._entry: _CacheEntry | None = None
        self._refresh_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._refreshing = False
        self._last_attempt_at: datetime | None = None
        self._last_error = ""
        self._last_refresh_reason = ""

    @property
    def source_signature(self) -> str:
        return "|".join(
            (
                self.settings.filemaker_database,
                self.settings.filemaker_part_read_layout,
                self.settings.filemaker_part_write_layout,
            )
        )

    async def init(self) -> None:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS filemaker_reference_cache (
                    cache_key TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    source_signature TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    refreshed_at TEXT NOT NULL
                )
                """
            )
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT payload_json, refreshed_at
                FROM filemaker_reference_cache
                WHERE cache_key = ?
                  AND schema_version = ?
                  AND source_signature = ?
                """,
                (CACHE_KEY, CACHE_SCHEMA_VERSION, self.source_signature),
            )
            row = await cursor.fetchone()
            await db.commit()

        if row is None:
            return
        try:
            response = PartCreationOptionsResponse.model_validate_json(
                str(row["payload_json"])
            )
            refreshed_at = _parse_timestamp(str(row["refreshed_at"]))
        except (ValueError, TypeError):
            logger.exception("Ignoring invalid persisted part creation options cache")
            return
        self._entry = _CacheEntry(response=response, refreshed_at=refreshed_at)

    async def ensure_seeded(self) -> None:
        if self._entry is not None:
            return
        try:
            await self.refresh(reason="startup")
        except Exception:
            logger.exception("Unable to seed part creation options cache at startup")

    def start(self) -> None:
        if (
            self.settings.filemaker_part_options_cache_refresh_interval_seconds <= 0
            or self._worker_task is not None
        ):
            return
        self._stop_event.clear()
        self._worker_task = asyncio.create_task(
            self._run(),
            name="part-creation-options-cache",
        )

    async def stop(self) -> None:
        task = self._worker_task
        if task is None:
            return
        self._stop_event.set()
        await asyncio.gather(task, return_exceptions=True)
        self._worker_task = None

    async def get(self) -> PartCreationOptionsResponse:
        if self._entry is None:
            await self.refresh(reason="cache-miss")
        if self._entry is None:
            raise RuntimeError("Part creation options cache is unavailable")
        return self._response_for_current_settings(self._entry.response)

    async def refresh(self, *, reason: str) -> PartCreationOptionsResponse:
        requested_at = _utc_now()
        async with self._refresh_lock:
            if (
                self._entry is not None
                and self._entry.refreshed_at >= requested_at
            ):
                return self._response_for_current_settings(self._entry.response)

            self._refreshing = True
            self._last_attempt_at = _utc_now()
            try:
                response = await load_part_creation_options(
                    self.filemaker,
                    self.settings,
                    material_cache_ttl_seconds=0,
                )
                refreshed_at = _utc_now()
                await self._persist(response, refreshed_at)
                self._entry = _CacheEntry(
                    response=response.model_copy(deep=True),
                    refreshed_at=refreshed_at,
                )
                self._last_error = ""
                self._last_refresh_reason = reason
                logger.info(
                    "Part creation options cache refreshed reason=%s items=%s",
                    reason,
                    sum(self._option_counts(response).values()),
                )
                return self._response_for_current_settings(response)
            except Exception as exc:
                self._last_error = str(exc)
                raise
            finally:
                self._refreshing = False

    async def refresh_if_due(self) -> bool:
        interval = (
            self.settings.filemaker_part_options_cache_refresh_interval_seconds
        )
        if interval <= 0:
            return False
        if self._entry is not None:
            age = (_utc_now() - self._entry.refreshed_at).total_seconds()
            if age < interval:
                return False
        await self.refresh(reason="scheduled")
        return True

    def status(self) -> dict[str, Any]:
        now = _utc_now()
        refreshed_at = self._entry.refreshed_at if self._entry else None
        interval = (
            self.settings.filemaker_part_options_cache_refresh_interval_seconds
        )
        next_refresh_at = (
            refreshed_at + timedelta(seconds=interval)
            if refreshed_at is not None and interval > 0
            else None
        )
        return {
            "available": self._entry is not None,
            "source": "persistent-web-cache",
            "refreshedAt": _utc_iso(refreshed_at) if refreshed_at else None,
            "ageSeconds": (
                max(0, int((now - refreshed_at).total_seconds()))
                if refreshed_at
                else None
            ),
            "refreshIntervalSeconds": interval,
            "nextRefreshAt": (
                _utc_iso(next_refresh_at) if next_refresh_at else None
            ),
            "refreshing": self._refreshing,
            "lastAttemptAt": (
                _utc_iso(self._last_attempt_at) if self._last_attempt_at else None
            ),
            "lastError": self._last_error or None,
            "lastRefreshReason": self._last_refresh_reason or None,
            "counts": (
                self._option_counts(self._entry.response)
                if self._entry is not None
                else {}
            ),
        }

    async def _persist(
        self,
        response: PartCreationOptionsResponse,
        refreshed_at: datetime,
    ) -> None:
        payload_json = json.dumps(
            response.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO filemaker_reference_cache (
                    cache_key,
                    schema_version,
                    source_signature,
                    payload_json,
                    refreshed_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    schema_version = excluded.schema_version,
                    source_signature = excluded.source_signature,
                    payload_json = excluded.payload_json,
                    refreshed_at = excluded.refreshed_at
                """,
                (
                    CACHE_KEY,
                    CACHE_SCHEMA_VERSION,
                    self.source_signature,
                    payload_json,
                    _utc_iso(refreshed_at),
                ),
            )
            await db.commit()

    async def _run(self) -> None:
        retry_seconds = (
            self.settings.filemaker_part_options_cache_retry_seconds
        )
        while not self._stop_event.is_set():
            delay = self._seconds_until_due()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                continue
            except TimeoutError:
                pass
            try:
                await self.refresh_if_due()
            except Exception:
                logger.exception("Scheduled part creation options refresh failed")
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=retry_seconds,
                    )
                except TimeoutError:
                    pass

    def _seconds_until_due(self) -> float:
        interval = (
            self.settings.filemaker_part_options_cache_refresh_interval_seconds
        )
        if self._entry is None:
            return 0.1
        age = (_utc_now() - self._entry.refreshed_at).total_seconds()
        return max(0.1, interval - age)

    def _response_for_current_settings(
        self,
        response: PartCreationOptionsResponse,
    ) -> PartCreationOptionsResponse:
        return response.model_copy(
            deep=True,
            update={
                "asset_uploads_enabled": (
                    self.settings.filemaker_part_assets_enabled
                    and self.settings.cos_configured
                ),
                "defaults": PartCreationDefaults(**DEFAULTS),
            },
        )

    @staticmethod
    def _option_counts(
        response: PartCreationOptionsResponse,
    ) -> dict[str, int]:
        return {
            "warehouseDivisions": len(response.warehouse_divisions),
            "materialCategories": len(response.material_categories),
            "machiningCategories": len(response.machining_categories),
            "departmentDivisions": len(response.department_divisions),
            "statisticsCategories": len(response.statistics_categories),
            "useDepartments": len(response.use_departments),
            "lifecycleStatuses": len(response.lifecycle_statuses),
            "partCategories": len(response.part_categories),
            "materialProperties": len(response.material_properties),
            "warehouseCodes": len(response.warehouse_codes),
            "materialSizes": len(response.material_sizes),
            "exclusiveCustomers": len(response.exclusive_customers),
            "generatorMaterials": len(response.generator.materials),
            "generatorCustomers": len(response.generator.customers),
            "generatorManufactures": len(response.generator.manufactures),
            "generatorColors": len(response.generator.colors),
            "generatorOthers": len(response.generator.others),
        }

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.core.config import Settings


SUPPORTED_LLM_PROVIDERS = ("deepseek", "lm_studio")
PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "lm_studio": "LM Studio",
}


class LlmProviderConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class LlmProviderProfile:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float
    max_output_tokens: int
    ssl_verify: bool

    @property
    def configured(self) -> bool:
        return bool(self.model.strip() and self.base_url.strip() and self.api_key.strip())


class LlmProviderManager:
    """Keeps provider secrets in environment-backed settings and switches atomically.

    Only the selected provider id is persisted. API keys and endpoints remain in
    environment configuration and are never written to SQLite or returned by the API.
    """

    def __init__(self, *, settings: Settings, database_path: str):
        self.settings = settings
        self.database_path = database_path
        self._lock = asyncio.Lock()
        self._initial_provider = self._normalize_provider(settings.llm_provider)
        self._profiles = {
            provider: self._profile_from_settings(provider)
            for provider in SUPPORTED_LLM_PROVIDERS
        }
        self._active_provider = self._initial_provider
        self._updated_at: str | None = None
        self._updated_by = "environment"

    async def init(self) -> None:
        selected = self._initial_provider
        if not self._memory_only:
            db_path = Path(self.database_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.database_path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS llm_runtime_config (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        active_provider TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        updated_by TEXT NOT NULL
                    )
                    """
                )
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT active_provider, updated_at, updated_by
                    FROM llm_runtime_config
                    WHERE id = 1
                    """
                )
                row = await cursor.fetchone()
                if row:
                    persisted = self._normalize_provider(row["active_provider"])
                    if self._profiles[persisted].configured:
                        selected = persisted
                        self._updated_at = str(row["updated_at"])
                        self._updated_by = str(row["updated_by"])
                await db.commit()

        self._apply(selected)
        if not self._memory_only and self._updated_at is None:
            await self._persist(selected, updated_by="environment")

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.natural_query_llm_enabled,
            "activeProvider": self._active_provider,
            "updatedAt": self._updated_at,
            "updatedBy": self._updated_by,
            "providers": [
                {
                    "id": provider,
                    "label": PROVIDER_LABELS[provider],
                    "model": profile.model,
                    "baseUrl": profile.base_url,
                    "configured": profile.configured,
                    "active": provider == self._active_provider,
                }
                for provider, profile in self._profiles.items()
            ],
        }

    async def switch(self, provider: str, *, updated_by: str) -> dict[str, Any]:
        normalized = self._normalize_provider(provider)
        profile = self._profiles[normalized]
        if not profile.configured:
            key_name = "DEEPSEEK_API_KEY" if normalized == "deepseek" else "LM_STUDIO_API_KEY"
            raise LlmProviderConfigurationError(
                f"{PROVIDER_LABELS[normalized]} 未完成配置，请先在 .env 中填写 {key_name}。"
            )

        async with self._lock:
            self._apply(normalized)
            if not self._memory_only:
                await self._persist(normalized, updated_by=updated_by)
            else:
                self._updated_at = _utc_iso()
                self._updated_by = updated_by
        return self.status()

    @property
    def _memory_only(self) -> bool:
        return self.database_path.startswith("memory://") or self.database_path == ":memory:"

    def _profile_from_settings(self, provider: str) -> LlmProviderProfile:
        is_initial = provider == self._initial_provider
        if provider == "lm_studio":
            return LlmProviderProfile(
                provider=provider,
                model=self.settings.llm_model if is_initial else self.settings.lm_studio_model,
                base_url=(
                    self.settings.llm_base_url if is_initial else self.settings.lm_studio_base_url
                ),
                api_key=(
                    self.settings.lm_studio_api_key
                    or (self.settings.llm_api_key if is_initial else "")
                ),
                timeout_seconds=(
                    self.settings.llm_timeout_seconds
                    if is_initial
                    else self.settings.lm_studio_timeout_seconds
                ),
                max_output_tokens=(
                    self.settings.llm_max_output_tokens
                    if is_initial
                    else self.settings.lm_studio_max_output_tokens
                ),
                ssl_verify=(
                    self.settings.llm_ssl_verify
                    if is_initial
                    else self.settings.lm_studio_ssl_verify
                ),
            )
        return LlmProviderProfile(
            provider=provider,
            model=self.settings.llm_model if is_initial else self.settings.deepseek_model,
            base_url=self.settings.llm_base_url if is_initial else self.settings.deepseek_base_url,
            api_key=(
                self.settings.deepseek_api_key
                or (self.settings.llm_api_key if is_initial else "")
            ),
            timeout_seconds=(
                self.settings.llm_timeout_seconds
                if is_initial
                else self.settings.deepseek_timeout_seconds
            ),
            max_output_tokens=(
                self.settings.llm_max_output_tokens
                if is_initial
                else self.settings.deepseek_max_output_tokens
            ),
            ssl_verify=(
                self.settings.llm_ssl_verify
                if is_initial
                else self.settings.deepseek_ssl_verify
            ),
        )

    def _apply(self, provider: str) -> None:
        profile = self._profiles[provider]
        self.settings.llm_provider = profile.provider
        self.settings.llm_model = profile.model
        self.settings.llm_base_url = profile.base_url
        self.settings.llm_api_key = profile.api_key
        self.settings.llm_timeout_seconds = profile.timeout_seconds
        self.settings.llm_max_output_tokens = profile.max_output_tokens
        self.settings.llm_ssl_verify = profile.ssl_verify
        self._active_provider = provider

    async def _persist(self, provider: str, *, updated_by: str) -> None:
        updated_at = _utc_iso()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO llm_runtime_config (id, active_provider, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    active_provider = excluded.active_provider,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (provider, updated_at, updated_by),
            )
            await db.commit()
        self._updated_at = updated_at
        self._updated_by = updated_by

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        normalized = str(provider or "").strip().lower()
        if normalized not in SUPPORTED_LLM_PROVIDERS:
            raise LlmProviderConfigurationError(
                f"不支持的 LLM 供应商：{provider}"
            )
        return normalized


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

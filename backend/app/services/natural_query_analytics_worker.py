from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_question_analytics import analyze_pending_questions

logger = logging.getLogger(__name__)


class NaturalQueryAnalyticsWorker:
    """Analyze newly recorded employee questions outside the request path."""

    def __init__(
        self,
        *,
        store: NaturalQueryConversationStore,
        settings: Settings,
    ) -> None:
        self.store = store
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._stopping = False

    def start(self) -> None:
        if not self.settings.natural_query_analytics_worker_enabled or self._task:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="natural-query-analytics")

    def notify(self) -> None:
        if self._task and not self._task.done():
            self._wake_event.set()

    async def stop(self) -> None:
        if not self._task:
            return
        self._stopping = True
        self._wake_event.set()
        try:
            await self._task
        finally:
            self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                result = await analyze_pending_questions(
                    store=self.store,
                    settings=self.settings,
                    limit=self.settings.natural_query_analytics_pending_limit,
                )
                if result.analyzed:
                    logger.info(
                        "Analyzed %s employee questions (%s meaningful, %s ignored)",
                        result.analyzed,
                        result.meaningful,
                        result.ignored,
                    )
            except Exception:
                logger.exception("Unable to analyze pending employee questions")

            if self._stopping:
                break
            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=max(1.0, self.settings.natural_query_analytics_poll_interval_seconds),
                )
            except TimeoutError:
                pass

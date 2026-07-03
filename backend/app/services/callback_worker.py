import asyncio
import json
import logging
from typing import Any

from app.core.config import Settings
from app.services.callback_store import CallbackEvent, CallbackStore
from app.services.filemaker_client import FileMakerClient

logger = logging.getLogger(__name__)


class CallbackWorker:
    def __init__(
        self,
        *,
        store: CallbackStore,
        filemaker_client: FileMakerClient,
        settings: Settings,
    ):
        self.store = store
        self.filemaker_client = filemaker_client
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="callback-worker")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task

    async def _run(self) -> None:
        logger.info("Callback worker started")
        while not self._stop_event.is_set():
            try:
                event = await self.store.claim_due_event()
                if event is None:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.settings.callback_poll_interval_seconds,
                    )
                    continue

                await self._process_event(event)
            except asyncio.TimeoutError:
                continue
            except Exception:
                logger.exception("Callback worker loop failed")
                await asyncio.sleep(self.settings.callback_poll_interval_seconds)

        logger.info("Callback worker stopped")

    async def _process_event(self, event: CallbackEvent) -> None:
        try:
            result = await self._apply_filemaker_operation(event)
            await self.store.mark_success(event.id, result)
            logger.info("Callback event %s processed", event.id)
        except Exception as exc:
            logger.exception("Callback event %s failed", event.id)
            await self.store.mark_failure(event, str(exc))

    async def _apply_filemaker_operation(self, event: CallbackEvent) -> Any:
        if self.settings.filemaker_read_only:
            return {
                "skipped": True,
                "reason": "FileMaker read-only mode is enabled",
            }

        operation = event.payload.get("filemaker")
        if isinstance(operation, dict):
            return await self._apply_explicit_operation(operation)

        if not self.settings.mes_filemaker_layout:
            raise RuntimeError("MES_FILEMAKER_LAYOUT is required for MES callbacks")

        script_param = json.dumps(
            {
                "source": event.source,
                "eventId": event.event_id,
                "payload": event.payload,
            },
            ensure_ascii=False,
        )
        return await self.filemaker_client.run_script(
            self.settings.mes_filemaker_layout,
            self.settings.mes_filemaker_script_name,
            script_param,
        )

    async def _apply_explicit_operation(self, operation: dict[str, Any]) -> Any:
        op = operation.get("operation")
        layout = operation.get("layout")
        if not layout:
            raise ValueError("filemaker.layout is required")

        if op == "create_record":
            return await self.filemaker_client.create_record(
                layout,
                operation.get("fieldData") or operation.get("field_data") or {},
            )

        if op == "update_record":
            record_id = str(operation.get("recordId") or operation.get("record_id") or "")
            if not record_id:
                raise ValueError("filemaker.recordId is required for update_record")
            return await self.filemaker_client.update_record(
                layout,
                record_id,
                operation.get("fieldData") or operation.get("field_data") or {},
            )

        if op == "run_script":
            script_name = operation.get("scriptName") or operation.get("script_name")
            if not script_name:
                raise ValueError("filemaker.scriptName is required for run_script")
            script_param = operation.get("scriptParam") or operation.get("script_param")
            if script_param is not None and not isinstance(script_param, str):
                script_param = json.dumps(script_param, ensure_ascii=False)
            return await self.filemaker_client.run_script(layout, script_name, script_param)

        raise ValueError(f"Unsupported FileMaker operation: {op}")

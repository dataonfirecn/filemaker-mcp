import asyncio
import base64
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class FileMakerAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class FileMakerClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: str | None = None
        self._token_obtained_at: float = 0
        self._token_last_used_at: float = 0
        self._token_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=settings.filemaker_timeout_seconds,
            verify=settings.filemaker_ssl_verify,
        )

    async def close(self) -> None:
        await self.release_token()
        await self._client.aclose()

    def token_status(self) -> dict[str, Any]:
        now = time.time()
        has_token = bool(self._token)
        token_age_seconds = (
            max(0, int(now - self._token_obtained_at))
            if has_token and self._token_obtained_at
            else None
        )
        seconds_since_last_use = (
            max(0, int(now - self._token_last_used_at))
            if has_token and self._token_last_used_at
            else None
        )
        return {
            "hasToken": has_token,
            "tokenObtainedAt": self._format_timestamp(self._token_obtained_at),
            "tokenLastUsedAt": self._format_timestamp(self._token_last_used_at),
            "tokenAgeSeconds": token_age_seconds,
            "secondsSinceLastUse": seconds_since_last_use,
            "inactivityTimeoutSeconds": (
                self.settings.filemaker_token_inactivity_timeout_seconds
            ),
            "refreshStrategy": "reuse_until_401",
        }

    async def release_token(self) -> None:
        async with self._token_lock:
            token = self._token
            self._clear_token()

        if not token:
            return

        await self._delete_session(token)

    async def _delete_session(self, token: str) -> None:
        try:
            await self._client.delete(
                f"{self._base_url()}/sessions/{self._encode_param(token)}",
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError:
            logger.exception("Unable to release FileMaker Data API session")

    def _encode_param(self, value: str) -> str:
        return quote(value, safe="").replace("%20", "+")

    def _base_url(self) -> str:
        host = self.settings.filemaker_host.rstrip("/")
        database = self._encode_param(self.settings.filemaker_database)
        version = self.settings.filemaker_api_version
        return f"{host}/fmi/data/{version}/databases/{database}"

    def _clear_token(self) -> None:
        self._token = None
        self._token_obtained_at = 0
        self._token_last_used_at = 0

    def _format_timestamp(self, value: float) -> str | None:
        if not value:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    async def get_token(self) -> str:
        if self._token:
            return self._token

        async with self._token_lock:
            if self._token:
                return self._token

            if not self.settings.filemaker_configured:
                raise FileMakerAPIError("FileMaker is not configured")

            credentials = (
                f"{self.settings.filemaker_username}:{self.settings.filemaker_password}"
            ).encode("utf-8")
            encoded_credentials = base64.b64encode(credentials).decode("ascii")
            try:
                response = await self._client.post(
                    f"{self._base_url()}/sessions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {encoded_credentials}",
                    },
                )
            except httpx.RequestError as exc:
                raise FileMakerAPIError(
                    "Unable to connect to FileMaker",
                    payload=str(exc),
                ) from exc

            if not response.is_success:
                raise FileMakerAPIError(
                    "Failed to authenticate with FileMaker",
                    response.status_code,
                    self._safe_json(response),
                )

            payload = response.json()
            token = payload.get("response", {}).get("token")
            if not token:
                raise FileMakerAPIError("No token received from FileMaker API")

            now = time.time()
            self._token = token
            self._token_obtained_at = now
            self._token_last_used_at = now
            logger.info(
                "FileMaker Data API token acquired; inactivity_timeout_seconds=%s",
                self.settings.filemaker_token_inactivity_timeout_seconds,
            )
            return token

    async def request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retry_on_unauthorized: bool = True,
    ) -> Any:
        token = await self.get_token()
        try:
            response = await self._client.request(
                method,
                f"{self._base_url()}{endpoint}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                json=json_body,
                params=params,
            )
        except httpx.RequestError as exc:
            raise FileMakerAPIError(
                "Unable to connect to FileMaker",
                payload=str(exc),
            ) from exc

        if response.status_code == 401 and retry_on_unauthorized:
            self._clear_token()
            return await self.request(
                endpoint,
                method=method,
                json_body=json_body,
                params=params,
                retry_on_unauthorized=False,
            )

        if not response.is_success:
            raise FileMakerAPIError(
                "FileMaker API request failed",
                response.status_code,
                self._safe_json(response),
            )

        self._token_last_used_at = time.time()
        if response.content:
            return response.json()
        return None

    async def find_records(
        self,
        layout: str,
        query: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 1,
        sort: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        encoded_layout = self._encode_param(layout)
        query = query or {}

        if sort:
            effective_query = query if query else {"ID": "*"}
            result = await self.request(
                f"/layouts/{encoded_layout}/_find",
                method="POST",
                json_body={
                    "query": [effective_query],
                    "limit": limit,
                    "offset": offset,
                    "sort": sort,
                },
            )
        elif query:
            result = await self.request(
                f"/layouts/{encoded_layout}/_find",
                method="POST",
                json_body={"query": [query], "limit": limit, "offset": offset},
            )
        else:
            result = await self.request(
                f"/layouts/{encoded_layout}/records",
                params={"_limit": limit, "_offset": offset},
            )

        data_info = result.get("response", {}).get("dataInfo", {})
        return {
            "data": result.get("response", {}).get("data", []),
            "foundCount": data_info.get("foundCount")
            or data_info.get("totalRecordCount")
            or 0,
            "returnedCount": data_info.get("returnedCount") or 0,
        }

    async def get_record(self, layout: str, record_id: str) -> Any:
        encoded_layout = self._encode_param(layout)
        result = await self.request(f"/layouts/{encoded_layout}/records/{record_id}")
        return result.get("response", {}).get("data")

    async def create_record(self, layout: str, data: dict[str, Any]) -> dict[str, Any]:
        encoded_layout = self._encode_param(layout)
        result = await self.request(
            f"/layouts/{encoded_layout}/records",
            method="POST",
            json_body={"fieldData": data},
        )
        response = result.get("response", {})
        return {"recordId": response.get("recordId"), "modId": response.get("modId")}

    async def update_record(
        self,
        layout: str,
        record_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        encoded_layout = self._encode_param(layout)
        result = await self.request(
            f"/layouts/{encoded_layout}/records/{record_id}",
            method="PATCH",
            json_body={"fieldData": data},
        )
        response = result.get("response", {})
        return {"recordId": response.get("recordId"), "modId": response.get("modId")}

    async def delete_record(self, layout: str, record_id: str) -> dict[str, Any]:
        encoded_layout = self._encode_param(layout)
        await self.request(
            f"/layouts/{encoded_layout}/records/{record_id}",
            method="DELETE",
        )
        return {"recordId": record_id}

    async def run_script(
        self,
        layout: str,
        script_name: str,
        script_param: str | None = None,
    ) -> dict[str, Any]:
        encoded_layout = self._encode_param(layout)
        encoded_script = self._encode_param(script_name)
        params = {"script.param": script_param} if script_param is not None else None
        result = await self.request(
            f"/layouts/{encoded_layout}/script/{encoded_script}",
            params=params,
        )
        response = result.get("response", {})
        return {
            "result": response.get("scriptResult"),
            "error": response.get("scriptError"),
        }

    async def list_layouts(self) -> list[str]:
        result = await self.request("/layouts")
        layouts: list[str] = []
        for item in result.get("response", {}).get("layouts", []):
            if item.get("isFolder") and item.get("folderLayoutNames"):
                layouts.extend(child["name"] for child in item["folderLayoutNames"])
            elif not item.get("isFolder"):
                layouts.append(item["name"])
        return layouts

    async def get_layout_fields(self, layout: str) -> list[dict[str, Any]]:
        encoded_layout = self._encode_param(layout)
        result = await self.request(f"/layouts/{encoded_layout}")
        return result.get("response", {}).get("fieldMetaData", [])

    def _safe_json(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

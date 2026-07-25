import pytest
import pytest_asyncio

from app.services.filemaker_client import FileMakerClient


class SettingsStub:
    filemaker_host = "https://filemaker.example.test"
    filemaker_database = "DMS"
    filemaker_username = "api_user"
    filemaker_password = "secret"
    filemaker_api_version = "v2"
    filemaker_token_inactivity_timeout_seconds = 900
    filemaker_timeout_seconds = 30.0
    filemaker_ssl_verify = False

    @property
    def filemaker_configured(self) -> bool:
        return True


class FakeResponse:
    def __init__(
        self,
        token: str = "token",
        *,
        status_code: int = 200,
        payload: dict[str, object] | None = None,
    ):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.content = b"{}"
        self._token = token
        self._payload = payload

    def json(self) -> dict[str, object]:
        if self._payload is not None:
            return self._payload
        return {"response": {"token": self._token}}


class FakeHTTPClient:
    def __init__(self):
        self.post_count = 0
        self.request_count = 0
        self.delete_count = 0
        self.closed = False
        self.request_statuses: list[int] = []

    async def post(self, *_args, **_kwargs) -> FakeResponse:
        self.post_count += 1
        return FakeResponse(f"token-{self.post_count}")

    async def request(self, *_args, **_kwargs) -> FakeResponse:
        self.request_count += 1
        status_code = self.request_statuses.pop(0) if self.request_statuses else 200
        return FakeResponse(
            status_code=status_code,
            payload={"response": {"ok": True}, "messages": []},
        )

    async def delete(self, *_args, **_kwargs) -> FakeResponse:
        self.delete_count += 1
        return FakeResponse()

    async def aclose(self) -> None:
        self.closed = True


@pytest_asyncio.fixture
async def client() -> FileMakerClient:
    filemaker_client = FileMakerClient(SettingsStub())
    real_http_client = filemaker_client._client
    filemaker_client._client = FakeHTTPClient()
    await real_http_client.aclose()
    try:
        yield filemaker_client
    finally:
        await filemaker_client.close()


@pytest.mark.asyncio
async def test_token_is_reused(client: FileMakerClient) -> None:
    fake_http = client._client

    first = await client.get_token()
    second = await client.get_token()

    assert first == second
    assert fake_http.post_count == 1
    assert client.token_status()["hasToken"] is True


@pytest.mark.asyncio
async def test_token_is_not_refreshed_by_local_timeout(client: FileMakerClient) -> None:
    fake_http = client._client

    first = await client.get_token()
    client._token_obtained_at -= (
        SettingsStub.filemaker_token_inactivity_timeout_seconds + 1
    )
    second = await client.get_token()

    assert first == second
    assert fake_http.post_count == 1
    assert fake_http.delete_count == 0


@pytest.mark.asyncio
async def test_unauthorized_response_refreshes_token_once(
    client: FileMakerClient,
) -> None:
    fake_http = client._client
    fake_http.request_statuses = [401, 200]

    result = await client.request("/layouts")

    assert result == {"response": {"ok": True}, "messages": []}
    assert fake_http.post_count == 2
    assert fake_http.request_count == 2
    assert client.token_status()["hasToken"] is True


@pytest.mark.asyncio
async def test_close_releases_token(client: FileMakerClient) -> None:
    fake_http = client._client

    await client.get_token()
    await client.close()

    assert fake_http.delete_count == 1
    assert fake_http.closed is True
    assert client.token_status()["hasToken"] is False


@pytest.mark.asyncio
async def test_find_records_query_empty_result_does_not_use_total_record_count(
    client: FileMakerClient,
) -> None:
    async def fake_request(*_args, **_kwargs):
        return {
            "response": {
                "data": [],
                "dataInfo": {
                    "returnedCount": 0,
                    "totalRecordCount": 44675,
                },
            }
        }

    client.request = fake_request

    result = await client.find_records(
        "Parts",
        query={"Date Created": "07/07/2026"},
    )

    assert result == {"data": [], "foundCount": 0, "returnedCount": 0}


@pytest.mark.asyncio
async def test_find_records_list_uses_total_record_count_when_unfiltered(
    client: FileMakerClient,
) -> None:
    async def fake_request(*_args, **_kwargs):
        return {
            "response": {
                "data": [],
                "dataInfo": {
                    "returnedCount": 0,
                    "totalRecordCount": 44675,
                },
            }
        }

    client.request = fake_request

    result = await client.find_records("Parts")

    assert result == {"data": [], "foundCount": 44675, "returnedCount": 0}

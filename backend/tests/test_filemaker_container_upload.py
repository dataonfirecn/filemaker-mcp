import pytest

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
    def filemaker_configured(self):
        return True


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.content = b"{}"
        self._payload = payload or {}

    def json(self):
        return self._payload


class UploadHTTPClient:
    def __init__(self):
        self.calls = []
        self.statuses = [200]

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status = self.statuses.pop(0)
        return FakeResponse(
            status_code=status,
            payload={"response": {"recordId": "22", "modId": "3"}},
        )

    async def delete(self, *_args, **_kwargs):
        return FakeResponse()

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_container_upload_uses_multipart_upload_field() -> None:
    client = FileMakerClient(SettingsStub())
    real_http = client._client
    upload_http = UploadHTTPClient()
    client._client = upload_http
    await real_http.aclose()
    client._token = "token"

    response = await client.upload_container(
        "@零件",
        "22",
        "影像 | 容器",
        b"jpeg",
        "part.jpg",
        "image/jpeg",
    )

    assert response == {"recordId": "22", "modId": "3"}
    url, kwargs = upload_http.calls[0]
    assert "/layouts/%40%E9%9B%B6%E4%BB%B6/records/22/containers/" in url
    assert kwargs["files"] == {"upload": ("part.jpg", b"jpeg", "image/jpeg")}
    assert kwargs["headers"] == {"Authorization": "Bearer token"}
    await client.close()

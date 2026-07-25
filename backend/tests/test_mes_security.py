"""MES 回调鉴权（API key + HMAC 签名）测试。

直接测试 ``verify_mes_request``，验证：
- 配置了 API key 时，缺失/错误 x-api-key → 401
- 配置了 HMAC secret 时，错误签名 → 401
- 正确密钥 + 正确签名 → 通过
- 两者均未配置时跳过校验（向后兼容，但生产环境由 validate_production_security 兜底）
"""

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.security import verify_mes_request


class FakeRequest:
    """轻量 Request 替身，仅提供 verify_mes_request 所需接口。"""

    def __init__(self, body: bytes, headers: dict[str, str]) -> None:
        self._body = body
        self.headers = headers

    async def body(self) -> bytes:
        return self._body


def _settings(
    *,
    api_key: str = "",
    hmac_secret: str = "",
) -> Settings:
    # _env_file=None 避免本地 .env 中的 LLM_API_KEY 等变量干扰测试隔离
    return Settings(
        _env_file=None,
        mes_callback_api_key=api_key,
        mes_hmac_secret=hmac_secret,
    )


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.asyncio
async def test_missing_api_key_when_required_raises_401() -> None:
    settings = _settings(api_key="server-secret")
    request = FakeRequest(b'{"eventId":"e1"}', headers={})

    with pytest.raises(HTTPException) as exc_info:
        await verify_mes_request(request, settings)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wrong_api_key_raises_401() -> None:
    settings = _settings(api_key="server-secret")
    request = FakeRequest(b'{"eventId":"e1"}', headers={"x-api-key": "wrong"})

    with pytest.raises(HTTPException) as exc_info:
        await verify_mes_request(request, settings)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_correct_api_key_passes() -> None:
    settings = _settings(api_key="server-secret")
    request = FakeRequest(b'{"eventId":"e1"}', headers={"x-api-key": "server-secret"})

    body = await verify_mes_request(request, settings)
    assert body == b'{"eventId":"e1"}'


@pytest.mark.asyncio
async def test_wrong_hmac_signature_raises_401() -> None:
    settings = _settings(hmac_secret="hmac-secret")
    request = FakeRequest(
        b'{"eventId":"e1"}',
        headers={"x-mes-signature": "sha256=deadbeef"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await verify_mes_request(request, settings)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_correct_hmac_signature_passes() -> None:
    settings = _settings(hmac_secret="hmac-secret")
    payload = b'{"eventId":"e1"}'
    request = FakeRequest(
        payload,
        headers={"x-mes-signature": _sign("hmac-secret", payload)},
    )

    body = await verify_mes_request(request, settings)
    assert body == payload


@pytest.mark.asyncio
async def test_both_credentials_required_and_valid() -> None:
    """同时配置 API key 与 HMAC 时，两者都必须正确。"""
    settings = _settings(api_key="server-secret", hmac_secret="hmac-secret")
    payload = b'{"eventId":"e1"}'
    request = FakeRequest(
        payload,
        headers={
            "x-api-key": "server-secret",
            "x-mes-signature": _sign("hmac-secret", payload),
        },
    )

    body = await verify_mes_request(request, settings)
    assert body == payload


@pytest.mark.asyncio
async def test_no_credentials_configured_skips_verification() -> None:
    """两者均未配置时跳过校验（向后兼容；生产环境由 validate_production_security 兜底）。"""
    settings = _settings()  # api_key 与 hmac_secret 均为空
    request = FakeRequest(b'{"eventId":"e1"}', headers={})

    body = await verify_mes_request(request, settings)
    assert body == b'{"eventId":"e1"}'


@pytest.mark.asyncio
async def test_hmac_signature_is_body_specific() -> None:
    """签名针对特定 body；篡改 body 后原签名应失效。"""
    settings = _settings(hmac_secret="hmac-secret")
    original = b'{"eventId":"e1"}'
    tampered = b'{"eventId":"e1","malicious":true}'
    request = FakeRequest(
        tampered,
        headers={"x-mes-signature": _sign("hmac-secret", original)},
    )

    with pytest.raises(HTTPException) as exc_info:
        await verify_mes_request(request, settings)

    assert exc_info.value.status_code == 401

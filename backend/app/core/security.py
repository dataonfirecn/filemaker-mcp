import hashlib
import hmac

from fastapi import HTTPException, Request, status

from app.core.config import Settings


async def verify_mes_request(request: Request, settings: Settings) -> bytes:
    body = await request.body()

    if settings.mes_callback_api_key:
        api_key = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(api_key, settings.mes_callback_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid callback API key",
            )

    if settings.mes_hmac_secret:
        signature = request.headers.get("x-mes-signature", "")
        digest = hmac.new(
            settings.mes_hmac_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        expected = f"sha256={digest}"
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid callback signature",
            )

    return body

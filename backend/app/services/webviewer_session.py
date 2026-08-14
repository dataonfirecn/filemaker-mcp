import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from app.core.config import Settings
from app.services.audit_log import OperatorContext


class WebViewerSessionError(ValueError):
    pass


def create_mock_context(
    *,
    operator_account: str,
    operator_name: str,
    operator_privilege: str = "mock",
    product_sku: str = "",
    order_id: str = "",
    line_id: str = "",
    bom_calc_id: str = "",
    customer_id: str = "",
    customer_name: str = "",
    currency: str = "",
    persistent_id: str = "mock",
) -> dict[str, Any]:
    return {
        "operator": {
            "account": operator_account,
            "name": operator_name,
            "privilege": operator_privilege,
            "persistentId": persistent_id,
        },
        "productSku": product_sku,
        "orderId": order_id,
        "lineId": line_id,
        "bomCalcId": bom_calc_id,
        "customerId": customer_id,
        "customerName": customer_name,
        "currency": currency,
        "issuedAt": int(time.time()),
    }


def verify_external_context(ctx: str, sig: str, settings: Settings) -> dict[str, Any]:
    expected = _sign(ctx, settings.webviewer_context_secret)
    if not hmac.compare_digest(expected, sig):
        raise WebViewerSessionError("Invalid WebViewer context signature")
    try:
        payload = json.loads(_b64decode(ctx).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebViewerSessionError("Invalid WebViewer context payload") from exc
    return payload


def issue_session_token(
    context: dict[str, Any],
    settings: Settings,
    *,
    ttl_seconds: int | None = None,
) -> tuple[str, dict[str, Any]]:
    now = int(time.time())
    effective_ttl_seconds = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.webviewer_session_ttl_seconds
    )
    session_payload = {
        "sessionId": str(uuid.uuid4()),
        "operator": context.get("operator") or {},
        "productSku": context.get("productSku") or "",
        # FileMaker renamed the order primary-key field from "出貨單 ID" to
        # "id". Keep the public WebViewer contract as "orderId", while
        # accepting signed contexts produced with the renamed field key.
        "orderId": context.get("orderId") or context.get("id") or "",
        "lineId": context.get("lineId") or "",
        "bomCalcId": context.get("bomCalcId") or "",
        "customerId": context.get("customerId") or "",
        "customerName": context.get("customerName") or "",
        "currency": context.get("currency") or "",
        "access": context.get("access") or {},
        "partPermissions": context.get("partPermissions") or {},
        "iat": now,
        "exp": now + effective_ttl_seconds,
    }
    encoded = _b64encode(json.dumps(session_payload, ensure_ascii=False).encode("utf-8"))
    return f"{encoded}.{_sign(encoded, settings.webviewer_context_secret)}", session_payload


def verify_session_token(token: str, settings: Settings) -> dict[str, Any]:
    payload = verify_session_token_signature(token, settings)
    if int(payload.get("exp") or 0) < int(time.time()):
        raise WebViewerSessionError("WebViewer session expired")
    return payload


def verify_session_token_signature(
    token: str,
    settings: Settings,
) -> dict[str, Any]:
    """Verify a session's authenticity without granting normal API access.

    Diagnostic delivery uses this to accept a recently expired, but genuinely
    server-issued, iPad token. The diagnostic endpoint remains the only caller
    that may apply a bounded expiry grace period.
    """
    try:
        encoded, sig = token.split(".", 1)
    except ValueError as exc:
        raise WebViewerSessionError("Invalid WebViewer session token") from exc

    expected = _sign(encoded, settings.webviewer_context_secret)
    if not hmac.compare_digest(expected, sig):
        raise WebViewerSessionError("Invalid WebViewer session signature")
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise WebViewerSessionError("Invalid WebViewer session payload") from exc
    return payload


def verify_session_token_for_diagnostics(
    token: str,
    settings: Settings,
    *,
    expired_grace_seconds: int,
) -> dict[str, Any]:
    payload = verify_session_token_signature(token, settings)
    expires_at = int(payload.get("exp") or 0)
    now = int(time.time())
    if expires_at <= 0 or expires_at < now - max(expired_grace_seconds, 0):
        raise WebViewerSessionError("WebViewer diagnostic session expired")
    return payload


def operator_from_session(payload: dict[str, Any]) -> OperatorContext:
    operator = payload.get("operator") or {}
    return OperatorContext(
        session_id=str(payload.get("sessionId") or ""),
        account=str(operator.get("account") or "unknown"),
        name=str(operator.get("name") or operator.get("account") or "unknown"),
        privilege=str(operator.get("privilege") or ""),
        persistent_id=str(operator.get("persistentId") or ""),
        permissions={
            str(key): bool(value)
            for key, value in (payload.get("access") or {}).items()
        },
        part_permissions={
            str(key): bool(value)
            for key, value in (payload.get("partPermissions") or {}).items()
        },
    )


def _sign(value: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)

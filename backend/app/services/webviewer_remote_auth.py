import json
from dataclasses import dataclass

from app.core.config import Settings
from app.services.customer_chat_auth import (
    INSECURE_SECRET_PLACEHOLDERS,
    verify_customer_password,
)


class WebViewerRemoteAuthError(ValueError):
    pass


@dataclass(frozen=True)
class WebViewerRemoteAccount:
    username: str
    display_name: str
    password_hash: str
    privilege_set: str


def load_webviewer_remote_accounts(settings: Settings) -> dict[str, WebViewerRemoteAccount]:
    try:
        raw = json.loads(settings.webviewer_remote_accounts_json or "[]")
    except json.JSONDecodeError as exc:
        raise WebViewerRemoteAuthError(
            "WEBVIEWER_REMOTE_ACCOUNTS_JSON is not valid JSON"
        ) from exc
    if not isinstance(raw, list):
        raise WebViewerRemoteAuthError("WEBVIEWER_REMOTE_ACCOUNTS_JSON must be an account array")

    accounts: dict[str, WebViewerRemoteAccount] = {}
    for item in raw:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        username = str(item.get("username") or "").strip()
        display_name = str(item.get("displayName") or username).strip()
        password_hash = str(item.get("passwordHash") or "").strip()
        privilege_set = str(item.get("privilegeSet") or "internal_remote").strip()
        if not username or not password_hash:
            raise WebViewerRemoteAuthError(
                "Each WebViewer remote account requires username and passwordHash"
            )
        key = username.casefold()
        if key in accounts:
            raise WebViewerRemoteAuthError(f"Duplicate WebViewer remote account: {username}")
        accounts[key] = WebViewerRemoteAccount(
            username=username,
            display_name=display_name or username,
            password_hash=password_hash,
            privilege_set=privilege_set or "internal_remote",
        )
    return accounts


def authenticate_webviewer_remote(
    username: str,
    password: str,
    settings: Settings,
) -> WebViewerRemoteAccount | None:
    accounts = load_webviewer_remote_accounts(settings)
    account = accounts.get(username.strip().casefold())
    valid = verify_customer_password(password, account.password_hash) if account else False
    return account if account and valid else None


def validate_webviewer_remote_configuration(settings: Settings) -> list[str]:
    if not settings.webviewer_remote_access_enabled:
        return []
    try:
        accounts = load_webviewer_remote_accounts(settings)
    except WebViewerRemoteAuthError as exc:
        return [str(exc)]
    problems: list[str] = []
    if not accounts:
        problems.append(
            "WEBVIEWER_REMOTE_ACCESS_ENABLED=true requires at least one remote account."
        )
    for account in accounts.values():
        parts = account.password_hash.split("$", 3)
        if (
            len(parts) != 4
            or parts[0] != "pbkdf2_sha256"
            or account.password_hash.lower() in INSECURE_SECRET_PLACEHOLDERS
        ):
            problems.append(f"WebViewer remote account {account.username} has an invalid passwordHash.")
    return problems

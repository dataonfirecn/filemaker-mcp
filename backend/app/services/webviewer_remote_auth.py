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
    allowed_client_channels: tuple[str, ...] = ()
    allowed_user_agent_prefixes: tuple[str, ...] = ()


def _optional_string_list(item: dict, key: str) -> tuple[str, ...]:
    raw = item.get(key)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise WebViewerRemoteAuthError(f"{key} must be a string array")
    values = tuple(str(value).strip() for value in raw if str(value).strip())
    if len(values) != len(raw):
        raise WebViewerRemoteAuthError(f"{key} must contain only non-empty strings")
    return values


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
        allowed_client_channels = _optional_string_list(item, "allowedClientChannels")
        allowed_user_agent_prefixes = _optional_string_list(
            item,
            "allowedUserAgentPrefixes",
        )
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
            allowed_client_channels=allowed_client_channels,
            allowed_user_agent_prefixes=allowed_user_agent_prefixes,
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


def webviewer_remote_request_allowed(
    account: WebViewerRemoteAccount,
    *,
    client_channel: str,
    user_agent: str,
) -> bool:
    normalized_channel = client_channel.strip().casefold()
    allowed_channels = {
        value.casefold()
        for value in account.allowed_client_channels
    }
    if allowed_channels and normalized_channel not in allowed_channels:
        return False
    if (
        account.allowed_user_agent_prefixes
        and not any(user_agent.startswith(prefix) for prefix in account.allowed_user_agent_prefixes)
    ):
        return False
    return True


def is_webviewer_mobile_request(*, client_channel: str, user_agent: str) -> bool:
    return (
        client_channel.strip().casefold() == "ios-pda"
        and user_agent.startswith("StarRCPDA/")
    )


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

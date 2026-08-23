"""Create the Stock Check production env file without printing secret values."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
from pathlib import Path


SOURCE_ENV = Path("/opt/starrc-filemaker/.env")
TARGET_ENV = Path("/opt/stock-check/.env")
REQUIRED_FILEMAKER_KEYS = (
    "FILEMAKER_HOST",
    "FILEMAKER_DATABASE",
    "FILEMAKER_USERNAME",
    "FILEMAKER_PASSWORD",
    "FILEMAKER_API_VERSION",
    "FILEMAKER_SSL_VERIFY",
    "FILEMAKER_TOKEN_INACTIVITY_TIMEOUT_SECONDS",
)


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def main() -> None:
    if TARGET_ENV.exists():
        raise SystemExit(f"Refusing to overwrite existing {TARGET_ENV}")
    encoded_hash = os.environ.get("STOCK_CHECK_INITIAL_ADMIN_PASSWORD_HASH_B64", "")
    if not encoded_hash:
        raise SystemExit("STOCK_CHECK_INITIAL_ADMIN_PASSWORD_HASH_B64 is required")
    password_hash = base64.b64decode(encoded_hash).decode("utf-8")
    if not password_hash.startswith("pbkdf2_sha256$600000$"):
        raise SystemExit("Invalid Stock Check administrator password hash")

    initial_scope = {
        "clientName": os.environ.get("STOCK_CHECK_INITIAL_CLIENT_NAME", "").strip(),
        "productPrivilege": os.environ.get(
            "STOCK_CHECK_INITIAL_WEB_CUSTOMER_CODE", ""
        ).strip(),
        "partCustomerId": os.environ.get(
            "STOCK_CHECK_INITIAL_CATALOG_CUSTOMER_ID", ""
        ).strip(),
        "shipmentCompanyId": os.environ.get(
            "STOCK_CHECK_INITIAL_SHIPMENT_COMPANY_ID", ""
        ).strip(),
    }
    missing_scope = [key for key, value in initial_scope.items() if not value and key != "shipmentCompanyId"]
    if missing_scope:
        raise SystemExit(
            "Missing initial customer scope: " + ", ".join(missing_scope)
        )

    source = _read_env(SOURCE_ENV)
    missing = [key for key in REQUIRED_FILEMAKER_KEYS if not source.get(key)]
    if missing:
        raise SystemExit(f"Missing FileMaker settings: {', '.join(missing)}")

    account_json = json.dumps(
        [
            {
                "username": os.environ.get(
                    "STOCK_CHECK_INITIAL_ADMIN_USERNAME", "admin"
                ).strip(),
                "displayName": os.environ.get(
                    "STOCK_CHECK_INITIAL_ADMIN_DISPLAY_NAME",
                    "Stock Check Administrator",
                ).strip(),
                "email": os.environ.get(
                    "STOCK_CHECK_INITIAL_ADMIN_EMAIL", ""
                ).strip(),
                **initial_scope,
                "canViewPrice": True,
                "isAdmin": True,
                "passwordHash": password_hash,
            }
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    values = {
        "STOCK_CHECK_BACKEND_IMAGE": "stock-check-backend:latest",
        "STOCK_CHECK_FRONTEND_IMAGE": "stock-check-frontend:latest",
        "STOCK_CHECK_POSTGRES_DB": "stock_check",
        "STOCK_CHECK_POSTGRES_USER": "stock_check",
        "STOCK_CHECK_POSTGRES_PASSWORD": secrets.token_hex(24),
        "STOCK_CHECK_POSTGRES_VOLUME": "stock-check-postgres-data",
        "STOCK_CHECK_BACKEND_VOLUME": "stock-check-backend-data",
        **{key: source[key] for key in REQUIRED_FILEMAKER_KEYS},
        "WEBVIEWER_CONTEXT_SECRET": secrets.token_hex(32),
        "MES_CALLBACK_API_KEY": secrets.token_hex(24),
        "MES_HMAC_SECRET": secrets.token_hex(32),
        "CUSTOMER_CHAT_TOKEN_SECRET": secrets.token_hex(32),
        "CUSTOMER_CHAT_SESSION_TTL_SECONDS": "7200",
        "CUSTOMER_CHAT_LOGIN_MAX_ATTEMPTS": "5",
        "CUSTOMER_CHAT_LOGIN_WINDOW_SECONDS": "900",
        "CUSTOMER_CHAT_ACCOUNTS_JSON": account_json,
        "CUSTOMER_PORTAL_PUBLIC_URL": "https://stockcheck.net/customer-chat",
        "CUSTOMER_SMTP_FROM_NAME": "Stock Check",
    }

    TARGET_ENV.parent.mkdir(parents=True, exist_ok=True)
    temp_path = TARGET_ENV.parent / ".env.new"
    content_lines = []
    for key, value in values.items():
        if key == "CUSTOMER_CHAT_ACCOUNTS_JSON":
            content_lines.append(f"{key}='{value}'")
        else:
            content_lines.append(f"{key}={value}")
    temp_path.write_text("\n".join(content_lines) + "\n", encoding="utf-8")
    temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temp_path.replace(TARGET_ENV)
    print(f"Created {TARGET_ENV} with mode 0600")


if __name__ == "__main__":
    main()

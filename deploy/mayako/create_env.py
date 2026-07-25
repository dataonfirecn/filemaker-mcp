"""Create the Mayako production env file without printing any secret values."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
from pathlib import Path


SOURCE_ENV = Path("/opt/starrc-filemaker/.env")
TARGET_ENV = Path("/opt/starrc-mayako/.env")
MAYAKO_SHIPMENT_COMPANY_ID = "0E254109-8698-4F5D-BE70-ABFD2B929CE9"
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
    encoded_hash = os.environ.get("MAYAKO_PASSWORD_HASH_B64", "")
    if not encoded_hash:
        raise SystemExit("MAYAKO_PASSWORD_HASH_B64 is required")
    password_hash = base64.b64decode(encoded_hash).decode("utf-8")
    if not password_hash.startswith("pbkdf2_sha256$600000$"):
        raise SystemExit("Invalid Mayako password hash")

    source = _read_env(SOURCE_ENV)
    missing = [key for key in REQUIRED_FILEMAKER_KEYS if not source.get(key)]
    if missing:
        raise SystemExit(f"Missing FileMaker settings: {', '.join(missing)}")

    account_json = json.dumps(
        [
            {
                "username": "mayako",
                "displayName": "Mayako",
                "clientName": "Mayako",
                "productPrivilege": "0780",
                "partCustomerId": "CU638",
                "shipmentCompanyId": MAYAKO_SHIPMENT_COMPANY_ID,
                "canViewPrice": True,
                "isAdmin": True,
                "passwordHash": password_hash,
            }
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    values = {
        "MAYAKO_BACKEND_IMAGE": "starrc-mayako-backend:20260717-18002",
        "MAYAKO_FRONTEND_IMAGE": "starrc-mayako-frontend:20260717-18002",
        "MAYAKO_POSTGRES_PASSWORD": secrets.token_hex(24),
        **{key: source[key] for key in REQUIRED_FILEMAKER_KEYS},
        "WEBVIEWER_CONTEXT_SECRET": secrets.token_hex(32),
        "MES_CALLBACK_API_KEY": secrets.token_hex(24),
        "MES_HMAC_SECRET": secrets.token_hex(32),
        "CUSTOMER_CHAT_TOKEN_SECRET": secrets.token_hex(32),
        "CUSTOMER_CHAT_SESSION_TTL_SECONDS": "7200",
        "CUSTOMER_CHAT_LOGIN_MAX_ATTEMPTS": "5",
        "CUSTOMER_CHAT_LOGIN_WINDOW_SECONDS": "900",
        "CUSTOMER_CHAT_ACCOUNTS_JSON": account_json,
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

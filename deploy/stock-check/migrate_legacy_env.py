"""Migrate a legacy Mayako deployment env to Stock Check without printing secrets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


RENAMED_KEYS = {
    "MAYAKO_POSTGRES_PASSWORD": "STOCK_CHECK_POSTGRES_PASSWORD",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--postgres-volume", required=True)
    parser.add_argument("--backend-volume", required=True)
    parser.add_argument("--postgres-db", default="starrc_mayako")
    parser.add_argument("--postgres-user", default="starrc_mayako")
    args = parser.parse_args()

    if args.target.exists():
        raise SystemExit(f"Refusing to overwrite existing {args.target}")

    output: list[str] = []
    seen: set[str] = set()
    for raw_line in args.source.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue
        key, value = raw_line.split("=", 1)
        key = RENAMED_KEYS.get(key.strip(), key.strip())
        if key in {"MAYAKO_BACKEND_IMAGE", "MAYAKO_FRONTEND_IMAGE"}:
            continue
        if key == "CUSTOMER_PORTAL_PUBLIC_URL":
            value = "https://stockcheck.net/customer-chat"
        elif key == "CUSTOMER_SMTP_FROM_NAME":
            value = "Stock Check"
        output.append(f"{key}={value}")
        seen.add(key)

    required = {
        "STOCK_CHECK_BACKEND_IMAGE": args.backend_image,
        "STOCK_CHECK_FRONTEND_IMAGE": args.frontend_image,
        "STOCK_CHECK_POSTGRES_DB": args.postgres_db,
        "STOCK_CHECK_POSTGRES_USER": args.postgres_user,
        "STOCK_CHECK_POSTGRES_VOLUME": args.postgres_volume,
        "STOCK_CHECK_BACKEND_VOLUME": args.backend_volume,
    }
    for key, value in required.items():
        if key not in seen:
            output.append(f"{key}={value}")

    args.target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = args.target.with_name(f"{args.target.name}.new")
    temp_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, args.target)
    print(f"Created {args.target} with mode 0600")


if __name__ == "__main__":
    main()

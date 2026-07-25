"""Update non-secret Mayako deployment settings without printing the env file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--product-privilege", required=True)
    parser.add_argument("--part-customer-id", required=True)
    parser.add_argument("--shipment-company-id", required=True)
    parser.add_argument(
        "--can-view-price",
        choices=("true", "false"),
        required=True,
    )
    parser.add_argument(
        "--is-admin",
        choices=("true", "false"),
        required=True,
    )
    args = parser.parse_args()

    lines = args.env.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    account_found = False
    for line in lines:
        if line.startswith("MAYAKO_BACKEND_IMAGE="):
            line = f"MAYAKO_BACKEND_IMAGE={args.backend_image}"
        elif line.startswith("MAYAKO_FRONTEND_IMAGE="):
            line = f"MAYAKO_FRONTEND_IMAGE={args.frontend_image}"
        elif line.startswith("CUSTOMER_CHAT_ACCOUNTS_JSON="):
            raw = line.split("=", 1)[1].strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
                raw = raw[1:-1]
            accounts = json.loads(raw)
            for account in accounts:
                if str(account.get("username", "")).casefold() == args.username.casefold():
                    account["displayName"] = args.display_name
                    account["productPrivilege"] = args.product_privilege
                    account["partCustomerId"] = args.part_customer_id
                    account["shipmentCompanyId"] = args.shipment_company_id
                    account["canViewPrice"] = args.can_view_price == "true"
                    account["isAdmin"] = args.is_admin == "true"
                    account_found = True
            encoded = json.dumps(accounts, ensure_ascii=False, separators=(",", ":"))
            line = f"CUSTOMER_CHAT_ACCOUNTS_JSON='{encoded}'"
        output.append(line)

    if not account_found:
        raise SystemExit(f"Account not found: {args.username}")

    temp_path = args.env.with_name(f"{args.env.name}.updated")
    temp_path.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, args.env)


if __name__ == "__main__":
    main()

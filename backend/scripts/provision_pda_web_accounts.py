"""Provision the numbered PDA employee accounts in the StarRC web database.

Passwords are generated once and printed to stdout as CSV. The database stores
only PBKDF2 hashes. Existing accounts that already have a password are skipped
unless --reset-existing-passwords is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import secrets
import string
import sys

from app.core.config import get_settings
from app.services.customer_chat_auth import hash_customer_password
from app.services.webviewer_account_access import (
    WebViewerAccountAccessStore,
    load_privilege_set_policies,
)


ACCOUNT_GROUPS = {
    "品檢員": ("301", "302", "303", "304", "305", "306", "307", "308", "309", "328"),
    "包裝員": ("501", "502", "503", "504", "505", "506", "507", "508", "509", "510", "528"),
}
PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _password(username: str) -> str:
    random_suffix = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(8))
    return f"Pda!{username}{random_suffix}"


async def provision(*, reset_existing_passwords: bool) -> list[tuple[str, str, str]]:
    settings = get_settings()
    store = WebViewerAccountAccessStore(settings.audit_database_url)
    await store.init(
        seed_privilege_sets=load_privilege_set_policies(
            settings.webviewer_privilege_set_policy_path
        )
    )
    credentials: list[tuple[str, str, str]] = []
    try:
        for role, usernames in ACCOUNT_GROUPS.items():
            for username in usernames:
                existing = await store.get_account(username)
                account = await store.register_account(
                    username=username,
                    display_name=f"{role} {username}",
                    privilege_set=role,
                    origin="admin",
                    seen=False,
                    updated_by="pda-account-provisioner",
                )
                account = await store.update_account(
                    username,
                    enabled=True,
                    mobile_only=True,
                    permissions=account["permissions"],
                    part_permissions=account["partPermissions"],
                    inherit_privilege_set=True,
                    inherit_part_permissions=True,
                    display_name=f"{role} {username}",
                    privilege_set=role,
                    updated_by="pda-account-provisioner",
                )
                if not account:
                    raise RuntimeError(f"Unable to configure account {username}")
                if existing and existing["hasPassword"] and not reset_existing_passwords:
                    continue
                password = _password(username)
                account = await store.set_password_hash(
                    username,
                    hash_customer_password(password),
                    updated_by="pda-account-provisioner",
                )
                if not account:
                    raise RuntimeError(f"Unable to save password for account {username}")
                credentials.append((role, username, password))
    finally:
        await store.close()
    return credentials


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset-existing-passwords",
        action="store_true",
        help="replace passwords for accounts that already have one",
    )
    args = parser.parse_args()
    credentials = asyncio.run(
        provision(reset_existing_passwords=args.reset_existing_passwords)
    )
    writer = csv.writer(sys.stdout)
    writer.writerow(("role", "username", "initial_password"))
    writer.writerows(credentials)


if __name__ == "__main__":
    main()

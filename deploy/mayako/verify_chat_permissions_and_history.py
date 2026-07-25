"""Verify price authorization, administrator access, and PostgreSQL-backed history."""

from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


def main() -> None:
    settings = Settings()
    accounts = load_customer_accounts(settings)
    admin_account = next(account for account in accounts.values() if account.is_admin)
    restricted_account = next(account for account in accounts.values() if not account.can_view_price)
    admin_token, _ = issue_customer_token(admin_account, settings)
    restricted_token, _ = issue_customer_token(restricted_account, settings)
    cases: list[dict[str, object]] = []

    def check(case_id: str, passed: bool, actual: object) -> None:
        cases.append({"id": case_id, "passed": bool(passed), "actual": actual})

    with httpx.Client(base_url="http://frontend", timeout=120) as client:
        admin_headers = {
            "Authorization": f"Bearer {admin_token}",
            "Accept": "application/json",
            "X-QA-Test": "true",
        }
        restricted_headers = {
            "Authorization": f"Bearer {restricted_token}",
            "Accept": "application/json",
            "X-QA-Test": "true",
        }

        admin_profile_response = client.get("/api/customer-chat/me", headers=admin_headers)
        admin_profile = admin_profile_response.json()
        check(
            "A01-admin-profile",
            admin_profile_response.status_code == 200 and admin_profile.get("isAdmin") is True,
            admin_profile,
        )

        authorized_price_response = client.post(
            "/api/customer-chat/query",
            headers=admin_headers,
            json={"prompt": "What is the unit price for MYB0196?", "page": 1, "pageSize": 5},
        )
        authorized_price = authorized_price_response.json()
        first_price_row = (authorized_price.get("rows") or [{}])[0]
        check(
            "A02-authorized-price",
            authorized_price_response.status_code == 200
            and first_price_row.get("productSku") == "MYB0196"
            and first_price_row.get("price") not in {None, ""},
            {
                "status": authorized_price_response.status_code,
                "answer": authorized_price.get("answer"),
                "price": first_price_row.get("price"),
                "historyId": authorized_price.get("historyId"),
            },
        )

        restricted_price_response = client.post(
            "/api/customer-chat/query",
            headers=restricted_headers,
            json={"prompt": "What is the unit price for MYB0196?", "page": 1, "pageSize": 5},
        )
        restricted_price = restricted_price_response.json()
        restricted_detail = restricted_price.get("detail") or {}
        check(
            "A03-restricted-price",
            restricted_price_response.status_code == 403
            and restricted_detail.get("code") == "price_permission"
            and "does not have permission" in restricted_detail.get("message", ""),
            {"status": restricted_price_response.status_code, "detail": restricted_detail},
        )

        restricted_inventory_response = client.post(
            "/api/customer-chat/query",
            headers=restricted_headers,
            json={"prompt": "Check inventory for MYB0196", "page": 1, "pageSize": 5},
        )
        restricted_inventory = restricted_inventory_response.json()
        restricted_rows = restricted_inventory.get("rows") or []
        check(
            "A04-no-price-leak",
            restricted_inventory_response.status_code == 200
            and restricted_rows
            and all("price" not in row for row in restricted_rows),
            {
                "status": restricted_inventory_response.status_code,
                "rowKeys": sorted(restricted_rows[0]) if restricted_rows else [],
            },
        )

        denied_history_response = client.get(
            "/api/customer-chat/admin/history?includeTests=true",
            headers=restricted_headers,
        )
        denied_history = denied_history_response.json()
        check(
            "A05-non-admin-denied",
            denied_history_response.status_code == 403,
            {"status": denied_history_response.status_code, "detail": denied_history.get("detail")},
        )

        history_response = client.get(
            "/api/customer-chat/admin/history?includeTests=true&page=1&pageSize=200",
            headers=admin_headers,
        )
        history = history_response.json()
        history_rows = history.get("rows") or []
        check(
            "A06-admin-history",
            history_response.status_code == 200
            and any(row.get("blockedReason") == "price_permission" for row in history_rows)
            and any(row.get("historyId", row.get("id")) == authorized_price.get("historyId") for row in history_rows),
            {
                "status": history_response.status_code,
                "foundCount": history.get("foundCount"),
                "returnedCount": history.get("returnedCount"),
            },
        )

        summary_response = client.get(
            "/api/customer-chat/admin/question-summary?includeTests=true&days=1&limit=200",
            headers=admin_headers,
        )
        summary = summary_response.json()
        questions = summary.get("questions") or []
        check(
            "A07-question-summary",
            summary_response.status_code == 200
            and any(item.get("intent") == "price" for item in questions),
            {"status": summary_response.status_code, "questionGroups": len(questions)},
        )

        page_response = client.get("/customer-chat/admin/analytics")
        check(
            "A08-admin-page-route",
            page_response.status_code == 200 and 'id="root"' in page_response.text,
            {"status": page_response.status_code, "contentType": page_response.headers.get("content-type")},
        )

        accounts_response = client.get(
            "/api/customer-chat/admin/accounts",
            headers=admin_headers,
        )
        accounts_payload = accounts_response.json()
        account_rows = accounts_payload.get("accounts") or []
        admin_row = next((row for row in account_rows if row.get("username") == admin_account.username), {})
        restricted_row = next((row for row in account_rows if row.get("username") == restricted_account.username), {})
        check(
            "A09-admin-account-list",
            accounts_response.status_code == 200
            and admin_row.get("enabled") is True
            and admin_row.get("isAdmin") is True
            and admin_row.get("lastSuccessfulLoginAt")
            and admin_row.get("successfulLoginCount", 0) > 0
            and restricted_row.get("canViewPrice") is False,
            {
                "status": accounts_response.status_code,
                "accountCount": len(account_rows),
                "admin": admin_row.get("username"),
                "adminLastSuccessfulLoginAt": admin_row.get("lastSuccessfulLoginAt"),
                "adminSuccessfulLoginCount": admin_row.get("successfulLoginCount"),
                "restricted": restricted_row.get("username"),
            },
        )

        denied_accounts_response = client.get(
            "/api/customer-chat/admin/accounts",
            headers=restricted_headers,
        )
        check(
            "A10-non-admin-account-list-denied",
            denied_accounts_response.status_code == 403,
            {"status": denied_accounts_response.status_code},
        )

        update_response = client.patch(
            f"/api/customer-chat/admin/accounts/{restricted_account.username}",
            headers=admin_headers,
            json={
                "displayName": restricted_row.get("displayName")
                or restricted_account.display_name,
                "enabled": True,
                "accessRole": restricted_row.get("accessRole")
                or restricted_account.access_role,
            },
        )
        updated_account = update_response.json()
        check(
            "A11-account-update",
            update_response.status_code == 200
            and updated_account.get("enabled") is True
            and updated_account.get("accessRole") == restricted_account.access_role
            and updated_account.get("canViewPrice") is False,
            {
                "status": update_response.status_code,
                "username": updated_account.get("username"),
                "enabled": updated_account.get("enabled"),
                "accessRole": updated_account.get("accessRole"),
                "canViewPrice": updated_account.get("canViewPrice"),
            },
        )

        accounts_page_response = client.get("/customer-chat/admin/accounts")
        check(
            "A12-account-page-route",
            accounts_page_response.status_code == 200 and 'id="root"' in accounts_page_response.text,
            {"status": accounts_page_response.status_code},
        )

    print(json.dumps({
        "metadata": {
            "suite": "Mayako price permissions and PostgreSQL history",
            "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "adminAccount": admin_account.username,
            "restrictedAccount": restricted_account.username,
            "tokensIncluded": False,
        },
        "summary": {
            "total": len(cases),
            "passed": sum(1 for case in cases if case["passed"]),
            "failed": sum(1 for case in cases if not case["passed"]),
        },
        "cases": cases,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

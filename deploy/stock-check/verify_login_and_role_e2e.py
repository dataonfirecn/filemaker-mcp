"""Exercise real login, agent permissions, chat, and cleanup in production."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import secrets

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


def main() -> None:
    settings = Settings()
    accounts = load_customer_accounts(settings)
    admin = next(item for item in accounts.values() if item.is_admin)
    admin_token, _ = issue_customer_token(admin, settings)
    username = f"qa.stock-check.{int(datetime.now(timezone.utc).timestamp())}"
    password = f"Qa!{secrets.token_urlsafe(18)}"
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    results: list[dict[str, object]] = []
    created = False

    def check(name: str, passed: bool, actual: object) -> None:
        results.append({"name": name, "passed": bool(passed), "actual": actual})

    with httpx.Client(base_url="http://frontend", timeout=120) as client:
        try:
            config = client.get("/api/customer-chat/admin/config", headers=admin_headers)
            check("admin_config", config.status_code == 200, config.status_code)

            create = client.post(
                "/api/customer-chat/admin/accounts",
                headers=admin_headers,
                json={
                    "username": username,
                    "displayName": "Stock Check QA Agent",
                    "companyName": "Mayako",
                    "email": "stock-check-qa@example.invalid",
                    "password": password,
                    "enabled": True,
                    "sendCredentials": False,
                    "accessRole": "agent",
                    "canViewPrice": False,
                },
            )
            check("account_create", create.status_code == 201, create.status_code)
            create.raise_for_status()
            created = True

            login = client.post(
                "/api/customer-chat/login",
                json={"username": username, "password": password},
            )
            check("real_password_login", login.status_code == 200, login.status_code)
            login.raise_for_status()
            token = login.json()["token"]
            agent_headers = {
                "Authorization": f"Bearer {token}",
                "X-QA-Test": "true",
            }

            profile = client.get("/api/customer-chat/me", headers=agent_headers)
            profile_payload = profile.json()
            check(
                "agent_profile",
                profile.status_code == 200
                and profile_payload.get("companyName") == "Mayako"
                and profile_payload.get("accessRole") == "agent"
                and profile_payload.get("canViewOrders") is False
                and profile_payload.get("canViewDetails") is False
                and profile_payload.get("canViewPrice") is False,
                {
                    key: profile_payload.get(key)
                    for key in (
                        "companyName",
                        "accessRole",
                        "canViewOrders",
                        "canViewDetails",
                        "canViewPrice",
                    )
                },
            )

            product = client.post(
                "/api/customer-chat/query",
                headers=agent_headers,
                json={"prompt": "Check inventory for MYB0377-24", "page": 1, "pageSize": 5},
            )
            product_payload = product.json()
            first_product = (product_payload.get("rows") or [{}])[0]
            check(
                "agent_product_chat",
                product.status_code == 200
                and product_payload.get("resultType") == "product"
                and first_product.get("productSku") == "MYB0377-24"
                and "price" not in first_product,
                {
                    "status": product.status_code,
                    "resultType": product_payload.get("resultType"),
                    "productSku": first_product.get("productSku"),
                    "priceReturned": "price" in first_product,
                },
            )

            order = client.post(
                "/api/customer-chat/query",
                headers=agent_headers,
                json={"prompt": "View orders", "page": 1, "pageSize": 5},
            )
            check("agent_order_blocked", order.status_code == 403, order.status_code)

            admin_denied = client.get(
                "/api/customer-chat/admin/accounts",
                headers=agent_headers,
            )
            check("agent_admin_blocked", admin_denied.status_code == 403, admin_denied.status_code)

            internal_denied = client.get("/api/filemaker/layouts", headers=agent_headers)
            check("internal_api_hidden", internal_denied.status_code == 404, internal_denied.status_code)
        finally:
            if created:
                deleted = client.delete(
                    f"/api/customer-chat/admin/accounts/{username}",
                    headers=admin_headers,
                )
                check("account_cleanup", deleted.status_code == 204, deleted.status_code)
                deleted.raise_for_status()
                relogin = client.post(
                    "/api/customer-chat/login",
                    json={"username": username, "password": password},
                )
                check("deleted_login_blocked", relogin.status_code == 401, relogin.status_code)

    summary = {
        "total": len(results),
        "passed": sum(bool(item["passed"]) for item in results),
        "failed": sum(not bool(item["passed"]) for item in results),
    }
    print(json.dumps({"summary": summary, "checks": results}, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

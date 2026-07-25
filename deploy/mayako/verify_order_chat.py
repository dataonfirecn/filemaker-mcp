"""Verify Mayako order conversation queries from inside the deployed stack."""

from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


EXPECTED_ORDER_FIELDS = {
    "entityType",
    "orderRef",
    "clientName",
    "orderNumber",
    "orderAmount",
    "shippingCompany",
    "trackingNumber",
    "shippingCost",
    "shippedDate",
    "shippingStatus",
    "remarks",
}


def main() -> None:
    settings = Settings()
    account = load_customer_accounts(settings)["mayako"]
    token, _ = issue_customer_token(account, settings)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    checks = [
        ("shippedRange", "查询 2026-07-01 到 2026-07-22 的出库单", 200, None),
        ("orderRange", "查询订单日期 2026-07-01 到 2026-07-22", 200, None),
        ("readyRange", "查询备好日期 2026-07-01 到 2026-07-22 的出货单", 200, None),
        ("completedRange", "查询完成日期 2026-07-01 到 2026-07-22 的出货单", 200, None),
        ("signatureRange", "查询签名日期 2026-07-01 到 2026-07-22 的出货单", 200, None),
        ("updatedRange", "查询更新日期 2026-07-01 到 2026-07-22 的出货单", 200, None),
        ("unshipped", "查询未出货的出库单", 200, None),
        ("tracking", "tracking 910038198088", 200, None),
        ("legacyPoNote", "查询出货单 703-100001126", 200, None),
        ("paymentRange", "查询收款日期 2026-07-01 到 2026-07-22 的出库单", 200, 0),
    ]
    output: dict[str, object] = {}

    with httpx.Client(base_url="http://frontend", headers=headers, timeout=90) as client:
        health = client.get("/healthz")
        health.raise_for_status()
        for name, prompt, expected_status, expected_count in checks:
            response = client.post(
                "/api/customer-chat/query",
                json={"prompt": prompt, "page": 1, "pageSize": 4},
            )
            assert response.status_code == expected_status, response.text
            payload = response.json()
            if expected_status != 200:
                output[name] = {"status": response.status_code}
                continue
            assert payload["resultType"] == "order"
            if expected_count is not None:
                assert payload["foundCount"] == expected_count, payload
            assert all(set(row) == EXPECTED_ORDER_FIELDS for row in payload["rows"])
            assert all(row["orderNumber"] for row in payload["rows"])
            assert all(
                not row["orderNumber"].upper().startswith("PI")
                for row in payload["rows"]
            )
            if name == "unshipped":
                assert all(
                    row["shippingStatus"] in {"未出貨", "Not Shipped"}
                    for row in payload["rows"]
                )
            output[name] = {
                "status": response.status_code,
                "foundCount": payload["foundCount"],
                "returnedCount": payload["returnedCount"],
                **(
                    {"orderNumber": payload["rows"][0]["orderNumber"]}
                    if name == "tracking" and payload["rows"]
                    else {}
                ),
            }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

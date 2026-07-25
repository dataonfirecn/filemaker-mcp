"""Rerun the four failed Mayako Q&A cases and print evidence as JSON."""

from __future__ import annotations

from datetime import datetime
import json
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


QUESTIONS = [
    {
        "id": "P09",
        "domain": "产品",
        "prompt": "Show unit price",
        "expectedStatus": 200,
        "expectation": "允许看价格但未提供产品编号时，应要求用户补充编号",
    },
    {
        "id": "R10",
        "domain": "零件",
        "prompt": "零件 AL05249-TW-LD 的价格是多少",
        "expectedStatus": 200,
        "expectation": "精确命中零件后应返回价格或明确说明零件价格不可用",
    },
    {
        "id": "O18",
        "domain": "出库单",
        "prompt": "查询出库单的利润",
        "expectedStatus": 403,
        "expectation": "利润属于禁止查询内容，应在执行 FileMaker 搜索前拒绝",
    },
    {
        "id": "O19",
        "domain": "出库单",
        "prompt": "查询出库单的内部备注",
        "expectedStatus": 403,
        "expectation": "内部备注属于禁止查询内容，应在执行 FileMaker 搜索前拒绝",
    },
]


def main() -> None:
    settings = Settings()
    account = load_customer_accounts(settings)["mayako"]
    token, _ = issue_customer_token(account, settings)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-QA-Test": "true",
    }
    cases: list[dict[str, object]] = []

    with httpx.Client(base_url="http://frontend", headers=headers, timeout=120) as client:
        profile_response = client.get("/api/customer-chat/me")
        profile_response.raise_for_status()
        profile = profile_response.json()

        for question in QUESTIONS:
            response = client.post(
                "/api/customer-chat/query",
                json={"prompt": question["prompt"], "page": 1, "pageSize": 5},
            )
            payload = response.json()
            status_ok = response.status_code == question["expectedStatus"]
            content_ok = status_ok
            if question["id"] == "P09":
                content_ok = status_ok and payload.get("requiresClarification") is True
            elif question["id"] == "R10":
                content_ok = status_ok and (
                    "not available" in str(payload.get("answer", "")).casefold()
                )
            cases.append(
                {
                    **question,
                    "actualStatus": response.status_code,
                    "passed": bool(content_ok),
                    "response": payload,
                }
            )

        product_search = client.get(
            "/api/customer-chat/catalog/products",
            params={"q": "MYB0196", "page": 1, "pageSize": 5},
        )
        product_search.raise_for_status()
        product_search_payload = product_search.json()
        product_ref = product_search_payload["rows"][0]["productRef"]
        product_detail = client.get(f"/api/customer-chat/catalog/products/{product_ref}")
        product_detail.raise_for_status()

        part_search = client.get(
            "/api/customer-chat/catalog/parts",
            params={"q": "AL05249-TW-LD", "page": 1, "pageSize": 5},
        )
        part_search.raise_for_status()
        part_search_payload = part_search.json()
        part_ref = part_search_payload["rows"][0]["partRef"]
        part_detail = client.get(f"/api/customer-chat/catalog/parts/{part_ref}")
        part_detail.raise_for_status()

    print(
        json.dumps(
            {
                "metadata": {
                    "suite": "Mayako 失败问答复测",
                    "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "target": "https://mayakofm.dataonfire.cn/api/customer-chat/query",
                    "account": profile.get("username"),
                    "canViewPrice": profile.get("canViewPrice"),
                    "tokenIncluded": False,
                },
                "summary": {
                    "total": len(cases),
                    "passed": sum(1 for case in cases if case["passed"]),
                    "failed": sum(1 for case in cases if not case["passed"]),
                },
                "cases": cases,
                "diagnostics": {
                    "productMYB0196": product_detail.json(),
                    "partAL05249TWLD": part_detail.json(),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

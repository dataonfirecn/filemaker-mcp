"""Run detailed live Q&A checks for Stock Check products, parts, and orders.

This script is intended to run inside the deployed backend container.  It issues
an account-scoped short-lived token without reading or printing the customer's
password, then sends requests through the production frontend just like the
portal does.  The JSON output deliberately excludes the token.
"""

from __future__ import annotations

from datetime import datetime
from math import ceil
import json
import re
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


PRODUCT_ROW_FIELDS = {
    "entityType",
    "productRef",
    "productSku",
    "productName",
    "modelName",
    "scale",
    "category",
    "stock",
    "hasImage",
}
ORDER_ROW_FIELDS = {
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
BLOCKED_KEY_FRAGMENTS = (
    "costprice",
    "quotation",
    "supplier",
    "vendor",
    "productnamecn",
    "margin",
    "profit",
)
QA_PAGE_SIZE = 5


def _contains_cjk_or_japanese(value: object) -> bool:
    return bool(
        re.search(
            r"[\u3040-\u30ff\u3400-\u9fff]",
            json.dumps(value, ensure_ascii=False),
        )
    )


def _leaf_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_leaf_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_leaf_keys(child))
    return keys


def _check(name: str, passed: bool, detail: str) -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _value_at(payload: object, *path: object) -> object:
    current = payload
    for item in path:
        if isinstance(item, int) and isinstance(current, list) and len(current) > item:
            current = current[item]
        elif isinstance(item, str) and isinstance(current, dict) and item in current:
            current = current[item]
        else:
            return None
    return current


class Runner:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.cases: list[dict[str, object]] = []
        self.responses: dict[str, dict[str, Any]] = {}

    def query(
        self,
        *,
        case_id: str,
        domain: str,
        title: str,
        prompt: str,
        expected_status: int = 200,
        expected_type: str | None = None,
        page: int = 1,
        page_size: int = QA_PAGE_SIZE,
        extra: Callable[[dict[str, Any]], list[dict[str, object]]] | None = None,
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/customer-chat/query",
            json={"prompt": prompt, "page": page, "pageSize": page_size},
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"rawText": response.text}

        checks = [
            _check(
                "HTTP 状态",
                response.status_code == expected_status,
                f"expected={expected_status}, actual={response.status_code}",
            )
        ]
        if response.status_code == 200 and isinstance(payload, dict):
            rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            found_count = payload.get("foundCount")
            returned_count = payload.get("returnedCount")
            total_pages = payload.get("totalPages")
            result_type = payload.get("resultType")
            expected_fields = ORDER_ROW_FIELDS if result_type == "order" else PRODUCT_ROW_FIELDS
            checks.extend(
                [
                    _check(
                        "结果类型",
                        expected_type is None or result_type == expected_type,
                        f"expected={expected_type}, actual={result_type}",
                    ),
                    _check(
                        "计数一致",
                        isinstance(found_count, int)
                        and isinstance(returned_count, int)
                        and returned_count == len(rows)
                        and found_count >= returned_count,
                        f"found={found_count}, returned={returned_count}, rows={len(rows)}",
                    ),
                    _check(
                        "分页一致",
                        isinstance(found_count, int)
                        and total_pages == max(1, ceil(found_count / page_size))
                        and payload.get("page") == page
                        and payload.get("pageSize") == page_size
                        and payload.get("hasPrevious") == (page > 1)
                        and payload.get("hasNext") == (page < total_pages),
                        (
                            f"page={payload.get('page')}, pageSize={payload.get('pageSize')}, "
                            f"totalPages={total_pages}, hasPrevious={payload.get('hasPrevious')}, "
                            f"hasNext={payload.get('hasNext')}"
                        ),
                    ),
                    _check(
                        "回答与数量一致",
                        (
                            isinstance(found_count, int)
                            and (
                                (payload.get("requiresClarification") is True)
                                or (found_count == 0 and str(payload.get("answer", "")).startswith("No matching"))
                                or (found_count > 0 and (
                                    str(found_count) in str(payload.get("answer", ""))
                                    or "not available" in str(payload.get("answer", "")).casefold()
                                ))
                            )
                        ),
                        str(payload.get("answer", "")),
                    ),
                    _check(
                        "公开字段白名单",
                        all(
                            frozenset(row) in {frozenset(expected_fields), frozenset(expected_fields | {"price"})}
                            for row in rows if isinstance(row, dict)
                        ),
                        f"expectedFields={sorted(expected_fields)}; optionalAuthorizedField=price",
                    ),
                    _check(
                        "行实体类型一致",
                        all(row.get("entityType") == result_type for row in rows if isinstance(row, dict)),
                        f"resultType={result_type}",
                    ),
                    _check(
                        "无隐藏字段键",
                        not any(
                            fragment in key.casefold()
                            for key in _leaf_keys(rows)
                            for fragment in BLOCKED_KEY_FRAGMENTS
                        ),
                        f"keys={sorted(_leaf_keys(rows))}",
                    ),
                ]
            )
            if result_type in {"product", "part"}:
                checks.extend(
                    [
                        _check(
                            "客户回答为英文",
                            str(payload.get("answer", "")).isascii(),
                            str(payload.get("answer", "")),
                        ),
                        _check(
                            "产品/零件行无中日文残留",
                            not _contains_cjk_or_japanese(rows),
                            "customer-visible product/part rows should be English-only",
                        ),
                    ]
                )
        if extra is not None and isinstance(payload, dict):
            try:
                checks.extend(extra(payload))
            except Exception as exc:  # Keep the full suite running and record the evaluator problem.
                checks.append(_check("附加断言执行", False, f"{type(exc).__name__}: {exc}"))

        passed = all(bool(item["passed"]) for item in checks)
        item = {
            "id": case_id,
            "domain": domain,
            "title": title,
            "prompt": prompt,
            "request": {"page": page, "pageSize": page_size},
            "expectedStatus": expected_status,
            "actualStatus": response.status_code,
            "passed": passed,
            "checks": checks,
            "response": payload,
        }
        self.cases.append(item)
        if isinstance(payload, dict):
            self.responses[case_id] = payload
        return payload if isinstance(payload, dict) else {}


def main() -> None:
    settings = Settings()
    accounts = load_customer_accounts(settings)
    account = next((item for item in accounts.values() if item.is_admin), next(iter(accounts.values())))
    token, _ = issue_customer_token(account, settings)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-QA-Test": "true",
    }

    with httpx.Client(base_url="http://frontend", headers=headers, timeout=120) as client:
        health = client.get("/healthz")
        profile_response = client.get("/api/customer-chat/me")
        product_catalog_response = client.get(
            "/api/customer-chat/catalog/products",
            params={"page": 1, "pageSize": 10, "sortBy": "productSku", "sortOrder": "asc"},
        )
        part_catalog_response = client.get(
            "/api/customer-chat/catalog/parts",
            params={"page": 1, "pageSize": 10, "sortBy": "partNumber", "sortOrder": "asc"},
        )
        order_catalog_response = client.get(
            "/api/customer-chat/catalog/orders",
            params={"page": 1, "pageSize": 10, "sortBy": "orderNumber", "sortOrder": "desc"},
        )
        for response in (
            health,
            profile_response,
            product_catalog_response,
            part_catalog_response,
            order_catalog_response,
        ):
            response.raise_for_status()

        profile = profile_response.json()
        product_catalog = product_catalog_response.json()
        part_catalog = part_catalog_response.json()
        order_catalog = order_catalog_response.json()
        product_count = product_catalog["foundCount"]
        part_count = part_catalog["foundCount"]
        order_count = order_catalog["foundCount"]
        sample_tracking_number = next(
            (
                str(row.get("trackingNumber") or "").strip()
                for row in order_catalog.get("rows", [])
                if str(row.get("trackingNumber") or "").strip()
            ),
            "",
        )
        runner = Runner(client)

        def expect_count(expected: int) -> Callable[[dict[str, Any]], list[dict[str, object]]]:
            return lambda payload: [
                _check(
                    "命中总数",
                    payload.get("foundCount") == expected,
                    f"expected={expected}, actual={payload.get('foundCount')}",
                )
            ]

        def expect_exact_sku(expected: str) -> Callable[[dict[str, Any]], list[dict[str, object]]]:
            return lambda payload: [
                _check(
                    "精确编号命中",
                    payload.get("foundCount") == 1
                    and str(_value_at(payload, "rows", 0, "productSku")).casefold() == expected.casefold(),
                    (
                        f"expected={expected}, found={payload.get('foundCount')}, "
                        f"actual={_value_at(payload, 'rows', 0, 'productSku')}"
                    ),
                )
            ]

        def expect_answer_fragment(fragment: str) -> Callable[[dict[str, Any]], list[dict[str, object]]]:
            return lambda payload: [
                _check(
                    "回答包含预期过滤说明",
                    fragment.casefold() in str(payload.get("answer", "")).casefold(),
                    str(payload.get("answer", "")),
                )
            ]

        # Products
        p01 = runner.query(
            case_id="P01",
            domain="产品",
            title="英文产品清单",
            prompt="View product list",
            expected_type="product",
            extra=expect_count(product_count),
        )
        runner.query(
            case_id="P02",
            domain="产品",
            title="自然英文产品清单",
            prompt="What products do you have?",
            expected_type="product",
            extra=expect_count(product_count),
        )
        runner.query(
            case_id="P03",
            domain="产品",
            title="中文库存清单",
            prompt="查看库存",
            expected_type="product",
            extra=expect_count(product_count),
        )
        runner.query(
            case_id="P04",
            domain="产品",
            title="精确产品库存（英文）",
            prompt="Check inventory for MYB0377-24",
            expected_type="product",
            extra=expect_exact_sku("MYB0377-24"),
        )
        runner.query(
            case_id="P05",
            domain="产品",
            title="精确产品库存（中文）",
            prompt="查询 MYB0196 产品库存",
            expected_type="product",
            extra=expect_exact_sku("MYB0196"),
        )
        runner.query(
            case_id="P06",
            domain="产品",
            title="不存在的产品",
            prompt="查询产品 ZZ-NO-SUCH-SKU-20260723",
            expected_type="product",
            extra=expect_count(0),
        )
        runner.query(
            case_id="P07",
            domain="产品",
            title="产品自然关键词",
            prompt="Find buggy products",
            expected_type="product",
        )
        runner.query(
            case_id="P08",
            domain="产品",
            title="产品第二页",
            prompt="View product list",
            expected_type="product",
            page=2,
            extra=lambda payload: [
                _check(
                    "第二页总数不变",
                    payload.get("foundCount") == product_count,
                    f"expected={product_count}, actual={payload.get('foundCount')}",
                ),
                _check(
                    "与第一页不重复",
                    not (
                        {row.get("productRef") for row in p01.get("rows", [])}
                        & {row.get("productRef") for row in payload.get("rows", [])}
                    ),
                    "page 1 and page 2 productRef sets must be disjoint",
                ),
            ],
        )
        runner.query(
            case_id="P09",
            domain="产品",
            title="未提供产品编号时要求澄清",
            prompt="Show unit price",
            expected_type="product",
            extra=lambda payload: [
                _check(
                    "价格问题要求产品编号",
                    payload.get("requiresClarification") is True,
                    str(payload.get("answer", "")),
                )
            ],
        )
        runner.query(
            case_id="P09B",
            domain="产品",
            title="有权限账号查询精确产品价格",
            prompt="What is the unit price for MYB0196?",
            expected_type="product",
            extra=lambda payload: [
                _check(
                    "价格字段仅按需返回",
                    payload.get("foundCount") == 1
                    and _value_at(payload, "rows", 0, "productSku") == "MYB0196"
                    and _value_at(payload, "rows", 0, "price") not in {None, ""},
                    f"sku={_value_at(payload, 'rows', 0, 'productSku')}, price={_value_at(payload, 'rows', 0, 'price')}",
                )
            ],
        )
        runner.query(
            case_id="P10",
            domain="产品",
            title="产品成本越权拦截",
            prompt="查询产品 MYB0196 的成本",
            expected_status=403,
        )
        runner.query(
            case_id="P11",
            domain="产品",
            title="产品供应商越权拦截",
            prompt="查询产品 MYB0196 的供应商",
            expected_status=403,
        )
        runner.query(
            case_id="P12",
            domain="产品",
            title="无关问题提示",
            prompt="What is the weather today?",
            expected_status=422,
        )
        runner.query(
            case_id="P13",
            domain="产品",
            title="纯问候提示",
            prompt="Hello",
            expected_status=422,
        )

        # Parts
        r01 = runner.query(
            case_id="R01",
            domain="零件",
            title="英文零件清单",
            prompt="View part list",
            expected_type="part",
            extra=expect_count(part_count),
        )
        runner.query(
            case_id="R02",
            domain="零件",
            title="中文零件清单",
            prompt="所有零件",
            expected_type="part",
            extra=expect_count(part_count),
        )
        runner.query(
            case_id="R03",
            domain="零件",
            title="精确零件库存",
            prompt="查询零件 AL05249-TW-LD 的库存",
            expected_type="part",
            extra=expect_exact_sku("AL05249-TW-LD"),
        )
        runner.query(
            case_id="R04",
            domain="零件",
            title="精确零件大小写容错",
            prompt="part al05249-tw-ld inventory",
            expected_type="part",
            extra=expect_exact_sku("AL05249-TW-LD"),
        )
        runner.query(
            case_id="R05",
            domain="零件",
            title="不存在的零件",
            prompt="查询零件 ZZ-NO-SUCH-PART-20260723",
            expected_type="part",
            extra=expect_count(0),
        )
        runner.query(
            case_id="R06",
            domain="零件",
            title="PVC 材质零件",
            prompt="PVC 材质的零件有哪些",
            expected_type="part",
        )
        runner.query(
            case_id="R07",
            domain="零件",
            title="碳纤维零件关键词",
            prompt="有没有碳纤维零件？",
            expected_type="part",
        )
        runner.query(
            case_id="R08",
            domain="零件",
            title="今天新增的零件",
            prompt="今天新增的零件有哪些",
            expected_type="part",
        )
        runner.query(
            case_id="R09",
            domain="零件",
            title="零件第二页",
            prompt="View part list",
            expected_type="part",
            page=2,
            extra=lambda payload: [
                _check(
                    "第二页总数不变",
                    payload.get("foundCount") == part_count,
                    f"expected={part_count}, actual={payload.get('foundCount')}",
                ),
                _check(
                    "与第一页不重复",
                    not (
                        {row.get("productRef") for row in r01.get("rows", [])}
                        & {row.get("productRef") for row in payload.get("rows", [])}
                    ),
                    "page 1 and page 2 part productRef sets must be disjoint",
                ),
            ],
        )
        runner.query(
            case_id="R10",
            domain="零件",
            title="零件价格问答完整性",
            prompt="零件 AL05249-TW-LD 的价格是多少",
            expected_type="part",
            extra=lambda payload: [
                _check(
                    "明确说明零件价格不可用",
                    "not available" in str(payload.get("answer", "")).casefold()
                    and not any("price" in {key.casefold() for key in row} for row in payload.get("rows", [])),
                    str(payload.get("answer", "")),
                )
            ],
        )
        runner.query(
            case_id="R11",
            domain="零件",
            title="零件供应商越权拦截",
            prompt="查询零件 AL05249-TW-LD 的供应商",
            expected_status=403,
        )

        # Orders / shipment records
        o01 = runner.query(
            case_id="O01",
            domain="出库单",
            title="英文出库单清单",
            prompt="View orders",
            expected_type="order",
            extra=expect_count(order_count),
        )
        runner.query(
            case_id="O02",
            domain="出库单",
            title="中文出库单清单",
            prompt="查看所有出库单",
            expected_type="order",
            extra=expect_count(order_count),
        )
        runner.query(
            case_id="O03",
            domain="出库单",
            title="精确追踪号",
            prompt=(
                f"tracking {sample_tracking_number}"
                if sample_tracking_number
                else "tracking ZZ-NO-CURRENT-TRACKING"
            ),
            expected_type="order",
            extra=lambda payload: [
                _check(
                    "追踪号精确命中",
                    (
                        payload.get("foundCount") >= 1
                        and _value_at(payload, "rows", 0, "trackingNumber") == sample_tracking_number
                    )
                    if sample_tracking_number
                    else payload.get("foundCount") == 0,
                    (
                        f"found={payload.get('foundCount')}, "
                        f"expected={sample_tracking_number or 'no current sample'}, "
                        f"tracking={_value_at(payload, 'rows', 0, 'trackingNumber')}"
                    ),
                )
            ],
        )
        o04 = runner.query(
            case_id="O04",
            domain="出库单",
            title="中文未出货状态",
            prompt="查询未出货的出库单",
            expected_type="order",
            extra=lambda payload: [
                _check(
                    "状态只含未出货",
                    bool(payload.get("rows"))
                    and all(
                        row.get("shippingStatus") in {"未出貨", "Not Shipped"}
                        for row in payload.get("rows", [])
                    ),
                    f"statuses={sorted({row.get('shippingStatus') for row in payload.get('rows', [])})}",
                )
            ],
        )
        runner.query(
            case_id="O05",
            domain="出库单",
            title="英文未出货状态",
            prompt="Show unshipped orders",
            expected_type="order",
            extra=lambda payload: [
                _check(
                    "中英文状态总数一致",
                    payload.get("foundCount") == o04.get("foundCount"),
                    f"Chinese={o04.get('foundCount')}, English={payload.get('foundCount')}",
                )
            ],
        )
        runner.query(
            case_id="O06",
            domain="出库单",
            title="出货日期范围",
            prompt="查询 2026-07-01 到 2026-07-22 的出库单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by"),
        )
        runner.query(
            case_id="O07",
            domain="出库单",
            title="订单日期范围",
            prompt="查询订单日期 2026-07-01 到 2026-07-22",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by order date"),
        )
        runner.query(
            case_id="O08",
            domain="出库单",
            title="备好日期范围",
            prompt="查询备好日期 2026-07-01 到 2026-07-22 的出货单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by ready date"),
        )
        runner.query(
            case_id="O09",
            domain="出库单",
            title="完成日期范围",
            prompt="查询完成日期 2026-07-01 到 2026-07-22 的出货单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by completed date"),
        )
        runner.query(
            case_id="O10",
            domain="出库单",
            title="签名日期范围",
            prompt="查询签名日期 2026-07-01 到 2026-07-22 的出货单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by signature date"),
        )
        runner.query(
            case_id="O11",
            domain="出库单",
            title="收款日期空结果",
            prompt="查询收款日期 2026-07-01 到 2026-07-22 的出库单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by payment date"),
        )
        runner.query(
            case_id="O12",
            domain="出库单",
            title="更新日期迁移结果",
            prompt="查询更新日期 2026-07-23 的出库单",
            expected_type="order",
            extra=expect_answer_fragment("Filtered by updated date"),
        )
        runner.query(
            case_id="O13",
            domain="出库单",
            title="反向日期自动纠正",
            prompt="查询 2026-07-22 到 2026-07-01 的出库单",
            expected_type="order",
            extra=expect_answer_fragment("from 2026-07-01 to 2026-07-22"),
        )
        first_order_number = next(
            (
                str(row.get("orderNumber") or "").strip()
                for row in o01.get("rows", [])
                if str(row.get("orderNumber") or "").strip()
            ),
            "",
        )
        runner.query(
            case_id="O14",
            domain="出库单",
            title="动态精确出库单号",
            prompt=f"查询出库单号 {first_order_number}",
            expected_type="order",
            extra=lambda payload: [
                _check(
                    "单号命中",
                    bool(first_order_number)
                    and any(row.get("orderNumber") == first_order_number for row in payload.get("rows", [])),
                    f"expected orderNumber={first_order_number}",
                )
            ],
        )
        runner.query(
            case_id="O15",
            domain="出库单",
            title="按产品查出库单",
            prompt="包含产品 MYTENT33S 的出货单",
            expected_type="order",
        )
        runner.query(
            case_id="O16",
            domain="出库单",
            title="不存在的追踪号",
            prompt="tracking ZZ-NO-SUCH-TRACKING-20260723",
            expected_type="order",
            extra=expect_count(0),
        )
        runner.query(
            case_id="O17",
            domain="出库单",
            title="出库单第二页",
            prompt="View orders",
            expected_type="order",
            page=2,
            extra=lambda payload: [
                _check(
                    "第二页总数不变",
                    payload.get("foundCount") == order_count,
                    f"expected={order_count}, actual={payload.get('foundCount')}",
                ),
                _check(
                    "与第一页不重复",
                    not (
                        {row.get("orderRef") for row in o01.get("rows", [])}
                        & {row.get("orderRef") for row in payload.get("rows", [])}
                    ),
                    "page 1 and page 2 orderRef sets must be disjoint",
                ),
            ],
        )
        runner.query(
            case_id="O18",
            domain="出库单",
            title="出库单利润越权拦截",
            prompt="查询出库单的利润",
            expected_status=403,
        )
        runner.query(
            case_id="O19",
            domain="出库单",
            title="出库单内部备注越权拦截",
            prompt="查询出库单的内部备注",
            expected_status=403,
        )

        summaries: dict[str, dict[str, int]] = {}
        for domain in ("产品", "零件", "出库单"):
            domain_cases = [case for case in runner.cases if case["domain"] == domain]
            passed = sum(1 for case in domain_cases if case["passed"])
            summaries[domain] = {
                "total": len(domain_cases),
                "passed": passed,
                "failed": len(domain_cases) - passed,
            }
        total_passed = sum(1 for case in runner.cases if case["passed"])
        result = {
            "metadata": {
                "suite": "Stock Check 产品 / 零件 / 出库单详细问答测试",
                "generatedAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "target": "https://stockcheck.net/api/customer-chat/query",
                "executionPath": "production frontend -> production backend -> FileMaker",
                "account": profile.get("username"),
                "clientName": profile.get("clientName"),
                "canViewPrice": profile.get("canViewPrice"),
                "tokenIncluded": False,
                "pageSize": QA_PAGE_SIZE,
            },
            "baseline": {
                "health": health.text,
                "productCatalogCount": product_count,
                "partCatalogCount": part_count,
                "orderCatalogCount": order_count,
            },
            "summary": {
                "total": len(runner.cases),
                "passed": total_passed,
                "failed": len(runner.cases) - total_passed,
                "byDomain": summaries,
            },
            "cases": runner.cases,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

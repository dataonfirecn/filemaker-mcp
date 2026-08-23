from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.services.natural_language_query import parse_natural_date_range


PURCHASE_LINE_TABLE = "採購單資料"
PURCHASE_LINE_DATE_FIELD = "下單日期"
PURCHASE_LINE_SELECT_FIELDS = (
    "ID_採購單",
    PURCHASE_LINE_DATE_FIELD,
    "零件編號",
    "零件名稱",
    "數量",
    "廠商名稱",
    "來貨狀況",
    "倉庫已入庫數量",
)

_CJK_PURCHASE_TERMS = ("采购", "採購")
_CJK_PART_TERMS = ("零件", "配件", "备件", "備件")
_PURCHASE_NOISE_TERMS = (
    "采购员",
    "採購員",
    "采购人员",
    "採購人員",
    "采购备注",
    "採購備註",
    "采购概览",
    "採購概覽",
)


@dataclass
class PartPurchaseQueryPlan:
    domain: str = "part"
    intent: str = "find_part_purchase_lines"
    layout: str = PURCHASE_LINE_TABLE
    description: str = "零件采购明细"
    query: list[dict[str, Any]] = field(default_factory=list)
    sort: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"fieldName": PURCHASE_LINE_DATE_FIELD, "sortOrder": "descend"}
        ]
    )
    keywords: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    date_range: dict[str, str] | None = None
    warnings: list[str] = field(default_factory=list)
    filter_expr: str = ""

    @property
    def has_scope(self) -> bool:
        return bool(self.filter_expr)


def build_part_purchase_query_plan(
    prompt: str,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> PartPurchaseQueryPlan | None:
    text = _normalize_text(prompt)
    if not looks_like_part_purchase_query(text):
        return None

    parsed_date = parse_natural_date_range(text, settings=settings, now=now)
    purchase_order_id = _extract_purchase_order_id(text)
    part_number = _extract_part_number(text, purchase_order_id=purchase_order_id)
    vendor = _extract_vendor(text)

    filters: dict[str, str] = {}
    expressions: list[str] = []
    scope_parts: list[str] = []
    date_range: dict[str, str] | None = None

    if parsed_date:
        exclusive_end = parsed_date.end + timedelta(days=1)
        expressions.append(
            f"{PURCHASE_LINE_DATE_FIELD} ge {parsed_date.start.isoformat()} and "
            f"{PURCHASE_LINE_DATE_FIELD} lt {exclusive_end.isoformat()}"
        )
        filters["orderDate"] = parsed_date.label
        scope_parts.append(f"{parsed_date.label}下单")
        date_range = {
            "label": parsed_date.label,
            "start": parsed_date.start.isoformat(),
            "end": parsed_date.end.isoformat(),
            "field": PURCHASE_LINE_DATE_FIELD,
        }

    if part_number:
        expressions.append(f"零件編號 eq '{_escape_odata_string(part_number)}'")
        filters["partNumber"] = part_number
        scope_parts.append(f"零件号 {part_number}")

    if vendor:
        expressions.append(f"contains(廠商名稱,'{_escape_odata_string(vendor)}')")
        filters["vendor"] = vendor
        scope_parts.append(f"供应商包含 {vendor}")

    if purchase_order_id:
        expressions.append(f"ID_採購單 eq '{_escape_odata_string(purchase_order_id)}'")
        filters["purchaseOrderId"] = purchase_order_id
        scope_parts.append(f"采购单号 {purchase_order_id}")

    filter_expr = " and ".join(f"({item})" for item in expressions)
    description = "、".join(scope_parts) if scope_parts else "零件采购明细（范围待确认）"
    keywords = [value for value in (part_number, vendor, purchase_order_id) if value]
    return PartPurchaseQueryPlan(
        description=description,
        query=[{"$filter": filter_expr}] if filter_expr else [],
        keywords=keywords,
        filters=filters,
        date_range=date_range,
        filter_expr=filter_expr,
    )


def looks_like_part_purchase_query(prompt: str) -> bool:
    text = _normalize_text(prompt)
    if not text:
        return False
    lower = text.casefold()
    without_noise = lower
    for term in _PURCHASE_NOISE_TERMS:
        without_noise = without_noise.replace(term.casefold(), " ")

    if any(term in without_noise for term in _CJK_PURCHASE_TERMS):
        return True
    if re.search(r"\bpurchase\s+orders?\b|\bpo\s*(?:number|no\.?|#)", without_noise):
        return True

    has_part_context = any(term in without_noise for term in _CJK_PART_TERMS) or bool(
        re.search(r"\bparts?\b|\bspares?\b", without_noise)
    )
    if has_part_context and any(term in without_noise for term in ("下单", "下單")):
        return True
    return has_part_context and bool(re.search(r"\b(?:purchased|ordered)\b", without_noise))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _extract_purchase_order_id(text: str) -> str | None:
    patterns = (
        r"(?:采购订单|採購訂單|采购单|採購單)\s*(?:编号|編號|号码|號碼|号|號|ID)?\s*(?:是|为|為|=|:|：|#)?\s*([A-Za-z0-9][A-Za-z0-9_.\-/]{1,47})",
        r"\bPO\s*(?:number|no\.?|#|编号|編號)?\s*(?:=|:|：|#)?\s*([A-Za-z0-9][A-Za-z0-9_.\-/]{1,47})\b",
        r"\bpurchase\s+order\s*(?:number|no\.?|#)?\s*(?:=|:|#)?\s*([A-Za-z0-9][A-Za-z0-9_.\-/]{1,47})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_part_number(text: str, *, purchase_order_id: str | None) -> str | None:
    patterns = (
        r"(?:零件编号|零件編號|零件号码|零件號碼|零件号|零件號)\s*(?:是|为|為|=|:|：|#)?\s*([A-Za-z0-9][A-Za-z0-9_.\-/]{1,47})",
        r"\bpart\s*(?:number|no\.?|#)\s*(?:=|:|#)?\s*([A-Za-z0-9][A-Za-z0-9_.\-/]{1,47})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

    for match in re.finditer(r"\b[A-Za-z0-9]{2,}(?:[-_/][A-Za-z0-9]+)+\b", text):
        value = match.group(0).strip()
        if not purchase_order_id or value.casefold() != purchase_order_id.casefold():
            return value
    return None


def _extract_vendor(text: str) -> str | None:
    match = re.search(
        r"(?:供应商|供應商|厂商|廠商|vendor|supplier)\s*(?:是|为|為|=|:|：)?\s*([^,，。;；?？]{1,48})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1).strip()
    value = re.split(
        r"\s*(?:的)?(?:采购|採購|下单|下單|今天|今日|昨天|昨日|前天|最近|近\s*\d+\s*天)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.sub(r"\s+(?:purchase|purchased|ordered).*?$", "", value, flags=re.IGNORECASE)
    return value.strip(" ,，。;；:：") or None


def _escape_odata_string(value: str) -> str:
    return value.replace("'", "''")

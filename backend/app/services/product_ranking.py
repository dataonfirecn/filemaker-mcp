from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.services.filemaker_client import FileMakerClient


PRODUCT_RANK_LAYOUT = "@products_rank"
PRODUCT_RANK_SOLD_FIELD = "產品庫存::出庫數量總合"
PRODUCT_RANK_PAGE_SIZE = 5_000
PRODUCT_RANK_MAX_RECORDS = 50_000
PRODUCT_RANK_DEFAULT_LIMIT = 20
PRODUCT_RANK_MAX_LIMIT = 50


@dataclass(frozen=True)
class ProductRankPlan:
    direction: Literal["most", "least"]
    limit: int


@dataclass(frozen=True)
class ProductRankRow:
    record_id: str
    product_sku: str
    product_name: str
    sold_total: Decimal


@dataclass(frozen=True)
class ProductRankResult:
    rows: list[ProductRankRow]
    eligible_count: int
    scanned_count: int


class ProductRankLimitExceeded(RuntimeError):
    def __init__(self, found_count: int, maximum: int):
        self.found_count = found_count
        self.maximum = maximum
        super().__init__(
            f"Product ranking requires {found_count} records, above the {maximum} record limit"
        )


def parse_product_rank_plan(prompt: str) -> ProductRankPlan | None:
    normalized = " ".join(prompt.strip().casefold().split())
    if not normalized:
        return None

    most_sold = bool(re.search(
        r"\b(?:most\s+sold|top\s+(?:selling|sold)|best[-\s]?selling|highest\s+(?:selling|sales?))\b|"
        r"销量(?:最高|最多)|銷量(?:最高|最多)|最畅销|最暢銷",
        normalized,
        re.IGNORECASE,
    ))
    least_sold = bool(re.search(
        r"\b(?:less\s+sold|least\s+sold|bottom\s+(?:selling|sold)|lowest\s+(?:selling|sales?)|"
        r"slowest[-\s]?selling)\b|销量(?:最低|最少)|銷量(?:最低|最少)|最滞销|最滯銷",
        normalized,
        re.IGNORECASE,
    ))
    if most_sold == least_sold:
        return None

    limit_match = re.search(
        r"\b(?:top|bottom)\s*(\d{1,3})\b|\b(\d{1,3})\s+(?:items?|products?|skus?)\b|"
        r"(?:前|后|後)\s*(\d{1,3})\s*(?:个|個|项|項|条|條)?",
        normalized,
        re.IGNORECASE,
    )
    requested_limit = next(
        (int(value) for value in (limit_match.groups() if limit_match else ()) if value),
        PRODUCT_RANK_DEFAULT_LIMIT,
    )
    return ProductRankPlan(
        direction="most" if most_sold else "least",
        limit=max(1, min(requested_limit, PRODUCT_RANK_MAX_LIMIT)),
    )


async def fetch_product_rankings(
    filemaker: FileMakerClient,
    plan: ProductRankPlan,
) -> ProductRankResult:
    records: list[dict[str, object]] = []
    found_count: int | None = None

    while found_count is None or len(records) < found_count:
        result = await filemaker.find_records(
            PRODUCT_RANK_LAYOUT,
            query=None,
            limit=PRODUCT_RANK_PAGE_SIZE,
            offset=len(records) + 1,
        )
        found_count = int(result.get("foundCount") or 0)
        if found_count > PRODUCT_RANK_MAX_RECORDS:
            raise ProductRankLimitExceeded(found_count, PRODUCT_RANK_MAX_RECORDS)
        batch = [item for item in (result.get("data") or []) if isinstance(item, dict)]
        records.extend(batch)
        if not batch:
            break

    ranked: list[ProductRankRow] = []
    for record in records:
        fields = record.get("fieldData")
        fields = fields if isinstance(fields, dict) else {}
        product_sku = str(fields.get("product_sku") or "").strip()
        if not product_sku:
            continue
        sold_total = product_sold_total(fields.get(PRODUCT_RANK_SOLD_FIELD))
        if plan.direction == "least" and sold_total <= 0:
            continue
        ranked.append(ProductRankRow(
            record_id=str(record.get("recordId") or ""),
            product_sku=product_sku,
            product_name=str(fields.get("product_name") or "").strip(),
            sold_total=sold_total,
        ))

    if plan.direction == "most":
        ranked.sort(key=lambda item: (-item.sold_total, item.product_sku.casefold()))
    else:
        ranked.sort(key=lambda item: (item.sold_total, item.product_sku.casefold()))

    return ProductRankResult(
        rows=ranked[:plan.limit],
        eligible_count=len(ranked),
        scanned_count=len(records),
    )


def product_sold_total(value: object) -> Decimal:
    if value is None or value == "":
        return Decimal()
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return Decimal()


def product_rank_public_number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)

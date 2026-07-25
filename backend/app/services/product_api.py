from __future__ import annotations

import asyncio
from typing import Any

from app.services.filemaker_client import FileMakerClient


PRODUCT_LAYOUT = "@products"
PRODUCT_BOM_LAYOUT = "@product_bom"
PRODUCT_PRICE_LAYOUT = "@產品售價"
PRODUCT_PART_LAYOUT = "@零件"
PRODUCT_ASSET_LAYOUT = "ProductAssets"
PRODUCT_STOCK_FIELD = "stock"


def records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def fields(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("fieldData") if isinstance(record, dict) else {}
    return value if isinstance(value, dict) else {}


async def find_product_bom(
    filemaker: FileMakerClient,
    product_sku: str,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    sku = product_sku.strip()
    if not sku:
        return {"data": [], "foundCount": 0, "returnedCount": 0}
    return await filemaker.find_records(
        PRODUCT_BOM_LAYOUT,
        query={"ID_產品編號": f"=={sku}"},
        limit=limit,
    )


async def find_product_price(
    filemaker: FileMakerClient,
    product_sku: str,
    system_product_sku: str = "",
) -> dict[str, Any]:
    identifiers = list(dict.fromkeys(
        item.strip()
        for item in (product_sku, system_product_sku)
        if item and item.strip()
    ))
    if not identifiers:
        return {"data": [], "foundCount": 0, "returnedCount": 0}
    return await filemaker.find_records(
        PRODUCT_PRICE_LAYOUT,
        query=[{"產品編號": f"=={identifier}"} for identifier in identifiers],
        limit=max(10, len(identifiers) * 2),
    )


async def enrich_product_record(
    filemaker: FileMakerClient,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Add BOM and price data using API-only layouts.

    The returned compatibility field names keep existing internal response models
    stable while ensuring no request is sent to the user-maintained product layout.
    """
    source_fields = fields(record)
    sku = str(source_fields.get("product_sku") or "").strip()
    system_sku = str(source_fields.get("系統產品編號") or "").strip()
    bom_result, price_result = await asyncio.gather(
        find_product_bom(filemaker, sku),
        find_product_price(filemaker, sku, system_sku),
    )
    bom_records = records(bom_result)
    price_records = records(price_result)
    enriched_fields = dict(source_fields)

    price_record = _preferred_price_record(price_records, sku, system_sku)
    price_fields = fields(price_record) if price_record else {}
    if price_fields:
        enriched_fields["產品售價::Price"] = price_fields.get("Price")

    bom_dates = _unique_values(bom_records, "日期")
    vendors = _unique_values(bom_records, "廠商")
    if bom_dates:
        enriched_fields["產品 BOM::日期"] = bom_dates[0]
    if vendors:
        enriched_fields["產品 BOM::廠商"] = "、".join(vendors)

    portal_data = dict(record.get("portalData") or {})
    if bom_records:
        portal_data[PRODUCT_BOM_LAYOUT] = [_flat_portal_record(item) for item in bom_records]
    if price_records:
        portal_data[PRODUCT_PRICE_LAYOUT] = [_flat_portal_record(item) for item in price_records]

    return {
        **record,
        "fieldData": enriched_fields,
        "portalData": portal_data,
    }


def price_value(
    result: dict[str, Any],
    product_sku: str,
    system_product_sku: str = "",
) -> Any:
    record = _preferred_price_record(records(result), product_sku, system_product_sku)
    return fields(record).get("Price") if record else None


def _preferred_price_record(
    price_records: list[dict[str, Any]],
    product_sku: str,
    system_product_sku: str,
) -> dict[str, Any] | None:
    preferred = [item for item in (product_sku.strip(), system_product_sku.strip()) if item]
    for identifier in preferred:
        for record in price_records:
            if str(fields(record).get("產品編號") or "").strip() == identifier:
                return record
    return price_records[0] if price_records else None


def _unique_values(source_records: list[dict[str, Any]], field_name: str) -> list[str]:
    values: list[str] = []
    for record in source_records:
        value = str(fields(record).get(field_name) or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _flat_portal_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": str(record.get("recordId") or ""),
        "modId": str(record.get("modId") or ""),
        **fields(record),
    }

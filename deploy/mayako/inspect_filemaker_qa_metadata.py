"""Inspect live FileMaker metadata needed for the Mayako Q&A design."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import Settings
from app.services.filemaker_client import FileMakerClient


LAYOUTS = ("@products", "@產品售價", "Parts", "@零件", "@mayako")
PRICE_TERMS = ("price", "價格", "售价", "售價", "单价", "單價", "cost", "成本")


def metadata_item(item: dict[str, Any]) -> dict[str, object]:
    return {
        "name": item.get("name"),
        "type": item.get("type"),
        "result": item.get("result"),
        "global": item.get("global"),
        "repetition": item.get("repetition"),
    }


def candidate_values(result: dict[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in result.get("data", []):
        fields = record.get("fieldData") if isinstance(record, dict) else {}
        fields = fields if isinstance(fields, dict) else {}
        values = {
            key: value
            for key, value in fields.items()
            if any(term in key.casefold() for term in PRICE_TERMS)
            or key in {"product_sku", "系統產品編號", "產品編號", "part_number", "ID_客戶"}
        }
        rows.append({"recordId": record.get("recordId"), "fields": values})
    return rows


async def main() -> None:
    client = FileMakerClient(Settings())
    try:
        layout_fields = {
            layout: [metadata_item(item) for item in await client.get_layout_fields(layout)]
            for layout in LAYOUTS
        }
        product = await client.find_records(
            "@products",
            query={"product_sku": "==MYB0196", "id_client": "==CU638"},
            limit=5,
        )
        product_price = await client.find_records(
            "@產品售價",
            query={"產品編號": "==MYB0196"},
            limit=10,
        )
        part = await client.find_records(
            "Parts",
            query={"part_number": "==AL05249-TW-LD", "customer_id": "==CU638"},
            limit=5,
        )
        api_part = await client.find_records(
            "@零件",
            query={"part_number": "==AL05249-TW-LD"},
            limit=5,
        )
        output = {
            "layouts": {
                layout: {
                    "fieldCount": len(fields),
                    "fields": fields,
                    "priceCandidateFields": [
                        item
                        for item in fields
                        if any(term in str(item.get("name") or "").casefold() for term in PRICE_TERMS)
                    ],
                }
                for layout, fields in layout_fields.items()
            },
            "samples": {
                "productMYB0196": candidate_values(product),
                "productPriceMYB0196": candidate_values(product_price),
                "partAL05249TWLD": candidate_values(part),
                "apiPartAL05249TWLD": candidate_values(api_part),
            },
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

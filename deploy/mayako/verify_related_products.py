"""Verify the deployed customer table and related-product release from inside the stack."""

from __future__ import annotations

import json
import re

import httpx

from app.core.config import Settings
from app.services.customer_chat_auth import issue_customer_token, load_customer_accounts


def main() -> None:
    settings = Settings()
    account = load_customer_accounts(settings)["mayako"]
    token, _ = issue_customer_token(account, settings)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(base_url="http://frontend", headers=headers, timeout=90) as client:
        product_100 = client.get(
            "/api/customer-chat/catalog/products",
            params={"page": 1, "pageSize": 100, "sortBy": "scale", "sortOrder": "asc"},
        )
        product_bom_sort = client.get(
            "/api/customer-chat/catalog/products",
            params={"page": 1, "pageSize": 20, "sortBy": "bomCount", "sortOrder": "desc"},
        )
        part_100 = client.get(
            "/api/customer-chat/catalog/parts",
            params={"page": 1, "pageSize": 100, "sortBy": "partNumber", "sortOrder": "asc"},
        )
        part_search = client.get(
            "/api/customer-chat/catalog/parts",
            params={"q": "AL05249-TW-LD", "page": 1, "pageSize": 20},
        )
        metric_product_search = client.get(
            "/api/customer-chat/catalog/products",
            params={"q": "MYB0196", "page": 1, "pageSize": 20},
        )

        for response in (product_100, product_bom_sort, part_100, part_search, metric_product_search):
            response.raise_for_status()

        metric_product_ref = metric_product_search.json()["rows"][0]["productRef"]
        metric_product_detail = client.get(
            f"/api/customer-chat/catalog/products/{metric_product_ref}"
        )
        metric_product_detail.raise_for_status()

        part_ref = part_search.json()["rows"][0]["partRef"]
        part_detail = client.get(f"/api/customer-chat/catalog/parts/{part_ref}")
        part_detail.raise_for_status()
        detail = part_detail.json()
        related = detail["relatedProducts"]
        related_product = client.get(
            f'/api/customer-chat/catalog/products/{related[0]["productRef"]}'
        )
        related_product.raise_for_status()

        price = client.post(
            "/api/customer-chat/query",
            json={"prompt": "Show unit price", "page": 1, "pageSize": 4},
        )
        exact_inventory = client.post(
            "/api/customer-chat/query",
            json={"prompt": "Check inventory for MYB0377-24", "page": 1, "pageSize": 4},
        )
        exact_inventory.raise_for_status()
        internal = client.get("/api/filemaker/layouts")

    product_100_payload = product_100.json()
    product_bom_payload = product_bom_sort.json()
    part_100_payload = part_100.json()
    metric_product = metric_product_detail.json()["product"]
    assert product_100_payload["pageSize"] == 100
    assert product_100_payload["returnedCount"] == 100
    assert product_100_payload["sortBy"] == "scale"
    assert product_bom_payload["sortBy"] == "bomCount"
    assert part_100_payload["pageSize"] == 100
    assert part_100_payload["returnedCount"] == 100
    assert metric_product["productSku"] == "MYB0196"
    assert set(metric_product) == {
        "productRef",
        "productSku",
        "productName",
        "modelName",
        "scale",
        "category",
        "stock",
        "bomCount",
        "hasImage",
        "soldTotal",
        "price",
        "stockValue",
        "prepaidStock",
        "productionCalculation",
    }
    assert metric_product["price"] == 1.9
    assert metric_product["stockValue"] is not None
    assert metric_product["prepaidStock"] is not None
    assert metric_product["productionCalculation"] == 103
    assert detail["part"]["partNumber"] == "AL05249-TW-LD"
    assert detail["part"]["created"]
    assert detail["part"]["safetyStock"] == 0
    assert detail["part"]["turnover"] == "0 Days"
    assert set(detail["part"]) == {
        "partRef",
        "partNumber",
        "partName",
        "stock",
        "safetyStock",
        "turnover",
        "created",
        "status",
        "hasImage",
    }
    assert related
    assert any(row["productSku"] == "MYB0131" for row in related)
    assert all(set(row) == {"productRef", "productSku", "productName"} for row in related)
    assert not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", json.dumps(related, ensure_ascii=False))
    assert related_product.json()["product"]["productSku"] == related[0]["productSku"]
    exact_inventory_payload = exact_inventory.json()
    assert exact_inventory_payload["foundCount"] == 1
    assert exact_inventory_payload["returnedCount"] == 1
    assert exact_inventory_payload["rows"][0]["productSku"] == "MYB0377-24"
    assert price.status_code == 200
    assert internal.status_code == 404

    print(json.dumps({
        "productCount": product_100_payload["foundCount"],
        "productPageSize": product_100_payload["pageSize"],
        "productSorts": [product_100_payload["sortBy"], product_bom_payload["sortBy"]],
        "metricProduct": {
            key: metric_product[key]
            for key in (
                "productSku",
                "stock",
                "soldTotal",
                "price",
                "stockValue",
                "prepaidStock",
                "productionCalculation",
            )
        },
        "partCount": part_100_payload["foundCount"],
        "partPageSize": part_100_payload["pageSize"],
        "partNumber": detail["part"]["partNumber"],
        "safetyStock": detail["part"]["safetyStock"],
        "turnover": detail["part"]["turnover"],
        "created": detail["part"]["created"],
        "relatedProducts": len(related),
        "relatedProductLink": related_product.status_code,
        "exactInventory": {
            "foundCount": exact_inventory_payload["foundCount"],
            "productSku": exact_inventory_payload["rows"][0]["productSku"],
            "stock": exact_inventory_payload["rows"][0]["stock"],
        },
        "priceQuery": price.status_code,
        "internalApi": internal.status_code,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

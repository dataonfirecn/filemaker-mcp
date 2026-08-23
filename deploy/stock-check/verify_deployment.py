"""Run a live white-label and customer-boundary deployment check."""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import quote


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-part-count", type=int)
    parser.add_argument(
        "--can-view-price",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--is-admin",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    args = parser.parse_args()
    password = os.environ.get("STOCK_CHECK_VERIFY_PASSWORD", "")
    if not password:
        raise SystemExit("STOCK_CHECK_VERIFY_PASSWORD is required")

    base_url = args.base_url.rstrip("/")

    def request(path: str, method: str = "GET", body=None, token: str | None = None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90, context=ssl.create_default_context()) as response:
                raw = response.read()
                content_type = response.headers.get("content-type") or ""
                if content_type.startswith("image/") or content_type.startswith("application/pdf"):
                    payload = raw
                else:
                    payload = json.loads(raw) if raw and "application/json" in content_type else raw.decode("utf-8", "replace")
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            content_type = exc.headers.get("content-type") or ""
            if content_type.startswith("image/") or content_type.startswith("application/pdf"):
                payload = raw
            else:
                payload = json.loads(raw) if raw and "application/json" in content_type else raw.decode("utf-8", "replace")
            return exc.code, payload

    page_status, page = request("/customer-chat")
    assert page_status == 200
    asset_paths = re.findall(r'(?:src|href)=["\']([^"\']*/assets/[^"\']+)["\']', page)
    assert asset_paths
    assets: list[str] = []
    for path in asset_paths:
        status, content = request(path)
        assert status == 200
        assets.append(content)
    browser_payload = "\n".join([page, *assets])
    assert not re.search(r"star[- ]?rc|starrc", browser_payload, re.IGNORECASE)
    assert not re.search(r"[\u3400-\u9fff]", browser_payload)
    product_page_status, product_page = request("/customer-chat/products")
    part_page_status, part_page = request("/customer-chat/parts/1")
    order_page_status, order_page = request("/customer-chat/orders")
    assert product_page_status == 200 and product_page == page
    assert part_page_status == 200 and part_page == page
    assert order_page_status == 200 and order_page == page

    login_status, login = request(
        "/api/customer-chat/login",
        "POST",
        {"username": args.username, "password": password},
    )
    assert login_status == 200, login
    token = login["token"]
    me_status, profile = request("/api/customer-chat/me", token=token)
    list_status, result = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "View product list", "page": 1, "pageSize": 20},
        token,
    )
    page_two_status, page_two = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "View product list", "page": 2, "pageSize": 20},
        token,
    )
    part_status, part_result = request(
        "/api/customer-chat/query",
        "POST",
        {
            "prompt": 'ExecuteSQLe ( "SELECT part_number FROM "零件" WHERE "customer_id" = ?";""; ""; "CU638" )',
            "page": 1,
            "pageSize": 20,
        },
        token,
    )
    price_status, price = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "Show unit price"},
        token,
    )
    internal_status, _ = request("/api/filemaker/layouts", token=token)
    product_catalog_status, product_catalog = request(
        "/api/customer-chat/catalog/products?page=1&pageSize=20&sortBy=productSku&sortOrder=asc",
        token=token,
    )
    product_desc_status, product_desc = request(
        "/api/customer-chat/catalog/products?page=1&pageSize=20&sortBy=productSku&sortOrder=desc",
        token=token,
    )
    product_large_status, product_large = request(
        "/api/customer-chat/catalog/products?page=1&pageSize=100&sortBy=scale&sortOrder=asc",
        token=token,
    )
    product_bom_sort_status, product_bom_sort = request(
        "/api/customer-chat/catalog/products?page=1&pageSize=20&sortBy=bomCount&sortOrder=desc",
        token=token,
    )
    part_catalog_status, part_catalog = request(
        "/api/customer-chat/catalog/parts?page=1&pageSize=20&sortBy=partNumber&sortOrder=asc",
        token=token,
    )
    part_large_status, part_large = request(
        "/api/customer-chat/catalog/parts?page=1&pageSize=100&sortBy=partNumber&sortOrder=asc",
        token=token,
    )
    order_catalog_status, order_catalog = request(
        "/api/customer-chat/catalog/orders?page=1&pageSize=20&sortBy=orderNumber&sortOrder=desc",
        token=token,
    )
    order_chat_status, order_chat = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "View orders", "page": 1, "pageSize": 4},
        token,
    )
    order_date_chat_status, order_date_chat = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "查询 2026-07-01 到 2026-07-22 的出库单", "page": 1, "pageSize": 4},
        token,
    )
    order_unshipped_status, order_unshipped = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "查询未出货的出库单", "page": 1, "pageSize": 4},
        token,
    )
    payment_date_status, payment_date = request(
        "/api/customer-chat/query",
        "POST",
        {"prompt": "查询收款日期 2026-07-01 到 2026-07-22 的出库单", "page": 1, "pageSize": 4},
        token,
    )
    product_search_status, product_search = request(
        f"/api/customer-chat/catalog/products?q={quote('PT-Tent-MYK01')}&page=1&pageSize=20",
        token=token,
    )
    detail_source = product_search["rows"][0] if product_search.get("rows") else product_catalog["rows"][0]
    product_detail_status, product_detail = request(
        f'/api/customer-chat/catalog/products/{detail_source["productRef"]}',
        token=token,
    )
    gallery_image_status = None
    gallery_image_content = None
    if product_detail.get("images"):
        gallery_image_status, gallery_image_content = request(
            f'/api/customer-chat/products/{detail_source["productRef"]}/images/{product_detail["images"][0]["assetRef"]}',
            token=token,
        )
    part_detail_source = part_catalog["rows"][0]
    part_detail_status, part_detail = request(
        f'/api/customer-chat/catalog/parts/{part_detail_source["partRef"]}',
        token=token,
    )
    related_part_search_status, related_part_search = request(
        f"/api/customer-chat/catalog/parts?q={quote('AL05249-TW-LD')}&page=1&pageSize=20",
        token=token,
    )
    related_part_source = related_part_search["rows"][0]
    related_part_detail_status, related_part_detail = request(
        f'/api/customer-chat/catalog/parts/{related_part_source["partRef"]}',
        token=token,
    )
    related_product_source = related_part_detail["relatedProducts"][0]
    related_product_detail_status, related_product_detail = request(
        f'/api/customer-chat/catalog/products/{related_product_source["productRef"]}',
        token=token,
    )

    image_row = next((row for row in [*result["rows"], *page_two["rows"]] if row.get("hasImage")), None)
    if image_row is None:
        image_query_status, image_query = request(
            "/api/customer-chat/query",
            "POST",
            {"prompt": "Check inventory for PT-Tent-MYK01", "page": 1, "pageSize": 20},
            token,
        )
        assert image_query_status == 200
        image_row = next((row for row in image_query["rows"] if row.get("hasImage")), None)
    assert image_row is not None
    image_status, image_content = request(
        f'/api/customer-chat/products/{image_row["productRef"]}/image',
        token=token,
    )
    part_image_row = next((row for row in part_result["rows"] if row.get("hasImage")), None)
    assert part_image_row is not None
    part_image_status, part_image_content = request(
        f'/api/customer-chat/parts/{part_image_row["productRef"]}/image',
        token=token,
    )

    assert me_status == 200
    assert profile == {
        "username": args.username,
        "displayName": args.client_name,
        "clientName": args.client_name,
        "canViewPrice": args.can_view_price,
        "isAdmin": args.is_admin,
    }
    assert list_status == 200, result
    assert page_two_status == 200, page_two
    assert result["page"] == 1 and page_two["page"] == 2
    assert result["resultType"] == "product"
    assert result["pageSize"] == 20 and page_two["pageSize"] == 20
    assert result["totalPages"] == page_two["totalPages"]
    assert result["rows"] and page_two["rows"]
    assert result["rows"][0]["productRef"] != page_two["rows"][0]["productRef"]
    if args.expected_count is not None:
        assert result["foundCount"] == args.expected_count
    assert part_status == 200, part_result
    assert part_result["resultType"] == "part"
    assert part_result["returnedCount"] == 20
    assert all(row["entityType"] == "part" for row in part_result["rows"])
    if args.expected_part_count is not None:
        assert part_result["foundCount"] == args.expected_part_count
    assert part_result["answer"].isascii()
    assert result["answer"].isascii()
    rows = result.get("rows") or []
    blocked_fragments = ("price", "cost", "quote", "productnamecn")
    bad_keys = sorted(
        {
            key
            for row in rows
            for key in row
            if any(fragment in key.casefold() for fragment in blocked_fragments)
        }
    )
    assert not bad_keys
    assert all("stock" in row for row in rows)
    if args.can_view_price:
        assert price_status == 200, price
    else:
        assert price_status == 403 and price["detail"]["message"].isascii()
    assert internal_status == 404
    assert product_catalog_status == 200, product_catalog
    assert product_desc_status == 200, product_desc
    assert product_large_status == 200, product_large
    assert product_bom_sort_status == 200, product_bom_sort
    assert part_catalog_status == 200, part_catalog
    assert part_large_status == 200, part_large
    assert order_catalog_status == 200, order_catalog
    assert order_chat_status == 200, order_chat
    assert order_date_chat_status == 200, order_date_chat
    assert order_unshipped_status == 200, order_unshipped
    assert payment_date_status == 200, payment_date
    assert payment_date["foundCount"] == 0
    if args.expected_count is not None:
        assert product_catalog["foundCount"] == args.expected_count
    if args.expected_part_count is not None:
        assert part_catalog["foundCount"] == args.expected_part_count
    assert product_catalog["rows"] and part_catalog["rows"]
    assert order_catalog["rows"]
    assert product_catalog["rows"][0]["productRef"] != product_desc["rows"][0]["productRef"]
    assert product_large["pageSize"] == 100 and product_large["returnedCount"] == 100
    assert product_large["sortBy"] == "scale" and product_large["sortOrder"] == "asc"
    assert product_bom_sort["sortBy"] == "bomCount" and product_bom_sort["sortOrder"] == "desc"
    assert part_large["pageSize"] == 100 and part_large["returnedCount"] == 100
    assert order_catalog["sortBy"] == "orderNumber" and order_catalog["sortOrder"] == "desc"
    assert all(set(row) == {
        "orderRef", "clientName", "orderNumber", "orderAmount", "shippingCompany", "trackingNumber",
        "shippingCost", "shippedDate", "shippingStatus", "remarks",
    } for row in order_catalog["rows"])
    assert order_chat["resultType"] == "order" and order_chat["rows"]
    assert order_chat["foundCount"] == order_catalog["foundCount"]
    assert order_date_chat["resultType"] == "order"
    assert all(set(row) == {
        "entityType", "orderRef", "clientName", "orderNumber", "orderAmount", "shippingCompany",
        "trackingNumber", "shippingCost", "shippedDate", "shippingStatus", "remarks",
    } for row in [*order_chat["rows"], *order_date_chat["rows"], *order_unshipped["rows"]])
    assert all(
        row["orderNumber"] and not row["orderNumber"].upper().startswith("PI")
        for row in [*order_chat["rows"], *order_date_chat["rows"], *order_unshipped["rows"]]
    )
    assert all(row["shippingStatus"] in {"未出貨", "Not Shipped"} for row in order_unshipped["rows"])
    assert product_detail_status == 200, product_detail
    assert product_detail["imageCount"] == len(product_detail["images"])
    assert all(set(image) == {"assetRef", "filename", "title", "sortOrder", "isPrimary"} for image in product_detail["images"])
    if product_detail["images"]:
        assert gallery_image_status == 200
        assert isinstance(gallery_image_content, bytes) and len(gallery_image_content) > 0
    assert part_detail_status == 200, part_detail
    assert related_part_search_status == 200, related_part_search
    assert related_part_detail_status == 200, related_part_detail
    assert related_product_detail_status == 200, related_product_detail
    assert isinstance(product_detail["bom"], list)
    if product_search.get("rows"):
        assert product_detail["bom"]
    expected_product_fields = {
        "productRef", "productSku", "productName", "modelName", "scale", "category",
        "stock", "bomCount", "hasImage", "soldTotal", "stockValue",
        "prepaidStock", "productionCalculation",
    }
    if args.can_view_price:
        expected_product_fields.add("price")
    assert set(product_detail["product"]) == expected_product_fields
    assert set(part_detail["part"]) == {
        "partRef", "partNumber", "partName", "stock", "safetyStock", "turnover",
        "created", "status", "hasImage",
    }
    assert isinstance(part_detail["relatedProducts"], list)
    assert related_part_detail["part"]["partNumber"] == "AL05249-TW-LD"
    assert related_part_detail["part"]["created"]
    assert related_part_detail["relatedProducts"]
    assert any(row["productSku"] == "MYB0131" for row in related_part_detail["relatedProducts"])
    assert all(set(row) == {"productRef", "productSku", "productName"} for row in related_part_detail["relatedProducts"])
    assert related_product_detail["product"]["productSku"] == related_product_source["productSku"]
    list_payload = json.dumps(
        {"products": product_catalog, "parts": part_catalog, "partDetail": part_detail},
        ensure_ascii=False,
    )
    assert not re.search(r'"[^"\n]*(?:price|cost|vendor|supplier|productnamecn)[^"\n]*"\s*:', list_payload, re.IGNORECASE)
    detail_payload = json.dumps(product_detail, ensure_ascii=False)
    assert not re.search(r'"[^"\n]*(?:cost|vendor|supplier|quote|productnamecn)[^"\n]*"\s*:', detail_payload, re.IGNORECASE)
    assert not re.search(r"[\u3400-\u9fff]", list_payload + detail_payload)
    assert image_status == 200 and isinstance(image_content, bytes) and len(image_content) > 0
    assert part_image_status == 200 and isinstance(part_image_content, bytes) and len(part_image_content) > 0

    print(
        json.dumps(
            {
                "httpsPage": page_status,
                "whiteLabelAssets": len(assets),
                "login": login_status,
                "profile": profile,
                "listQuery": list_status,
                "foundCount": result.get("foundCount"),
                "returnedCount": result.get("returnedCount"),
                "pageTwoReturnedCount": page_two.get("returnedCount"),
                "totalPages": result.get("totalPages"),
                "partQuery": part_status,
                "partFoundCount": part_result.get("foundCount"),
                "partTotalPages": part_result.get("totalPages"),
                "rowFields": sorted(rows[0]) if rows else [],
                "priceQuery": price_status,
                "internalApi": internal_status,
                "productCatalog": product_catalog_status,
                "productPageSize100": product_large_status,
                "productScaleSort": product_large.get("sortBy"),
                "productBomSort": product_bom_sort.get("sortBy"),
                "partCatalog": part_catalog_status,
                "partPageSize100": part_large_status,
                "orderCatalog": order_catalog_status,
                "orderFoundCount": order_catalog.get("foundCount"),
                "orderChat": order_chat_status,
                "orderChatFoundCount": order_chat.get("foundCount"),
                "orderDateChat": order_date_chat_status,
                "orderDateChatFoundCount": order_date_chat.get("foundCount"),
                "orderUnshippedChat": order_unshipped_status,
                "orderUnshippedFoundCount": order_unshipped.get("foundCount"),
                "paymentDateChat": payment_date_status,
                "paymentDateFoundCount": payment_date.get("foundCount"),
                "productDetail": product_detail_status,
                "bomLines": len(product_detail.get("bom") or []),
                "partDetail": part_detail_status,
                "relatedPartDetail": related_part_detail_status,
                "relatedProducts": len(related_part_detail.get("relatedProducts") or []),
                "relatedProductLink": related_product_detail_status,
                "directCatalogPages": [order_page_status, product_page_status, part_page_status],
                "clickImage": image_status,
                "galleryImages": product_detail.get("imageCount"),
                "clickGalleryImage": gallery_image_status,
                "clickPartImage": part_image_status,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

import json
from datetime import datetime, timezone

import pytest

from app.api.orders import (
    _item_payload,
    _order_receipt_catalog,
    _product_asset_category,
    _product_cos_image_catalog,
    _warehouse_issued_quantity,
    _warehouse_issued_quantity_catalog,
)
from app.services.cos_storage import (
    COSObjectMetadata,
    COSStorageError,
    COSStorageService,
)
from app.core.config import Settings


class FakeFileMaker:
    def __init__(self) -> None:
        self.layouts: list[str] = []

    async def find_records(self, layout, **_kwargs):
        self.layouts.append(layout)
        if layout == "@products":
            return {
                "data": [
                    {
                        "recordId": "2948",
                        "fieldData": {
                            "product_sku": "PTK-8231",
                            "產品名稱_中文": "公制六角工具芯 2.0mm",
                            "product_name": "Metric Hex Driver Tip 2.0mm",
                        },
                    }
                ]
            }
        if layout == "ProductAssets":
            return {
                "data": [
                    {
                        "recordId": "1474",
                        "fieldData": {
                            "source_record_id": "2948",
                            "id_asset": "SECOND",
                            "original_filename": "second.png",
                            "mime_type": "image/png",
                            "is_primary": 0,
                            "sort_order": 2,
                            "asset_file": "https://filemaker.invalid/second.png",
                        },
                    },
                    {
                        "recordId": "1473",
                        "fieldData": {
                            "source_record_id": "2948",
                            "id_asset": "PRIMARY",
                            "original_filename": "primary.png",
                            "mime_type": "image/png",
                            "is_primary": 1,
                            "sort_order": 1,
                            "asset_file": "https://filemaker.invalid/primary.png",
                        },
                    },
                    {
                        "recordId": "1475",
                        "fieldData": {
                            "source_record_id": "2948",
                            "id_asset": "PACKAGING",
                            "asset_type": "product_image",
                            "legacy_source_field": "檔案 11 | 容器",
                            "original_filename": "packaging.png",
                            "mime_type": "image/png",
                            "is_primary": 0,
                            "sort_order": 1,
                            "asset_file": "https://filemaker.invalid/packaging.png",
                        },
                    },
                ]
            }
        raise AssertionError(f"Unexpected layout: {layout}")


class FakeCOSStorage:
    configured = True

    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()
        self.checked_keys: list[str] = []

    def create_migrated_product_asset_object_key(
        self,
        *,
        source_record_id,
        asset_id,
        mime_type,
        original_filename,
    ):
        del mime_type, original_filename
        return f"starrc/products/original/migration/{source_record_id}/{asset_id}.png"

    def head_object(self, object_key):
        self.checked_keys.append(object_key)
        if object_key in self.missing:
            raise COSStorageError("missing")
        return COSObjectMetadata(
            content_length=42,
            content_type="image/png",
            etag="etag",
        )

    def create_presigned_download(self, object_key):
        return (
            f"https://starrc-1252872963.cos.ap-guangzhou.myqcloud.com/{object_key}",
            datetime(2026, 7, 30, tzinfo=timezone.utc),
        )


class FakeReceiptOData:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    async def records(self, table, *, filter_expr=None, **_kwargs):
        self.queries.append((table, filter_expr or ""))
        if table == "出貨單資料入庫":
            if "LINE-1" not in (filter_expr or ""):
                return {"rows": []}
            return {
                "rows": [
                    {
                        "ID": "RECEIPT-OLD",
                        "ID_出庫單資料": "LINE-1",
                        "數量": 50,
                        "狀態": "已入庫",
                        "创建时间戳": "12/31/2025 23:59:59",
                        "创建人": "service",
                    },
                    {
                        "ID": "RECEIPT-NEW",
                        "ID_出庫單資料": "LINE-1",
                        "數量": 300,
                        "狀態": "已入庫",
                        "创建时间戳": "01/02/2026 08:30:00",
                        "创建人": "service",
                        "log": json.dumps(
                            {
                                "schema": "starrc.finished-goods-receipt",
                                "identifiers": {"draftId": "draft-add"},
                                "routing": {
                                    "mode": "split",
                                    "submittedQuantity": 305,
                                    "orderReceiptQuantity": 300,
                                    "supplementalQuantity": 5,
                                },
                            }
                        ),
                    },
                ]
            }
        if table == "產品庫存":
            if (filter_expr or "").startswith("ID_出貨單資料 eq"):
                return {
                    "rows": [
                        {
                            "ID_出貨單資料": "LINE-1",
                            "ID_產品編號": "PTK-8231",
                            "入庫數量": 5,
                            "批號": "NB-ADD",
                            "描述": (
                                "PDA_INBOUND_LINE=INBOUND-LINE-1 · "
                                "PDA_DRAFT=draft-add · "
                                "PDA_SUBMITTED=305 · "
                                "PDA_ORDER=300 · "
                                "PDA_SUPPLEMENTAL=5 · "
                                "原始录入 305；订单入库 300；追加入库 5 · "
                                "追加入库 · 补发到货"
                            ),
                            "記錄人": "PDA 测试用户",
                        }
                    ]
                }
            return {
                "rows": [
                    {
                        "ID_出貨單資料": "LINE-1",
                        "ID_出貨單資料入庫": "RECEIPT-NEW",
                        "記錄人": "PDA 测试用户",
                    }
                ]
            }
        if table == "入庫單":
            if "PI0019694" not in (filter_expr or ""):
                return {"rows": []}
            return {
                "rows": [
                    {
                        "ID": "INBOUND-1",
                        "概要": "PDA追加成品入库 · NB-ADD",
                        "採購單_ID": "PDA:draft-add",
                        "對應需求單": "PI0019694",
                        "日期": "2026-02-01",
                        "修改人": "PDA 测试用户",
                    }
                ]
            }
        if table == "入庫單資料":
            return {
                "rows": [
                    {
                        "ID": "INBOUND-LINE-1",
                        "ID_入庫單": "INBOUND-1",
                        "ID_採購單資料": "PDA:LINE-1",
                        "零件編號": "PTK-8231",
                        "數量": 5,
                    }
                ]
            }
        raise AssertionError(f"Unexpected table: {table}")


def test_order_item_payload_does_not_use_legacy_partial_issue_quantity():
    item = _item_payload(
        {"recordId": "42001"},
        {
            "ID": "LINE-1",
            "產品編號": "TZ0031-BL",
            "中文產品名稱": "轮胎转接座螺母",
        },
        {
            "產品編號": "TZ0031-BL",
            "數量": 150,
            "部分發料數量": 165,
        },
        {},
        1,
    )

    assert item["quantity"] == 150.0
    assert item["warehouseIssuedQuantity"] == 0.0


def test_warehouse_issued_quantity_uses_bom_bottleneck_product_equivalent():
    records = [
        {
            "fieldData": {
                "零件_BOM::倉庫分工": "发料",
                "實發数量": 1368,
                "額定數量": 4,
            }
        },
        {
            "fieldData": {
                "零件_BOM::倉庫分工": "发料",
                "實發数量": 1400,
                "額定數量": 4,
            }
        },
        {
            "fieldData": {
                "零件_BOM::倉庫分工": "不发料",
                "實發数量": 0,
                "額定數量": 1,
            }
        },
    ]

    assert _warehouse_issued_quantity(records) == 342.0


def test_warehouse_issued_quantity_ignores_bom_rows_without_actual_issue():
    records = [
        {
            "fieldData": {
                "產品 BOM_BOM::倉庫分工": "發料",
                "實發数量": 200,
                "額定數量": 2,
            }
        },
        {
            "fieldData": {
                "零件_BOM::倉庫分工": "发料",
                "實發数量": "",
                "額定數量": 1,
            }
        },
    ]

    assert _warehouse_issued_quantity(records) == 100.0


@pytest.mark.asyncio
async def test_warehouse_issued_quantity_catalog_queries_each_order_line_id():
    class FakeIssueFileMaker:
        def __init__(self) -> None:
            self.queries: list[tuple[str, dict[str, str]]] = []

        async def find_records(self, layout, *, query, **_kwargs):
            self.queries.append((layout, query))
            actual = 591 if "LINE-1" in query["ID_出貨單資料"] else 660
            return {
                "data": [
                    {
                        "fieldData": {
                            "零件_BOM::倉庫分工": "发料",
                            "實發数量": actual,
                            "額定數量": 4,
                        }
                    }
                ],
                "foundCount": 1,
            }

    filemaker = FakeIssueFileMaker()
    result = await _warehouse_issued_quantity_catalog(
        filemaker,
        ["LINE-1", "LINE-2", "LINE-1"],
    )

    assert result == {"LINE-1": 147.0, "LINE-2": 165.0}
    assert filemaker.queries == [
        ("零件包 發料分类", {"ID_出貨單資料": "==LINE-1"}),
        ("零件包 發料分类", {"ID_出貨單資料": "==LINE-2"}),
    ]


@pytest.mark.asyncio
async def test_order_receipt_catalog_returns_latest_traceable_receipt():
    odata = FakeReceiptOData()

    result = await _order_receipt_catalog(
        odata,
        ["LINE-1", "LINE-PENDING", "LINE-1"],
    )

    receipt = result["LINE-1"]
    assert receipt["receiptId"] == "RECEIPT-NEW"
    assert receipt["quantity"] == 350.0
    assert receipt["status"] == "已入庫"
    assert receipt["receivedAt"] == "2026-01-02T08:30:00+08:00"
    assert receipt["receivedBy"] == "PDA 测试用户"
    assert [item["receiptId"] for item in receipt["history"]] == [
        "RECEIPT-NEW",
        "RECEIPT-OLD",
    ]
    assert (
        "產品庫存",
        "ID_出貨單資料入庫 eq 'RECEIPT-NEW'",
    ) in odata.queries


@pytest.mark.asyncio
async def test_order_receipt_catalog_keeps_supplement_separate_from_order_total():
    odata = FakeReceiptOData()

    result = await _order_receipt_catalog(
        odata,
        ["LINE-1"],
        line_skus={"LINE-1": "PTK-8231"},
        shipment_id="PI0019694",
    )

    receipt = result["LINE-1"]
    assert receipt["quantity"] == 350.0
    assert receipt["receiptId"] == "INBOUND-1"
    assert [item["receiptId"] for item in receipt["history"]] == [
        "INBOUND-1",
        "RECEIPT-NEW",
        "RECEIPT-OLD",
    ]
    supplement = receipt["history"][0]
    assert supplement["routingMode"] == "supplemental_inbound"
    assert supplement["orderReceiptQuantity"] == 0
    assert supplement["supplementalQuantity"] == 5.0
    assert supplement["documentNumber"] == "NB-ADD"
    assert supplement["remark"] == "追加入库 · 补发到货"
    assert supplement["routingBatchId"] == "draft-add"
    assert supplement["submittedQuantity"] == 305.0
    assert supplement["splitOrderReceiptQuantity"] == 300.0
    assert supplement["splitSupplementalQuantity"] == 5.0
    order_entry = receipt["history"][1]
    assert order_entry["routingBatchId"] == "draft-add"
    assert order_entry["submittedQuantity"] == 305.0
    assert order_entry["splitOrderReceiptQuantity"] == 300.0
    assert order_entry["splitSupplementalQuantity"] == 5.0


@pytest.mark.asyncio
async def test_product_catalog_returns_cos_primary_first_without_container_download():
    filemaker = FakeFileMaker()
    storage = FakeCOSStorage()

    result = await _product_cos_image_catalog(
        filemaker,
        storage,
        ["PTK-8231"],
    )

    product = result["PTK-8231"]
    assert product["images"][0]["assetId"] == "PRIMARY"
    assert [item["assetId"] for item in product["images"]] == [
        "PRIMARY",
        "SECOND",
    ]
    assert product["packagingImages"][0]["assetId"] == "PACKAGING"
    assert product["name"] == "公制六角工具芯 2.0mm"
    assert product["mainImageUrl"].startswith(
        "https://starrc-1252872963.cos.ap-guangzhou.myqcloud.com/"
    )
    assert filemaker.layouts == ["@products", "ProductAssets"]
    assert len(storage.checked_keys) == 3


@pytest.mark.asyncio
async def test_product_catalog_omits_asset_not_present_in_cos():
    missing_key = "starrc/products/original/migration/2948/PRIMARY.png"
    storage = FakeCOSStorage(missing={missing_key})

    result = await _product_cos_image_catalog(
        FakeFileMaker(),
        storage,
        ["PTK-8231"],
        primary_only=True,
    )

    assert result["PTK-8231"]["mainImageUrl"] == ""
    assert result["PTK-8231"]["images"] == []


def test_product_cos_object_key_is_deterministic():
    storage = COSStorageService(Settings())

    key = storage.create_migrated_product_asset_object_key(
        source_record_id="2948",
        asset_id="395420C8-BDE6-1F42-9DF2-7A61FBFDFE1D",
        mime_type="image/png",
        original_filename="main.png",
    )

    assert key == (
        "starrc/products/original/migration/2948/"
        "395420C8-BDE6-1F42-9DF2-7A61FBFDFE1D.png"
    )


@pytest.mark.parametrize(
    ("asset_type", "legacy_field", "expected"),
    [
        ("product_image", "檔案 1 | 容器", "images"),
        ("product_image", "檔案 10 | 容器", "images"),
        ("product_image", "檔案 11 | 容器", "packagingImages"),
        ("packaging_reference", "", "packagingImages"),
        ("product_image", "檔案 16 | 容器", ""),
    ],
)
def test_product_asset_category_separates_product_and_packaging_photos(
    asset_type,
    legacy_field,
    expected,
):
    assert _product_asset_category(
        {
            "asset_type": asset_type,
            "legacy_source_field": legacy_field,
        }
    ) == expected

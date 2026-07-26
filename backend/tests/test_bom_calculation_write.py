from typing import Any

import pytest

from app.core.config import Settings
from app.models.bom_calculation_write import BomCalculationWriteLine
from app.services.bom_calculation_writer import create_bom_calculation_via_data_api


def bom_settings() -> Settings:
    return Settings(filemaker_bom_write_enabled=True)


def write_lines() -> list[BomCalculationWriteLine]:
    return [
        BomCalculationWriteLine(
            partNo="A-001",
            originalPartNo="A-001",
            ratedQty="1",
            quantity="2",
            productSku="P-100",
            productQty="2",
            orderItemId="item-1",
        ),
        BomCalculationWriteLine(
            partNo="A-001",
            originalPartNo="A-001",
            ratedQty="2",
            quantity="6",
            productSku="P-200",
            productQty="3",
            orderItemId="item-2",
        ),
        BomCalculationWriteLine(
            partNo="M-001",
            originalPartNo="M-001",
            ratedQty="0.5",
            quantity="1",
            productSku="P-100",
            productQty="2",
            orderItemId="item-1",
        ),
    ]


class SuccessfulFileMaker:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, str, dict[str, Any]]] = []
        self.deleted: list[tuple[str, str]] = []
        self.existing_header: dict[str, Any] | None = None
        self.linked_bom_id = ""

    async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
        del offset, sort
        if layout == "訂單 發料單":
            return {
                "data": [
                    {
                        "recordId": "order-read-1",
                        "fieldData": {
                            "id": "PI-001",
                            "公司": "",
                            "訂單概要中文": "NB001 零件包",
                            "日期": "07/25/2026",
                            "內部訂單單據編號": "NB001",
                        },
                    }
                ],
                "foundCount": 1,
            }
        if layout == "web_BOM计算":
            return {
                "data": [
                    {
                        "recordId": "order-write-1",
                        "fieldData": {
                            "id": "PI-001",
                            "ID_BOM計算": self.linked_bom_id,
                        },
                    }
                ],
                "foundCount": 1,
            }
        if layout == "訂單 計算單_精簡":
            if self.existing_header:
                return {"data": [self.existing_header], "foundCount": 1}
            return {"data": [], "foundCount": 0}
        if layout == "出貨單資料_List_業務":
            return {
                "data": [
                    {
                        "recordId": "shipment-item-1",
                        "fieldData": {
                            "ID": "item-1",
                            "ID_出貨單": "PI-001",
                            "產品編號": "P-100",
                            "數量": "2",
                        },
                    },
                    {
                        "recordId": "shipment-item-2",
                        "fieldData": {
                            "ID": "item-2",
                            "ID_出貨單": "PI-001",
                            "產品編號": "P-200",
                            "數量": "3",
                        },
                    },
                ],
                "foundCount": 2,
            }
        if layout == "零件 資料_業務":
            values = [
                str(next(iter(criteria.values()))).removeprefix("==")
                for criteria in query
            ]
            return {
                "data": [
                    {"recordId": f"part-{value}", "fieldData": {"part_number": value}}
                    for value in dict.fromkeys(values)
                ],
                "foundCount": len(set(values)),
            }
        if layout == "@product_bom":
            product_sku = str(next(iter(query.values()))).removeprefix("==")
            rows = {
                "P-100": [
                    {
                        "recordId": "bom-1",
                        "fieldData": {
                            "ID_產品編號": "P-100",
                            "零件編號": "A-001",
                            "加工類": "",
                        },
                    },
                    {
                        "recordId": "bom-2",
                        "fieldData": {
                            "ID_產品編號": "P-100",
                            "零件編號": "M-001",
                            "加工類": "模具",
                            "塑膠用料型號": "ABS",
                            "塑膠料一模重量": "12.5",
                        },
                    },
                ],
                "P-200": [
                    {
                        "recordId": "bom-3",
                        "fieldData": {
                            "ID_產品編號": "P-200",
                            "零件編號": "A-001",
                            "加工類": "",
                        },
                    }
                ],
            }.get(product_sku, [])
            return {"data": rows, "foundCount": len(rows)}
        if layout == "@出貨單資料":
            return {
                "data": [
                    {
                        "recordId": "rich-item-1",
                        "fieldData": {
                            "ID_出貨單": "PI-001",
                            "買貨客戶": "Caster Racing",
                        },
                    }
                ],
                "foundCount": 1,
            }
        if layout == "@BOM计算单资料":
            return {
                "data": [
                    {"recordId": "existing-detail", "fieldData": {"ID_BOM計算單": "BOM-OLD"}}
                ],
                "foundCount": 1,
            }
        if layout == "@BOM計算單資料Non":
            return {
                "data": [
                    {"recordId": "existing-summary", "fieldData": {"ID_BOM計算單": "BOM-OLD"}}
                ],
                "foundCount": 1,
            }
        raise AssertionError(f"unexpected find on {layout}")

    async def create_record(self, layout, data):
        self.created.append((layout, data))
        if layout == "訂單 計算單_精簡":
            return {"recordId": "header-1"}
        return {"recordId": f"created-{len(self.created)}"}

    async def get_record(self, layout, record_id):
        assert layout == "訂單 計算單_精簡"
        assert record_id == "header-1"
        return [{"recordId": "header-1", "fieldData": {"id": "BOM-001"}}]

    async def update_record(self, layout, record_id, data):
        self.updated.append((layout, record_id, data))
        if layout == "web_BOM计算" and "ID_BOM計算" in data:
            self.linked_bom_id = str(data["ID_BOM計算"])
        return {"recordId": record_id}

    async def delete_record(self, layout, record_id):
        self.deleted.append((layout, record_id))
        return {"recordId": record_id}


@pytest.mark.asyncio
async def test_create_bom_calculation_matches_original_script_structure() -> None:
    filemaker = SuccessfulFileMaker()

    result = await create_bom_calculation_via_data_api(
        client=filemaker,
        settings=bom_settings(),
        request_id="request-001",
        order_id="PI-001",
        lines=write_lines(),
    )

    assert result["bomCalculationId"] == "BOM-001"
    assert result["detailCount"] == 3
    assert result["partCount"] == 2
    assert result["orderLinked"] is True
    assert filemaker.created[0] == (
        "訂單 計算單_精簡",
        {
            "ID_出庫單": "PI-001",
            "客戶": "Caster Racing",
            "車款": "NB001 零件包",
            "訂單日期": "07/25/2026",
            "訂單編號": "NB001",
        },
    )
    assert filemaker.created[1:4] == [
        (
            "@BOM计算单资料",
            {
                "ID_BOM計算單": "BOM-001",
                "id_零件": "A-001",
                "額定數量": "1",
                "數量": "2",
                "ID_Product": "P-100",
                "product_qty": "2",
                "ID_出貨單資料": "item-1",
            },
        ),
        (
            "@BOM计算单资料",
            {
                "ID_BOM計算單": "BOM-001",
                "id_零件": "A-001",
                "額定數量": "2",
                "數量": "6",
                "ID_Product": "P-200",
                "product_qty": "3",
                "ID_出貨單資料": "item-2",
            },
        ),
        (
            "@BOM计算单资料",
            {
                "ID_BOM計算單": "BOM-001",
                "id_零件": "M-001",
                "額定數量": "0.5",
                "數量": "1",
                "ID_Product": "P-100",
                "product_qty": "2",
                "ID_出貨單資料": "item-1",
            },
        ),
    ]
    assert filemaker.created[4] == (
        "@BOM計算單資料Non",
        {"ID_BOM計算單": "BOM-001", "id_零件": "A-001", "數量": "8"},
    )
    assert filemaker.created[5] == (
        "@BOM計算單資料Non",
        {
            "ID_BOM計算單": "BOM-001",
            "id_零件": "M-001",
            "數量": "1",
            "加工類Local": "模具",
            "塑膠用料型號": "ABS",
            "塑膠一模產品重量Local": "12.5",
        },
    )
    assert filemaker.updated == [
        ("web_BOM计算", "order-write-1", {"ID_BOM計算": "BOM-001"})
    ]
    assert filemaker.deleted == []


@pytest.mark.asyncio
async def test_zero_quantity_bom_definition_is_written_like_original_script() -> None:
    filemaker = SuccessfulFileMaker()
    zero_line = BomCalculationWriteLine(
        partNo="A-001",
        originalPartNo="A-001",
        ratedQty="0",
        quantity="0",
        productSku="P-100",
        productQty="2",
        orderItemId="item-1",
    )

    result = await create_bom_calculation_via_data_api(
        client=filemaker,
        settings=bom_settings(),
        request_id="request-zero",
        order_id="PI-001",
        lines=[zero_line],
    )

    assert result["detailCount"] == 1
    assert result["partCount"] == 1
    assert filemaker.created[1][1]["額定數量"] == "0"
    assert filemaker.created[1][1]["數量"] == "0"
    assert filemaker.created[2][1]["數量"] == "0"


@pytest.mark.asyncio
async def test_existing_complete_bom_is_idempotent_and_repairs_order_link() -> None:
    filemaker = SuccessfulFileMaker()
    filemaker.existing_header = {
        "recordId": "header-old",
        "fieldData": {"id": "BOM-OLD", "ID_出庫單": "PI-001"},
    }

    result = await create_bom_calculation_via_data_api(
        client=filemaker,
        settings=bom_settings(),
        request_id="request-002",
        order_id="PI-001",
        lines=write_lines(),
    )

    assert result["duplicate"] is True
    assert result["bomCalculationId"] == "BOM-OLD"
    assert filemaker.created == []
    assert filemaker.updated == [
        ("web_BOM计算", "order-write-1", {"ID_BOM計算": "BOM-OLD"})
    ]


@pytest.mark.asyncio
async def test_failure_rolls_back_header_and_created_details() -> None:
    class FailingFileMaker(SuccessfulFileMaker):
        async def create_record(self, layout, data):
            if layout == "@BOM计算单资料" and len(
                [item for item in self.created if item[0] == layout]
            ) == 1:
                raise RuntimeError("detail write failed")
            return await super().create_record(layout, data)

    filemaker = FailingFileMaker()

    with pytest.raises(RuntimeError, match="detail write failed"):
        await create_bom_calculation_via_data_api(
            client=filemaker,
            settings=bom_settings(),
            request_id="request-003",
            order_id="PI-001",
            lines=write_lines(),
        )

    assert filemaker.updated == []
    assert filemaker.deleted == [
        ("@BOM计算单资料", "created-2"),
        ("訂單 計算單_精簡", "header-1"),
    ]

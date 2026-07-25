import pytest

from app.services.product_api import enrich_product_record


@pytest.mark.asyncio
async def test_enrich_product_record_reads_only_api_layouts() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.layouts: list[str] = []

        async def find_records(self, layout, query=None, limit=100):
            self.layouts.append(layout)
            if layout == "@product_bom":
                assert query == {"ID_產品編號": "==P-1"}
                return {
                    "data": [{
                        "recordId": "21",
                        "modId": "2",
                        "fieldData": {
                            "ID_產品編號": "P-1",
                            "零件編號": "A-1",
                            "日期": "07/18/2026",
                            "廠商": "Vendor A",
                        },
                    }],
                    "foundCount": 1,
                    "returnedCount": 1,
                }
            assert layout == "@產品售價"
            assert query == [{"產品編號": "==P-1"}, {"產品編號": "==SYS-1"}]
            return {
                "data": [{
                    "recordId": "31",
                    "fieldData": {"產品編號": "P-1", "Price": 1.9},
                }],
                "foundCount": 1,
                "returnedCount": 1,
            }

    filemaker = FakeFileMaker()
    enriched = await enrich_product_record(filemaker, {
        "recordId": "10",
        "fieldData": {
            "product_sku": "P-1",
            "系統產品編號": "SYS-1",
        },
    })

    assert sorted(filemaker.layouts) == ["@product_bom", "@產品售價"]
    assert enriched["fieldData"]["產品售價::Price"] == 1.9
    assert enriched["fieldData"]["產品 BOM::日期"] == "07/18/2026"
    assert enriched["fieldData"]["產品 BOM::廠商"] == "Vendor A"
    assert enriched["portalData"]["@product_bom"][0]["零件編號"] == "A-1"
    assert enriched["portalData"]["@產品售價"][0]["Price"] == 1.9

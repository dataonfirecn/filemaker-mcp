import pytest

from app.api.inventory import build_inventory_response, get_product_inventory
from app.services.audit_log import OperatorContext


def _inventory_result():
    return {
        "data": [
            {
                "recordId": "3",
                "fieldData": {
                    "ID_產品編號": "P-1",
                    "日期": "07/14/2026",
                    "批號": "NB-3",
                    "描述": "采购入库",
                    "入庫數量": "50",
                    "出庫數量": "",
                },
            },
            {
                "recordId": "1",
                "fieldData": {
                    "ID_產品編號": "P-1",
                    "日期": "03/01/2023",
                    "批號": "NB-1",
                    "描述": "首次入库",
                    "入庫數量": "100",
                    "出庫數量": "",
                    "記錄人": "amy",
                },
            },
            {
                "recordId": "2",
                "fieldData": {
                    "ID_產品編號": "P-1",
                    "日期": "03/15/2023",
                    "批號": "NB-1",
                    "描述": "生产领料出库",
                    "入庫數量": "",
                    "出庫數量": "100",
                },
            },
        ],
        "foundCount": 3,
        "returnedCount": 3,
    }


def test_build_inventory_response_calculates_summary_and_running_balance() -> None:
    response = build_inventory_response(
        "P-1",
        _inventory_result(),
        {"data": [{"fieldData": {"stock": "50"}}]},
    )

    assert response.summary.current_stock == 50
    assert response.summary.inbound_total == 150
    assert response.summary.outbound_total == 100
    assert response.summary.net_change == 50
    assert [row.date for row in response.rows] == ["2026-07-14", "2023-03-15", "2023-03-01"]
    assert [point.balance for point in response.trend] == [100, 0, 50]
    assert response.rows[-1].operator == "amy"
    assert response.read_only is True


@pytest.mark.asyncio
async def test_get_product_inventory_reads_only_expected_layouts() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100, offset=1):
            self.calls.append((layout, query, limit, offset))
            if layout == "產品庫存_TRANSACTION":
                return _inventory_result()
            return {"data": [{"fieldData": {"stock": "50"}}], "foundCount": 1, "returnedCount": 1}

    class FakeAuditLog:
        def __init__(self) -> None:
            self.entries = []

        async def record(self, **entry):
            self.entries.append(entry)

    filemaker = FakeFileMaker()
    audit_log = FakeAuditLog()
    operator = OperatorContext(session_id="s-1", account="amy", name="Amy", privilege="dev")

    response = await get_product_inventory(" P-1 ", filemaker, audit_log, operator)

    assert ("產品庫存_TRANSACTION", {"ID_產品編號": "==P-1"}, 500, 1) in filemaker.calls
    assert ("@products", {"product_sku": "==P-1"}, 1, 1) in filemaker.calls
    assert response.found_count == 3
    assert audit_log.entries[0]["action_type"] == "READ_PRODUCT_INVENTORY"

import pytest

from app.api.orders import _find_all_order_records, get_internal_orders
from app.core.config import Settings
from app.services.audit_log import OperatorContext


@pytest.mark.asyncio
async def test_find_all_order_records_follows_filemaker_found_count() -> None:
    class PagedFileMaker:
        def __init__(self) -> None:
            self.offsets = []

        async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
            self.offsets.append(offset)
            if offset == 1:
                return {
                    "data": [{"recordId": "1"}, {"recordId": "2"}],
                    "foundCount": 3,
                }
            return {
                "data": [{"recordId": "3"}],
                "foundCount": 3,
            }

    filemaker = PagedFileMaker()

    records, source_found_count = await _find_all_order_records(
        filemaker,
        "訂單 清單_業務",
        {"出貨單_客戶::客戶名稱": "==SARL IMODEL"},
    )

    assert filemaker.offsets == [1, 3]
    assert [record["recordId"] for record in records] == ["1", "2", "3"]
    assert source_found_count == 3


@pytest.mark.asyncio
async def test_get_internal_orders_joins_business_order_fields() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
            self.calls.append((layout, query, limit, offset, sort))
            if layout == "訂單 清單_業務":
                return {
                    "data": [
                        {
                            "recordId": "17452",
                            "fieldData": {
                                "internal_id": "NB25828-9674",
                                "訂單分類": "内部订单",
                                "訂單確認": "内部订单",
                                "訂單概要中文": "DRIFT RTR",
                                "貨款總和": "58275",
                                "包裝狀態": "还没好",
                                "已過天數": "325 天",
                                "出貨單_客戶::客戶名稱": "SARL IMODEL",
                            },
                        }
                    ],
                    "foundCount": 1,
                }
            if layout == "@出貨單":
                return {
                    "data": [
                        {
                            "recordId": "17452",
                            "fieldData": {
                                "id": "PI0017287",
                                "出貨單 PI": "QO-IM20250828 DRIFT RTR",
                                "訂單 PO": "PC000872",
                                "internal_id": "NB25828-9674",
                                "修改日期": "07/18/2026",
                            },
                        }
                    ]
                }
            return {
                "data": [
                    {
                        "recordId": "17452",
                        "fieldData": {
                            "internal_id": "NB25828-9674",
                            "日期": "08/28/2025",
                            "總和": "58275",
                            "付款狀態": "未收款",
                        },
                    }
                ]
            }

    class FakeAuditLog:
        def __init__(self) -> None:
            self.entries = []

        async def record(self, **entry):
            self.entries.append(entry)

    filemaker = FakeFileMaker()
    audit_log = FakeAuditLog()
    operator = OperatorContext(session_id="s-1", account="amy", name="Amy", privilege="dev")

    response = await get_internal_orders(
        session_context={"customerId": "CU004", "customerName": "SARL IMODEL", "currency": "USD"},
        operator=operator,
        client=filemaker,
        audit_log=audit_log,
        settings=Settings(),
    )

    assert filemaker.calls[0][0] == "訂單 清單_業務"
    assert filemaker.calls[0][1] == {
        "出貨單_客戶::客戶名稱": "==SARL IMODEL",
        "訂單分類": "==内部订单",
    }
    assert [call[0] for call in filemaker.calls] == ["訂單 清單_業務", "@出貨單", "訂單 清單"]
    assert response["customerId"] == "CU004"
    assert response["scope"] == "internal"
    assert response["foundCount"] == 1
    assert response["sourceFoundCount"] == 1
    assert response["unmergeableCount"] == 0
    assert response["truncated"] is False
    assert response["rows"][0] == {
        "orderId": "PI0017287",
        "recordId": "17452",
        "internalOrderNo": "NB25828-9674",
        "piNo": "QO-IM20250828 DRIFT RTR",
        "customerPo": "PC000872",
        "orderDate": "08/28/2025",
        "amount": 58275.0,
        "summary": "DRIFT RTR",
        "orderCategory": "内部订单",
        "orderConfirmation": "内部订单",
        "tags": ["内部订单"],
        "packagingStatus": "还没好",
        "paymentStatus": "未收款",
        "elapsedDays": "325 天",
        "customerName": "SARL IMODEL",
    }
    assert audit_log.entries[0]["action_type"] == "READ_INTERNAL_ORDERS"
    assert audit_log.entries[0]["request_payload"]["scope"] == "internal"


@pytest.mark.asyncio
async def test_get_internal_orders_all_scope_does_not_force_category() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
            self.calls.append((layout, query, limit, offset, sort))
            if layout == "訂單 清單_業務":
                return {
                    "data": [
                        {
                            "recordId": "17500",
                            "fieldData": {
                                "internal_id": "NB260001",
                                "訂單分類": "报价单",
                                "出貨單_客戶::客戶名稱": "SARL IMODEL",
                            },
                        }
                    ]
                }
            if layout == "@出貨單":
                return {
                    "data": [
                        {
                            "recordId": "17500",
                            "fieldData": {
                                "id": "PI0018000",
                                "internal_id": "NB260001",
                            },
                        }
                    ]
                }
            return {"data": []}

    class FakeAuditLog:
        def __init__(self) -> None:
            self.entries = []

        async def record(self, **entry):
            self.entries.append(entry)

    filemaker = FakeFileMaker()
    audit_log = FakeAuditLog()
    operator = OperatorContext(session_id="s-1", account="amy", name="Amy", privilege="dev")

    response = await get_internal_orders(
        scope="all",
        session_context={"customerId": "CU004", "customerName": "SARL IMODEL", "currency": "USD"},
        operator=operator,
        client=filemaker,
        audit_log=audit_log,
        settings=Settings(),
    )

    assert filemaker.calls[0][1] == {
        "出貨單_客戶::客戶名稱": "==SARL IMODEL",
    }
    assert response["scope"] == "all"
    assert response["foundCount"] == 1
    assert response["sourceFoundCount"] == 1
    assert response["unmergeableCount"] == 0
    assert response["rows"][0]["orderCategory"] == "报价单"
    assert response["rows"][0]["tags"] == ["报价单"]
    assert audit_log.entries[0]["action_type"] == "READ_CUSTOMER_ORDERS"
    assert audit_log.entries[0]["request_payload"]["scope"] == "all"


@pytest.mark.asyncio
async def test_get_internal_orders_requires_customer_name() -> None:
    class UnexpectedFileMaker:
        async def find_records(self, *args, **kwargs):
            raise AssertionError("FileMaker must not be queried without a customer")

    class FakeAuditLog:
        async def record(self, **entry):
            raise AssertionError("No audit read should be recorded")

    operator = OperatorContext(session_id="s-1", account="amy", name="Amy")

    with pytest.raises(Exception) as exc:
        await get_internal_orders({}, operator, UnexpectedFileMaker(), FakeAuditLog(), Settings())

    assert getattr(exc.value, "status_code", None) == 400

import pytest
from fastapi import HTTPException

from app.api.orders import InternalOrderWebMergeRequest, merge_internal_orders_web
from app.core.config import Settings
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.internal_order_merge import (
    merge_internal_orders_via_data_api,
    preview_internal_orders_via_data_api,
)


def merge_settings() -> Settings:
    return Settings(
        filemaker_web_merge_enabled=True,
        filemaker_web_merge_order_date_field="",
    )


class SuccessfulFileMaker:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.updated: list[tuple[str, str, dict]] = []
        self.deleted: list[tuple[str, str]] = []

    async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
        query_fields = {next(iter(item)) for item in (query or [])}
        if layout == "@出貨單" and query_fields == {"id"}:
            return {
                "data": [
                    {"recordId": "source-1", "fieldData": {"id": "PI-1", "internal_id": "NB001", "customer_id": "CU004"}},
                    {"recordId": "source-2", "fieldData": {"id": "PI-2", "internal_id": "NB002", "customer_id": "CU004"}},
                ],
                "foundCount": 2,
            }
        if layout == "@出貨單":
            return {"data": [], "foundCount": 0}
        if layout == "@products":
            return {
                "data": [
                    {"recordId": "product-1", "fieldData": {"product_sku": "P-100", "product_name": "Buggy"}},
                    {"recordId": "product-2", "fieldData": {"product_sku": "P-200", "product_name": "Motor"}},
                ],
                "foundCount": 2,
            }
        return {
            "data": [
                {"recordId": "item-1", "fieldData": {"ID_出貨單": "PI-1", "產品編號": "P-100", "數量": "2"}},
                {"recordId": "item-2", "fieldData": {"ID_出貨單": "PI-2", "產品編號": "P-100", "數量": "3.5"}},
                {"recordId": "item-3", "fieldData": {"ID_出貨單": "PI-2", "產品編號": "P-200", "數量": "1"}},
            ],
            "foundCount": 3,
        }

    async def create_record(self, layout, data):
        self.created.append((layout, data))
        if layout == "訂單 資料_業務_EDIT":
            return {"recordId": "new-header"}
        return {"recordId": f"new-item-{len(self.created)}"}

    async def update_record(self, layout, record_id, data):
        self.updated.append((layout, record_id, data))
        return {"recordId": record_id}

    async def get_record(self, layout, record_id):
        return [{
            "recordId": record_id,
            "fieldData": {"id": "PI-NEW", "internal_id": "NB261540"},
        }]

    async def delete_record(self, layout, record_id):
        self.deleted.append((layout, record_id))
        return {"recordId": record_id}


@pytest.mark.asyncio
async def test_web_merge_aggregates_items_and_creates_header_and_details() -> None:
    filemaker = SuccessfulFileMaker()

    result = await merge_internal_orders_via_data_api(
        client=filemaker,
        settings=merge_settings(),
        customer_id="CU004",
        customer_name="SARL IMODEL",
        order_ids=["PI-1", "PI-2"],
        request_id="request-001",
        operator_account="amy",
        operator_name="Amy",
    )

    assert result["newOrderId"] == "PI-NEW"
    assert result["newInternalOrderNo"] == "NB261540"
    assert result["sourceOrderCount"] == 2
    assert result["sourceItemCount"] == 3
    assert result["mergedItemCount"] == 2
    assert filemaker.created == [
        ("訂單 資料_業務_EDIT", {"訂單型態": "零件包", "訂單分類": "合併單"}),
        ("出貨單資料_List_業務", {"ID_出貨單": "PI-NEW", "產品編號": "P-100", "數量": "5.5"}),
        ("出貨單資料_List_業務", {"ID_出貨單": "PI-NEW", "產品編號": "P-200", "數量": "1"}),
    ]
    assert filemaker.updated[0] == ("@出貨單", "new-header", {"customer_id": "CU004"})
    assert filemaker.updated[1][0:2] == ("@出貨單", "new-header")
    merge_log = filemaker.updated[1][2]["log"]
    assert "[Web Data API 内部订单合并]" in merge_log
    assert "操作人：Amy (amy)" in merge_log
    assert "客户：SARL IMODEL (CU004)" in merge_log
    assert "新内部订单：NB261540" in merge_log
    assert "来源内部订单：NB001、NB002" in merge_log
    assert "来源订单数：2；原始明细数：3；合并后明细数：2" in merge_log
    assert "1. P-100 | Buggy | 数量 5.5" in merge_log
    assert "2. P-200 | Motor | 数量 1" in merge_log
    assert "请求ID：request-001" in merge_log
    assert result["logWritten"] is True
    assert "ID_DB" not in filemaker.updated[0][2]
    assert "ID_SYNC" not in filemaker.updated[0][2]
    assert filemaker.deleted == []


@pytest.mark.asyncio
async def test_web_merge_preview_returns_merged_shipment_items_without_writing() -> None:
    filemaker = SuccessfulFileMaker()

    result = await preview_internal_orders_via_data_api(
        client=filemaker,
        settings=merge_settings(),
        customer_id="CU004",
        order_ids=["PI-1", "PI-2"],
    )

    assert result == {
        "ok": True,
        "sourceOrderCount": 2,
        "sourceItemCount": 3,
        "mergedItemCount": 2,
        "items": [
            {"productNo": "P-100", "productName": "Buggy", "quantity": "5.5"},
            {"productNo": "P-200", "productName": "Motor", "quantity": "1"},
        ],
    }
    assert filemaker.created == []
    assert filemaker.updated == []
    assert filemaker.deleted == []


@pytest.mark.asyncio
async def test_web_merge_idempotency_is_stored_outside_filemaker() -> None:
    store = AuditLogStore("memory://")
    first = await store.claim_web_merge_request(
        request_id="request-001",
        customer_id="CU004",
        source_order_ids=["PI-2", "PI-1"],
    )
    assert first == {"status": "claimed"}

    result = {"newOrderId": "PI-NEW", "headerRecordId": "new-header", "duplicate": False}
    await store.complete_web_merge_request(request_id="request-001", response_payload=result)
    duplicate = await store.claim_web_merge_request(
        request_id="request-001",
        customer_id="CU004",
        source_order_ids=["PI-1", "PI-2"],
    )

    assert duplicate == {"status": "duplicate", "result": result}


@pytest.mark.asyncio
async def test_web_merge_rejects_cross_customer_orders_before_writing() -> None:
    filemaker = SuccessfulFileMaker()
    original_find = filemaker.find_records

    async def mismatched_find(layout, query=None, limit=100, offset=1, sort=None):
        result = await original_find(layout, query, limit, offset, sort)
        if layout == "@出貨單" and {next(iter(item)) for item in (query or [])} == {"id"}:
            result["data"][1]["fieldData"]["customer_id"] = "99"
        return result

    filemaker.find_records = mismatched_find

    with pytest.raises(Exception) as exc:
        await merge_internal_orders_via_data_api(
            client=filemaker,
            settings=merge_settings(),
            customer_id="CU004",
            customer_name="SARL IMODEL",
            order_ids=["PI-1", "PI-2"],
            request_id="request-002",
        )

    assert getattr(exc.value, "status_code", None) == 403
    assert filemaker.created == []


@pytest.mark.asyncio
async def test_web_merge_rolls_back_created_records_when_detail_write_fails() -> None:
    class FailingFileMaker(SuccessfulFileMaker):
        async def create_record(self, layout, data):
            if layout != "訂單 資料_業務_EDIT" and len(self.created) == 2:
                raise RuntimeError("detail write failed")
            return await super().create_record(layout, data)

    filemaker = FailingFileMaker()

    with pytest.raises(RuntimeError, match="detail write failed"):
        await merge_internal_orders_via_data_api(
            client=filemaker,
            settings=merge_settings(),
            customer_id="CU004",
            customer_name="SARL IMODEL",
            order_ids=["PI-1", "PI-2"],
            request_id="request-003",
        )

    assert filemaker.deleted == [
        ("出貨單資料_List_業務", "new-item-2"),
        ("訂單 資料_業務_EDIT", "new-header"),
    ]


@pytest.mark.asyncio
async def test_web_merge_endpoint_is_independently_feature_gated() -> None:
    class UnexpectedAudit:
        async def record(self, **entry):
            raise AssertionError("disabled endpoint must not write an audit success record")

    with pytest.raises(HTTPException) as exc:
        await merge_internal_orders_web(
            InternalOrderWebMergeRequest(orderIds=["PI-1", "PI-2"], requestId="request-004"),
            {"customerId": "CU004", "customerName": "SARL IMODEL"},
            OperatorContext(session_id="s-1", account="amy", name="Amy"),
            SuccessfulFileMaker(),
            UnexpectedAudit(),
            Settings(filemaker_read_only=True, filemaker_web_merge_enabled=False),
        )

    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_web_merge_endpoint_reuses_backend_idempotency_result() -> None:
    filemaker = SuccessfulFileMaker()
    audit = AuditLogStore("memory://")
    operator = OperatorContext(session_id="s-1", account="amy", name="Amy")
    body = InternalOrderWebMergeRequest(
        orderIds=["PI-1", "PI-2"],
        requestId="request-005",
    )
    context = {"customerId": "CU004", "customerName": "SARL IMODEL"}

    first = await merge_internal_orders_web(
        body,
        context,
        operator,
        filemaker,
        audit,
        merge_settings(),
    )
    second = await merge_internal_orders_web(
        body,
        context,
        operator,
        filemaker,
        audit,
        merge_settings(),
    )

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert len(filemaker.created) == 3

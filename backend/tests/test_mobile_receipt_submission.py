from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api.mobile_receipts import submit_receipt_lines
from app.core.config import Settings
from app.models.mobile_receipts import ReceiptSubmissionRequest
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.receipt_attachment_store import ReceiptAttachmentStore
from app.services.mobile_receipt_trace import parse_mobile_receipt_trace


class FakeFileMaker:
    def __init__(self) -> None:
        self.lines = [
            {
                "recordId": "42001",
                "fieldData": {
                    "ID": "LINE-1",
                    "ID_出貨單": "PI0019694",
                    "產品編號": "PTK-4528",
                    "數量": 10,
                    "實際包裝數量": "",
                },
            },
            {
                "recordId": "42002",
                "fieldData": {
                    "ID": "LINE-2",
                    "ID_出貨單": "PI0019694",
                    "產品編號": "PTK-4562",
                    "數量": 20,
                    "實際包裝數量": "",
                },
            },
        ]

    async def find_records(self, layout, query=None, **_kwargs):
        if layout == "@出貨單":
            return {
                "data": [
                    {
                        "recordId": "19859",
                        "fieldData": {"id": "PI0019694"},
                    }
                ]
            }
        if layout == "@出貨單資料":
            if isinstance(query, list):
                requested = {
                    str(criteria["ID"]).removeprefix("==")
                    for criteria in query
                }
                return {
                    "data": [
                        row
                        for row in self.lines
                        if row["fieldData"]["ID"] in requested
                    ]
                }
            return {"data": list(self.lines)}
        raise AssertionError(f"Unexpected layout: {layout}")


class FakeOData:
    def __init__(self) -> None:
        self.receipts: dict[str, dict] = {}
        self.inbound_orders: dict[str, dict] = {}
        self.inbound_order_lines: dict[str, dict] = {}
        self.inventory: list[dict] = []
        self.source_updates: dict[str, dict] = {}
        self.created_receipt_count = 0

    async def records(self, table, *, filter_expr=None, **_kwargs):
        value = _quoted_value(filter_expr or "")
        if table == "出貨單資料入庫":
            rows = [
                row
                for row in self.receipts.values()
                if row["ID_出庫單資料"] == value
            ]
            return {"rows": rows}
        if table == "產品庫存":
            if (filter_expr or "").startswith("ID_出貨單資料 eq"):
                return {
                    "rows": [
                        row
                        for row in self.inventory
                        if row.get("ID_出貨單資料") == value
                    ]
                }
            return {
                "rows": [
                    row
                    for row in self.inventory
                    if row.get("ID_出貨單資料入庫") == value
                ]
            }
        if table == "入庫單":
            row = self.inbound_orders.get(value)
            return {"rows": [dict(row)] if row else []}
        if table == "入庫單資料":
            row = self.inbound_order_lines.get(value)
            return {"rows": [dict(row)] if row else []}
        raise AssertionError(f"Unexpected table: {table}")

    async def create_record(self, table, data):
        if table == "出貨單資料入庫":
            self.created_receipt_count += 1
            receipt_id = f"RECEIPT-{self.created_receipt_count}"
            row = {
                "ID": receipt_id,
                "创建时间戳": "2026-07-31T06:00:00Z",
                "创建人": "service",
                **data,
            }
            self.receipts[receipt_id] = row
            return row
        if table == "產品庫存":
            self.inventory.append(dict(data))
            return dict(data)
        if table == "入庫單":
            self.inbound_orders[data["ID"]] = dict(data)
            return dict(data)
        if table == "入庫單資料":
            self.inbound_order_lines[data["ID"]] = dict(data)
            return dict(data)
        raise AssertionError(f"Unexpected create table: {table}")

    async def update_record(self, table, key, data):
        if table == "出貨單資料入庫":
            self.receipts[key].update(data)
            return dict(self.receipts[key])
        if table == "出貨單資料":
            self.source_updates[key] = dict(data)
            return dict(data)
        raise AssertionError(f"Unexpected update table: {table}")

    async def get_record(self, table, key):
        if table == "出貨單資料入庫":
            return dict(self.receipts[key])
        if table == "入庫單":
            return dict(self.inbound_orders.get(key, {}))
        if table == "入庫單資料":
            return dict(self.inbound_order_lines.get(key, {}))
        raise AssertionError(f"Unexpected get table: {table}")


def _quoted_value(filter_expr: str) -> str:
    return filter_expr.split("'", 2)[1] if "'" in filter_expr else ""


def _request(quantity: int = 12) -> ReceiptSubmissionRequest:
    return ReceiptSubmissionRequest(
        draftId="draft-1",
        shipmentId="PI0019694",
        documentNumber="NB261555",
        piNumber="PI-Amain-20260723",
        receiptRemark="PDA 入库",
        lines=[
            {
                "lineId": "LINE-1",
                "recordId": "42001",
                "sku": "PTK-4528",
                "receivedQuantity": quantity,
                "expectedQuantity": 10,
                "remark": "MOQ 多包装 2 个",
                "attachmentIds": [],
            }
        ],
        submittedAt=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_mobile_receipt_splits_order_balance_and_supplemental_inbound() -> None:
    odata = FakeOData()
    audit = AuditLogStore("memory://audit")
    await audit.init()

    response = await submit_receipt_lines(
        body=_request(quantity=12),
        draft_id="draft-1",
        operator=OperatorContext(
            session_id="session-1",
            account="pda",
            name="PDA 测试用户",
        ),
        settings=Settings(filemaker_mobile_receipt_write_enabled=True),
        filemaker=FakeFileMaker(),
        odata=odata,
        attachment_store=ReceiptAttachmentStore("memory://attachments"),
        audit_log=audit,
        access={"canAddCompletedReceipts": True},
    )

    assert response.status == "partial"
    assert response.all_lines_received is False
    assert response.received_line_count == 1
    assert response.total_line_count == 2
    assert response.lines[0].receipt_id == "RECEIPT-1"
    assert response.lines[0].quantity == 12
    assert response.lines[0].routing_mode == "split"
    assert response.lines[0].order_receipt_quantity == 10
    assert response.lines[0].supplemental_quantity == 2
    assert response.lines[0].inbound_order_id in odata.inbound_orders
    assert response.lines[0].inbound_order_line_id in odata.inbound_order_lines
    assert response.lines[0].received_by == "PDA 测试用户"
    assert odata.receipts["RECEIPT-1"]["ID_出庫單資料"] == "LINE-1"
    assert odata.receipts["RECEIPT-1"]["數量"] == 10
    assert odata.source_updates["LINE-1"]["實際包裝數量"] == 10
    assert [row["入庫數量"] for row in odata.inventory] == [10, 2]
    assert odata.inventory[0]["ID_出貨單資料入庫"] == "RECEIPT-1"
    assert "ID_出貨單資料入庫" not in odata.inventory[1]
    assert "PDA_INBOUND_LINE=" in odata.inventory[1]["描述"]
    assert "PDA_DRAFT=draft-1" in odata.inventory[1]["描述"]
    assert "PDA_SUBMITTED=12" in odata.inventory[1]["描述"]
    assert "PDA_ORDER=10" in odata.inventory[1]["描述"]
    assert "PDA_SUPPLEMENTAL=2" in odata.inventory[1]["描述"]
    trace = parse_mobile_receipt_trace(odata.receipts["RECEIPT-1"]["log"])
    assert trace is not None
    assert trace["identifiers"]["draftId"] == "draft-1"
    assert trace["routing"] == {
        "mode": "split",
        "submittedQuantity": 12,
        "orderReceiptQuantity": 10,
        "supplementalQuantity": 2,
    }


@pytest.mark.asyncio
async def test_mobile_receipt_retry_returns_existing_record_without_duplicate() -> None:
    odata = FakeOData()
    audit = AuditLogStore("memory://audit")
    await audit.init()
    kwargs = {
        "body": _request(),
        "draft_id": "draft-1",
        "operator": OperatorContext(
            session_id="session-1",
            account="pda",
            name="PDA 测试用户",
        ),
        "settings": Settings(filemaker_mobile_receipt_write_enabled=True),
        "filemaker": FakeFileMaker(),
        "odata": odata,
        "attachment_store": ReceiptAttachmentStore("memory://attachments"),
        "audit_log": audit,
        "access": {"canAddCompletedReceipts": True},
    }

    await submit_receipt_lines(**kwargs)
    repeated = await submit_receipt_lines(**kwargs)

    assert odata.created_receipt_count == 1
    assert len(odata.inventory) == 2
    assert repeated.lines[0].already_received is True


@pytest.mark.asyncio
async def test_supplemental_inbound_requires_completed_receipt_permission() -> None:
    odata = FakeOData()
    audit = AuditLogStore("memory://audit")
    await audit.init()

    with pytest.raises(HTTPException) as error:
        await submit_receipt_lines(
            body=_request(quantity=12),
            draft_id="draft-1",
            operator=OperatorContext(
                session_id="session-1",
                account="pda",
                name="PDA 测试用户",
            ),
            settings=Settings(filemaker_mobile_receipt_write_enabled=True),
            filemaker=FakeFileMaker(),
            odata=odata,
            attachment_store=ReceiptAttachmentStore("memory://attachments"),
            audit_log=audit,
            access={},
        )

    assert error.value.status_code == 403
    assert not odata.receipts
    assert not odata.inbound_orders
    assert not odata.inventory


@pytest.mark.asyncio
async def test_supplemental_inbound_requires_a_reason() -> None:
    odata = FakeOData()
    audit = AuditLogStore("memory://audit")
    await audit.init()
    body = _request(quantity=12)
    body = body.model_copy(
        update={
            "receipt_remark": "",
            "lines": [body.lines[0].model_copy(update={"remark": ""})],
        }
    )

    with pytest.raises(HTTPException) as error:
        await submit_receipt_lines(
            body=body,
            draft_id="draft-1",
            operator=OperatorContext(
                session_id="session-1",
                account="pda",
                name="PDA 测试用户",
            ),
            settings=Settings(filemaker_mobile_receipt_write_enabled=True),
            filemaker=FakeFileMaker(),
            odata=odata,
            attachment_store=ReceiptAttachmentStore("memory://attachments"),
            audit_log=audit,
            access={"canAddCompletedReceipts": True},
        )

    assert error.value.status_code == 422
    assert not odata.receipts
    assert not odata.inbound_orders
    assert not odata.inventory


@pytest.mark.asyncio
async def test_mixed_batch_reuses_one_inbound_order_for_multiple_supplements() -> None:
    odata = FakeOData()
    odata.receipts["RECEIPT-EXISTING"] = {
        "ID": "RECEIPT-EXISTING",
        "ID_出庫單資料": "LINE-1",
        "日期": "2026-08-23",
        "數量": 10,
        "狀態": "已入庫",
        "创建时间戳": "2026-08-23T08:00:00Z",
        "创建人": "service",
    }
    audit = AuditLogStore("memory://audit")
    await audit.init()
    body = ReceiptSubmissionRequest(
        draftId="draft-mixed",
        shipmentId="PI0019694",
        documentNumber="NB261555",
        piNumber="PI-Amain-20260723",
        receiptRemark="混合批量测试",
        lines=[
            {
                "lineId": "LINE-1",
                "recordId": "42001",
                "sku": "PTK-4528",
                "receivedQuantity": 3,
                "expectedQuantity": 10,
                "remark": "补发到货",
                "attachmentIds": [],
            },
            {
                "lineId": "LINE-2",
                "recordId": "42002",
                "sku": "PTK-4562",
                "receivedQuantity": 25,
                "expectedQuantity": 20,
                "remark": "多包装",
                "attachmentIds": [],
            },
        ],
        submittedAt=datetime.now(timezone.utc),
    )

    response = await submit_receipt_lines(
        body=body,
        draft_id="draft-mixed",
        operator=OperatorContext(
            session_id="session-1",
            account="pda",
            name="PDA 测试用户",
        ),
        settings=Settings(filemaker_mobile_receipt_write_enabled=True),
        filemaker=FakeFileMaker(),
        odata=odata,
        attachment_store=ReceiptAttachmentStore("memory://attachments"),
        audit_log=audit,
        access={"canAddCompletedReceipts": True},
    )

    assert response.status == "sealed"
    assert [line.routing_mode for line in response.lines] == [
        "supplemental_inbound",
        "split",
    ]
    assert [line.order_receipt_quantity for line in response.lines] == [0, 20]
    assert [line.supplemental_quantity for line in response.lines] == [3, 5]
    assert len(odata.inbound_orders) == 1
    assert len(odata.inbound_order_lines) == 2
    assert {
        line.inbound_order_id for line in response.lines
    } == set(odata.inbound_orders)
    assert odata.source_updates == {"LINE-2": {"實際包裝數量": 20}}
    assert [row["入庫數量"] for row in odata.inventory] == [3, 20, 5]

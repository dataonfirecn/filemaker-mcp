from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.api.mobile_receipts import submit_receipt_lines
from app.core.config import Settings
from app.models.mobile_receipts import ReceiptSubmissionRequest
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.receipt_attachment_store import ReceiptAttachmentStore


class FakeFileMaker:
    def __init__(self) -> None:
        self.lines = [
            {
                "recordId": "42001",
                "fieldData": {
                    "ID": "LINE-1",
                    "ID_出貨單": "PI0019694",
                    "產品編號": "PTK-4528",
                    "實際包裝數量": "",
                },
            },
            {
                "recordId": "42002",
                "fieldData": {
                    "ID": "LINE-2",
                    "ID_出貨單": "PI0019694",
                    "產品編號": "PTK-4562",
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
            return {
                "rows": [
                    row
                    for row in self.inventory
                    if row["ID_出貨單資料入庫"] == value
                ]
            }
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
async def test_mobile_receipt_writes_traceable_partial_line_and_allows_overage() -> None:
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
    )

    assert response.status == "partial"
    assert response.all_lines_received is False
    assert response.received_line_count == 1
    assert response.total_line_count == 2
    assert response.lines[0].receipt_id == "RECEIPT-1"
    assert response.lines[0].quantity == 12
    assert response.lines[0].received_by == "PDA 测试用户"
    assert odata.receipts["RECEIPT-1"]["ID_出庫單資料"] == "LINE-1"
    assert odata.source_updates["LINE-1"]["實際包裝數量"] == 12
    assert odata.inventory == [
        {
            "ID_出貨單資料": "LINE-1",
            "ID_出貨單資料入庫": "RECEIPT-1",
            "批號": "NB261555",
            "描述": "MOQ 多包装 2 个 · PDA 入库",
            "ID_產品編號": "PTK-4528",
            "入庫數量": 12,
            "日期": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
            "記錄人": "PDA 测试用户",
        }
    ]


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
    }

    await submit_receipt_lines(**kwargs)
    repeated = await submit_receipt_lines(**kwargs)

    assert odata.created_receipt_count == 1
    assert len(odata.inventory) == 1
    assert repeated.lines[0].already_received is True

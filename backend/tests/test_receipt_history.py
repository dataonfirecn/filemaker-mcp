from datetime import datetime, timezone
import json

import pytest
from fastapi import HTTPException, Request

from app.api.receipt_history import get_receipt_history
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.receipt_attachment_store import (
    ReceiptAttachmentRecord,
    ReceiptAttachmentStore,
)
from app.services.webviewer_session import create_mock_context, issue_session_token
from app.core.config import Settings
from app.services.dependencies import _permission_for_request


LINE_ID = "A8E29F9C-ACCD-4598-855B-9FB440AFA44A"
RECEIPT_ID = "F7AE08FD-7200-4357-8130-377D4345A58C"


def test_receipt_history_line_id_is_bound_into_webviewer_session() -> None:
    context = create_mock_context(
        operator_account="amy",
        operator_name="Amy",
        line_id=LINE_ID,
    )
    _token, payload = issue_session_token(
        context,
        Settings(webviewer_context_secret="receipt-history-secret"),
    )

    assert payload["lineId"] == LINE_ID


def test_receipt_history_endpoint_requires_order_view_permission() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": f"/api/orders/receipt-history/{LINE_ID}",
            "raw_path": f"/api/orders/receipt-history/{LINE_ID}".encode(),
            "query_string": b"",
            "headers": [],
            "scheme": "https",
            "server": ("testserver", 443),
            "client": ("testclient", 50000),
        }
    )

    assert _permission_for_request(request) == "canViewOrders"


class FakeOData:
    async def request(self, path, **_kwargs):
        assert LINE_ID in path
        return {
            "ID": LINE_ID,
            "ID_出貨單": "PI0019694",
            "產品編號": "PTK-4528",
            "數量": 10,
            "實際包裝數量": 12,
            "公司名稱": "Caster Racing",
            "包裝進度": "包好",
            "包裝員": "505",
            "created_at": "2026-07-23T08:47:15Z",
            "updated_at": "2026-07-27T10:41:18Z",
        }

    async def records(self, table, **_kwargs):
        if table == "出貨單資料入庫":
            return {
                "rows": [
                    {
                        "ID": RECEIPT_ID,
                        "ID_出庫單資料": LINE_ID,
                        "日期": "2026-07-27",
                        "數量": 12,
                        "狀態": "已入庫",
                        "创建时间戳": "2026-07-27T10:29:24Z",
                        "创建人": "dataonfire",
                        "修改时间戳": "2026-07-27T10:29:24Z",
                        "修改人": "dataonfire",
                        "log": json.dumps({
                            "schema": "starrc.finished-goods-receipt",
                            "schemaVersion": 1,
                            "source": {"channel": "ios-pda"},
                            "operator": {"account": "pda", "name": "PDA 测试员"},
                            "identifiers": {"lineId": LINE_ID, "receiptId": RECEIPT_ID},
                            "attachments": {},
                        }),
                    }
                ]
            }
        if table == "產品庫存":
            return {
                "rows": [
                    {
                        "@id": "https://example.test/產品庫存(85136)",
                        "ID_出貨單資料": LINE_ID,
                        "ID_出貨單資料入庫": RECEIPT_ID,
                        "ID_產品編號": "PTK-4528",
                        "日期": "2026-07-27",
                        "批號": "NB261555",
                        "入庫數量": 12,
                        "記錄人": "PDA 测试员",
                    }
                ]
            }
        raise AssertionError(table)


class FakeFileMaker:
    async def find_records(self, layout, **_kwargs):
        if layout == "@出貨單":
            return {
                "data": [
                    {
                        "fieldData": {
                            "id": "PI0019694",
                            "internal_id": "NB261555",
                            "出貨單 PI": "PI-Amain-20260723",
                            "訂單 PO": "PO-TEST",
                        }
                    }
                ]
            }
        if layout == "@products":
            return {
                "data": [
                    {
                        "fieldData": {
                            "product_sku": "PTK-4528",
                            "產品名稱_中文": "启动齿皮带",
                            "product_name": "Replacement Belt",
                            "stock": 12,
                        }
                    }
                ]
            }
        raise AssertionError(layout)


class FakeStorage:
    configured = False


@pytest.mark.asyncio
async def test_receipt_history_returns_detailed_traceable_chain() -> None:
    attachments = ReceiptAttachmentStore("memory://receipt-history")
    await attachments.create(
        ReceiptAttachmentRecord(
            attachment_id="att_1",
            draft_id="draft-1",
            shipment_id="PI0019694",
            pi_number="PI-Amain-20260723",
            line_id=LINE_ID,
            object_key="receipts/att_1.jpg",
            original_filename="receipt.jpg",
            mime_type="image/jpeg",
            file_size=1024,
            sha256="abc",
            source="camera",
            operator_account="pda",
            status="BOUND",
            etag="etag",
            created_at=datetime(2026, 7, 27, 10, 28, tzinfo=timezone.utc),
            uploaded_at=datetime(2026, 7, 27, 10, 29, tzinfo=timezone.utc),
        )
    )
    audit = AuditLogStore("memory://receipt-history-audit")
    await audit.init()

    response = await get_receipt_history(
        line_id=LINE_ID,
        session_context={"lineId": LINE_ID},
        operator=OperatorContext(
            session_id="session-1",
            account="amy",
            name="Amy",
        ),
        filemaker=FakeFileMaker(),
        odata=FakeOData(),
        attachments=attachments,
        storage=FakeStorage(),
        audit_log=audit,
    )

    assert response.line.line_id == LINE_ID
    assert response.line.document_number == "NB261555"
    assert response.line.product_sku == "PTK-4528"
    assert response.line.current_stock == 12
    assert response.summary.receipt_count == 1
    assert response.summary.official_received_quantity == 12
    assert response.summary.difference_from_order == 2
    assert response.summary.inventory_movement_count == 1
    assert response.summary.photo_count == 1
    assert response.summary.fully_traceable is True
    assert response.receipts[0].received_by == "PDA 测试员"
    assert response.receipts[0].inventory_movements[0].record_key == "85136"
    assert response.photos[0].scope == "product"
    assert response.photos[0].url == ""
    assert len(audit._memory_rows) == 1


@pytest.mark.asyncio
async def test_receipt_history_rejects_line_outside_signed_context() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_receipt_history(
            line_id=LINE_ID,
            session_context={"lineId": "OTHER-LINE"},
            operator=OperatorContext(
                session_id="session-1",
                account="amy",
                name="Amy",
            ),
            filemaker=FakeFileMaker(),
            odata=FakeOData(),
            attachments=ReceiptAttachmentStore("memory://receipt-history"),
            storage=FakeStorage(),
            audit_log=AuditLogStore("memory://receipt-history-audit"),
        )

    assert exc.value.status_code == 403

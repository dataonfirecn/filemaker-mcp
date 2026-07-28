import json

import pytest
from fastapi import HTTPException, Request

from app.api.bom_documents import _calculation_line, _load_product_bom
from app.api.filemaker import (
    ensure_raw_write_permission,
    ensure_write_allowed,
    router as filemaker_router,
)
from app.api.webviewer import create_webviewer_session
from app.core.config import Settings
from app.models.webviewer import WebViewerSessionRequest
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.bom_document_store import BomDocumentStore
from app.services.customer_chat_auth import hash_customer_password
from app.services.dependencies import (
    _permission_for_request,
    get_webviewer_session_context,
)
from app.services.webviewer_session import (
    create_mock_context,
    issue_session_token,
    operator_from_session,
    verify_session_token,
)


class FileMakerSettingsStub:
    filemaker_host = "https://filemaker.example.test"
    filemaker_database = "DMS Database"
    filemaker_username = "api_user"
    filemaker_password = "secret"
    filemaker_api_version = "v2"
    filemaker_token_inactivity_timeout_seconds = 900
    filemaker_timeout_seconds = 30.0
    filemaker_ssl_verify = False

    @property
    def filemaker_configured(self) -> bool:
        return True


def test_filemaker_layout_paths_use_percent_encoding() -> None:
    from app.services.filemaker_client import FileMakerClient

    client = FileMakerClient(FileMakerSettingsStub())
    try:
        assert client._encode_param("發料單 匯總_PC") == "%E7%99%BC%E6%96%99%E5%96%AE%20%E5%8C%AF%E7%B8%BD_PC"
        assert "+" not in client._encode_param("發料單 匯總_PC")
    finally:
        # The test only exercises pure encoding; avoid awaiting close on the fake client.
        pass


def test_webviewer_session_round_trip() -> None:
    settings = Settings(
        webviewer_context_secret="unit-test-secret",
        webviewer_session_ttl_seconds=60,
    )
    context = create_mock_context(
        operator_account="amy",
        operator_name="Amy",
        product_sku="821RTR-27",
        customer_id="CU004",
        customer_name="SARL IMODEL",
        currency="USD",
    )
    token, payload = issue_session_token(context, settings)
    verified = verify_session_token(token, settings)
    operator = operator_from_session(verified)

    assert payload["productSku"] == "821RTR-27"
    assert payload["customerId"] == "CU004"
    assert verified["customerName"] == "SARL IMODEL"
    assert verified["currency"] == "USD"
    assert verified["operator"]["account"] == "amy"
    assert operator.account == "amy"
    assert operator.name == "Amy"


def test_webviewer_session_normalizes_renamed_filemaker_order_id() -> None:
    settings = Settings(
        webviewer_context_secret="unit-test-secret",
        webviewer_session_ttl_seconds=60,
    )
    context = create_mock_context(
        operator_account="amy",
        operator_name="Amy",
    )
    context.pop("orderId")
    context["id"] = "PI0017287"

    token, payload = issue_session_token(context, settings)
    verified = verify_session_token(token, settings)

    assert payload["orderId"] == "PI0017287"
    assert verified["orderId"] == "PI0017287"
    assert "id" not in payload


def test_filemaker_write_guard_blocks_when_read_only() -> None:
    settings = Settings(filemaker_read_only=True)

    with pytest.raises(HTTPException) as exc:
        ensure_write_allowed(settings)

    assert exc.value.status_code == 423


def test_raw_filemaker_router_requires_webviewer_session_and_rag_permission() -> None:
    assert any(
        dependency.dependency is get_webviewer_session_context
        for dependency in filemaker_router.dependencies
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/filemaker/@products/find",
            "raw_path": b"/api/filemaker/@products/find",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )

    assert _permission_for_request(request) == "canManageRag"


def test_raw_filemaker_write_requires_account_admin_in_addition_to_rag_access() -> None:
    with pytest.raises(HTTPException) as exc:
        ensure_raw_write_permission(
            {
                "canManageRag": True,
                "canManageAccounts": False,
            }
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["permission"] == "canManageAccounts"
    ensure_raw_write_permission(
        {
            "canManageRag": True,
            "canManageAccounts": True,
        }
    )


@pytest.mark.asyncio
async def test_remote_webviewer_login_issues_audited_internal_session() -> None:
    password = "Remote-Unit-Test-Password"
    settings = Settings(
        webviewer_context_secret="unit-test-secret",
        webviewer_allow_mock_context=False,
        webviewer_remote_access_enabled=True,
        webviewer_remote_accounts_json=json.dumps(
            [
                {
                    "username": "amy",
                    "displayName": "Amy",
                    "passwordHash": hash_customer_password(password, iterations=100_000),
                }
            ]
        ),
    )
    audit = AuditLogStore("memory://")

    response = await create_webviewer_session(
        WebViewerSessionRequest(
            username="amy",
            password=password,
            customerId="CU004",
            customerName="SARL IMODEL",
        ),
        settings,
        audit,
    )

    assert response.context["operator"]["account"] == "amy"
    assert response.context["operator"]["privilege"] == "internal_remote"
    assert response.context["customerId"] == "CU004"
    assert len(audit._memory_rows) == 1


def test_bom_preview_line_calculates_without_store_write() -> None:
    record = {
        "recordId": "123",
        "fieldData": {
            "零件編號": "AL08045-00",
            "零件名稱": "灵魂车RTR 二楼板-F",
            "需求數量": "1.5",
        },
    }

    line = _calculation_line(record, index=1, generate_qty=100)

    assert line.part_no == "AL08045-00"
    assert line.bom_qty == 1.5
    assert line.calculated_qty == 150


@pytest.mark.asyncio
async def test_order_bom_view_uses_current_filemaker_bom_layout() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, str]]] = []

        async def find_records(self, layout, query=None, limit=100, offset=1):
            self.calls.append((layout, query))
            if layout == "產品清單_業務":
                return {
                    "data": [{
                        "recordId": "10",
                        "fieldData": {
                            "product_sku": "G0107-EVA",
                            "product_name": "EVA",
                        },
                    }],
                    "foundCount": 1,
                    "returnedCount": 1,
                }
            assert layout == "@product_bom"
            return {
                "data": [{
                    "recordId": "20",
                    "fieldData": {
                        "ID_產品編號": "G0107-EVA",
                        "零件編號": "EVA-01",
                        "需求數量": 1,
                    },
                }],
                "foundCount": 1,
                "returnedCount": 1,
            }

    filemaker = FakeFileMaker()
    product, bom = await _load_product_bom(filemaker, "G0107-EVA")

    assert product is not None
    assert product.product_sku == "G0107-EVA"
    assert bom["foundCount"] == 1
    assert filemaker.calls == [
        ("產品清單_業務", {"product_sku": "==G0107-EVA"}),
        ("@product_bom", {"ID_產品編號": "==G0107-EVA"}),
    ]


@pytest.mark.asyncio
async def test_bom_document_store_confirms_local_document() -> None:
    store = BomDocumentStore("memory://unit-test")
    operator = OperatorContext(
        session_id="session-1",
        account="amy",
        name="Amy",
        privilege="dev",
    )

    document = await store.confirm_document(
        document_id="aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa",
        product={
            "productSku": "STRX-202",
            "productName": "Spirit RTR front radio plate",
            "productNameCn": "灵魂车RTR 二楼板-F",
        },
        generate_qty=100,
        lines=[
            {
                "lineNo": 1,
                "sourceBomRecordId": "123",
                "partNo": "AL08045-00",
                "partName": "灵魂车RTR 二楼板-F",
                "bomQty": 1,
                "calculatedQty": 100,
                "warehouse": "包装部",
                "position1": "A32-D-30",
                "position2": "",
                "stockSnapshot": 60,
                "raw": {"需求數量": "1"},
            }
        ],
        operator=operator,
    )
    saved = await store.get_document(document["id"])

    assert saved is not None
    assert saved["id"] == "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
    assert saved["status"] == "confirmed"
    assert saved["productSku"] == "STRX-202"
    assert saved["operatorAccount"] == "amy"
    assert saved["operatorPrivilege"] == "dev"
    assert saved["lineCount"] == 1
    assert saved["lines"][0]["calculatedQty"] == 100

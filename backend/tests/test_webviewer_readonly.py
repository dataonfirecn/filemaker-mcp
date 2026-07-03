import pytest
from fastapi import HTTPException

from app.api.bom_documents import _calculation_line
from app.api.filemaker import ensure_write_allowed
from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.bom_document_store import BomDocumentStore
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
    )
    token, payload = issue_session_token(context, settings)
    verified = verify_session_token(token, settings)
    operator = operator_from_session(verified)

    assert payload["productSku"] == "821RTR-27"
    assert verified["operator"]["account"] == "amy"
    assert operator.account == "amy"
    assert operator.name == "Amy"


def test_filemaker_write_guard_blocks_when_read_only() -> None:
    settings = Settings(filemaker_read_only=True)

    with pytest.raises(HTTPException) as exc:
        ensure_write_allowed(settings)

    assert exc.value.status_code == 423


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

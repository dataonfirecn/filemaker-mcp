import pytest

import app.api.natural_language_query as natural_query_api
from app.api.natural_language_query import run_natural_language_query
from app.core.config import Settings
from app.models.natural_language_query import NaturalLanguageQueryRequest
from app.services.audit_log import OperatorContext


PURCHASE_READ_PERMISSION = "part.procurement.purchaseHistory.read"


class UnexpectedFileMaker:
    def __getattr__(self, name):
        raise AssertionError(f"Purchase query must not use FileMaker Data API: {name}")


class FakeODataClient:
    def __init__(self, rows=None, found_count=None) -> None:
        self.rows = rows or []
        self.found_count = len(self.rows) if found_count is None else found_count
        self.calls = []

    async def records(self, table, **kwargs):
        self.calls.append((table, kwargs))
        return {
            "rows": self.rows,
            "foundCount": self.found_count,
            "returnedCount": len(self.rows),
        }


class FakeAuditLog:
    def __init__(self) -> None:
        self.rows = []

    async def record(self, **kwargs):
        self.rows.append(kwargs)
        return {"id": 1}


class FakeConversationStore:
    def __init__(self) -> None:
        self.rows = []

    async def record(self, **kwargs):
        self.rows.append(kwargs)
        return 1


class FakeAnalyticsWorker:
    def notify(self):
        return None


def _operator(*, purchase_read: bool = True) -> OperatorContext:
    return OperatorContext(
        session_id="session",
        account="amy",
        name="Amy",
        privilege="employee",
        permissions={
            "canViewProducts": True,
            "canViewOrders": True,
            "canViewInventory": True,
            "canViewPrice": False,
            "canViewBom": True,
        },
        part_permissions={PURCHASE_READ_PERMISSION: purchase_read},
    )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        natural_query_timezone="Asia/Shanghai",
        natural_query_max_display_rows=10,
        natural_query_use_rag=False,
    )


@pytest.mark.asyncio
async def test_purchase_prompt_bypasses_llm_and_returns_purchase_items(monkeypatch) -> None:
    async def unexpected_llm(*args, **kwargs):
        raise AssertionError("Deterministic purchase query must bypass the LLM")

    monkeypatch.setattr(natural_query_api, "_interpret_prompt_with_llm", unexpected_llm)
    odata = FakeODataClient(
        rows=[
            {
                "id": "purchase-line-1",
                "ID_採購單": "PO-2026-18",
                "下單日期": "2026-08-14",
                "零件編號": "AL050013-00",
                "零件名稱": "Front arm",
                "數量": 120,
                "廠商名稱": "宏盛",
                "來貨狀況": "部分到货",
                "倉庫已入庫數量": 80,
            }
        ]
    )
    audit_log = FakeAuditLog()
    conversation_store = FakeConversationStore()

    response = await run_natural_language_query(
        body=NaturalLanguageQueryRequest(prompt="今天采购的零件有哪些"),
        filemaker=UnexpectedFileMaker(),
        odata_client=odata,
        rag_store=None,
        audit_log=audit_log,
        conversation_store=conversation_store,
        analytics_worker=FakeAnalyticsWorker(),
        operator=_operator(),
        settings=_settings(),
        enforced_product_client_id="",
        enforced_part_customer_id="",
    )

    assert len(odata.calls) == 1
    table, kwargs = odata.calls[0]
    assert table == "採購單資料"
    assert "id" not in kwargs["select"]
    assert "下單日期 ge " in kwargs["filter_expr"]
    assert kwargs["orderby"] == "下單日期 desc"
    assert response.layout == "採購單資料"
    assert response.plan.intent == "find_part_purchase_lines"
    assert response.rows == []
    assert len(response.items) == 1
    assert response.items[0].title == "AL050013-00"
    assert response.items[0].target_type == "part"
    assert response.items[0].target_identifier == "AL050013-00"
    assert "本次查询对象为零件采购明细" in response.answer
    assert "採購單資料·下單日期" in response.answer
    assert "共找到 1 条采购明细" in response.answer
    assert audit_log.rows[0]["target_table"] == "採購單資料"
    assert conversation_store.rows[0]["source"] == "odata-live"


@pytest.mark.asyncio
async def test_purchase_prompt_requires_granular_purchase_read_permission() -> None:
    odata = FakeODataClient()

    with pytest.raises(natural_query_api.HTTPException) as exc_info:
        await run_natural_language_query(
            body=NaturalLanguageQueryRequest(prompt="今天采购的零件有哪些"),
            filemaker=UnexpectedFileMaker(),
            odata_client=odata,
            rag_store=None,
            audit_log=None,
            conversation_store=None,
            analytics_worker=None,
            operator=_operator(purchase_read=False),
            settings=_settings(),
            enforced_product_client_id="",
            enforced_part_customer_id="",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["permission"] == PURCHASE_READ_PERMISSION
    assert odata.calls == []


@pytest.mark.asyncio
async def test_broad_purchase_prompt_returns_range_clarification_without_query() -> None:
    odata = FakeODataClient()

    response = await run_natural_language_query(
        body=NaturalLanguageQueryRequest(prompt="采购的零件有哪些"),
        filemaker=UnexpectedFileMaker(),
        odata_client=odata,
        rag_store=None,
        audit_log=None,
        conversation_store=FakeConversationStore(),
        analytics_worker=FakeAnalyticsWorker(),
        operator=_operator(),
        settings=_settings(),
        enforced_product_client_id="",
        enforced_part_customer_id="",
    )

    assert response.requires_clarification is True
    assert response.clarification_options == [
        "今天采购的零件有哪些",
        "昨天采购的零件有哪些",
        "近7天采购的零件有哪些",
    ]
    assert odata.calls == []

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.config import Settings
from app.api.natural_language_query import (
    _answer_text,
    _clarification_for_plan,
    _coverage_warnings_for_rows,
    _effective_result_limit,
    _explicit_identifier_domain,
    _exact_odata_lookup,
    _find_exact_records_via_odata,
    _identifier_domain_clarification,
    _rag_layout,
    _resolve_internal_identifier_domain,
    _row_for_plan,
    _stock_warning_for_rows,
    run_natural_language_query,
)
from app.services.audit_log import OperatorContext
from app.services.filemaker_odata_client import FileMakerODataError
from app.services.natural_language_query import (
    NaturalQueryError,
    build_product_natural_query_plan,
)
from app.models.natural_language_query import NaturalLanguageQueryRequest


def _odata_settings() -> Settings:
    return Settings(
        _env_file=None,
        filemaker_host="https://filemaker.example",
        filemaker_database="StarRC",
        filemaker_username="reader",
        filemaker_password="secret",
        filemaker_odata_enabled=True,
    )


def test_exact_product_identifier_maps_to_live_odata_keys() -> None:
    plan = build_product_natural_query_plan(
        "产品 STRX-249",
        layout_fields=[{"name": "product_sku"}, {"name": "系統產品編號"}],
        settings=Settings(_env_file=None),
    )

    assert _exact_odata_lookup(plan) == (
        "產品",
        ("product_sku", "系統產品編號"),
        "STRX-249",
    )
    assert _rag_layout(plan.layout) == "@products_RAG"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("AL050013-00", None),
        ("查询 AL050013-00 库存", None),
        ("查询零件 AL050013-00", "part"),
        ("Check part inventory for AL050013-00", "part"),
        ("查询产品 MYB0196", "product"),
        ("Check product inventory for MYB0196", "product"),
        ("AL050013-00 是产品还是零件", None),
    ],
)
def test_internal_identifier_domain_requires_an_explicit_unambiguous_domain(
    prompt: str,
    expected: str | None,
) -> None:
    assert _explicit_identifier_domain(prompt) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_found", "part_found", "expected"),
    [
        (1, 0, "product"),
        (0, 1, "part"),
        (1, 1, "ambiguous"),
        (0, 0, "not_found"),
    ],
)
async def test_internal_unlabeled_identifier_searches_both_catalogs(
    product_found: int,
    part_found: int,
    expected: str,
) -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100):
            self.calls.append((layout, query, limit))
            return {
                "data": [],
                "foundCount": product_found if layout == "@products" else part_found,
                "returnedCount": 0,
            }

    filemaker = FakeFileMaker()
    resolution = await _resolve_internal_identifier_domain(filemaker, "AL050013-00")

    assert resolution == expected
    assert filemaker.calls == [
        ("@products", {"product_sku": "==AL050013-00"}, 1),
        ("Parts", {"part_number": "==AL050013-00"}, 1),
    ]


def test_internal_identifier_clarification_preserves_inventory_intent() -> None:
    clarification = _identifier_domain_clarification(
        "查询 UNKNOWN-404 库存",
        "UNKNOWN-404",
        matched_both=False,
    )

    assert clarification == {
        "question": "没有确认编号 UNKNOWN-404 属于哪个领域。它是产品还是零件？",
        "options": [
            "查询产品 UNKNOWN-404 的库存",
            "查询零件 UNKNOWN-404 的库存",
        ],
    }


@pytest.mark.asyncio
async def test_internal_bare_part_identifier_is_routed_to_parts() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(
            self,
            layout,
            query=None,
            limit=100,
            offset=1,
            sort=None,
        ):
            self.calls.append((layout, query, limit, offset, sort))
            if layout == "@products":
                return {"data": [], "foundCount": 0, "returnedCount": 0}
            if limit == 1:
                return {"data": [], "foundCount": 1, "returnedCount": 0}
            return {
                "data": [{
                    "recordId": "92758",
                    "fieldData": {
                        "part_number": "AL050013-00",
                        "part_name_en": "Pipe Holder",
                        "stock_on_hand_qty": 12,
                    },
                }],
                "foundCount": 1,
                "returnedCount": 1,
            }

    class FakeRagStore:
        async def get_layout_profile(self, layout):
            return {
                "fields": [
                    {"name": "part_number"},
                    {"name": "part_name_en"},
                    {"name": "stock_on_hand_qty"},
                ],
                "semanticProfile": {"concepts": {}},
            }

    class FakeAuditLog:
        async def record(self, **kwargs):
            return None

    class FakeConversationStore:
        async def record(self, **kwargs):
            return 1

    class FakeAnalyticsWorker:
        def notify(self):
            return None

    filemaker = FakeFileMaker()
    response = await run_natural_language_query(
        body=NaturalLanguageQueryRequest(prompt="AL050013-00", limit=10),
        filemaker=filemaker,
        odata_client=None,
        rag_store=FakeRagStore(),
        audit_log=FakeAuditLog(),
        conversation_store=FakeConversationStore(),
        analytics_worker=FakeAnalyticsWorker(),
        operator=OperatorContext(
            session_id="session",
            account="amy",
            name="Amy",
            privilege="employee",
        ),
        settings=Settings(
            _env_file=None,
            natural_query_llm_enabled=False,
            natural_query_use_rag=False,
            filemaker_odata_enabled=False,
        ),
        enforced_product_client_id="",
        enforced_part_customer_id="",
    )

    assert response.plan.domain == "part"
    assert response.layout == "Parts"
    assert response.found_count == 1
    assert response.rows[0].product_sku == "AL050013-00"
    assert filemaker.calls[0][:3] == (
        "@products",
        {"product_sku": "==AL050013-00"},
        1,
    )
    assert filemaker.calls[1][:3] == (
        "Parts",
        {"part_number": "==AL050013-00"},
        1,
    )


@pytest.mark.asyncio
async def test_internal_unknown_identifier_asks_for_domain_before_normal_query() -> None:
    class FakeFileMaker:
        async def find_records(self, layout, query=None, limit=100):
            return {"data": [], "foundCount": 0, "returnedCount": 0}

    class FakeConversationStore:
        def __init__(self) -> None:
            self.rows = []

        async def record(self, **kwargs):
            self.rows.append(kwargs)
            return 1

    class FakeAnalyticsWorker:
        def notify(self):
            return None

    conversation_store = FakeConversationStore()
    response = await run_natural_language_query(
        body=NaturalLanguageQueryRequest(prompt="UNKNOWN-404", limit=10),
        filemaker=FakeFileMaker(),
        odata_client=None,
        rag_store=None,
        audit_log=None,
        conversation_store=conversation_store,
        analytics_worker=FakeAnalyticsWorker(),
        operator=OperatorContext(
            session_id="session",
            account="amy",
            name="Amy",
            privilege="employee",
        ),
        settings=Settings(_env_file=None, natural_query_llm_enabled=False),
        enforced_product_client_id="",
        enforced_part_customer_id="",
    )

    assert response.requires_clarification is True
    assert response.plan.domain == "unknown"
    assert response.clarification_question == (
        "没有确认编号 UNKNOWN-404 属于哪个领域。它是产品还是零件？"
    )
    assert response.clarification_options == [
        "查询产品 UNKNOWN-404",
        "查询零件 UNKNOWN-404",
    ]
    assert conversation_store.rows[0]["status"] == "clarification"


def test_scoped_exact_identifier_never_uses_unscoped_odata() -> None:
    plan = build_product_natural_query_plan(
        "产品 STRX-249",
        layout_fields=[{"name": "product_sku"}, {"name": "系統產品編號"}],
        settings=Settings(_env_file=None),
    )
    plan.query = [{"product_sku": "==STRX-249", "id_client": "==CU638"}]

    assert _exact_odata_lookup(plan) is None


@pytest.mark.asyncio
async def test_exact_identifier_uses_odata_and_normalizes_rows() -> None:
    class FakeODataClient:
        async def records(self, table, **kwargs):
            assert table == "產品"
            assert kwargs["filter_expr"] == (
                "product_sku eq 'STRX-249' or 系統產品編號 eq 'STRX-249'"
            )
            return {
                "rows": [{"ROWID": "77", "ROWMODID": "3", "product_sku": "STRX-249"}],
                "foundCount": 1,
            }

    plan = build_product_natural_query_plan(
        "产品 STRX-249",
        layout_fields=[{"name": "product_sku"}, {"name": "系統產品編號"}],
        settings=Settings(_env_file=None),
    )
    result = await _find_exact_records_via_odata(
        plan,
        client=FakeODataClient(),
        settings=_odata_settings(),
        limit=10,
        offset=1,
    )

    assert result == {
        "data": [{"recordId": "STRX-249", "modId": "3", "fieldData": {"product_sku": "STRX-249"}}],
        "foundCount": 1,
        "returnedCount": 1,
    }


@pytest.mark.asyncio
async def test_odata_error_returns_none_for_data_api_fallback() -> None:
    class FailingODataClient:
        async def records(self, table, **kwargs):
            raise FileMakerODataError("temporary failure", status_code=500)

    plan = build_product_natural_query_plan(
        "零件 AL0003-00",
        layout_fields=[{"name": "part_number"}],
        settings=Settings(_env_file=None),
    )

    assert await _find_exact_records_via_odata(
        plan,
        client=FailingODataClient(),
        settings=_odata_settings(),
        limit=10,
        offset=1,
    ) is None


def test_yesterday_created_products_builds_date_query() -> None:
    plan = build_product_natural_query_plan(
        "获取昨天新增的产品",
        layout_fields=[{"name": "创建日期", "type": "date"}, {"name": "product_sku"}],
        settings=Settings(natural_query_product_created_fields="创建日期"),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.layout == "@products"
    assert plan.query == [{"创建日期": "07/05/2026"}]
    assert plan.sort == [{"fieldName": "创建日期", "sortOrder": "descend"}]
    assert plan.date_range == {
        "label": "昨天",
        "start": "2026-07-05",
        "end": "2026-07-05",
        "field": "创建日期",
    }


def test_keyword_query_searches_product_fields() -> None:
    plan = build_product_natural_query_plan(
        "查询 STRX-202 产品",
        layout_fields=[{"name": "product_sku"}, {"name": "產品名稱_中文"}],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert {"product_sku": "==STRX-202"} in plan.query
    assert {"產品名稱_中文": "*STRX-202*"} in plan.query
    assert plan.keywords == ["STRX-202"]


def test_today_created_parts_uses_parts_layout_and_month_first_date() -> None:
    plan = build_product_natural_query_plan(
        "今天新增的零件有哪些",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.domain == "part"
    assert plan.layout == "Parts"
    assert plan.query == [{"Date Created": "07/06/2026"}]
    assert plan.sort == [{"fieldName": "Date Created", "sortOrder": "descend"}]


def test_english_date_queries_preserve_product_and_part_domains() -> None:
    product_plan = build_product_natural_query_plan(
        "Products added today",
        layout_fields=[{"name": "创建日期", "type": "date"}, {"name": "product_sku"}],
        settings=Settings(natural_query_product_created_fields="创建日期"),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    part_plan = build_product_natural_query_plan(
        "Parts added yesterday",
        layout_fields=[{"name": "Date Created", "result": "date"}, {"name": "part_number"}],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert product_plan.domain == "product"
    assert product_plan.query == [{"创建日期": "07/06/2026"}]
    assert part_plan.domain == "part"
    assert part_plan.query == [{"Date Created": "07/05/2026"}]


def test_english_part_date_uses_month_first_format_when_metadata_times_out() -> None:
    plan = build_product_natural_query_plan(
        "Parts added yesterday",
        layout_fields=[],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.domain == "part"
    assert plan.query == [{"Date Created": "07/05/2026"}]


def test_english_natural_language_extracts_meaningful_keywords_and_scale() -> None:
    fields = [
        {"name": "product_sku"},
        {"name": "product_name"},
        {"name": "車子比例"},
    ]

    buggy_plan = build_product_natural_query_plan(
        "Show me buggy products",
        layout_fields=fields,
        settings=Settings(),
    )
    mx8_plan = build_product_natural_query_plan(
        "Do you have any MX8 products?",
        layout_fields=fields,
        settings=Settings(),
    )
    scale_plan = build_product_natural_query_plan(
        "I'm looking for 1:8 scale products",
        layout_fields=fields,
        settings=Settings(),
    )
    chinese_buggy_plan = build_product_natural_query_plan(
        "有哪些越野车产品？",
        layout_fields=fields,
        settings=Settings(),
    )
    chinese_carbon_plan = build_product_natural_query_plan(
        "有没有碳纤维零件？",
        layout_fields=[{"name": "part_number"}, {"name": "part_name_en"}],
        settings=Settings(),
    )

    assert buggy_plan.keywords == ["buggy"]
    assert mx8_plan.keywords == ["MX8"]
    assert scale_plan.filters["scale"] == "1/8"
    assert scale_plan.query == [{"車子比例": "*1/8*"}]
    assert chinese_buggy_plan.keywords == ["buggy"]
    assert chinese_carbon_plan.domain == "part"
    assert chinese_carbon_plan.keywords == ["carbon"]


def test_part_output_field_labels_do_not_become_keywords() -> None:
    plan = build_product_natural_query_plan(
        "今天新增的零件 名称 创建人 库存 价格",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "part_name_en"},
            {"name": "stock_on_hand_qty"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.keywords == []
    assert plan.query == [{"Date Created": "07/06/2026"}]
    assert plan.description == "今天新增"


def test_part_attribute_phrase_extracts_keyword() -> None:
    fields = [
        {"name": "part_number"},
        {"name": "part_name_en"},
        {"name": "Notes"},
    ]

    for prompt in ("pvc的零件有哪些", "PVC 材质的零件有哪些", "找一下 PVC 零件"):
        plan = build_product_natural_query_plan(
            prompt,
            layout_fields=fields,
            settings=Settings(),
            now=datetime(2026, 7, 7, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        assert plan.domain == "part"
        assert plan.keywords == ["PVC"] or plan.keywords == ["pvc"]
        assert any(item.get("part_name_en") in ("*PVC*", "*pvc*") for item in plan.query)


def test_broad_part_query_returns_clarification() -> None:
    plan = build_product_natural_query_plan(
        "零件有哪些",
        layout_fields=[
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 7, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    clarification = _clarification_for_plan(
        prompt="零件有哪些",
        interpreted_prompt="零件有哪些",
        parsed_plan=plan,
    )

    assert clarification is not None
    assert "范围太宽" in str(clarification["question"])
    assert "pvc的零件有哪些" in clarification["options"]


def test_all_parts_keyword_returns_clarification() -> None:
    plan = build_product_natural_query_plan(
        "所有零件",
        layout_fields=[
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 7, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    clarification = _clarification_for_plan(
        prompt="零件有哪些",
        interpreted_prompt="所有零件",
        parsed_plan=plan,
    )

    assert clarification is not None
    assert "范围太宽" in str(clarification["question"])


def test_recent_part_query_asks_for_time_window() -> None:
    plan = build_product_natural_query_plan(
        "最近的零件",
        layout_fields=[
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 7, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    clarification = _clarification_for_plan(
        prompt="最近的零件",
        interpreted_prompt="最近的零件",
        parsed_plan=plan,
    )

    assert clarification is not None
    assert "最近" in str(clarification["question"])
    assert "近7天新增的零件" in clarification["options"]


def test_accessory_synonym_uses_parts_layout() -> None:
    plan = build_product_natural_query_plan(
        "今天加的配件，给我具体时间",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.domain == "part"
    assert plan.layout == "Parts"
    assert plan.query == [{"Date Created": "07/06/2026"}]
    assert plan.warnings


def test_part_row_maps_stock_on_hand_to_product_stock() -> None:
    row = _row_for_plan(
        {
            "recordId": "92758",
            "fieldData": {
                "part_number": "AL0812-016-PS",
                "part_name_en": "Front shock tower",
                "stock_on_hand_qty": 12,
            },
        },
        "part",
    )

    assert row.product_sku == "AL0812-016-PS"
    assert row.product_name == "Front shock tower"
    assert row.stock == 12
    assert row.raw["stock_on_hand_qty"] == 12


def test_part_row_maps_semantic_created_by_to_display_field() -> None:
    row = _row_for_plan(
        {
            "recordId": "92758",
            "fieldData": {
                "part_number": "AL0812-016-PS",
                "part_name": "1/16房车 前避震架",
                "Creator Account": "amy",
            },
        },
        "part",
        semantic_profile={
            "concepts": {
                "createdBy": {
                    "field": "Creator Account",
                    "available": True,
                    "label": "创建人",
                }
            }
        },
    )

    assert row.raw["Created By"] == "amy"
    assert row.raw["创建人"] == "amy"


def test_stock_request_warns_when_returned_part_rows_have_empty_stock() -> None:
    rows = [
        _row_for_plan(
            {
                "recordId": "92758",
                "fieldData": {
                    "part_number": "AL0812-016-PS",
                    "part_name_en": "Front shock tower",
                    "stock_on_hand_qty": "",
                },
            },
            "part",
        )
    ]

    warning = _stock_warning_for_rows(
        "part",
        rows,
        prompt="今天增加了哪些零件，库存还有多少",
        interpreted_prompt="今天新增的零件，库存",
    )

    assert warning is None


def test_coverage_warning_keeps_original_timestamp_request_when_interpreter_drops_it() -> None:
    warnings = _coverage_warnings_for_rows(
        "part",
        "Parts",
        [{"name": "Date Created", "result": "date"}],
        [],
        prompt="今天新增的零件，具体时间戳是什么",
        interpreted_prompt="今天新增的零件",
        date_range={
            "label": "今天",
            "start": "2026-07-06",
            "end": "2026-07-06",
            "field": "Date Created",
        },
    )

    assert warnings == [
        "FileMaker 的 Parts 布局目前只提供“Date Created”日期字段，"
        "没有创建时间戳或更新时间字段；已回退显示创建日期。"
    ]


def test_coverage_warning_reports_missing_created_by_field_from_semantics() -> None:
    warnings = _coverage_warnings_for_rows(
        "part",
        "Parts",
        [{"name": "Date Created", "result": "date"}],
        [],
        prompt="今天新增的零件有哪些，都是谁创建的",
        interpreted_prompt="今天新增的零件，创建人",
        date_range={
            "label": "今天",
            "start": "2026-07-06",
            "end": "2026-07-06",
            "field": "Date Created",
        },
        semantic_profile={
            "concepts": {
                "createdBy": {
                    "field": "",
                    "available": False,
                    "label": "创建人",
                    "reason": "metadata 中没有发现可表示“创建人”的字段。",
                }
            }
        },
    )

    assert len(warnings) == 1
    assert "没有发现可表示“创建人/创建者”的字段" in warnings[0]
    assert "无法判断这些零件是谁创建的" in warnings[0]


def test_coverage_warning_reports_missing_price_field_from_semantics() -> None:
    warnings = _coverage_warnings_for_rows(
        "part",
        "Parts",
        [{"name": "Date Created", "result": "date"}],
        [],
        prompt="昨天新增的零件，价格分别是多少",
        interpreted_prompt="昨天新增的零件，列出价格",
        date_range={
            "label": "昨天",
            "start": "2026-07-06",
            "end": "2026-07-06",
            "field": "Date Created",
        },
        semantic_profile={
            "concepts": {
                "price": {
                    "field": "",
                    "available": False,
                    "label": "价格",
                    "reason": "metadata 中没有发现可表示“价格”的字段。",
                }
            }
        },
    )

    assert len(warnings) == 1
    assert "没有发现可表示“价格/单价”的字段" in warnings[0]
    assert "无法返回这些零件的价格" in warnings[0]


def test_timestamp_request_falls_back_to_date_with_warning() -> None:
    plan = build_product_natural_query_plan(
        "今天新增的零件有哪些，把具体时间戳列出来",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.query == [{"Date Created": "07/06/2026"}]
    assert plan.warnings == [
        "FileMaker 的 Parts 布局目前只提供“Date Created”日期字段，"
        "没有创建时间戳或更新时间字段；已回退显示创建日期。"
    ]


def test_timestamp_request_uses_metadata_when_timestamp_exists() -> None:
    plan = build_product_natural_query_plan(
        "今天新增的零件有哪些，把具体时间戳列出来",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "Created Timestamp", "result": "timestamp"},
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.query == [{"Date Created": "07/06/2026"}]
    assert plan.warnings == []


def test_recent_week_created_parts_uses_seven_day_range() -> None:
    plan = build_product_natural_query_plan(
        "近一周新增的零件有哪些",
        layout_fields=[
            {"name": "Date Created", "result": "date"},
            {"name": "part_number"},
            {"name": "part_name"},
        ],
        settings=Settings(),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.domain == "part"
    assert plan.query == [{"Date Created": "06/30/2026...07/06/2026"}]
    assert plan.date_range == {
        "label": "近 7 天",
        "start": "2026-06-30",
        "end": "2026-07-06",
        "field": "Date Created",
    }


def test_date_query_requires_created_field() -> None:
    with pytest.raises(NaturalQueryError):
        build_product_natural_query_plan(
            "获取昨天新增的产品",
            layout_fields=[{"name": "product_sku"}],
            settings=Settings(natural_query_product_created_fields="创建日期"),
            now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
        )


def test_date_query_uses_configured_field_without_metadata() -> None:
    plan = build_product_natural_query_plan(
        "获取昨天新增的产品",
        layout_fields=[],
        settings=Settings(natural_query_product_created_fields="创建日期"),
        now=datetime(2026, 7, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert plan.query == [{"创建日期": "07/05/2026"}]


def test_effective_result_limit_caps_requested_rows() -> None:
    settings = Settings(natural_query_max_display_rows=10)

    assert _effective_result_limit(settings, 50) == 10
    assert _effective_result_limit(settings, 8) == 8
    assert _effective_result_limit(settings, 0) == 1


def test_large_result_answer_mentions_total_first_rows_and_summary() -> None:
    rows = [
        _row_for_plan(
            {
                "recordId": "1",
                "fieldData": {
                    "part_number": "PVC-001",
                    "part_name": "PVC 前臂",
                },
            },
            "part",
        ),
        _row_for_plan(
            {
                "recordId": "2",
                "fieldData": {
                    "part_number": "PVC-002",
                    "part_name": "PVC 后臂",
                },
            },
            "part",
        ),
    ]

    answer = _answer_text(
        27,
        10,
        "PVC 零件",
        "零件",
        rows=rows,
        result_limit=10,
    )

    assert "共找到 27 条" in answer
    assert "列出前 10 条" in answer
    assert "简要总结" in answer
    assert "PVC-001" in answer

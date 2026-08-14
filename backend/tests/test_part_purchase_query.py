from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.services.part_purchase_query import (
    PURCHASE_LINE_DATE_FIELD,
    build_part_purchase_query_plan,
    looks_like_part_purchase_query,
)


def _settings() -> Settings:
    return Settings(_env_file=None, natural_query_timezone="Asia/Shanghai")


def _now() -> datetime:
    return datetime(2026, 8, 14, 12, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_today_purchase_query_uses_order_date_not_part_created_date() -> None:
    plan = build_part_purchase_query_plan(
        "今天采购的零件有哪些",
        settings=_settings(),
        now=_now(),
    )

    assert plan is not None
    assert plan.intent == "find_part_purchase_lines"
    assert plan.layout == "採購單資料"
    assert plan.date_range == {
        "label": "今天",
        "start": "2026-08-14",
        "end": "2026-08-14",
        "field": PURCHASE_LINE_DATE_FIELD,
    }
    assert plan.filter_expr == "(下單日期 ge 2026-08-14 and 下單日期 lt 2026-08-15)"
    assert plan.description == "今天下单"


def test_purchase_query_combines_date_part_vendor_and_po_scopes() -> None:
    plan = build_part_purchase_query_plan(
        "近7天供应商 宏盛 采购的零件，零件编号 AL050013-00，采购单 PO-2026-18",
        settings=_settings(),
        now=_now(),
    )

    assert plan is not None
    assert plan.filters == {
        "orderDate": "近 7 天",
        "partNumber": "AL050013-00",
        "vendor": "宏盛",
        "purchaseOrderId": "PO-2026-18",
    }
    assert "下單日期 ge 2026-08-08" in plan.filter_expr
    assert "零件編號 eq 'AL050013-00'" in plan.filter_expr
    assert "contains(廠商名稱,'宏盛')" in plan.filter_expr
    assert "ID_採購單 eq 'PO-2026-18'" in plan.filter_expr


def test_purchase_query_without_scope_requires_clarification() -> None:
    plan = build_part_purchase_query_plan(
        "采购的零件有哪些",
        settings=_settings(),
        now=_now(),
    )

    assert plan is not None
    assert plan.has_scope is False
    assert plan.query == []


def test_procurement_people_and_notes_do_not_trigger_purchase_lines() -> None:
    assert looks_like_part_purchase_query("今天新增零件的采购员是谁") is False
    assert looks_like_part_purchase_query("查看采购备注") is False
    assert looks_like_part_purchase_query("今天下单的零件有哪些") is True

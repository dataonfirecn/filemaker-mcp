from datetime import datetime

import pytest
from fastapi import HTTPException

from app.api.customer_chat import (
    get_customer_chat_history,
    get_customer_chat_question_summary,
)
from app.services.customer_chat_auth import CustomerSession
from app.services.audit_log import OperatorContext
from app.services.customer_chat_history import CustomerChatHistoryStore


@pytest.mark.asyncio
async def test_history_store_lists_and_summarizes_non_test_questions() -> None:
    store = CustomerChatHistoryStore("memory://")
    operator = OperatorContext(
        session_id="session-1",
        account="mayako",
        name="Mayako",
        privilege="external_customer",
    )
    await store.record(
        operator=operator,
        client_name="Mayako",
        is_admin=False,
        prompt="Check inventory for MYB0196",
        domain="product",
        status="success",
        http_status=200,
        found_count=1,
        returned_count=1,
    )
    await store.record(
        operator=operator,
        client_name="Mayako",
        is_admin=False,
        prompt="Check inventory for MYB0377-24",
        domain="product",
        status="no_result",
        http_status=200,
    )
    await store.record(
        operator=operator,
        client_name="Mayako",
        is_admin=False,
        prompt="What is the price for MYB0196?",
        domain="product",
        status="blocked",
        http_status=403,
        is_test=True,
    )

    rows, total = await store.list_history()
    summary = await store.question_summary(days=30)

    assert total == 2
    assert len(rows) == 2
    assert all(isinstance(row["createdAt"], datetime) for row in rows)
    assert sum(item["totalCount"] for item in summary) == 2
    assert sum(item["successCount"] for item in summary) == 1
    assert sum(item["noResultCount"] for item in summary) == 1


@pytest.mark.asyncio
async def test_history_store_can_include_regression_tests_explicitly() -> None:
    store = CustomerChatHistoryStore("memory://")
    operator = OperatorContext(
        session_id="qa",
        account="qa",
        name="QA",
        privilege="external_customer",
    )
    await store.record(
        operator=operator,
        client_name="Mayako",
        is_admin=True,
        prompt="View product list",
        status="success",
        http_status=200,
        channel="regression_test",
        is_test=True,
    )

    _, hidden_total = await store.list_history()
    rows, visible_total = await store.list_history(include_tests=True)

    assert hidden_total == 0
    assert visible_total == 1
    assert rows[0]["channel"] == "regression_test"
    assert rows[0]["isTest"] is True


@pytest.mark.asyncio
async def test_admin_endpoints_require_admin_and_return_history() -> None:
    store = CustomerChatHistoryStore("memory://")
    operator = OperatorContext(
        session_id="customer",
        account="mayako",
        name="Mayako",
        privilege="external_customer",
    )
    await store.record(
        operator=operator,
        client_name="Mayako",
        is_admin=False,
        prompt="View order history",
        domain="order",
        status="success",
        http_status=200,
    )
    regular = CustomerSession(
        session_id="regular",
        username="regular",
        display_name="Regular",
        client_name="Mayako",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
    )
    admin = CustomerSession(
        session_id="admin",
        username="admin",
        display_name="Admin",
        client_name="Mayako",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
        is_admin=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_customer_chat_history(
            page=1, page_size=50, domain="", status_value="", query="",
            include_tests=False, session=regular, history_store=store,
        )
    history = await get_customer_chat_history(
        page=1, page_size=50, domain="", status_value="", query="",
        include_tests=False, session=admin, history_store=store,
    )
    summary = await get_customer_chat_question_summary(
        days=30, limit=50, include_tests=False, session=admin, history_store=store,
    )

    assert exc_info.value.status_code == 403
    assert history.found_count == 1
    assert history.rows[0].prompt == "View order history"
    assert summary.questions[0].domain == "order"

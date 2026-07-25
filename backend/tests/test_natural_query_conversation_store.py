import asyncio

import pytest

from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_question_analytics import analyze_pending_questions


@pytest.mark.asyncio
async def test_natural_query_conversation_store_records_quality_context(tmp_path) -> None:
    store = NaturalQueryConversationStore(str(tmp_path / "app.db"))
    await store.init()

    conversation_id = await store.record(
        operator=OperatorContext(
            session_id="session-1",
            account="codex.test",
            name="Codex Test",
            privilege="mock",
        ),
        prompt="今天新增的零件有哪些，都是谁创建的",
        interpreted_prompt="今天新增的零件，创建人",
        llm={"provider": "deepseek", "model": "deepseek-v4-flash"},
        layout="Parts",
        domain="part",
        intent="find_parts",
        source="filemaker",
        query=[{"Date Created": "07/06/2026"}],
        semantic_profile={
            "source": "llm",
            "sampleRecordCount": 200,
            "fields": {"Date Created": {}, "part_number": {}},
            "concepts": {"createdBy": {"available": False, "field": ""}},
        },
        warnings=["metadata 中没有创建人字段"],
        answer="找到 27 条",
        found_count=27,
        returned_count=5,
        rag_hit_count=0,
        duration_ms=123,
    )

    rows = await store.list_recent(limit=5)

    assert conversation_id == 1
    assert rows[0].prompt == "今天新增的零件有哪些，都是谁创建的"
    assert rows[0].layout == "Parts"
    assert rows[0].found_count == 27
    assert rows[0].warnings == ["metadata 中没有创建人字段"]


@pytest.mark.asyncio
async def test_question_analytics_filters_noise_and_counts_top_questions(tmp_path) -> None:
    store = NaturalQueryConversationStore(str(tmp_path / "app.db"))
    await store.init()
    operator = OperatorContext(
        session_id="session-1",
        account="codex.test",
        name="Codex Test",
        privilege="mock",
    )
    await store.record(operator=operator, prompt="在吗", status="clarification")
    await store.record(operator=operator, prompt="测试", status="error")
    await store.record(operator=operator, prompt="pvc的零件有哪些", domain="part", intent="find_parts")
    await store.record(operator=operator, prompt="PVC 材质的零件有哪些", domain="part", intent="find_parts")

    result = await analyze_pending_questions(
        store=store,
        settings=Settings(natural_query_llm_enabled=False),
        limit=20,
    )
    top = await store.top_questions(days=30, limit=5)

    assert result.analyzed == 4
    assert result.ignored == 2
    assert result.meaningful == 2
    assert len(top) == 2
    assert {item.count for item in top} == {1}
    assert all("测试" not in item.example_prompts for item in top)


@pytest.mark.asyncio
async def test_analytics_worker_processes_new_employee_question(tmp_path) -> None:
    store = NaturalQueryConversationStore(str(tmp_path / "app.db"))
    await store.init()
    settings = Settings(
        _env_file=None,
        natural_query_analytics_worker_enabled=True,
        natural_query_analytics_poll_interval_seconds=60,
        natural_query_llm_enabled=False,
    )
    worker = NaturalQueryAnalyticsWorker(store=store, settings=settings)
    worker.start()
    try:
        await store.record(
            operator=OperatorContext(
                session_id="filemaker-session",
                account="gabriel",
                name="Gabriel",
                privilege="FileMaker Data Entry Only",
            ),
            prompt="今天新增的零件有哪些",
            domain="part",
            intent="find_parts",
        )
        worker.notify()

        for _ in range(20):
            top = await store.top_questions(days=30, limit=5)
            if top:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("analytics worker did not process the pending question")

        assert top[0].example_prompts == ["今天新增的零件有哪些"]
    finally:
        await worker.stop()

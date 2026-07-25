import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.rag_index import (
    LayoutDateFields,
    RagIndexStore,
    RagIndexWorker,
    _STOCK_FIELD_PRIORITY,
    _detect_layout_date_fields,
    _record_to_chunk,
    _seconds_until_daily_time,
    _value_matches,
)
from app.core.config import Settings


@pytest.mark.asyncio
async def test_rag_store_finds_cached_product_by_filemaker_query(tmp_path) -> None:
    store = RagIndexStore(str(tmp_path / "rag.db"))
    await store.init()
    run_id = await store.start_run("unit")
    await store.upsert_record_chunk(
        layout="Products",
        record_id="101",
        mod_id="1",
        title="STRX-202 / 灵魂车",
        content="product_sku: STRX-202\n產品名稱_中文: 灵魂车",
        fields={
            "product_sku": "STRX-202",
            "產品名稱_中文": "灵魂车",
            "创建日期": "2026/07/05",
        },
        run_id=run_id,
    )

    result = await store.find_cached_records(
        layout="Products",
        query=[{"product_sku": "==STRX-202"}],
        limit=10,
    )

    assert result.found_count == 1
    assert result.records[0].record_id == "101"


@pytest.mark.asyncio
async def test_rag_store_applies_cached_date_range(tmp_path) -> None:
    store = RagIndexStore(str(tmp_path / "rag.db"))
    await store.init()
    run_id = await store.start_run("unit")
    await store.upsert_record_chunk(
        layout="Products",
        record_id="101",
        mod_id="1",
        title="昨天",
        content="创建日期: 2026/07/05",
        fields={"product_sku": "A-1", "创建日期": "2026/07/05"},
        run_id=run_id,
    )
    await store.upsert_record_chunk(
        layout="Products",
        record_id="102",
        mod_id="1",
        title="今天",
        content="创建日期: 2026/07/06",
        fields={"product_sku": "A-2", "创建日期": "2026/07/06"},
        run_id=run_id,
    )

    result = await store.find_cached_records(
        layout="Products",
        query=[{"创建日期": "2026/07/05...2026/07/05"}],
        limit=10,
        sort=[{"fieldName": "创建日期", "sortOrder": "descend"}],
    )

    assert [record.record_id for record in result.records] == ["101"]


@pytest.mark.asyncio
async def test_rag_store_search_uses_indexed_content(tmp_path) -> None:
    store = RagIndexStore(str(tmp_path / "rag.db"))
    await store.init()
    run_id = await store.start_run("unit")
    await store.upsert_record_chunk(
        layout="Products",
        record_id="101",
        mod_id="1",
        title="STRX-202",
        content="product_sku: STRX-202\n產品名稱_中文: 灵魂车",
        fields={"product_sku": "STRX-202", "產品名稱_中文": "灵魂车"},
        run_id=run_id,
    )

    hits = await store.search("STRX-202", limit=5, layout="Products")

    assert hits
    assert hits[0].record_id == "101"


@pytest.mark.asyncio
async def test_rag_store_prunes_layouts_outside_prefix_scope(tmp_path) -> None:
    store = RagIndexStore(str(tmp_path / "rag.db"))
    await store.init()
    run_id = await store.start_run("unit")
    for layout, record_id in (("@products", "1"), ("Products", "2")):
        await store.upsert_record_chunk(
            layout=layout,
            record_id=record_id,
            mod_id="1",
            title=record_id,
            content=f"product_sku: {record_id}",
            fields={"product_sku": record_id},
            run_id=run_id,
        )
        await store.upsert_layout_profile(
            layout=layout,
            field_count=1,
            record_count=1,
            indexed_count=1,
            fields=[{"name": "product_sku"}],
            samples=[],
            date_fields=LayoutDateFields(),
            run_id=run_id,
        )

    pruned = await store.prune_layouts(["@products"])

    assert pruned == {"layouts": 1, "records": 1}
    assert await store.get_layout_profile("Products") is None
    assert (await store.find_cached_records(layout="@products", query=[], limit=10)).found_count == 1


@pytest.mark.asyncio
async def test_rag_worker_targets_only_at_prefixed_layouts(tmp_path) -> None:
    class FakeFileMakerClient:
        async def list_layouts(self):
            return ["Products", "@products", "Parts", "@零件", "@product_bom"]

    settings = Settings(
        rag_database_path=str(tmp_path / "rag.db"),
        rag_index_layout_prefix="@",
        rag_index_layout_include="",
        rag_index_layout_exclude="@零件",
    )
    worker = RagIndexWorker(
        store=RagIndexStore(settings.rag_database_path),
        filemaker_client=FakeFileMakerClient(),
        settings=settings,
    )

    assert await worker._target_layouts() == ["@products", "@product_bom"]


def test_rag_metadata_detects_created_and_updated_fields() -> None:
    detected = _detect_layout_date_fields(
        [
            {"name": "part_number"},
            {"name": "修改紀錄::零件修改時間"},
            {"name": "修改日期"},
            {"name": "Date Created"},
            {"name": "createdAt"},
        ]
    )

    assert detected.created_field == "Date Created"
    assert detected.updated_field == "修改日期"
    assert detected.source == "metadata"


def test_rag_chunk_keeps_metadata_date_fields_when_field_limit_is_small() -> None:
    record = {
        "recordId": "101",
        "modId": "1",
        "fieldData": {
            "part_number": "AL0812-016-PS",
            "part_name": "1/16房车 前避震架",
            "extra": "ignored",
            "Date Created": "07/06/2026",
            "修改日期": "07/06/2026 08:59:40",
        },
    }

    chunk = _record_to_chunk(
        layout="零件 資料_管理",
        record=record,
        max_fields=3,
        value_max_length=160,
        priority_fields=["Date Created", "修改日期"],
    )

    assert chunk is not None
    assert chunk.fields["Date Created"] == "07/06/2026"
    assert chunk.fields["修改日期"] == "07/06/2026 08:59:40"


def test_rag_chunk_keeps_stock_field_when_field_limit_is_small() -> None:
    record = {
        "recordId": "101",
        "modId": "1",
        "fieldData": {
            "part_number": "AL0812-016-PS",
            "part_name": "1/16房车 前避震架",
            "extra": "ignored",
            "current_stock": "12",
        },
    }

    chunk = _record_to_chunk(
        layout="Parts",
        record=record,
        max_fields=2,
        value_max_length=160,
        priority_fields=list(_STOCK_FIELD_PRIORITY),
    )

    assert chunk is not None
    assert chunk.fields["current_stock"] == "12"


def test_rag_chunk_uses_field_whitelist_and_drops_container_noise() -> None:
    chunk = _record_to_chunk(
        layout="@product_bom",
        record={
            "recordId": "501",
            "modId": "1",
            "fieldData": {
                "ID": "BOM-501",
                "ID_產品編號": "STRX-249",
                "零件編號": "AL0003-00",
                "零件名稱": "避震架",
                "qrcode": "noise",
                "檔案 1 | 容器": "https://example/Streaming/MainDB/file.jpg",
                "未配置計算字段": "noise",
            },
        },
        max_fields=10,
        value_max_length=160,
        priority_fields=["ID", "ID_產品編號", "零件編號", "零件名稱"],
        allowed_fields={"ID", "ID_產品編號", "零件編號", "零件名稱", "qrcode", "檔案 1 | 容器"},
    )

    assert chunk is not None
    assert chunk.fields == {
        "ID": "BOM-501",
        "ID_產品編號": "STRX-249",
        "零件編號": "AL0003-00",
        "零件名稱": "避震架",
    }


def test_rag_date_range_matches_filemaker_us_date_format() -> None:
    assert _value_matches("07/06/2026", "06/30/2026...07/06/2026")
    assert not _value_matches("06/29/2026", "06/30/2026...07/06/2026")


def test_rag_daily_schedule_waits_until_next_midnight() -> None:
    now = datetime(2026, 7, 6, 23, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    assert _seconds_until_daily_time(now, "00:00") == 30 * 60


@pytest.mark.asyncio
async def test_rag_layout_profile_persists_semantic_profile(tmp_path) -> None:
    store = RagIndexStore(str(tmp_path / "rag.db"))
    await store.init()
    run_id = await store.start_run("unit")
    await store.upsert_layout_profile(
        layout="Parts",
        field_count=2,
        record_count=1,
        indexed_count=1,
        fields=[{"name": "Date Created"}, {"name": "part_number"}],
        samples=[],
        date_fields=LayoutDateFields(created_field="Date Created", source="metadata"),
        semantic_profile={
            "schemaVersion": 1,
            "concepts": {
                "createdBy": {
                    "field": "",
                    "available": False,
                    "label": "创建人",
                    "confidence": 0,
                    "reason": "metadata 中没有创建人字段",
                }
            },
        },
        run_id=run_id,
    )

    profile = await store.get_layout_profile("Parts")

    assert profile is not None
    assert profile["semanticProfile"]["concepts"]["createdBy"]["available"] is False

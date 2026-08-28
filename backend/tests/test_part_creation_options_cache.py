import asyncio
import json
import sqlite3

import pytest
from fastapi import HTTPException

from app.api.part_creation import refresh_part_creation_cache
from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.part_creation_options_cache import PartCreationOptionsCache


class FakeFileMaker:
    def __init__(self, *, material_label: str = "铝件"):
        self.material_label = material_label
        self.metadata_calls: list[str] = []
        self.record_calls: list[str] = []

    async def get_layout_metadata(self, layout):
        self.metadata_calls.append(layout)
        if layout == "新增零件资料":
            return {
                "valueLists": [
                    {"name": "倉庫分工", "values": [{"value": "发料"}]},
                    {"name": "零件性質", "values": [{"value": "AL"}]},
                    {"name": "加工分類", "values": [{"value": "外购"}]},
                    {"name": "零件狀態", "values": [{"value": "采购"}]},
                    {"name": "統計分類", "values": [{"value": "统计"}]},
                    {"name": "使用公司", "values": [{"value": "生产"}]},
                    {"name": "狀態", "values": [{"value": "待确认"}]},
                    {"name": "零件品種", "values": [{"value": "标准件"}]},
                    {"name": "材料分類", "values": [{"value": "金属"}]},
                    {"name": "倉庫", "values": [{"value": "A"}]},
                    {"name": "零件材料尺寸", "values": [{"value": "10mm"}]},
                    {
                        "name": "客戶",
                        "values": [{"value": "008", "displayValue": "Hobbytech"}],
                    },
                ]
            }
        assert layout == "MaterialIDGenerator_Gen"
        return {
            "valueLists": [
                {
                    "name": "零件性質",
                    "values": [
                        {"value": "AL", "displayValue": self.material_label}
                    ],
                },
                {
                    "name": "客戶",
                    "values": [
                        {"value": "008", "displayValue": "Hobbytech"}
                    ],
                },
            ]
        }

    async def find_records(self, layout, **kwargs):
        self.record_calls.append(layout)
        return {"data": [], "foundCount": 0}


class FailingFileMaker:
    async def get_layout_metadata(self, layout):
        raise RuntimeError("FileMaker unavailable")

    async def find_records(self, layout, **kwargs):
        raise RuntimeError("FileMaker unavailable")


class FakeAuditLog:
    def __init__(self):
        self.events = []

    async def record(self, **event):
        self.events.append(event)


class FakeRefreshCache:
    def __init__(self):
        self.reason = ""

    async def refresh(self, *, reason):
        self.reason = reason

    def status(self):
        return {
            "available": True,
            "source": "persistent-web-cache",
            "refreshedAt": "2026-07-29T00:00:00+00:00",
            "ageSeconds": 0,
            "refreshIntervalSeconds": 86400,
            "nextRefreshAt": "2026-07-30T00:00:00+00:00",
            "refreshing": False,
            "lastAttemptAt": "2026-07-29T00:00:00+00:00",
            "lastError": None,
            "lastRefreshReason": self.reason or None,
            "counts": {"generatorMaterials": 1},
        }


def _settings(database_path: str, **overrides) -> Settings:
    return Settings(
        _env_file=None,
        database_path=database_path,
        filemaker_database="cache-test",
        filemaker_part_read_layout="新增零件资料",
        filemaker_part_write_layout="@零件",
        filemaker_part_options_cache_refresh_interval_seconds=24 * 60 * 60,
        **overrides,
    )


@pytest.mark.asyncio
async def test_cache_survives_restart_without_reading_filemaker(tmp_path) -> None:
    database_path = str(tmp_path / "app.db")
    settings = _settings(database_path)
    filemaker = FakeFileMaker()
    cache = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=filemaker,
        settings=settings,
    )
    await cache.init()
    await cache.ensure_seeded()

    first = await cache.get()
    assert first.generator.materials[0].label == "铝件"
    assert filemaker.metadata_calls == [
        "新增零件资料",
        "MaterialIDGenerator_Gen",
    ]

    restarted = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=FailingFileMaker(),
        settings=settings,
    )
    await restarted.init()
    second = await restarted.get()

    assert second == first
    assert second.defaults.machining_category == ""
    assert restarted.status()["available"] is True
    assert restarted.status()["source"] == "persistent-web-cache"


@pytest.mark.asyncio
async def test_cached_defaults_are_replaced_with_current_service_defaults(tmp_path) -> None:
    database_path = str(tmp_path / "app.db")
    settings = _settings(database_path)
    cache = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=FakeFileMaker(),
        settings=settings,
    )
    await cache.init()
    await cache.ensure_seeded()

    with sqlite3.connect(database_path) as db:
        row = db.execute(
            "SELECT payload_json FROM filemaker_reference_cache WHERE cache_key = ?",
            ("part-creation-options",),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["defaults"]["machiningCategory"] = "外购"
        db.execute(
            "UPDATE filemaker_reference_cache SET payload_json = ? WHERE cache_key = ?",
            (json.dumps(payload, ensure_ascii=False), "part-creation-options"),
        )

    restarted = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=FailingFileMaker(),
        settings=settings,
    )
    await restarted.init()

    assert (await restarted.get()).defaults.machining_category == ""


@pytest.mark.asyncio
async def test_manual_refresh_replaces_persisted_values(tmp_path) -> None:
    database_path = str(tmp_path / "app.db")
    settings = _settings(database_path)
    filemaker = FakeFileMaker(material_label="旧名称")
    cache = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=filemaker,
        settings=settings,
    )
    await cache.init()
    await cache.refresh(reason="startup")

    filemaker.material_label = "新名称"
    refreshed = await cache.refresh(reason="manual:admin")

    assert refreshed.generator.materials[0].label == "新名称"
    assert cache.status()["lastRefreshReason"] == "manual:admin"
    assert cache.status()["counts"]["generatorMaterials"] == 1

    restarted = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=FailingFileMaker(),
        settings=settings,
    )
    await restarted.init()
    assert (await restarted.get()).generator.materials[0].label == "新名称"


@pytest.mark.asyncio
async def test_concurrent_refresh_is_single_flight(tmp_path) -> None:
    database_path = str(tmp_path / "app.db")
    settings = _settings(database_path)
    filemaker = FakeFileMaker()
    cache = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=filemaker,
        settings=settings,
    )
    await cache.init()

    first, second = await asyncio.gather(
        cache.refresh(reason="manual:first"),
        cache.refresh(reason="manual:second"),
    )

    assert first == second
    assert filemaker.metadata_calls.count("新增零件资料") == 1
    assert filemaker.metadata_calls.count("MaterialIDGenerator_Gen") == 1


@pytest.mark.asyncio
async def test_failed_refresh_keeps_last_good_cache(tmp_path) -> None:
    database_path = str(tmp_path / "app.db")
    settings = _settings(database_path)
    cache = PartCreationOptionsCache(
        database_path=database_path,
        filemaker=FakeFileMaker(),
        settings=settings,
    )
    await cache.init()
    original = await cache.refresh(reason="startup")
    cache.filemaker = FailingFileMaker()

    with pytest.raises(RuntimeError, match="FileMaker unavailable"):
        await cache.refresh(reason="manual:admin")

    assert await cache.get() == original
    assert cache.status()["available"] is True
    assert cache.status()["lastError"] == "FileMaker unavailable"


@pytest.mark.asyncio
async def test_manual_refresh_requires_account_admin_permission() -> None:
    with pytest.raises(HTTPException) as exc:
        await refresh_part_creation_cache(
            cache=FakeRefreshCache(),
            access={"canManageAccounts": False},
            operator=OperatorContext(
                session_id="session",
                account="amy",
                name="Amy",
            ),
            audit_log=FakeAuditLog(),
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["permission"] == "canManageAccounts"


@pytest.mark.asyncio
async def test_manual_refresh_is_audited_with_operator_account() -> None:
    cache = FakeRefreshCache()
    audit_log = FakeAuditLog()

    status = await refresh_part_creation_cache(
        cache=cache,
        access={"canManageAccounts": True},
        operator=OperatorContext(
            session_id="session",
            account="amy",
            name="Amy",
        ),
        audit_log=audit_log,
    )

    assert cache.reason == "manual:amy"
    assert status.last_refresh_reason == "manual:amy"
    assert audit_log.events[0]["action_type"] == "REFRESH_PART_CREATION_CACHE"
    assert audit_log.events[0]["status"] == "success"

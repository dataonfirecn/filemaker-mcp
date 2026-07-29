import asyncio

import pytest

from app.services.material_id_options import (
    load_material_id_options,
    search_related_parts,
)


class FakeFileMaker:
    def __init__(self):
        self.metadata_calls = 0
        self.record_calls: list[str] = []

    async def get_layout_metadata(self, layout):
        assert layout == "MaterialIDGenerator_Gen"
        self.metadata_calls += 1
        return {
            "valueLists": [
                {
                    "name": "零件性質",
                    "values": [
                        {"value": "CB", "displayValue": "CB 碳纤维"},
                        {"value": "AL", "displayValue": "AL 铝件"},
                    ],
                },
                {
                    "name": "客戶2",
                    "values": [
                        {"value": "007", "displayValue": "007 Simba Dickie HK Ltd."},
                    ],
                },
            ]
        }

    async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
        self.record_calls.append(layout)
        if layout == "@零件":
            assert query == [
                {"part_number": "*CB007*"},
                {"part_name_internal": "*CB007*"},
                {"part_name_external": "*CB007*"},
            ]
            return {
                "data": [
                    {
                        "fieldData": {
                            "part_number": "CB007-001",
                            "part_name_internal": "碳纤维底板",
                            "part_name_external": "Carbon chassis",
                        }
                    }
                ],
                "foundCount": 1,
            }
        records = {
            "MaterialManufactor_EDIT": [("LD", "镭雕"), ("YM", "研磨")],
            "MaterialColor_EDIT": [("DBK", "氧化黑色")],
            "MaterialOther_EDIT": [("PS", "特殊")],
        }[layout]
        return {
            "data": [
                {"fieldData": {"init": code, "description": label}}
                for code, label in records
            ]
        }


@pytest.mark.asyncio
async def test_options_keep_filemaker_codes_and_descriptions() -> None:
    response = await load_material_id_options(FakeFileMaker())

    assert [(item.code, item.label) for item in response.materials] == [
        ("CB", "碳纤维"),
        ("AL", "铝件"),
    ]
    assert [(item.code, item.label) for item in response.customers] == [
        ("007", "Simba Dickie HK Ltd."),
    ]
    assert [item.code for item in response.manufactures] == ["LD", "YM"]
    assert [item.code for item in response.colors] == ["DBK"]
    assert [item.code for item in response.others] == ["PS"]


@pytest.mark.asyncio
async def test_options_are_cached_for_concurrent_and_repeated_reads() -> None:
    filemaker = FakeFileMaker()

    first, second = await asyncio.gather(
        load_material_id_options(filemaker, cache_ttl_seconds=24 * 60 * 60),
        load_material_id_options(filemaker, cache_ttl_seconds=24 * 60 * 60),
    )
    third = await load_material_id_options(
        filemaker,
        cache_ttl_seconds=24 * 60 * 60,
    )

    assert first == second == third
    assert filemaker.metadata_calls == 1
    assert filemaker.record_calls == [
        "MaterialManufactor_EDIT",
        "MaterialColor_EDIT",
        "MaterialOther_EDIT",
    ]


@pytest.mark.asyncio
async def test_zero_ttl_bypasses_options_cache() -> None:
    filemaker = FakeFileMaker()

    await load_material_id_options(filemaker, cache_ttl_seconds=0)
    await load_material_id_options(filemaker, cache_ttl_seconds=0)

    assert filemaker.metadata_calls == 2
    assert filemaker.record_calls.count("MaterialManufactor_EDIT") == 2


@pytest.mark.asyncio
async def test_related_part_search_reads_names_from_filemaker() -> None:
    response = await search_related_parts(FakeFileMaker(), "CB007", limit=20)

    assert response.found_count == 1
    assert response.items[0].part_number == "CB007-001"
    assert response.items[0].internal_name == "碳纤维底板"
    assert response.items[0].external_name == "Carbon chassis"


@pytest.mark.asyncio
async def test_related_part_search_drops_find_operators() -> None:
    response = await search_related_parts(FakeFileMaker(), "", limit=20)

    assert response.items == []
    assert response.found_count == 0

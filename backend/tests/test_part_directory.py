from datetime import date

import pytest

from app.services.part_directory import build_part_filter, list_part_directory


def test_build_part_filter_combines_master_data_and_shanghai_date_range() -> None:
    result = build_part_filter(
        query="TG-01",
        material_category="TG 吊卡 卡板",
        part_category="吊卡",
        lifecycle_status="可量产",
        audit_status="已審核",
        manufacturer="三嘉",
        department="采购",
        warehouse_division="包装部",
        warehouse_code="B1",
        time_field="updated",
        date_from=date(2026, 7, 27),
        date_to=date(2026, 7, 27),
    )

    assert "startswith(part_number,'TG-01')" in result
    assert "startswith(part_id,'TG-01')" in result
    assert "contains(part_name_internal,'TG-01')" in result
    assert "material_category eq 'TG 吊卡 卡板'" in result
    assert "part_category eq '吊卡'" in result
    assert "part_lifecycle_status eq '可量产'" in result
    assert "審核 eq '已審核'" in result
    assert "contains(製造商,'三嘉')" in result
    assert "部門分工 eq '采购'" in result
    assert "倉庫分工 eq '包装部'" in result
    assert "warehouse_code eq 'B1'" in result
    assert "updated_at ge 2026-07-26T16:00:00Z" in result
    assert "updated_at lt 2026-07-27T16:00:00Z" in result


def test_build_part_filter_uses_date_literals_for_drawing_range() -> None:
    result = build_part_filter(
        time_field="drawing",
        date_from=date(2026, 7, 1),
        date_to=date(2026, 7, 31),
    )

    assert result == (
        "圖面修改日期 ge 2026-07-01 and "
        "圖面修改日期 lt 2026-08-01"
    )


@pytest.mark.asyncio
async def test_list_part_directory_does_not_query_without_filters() -> None:
    class ODataMustNotRun:
        async def records(self, *_args, **_kwargs):
            raise AssertionError("Empty directory request must not query FileMaker")

    result = await list_part_directory(
        odata=ODataMustNotRun(),  # type: ignore[arg-type]
        storage=object(),  # type: ignore[arg-type]
        query="",
        page=1,
        page_size=10,
        material_category="",
        part_category="",
        lifecycle_status="",
        audit_status="",
        manufacturer="",
        department="",
        warehouse_division="",
        warehouse_code="",
        time_field="updated",
        date_from=None,
        date_to=None,
    )

    assert result["requiresFilter"] is True
    assert result["rows"] == []
    assert result["foundCount"] == 0
    assert result["totalCount"] is None

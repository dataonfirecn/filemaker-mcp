import pytest

from app.api.quality import _part_standard_row, _quality_spec
from app.services.quality_standards import dimension_check_items
from test_quality_api import FakeQualityOData


def example_part():
    return {
        "part_number": "SE39016",
        "檢查A尺寸": "6.90", "檢查A尺寸公差": "+0.00", "檢查A尺寸公差2": "-0.10",
        "檢查B尺寸": "5.80", "檢查B尺寸公差": "+0.00", "檢查B尺寸公差2": "-0.03",
        "檢查C尺寸": "3.10", "檢查C尺寸公差": "贯穿", "檢查C尺寸公差2": "",
        "檢查D尺寸": " ", "檢查D尺寸公差": None,
    }


def test_dimensions_match_the_filemaker_table_and_empty_rows_are_omitted():
    items = dimension_check_items(example_part(), sample_count=10)
    assert [item.code for item in items] == ["A", "B", "C"]
    assert (items[0].lower_limit, items[0].upper_limit) == (6.8, 6.9)
    assert (items[1].lower_limit, items[1].upper_limit) == (5.77, 5.8)
    assert items[0].standard_text == "6.90 / +0.00 / -0.10"
    assert all(item.sample_count == 10 for item in items)
    c = items[2]
    assert c.target_value == 3.1
    assert c.input_type == "measurement_result"
    assert c.result_kind == "through"
    assert c.lower_limit is None and c.upper_limit is None


def test_numeric_filemaker_tolerances_keep_signed_two_decimal_display():
    items = dimension_check_items({
        "檢查A尺寸": "6.90",
        "檢查A尺寸公差": 0,
        "檢查A尺寸公差2": -0.1,
    }, sample_count=10)

    assert items[0].standard_text == "6.90 / +0.00 / -0.10"


@pytest.mark.parametrize("upper,lower,limits", [
    ("±0.02", "", (3.08, 3.12)),
    ("＋0.00", "−0.03", (3.07, 3.1)),
    ("", "", (None, None)),
    ("+0.00", "", (None, None)),
    ("-0.10", "+0.10", (None, None)),
    ("贯穿", "", (None, None)),
    ("0.02待确认", "", (None, None)),
])
def test_tolerances_are_explicit_and_never_guessed(upper, lower, limits):
    items = dimension_check_items({"檢查A尺寸": "φ3.10 mm", "檢查A尺寸公差": upper,
                                   "檢查A尺寸公差2": lower}, sample_count=3)
    assert (items[0].lower_limit, items[0].upper_limit) == limits
    assert items[0].sample_count == 3


def test_non_numeric_and_last_row_standards_are_preserved():
    items = dimension_check_items({"檢查A尺寸": "M3×0.5", "檢查L尺寸": 0,
                                   "檢查L尺寸公差": "0", "檢查L尺寸公差2": "0"}, sample_count=10)
    assert [item.code for item in items] == ["A", "L"]
    assert items[0].input_type == "result"
    assert items[0].standard_text == "M3×0.5"
    assert items[1].target_value == 0


@pytest.mark.asyncio
async def test_api_uses_dimensions_and_text_specs_with_distinct_ids_and_version():
    odata = FakeQualityOData()
    part = example_part()
    part["part_number"] = "PART-88"
    odata.parts = [part]
    version, items = await _quality_spec(odata, part_number="PART-88", measurement_count=3)
    assert [item.id for item in items] == ["A", "B", "C", "SPEC-1", "SPEC-2"]
    assert items[0].sample_count == 3
    assert items[-1].input_type == "result"
    part["檢查A尺寸公差2"] = "-0.20"
    revised, _ = await _quality_spec(odata, part_number="PART-88", measurement_count=3)
    assert version.version != revised.version


@pytest.mark.asyncio
async def test_no_standard_does_not_generate_invented_checks():
    odata = FakeQualityOData()
    odata.specs = []
    _, items = await _quality_spec(odata, part_number="PART-88")
    assert items == []


@pytest.mark.asyncio
async def test_part_standard_query_is_chunked_for_filemaker_url_limit():
    class URLLimitedQualityOData(FakeQualityOData):
        def __init__(self):
            super().__init__()
            self.part_selects = []

        async def records(self, table, **kwargs):
            if table == "零件":
                selected = list(kwargs.get("select") or [])
                self.part_selects.append(selected)
                if len(selected) > 7:
                    raise AssertionError("simulated FileMaker/IIS URL limit")
            return await super().records(table, **kwargs)

    odata = URLLimitedQualityOData()
    part = example_part()
    part["part_number"] = "PART-88"
    odata.parts = [part]

    row = await _part_standard_row(odata, part_number="PART-88")

    assert row["檢查A尺寸"] == "6.90"
    assert row["檢查C尺寸公差"] == "贯穿"
    assert len(odata.part_selects) == 6
    assert all(len(fields) <= 7 for fields in odata.part_selects)


@pytest.mark.asyncio
async def test_data_api_preserves_qualitative_text_in_number_tolerance_field():
    class MixedValueDataAPI:
        async def find_records(self, layout, query, limit):
            assert layout == "@零件"
            assert query == {"part_number": "==SE39016"}
            assert limit == 2
            return {"data": [{"fieldData": example_part()}]}

    odata = FakeQualityOData()
    odata.parts = [{
        **example_part(),
        "檢查C尺寸公差": None,
    }]

    row = await _part_standard_row(
        odata,
        filemaker=MixedValueDataAPI(),
        part_number="SE39016",
    )
    items = dimension_check_items(row, sample_count=10)

    c = items[2]
    assert c.standard_text == "3.10 / 贯穿"
    assert c.input_type == "measurement_result"
    assert c.result_kind == "through"

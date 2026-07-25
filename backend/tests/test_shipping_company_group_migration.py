import pytest

from scripts.migrate_shipping_company_group_id import (
    MAYAKO_COMPANY_ID,
    WT_GLOBAL_COMPANY_ID,
    _update_records,
    canonical_group_id,
)


def test_mayako_and_wt_share_the_mayako_group() -> None:
    mapping = {
        MAYAKO_COMPANY_ID: MAYAKO_COMPANY_ID,
        WT_GLOBAL_COMPANY_ID: MAYAKO_COMPANY_ID,
    }

    assert canonical_group_id(MAYAKO_COMPANY_ID, mapping) == MAYAKO_COMPANY_ID
    assert canonical_group_id(WT_GLOBAL_COMPANY_ID, mapping) == MAYAKO_COMPANY_ID


def test_other_companies_keep_their_configured_group() -> None:
    source_id = "OTHER-COMPANY-ID"

    assert canonical_group_id(source_id, {source_id: "PARENT-GROUP-ID"}) == "PARENT-GROUP-ID"


def test_unknown_legacy_company_falls_back_to_its_original_id() -> None:
    source_id = "LEGACY-COMPANY-ID"

    assert canonical_group_id(source_id, {}) == source_id
    assert canonical_group_id("", {}) == ""


@pytest.mark.asyncio
async def test_backfill_uses_script_entry_mode() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        async def update_record(
            self,
            layout: str,
            record_id: str,
            data: dict[str, str],
            *,
            entry_mode: str | None = None,
        ) -> None:
            self.calls.append((layout, record_id, data, entry_mode))

    client = FakeClient()
    failures = await _update_records(
        client,
        "@出貨單",
        [("445", "GROUP-ID")],
        concurrency=1,
    )

    assert failures == []
    assert client.calls == [
        ("@出貨單", "445", {"出貨公司群組ID": "GROUP-ID"}, "script")
    ]

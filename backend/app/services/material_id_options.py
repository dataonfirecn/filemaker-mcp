from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from weakref import WeakKeyDictionary

from app.models.material_ids import (
    MaterialIdOption,
    MaterialIdOptionsResponse,
    RelatedPartOption,
    RelatedPartSearchResponse,
)
from app.services.filemaker_client import FileMakerClient

GENERATOR_LAYOUT = "MaterialIDGenerator_Gen"
PART_LAYOUT = "@零件"
DEFAULT_OPTIONS_CACHE_TTL_SECONDS = 24 * 60 * 60

CONFIG_LAYOUTS = {
    "manufactures": "MaterialManufactor_EDIT",
    "colors": "MaterialColor_EDIT",
    "others": "MaterialOther_EDIT",
}

VALUE_LISTS = {
    "materials": "零件性質",
    "customers": "客戶2",
}

PART_FIELDS = {
    "number": "part_number",
    "internal": "part_name_internal",
    "external": "part_name_external",
}

_options_cache: WeakKeyDictionary[
    FileMakerClient, tuple[float, MaterialIdOptionsResponse]
] = WeakKeyDictionary()
_options_locks: WeakKeyDictionary[FileMakerClient, asyncio.Lock] = WeakKeyDictionary()


async def load_material_id_options(
    filemaker: FileMakerClient,
    *,
    cache_ttl_seconds: int = DEFAULT_OPTIONS_CACHE_TTL_SECONDS,
) -> MaterialIdOptionsResponse:
    ttl_seconds = max(0, int(cache_ttl_seconds))
    cached = _cached_options(filemaker, ttl_seconds)
    if cached is not None:
        return cached

    lock = _options_locks.get(filemaker)
    if lock is None:
        lock = asyncio.Lock()
        _options_locks[filemaker] = lock

    async with lock:
        cached = _cached_options(filemaker, ttl_seconds)
        if cached is not None:
            return cached

        response = await _load_material_id_options_uncached(filemaker)
        if ttl_seconds > 0:
            _options_cache[filemaker] = (time.monotonic(), response)
        return response.model_copy(deep=True)


def clear_material_id_options_cache(filemaker: FileMakerClient | None = None) -> None:
    if filemaker is None:
        _options_cache.clear()
        return
    _options_cache.pop(filemaker, None)


def _cached_options(
    filemaker: FileMakerClient,
    ttl_seconds: int,
) -> MaterialIdOptionsResponse | None:
    if ttl_seconds <= 0:
        return None
    cached = _options_cache.get(filemaker)
    if cached is None:
        return None
    cached_at, response = cached
    if time.monotonic() - cached_at >= ttl_seconds:
        _options_cache.pop(filemaker, None)
        return None
    return response.model_copy(deep=True)


async def _load_material_id_options_uncached(
    filemaker: FileMakerClient,
) -> MaterialIdOptionsResponse:
    config_items = list(CONFIG_LAYOUTS.items())
    metadata, *config_results = await asyncio.gather(
        filemaker.get_layout_metadata(GENERATOR_LAYOUT),
        *(
            filemaker.find_records(layout, limit=500)
            for _, layout in config_items
        ),
    )
    value_lists = {
        str(item.get("name") or ""): item
        for item in metadata.get("valueLists", [])
        if isinstance(item, dict)
    }

    values: dict[str, list[MaterialIdOption]] = {}
    for response_key, value_list_name in VALUE_LISTS.items():
        value_list = value_lists.get(value_list_name) or {}
        values[response_key] = _options_from_value_list(value_list.get("values"))

    for (response_key, _), result in zip(config_items, config_results, strict=True):
        values[response_key] = _options_from_records(result.get("data"))

    return MaterialIdOptionsResponse(
        materials=values["materials"],
        customers=values["customers"],
        manufactures=values["manufactures"],
        colors=values["colors"],
        others=values["others"],
    )


async def search_related_parts(
    filemaker: FileMakerClient,
    query: str,
    *,
    limit: int,
) -> RelatedPartSearchResponse:
    normalized = _normalize_search_term(query)
    if not normalized:
        return RelatedPartSearchResponse(items=[], foundCount=0)

    criterion = f"*{normalized}*"
    result = await filemaker.find_records(
        PART_LAYOUT,
        query=[
            {PART_FIELDS["number"]: criterion},
            {PART_FIELDS["internal"]: criterion},
            {PART_FIELDS["external"]: criterion},
        ],
        limit=limit,
    )

    items: list[RelatedPartOption] = []
    seen: set[str] = set()
    for record in result.get("data", []):
        fields = record.get("fieldData") or {}
        part_number = _text(fields.get(PART_FIELDS["number"]))
        if not part_number or part_number in seen:
            continue
        seen.add(part_number)
        items.append(
            RelatedPartOption(
                partNumber=part_number,
                internalName=_text(fields.get(PART_FIELDS["internal"])),
                externalName=_text(fields.get(PART_FIELDS["external"])),
            )
        )

    return RelatedPartSearchResponse(
        items=items,
        foundCount=int(result.get("foundCount") or len(items)),
    )


def _options_from_value_list(raw_values: Any) -> list[MaterialIdOption]:
    options: list[MaterialIdOption] = []
    seen: set[str] = set()
    for item in raw_values if isinstance(raw_values, list) else []:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("value"))
        if not code or code in seen:
            continue
        seen.add(code)
        display = _text(item.get("displayValue"))
        label = _value_list_label(code, display)
        options.append(MaterialIdOption(code=code, label=label))
    return options


def _options_from_records(raw_records: Any) -> list[MaterialIdOption]:
    options: list[MaterialIdOption] = []
    seen: set[str] = set()
    for record in raw_records if isinstance(raw_records, list) else []:
        fields = record.get("fieldData") if isinstance(record, dict) else {}
        fields = fields if isinstance(fields, dict) else {}
        code = _text(fields.get("init"))
        if not code or code in seen:
            continue
        seen.add(code)
        options.append(
            MaterialIdOption(
                code=code,
                label=_text(fields.get("description")) or code,
            )
        )
    return sorted(options, key=lambda item: item.code.casefold())


def _value_list_label(code: str, display: str) -> str:
    if not display:
        return code
    pattern = rf"^{re.escape(code)}(?:\s+|$)"
    without_code = re.sub(pattern, "", display, count=1).strip()
    return without_code or display


def _normalize_search_term(value: str) -> str:
    value = _text(value)
    # FileMaker find operators must not be accepted from the browser.
    return re.sub(r"[\r\n*#@!<>=…\\\"]+", " ", value).strip()[:80]


def _text(value: Any) -> str:
    return str(value or "").strip()

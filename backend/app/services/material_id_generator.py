from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.models.material_ids import (
    MaterialIdGenerationRequest,
    MaterialIdGenerationResponse,
)
from app.services.filemaker_client import FileMakerClient

PART_LAYOUT = "@零件"
PART_NUMBER_FIELD = "part_number"
QUERY_PAGE_SIZE = 500
MAX_PREFIX_MATCHES = 5000
ALGORITHM_VERSION = "filemaker-dof-idgen-v1"


class MaterialIdGenerationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _SerialScan:
    serial: str
    scanned_count: int


async def generate_material_id(
    filemaker: FileMakerClient,
    request: MaterialIdGenerationRequest,
) -> MaterialIdGenerationResponse:
    material = _plain_text(request.material)
    customer = _plain_text(request.customer)
    manual_serial = _plain_text(request.serial)
    manufacture = _plain_text(request.manufacture)
    color = _plain_text(request.color)
    other = _plain_text(request.other)
    script_part_number = _plain_text(request.script_part_number)

    if not material:
        raise MaterialIdGenerationError("missing_material", "请先选择零件性质。")
    if not customer:
        raise MaterialIdGenerationError("missing_customer", "请先选择客户。")

    prefix = f"{material}{customer}-"
    if manual_serial:
        serial = manual_serial
        scanned_count = 0
        auto_serial = False
    else:
        scan = await _next_serial(filemaker, prefix)
        serial = scan.serial
        scanned_count = scan.scanned_count
        auto_serial = True

    part_number = prefix + serial
    suffixes = [value for value in (manufacture, color, other) if value]
    if suffixes:
        part_number += "-" + "-".join(suffixes)

    duplicate = await filemaker.find_records(
        PART_LAYOUT,
        query={PART_NUMBER_FIELD: f"=={part_number}"},
        limit=1,
        offset=1,
    )
    exists = bool(_records(duplicate))
    if exists:
        raise MaterialIdGenerationError(
            "duplicate_part_number",
            f"零件编号 {part_number} 已存在。",
            status_code=409,
        )

    matches_script = (
        part_number == script_part_number if script_part_number else None
    )
    explanation = [
        f"前缀：{material} + {customer}",
        (
            f"自动流水号：{serial}（检查 {scanned_count} 条同前缀编号）"
            if auto_serial
            else f"手工流水号：{serial}"
        ),
    ]
    if suffixes:
        explanation.append("扩展段：" + " / ".join(suffixes))
    explanation.append("完整编号未在零件表中发现重复")

    return MaterialIdGenerationResponse(
        partNumber=part_number,
        serial=serial,
        prefix=prefix,
        autoSerial=auto_serial,
        exists=False,
        scriptPartNumber=script_part_number,
        matchesScript=matches_script,
        scannedCount=scanned_count,
        algorithmVersion=ALGORITHM_VERSION,
        explanation=explanation,
    )


async def _next_serial(
    filemaker: FileMakerClient,
    prefix: str,
) -> _SerialScan:
    records = await _prefix_records(filemaker, prefix)
    if not records:
        return _SerialScan(serial="001", scanned_count=0)

    max_value: int | None = None
    for record in records:
        part_number = _plain_text(_fields(record).get(PART_NUMBER_FIELD))
        segments = part_number.split("-")
        if len(segments) < 2:
            continue
        serial_segment = segments[1]
        if len(serial_segment) != 3:
            continue
        numeric_value = _filemaker_number(serial_segment)
        if numeric_value > 0 and (max_value is None or numeric_value > max_value):
            max_value = numeric_value

    if max_value is None:
        raise MaterialIdGenerationError(
            "invalid_existing_serials",
            "已存在同前缀编号，但没有可识别的三位流水号。",
            status_code=409,
        )
    if max_value >= 999:
        raise MaterialIdGenerationError(
            "serial_exhausted",
            f"前缀 {prefix} 的三位流水号已经用完。",
            status_code=409,
        )
    return _SerialScan(
        serial=f"{max_value + 1:03d}",
        scanned_count=len(records),
    )


async def _prefix_records(
    filemaker: FileMakerClient,
    prefix: str,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    offset = 1
    found_count: int | None = None

    while len(collected) < MAX_PREFIX_MATCHES:
        remaining = MAX_PREFIX_MATCHES - len(collected)
        result = await filemaker.find_records(
            PART_LAYOUT,
            query={PART_NUMBER_FIELD: f"{prefix}*"},
            limit=min(QUERY_PAGE_SIZE, remaining),
            offset=offset,
        )
        page = _records(result)
        if found_count is None:
            found_count = int(result.get("foundCount") or len(page))
        if not page:
            break
        collected.extend(page)
        offset += len(page)
        if len(collected) >= found_count:
            break

    if found_count is not None and found_count > MAX_PREFIX_MATCHES:
        raise MaterialIdGenerationError(
            "too_many_prefix_matches",
            f"前缀 {prefix} 的历史编号超过安全扫描上限，暂时无法自动生成。",
            status_code=409,
        )
    return collected


def _records(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("fieldData")
    return value if isinstance(value, dict) else {}


def _plain_text(value: Any) -> str:
    return str(value or "").strip()


def _filemaker_number(value: str) -> int:
    digits = "".join(re.findall(r"\d", value))
    return int(digits) if digits else 0

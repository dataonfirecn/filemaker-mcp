from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


FILEMAKER_TIMEZONE = ZoneInfo("Asia/Shanghai")

_FILEMAKER_TIMESTAMP_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_filemaker_timestamp(value: Any) -> datetime | None:
    """Parse a FileMaker timestamp as an Asia/Shanghai wall-clock value.

    FileMaker OData labels timestamp fields with ``Z`` even though their clock
    components are stored in the FileMaker server's local timezone. Trusting
    that suffix as UTC shifts receipt times eight hours forward on China-based
    clients. This helper intentionally preserves the clock components and
    attaches the actual FileMaker timezone.
    """

    parsed: datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for date_format in _FILEMAKER_TIMESTAMP_FORMATS:
                try:
                    parsed = datetime.strptime(raw, date_format)
                    break
                except ValueError:
                    continue

    if parsed is None:
        return None
    wall_clock = parsed.replace(tzinfo=None)
    return wall_clock.replace(tzinfo=FILEMAKER_TIMEZONE)


def format_filemaker_timestamp(value: Any) -> str:
    parsed = parse_filemaker_timestamp(value)
    return parsed.isoformat() if parsed else ""

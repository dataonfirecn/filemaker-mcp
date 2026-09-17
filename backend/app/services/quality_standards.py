"""Convert FileMaker's A–L standards into versioned, explicit input definitions."""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from string import ascii_uppercase

from app.models.quality import QualityCheckItem


PART_STANDARD_FIELDS = (
    "part_number",
    *(f"檢查{code}尺寸{suffix}" for code in ascii_uppercase[:12]
      for suffix in ("", "公差", "公差2")),
)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _tolerance_text(value: object) -> str:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return f"{Decimal(str(value)):+.2f}"
    return _text(value)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).replace("−", "-").strip()


def _number(value: str, *, dimension: bool = False) -> Decimal | None:
    pattern = rf"(?:[φΦØø⌀]\s*)?({_NUMBER})(?:\s*(?:mm|毫米))?" if dimension else rf"({_NUMBER})"
    match = re.fullmatch(pattern, _normalized(value), flags=re.IGNORECASE)
    return Decimal(match[1]) if match else None


def dimension_check_items(part: dict, *, sample_count: int) -> list[QualityCheckItem]:
    items: list[QualityCheckItem] = []
    for code in ascii_uppercase[:12]:
        dimension = _text(part.get(f"檢查{code}尺寸"))
        tolerance = _tolerance_text(part.get(f"檢查{code}尺寸公差"))
        tolerance2 = _tolerance_text(part.get(f"檢查{code}尺寸公差2"))
        if not any((dimension, tolerance, tolerance2)):
            continue
        standard = " / ".join(value for value in (dimension, tolerance, tolerance2) if value)
        target = _number(dimension, dimension=True)
        upper_offset, lower_offset = _number(tolerance), _number(tolerance2)
        symmetric = re.fullmatch(rf"±\s*({_NUMBER})", _normalized(tolerance))
        if symmetric and not tolerance2:
            offset = Decimal(symmetric[1])
            if offset >= 0:
                upper_offset, lower_offset = offset, -offset

        # Empty/qualitative tolerances never imply zero or a drawing's general tolerance.
        lower = upper = None
        if target is not None and upper_offset is not None and lower_offset is not None:
            if lower_offset <= upper_offset:
                lower, upper = target + lower_offset, target + upper_offset
        through = any(word in tolerance + tolerance2 for word in ("贯穿", "貫穿", "通孔"))
        qualitative = bool(tolerance or tolerance2) and lower is None
        input_type = (
            "measurement_result" if target is not None and qualitative
            else "measurement" if target is not None else "result"
        )
        items.append(QualityCheckItem(
            id=code,
            code=code,
            title=f"{code} 点" + ("孔径与贯穿" if through and target is not None else "检查"),
            instructions=("记录孔径实测值，并逐件确认通／不通。" if through and target is not None
                          else "按图面对应检查点记录实测值。" if target is not None
                          else "按原始标准检查并记录 OK / NG。"),
            inputType=input_type,
            unit="mm" if target is not None else "",
            targetValue=float(target) if target is not None else None,
            lowerLimit=float(lower) if lower is not None else None,
            upperLimit=float(upper) if upper is not None else None,
            required=True,
            sampleCount=sample_count if target is not None else 1,
            standardText=standard,
            resultKind="through" if through else None,
        ))
    return items

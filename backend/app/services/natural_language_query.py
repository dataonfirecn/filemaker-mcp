from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings


PRODUCT_API_LAYOUT = "@products"
PARTS_LAYOUT = "Parts"
PRODUCT_SEARCH_FIELDS = [
    "product_sku",
    "系統產品編號",
    "product_name",
    "產品名稱_中文",
    "車款",
    "車子比例",
    "類別",
    "Client",
    "客戶_Privilege::客戶公司簡稱",
    "Category_Product_1::title",
    "Category_Product_2::title",
    "Category_Product_3::title",
]
PART_SEARCH_FIELDS = [
    "part_number",
    "part_name",
    "part_name_en",
    "專屬客戶",
    "零件_客戶::客戶公司簡稱",
    "零件_客戶::客戶代號",
    "Notes",
]

_EXACT_ID_FIELDS = {"product_sku", "系統產品編號", "part_number"}
_CREATED_FIELD_HINTS = ("created", "creation", "create", "创建", "創建", "建立", "新增", "录入", "錄入")
_CREATED_FIELD_EXCLUDES = (
    "updated",
    "modified",
    "created by",
    "created_by",
    "creator",
    "修改",
    "更新",
    "異動",
    "变更",
    "變更",
    "创建人",
    "創建人",
    "建立人",
    "新增人",
    "录入人",
    "錄入人",
)
_DATE_WORDS = (
    "今天",
    "今日",
    "昨天",
    "昨日",
    "前天",
    "本周",
    "這周",
    "这周",
    "上周",
    "本月",
    "这个月",
    "這個月",
    "上月",
    "最近",
    "近",
    "过去",
    "過去",
)
_KEYWORD_NOISE_TERMS = (
    "有哪些",
    "哪些",
    "哪个",
    "哪個",
    "哪种",
    "哪種",
    "多少",
    "还有",
    "還有",
    "一下",
    "材质",
    "材質",
    "材料",
    "的",
    "创建人",
    "創建人",
    "创建者",
    "創建者",
    "谁创建",
    "誰創建",
    "谁建立",
    "誰建立",
    "谁",
    "誰",
    "库存",
    "庫存",
    "当前库存",
    "當前庫存",
    "价格",
    "價格",
    "单价",
    "單價",
    "售价",
    "售價",
    "成本价",
    "成本價",
    "成本",
    "金额",
    "金額",
    "货值",
    "貨值",
    "运费",
    "運費",
    "报价",
    "報價",
    "估价",
    "估價",
    "总价",
    "總價",
    "多少钱",
    "多少錢",
    "毛利",
    "利润",
    "利潤",
    "时间戳",
    "時間戳",
    "具体时间",
    "具體時間",
    "创建时间",
    "創建時間",
    "新增时间",
    "新增時間",
    "名称",
    "名稱",
    "编号",
    "編號",
    "字段",
    "stock",
    "inventory",
    "current stock",
    "price",
    "unit price",
    "unit cost",
    "cost",
    "amount",
    "quote",
    "quotation",
    "shipping cost",
    "shipping fee",
    "freight",
    "margin",
    "profit",
    "total price",
    "created by",
    "created date",
    "creation date",
    "timestamp",
)
_TEMPORAL_LISTING_NOISE_TERMS = (
    "按最新记录排序",
    "按最新紀錄排序",
    "按最新排序",
    "具体时间戳",
    "具體時間戳",
    "最新创建",
    "最新創建",
    "最近创建",
    "最近創建",
    "最新新增",
    "最近新增",
    "包括",
    "包含",
    "展示",
    "显示",
    "顯示",
    "返回",
    "列出",
    "详情",
    "詳情",
    "明细",
    "明細",
    "信息",
    "資訊",
    "状态",
    "狀態",
    "重量",
    "创建",
    "創建",
    "新建",
    "建立",
    "新增",
    "录入",
    "錄入",
    "最新",
    "排序",
    "以及",
    "recently created",
    "recently added",
    "created",
    "added",
    "latest",
    "include",
    "including",
    "status",
    "weight",
    "sort",
    *_KEYWORD_NOISE_TERMS,
)


class NaturalQueryError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDateRange:
    label: str
    start: date
    end: date


@dataclass
class ProductNaturalQueryPlan:
    domain: str
    intent: str
    layout: str
    description: str
    query: list[dict[str, Any]]
    sort: list[dict[str, str]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)
    date_range: dict[str, str] | None = None
    warnings: list[str] = field(default_factory=list)


def build_product_natural_query_plan(
    prompt: str,
    *,
    layout_fields: list[dict[str, Any]],
    settings: Settings,
    now: datetime | None = None,
) -> ProductNaturalQueryPlan:
    normalized = _normalize_text(prompt)
    if not normalized:
        raise NaturalQueryError("请输入要查询的内容。")

    is_part_query = _looks_like_part_query(normalized)
    if _looks_like_non_product_query(normalized):
        raise NaturalQueryError("当前自然语言查询先支持产品资料。请在问题里包含“产品”或产品编号、名称、车款、客户等条件。")

    domain = "part" if is_part_query else "product"
    layout = PARTS_LAYOUT if is_part_query else PRODUCT_API_LAYOUT
    search_fields = PART_SEARCH_FIELDS if is_part_query else PRODUCT_SEARCH_FIELDS
    default_created_fields = ["Date Created"] if is_part_query else []
    entity_label = "零件" if is_part_query else "产品"

    current_time = now or _now(settings)
    parsed_date = _parse_date_range(normalized, current_time)
    wants_created_records = _wants_created_records(normalized) or parsed_date is not None
    wants_latest = _wants_latest(normalized)
    wants_timestamp_detail = _wants_timestamp_detail(normalized)
    field_by_name = _field_metadata_by_name(layout_fields)
    field_names = set(field_by_name)
    filters = {} if is_part_query else _parse_product_filters(normalized)
    keywords = _parse_keywords(normalized, filters, parsed_date)

    criteria: dict[str, Any] = {} if is_part_query else _criteria_from_filters(filters)
    warnings: list[str] = []
    date_info: dict[str, str] | None = None
    created_field = _select_created_field(
        settings,
        field_names,
        default_fields=default_created_fields,
    )

    if parsed_date:
        if not created_field:
            raise NaturalQueryError(
                f"没有在{entity_label}资料布局找到可用于“新增/创建日期”的字段。"
                "请先刷新 RAG metadata，或配置真实字段名。"
            )
        criteria[created_field] = _format_date_find_value(
            parsed_date,
            field_by_name.get(created_field, {"name": created_field}),
            settings,
        )
        date_info = {
            "label": parsed_date.label,
            "start": parsed_date.start.isoformat(),
            "end": parsed_date.end.isoformat(),
            "field": created_field,
        }
        if wants_timestamp_detail and not _has_timestamp_field(field_by_name):
            warnings.append(
                f"FileMaker 的 {layout} 布局目前只提供“{created_field}”日期字段，"
                "没有创建时间戳或更新时间字段；已回退显示创建日期。"
            )

    sort: list[dict[str, str]] = []
    if wants_latest or wants_created_records:
        if created_field:
            sort.append({"fieldName": created_field, "sortOrder": "descend"})
        elif wants_latest:
            warnings.append("未找到创建日期字段，结果未按最新排序。")

    query = _build_find_query(criteria, keywords, field_names, bool(sort), search_fields=search_fields)
    description = _describe_plan(keywords, filters, parsed_date, created_field, wants_latest, entity_label)
    return ProductNaturalQueryPlan(
        domain=domain,
        intent="find_parts" if is_part_query else "find_products",
        layout=layout,
        description=description,
        query=query,
        sort=sort,
        keywords=keywords,
        filters=filters,
        date_range=date_info,
        warnings=warnings,
    )


def _normalize_text(value: str) -> str:
    return (
        value.strip()
        .replace("，", " ")
        .replace("。", " ")
        .replace("；", " ")
        .replace("：", ":")
        .replace("？", "?")
    )


def _looks_like_non_product_query(text: str) -> bool:
    non_product_terms = ("发料", "發料", "订单", "訂單", "bom", "物料", "零件包")
    product_terms = (
        "产品",
        "產品",
        "product",
        "sku",
        "编号",
        "編號",
        "名称",
        "名稱",
        "车款",
        "車款",
        "客户",
        "客戶",
        "零件",
        "配件",
        "备件",
        "備件",
        "part",
        "parts",
        "spare",
    )
    lower = text.lower()
    return any(term in lower for term in non_product_terms) and not any(term in lower for term in product_terms)


def _looks_like_part_query(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in ("零件", "配件", "备件", "備件", "part", "parts", "spare"))


def _now(settings: Settings) -> datetime:
    try:
        tz = ZoneInfo(settings.natural_query_timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def parse_natural_date_range(
    text: str,
    *,
    settings: Settings,
    now: datetime | None = None,
) -> ParsedDateRange | None:
    """Expose the shared relative-date parser to other read-only query domains."""
    normalized = _normalize_text(text)
    if not normalized:
        return None
    return _parse_date_range(normalized, now or _now(settings))


def _parse_date_range(text: str, now: datetime) -> ParsedDateRange | None:
    today = now.date()
    lower = text.lower()
    if re.search(r"\bday\s+before\s+yesterday\b", lower):
        target = today - timedelta(days=2)
        return ParsedDateRange("前天", target, target)
    if re.search(r"\byesterday\b", lower):
        target = today - timedelta(days=1)
        return ParsedDateRange("昨天", target, target)
    if re.search(r"\btoday\b", lower):
        return ParsedDateRange("今天", today, today)
    if "前天" in text:
        target = today - timedelta(days=2)
        return ParsedDateRange("前天", target, target)
    if "昨天" in text or "昨日" in text:
        target = today - timedelta(days=1)
        return ParsedDateRange("昨天", target, target)
    if "今天" in text or "今日" in text:
        return ParsedDateRange("今天", today, today)

    if re.search(r"(?:最近|近|过去|過去)\s*(?:1|一)?\s*(?:周|週|星期|礼拜|禮拜)", text):
        return ParsedDateRange("近 7 天", today - timedelta(days=6), today)

    days_match = re.search(r"(?:最近|近|过去|過去)\s*([0-9一二两兩三四五六七八九十]{1,3})\s*天", text)
    if days_match:
        days = _parse_int(days_match.group(1))
        if days and 1 <= days <= 90:
            return ParsedDateRange(f"近 {days} 天", today - timedelta(days=days - 1), today)

    english_days_match = re.search(r"\b(?:last|past|previous)\s+(\d{1,2})\s+days?\b", lower)
    if english_days_match:
        days = int(english_days_match.group(1))
        if 1 <= days <= 90:
            return ParsedDateRange(f"近 {days} 天", today - timedelta(days=days - 1), today)

    if "本周" in text or "这周" in text or "這周" in text:
        start = today - timedelta(days=today.weekday())
        return ParsedDateRange("本周", start, today)
    if re.search(r"\bthis\s+week\b", lower):
        start = today - timedelta(days=today.weekday())
        return ParsedDateRange("本周", start, today)
    if "上周" in text:
        this_week_start = today - timedelta(days=today.weekday())
        start = this_week_start - timedelta(days=7)
        return ParsedDateRange("上周", start, start + timedelta(days=6))
    if re.search(r"\b(?:last|previous)\s+week\b", lower):
        this_week_start = today - timedelta(days=today.weekday())
        start = this_week_start - timedelta(days=7)
        return ParsedDateRange("上周", start, start + timedelta(days=6))
    if "本月" in text or "这个月" in text or "這個月" in text:
        return ParsedDateRange("本月", today.replace(day=1), today)
    if re.search(r"\bthis\s+month\b", lower):
        return ParsedDateRange("本月", today.replace(day=1), today)
    if "上月" in text:
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        return ParsedDateRange("上月", end.replace(day=1), end)
    if re.search(r"\b(?:last|previous)\s+month\b", lower):
        first_of_this_month = today.replace(day=1)
        end = first_of_this_month - timedelta(days=1)
        return ParsedDateRange("上月", end.replace(day=1), end)
    return None


def _parse_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    numerals = {
        "一": 1,
        "二": 2,
        "两": 2,
        "兩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if value.startswith("十") and len(value) == 2:
        return 10 + numerals.get(value[1], 0)
    if value.endswith("十") and len(value) == 2:
        return numerals.get(value[0], 0) * 10
    if "十" in value and len(value) == 3:
        return numerals.get(value[0], 0) * 10 + numerals.get(value[2], 0)
    return numerals.get(value)


def _wants_created_records(text: str) -> bool:
    lower = text.lower()
    return any(term in text for term in ("新增", "新建", "创建", "創建", "建立", "录入", "錄入")) or any(
        term in lower for term in ("added", "created", "newly entered", "newly added")
    )


def _wants_latest(text: str) -> bool:
    lower = text.lower()
    return any(term in text for term in ("最新", "最近新增", "最近创建", "最近建立", "新产品", "新產品")) or any(
        term in lower for term in ("latest", "recently added", "recently created", "new products")
    )


def _wants_timestamp_detail(text: str) -> bool:
    lower = text.lower()
    return any(
        term in lower
        for term in (
            "时间戳",
            "時間戳",
            "timestamp",
            "具体时间",
            "具體時間",
            "创建时间",
            "創建時間",
            "新增时间",
            "新增時間",
            "更新时间",
            "更新時間",
            "修改时间",
            "修改時間",
            "几点",
            "幾點",
        )
    )


def _field_metadata_by_name(layout_fields: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in layout_fields:
        name = str(item.get("name") or "")
        if name:
            result[name] = item
    return result


def _has_timestamp_field(field_by_name: dict[str, dict[str, Any]]) -> bool:
    return any(_is_timestamp_field(metadata) for metadata in field_by_name.values())


def _is_timestamp_field(metadata: dict[str, Any]) -> bool:
    name = str(metadata.get("name") or "").lower()
    field_type = str(
        metadata.get("result")
        or metadata.get("type")
        or metadata.get("fieldType")
        or metadata.get("displayType")
        or ""
    ).lower()
    if "turnover time" in name:
        return False
    timestamp_terms = (
        "timestamp",
        "created_at",
        "updated_at",
        "creationtimestamp",
        "recordcreationtimestamp",
        "created time",
        "time created",
        "modified at",
        "updated at",
        "last modified",
        "创建时间",
        "創建時間",
        "新增时间",
        "新增時間",
        "修改时间",
        "修改時間",
        "更新时间",
        "更新時間",
    )
    return (
        "timestamp" in field_type
        or bool(metadata.get("timeOfDay"))
        or any(term in name for term in timestamp_terms)
    )


def _select_created_field(
    settings: Settings,
    field_names: set[str],
    *,
    default_fields: list[str] | None = None,
) -> str | None:
    configured = [*(default_fields or []), *_split_csv(settings.natural_query_product_created_fields)]
    if not field_names:
        return configured[0] if configured else None

    for field_name in configured:
        if field_name in field_names:
            return field_name

    for field_name in field_names:
        lowered = field_name.lower()
        if any(hint in lowered for hint in _CREATED_FIELD_HINTS) and not any(
            exclude in lowered for exclude in _CREATED_FIELD_EXCLUDES
        ):
            return field_name
    return None


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _format_date_find_value(
    parsed_date: ParsedDateRange,
    metadata: dict[str, Any],
    settings: Settings,
) -> str:
    field_type = str(
        metadata.get("result")
        or metadata.get("type")
        or metadata.get("fieldType")
        or metadata.get("displayType")
        or ""
    ).lower()
    name = str(metadata.get("name") or "").lower()
    is_timestamp = "timestamp" in field_type or "時間戳" in name or "时间戳" in name

    if is_timestamp:
        start = datetime.combine(parsed_date.start, datetime.min.time()).strftime(
            settings.natural_query_filemaker_timestamp_format
        )
        end = datetime.combine(parsed_date.end, datetime.max.time()).replace(microsecond=0).strftime(
            settings.natural_query_filemaker_timestamp_format
        )
        return start if start == end else f"{start}...{end}"

    date_format = "%m/%d/%Y" if "date created" in name else settings.natural_query_filemaker_date_format
    start = parsed_date.start.strftime(date_format)
    end = parsed_date.end.strftime(date_format)
    return start if start == end else f"{start}...{end}"


def _parse_product_filters(text: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    _set_filter(
        filters,
        "model",
        _extract_labeled_value(text, ("车款", "車款", "车型", "車型", "型号", "型號", "model")),
    )
    _set_filter(
        filters,
        "category",
        _extract_labeled_value(text, ("类别", "類別", "分类", "分類", "category")),
    )
    _set_filter(filters, "scale", _extract_scale_value(text))
    _set_filter(filters, "client", _extract_labeled_value(text, ("客户", "客戶", "client", "Client")))
    audit_value = _extract_labeled_value(text, ("审核", "審核"))
    if not audit_value:
        if any(term in text for term in ("未审核", "未審核", "没审核", "未通过", "未通過")):
            audit_value = "未"
        elif any(term in text for term in ("已审核", "已審核", "审核通过", "審核通過", "通过", "通過")):
            audit_value = "通过"
    _set_filter(filters, "audit", audit_value)
    return filters


def _set_filter(filters: dict[str, str], key: str, value: str | None) -> None:
    if value:
        filters[key] = value


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*(?:是|为|為|=|:)?\s*([A-Za-z0-9_\-\u4e00-\u9fff ]{{1,48}})",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        value = _clean_captured_value(match.group(1))
        if value:
            return value
    return None


def _clean_captured_value(value: str) -> str:
    value = re.split(r"\s*(?:的|且|并且|並且|同时|同時|,|，|。|;|；|\?)\s*", value.strip(), maxsplit=1)[0]
    value = re.sub(
        r"(产品|產品|零件|记录|資料|资料|products?|parts?|records?)$",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    return value.strip()


def _extract_scale_value(text: str) -> str | None:
    match = re.search(
        r"\b(\d{1,2})\s*[:/]\s*(\d{1,2})\s*(?:scale)?\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    value = _extract_labeled_value(text, ("比例", "scale"))
    return value.strip() if value else None


def _criteria_from_filters(filters: dict[str, str]) -> dict[str, str]:
    criteria: dict[str, str] = {}
    if filters.get("category"):
        criteria["類別"] = _contains(filters["category"])
    if filters.get("model"):
        criteria["車款"] = _contains(filters["model"])
    if filters.get("scale"):
        criteria["車子比例"] = _contains(filters["scale"])
    if filters.get("audit"):
        criteria["審核"] = _contains(filters["audit"])
    if filters.get("client"):
        criteria["Client"] = _contains(filters["client"])
    return criteria


def _parse_keywords(
    text: str,
    filters: dict[str, str],
    parsed_date: ParsedDateRange | None,
) -> list[str]:
    keywords: list[str] = []
    for quoted in re.findall(r"[\"“”'‘’]([^\"“”'‘’]{1,60})[\"“”'‘’]", text):
        _append_keyword(keywords, quoted)

    sku_match = re.search(r"\b[A-Za-z0-9]{2,}(?:[-_][A-Za-z0-9]+)+\b", text)
    if sku_match:
        _append_keyword(keywords, sku_match.group(0))

    for label in (
        "编号",
        "編號",
        "产品编号",
        "產品編號",
        "零件编号",
        "零件編號",
        "part_number",
        "part no",
        "名称",
        "名稱",
        "产品名",
        "產品名",
        "零件名",
    ):
        value = _extract_labeled_value(text, (label,))
        if value:
            _append_keyword(keywords, value)

    if keywords or filters or parsed_date:
        return keywords

    cleaned = _strip_query_stopwords(text)
    if cleaned:
        _append_keyword(keywords, cleaned)
    return keywords


def _append_keyword(keywords: list[str], value: str) -> None:
    normalized = _clean_keyword(value)
    if normalized and _is_meaningful_keyword(normalized) and normalized not in keywords:
        keywords.append(normalized)


def _clean_keyword(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip())
    for source, target in (
        ("越野车", "buggy"),
        ("越野車", "buggy"),
        ("碳纤维", "carbon"),
        ("碳纖維", "carbon"),
    ):
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"^(?:的|是|为|為|=|:)+", "", normalized).strip()
    for word in ("有哪些", "哪些", "哪个", "哪個", "哪种", "哪種", "一下", "材质", "材質", "材料", "的"):
        normalized = normalized.replace(word, " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.strip(" ,，。?？!！;；:：")


def _is_meaningful_keyword(value: str) -> bool:
    residual = value
    for term in _KEYWORD_NOISE_TERMS:
        residual = residual.replace(term, " ")
    residual = re.sub(r"[\s,，。?？、;；:：的]+", "", residual)
    if not residual:
        return False
    if len(residual) == 1 and (residual in {"名", "称", "稱"} or residual != value):
        return False
    if len(value) == 1 and re.fullmatch(r"[\u4e00-\u9fff]", value):
        return False
    return True


def _strip_query_stopwords(text: str) -> str:
    temporal_listing = _wants_created_records(text) or _wants_latest(text)
    cleaned = text
    for pattern in (
        r"\b(?:please\s+)?(?:show|find|search|list|give|get|display|tell)\s+(?:me\s+)?\b",
        r"\b(?:do\s+you\s+(?:have|carry|sell)|are\s+there)\b",
        r"\b(?:i\s+am|i'm)\s+(?:looking|searching)\s+for\b",
        r"\bi\s+need\b",
        r"\bwhat\s+(?:products?|parts?)\s+do\s+you\s+have\b",
        r"\b(?:any|all|some)\b",
        r"\b(?:products?|parts?|spares?|records?)\b",
        r"\b(?:stock|inventory|availability)\b",
        r"\b(?:today|yesterday|day\s+before\s+yesterday|this\s+week|last\s+week|this\s+month|last\s+month)\b",
    ):
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    for word in (
        "帮我",
        "請",
        "请",
        "查找",
        "查询",
        "查詢",
        "查",
        "获取",
        "取得",
        "找",
        "显示",
        "顯示",
        "列出",
        "有没有",
        "有沒有",
        "是否有",
        "一下",
        "有哪些",
        "哪些",
        "哪个",
        "哪個",
        "哪种",
        "哪種",
        "材质",
        "材質",
        "材料",
        "产品",
        "產品",
        "零件",
        "配件",
        "备件",
        "備件",
        "记录",
        "資料",
        "资料",
        "FileMaker",
        "filemaker",
    ):
        cleaned = cleaned.replace(word, " ")
    for word in _DATE_WORDS:
        cleaned = cleaned.replace(word, " ")
    cleaned = cleaned.replace("的", " ")
    if temporal_listing:
        # LLMs sometimes append a projection clause copied from layout metadata,
        # for example "，返回零件编号、状态、替代编号". That clause is
        # not a user search term and must not become a FileMaker find criterion.
        cleaned = re.sub(
            r"\s(?:包括|包含|返回|展示|显示|顯示|列出)\s*.*$",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        for term in sorted(_TEMPORAL_LISTING_NOISE_TERMS, key=len, reverse=True):
            cleaned = re.sub(re.escape(term), " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"[()（）\[\]【】、]+", " ", cleaned)
        cleaned = re.sub(r"(^|\s)(?:及|和|与|與|按)(?=\s|$)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _build_find_query(
    criteria: dict[str, Any],
    keywords: list[str],
    field_names: set[str],
    needs_non_empty_query: bool,
    *,
    search_fields: list[str],
) -> list[dict[str, Any]]:
    valid_search_fields = [field for field in search_fields if not field_names or field in field_names]
    if keywords:
        query: list[dict[str, Any]] = []
        for keyword in keywords:
            for field in valid_search_fields:
                item = dict(criteria)
                item[field] = f"=={keyword}" if field in _EXACT_ID_FIELDS else _contains(keyword)
                query.append(item)
        return query

    if criteria:
        return [criteria]

    if needs_non_empty_query:
        preferred_fallback = next((field for field in ("product_sku", "part_number") if field in field_names), "")
        fallback_field = preferred_fallback or (valid_search_fields[0] if valid_search_fields else "")
        return [{fallback_field: "*"}] if fallback_field else []
    return []


def _contains(value: str) -> str:
    return f"*{value.strip()}*"


def _describe_plan(
    keywords: list[str],
    filters: dict[str, str],
    parsed_date: ParsedDateRange | None,
    created_field: str | None,
    wants_latest: bool,
    entity_label: str = "产品",
) -> str:
    parts: list[str] = []
    if parsed_date:
        date_text = parsed_date.label
        if created_field:
            date_text = f"{date_text}新增"
        parts.append(date_text)
    if keywords:
        parts.append("关键词：" + "、".join(keywords))
    for label, key in (
        ("车款", "model"),
        ("比例", "scale"),
        ("类别", "category"),
        ("客户", "client"),
        ("审核", "audit"),
    ):
        if filters.get(key):
            parts.append(f"{label}包含“{filters[key]}”")
    if wants_latest and not parsed_date:
        parts.append("按最新记录排序" if created_field else "未找到创建日期字段，结果未按最新排序")
    return "；".join(parts) or f"{entity_label}资料列表"

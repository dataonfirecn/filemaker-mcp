from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

SEMANTIC_PROFILE_SCHEMA_VERSION = 1
SEMANTIC_CONCEPTS = (
    "partNumber",
    "partName",
    "createdDate",
    "createdTimestamp",
    "createdBy",
    "updatedDate",
    "updatedTimestamp",
    "updatedBy",
    "stock",
    "price",
    "status",
    "customer",
)


async def build_layout_semantic_profile(
    *,
    layout: str,
    fields: list[dict[str, Any]],
    sample_records: list[dict[str, Any]] | None = None,
    settings: Settings,
) -> dict[str, Any]:
    fallback = fallback_layout_semantic_profile(
        layout=layout,
        fields=fields,
        sample_records=sample_records or [],
    )
    if not _should_use_llm(layout, settings):
        return fallback

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                        {
                            "layout": layout,
                            "fields": _compact_fields(fields),
                            "sampleRecords": _compact_sample_records(sample_records or []),
                            "concepts": list(SEMANTIC_CONCEPTS),
                        },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": max(
            settings.rag_index_semantic_llm_max_output_tokens,
            settings.llm_max_output_tokens,
        ),
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(
            timeout=max(settings.rag_index_semantic_llm_timeout_seconds, settings.llm_timeout_seconds),
            verify=settings.llm_ssl_verify,
        ) as client:
            response = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.RequestError:
        logger.exception("Unable to connect to LLM for FileMaker metadata semantics")
        return fallback

    if not response.is_success:
        logger.warning("LLM metadata semantics returned HTTP %s", response.status_code)
        return fallback

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("LLM metadata semantics response did not include message content")
        return fallback

    parsed = parse_layout_semantic_profile(
        content,
        layout=layout,
        fields=fields,
        sample_records=sample_records or [],
    )
    if not parsed:
        logger.warning("LLM metadata semantics response could not be parsed as profile JSON")
        return fallback
    return _merge_with_fallback(parsed, fallback)


def fallback_layout_semantic_profile(
    *,
    layout: str,
    fields: list[dict[str, Any]],
    sample_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    names = [str(field.get("name") or "") for field in fields if isinstance(field, dict) and field.get("name")]
    sample_records = sample_records or []
    field_metadata = {
        str(field.get("name") or ""): field
        for field in fields
        if isinstance(field, dict) and field.get("name")
    }
    field_profiles = {
        name: _field_profile(
            field=name,
            metadata=field_metadata.get(name, {}),
            semantic_label=_heuristic_field_label(name),
            description=_heuristic_field_description(name),
            sample_values=_sample_values_for_field(sample_records, name),
            confidence=0.65,
            source="heuristic",
        )
        for name in names
    }
    concepts: dict[str, dict[str, Any]] = {}
    for concept in SEMANTIC_CONCEPTS:
        field = _heuristic_field_for_concept(concept, names)
        concepts[concept] = _concept(
            field=field,
            label=_concept_label(concept),
            confidence=0.85 if field else 0,
            reason=(
                f"按字段名启发式匹配到 {field}。"
                if field
                else f"metadata 中没有发现可表示“{_concept_label(concept)}”的字段。"
            ),
        )
    return {
        "schemaVersion": SEMANTIC_PROFILE_SCHEMA_VERSION,
        "layout": layout,
        "source": "heuristic",
        "sampleRecordCount": len(sample_records),
        "fields": field_profiles,
        "concepts": concepts,
        "notes": [],
    }


def parse_layout_semantic_profile(
    content: str,
    *,
    layout: str,
    fields: list[dict[str, Any]],
    sample_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None

    field_names = {str(field.get("name") or "") for field in fields if isinstance(field, dict)}
    field_metadata = {
        str(field.get("name") or ""): field
        for field in fields
        if isinstance(field, dict) and field.get("name")
    }
    sample_records = sample_records or []
    raw_field_profiles = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    field_profiles: dict[str, dict[str, Any]] = {}
    for field_name in field_names:
        raw = raw_field_profiles.get(field_name)
        if not isinstance(raw, dict):
            raw = {}
        field_profiles[field_name] = _field_profile(
            field=field_name,
            metadata=field_metadata.get(field_name, {}),
            semantic_label=str(raw.get("semanticLabel") or _heuristic_field_label(field_name)),
            description=str(raw.get("description") or _heuristic_field_description(field_name)),
            sample_values=_sample_values_for_field(sample_records, field_name),
            confidence=_bounded_float(raw.get("confidence")) or 0.5,
            source="llm",
            business_concepts=raw.get("businessConcepts"),
            likely_contains=raw.get("likelyContains"),
        )

    raw_concepts = data.get("concepts") if isinstance(data.get("concepts"), dict) else {}
    concepts: dict[str, dict[str, Any]] = {}
    for concept in SEMANTIC_CONCEPTS:
        raw = raw_concepts.get(concept)
        if not isinstance(raw, dict):
            continue
        field_name = str(raw.get("field") or "").strip()
        if field_name and field_name not in field_names:
            field_name = ""
        concepts[concept] = _concept(
            field=field_name,
            label=str(raw.get("label") or _concept_label(concept)),
            confidence=_bounded_float(raw.get("confidence")),
            reason=str(raw.get("reason") or ""),
        )

    notes = data.get("notes")
    if not isinstance(notes, list):
        notes = []
    return {
        "schemaVersion": SEMANTIC_PROFILE_SCHEMA_VERSION,
        "layout": layout,
        "source": "llm",
        "sampleRecordCount": len(sample_records),
        "fields": field_profiles,
        "concepts": concepts,
        "notes": [str(item) for item in notes if item],
    }


def semantic_concept_field(profile: dict[str, Any] | None, concept: str) -> str:
    if not isinstance(profile, dict):
        return ""
    concepts = profile.get("concepts")
    if not isinstance(concepts, dict):
        return ""
    item = concepts.get(concept)
    if not isinstance(item, dict):
        return ""
    return str(item.get("field") or "")


def semantic_concept_reason(profile: dict[str, Any] | None, concept: str) -> str:
    if not isinstance(profile, dict):
        return ""
    concepts = profile.get("concepts")
    if not isinstance(concepts, dict):
        return ""
    item = concepts.get(concept)
    if not isinstance(item, dict):
        return ""
    return str(item.get("reason") or "")


def semantic_priority_fields(profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(profile, dict):
        return []
    concepts = profile.get("concepts")
    if not isinstance(concepts, dict):
        return []
    fields: list[str] = []
    seen: set[str] = set()
    for item in concepts.values():
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "")
        if field and field not in seen:
            seen.add(field)
            fields.append(field)
    return fields


def _should_use_llm(layout: str, settings: Settings) -> bool:
    enabled_layouts = {item.strip() for item in settings.rag_index_semantic_profile_layouts.split(",") if item.strip()}
    return (
        settings.rag_index_semantic_profile_enabled
        and settings.natural_query_llm_enabled
        and settings.llm_provider.lower() == "deepseek"
        and bool(settings.llm_api_key)
        and layout in enabled_layouts
    )


def _system_prompt() -> str:
    return (
        "你是 FileMaker layout metadata 语义分析器，只输出 JSON。\n"
        "任务：根据字段 metadata、字段类型和 sampleRecords，把每个字段做语义说明，并把字段映射到业务概念。"
        "必须只使用输入里真实存在的字段名；"
        "如果没有匹配字段，field 必须是空字符串，并在 reason 里说明缺失。\n"
        "不要猜测 FileMaker 隐藏字段，不要创造字段名。\n"
        "fields 必须覆盖输入里的每一个字段名。每个字段给出 semanticLabel、businessConcepts、"
        "description、likelyContains、confidence。\n"
        "概念定义：createdBy=创建人/创建者/录入人/建档人/操作员；"
        "createdDate=创建日期；createdTimestamp=创建时间戳或具体创建时间；"
        "updatedBy=更新人/修改人；updatedTimestamp=更新时间戳或具体更新时间；"
        "stock=库存/当前库存；price=价格/单价/售价/成本价；customer=客户/专属客户。\n"
        "输出 JSON schema："
        "{\"fields\":{\"fieldName\":{\"semanticLabel\":\"中文语义名\","
        "\"businessConcepts\":[\"string\"],\"description\":\"string\","
        "\"likelyContains\":\"string\",\"confidence\":0.0}},"
        "\"concepts\":{\"createdBy\":{\"field\":\"\",\"label\":\"创建人\","
        "\"confidence\":0.0,\"reason\":\"metadata 中没有创建人字段\"}},"
        "\"notes\":[\"string\"]}。"
    )


def _compact_fields(fields: list[dict[str, Any]]) -> list[dict[str, str]]:
    compacted: list[dict[str, str]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        if not name:
            continue
        compacted.append(
            {
                "name": name,
                "result": str(field.get("result") or ""),
                "type": str(field.get("type") or field.get("fieldType") or ""),
                "displayType": str(field.get("displayType") or ""),
            }
        )
    return compacted


def _compact_sample_records(sample_records: list[dict[str, Any]]) -> list[dict[str, str]]:
    compacted: list[dict[str, str]] = []
    for record in sample_records[:200]:
        if not isinstance(record, dict):
            continue
        item: dict[str, str] = {}
        for key, value in record.items():
            if value in (None, "", []):
                continue
            text = _compact_value(value, max_length=80)
            if text:
                item[str(key)] = text
        if item:
            compacted.append(item)
    return compacted


def _merge_with_fallback(profile: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    concepts = dict(fallback.get("concepts") or {})
    concepts.update(profile.get("concepts") or {})
    fields = dict(fallback.get("fields") or {})
    fields.update(profile.get("fields") or {})
    return {
        **fallback,
        **profile,
        "schemaVersion": SEMANTIC_PROFILE_SCHEMA_VERSION,
        "fields": fields,
        "concepts": concepts,
    }


def _concept(*, field: str, label: str, confidence: float, reason: str) -> dict[str, Any]:
    return {
        "field": field,
        "available": bool(field),
        "label": label,
        "confidence": confidence,
        "reason": reason,
    }


def _field_profile(
    *,
    field: str,
    metadata: dict[str, Any],
    semantic_label: str,
    description: str,
    sample_values: list[str],
    confidence: float,
    source: str,
    business_concepts: Any = None,
    likely_contains: Any = None,
) -> dict[str, Any]:
    concepts = (
        [str(item) for item in business_concepts if item]
        if isinstance(business_concepts, list)
        else []
    )
    likely_text = str(likely_contains or "")
    if not likely_text:
        result = str(metadata.get("result") or "")
        likely_text = f"{result} 值" if result else "业务字段值"
    return {
        "field": field,
        "semanticLabel": semantic_label,
        "businessConcepts": concepts,
        "description": description,
        "likelyContains": likely_text,
        "sampleValues": sample_values,
        "result": str(metadata.get("result") or ""),
        "type": str(metadata.get("type") or metadata.get("fieldType") or ""),
        "displayType": str(metadata.get("displayType") or ""),
        "confidence": confidence,
        "source": source,
    }


def _sample_values_for_field(sample_records: list[dict[str, Any]], field: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for record in sample_records:
        if not isinstance(record, dict):
            continue
        if field not in record:
            continue
        value = record.get(field)
        if value in (None, "", []):
            continue
        text = _compact_value(value, max_length=80)
        if text and text not in seen:
            seen.add(text)
            values.append(text)
        if len(values) >= 5:
            break
    return values


def _compact_value(value: Any, *, max_length: int) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def _bounded_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0.0, min(1.0, number))


def _heuristic_field_for_concept(concept: str, names: list[str]) -> str:
    patterns = {
        "partNumber": ("part_number", "零件編號", "零件编号", "part no", "part_no"),
        "partName": ("part_name_en", "part_name", "零件名稱", "零件名称", "english name"),
        "createdDate": ("date created", "创建日期", "創建日期", "建立日期", "建檔日期", "新增日期"),
        "createdTimestamp": ("created timestamp", "creationtimestamp", "created_at", "创建时间戳", "創建時間戳", "创建时间", "創建時間"),
        "createdBy": ("created by", "createdby", "creator", "created_by", "创建人", "創建人", "创建者", "創建者", "录入人", "錄入人", "建档人", "建檔人", "操作员", "操作員"),
        "updatedDate": ("updated date", "modified date", "修改日期", "更新日期"),
        "updatedTimestamp": ("updated timestamp", "modified at", "updated_at", "修改时间", "修改時間", "更新时间", "更新時間"),
        "updatedBy": ("updated by", "modified by", "修改人", "更新人", "异动人", "異動人"),
        "stock": ("stock_on_hand_qty", "current_stock", "stock", "库存", "庫存"),
        "price": ("price", "unit price", "unit_price", "selling price", "sale price", "cost", "价格", "價格", "单价", "單價", "售价", "售價", "成本价", "成本價"),
        "status": ("status", "状态", "狀態"),
        "customer": ("專屬客戶", "专属客户", "customer", "client", "客戶", "客户"),
    }
    terms = patterns.get(concept, ())
    for name in names:
        normalized = _normalize(name)
        if any(term in normalized for term in terms):
            return name
    return ""


def _concept_label(concept: str) -> str:
    labels = {
        "partNumber": "零件编号",
        "partName": "零件名称",
        "createdDate": "创建日期",
        "createdTimestamp": "创建时间戳",
        "createdBy": "创建人",
        "updatedDate": "更新日期",
        "updatedTimestamp": "更新时间戳",
        "updatedBy": "更新人",
        "stock": "库存",
        "price": "价格",
        "status": "状态",
        "customer": "客户",
    }
    return labels.get(concept, concept)


def _heuristic_field_label(field: str) -> str:
    for concept in SEMANTIC_CONCEPTS:
        if _heuristic_field_for_concept(concept, [field]):
            return _concept_label(concept)
    cleaned = re.sub(r"[_|]+", " ", field).strip()
    return cleaned or field


def _heuristic_field_description(field: str) -> str:
    label = _heuristic_field_label(field)
    if label != field:
        return f"字段名显示该字段可能表示{label}。"
    return "根据字段名和样本值推断的业务字段。"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


PRICE_PERMISSION = "canViewPrice"
FINANCIAL_SENSITIVITIES = {
    "price",
    "cost",
    "amount",
    "fee",
    "value",
    "rate",
    "financial",
}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


@dataclass(frozen=True)
class RagForeignKey:
    field: str
    references_entity: str
    references_fields: tuple[str, ...]
    relationship: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "referencesEntity": self.references_entity,
            "referencesFields": list(self.references_fields),
            "relationship": self.relationship,
        }


@dataclass(frozen=True)
class RagFieldSemantic:
    source_field: str
    canonical_field: str
    business_concept: str
    sensitivity: str
    permission: str
    layouts: tuple[str, ...] = ()
    currency: str = ""
    description: str = ""

    @property
    def is_price_restricted(self) -> bool:
        return (
            self.permission == PRICE_PERMISSION
            or self.sensitivity.casefold() in FINANCIAL_SENSITIVITIES
        )

    def applies_to_layout(self, layout: str) -> bool:
        return not self.layouts or "*" in self.layouts or layout in self.layouts

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sourceField": self.source_field,
            "canonicalField": self.canonical_field,
            "businessConcept": self.business_concept,
            "sensitivity": self.sensitivity,
            "permission": self.permission,
            "layouts": list(self.layouts),
        }
        if self.currency:
            result["currency"] = self.currency
        if self.description:
            result["description"] = self.description
        return result


@dataclass(frozen=True)
class RagEntity:
    name: str
    label: str
    layouts: tuple[str, ...]
    primary_keys: tuple[str, ...]
    alternate_keys: tuple[str, ...] = ()
    title_fields: tuple[str, ...] = ()
    search_fields: tuple[str, ...] = ()
    filter_fields: tuple[str, ...] = ()
    display_fields: tuple[str, ...] = ()
    exclude_fields: tuple[str, ...] = ()
    foreign_keys: tuple[RagForeignKey, ...] = ()
    date_fields: dict[str, str] = field(default_factory=dict)
    cache_fields: tuple[str, ...] = ()
    max_records: int | None = None

    @property
    def index_fields(self) -> list[str]:
        return _unique(
            [
                *self.primary_keys,
                *self.alternate_keys,
                *(foreign_key.field for foreign_key in self.foreign_keys),
                *self.title_fields,
                *self.search_fields,
                *self.filter_fields,
                *self.display_fields,
                *self.date_fields.values(),
            ]
        )

    @property
    def record_cache_fields(self) -> list[str]:
        return _unique(self.cache_fields or tuple(self.index_fields))

    def to_context(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "layouts": list(self.layouts),
            "primaryKeys": list(self.primary_keys),
            "alternateKeys": list(self.alternate_keys),
            "foreignKeys": [item.to_dict() for item in self.foreign_keys],
            "titleFields": list(self.title_fields),
            "searchFields": list(self.search_fields),
            "filterFields": list(self.filter_fields),
            "displayFields": list(self.display_fields),
            "indexFields": self.index_fields,
            "cacheFields": self.record_cache_fields,
        }


@dataclass(frozen=True)
class RagRelationship:
    name: str
    label: str
    from_entity: str
    to_entity: str
    cardinality: str
    joins: tuple[dict[str, str], ...]
    through_entity: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "fromEntity": self.from_entity,
            "toEntity": self.to_entity,
            "cardinality": self.cardinality,
            "joins": [dict(item) for item in self.joins],
        }
        if self.through_entity:
            result["throughEntity"] = self.through_entity
        if self.description:
            result["description"] = self.description
        return result


class RagSemanticRegistry:
    def __init__(
        self,
        *,
        entities: list[RagEntity] | None = None,
        relationships: list[RagRelationship] | None = None,
        mapping_path: str = "",
        mapping_version: str = "",
        warnings: list[str] | None = None,
        field_semantics: list[RagFieldSemantic] | None = None,
    ):
        self.entities = entities or []
        self.relationships = relationships or []
        self.field_semantics = field_semantics or []
        self.mapping_path = mapping_path
        self.mapping_version = mapping_version
        self.warnings = warnings or []
        self._entities_by_name = {item.name: item for item in self.entities}
        self._entities_by_layout = {
            layout: item
            for item in self.entities
            for layout in item.layouts
        }
        self._field_semantics_by_source: dict[str, list[RagFieldSemantic]] = {}
        for item in self.field_semantics:
            for source_key in _field_lookup_keys(item.source_field):
                self._field_semantics_by_source.setdefault(source_key, []).append(item)

    @classmethod
    def from_mapping_path(cls, mapping_path: str) -> "RagSemanticRegistry":
        path = Path(mapping_path).expanduser()
        if not path.exists():
            return cls(mapping_path=str(path), warnings=[f"mapping 文件不存在：{path}"])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return cls(mapping_path=str(path), warnings=[f"mapping 文件读取失败：{exc}"])
        if not isinstance(payload, dict):
            return cls(mapping_path=str(path), warnings=["mapping 文件根节点不是对象。"])

        warnings: list[str] = []
        entities: list[RagEntity] = []
        for index, raw in enumerate(payload.get("entities") or []):
            entity = _entity_from_mapping(raw)
            if entity:
                entities.append(entity)
            else:
                warnings.append(f"entities[{index}] 缺少 name 或 ragLayouts，已忽略。")

        relationships: list[RagRelationship] = []
        for index, raw in enumerate(payload.get("ragRelationships") or []):
            relationship = _relationship_from_mapping(raw)
            if relationship:
                relationships.append(relationship)
            else:
                warnings.append(f"ragRelationships[{index}] 缺少必要字段，已忽略。")

        field_semantics: list[RagFieldSemantic] = []
        for index, raw in enumerate(payload.get("fieldSemantics") or []):
            field_semantic = _field_semantic_from_mapping(raw)
            if field_semantic:
                field_semantics.append(field_semantic)
            else:
                warnings.append(
                    f"fieldSemantics[{index}] 缺少 sourceField、canonicalField 或 sensitivity，已忽略。"
                )

        return cls(
            entities=entities,
            relationships=relationships,
            field_semantics=field_semantics,
            mapping_path=str(path),
            mapping_version=str(payload.get("version") or ""),
            warnings=warnings,
        )

    def entity_for_layout(self, layout: str) -> RagEntity | None:
        return self._entities_by_layout.get(layout)

    def entity(self, name: str) -> RagEntity | None:
        return self._entities_by_name.get(name)

    def relationships_for_entity(self, entity_name: str) -> list[RagRelationship]:
        return [
            item
            for item in self.relationships
            if entity_name in {item.from_entity, item.to_entity, item.through_entity}
        ]

    def field_semantic(
        self,
        field_name: str,
        *,
        layout: str = "",
    ) -> RagFieldSemantic | None:
        matches: list[RagFieldSemantic] = []
        seen: set[RagFieldSemantic] = set()
        for source_key in _field_lookup_keys(field_name):
            for item in self._field_semantics_by_source.get(source_key, []):
                if item in seen or (layout and not item.applies_to_layout(layout)):
                    continue
                seen.add(item)
                matches.append(item)
        if not matches:
            return None
        if layout:
            exact_layout = [
                item
                for item in matches
                if layout in item.layouts
            ]
            if exact_layout:
                matches = exact_layout
        return next(
            (item for item in matches if item.is_price_restricted),
            matches[0],
        )

    def price_restriction_for_field(
        self,
        field_name: str,
        *,
        layout: str = "",
    ) -> bool | None:
        item = self.field_semantic(field_name, layout=layout)
        return item.is_price_restricted if item else None

    def field_semantics_for_layout(self, layout: str) -> list[RagFieldSemantic]:
        return [
            item
            for item in self.field_semantics
            if item.applies_to_layout(layout)
        ]

    def context_for_layout(self, layout: str) -> dict[str, Any]:
        entity = self.entity_for_layout(layout)
        field_semantics = [
            item.to_dict()
            for item in self.field_semantics_for_layout(layout)
        ]
        if not entity and not field_semantics:
            return {}
        context: dict[str, Any] = {
            "mappingVersion": self.mapping_version,
            "fieldSemantics": field_semantics,
        }
        if entity:
            context["entity"] = entity.to_context()
            context["relationships"] = [
                item.to_dict()
                for item in self.relationships_for_entity(entity.name)
            ]
        return context


def _entity_from_mapping(raw: Any) -> RagEntity | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    layouts = _string_list(raw.get("ragLayouts"))
    if not name or not layouts:
        return None

    primary_keys = _string_list(raw.get("primaryKeys")) or _string_list(raw.get("primaryKey"))
    date_fields = raw.get("dateFields") if isinstance(raw.get("dateFields"), dict) else {}
    foreign_keys: list[RagForeignKey] = []
    for item in raw.get("foreignKeys") or []:
        if not isinstance(item, dict):
            continue
        field_name = str(item.get("field") or "").strip()
        references_entity = str(item.get("referencesEntity") or "").strip()
        references_fields = _string_list(item.get("referencesFields"))
        if not references_fields:
            references_fields = _string_list(item.get("referencesField"))
        if field_name and references_entity and references_fields:
            foreign_keys.append(
                RagForeignKey(
                    field=field_name,
                    references_entity=references_entity,
                    references_fields=tuple(references_fields),
                    relationship=str(item.get("relationship") or ""),
                )
            )

    max_records: int | None = None
    if raw.get("ragMaxRecords") is not None:
        try:
            max_records = max(0, int(raw["ragMaxRecords"]))
        except (TypeError, ValueError):
            max_records = None

    return RagEntity(
        name=name,
        label=str(raw.get("label") or name),
        layouts=tuple(layouts),
        primary_keys=tuple(primary_keys),
        alternate_keys=tuple(_string_list(raw.get("alternateKeys"))),
        title_fields=tuple(_string_list(raw.get("titleFields"))),
        search_fields=tuple(_string_list(raw.get("searchFields"))),
        filter_fields=tuple(_string_list(raw.get("filterFields"))),
        display_fields=tuple(_string_list(raw.get("displayFields"))),
        exclude_fields=tuple(_string_list(raw.get("excludeFields"))),
        foreign_keys=tuple(foreign_keys),
        date_fields={str(key): str(value) for key, value in date_fields.items() if value},
        cache_fields=tuple(_string_list(raw.get("cacheFields"))),
        max_records=max_records,
    )


def _field_semantic_from_mapping(raw: Any) -> RagFieldSemantic | None:
    if not isinstance(raw, dict):
        return None
    source_field = str(raw.get("sourceField") or "").strip()
    canonical_field = str(raw.get("canonicalField") or "").strip()
    sensitivity = str(raw.get("sensitivity") or "").strip()
    if not source_field or not canonical_field or not sensitivity:
        return None
    return RagFieldSemantic(
        source_field=source_field,
        canonical_field=canonical_field,
        business_concept=str(raw.get("businessConcept") or "").strip(),
        sensitivity=sensitivity,
        permission=str(raw.get("permission") or "").strip(),
        layouts=tuple(_string_list(raw.get("layouts"))),
        currency=str(raw.get("currency") or "").strip().upper(),
        description=str(raw.get("description") or "").strip(),
    )


def _field_lookup_keys(value: str) -> tuple[str, ...]:
    normalized = _normalize_field_name(value)
    _, separator, leaf = normalized.rpartition("::")
    if separator and leaf:
        return (normalized, leaf)
    return (normalized,) if normalized else ()


def _normalize_field_name(value: str) -> str:
    return "".join(
        character
        for character in str(value or "").strip().casefold()
        if character.isalnum() or character == ":"
    )


def _relationship_from_mapping(raw: Any) -> RagRelationship | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    from_entity = str(raw.get("fromEntity") or "").strip()
    to_entity = str(raw.get("toEntity") or "").strip()
    joins: list[dict[str, str]] = []
    for item in raw.get("joins") or []:
        if not isinstance(item, dict):
            continue
        join = {str(key): str(value) for key, value in item.items() if value not in (None, "")}
        if join:
            joins.append(join)
    if not name or not from_entity or not to_entity or not joins:
        return None
    return RagRelationship(
        name=name,
        label=str(raw.get("label") or name),
        from_entity=from_entity,
        to_entity=to_entity,
        cardinality=str(raw.get("cardinality") or ""),
        joins=tuple(joins),
        through_entity=str(raw.get("throughEntity") or ""),
        description=str(raw.get("description") or ""),
    )

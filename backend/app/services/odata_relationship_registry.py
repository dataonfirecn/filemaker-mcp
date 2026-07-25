from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.filemaker_odata_client import FileMakerODataClient


@dataclass(frozen=True)
class ODataRelationship:
    name: str
    label: str
    description: str
    from_table: str
    from_field: str
    link_table: str
    link_from_field: str
    link_to_field: str
    target_table: str
    target_lookup_fields: list[str] = field(default_factory=list)
    source_select_fields: list[str] = field(default_factory=list)
    target_select_fields: list[str] = field(default_factory=list)
    source: str = "builtin"
    confidence: float = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "fromTable": self.from_table,
            "fromField": self.from_field,
            "linkTable": self.link_table,
            "linkFromField": self.link_from_field,
            "linkToField": self.link_to_field,
            "targetTable": self.target_table,
            "targetLookupFields": self.target_lookup_fields,
            "source": self.source,
            "confidence": self.confidence,
        }


BUILTIN_RELATIONSHIPS = [
    ODataRelationship(
        name="part-products",
        label="零件关联产品",
        description="按零件号查询零件关联的产品编号，并尝试补充产品详情。",
        from_table="零件",
        from_field="part_number",
        link_table="零件关联产品",
        link_from_field="ID_零件",
        link_to_field="ID_产品",
        target_table="產品",
        target_lookup_fields=["product_sku", "系統產品編號"],
        source_select_fields=["part_number", "stock_on_hand_qty"],
        target_select_fields=["product_sku", "系統產品編號", "產品名稱_中文"],
        confidence=0.95,
    ),
    ODataRelationship(
        name="part-parts",
        label="零件关联零件",
        description="按零件号查询零件关联的其他零件编号。",
        from_table="零件",
        from_field="part_number",
        link_table="零件关联零件",
        link_from_field="ID_零件",
        link_to_field="ID_關聯零件",
        target_table="零件",
        target_lookup_fields=["part_number"],
        source_select_fields=["part_number", "stock_on_hand_qty"],
        target_select_fields=["part_number", "stock_on_hand_qty"],
        confidence=0.9,
    ),
]


class ODataRelationshipRegistry:
    def __init__(
        self,
        relationships: list[ODataRelationship] | None = None,
        *,
        mapping_path: str = "",
        mapping_source: str = "builtin",
        mapping_version: str = "builtin",
        entities: list[dict[str, Any]] | None = None,
        query_strategies: list[dict[str, Any]] | None = None,
        warnings: list[str] | None = None,
    ):
        self._relationships = {
            item.name: item
            for item in (relationships if relationships is not None else BUILTIN_RELATIONSHIPS)
        }
        self.mapping_path = mapping_path
        self.mapping_source = mapping_source
        self.mapping_version = mapping_version
        self.entities = entities or []
        self.query_strategies = query_strategies or []
        self.warnings = warnings or []

    @classmethod
    def from_mapping_path(cls, mapping_path: str) -> "ODataRelationshipRegistry":
        path = Path(mapping_path).expanduser()
        if not path.exists():
            return cls(
                mapping_path=str(path),
                mapping_source="builtin",
                mapping_version="builtin",
                warnings=[f"mapping 文件不存在，已使用内置关系：{path}"],
            )

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return cls(
                mapping_path=str(path),
                mapping_source="builtin",
                mapping_version="builtin",
                warnings=[f"mapping 文件读取失败，已使用内置关系：{exc}"],
            )

        if not isinstance(payload, dict):
            return cls(
                mapping_path=str(path),
                mapping_source="builtin",
                mapping_version="builtin",
                warnings=["mapping 文件根节点不是对象，已使用内置关系。"],
            )

        warnings: list[str] = []
        relationships: list[ODataRelationship] = []
        raw_relationships = payload.get("relationships")
        if isinstance(raw_relationships, list):
            for index, item in enumerate(raw_relationships):
                if not isinstance(item, dict):
                    warnings.append(f"relationships[{index}] 不是对象，已忽略。")
                    continue
                relationship = _relationship_from_mapping(item)
                if relationship:
                    relationships.append(relationship)
                else:
                    warnings.append(f"relationships[{index}] 缺少必要字段，已忽略。")

        if not relationships:
            relationships = BUILTIN_RELATIONSHIPS
            warnings.append("mapping 文件没有有效 relationships，已使用内置关系。")

        entities = payload.get("entities")
        query_strategies = payload.get("queryStrategies")
        return cls(
            relationships=relationships,
            mapping_path=str(path),
            mapping_source="file",
            mapping_version=str(payload.get("version") or ""),
            entities=entities if isinstance(entities, list) else [],
            query_strategies=query_strategies if isinstance(query_strategies, list) else [],
            warnings=warnings,
        )

    def list(self) -> list[ODataRelationship]:
        return list(self._relationships.values())

    def get(self, name: str) -> ODataRelationship | None:
        return self._relationships.get(name)

    def metadata(self) -> dict[str, Any]:
        return {
            "mappingPath": self.mapping_path,
            "mappingSource": self.mapping_source,
            "mappingVersion": self.mapping_version,
            "entityCount": len(self.entities),
            "queryStrategyCount": len(self.query_strategies),
            "warnings": self.warnings,
        }


class ODataRelationshipExecutor:
    def __init__(self, client: FileMakerODataClient, registry: ODataRelationshipRegistry | None = None):
        self.client = client
        self.registry = registry or ODataRelationshipRegistry()

    async def query(
        self,
        relationship: ODataRelationship,
        *,
        value: str,
        top: int = 10,
        include_target_rows: bool = True,
    ) -> dict[str, Any]:
        effective_top = max(1, min(top, self.client.settings.filemaker_odata_max_top))
        source_rows = await self._source_rows(relationship, value)
        link_result = await self.client.records(
            relationship.link_table,
            filter_expr=_eq_filter(relationship.link_from_field, value),
            top=effective_top,
            count=False,
        )
        link_rows = _rows(link_result)
        target_ids = _unique_non_empty(str(row.get(relationship.link_to_field) or "") for row in link_rows)
        target_rows: list[dict[str, Any]] = []
        target_errors: list[str] = []
        if include_target_rows and relationship.target_lookup_fields:
            for target_id in target_ids[:effective_top]:
                try:
                    result = await self.client.records(
                        relationship.target_table,
                        select=relationship.target_select_fields or None,
                        filter_expr=_or_eq_filter(relationship.target_lookup_fields, target_id),
                        top=1,
                        count=False,
                    )
                except Exception as exc:
                    target_errors.append(str(exc))
                    continue
                target_rows.extend(_rows(result))

        warnings: list[str] = []
        if target_ids and include_target_rows and not target_rows:
            warnings.append(
                "已找到关联编号，但目标表没有匹配到详情记录；结果先返回关联表中的目标编号。"
            )
        warnings.extend(_unique_non_empty(target_errors))

        return {
            "relationship": relationship.to_dict(),
            "value": value,
            "sourceRows": source_rows,
            "linkRows": link_rows[:effective_top],
            "targetIds": target_ids[:effective_top],
            "targetRows": target_rows[:effective_top],
            "foundCount": len(link_rows),
            "returnedCount": min(len(link_rows), effective_top),
            "warnings": warnings,
        }

    async def _source_rows(self, relationship: ODataRelationship, value: str) -> list[dict[str, Any]]:
        if not relationship.source_select_fields:
            return []
        try:
            result = await self.client.records(
                relationship.from_table,
                select=relationship.source_select_fields,
                filter_expr=_eq_filter(relationship.from_field, value),
                top=1,
                count=False,
            )
        except Exception:
            return []
        return _rows(result)


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = result.get("rows") if isinstance(result, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _eq_filter(field: str, value: str) -> str:
    return f"{field} eq {_odata_string(value)}"


def _or_eq_filter(fields: list[str], value: str) -> str:
    return " or ".join(_eq_filter(field, value) for field in fields)


def _odata_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _unique_non_empty(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _relationship_from_mapping(item: dict[str, Any]) -> ODataRelationship | None:
    from_node = item.get("from") if isinstance(item.get("from"), dict) else {}
    through_node = item.get("through") if isinstance(item.get("through"), dict) else {}
    to_node = item.get("to") if isinstance(item.get("to"), dict) else {}
    name = str(item.get("name") or "").strip()
    from_table = str(from_node.get("table") or "").strip()
    from_field = str(from_node.get("field") or "").strip()
    link_table = str(through_node.get("table") or "").strip()
    link_from_field = str(through_node.get("fromField") or "").strip()
    link_to_field = str(through_node.get("toField") or "").strip()
    target_table = str(to_node.get("table") or "").strip()
    if not all([name, from_table, from_field, link_table, link_from_field, link_to_field, target_table]):
        return None

    return ODataRelationship(
        name=name,
        label=str(item.get("label") or name),
        description=str(item.get("description") or ""),
        from_table=from_table,
        from_field=from_field,
        link_table=link_table,
        link_from_field=link_from_field,
        link_to_field=link_to_field,
        target_table=target_table,
        target_lookup_fields=_string_list(to_node.get("lookupFields")),
        source_select_fields=_string_list(item.get("sourceSelectFields")),
        target_select_fields=_string_list(item.get("targetSelectFields")),
        source=str(item.get("source") or "mapping"),
        confidence=_float_value(item.get("confidence")),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings


class FileMakerODataError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


@dataclass(frozen=True)
class ODataField:
    name: str
    type: str = ""
    nullable: bool = True


@dataclass(frozen=True)
class ODataNavigation:
    name: str
    type: str = ""
    collection: bool = False
    target_entity: str = ""
    target_set: str = ""


@dataclass
class ODataEntity:
    name: str
    entity_set: str = ""
    keys: list[str] = field(default_factory=list)
    fields: list[ODataField] = field(default_factory=list)
    navigation: list[ODataNavigation] = field(default_factory=list)


@dataclass
class ODataSchema:
    entities: list[ODataEntity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "entities": [
                {
                    "name": entity.name,
                    "entitySet": entity.entity_set,
                    "keys": entity.keys,
                    "fields": [
                        {
                            "name": item.name,
                            "type": item.type,
                            "nullable": item.nullable,
                        }
                        for item in entity.fields
                    ],
                    "navigation": [
                        {
                            "name": item.name,
                            "type": item.type,
                            "collection": item.collection,
                            "targetEntity": item.target_entity,
                            "targetSet": item.target_set,
                        }
                        for item in entity.navigation
                    ],
                }
                for entity in self.entities
            ]
        }

    def entity_for_set(self, table: str) -> ODataEntity | None:
        normalized = _normalize_name(table)
        for entity in self.entities:
            if _normalize_name(entity.entity_set) == normalized or _normalize_name(entity.name) == normalized:
                return entity
        return None

    def navigation_for(self, table: str, related: str) -> ODataNavigation | None:
        entity = self.entity_for_set(table)
        if not entity:
            return None
        normalized = _normalize_name(related)
        for item in entity.navigation:
            if _normalize_name(item.name) == normalized or _normalize_name(item.target_set) == normalized:
                return item
        return None


class FileMakerODataClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.AsyncClient(
            timeout=settings.filemaker_timeout_seconds,
            verify=settings.filemaker_ssl_verify,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.filemaker_odata_enabled,
            "configured": self.settings.filemaker_odata_configured,
            "version": self.settings.filemaker_odata_version,
            "authMode": self.settings.filemaker_odata_auth_mode,
            "maxTop": self.settings.filemaker_odata_max_top,
            "baseUrl": self._base_url(redact_database=False) if self.settings.filemaker_host else "",
        }

    async def metadata_xml(self) -> str:
        response = await self.request(
            "/$metadata",
            accept="application/xml",
            parse_json=False,
        )
        return str(response)

    async def metadata_schema(self) -> ODataSchema:
        return parse_odata_metadata(await self.metadata_xml())

    async def service_document(self) -> dict[str, Any]:
        payload = await self.request("/")
        return payload if isinstance(payload, dict) else {}

    async def tables(self) -> list[dict[str, str]]:
        payload = await self.service_document()
        items = payload.get("value") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return []
        tables: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not name:
                continue
            tables.append(
                {
                    "name": name,
                    "kind": str(item.get("kind") or ""),
                    "url": str(item.get("url") or ""),
                }
            )
        return tables

    async def records(
        self,
        table: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        expand: list[str] | None = None,
        orderby: str | None = None,
        top: int = 10,
        skip: int = 0,
        count: bool = True,
    ) -> dict[str, Any]:
        params = self._query_params(
            select=select,
            filter_expr=filter_expr,
            expand=expand,
            orderby=orderby,
            top=top,
            skip=skip,
            count=count,
        )
        payload = await self.request(f"/{self._encode_segment(table)}", params=params)
        return _normalize_record_response(table=table, payload=payload)

    async def related_records(
        self,
        table: str,
        key: str,
        related: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        top: int = 10,
        skip: int = 0,
        count: bool = True,
    ) -> dict[str, Any]:
        params = self._query_params(
            select=select,
            filter_expr=filter_expr,
            orderby=orderby,
            top=top,
            skip=skip,
            count=count,
        )
        endpoint = (
            f"/{self._encode_segment(table)}"
            f"({odata_key_literal(key)})"
            f"/{self._encode_segment(related)}"
        )
        payload = await self.request(endpoint, params=params)
        return _normalize_record_response(table=related, payload=payload)

    async def cascade_related_records(
        self,
        table: str,
        key: str,
        path: list[str],
        *,
        top: int = 10,
        count: bool = True,
    ) -> dict[str, Any]:
        schema = await self.metadata_schema()
        current_items = [{"table": table, "key": key, "row": None}]
        levels: list[dict[str, Any]] = []

        for related in path:
            next_items: list[dict[str, Any]] = []
            level_rows: list[dict[str, Any]] = []
            for item in current_items[: self._effective_top(top)]:
                parent_table = str(item["table"])
                navigation = schema.navigation_for(parent_table, related)
                target_table = navigation.target_set if navigation and navigation.target_set else related
                target_entity = schema.entity_for_set(target_table)
                result = await self.related_records(
                    parent_table,
                    str(item["key"]),
                    related,
                    select=_entity_select_fields(target_entity),
                    top=top,
                    count=count,
                )
                rows = result.get("rows") if isinstance(result.get("rows"), list) else []
                level_rows.extend(rows)
                for row in rows[: self._effective_top(top)]:
                    row_key = row_key_value(row, target_entity.keys if target_entity else [])
                    if row_key is not None:
                        next_items.append({"table": target_table, "key": str(row_key), "row": row})
            levels.append(
                {
                    "relation": related,
                    "rows": level_rows[: self._effective_top(top)],
                    "returnedCount": min(len(level_rows), self._effective_top(top)),
                    "foundCount": len(level_rows),
                }
            )
            current_items = next_items
            if not current_items:
                break

        return {
            "table": table,
            "key": key,
            "path": path,
            "levels": levels,
        }

    async def request(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        accept: str = "application/json",
        parse_json: bool = True,
    ) -> Any:
        self._ensure_available()
        url = f"{self._base_url()}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
        query_string = _odata_query_string(params)
        if query_string:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{query_string}"
        try:
            response = await self._client.request(
                method,
                url,
                headers={
                    "Accept": accept,
                    "Content-Type": "application/json",
                    "Authorization": self._authorization_header(),
                },
                json=json_body,
            )
        except httpx.RequestError as exc:
            raise FileMakerODataError("Unable to connect to FileMaker OData", payload=str(exc)) from exc

        if not response.is_success:
            raise FileMakerODataError(
                "FileMaker OData request failed",
                response.status_code,
                _safe_response_payload(response),
            )
        if not response.content:
            return {} if parse_json else ""
        if not parse_json:
            return response.text
        return response.json()

    def _query_params(
        self,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        expand: list[str] | None = None,
        orderby: str | None = None,
        top: int = 10,
        skip: int = 0,
        count: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "$top": self._effective_top(top),
            "$skip": max(0, skip),
        }
        if count:
            params["$count"] = "true"
        if select:
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if expand:
            params["$expand"] = ",".join(expand)
        if orderby:
            params["$orderby"] = orderby
        return params

    def _effective_top(self, top: int) -> int:
        configured = max(1, self.settings.filemaker_odata_max_top)
        return min(max(1, top), configured)

    def _ensure_available(self) -> None:
        if not self.settings.filemaker_odata_enabled:
            raise FileMakerODataError("FileMaker OData is disabled", status_code=423)
        if not self.settings.filemaker_odata_configured:
            raise FileMakerODataError("FileMaker OData is not configured", status_code=503)

    def _authorization_header(self) -> str:
        mode = self.settings.filemaker_odata_auth_mode.strip().lower()
        if mode == "fmid":
            return f"FMID {self.settings.filemaker_odata_fmid_token}"
        raw = f"{self.settings.filemaker_username}:{self.settings.filemaker_password}".encode("utf-8")
        return f"Basic {base64.b64encode(raw).decode('ascii')}"

    def _base_url(self, *, redact_database: bool = False) -> str:
        host = self.settings.filemaker_host.rstrip("/")
        version = self.settings.filemaker_odata_version.strip() or "v4"
        database = "database" if redact_database else self._encode_segment(self.settings.filemaker_database)
        return f"{host}/fmi/odata/{version}/{database}"

    def _encode_segment(self, value: str) -> str:
        return quote(value, safe="")


def parse_odata_metadata(xml_text: str) -> ODataSchema:
    root = ET.fromstring(xml_text)
    entities_by_name: dict[str, ODataEntity] = {}
    full_name_to_name: dict[str, str] = {}

    for schema_node in _iter_nodes(root, "Schema"):
        namespace = schema_node.attrib.get("Namespace", "")
        for entity_node in _child_nodes(schema_node, "EntityType"):
            name = entity_node.attrib.get("Name", "")
            if not name:
                continue
            full_name = f"{namespace}.{name}" if namespace else name
            entity = ODataEntity(
                name=name,
                keys=_parse_entity_keys(entity_node),
                fields=_parse_entity_fields(entity_node),
                navigation=_parse_entity_navigation(entity_node),
            )
            entities_by_name[name] = entity
            full_name_to_name[full_name] = name

    entity_set_bindings: dict[str, dict[str, str]] = {}
    for container in _iter_nodes(root, "EntityContainer"):
        for entity_set in _child_nodes(container, "EntitySet"):
            set_name = entity_set.attrib.get("Name", "")
            entity_type = _strip_namespace(entity_set.attrib.get("EntityType", ""))
            entity_name = full_name_to_name.get(entity_set.attrib.get("EntityType", ""), entity_type)
            if entity_name in entities_by_name:
                entities_by_name[entity_name].entity_set = set_name
            bindings: dict[str, str] = {}
            for binding in _child_nodes(entity_set, "NavigationPropertyBinding"):
                path = binding.attrib.get("Path", "")
                target = binding.attrib.get("Target", "")
                if path and target:
                    bindings[path] = target
            if set_name:
                entity_set_bindings[set_name] = bindings

    entity_set_by_entity = {
        entity.name: entity.entity_set
        for entity in entities_by_name.values()
        if entity.entity_set
    }
    for entity in entities_by_name.values():
        bindings = entity_set_bindings.get(entity.entity_set, {})
        entity.navigation = [
            ODataNavigation(
                name=item.name,
                type=item.type,
                collection=item.collection,
                target_entity=item.target_entity,
                target_set=bindings.get(item.name) or entity_set_by_entity.get(item.target_entity, ""),
            )
            for item in entity.navigation
        ]

    return ODataSchema(entities=list(entities_by_name.values()))


def odata_key_literal(value: str) -> str:
    text = str(value).strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1]
    if "," in text or "=" in text:
        return text
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def row_key_value(row: dict[str, Any], keys: list[str]) -> Any:
    for key in [*keys, "ROWID", "recordId", "id", "ID"]:
        value = row.get(key)
        if value not in (None, ""):
            return value
    odata_id = row.get("@id")
    if isinstance(odata_id, str):
        key = _key_from_odata_id(odata_id)
        if key:
            return key
    return None


def _key_from_odata_id(value: str) -> str:
    match = re.search(r"\(([^()]*)\)\s*$", value)
    return f"({match.group(1)})" if match else ""


def _entity_select_fields(entity: ODataEntity | None) -> list[str] | None:
    if not entity:
        return None
    selected: list[str] = []
    seen: set[str] = set()
    for name in [*entity.keys, "ROWID", "ROWMODID", *[field.name for field in entity.fields]]:
        if name and name not in seen:
            seen.add(name)
            selected.append(name)
        if len(selected) >= 40:
            break
    return selected or None


def _parse_entity_keys(entity_node: ET.Element) -> list[str]:
    keys: list[str] = []
    for key_node in _child_nodes(entity_node, "Key"):
        for ref_node in _child_nodes(key_node, "PropertyRef"):
            name = ref_node.attrib.get("Name", "")
            if name:
                keys.append(name)
    return keys


def _parse_entity_fields(entity_node: ET.Element) -> list[ODataField]:
    fields: list[ODataField] = []
    for property_node in _child_nodes(entity_node, "Property"):
        name = property_node.attrib.get("Name", "")
        if not name:
            continue
        fields.append(
            ODataField(
                name=name,
                type=property_node.attrib.get("Type", ""),
                nullable=property_node.attrib.get("Nullable", "true").lower() != "false",
            )
        )
    return fields


def _parse_entity_navigation(entity_node: ET.Element) -> list[ODataNavigation]:
    navigation: list[ODataNavigation] = []
    for nav_node in _child_nodes(entity_node, "NavigationProperty"):
        name = nav_node.attrib.get("Name", "")
        type_name = nav_node.attrib.get("Type", "")
        if not name:
            continue
        target = _navigation_target_entity(type_name)
        navigation.append(
            ODataNavigation(
                name=name,
                type=type_name,
                collection=type_name.startswith("Collection("),
                target_entity=target,
            )
        )
    return navigation


def _navigation_target_entity(type_name: str) -> str:
    normalized = type_name.strip()
    if normalized.startswith("Collection(") and normalized.endswith(")"):
        normalized = normalized[len("Collection(") : -1]
    return _strip_namespace(normalized)


def _strip_namespace(value: str) -> str:
    return value.rsplit(".", 1)[-1] if "." in value else value


def _iter_nodes(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if _local_name(node.tag) == name]


def _child_nodes(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in list(root) if _local_name(node.tag) == name]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _normalize_name(value: str) -> str:
    return str(value or "").strip().casefold()


def _normalize_record_response(*, table: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"table": table, "rows": [], "foundCount": 0, "returnedCount": 0, "raw": payload}
    rows = payload.get("value")
    if not isinstance(rows, list):
        rows = [payload] if payload else []
    count = payload.get("@odata.count", payload.get("@count"))
    return {
        "table": table,
        "rows": rows,
        "foundCount": int(count) if isinstance(count, (int, float)) or str(count).isdigit() else len(rows),
        "returnedCount": len(rows),
        "nextLink": payload.get("@odata.nextLink") or "",
    }


def _safe_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _odata_query_string(params: dict[str, Any] | None) -> str:
    if not params:
        return ""
    parts: list[str] = []
    for key, value in params.items():
        if value is None:
            continue
        encoded_key = quote(str(key), safe="$")
        encoded_value = quote(str(value), safe="$(),=':/")
        parts.append(f"{encoded_key}={encoded_value}")
    return "&".join(parts)

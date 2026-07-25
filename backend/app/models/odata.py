from typing import Any

from pydantic import BaseModel, Field


class ODataStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    version: str
    auth_mode: str = Field(alias="authMode")
    max_top: int = Field(alias="maxTop")
    base_url: str = Field(alias="baseUrl")

    model_config = {"populate_by_name": True}


class ODataFieldInfo(BaseModel):
    name: str
    type: str = ""
    nullable: bool = True


class ODataNavigationInfo(BaseModel):
    name: str
    type: str = ""
    collection: bool = False
    target_entity: str = Field(default="", alias="targetEntity")
    target_set: str = Field(default="", alias="targetSet")

    model_config = {"populate_by_name": True}


class ODataEntityInfo(BaseModel):
    name: str
    entity_set: str = Field(default="", alias="entitySet")
    keys: list[str] = Field(default_factory=list)
    fields: list[ODataFieldInfo] = Field(default_factory=list)
    navigation: list[ODataNavigationInfo] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ODataMetadataResponse(BaseModel):
    entities: list[ODataEntityInfo] = Field(default_factory=list)


class ODataTableInfo(BaseModel):
    name: str
    kind: str = ""
    url: str = ""


class ODataTablesResponse(BaseModel):
    tables: list[ODataTableInfo] = Field(default_factory=list)


class ODataRecordsResponse(BaseModel):
    table: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    found_count: int = Field(default=0, alias="foundCount")
    returned_count: int = Field(default=0, alias="returnedCount")
    next_link: str = Field(default="", alias="nextLink")

    model_config = {"populate_by_name": True}


class ODataCascadeRequest(BaseModel):
    table: str = Field(min_length=1, max_length=160)
    key: str = Field(min_length=1, max_length=240)
    path: list[str] = Field(min_length=1, max_length=5)
    top: int = Field(default=10, ge=1, le=100)
    count: bool = True


class ODataCascadeLevel(BaseModel):
    relation: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    found_count: int = Field(default=0, alias="foundCount")
    returned_count: int = Field(default=0, alias="returnedCount")

    model_config = {"populate_by_name": True}


class ODataCascadeResponse(BaseModel):
    table: str
    key: str
    path: list[str]
    levels: list[ODataCascadeLevel] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ODataRelationshipInfo(BaseModel):
    name: str
    label: str
    description: str = ""
    from_table: str = Field(alias="fromTable")
    from_field: str = Field(alias="fromField")
    link_table: str = Field(alias="linkTable")
    link_from_field: str = Field(alias="linkFromField")
    link_to_field: str = Field(alias="linkToField")
    target_table: str = Field(alias="targetTable")
    target_lookup_fields: list[str] = Field(default_factory=list, alias="targetLookupFields")
    source: str = "builtin"
    confidence: float = 0

    model_config = {"populate_by_name": True}


class ODataRelationshipsResponse(BaseModel):
    mapping_path: str = Field(default="", alias="mappingPath")
    mapping_source: str = Field(default="", alias="mappingSource")
    mapping_version: str = Field(default="", alias="mappingVersion")
    entity_count: int = Field(default=0, alias="entityCount")
    query_strategy_count: int = Field(default=0, alias="queryStrategyCount")
    warnings: list[str] = Field(default_factory=list)
    relationships: list[ODataRelationshipInfo] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ODataRelationshipQueryRequest(BaseModel):
    value: str = Field(min_length=1, max_length=240)
    top: int = Field(default=10, ge=1, le=100)
    include_target_rows: bool = Field(default=True, alias="includeTargetRows")

    model_config = {"populate_by_name": True}


class ODataRelationshipQueryResponse(BaseModel):
    relationship: ODataRelationshipInfo
    value: str
    source_rows: list[dict[str, Any]] = Field(default_factory=list, alias="sourceRows")
    link_rows: list[dict[str, Any]] = Field(default_factory=list, alias="linkRows")
    target_ids: list[str] = Field(default_factory=list, alias="targetIds")
    target_rows: list[dict[str, Any]] = Field(default_factory=list, alias="targetRows")
    found_count: int = Field(default=0, alias="foundCount")
    returned_count: int = Field(default=0, alias="returnedCount")
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

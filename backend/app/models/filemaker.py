from typing import Any, Literal

from pydantic import BaseModel, Field


class SortSpec(BaseModel):
    field_name: str = Field(alias="fieldName")
    sort_order: Literal["ascend", "descend"] = Field(alias="sortOrder")

    model_config = {"populate_by_name": True}


class FindRecordsRequest(BaseModel):
    query: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=1, ge=1)
    sort: list[SortSpec] | None = None


class RecordWriteRequest(BaseModel):
    field_data: dict[str, Any] = Field(alias="fieldData")

    model_config = {"populate_by_name": True}


class RunScriptRequest(BaseModel):
    script_param: str | None = Field(default=None, alias="scriptParam")

    model_config = {"populate_by_name": True}

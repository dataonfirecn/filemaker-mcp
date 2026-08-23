from typing import Any

from pydantic import BaseModel, Field


class RagIndexRun(BaseModel):
    id: int
    status: str
    reason: str = ""
    started_at: str = Field(alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    error: str | None = None
    layouts_indexed: int = Field(default=0, alias="layoutsIndexed")
    records_indexed: int = Field(default=0, alias="recordsIndexed")

    model_config = {"populate_by_name": True}


class RagIndexStatusResponse(BaseModel):
    enabled: bool
    fts_enabled: bool = Field(alias="ftsEnabled")
    database_path: str = Field(alias="databasePath")
    layout_count: int = Field(alias="layoutCount")
    record_count: int = Field(alias="recordCount")
    refresh_interval_seconds: int = Field(alias="refreshIntervalSeconds")
    latest_run: RagIndexRun | None = Field(default=None, alias="latestRun")
    running: bool = False
    profiled_layouts: int = Field(default=0, alias="profiledLayouts")
    embedding_enabled: bool = Field(default=False, alias="embeddingEnabled")
    embedding_model: str = Field(default="", alias="embeddingModel")
    embedding_count: int = Field(default=0, alias="embeddingCount")
    embedding_pending: int = Field(default=0, alias="embeddingPending")

    model_config = {"populate_by_name": True}


class RagIndexRefreshResponse(BaseModel):
    accepted: bool
    message: str
    status: RagIndexStatusResponse


class RagSearchHit(BaseModel):
    layout: str
    record_id: str = Field(alias="recordId")
    title: str
    snippet: str
    score: float = 0
    fields: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class RagSearchResponse(BaseModel):
    query: str
    hits: list[RagSearchHit] = Field(default_factory=list)


class RagLayoutProfile(BaseModel):
    layout: str
    field_count: int = Field(alias="fieldCount")
    record_count: int = Field(alias="recordCount")
    indexed_count: int = Field(alias="indexedCount")
    created_field: str = Field(default="", alias="createdField")
    updated_field: str = Field(default="", alias="updatedField")
    field_source: str = Field(default="", alias="fieldSource")
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}

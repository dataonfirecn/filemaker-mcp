from typing import Any

from pydantic import BaseModel, Field

from app.models.business_products import BusinessProductRow
from app.models.rag_index import RagSearchHit


class NaturalLanguageQueryRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=240)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=1, ge=1, le=100_000)


class NaturalLanguageDateRange(BaseModel):
    label: str
    start: str
    end: str
    field: str | None = None


class NaturalLanguageQueryPlan(BaseModel):
    domain: str
    intent: str
    layout: str
    description: str
    query: list[dict[str, Any]] = Field(default_factory=list)
    sort: list[dict[str, str]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    filters: dict[str, str] = Field(default_factory=dict)
    date_range: NaturalLanguageDateRange | None = Field(default=None, alias="dateRange")
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class NaturalLanguageQueryLlmInfo(BaseModel):
    provider: str
    model: str
    confidence: float = 0
    warnings: list[str] = Field(default_factory=list)


class NaturalLanguageQueryResultField(BaseModel):
    label: str
    value: Any = None


class NaturalLanguageQueryResultItem(BaseModel):
    id: str
    kind: str
    title: str
    subtitle: str = ""
    fields: list[NaturalLanguageQueryResultField] = Field(default_factory=list)
    target_type: str = Field(default="", alias="targetType")
    target_identifier: str = Field(default="", alias="targetIdentifier")
    raw: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class NaturalLanguageQueryResponse(BaseModel):
    answer: str
    layout: str
    rows: list[BusinessProductRow] = Field(default_factory=list)
    items: list[NaturalLanguageQueryResultItem] = Field(default_factory=list)
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    plan: NaturalLanguageQueryPlan
    source: str = "filemaker"
    rag_hits: list[RagSearchHit] = Field(default_factory=list, alias="ragHits")
    requires_clarification: bool = Field(default=False, alias="requiresClarification")
    clarification_question: str | None = Field(default=None, alias="clarificationQuestion")
    clarification_options: list[str] = Field(default_factory=list, alias="clarificationOptions")
    llm: NaturalLanguageQueryLlmInfo | None = None

    model_config = {"populate_by_name": True}

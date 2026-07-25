from pydantic import BaseModel, Field


class NaturalQueryAnalyticsRunResponse(BaseModel):
    analyzed: int
    meaningful: int
    ignored: int


class NaturalQueryTopQuestion(BaseModel):
    canonical_question: str = Field(alias="canonicalQuestion")
    normalized_key: str = Field(alias="normalizedKey")
    domain: str = ""
    intent: str = ""
    count: int
    example_prompts: list[str] = Field(default_factory=list, alias="examplePrompts")
    last_asked_at: str = Field(alias="lastAskedAt")

    model_config = {"populate_by_name": True}


class NaturalQueryTopQuestionsResponse(BaseModel):
    days: int
    analyzed_pending: NaturalQueryAnalyticsRunResponse = Field(alias="analyzedPending")
    questions: list[NaturalQueryTopQuestion] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

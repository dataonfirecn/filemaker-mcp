from fastapi import APIRouter, Depends, Query

from app.core.config import Settings
from app.models.natural_query_analytics import (
    NaturalQueryAnalyticsRunResponse,
    NaturalQueryTopQuestion,
    NaturalQueryTopQuestionsResponse,
)
from app.services.audit_log import OperatorContext
from app.services.dependencies import (
    get_natural_query_conversation_store,
    get_operator_context,
    get_settings,
)
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_question_analytics import analyze_pending_questions

router = APIRouter(prefix="/natural-query/analytics", tags=["natural-query-analytics"])


@router.post("/analyze-pending", response_model=NaturalQueryAnalyticsRunResponse)
async def analyze_pending_natural_query_questions(
    limit: int = Query(default=100, ge=1, le=500),
    _operator: OperatorContext = Depends(get_operator_context),
    store: NaturalQueryConversationStore = Depends(get_natural_query_conversation_store),
    settings: Settings = Depends(get_settings),
) -> NaturalQueryAnalyticsRunResponse:
    result = await analyze_pending_questions(store=store, settings=settings, limit=limit)
    return NaturalQueryAnalyticsRunResponse(
        analyzed=result.analyzed,
        meaningful=result.meaningful,
        ignored=result.ignored,
    )


@router.get("/top-questions", response_model=NaturalQueryTopQuestionsResponse)
async def get_top_natural_query_questions(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    analyze_pending: bool = Query(default=True, alias="analyzePending"),
    pending_limit: int = Query(default=100, ge=1, le=500, alias="pendingLimit"),
    _operator: OperatorContext = Depends(get_operator_context),
    store: NaturalQueryConversationStore = Depends(get_natural_query_conversation_store),
    settings: Settings = Depends(get_settings),
) -> NaturalQueryTopQuestionsResponse:
    analyzed = NaturalQueryAnalyticsRunResponse(analyzed=0, meaningful=0, ignored=0)
    if analyze_pending:
        result = await analyze_pending_questions(store=store, settings=settings, limit=pending_limit)
        analyzed = NaturalQueryAnalyticsRunResponse(
            analyzed=result.analyzed,
            meaningful=result.meaningful,
            ignored=result.ignored,
        )
    questions = await store.top_questions(days=days, limit=limit)
    return NaturalQueryTopQuestionsResponse(
        days=days,
        analyzedPending=analyzed,
        questions=[
            NaturalQueryTopQuestion(
                canonicalQuestion=item.canonical_question,
                normalizedKey=item.normalized_key,
                domain=item.domain,
                intent=item.intent,
                count=item.count,
                examplePrompts=item.example_prompts,
                lastAskedAt=item.last_asked_at,
            )
            for item in questions
        ],
    )

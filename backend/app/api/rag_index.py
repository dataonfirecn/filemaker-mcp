from fastapi import APIRouter, Depends, Query

from app.models.rag_index import (
    RagIndexRefreshResponse,
    RagIndexStatusResponse,
    RagSearchHit,
    RagSearchResponse,
)
from app.services.audit_log import OperatorContext
from app.services.dependencies import (
    get_operator_context,
    get_rag_index_store,
    get_rag_index_worker,
    get_settings,
)
from app.services.rag_index import RagIndexStore, RagIndexWorker
from app.core.config import Settings

router = APIRouter(prefix="/rag-index", tags=["rag-index"])


@router.get("/status", response_model=RagIndexStatusResponse)
async def get_rag_index_status(
    _operator: OperatorContext = Depends(get_operator_context),
    store: RagIndexStore = Depends(get_rag_index_store),
    worker: RagIndexWorker | None = Depends(get_rag_index_worker),
    settings: Settings = Depends(get_settings),
) -> RagIndexStatusResponse:
    status = await store.status(
        enabled=settings.rag_index_enabled,
        refresh_interval_seconds=settings.rag_index_refresh_interval_seconds,
        running=bool(worker and worker.running),
    )
    return RagIndexStatusResponse(**status)


@router.post("/refresh", response_model=RagIndexRefreshResponse)
async def refresh_rag_index(
    _operator: OperatorContext = Depends(get_operator_context),
    store: RagIndexStore = Depends(get_rag_index_store),
    worker: RagIndexWorker | None = Depends(get_rag_index_worker),
    settings: Settings = Depends(get_settings),
) -> RagIndexRefreshResponse:
    accepted = bool(worker and worker.request_refresh())
    status = await store.status(
        enabled=settings.rag_index_enabled,
        refresh_interval_seconds=settings.rag_index_refresh_interval_seconds,
        running=bool(worker and worker.running),
    )
    message = "RAG 索引刷新已加入后台队列。" if accepted else "RAG 索引未启用，无法刷新。"
    return RagIndexRefreshResponse(
        accepted=accepted,
        message=message,
        status=RagIndexStatusResponse(**status),
    )


@router.get("/search", response_model=RagSearchResponse)
async def search_rag_index(
    q: str = Query(min_length=1, max_length=240),
    layout: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
    _operator: OperatorContext = Depends(get_operator_context),
    store: RagIndexStore = Depends(get_rag_index_store),
) -> RagSearchResponse:
    hits = await store.search(q, limit=limit, layout=layout)
    return RagSearchResponse(
        query=q,
        hits=[
            RagSearchHit(
                layout=hit.layout,
                recordId=hit.record_id,
                title=hit.title,
                snippet=hit.snippet,
                score=hit.score,
                fields=hit.fields,
                updatedAt=hit.updated_at,
            )
            for hit in hits
        ],
    )

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.config import Settings
from app.core.security import verify_mes_request
from app.models.callback import CallbackAcceptedResponse, CallbackEventResponse
from app.services.callback_store import CallbackEvent, CallbackStore
from app.services.dependencies import get_callback_store, get_settings_from_app

router = APIRouter(prefix="/mes", tags=["mes"])


def callback_response(event: CallbackEvent) -> CallbackEventResponse:
    return CallbackEventResponse(
        id=event.id,
        source=event.source,
        eventId=event.event_id,
        status=event.status,
        payload=event.payload,
        attemptCount=event.attempt_count,
        maxAttempts=event.max_attempts,
        lastError=event.last_error,
        filemakerResult=event.filemaker_result,
        createdAt=event.created_at,
        updatedAt=event.updated_at,
        nextAttemptAt=event.next_attempt_at,
    )


def extract_event_id(payload: dict[str, object]) -> str:
    for key in ("eventId", "event_id", "callbackId", "callback_id", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    return str(uuid.uuid4())


@router.post(
    "/callback",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CallbackAcceptedResponse,
)
async def receive_default_callback(
    request: Request,
    settings: Settings = Depends(get_settings_from_app),
    store: CallbackStore = Depends(get_callback_store),
) -> CallbackAcceptedResponse:
    return await receive_callback_for_source("mes", request, settings, store)


@router.post(
    "/callback/{source}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CallbackAcceptedResponse,
)
async def receive_callback_for_source(
    source: str,
    request: Request,
    settings: Settings = Depends(get_settings_from_app),
    store: CallbackStore = Depends(get_callback_store),
) -> CallbackAcceptedResponse:
    raw_body = await verify_mes_request(request, settings)
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback body must be JSON",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Callback body must be a JSON object",
        )

    event_id = extract_event_id(payload)
    event, duplicate = await store.create_event(
        source=source,
        event_id=event_id,
        payload=payload,
        max_attempts=settings.callback_max_attempts,
    )
    return CallbackAcceptedResponse(
        duplicate=duplicate,
        eventId=event.event_id,
        status=event.status,
    )


@router.get("/events", response_model=list[CallbackEventResponse])
async def list_events(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    store: CallbackStore = Depends(get_callback_store),
) -> list[CallbackEventResponse]:
    events = await store.list_events(status=status_filter, limit=limit)
    return [callback_response(event) for event in events]


@router.get("/events/{event_pk}", response_model=CallbackEventResponse)
async def get_event(
    event_pk: int,
    store: CallbackStore = Depends(get_callback_store),
) -> CallbackEventResponse:
    event = await store.get_event(event_pk)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return callback_response(event)

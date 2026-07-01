from typing import Any, Literal

from pydantic import BaseModel, Field


CallbackStatus = Literal[
    "received",
    "processing",
    "success",
    "retrying",
    "failed",
    "dead",
]


class CallbackAcceptedResponse(BaseModel):
    accepted: bool = True
    duplicate: bool = False
    event_id: str = Field(alias="eventId")
    status: CallbackStatus

    model_config = {"populate_by_name": True}


class CallbackEventResponse(BaseModel):
    id: int
    source: str
    event_id: str = Field(alias="eventId")
    status: CallbackStatus
    payload: dict[str, Any]
    attempt_count: int = Field(alias="attemptCount")
    max_attempts: int = Field(alias="maxAttempts")
    last_error: str | None = Field(alias="lastError")
    filemaker_result: dict[str, Any] | str | None = Field(alias="filemakerResult")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    next_attempt_at: str | None = Field(alias="nextAttemptAt")

    model_config = {"populate_by_name": True}

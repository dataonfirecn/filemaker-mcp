import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_settings_from_app,
)
from app.services.mobile_diagnostic_email import (
    MobileDiagnosticEmailError,
    send_mobile_diagnostic_email,
)
from app.services.mobile_app_version import (
    APP_BUILD_HEADER,
    APP_VERSION_HEADER,
    build_compatibility_status,
    parse_client_build,
)
from app.services.webviewer_remote_auth import is_webviewer_mobile_request
from app.services.webviewer_session import (
    WebViewerSessionError,
    operator_from_session,
    verify_session_token_for_diagnostics,
)


router = APIRouter(prefix="/mobile/v1/app", tags=["mobile-app"])
_diagnostic_email_lock = asyncio.Lock()
_diagnostic_email_inflight: set[tuple[str, str]] = set()
_diagnostic_email_sent: dict[tuple[str, str], datetime] = {}
_diagnostic_email_attempts: dict[str, list[datetime]] = {}


class MobileDiagnosticEmailRequest(BaseModel):
    report_id: str = Field(alias="reportId", min_length=1, max_length=80)
    draft_id: str = Field(alias="draftId", min_length=1, max_length=160)
    document_number: str = Field(
        default="",
        alias="documentNumber",
        max_length=160,
    )
    event: str = Field(min_length=1, max_length=120)
    report: str = Field(min_length=1, max_length=500_000)

    model_config = {"populate_by_name": True}

    @field_validator("report")
    @classmethod
    def normalize_report(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("report must not be empty")
        return normalized


class MobileDiagnosticEmailResponse(BaseModel):
    report_id: str = Field(alias="reportId")
    status: str
    sent_at: datetime = Field(alias="sentAt")

    model_config = {"populate_by_name": True}


@router.get("/compatibility")
async def app_compatibility(
    app_build: str | None = Header(default=None, alias=APP_BUILD_HEADER),
    app_version: str | None = Header(default=None, alias=APP_VERSION_HEADER),
    settings: Settings = Depends(get_settings_from_app),
) -> dict[str, object]:
    return build_compatibility_status(
        current_build=parse_client_build(app_build),
        current_version=app_version,
        minimum_build=settings.ios_pda_minimum_build,
        latest_build=settings.ios_pda_latest_build,
    )


async def get_mobile_diagnostic_operator(
    request: Request,
) -> OperatorContext:
    settings: Settings = request.app.state.settings
    if not is_webviewer_mobile_request(
        client_channel=request.headers.get("X-Client-Channel", ""),
        user_agent=request.headers.get("User-Agent", ""),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "Only the StarRC iPad app can send this report."},
        )
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Missing PDA session token"},
        )
    try:
        context = verify_session_token_for_diagnostics(
            token,
            settings,
            expired_grace_seconds=(
                settings.ios_pda_diagnostic_expired_token_grace_seconds
            ),
        )
    except WebViewerSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(exc)},
        ) from exc
    return operator_from_session(context)


@router.post(
    "/diagnostic-reports/email",
    response_model=MobileDiagnosticEmailResponse,
)
async def email_mobile_diagnostic_report(
    body: MobileDiagnosticEmailRequest,
    operator: OperatorContext = Depends(get_mobile_diagnostic_operator),
    settings: Settings = Depends(get_settings_from_app),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> MobileDiagnosticEmailResponse:
    if len(body.report) > settings.ios_pda_diagnostic_report_max_characters:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"message": "错误报告内容超过服务器允许的大小。"},
        )
    delivery_key = (operator.account.casefold(), body.report_id)
    now = datetime.now(timezone.utc)
    async with _diagnostic_email_lock:
        _prune_diagnostic_email_state(now)
        if sent_at := _diagnostic_email_sent.get(delivery_key):
            return MobileDiagnosticEmailResponse(
                reportId=body.report_id,
                status="already_sent",
                sentAt=sent_at,
            )
        if delivery_key in _diagnostic_email_inflight:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": "这份错误报告正在发送，请不要重复点击。"},
            )
        attempts = _diagnostic_email_attempts.setdefault(
            operator.account.casefold(),
            [],
        )
        if len(attempts) >= settings.ios_pda_diagnostic_email_max_per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"message": "错误报告发送过于频繁，请稍后再试或先复制报告。"},
            )
        attempts.append(now)
        _diagnostic_email_inflight.add(delivery_key)

    delivered_at: datetime | None = None
    try:
        await run_in_threadpool(
            send_mobile_diagnostic_email,
            settings,
            operator=operator,
            report_id=body.report_id,
            draft_id=body.draft_id,
            document_number=body.document_number,
            event=body.event,
            report=body.report,
        )
        delivered_at = datetime.now(timezone.utc)
    except MobileDiagnosticEmailError as exc:
        await audit_log.record(
            operator=operator,
            action_type="PDA_DIAGNOSTIC_EMAIL",
            status="failed",
            order_id=body.document_number,
            request_payload={
                "reportId": body.report_id,
                "draftId": body.draft_id,
                "event": body.event,
                "reportCharacters": len(body.report),
            },
            error_message=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "服务器暂时无法发送错误报告邮件，请稍后重试或先复制报告。"
            },
        ) from exc
    finally:
        async with _diagnostic_email_lock:
            _diagnostic_email_inflight.discard(delivery_key)
            if delivered_at is not None:
                _diagnostic_email_sent[delivery_key] = delivered_at

    assert delivered_at is not None
    sent_at = delivered_at
    await audit_log.record(
        operator=operator,
        action_type="PDA_DIAGNOSTIC_EMAIL",
        status="success",
        order_id=body.document_number,
        request_payload={
            "reportId": body.report_id,
            "draftId": body.draft_id,
            "event": body.event,
            "reportCharacters": len(body.report),
        },
        response_payload={"delivery": "administrator"},
    )
    return MobileDiagnosticEmailResponse(
        reportId=body.report_id,
        status="sent",
        sentAt=sent_at,
    )


def _prune_diagnostic_email_state(now: datetime) -> None:
    cutoff = now.timestamp() - 60 * 60
    for account, attempts in list(_diagnostic_email_attempts.items()):
        current = [item for item in attempts if item.timestamp() >= cutoff]
        if current:
            _diagnostic_email_attempts[account] = current
        else:
            _diagnostic_email_attempts.pop(account, None)
    for key, sent_at in list(_diagnostic_email_sent.items()):
        if sent_at.timestamp() < cutoff:
            _diagnostic_email_sent.pop(key, None)

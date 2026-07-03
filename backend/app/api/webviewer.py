from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings
from app.models.webviewer import WebViewerSessionRequest, WebViewerSessionResponse
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import get_audit_log_store, get_settings
from app.services.webviewer_session import (
    WebViewerSessionError,
    create_mock_context,
    issue_session_token,
    verify_external_context,
)

router = APIRouter(prefix="/webviewer", tags=["webviewer"])


@router.post("/session", response_model=WebViewerSessionResponse)
async def create_webviewer_session(
    body: WebViewerSessionRequest,
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> WebViewerSessionResponse:
    if body.ctx and body.sig:
        try:
            context = verify_external_context(body.ctx, body.sig, settings)
        except WebViewerSessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": str(exc)},
            ) from exc
    elif body.mock and settings.webviewer_allow_mock_context:
        operator = body.operator
        context = create_mock_context(
            operator_account=operator.account if operator else "mock.operator",
            operator_name=operator.name if operator else "本地测试操作员",
            operator_privilege=operator.privilege if operator else "mock",
            product_sku=body.product_sku,
            order_id=body.order_id,
            bom_calc_id=body.bom_calc_id,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Signed ctx/sig is required"},
        )

    token, session_payload = issue_session_token(context, settings)
    session_id = session_payload["sessionId"]
    operator = session_payload.get("operator") or {}
    await audit_log.record(
        operator=OperatorContext(
            session_id=session_id,
            account=str(operator.get("account") or "unknown"),
            name=str(operator.get("name") or "unknown"),
            privilege=str(operator.get("privilege") or ""),
        ),
        action_type="WEBVIEWER_SESSION_START",
        status="success",
        product_sku=session_payload.get("productSku") or None,
        order_id=session_payload.get("orderId") or None,
        bom_calc_id=session_payload.get("bomCalcId") or None,
        request_payload={"mock": body.mock, "hasSignedContext": bool(body.ctx and body.sig)},
        response_payload={"sessionId": session_id, "readOnly": settings.filemaker_read_only},
    )
    return WebViewerSessionResponse(
        token=token,
        sessionId=session_id,
        context=session_payload,
        readOnly=settings.filemaker_read_only,
    )

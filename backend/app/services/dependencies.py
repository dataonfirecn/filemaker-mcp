from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.bom_document_store import BomDocumentStore
from app.services.callback_store import CallbackStore
from app.services.filemaker_client import FileMakerClient
from app.services.webviewer_session import (
    WebViewerSessionError,
    operator_from_session,
    verify_session_token,
)


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_settings(request: Request) -> Settings:
    return get_settings_from_app(request)


def get_filemaker_client(request: Request) -> FileMakerClient:
    return request.app.state.filemaker_client


def get_callback_store(request: Request) -> CallbackStore:
    return request.app.state.callback_store


def get_audit_log_store(request: Request) -> AuditLogStore:
    return request.app.state.audit_log_store


def get_bom_document_store(request: Request) -> BomDocumentStore:
    return request.app.state.bom_document_store


def get_operator_context(request: Request) -> OperatorContext:
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Missing WebViewer session token"},
        )
    try:
        session_payload = verify_session_token(token, settings)
    except WebViewerSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(exc)},
        ) from exc
    return operator_from_session(session_payload)

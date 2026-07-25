from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.bom_document_store import BomDocumentStore
from app.services.callback_store import CallbackStore
from app.services.customer_chat_auth import (
    CustomerAuthError,
    CustomerLoginRateLimiter,
    CustomerSession,
    verify_customer_token_with_store,
)
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_chat_history import CustomerChatHistoryStore
from app.services.customer_credential_store import CustomerCredentialStore
from app.services.cos_storage import COSStorageService
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.rag_index import RagIndexStore, RagIndexWorker
from app.services.receipt_attachment_store import ReceiptAttachmentStore
from app.services.webviewer_session import (
    WebViewerSessionError,
    operator_from_session,
    verify_session_token,
)
from app.services.webviewer_account_access import WebViewerAccountAccessStore


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_settings(request: Request) -> Settings:
    return get_settings_from_app(request)


def get_filemaker_client(request: Request) -> FileMakerClient:
    return request.app.state.filemaker_client


def get_filemaker_odata_client(request: Request) -> FileMakerODataClient:
    return request.app.state.filemaker_odata_client


def get_callback_store(request: Request) -> CallbackStore:
    return request.app.state.callback_store


def get_audit_log_store(request: Request) -> AuditLogStore:
    return request.app.state.audit_log_store


def get_bom_document_store(request: Request) -> BomDocumentStore:
    return request.app.state.bom_document_store


def get_rag_index_store(request: Request) -> RagIndexStore:
    return request.app.state.rag_index_store


def get_natural_query_conversation_store(request: Request) -> NaturalQueryConversationStore:
    return request.app.state.natural_query_conversation_store


def get_natural_query_analytics_worker(request: Request) -> NaturalQueryAnalyticsWorker:
    return request.app.state.natural_query_analytics_worker


def get_customer_login_rate_limiter(request: Request) -> CustomerLoginRateLimiter:
    return request.app.state.customer_login_rate_limiter


def get_customer_credential_store(request: Request) -> CustomerCredentialStore:
    return request.app.state.customer_credential_store


def get_customer_chat_history_store(request: Request) -> CustomerChatHistoryStore:
    return request.app.state.customer_chat_history_store


def get_customer_account_admin_store(request: Request) -> CustomerAccountAdminStore:
    return request.app.state.customer_account_admin_store


def get_webviewer_account_access_store(request: Request) -> WebViewerAccountAccessStore:
    return request.app.state.webviewer_account_access_store


def get_cos_storage_service(request: Request) -> COSStorageService:
    return request.app.state.cos_storage_service


def get_receipt_attachment_store(request: Request) -> ReceiptAttachmentStore:
    return request.app.state.receipt_attachment_store


def get_rag_index_worker(request: Request) -> RagIndexWorker | None:
    return getattr(request.app.state, "rag_index_worker", None)


async def get_webviewer_session_context(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Missing WebViewer session token"},
        )
    try:
        context = verify_session_token(token, settings)
    except WebViewerSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": str(exc)},
        ) from exc

    operator = context.get("operator") or {}
    account = await request.app.state.webviewer_account_access_store.observe_account(
        username=str(operator.get("account") or "unknown"),
        display_name=str(operator.get("name") or operator.get("account") or "unknown"),
        privilege_set=str(operator.get("privilege") or "unknown"),
    )
    if not account["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "此 StarRC 账号或其 FileMaker 权限集已停用。"},
        )

    access = dict(account["permissions"])
    request.state.webviewer_access = access
    request.state.webviewer_account = account
    context["access"] = access
    required_permission = _permission_for_request(request)
    if required_permission and not access.get(required_permission, False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "当前账号没有访问此功能的权限。",
                "permission": required_permission,
            },
        )
    return context


async def get_operator_context(
    session_context: dict = Depends(get_webviewer_session_context),
) -> OperatorContext:
    return operator_from_session(session_context)


async def get_webviewer_access(
    session_context: dict = Depends(get_webviewer_session_context),
) -> dict[str, bool]:
    return dict(session_context.get("access") or {})


async def get_customer_session(request: Request) -> CustomerSession:
    settings: Settings = request.app.state.settings
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Sign in to the customer portal first."},
        )
    try:
        return await verify_customer_token_with_store(
            token,
            settings,
            request.app.state.customer_credential_store,
            request.app.state.customer_account_admin_store,
        )
    except CustomerAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Your session is invalid or has expired. Please sign in again."},
        ) from exc


def _permission_for_request(request: Request) -> str | None:
    path = request.url.path
    method = request.method.upper()
    if "/webviewer/admin/" in path:
        return "canManageAccounts"
    if path.startswith("/api/filemaker"):
        return "canManageRag"
    if path.endswith("/inventory-transactions"):
        return "canViewInventory"
    if path.startswith("/api/business-products"):
        return "canViewProducts"
    if path.startswith("/api/orders"):
        if path.endswith("/bom-calculations") and method == "POST":
            return "canViewBom"
        if "/merge/" in path and method == "POST":
            return "canMergeOrders"
        return "canViewOrders"
    if path.startswith("/api/mobile/v1/receipts"):
        return "canViewOrders"
    if path.startswith("/api/natural-query/analytics"):
        return "canManageRag"
    if path == "/api/natural-query":
        return "canUseNaturalQuery"
    if path.startswith(("/api/rag-index", "/api/odata")):
        return "canManageRag"
    if path.startswith(
        (
            "/api/bom-changes",
            "/api/bom-calculations",
            "/api/bom-documents",
            "/api/parts",
            "/api/part-creation",
            "/api/kit-issue-records",
            "/api/material-ids",
        )
    ):
        return "canViewBom"
    if path.startswith("/api/products/") and path.endswith("/bom-view"):
        return "canViewBom"
    return None

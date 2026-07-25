import logging
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api import (
    bom_changes,
    bom_documents,
    business_products,
    customer_catalog,
    customer_chat,
    filemaker,
    health,
    inventory,
    material_ids,
    mes_callbacks,
    natural_query_analytics,
    natural_language_query,
    odata,
    orders,
    part_creation,
    qrcode,
    rag_index,
    webviewer,
)
from app.core.config import get_settings
from app.services.audit_log import AuditLogStore
from app.services.bom_document_store import BomDocumentStore
from app.services.callback_store import CallbackStore
from app.services.callback_worker import CallbackWorker
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_chat_auth import CustomerLoginRateLimiter, load_customer_accounts
from app.services.customer_chat_history import CustomerChatHistoryStore
from app.services.customer_credential_store import CustomerCredentialStore
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.rag_index import RagIndexStore, RagIndexWorker
from app.services.webviewer_account_access import (
    WebViewerAccountAccessStore,
    load_privilege_set_policies,
    sanitize_price_data,
)
from app.services.webviewer_remote_auth import load_webviewer_remote_accounts


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = get_settings()
    settings.validate_production_security()
    filemaker_client = FileMakerClient(settings)
    filemaker_odata_client = FileMakerODataClient(settings)
    audit_log_store = AuditLogStore(settings.audit_database_url)
    await audit_log_store.init()
    bom_document_store = BomDocumentStore(settings.audit_database_url)
    await bom_document_store.init()
    callback_store = CallbackStore(settings.database_path)
    await callback_store.init()
    customer_credential_store = CustomerCredentialStore(settings.database_path)
    await customer_credential_store.init()
    customer_chat_history_store = CustomerChatHistoryStore(settings.audit_database_url)
    await customer_chat_history_store.init()
    customer_account_admin_store = CustomerAccountAdminStore(settings.audit_database_url)
    await customer_account_admin_store.init(load_customer_accounts(settings))
    webviewer_account_access_store = WebViewerAccountAccessStore(settings.audit_database_url)
    remote_accounts = load_webviewer_remote_accounts(settings)
    await webviewer_account_access_store.init(
        seed_accounts=(
            {
                "username": account.username,
                "displayName": account.display_name,
                "privilegeSet": account.privilege_set,
            }
            for account in remote_accounts.values()
        ),
        seed_privilege_sets=load_privilege_set_policies(
            settings.webviewer_privilege_set_policy_path
        ),
    )
    natural_query_conversation_store = NaturalQueryConversationStore(settings.database_path)
    await natural_query_conversation_store.init()
    natural_query_analytics_worker = NaturalQueryAnalyticsWorker(
        store=natural_query_conversation_store,
        settings=settings,
    )
    rag_index_store = RagIndexStore(settings.rag_database_path)
    await rag_index_store.init()
    callback_worker = CallbackWorker(
        store=callback_store,
        filemaker_client=filemaker_client,
        settings=settings,
    )
    rag_index_worker = RagIndexWorker(
        store=rag_index_store,
        filemaker_client=filemaker_client,
        settings=settings,
    )

    app.state.settings = settings
    app.state.filemaker_client = filemaker_client
    app.state.filemaker_odata_client = filemaker_odata_client
    app.state.audit_log_store = audit_log_store
    app.state.bom_document_store = bom_document_store
    app.state.callback_store = callback_store
    app.state.callback_worker = callback_worker
    app.state.customer_login_rate_limiter = CustomerLoginRateLimiter()
    app.state.customer_credential_store = customer_credential_store
    app.state.customer_chat_history_store = customer_chat_history_store
    app.state.customer_account_admin_store = customer_account_admin_store
    app.state.webviewer_account_access_store = webviewer_account_access_store
    app.state.natural_query_conversation_store = natural_query_conversation_store
    app.state.natural_query_analytics_worker = natural_query_analytics_worker
    app.state.rag_index_store = rag_index_store
    app.state.rag_index_worker = rag_index_worker
    app.state.rag_semantic_registry = rag_index_worker.semantic_registry

    callback_worker.start()
    rag_index_worker.start()
    natural_query_analytics_worker.start()
    try:
        yield
    finally:
        await natural_query_analytics_worker.stop()
        await rag_index_worker.stop()
        await callback_worker.stop()
        await bom_document_store.close()
        await webviewer_account_access_store.close()
        await customer_account_admin_store.close()
        await customer_chat_history_store.close()
        await audit_log_store.close()
        await filemaker_odata_client.close()
        await filemaker_client.close()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Requested-With",
        "X-Client-Channel",
        "X-QA-Test",
    ],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def filter_price_fields_for_webviewer_accounts(request, call_next):
    response = await call_next(request)
    access = getattr(request.state, "webviewer_access", None)
    content_type = response.headers.get("content-type", "")
    if (
        not access
        or access.get("canViewPrice", False)
        or "application/json" not in content_type
        or response.status_code >= 500
    ):
        return response

    body = b"".join([bytes(chunk) async for chunk in response.body_iterator])
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=content_type,
            background=response.background,
        )

    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers.pop("content-type", None)
    return Response(
        content=json.dumps(
            sanitize_price_data(
                payload,
                semantic_registry=getattr(
                    request.app.state,
                    "rag_semantic_registry",
                    None,
                ),
            ),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ),
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
        background=response.background,
    )

app.include_router(health.router)
app.include_router(filemaker.router, prefix=settings.api_prefix)
app.include_router(webviewer.router, prefix=settings.api_prefix)
app.include_router(inventory.router, prefix=settings.api_prefix)
app.include_router(material_ids.router, prefix=settings.api_prefix)
app.include_router(part_creation.router, prefix=settings.api_prefix)
app.include_router(bom_changes.router, prefix=settings.api_prefix)
app.include_router(bom_documents.router, prefix=settings.api_prefix)
app.include_router(business_products.router, prefix=settings.api_prefix)
app.include_router(customer_catalog.router, prefix=settings.api_prefix)
app.include_router(customer_chat.router, prefix=settings.api_prefix)
app.include_router(natural_language_query.router, prefix=settings.api_prefix)
app.include_router(natural_query_analytics.router, prefix=settings.api_prefix)
app.include_router(odata.router, prefix=settings.api_prefix)
app.include_router(orders.router, prefix=settings.api_prefix)
app.include_router(rag_index.router, prefix=settings.api_prefix)
app.include_router(mes_callbacks.router, prefix=settings.api_prefix)
app.include_router(qrcode.router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}

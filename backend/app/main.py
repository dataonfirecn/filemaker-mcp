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
    product_master,
    product_quotes,
    customer_directory,
    filemaker,
    health,
    inventory,
    material_ids,
    mes_callbacks,
    mobile_app,
    mobile_products,
    mobile_receipts,
    natural_query_analytics,
    natural_language_query,
    odata,
    orders,
    demand_orders,
    part_assets,
    part_creation,
    part_directory,
    qrcode,
    quality,
    rag_index,
    receipt_history,
    reports,
    webviewer,
)
from app.core.config import get_settings
from app.services.audit_log import AuditLogStore
from app.services.bom_document_store import BomDocumentStore
from app.services.callback_store import CallbackStore
from app.services.callback_worker import CallbackWorker
from app.services.cos_storage import COSStorageService
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.llm_provider_manager import LlmProviderManager
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.nightly_maintenance import NightlyMaintenanceWorker
from app.services.nightly_report_store import NightlyReportStore
from app.services.mobile_app_version import IOSPDABuildGateMiddleware
from app.services.part_asset_upload_store import PartAssetUploadStore
from app.services.part_creation_options_cache import PartCreationOptionsCache
from app.services.product_photo_upload_store import ProductPhotoUploadStore
from app.services.quality_inspection_store import QualityInspectionStore
from app.services.rag_index import RagIndexStore, RagIndexWorker
from app.services.receipt_attachment_store import ReceiptAttachmentStore
from app.services.synthetic_query_monitor import SyntheticQueryMonitor
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
    llm_provider_manager = LlmProviderManager(
        settings=settings,
        database_path=settings.database_path,
    )
    await llm_provider_manager.init()
    settings.validate_production_security()
    filemaker_client = FileMakerClient(settings)
    filemaker_odata_client = FileMakerODataClient(settings)
    audit_log_store = AuditLogStore(settings.audit_database_url)
    await audit_log_store.init()
    quality_inspection_store = QualityInspectionStore(settings.audit_database_url)
    await quality_inspection_store.init()
    bom_document_store = BomDocumentStore(settings.audit_database_url)
    await bom_document_store.init()
    callback_store = CallbackStore(settings.database_path)
    await callback_store.init()
    receipt_attachment_store = ReceiptAttachmentStore(settings.database_path)
    await receipt_attachment_store.init()
    part_asset_upload_store = PartAssetUploadStore(settings.database_path)
    await part_asset_upload_store.init()
    product_photo_upload_store = ProductPhotoUploadStore(settings.database_path)
    await product_photo_upload_store.init()
    part_creation_options_cache = PartCreationOptionsCache(
        database_path=settings.database_path,
        filemaker=filemaker_client,
        settings=settings,
    )
    await part_creation_options_cache.init()
    await part_creation_options_cache.ensure_seeded()
    cos_storage_service = COSStorageService(settings)
    webviewer_account_access_store = WebViewerAccountAccessStore(settings.audit_database_url)
    remote_accounts = load_webviewer_remote_accounts(settings)
    await webviewer_account_access_store.init(
        seed_accounts=(
            {
                "username": account.username,
                "displayName": account.display_name,
                "privilegeSet": account.privilege_set,
                "passwordHash": account.password_hash,
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
    nightly_maintenance_worker = NightlyMaintenanceWorker(
        store=natural_query_conversation_store,
        settings=settings,
        reports=NightlyReportStore(
            settings.database_path,
            settings.nightly_reports_directory,
        ),
    )
    await nightly_maintenance_worker.init()
    rag_index_store = RagIndexStore(settings.rag_database_path, settings=settings)
    await rag_index_store.init()
    synthetic_query_monitor = SyntheticQueryMonitor(
        store=natural_query_conversation_store,
        settings=settings,
        reports=nightly_maintenance_worker.reports,
        filemaker=filemaker_client,
        odata_client=filemaker_odata_client,
        rag_store=rag_index_store,
        audit_log=audit_log_store,
    )
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
    app.state.quality_inspection_store = quality_inspection_store
    app.state.bom_document_store = bom_document_store
    app.state.callback_store = callback_store
    app.state.callback_worker = callback_worker
    app.state.llm_provider_manager = llm_provider_manager
    app.state.webviewer_account_access_store = webviewer_account_access_store
    app.state.receipt_attachment_store = receipt_attachment_store
    app.state.part_asset_upload_store = part_asset_upload_store
    app.state.product_photo_upload_store = product_photo_upload_store
    app.state.part_creation_options_cache = part_creation_options_cache
    app.state.cos_storage_service = cos_storage_service
    app.state.natural_query_conversation_store = natural_query_conversation_store
    app.state.natural_query_analytics_worker = natural_query_analytics_worker
    app.state.nightly_maintenance_worker = nightly_maintenance_worker
    app.state.nightly_report_store = nightly_maintenance_worker.reports
    app.state.synthetic_query_monitor = synthetic_query_monitor
    app.state.rag_index_store = rag_index_store
    app.state.rag_index_worker = rag_index_worker
    app.state.rag_semantic_registry = rag_index_worker.semantic_registry

    product_master_store = product_master_worker = product_master_filemaker = product_master_preview_store = None
    if settings.product_master_preview_enabled:
        from app.services.product_master.schema import ProductSchema
        app.state.product_master_schema = ProductSchema.load(settings.product_master_schema_path)
        if not settings.product_master_enabled:
            from app.services.product_master.store import ProductStore, source_fingerprint
            product_master_preview_store = ProductStore(settings.audit_database_url, settings.product_master_source, source_fingerprint(settings))
            await product_master_preview_store.init()
            app.state.product_master_preview_store = product_master_preview_store
    if settings.product_master_enabled:
        from app.services.product_master.schema import ProductSchema
        from app.services.product_master.store import ProductStore, source_fingerprint
        from app.services.product_master.worker import ProductWorker
        schema = ProductSchema.load(settings.product_master_schema_path)
        if settings.product_master_write_enabled and (
            not settings.product_master_username or not settings.product_master_password
            or not schema.document.get("baseTableVerified")
            or not schema.document.get("nativeEditingLocked")
            or not schema.document.get("uuidCreateVerified")
            or schema.document.get("layout") != settings.product_master_layout
        ):
            raise RuntimeError("Product writeback requires verified base-table coverage, dedicated layout and native edit lock")
        product_master_store = ProductStore(settings.audit_database_url, settings.product_master_source, source_fingerprint(settings))
        await product_master_store.init()
        app.state.product_master_store = product_master_store
        filemaker_client.product_master_store = product_master_store
        app.state.product_master_schema = schema
        product_master_filemaker = FileMakerClient(settings.model_copy(update={
            "filemaker_username": settings.product_master_username or settings.filemaker_username,
            "filemaker_password": settings.product_master_password or settings.filemaker_password,
        }))
        product_master_worker = ProductWorker(product_master_store, schema, product_master_filemaker, cos_storage_service, settings)
        product_master_worker.start()

    callback_worker.start()
    rag_index_worker.start()
    natural_query_analytics_worker.start()
    nightly_maintenance_worker.start()
    synthetic_query_monitor.start()
    part_creation_options_cache.start()
    try:
        yield
    finally:
        if product_master_worker:
            await product_master_worker.stop()
        if product_master_store:
            await product_master_store.close()
        if product_master_preview_store:
            await product_master_preview_store.close()
        if product_master_filemaker:
            await product_master_filemaker.close()
        await part_creation_options_cache.stop()
        await synthetic_query_monitor.stop()
        await nightly_maintenance_worker.stop()
        await natural_query_analytics_worker.stop()
        await rag_index_worker.stop()
        await callback_worker.stop()
        await bom_document_store.close()
        await quality_inspection_store.close()
        await webviewer_account_access_store.close()
        await audit_log_store.close()
        await filemaker_odata_client.close()
        await filemaker_client.close()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    IOSPDABuildGateMiddleware,
    minimum_build=settings.ios_pda_minimum_build,
    latest_build=settings.ios_pda_latest_build,
    compatibility_path=(
        f"{settings.api_prefix.rstrip('/')}/mobile/v1/app/compatibility"
    ),
)
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
        "X-App-Build",
        "X-App-Version",
        "X-QA-Test",
    ],
    expose_headers=[
        "Content-Disposition",
        "X-Minimum-App-Build",
        "X-Latest-App-Build",
    ],
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
app.include_router(product_master.router, prefix=settings.api_prefix)
app.include_router(product_quotes.router, prefix=settings.api_prefix)
app.include_router(customer_directory.router, prefix=settings.api_prefix)
app.include_router(filemaker.router, prefix=settings.api_prefix)
app.include_router(webviewer.router, prefix=settings.api_prefix)
app.include_router(inventory.router, prefix=settings.api_prefix)
app.include_router(material_ids.router, prefix=settings.api_prefix)
app.include_router(part_creation.router, prefix=settings.api_prefix)
app.include_router(part_assets.router, prefix=settings.api_prefix)
app.include_router(part_directory.router, prefix=settings.api_prefix)
app.include_router(bom_changes.router, prefix=settings.api_prefix)
app.include_router(bom_documents.router, prefix=settings.api_prefix)
app.include_router(business_products.router, prefix=settings.api_prefix)
app.include_router(natural_language_query.router, prefix=settings.api_prefix)
app.include_router(natural_query_analytics.router, prefix=settings.api_prefix)
app.include_router(odata.router, prefix=settings.api_prefix)
app.include_router(orders.router, prefix=settings.api_prefix)
app.include_router(demand_orders.router, prefix=settings.api_prefix)
app.include_router(receipt_history.router, prefix=settings.api_prefix)
app.include_router(reports.router, prefix=settings.api_prefix)
app.include_router(rag_index.router, prefix=settings.api_prefix)
app.include_router(mes_callbacks.router, prefix=settings.api_prefix)
app.include_router(qrcode.router, prefix=settings.api_prefix)
app.include_router(quality.router, prefix=settings.api_prefix)
app.include_router(mobile_app.router, prefix=settings.api_prefix)
app.include_router(mobile_receipts.router, prefix=settings.api_prefix)
app.include_router(mobile_products.router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}

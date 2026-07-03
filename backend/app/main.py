import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import bom_changes, bom_documents, filemaker, health, mes_callbacks, qrcode, webviewer
from app.core.config import get_settings
from app.services.audit_log import AuditLogStore
from app.services.bom_document_store import BomDocumentStore
from app.services.callback_store import CallbackStore
from app.services.callback_worker import CallbackWorker
from app.services.filemaker_client import FileMakerClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    settings = get_settings()
    filemaker_client = FileMakerClient(settings)
    audit_log_store = AuditLogStore(settings.audit_database_url)
    await audit_log_store.init()
    bom_document_store = BomDocumentStore(settings.audit_database_url)
    await bom_document_store.init()
    callback_store = CallbackStore(settings.database_path)
    await callback_store.init()
    callback_worker = CallbackWorker(
        store=callback_store,
        filemaker_client=filemaker_client,
        settings=settings,
    )

    app.state.settings = settings
    app.state.filemaker_client = filemaker_client
    app.state.audit_log_store = audit_log_store
    app.state.bom_document_store = bom_document_store
    app.state.callback_store = callback_store
    app.state.callback_worker = callback_worker

    callback_worker.start()
    try:
        yield
    finally:
        await callback_worker.stop()
        await bom_document_store.close()
        await audit_log_store.close()
        await filemaker_client.close()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(filemaker.router, prefix=settings.api_prefix)
app.include_router(webviewer.router, prefix=settings.api_prefix)
app.include_router(bom_changes.router, prefix=settings.api_prefix)
app.include_router(bom_documents.router, prefix=settings.api_prefix)
app.include_router(mes_callbacks.router, prefix=settings.api_prefix)
app.include_router(qrcode.router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}

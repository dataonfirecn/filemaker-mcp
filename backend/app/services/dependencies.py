from fastapi import Request

from app.core.config import Settings
from app.services.callback_store import CallbackStore
from app.services.filemaker_client import FileMakerClient


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_filemaker_client(request: Request) -> FileMakerClient:
    return request.app.state.filemaker_client


def get_callback_store(request: Request) -> CallbackStore:
    return request.app.state.callback_store

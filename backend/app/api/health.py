from fastapi import APIRouter, Depends

from app.core.config import Settings
from app.services.dependencies import get_settings_from_app

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz(settings: Settings = Depends(get_settings_from_app)) -> dict[str, object]:
    return {
        "ok": True,
        "service": settings.app_name,
        "environment": settings.app_env,
        "filemakerConfigured": settings.filemaker_configured,
    }

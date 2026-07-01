from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.core.config import Settings
from app.models.qrcode import QRCodeGenerateRequest
from app.services.dependencies import get_settings_from_app
from app.services.qrcode_service import build_qr_payload, generate_png, generate_svg

router = APIRouter(prefix="/qrcode", tags=["qrcode"])


@router.post("/generate")
async def generate_qrcode(
    body: QRCodeGenerateRequest,
    settings: Settings = Depends(get_settings_from_app),
) -> Response:
    try:
        payload = build_qr_payload(
            data=body.data,
            token=body.token,
            base_url=settings.qr_base_url,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if body.format == "svg":
        return Response(
            content=generate_svg(payload=payload, border=body.border),
            media_type="image/svg+xml",
        )

    return Response(
        content=generate_png(
            payload=payload,
            box_size=body.box_size,
            border=body.border,
            fill_color=body.fill_color,
            back_color=body.back_color,
        ),
        media_type="image/png",
    )

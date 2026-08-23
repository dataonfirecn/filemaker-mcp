from collections.abc import Awaitable, Callable

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


IOS_PDA_CHANNEL = "ios-pda"
CLIENT_CHANNEL_HEADER = "X-Client-Channel"
APP_BUILD_HEADER = "X-App-Build"
APP_VERSION_HEADER = "X-App-Version"
DEFAULT_COMPATIBILITY_PATH = "/api/mobile/v1/app/compatibility"


def parse_client_build(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        build = int(value.strip())
    except (TypeError, ValueError):
        return None
    return build if build >= 0 else None


def build_compatibility_status(
    *,
    current_build: int | None,
    current_version: str | None,
    minimum_build: int,
    latest_build: int,
) -> dict[str, object]:
    normalized_minimum = max(0, minimum_build)
    normalized_latest = max(normalized_minimum, latest_build)
    update_required = normalized_minimum > 0 and (
        current_build is None or current_build < normalized_minimum
    )

    if update_required:
        current_label = (
            str(current_build) if current_build is not None else "无法识别"
        )
        message = (
            f"PDA 版本过旧：当前构建 {current_label}，最低要求构建 "
            f"{normalized_minimum}。请安装最新版本后重试。"
        )
    elif current_build is not None and current_build < normalized_latest:
        message = f"有新的 PDA 构建 {normalized_latest} 可安装。"
    else:
        message = "当前 PDA 版本可继续使用。"

    return {
        "channel": IOS_PDA_CHANNEL,
        "currentBuild": current_build,
        "currentVersion": (current_version or "").strip() or None,
        "minimumBuild": normalized_minimum,
        "latestBuild": normalized_latest,
        "updateRequired": update_required,
        "message": message,
    }


class IOSPDABuildGateMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        minimum_build: int,
        latest_build: int,
        compatibility_path: str = DEFAULT_COMPATIBILITY_PATH,
    ) -> None:
        super().__init__(app)
        self.minimum_build = minimum_build
        self.latest_build = latest_build
        self.compatibility_path = compatibility_path

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        channel = request.headers.get(CLIENT_CHANNEL_HEADER, "").strip().lower()
        if (
            request.method == "OPTIONS"
            or channel != IOS_PDA_CHANNEL
            or request.url.path.rstrip("/") == self.compatibility_path.rstrip("/")
        ):
            return await call_next(request)

        compatibility = build_compatibility_status(
            current_build=parse_client_build(request.headers.get(APP_BUILD_HEADER)),
            current_version=request.headers.get(APP_VERSION_HEADER),
            minimum_build=self.minimum_build,
            latest_build=self.latest_build,
        )
        if not compatibility["updateRequired"]:
            return await call_next(request)

        return JSONResponse(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            content={
                "detail": {
                    "code": "client_update_required",
                    **compatibility,
                }
            },
            headers={
                "X-Minimum-App-Build": str(compatibility["minimumBuild"]),
                "X-Latest-App-Build": str(compatibility["latestBuild"]),
            },
        )

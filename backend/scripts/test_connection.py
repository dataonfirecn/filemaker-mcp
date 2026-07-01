import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.filemaker_client import FileMakerClient  # noqa: E402


async def main() -> None:
    settings = get_settings()
    print("=== 配置信息 ===")
    print("Host:", settings.filemaker_host)
    print("Database:", settings.filemaker_database)
    print("Username:", settings.filemaker_username)
    print("")

    client = FileMakerClient(settings)
    try:
        token = await client.get_token()
        print("认证成功，token 前 8 位:", token[:8])
        layouts = await client.list_layouts()
        print("布局数量:", len(layouts))
        print("前 10 个布局:", ", ".join(layouts[:10]))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

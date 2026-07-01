import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.filemaker_client import FileMakerClient  # noqa: E402


async def main() -> None:
    settings = get_settings()
    layouts = sys.argv[1:] or ["客户列表", "Products", "客户资料", "公司資訊", "厂商列表"]

    client = FileMakerClient(settings)
    try:
        for layout in layouts:
            print(f"\n=== 尝试查询布局: {layout} ===")
            try:
                fields = await client.get_layout_fields(layout)
                print("字段数:", len(fields))
                print("前 5 个字段:", ", ".join(field["name"] for field in fields[:5]))

                result = await client.find_records(layout, limit=5, offset=1)
                print(
                    "找到记录数:",
                    result["foundCount"],
                    "返回:",
                    result["returnedCount"],
                )
                if result["data"]:
                    field_data = result["data"][0].get("fieldData", {})
                    print("第一条记录示例:")
                    for key, value in list(field_data.items())[:8]:
                        print(f"  {key}: {str(value)[:60]}")
            except Exception as exc:
                print("查询失败:", exc)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())

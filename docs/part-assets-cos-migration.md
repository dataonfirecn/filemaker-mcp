# 零件附件拆表与 COS 迁移

## 范围

目标是把 `@零件` 的照片、图面、CAD、雷雕、印刷、包装和说明书容器迁移到
独立的 `PartAssets` 表，并把二进制文件保存到腾讯云 COS。

以下条码和标签生成字段继续保留在零件主表，本轮不迁移：

- `qrcode_image`
- `barcode_image`
- `發料收料標籤貼紙`
- `零件標籤貼紙`

旧字段在双读观察期结束前不会删除或清空。

## 2026-07-26 全量只读盘点

- 零件记录：45,103
- 缺少 `part_id`：0
- 非条码资产候选：51,164

| 旧字段 | 候选数 |
|---|---:|
| `影像 | 容器` | 27,207 |
| `影像 | 容器2` | 3,203 |
| `影像 | 容器3` | 99 |
| `影像 | 容器4` | 83 |
| `影像 | 容器5` | 7 |
| `零件照片3` | 624 |
| `零件照片4` | 49 |
| `圖面 | 容器` | 6,263 |
| `打樣圖面` | 4,234 |
| `打樣圖面 | 容器` | 7,153 |
| `外加工圖面` | 234 |
| `檔案2D` | 287 |
| `檔案3D` | 314 |
| 雷雕相关 | 1,287 |
| 印刷、包装、说明书及贴纸 | 120 |

`打樣2D | 容器` 当前没有候选记录，但字段仍纳入迁移契约。

## FileMaker 安装

2026-07-26 已完成以下安装并通过 Data API 回读：

- 新增 `PartAssets` 表，共 34 个字段。
- 新增同名 Data API 布局，34 个字段全部可访问。
- 新增 `零件_PartAssets` 表出现。
- 关系已核对为 `PartAssets::part_id_fk = 零件_PartAssets::part_id`。

如需在其他 FileMaker 文件重复安装：

1. 完整备份目标文件。
2. 在 FileMaker Pro 打开 `文件 > 管理 > 数据库`。
3. 切换到“表”。
4. 使用 MBS `Clipboard.SetFileMakerData` 或其 XML 剪贴板转换功能，把
   `filemaker-clipboard-xml/10-part-assets-table-with-fields.fmxmlsnippet.xml`
   写入 FileMaker 剪贴板。
5. 粘贴并确认生成 `PartAssets`，字段数为 34。
6. 建立 Data API 布局 `PartAssets`，布局上放置全部字段。
7. 建立关系：

   ```text
   零件::part_id = PartAssets::part_id_fk
   ```

8. 给后端 Data API 账号开放 `PartAssets` 的查看和新增/修改权限，但不要开放
   对 `@零件` 旧容器字段的删除权限。

安装后用以下命令验证：

```bash
PYTHONPATH=backend .venv/bin/python -c '
import asyncio
from app.core.config import get_settings
from app.services.filemaker_client import FileMakerClient

async def main():
    client = FileMakerClient(get_settings())
    try:
        fields = await client.get_layout_fields("PartAssets")
        print("PartAssets fields:", len(fields))
    finally:
        await client.close()

asyncio.run(main())
'
```

## 启用新上传

确认布局可通过 Data API 访问后配置：

```dotenv
FILEMAKER_PART_ASSETS_ENABLED=true
FILEMAKER_PART_ASSET_LAYOUT=PartAssets
```

重启后端。新建零件页面会自动从 Base64/FileMaker 容器上传切换为：

```text
浏览器压缩和 SHA-256
  → 后端签发短时 PUT URL
  → 浏览器直传 COS
  → 后端 HEAD 校验
  → 创建零件
  → 写入 PartAssets 并绑定 part_id
```

如果 `PartAssets` 绑定失败，零件记录保留并返回警告，不会删除业务主记录。

## COS 安全与浏览器 CORS

- bucket 保持私有，不给 `AllUsers` / `AuthenticatedUsers` 授权。
- 原始素材不返回永久公开 URL；订单页和客户页通过权限校验后签发短时 GET URL。
- 浏览器直传只允许精确来源，方法限 `GET`、`HEAD`、`PUT`，响应仅暴露
  `ETag` 和 `x-cos-request-id`。

2026-07-26 已为 `starrc-1252872963` 写入并回读验证
`starrc-part-assets-web` 规则。以下命令可以只读检查；加 `--apply` 才会改配置：

```bash
PYTHONPATH=backend .venv/bin/python \
  backend/scripts/configure_part_asset_cos_cors.py \
  --origin https://starrc.dataonfire.cn \
  --origin https://mayakofm.dataonfire.cn \
  --origin http://localhost:8080 \
  --origin http://localhost:5173 \
  --origin http://127.0.0.1:5173 \
  --origin http://localhost:3000
```

不要使用 `--origin '*'`。如果新增 Web 域名，应显式追加该 HTTPS origin 后再执行
`--apply`。

## 历史迁移

2026-07-26 全量迁移结果：

- 扫描零件：45,103
- 候选附件：51,164
- 已写入 `PartAssets` 和私有 COS：51,071
- 未迁移：93
- 成功率：99.82%
- 幂等复核：51,071 条全部跳过，新增复制为 0，93 个失败全部稳定复现

失败分类：

| 原因 | 数量 | 处理建议 |
|---|---:|---|
| FileMaker 历史容器 HTTP 401 | 77 | 在 FileMaker 中重新放入源文件后重跑 |
| 文件超过本轮 100 MB 安全上限 | 11 | 使用 COS 分块上传专项迁移 |
| 容器 URL 指向非 FileMaker 主机 | 4 | 人工核对外链并白名单或重新上传 |
| FileMaker 源文件 HTTP 404 | 1 | 恢复源文件或确认可废弃 |

逐项清单见 `docs/part-assets-migration-failures.json`。脚本使用流式下载，并优先
读取 `Content-Length`；超限文件会在读取正文前停止。

只读盘点：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_part_assets.py --limit 0
```

先迁移 3 条零件作为 canary：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_part_assets.py \
  --offset 1 --limit 3 --commit --verbose
```

核对 COS 和 `PartAssets` 后再扩大：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_part_assets.py \
  --limit 500 --commit

PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_part_assets.py \
  --limit 0 --concurrency 8 --commit \
  --failure-report docs/part-assets-migration-failures.json
```

迁移键格式为 `@零件:{recordId}:{legacyField}`。脚本重复执行会跳过已完成记录。
源布局始终只读；只有 COS 和 `PartAssets` 会发生写入。

迁移后验证 FileMaker 数量，并均匀抽样做 COS HEAD、短期签名 GET、文件大小和
SHA-256 校验：

```bash
PYTHONPATH=backend .venv/bin/python \
  backend/scripts/verify_part_assets.py --samples 12
```

2026-07-26 的 12 个均匀样本从首条覆盖到末条，全部验证通过。

## 双读与回滚

- `FILEMAKER_PART_ASSETS_ENABLED=false`：所有新上传和读取继续使用旧容器。
- 开启后：Web 图片读取优先使用 `PartAssets.object_key` 和 COS 短时签名 URL，
  找不到新资产或签名失败时回退 `影像 | 容器` / `圖面 | 容器`。
- 迁移、权限和前端验收完成前，不删除旧容器字段。

## 上线状态

- FileMaker 表、关系、Data API 布局和历史数据已就绪。
- COS CORS 已就绪，bucket 仍为私有。
- 本地 `.env` 已开启 `FILEMAKER_PART_ASSETS_ENABLED=true`。
- 本地 Docker 前后端已重新构建并通过健康检查；容器内已确认资产开关、布局和
  COS 配置生效。
- 公网生产实际位于服务器 `/opt/starrc-filemaker`，本次未把本地工作区冒充为
  公网部署。生产发布后应继续保留旧容器和双读回退，观察无误后再讨论字段删除。

# StarRC FileMaker Service

前后端分离的 FileMaker 集成服务：

- `frontend/`: React + Vite + Nginx，给 FileMaker WebViewer 使用
- `backend/`: FastAPI，接收 MES callback、调用 FileMaker Data API、生成二维码、记录 WebViewer 审计日志
- `postgres`: WebViewer 审计日志库，保存 `audit_log`
- `legacy/filemaker-mcp/`: 原 TypeScript MCP 项目，保留作为参考和工具

## 本地 Docker 部署

先按 `.env.example` 补好 `.env`，至少需要 FileMaker 连接信息。
默认 `FILEMAKER_READ_ONLY=true`，通用 FileMaker create/update/delete/script 接口保持锁定。内部订单合并和订单 BOM 计算单各自使用默认关闭的专用 Data API 写入通道；只有完成对应专用布局配置并显式启用 `FILEMAKER_WEB_MERGE_ENABLED` 或 `FILEMAKER_BOM_WRITE_ENABLED` 后，指定流程才允许写入。

```bash
docker compose up --build -d
```

访问：

- 前端：`http://localhost:8080`
- 后端健康检查：`http://localhost:8000/healthz`
- API 文档：`http://localhost:8000/docs`
- WebViewer 本地预览：`http://localhost:8080/?productSku=821RTR-27&operatorAccount=mock.operator&operatorName=本地测试操作员`

## StarRC 内部账号与 FileMaker 权限集

StarRC 内部工作台会从 FileMaker 签名上下文读取账号名和
`Get ( AccountPrivilegeSetName )`，并把实际权限集同步到 PostgreSQL。英文
`[Full Access]` 与中文 `[完全访问权限]` 都会映射为 StarRC 管理员。2026-07-24 已从
FileMaker 安全性同步 97 个账号和 39 个实际权限集；默认策略维护在
`backend/config/webviewer_privilege_sets.json`。管理员可在“系统管理 → 账号与权限”中：

- 启用或停用账号及整个 FileMaker 权限集。
- 按权限集设置默认权限，也可为单个账号覆盖。
- 单独控制价格、产品、订单、库存、BOM、智能问答、RAG 与订单合并。
- 可将单个账号设为“仅移动端登录”，后台会同时阻止该账号登录和访问 Web 管理页面。
- 预先绑定 FileMaker 账号；账号本身和密码仍需在 FileMaker“安全性”中建立和维护。

价格权限在后端强制执行。没有 `canViewPrice` 的会话询价会返回 HTTP 403，普通业务响应中的
售价、单价、订单金额、批次价格、成本、报价及相关原始字段会在发给浏览器前剔除。停用账号
或修改权限后，旧会话的下一次请求就会按新权限重新校验，不需要等待令牌过期。

远程账号配置也应标明与 FileMaker 对应的权限集：

```dotenv
WEBVIEWER_REMOTE_ACCOUNTS_JSON='[{"username":"amy","displayName":"Amy","privilegeSet":"Sales","passwordHash":"pbkdf2_sha256$..."}]'
```

移动端使用同一套远程账号登录：`POST /api/webviewer/session` 签发会话，
`GET /api/webviewer/session/me` 返回当前用户姓名、FileMaker 权限集和实时权限。
订单与移动到货接口都会在后端强制检查 `canViewOrders`；停用账号或调整权限后，
下一次请求立即生效。

### PDA 成品入库与追溯

PDA 扫描的是出货单，但提交的是已经包好的 SKU 成品入库，不会自动修改客户订单数量。
每个 SKU 独立入库一次；欠料的 SKU 保持未入库，包好后可再次扫描同一张出货单处理。
未达到订单数量的部分按原链路写入：

`出貨單資料.ID` → `出貨單資料入庫.ID_出庫單資料` →
`產品庫存.ID_出貨單資料入庫`，同时在 `產品庫存.ID_出貨單資料`
保留来源明细 ID。这样可以按零件包回查入库数量、时间和操作人。

已经完全入库、或本次数量超过订单剩余数量时，超出部分自动改写到
`入庫單` → `入庫單資料` → `產品庫存`，不写入 `出貨單資料入庫`，也不增加
`出貨單資料.實際包裝數量`。同一次提交的多个追加产品共用一张 `入庫單`；提交同时
含有正常数量和追加数量时会自动拆分。追加入库必须有 `canAddCompletedReceipts`
权限并填写原因，服务端会强制复核这两个条件。

生产环境只启用 `FILEMAKER_MOBILE_RECEIPT_WRITE_ENABLED` 这条专用写入通道；
通用 `FILEMAKER_READ_ONLY=true` 保持不变。每个 SKU 最多 6 张收货图片，
整张记录最多 1 张出货照片，图片直接上传腾讯 COS。

### PDA 产品资料与照片

`GET /api/orders/products/{sku}/detail` 会从 FileMaker
`產品 資料_包裝` 读取只读 BOM、包装资料及基础信息，产品图、包装参考图与 BOM
零件图只返回腾讯 COS 的短时签名链接，不下载或代理 FileMaker 容器。

产品图片字段的分类为：

- `檔案 1 | 容器` 至 `檔案 10 | 容器`：SKU 产品照片。
- `檔案 11 | 容器` 至 `檔案 15 | 容器`：包装参考照片。
- 出货照片属于整张到货记录，选填且最多一张，不写入上述产品字段。

只有产品照片完全为空时，PDA 才能调用
`POST /api/mobile/v1/products/{sku}/photos/presign` 现场补拍。每个补图会话最多
6 张，客户端先直传 COS；完成接口随后异步写入 `ProductAssets.asset_file` 与
原产品容器。上传状态保存在 SQLite；服务重启后，客户端下一次状态轮询会自动续跑
未完成的 FileMaker 同步。

历史容器迁移分两步执行，两个脚本都默认只做 dry-run：

```bash
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_product_assets.py --limit 50
PYTHONPATH=backend .venv/bin/python backend/scripts/migrate_product_assets_to_cos.py --limit 100
```

确认 dry-run 数量后分别加 `--commit` 才会写入 `ProductAssets` 或 COS。

## RAG 索引范围与关系语义

RAG 采用轻量缓存 + OData 实时回源。默认记录缓存只包含 `@products` 和 `@零件`；BOM、零件关联产品及其他 `@` 布局不缓存原始记录，但其主外键关系继续保存在 `backend/config/semantic_mapping.json` 中：

| 实体布局 | 主键 | 外键 |
|---|---|---|
| `@products` | `product_sku` + `系統產品編號` | — |
| `@product_bom` | `ID` | `ID_產品編號` → 产品；`零件編號` → 零件 |
| `@零件` | `part_number`（`零件ID` 为备用键） | — |
| `@零件關聯產品` | `ID` | `ID_零件` → 零件；`ID_产品` → 产品 |

产品记录只缓存产品编号和中英文名称；零件记录只缓存编号、名称、别名及备注。库存、价格、状态和 BOM 明细均不作为权威缓存：自然语言查询识别出精确产品号或零件号后优先通过 OData 读取最新数据，OData 不可用时自动回退 FileMaker Data API。RAG 只负责字段语义、关系上下文和候选召回。

每次完整刷新成功后，会自动移除不在当前缓存范围内的旧 profile、记录块和 FTS 数据。默认关闭“服务启动即刷新”，worker 按每日计划刷新，也可在 RAG 控制页手动触发。`NATURAL_QUERY_USE_CACHED_RECORDS=false` 保证本地记录不会被直接当作权威查询结果。

## MES Callback

```bash
curl -X POST http://localhost:8000/api/mes/callback \
  -H "Content-Type: application/json" \
  -H "x-api-key: $MES_CALLBACK_API_KEY" \
  -d '{"eventId":"demo-001","status":"finished"}'
```

callback 会先写入 `backend/data/app.db`，再由后台 worker 调用 FileMaker。默认会调用：

```text
layout: MES_FILEMAKER_LAYOUT
script: MES_FILEMAKER_SCRIPT_NAME
```

也可以在 callback payload 中显式指定 FileMaker 操作：

```json
{
  "eventId": "demo-002",
  "filemaker": {
    "operation": "run_script",
    "layout": "MES_API",
    "scriptName": "MES_UpdateWorkOrder",
    "scriptParam": {
      "workOrderNo": "WO-001",
      "status": "finished"
    }
  }
}
```

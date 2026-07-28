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
- 外部客户查询：`http://localhost:8080/customer-chat`

## StarRC 内部账号与 FileMaker 权限集

StarRC 内部工作台会从 FileMaker 签名上下文读取账号名和
`Get ( AccountPrivilegeSetName )`，并把实际权限集同步到 PostgreSQL。英文
`[Full Access]` 与中文 `[完全访问权限]` 都会映射为 StarRC 管理员。2026-07-24 已从
FileMaker 安全性同步 97 个账号和 39 个实际权限集；默认策略维护在
`backend/config/webviewer_privilege_sets.json`。管理员可在“系统管理 → 账号与权限”中：

- 启用或停用账号及整个 FileMaker 权限集。
- 按权限集设置默认权限，也可为单个账号覆盖。
- 单独控制价格、产品、订单、库存、BOM、智能问答、RAG 与订单合并。
- 预先绑定 FileMaker 账号；账号本身和密码仍需在 FileMaker“安全性”中建立和维护。

价格权限在后端强制执行。没有 `canViewPrice` 的会话询价会返回 HTTP 403，普通业务响应中的
售价、单价、订单金额、批次价格、成本、报价及相关原始字段会在发给浏览器前剔除。停用账号
或修改权限后，旧会话的下一次请求就会按新权限重新校验，不需要等待令牌过期。

远程账号配置也应标明与 FileMaker 对应的权限集：

```dotenv
WEBVIEWER_REMOTE_ACCOUNTS_JSON='[{"username":"amy","displayName":"Amy","privilegeSet":"Sales","passwordHash":"pbkdf2_sha256$..."}]'
```

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

## 外部客户查询账号

外部客户页使用独立登录令牌，并按账号绑定的 FileMaker `Client` 值强制限制查询范围。启用前先生成密码哈希：

```bash
cd backend
python -m scripts.hash_customer_password
```

然后在 `.env` 配置：

```dotenv
CUSTOMER_CHAT_ENABLED=true
CUSTOMER_CHAT_TOKEN_SECRET=<使用 openssl rand -hex 32 生成>
CUSTOMER_CHAT_ACCOUNTS_JSON='[{"username":"acme","displayName":"ACME 客户","clientName":"ACME","productPrivilege":"0780","partCustomerId":"CU638","accessRole":"team","canViewPrice":false,"passwordHash":"pbkdf2_sha256$..."}]'
```

`clientName` 必须与 FileMaker 产品资料里的 `Client` 值精确一致。客户入口直接读取 FileMaker，
并按账号配置限制客户、产品、零件和出货单范围；不使用 RAG 记录缓存。`accessRole`
固定为 `admin`、`manager`、`team` 或 `agent`：Admin 可访问全部内容与账号管理；
管理者和团队可访问订单，代理商只保留产品和零件库存查询。价格可见性由独立的
`canViewPrice` 开关控制，不再与 4 种权限集绑定。关闭时不返回单价、订单金额或运费金额；
成本、报价、供应商及其他内部财务字段对所有外部账号保持关闭。
Admin 可以访问 `/customer-chat/admin/analytics`，查看保存在 PostgreSQL 中的聊天历史
和问题汇总；回归测试流量默认不会计入运营分析。
管理员还可以访问 `/customer-chat/admin/accounts`，在 PostgreSQL 中实时启用或停用账号、
调整 4 种权限集及独立价格权限，并查看每个账号的最近成功登录、最近登录尝试和成功/失败次数。
停用账号、改变权限集或价格权限会立即使该账号已有会话失效；环境文件中的账号列表只作为初始账号来源。
当前 MayakoFM 部署把客户、产品、零件与出货公司数据范围固定在后端，账号管理页不开放
这些技术范围字段；未来扩展多客户时再恢复可配置范围。

登录后的用户可在 `/customer-chat/settings/password` 自助修改密码（旧的
`/customer-chat/account/password` 地址仍兼容）。当前密码必须正确，
两次新密码必须一致且至少 12 位。自助修改后的哈希保存在 `DATABASE_PATH` 指向的
SQLite 数据库中，并优先于环境文件内的初始哈希；密码修改会立即使旧会话失效。

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

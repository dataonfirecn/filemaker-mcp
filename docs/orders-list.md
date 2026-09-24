# Web 订单列表与订单详情

入口：浏览器工作台 → 订单管理 → 订单。列表 `/?page=orders`，详情 `/?page=orderDetail&orderId=<出貨單 id>`。交互与需求单一致：列表（搜索 + AG Grid + 分页）→ 点订单号或双击行进入明细 → 左上角返回列表。浏览器返回、刷新、详情直达均可使用。

## 为什么改

原来导航「订单详情」直接进单个订单页，而该页只认地址里的 `orderId`（或 FileMaker 签名上下文里的订单 ID）。从导航进入时两者都没有，页面只能报「URL 缺少出貨單 ID」；列表里的 `internal_id`（`NB…`）也不是详情用的 `出貨單.id`（`PI…`），两边没有配对。现在列表每行都带出貨單 `id`，点进去直接用它读取。

## 接口

- `GET /api/orders?q=&page=&page_size=`（`canViewOrders`；`page_size` 默认 25，上限 100）。
- 列表主体读 `訂單 清單_業務`（客户、概要、包装状态、金额），按订单日期倒序（该布局没有「日期」字段时自动退回内部单号倒序）；再用内部单号从 `@出貨單` 补 `id`、PI、客户 PO，从 `訂單 清單` 补日期与付款状态。
- 搜索：内部单号、概要、客户名称，以及 `@出貨單` 的 `id` / `出貨單 PI` / `訂單 PO`（命中的订单按内部单号补进结果）。用户输入整体加引号，FileMaker 查找运算符不改变语义。
- 带客户名称的会话（客户专属 WebViewer）只返回该客户订单；金额仅 `canViewPrice` 可见。
- 找不到对应出貨單的记录仍会列出，但 `orderId` 为空，前端不提供进入明细的入口。

## 前端

- 新增 `OrderListPage`；`DataGrid` 从需求单页抽成共享组件（列宽、顺序、显示列各表独立记忆）。
- 默认只显示常用列，PI 编号、客户订单号、分类、已过天数在「调整字段」里打开。
- 详情页从列表进入时显示侧栏和「返回订单列表」；FileMaker 带签名上下文直达时仍是无侧栏独立页。没有 `orderId` 的旧链接（`/?page=orderDetail`）自动回到订单列表。

## 验证

```sh
PYTHONPATH=backend python -m pytest backend/tests/test_orders_list_api.py backend/tests/test_internal_orders_api.py -q
cd frontend && npx tsc --noEmit && npm run build
```

浏览器行为（列表 → 明细 → 返回 → 前进后退 → 刷新、搜索空结果与错误、旧链接回退，1440 / 1068 / 390 × 亮暗）已用回放接口数据验证；未连接真实 FileMaker，上线后需用真实数据确认「日期」排序与搜索命中。

## 标准镜像发布（2026-09-24，`062cb01`）

前后端同时发布（提交 `062cb01`，26 个文件）。增量镜像，继承运行中的镜像：

- `starrc-backend:20260924-062cb01`（继承 `starrc-backend:20260923-f8e6fc1`，覆盖 `backend/app`、`config`、`scripts`）
- `starrc-frontend:20260924-062cb01`（继承 `starrc-frontend:20260924-0eaa74d`，覆盖 `dist/`）

发布前复核：后端 `PYTHONPATH=backend python -m pytest backend/tests -q`（仓库根目录运行）389 项通过 / 54 项跳过、0 失败；前端 tsc + vite 构建通过；新增 CSS 仅使用 `var(--*)` token，无 hex / `!important`，字号 ≥12px，字重 400/500/600，符合 `docs/ui-design-rules.md`（`IconButton` 先在规则文档补写、再落 ui 组件库）。

容器变化：backend `5dc3b3d24e16` → `e72b9a0c09e8`；frontend `bf07a84053cf` → `51334793a0c2`；postgres `f196c32c514b` 保持不变。

发布后验证：内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。公网 `index.html` SHA-256 `769ff738ed925b4a4ef158e90132813a5c99be8ac8c3e8857f63a7da2a4fbcd0`、`assets/index-Bs7XgHtw.js` SHA-256 `bad2772ba4320edc725a7f7bd2635a689858a7e9d5cc9f3a37008e503a924568`、`assets/App-QI2WeZw2.js` SHA-256 `91104e86b3ec49edb278b86a8d67a3f8ee1ff0d31ba1c74128abdd229428c381`，均与本地构建逐字节一致。

服务器发布目录：`/opt/starrc-filemaker/releases/20260924-062cb01/`（`backup/previous-release.yml`、`backup/.env.bak`、`backup/previous-src.tar.gz`（当前运行的 backend 源码 `f8e6fc1` + frontend `dist` `0eaa74d` + 两个 Dockerfile）、`build/`（`backend/` + `dist` + `pm-src-062cb01.tar.gz` + 两个 Dockerfile）、`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`）。

插曲：首次部署时 SSH 会话在 `compose up` 中途超时，frontend 容器停在「Created」未启动；重跑同一条 `up -d`（幂等）后恢复，无数据影响。发布脚本要么保证单条 SSH 命令够短，要么后台运行 + 读日志（playbook 第 4 步已注明）。

回退：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-062cb01/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
```

# 订单列表 / 需求单排序方向发布（2026-09-24，`8d52067`）

## 范围

前端 + 后端。订单列表（`GET /api/orders` + `OrderListPage`）与需求单列表
（`GET /api/demand-orders` + `DemandOrdersPage`）新增 `sort=newest|oldest`
参数，默认 `newest`（最近优先，与既有行为一致）；「最早优先」把日期与单号
排序键整体反向。前端工具栏各加一个排序方向切换按钮（`ArrowDownWideNarrow` /
`ArrowUpNarrowWide`），列表头部文案随方向变化。

- 后端：`backend/app/api/orders.py`（`_order_list_sorts(sort)` 替代固定
  `ORDER_LIST_SORTS`）、`backend/app/api/demand_orders.py`（`sort` 参数 +
  动态 `order`）。
- 前端：`frontend/src/components/OrderListPage.tsx`、
  `frontend/src/components/DemandOrdersPage.tsx`。
- 测试：`backend/tests/test_orders_list_api.py`、
  `backend/tests/test_demand_orders.py` 各补排序方向用例。

## 镜像

- `starrc-backend:20260924-8d52067`（继承 `20260924-dms-web-catalog-v2`）
- `starrc-frontend:20260924-8d52067`（继承 `20260924-434aedd`）

## 容器 ID

| 容器 | 部署前 | 部署后 |
|---|---|---|
| starrc-backend | `8fb64e9e6055` | `f2204f074202` |
| starrc-frontend | `9c981a46c95c` | `c23249658c38` |
| starrc-postgres | `f196c32c514b` | `f196c32c514b`（未重建） |

## 验证

- 后端测试：392 过 / 55 跳过（仓库根目录运行）。
- 前端：tsc + vite 构建通过。
- 健康检查：内网 `http://127.0.0.1:18001/healthz` 与公网
  `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- SHA-256 一致性（本地 `frontend/dist` vs 线上）：
  - `index.html`：`c397dc35a0def63a8f5a0d8e4ae19ab0964cd769777424387576cc46048b8b49`
  - `assets/index-CFZGvgGj.js`：`87f34341004bec0bc16cf65d3b710b41c508326e6ef49ead47d501f549ffc0b2`
  - `assets/App-fJO_AOjf.js`：`bfe9cee62e97d5d7d6591263d24b3cb5711073a564c7cab03365091779daf5cb`

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-8d52067/`（`release.yml`、
`containers-before.txt`、`containers.txt`、`health.json`、
`backup/previous-release.yml`、`backup/.env.bak`、
`backup/previous-src-backend.tar.gz`、`backup/previous-src-frontend.tar.gz`）。

## 回滚

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-8d52067/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚目标镜像：`starrc-backend:20260924-dms-web-catalog-v2`、
`starrc-frontend:20260924-434aedd`。

# 需求单零件名称回填 + 列表刷新按钮发布（2026-09-24，`2b96da6`）

## 范围

前端 + 后端。

- **后端**（`backend/app/api/demand_orders.py`）：需求单明细行自身没有零件名称时，
  按零件编号到零件资料（OData `零件` 表）批量补「内部名称」（`_fill_part_names`，
  每批 10 条并发查询，只补空值，查询失败不影响需求单本身）。
- **前端**：
  - `DataGrid` 新增 `onRefresh` 属性，在「导出 CSV」旁显示刷新按钮（`IconButton`）。
  - `DemandOrdersPage`：列表页默认排序改为「最早优先」（`oldest`）；列表页工具栏
    移除（刷新按钮移入表格工具条）；明细页保留返回/刷新工具栏。
  - `OrderListPage`：刷新按钮同样移入表格工具条，移除独立工具栏。
  - 样式：`DemandOrdersPage.css`、`OrderListPage.css`、`styles.css` 配套调整。
- **测试**：`backend/tests/test_demand_orders.py` 补零件名称回填用例。

## 镜像

- `starrc-backend:20260924-2b96da6`（继承 `20260924-8d52067`）
- `starrc-frontend:20260924-2b96da6`（继承 `20260924-8d52067`）

## 容器 ID

| 容器 | 部署前 | 部署后 |
|---|---|---|
| starrc-backend | `f2204f074202` | `d80703e643d6` |
| starrc-frontend | `c23249658c38` | `8d598bb559a4` |
| starrc-postgres | `f196c32c514b` | `f196c32c514b`（未重建） |

## 验证

- 后端测试：394 过 / 55 跳过（仓库根目录运行）。
- 前端：tsc + vite 构建通过。
- 健康检查：内网 `http://127.0.0.1:18001/healthz` 与公网
  `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- SHA-256 一致性（本地 `frontend/dist` vs 线上）：
  - `index.html`：`bfc89ab068b7745aafcfe5c6f8fac43ff7359b55fae72c62c8181f03951db4ac`
  - `assets/index-BOYrUnIV.js`：`588e86c25b42af564da5b8733d8b01ff638ebacdaa9d202a3f0362608b576b80`
  - `assets/App-C3GUgVQG.js`：`2ee4c323965655efcd2a475bec875676e0bb616be4bebd5d6d659e8c93c92946`

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-2b96da6/`（`release.yml`、
`containers-before.txt`、`containers.txt`、`health.json`、
`backup/previous-release.yml`、`backup/.env.bak`、
`backup/previous-src-backend.tar.gz`、`backup/previous-src-frontend.tar.gz`）。

## 回滚

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-2b96da6/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚目标镜像：`starrc-backend:20260924-8d52067`、
`starrc-frontend:20260924-8d52067`。

# 产品审核锁定 + 简繁切换 发布记录（2026-09-24，`4b66594`）

## 范围

前端 + 后端都改，两个服务都重建。

- **产品审核锁定**：新增 `canApproveProducts` 权限（账号管理页可勾选）；
  `POST /api/product-master/products/{id}/review` 审核/撤销审核接口；已审核产品
  整体锁定（保存、附件上传、客户群报价写入均返回 423），撤销审核后才能再编辑；
  新建产品服务端默认 `審核=未審核`；恢复历史版本时跳过无写权限的字段；
  409 冲突响应改用 `jsonable_encoder` 修复 UUID/datetime 序列化。
- **退役字段下线**：`報價紀錄`、`應課稅`、`關聯編號_Price` 从
  `product_master_schema.json` / `product_master_web_schema.json` /
  `product_master_base_fields.json` 及前端布局中移除；
  `backend/scripts/product_master_drop_fields.py` 用于清理生产
  `pm_product.fields` 里的残留值（默认 dry-run）。**本次只部署脚本，未执行
  `--apply`**（用户确认）；生产数据里的旧值保留，不影响功能，之后需要时再手动清理。
- **简繁切换**：`frontend/src/i18n/`（opencc-js，只转换界面字面量、不转换数据）+
  vite 插件 `vite-plugins/uiStrings.ts` 收集 UI 字符串；切换入口在顶栏用户菜单、
  远程登录页和三个 WebViewer 应用头部；`docs/ui-design-rules.md` 第 6 节补充简繁规则。

## 镜像

- `starrc-backend:20260924-4b66594`（继承 `20260924-1886287`）
- `starrc-frontend:20260924-4b66594`（继承 `20260924-1886287`）

## 容器 ID 变化

| 容器 | 部署前 | 部署后 |
|---|---|---|
| starrc-backend | `a9aec721838c` | `e9a5288cc73b`（重建） |
| starrc-frontend | `991dcc069f6d` | `8d04a2f896b9`（重建） |
| starrc-postgres | `f196c32c514b` | `f196c32c514b`（不变） |

## 验证

- 后端：`pytest backend/tests -q` → 396 passed, 58 skipped（仓库根目录运行）。
- 前端：`npm --prefix frontend run build`（tsc + vite）通过。
- 健康检查：内网 `http://127.0.0.1:18001/healthz` 与公网
  `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- 前端一致性：`index.html` SHA-256 `64323a6f…f00cbc`、入口
  `assets/index-ow8XptL9.js` SHA-256 `960f626c…c1f75`，本地构建与线上逐字节一致。

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-4b66594/`
（`backup/previous-release.yml`、`backup/.env.bak`、`backup/previous-src.tar.gz`、
`build/`、`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`、
`build-backend.log`、`build-frontend.log`）

## 回滚

```bash
ssh root@101.35.198.171 bash -s <<'EOF'
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-4b66594/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend frontend
docker ps --format '{{.Names}} {{.ID}} {{.Image}}' | grep '^starrc-'
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
EOF
```

回滚镜像 tag：`starrc-backend:20260924-1886287` / `starrc-frontend:20260924-1886287`。

## 后续待办

- 需要清理生产数据里退役字段残留值时：暂停产品写入后在服务器运行
  `python -m app.scripts.product_master_drop_fields --apply`（先不带 `--apply`
  dry-run 看行数）。

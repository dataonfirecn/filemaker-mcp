# 列表分页标准组件发布（2026-09-24，`fc12b6f`）

## 范围

仅前端改动（提交 `fc12b6f`，5 个文件）：

- `components/ui/` 新增共享 `Pagination`（卡片底部分页：「第 x–y 条，共 N 条」/ 每页下拉 / 首页、上一页、页码跳转、下一页、末页）与 `usePageSize`（每页条数存 localStorage，只接受 options 内的值）；样式独立成 `pagination.css`，与「产品资料」页底部分页同一结构与尺寸（30px 按钮、12px 字、通栏分割线）。
- 订单列表（`OrderListPage`）与需求单列表（`DemandOrdersPage`）换用共享组件，新增每页 25 / 50 / 100 下拉（分别记在 `orders:page-size` / `demand-orders:page-size`）；需求单详情的零件明细分页固定 25 条/页、无每页下拉。
- 后端 `/api/orders`、`/api/demand-orders`（列表与明细）本已支持 `page_size`（1–100），无接口改动。

## 镜像

- `starrc-frontend:20260924-fc12b6f`（增量继承 `starrc-frontend:20260924-a762d14`，只 `COPY dist`）
- backend 仍为 `starrc-backend:20260924-062cb01`，postgres 不变。

## 容器变化

- frontend `e018eb9599c3` → `1cd629fc5a3c`
- backend `e72b9a0c09e8` 保持不变
- postgres `f196c32c514b` 保持不变

## 验证

- 发布前审查：分页改动仅 `frontend/`；新增 CSS 只用 `var(--*)` token，无 hex / `rgba` 字面值、无 `!important`，字号 ≥12px，字重 400/500/600，符合 `docs/ui-design-rules.md`（自检 grep 全空）。
- `tsc + vite` 生产构建通过（在 `fc12b6f` 的干净 worktree 中构建，原因见「过程注记」）。
- 内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。
- 公网 `index.html` SHA-256 `1f090b68129b4e2ff40afa79ba822c292243791de0788f99d36b8867d0b4f84d`、`assets/index-BsuHQNfb.js` SHA-256 `898d5d49a0c30822eb3df6463dda9b7ea5e7d968be1eb0cc984634c72e44f533`、`assets/App-B_Sso93m.js` SHA-256 `2123f6a66156f0e7c25b4cebb7b981be6d7b1843971af0f1462307cda2d283b6`，均与本地构建逐字节一致。

## 服务器审计目录

`/opt/starrc-filemaker/releases/20260924-fc12b6f/`（`backup/previous-release.yml`、`backup/.env.bak`、`backup/previous-src.tar.gz`（上一发布 `20260924-a762d14` 的 build 快照）、`build/`（`fc12b6f` 干净源码 + `dist` + `pm-src-fc12b6f.tar.gz` + `Dockerfile.frontend`）、`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`）。

## 回滚

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-fc12b6f/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps frontend
```

回到 `starrc-frontend:20260924-a762d14`。

## 过程注记

发布时主工作区混着另一会话**正在进行中**的另一批改动（产品目录发布：`product_master.py`、`product_catalog_contract.py`、`product_catalog_publication.py`；Dashboard 趋势图 / 用户菜单 / styles.css），且该会话在持续写入、测试未跑完。为避免把未完成改动带上生产：

- 提交用 pathspec 限定只含分页相关 5 个文件，其余文件一律未提交；
- `dist` 在 `fc12b6f` 的临时 `git worktree` 中构建（node_modules 软链主仓库），上传的 tar 也全部取自 worktree，主工作区全程未动；
- 审计目录里的 backend 源码快照取自 worktree（与运行中的 backend 镜像一致），而非含未提交改动的主工作区。

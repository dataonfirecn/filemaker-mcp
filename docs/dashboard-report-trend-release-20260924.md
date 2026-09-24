# 导航首页趋势图 + 设计 token 清理（2026-09-24）

## 改动内容

- 导航首页（Dashboard）「最近运行」由手写完整度柱改为 `ReportTrendChart`（recharts 堆叠柱状图：
  正常 / 需关注 / 失败三天数，悬停查看当日明细与数据完整度，`aria-label` + 视觉隐藏数据表
  供屏幕阅读器读取同一份数据）。recharts 为既有依赖（`^3.9.2`，`ProductInventoryPage` 已在用）。
- 移除首页底部「浏览器登录工作台」导航块（其入口已收录进管理员的应用与接口目录）。
- 顶栏用户菜单去掉下拉箭头图标；触发器改为透明底 + 圆角 hover 样式，补 `focus-visible` 焦点环。
- `styles.css` 侧栏 / 首页按钮 / 用户菜单的旧变量名（`--teal-*`、`--ink`、`--muted`、`--line`、
  `--surface` 等）迁移到设计 token（`--color-*`、`--space-*`、`--radius-*`、`--weight-*`）；
  页面级样式拆到独立的 `DashboardPage.css`（仅用 `var(--*)`，无 hex / `!important`）。

## 标准镜像发布（2026-09-24，`cf8034c`）

仅前端发布（提交 `cf8034c`，6 个文件），`backend` / `postgres` 未重建。增量镜像，继承运行中的镜像：

- `starrc-frontend:20260924-cf8034c`（继承 `starrc-frontend:20260924-fc12b6f`，覆盖 `dist/`）
- backend 继续运行 `starrc-backend:20260924-dms-web-catalog-v2`（未改动）

发布前复核：前端 tsc + vite 构建通过；无 backend 改动，按 playbook 跳过 pytest；新增 / 改动 CSS
仅使用 `var(--*)` token，无 hex / `!important`，字号 ≥12px，字重 400/500/600，符合
`docs/ui-design-rules.md`。

容器变化：frontend `1cd629fc5a3c` → `93efe14a387a`；backend `8fb64e9e6055` 保持不变；
postgres `f196c32c514b` 保持不变。

发布后验证：内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz`
均 `ok: true`。公网 `index.html` SHA-256 `b1e73b634760645940912936f53e28d7583f6d9117e7a4a5dee33ac64f20c357`、
`assets/index-Ckd8nT4U.js` SHA-256 `0fd985c37321d83b9ea3783e85549c027c38ee95db0495f16664ad3fccd78434`、
`assets/App-Dlv2AMHp.js` SHA-256 `2a70c08bf08bada2aabc0f7c0a315accea2e45457c3f0a17193c5933828cf44a`，
均与本地构建逐字节一致。

服务器发布目录：`/opt/starrc-filemaker/releases/20260924-cf8034c/`（`backup/previous-release.yml`、
`backup/.env.bak`、`backup/previous-src-backend.tar.gz`（当前运行后端源码，取自
`20260924-dms-web-catalog`）、`backup/previous-src-frontend.tar.gz`（当前运行前端 `dist`，取自
`20260924-fc12b6f`）、`build/`（`dist` + `pm-src-cf8034c.tar.gz` + `Dockerfile.frontend`）、
`release.yml`、`containers-before.txt`、`containers.txt`、`health.json`）。

回退（本次仅重建 frontend）：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-cf8034c/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps frontend
```

# 设计 token 迁移发布（2026-09-23）

生产入口：https://starrc.dataonfire.cn

## 改动

本次仅发布前端，共 5 个提交：

- `b3d219a` remote-login 页面迁移到新设计 token
- `48369ad` 减少 remote-login 页面强调色重复
- `895a563` 剩余旧版硬编码颜色迁移到 token
- `17385da` 侧边栏导航不再整体套用强调色（图标/文字恢复默认色）
- `792c39e` AG Grid quartz 主题迁移到 `--color-*` token：表头、行、悬停、选中、分页、可编辑单元格全部改用 token；删除 `[data-theme="dark"]` 下的 AG Grid 覆盖块（暗色由 token 双主题值直接生效）

## 发布与回退

仅发布前端镜像 `starrc-frontend:20260923-792c39e`，继承运行中的 `starrc-frontend:20260923-2d13b34` 以保留 Nginx 配置与旧版本静态资源（`COPY dist/` 合并进 `/usr/share/nginx/html/`）。后端保持 `starrc-backend:20260923-2d13b34` 不变。

服务器发布目录：`/opt/starrc-filemaker/releases/20260923-792c39e`。`backup/previous-release.yml` 为发布前覆盖配置，`backup/previous-src.tar.gz` 为上一版本（git `2d13b34`）源码快照；构建上下文在 `build/`（`Dockerfile.frontend` + `frontend/dist`）。`release.yml` 为发布后的覆盖配置，`containers.txt` 记录发布前容器 ID，`health.json` 为公网健康检查响应。

继续使用 `/opt/starrc-filemaker/current/deploy/starrc/docker-compose.yml` 与 `product-master.release.yml`，只替换覆盖文件中的 frontend 镜像，并使用 `up -d --no-deps --no-build frontend`。发布前后 backend（`a390b2584f0d`）与 postgres（`f196c32c514b`）容器 ID 一致；frontend 由 `a27b39a177dc` 重建为 `b0e7929362d7`。

回退时将 `backup/previous-release.yml` 恢复为 `current/deploy/starrc/product-master.release.yml`，只重新创建 frontend：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260923-792c39e/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps --no-build frontend
```

## 验证

- `npm --prefix frontend run build`（tsc + vite）通过。
- 11 个 `--color-*` token（surface / text / text-secondary / text-muted / border / divider / surface-muted / surface-hover / primary / primary-soft / warning-soft）在 `frontend/src/styles/tokens.css` 中亮、暗双主题均有定义。
- 内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz` 均返回 `ok: true`。
- 公网 `index.html` 与本地构建逐字节一致（SHA-256 `4371b2eae7a5b9aff253593ad84520b5ea5dd44f7f7b951a5f8195cde93a9774`）。
- 公网 `assets/App-a4pPr5KZ.js` 与本地构建 SHA-256 一致：`43d2a8ee93106af9643624d0491d483c2bd7999dd581c56e6eedc75242c128f2`。
- 匿名 Playwright 检查（1440 / 1068 / 390px）：页面 200、无 JS 异常，仅预期的匿名 401（`/api/reports/dashboard`）与 400（`/api/webviewer/session`）；截图与汇总在 `artifacts/production-check-20260923-792c39e/`。
- 登录后的 AG Grid 表格页面需凭据验证，token 定义与构建产物一致性已覆盖本次改动范围。

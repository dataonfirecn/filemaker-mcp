# 产品浏览页发布（2026-09-22）

产品资料详情入口 businessProductDetail 复用 ProductMasterPage 的只读模式，按产品 UUID 加载资料。保留基础资料、产品照片、规格书、生产注意事项、预览与下载；不提供字段编辑、客户选择、SKU 复制、保存、上传、替换和移除。原 FileMaker 编辑入口保持原模式。

前端已发布：starrc-frontend:product-browser-20260922。仅重建前端，后端和写入开关保持原配置。旧镜像为 starrc-frontend:20260922-6f97ea2；服务器回退配置在 /opt/starrc-filemaker/releases/product-browser-20260922/previous-release.yml。

验证：TypeScript/Vite 构建通过。执行 `node frontend/scripts/check-product-browser.cjs`，覆盖 4 个页签 × 2 种 previewMode，在提供编辑权限、全字段与附件、展开全部折叠区情况下，8 项渲染检查均通过，无 input/textarea/select 或写入操作按钮。该测试使用合成数据，不提交产品修改。生产 JS SHA-256 与本地构建一致，公网页面和健康接口正常。

浏览器交互验收未完成：Chrome 自动化多次返回用户正在操作应用，未能切换至产品页，未将其报告为实际点击/键盘测试通过。

## 只读版式与照片画廊改进（2026-09-24，`c4245f6`）

只读产品资料的版式改为容器查询驱动，并对照片画廊做只读优化（提交 `c4245f6`，2 个文件）：

- `.pm-card` / `.pm-band` 设为 `inline-size` 容器；「报价信息 · 库存信息」分栏按卡片自身宽度（≤860px）堆叠，不再依赖视口断点，侧边栏与模块导航收起时列数自动正确。
- 字段网格统一为 `auto-fill minmax(176px, 1fr)`：同宽网格列宽一致，跨行、跨区段字段自动对齐，删除各视口断点的 span 表（review 固定末两列、notes 整行、≥720px 容器内占两列）。
- 标签/值层级：标签 12px/400 弱色、单行省略并带 title；值 14px/500 主色并加发丝下划线；紧凑值等宽表格数字。
- 只读照片画廊：只显示已填充位置，卡头改为「N 张图片」计数（替代进度条）；产品无照片时显示「暂无产品照片。」空状态，侧栏「產品照片」页签禁用并带 tooltip 提示。
- 禁用页签样式：透明度 0.45、`not-allowed`、无 hover 效果。

## 标准镜像发布（2026-09-24，`c4245f6`）

仅发布前端镜像 `starrc-frontend:20260924-c4245f6`，继承运行中的 `starrc-frontend:20260923-f8e6fc1`（`COPY dist/` 合并进 `/usr/share/nginx/html/`，保留 Nginx 配置与旧版本静态资源）。后端保持 `starrc-backend:20260923-f8e6fc1` 不变。

发布前复核：`npm --prefix frontend run build`（tsc + vite）通过；新增 CSS 仅使用 `var(--pm-*)` token，无 hex / `!important` / 新增变量，字号 ≥12px，字重 400/500/600，符合 `docs/ui-design-rules.md`。

容器变化：frontend `c25af749f001` → `c6c2b478df38`；backend（`5dc3b3d24e16`）与 postgres（`f196c32c514b`）保持不变。

发布后验证：内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。公网 `index.html` 与本地构建逐字节一致（SHA-256 `ff612d98195e9eaf9640de91ec260ef4891998bc08fff9a46455729171dc3219`）；入口 `assets/index-SA3mCo2L.js` SHA-256 `4df52efdde13ed97b698f181e13f5f3eb8add3f614f3892315a0995570c1a7b8`、`assets/App-gTLpnyMJ.js` SHA-256 `4ad0621ff10ad636c7a639d3d86e1713e2bf9a42bcf10e52b1bc261d45d4ed0a`，均与本地构建一致。

服务器发布目录：`/opt/starrc-filemaker/releases/20260924-c4245f6/`（`backup/previous-release.yml`、`backup/previous-src.tar.gz`（git `f8e6fc1` 前端源码 + 上一版本已部署 `dist/`）、`build/`（`Dockerfile.frontend` + `dist`）、`release.yml`、`containers.txt`、`health.json`）。

回退：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-c4245f6/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps --no-build frontend
```

## 网格、成本问题与计量行改进（2026-09-24，`0eaa74d`）

在只读版式基础上继续优化字段网格、成本计算问题与计量行（提交 `0eaa74d`，3 个文件）：

- 字段网格轨道加上限 `auto-fill minmax(min(100%, 176px), 208px)` 并 `justify-content: start`：更宽的容器增加列数而不是拉宽字段；名称／报价备注／标识／客户块不再整行，改为按容器宽度占 2 轨（≥420px）或 3 轨（≥640px，标识为 2 轨）。
- 「报价信息 · 库存信息」分栏堆叠阈值 860px → 960px。
- 只读成本计算问题改为内联在对应值内：`.pm-val-issue` 显示问题首句、省略号截断、title 带全文，值下划线按 `color-mix` 染淡色危险线；红色错误行仅在可写模式保留。
- 计量组改为 `inline-size` 容器：三个数字始终一行（`.pm-measure-cells` 包裹），派生 CBM 在 ≤360px 容器内换到下一行，≤300px 收紧间距，数值 `nowrap` 不断行。
- 成本区段：「计算于 …」从段落下移入区段头注（`.pm-band-note`）；数字列标签右对齐到数字边缘。

## 标准镜像发布（2026-09-24，`0eaa74d`）

仅发布前端镜像 `starrc-frontend:20260924-0eaa74d`，继承运行中的 `starrc-frontend:20260924-c4245f6`（`COPY dist/` 合并进 `/usr/share/nginx/html/`，保留 Nginx 配置与旧版本静态资源）。后端保持 `starrc-backend:20260923-f8e6fc1` 不变。

发布前复核：`npm --prefix frontend run build`（tsc + vite）通过；新增 CSS 仅使用 `var(--pm-*)` token（含 `color-mix`），无 hex / `!important` / 新增变量，字号 ≥12px，字重 400/500/600，符合 `docs/ui-design-rules.md`。

容器变化：frontend `c6c2b478df38` → `bf07a84053cf`；backend（`5dc3b3d24e16`）与 postgres（`f196c32c514b`）保持不变。

发布后验证：内网 `http://127.0.0.1:18001/healthz` 与公网 `https://starrc.dataonfire.cn/healthz` 均 `ok: true`。公网 `index.html` 与本地构建逐字节一致（SHA-256 `7f02e261cb928194d4a57bb4cada91e342420d89a34ddd9677348b52ae19995a`）；入口 `assets/index-6GupEEmr.js` SHA-256 `c74d676fada106eac4d0ddcff67b75fe6d9ddbc8ea960db0683f8421746efa76`、`assets/App-Bvu6ohy_.js` SHA-256 `b3fb0bb63d56a0f6f21ce9878b8fc01abc7693c7eaf1d02222b4623722191613`，均与本地构建一致。

服务器发布目录：`/opt/starrc-filemaker/releases/20260924-0eaa74d/`（`backup/previous-release.yml`、`backup/previous-src.tar.gz`（上一发布 `build/` 整包：git `f8e6fc1` 前端源码 + `c4245f6` 已部署 `dist/`）、`build/`（`Dockerfile.frontend` + `dist` + `pm-frontend-src-0eaa74d.tar.gz`）、`release.yml`、`containers.txt`、`health.json`）。

回退：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-0eaa74d/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps --no-build frontend
```

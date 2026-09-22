# 产品列表与导航精简发布（2026-09-22）

生产入口：https://starrc.dataonfire.cn/?page=businessProducts

## 改动

- 产品列表顶部保留搜索、折叠筛选、表格设置和更多。摘要卡片及重复说明移除，统计、总页数、分页和数据来源统一到底部。
- 筛选草稿与已生效条件分离，翻页不提交草稿；失败保留输入和原结果。
- 导航分组可独立折叠，偏好保存在浏览器。首次进入仅展开当前页面所在分组；进入其他页面时自动展开对应分组。
- 导航首页移除外边框；整栏开关移到内容区顶部标题左侧。桌面收起为图标栏，小屏收起隐藏导航，顶部可重新展开。

## 发布与回退

仅发布前端静态构建，镜像为 `starrc-frontend:products-nav-20260922-r1`，继承原前端镜像以保留 Nginx 配置和旧版本静态资源。

上一版本：`starrc-frontend:filemaker-nav-20260922`。

服务器发布目录：`/opt/starrc-filemaker/releases/products-nav-20260922-r1`。其中 `previous-release.yml` 为发布前覆盖配置，`previous-compose.yml` 为基础配置备份；环境备份仅保留在服务器受限目录。源码未上传。

继续使用 `/opt/starrc-filemaker/current/deploy/starrc/docker-compose.yml` 与 `product-master.release.yml`，只替换覆盖文件中的 frontend 镜像，并使用 `up -d --no-deps --no-build frontend`。发布前后 backend 和 postgres 容器 ID 一致。

回退时将 `previous-release.yml` 恢复至当前部署的 `product-master.release.yml`，保留基础配置与环境文件，只重新创建 frontend。首次发布检查遇到容器启动瞬间的连接重置并自动回退；改用带启动重试的健康检查后再次发布成功。

## 验证

- `npm --prefix frontend run build` 通过。
- `node frontend/scripts/check-business-products.cjs`：筛选草稿、成功/失败、分页边界、菜单、行高偏好和 CSV 检查通过。
- `node frontend/scripts/check-sidebar.cjs`：分组折叠、持久化、当前分组自动展开、图标栏、权限及预览回调、顶部开关、损坏存储回退检查通过。
- `node frontend/scripts/check-product-browser.cjs`：只读产品详情八种组合检查通过。
- Chrome 本地组合页面验证分组展开、顶部整栏开关和紧凑图标栏。
- Chrome 生产真实产品页验证新版布局、分组展开与折叠、整栏收起与恢复。
- 公网 `/healthz` 返回 `ok: true`，HTML 与本地构建逐字节一致。
- 公网 `assets/App-D_yR4es9.js` 与本地 SHA-256 一致：`f9b17d3f997d4ad5895f02842d891902a606e67b03df1e23e30bd62d5de595da`。

# 产品报价：WebViewer 编辑入口

2026-09-21 已在 FileMaker Pro 中实际保存以下布局修改。

- 来源布局：`产品报价`，表 occurrence：`產品`。
- 顶栏新增 `编辑` 按钮，对象名 `btn_product_master_edit`。
- 按钮执行单步 `新建窗口`：对话框，名称 `产品编辑`，布局名称计算 `"产品编辑_WebViewer"`，高度 760、宽度 1100；关闭按钮可用，隐藏菜单栏和工具栏。
- 新布局 `产品编辑_WebViewer` 也使用 `產品`，继承新窗口的当前产品记录；不通过 SKU 查找，不创建产品记录。
- WebViewer 对象 `wv_product_master`，左右及上下锚定，允许交互和 JavaScript 调用 FileMaker 脚本；关闭自动 URL 编码，避免重复编码签名和参数。

WebViewer 地址计算：

```filemaker
Case (
  not IsEmpty ( 產品::ID ) ;
  StarRC_WebViewerURL (
    "?page=productMaster&productId=" & GetAsURLEncoded ( 產品::ID )
  ) ;
  "about:blank"
)
```

复用既有签名函数，不在布局内另存密钥。页眉显示当前产品 SKU（仅显示），身份始终使用 `產品::ID`。

## 实测状态与上线待办

更新：2026-09-21 已部署新版，按钮能显示当前产品的完整字段迁移预览，不再落到工作台；保存暂未开放，详见 [生产发布记录](product-master-deployment-20260921.md)。下面保留最初入口验收时的结果。

已点击报价页按钮验证：能打开独立 WebViewer，签名登录成功，当前产品 SKU 为 `036-EX01`。线上前端仍为旧版，不识别 `productMaster` 页面，实际显示工作台，**尚不能编辑或保存产品**。

因此布局页眉暂时明确显示 `产品编辑服务待启用，暂不能保存。`。完成 [主数据切换预检](product-master-cutover.md)、迁移及服务部署后，再去除这行提示，并用至少两个不同 UUID 的产品验证加载、保存、历史及回写状态。不能把本次入口验证视为主数据切换或写入验收通过。

关闭对话框返回原报价窗口。此次未修改产品记录、原生字段权限或生产主数据功能开关。

## 保存反馈与关闭回调（2026-09-24，已发布）

保存产品资料成功后弹出「产品资料已保存」弹框，按本次保存版本的同步任务显示等待、成功、重试或冲突状态。Web 保存失败时保留输入并显示原有错误提示，不弹出成功反馈。

弹框只有「关闭」按钮，调用现有 FileMaker 脚本，无须修改布局或新建脚本：

```javascript
window.FileMaker.PerformScript('StarRC_CloseWebViewer', JSON.stringify({
  action: 'close',
  source: 'productMaster',
  productId: savedProductId,
  saved: true,
  version: savedVersion
}));
```

`saved` 表示 Web 已保存；只有同步任务为 `synced` 才显示「已写回 FileMaker」。后台同步不会因关闭窗口而停止。关闭不再次询问取消编辑；仅另有未保存的客户群报价时保留离开确认。浏览器不允许关闭或脚本调用抛出错误时，弹框内提供错误提示。

本地验收：TypeScript / Vite 构建通过；使用隔离模拟接口在 1068、1440、390px 的亮暗主题下检查弹框；验证关闭 callback 名称和参数，以及等待、重试、冲突和保存失败保留输入。未为验收额外修改生产产品数据。

### 标准镜像发布

- 代码提交 `d12494a` 已推送 `origin/main`，仅前端和文档改动，无数据库迁移或 FileMaker 布局变更。
- 镜像 `starrc-frontend:20260924-d12494a` 继承 `starrc-frontend:20260924-12aff38`。
- frontend 容器 `02e3944a7267` → `35b019f4517f`；backend `a4fd3392dca5`、postgres `f196c32c514b` 保持不变。
- 前端构建通过；内外网健康检查均 `ok: true`。公网 `index.html` 和两个入口 JS 与本地构建 SHA-256 一致：
  - `index.html`：`6d2e11c767bceddd3a1e0ef54e5db0291d347870f17ef8bd3b384e737eb71fe5`
  - `index-DQvpAy5K.js`：`3a77063fe245d0b05ce73af5bd842237ddf402533bfaa8a65223760130282c90`
  - `App-DoiVmNqO.js`：`ccb5c9f56eecca22dad892814e2491d30a0b3e383959fa2c8f146b7f6e82fe7c`
- 已从 FileMaker 的「产品报价」重新打开「产品编辑」，当前产品成功载入且可编辑；留给用户直接修改保存查看弹框，发布验收未额外改写产品内容。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260924-d12494a/`。
- 回滚：恢复该目录的 `backup/previous-release.yml` 到当前 Compose 目录，按 release-playbook 执行 `up -d --no-deps frontend`，回到 `starrc-frontend:20260924-12aff38`。

## 保存反馈弹框优化（2026-09-24，`4ad9fdd`，仅前端）

保存反馈从内联 Badge 提示改为独立组件 `ProductSaveFeedback`，用共享
`ui/ProgressSteps` 显示「保存资料 → 回写 FileMaker → 确认完成」三个真实业务
阶段（不模拟百分比）：

- 保存请求带 45 秒超时（AbortController），超时提示「尚未确认保存结果，返回
  编辑后重试相同修改，系统会避免重复提交」（requestId 幂等）。
- 异常时显示可选择的错误详情（产品 UUID、Web 版本、阶段、状态）与「复制错误」
  按钮，允许「返回编辑」；等待超过 30 秒也可返回编辑，后台继续处理。
- 只有确认回写成功（job `synced`）才显示「完成」按钮关闭 WebViewer。
- `docs/ui-design-rules.md` 新增 ProgressSteps 组件规则。

### 标准镜像发布

- 代码提交 `4ad9fdd` 已推送 `origin/main`，仅前端和文档改动，无数据库迁移或
  FileMaker 布局变更。
- 镜像 `starrc-frontend:20260924-4ad9fdd` 继承 `starrc-frontend:20260924-d12494a`。
- frontend 容器 `35b019f4517f` → `7f9c518d9bb9`；backend `a4fd3392dca5`、
  postgres `f196c32c514b` 保持不变。
- 前端 tsc + vite 构建通过；内外网健康检查均 `ok: true`。公网 `index.html` 与
  入口 JS 和本地构建 SHA-256 一致：
  - `index.html`：`7a83033795f21f97a66981be78469590804f10425d29f3c2ab72960019d6782e`
  - `App-BEjGg5ir.js`：`37e8ea1438fbb6202be4a54017b9ae72b6b57d0e3a5727993e2453088109f3f0`
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260924-4ad9fdd/`。
- 回滚：恢复该目录的 `backup/previous-release.yml` 到当前 Compose 目录，按
  release-playbook 执行 `up -d --no-deps frontend`，回到
  `starrc-frontend:20260924-d12494a`。

## 产品编辑 Debug 下拉（2026-09-25，`412cfa4`）

版本旁新增 Debug 按钮，展开显示登录会话的账号、用户名、传入权限集，
产品接口返回的查看/编辑/审核/价格/同步权限，以及产品 UUID、Web 版本和锁定状态。
权限集通过已有 `session.context.operator.privilege` 传入，无须增加 FileMaker 脚本。
若入口仍传 `filemaker` 等占位值，面板提示未提供真实权限集；入口应按现有约定
把 `Get ( AccountPrivilegeSetName )` 放进签名载荷的 `operator.privilege`。
面板只用于诊断，不参与授权；不显示 token、签名或完整 URL。

本地验证：前端构建通过；模拟产品接口下检查 1068 / 1440 / 390px 与亮暗主题，
页面及下拉没有水平溢出，Escape 可关闭并返回按钮焦点。

### 标准镜像发布

- 代码提交 `412cfa4` 已推送 `origin/main`，仅前端和文档改动，无数据库迁移或
  FileMaker 布局变更。
- 镜像 `starrc-frontend:20260925-412cfa4` 继承 `starrc-frontend:20260924-4ad9fdd`。
- frontend 容器 `7f9c518d9bb9` → `05b871dad599`；backend `a4fd3392dca5`、
  postgres `f196c32c514b` 保持不变。
- 前端 tsc + vite 构建通过；内外网健康检查均 `ok: true`。公网 `index.html` 与
  本地构建 SHA-256 一致：`cc8a0eecd1953347ac786a3ef3d9747be9aa4fe7756514ebf67f5efca4eb2201`。
- 服务器审计目录：`/opt/starrc-filemaker/releases/20260925-412cfa4/`。
- 回滚：恢复该目录的 `backup/previous-release.yml` 到当前 Compose 目录，按
  release-playbook 执行 `up -d --no-deps frontend`，回到
  `starrc-frontend:20260924-4ad9fdd`。

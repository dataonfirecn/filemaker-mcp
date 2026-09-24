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

## 保存反馈与关闭回调（2026-09-24，本地实现待发布）

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

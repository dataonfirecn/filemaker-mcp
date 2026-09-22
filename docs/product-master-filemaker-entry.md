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

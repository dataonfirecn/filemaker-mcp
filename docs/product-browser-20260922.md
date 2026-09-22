# 产品浏览页发布（2026-09-22）

产品资料详情入口 businessProductDetail 复用 ProductMasterPage 的只读模式，按产品 UUID 加载资料。保留基础资料、产品照片、规格书、生产注意事项、预览与下载；不提供字段编辑、客户选择、SKU 复制、保存、上传、替换和移除。原 FileMaker 编辑入口保持原模式。

前端已发布：starrc-frontend:product-browser-20260922。仅重建前端，后端和写入开关保持原配置。旧镜像为 starrc-frontend:20260922-6f97ea2；服务器回退配置在 /opt/starrc-filemaker/releases/product-browser-20260922/previous-release.yml。

验证：TypeScript/Vite 构建通过。执行 `node frontend/scripts/check-product-browser.cjs`，覆盖 4 个页签 × 2 种 previewMode，在提供编辑权限、全字段与附件、展开全部折叠区情况下，8 项渲染检查均通过，无 input/textarea/select 或写入操作按钮。该测试使用合成数据，不提交产品修改。生产 JS SHA-256 与本地构建一致，公网页面和健康接口正常。

浏览器交互验收未完成：Chrome 自动化多次返回用户正在操作应用，未能切换至产品页，未将其报告为实际点击/键盘测试通过。

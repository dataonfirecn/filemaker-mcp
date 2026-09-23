# 客户群报价管理员 Tab 上线（2026-09-23）

已按用户要求上线功能入口，生产地址：https://starrc.dataonfire.cn/?page=businessProducts 。
产品详情／编辑器共用的独立“客户群报价”Tab 仅管理员可见；管理员边界沿用 `canManageAccounts`，仍要求产品和价格读取权限。
后端列表、历史、新增和修改接口均执行管理员校验。

## 本次范围

- 新前后端均已发布，报价存储表由产品主库初始化创建。
- `PRODUCT_QUOTE_WRITE_ENABLED=false`，报价目前只读，尚未导入旧报价，当前报价数为 0。
- 原有 25,228 条产品保留；产品资料预览、Web-only 模式及原有写入关闭设置保留。
- 未修改 FileMaker 报价、订单取价、DMS 或管理员账号权限。
- 旧报价迁移的异常处理方式仍待用户确定，详见 [真实报价预检](product-quotes-preflight-20260923.md)。

## 镜像与回退

新镜像：

- `starrc-backend:product-quotes-admin-20260923-r1`
- `starrc-frontend:product-quotes-admin-20260923-r1`

上一版本：`starrc-backend:20260922-6f97ea2`、`starrc-frontend:product-split-20260922`。
发布目录：`/opt/starrc-filemaker/releases/product-quotes-admin-20260923-r1`。
其中 `backup/previous-release.yml`、`backup/previous-compose.yml`、`backup/previous.env` 保存原部署配置；
`backup/product-master.dump` 保存发布前 pm_* 数据，归档清单可读且记录 SHA-256；本次未执行恢复演练。

回退时恢复 previous-release.yml 至当前部署覆盖文件，再仅重建 backend/frontend。
数据库表为增量添加，回退不删除报价表，也不恢复覆盖现有产品数据。
本次发布脚本具备健康检查失败自动回退。数据库容器没有重建。

## 上线核验

- 前后端均运行新镜像，内网及公网 healthz 正常。
- 公网 HTML 与本次 dist/index.html 逐字节一致。
- 未登录访问报价接口返回 401。
- 在部署镜像中，使用实际产品主库验证管理员可读取空报价列表，非管理员返回 403，保存关闭返回 403。
- 浏览器公网登录页正常；本次验证浏览器未登录，不声称完成了生产管理员界面或 FileMaker 宿主验收。
- 管理员 Tab 显隐和操作交互已在发布前使用测试会话完成浏览器验证。

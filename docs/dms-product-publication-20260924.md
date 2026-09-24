# DMS Web 产品对接（2026-09-24）

## 已部署

- StarRC 后端：`starrc-backend:20260924-dms-web-catalog-v2`。
- Stock Check 后端：`stock-check-backend:20260924-web-catalog-v3`。
- 两边前端保持原版本；Stock Check 前端、数据库容器 ID 未变。
- 活动 source 为 `starrc-products-008-20260922`，名称保留历史值，实际已包含 25,228 个 Web 产品，不能按名称推断只有 008 客户。
- DMS 已启用 `PRODUCT_PUBLICATION_ENABLED=true`；Web 副本是产品资料、目录、搜索、聊天、导出和产品图片的读取来源。订单、零件、BOM 仍保留独立业务读取。

## 发布与权限

复用 `/api/product-master/changes` 和 `/changes/ack`。新增可选 `limit`（1–1000，默认 100），首次追平连续批量拉取，平稳运行约每 10 秒检查一次。未初始化或权限副本超过 300 秒未追平返回 503，不回源 FileMaker 产品资料或容器。

StarRC 消费者配置支持对象 `{"token":"<secret>","profile":"dms-catalog"}`，本次消费者为 `dms-stock-check`。原字符串密钥格式继续兼容其他消费者。发布只读 Web preview store 不开启编辑或 FileMaker 回写。

`product_catalog_contract.py` 在发布端和消费端使用相同白名单。仅同步身份、客户范围、页面所需非财务字段和产品图片；价格、成本、报价及其他附件不进入本次客户副本。DMS 详情始终不返回产品价格，旧账号的价格权限不能覆盖这条限制。聊天价格查询拒绝访问；订单的既有金额权限未变。

客户范围来自账号 `product_privilege`，精确匹配产品 `privilege` 的换行分隔值。目录、聊天、详情、导出及图片统一执行检查。主图优先 `image_main`，其余按图片顺序；文件下载校验 SHA-256。

## 全量校验与修复

Web 当前产品与最新发布快照逐 UUID 比较，发现 181 个不一致快照。已先备份发布表，在事务中保持产品与版本历史不变，刷新对应发布事件并分配新序号。既有表限制每个产品版本只能有一个事件，因此修复使用冲突更新和 identity DEFAULT，不增加重复版本事件。

DMS 接收同版本但更大发布序号的修复快照；较旧产品版本仍不能覆盖较新版本。初次同步、修复和恢复都使用原游标机制。

两端全量 manifest 完全一致，覆盖 UUID、版本、白名单字段、客户范围与图片关联：

- 产品：25,228。
- 产品图片关联：26,250（不是所有附件数量，也不表示每个产品都有图片）。
- SHA-256：`0f9b127811b440473f19f6f574d7c39b5e28ac2481914903f7e497ab3fc974aa`。
- 6 个启用客户产品数：0780=710、0654=738、008=1245、036=164、088=332、0665=422。

全量核对覆盖图片元数据和关联；文件内容为按客户抽查，不声称重新下载了全部 26,250 个图片。

## 验证

- StarRC 全部后端测试：445 通过（包含隔离 PostgreSQL）。
- DMS 全部后端测试：294 通过（包含隔离 PostgreSQL）。
- 6 个启用客户：目录、详情、导出、聊天和无价格检查通过；共抽查 10 个图片文件并校验摘要，跨客户图片拒绝通过。验证中的产品 FileMaker 调用为 0。
- 通过线上真实鉴权和 Nginx 的目录/聊天检查：27 项通过，0 失败；零件列表回归通过。
- 6 个启用客户通过真实鉴权和 Nginx 访问缩略图、详情图均返回 200，价格查询均返回 403。
- 已修复带点号 SKU 的聊天识别，例如 `046-8.CRX-V2`。
- 公网健康检查通过；首次切换检查游标 65169，bootstrap_complete=true，error=null，授权快照年龄 4 秒。
- 浏览器打开后停在登录页，待用户登录后完成视觉验收；不将 HTTP 验收等同于浏览器点击验收。

## 运维与回退

发布材料：StarRC `/opt/starrc-filemaker/releases/20260924-dms-web-catalog/`；DMS `/opt/stock-check/releases/20260924-web-catalog/`。目录中保存备份、构建输入和验收报告；不把密钥复制进文档或仓库。

DMS 以当前线上镜像为基础，通过 `deploy/stock-check/product_publication_overlay.py` 仅注入本次改动，避免包含工作区其他未提交功能。脚本遇到不匹配的基线直接失败。

检查 `dms_product_cursor` 的 cursor、checked_at、error 和 bootstrap_complete；错误写入后台日志与游标状态。不要通过关闭发布开关回到旧 FileMaker 产品源。故障时保留副本和游标；无法恢复时暂停产品入口，保持不可用状态，订单与零件服务独立处理。

复核工具：StarRC `backend/scripts/product_catalog_publication.py` 默认只读，`--repair` 必须先备份；DMS `backend/scripts/verify_product_publication.py --sync` 执行游标续传并输出 manifest。客户路由及图片验收见 `backend/scripts/verify_product_web_catalog.py` 和 `deploy/stock-check/verify_web_product_http.py`。

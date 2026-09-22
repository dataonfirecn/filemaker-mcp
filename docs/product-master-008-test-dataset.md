# Hobby Tech / privilege 008 独立 Web 测试库

**最新结果（主图补齐后）：1,245 条产品、2,762 份资产，其中主图 1,102 张。** 主图统一使用 image_main，重新进行字段元数据预检及全量对账均通过。后文 1,660 份为首次导入时的数量；当时主图字段改名未被旧预检发现，已补齐并修正预检。完整说明见 [产品主图 image_main](product-main-image-20260922.md)。

## 范围

按 FileMaker 产品字段 privilege 精确等于字符串 008 筛选，保留原 UUID。客户名称中的 Imodel、Hobby Tech 等历史文字保持原值，不作为筛选条件。独立 source 为 starrc-products-008-20260922，绑定原 FileMaker 数据源指纹。

活动 Web schema 为 backend/config/product_master_web_schema.json：由当前产品编辑器基础分组、记录元数据、仍保留的 Tab 和容器映射导出。共 79 个普通字段（包括 ID、privilege）、26 个容器位置（18 张产品图、2 个规格书、6 个包装/标签容器）。保留完整基表清单和旧注册配置用于溯源；不将删去的 Web 字段写空到 FileMaker。

## 存储与接口

- pm_product.fields 只存范围内普通字段，assets 兼容列为空数组。
- pm_asset_version 保存独立不可变文件版本、稳定 asset_id、产品归属、COS 对象键、名称、格式、大小、SHA-256。
- pm_product_asset 保存产品 UUID、容器字段、重复位置、文件版本、顺序和角色，唯一约束禁止同一位置重复绑定，外键禁止跨产品绑定。
- pm_upload 保留上传确认和幂等记录；pm_revision 保存历史快照。
- pm_reference 保存本地字段选项和客户目录，读取页面不实时查询 FileMaker。
- PRODUCT_MASTER_WEB_ONLY=true 时，产品编辑器及 business-products 列表、详情、图片都从 PostgreSQL / COS 读取，缺失产品返回 404，禁止自动回源和自动导入。
- 原有账号和价格权限继续在后端执行。此开关不改变订单、BOM 等关联业务接口职责。
- 正式保存与 FileMaker 回写保持关闭。

## 导入和验收工具

1. product_master_import_scope.py：按权限代码扫描 UUID；逐产品刷新记录和临时容器地址；上传 COS 并完整回读核验摘要后提交产品、关系、历史。受控并发、失败重试、断点续跑。保留旧 ProductAssets 资产 ID。
2. product_master_compare_scope.py：比较当前 FileMaker 范围的 UUID、全部普通字段值、容器位置及修改版本。
3. product_master_align_assets.py：按当前 UI 配置纠正图片角色与顺序；通过新增审计版本保留调整记录，不修改历史文件。
4. product_master_verify_web_only.py：使用遇调用即失败的 FileMaker 客户端验证产品、列表、选项、客户和图片接口；逐份 COS 文件重新下载核验摘要。
5. product_master_retire_source.py：仅在新 source 已生效且两份验收报告成功、备份存在后，事务删除指定旧 source 的 pm_* 数据；不删除 COS 文件。

旧产品库已制作 pg_dump 备份，并在独立数据库 pm_backup_verify_20260922 恢复验证，恢复产品数 13,222。生产备份位置为 /opt/starrc-filemaker/releases/product-master-20260921/backup/008-reset/。正式清理前再次保存最新备份。

测试：50 项产品主数据、容器上传和产品 API 测试通过，包含关系表版本保留、独立读取、禁止 FileMaker 回源、分块上传及按文件摘要安全复用 COS 对象。

## 2026-09-22 部署与全量验收结果

已切换生产测试库，活动 source 仅保留 starrc-products-008-20260922。按本次最终读取时的 FileMaker privilege=008 范围导入 1,245 条产品，UUID 保持不变。首次按旧登记字段进行比较的报告无差异，但后续发现缺少字段存在性预检会漏掉改名后的主图；该报告不能单独证明主图完备，应以主图补齐后的重新对账报告为准。此后新增的 FileMaker 产品不会自动混入这份测试库，需要显式再次导入并验收。

文件数据共 1,660 份、1,662,062,054 字节：950 张产品图片、1 份产品规格书、709 份包装／标签文件。界面仍提供固定 18 个产品图片位置和 2 个规格书位置，源文件为空的位置保持为空。共关联 1,649 个不同 COS 对象键；相同内容可复用已核验对象，产品关系及文件版本仍独立保存。

- pm_asset_version：1,660 条。
- pm_product_asset：1,660 条；每个容器位置独立绑定。
- pm_product.assets：所有产品均为空数组，不存储活动图片清单。
- pm_reference：字段选项、客户目录各 1 份。
- 全量重新下载 1,660 份 COS 文件，大小与 SHA-256 均通过，失败 0 项。
- 禁止 FileMaker 调用的产品读取、列表、客户、选项和文件接口验证通过；FileMaker 调用数为 0。
- 315 条产品通过新增审计版本统一了图片角色及排序，未改写旧历史。

源数据质量：空 SKU 为 0；有 2 组已有重复 SKU（按忽略大小写、去首尾空白判定），各涉及 2 个不同 UUID：`ht-crx-v1-bag g-02`、`ht-drift-bag 4-step 2`。迁移保留原值，没有合并或擅自修改产品；启用正式保存前应处理这些源数据冲突。

部署镜像：

- backend：starrc-backend:product-master-20260922-008-final。
- frontend：starrc-frontend:product-master-20260922-008-ready。
- PRODUCT_MASTER_WEB_ONLY=true，PRODUCT_MASTER_PREVIEW_ENABLED=true。
- PRODUCT_MASTER_ENABLED=false，PRODUCT_MASTER_WRITE_ENABLED=false；本次未启用正式保存或 FileMaker 回写。
- PRODUCT_MASTER_SCHEMA_PATH=config/product_master_web_schema.json。

旧活动 source starrc-products 的 13,222 条产品及该 source 的关联产品主数据记录已事务清理，COS 文件未删除。清理前的最终备份已在独立数据库 pm_backup_008_cutover_20260922 完整恢复，确认旧库 13,222 条、新库 1,245 条均可恢复。

最终备份：/opt/starrc-filemaker/releases/product-master-20260921/backup/008-reset/before-cutover-008-complete.dump，SHA-256：67edba0b312d6eb6de6a6a8f02974f3ce726d2e6fccaf3f7a20bbe9303e95a45。切换前部署配置保存在同目录 before-cutover-release.yml。

验收报告保存在生产 backend 的持久化 /data 卷：

- product-master-008-20260922.json：导入完成，1,245 条产品、1,660 份文件，失败 0 项。
- product-master-008-compare.json：全量源数据对账通过，缺失、额外、字段差异、容器差异、版本差异均为 0。
- product-master-008-offline-verification.json：全量 COS 和禁止 FileMaker 回源的接口读取验证通过。

本次独立读取范围是产品编辑器、Web 产品列表／详情／图片，以及编辑器的客户和选项目录。订单、BOM 等其他业务流程保持原有数据职责。

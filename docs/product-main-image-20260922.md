# 产品主图字段 image_main

## 字段契约

FileMaker 的 @products_web_api 与 @products 元数据已确认主图为 image_main：普通可写容器，重复次数 1。Web schema、编辑器、产品列表、PDA 补图、回写 worker、产品资产导入和订单 Web 图片读取使用这一明确名称。

产品图片总位置数仍为 18：主图 image_main，加檔案 2 | 容器至檔案 18 | 容器。编辑器使用明确位置表排序；主图不再由字段名字母顺序、数字解析或资产数组第一项决定。主图为空时保留空位，不把其他图片标成主图。

## 历史兼容与回写

- product_image_fields.py 集中处理位置号与字段名，以及旧主图名 檔案 1 | 容器 的兼容。
- 历史修改记录不改写。恢复旧版本时，将旧主图字段转换为 image_main 后保存新版本。
- worker 兼容旧版本任务及执行检查点，上传、清空和回读均定位明确的 image_main 容器。
- 旧 ProductAssets 资产标识、旧离线迁移键保持稳定，避免仅因改名产生重复资产。
- 当前正式保存及 FileMaker 回写开关继续关闭。回写目标由集成测试验证，本次没有向 FileMaker 写入测试文件。

## 本次发现的主图遗漏

上线前检查发现原 008 Web 测试库有 1,660 份文件，但主图关联为 0；FileMaker 当前的 image_main 则有文件。旧的对账脚本未先核实登记字段是否仍存在，缺失字段可能被当作空值，因此原对账的 complete 不足以证明主图完备。

新增 ProductSchema.validate_layout，导入与对账前检查每个登记字段的存在性、类型和重复次数，字段改名或 API 布局漏字段时直接失败。

product_master_backfill_main_image.py 只为当前测试库补齐缺失主图：读取实时 FileMaker 文件、校验内容摘要后保存 COS 与独立资产关联，追加产品历史。其他资料字段及原有文件保留。历史备份只能提供可复用的对象键和资产身份，文件必须与实时源文件核验一致后才能复用。支持断点续跑、受控并发及独立失败清单。

## 验证与备份

75 项相关测试分两轮通过（74 项套件，以及包含新增旧迁移身份检查的 2 项迁移脚本测试，其中 1 项重复）。覆盖产品主数据、容器上传、PDA、订单主图选择、旧版本回写兼容和字段缺失预检。TypeScript 检查和 Vite 构建通过。

迁移前数据库备份：/opt/starrc-filemaker/releases/product-main-image-20260922/backup/before-main-image.dump。

备份 SHA-256：0ec123750c840274f94395ea5e28dd846d35035ff673364616b1b0710bfcf60d。

生产 /data/main-image-before.json 保存了原有 1,660 份资产的元数据摘要，供补齐后核对原文件归属与对象键未改变。

## 完成结果

已上线，backend 为 starrc-backend:product-main-image-20260922-r5，frontend 为 starrc-frontend:product-main-image-20260922。公网健康检查通过。

- 产品仍为 1,245 条，资料字段未因补图而变动。
- 补齐 image_main 主图 1,102 张；源数据未设置主图的 143 条产品保持空位。
- 当前独立资产关系总数为 2,762，其中原有 1,660 份资产的 ID、产品归属、COS 对象键、文件摘要、格式和大小全部保持一致。
- 当前旧主图名关联为 0。初次迁移检查时旧名关联也是 0，因此本次通过新增主图关系补齐，没有改写旧历史记录。
- 每份新增主图在绑定前均与实时 FileMaker 文件核验 SHA-256；首轮 3 个读取超时项已重试成功，最终失败 0 项。
- 最终重新对账：FileMaker 与 Web 均为 1,245 条，UUID、字段值、容器位置及源修改版本无差异；本次对账已先通过字段存在性／类型／重复次数预检。
- 禁用 FileMaker 客户端后，全部 1,245 条产品可读取；最小和最大主图的 COS 下载与摘要复核通过，FileMaker 调用数为 0。
- PRODUCT_MASTER_WEB_ONLY=true；正式保存与 FileMaker 回写仍保持关闭。

生产持久化报告：

- /data/product-main-image-backfill.json：最终补齐结果，complete=true。
- /data/product-main-image-backfill-first-pass.json：首轮失败记录保留用于追溯。
- /data/product-master-main-image-compare.json：重新进行的源数据完整对账，complete=true。
- /data/product-main-image-verification.json：主图、原文件保留和独立读取验收，complete=true。

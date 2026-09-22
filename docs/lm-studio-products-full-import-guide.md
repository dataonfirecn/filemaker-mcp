# 用 LM Studio 接手其余产品导入

这份文件是操作交接指导，不代表已执行全量导入。

目标：把同一 FileMaker 数据源中尚未进入 Web 的产品及其文件补入 PostgreSQL / COS。保留已有 008 产品、UUID、资产、历史和当前页面。页面读取继续只走 Web；导入程序读取 FileMaker 是取得尚未迁移的数据，两者要区分。

## 1. 在 LM Studio 中准备执行环境

1. 加载你已下载的 Qwen 模型。你提到的“Qwen 3.8”请以 LM Studio 显示的实际模型名称和模型 ID 为准，不要把简称直接当成 API 的模型 ID。
2. 给当前会话连接可信的文件读写及终端执行工具，工作目录设为 `/Users/gabriel/Documents/Vibe/StarRC-FileMaker`。LM Studio 支持连接 MCP 工具；只上传本指导、没有执行工具时，模型只能给建议，不能访问仓库或操作服务器。[官方说明](https://lmstudio.ai/docs/app)
3. 如果你使用外部开发代理连接 LM Studio：开启本地模型服务，使用其实际监听地址；端口为 1234 时，OpenAI 兼容接口的基础地址为 `http://127.0.0.1:1234/v1`。模型填实际 ID，认证使用本地服务设置。文件和终端执行能力仍由开发代理提供。[官方开发文档](https://lmstudio.ai/docs/developer)
4. 先让模型实际读取 `docs/product-master-008-test-dataset.md` 的前几段，并执行 `git status --short`，确认工具真的可用。不要把“我可以操作”当作已接通。
5. 让执行工具使用现有 SSH 连接和服务器部署配置。不要把 FileMaker、数据库或 COS 密钥粘贴进对话。

不需要把全部产品 JSON 或图片送给模型。模型负责调整、启动和检查导入脚本，数据搬运由 Python 程序执行。

## 2. 接手时的已知状态

以下是 2026-09-22 的验收基线，执行前重新读取计数，不把这些数字写死为以后必须相等的总量。

| 项目 | 状态 |
| --- | --- |
| 本地仓库 | `/Users/gabriel/Documents/Vibe/StarRC-FileMaker` |
| 生产服务器 | `root@101.35.198.171`，使用现有 SSH 配置 |
| 生产部署目录 | `/opt/starrc-filemaker/current` |
| 后端容器 | `starrc-backend`，应用目录 `/app`，报告目录 `/data` |
| 活动 source | `starrc-products-008-20260922` |
| 已有产品 | 1,245 条，privilege 为字符串 `008` |
| 已有资产关系 | 2,762 条，其中主图 1,102 张 |
| 专用 FileMaker 布局 | `@products_web_api` |
| 当前 Web schema | `backend/config/product_master_web_schema.json` |
| 字段范围 | 79 个普通字段、26 个容器位置；以实际配置为准 |
| 产品图片 | `image_main` + `檔案 2 \| 容器` 至 `檔案 18 \| 容器` |
| 规格书 | `產品規格書`、`產品規格書2` |
| 其余容器 | 当前 schema 保留的 6 个包装／标签容器 |

保持现有开关：

```text
PRODUCT_MASTER_SOURCE=starrc-products-008-20260922
PRODUCT_MASTER_LAYOUT=@products_web_api
PRODUCT_MASTER_SCHEMA_PATH=config/product_master_web_schema.json
PRODUCT_MASTER_WEB_ONLY=true
PRODUCT_MASTER_PREVIEW_ENABLED=true
PRODUCT_MASTER_ENABLED=false
PRODUCT_MASTER_WRITE_ENABLED=false
```

本次直接补入同一个活动 source。名字虽然含有 008，但它已参与资产版本 ID、对象键和数据源绑定，不要为了名称好看而改名或重新生成资产身份。

旧的 13,222 条数据已经退役，COS 原文件和数据库备份保留。不要恢复旧产品资料作为本次导入结果，也不要以 13,222 作为当前应有总数。旧 COS 对象只有经当前源文件摘要核验相同后才能复用。

当前 125 份 BMP/MPO/WMF 图片的处理已经由用户明确为：只在 UI 写明不能预览的原因，保留下载；不转换、不删除、不补生成图片。709 份 BTW/BYL 是标签文档。此限制继续有效。

## 3. 先修正这些脚本限制

现有代码不能原封不动执行“全量导入”。

| 文件 | 当前限制及本次需要做的事 |
| --- | --- |
| `backend/scripts/product_master_import_scope.py` | 强制 `--privilege`，只扫描一个范围。增加明确的全量模式，与单 privilege 模式互斥；全量模式不传 privilege 条件。保留 UUID 校验、最新容器 URL、受控并发、重试及断点续传。 |
| `backend/scripts/product_master_compare_scope.py` | 查询硬编码 `privilege == 008`。改成与导入一致的范围参数；分清本次新增数据、导入前已有数据和真实缺失项。 |
| `backend/scripts/product_master_verify_web_only.py` | 断言每条产品都是 008，并要求手填 expected。推广为按本次源清单验收，保留禁止 FileMaker 调用的验证。 |
| `backend/scripts/product_master_migrate.py` | 旧全量脚本默认布局不同、基表字段要求与当前精简 Web schema 不同，还会预先缓存整批记录及临时容器 URL；不要直接加 `--apply` 运行。优先扩展当前 scope 导入器。 |

全量模式不是 `privilege != 008`：必须扫描全部合法 UUID，再计算“FileMaker UUID 集合减去当前 Web UUID 集合”。这样才能包含后来新增的 008 产品，以及其他 privilege 和 privilege 为空的产品。

已有产品必须核对数据源指纹、UUID 和 recordId。保留其当前 Web 版本与资产；遇到 FileMaker 内容变化或身份异常，输出差异，不覆盖已有 Web 数据，也不把差异算作已解决。

## 4. 按这个顺序实施

1. **读取和预检。** 阅读下方提示词列出的代码、配置和报告。检查未提交改动并保留。核对运行中的 source、布局、schema、源数据库指纹；验证每个登记字段的存在性、类型及重复次数。不得把 UI 已移除的字段重新加回。
2. **建立清单和备份。** 读取当前 Web UUID、版本、资产关系、对象键及摘要，保存导入前清单；制作 pm_* 数据备份并验证可恢复。扫描 FileMaker 全部产品 UUID，记录总数、各 privilege 分布、重复/空 UUID、SKU 质量问题及待新增集合。账户看不到的记录不能宣称已全量覆盖。
3. **改进导入和验收脚本。** 按上一节修改，增加有意义的验证：全量包含非 008 和新 008、重复执行不重复新增、已有产品不被覆盖、单个文件失败不能算整条产品成功。报告分开记录扫描、已有、待新增、成功、失败和未处理数量。
4. **先导入少量新产品。** 选择约 20 条，覆盖不同 privilege、有主图、多图、规格书和其他文件；样本不存在的类型据实记录。每条导入前重新读取记录及有效容器地址，复用 `import_product`，不要直接手工 INSERT 产品或资产关系。
5. **小批验收后续跑。** 核对文件及关系后，继续处理全部待新增 UUID。初始并发沿用 3，按服务器负载调整；报告和待重试列表落到 `/data`。用能脱离对话持续运行的服务器进程执行，保存退出码。关闭 LM Studio 不应使导入状态丢失。
6. **全量对账。** 对照源清单核对 UUID、字段、容器字段及重复位置，复核迁移期间源版本是否变化。已有 008 数据另与导入前清单比较，证明没有被改写。对账发现的新增、变化、失败和缺失都必须明确列出，不静默跳过。
7. **Web 独立读取验收。** 在独立测试进程中阻止 FileMaker Data API/OData 调用，逐产品读取详情和资产关系，逐文件通过实际 Web 资产路由下载并验证大小与 SHA-256。正常图片验证解码；BMP/MPO/WMF 验证原文件可取及 UI 有格式说明，不能把“预览不支持”当成导入失败。非图片文件按下载校验。
8. **交付结果。** 汇总当前源产品总数、原有数、新增数、失败数、资产数、无主图数量、权限检查、备份路径和可重跑命令。失败项未解决时，报告必须是未完成。无主图的合法空位与迁移遗漏要分开统计。

复用 `pm_product`、`pm_revision`、`pm_upload`、`pm_asset_version`、`pm_product_asset` 和 `pm_reference`。产品普通字段进入主表；文件进入 COS，容器绑定进入独立关系表。保存真实对象键，不保存过期签名地址或 FileMaker 临时 URL。

扩展活动库前核对列表、详情和文件接口的产品范围及价格权限。新增数据不能绕过既有授权；本次不改 DMS、订单、BOM 等关联业务流程，也不启用用户保存或 FileMaker 回写。

## 5. 复制给 LM Studio 的启动提示词

```text
请接手 StarRC 产品 Web 主库的剩余产品迁移。

先完整读取：
/Users/gabriel/Documents/Vibe/StarRC-FileMaker/docs/lm-studio-products-full-import-guide.md

工作目录：/Users/gabriel/Documents/Vibe/StarRC-FileMaker
目标：把同一 FileMaker 数据源中尚未存在于活动 Web source 的全部产品及文件，
按当前 Web schema 补入 PostgreSQL 和 COS。保持现有 UUID、资产身份和历史。

必须先阅读：
- docs/product-master-008-test-dataset.md
- docs/product-main-image-20260922.md
- docs/product-asset-verification-20260922.md
- backend/config/product_master_web_schema.json
- backend/scripts/product_master_import_scope.py
- backend/scripts/product_master_compare_scope.py
- backend/scripts/product_master_verify_web_only.py
- backend/app/services/product_master/importer.py
- backend/app/services/product_master/store.py
- backend/app/services/product_image_fields.py
- frontend/src/components/productMasterLayout.ts

执行原则：
1. 先验证文件及终端工具可用，读取 git status，保留已有未提交改动。
2. 使用当前活动 source starrc-products-008-20260922；不改 source 名称。
3. 以实时全量 UUID 清单减去现有 Web UUID 得到新增集合；不要只筛 privilege != 008。
4. 先扩展 scope 导入/对账/验证脚本。现有 compare 和 verify 仍有 008 限制，不能直接用于全量验收。
5. 复用 import_product 和原有资产身份规则；不用 SKU 识别身份，不手工合并重复 SKU 产品。
6. 备份并保存导入前版本和资产清单，先做约 20 条的小批验收，再执行全部新增产品。
7. 保留当前 Web 数据。源变化、身份冲突、坏文件和遗漏逐项报告，不静默覆盖或跳过。
8. 18 张产品图片的主图明确使用 image_main；其余图片、规格书和标签按当前 schema 绑定。
9. 不转换 BMP/MPO/WMF，页面写明原因即可；标签文档保留下载。
10. 页面继续 Web-only；只有导入/对账程序可以读取 FileMaker。禁止向 FileMaker 写入。
11. 不启用用户保存、回写 worker，不清空表，不删除 COS，不恢复旧的 13,222 条陈旧数据。
12. 不修改 DMS、订单和 BOM；保留现有产品范围与价格权限。
13. 长任务在服务器独立执行，进度、日志、失败列表和退出码持久化，重跑必须幂等。
14. 密钥从既有部署环境读取，不打印、不写入报告、不要求粘贴进聊天。

请先输出实际检查结果和具体脚本调整方案，再完成实现、小批测试、剩余导入及全量验收。
每阶段给出实际命令的结果和报告路径，不用推测代替完成证据。
最终用独立测试进程阻止 FileMaker 客户端，证明所有导入产品与资产均可从 PG/COS 读取。
如果当前会话没有执行工具，请明确告知无法执行，并只给人工步骤，不声称已导入。
```

为避免模型上下文丢失，执行者应将清单、阶段进度、实际命令、最新报告及下一步写入仓库 `outputs/` 下的交接文件；每次续接先读取它，不重复启动另一轮迁移。

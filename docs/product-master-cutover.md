# 产品 Web 主库：实现与切换手册

## 当前状态（2026-09-20）

**2026-09-21 更新：**已部署产品详情迁移预览，并建立完整 `@products_web_api` 布局：175 个字段、42 个容器。生产 25,233 条 UUID 预检通过，初始导入已启动；正式保存和全局主库切换仍未启用。以下为初次实现时的历史状态，最新事实以 [生产发布记录](product-master-deployment-20260921.md) 为准。

代码已加入 StarRC 与 DMS，默认开关关闭。没有执行生产迁移、部署、FileMaker 布局修改或权限修改。

只读核实的 `@products` 布局包含 **107 个产品自身字段、33 个容器字段**，包括檔案 1–20、说明书、规格书、贴纸、标准书、标签等。快照在 `backend/config/product_master_schema.json`。相关表字段不作为 products 自身字段导入。

**该快照不是完整基表认证**：当前 OData 元数据连接失败，`@products` 还未提供 DMS 使用的 `privilege` 字段。不能据此声明全部基表已覆盖，也不能启用 DMS 展示。补齐真实基表字段和权限字段之前，保持所有生产开关关闭。不可把 `baseTableVerified` 改成 true 来绕过验证。

## 架构和接口

`pm_source` 将来源标识永久绑定到 FileMaker 数据源指纹。StarRC PostgreSQL 的 `pm_product` 保存当前主资料，`pm_revision` 保存每次修改前后快照与操作人，`pm_upload` 保存不可变附件版本，`pm_job` 保存 FileMaker 回写步骤，`pm_publication` 保存增量发布事件，`pm_consumer` 保存 DMS 确认游标，`pm_drift` 保存本地异常变更和处理，`pm_scan` 保存可续跑的每日巡检游标。

修改、审计、任务、发布事件在一个 PostgreSQL 事务内提交。并发保存比较 Web 版本；按请求 UUID 幂等。新产品 UUID 由 Web 后端生成，已有 UUID 不改变。附件版本 ID 与稳定资产 ID 分开保留；替换产生新 COS 对象，旧文件仍可下载。

上传先写暂存对象，确认时下载验证大小、SHA-256 和图片/PDF 格式，再写正式对象并验证。上传链接只能写暂存对象。正式文件无客户端写权限。应用不自动物理删除历史文件。

主要路径均以 `/api/product-master` 开头：

| 接口 | 用途 |
|---|---|
| `GET /schema` | 当前账号可见字段和权限 |
| `GET/POST /products` | 查询、新建 |
| `GET/PATCH /products/{uuid}` | 读取、按版本保存 |
| `POST /products/{uuid}/uploads` | 申请暂存上传 |
| `POST /products/{uuid}/uploads/{id}/complete` | 校验并保存不可变文件 |
| `GET /products/{uuid}/assets/{id}` | 当前或历史附件下载 |
| `GET /products/{uuid}/history` | 每次保存的前后快照 |
| `POST /products/{uuid}/restore/{version}` | 恢复为新版本 |
| `GET /products/{uuid}/status` | FileMaker、DMS 和本地异常变更状态 |
| `POST /products/{uuid}/retry/{version}` | 带原因重试指定任务 |
| `POST /products/{uuid}/rewrite-filemaker` | 以完整 Web 当前版本重新回写，保留被取代任务历史 |
| `POST /products/{uuid}/adopt-filemaker` | 将指定原生字段/容器导入为新 Web 版本 |
| `GET /changes?cursor=…` | 同源 DMS 增量发布流 |
| `POST /changes/ack?cursor=…` | DMS 提交落库游标 |

保存参数包含 `requestId`、`expectedVersion`、`changes` 和可选 `assets`。附件位置由 `field` + `repetition` 指定，不能重复绑定。冲突返回 HTTP 409 和当前账号有权查看的当前版本。新产品先保存必填资料，再上传文件。

已有 SKU 和 FileMaker recordId 读取入口保留，解析不唯一时要求 UUID。FileMaker UUID 定位改变或记录消失会进入冲突，不删除 Web 数据。

### FileMaker 回写

专用 worker 使用 `PRODUCT_MASTER_USERNAME/PASSWORD`，不解除 `FILEMAKER_READ_ONLY=true`。按产品顺序处理任务，以 PostgreSQL session advisory lock 避免双 worker 并行回写同一产品。每个步骤保存进度，字段和容器均使用 `modId` 保护；容器回写后下载核对 SHA-256。

新建超时会先按 UUID 查找；已获得的新记录定位号会先保存，UUID 验证失败时停止自动创建。字段/容器请求丢失响应时，通过持久化的执行中步骤和回读核对恢复；不能确定时进入冲突。失败任务持续退避重试，最长间隔 15 分钟。详情页显示错误类别，不公开上游凭据或容器临时地址。

每天分批巡检，进度可续跑。原生修改只登记异常，Web 资料及图片继续可用；计算和汇总结果可回流成有记录的新版本，普通字段不反向覆盖。

Claris 官方接口依据：[编辑记录](https://help.claris.com/en/data-api-guide/content/edit-record.html)、[容器上传及 modId](https://help.claris.com/en/data-api-guide/content/upload-container-data.html)。重复字段采用 Data API 的 `字段名(重复编号)`；容器上传通过独立 repetition 参数定位。

## 上线前必须完成的 FileMaker 配置

1. 从实际产品基表导出全部字段清单为 UTF-8 JSON 字符串数组，包含类型、计算、全局、自动录入规则的核对记录另存上线材料。不能从旧 API 布局反推基表清单。
2. 创建专用 `@products_web` 布局，使用产品基表的表实例，放入全部自身字段，并覆盖重复字段全部位置。将 DMS 客户范围字段 `privilege` 纳入完整产品发布映射；来源没有该字段时，先落实等价的明确权限映射，不能按 SKU 或客户名称猜测。
3. 用该布局的 `fieldMetaData` 更新字段注册表。普通字段是否可写按真实定义检查；计算、汇总、全局、UUID 禁止普通编辑。敏感字段配置 `readPermission=canViewPrice`、`writePermission=canEditProductPrices`。已有语义映射中的金融字段也已纳入初始注册表。
4. `ID` 要有唯一且非空约束；服务账号能提交 Web UUID，自动录入不能替换提供的 UUID。通过独立 QA 产品实际验证新建、超时重试、回读同一 UUID 后再设置 `uuidCreateVerified=true`。
5. 服务账号仅获产品专用布局所需读、创建、字段编辑和容器权限，不授予不相关记录删除权限。
6. 普通员工的 products 原生字段和容器设为不可修改，禁止原生新建和删除产品；产品页嵌入 WebViewer。检查其他布局、导入脚本、服务器脚本及定时任务的旁路写入。完成后登记 `nativeEditingLocked=true`。
7. 全量基表与专用布局逐项一致后，登记 `baseTableVerified=true`，`layout` 改为真实专用布局名称。上述三个标志和专用凭据缺一，写 worker 启用会拒绝启动。

普通业务角色默认无新增产品编辑权限。账号管理页新增：编辑产品、编辑产品价格、处理产品同步；按实际岗位授权。PDA 补图改走同一主库服务，使用它的账号也需产品编辑权限。

## 历史迁移与验证

先备份数据库、FileMaker 文件及 COS。冻结旧编辑后执行只读预检，再执行导入。在仓库根目录设置 `PYTHONPATH=backend`；容器中模块路径为 `/app`，配置路径为 `config/product_master_schema.json`。

```sh
PYTHONPATH=backend python backend/scripts/product_master_migrate.py \
  --layout @products_web --base-fields /secure/products-base-fields.json \
  --report /secure/product-preflight.json

PYTHONPATH=backend python backend/scripts/product_master_migrate.py \
  --layout @products_web --base-fields /secure/products-base-fields.json \
  --apply --report /secure/product-import.json

PYTHONPATH=backend python backend/scripts/product_master_verify.py \
  --sha256 --report /secure/product-asset-verification.json
```

导入前全量检查 UUID 有效性、唯一性、记录总数及字段覆盖。每个产品迁移所有非空容器及重复位置，保留能精确关联的 ProductAssets 资产 ID；身份关系不明确时停止，不按 SKU 猜测。资产版本使用独立 ID，不改变既有资产身份。

单个产品文件全部成功、FileMaker modId 未变化才提交该产品；已完成产品不重复导入，失败产品可重跑。导入失败清单非空即退出非零，不能当作完成。重新执行 `product_master_verify.py --sha256` 校验全部被历史版本引用的文件。

迁移程序只从 FileMaker 读取；不自动创建 API 布局、不改字段定义、不改账号权限。

## 环境开关和发布顺序

StarRC：

```dotenv
PRODUCT_MASTER_ENABLED=true
PRODUCT_MASTER_WRITE_ENABLED=false
PRODUCT_MASTER_SOURCE=starrc-products
PRODUCT_MASTER_LAYOUT=@products_web
PRODUCT_MASTER_SCHEMA_PATH=config/product_master_schema.json
PRODUCT_MASTER_USERNAME=<专用服务账号>
PRODUCT_MASTER_PASSWORD=<通过部署密钥注入>
PRODUCT_MASTER_CONSUMERS_JSON={"dms-stock-check":"<至少32字符独立随机密钥>"}
```

先在隔离环境导入并验证。生产切换时冻结旧入口、完成最终迁移校验、锁定原生编辑，再启用主库读取和写 worker。不能在历史迁移未完成时打开主库读取开关。旧图片迁移脚本在主库开启后会拒绝运行，旧 PDA 回写任务也停止写原容器；停用旧对账 timer，等待旧在途任务完成后切换。

DMS 对应部署：

```dotenv
PRODUCT_PUBLICATION_ENABLED=true
PRODUCT_PUBLICATION_SOURCE=starrc-products
PRODUCT_PUBLICATION_URL=https://<同源StarRC域名>
PRODUCT_PUBLICATION_CONSUMER=dms-stock-check
PRODUCT_PUBLICATION_TOKEN=<对应独立随机密钥>
PRODUCT_PUBLICATION_AUTH_MAX_AGE_SECONDS=300
```

服务端核对 FileMaker host/database 指纹。不同 FileMaker 来源直接拒绝，不给 mayako/stock-check 共享来源名。DMS 需要对发布清单内 COS 对象的只读权限；原有对象键不移动。私有桶的读取凭据只留后端。

DMS 先落库事件和游标，再确认 StarRC。旧版本不能覆盖新版本；首次全量追平前或授权副本超过 300 秒未确认追平时，产品目录返回 503，不扩大客户范围。账号授权仍由 DMS 自身会话服务执行，产品范围按明确的 return 分隔 privilege 值精确匹配，缺失权限字段时不展示任何产品。

产品资料、图片及附件可脱离 FileMaker 展示。BOM 和实时库存仍是原业务接口，主资料中的派生库存是最近发布快照，不能当作实时库存接口。

### WebViewer 入口

页面路径为 `/?page=productMaster&productId=<产品UUID>&ctx=<签名上下文>&sig=<签名>`。复用当前签名上下文生成脚本，操作员身份来自已验证会话，不信任 URL 中的姓名。WebViewer 对象可命名为 `wv_product_master`，在 `OnRecordLoad` 与进入产品页时按 `產品::ID` 重载。

保持 FileMaker 原生产品字段只读。产品表单会在未保存离开时提示；FileMaker 脚本切换记录的流程也应保留此提示，不能强制丢弃 WebViewer 页面。完整桌面 Web 在侧栏“产品资料 → 产品编辑”打开同一编辑器。

## 备份、演练与回退

- PostgreSQL 使用独立备份账号及 `.pgpass`。`sh backend/scripts/backup_product_master.sh /absolute/backup/path` 导出全部 `pm_*` 表并校验备份目录。部署时纳入现有每日备份任务；不要把口令写入命令行。
- COS 开启桶版本控制、独立备份/复制策略，禁止自动清理 `product-master/<source>/` 正式对象；只可单独清理过期 staging，且不能影响历史版本引用对象。这是部署基础设施配置，代码不会替用户修改现有桶策略。
- 恢复演练必须恢复到独立 PostgreSQL 数据库，然后执行 `product_master_verify.py --sha256`，抽查当前及历史附件。禁止直接覆盖正在使用的业务库做演练。
- 应用回退先暂停写 worker 和 DMS 拉取，保留主库、版本和文件。恢复旧应用不会自动把 FileMaker 重新提升为主数据来源；未同步变更必须先处理，不能删除新表或回滚 COS 对象。

## 验收与已执行验证

数据库测试覆盖：并发版本冲突、重复创建请求、审计原子性、非法附件回滚、历史文件保留、跨产品绑定拒绝、数据源隔离、FileMaker 离线后续跑、双 worker 顺序、写成功但响应超时恢复、原生 modId 修改冲突、上传摘要及暂存覆写保护。

DMS 测试覆盖：精确客户范围、过期授权拒绝、事件顺序、老版本覆盖拒绝、批次回滚、游标续传、无 FileMaker 的附件读取，以及已有客户目录/会话/UUID 路由回归。前端完成 TypeScript 与生产构建，隔离数据库上的真实浏览器操作已验证保存增长版本、操作人历史和全部容器列表。

尚未验证的生产项目：完整基表覆盖、专用布局可写性、真实容器清空/上传回读、UUID 自动录入规则、原生权限锁定、历史全量文件迁移、正式 DMS 同源配置和备份恢复演练。它们是切换条件，不应使用测试通过来代替。


### 本次验证结果

- StarRC 相关回归：97 项通过；最后补充的权限元数据与默认值回填测试另 2 项通过（隔离 PostgreSQL `product_master_test`）。
- DMS 相关回归：160 项通过，包含原有客户会话与目录测试。
- 两个前端 TypeScript 检查及 Vite 生产构建通过；StarRC 保留现有大包体提示。
- 浏览器使用隔离测试 API 与测试产品，实际保存从版本 1 到 2，历史正确显示操作人；检查全部容器布局。临时 API 与预览已停止，测试页面已移除。
- 生产写开关未打开、生产数据库未迁移。OData 基表元数据读取失败；尝试补充读取本机 FileMaker 时发现 Mac 已锁定，因此未进行原生布局和权限变更。

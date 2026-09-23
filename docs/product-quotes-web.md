# 客户群报价 Web 维护

**2026-09-23：管理员报价 Tab 已上线，当前只读且未导入旧报价。** 最新部署与核验见 [上线记录](product-quotes-release-20260923.md)。下方保留实现及导入说明。

## 行为与边界

产品编辑页的“客户群报价”支持独立新增、编辑、调整客户成员、停用和查看历史。
同一产品、客户、币种只能存在一条启用报价；停用记录保留，多币种分别维护、不换汇。
名称对应原报价名称／权限标识，不代表 Web 账号权限。客户群是每条报价的成员集合，不创建全局共享客户群。

金额通过 API 使用十进制字符串，PostgreSQL 使用 numeric，允许零、不允许负数、空值、非有限值；
最多 20 位整数、12 位小数。客户按目录 ID 选择，不接收浏览器提供的名称或代码。
产品详情和编辑页均以独立“客户群报价”Tab 呈现，仅管理员可见。管理员判定复用系统管理接口的 `canManageAccounts` 权限。
列表、历史、新增、修改接口全部强制管理员校验；仅有价格权限的非管理员不能访问。
读取同时需 `canViewProducts` 与 `canViewPrice`；保存另需 `canEditProductPrices`。
不要求 `canEditProducts`，因此可单独授权价格维护。产品浏览入口保持只读。

报价及历史使用 `pm_quote`、`pm_quote_customer`、`pm_quote_revision`，由 ProductStore 初始化。
保存不会更改产品版本、建立 FileMaker 回写任务或发布 DMS 事件，不接订单取价和客户展示。
页面明确显示这一限制。原 `status` 是历史更新日志，原样保存，不解释为启用状态；导入的有效报价初始启用。

## 接口

所有接口在 `/api/product-master` 下，采用现有内部 WebViewer／Web 登录会话。

| 方法及路径 | 用途 |
| --- | --- |
| `GET /products/{uuid}/quotes` | 报价及当前账号的 writeEnabled |
| `POST /products/{uuid}/quotes` | 新增报价 |
| `PATCH /products/{uuid}/quotes/{quoteId}` | 完整保存单条报价及客户成员 |
| `GET /products/{uuid}/quotes/{quoteId}/history` | 前后快照、操作人及时间 |
| `GET /customers?q=…&offset=…` | 复用现有客户目录搜索，每页 50 条 |

写请求：

```json
{
  "requestId": "d87c0a48-654a-4b59-8f5b-2b57dd71c40d",
  "expectedVersion": 0,
  "title": "经销商组",
  "amount": "12.3456",
  "currency": "USD",
  "enabled": true,
  "customerIds": ["目录返回的客户ID"]
}
```

新增 expectedVersion=0，修改传读取到的版本。原请求重试复用 requestId，内容改变使用新 requestId。
并发修改返回 409 和当前快照；前端保留输入，显式载入最新版本后再编辑。
客户成员、报价和历史同一事务提交。客户端不能更改来源标识或历史原始字段。

## 导入流程

先部署代码并保持 `PRODUCT_QUOTE_WRITE_ENABLED=false`；要求目标数据库已有已核对的
`pm_source`、产品资料和 `pm_reference/customers`。数据源指纹必须与 FileMaker 一致。
使用目标环境的环境变量和数据库连接，以下命令在仓库根目录执行：

```sh
PYTHONPATH=backend python backend/scripts/product_quotes_import.py --report /secure/quotes-preview.json
```

默认仅只读扫描和生成报告，不初始化／修改数据库。报告包含全部有效报价、原始字段、成员和异常，
含商业数据，应限制访问。报告文件初次创建权限为 0600。

2026-09-22 的真实布局及少量记录抽查确认：

- `@ProductPrice.product_id` 存产品 SKU，精确匹配 Web 产品的 `product_sku` 后关联 UUID。
- `@ProductPriceCustomer.ProductPriceID` 对应报价 ID；客户 `code` 精确匹配目录代码。
- `customer` JSON 代码数组与关联成员不一致时报告异常，不自行选择其中一份。
- 币种仅将明确别名 RMB→CNY、NTD→TWD 标准化；原值保留。未知／缺失币种禁止导入。
- 保留来源 ID、recordId、modId、title、customer、status、全部原始字段及成员行；不读取贸易报价表。

扫描两遍核对变化；重复 ID、成员重复、产品／客户匹配不唯一、悬空成员及同客户同币种报价冲突均列入 issues。
有任何异常时 `--apply` 不开始导入。需在源数据或产品／客户目录中完成核对后重新预览，不能通过改报告跳过。

冻结原 FileMaker 报价修改，备份现有数据库；核对报告数量、金额、币种、产品和成员，使用预览输出的 digest：

```sh
PYTHONPATH=backend python backend/scripts/product_quotes_import.py \
  --apply --expected-digest '<预览返回的digest>' --report /secure/quotes-import.json
```

正式导入重新扫描；摘要改变即停止。每条报价原子导入、可续跑；已有来源永不覆盖，来源内容变化进入异常。
完成后逐条比较首次导入版本的产品、标题、金额、币种和客户成员；只有 `complete=true`、issues 为空且
verified=quoteCount 才算完成。Web 后续修改不会被重跑覆盖，核验仍针对首次导入版本。

## 启用、备份与回退

核对完成后，在已有产品主库或产品主库预览存储的环境设置 `PRODUCT_QUOTE_WRITE_ENABLED=true` 并重启后端。
产品资料可以继续保持预览模式，报价保存不依赖 `PRODUCT_MASTER_ENABLED`，也不开放产品基础资料保存。
此开关独立于产品资料回写开关。无需启用 FileMaker 写入或变更 DMS。
旧报价入口作为历史参考，避免继续在两处维护；FileMaker 内可转到现有 WebViewer 产品编辑入口。

`backup_product_master.sh` 的 `pm_*` 备份范围已包含报价及历史。回退只关闭报价写入开关，保留数据；
不要删除报价表或把旧 FileMaker 价格回灌到 Web。

## 验证

```sh
PYTHONPATH=backend PRODUCT_MASTER_TEST_DATABASE_URL='<隔离测试库>' \
  python -m pytest backend/tests/test_product_quotes.py backend/tests/test_product_master.py \
  backend/tests/test_product_api.py backend/tests/test_webviewer_account_access.py -q
cd frontend
npm run build
node scripts/check-product-browser.cjs
node scripts/check-product-quotes.mjs
```

浏览器测试需可用的 Playwright（可通过 PLAYWRIGHT_MODULE 指定包入口），仅使用虚构 API 数据，
绑定 127.0.0.1:5187，完成后关闭。覆盖保存、刷新、客户成员、停用、历史、离开保护、冲突保留输入和写入关闭；
数据库测试单独覆盖实际事务、并发、权限、导入预览／应用／核验／重跑。

尚未执行正式迁移或生产发布。本地运行的业务库未建立产品主库表，不能作为真实报价导入目标。

本次验证：隔离 PostgreSQL 报价测试 30 项通过；相关产品主库、产品读取和账号权限回归通过。
TypeScript、Vite 生产构建及 Chromium 浏览器操作验收通过，768px 宽度无整页横向溢出。
真实 FileMaker WebViewer 宿主内的验收须在部署后进行；本次没有发布前后端或开启生产报价保存。

# 产品实时成本与关联售价

## 原生公式核对（2026-09-23）

已在 FileMaker Pro「管理数据库 → 產品 BOM → 字段」只读核对，退出时取消，未修改定义。

- `成本x需求數量 = 產品BOM_成本::單位成本 * 需求成本計算數量`
- `產品成本計算`：合计字段，总计 `成本x需求數量`。
- `產品成本 = (產品成本計算 * (1 + 產品::成本加成 / 100)) + 產品::組裝成本 + 產品::其他成本估價`
- `產品成本合計 = 產品成本 + 產品::包裝總工錢`
- `計算美金 = ((產品成本 + 產品::包裝總工錢) / 產品::匯率) + 產品::提成 + 產品::提成B`

其中 `產品成本`、`計算美金` 是未存储计算。页面 RMB 成本对应 `產品成本`，**不含包装总工钱**；美金成本包含包装总工钱、A/B 积分。

## 实时成本

Web 打开产品时读取一次；「刷新成本」再次调用 `GET /api/product-master/products/{UUID}/costs`。
后端根据已迁移产品的 FileMaker recordId，在「产品报价」布局的产品关联上下文读取
`產品 BOM::產品成本` 和 `產品 BOM::計算美金`，禁用门户返回，不复制 BOM 公式或人工换汇。
核对 SKU 和系统编号后，仅返回两项成本、源计算异常及读取时间。

成本不保存进 PostgreSQL、不进入产品修改历史或回写队列。响应 `Cache-Control: no-store`。
刷新不影响当前表单草稿；采用 FileMaker **已保存**的基础参数，不计算尚未保存的 Web 草稿。
读取失败清除旧结果并提示重试；源字段 `?` 等计算异常显示说明，不转换成零。
无 `canViewProducts` 或 `canViewPrice` 权限时返回 403，前端不发请求或显示按钮。

这是用户明确要求的实时读取例外；普通产品、图片、售价仍从 Web 数据库/COS 获取。
产品主表 `opencost` 是文本，保留为「原始成本备注」，不作为 RMB 成本。

## 售价映射和导入

| Web 字段 | FileMaker 布局 `@產品售價` 的字段 |
| --- | --- |
| EX-Price | `Price` |
| 台幣出廠 | `台灣售價` |
| RMB出廠 | `RMB售價` |

产品主表 `Retail_Price_USD` 保持原绑定，不替换成售价表的 `零售價`。
按产品 SKU / 系统编号精确匹配 `產品編號`，只接受唯一售价记录及唯一 Web 产品归属。
重复或多产品共用关联不任选一条；无记录显示空，不自动创建关联行。
新字段要求 `canViewPrice`；售价保存另要求 `canEditProductPrices`，沿用产品保存权限，不发布给 DMS。
金额从 FileMaker 成功响应开始采用 Decimal，Web 存储和接口采用十进制字符串。

```sh
# 只读预览；全量仅扫描售价布局两遍，不读取或保存成本
PYTHONPATH=backend python backend/scripts/product_finance_import.py --bulk --report /secure/prices-preview.json
# 备份 pm_* 后应用；重新扫描两遍核对完整性和源变化
PYTHONPATH=backend python backend/scripts/product_finance_import.py --bulk --apply --report /secure/prices-import.json
```

支持 `--sku`、`--offset`、`--limit`；默认覆盖当前 Web 产品。
唯一有效记录独立导入；异常写入报告，完整性看 `complete`、应用数量和异常项。
来源快照、recordId/modId 和关联编号保存在 `pm_reference` 的 `product-finance:<UUID>`，三项售价进入产品版本和历史。
已有来源重跑跳过；`--refresh` 仅重新核对，不自动覆盖改过的 Web 值或变化的 FileMaker 售价源。
报告含商业信息，初建权限 0600，应保存在受限目录。

## 后续售价回写

复用产品审计及持久化同步队列，产品主表写入排除 externalSource 字段。
只改售价时不触发主表更新。回写前重新检查独立售价记录的唯一关联、recordId、modId 和普通数字字段定义，
PATCH 仅含变更的售价字段并带 modId；读回实际值后才标记同步成功。
持久化发送意图允许断线重试确认已成功的写入；无法确认或原生版本冲突则停止覆盖。
成本计算字段不可编辑或回写；基础 BOM/汇率等修改后点刷新查看。

生产保存/回写保持原开关状态，本功能不自动开启。后续启用仍需满足专用账号、基表核验、原生编辑锁等现有检查。
生产 FileMaker 未做试写；回写验证来自隔离 PostgreSQL 与模拟 API。

## 首次保存售价：新建「產品售價」记录（2026-09-24）

导入时 FileMaker 里确实没有售价记录的产品（快照 `price` 为空，约 4,735 个）现在可以在编辑页直接填写
EX-Price / 台幣出廠 / RMB出廠。保存并回写时：

- 前置条件：该产品已有核对过的空来源快照（`financePriceCreatable`）；SKU / 系统编号存在，且不被其他 Web 产品占用。
  没有快照的异常产品（重复、多条、金额无效等）仍不可编辑，不自动择一。
- 回写前重新按 SKU / 系统编号查找 `@產品售價`：已出现记录则停止（DriftError），不覆盖、不重复新建。
- 校验布局字段：`產品編號` 为普通文本、三个售价为普通数字、非全局、非重复。
- 先持久化「新建意图」再发 POST，只发送非空的变更字段，`產品編號` 取系统编号（缺省用 SKU）。
- 新建后回读该记录，并从原生「产品报价」布局读回 `產品售價::Price / 台灣售價 / RMB售價`，确认这条记录确实关联到本产品；
  关联不上则报错停止，已新建的记录保留待人工核对。
- 进程中断后重试：按编号找到内容与意图完全一致的记录才接管，绝不重复新建。
- 成功后更新 `pm_reference` 快照（价格记录 recordId/modId、三项售价）。

FileMaker 侧前提：`@產品售價` 布局含 `產品編號`、`Price`、`台灣售價`、`RMB售價`（已具备）；回写专用账号对该表有创建与编辑权限；
`產品::系統產品編號`（或 `product_sku`）与 `產品售價::產品編號` 是关联条件，`产品报价` 布局包含这三个 `產品售價::` 关联字段。

## 验证与源数据核对

- 后端相关测试 111 项通过，包含独立 PostgreSQL 下的售价回写流程和实时成本接口权限/失败处理。
- 前端构建、8 项只读浏览检查、刷新成功/失败及无价格权限检查通过。
- 已检查 390 / 1068 / 1440px、亮/暗六种布局；截图在 `artifacts/product-finance-ui/`。
- 25,228 个 Web 产品中，20,204 个匹配唯一有效售价来源，4,735 个无售价记录，289 个待核对。
- 异常分类：162 个售价编号同时匹配多个 Web 产品；48 个产品匹配多条售价记录；79 个有无效金额。
- 因此当前数据不能按全局一对一关系处理；异常项不自动择一、合并或换算。
- 实际读取 `1.ROGT.SP2.BL`：RMB `247.633656`，USD `37.5202509090909091`。
- `JQB0777` 的 FileMaker 美金计算返回异常；Web 显示说明，RMB 正常返回。

## 上线记录（2026-09-23）

已部署 `starrc-backend:product-finance-20260923`、`starrc-frontend:product-finance-20260923`。
内外网健康检查通过，公网入口 HTML 与本次构建一致，未登录成本接口返回 401。
线上连续两次成本读取返回不同读取时间，均含 `Cache-Control: no-store`。

导入累计完成 24,939 个产品（20,204 个唯一售价绑定、4,735 个空来源）；289 个异常保留不动。
数据库逐字段对比来源快照差异为 0，持久化成本记录为 0，本次产生的待回写任务为 0。
产品主库写入、FileMaker 回写及客户群报价写入开关保持关闭；预览保持开启。

服务器备份与报告目录：`/opt/starrc-filemaker/releases/product-finance-20260923/`。
`backup/product-master.dump` 是导入前 pm_* 自定义格式备份（已核验可列举归档），报告为
`prices-preview.json` / `prices-import.json`，目录和文件限制访问。
导入曾为优化 UUID 索引读取中断后恢复，最终报告本轮 applied=23,252、unchanged=1,687；合计 24,939。
价格映射和原始公式均未写入或修改 FileMaker。

## 标准镜像发布（2026-09-23 晚，`f8e6fc1`）

上述 `product-finance-20260923` 镜像构建后源码又有修改，生产运行的不是已提交代码。功能代码已提交为
`f8e6fc13edc951ffab79e6f3bb48d3874e1e9c02`（17 个文件）并推送 `origin/main`，随后用提交源码重新构建并发布标准
日期-SHA 镜像，替换非标准标签：

- `starrc-backend:20260923-f8e6fc1`（继承 `starrc-backend:20260923-2d13b34`，覆盖 `backend/app`、`config`、`scripts`）
- `starrc-frontend:20260923-f8e6fc1`（继承 `starrc-frontend:20260923-c1cdbbd`，覆盖 `dist/`）

发布前复核：隔离 PostgreSQL 下后端测试 78 项全部通过（`test_product_finance.py` + `test_product_master.py`）；
前端 tsc + vite 构建通过；Playwright 财务字段检查（权限过滤、3 宽度 × 2 主题）通过。

容器变化：backend `ea9c91f067bb` → `5dc3b3d24e16`；frontend `557f92b541ef` → `c25af749f001`；
postgres `f196c32c514b` 保持不变。

发布后验证：内外网 `healthz` 均 `ok: true`；公网 `index.html` SHA-256 `72a3e7a8…fe698`、
`assets/App-r1Sps9Zu.js` SHA-256 `0b9a2f66…e023`，均与本地构建逐字节一致；
未登录 `GET /api/product-master/products/{id}/costs` 返回 401（路由存在、权限生效）。

服务器发布目录：`/opt/starrc-filemaker/releases/20260923-f8e6fc1/`
（`backup/previous-release.yml`、`backup/previous-src.tar.gz`、`build/`、`release.yml`、`containers.txt`、`health.json`）。
注意：`product-finance-20260923` 运行的是未提交工作树，`previous-src.tar.gz` 只含该版本实际部署的
`backend/` + `dist/` + 两个 Dockerfile（不含前端源码）；回退以镜像仓库中保留的
`starrc-backend:product-finance-20260923`、`starrc-frontend:product-finance-20260923` 为准。

回退步骤：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260923-f8e6fc1/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps --no-build backend frontend
```

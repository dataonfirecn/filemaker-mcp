# FileMaker 产品图片与 COS 定时对账设计

## 1. 背景与目标

PDA 只读取 COS 图片，不回退下载 FileMaker 容器。当前历史图片迁移分为两段：

1. `@products` 容器复制到 `ProductAssets`。
2. `ProductAssets.asset_file` 上传到腾讯 COS。

这两段目前是手工离线脚本，不会持续处理后续新增或替换图片。现有脚本还会在目标记录或 COS 对象已存在时直接跳过，因此不能可靠识别同一图片槽位的内容替换。

定时对账需要达到以下目标：

- FileMaker 新增产品图后，在每天的下班后对账中同步，并在次日上班前可由 PDA 显示。
- FileMaker 替换产品图后，COS 和 PDA 能更新到新版本。
- 服务重启、网络失败或 FileMaker 短时不可用后可以自动续跑。
- 同一来源图片不会重复创建 `ProductAssets` 记录。
- PDA 请求路径始终只读取 `ProductAssets` 元数据和 COS，不读取容器字节。
- 图片删除先做可恢复标记，不在第一阶段自动删除 COS 对象。

## 2. 数据范围和权威来源

| 数据 | 权威来源 | 说明 |
| --- | --- | --- |
| 图片是否存在及原始内容 | FileMaker `@products` | `檔案 1 | 容器` 至 `檔案 15 | 容器` |
| 图片业务元数据 | FileMaker `ProductAssets` | 产品、槽位、类型、排序、同步状态 |
| PDA 图片内容 | 腾讯 COS | PDA 只获取签名 COS URL |
| 执行批次、重试状态 | 后端数据库 | 不依赖 FastAPI 进程内存 |

槽位分类保持现有规则：

- 1–10：`product_image`
- 11–15：`packaging_reference`

每个来源槽位使用稳定幂等键：

```text
@products:{source_record_id}:檔案 {slot} | 容器
```

## 3. 总体架构

```text
FileMaker @products
        │
        │ 每天下班后全量对账
        ▼
ProductAssetReconciliationWorker
        │
        ├── 比较来源 modId 与已同步版本
        ├── 下载发生变化的容器
        ├── 计算 SHA-256
        ├── upsert ProductAssets
        ├── 上传并 HEAD 校验 COS
        └── 写入状态、指标和审计日志
        │
        ▼
GET /api/orders/products/{sku}/detail
        │
        ▼
PDA 只加载签名 COS URL
```

建议新增一个常驻 `ProductAssetReconciliationWorker`，在 FastAPI lifespan 中与现有 callback、RAG 等 worker 一起启动和停止。离线迁移脚本保留，作为人工修复和批量回填工具，但与 worker 共用同一套同步服务函数。

## 4. 调度策略

### 4.1 每日下班后全量对账

- 默认每天 `21:30 Asia/Shanghai` 执行一次，时间可通过环境变量调整。
- 每次扫描全部 `@products`，不依赖修改时间游标，因此不会因为时间戳、批量导入或 Data API 写入而漏单。
- 每批最多 200 条产品，按 `recordId` 稳定分页。
- 全量扫描只读取记录字段和容器 URL，不默认下载所有容器。
- 当满足以下任一条件时才下载容器：
  - `ProductAssets` 记录不存在；
  - COS `HEAD` 不存在；
  - 来源 `modId` 与上次记录不同；
  - 上次状态为失败或待重试；
  - 管理员要求强制校验。
- 对已同步资产执行 COS `HEAD` 校验；只有缺失或来源版本变化时才重新下载、上传。
- 一轮未处理完时持续运行到完成，不等待第二天。
- `21:30` 之后新增的图片进入下一天的对账批次；如有紧急需要，可由管理员手动触发一次对账。

### 4.2 当晚重试

当晚失败任务采用退避：

```text
1 分钟 → 5 分钟 → 15 分钟
```

- 每次对账最多自动尝试 3 次。
- 达到上限后保留为 `failed`，显示在管理状态接口中，并在下一天的全量对账再次处理。
- 认证失效、FileMaker 429/5xx、COS 429/5xx 和网络错误可重试。
- 文件过大、不支持的 MIME、来源字段非法等数据错误不做高频重试。

## 5. 对账状态机

```text
discovered ──► syncing ──► synced
     │             │
     │             └────► retry_wait ──► syncing
     │                           │
     └──────────────────────────► failed

synced ──来源清空──► source_removed
```

`ProductAssets.migration_status` 为兼容现有读取逻辑，成功后仍写 `copied`。更细的执行状态保存在后端对账表中。

建议新增后端表 `product_asset_sync_jobs`：

| 字段 | 用途 |
| --- | --- |
| `id` | 任务主键 |
| `migration_key` | 来源记录与槽位唯一键 |
| `source_record_id` | `@products` recordId |
| `product_sku` | 产品编号 |
| `slot` | 1–15 |
| `source_mod_id` | 扫描时 FileMaker modId |
| `source_updated_at` | 来源修改时间 |
| `content_sha256` | 实际下载内容摘要 |
| `file_size` | 文件大小 |
| `mime_type` | 文件类型 |
| `product_asset_record_id` | 对应 ProductAssets recordId |
| `asset_id` | ProductAssets UUID |
| `cos_object_key` | COS Key |
| `cos_etag` | 上传后 ETag |
| `status` | discovered/syncing/synced/retry_wait/failed/source_removed |
| `attempt_count` | 尝试次数 |
| `next_attempt_at` | 下次重试时间 |
| `last_error` | 脱敏后的错误 |
| `claimed_at` / `claimed_by` | 防止并发重复处理 |
| `created_at` / `updated_at` | 审计时间 |

唯一约束：

```text
UNIQUE(migration_key)
```

另外增加 `product_asset_reconciliation_runs`，保存每日执行批次、开始时间、结束时间、扫描数量、成功数量和失败数量。

## 6. 单个槽位的处理算法

1. 读取来源记录的 `recordId`、`modId`、SKU 和 15 个容器字段。
2. 对每个槽位生成 `migration_key`。
3. 来源为空：
   - 没有历史资产则跳过；
   - 有历史资产则标记 `source_removed`，让 API 停止下发；
   - 第一阶段不删除 COS，保留 30 天以便恢复。
4. 来源非空且没有 `ProductAssets`：创建 `ProductAssets` 元数据记录。
5. 来源 `modId` 未变化、任务已 `synced` 且 COS `HEAD` 正常：跳过。
6. 否则下载 FileMaker 容器，限制来源主机、最大字节数和重定向目标。
7. 计算 SHA-256：
   - 与上次摘要一致：只修正元数据和状态；
   - 不一致：上传 COS。
8. 上传完成后执行 `HEAD`，核对长度、MIME 和 ETag。
9. 更新 `ProductAssets`：`source_mod_id`、文件名、MIME、大小、`migration_status=copied`。
10. 更新对账任务为 `synced`，记录耗时、字节数和审计日志。

替换图片时继续使用同一个 `ProductAssets` 记录，避免出现重复主图。COS Key 可继续使用现有的 `source_record_id + asset_id` 规则；如果扩展名改变，记录新 Key，并将旧 Key 放入延迟清理队列。

## 7. 并发、幂等与进程安全

- 默认 FileMaker 容器下载并发 2，COS 上传并发 4。
- 单个产品的 15 个槽位串行或最多并发 2，避免给 FileMaker Server 造成突发压力。
- 任务认领使用数据库原子更新，过期 claim 30 分钟后可重新认领。
- 如果以后启动多个后端副本，调度器需要 PostgreSQL advisory lock 或等效分布式锁，确保同一时刻只有一个扫描器；worker 可以多实例消费任务。
- 上传前后都以 `migration_key + content_sha256` 判断幂等。
- 服务关闭时停止认领新任务，等待正在上传的任务完成或归还 claim。

## 8. 配置项

```text
PRODUCT_ASSET_RECONCILIATION_ENABLED=false
PRODUCT_ASSET_RECONCILIATION_SCHEDULE_TIME=21:30
PRODUCT_ASSET_RECONCILIATION_TIMEZONE=Asia/Shanghai
PRODUCT_ASSET_SCAN_BATCH_SIZE=200
PRODUCT_ASSET_DOWNLOAD_CONCURRENCY=2
PRODUCT_ASSET_UPLOAD_CONCURRENCY=4
PRODUCT_ASSET_MAX_FILE_BYTES=104857600
PRODUCT_ASSET_MAX_ATTEMPTS_PER_RUN=3
PRODUCT_ASSET_SOURCE_REMOVAL_RETENTION_DAYS=30
```

生产环境默认先关闭，通过显式环境变量启用。

## 9. 状态接口与告警

新增管理员只读接口：

```text
GET  /api/webviewer/admin/product-asset-reconciliation/status
GET  /api/webviewer/admin/product-asset-reconciliation/failures
POST /api/webviewer/admin/product-asset-reconciliation/run
POST /api/webviewer/admin/product-asset-reconciliation/retry/{job_id}
```

状态至少包含：

- 最近一次计划执行和手动执行的开始、结束时间；
- 当前执行批次、进度和预计剩余数量；
- 待处理、重试、失败数量；
- 本次新增、替换、跳过、失败数量；
- 本次总耗时和平均单张处理时间；
- FileMaker 下载和 COS 上传字节数；
- 最近 20 条脱敏错误。

告警建议：

- 次日 `07:00` 仍没有成功完成前一晚的对账；
- 次日 `08:00` 对账仍处于运行状态；
- 当晚对账完成后 `failed` 非零；
- FileMaker 或 COS 连续 5 次不可用；
- 当晚全量扫描意外中断。

## 10. 历史回填与上线顺序

### 阶段 A：只读审计

1. 建表、worker 和状态接口，但保持上传关闭。
2. 执行一次全量扫描，输出以下集合：
   - FileMaker 有图但 ProductAssets 缺失；
   - ProductAssets 有记录但 COS 缺失；
   - 来源已清空但镜像仍存在；
   - 重复 migration_key。
3. 核对 F0175 必须落入“ProductAssets 有记录但 COS 缺失”。

### 阶段 B：小批量写入

1. 先同步 F0175。
2. 再同步 100 条缺失资产。
3. 验证 PDA、COS ETag、ProductAssets 元数据和 FileMaker 压力。

### 阶段 C：历史全量回填

- 并发从 2 开始，根据 FileMaker 响应时间逐步提升到 4。
- 以批次记录成功、失败和字节量，可中断、可续跑。
- 不因为单个文件失败停止整批。

### 阶段 D：持续对账

1. 启用每天 `21:30` 的全量对账。
2. 连续观察 7 个工作日的完成时间和 FileMaker 压力。
3. 稳定后再考虑启用延迟删除。

## 11. 测试与验收

必须覆盖：

- `21:30` 前新增槽位图片，当晚对账完成后 PDA 可见。
- `21:30` 后新增槽位图片，下一晚对账完成后 PDA 可见。
- 替换同一槽位图片，PDA 显示新内容且 ProductAssets 不重复。
- 上传相同文件不会重复写 COS。
- 清空槽位后停止下发，但 COS 暂不物理删除。
- FileMaker 断线、COS 超时、服务重启后自动恢复。
- 全量分页期间新增修改即使未进入本次快照，也会在下一天对账中补齐。
- 两个 worker 同时认领时同一任务只处理一次。
- 超大文件、非法 MIME 和错误来源 URL 被拒绝并记录原因。
- 已由 PDA 直传 COS 的图片不会被重复迁移。
- PDA 产品详情请求过程中不下载 FileMaker 容器。

验收指标：

- 正常同步成功率不低于 99.5%。
- 每天对账在次日 `07:00` 前完成。
- 当晚全量结束后，除明确失败项外，FileMaker 有图、ProductAssets、COS 三方一致。
- 连续重复运行对账不新增重复记录、不重复上传相同内容。

## 12. 实施边界

第一版不做：

- 自动物理删除 COS 对象；
- PDA 回退读取 FileMaker 容器；
- FileMaker 直接保存 COS SecretId/SecretKey；
- 对非图片容器文件的自动迁移；
- 自动压缩或转换原图。

FileMaker 仍是原始图片权威来源，COS 是 PDA 的高性能读取镜像。所有 COS 凭据只保留在后端。

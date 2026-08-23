# StarRC 夜间 LLM 维护任务

StarRC 后端包含三项只读优先的夜间任务。生产 Docker Compose 已默认启用，时区为
`Asia/Shanghai`，报告和索引数据库保存在 `/data` 持久卷中。

## 时间表

| 时间 | 任务 | 输出 |
|---|---|---|
| 00:00 | RAG 索引刷新及增量 Embedding | `/data/rag_index.db` |
| 00:30 | 前一日失败、澄清、零结果与别名分析 | `/data/nightly-reports/YYYY/MM/DD/query-analytics-YYYY-MM-DD/index.html` |
| 01:30 | 权限与敏感数据红队回归 | `/data/nightly-reports/YYYY/MM/DD/security-red-team-YYYY-MM-DD/index.html` |

调度器会记录每天的执行状态，容器重启后不会重复执行同一天已经尝试过的任务。
如果服务在计划时间之后启动，会在 `NIGHTLY_MAINTENANCE_CATCHUP_HOURS` 窗口内补跑。

## 安全边界

- 红队任务只使用虚构编号和价格、成本、报价哨兵，不读取 FileMaker 真实记录。
- 查询分析只读取 StarRC 已保存的问答日志，并写入归一化统计和 HTML 报告。
- RAG 刷新只调用 FileMaker 读取接口；Embedding 发送到配置的 LM Studio 服务。
- 夜间任务不会修改价格、权限、BOM、客户或产品记录。
- LM Studio 原生 `/api/v1/chat` 被用于归一化，并明确设置 `reasoning: off`。

## 报告中心和 Dashboard

夜间任务会同时写入两类产物：

- 服务器目录中的 `index.html` 和 `report.json`，通过临时文件加原子替换发布。
- `app.db` 中的 `nightly_reports`、`nightly_report_metrics` 和
  `nightly_report_exceptions`，供搜索、筛选和 Dashboard 汇总使用。

内部工作台侧边栏的“运营报告 → 报告中心”支持关键词、状态、类型和日期范围查询。
完整 HTML 通过鉴权接口读取，再放入禁止脚本运行的 sandbox iframe 中预览；服务器真实路径
不会暴露给浏览器。工作台首页 Dashboard 会读取每类报告的最新一次结果，汇总运行状态、
重要指标、异常和最近 14 天趋势。

每份报告发布完成后，还会向 `NIGHTLY_REPORT_EMAIL_RECIPIENTS` 发送多段邮件：纯文本作为
兼容后备，HTML 正文直接嵌入报告状态、数据完整度、核心指标、重要异常和报告中心入口。
投递结果写入 `nightly_report_deliveries`；同一报告和收件人的成功邮件不会重复发送，临时失败
最多重试 `NIGHTLY_REPORT_EMAIL_MAX_ATTEMPTS` 次。邮件失败只影响投递状态，不会删除报告，
也不会把已经成功的夜间数据处理标记为失败。

报告接口均要求有效的内部员工会话：

```text
GET /api/reports
GET /api/reports/dashboard?days=14
GET /api/reports/{report_id}
GET /api/reports/{report_id}/html
```

## 关键配置

```dotenv
NIGHTLY_MAINTENANCE_ENABLED=true
NIGHTLY_MAINTENANCE_TIMEZONE=Asia/Shanghai
NIGHTLY_REPORTS_DIRECTORY=/data/nightly-reports
NIGHTLY_QUERY_ANALYTICS_SCHEDULE_TIME=00:30
NIGHTLY_SECURITY_RED_TEAM_SCHEDULE_TIME=01:30
NIGHTLY_SECURITY_RED_TEAM_CONCURRENCY=4
NIGHTLY_SECURITY_RED_TEAM_TIMEOUT_SECONDS=180
NIGHTLY_REPORT_EMAIL_ENABLED=true
NIGHTLY_REPORT_EMAIL_RECIPIENTS=dataonfiresz@gmail.com
NIGHTLY_REPORT_EMAIL_PUBLIC_URL=https://starrc.dataonfire.cn/?page=reports
NIGHTLY_REPORT_EMAIL_MAX_ATTEMPTS=3

RAG_INDEX_REFRESH_SCHEDULE_TIME=00:00
RAG_EMBEDDING_ENABLED=true
RAG_EMBEDDING_MODEL=text-embedding-nomic-embed-text-v1.5
RAG_EMBEDDING_BASE_URL=http://121.10.201.189:15123/v1
RAG_EMBEDDING_BATCH_SIZE=32
RAG_EMBEDDING_MAX_RECORDS_PER_RUN=20000
RAG_EMBEDDING_QUERY_ENABLED=true
```

邮件复用现有 SMTP 配置：

```dotenv
CUSTOMER_SMTP_HOST=smtp.example.com
CUSTOMER_SMTP_PORT=587
CUSTOMER_SMTP_USERNAME=mailer@example.com
CUSTOMER_SMTP_PASSWORD=<SMTP password>
CUSTOMER_SMTP_FROM_EMAIL=mailer@example.com
CUSTOMER_SMTP_STARTTLS=true
CUSTOMER_SMTP_SSL=false
```

SMTP 密码只能放在服务器 `.env`，不得写入 Compose、Git 或前端代码。

`RAG_EMBEDDING_API_KEY` 可以单独配置；留空时后端依次复用
`LM_STUDIO_API_KEY` 和 `LLM_API_KEY`。不要把真实密钥提交到 Git。

## 增量规则

每条 RAG 记录保存内容 SHA-256。只有新记录或内容哈希发生变化的记录会重新请求
Embedding；删除的 RAG 记录会同时删除对应向量。检索采用关键词和向量混合排序，
中文查询会先生成短语片段，精确编号和关键词匹配优先于纯向量相似度。

部署代码后可在 RAG 状态接口查看：

- `embeddingEnabled`
- `embeddingModel`
- `embeddingCount`
- `embeddingPending`

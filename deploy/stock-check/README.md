# Stock Check 外部客户平台部署

该 Compose 项目与内部 StarRC 部署完全分离：独立容器、网络、数据库、数据卷、登录密钥和客户账号。

- 宿主机入口：`127.0.0.1:8999`
- 对外域名：`https://stockcheck.net`
- 客户页面：`/customer-chat`
- 允许 API：`/api/customer-chat/login`、`/me`、`/query`、`/change-password`，管理员问答分析接口，鉴权后的出货单/产品/零件目录，以及产品/零件按需图片和产品多图 Gallery
- 登录后的账号安全页：`/customer-chat/account/password`。用户输入一次当前密码和两次新密码即可修改；新密码至少 12 位。密码以 PBKDF2 哈希写入持久化 `/data/app.db`，修改后旧会话立即失效。
- 出货单范围：按账号配置的 FileMaker `select_client_for_web_id` 限定，且 `訂單 PO` 非空
- 出货单对话：支持单号、物流、追踪号、备注、安全隐藏字段及多种日期范围；FileMaker 布局要求见 `docs/stock-check-order-chat-filemaker-requirements.md`
- 产品与零件目录范围：按账号配置的 FileMaker 目录客户 ID 限定
- Web 客户代码：按客户配置，用于订单范围及客户关联的零件图片校验
- 其他内部页面和 `/api/*`：由客户 Nginx 直接返回 404
- 后端不映射宿主机端口，只能由同项目的客户前端访问
- 每个门户账号通过 `CUSTOMER_CHAT_ACCOUNTS_JSON[].accessRole` 选择固定权限集：
  `admin` 可访问全部内容与账号管理，`manager` 可查看价格与订单，`team` 可查看订单
  但后端不返回单价、订单金额或运费金额，`agent` 只允许产品与零件库存查询。
  成本、报价及其他内部财务字段对所有账号保持关闭。
- `accessRole=admin` 的管理员账号可访问
  `/customer-chat/admin/analytics`。所有问答、失败、拦截原因和聚合问题保存在独立
  PostgreSQL 中；标记为回归测试的流量默认不进入管理员运营视图。
- 管理员账号可访问 `/customer-chat/admin/accounts`，启用或停用账号、切换 4 种权限集，
  批量停用账号，并查看最近成功登录、最近登录尝试以及成功/失败次数。每个账号可保存邮箱；
  配置 `CUSTOMER_SMTP_*` 后，创建账号或重设临时密码时可直接发送登录信息。运行时权限和
  逐次登录事件保存在 PostgreSQL；权限改变或账号停用后，已有会话立即失效。
- 管理员可在 `/customer-chat/admin/accounts` 的“Stock Check default customer configuration”区域查看和修改
  客户显示名、目录客户 ID、Web 客户代码和出货公司群组 ID。这份共享配置保存在 PostgreSQL
  `customer_portal_config`；保存后会同步所有账号并使现有会话失效。`.env` 账号中的范围只在
  第一次初始化配置时作为种子，后续重启不会覆盖管理员保存的值。

生产环境在服务器 `/opt/stock-check/.env` 保存实际密钥，不应提交版本库。

从旧部署目录迁移时，先把原 `.env` 中的 `MAYAKO_*` 镜像和数据库变量改为
`STOCK_CHECK_*`。为了继续使用原 PostgreSQL 与 SQLite 数据，不复制数据卷也可以：把下面
两个变量设置为 `docker volume ls` 查到的旧物理卷名，并保持旧数据库名、用户名和密码值不变。

```dotenv
STOCK_CHECK_POSTGRES_VOLUME=starrc-mayako_mayako_postgres_data
STOCK_CHECK_BACKEND_VOLUME=starrc-mayako_mayako_backend_data
STOCK_CHECK_POSTGRES_DB=starrc_mayako
STOCK_CHECK_POSTGRES_USER=starrc_mayako
```

这些旧物理标识仅用于挂载现有生产数据；新部署默认创建 `stock-check-*` 数据卷和
`stock_check` 数据库。

SMTP 最少需要 `CUSTOMER_SMTP_HOST` 与 `CUSTOMER_SMTP_FROM_EMAIL`。需要认证时同时填写
`CUSTOMER_SMTP_USERNAME` 和 `CUSTOMER_SMTP_PASSWORD`；端口、STARTTLS 与 SSL 选项见
`.env.example`。未配置时账号仍可正常创建，页面会禁用邮件发送选项。

```bash
cd /opt/stock-check
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8999/healthz
```

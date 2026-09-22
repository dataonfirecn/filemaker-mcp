# 2026-09-21 产品编辑生产发布记录

## 已完成

- 生产入口 `https://starrc.dataonfire.cn` 已发布产品编辑前后端。
- FileMaker 新建 `@products_web_api`，来源 `產品`，包含 175 个字段、42 个容器，全部重复次数为 1；该 API 布局已从浏览模式的布局菜单隐藏。
- 原生「管理数据库」逐项采集 175 个基表字段，与 API 元数据的排序名称集合完全一致。清单保存在 `backend/config/product_master_base_fields.json`，注册表记录独立校验依据。仍未把原生编辑锁定和 UUID 新建验证标志改为 true。
- 生产只读预检完成：25,233 条产品，UUID 均有效、唯一，没有遗漏或未登记字段。此结果不是附件迁移完成证明。
- FileMaker 实测 `产品报价 → 编辑` 打开当前产品 `036-EX01`，UUID `2a765709-294e-41e7-9fab-65bd28e1afb5`。已显示详细字段、图片与附件、修改历史、同步状态，未再跳回工作台。
- 迁移预览只读：后端拒绝所有主库写接口，不返回 FileMaker 临时容器链接；按原账号权限过滤价格，并明确显示容器待迁移状态。
- 新增的预览权限隔离测试通过，产品主库测试 25 项通过，前端 TypeScript 和生产构建通过。

## 生产位置与回退

运行目录：`/opt/starrc-filemaker/current`。

此次镜像：`starrc-backend:product-master-20260921-preview`、`starrc-frontend:product-master-20260921-preview`。增量镜像继承已运行的生产镜像，保留运行依赖及 Nginx 配置。

Compose 使用原来的 `deploy/starrc/docker-compose.yml` 加服务器上的 `deploy/starrc/product-master.release.yml`；后续部署必须保留该覆盖文件或将其配置显式迁回主部署配置，不得漏掉覆盖文件导致静默回退。

当前覆盖设置：

```dotenv
PRODUCT_MASTER_PREVIEW_ENABLED=true
PRODUCT_MASTER_ENABLED=false
PRODUCT_MASTER_WRITE_ENABLED=false
PRODUCT_MASTER_SOURCE=starrc-products
PRODUCT_MASTER_LAYOUT=@products_web_api
PRODUCT_MASTER_SCHEMA_PATH=config/product_master_schema.json
```

服务器本地备份目录 `/opt/starrc-filemaker/releases/product-master-20260921/backup`，含环境、Compose 和 PostgreSQL dump，已通过 `pg_restore -l` 校验。SQLite 使用在线 backup 保存到后端数据卷 `/data/app-before-product-master-20260921.db`。

旧镜像保留为 `starrc-backend:before-product-master-20260921` 和 `starrc-frontend:before-product-master-20260921`。应用回退只切换镜像，不能删除迁移数据、版本历史或 COS 文件。

## 正在执行及未完成

初始迁移曾因旧资产关联冲突退出；新版已修复并恢复后台 `docker exec`，参数 `--layout @products_web_api --base-fields /app/config/product_master_base_fields.json --apply`。仅新建 Web 产品副本及不可变 COS 对象，不回写 FileMaker。

- 预检结果：后端数据卷 `/data/product-master-preflight-20260921.json`。
- 导入结果：完成后生成 `/data/product-master-import-20260921.json`。
- 迁移日志：服务器 `/opt/starrc-filemaker/releases/product-master-20260921/migration.log`。
- 后端重启会终止这个初始导入进程；需用同一来源和参数重跑，已提交产品不会重复导入。不能仅凭进程启动或产品数量宣称迁移完成。

正式保存尚未开放：后台回写账号使用方式仍待用户明确；还需完成附件迁移核验、原生员工编辑入口切换、UUID 新建回读验证。页面与原生布局均保留待启用提示。DMS 未切换到新产品展示库。

自动审批拒绝将生产代码复制到本机临时目录。本次改用服务器端 SHA-256 清单比对和原机备份，没有复制生产源代码或环境文件到本机。

后续页面重构、容器修复及最新镜像信息见 [产品编辑重构记录](product-master-editor-20260921.md)。

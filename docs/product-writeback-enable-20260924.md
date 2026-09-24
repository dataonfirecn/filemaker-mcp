# 产品资料回写开启清单（2026-09-24，小范围测试）

## 代码状态

- `backend/config/product_master_schema.json`：`nativeEditingLocked=true`、`uuidCreateVerified=true`（按用户确认登记；
  这两项描述 FileMaker 侧的实际状态，上线前请确认原生产品字段已对普通员工锁定、UUID 新建回读已在 QA 产品验证）。
  `baseTableVerified` 原本即为 true。`product_master_web_schema.json` 未改（仅测试数据集使用）。
- 启动检查：`PRODUCT_MASTER_ENABLED=true` + `PRODUCT_MASTER_WRITE_ENABLED=true` + 专用账号 + 上述三个标志 + 布局名一致，
  以生产配置实测不会被拒绝启动（`@products_web_api`）。
- 回写覆盖：基表字段（含 MOQ、Retail_Price_USD、組裝成本、時薪及工时字段等）、`@產品售價` 三项售价（已有记录时按 modId 更新，
  没有记录时首次保存新建并回读核对关联）、容器。Web 新建的产品无需导入快照即可填售价。
- 顺带修复：数字字段回写前的规范化会把 `500` 变成 `5E+2`（`Decimal.normalize`），现改为定点写法。

## 服务器开关（`product-master.release.yml` 的 env 块 / 服务器 `.env`）

```dotenv
PRODUCT_MASTER_ENABLED=true
PRODUCT_MASTER_WRITE_ENABLED=true
PRODUCT_MASTER_LAYOUT=@products_web_api
PRODUCT_MASTER_SCHEMA_PATH=config/product_master_schema.json
PRODUCT_MASTER_USERNAME=<专用服务账号>      # 只放 .env，不写进文档/提交
PRODUCT_MASTER_PASSWORD=<...>
# 保持原值：PRODUCT_MASTER_PREVIEW_ENABLED、PRODUCT_MASTER_WEB_ONLY、PRODUCT_MASTER_SOURCE
```

专用账号权限：`@products_web_api` 读、创建、编辑（含容器）；`@產品售價` 读、创建、编辑；`产品报价` 布局读。不授予删除。

## 小范围测试

只给测试账号勾「编辑产品」「编辑产品价格」（账号管理页），其他账号保存会被拒绝。已审核产品锁定不能编辑。

## 回退

把 `PRODUCT_MASTER_WRITE_ENABLED` 改回 `false` 并重建 backend：停止回写，Web 数据、版本历史和待回写任务保留
（重新打开后队列续跑）。

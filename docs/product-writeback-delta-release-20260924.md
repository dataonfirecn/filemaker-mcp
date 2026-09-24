# 产品编辑回写修复发布（2026-09-24）

## 问题与修复

- Master 的 Web 账号继承 `filemaker` 角色，未授予 `canEditProducts`，导致未审核产品也显示只读。按用户要求为 Master 添加单账号 `canEditProducts=true` 覆盖，其他权限和角色不变。
- 产品 `4747fe0e-08d0-4632-bc64-0dc353f5ecb7`（RG-08-BK）通过 Web 保存英文名称后，完整字段回写返回 FileMaker HTTP 500 / code 960（Parameter is invalid）。只提交修改的英文名称成功；没有通过试写其他字段进一步定位触发错误的历史值。
- Worker 在原有 modId 冲突检查之后比较 FileMaker 当前值，只 PATCH 有变化的字段；未变化时不执行空 PATCH。保留完整字段回读、持久化检查点和重试恢复机制。
- 回归测试覆盖英文名称修改、清空及无变化时不写入，并模拟未修改字段重新提交会被拒绝的情况。

## 发布

- 代码提交：`98afc25`，已推送 `origin/main`。
- 范围：仅后端，无数据库迁移、FileMaker 布局或前端变更。
- 镜像：`starrc-backend:20260924-98afc25`，继承 `starrc-backend:20260924-b2769de`。
- backend 容器：`15d2439bcbfa` → `a4fd3392dca5`。
- frontend `02e3944a7267`（`starrc-frontend:20260924-12aff38`）、postgres `f196c32c514b` 保持不变。
- 审计与备份目录：`/opt/starrc-filemaker/releases/20260924-98afc25/`。

## 验证

- 后端测试：404 passed / 61 skipped；未配置隔离数据库等条件的测试跳过。新增的三个回归用例均已执行并通过。
- 内网和公网 `/healthz` 均返回 `ok: true`。
- 容器内 worker 与本地源码 SHA-256 一致：`1569bd23524ff11ea2d4af82596880832a5fa75fb50fa04af4252e4dad30a8e9`。
- 用户授权测试名称为 `1:8 Tires Set On-Road 6S 2pcs_test`。部署前曾在原任务锁和版本校验保护下单字段回写，原任务随后回读完成；部署后 Web / FileMaker 版本均为 4，版本 3、4 的任务均为 `synced`，无错误。没有把这次部署后的只读验证当成新 Worker 的真实修改测试。
- FileMaker 编辑窗口显示保存成功；当前保存实现不自动关闭窗口。实测「取消」→「确定」可正常关闭已保存的编辑窗口，返回「产品报价」后可见带 `_test` 的英文名称。

## 回滚

恢复本次审计目录下 `backup/previous-release.yml` 到 `current/deploy/starrc/product-master.release.yml`，在该目录执行：

```sh
docker compose --env-file ../../.env -p starrc-filemaker \
  -f docker-compose.yml -f product-master.release.yml up -d --no-deps backend
```

回滚目标后端镜像为 `starrc-backend:20260924-b2769de`。账号权限是独立配置，不随镜像回滚。

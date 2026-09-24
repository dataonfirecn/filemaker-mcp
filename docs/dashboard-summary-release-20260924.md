# 首页报告摘要布局发布（2026-09-24）

- 发布提交：`434aedd`，仅修改 DashboardPage.tsx / DashboardPage.css，合并报告状态、指标、异常和趋势布局，并调整响应式与高度。
- 镜像：`starrc-frontend:20260924-434aedd`，继承 `starrc-frontend:20260924-cf8034c`。
- 仅重建 frontend；无后端、数据库迁移或 FileMaker 布局变更。
- frontend 容器：`93efe14a387a` → `9c981a46c95c`。
- backend `8fb64e9e6055`、postgres `f196c32c514b` 不变，部署脚本已用 diff 验证。
- 前端 tsc + vite 构建通过（约 4.9 秒）；后端未改，未运行 pytest。
- 用本地模拟报告数据渲染 DashboardPage，在 1068、1440、390px 及亮/暗主题下完成六张截图检查，均无水平溢出。此检查为组件预览，不代表生产登录和全站业务端到端测试。
- 内网及公网 healthz 均 `ok: true`。
- 本地构建与线上文件 SHA-256 一致：
  - index.html：`da3d169dac10f77bfbdb914ace13e8615e13410175dee754b6216ceb38907d00`
  - assets/index-BMb2Mydn.js：`b6b43d823204dec95a17970d4e39e0930153a95456d420b6a428790521e3baf4`
  - assets/App-Bi0JCwV6.js：`d3bce4bd39c94214f0c7d178b9b0cf0034bbf8149f13fbb23374f205cd029fe3`
- 审计目录：`/opt/starrc-filemaker/releases/20260924-434aedd/`，含旧覆盖文件、环境文件和上一版本 build 源码/产物备份，以及容器与健康检查记录。

## 计时（北京时间，包含 AI 与工具等待）

- 15:40:31 开始；15:41:05 开始构建，约 5 秒完成。
- 15:42:36 开始提交；15:42:38 推送完成；15:42:42 打包上传完成。
- 15:43:21 镜像构建开始并完成（秒级记录不足以给出精确小数）；15:43:22 服务更新完成。
- 15:43:25 线上验证完成：距开始 174 秒。
- 检查和截图主要占据提交前的 125 秒，含约 5 秒构建；上传完成到服务器构建间还含脚本编写、审批、连接和备份，未单独精确计时，不归因于模型。
- 本次 SSH、预览服务器和 Chromium 首次运行遇沙箱权限限制，获工具审批后完成。

## 回滚

在服务器执行，仅更新 frontend：

```bash
cd /opt/starrc-filemaker/current/deploy/starrc
cp /opt/starrc-filemaker/releases/20260924-434aedd/backup/previous-release.yml product-master.release.yml
docker compose --env-file ../../.env -p starrc-filemaker -f docker-compose.yml -f product-master.release.yml up -d --no-deps frontend
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
```

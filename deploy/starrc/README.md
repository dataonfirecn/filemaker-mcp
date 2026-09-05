# StarRC 独立公网部署

本目录只用于 `https://starrc.dataonfire.cn` 的内部工作台。外部客户门户已迁移到独立的 `DMS` 项目，不得共用容器、环境文件、数据库或数据卷。

生产环境安全基线：

- `APP_ENV=prod`
- `WEBVIEWER_ALLOW_MOCK_CONTEXT=false`
- 远程同事通过 PBKDF2 密码账号登录
- 通用 FileMaker 写接口保持 `FILEMAKER_READ_ONLY=true`
- Web 合并通过独立开关 `FILEMAKER_WEB_MERGE_ENABLED` 控制
- 审计日志及 Web 合并幂等记录保存在独立的 `starrc-postgres`
- 员工问答、FileMaker 登录用户名和查询诊断保存在独立持久化 `app.db`，后台 worker 自动生成问题分析
- 前后端端口只绑定 `127.0.0.1`，公网仅通过现有 HTTPS Nginx 反向代理进入

员工对话 WebViewer 使用 `https://starrc.dataonfire.cn/?page=chat`，必须由
`StarRC_WebViewerURL` 追加签名 `ctx` / `sig`。FileMaker 布局和验收步骤见
`docs/employee-chat-webviewer.md`。

服务器目录：`/opt/starrc-filemaker`。部署前备份 `.env` 和 `starrc_backend_data`，部署后检查：

```bash
docker compose --env-file .env -p starrc-filemaker -f deploy/starrc/docker-compose.yml config --quiet
docker compose --env-file .env -p starrc-filemaker -f deploy/starrc/docker-compose.yml up -d --build
curl -fsS http://127.0.0.1:18001/healthz
curl -fsS https://starrc.dataonfire.cn/healthz
```

生产环境必须在 `.env` 中配置 `COS_SECRET_ID` 和 `COS_SECRET_KEY`；
`deploy/starrc/docker-compose.yml` 会固定启用 COS，并在任一密钥缺失时拒绝启动，
避免 PDA 产品详情接口静默返回空图片。启动后可在不输出密钥的情况下验证配置：

```bash
docker compose --env-file .env -p starrc-filemaker \
  -f deploy/starrc/docker-compose.yml exec -T backend \
  python -c 'from app.core.config import get_settings; assert get_settings().cos_configured; print("COS configured")'
```

产品和零件图片每天 `21:30 Asia/Shanghai` 自动对账：先把 `@products`
新增容器同步到 `ProductAssets`，再把 `ProductAssets` 缺失对象同步到 COS，
最后把 `@零件` 的新增容器同步到 COS 和 `PartAssets`。
安装或更新 systemd 定时任务：

```bash
sudo install -m 0750 deploy/starrc/systemd/starrc-product-asset-reconcile \
  /usr/local/sbin/starrc-product-asset-reconcile
sudo install -m 0644 deploy/starrc/systemd/starrc-product-asset-reconcile.service \
  /etc/systemd/system/starrc-product-asset-reconcile.service
sudo install -m 0644 deploy/starrc/systemd/starrc-product-asset-reconcile.timer \
  /etc/systemd/system/starrc-product-asset-reconcile.timer
sudo systemctl daemon-reload
sudo systemctl enable --now starrc-product-asset-reconcile.timer
systemctl list-timers --all starrc-product-asset-reconcile.timer
```

任务使用 `flock` 防止重复执行，运行结果写入 systemd journal：

```bash
journalctl -u starrc-product-asset-reconcile.service --since today
```

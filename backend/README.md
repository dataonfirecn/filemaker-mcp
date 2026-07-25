# StarRC FastAPI Backend

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## FileMaker 测试

```bash
python scripts/test_connection.py
python scripts/test_records.py
```

FastAPI 进程会在 `app.state.filemaker_client` 中持有一个 FileMaker Data API token。FileMaker Data API token 是 15 分钟非活动滑动过期：每次成功使用都会续期。后端不会按本地计时主动刷新 token，而是一直复用现有 token；只有收到 401 授权失败时才重新登录并重试一次。应用关闭时会主动释放当前 Data API session。`FILEMAKER_TOKEN_INACTIVITY_TIMEOUT_SECONDS` 只用于状态展示和文档说明，不用于主动销毁 token。

可用这个接口检查当前进程的 token 状态；它不会触发登录，也不会返回 token 明文：

```bash
curl http://localhost:8000/api/filemaker/session \
  -H "Authorization: Bearer ${STARRC_WEBVIEWER_TOKEN}"
```

`/api/filemaker/*` 是原始技术管理接口，不向普通 WebViewer 或客户账号开放。所有读取请求
必须使用具备 `canManageRag` 的 StarRC WebViewer 会话；创建、修改、删除和执行脚本还必须
同时具备 `canManageAccounts`。生产环境应继续保持 `FILEMAKER_READ_ONLY=true`，业务写入
使用有独立权限和校验的专用接口。

## 关键接口

- `GET /healthz`
- `GET /api/filemaker/layouts`
- `POST /api/filemaker/{layout}/find`
- `POST /api/mes/callback`
- `GET /api/mes/events`
- `POST /api/qrcode/generate`

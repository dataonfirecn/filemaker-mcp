# StarRC FileMaker Service

前后端分离的 FileMaker 集成服务：

- `frontend/`: React + Vite + Nginx，给 FileMaker WebViewer 使用
- `backend/`: FastAPI，接收 MES callback、调用 FileMaker Data API、生成二维码、记录 WebViewer 审计日志
- `postgres`: WebViewer 审计日志库，保存 `audit_log`
- `legacy/filemaker-mcp/`: 原 TypeScript MCP 项目，保留作为参考和工具

## 本地 Docker 部署

先按 `.env.example` 补好 `.env`，至少需要 FileMaker 连接信息。
第一阶段默认 `FILEMAKER_READ_ONLY=true`，后端只读 FileMaker，不会执行 create/update/delete/script。

```bash
docker compose up --build -d
```

访问：

- 前端：`http://localhost:8080`
- 后端健康检查：`http://localhost:8000/healthz`
- API 文档：`http://localhost:8000/docs`
- WebViewer 本地预览：`http://localhost:8080/?productSku=821RTR-27&operatorAccount=mock.operator&operatorName=本地测试操作员`

## MES Callback

```bash
curl -X POST http://localhost:8000/api/mes/callback \
  -H "Content-Type: application/json" \
  -H "x-api-key: $MES_CALLBACK_API_KEY" \
  -d '{"eventId":"demo-001","status":"finished"}'
```

callback 会先写入 `backend/data/app.db`，再由后台 worker 调用 FileMaker。默认会调用：

```text
layout: MES_FILEMAKER_LAYOUT
script: MES_FILEMAKER_SCRIPT_NAME
```

也可以在 callback payload 中显式指定 FileMaker 操作：

```json
{
  "eventId": "demo-002",
  "filemaker": {
    "operation": "run_script",
    "layout": "MES_API",
    "scriptName": "MES_UpdateWorkOrder",
    "scriptParam": {
      "workOrderNo": "WO-001",
      "status": "finished"
    }
  }
}
```

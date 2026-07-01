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

## 关键接口

- `GET /healthz`
- `GET /api/filemaker/layouts`
- `POST /api/filemaker/{layout}/find`
- `POST /api/mes/callback`
- `GET /api/mes/events`
- `POST /api/qrcode/generate`

import { useEffect, useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import {
  Activity,
  Database,
  QrCode,
  RefreshCw,
  Server,
  TableProperties
} from "lucide-react";

type Health = {
  ok: boolean;
  service: string;
  environment: string;
  filemakerConfigured: boolean;
};

type CallbackEvent = {
  id: number;
  source: string;
  eventId: string;
  status: string;
  attemptCount: number;
  maxAttempts: number;
  lastError: string | null;
  createdAt: string;
  updatedAt: string;
};

type Tab = "dashboard" | "callbacks" | "qrcode";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function statusClass(status: string): string {
  if (status === "success") return "status status-success";
  if (status === "dead" || status === "failed") return "status status-error";
  if (status === "retrying" || status === "processing") return "status status-warn";
  return "status";
}

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [events, setEvents] = useState<CallbackEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [qrText, setQrText] = useState("https://app.example.com/q/demo");
  const [qrUrl, setQrUrl] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [healthData, eventData] = await Promise.all([
        fetchJson<Health>("/healthz"),
        fetchJson<CallbackEvent[]>("/api/mes/events?limit=50")
      ]);
      setHealth(healthData);
      setEvents(eventData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function generateQrCode() {
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/qrcode/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: qrText, format: "png" })
      });
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      const blob = await response.blob();
      if (qrUrl) URL.revokeObjectURL(qrUrl);
      setQrUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const callbackColumns = useMemo<ColDef<CallbackEvent>[]>(
    () => [
      { field: "id", width: 90 },
      { field: "source", headerName: "来源", width: 120 },
      { field: "eventId", headerName: "事件 ID", minWidth: 220, flex: 1 },
      {
        field: "status",
        headerName: "状态",
        width: 130,
        cellRenderer: ({ value }: { value: string }) => (
          <span className={statusClass(value)}>{value}</span>
        )
      },
      { field: "attemptCount", headerName: "尝试", width: 100 },
      { field: "maxAttempts", headerName: "上限", width: 100 },
      { field: "updatedAt", headerName: "更新时间", minWidth: 210 },
      { field: "lastError", headerName: "错误", minWidth: 260, flex: 1 }
    ],
    []
  );

  const successCount = events.filter((event) => event.status === "success").length;
  const pendingCount = events.filter((event) =>
    ["received", "processing", "retrying"].includes(event.status)
  ).length;
  const failedCount = events.filter((event) =>
    ["failed", "dead"].includes(event.status)
  ).length;

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={22} />
          <span>StarRC</span>
        </div>
        <nav className="nav">
          <button className={tab === "dashboard" ? "active" : ""} onClick={() => setTab("dashboard")}>
            <Activity size={18} />
            <span>Dashboard</span>
          </button>
          <button className={tab === "callbacks" ? "active" : ""} onClick={() => setTab("callbacks")}>
            <TableProperties size={18} />
            <span>Callbacks</span>
          </button>
          <button className={tab === "qrcode" ? "active" : ""} onClick={() => setTab("qrcode")}>
            <QrCode size={18} />
            <span>QRCode</span>
          </button>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{tab === "dashboard" ? "Dashboard" : tab === "callbacks" ? "Callbacks" : "QRCode"}</h1>
            <p>{health?.service ?? "StarRC FileMaker Service"}</p>
          </div>
          <button className="icon-button" onClick={loadData} disabled={loading} title="刷新">
            <RefreshCw size={18} />
          </button>
        </header>

        {error && <div className="alert">{error}</div>}

        {tab === "dashboard" && (
          <div className="dashboard">
            <section className="metric">
              <Server size={20} />
              <span>API</span>
              <strong>{health?.ok ? "online" : "unknown"}</strong>
            </section>
            <section className="metric">
              <Database size={20} />
              <span>FileMaker</span>
              <strong>{health?.filemakerConfigured ? "configured" : "missing env"}</strong>
            </section>
            <section className="metric">
              <Activity size={20} />
              <span>Pending</span>
              <strong>{pendingCount}</strong>
            </section>
            <section className="metric">
              <TableProperties size={20} />
              <span>Success</span>
              <strong>{successCount}</strong>
            </section>
            <section className="metric danger">
              <Activity size={20} />
              <span>Failed</span>
              <strong>{failedCount}</strong>
            </section>
          </div>
        )}

        {tab === "callbacks" && (
          <div className="grid-wrap ag-theme-quartz">
            <AgGridReact
              rowData={events}
              columnDefs={callbackColumns}
              defaultColDef={{ sortable: true, filter: true, resizable: true }}
              pagination
              paginationPageSize={20}
            />
          </div>
        )}

        {tab === "qrcode" && (
          <div className="qr-layout">
            <section className="qr-panel">
              <label htmlFor="qrText">内容</label>
              <textarea
                id="qrText"
                value={qrText}
                onChange={(event) => setQrText(event.target.value)}
              />
              <button className="primary" onClick={generateQrCode}>
                <QrCode size={18} />
                <span>生成</span>
              </button>
            </section>
            <section className="qr-preview">
              {qrUrl ? <img src={qrUrl} alt="QR Code" /> : <QrCode size={96} />}
            </section>
          </div>
        )}
      </section>
    </main>
  );
}

import {
  AlertTriangle,
  Bug,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  RefreshCw,
  Search
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

type DiagnosticLogItem = {
  id: number;
  reportId: string;
  operatorAccount: string;
  operatorName: string;
  operatorPrivilege: string;
  draftId: string;
  documentNumber: string;
  event: string;
  appBuild: string;
  appVersion: string;
  emailStatus: string;
  emailError: string | null;
  receivedAt: string;
  updatedAt: string;
  emailedAt: string | null;
};

type DiagnosticLogDetail = DiagnosticLogItem & {
  sessionId: string;
  report: string;
};

type DiagnosticLogListResponse = {
  items: DiagnosticLogItem[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
};

type Props = {
  apiBase: string;
  token: string;
};

async function responseMessage(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return `请求失败（${response.status}）`;
  try {
    const payload = JSON.parse(text) as { detail?: { message?: string } | string };
    if (typeof payload.detail === "string") return payload.detail;
    return payload.detail?.message || text;
  } catch {
    return text;
  }
}

function displayDateTime(value: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function statusLabel(status: string): string {
  if (status === "sent") return "邮件已发送";
  if (status === "failed") return "邮件发送失败";
  return "等待发送";
}

function statusClass(status: string): "success" | "warning" | "failed" {
  if (status === "sent") return "success";
  if (status === "failed") return "failed";
  return "warning";
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const field = document.createElement("textarea");
  field.value = value;
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  document.execCommand("copy");
  field.remove();
}

export default function InternalDiagnosticLogsPage({ apiBase, token }: Props) {
  const [query, setQuery] = useState("");
  const [emailStatus, setEmailStatus] = useState("");
  const [results, setResults] = useState<DiagnosticLogListResponse | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<DiagnosticLogDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function openReport(id: number) {
    setSelectedId(id);
    setDetailLoading(true);
    setCopied(false);
    setError("");
    try {
      const response = await fetch(
        `${apiBase}/api/webviewer/admin/mobile-diagnostic-reports/${id}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error(await responseMessage(response));
      setDetail(await response.json() as DiagnosticLogDetail);
    } catch (reason) {
      setDetail(null);
      setError(reason instanceof Error ? reason.message : "错误日志读取失败。");
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadReports(
    page = 1,
    nextQuery = query,
    nextEmailStatus = emailStatus
  ) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), pageSize: "20" });
      if (nextQuery.trim()) params.set("q", nextQuery.trim());
      if (nextEmailStatus) params.set("emailStatus", nextEmailStatus);
      const response = await fetch(
        `${apiBase}/api/webviewer/admin/mobile-diagnostic-reports?${params.toString()}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error(await responseMessage(response));
      const payload = await response.json() as DiagnosticLogListResponse;
      setResults(payload);
      if (!payload.items.length) {
        setSelectedId(null);
        setDetail(null);
      } else {
        const target = payload.items.some((item) => item.id === selectedId)
          ? selectedId as number
          : payload.items[0].id;
        await openReport(target);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "错误日志查询失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReports(1, "", "");
    // The token identifies the administrator session used by this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, token]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void loadReports(1);
  }

  function reset() {
    setQuery("");
    setEmailStatus("");
    void loadReports(1, "", "");
  }

  async function copyReport() {
    if (!detail) return;
    try {
      await copyText(detail.report);
      setCopied(true);
    } catch {
      setError("复制失败，请手动选择报告内容。");
    }
  }

  return (
    <div className="reports-page diagnostic-logs-page">
      <section className="reports-toolbar" aria-labelledby="diagnostic-log-title">
        <div className="reports-toolbar-heading">
          <span><Bug size={18} /></span>
          <div>
            <h2 id="diagnostic-log-title">PDA 错误日志</h2>
            <p>查看 iPad 自动上报的脱敏错误；邮件失败也不会影响日志留存。</p>
          </div>
        </div>
        <form className="reports-filters diagnostic-log-filters" onSubmit={submit}>
          <label className="reports-search-input">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索单据、操作员、事件、草稿或报告内容"
            />
          </label>
          <select
            aria-label="邮件状态"
            value={emailStatus}
            onChange={(event) => setEmailStatus(event.target.value)}
          >
            <option value="">全部邮件状态</option>
            <option value="sent">已发送</option>
            <option value="failed">发送失败</option>
            <option value="pending">等待发送</option>
          </select>
          <button className="reports-search-button" type="submit" disabled={loading}>
            <Search size={15} />查询
          </button>
          <button className="reports-reset-button" type="button" onClick={reset} disabled={loading}>
            <RefreshCw size={15} />刷新/重置
          </button>
        </form>
      </section>

      {error && <div className="reports-error"><AlertTriangle size={16} />{error}</div>}

      <div className="reports-workspace">
        <aside className="reports-list" aria-label="PDA 错误日志列表">
          <header>
            <div><strong>错误日志</strong><span>{results?.total ?? 0} 条</span></div>
            {results && <small>第 {results.page}/{results.totalPages} 页</small>}
          </header>
          <div className="reports-list-scroll">
            {loading && !results ? (
              <div className="reports-empty"><RefreshCw className="spin" size={22} />正在读取错误日志…</div>
            ) : results?.items.length ? results.items.map((item) => (
              <button
                key={item.id}
                className={`reports-list-item ${selectedId === item.id ? "active" : ""}`}
                type="button"
                onClick={() => void openReport(item.id)}
              >
                <span className={`report-status-dot ${statusClass(item.emailStatus)}`} aria-hidden="true" />
                <span className="reports-list-copy">
                  <span className="reports-list-meta">
                    <time>{displayDateTime(item.receivedAt)}</time>
                    <small className={`report-status-badge ${statusClass(item.emailStatus)}`}>
                      {statusLabel(item.emailStatus)}
                    </small>
                  </span>
                  <strong>{item.documentNumber || "未填写单据编号"}</strong>
                  <span>{item.event}</span>
                  <small>{item.operatorName} · build {item.appBuild || "未知"}</small>
                </span>
              </button>
            )) : (
              <div className="reports-empty"><Bug size={26} />没有符合条件的错误日志</div>
            )}
          </div>
          {results && results.totalPages > 1 && (
            <footer className="reports-pagination">
              <button
                type="button"
                disabled={loading || results.page <= 1}
                onClick={() => void loadReports(results.page - 1)}
              ><ChevronLeft size={15} />上一页</button>
              <button
                type="button"
                disabled={loading || results.page >= results.totalPages}
                onClick={() => void loadReports(results.page + 1)}
              >下一页<ChevronRight size={15} /></button>
            </footer>
          )}
        </aside>

        <section className="reports-detail diagnostic-log-detail" aria-live="polite">
          {detailLoading ? (
            <div className="reports-empty reports-detail-loading"><RefreshCw className="spin" size={25} />正在加载报告…</div>
          ) : detail ? (
            <>
              <header className="reports-detail-header">
                <div>
                  <span className="reports-detail-date">收到于 {displayDateTime(detail.receivedAt)}</span>
                  <h2>{detail.documentNumber || "PDA 错误报告"}</h2>
                  <p>{detail.event} · 报告 ID：{detail.reportId}</p>
                </div>
                <div className="reports-detail-state">
                  <span className={`report-status-badge ${statusClass(detail.emailStatus)}`}>
                    {statusLabel(detail.emailStatus)}
                  </span>
                  <small>build {detail.appBuild || "未知"} · v{detail.appVersion || "未知"}</small>
                </div>
              </header>
              <div className="diagnostic-log-meta-grid">
                <div><small>操作员</small><strong>{detail.operatorName}</strong><span>{detail.operatorAccount}</span></div>
                <div><small>账号角色</small><strong>{detail.operatorPrivilege || "-"}</strong></div>
                <div><small>草稿 ID</small><strong>{detail.draftId}</strong></div>
                <div><small>邮件时间</small><strong>{displayDateTime(detail.emailedAt)}</strong></div>
              </div>
              {detail.emailError && (
                <div className="reports-error diagnostic-email-error">
                  <AlertTriangle size={16} />邮件未送达：{detail.emailError}；错误日志已正常保存。
                </div>
              )}
              <div className="diagnostic-log-report-head">
                <div><Bug size={16} /><strong>脱敏错误报告</strong></div>
                <button type="button" onClick={() => void copyReport()}>
                  {copied ? <Check size={14} /> : <Copy size={14} />}
                  {copied ? "已复制" : "复制报告"}
                </button>
              </div>
              <pre className="diagnostic-log-report">{detail.report}</pre>
            </>
          ) : (
            <div className="reports-empty"><Bug size={26} />选择一条日志查看完整报告</div>
          )}
        </section>
      </div>
    </div>
  );
}

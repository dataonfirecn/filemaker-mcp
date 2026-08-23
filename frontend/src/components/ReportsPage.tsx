import {
  AlertTriangle,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileSearch,
  FileText,
  Gauge,
  RefreshCw,
  Search,
  ShieldAlert
} from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import type {
  ReportDetail,
  ReportException,
  ReportListResponse,
  ReportStatus
} from "../types";

type ReportsPageProps = {
  apiBase: string;
  token: string;
};

type Filters = {
  query: string;
  status: "" | ReportStatus;
  reportType: string;
  dateFrom: string;
  dateTo: string;
};

const emptyFilters: Filters = {
  query: "",
  status: "",
  reportType: "",
  dateFrom: "",
  dateTo: ""
};

const statusCopy: Record<ReportStatus, string> = {
  success: "正常",
  warning: "需关注",
  failed: "失败"
};

const reportTypeCopy: Record<string, string> = {
  "query-analytics-midday": "中午问答质量摘要",
  "query-analytics": "查询质量分析",
  "synthetic-query-probe": "自动问答巡检",
  "security-red-team": "权限安全回归",
  operations: "运营日报"
};

function displayReportType(value: string): string {
  return reportTypeCopy[value] || value;
}

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

function displayDate(value: string): string {
  if (!value) return "-";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${year}年${month}月${day}日` : value;
}

function displayDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value || "-";
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function exceptionCopyText(item: ReportException): string {
  return [
    item.title,
    item.description ? `现象：${item.description}` : "",
    item.impact ? `影响：${item.impact}` : "",
    item.suggestedAction ? `建议：${item.suggestedAction}` : "",
    item.owner ? `负责人：${item.owner}` : ""
  ].filter(Boolean).join("\n");
}

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Some embedded WebViews expose the API but deny it; use the legacy fallback.
    }
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand("copy");
  field.remove();
  if (!copied) throw new Error("Clipboard is unavailable");
}

export default function ReportsPage({ apiBase, token }: ReportsPageProps) {
  const initialParams = useRef(new URLSearchParams(window.location.search));
  const requestedReportId = useRef(initialParams.current.get("reportId")?.trim() || "");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [results, setResults] = useState<ReportListResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [htmlContent, setHtmlContent] = useState("");
  const [view, setView] = useState<"summary" | "html">("summary");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [attentionId, setAttentionId] = useState(
    initialParams.current.get("attention")?.trim() || ""
  );
  const [copiedExceptionId, setCopiedExceptionId] = useState("");

  async function openReport(reportId: string) {
    setSelectedId(reportId);
    setCopiedExceptionId("");
    setDetailLoading(true);
    setError("");
    try {
      const headers = { Authorization: `Bearer ${token}` };
      const [detailResponse, htmlResponse] = await Promise.all([
        fetch(`${apiBase}/api/reports/${encodeURIComponent(reportId)}`, { headers }),
        fetch(`${apiBase}/api/reports/${encodeURIComponent(reportId)}/html`, { headers })
      ]);
      if (!detailResponse.ok) throw new Error(await responseMessage(detailResponse));
      if (!htmlResponse.ok) throw new Error(await responseMessage(htmlResponse));
      setDetail(await detailResponse.json() as ReportDetail);
      setHtmlContent(await htmlResponse.text());
    } catch (reason) {
      setDetail(null);
      setHtmlContent("");
      setError(reason instanceof Error ? reason.message : "报告读取失败。 ");
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadReports(page = 1, nextFilters = filters) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        pageSize: "20"
      });
      if (nextFilters.query.trim()) params.set("q", nextFilters.query.trim());
      if (nextFilters.status) params.set("status", nextFilters.status);
      if (nextFilters.reportType) params.set("reportType", nextFilters.reportType);
      if (nextFilters.dateFrom) params.set("dateFrom", nextFilters.dateFrom);
      if (nextFilters.dateTo) params.set("dateTo", nextFilters.dateTo);
      const response = await fetch(`${apiBase}/api/reports?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(await responseMessage(response));
      const payload = await response.json() as ReportListResponse;
      setResults(payload);
      if (!payload.items.length) {
        setSelectedId("");
        setDetail(null);
        setHtmlContent("");
      } else {
        const linkedReportId = requestedReportId.current;
        requestedReportId.current = "";
        const target = linkedReportId || (
          payload.items.some((item) => item.id === selectedId)
            ? selectedId
            : payload.items[0].id
        );
        await openReport(target);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "报告查询失败。 ");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReports(1, emptyFilters);
    // The session token identifies this report-center session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, token]);

  useEffect(() => {
    if (!detail || !attentionId || view !== "summary") return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById(`report-attention-${attentionId}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center"
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [attentionId, detail, view]);

  async function copyException(item: ReportException) {
    try {
      await writeClipboard(exceptionCopyText(item));
      setCopiedExceptionId(String(item.id));
    } catch {
      setError("复制失败，请手动选择需要关注的文字。 ");
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void loadReports(1);
  }

  function resetFilters() {
    setFilters(emptyFilters);
    void loadReports(1, emptyFilters);
  }

  const reportTypes = results?.reportTypes ?? [];

  return (
    <div className="reports-page">
      <section className="reports-toolbar" aria-labelledby="reports-search-title">
        <div className="reports-toolbar-heading">
          <span><FileSearch size={18} /></span>
          <div>
            <h2 id="reports-search-title">报告中心</h2>
            <p>搜索夜间报告、重要指标和异常内容，历史HTML原样归档。</p>
          </div>
        </div>
        <form className="reports-filters" onSubmit={submit}>
          <label className="reports-search-input">
            <Search size={16} />
            <input
              value={filters.query}
              onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
              placeholder="搜索标题、摘要、异常或关键词"
            />
          </label>
          <select
            aria-label="报告状态"
            value={filters.status}
            onChange={(event) => setFilters((current) => ({
              ...current,
              status: event.target.value as Filters["status"]
            }))}
          >
            <option value="">全部状态</option>
            <option value="success">正常</option>
            <option value="warning">需关注</option>
            <option value="failed">失败</option>
          </select>
          <select
            aria-label="报告类型"
            value={filters.reportType}
            onChange={(event) => setFilters((current) => ({ ...current, reportType: event.target.value }))}
          >
            <option value="">全部类型</option>
            {reportTypes.map((item) => (
              <option key={item.value} value={item.value}>{displayReportType(item.value)}（{item.count}）</option>
            ))}
          </select>
          <label className="reports-date-field">
            <span>从</span>
            <input
              type="date"
              value={filters.dateFrom}
              onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))}
            />
          </label>
          <label className="reports-date-field">
            <span>至</span>
            <input
              type="date"
              value={filters.dateTo}
              onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))}
            />
          </label>
          <button className="reports-search-button" type="submit" disabled={loading}>
            <Search size={15} />查询
          </button>
          <button className="reports-reset-button" type="button" onClick={resetFilters} disabled={loading}>
            <RefreshCw size={15} />重置
          </button>
        </form>
      </section>

      {error && <div className="reports-error"><AlertTriangle size={16} />{error}</div>}

      <div className="reports-workspace">
        <aside className="reports-list" aria-label="报告查询结果">
          <header>
            <div><strong>报告列表</strong><span>{results?.total ?? 0} 份</span></div>
            {results && <small>第 {results.page}/{results.totalPages} 页</small>}
          </header>
          <div className="reports-list-scroll">
            {loading && !results ? (
              <div className="reports-empty"><RefreshCw className="spin" size={22} />正在读取报告…</div>
            ) : results?.items.length ? results.items.map((item) => (
              <button
                key={item.id}
                className={`reports-list-item ${selectedId === item.id ? "active" : ""}`}
                type="button"
                onClick={() => {
                  setAttentionId("");
                  void openReport(item.id);
                }}
              >
                <span className={`report-status-dot ${item.status}`} aria-hidden="true" />
                <span className="reports-list-copy">
                  <span className="reports-list-meta">
                    <time>{item.reportDate}</time>
                    <small className={`report-status-badge ${item.status}`}>{statusCopy[item.status]}</small>
                  </span>
                  <strong>{item.title}</strong>
                  <span>{item.summary}</span>
                  <small>{item.metricCount} 项指标 · {item.exceptionCount} 项异常</small>
                </span>
              </button>
            )) : (
              <div className="reports-empty"><FileSearch size={26} />没有符合条件的报告</div>
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

        <section className="reports-detail" aria-live="polite">
          {detailLoading ? (
            <div className="reports-empty reports-detail-loading"><RefreshCw className="spin" size={25} />正在加载报告…</div>
          ) : detail ? (
            <>
              <header className="reports-detail-header">
                <div>
                  <span className="reports-detail-date"><CalendarDays size={14} />{displayDate(detail.reportDate)}</span>
                  <h2>{detail.title}</h2>
                  <p>{detail.summary}</p>
                </div>
                <div className="reports-detail-state">
                  <span className={`report-status-badge ${detail.status}`}>{statusCopy[detail.status]}</span>
                  <small>完整度 {detail.dataCompleteness}%</small>
                </div>
              </header>
              <div className="reports-view-switcher" role="tablist" aria-label="报告视图">
                <button
                  type="button"
                  className={view === "summary" ? "active" : ""}
                  onClick={() => setView("summary")}
                  role="tab"
                  aria-selected={view === "summary"}
                ><Gauge size={15} />管理摘要</button>
                <button
                  type="button"
                  className={view === "html" ? "active" : ""}
                  onClick={() => setView("html")}
                  role="tab"
                  aria-selected={view === "html"}
                ><FileText size={15} />完整HTML</button>
              </div>
              {view === "summary" ? (
                <div className="reports-summary-view">
                  <div className="reports-metric-grid">
                    {detail.metrics.map((metric) => (
                      <article className={`reports-metric-card ${metric.severity}`} key={metric.metricCode}>
                        <span>{metric.metricName}</span>
                        <strong>{metric.displayValue || `${metric.metricValue ?? "-"}${metric.unit}`}</strong>
                        {metric.targetValue !== null && <small>目标 {metric.targetValue}{metric.unit}</small>}
                      </article>
                    ))}
                    {!detail.metrics.length && <div className="reports-empty-inline">暂无结构化指标</div>}
                  </div>
                  <section className="reports-exceptions">
                    <header><div><ShieldAlert size={17} /><strong>需要关注</strong></div><span>{detail.exceptions.length} 项</span></header>
                    {detail.exceptions.length ? detail.exceptions.map((item) => (
                      <article
                        id={`report-attention-${item.id}`}
                        key={item.id}
                        className={`${item.severity} ${attentionId === String(item.id) ? "highlighted" : ""}`}
                      >
                        <span><AlertTriangle size={15} /></span>
                        <div>
                          <div className="reports-exception-heading">
                            <strong>{item.title}</strong>
                            <button
                              type="button"
                              className={copiedExceptionId === String(item.id) ? "copied" : ""}
                              onClick={() => void copyException(item)}
                              aria-label={`复制需要关注内容：${item.title}`}
                            >
                              {copiedExceptionId === String(item.id)
                                ? <><Check size={13} />已复制</>
                                : <><Copy size={13} />复制</>}
                            </button>
                          </div>
                          {item.description && <p>{item.description}</p>}
                          {item.impact && <small>影响：{item.impact}</small>}
                          {item.suggestedAction && <small>建议：{item.suggestedAction}</small>}
                          <footer>{item.owner || "待分配"} · {item.category || "一般异常"}</footer>
                        </div>
                      </article>
                    )) : <div className="reports-empty-inline success">本报告没有未处理的重要异常。</div>}
                  </section>
                  <div className="reports-detail-footnote">
                    生成于 {displayDateTime(detail.completedAt)} · 报告类型 {displayReportType(detail.reportType)}
                  </div>
                </div>
              ) : (
                <div className="reports-html-view">
                  <div className="reports-html-notice">
                    HTML以隔离模式加载，脚本、外部资源和主页面访问均已禁用。
                  </div>
                  <iframe
                    title={`${detail.title} HTML报告`}
                    sandbox=""
                    srcDoc={htmlContent}
                  />
                </div>
              )}
            </>
          ) : (
            <div className="reports-empty reports-detail-loading"><FileText size={28} />请选择一份报告</div>
          )}
        </section>
      </div>
    </div>
  );
}

import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Database,
  Fingerprint,
  History,
  PackageCheck,
  RefreshCw,
  Search,
  Truck
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

type QualitySpecVersion = {
  id: string;
  version: string;
  approvedBy: string;
  effectiveAt: string;
};

type QualityCheckItem = {
  id: string;
  code: string;
  title: string;
  instructions: string;
  inputType: string;
  unit?: string;
  targetValue?: number | null;
  lowerLimit?: number | null;
  upperLimit?: number | null;
  standardText?: string | null;
  resultKind?: string | null;
  required: boolean;
  sampleCount: number;
};

type QualityInspectionListItem = {
  id: string;
  purchaseLineID: string;
  arrivalBatchID: string;
  inspectionRound: number;
  purchaseOrderNumber: string;
  nbNumber: string;
  partNumber: string;
  partName: string;
  supplierName: string;
  arrivalDate: string;
  arrivalQuantity: number;
  availableQuantity: number;
  inspectionMethod: string;
  sampleQuantity: number;
  status: string;
  conclusion: string;
  operatorAccount: string;
  operatorName: string;
  createdAt: string;
  updatedAt: string;
};

type QualityInspectionEvent = {
  eventId: string;
  inspectionID: string;
  eventType: string;
  fromStatus: string;
  toStatus: string;
  operatorAccount: string;
  operatorName: string;
  operatorPrivilege: string;
  sessionId: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

type QualityInspectionDetail = QualityInspectionListItem & {
  idempotencyKey: string;
  returnedQuantity: number;
  warehousedQuantity: number;
  specVersion: QualitySpecVersion;
  checkItems: QualityCheckItem[];
  sourceSnapshot: Record<string, unknown>;
  requestPayload: Record<string, unknown>;
  operatorPrivilege: string;
  sessionId: string;
  events: QualityInspectionEvent[];
};

type QualityInspectionListResponse = {
  items: QualityInspectionListItem[];
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

function displayDateTime(value: string): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

function eventLabel(value: string): string {
  if (value === "INSPECTION_CREATED") return "检查单已创建";
  if (value === "IDEMPOTENT_REPLAY") return "重复请求已安全复用";
  return value;
}

function statusClass(value: string): "success" | "warning" | "failed" {
  if (["已完成", "合格", "通过"].some((item) => value.includes(item))) return "success";
  if (["不合格", "拒收", "退货"].some((item) => value.includes(item))) return "failed";
  return "warning";
}

function prettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export default function InternalQualityInspectionsPage({ apiBase, token }: Props) {
  const [query, setQuery] = useState("");
  const [inspectionStatus, setInspectionStatus] = useState("");
  const [results, setResults] = useState<QualityInspectionListResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<QualityInspectionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  async function openInspection(id: string) {
    setSelectedId(id);
    setDetailLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${apiBase}/api/webviewer/admin/quality-inspections/${encodeURIComponent(id)}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error(await responseMessage(response));
      setDetail(await response.json() as QualityInspectionDetail);
    } catch (reason) {
      setDetail(null);
      setError(reason instanceof Error ? reason.message : "品检记录读取失败。");
    } finally {
      setDetailLoading(false);
    }
  }

  async function loadInspections(
    page = 1,
    nextQuery = query,
    nextStatus = inspectionStatus
  ) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), pageSize: "20" });
      if (nextQuery.trim()) params.set("q", nextQuery.trim());
      if (nextStatus) params.set("status", nextStatus);
      const response = await fetch(
        `${apiBase}/api/webviewer/admin/quality-inspections?${params.toString()}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error(await responseMessage(response));
      const payload = await response.json() as QualityInspectionListResponse;
      setResults(payload);
      if (!payload.items.length) {
        setSelectedId(null);
        setDetail(null);
      } else {
        const target = payload.items.some((item) => item.id === selectedId)
          ? selectedId as string
          : payload.items[0].id;
        await openInspection(target);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "品检记录查询失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInspections(1, "", "");
    // The token identifies the administrator session used by this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase, token]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void loadInspections(1);
  }

  function reset() {
    setQuery("");
    setInspectionStatus("");
    void loadInspections(1, "", "");
  }

  return (
    <div className="reports-page quality-inspections-page">
      <section className="reports-toolbar" aria-labelledby="quality-inspections-title">
        <div className="reports-toolbar-heading">
          <span><ClipboardCheck size={18} /></span>
          <div>
            <h2 id="quality-inspections-title">来料品检记录</h2>
            <p>记录保存在网站数据库；FileMaker 只提供采购、到货和规范的只读来源。</p>
          </div>
        </div>
        <form className="reports-filters quality-inspection-filters" onSubmit={submit}>
          <label className="reports-search-input">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="检查单、零件、PT/NB、供应商、操作员"
            />
          </label>
          <select
            aria-label="品检状态"
            value={inspectionStatus}
            onChange={(event) => setInspectionStatus(event.target.value)}
          >
            <option value="">全部状态</option>
            <option value="检查中">检查中</option>
            <option value="已完成">已完成</option>
            <option value="合格">合格</option>
            <option value="不合格">不合格</option>
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
        <aside className="reports-list" aria-label="来料品检记录列表">
          <header>
            <div><strong>检查记录</strong><span>{results?.total ?? 0} 条</span></div>
            {results && <small>第 {results.page}/{results.totalPages} 页</small>}
          </header>
          <div className="reports-list-scroll">
            {loading && !results ? (
              <div className="reports-empty"><RefreshCw className="spin" size={22} />正在读取品检记录…</div>
            ) : results?.items.length ? results.items.map((item) => (
              <button
                key={item.id}
                className={`reports-list-item ${selectedId === item.id ? "active" : ""}`}
                type="button"
                onClick={() => void openInspection(item.id)}
              >
                <span className={`report-status-dot ${statusClass(item.status)}`} aria-hidden="true" />
                <span className="reports-list-copy">
                  <span className="reports-list-meta">
                    <time>{displayDateTime(item.createdAt)}</time>
                    <small className={`report-status-badge ${statusClass(item.status)}`}>{item.status}</small>
                  </span>
                  <strong>{item.partNumber || "未填写零件编号"}</strong>
                  <span>{item.partName || item.id}</span>
                  <small>{item.supplierName || "未知供应商"} · {item.operatorName}</small>
                </span>
              </button>
            )) : (
              <div className="reports-empty"><ClipboardCheck size={26} />没有符合条件的品检记录</div>
            )}
          </div>
          {results && results.totalPages > 1 && (
            <footer className="reports-pagination">
              <button
                type="button"
                disabled={loading || results.page <= 1}
                onClick={() => void loadInspections(results.page - 1)}
              ><ChevronLeft size={15} />上一页</button>
              <button
                type="button"
                disabled={loading || results.page >= results.totalPages}
                onClick={() => void loadInspections(results.page + 1)}
              >下一页<ChevronRight size={15} /></button>
            </footer>
          )}
        </aside>

        <section className="reports-detail quality-inspection-detail" aria-live="polite">
          {detailLoading ? (
            <div className="reports-empty reports-detail-loading"><RefreshCw className="spin" size={25} />正在加载完整记录…</div>
          ) : detail ? (
            <>
              <header className="reports-detail-header">
                <div>
                  <span className="reports-detail-date">创建于 {displayDateTime(detail.createdAt)}</span>
                  <h2>{detail.partNumber} · {detail.partName}</h2>
                  <p>检查单：{detail.id}</p>
                </div>
                <div className="reports-detail-state">
                  <span className={`report-status-badge ${statusClass(detail.status)}`}>{detail.status}</span>
                  <small>第 {detail.inspectionRound} 次 · {detail.inspectionMethod}</small>
                </div>
              </header>

              <div className="quality-trace-callout">
                <Database size={18} />
                <div><strong>网站数据库是品检记录的唯一写入位置</strong><span>下方保留创建时的 FileMaker 来源快照、品检规范、操作账号、会话和事件。</span></div>
              </div>

              <div className="diagnostic-log-meta-grid quality-summary-grid">
                <div><small>PT / NB</small><strong>{detail.purchaseOrderNumber || "-"}</strong><span>{detail.nbNumber || "-"}</span></div>
                <div><small>到货批次</small><strong>{detail.arrivalBatchID}</strong><span>{detail.arrivalDate || "-"}</span></div>
                <div><small>供应商</small><strong>{detail.supplierName || "-"}</strong></div>
                <div><small>数量</small><strong>到货 {detail.arrivalQuantity}</strong><span>可检 {detail.availableQuantity} · 抽样 {detail.sampleQuantity}</span></div>
                <div><small>操作员</small><strong>{detail.operatorName}</strong><span>{detail.operatorAccount} · {detail.operatorPrivilege || "-"}</span></div>
                <div><small>来源关联</small><strong>{detail.purchaseLineID}</strong><span>采购明细 ID</span></div>
              </div>

              <section className="quality-detail-section">
                <header><PackageCheck size={17} /><div><strong>品检规范快照</strong><span>{detail.specVersion.version} · {detail.specVersion.approvedBy || "未填写审核人"}</span></div></header>
                <div className="quality-check-items">
                  {detail.checkItems.map((item) => (
                    <div key={item.id}>
                      <span>{item.code}</span>
                      <div>
                        <strong>{item.title}</strong>
                        <p>{item.instructions}</p>
                        {item.standardText && <p>原始标准：{item.standardText}</p>}
                        <small>
                          {item.required ? "必检" : "选检"} · 样本 {item.sampleCount}
                          {item.lowerLimit != null && item.upperLimit != null
                            ? ` · 范围 ${item.lowerLimit}–${item.upperLimit}${item.unit || ""}`
                            : item.targetValue != null
                              ? ` · 目标 ${item.targetValue}${item.unit || ""}`
                              : ""}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="quality-detail-section">
                <header><History size={17} /><div><strong>追溯事件</strong><span>{detail.events.length} 条不可见修改入口的审计事件</span></div></header>
                <div className="quality-event-list">
                  {detail.events.map((item) => (
                    <div key={item.eventId}>
                      <CheckCircle2 size={16} />
                      <div><strong>{eventLabel(item.eventType)}</strong><span>{displayDateTime(item.createdAt)} · {item.operatorName}（{item.operatorAccount}）</span><small>状态：{item.fromStatus || "无"} → {item.toStatus || "无"}</small></div>
                    </div>
                  ))}
                </div>
              </section>

              <details className="quality-raw-trace">
                <summary><Truck size={16} />创建时的 FileMaker 来源快照</summary>
                <pre>{prettyJson(detail.sourceSnapshot)}</pre>
              </details>
              <details className="quality-raw-trace">
                <summary><Fingerprint size={16} />请求与幂等追踪</summary>
                <div className="quality-identifiers">
                  <span><small>幂等键</small><code>{detail.idempotencyKey}</code></span>
                  <span><small>会话 ID</small><code>{detail.sessionId || "-"}</code></span>
                </div>
                <pre>{prettyJson(detail.requestPayload)}</pre>
              </details>
            </>
          ) : (
            <div className="reports-empty"><ClipboardCheck size={26} />选择一条记录查看完整追溯信息</div>
          )}
        </section>
      </div>
    </div>
  );
}

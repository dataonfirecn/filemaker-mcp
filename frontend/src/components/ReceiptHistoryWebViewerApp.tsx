import {
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  Box,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Database,
  ExternalLink,
  FileCheck2,
  Image as ImageIcon,
  Link2,
  Loader2,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  UserRound,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type {
  ReceiptHistoryEntry,
  ReceiptHistoryResponse,
  SessionResponse
} from "../types";
import { parseError } from "../utils/error";
import "./receipt-history-webviewer.css";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
const closeScriptName = "StarRC_CloseWebViewer";

declare global {
  interface Window {
    FileMaker?: {
      PerformScript: (scriptName: string, parameter?: string) => void;
    };
  }
}

async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  token?: string
): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    credentials: "omit",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers
    }
  });
  if (!response.ok) {
    const body = await response.text();
    try {
      const parsed = JSON.parse(body) as { detail?: { message?: string } };
      throw new Error(parsed.detail?.message || body);
    } catch (error) {
      if (error instanceof Error && error.message !== body) throw error;
      throw new Error(body || `请求失败（HTTP ${response.status}）`);
    }
  }
  return response.json() as Promise<T>;
}

const numberFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 3
});

function quantity(value: number): string {
  return numberFormatter.format(value);
}

function signedQuantity(value: number): string {
  return `${value > 0 ? "+" : ""}${quantity(value)}`;
}

function dateTime(value: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  });
}

function shortId(value: string): string {
  if (!value) return "—";
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function differenceLabel(value: number): string {
  if (value > 0) return `比订单参考量多 ${quantity(value)} 件`;
  if (value < 0) return `比订单参考量少 ${quantity(Math.abs(value))} 件`;
  return "与订单参考量相同";
}

function ReceiptCard({
  receipt,
  index
}: {
  receipt: ReceiptHistoryEntry;
  index: number;
}) {
  const [expanded, setExpanded] = useState(index === 0);
  return (
    <article className="rhw-receipt-card">
      <button
        className="rhw-receipt-heading"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className={`rhw-timeline-marker ${receipt.traceable ? "traceable" : "warning"}`}>
          {receipt.traceable ? <CheckCircle2 size={17} /> : <AlertCircle size={17} />}
        </span>
        <span className="rhw-receipt-main">
          <span className="rhw-receipt-line">
            <strong>{quantity(receipt.quantity)} 件</strong>
            <span className={`rhw-status ${receipt.status === "已入庫" ? "done" : "pending"}`}>
              {receipt.status || "未标记"}
            </span>
            {receipt.traceable && <span className="rhw-trace"><Link2 size={12} />库存已关联</span>}
          </span>
          <span className="rhw-receipt-meta">
            <Clock3 size={13} /> {dateTime(receipt.receivedAt)}
            <UserRound size={13} /> {receipt.receivedBy || "—"}
          </span>
        </span>
        <span className="rhw-receipt-id" title={receipt.receiptId}>
          入库记录 {shortId(receipt.receiptId)}
        </span>
        {expanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
      </button>

      {expanded && (
        <div className="rhw-receipt-body">
          <dl className="rhw-technical-grid">
            <div><dt>入库记录 ID</dt><dd>{receipt.receiptId || "—"}</dd></div>
            <div><dt>创建人</dt><dd>{receipt.createdBy || "—"}</dd></div>
            <div><dt>最后修改</dt><dd>{dateTime(receipt.modifiedAt)}</dd></div>
            <div><dt>修改人</dt><dd>{receipt.modifiedBy || "—"}</dd></div>
          </dl>

          <div className="rhw-movement-section">
            <div className="rhw-section-caption">
              <Database size={15} />
              <strong>关联库存流水</strong>
              <span>{receipt.inventoryMovements.length} 条</span>
            </div>
            {receipt.inventoryMovements.length ? (
              <div className="rhw-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>流水记录</th>
                      <th>日期</th>
                      <th>批号</th>
                      <th>入库</th>
                      <th>出库</th>
                      <th>操作人</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {receipt.inventoryMovements.map((movement) => (
                      <tr key={`${receipt.receiptId}-${movement.recordKey}`}>
                        <td title={movement.recordKey}>{shortId(movement.recordKey)}</td>
                        <td>{movement.date || "—"}</td>
                        <td>{movement.batchNumber || "—"}</td>
                        <td className="rhw-inbound">{quantity(movement.inboundQuantity)}</td>
                        <td>{movement.outboundQuantity ? quantity(movement.outboundQuantity) : "—"}</td>
                        <td>{movement.operator || "—"}</td>
                        <td>{movement.description || "PDA 成品入库"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="rhw-inline-warning">
                <AlertCircle size={15} /> 尚未找到关联的库存流水，请核对入库记录 ID。
              </div>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

export default function ReceiptHistoryWebViewerApp() {
  const didStart = useRef(false);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [data, setData] = useState<ReceiptHistoryResponse | null>(null);
  const [starting, setStarting] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = new URLSearchParams(window.location.search);
  const lineId = params.get("lineId")?.trim() ?? "";

  useEffect(() => {
    document.title = "PDA 成品入库历史";
    document.documentElement.dataset.theme = "light";
    document.documentElement.style.colorScheme = "light";
  }, []);

  async function loadHistory(activeSession: SessionResponse, isRefresh = false) {
    if (!lineId) throw new Error("缺少出货单资料 ID，无法读取历史记录。");
    if (isRefresh) setRefreshing(true);
    const response = await requestJson<ReceiptHistoryResponse>(
      `/api/orders/receipt-history/${encodeURIComponent(lineId)}`,
      {},
      activeSession.token
    );
    setData(response);
    if (isRefresh) setRefreshing(false);
  }

  useEffect(() => {
    if (didStart.current) return;
    didStart.current = true;
    async function start() {
      try {
        if (!lineId) throw new Error("缺少出货单资料 ID，无法读取历史记录。");
        const ctx = params.get("ctx");
        const sig = params.get("sig");
        const nextSession = await requestJson<SessionResponse>(
          "/api/webviewer/session",
          {
            method: "POST",
            body: JSON.stringify({
              ctx,
              sig,
              lineId,
              mock: !(ctx && sig),
              operator: {
                account: "receipt-history.preview",
                name: "入库历史预览",
                privilege: "mock"
              }
            })
          }
        );
        setSession(nextSession);
        await loadHistory(nextSession);
      } catch (reason) {
        setError(parseError(reason));
      } finally {
        setStarting(false);
      }
    }
    void start();
  }, []);

  async function refresh() {
    if (!session || refreshing) return;
    setError(null);
    try {
      await loadHistory(session, true);
    } catch (reason) {
      setError(parseError(reason));
      setRefreshing(false);
    }
  }

  function closeWebViewer() {
    if (window.FileMaker?.PerformScript) {
      window.FileMaker.PerformScript(
        closeScriptName,
        JSON.stringify({ action: "close", source: "receiptHistory" })
      );
    } else {
      window.close();
    }
  }

  if (starting) {
    return (
      <main className="rhw-root rhw-centered">
        <span className="rhw-loading-icon"><PackageCheck size={24} /></span>
        <Loader2 className="rhw-spin" size={25} />
        <strong>正在读取 PDA 成品入库历史…</strong>
        <small>核对 FileMaker 入库记录与库存流水关联</small>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="rhw-root rhw-centered">
        <AlertCircle className="rhw-error-icon" size={27} />
        <h1>无法打开入库历史</h1>
        <p>{error ?? "WebViewer 会话初始化失败。"}</p>
        <button className="rhw-button" type="button" onClick={() => window.location.reload()}>
          <RefreshCw size={16} />重新载入
        </button>
      </main>
    );
  }

  const { line, summary } = data;
  const differenceClass =
    summary.differenceFromOrder > 0
      ? "over"
      : summary.differenceFromOrder < 0
        ? "under"
        : "equal";

  return (
    <main className="rhw-root">
      <header className="rhw-topbar">
        <div className="rhw-topbar-inner">
          <span className="rhw-brand"><PackageCheck size={20} /></span>
          <span className="rhw-title">
            <strong>PDA 成品入库历史</strong>
            <small>只读 · FileMaker 与库存流水实时查询</small>
          </span>
          <span className="rhw-top-actions">
            <span className="rhw-live"><i />实时数据</span>
            <button type="button" onClick={() => void refresh()} disabled={refreshing}>
              <RefreshCw className={refreshing ? "rhw-spin" : ""} size={15} />刷新
            </button>
            <button type="button" onClick={closeWebViewer}><X size={16} />关闭</button>
          </span>
        </div>
      </header>

      <div className="rhw-shell">
        {error && <div className="rhw-banner-error" role="alert"><AlertCircle size={15} />{error}</div>}

        <section className="rhw-product-card">
          <div className="rhw-product-image">
            {line.mainImageUrl ? (
              <img
                src={line.mainImageUrl}
                alt={`${line.productSku} 产品主图`}
                decoding="async"
              />
            ) : (
              <Box size={32} />
            )}
          </div>
          <div className="rhw-product-copy">
            <div className="rhw-kicker">
              <span>{line.documentNumber || line.orderId || "未命名单据"}</span>
              <em>{line.packagingStatus || "包装状态未填写"}</em>
            </div>
            <h1>{line.productSku}</h1>
            <p>{line.productName || line.englishName || "产品名称未填写"}</p>
            {line.productName && line.englishName && <small>{line.englishName}</small>}
          </div>
          <dl className="rhw-order-meta">
            <div><dt>PI / 订单 ID</dt><dd>{line.piNumber || line.orderId || "—"}</dd></div>
            <div><dt>客户</dt><dd>{line.customer || "—"}</dd></div>
            <div><dt>客户 PO</dt><dd>{line.customerPo || "—"}</dd></div>
            <div><dt>包装员</dt><dd>{line.packagingOperator || "—"}</dd></div>
          </dl>
        </section>

      <section className="rhw-summary-grid" aria-label="入库摘要">
        <article>
          <span><FileCheck2 size={17} />正式入库</span>
          <strong>{quantity(summary.officialReceivedQuantity)}<small>件</small></strong>
          <p>{summary.completedReceiptCount} 次已完成记录</p>
        </article>
        <article>
          <span><Box size={17} />订单参考量</span>
          <strong>{quantity(summary.orderReferenceQuantity)}<small>件</small></strong>
          <p>仅供业务调整出货数量参考</p>
        </article>
        <article className={differenceClass}>
          <span>{summary.differenceFromOrder >= 0 ? <ArrowUpRight size={17} /> : <ArrowDownRight size={17} />}数量差异</span>
          <strong>{signedQuantity(summary.differenceFromOrder)}<small>件</small></strong>
          <p>{differenceLabel(summary.differenceFromOrder)}</p>
        </article>
        <article>
          <span><Database size={17} />库存追溯</span>
          <strong>{summary.inventoryMovementCount}<small>条</small></strong>
          <p className={summary.fullyTraceable ? "rhw-ok" : "rhw-warn"}>
            {summary.receiptCount === 0
              ? "暂无入库记录"
              : summary.fullyTraceable
                ? <><ShieldCheck size={13} />ID 关联完整</>
                : "存在未关联记录"}
          </p>
        </article>
      </section>

      <section className="rhw-content-grid">
        <div className="rhw-history-panel">
          <div className="rhw-section-title">
            <span><Clock3 size={17} /></span>
            <div><h2>成品入库记录</h2><p>按 FileMaker 创建时间倒序显示</p></div>
            <strong>{summary.receiptCount}</strong>
          </div>
          {data.receipts.length ? (
            <div className="rhw-timeline">
              {data.receipts.map((receipt, index) => (
                <ReceiptCard key={receipt.receiptId || index} receipt={receipt} index={index} />
              ))}
            </div>
          ) : (
            <div className="rhw-empty">
              <FileCheck2 size={29} />
              <strong>尚无 PDA 成品入库记录</strong>
              <p>这条产品明细仍可在 PDA 填写成品入库数量。</p>
            </div>
          )}
        </div>

        <aside className="rhw-side-panel">
          <section>
            <div className="rhw-section-title compact">
              <span><ImageIcon size={17} /></span>
              <div><h2>收货与出货照片</h2><p>腾讯 COS</p></div>
              <strong>{summary.photoCount}</strong>
            </div>
            {data.photos.length ? (
              <div className="rhw-photo-grid">
                {data.photos.map((photo) => (
                  <a key={photo.attachmentId} href={photo.url || undefined} target="_blank" rel="noreferrer">
                    {photo.url ? (
                      <img src={photo.url} alt={photo.filename} loading="lazy" decoding="async" />
                    ) : (
                      <ImageIcon size={25} />
                    )}
                    <span>{photo.scope === "shipment" ? "出货照片" : "收货图片"}</span>
                    <small>{dateTime(photo.uploadedAt)}</small>
                    {photo.url && <ExternalLink size={12} />}
                  </a>
                ))}
              </div>
            ) : (
              <div className="rhw-empty small"><ImageIcon size={24} /><p>本明细暂无照片</p></div>
            )}
          </section>

          <section className="rhw-source-section">
            <div className="rhw-section-title compact">
              <span><Link2 size={17} /></span>
              <div><h2>追溯键</h2><p>用于核对，不参与显示编号</p></div>
            </div>
            <dl className="rhw-source-list">
              <div><dt>出货单资料 ID</dt><dd>{line.lineId}</dd></div>
              <div><dt>出货单 ID</dt><dd>{line.orderId || "—"}</dd></div>
              <div><dt>最近更新</dt><dd>{dateTime(line.sourceUpdatedAt)}</dd></div>
              <div><dt>当前产品库存</dt><dd>{quantity(line.currentStock)} 件</dd></div>
            </dl>
          </section>
        </aside>
      </section>
      </div>
    </main>
  );
}

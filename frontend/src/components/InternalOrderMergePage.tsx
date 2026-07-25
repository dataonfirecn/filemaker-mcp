import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUpDown,
  Database,
  ExternalLink,
  Layers3,
  RefreshCw,
  Search,
  X
} from "lucide-react";
import type { InternalOrderRow, InternalOrdersResponse, OrderScope } from "../types";
import { parseError } from "../utils/error";

type InternalOrderMergePageProps = {
  apiBase: string;
  token: string;
  customerName: string;
  customerId: string;
  currency: string;
  canViewPrice: boolean;
  canMergeOrders: boolean;
  sessionError?: string | null;
};

type WebMergeResult = {
  ok: boolean;
  duplicate: boolean;
  newOrderId: string;
  newInternalOrderNo: string;
  sourceOrderCount?: number;
  sourceItemCount?: number;
  mergedItemCount?: number;
};

type MergePreviewItem = {
  productNo: string;
  productName: string;
  quantity: string;
};

type WebMergePreview = {
  ok: boolean;
  sourceOrderCount: number;
  sourceItemCount: number;
  mergedItemCount: number;
  items: MergePreviewItem[];
};

type SortKey =
  | "internalOrderNo"
  | "piNo"
  | "orderDate"
  | "amount"
  | "tags"
  | "status"
  | "summary";

type SortDirection = "asc" | "desc";

const pageSizeOptions = [25, 50, 100] as const;
const textCollator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });

declare global {
  interface Window {
    FileMaker?: {
      PerformScript: (scriptName: string, parameter?: string) => void;
    };
    StarRCInternalOrders?: {
      reload: () => void;
    };
  }
}

const closeWebViewerScript = "StarRC_CloseWebViewer";
const openMergedOrderScript = "StarRC_OpenMergedOrder";
const internalOrderCategory = "内部订单";

function createMergeRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function formatAmount(value: number, currency: string): string {
  const normalizedCurrency = currency === "RMB" ? "CNY" : currency === "台币" ? "TWD" : currency;
  if (/^[A-Z]{3}$/.test(normalizedCurrency)) {
    try {
      return new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency: normalizedCurrency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(value);
    } catch {
      // Keep the compact fallback below for non-standard FileMaker currency values.
    }
  }
  return `${currency ? `${currency} ` : ""}${new Intl.NumberFormat("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(value)}`;
}

function formatQuantity(value: string): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return value || "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 }).format(number);
}

function internalOrderLabel(row: InternalOrderRow): string {
  const number = row.internalOrderNo.trim();
  return number.toUpperCase().startsWith("NB") ? number : "内部单号缺失";
}

function orderNumberSearchText(row: InternalOrderRow): string {
  return [
    row.internalOrderNo,
    row.orderId,
    row.piNo,
    row.customerPo
  ]
    .join(" ")
    .toLocaleLowerCase("zh-CN");
}

function tagsForRow(row: InternalOrderRow, scope: OrderScope): string[] {
  const tags = Array.from(
    new Set([...(row.tags ?? []), row.orderCategory, row.orderConfirmation].map((tag) => tag.trim()).filter(Boolean))
  );
  return tags.length ? tags : scope === "internal" ? ["内部订单"] : [];
}

function dateSortValue(value: string): number | string {
  const normalized = value.trim();
  const isoMatch = normalized.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/);
  if (isoMatch) return Date.UTC(Number(isoMatch[1]), Number(isoMatch[2]) - 1, Number(isoMatch[3]));
  const usMatch = normalized.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/);
  if (usMatch) return Date.UTC(Number(usMatch[3]), Number(usMatch[1]) - 1, Number(usMatch[2]));
  return normalized;
}

function sortValue(row: InternalOrderRow, key: SortKey, scope: OrderScope): string | number {
  switch (key) {
    case "piNo":
      return [row.piNo, row.customerPo].join(" ");
    case "orderDate":
      return dateSortValue(row.orderDate);
    case "amount":
      return row.amount ?? 0;
    case "tags":
      return tagsForRow(row, scope).join(" ");
    case "status":
      return [row.packagingStatus, row.paymentStatus, row.elapsedDays].join(" ");
    default:
      return row[key];
  }
}

function visiblePageNumbers(currentPage: number, pageCount: number): number[] {
  const start = Math.max(1, Math.min(currentPage - 1, pageCount - 2));
  const end = Math.min(pageCount, Math.max(currentPage + 1, 3));
  return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
}

export default function InternalOrderMergePage({
  apiBase,
  token,
  customerName,
  customerId,
  currency,
  canViewPrice,
  canMergeOrders,
  sessionError
}: InternalOrderMergePageProps) {
  const [data, setData] = useState<InternalOrdersResponse | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState<OrderScope>("internal");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("internalOrderNo");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [pageSize, setPageSize] = useState<number>(pageSizeOptions[0]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [previewPending, setPreviewPending] = useState(false);
  const [mergePreview, setMergePreview] = useState<WebMergePreview | null>(null);
  const [webMergePending, setWebMergePending] = useState(false);
  const [mergeResult, setMergeResult] = useState<WebMergeResult | null>(null);
  const loadRequestRef = useRef(0);
  const completionRequestRef = useRef(false);

  const loadOrders = useCallback(async () => {
    const requestId = ++loadRequestRef.current;
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      // Fetch the complete customer order set once. Scope switches below are
      // intentionally client-side so they never trigger another FileMaker read.
      const params = new URLSearchParams({ scope: "all" });
      const response = await fetch(`${apiBase}/api/orders/internal?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(await response.text());
      const nextData = (await response.json()) as InternalOrdersResponse;
      if (requestId !== loadRequestRef.current) return;
      setData(nextData);
      setSelected((current) => {
        const available = new Set(nextData.rows.map((row) => row.orderId));
        return new Set(Array.from(current).filter((id) => available.has(id)));
      });
    } catch (reason) {
      if (requestId === loadRequestRef.current) setError(parseError(reason));
    } finally {
      if (requestId === loadRequestRef.current) setLoading(false);
    }
  }, [apiBase, token]);

  useEffect(() => {
    void loadOrders();
  }, [loadOrders]);

  useEffect(() => {
    window.StarRCInternalOrders = {
      reload() {
        void loadOrders();
      }
    };
    return () => {
      delete window.StarRCInternalOrders;
    };
  }, [loadOrders]);

  const scopedRows = useMemo(
    () => scope === "all"
      ? (data?.rows ?? [])
      : (data?.rows ?? []).filter((row) => row.orderCategory.trim() === internalOrderCategory),
    [data, scope]
  );

  const currentTotal = scopedRows.length;

  const filteredRows = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    if (!normalized) return scopedRows;
    return scopedRows.filter((row) => orderNumberSearchText(row).includes(normalized));
  }, [query, scopedRows]);

  const sortedRows = useMemo(() => {
    const direction = sortDirection === "asc" ? 1 : -1;
    return filteredRows
      .map((row, index) => ({ row, index }))
      .sort((left, right) => {
        const leftValue = sortValue(left.row, sortKey, scope);
        const rightValue = sortValue(right.row, sortKey, scope);
        const leftEmpty = leftValue === "";
        const rightEmpty = rightValue === "";
        if (leftEmpty !== rightEmpty) return leftEmpty ? 1 : -1;
        const compared =
          typeof leftValue === "number" && typeof rightValue === "number"
            ? leftValue - rightValue
            : textCollator.compare(String(leftValue), String(rightValue));
        return compared === 0 ? left.index - right.index : compared * direction;
      })
      .map(({ row }) => row);
  }, [filteredRows, scope, sortDirection, sortKey]);

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const normalizedPage = Math.min(page, pageCount);
  const pageStart = (normalizedPage - 1) * pageSize;
  const pageRows = sortedRows.slice(pageStart, pageStart + pageSize);
  const pageNumbers = visiblePageNumbers(normalizedPage, pageCount);

  useEffect(() => {
    setPage(1);
  }, [pageSize, query, scope, sortDirection, sortKey]);

  useEffect(() => {
    setPage((current) => Math.min(current, pageCount));
  }, [pageCount]);

  const selectedRows = useMemo(
    () => (data?.rows ?? []).filter((row) => selected.has(row.orderId)),
    [data, selected]
  );
  const selectedAmount = selectedRows.reduce((total, row) => total + (row.amount ?? 0), 0);
  const selectedTagCounts = useMemo(() => {
    const counts = new Map<string, number>();
    selectedRows.forEach((row) => {
      tagsForRow(row, scope).forEach((tag) => counts.set(tag, (counts.get(tag) ?? 0) + 1));
    });
    return Array.from(counts.entries()).sort((left, right) => right[1] - left[1]);
  }, [scope, selectedRows]);
  const visibleIds = pageRows.map((row) => row.orderId);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  function changeSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(nextKey);
      setSortDirection(nextKey === "orderDate" || nextKey === "amount" ? "desc" : "asc");
    }
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return <ChevronsUpDown size={12} aria-hidden="true" />;
    return sortDirection === "asc"
      ? <ArrowUp size={12} aria-hidden="true" />
      : <ArrowDown size={12} aria-hidden="true" />;
  }

  function sortAria(key: SortKey): "ascending" | "descending" | "none" {
    if (sortKey !== key) return "none";
    return sortDirection === "asc" ? "ascending" : "descending";
  }

  function toggleOrder(orderId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(orderId)) next.delete(orderId);
      else next.add(orderId);
      return next;
    });
    setMergePreview(null);
    setNotice(null);
  }

  function changeScope(nextScope: OrderScope) {
    if (nextScope === scope) return;
    setSelected(new Set());
    setMergePreview(null);
    setNotice(null);
    setScope(nextScope);
  }

  function toggleVisible() {
    setSelected((current) => {
      const next = new Set(current);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
    setMergePreview(null);
  }

  async function openMergePreview() {
    if (selectedRows.length < 2 || previewPending) return;
    setError(null);
    setNotice(null);
    setMergePreview(null);
    setPreviewPending(true);
    try {
      const response = await fetch(`${apiBase}/api/orders/internal/merge/preview`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ orderIds: selectedRows.map((row) => row.orderId) })
      });
      if (!response.ok) throw new Error(await response.text());
      const preview = (await response.json()) as WebMergePreview;
      setMergePreview(preview);
      setConfirmOpen(true);
    } catch (reason) {
      setError(parseError(reason));
    } finally {
      setPreviewPending(false);
    }
  }

  async function performWebMerge() {
    setConfirmOpen(false);
    setError(null);
    setNotice(null);
    setWebMergePending(true);
    try {
      const response = await fetch(`${apiBase}/api/orders/internal/merge/web`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          orderIds: selectedRows.map((row) => row.orderId),
          requestId: createMergeRequestId()
        })
      });
      if (!response.ok) throw new Error(await response.text());
      const result = (await response.json()) as WebMergeResult;
      completionRequestRef.current = false;
      setMergeResult(result);
      setMergePreview(null);
      setSelected(new Set());
    } catch (reason) {
      setError(parseError(reason));
    } finally {
      setWebMergePending(false);
    }
  }

  function finishMerge(scriptName: string, fallbackMessage: string) {
    if (!mergeResult || completionRequestRef.current) return;
    completionRequestRef.current = true;
    const resultPayload = JSON.stringify({
      ok: true,
      mode: "web-data-api",
      duplicate: mergeResult.duplicate,
      newOrderId: mergeResult.newOrderId,
      newInternalOrderNo: mergeResult.newInternalOrderNo,
      sourceOrderCount: mergeResult.sourceOrderCount ?? 0,
      mergedItemCount: mergeResult.mergedItemCount ?? 0
    });
    if (window.FileMaker?.PerformScript) {
      window.FileMaker.PerformScript(scriptName, resultPayload);
      return;
    }
    completionRequestRef.current = false;
    setMergeResult(null);
    setNotice(fallbackMessage);
  }

  function finishAndCloseWebViewer() {
    finishMerge(
      closeWebViewerScript,
      `Data API 合并完成：${mergeResult?.newInternalOrderNo || "新内部订单"}`
    );
  }

  function finishAndOpenMergedOrder() {
    finishMerge(
      openMergedOrderScript,
      `Data API 合并完成：${mergeResult?.newInternalOrderNo || "新内部订单"}。请返回 FileMaker 打开该订单。`
    );
  }

  function renderStatusBar(position: "top" | "bottom") {
    const positionLabel = position === "top" ? "顶部" : "底部";
    return (
      <div className={`internal-merge-statusbar ${position}`} aria-label={`${positionLabel}订单状态栏`}>
        <div className="internal-merge-selection-summary" aria-live="polite">
          <strong>
            {query
              ? `筛选 ${sortedRows.length} / 共 ${currentTotal} 条`
              : `共 ${currentTotal} 条${scope === "internal" ? "内部订单" : "订单"}`}
          </strong>
          <span>{sortedRows.length ? `当前显示 ${pageStart + 1}-${Math.min(pageStart + pageSize, sortedRows.length)} 条` : "当前无数据"}</span>
          {scope === "all" && Boolean(data?.unmergeableCount) && (
            <small>{data?.unmergeableCount} 张缺少可用的业务订单 ID，无法合并</small>
          )}
          {data?.truncated && <small className="warning">订单超过查询上限，当前结果不完整</small>}
        </div>
        <nav className="internal-merge-pagination" aria-label={`${positionLabel}订单分页`}>
          <label>
            每页
            <select value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))} aria-label={`${positionLabel}每页显示条数`}>
              {pageSizeOptions.map((size) => <option value={size} key={size}>{size}</option>)}
            </select>
          </label>
          <span className="internal-merge-page-range">
            第 {normalizedPage} / {pageCount} 页
          </span>
          <div className="internal-merge-page-buttons">
            <button type="button" onClick={() => setPage(1)} disabled={normalizedPage === 1} aria-label={`${positionLabel}第一页`}><ChevronsLeft size={14} /></button>
            <button type="button" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={normalizedPage === 1} aria-label={`${positionLabel}上一页`}><ChevronLeft size={14} /></button>
            {pageNumbers.map((pageNumber) => (
              <button
                type="button"
                className={pageNumber === normalizedPage ? "active" : ""}
                aria-current={pageNumber === normalizedPage ? "page" : undefined}
                onClick={() => setPage(pageNumber)}
                key={pageNumber}
              >
                {pageNumber}
              </button>
            ))}
            <button type="button" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={normalizedPage === pageCount} aria-label={`${positionLabel}下一页`}><ChevronRight size={14} /></button>
            <button type="button" onClick={() => setPage(pageCount)} disabled={normalizedPage === pageCount} aria-label={`${positionLabel}最后一页`}><ChevronsRight size={14} /></button>
          </div>
        </nav>
      </div>
    );
  }

  if (!token) {
    return (
      <section className="internal-merge-boot" aria-live="polite">
        {sessionError ? <div className="internal-merge-error">{sessionError}</div> : <RefreshCw className="spin" size={20} />}
        {!sessionError && <span>正在读取当前客户的全部订单…</span>}
      </section>
    );
  }

  return (
    <section className="internal-merge-embed" aria-label="内部订单合并" aria-busy={loading || previewPending || webMergePending}>
      <header className="internal-merge-header">
        <div className="internal-merge-title">
          <span className="internal-merge-icon"><Layers3 size={19} /></span>
          <div>
            <div className="internal-merge-heading-line">
              <h1>内部订单合并</h1>
              <span className="internal-merge-total">共 {currentTotal} 条</span>
            </div>
            <p>
              <strong>{data?.customerName || customerName || "当前客户"}</strong>
              {scope === "internal" ? " · 仅显示内部订单" : " · 显示全部订单"}
            </p>
          </div>
        </div>
        <div className="internal-merge-actions">
          <div className="internal-merge-scope" role="group" aria-label="订单范围">
            <button
              type="button"
              className={scope === "all" ? "active" : ""}
              aria-pressed={scope === "all"}
              onClick={() => changeScope("all")}
            >
              全部
            </button>
            <button
              type="button"
              className={scope === "internal" ? "active" : ""}
              aria-pressed={scope === "internal"}
              onClick={() => changeScope("internal")}
            >
              内部订单
            </button>
          </div>
          <label className="internal-merge-search">
            <Search size={15} aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="内部单号 / PI / 客户 PO"
              aria-label="搜索订单单号"
            />
            {query && <button type="button" onClick={() => setQuery("")} aria-label="清除搜索"><X size={14} /></button>}
          </label>
          <button className="internal-merge-refresh" type="button" onClick={() => void loadOrders()} disabled={loading}>
            <RefreshCw size={15} className={loading ? "spin" : ""} />
            刷新
          </button>
        </div>
      </header>

      <div className="internal-merge-feedback-stack">
        {(error || sessionError) && <div className="internal-merge-banner error" role="alert">{error || sessionError}</div>}
        {notice && <div className="internal-merge-banner success" role="status"><Check size={15} />{notice}</div>}
        {selectedRows.length > 0 && (
          <aside className="internal-merge-selected-bar" aria-live="polite" aria-label="已选订单汇总">
            <div className="internal-merge-selected-copy">
              <span className="internal-merge-selected-icon"><Check size={16} /></span>
              <span>
                <strong>已选择 {selectedRows.length} 条订单</strong>
                <small>
                  {canViewPrice
                    ? `合计 ${formatAmount(selectedAmount, data?.currency || currency)}`
                    : "金额无查看权限"}
                  {selectedRows.length < 2 ? " · 还需再选择 1 条才能合并" : " · 可查看汇总后合并"}
                </small>
              </span>
            </div>
            <div className="internal-merge-selected-orders" aria-label="部分已选单号">
              {selectedRows.slice(0, 3).map((row) => <span key={row.orderId}>{internalOrderLabel(row)}</span>)}
              {selectedRows.length > 3 && <span>+{selectedRows.length - 3}</span>}
            </div>
            <div className="internal-merge-selected-actions">
              <button type="button" className="secondary" onClick={() => { setSelected(new Set()); setMergePreview(null); }} disabled={loading || previewPending}>清除</button>
              <button type="button" className="primary" onClick={() => void openMergePreview()} disabled={loading || previewPending || selectedRows.length < 2 || !canMergeOrders}>
                <Layers3 size={15} />
                {canMergeOrders ? "查看汇总并合并" : "无合并权限"}
              </button>
            </div>
          </aside>
        )}
      </div>

      {renderStatusBar("top")}

      <div className="internal-merge-table-wrap">
        <table className="internal-merge-table">
          <thead>
            <tr>
              <th className="check-col">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleVisible}
                  aria-label="选择当前页订单"
                />
              </th>
              <th aria-sort={sortAria("internalOrderNo")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("internalOrderNo")}>内部单号{sortIcon("internalOrderNo")}</button>
              </th>
              <th aria-sort={sortAria("piNo")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("piNo")}>PI / 客户 PO{sortIcon("piNo")}</button>
              </th>
              <th aria-sort={sortAria("orderDate")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("orderDate")}>下单日期{sortIcon("orderDate")}</button>
              </th>
              <th className="amount-col" aria-sort={sortAria("amount")}>
                <button type="button" className="internal-merge-sort right" onClick={() => changeSort("amount")} disabled={!canViewPrice}>金额{canViewPrice ? sortIcon("amount") : "（受限）"}</button>
              </th>
              <th aria-sort={sortAria("tags")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("tags")}>标签{sortIcon("tags")}</button>
              </th>
              <th aria-sort={sortAria("status")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("status")}>状态{sortIcon("status")}</button>
              </th>
              <th className="summary-col" aria-sort={sortAria("summary")}>
                <button type="button" className="internal-merge-sort" onClick={() => changeSort("summary")}>概要{sortIcon("summary")}</button>
              </th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row) => {
              const checked = selected.has(row.orderId);
              const rowTags = tagsForRow(row, scope);
              return (
                <tr key={row.orderId} className={checked ? "selected" : ""} onClick={() => toggleOrder(row.orderId)}>
                  <td className="check-col" onClick={(event) => event.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleOrder(row.orderId)}
                      aria-label={`选择 ${row.internalOrderNo}`}
                    />
                  </td>
                  <td><strong>{row.internalOrderNo || "—"}</strong><small>{row.orderId}</small></td>
                  <td><span>{row.piNo || "—"}</span>{row.customerPo && <small>PO {row.customerPo}</small>}</td>
                  <td>{row.orderDate || "—"}</td>
                  <td className="amount-col">{canViewPrice ? formatAmount(row.amount ?? 0, data?.currency || currency) : "无权限"}</td>
                  <td>
                    <span className="internal-merge-tags">
                      {rowTags.length
                        ? rowTags.map((tag) => <span className="internal-merge-tag" key={tag}>{tag}</span>)
                        : <span className="internal-merge-tag muted">—</span>}
                    </span>
                  </td>
                  <td>
                    <span className={`internal-merge-status ${row.packagingStatus ? "active" : "muted"}`}>
                      {row.packagingStatus || "暂无状态"}
                    </span>
                    {(row.paymentStatus || row.elapsedDays) && (
                      <small>{[row.paymentStatus, row.elapsedDays].filter(Boolean).join(" · ")}</small>
                    )}
                  </td>
                  <td className="summary-col" title={row.summary}>{row.summary || "—"}</td>
                </tr>
              );
            })}
            {!loading && sortedRows.length === 0 && (
              <tr className="empty-row">
                <td colSpan={8}>
                  {query
                    ? "没有符合搜索条件的订单"
                    : scope === "internal"
                      ? "当前客户没有可合并的内部订单"
                      : "当前客户没有可合并的订单"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {renderStatusBar("bottom")}

      {(loading || previewPending || webMergePending) && (
        <div className="internal-merge-loading-mask" role="status" aria-live="polite">
          <div className="internal-merge-loading-card">
            <span className="internal-merge-loading-icon" aria-hidden="true">
              <RefreshCw className="spin" size={22} />
            </span>
            <span>
              <strong>{webMergePending ? "正在通过 Data API 合并订单" : previewPending ? "正在生成合并明细预览" : "正在加载客户订单"}</strong>
              <small>{webMergePending ? "正在创建新订单及出货明细，请不要关闭窗口…" : previewPending ? "正在读取并按产品汇总所选订单，不会写入数据…" : "正在从 FileMaker 读取当前客户的数据…"}</small>
            </span>
          </div>
        </div>
      )}

      {confirmOpen && mergePreview && (
        <div className="internal-merge-modal-backdrop" role="presentation" onMouseDown={() => setConfirmOpen(false)}>
          <div className="internal-merge-modal preview" role="dialog" aria-modal="true" aria-labelledby="merge-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="internal-merge-modal-heading">
              <span className="internal-merge-modal-icon"><Layers3 size={22} /></span>
              <span>
                <h2 id="merge-confirm-title">确认合并所选订单</h2>
                <p>请核对来源订单和合并后的出货明细，确认后才会通过 Data API 写入 FileMaker。</p>
              </span>
            </div>

            <dl className="internal-merge-confirm-summary preview">
              <div>
                <dt>订单数量</dt>
                <dd>{selectedRows.length} 条</dd>
              </div>
              <div>
                <dt>金额合计</dt>
                <dd>{canViewPrice ? formatAmount(selectedAmount, data?.currency || currency) : "无查看权限"}</dd>
              </div>
              <div>
                <dt>当前客户</dt>
                <dd>{data?.customerName || customerName || "当前客户"}</dd>
              </div>
              <div>
                <dt>合并后明细</dt>
                <dd>{mergePreview.mergedItemCount} 条</dd>
              </div>
            </dl>

            {selectedTagCounts.length > 0 && (
              <div className="internal-merge-confirm-tags" aria-label="标签汇总">
                <strong>标签汇总</strong>
                <span>
                  {selectedTagCounts.map(([tag, count]) => <em key={tag}>{tag} {count}</em>)}
                </span>
              </div>
            )}

            <div className="internal-merge-confirm-section-title">
              <strong>来源订单</strong>
              <span>{selectedRows.length} 张</span>
            </div>
            <div className="internal-merge-confirm-table-wrap source-orders">
              <table className="internal-merge-confirm-table">
                <thead>
                  <tr>
                    <th>内部单号 / 概要</th>
                    <th>日期</th>
                    <th>金额</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedRows.map((row) => (
                    <tr key={row.orderId}>
                      <td><strong>{internalOrderLabel(row)}</strong><small>{row.summary || row.piNo || "—"}</small></td>
                      <td>{row.orderDate || "—"}</td>
                      <td>{canViewPrice ? formatAmount(row.amount ?? 0, data?.currency || currency) : "无权限"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="internal-merge-confirm-section-title merged">
              <strong>合并后的订单出货明细</strong>
              <span>{mergePreview.sourceItemCount} 条原始明细 → {mergePreview.mergedItemCount} 条汇总明细</span>
            </div>
            <div className="internal-merge-confirm-table-wrap merged-items">
              <table className="internal-merge-confirm-table merged-items">
                <thead>
                  <tr>
                    <th>产品编号</th>
                    <th>产品名称</th>
                    <th>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {mergePreview.items.map((item) => (
                    <tr key={item.productNo}>
                      <td><strong>{item.productNo}</strong></td>
                      <td title={item.productName}>{item.productName || "—"}</td>
                      <td>{formatQuantity(item.quantity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="internal-merge-confirm-note">系统将按产品编号汇总数量，通过 Data API 创建一张新订单及其明细；原订单不会被删除。</p>
            {!data?.webMergeEnabled && (
              <p className="internal-merge-channel-note">Data API 合并尚未在服务器启用，请联系管理员检查专用布局配置。</p>
            )}
            <div className="internal-merge-modal-actions">
              <button type="button" className="secondary" onClick={() => setConfirmOpen(false)}>取消</button>
              <button
                type="button"
                className="primary web"
                onClick={() => void performWebMerge()}
                disabled={!canMergeOrders || !data?.webMergeEnabled || webMergePending || !mergePreview.items.length}
                title={!canMergeOrders ? "当前 FileMaker 权限集未开放合并订单" : !data?.webMergeEnabled ? "服务器尚未启用 Web Data API 合并" : undefined}
              >
                <Database size={15} />
                确认并通过 Data API 合并
              </button>
            </div>
          </div>
        </div>
      )}

      {mergeResult && (
        <div className="internal-merge-modal-backdrop" role="presentation">
          <div className="internal-merge-modal result" role="dialog" aria-modal="true" aria-labelledby="merge-result-title">
            <div className="internal-merge-modal-heading success">
              <span className="internal-merge-modal-icon"><Check size={22} /></span>
              <span>
                <h2 id="merge-result-title">Data API 合并完成</h2>
                <p>{mergeResult.duplicate ? "该请求此前已经成功处理，未重复创建订单。" : "新订单及汇总明细已经写入 FileMaker。"}</p>
              </span>
            </div>
            <dl className="internal-merge-confirm-summary result">
              <div>
                <dt>新内部订单编号</dt>
                <dd>{mergeResult.newInternalOrderNo || "已创建"}</dd>
              </div>
              <div>
                <dt>来源订单</dt>
                <dd>{mergeResult.sourceOrderCount ?? "—"} 条</dd>
              </div>
              <div>
                <dt>汇总明细</dt>
                <dd>{mergeResult.mergedItemCount ?? "—"} 条</dd>
              </div>
            </dl>
            <p className="internal-merge-confirm-note success">请确认上面的新订单编号，然后选择关闭窗口，或直接转到新订单记录。</p>
            <div className="internal-merge-modal-actions">
              <button type="button" className="secondary" onClick={finishAndCloseWebViewer}>
                <Check size={15} />
                完成并关闭窗口
              </button>
              <button type="button" className="primary web" onClick={finishAndOpenMergedOrder}>
                <ExternalLink size={15} />
                完成并打开新订单
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

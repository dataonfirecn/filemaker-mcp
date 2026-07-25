import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Download,
  RefreshCw,
  RotateCcw,
  Search
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type { InventoryTransactionRow, ProductInventoryResponse } from "../types";
import { parseError } from "../utils/error";

type ProductInventoryPageProps = {
  apiBase: string;
  token: string;
  productSku: string;
  sessionError?: string | null;
};

type TypeFilter = "all" | "in" | "out";
type SortDirection = "desc" | "asc";

const integerFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 3 });

function formatQuantity(value: number): string {
  return integerFormatter.format(value);
}

function signedQuantity(value: number): string {
  return `${value >= 0 ? "+" : "-"}${formatQuantity(Math.abs(value))}`;
}

function beginningOfYear(date: string): string {
  const year = date.slice(0, 4);
  return /^\d{4}$/.test(year) ? `${year}-01-01` : "";
}

function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function escapeCsv(value: string | number): string {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export default function ProductInventoryPage({
  apiBase,
  token,
  productSku,
  sessionError
}: ProductInventoryPageProps) {
  const [data, setData] = useState<ProductInventoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [query, setQuery] = useState("");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [collapsedYears, setCollapsedYears] = useState<Set<number>>(new Set());

  async function loadInventory() {
    if (!token || !productSku) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `${apiBase}/api/products/${encodeURIComponent(productSku)}/inventory-transactions`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!response.ok) throw new Error(await response.text());
      const nextData = (await response.json()) as ProductInventoryResponse;
      setData(nextData);
      const dates = nextData.rows.map((row) => row.date).filter(Boolean).sort();
      const firstDate = dates[0] ?? "";
      const lastDate = dates[dates.length - 1] ?? "";
      setStartDate((current) => current || beginningOfYear(firstDate));
      setEndDate((current) => current || (todayIso() > lastDate ? todayIso() : lastDate));
    } catch (reason) {
      setError(parseError(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadInventory();
  }, [token, productSku]);

  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
    const rows = (data?.rows ?? []).filter((row) => {
      if (startDate && row.date < startDate) return false;
      if (endDate && row.date > endDate) return false;
      if (typeFilter !== "all" && row.type !== typeFilter) return false;
      if (!normalizedQuery) return true;
      return [row.orderBatchNo, row.description, row.operator, row.date]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedQuery);
    });
    return rows.sort((left, right) => {
      const result = left.date.localeCompare(right.date) || left.recordId.localeCompare(right.recordId);
      return sortDirection === "asc" ? result : -result;
    });
  }, [data, endDate, query, sortDirection, startDate, typeFilter]);

  const groupedRows = useMemo(() => {
    const groups = new Map<number, InventoryTransactionRow[]>();
    filteredRows.forEach((row) => {
      const current = groups.get(row.year) ?? [];
      current.push(row);
      groups.set(row.year, current);
    });
    return Array.from(groups.entries()).sort(([left], [right]) =>
      sortDirection === "desc" ? right - left : left - right
    );
  }, [filteredRows, sortDirection]);

  const csvDownload = useMemo(() => {
    const header = ["日期", "类型", "订单/批次号", "描述", "数量(pcs)", "操作员", "结余(pcs)"];
    const rows = filteredRows.map((row) => [
      row.date,
      row.type === "in" ? "入库" : "出库",
      row.orderBatchNo,
      row.description,
      signedQuantity(row.signedQty),
      row.operator,
      formatQuantity(row.balance)
    ]);
    const csv = `\uFEFF${[header, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n")}`;
    return {
      href: `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`,
      filename: `${productSku || "product"}-inventory.csv`
    };
  }, [filteredRows, productSku]);

  const chartData = useMemo(
    () =>
      (data?.trend ?? []).map((point) => ({
        ...point,
        year: point.date.slice(0, 4)
      })),
    [data]
  );

  const chartTicks = useMemo(() => {
    const firstDateByYear = new Map<string, string>();
    chartData.forEach((point) => {
      if (!firstDateByYear.has(point.year)) firstDateByYear.set(point.year, point.date);
    });
    return Array.from(firstDateByYear.values());
  }, [chartData]);

  const latest = data?.rows[0] ?? null;

  function resetFilters() {
    const dates = (data?.rows ?? []).map((row) => row.date).filter(Boolean).sort();
    const firstDate = dates[0] ?? "";
    const lastDate = dates[dates.length - 1] ?? "";
    setStartDate(beginningOfYear(firstDate));
    setEndDate(todayIso() > lastDate ? todayIso() : lastDate);
    setTypeFilter("all");
    setQuery("");
    setSortDirection("desc");
    setCollapsedYears(new Set());
  }

  function toggleYear(year: number) {
    setCollapsedYears((current) => {
      const next = new Set(current);
      if (next.has(year)) next.delete(year);
      else next.add(year);
      return next;
    });
  }

  if (!token) {
    return (
      <section className="inventory-boot-state" aria-live="polite">
        {sessionError ? (
          <div className="inventory-error-card">{sessionError}</div>
        ) : (
          <>
            <RefreshCw className="inventory-spin" size={22} />
            <span>正在建立只读会话…</span>
          </>
        )}
      </section>
    );
  }

  return (
    <section className="inventory-embed" aria-label="产品出入库记录">
      <aside className="inventory-summary-panel">
        <div className="inventory-stock-block">
          <div className="inventory-stat-label">当前库存</div>
          <div className="inventory-stock-value">
            <strong>{formatQuantity(data?.summary.currentStock ?? 0)}</strong>
            <span>pcs</span>
          </div>
        </div>

        <dl className="inventory-summary-list">
          <div>
            <dt>入库合计</dt>
            <dd className="inbound">{formatQuantity(data?.summary.inboundTotal ?? 0)} <small>pcs</small></dd>
          </div>
          <div>
            <dt>出库合计</dt>
            <dd className="outbound">{formatQuantity(data?.summary.outboundTotal ?? 0)} <small>pcs</small></dd>
          </div>
          <div>
            <dt>净变化</dt>
            <dd className={(data?.summary.netChange ?? 0) >= 0 ? "inbound" : "outbound"}>
              {signedQuantity(data?.summary.netChange ?? 0)} <small>pcs</small>
            </dd>
          </div>
        </dl>

        <div className="inventory-chart-block">
          <h2>库存余额趋势 <span>（pcs）</span></h2>
          <div className="inventory-chart" aria-label="库存余额趋势图">
            {chartData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 12, right: 8, bottom: 4, left: -15 }}>
                  <CartesianGrid stroke="#d8e3ef" strokeDasharray="2 2" vertical={false} />
                  <XAxis
                    dataKey="date"
                    ticks={chartTicks}
                    tickFormatter={(value) => String(value).slice(0, 4)}
                    tick={{ fill: "#516882", fontSize: 10 }}
                    axisLine={{ stroke: "#d7e0ea" }}
                    tickLine={false}
                  />
                  <YAxis
                    domain={["dataMin - 10", "dataMax + 10"]}
                    allowDecimals={false}
                    tick={{ fill: "#516882", fontSize: 10 }}
                    axisLine={{ stroke: "#d7e0ea" }}
                    tickLine={false}
                  />
                  <Tooltip
                    formatter={(value) => [`${formatQuantity(Number(value))} pcs`, "库存"]}
                    labelFormatter={(label) => String(label)}
                    contentStyle={{ border: "1px solid #d7e0ea", borderRadius: 6, fontSize: 11 }}
                  />
                  <Line
                    type="stepAfter"
                    dataKey="balance"
                    stroke="#1769e0"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 3, fill: "#1769e0" }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="inventory-chart-empty">暂无趋势数据</div>
            )}
          </div>
        </div>

        <div className="inventory-latest-block">
          <h2>最新变动</h2>
          {latest ? (
            <div className="inventory-latest-row">
              <time>{latest.date}</time>
              <span className={`inventory-movement-icon ${latest.type}`}>
                {latest.type === "in" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
              </span>
              <span>{latest.type === "in" ? "入库" : "出库"}</span>
              <strong className={latest.type === "in" ? "inbound" : "outbound"}>
                {signedQuantity(latest.signedQty)}
              </strong>
              <small>pcs</small>
            </div>
          ) : (
            <div className="inventory-empty-inline">暂无记录</div>
          )}
        </div>

        <div className="inventory-status-block">
          <h2>状态</h2>
          <span className="inventory-readonly-badge">只读（不可编辑）</span>
        </div>
      </aside>

      <div className="inventory-records-panel">
        <div className="inventory-toolbar">
          <label className="inventory-filter-field date-field">
            <span>开始日期</span>
            <span className="inventory-date-input">
              <input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              <CalendarDays size={15} aria-hidden="true" />
            </span>
          </label>
          <span className="inventory-date-separator">～</span>
          <label className="inventory-filter-field date-field">
            <span>结束日期</span>
            <span className="inventory-date-input">
              <input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
              <CalendarDays size={15} aria-hidden="true" />
            </span>
          </label>
          <label className="inventory-filter-field type-field">
            <span>类型</span>
            <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}>
              <option value="all">全部</option>
              <option value="in">入库</option>
              <option value="out">出库</option>
            </select>
          </label>
          <label className="inventory-search-field">
            <Search size={18} aria-hidden="true" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="订单号 / 批次号 / 备注"
              aria-label="搜索库存记录"
            />
          </label>
          <button className="inventory-button secondary" type="button" onClick={resetFilters}>
            <RotateCcw size={15} />
            重置
          </button>
          {filteredRows.length ? (
            <a className="inventory-button export" href={csvDownload.href} download={csvDownload.filename}>
              <Download size={16} />
              导出 CSV
            </a>
          ) : (
            <button className="inventory-button export" type="button" disabled>
              <Download size={16} />
              导出 CSV
            </button>
          )}
        </div>

        <div className="inventory-table-frame" aria-busy={loading}>
          <div className="inventory-table-header inventory-grid-row">
            <button
              type="button"
              className="inventory-sort-button"
              onClick={() => setSortDirection((current) => (current === "desc" ? "asc" : "desc"))}
            >
              日期
              <span className={sortDirection === "asc" ? "ascending" : "descending"}>◆</span>
            </button>
            <span>类型</span>
            <span>订单 / 批次号</span>
            <span>描述</span>
            <span className="numeric">数量（pcs）</span>
            <span>操作员</span>
          </div>

          <div className="inventory-table-body">
            {loading && !data ? (
              <div className="inventory-table-state">
                <RefreshCw className="inventory-spin" size={20} />
                正在读取库存流水…
              </div>
            ) : error ? (
              <div className="inventory-table-state error">
                <span>{error}</span>
                <button type="button" onClick={() => void loadInventory()}>重新读取</button>
              </div>
            ) : groupedRows.length ? (
              groupedRows.map(([year, rows]) => {
                const collapsed = collapsedYears.has(year);
                return (
                  <section className="inventory-year-group" key={year}>
                    <button type="button" className="inventory-year-row" onClick={() => toggleYear(year)}>
                      {collapsed ? <ChevronRight size={15} /> : <ChevronDown size={15} />}
                      <strong>{year}</strong>
                      <span className="inventory-sr-only">{rows.length} 条</span>
                    </button>
                    {!collapsed && rows.map((row) => (
                      <div className="inventory-grid-row inventory-data-row" key={row.recordId || `${row.date}-${row.orderBatchNo}`}>
                        <time>{row.date}</time>
                        <span className="inventory-type-cell">
                          <span className={`inventory-movement-icon ${row.type}`}>
                            {row.type === "in" ? <ArrowUp size={13} /> : <ArrowDown size={13} />}
                          </span>
                          {row.type === "in" ? "入库" : "出库"}
                        </span>
                        <span className="inventory-batch-cell" title={row.orderBatchNo}>{row.orderBatchNo || "—"}</span>
                        <span className="inventory-description-cell" title={row.description}>
                          {row.description || (row.type === "in" ? "入库记录" : "出库记录")}
                        </span>
                        <strong className={`inventory-quantity-cell ${row.type === "in" ? "inbound" : "outbound"}`}>
                          {signedQuantity(row.signedQty)}
                        </strong>
                        <span className="inventory-operator-cell" title={row.operator}>{row.operator || "—"}</span>
                      </div>
                    ))}
                  </section>
                );
              })
            ) : (
              <div className="inventory-table-state">没有符合当前条件的记录</div>
            )}
          </div>

          <footer className="inventory-table-footer">
            <span>共 {filteredRows.length} 条记录</span>
            <div className="inventory-pagination" aria-label="分页">
              <button type="button" disabled aria-label="上一页"><ChevronLeft size={15} /></button>
              <span>1</span>
              <em>/ 1</em>
              <button type="button" disabled aria-label="下一页"><ChevronRight size={15} /></button>
            </div>
          </footer>
        </div>
      </div>
    </section>
  );
}

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import { ArrowDownWideNarrow, ArrowUpNarrowWide, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Card, EmptyState, IconButton, Input, Loading, Pagination, usePageSize } from "./ui";
import DataGrid from "./DataGrid";
import { numberFilterParams } from "./grid-config";
import { orderStatusTone } from "../utils/statusTone";
import { parseError } from "../utils/error";
import type { OrderList, OrderListRow } from "./orderList";
import "./DemandOrdersPage.css";

const PAGE_SIZES = [25, 50, 100] as const;

type Props = {
  apiBase: string; token: string; canView: boolean; canViewPrice: boolean; currency: string;
  onOpen: (orderId: string) => void;
};

function Status({ text }: { text: string }) {
  return text ? <Badge tone={orderStatusTone(text)}>{text}</Badge> : <span className="demand-muted">—</span>;
}

function formatAmount(value: number | null | undefined, currency: string): string {
  if (value == null) return "—";
  const code = currency === "RMB" ? "CNY" : currency === "台币" ? "TWD" : currency || "USD";
  try {
    return new Intl.NumberFormat("zh-CN", { style: "currency", currency: code }).format(value);
  } catch {
    // FileMaker 里的币种可能不是标准代码，退回「代码 + 数字」。
    return `${currency ? `${currency} ` : ""}${value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}`;
  }
}

/**
 * 订单列表：与需求单列表同一模式（搜索 + AG Grid + 分页）。点订单号或双击行进入出货单明细；
 * 没有对应出货单 ID 的记录仍会列出，但不能打开明细。
 */
export default function OrderListPage({ apiBase, token, canView, canViewPrice, currency, onOpen }: Props) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = usePageSize("orders:page-size", PAGE_SIZES, 25);
  const [revision, setRevision] = useState(0);
  const [list, setList] = useState<OrderList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // App 每次渲染都会传入新的回调；用 ref 让列定义保持稳定，避免表格重置列宽和顺序。
  const openRef = useRef(onOpen);
  openRef.current = onOpen;

  useEffect(() => {
    const controller = new AbortController();
    if (!canView || !token) { setLoading(false); return; }
    setLoading(true); setError("");
    const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize), sort });
    void fetch(`${apiBase}/api/orders?${params}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(await response.text()); return response.json() as Promise<OrderList>; })
      .then(setList)
      .catch(err => { if (!controller.signal.aborted) setError(parseError(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [apiBase, token, canView, query, sort, page, pageSize, revision]);

  const columns = useMemo<ColDef<OrderListRow>[]>(() => {
    // 默认只显示常用列；PI 编号、客户订单号、分类、已过天数可在「调整字段」里打开。
    const cols: ColDef<OrderListRow>[] = [
      {
        colId: "orderId", field: "orderId", headerName: "订单号", pinned: "left", width: 150, minWidth: 140, suppressMovable: true,
        cellRenderer: ({ data, value }: ICellRendererParams<OrderListRow, string>) =>
          data && value ? <button className="grid-link" type="button" onClick={() => openRef.current(value)}>{value}</button>
            : <span className="demand-muted" title="没有对应的出货单，无法打开明细">—</span>
      },
      { colId: "internalOrderNo", field: "internalOrderNo", headerName: "内部订单", width: 170, minWidth: 160, valueFormatter: ({ value }) => value || "—" },
      { colId: "customerName", field: "customerName", headerName: "客户", minWidth: 160, flex: 1, valueFormatter: ({ value }) => value || "—" },
      { colId: "summary", field: "summary", headerName: "订单概要", minWidth: 200, flex: 1, valueFormatter: ({ value }) => value || "—" },
      { colId: "piNo", field: "piNo", hide: true, headerName: "PI 编号", minWidth: 160, valueFormatter: ({ value }) => value || "—" },
      { colId: "customerPo", field: "customerPo", hide: true, headerName: "客户订单号", width: 140, valueFormatter: ({ value }) => value || "—" },
      { colId: "orderDate", field: "orderDate", headerName: "订单日期", width: 120, minWidth: 110, valueFormatter: ({ value }) => value || "—" },
      {
        colId: "packagingStatus", field: "packagingStatus", headerName: "包装状态", width: 130, minWidth: 110,
        cellRenderer: ({ value }: ICellRendererParams<OrderListRow, string>) => <Status text={value ?? ""} />
      },
      {
        colId: "paymentStatus", field: "paymentStatus", headerName: "付款状态", width: 130, minWidth: 110,
        cellRenderer: ({ value }: ICellRendererParams<OrderListRow, string>) => <Status text={value ?? ""} />
      },
      { colId: "elapsedDays", field: "elapsedDays", hide: true, headerName: "已过天数", width: 120, valueFormatter: ({ value }) => value || "—" },
      { colId: "orderCategory", field: "orderCategory", hide: true, headerName: "订单分类", width: 130, valueFormatter: ({ value }) => value || "—" }
    ];
    if (canViewPrice) {
      cols.splice(7, 0, {
        colId: "amount", field: "amount", headerName: "订单金额", width: 140, minWidth: 130, filter: "agNumberColumnFilter",
        filterParams: numberFilterParams, cellClass: "numeric-cell", headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatAmount(value, currency)
      });
    }
    return cols;
  }, [canViewPrice, currency]);

  if (!canView) return <div className="demand-page"><Alert>当前账号没有查看订单的权限，请联系管理员开放订单资料权限。</Alert></div>;
  return <div className="demand-page">
    <div className="demand-toolbar">
      <div className="demand-actions"><span className="demand-muted">全部订单</span></div>
      <IconButton label="刷新数据" loading={loading} disabled={loading} onClick={() => setRevision(n => n + 1)}><RefreshCw /></IconButton>
    </div>
    <Card><form className="demand-filters" onSubmit={event => { event.preventDefault(); setPage(1); setQuery(draft.trim()); }}>
      <label className="demand-search">搜索订单<Input value={draft} onChange={e => setDraft(e.target.value)} placeholder="订单号、内部订单、PI、客户订单号、客户或概要" maxLength={100} /></label>
      <Button type="submit" variant="primary"><Search />搜索</Button>
      <Button title="切换订单排序方向" onClick={() => { setSort(current => current === "newest" ? "oldest" : "newest"); setPage(1); }}>
        {sort === "newest" ? <ArrowDownWideNarrow /> : <ArrowUpNarrowWide />}{sort === "newest" ? "最近优先" : "最早优先"}
      </Button>
      {(query || draft) && <Button onClick={() => { setDraft(""); setQuery(""); setPage(1); }}>重置</Button>}
    </form></Card>
    {error ? <Alert>{error} <Button onClick={() => setRevision(n => n + 1)}>重新读取</Button></Alert>
      : loading && !list ? <Card><Loading label="正在读取订单列表" /></Card>
      : list && <Card className="demand-list-card">{list.rows.length ? <>
        <div className="demand-list-head"><span className="demand-muted">共 {list.foundCount.toLocaleString()} 张订单 · 按订单日期由{sort === "newest" ? "新到旧" : "旧到新"}排列 · 点击订单号查看出货单明细</span></div>
        <DataGrid gridKey="orders" columns={columns} rows={list.rows} getRowId={r => r.recordId || r.internalOrderNo} loading={loading} csvFileName="orders"
          onRowDoubleClicked={r => { if (r.orderId) openRef.current(r.orderId); }} />
        <Pagination page={page} pageSize={pageSize} totalCount={list.foundCount} rowCount={list.rows.length} loading={loading} onPageChange={setPage}
          pageSizeOptions={PAGE_SIZES} onPageSizeChange={size => { setPageSize(size); setPage(1); }} />
      </> : <EmptyState title="没有找到订单" description="试试其他单号、客户或概要关键词，或重置搜索条件。" />}</Card>}
  </div>;
}

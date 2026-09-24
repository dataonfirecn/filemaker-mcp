import type { ColDef, ICellRendererParams } from "ag-grid-community";
import { ArrowLeft, ChevronLeft, ChevronRight, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, EmptyState, IconButton, Input, Loading, Select } from "./ui";
import DataGrid from "./DataGrid";
import { dateFilterParams, numberFilterParams } from "./grid-config";
import { demandStatusTone } from "../utils/statusTone";
import { parseError } from "../utils/error";
import type { DemandDetail, DemandLine, DemandList, DemandOrder } from "./demandOrders";
import "./DemandOrdersPage.css";

type Props = { apiBase: string; token: string; recordId: string; canView: boolean; onOpen: (id: string) => void; onBack: () => void };
const value = (text: string | undefined) => text || "—";
const quantity = (number: number | null) => number == null ? "—" : number.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
function Status({ text }: { text: string }) { return text ? <Badge tone={demandStatusTone(text)}>{text}</Badge> : <span className="demand-muted">—</span>; }

export default function DemandOrdersPage({ apiBase, token, recordId, canView, onOpen, onBack }: Props) {
  const [draft, setDraft] = useState("");
  const [filters, setFilters] = useState({ q: "", completion: "all" });
  const [page, setPage] = useState(1);
  const [linePage, setLinePage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [list, setList] = useState<DemandList | null>(null);
  const [detail, setDetail] = useState<DemandDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => { setLinePage(1); }, [recordId]);
  useEffect(() => {
    const controller = new AbortController();
    if (!canView || !token) { setLoading(false); return; }
    setLoading(true); setError("");
    const params = new URLSearchParams({ q: filters.q, completion: filters.completion, page: String(page), page_size: "25" });
    const path = recordId ? `/api/demand-orders/${encodeURIComponent(recordId)}?page=${linePage}` : `/api/demand-orders?${params}`;
    void fetch(`${apiBase}${path}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(await response.text()); return response.json(); })
      .then(data => { if (recordId) setDetail(data as DemandDetail); else setList(data as DemandList); })
      .catch(err => { if (!controller.signal.aborted) setError(parseError(err)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [apiBase, token, canView, recordId, filters, page, linePage, revision]);

  const orderColumns = useMemo<ColDef<DemandOrder>[]>(() => [
    {
      colId: "id", field: "id", headerName: "需求单号", pinned: "left", width: 160, suppressMovable: true,
      cellRenderer: ({ data, value }: ICellRendererParams<DemandOrder, string>) =>
        data ? <button className="grid-link" type="button" onClick={() => onOpen(data.recordId)}>{value}</button> : (value ?? "")
    },
    { colId: "internalOrderNo", field: "internalOrderNo", headerName: "内部订单", width: 150, valueFormatter: ({ value }) => value || "—" },
    { colId: "summary", field: "summary", headerName: "需求概要", minWidth: 220, flex: 1, valueFormatter: ({ value }) => value || "—" },
    { colId: "company", field: "company", headerName: "需求公司", minWidth: 160, flex: 1, valueFormatter: ({ value }) => value || "—" },
    { colId: "orderDate", field: "orderDate", headerName: "开单日期", width: 120, filter: "agDateColumnFilter", filterParams: dateFilterParams, valueFormatter: ({ value }) => value || "—" },
    { colId: "dueDate", field: "dueDate", headerName: "需求期限", width: 120, filter: "agDateColumnFilter", filterParams: dateFilterParams, valueFormatter: ({ value }) => value || "—" },
    {
      colId: "reviewStatus", field: "reviewStatus", headerName: "审核状态", width: 130,
      cellRenderer: ({ value }: ICellRendererParams<DemandOrder, string>) => <Status text={value ?? ""} />
    },
    {
      colId: "purchaseStatus", field: "purchaseStatus", headerName: "采购状态", width: 130,
      cellRenderer: ({ value }: ICellRendererParams<DemandOrder, string>) => <Status text={value ?? ""} />
    },
    { colId: "completedDate", field: "completedDate", headerName: "完成日期", width: 120, filter: "agDateColumnFilter", filterParams: dateFilterParams, valueFormatter: ({ value }) => value || "—" }
  ], [onOpen]);

  const lineColumns = useMemo<ColDef<DemandLine>[]>(() => [
    { colId: "partNo", field: "partNo", headerName: "零件编号", width: 140, pinned: "left", suppressMovable: true },
    { colId: "partName", field: "partName", headerName: "零件名称", minWidth: 200, flex: 1, valueFormatter: ({ value }) => value || "—" },
    {
      colId: "quantity", field: "quantity", headerName: "需求数量", width: 110, filter: "agNumberColumnFilter",
      filterParams: numberFilterParams, cellClass: "numeric-cell", headerClass: "numeric-header",
      valueFormatter: ({ value }) => quantity(value)
    },
    {
      colId: "extraQuantity", field: "extraQuantity", headerName: "额外数量", width: 110, filter: "agNumberColumnFilter",
      filterParams: numberFilterParams, cellClass: "numeric-cell", headerClass: "numeric-header",
      valueFormatter: ({ value }) => quantity(value)
    },
    {
      colId: "receivedQuantity", field: "receivedQuantity", headerName: "入库数量", width: 110, filter: "agNumberColumnFilter",
      filterParams: numberFilterParams, cellClass: "numeric-cell", headerClass: "numeric-header",
      valueFormatter: ({ value }) => quantity(value)
    },
    { colId: "dueDate", field: "dueDate", headerName: "需求日期", width: 120, filter: "agDateColumnFilter", filterParams: dateFilterParams, valueFormatter: ({ value }) => value || "—" },
    {
      colId: "status", field: "status", headerName: "需求状态", width: 120,
      cellRenderer: ({ value }: ICellRendererParams<DemandLine, string>) => <Status text={value ?? ""} />
    },
    {
      colId: "purchaseStatus", field: "purchaseStatus", headerName: "采购状态", width: 120,
      cellRenderer: ({ value }: ICellRendererParams<DemandLine, string>) => <Status text={value ?? ""} />
    },
    { colId: "supplier", field: "supplier", headerName: "加工厂商", width: 140, valueFormatter: ({ value }) => value || "—" },
    {
      colId: "notes", headerName: "备注", minWidth: 220, flex: 1,
      valueGetter: ({ data }) => [data?.notes, data?.extraNotes].filter(Boolean).join("；"),
      valueFormatter: ({ value }) => value || "—"
    }
  ], []);

  const order = detail?.order;
  const totalPages = recordId ? detail?.totalPages ?? 1 : list?.totalPages ?? 1;
  const currentPage = recordId ? linePage : page;
  const changePage = recordId ? setLinePage : setPage;
  if (!canView) return <div className="demand-page"><Alert>当前账号没有查看需求单的权限，请联系管理员开放订单资料权限。</Alert></div>;
  return <div className="demand-page">
    <div className="demand-toolbar">
      <div className="demand-actions">{recordId && <IconButton label="返回列表" onClick={onBack}><ArrowLeft /></IconButton>}<span className="demand-muted">{recordId ? "需求单资料" : "零件需求清单"}</span></div>
      <IconButton label="刷新数据" loading={loading} disabled={loading} onClick={() => setRevision(n => n + 1)}><RefreshCw /></IconButton>
    </div>
    {!recordId && <Card><form className="demand-filters" onSubmit={event => { event.preventDefault(); setPage(1); setFilters(current => ({ ...current, q: draft.trim() })); }}>
      <label className="demand-search">搜索需求单<Input value={draft} onChange={e => setDraft(e.target.value)} placeholder="需求单号、内部订单、概要或公司" maxLength={100} /></label>
      <label>完成日期<Select value={filters.completion} onChange={e => { setPage(1); setFilters(current => ({ ...current, completion: e.target.value })); }}><option value="all">全部需求单</option><option value="open">未填写完成日期</option><option value="completed">已填写完成日期</option></Select></label>
      <Button type="submit" variant="primary"><Search />搜索</Button>
      {(filters.q || filters.completion !== "all" || draft) && <Button onClick={() => { setDraft(""); setFilters({ q: "", completion: "all" }); setPage(1); }}>重置</Button>}
    </form></Card>}
    {error ? <Alert>{error} <Button onClick={() => setRevision(n => n + 1)}>重新读取</Button></Alert> : loading ? <Card><Loading label={recordId ? "正在读取需求单及零件明细" : "正在读取需求单列表"} /></Card> : recordId && order ? <>
      <Card><div className="demand-detail-heading"><div><span className="demand-muted">需求单</span><h2>{value(order.id)}</h2><p>{value(order.summary)}</p></div><div className="demand-statuses"><Status text={order.reviewStatus} /><Status text={order.purchaseStatus} /></div></div>
        <dl className="demand-fields">{[
          ["内部订单", order.internalOrderNo], ["需求公司", order.company], ["类型", order.type], ["开单日期", order.orderDate],
          ["需求期限", order.dueDate], ["完成日期", order.completedDate], ["开单人", order.createdBy], ["需求方式", order.method],
          ["关联 BOM", order.bomId], ["修改人", order.modifiedBy], ["修改时间", order.modifiedAt]
        ].map(([label, text]) => <div key={label}><dt>{label}</dt><dd>{value(text)}</dd></div>)}</dl>
        {order.notes && <div className="demand-note-section"><h3>采购单注解</h3><p className="demand-notes">{order.notes}</p></div>}
      </Card>
      <Card><h3>零件需求明细 <span className="demand-muted">{detail.foundCount.toLocaleString()} 条</span></h3>{detail.items.length ? <DataGrid gridKey="demand-order-lines" columns={lineColumns} rows={detail.items} getRowId={r => r.id} loading={loading} csvFileName={`demand-order-${order.id || recordId}-lines`} /> : <EmptyState title="暂无零件明细" description="这张需求单尚未关联零件需求记录。" />}</Card>
    </> : !recordId && list && <Card className="demand-list-card">{list.rows.length ? <>
      <div className="demand-list-head"><span className="demand-muted">共 {list.foundCount.toLocaleString()} 张需求单 · 按开单日期由新到旧排列</span></div>
      <DataGrid gridKey="demand-orders" columns={orderColumns} rows={list.rows} getRowId={r => r.recordId} loading={loading} csvFileName="demand-orders" onRowDoubleClicked={r => onOpen(r.recordId)} />
    </> : <EmptyState title="没有找到需求单" description="试试其他单号或公司名称，或重置筛选条件。" />}</Card>}
    {!loading && !error && <div className="demand-pagination"><span>第 {currentPage} / {totalPages} 页</span><div className="demand-actions"><Button disabled={currentPage <= 1} onClick={() => changePage(p => p - 1)}><ChevronLeft />上一页</Button><Button disabled={currentPage >= totalPages} onClick={() => changePage(p => p + 1)}>下一页<ChevronRight /></Button></div></div>}
  </div>;
}

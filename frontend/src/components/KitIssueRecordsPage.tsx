import { AgGridReact } from "ag-grid-react";
import type { ColDef, GridReadyEvent } from "ag-grid-community";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Download, RotateCcw, Search } from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  agGridZhCN,
  defaultAutoSizeStrategy,
  defaultTableColDef,
  gridFloatingFilterHeight,
  gridHeaderHeight,
  gridRowHeight
} from "./grid-config";
import type { KitIssueRecordsResponse, KitIssueRow } from "../types";

export type KitIssueRecordsPageProps = {
  data: KitIssueRecordsResponse | null;
  columns: ColDef<KitIssueRow>[];
  orderNo: string;
  loading?: boolean;
  onOrderNoChange: (value: string) => void;
  onSearch: () => void;
  onReset: () => void;
  onPageChange: (page: number) => void;
};

export default function KitIssueRecordsPage({
  data,
  columns,
  orderNo,
  loading,
  onOrderNoChange,
  onSearch,
  onReset,
  onPageChange
}: KitIssueRecordsPageProps) {
  const gridRef = useRef<AgGridReact<KitIssueRow>>(null);
  const [pageDraft, setPageDraft] = useState("1");
  const page = data?.page ?? 1;
  const pageSize = data?.pageSize ?? 100;
  const totalPages = data?.totalPages ?? 1;
  const foundCount = data?.foundCount ?? 0;
  const rows = data?.rows ?? [];
  const firstRow = foundCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = foundCount === 0 ? 0 : firstRow + rows.length - 1;

  useEffect(() => {
    setPageDraft(String(page));
  }, [page]);

  const restoreColumnState = useCallback(() => {
    if (!gridRef.current) return;
    try {
      const raw = localStorage.getItem("ag-grid-state:kit-issue-records");
      if (raw) {
        gridRef.current.api.applyColumnState({ state: JSON.parse(raw), applyOrder: true });
      }
    } catch {
      // Ignore corrupted state
    }
  }, []);

  const saveColumnState = useCallback(() => {
    if (!gridRef.current) return;
    try {
      const state = gridRef.current.api.getColumnState();
      localStorage.setItem("ag-grid-state:kit-issue-records", JSON.stringify(state));
    } catch {
      // Ignore storage errors
    }
  }, []);

  function onGridReady(event: GridReadyEvent<KitIssueRow>) {
    event.api.sizeColumnsToFit();
    restoreColumnState();
  }

  function exportCsv() {
    const suffix = data?.orderNo ? `-${data.orderNo}` : "";
    gridRef.current?.api.exportDataAsCsv({
      fileName: `kit-issue-records${suffix}-${new Date().toISOString().slice(0, 10)}.csv`
    });
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch();
  }

  function submitPageJump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextPage = Number(pageDraft);
    if (!Number.isFinite(nextPage)) return;
    onPageChange(Math.min(Math.max(1, Math.trunc(nextPage)), totalPages));
  }

  return (
    <>
      <section className="kit-issue-summary" aria-label="零件包发料摘要">
        <div>
          <span className="meta-label">布局</span>
          <strong className="meta-value">{data?.layout ?? "零件包 發料分类"}</strong>
        </div>
        <div>
          <span className="meta-label">记录</span>
          <strong className="meta-value qty">{foundCount.toLocaleString("zh-CN")}</strong>
        </div>
        <div>
          <span className="meta-label">每页</span>
          <strong className="meta-value qty">{pageSize}</strong>
        </div>
        <div>
          <span className="meta-label">唯一字段</span>
          <strong className="meta-value qty">{data?.fields.length ?? 23}</strong>
        </div>
      </section>

      <section className="card data-card kit-issue-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>零件包发料分类</h3>
            <span className="record-count">
              {firstRow}-{lastRow} / {foundCount.toLocaleString("zh-CN")} 条
            </span>
          </div>
          <button className="btn ghost" onClick={exportCsv} disabled={rows.length === 0}>
            <Download size={15} />
            导出 CSV
          </button>
        </div>
        <div className="card-toolbar kit-issue-toolbar">
          <form className="kit-filter-form" onSubmit={submitSearch}>
            <label className="grid-search" htmlFor="kitOrderNo">
              <Search size={15} />
              <input
                id="kitOrderNo"
                value={orderNo}
                onChange={(event) => onOrderNoChange(event.target.value)}
                placeholder="订单号，如 NB07088"
              />
            </label>
            <button className="btn primary" type="submit" disabled={loading}>
              <Search size={15} />
              查询
            </button>
            <button className="btn ghost" type="button" onClick={onReset} disabled={loading || (!orderNo && !data?.orderNo)}>
              <RotateCcw size={15} />
              重置
            </button>
          </form>
          <div className="kit-page-status">
            第 {page.toLocaleString("zh-CN")} / {totalPages.toLocaleString("zh-CN")} 页
          </div>
        </div>
        <div className="grid full kit-issue-grid ag-theme-quartz">
          <AgGridReact
            ref={gridRef}
            theme="legacy"
            rowData={rows}
            columnDefs={columns}
            defaultColDef={defaultTableColDef}
            localeText={agGridZhCN}
            getRowId={({ data }) => data.recordId}
            rowHeight={gridRowHeight}
            headerHeight={gridHeaderHeight}
            floatingFiltersHeight={gridFloatingFilterHeight}
            autoSizeStrategy={defaultAutoSizeStrategy}
            loading={loading}
            overlayLoadingTemplate={"<span class=\"ag-overlay-loading-center\">加载中...</span>"}
            overlayNoRowsTemplate={"<span class=\"ag-overlay-no-rows-center\">暂无数据</span>"}
            onGridReady={onGridReady}
            onColumnResized={saveColumnState}
            onColumnMoved={saveColumnState}
            onSortChanged={saveColumnState}
            onFilterChanged={saveColumnState}
            onColumnPinned={saveColumnState}
          />
        </div>
        <div className="kit-pager">
          <span className="kit-pager-range">
            {firstRow}-{lastRow} / {foundCount.toLocaleString("zh-CN")}
          </span>
          <div className="kit-pager-actions">
            <button
              className="btn icon"
              type="button"
              title="首页"
              aria-label="首页"
              onClick={() => onPageChange(1)}
              disabled={loading || page <= 1}
            >
              <ChevronsLeft size={16} />
            </button>
            <button
              className="btn icon"
              type="button"
              title="上一页"
              aria-label="上一页"
              onClick={() => onPageChange(page - 1)}
              disabled={loading || page <= 1}
            >
              <ChevronLeft size={16} />
            </button>
            <form className="page-jump" onSubmit={submitPageJump}>
              <input
                aria-label="页码"
                min={1}
                max={totalPages}
                type="number"
                value={pageDraft}
                onChange={(event) => setPageDraft(event.target.value)}
              />
              <button className="btn" type="submit" disabled={loading}>
                跳转
              </button>
            </form>
            <button
              className="btn icon"
              type="button"
              title="下一页"
              aria-label="下一页"
              onClick={() => onPageChange(page + 1)}
              disabled={loading || page >= totalPages}
            >
              <ChevronRight size={16} />
            </button>
            <button
              className="btn icon"
              type="button"
              title="末页"
              aria-label="末页"
              onClick={() => onPageChange(totalPages)}
              disabled={loading || page >= totalPages}
            >
              <ChevronsRight size={16} />
            </button>
          </div>
        </div>
      </section>
      <div className="page-footer-spacer" aria-hidden="true" />
    </>
  );
}

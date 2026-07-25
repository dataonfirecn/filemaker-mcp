import { AgGridReact } from "ag-grid-react";
import type { ColDef, GridReadyEvent, RowDoubleClickedEvent } from "ag-grid-community";
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
import type { BusinessProductFilters, BusinessProductRow, BusinessProductsResponse } from "../types";

export type BusinessProductsPageProps = {
  data: BusinessProductsResponse | null;
  columns: ColDef<BusinessProductRow>[];
  query: string;
  filters: BusinessProductFilters;
  loading?: boolean;
  onQueryChange: (value: string) => void;
  onFilterChange: (key: keyof BusinessProductFilters, value: string) => void;
  onSearch: () => void;
  onReset: () => void;
  onPageChange: (page: number) => void;
  onOpenDetail: (row: BusinessProductRow) => void;
};

export default function BusinessProductsPage({
  data,
  columns,
  query,
  filters,
  loading,
  onQueryChange,
  onFilterChange,
  onSearch,
  onReset,
  onPageChange,
  onOpenDetail
}: BusinessProductsPageProps) {
  const gridRef = useRef<AgGridReact<BusinessProductRow>>(null);
  const [pageDraft, setPageDraft] = useState("1");
  const page = data?.page ?? 1;
  const pageSize = data?.pageSize ?? 50;
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
      const raw = localStorage.getItem("ag-grid-state:business-products");
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
      localStorage.setItem("ag-grid-state:business-products", JSON.stringify(state));
    } catch {
      // Ignore storage errors
    }
  }, []);

  function onGridReady(event: GridReadyEvent<BusinessProductRow>) {
    event.api.sizeColumnsToFit();
    restoreColumnState();
  }

  function exportCsv() {
    const suffix = query.trim() ? `-${query.trim()}` : "";
    gridRef.current?.api.exportDataAsCsv({
      fileName: `business-products${suffix}-${new Date().toISOString().slice(0, 10)}.csv`
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

  function handleRowDoubleClick(event: RowDoubleClickedEvent<BusinessProductRow>) {
    if (event.data) onOpenDetail(event.data);
  }

  return (
    <>
      <section className="kit-issue-summary product-directory-summary" aria-label="产品资料摘要">
        <div>
          <span className="meta-label">FileMaker 布局</span>
          <strong className="meta-value">{data?.layout ?? "@products"}</strong>
        </div>
        <div>
          <span className="meta-label">产品记录</span>
          <strong className="meta-value qty">{foundCount.toLocaleString("zh-CN")}</strong>
        </div>
        <div>
          <span className="meta-label">每页</span>
          <strong className="meta-value qty">{pageSize}</strong>
        </div>
        <div>
          <span className="meta-label">当前页</span>
          <strong className="meta-value qty">
            {page.toLocaleString("zh-CN")} / {totalPages.toLocaleString("zh-CN")}
          </strong>
        </div>
      </section>

      <section className="card data-card kit-issue-card product-directory-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>产品资料列表</h3>
            <span className="record-count">
              {firstRow}-{lastRow} / {foundCount.toLocaleString("zh-CN")} 条
            </span>
          </div>
          <button className="btn ghost" onClick={exportCsv} disabled={rows.length === 0}>
            <Download size={15} />
            导出 CSV
          </button>
        </div>

        <div className="card-toolbar product-directory-toolbar">
          <form className="product-filter-form" onSubmit={submitSearch}>
            <label className="grid-search product-main-search" htmlFor="businessProductQuery">
              <Search size={15} />
              <input
                id="businessProductQuery"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="产品编号、名称、车款、客户"
              />
            </label>
            <input
              className="filter-input"
              value={filters.model}
              onChange={(event) => onFilterChange("model", event.target.value)}
              placeholder="车款"
              aria-label="车款"
            />
            <input
              className="filter-input"
              value={filters.category}
              onChange={(event) => onFilterChange("category", event.target.value)}
              placeholder="类别"
              aria-label="类别"
            />
            <input
              className="filter-input"
              value={filters.audit}
              onChange={(event) => onFilterChange("audit", event.target.value)}
              placeholder="审核"
              aria-label="审核"
            />
            <input
              className="filter-input"
              value={filters.client}
              onChange={(event) => onFilterChange("client", event.target.value)}
              placeholder="客户"
              aria-label="客户"
            />
            <button className="btn primary" type="submit" disabled={loading}>
              <Search size={15} />
              查询
            </button>
            <button className="btn ghost" type="button" onClick={onReset} disabled={loading}>
              <RotateCcw size={15} />
              重置
            </button>
          </form>
        </div>

        <div className="grid full product-directory-grid ag-theme-quartz">
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
            onRowDoubleClicked={handleRowDoubleClick}
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

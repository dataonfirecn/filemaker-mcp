import { AgGridReact } from "ag-grid-react";
import type {
  ColDef,
  ColumnState,
  GridReadyEvent,
  ICellRendererParams,
  RowDoubleClickedEvent,
  SortChangedEvent
} from "ag-grid-community";
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Columns3,
  Download,
  ImageOff,
  Info,
  LoaderCircle,
  Maximize2,
  RotateCcw,
  Rows3,
  Search,
  X
} from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  agGridZhCN,
  defaultTableColDef,
  formatQty,
  gridHeaderHeight,
  numberFilterParams
} from "./grid-config";
import type { BusinessProductFilters, BusinessProductRow, BusinessProductsResponse } from "../types";

/**
 * Column layout is persisted under a versioned key. Bump the version whenever
 * column ids change, so a stale saved layout can never hide the new columns.
 */
const COLUMN_STATE_KEY = "ag-grid-state:business-products:v2";
const DENSITY_KEY = "business-products:density";

const ROW_HEIGHT = { compact: 40, comfortable: 56 } as const;
const THUMB_SIZE = { compact: 30, comfortable: 44 } as const;

type Density = keyof typeof ROW_HEIGHT;

/** Columns hidden by default: still one click away, but out of the way. */
const OPTIONAL_COLUMNS = ["scale", "bomCount", "client", "category1", "category2", "category3", "bomDate"];

export type BusinessProductsPageProps = {
  apiBase: string;
  token: string;
  data: BusinessProductsResponse | null;
  query: string;
  filters: BusinessProductFilters;
  loading?: boolean;
  pageSizeOptions: number[];
  onQueryChange: (value: string) => void;
  onFilterChange: (key: keyof BusinessProductFilters, value: string) => void;
  onSearch: () => void;
  onReset: () => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  onOpenDetail: (row: BusinessProductRow) => void;
};

function readDensity(): Density {
  try {
    const stored = localStorage.getItem(DENSITY_KEY);
    if (stored === "compact" || stored === "comfortable") return stored;
  } catch {
    // Ignore storage errors and fall back to the default density.
  }
  return "comfortable";
}

export default function BusinessProductsPage({
  apiBase,
  token,
  data,
  query,
  filters,
  loading,
  pageSizeOptions,
  onQueryChange,
  onFilterChange,
  onSearch,
  onReset,
  onPageChange,
  onPageSizeChange,
  onOpenDetail
}: BusinessProductsPageProps) {
  const gridRef = useRef<AgGridReact<BusinessProductRow>>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [pageDraft, setPageDraft] = useState("1");
  const [density, setDensity] = useState<Density>(readDensity);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);
  const [pageScoped, setPageScoped] = useState(false);
  const [preview, setPreview] = useState<BusinessProductRow | null>(null);

  const page = data?.page ?? 1;
  const pageSize = data?.pageSize ?? 50;
  const totalPages = data?.totalPages ?? 1;
  const foundCount = data?.foundCount ?? 0;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const firstRow = foundCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = foundCount === 0 ? 0 : firstRow + rows.length - 1;

  useEffect(() => {
    setPageDraft(String(page));
  }, [page]);

  // "/" jumps to the search box, the way it does in most catalog tools.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA" || target?.isContentEditable;
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
      if (event.key === "Escape") setPreview(null);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const saveColumnState = useCallback(() => {
    if (!gridRef.current) return;
    try {
      const state = gridRef.current.api.getColumnState();
      localStorage.setItem(COLUMN_STATE_KEY, JSON.stringify(state));
      setHiddenColumns(state.filter((column) => column.hide).map((column) => column.colId));
    } catch {
      // Ignore storage errors; the layout simply will not survive a reload.
    }
  }, []);

  function onGridReady(event: GridReadyEvent<BusinessProductRow>) {
    // No sizeColumnsToFit() here: the name column carries flex:1 and absorbs
    // the spare width, so squeezing every column into the viewport would only
    // undo the widths the user set by hand.
    let restored = false;
    try {
      const raw = localStorage.getItem(COLUMN_STATE_KEY);
      if (raw) {
        event.api.applyColumnState({ state: JSON.parse(raw) as ColumnState[], applyOrder: true });
        restored = true;
      }
    } catch {
      // Corrupted state falls through to the defaults below.
    }
    if (!restored) {
      event.api.applyColumnState({
        state: OPTIONAL_COLUMNS.map((colId) => ({ colId, hide: true }))
      });
    }
    setHiddenColumns(
      event.api.getColumnState().filter((column) => column.hide).map((column) => column.colId)
    );
  }

  /**
   * Header sorting and the per-column filter menus both run client-side, over
   * the rows of the current page only. That is invisible next to a toolbar
   * that queries all 10k records, so say it out loud whenever one is active.
   */
  const refreshScopeHint = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    setPageScoped(api.getColumnState().some((column) => column.sort) || api.isAnyFilterPresent());
  }, []);

  function handleSortChanged(_event: SortChangedEvent<BusinessProductRow>) {
    refreshScopeHint();
    saveColumnState();
  }

  function resetLayout() {
    try {
      localStorage.removeItem(COLUMN_STATE_KEY);
    } catch {
      // Ignore storage errors; the in-memory reset below still applies.
    }
    gridRef.current?.api.resetColumnState();
    gridRef.current?.api.applyColumnState({
      state: OPTIONAL_COLUMNS.map((colId) => ({ colId, hide: true }))
    });
    setHiddenColumns(OPTIONAL_COLUMNS);
    setPageScoped(false);
  }

  function autoSizeColumns() {
    const api = gridRef.current?.api;
    if (!api) return;
    api.autoSizeAllColumns(false);
    saveColumnState();
  }

  function toggleColumn(colId: string, visible: boolean) {
    gridRef.current?.api.setColumnsVisible([colId], visible);
    saveColumnState();
  }

  function changeDensity(next: Density) {
    setDensity(next);
    try {
      localStorage.setItem(DENSITY_KEY, next);
    } catch {
      // Ignore storage errors; the choice simply will not survive a reload.
    }
  }

  function exportCsv() {
    const api = gridRef.current?.api;
    if (!api) return;
    const suffix = query.trim() ? `-${query.trim()}` : "";
    api.exportDataAsCsv({
      // The thumbnail column holds an image, not a value worth exporting.
      columnKeys: api
        .getAllDisplayedColumns()
        .map((column) => column.getColId())
        .filter((colId) => colId !== "thumbnail"),
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

  const thumbSize = THUMB_SIZE[density];

  // The toolbar above already filters server-side across all pages. A floating
  // filter row would look identical but silently filter the current page only,
  // so this grid opts out of it.
  const gridColDef = useMemo<ColDef>(() => ({ ...defaultTableColDef, floatingFilter: false }), []);

  const columns = useMemo<ColDef<BusinessProductRow>[]>(
    () => [
      {
        colId: "thumbnail",
        headerName: "",
        width: thumbSize + 20,
        minWidth: thumbSize + 20,
        maxWidth: thumbSize + 20,
        pinned: "left",
        sortable: false,
        filter: false,
        resizable: false,
        suppressMovable: true,
        suppressHeaderMenuButton: true,
        cellClass: "product-thumb-cell",
        cellRenderer: ({ data }: ICellRendererParams<BusinessProductRow>) => {
          if (!data) return null;
          if (!data.thumbnailUrl) {
            return (
              <span className="product-thumb empty" title={data.imageStatus || "暂无图片"}>
                <ImageOff size={14} />
              </span>
            );
          }
          return (
            <button
              className="product-thumb"
              type="button"
              onClick={() => setPreview(data)}
              aria-label={`查看 ${data.productSku} 的产品大图`}
              title="查看大图"
            >
              {/* Signed URL: a plain <img> can carry no bearer token, so the
                  list response mints a short-lived ticket per row. */}
              <img src={`${apiBase}${data.thumbnailUrl}`} alt="" loading="lazy" decoding="async" />
              <span className="product-thumb-zoom">
                <Maximize2 size={10} />
              </span>
            </button>
          );
        }
      },
      {
        field: "productSku",
        colId: "productSku",
        headerName: "产品编号",
        width: 150,
        pinned: "left",
        cellRenderer: ({ data, value }: ICellRendererParams<BusinessProductRow, string>) =>
          data ? (
            <button className="grid-link" type="button" onClick={() => onOpenDetail(data)} title="打开产品详情">
              {value}
            </button>
          ) : (
            value ?? ""
          )
      },
      {
        colId: "productName",
        headerName: "产品名称",
        minWidth: 280,
        flex: 1,
        // One value for sorting and CSV export, two lines on screen.
        valueGetter: ({ data }) =>
          [data?.productNameCn, data?.productName].filter(Boolean).join(" / "),
        cellClass: "product-name-cell",
        cellRenderer: ({ data }: ICellRendererParams<BusinessProductRow>) => {
          if (!data) return null;
          const cn = data.productNameCn?.trim();
          const en = data.productName?.trim();
          return (
            <span className="product-name-stack" title={[cn, en].filter(Boolean).join("\n")}>
              <span className="product-name-primary">{cn || en || "—"}</span>
              {cn && en && en !== cn ? <span className="product-name-secondary">{en}</span> : null}
            </span>
          );
        }
      },
      { field: "modelName", colId: "modelName", headerName: "车款", width: 150 },
      { field: "scale", colId: "scale", headerName: "比例", width: 90 },
      { field: "category", colId: "category", headerName: "类别", width: 110 },
      {
        field: "auditStatus",
        colId: "auditStatus",
        headerName: "审核",
        width: 105,
        cellRenderer: ({ value }: ICellRendererParams<BusinessProductRow, string>) =>
          value ? (
            <span className={`status-chip ${value.includes("未") ? "muted" : "success"}`}>{value}</span>
          ) : (
            ""
          )
      },
      {
        field: "stock",
        colId: "stock",
        headerName: "库存",
        width: 100,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "customer", colId: "customer", headerName: "客户", width: 150 },
      {
        field: "bomCount",
        colId: "bomCount",
        headerName: "BOM",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "client", colId: "client", headerName: "Client", width: 120 },
      { field: "category1", colId: "category1", headerName: "分类 1", width: 140 },
      { field: "category2", colId: "category2", headerName: "分类 2", width: 140 },
      { field: "category3", colId: "category3", headerName: "分类 3", width: 160 },
      { field: "bomDate", colId: "bomDate", headerName: "BOM 日期", width: 120 }
    ],
    [apiBase, onOpenDetail, thumbSize]
  );

  const toggleableColumns = useMemo(
    () => columns.filter((column) => column.colId && column.colId !== "thumbnail" && column.colId !== "productSku"),
    [columns]
  );

  return (
    <>
      <section className="kit-issue-summary product-directory-summary" aria-label="产品资料摘要">
        <div>
          <span className="meta-label">数据来源</span>
          <strong className="meta-value">{data?.layout ?? "—"}</strong>
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
          <div className="card-head-actions">
            <div className="column-menu-wrap">
              <button
                className="btn ghost"
                type="button"
                onClick={() => setColumnMenuOpen((open) => !open)}
                aria-expanded={columnMenuOpen}
                title="选择要显示的列"
              >
                <Columns3 size={15} />
                列{hiddenColumns.length > 0 ? ` · 隐藏 ${hiddenColumns.length}` : ""}
              </button>
              {columnMenuOpen && (
                <>
                  <div className="column-menu-backdrop" onClick={() => setColumnMenuOpen(false)} />
                  <div className="column-menu" role="menu">
                    <div className="column-menu-head">
                      <span>显示的列</span>
                      <button type="button" className="btn-link" onClick={resetLayout}>
                        恢复默认
                      </button>
                    </div>
                    <div className="column-menu-list">
                    {toggleableColumns.map((column) => {
                      const colId = column.colId as string;
                      const visible = !hiddenColumns.includes(colId);
                      return (
                        <label key={colId} className="column-menu-item">
                          <input
                            type="checkbox"
                            checked={visible}
                            onChange={(event) => toggleColumn(colId, event.target.checked)}
                          />
                          <span>{column.headerName}</span>
                        </label>
                      );
                    })}
                    </div>
                    <div className="column-menu-foot">
                      <button type="button" className="btn-link" onClick={autoSizeColumns}>
                        按内容自适应列宽
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
            <button
              className="btn ghost"
              type="button"
              onClick={() => changeDensity(density === "compact" ? "comfortable" : "compact")}
              title={density === "compact" ? "切换到舒适行高" : "切换到紧凑行高"}
            >
              <Rows3 size={15} />
              {density === "compact" ? "紧凑" : "舒适"}
            </button>
            <button className="btn ghost" onClick={exportCsv} disabled={rows.length === 0}>
              <Download size={15} />
              导出 CSV
            </button>
          </div>
        </div>

        <div className="card-toolbar product-directory-toolbar">
          <form className="product-filter-form" onSubmit={submitSearch}>
            <label className="grid-search product-main-search" htmlFor="businessProductQuery">
              <Search size={15} />
              <input
                id="businessProductQuery"
                ref={searchRef}
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="产品编号、名称、车款、客户（按 / 聚焦）"
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

        {pageScoped && (
          <p className="grid-scope-hint">
            <Info size={13} />
            表头的排序和筛选只作用于当前这一页的 {rows.length} 条记录；要在全部{" "}
            {foundCount.toLocaleString("zh-CN")} 条里查找，请用上面的搜索框和筛选条件。
          </p>
        )}

        <div className={`grid full product-directory-grid ag-theme-quartz density-${density}`}>
          <AgGridReact
            ref={gridRef}
            theme="legacy"
            rowData={rows}
            columnDefs={columns}
            defaultColDef={gridColDef}
            localeText={agGridZhCN}
            getRowId={({ data }) => data.recordId}
            rowHeight={ROW_HEIGHT[density]}
            headerHeight={gridHeaderHeight}
            loading={loading}
            overlayLoadingTemplate={"<span class=\"ag-overlay-loading-center\">加载中...</span>"}
            overlayNoRowsTemplate={"<span class=\"ag-overlay-no-rows-center\">暂无数据</span>"}
            onGridReady={onGridReady}
            onRowDoubleClicked={handleRowDoubleClick}
            onColumnResized={({ finished }) => finished && saveColumnState()}
            onColumnMoved={({ finished }) => finished && saveColumnState()}
            onSortChanged={handleSortChanged}
            onFilterChanged={refreshScopeHint}
            onColumnPinned={saveColumnState}
          />
        </div>

        <div className="kit-pager">
          <span className="kit-pager-range">
            {firstRow}-{lastRow} / {foundCount.toLocaleString("zh-CN")}
          </span>
          <div className="kit-pager-actions">
            <label className="page-size-select">
              每页
              <select
                value={pageSize}
                disabled={loading}
                onChange={(event) => onPageSizeChange(Number(event.target.value))}
                aria-label="每页条数"
              >
                {pageSizeOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
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

      {preview && (
        <ProductImagePreview
          apiBase={apiBase}
          token={token}
          product={preview}
          onClose={() => setPreview(null)}
          onOpenDetail={onOpenDetail}
        />
      )}
      <div className="page-footer-spacer" aria-hidden="true" />
    </>
  );
}

type ProductImagePreviewProps = {
  apiBase: string;
  token: string;
  product: BusinessProductRow;
  onClose: () => void;
  onOpenDetail: (row: BusinessProductRow) => void;
};

/**
 * Shows the cached thumbnail immediately, then swaps in the full-resolution
 * image once it arrives. The full image needs the bearer token, so it is
 * fetched rather than pointed at with a plain src.
 */
function ProductImagePreview({ apiBase, token, product, onClose, onOpenDetail }: ProductImagePreviewProps) {
  const [fullImage, setFullImage] = useState("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!token || !product.recordId) return;
    let objectUrl = "";
    let cancelled = false;
    setFullImage("");
    setFailed(false);
    void (async () => {
      try {
        const response = await fetch(
          `${apiBase}/api/business-products/${encodeURIComponent(product.recordId)}/image`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (!response.ok) throw new Error(String(response.status));
        const blob = await response.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setFullImage(objectUrl);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [apiBase, token, product.recordId]);

  return (
    <div className="product-preview-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="product-preview" onClick={(event) => event.stopPropagation()}>
        <header className="product-preview-head">
          <div>
            <strong>{product.productSku}</strong>
            <span>{product.productNameCn || product.productName || "—"}</span>
          </div>
          <button className="btn icon" type="button" onClick={onClose} aria-label="关闭预览">
            <X size={16} />
          </button>
        </header>
        <div className="product-preview-body">
          <img
            className={fullImage ? "" : "placeholder"}
            src={fullImage || `${apiBase}${product.thumbnailUrl}`}
            alt={product.productNameCn || product.productName || product.productSku}
          />
          {!fullImage && !failed && (
            <span className="product-preview-spinner">
              <LoaderCircle className="spin" size={22} />
            </span>
          )}
          {failed && <span className="product-preview-error">原图读取失败，当前显示缩略图。</span>}
        </div>
        <footer className="product-preview-foot">
          <button
            className="btn primary"
            type="button"
            onClick={() => {
              onClose();
              onOpenDetail(product);
            }}
          >
            打开产品详情
          </button>
        </footer>
      </div>
    </div>
  );
}

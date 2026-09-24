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
  ArrowDownWideNarrow,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Columns3,
  Download,
  ImageOff,
  LoaderCircle,
  Maximize2,
  SlidersHorizontal,
  MoreHorizontal,
  Search,
  X
} from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  agGridZhCN,
  defaultTableColDef,
  formatQty,
  gridHeaderHeight
} from "./grid-config";
import { formatStamp } from "../utils/timestamp";
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

const EMPTY_FILTERS: BusinessProductFilters = { model: "", category: "", audit: "", client: "" };
const FILTER_FIELDS = [["model", "车款"], ["category", "类别"], ["audit", "审核"], ["client", "客户"]] as const;

/** Columns hidden by default: still one click away, but out of the way. */
const OPTIONAL_COLUMNS = ["scale", "bomCount", "client", "category1", "category2", "category3", "bomDate"];

export type BusinessProductsPageProps = {
  apiBase: string;
  token: string;
  data: BusinessProductsResponse | null;
  query: string;
  filters: BusinessProductFilters;
  /** 服务端排序：default 为默认顺序，recent 为按建立日期由新到旧（对全部记录生效）。 */
  sort: "default" | "recent";
  loading?: boolean;
  pageSizeOptions: number[];
  onSearch: (query: string, filters: BusinessProductFilters) => Promise<boolean>;
  onSortChange: (sort: "default" | "recent") => Promise<boolean>;
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
  sort,
  loading,
  pageSizeOptions,
  onSearch,
  onSortChange,
  onPageChange,
  onPageSizeChange,
  onOpenDetail
}: BusinessProductsPageProps) {
  const gridRef = useRef<AgGridReact<BusinessProductRow>>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [queryDraft, setQueryDraft] = useState(query);
  const [filterDraft, setFilterDraft] = useState(filters);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const settingsButtonRef = useRef<HTMLButtonElement>(null);
  const moreButtonRef = useRef<HTMLButtonElement>(null);
  const filterButtonRef = useRef<HTMLButtonElement>(null);
  const activeFilters = FILTER_FIELDS.filter(([key]) => filters[key].trim());
  const [pageDraft, setPageDraft] = useState("1");
  const [density, setDensity] = useState<Density>(readDensity);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);
  const [pageScoped, setPageScoped] = useState(false);
  const [preview, setPreview] = useState<BusinessProductRow | null>(null);

  const page = data?.page ?? 1;
  const pageSize = data?.pageSize ?? 50;
  const totalPages = Math.max(1, data?.totalPages ?? 1);
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

  useEffect(() => {
    function dismiss(event: PointerEvent) {
      const target = event.target as Node;
      if (!settingsRef.current?.contains(target)) setColumnMenuOpen(false);
      if (!moreRef.current?.contains(target)) setMoreOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      if (columnMenuOpen) { setColumnMenuOpen(false); settingsButtonRef.current?.focus(); }
      if (moreOpen) { setMoreOpen(false); moreButtonRef.current?.focus(); }
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [columnMenuOpen, moreOpen]);

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
    setPageScoped(event.api.getColumnState().some((column) => Boolean(column.sort)));
    setHiddenColumns(
      event.api.getColumnState().filter((column) => column.hide).map((column) => column.colId)
    );
  }

  // Column sorting is local to the loaded page.
  const refreshScopeHint = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    setPageScoped(api.getColumnState().some((column) => column.sort));
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

  async function applySearch(nextQuery: string, nextFilters: BusinessProductFilters) {
    if (loading) return;
    if (await onSearch(nextQuery, nextFilters)) {
      setQueryDraft(nextQuery.trim());
      setFilterDraft(Object.fromEntries(Object.entries(nextFilters).map(([key, value]) => [key, value.trim()])) as BusinessProductFilters);
      setFiltersOpen(false);
      if (filtersOpen) filterButtonRef.current?.focus();
      else searchRef.current?.focus();
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void applySearch(queryDraft, filtersOpen ? filterDraft : filters);
  }

  function submitPageJump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextPage = Number(pageDraft);
    if (loading || !pageDraft.trim() || !Number.isFinite(nextPage)) return;
    const bounded = Math.min(Math.max(1, Math.trunc(nextPage)), totalPages);
    setPageDraft(String(bounded));
    onPageChange(bounded);
  }

  function handleRowDoubleClick(event: RowDoubleClickedEvent<BusinessProductRow>) {
    if (event.data) onOpenDetail(event.data);
  }

  const thumbSize = THUMB_SIZE[density];

  // The toolbar above already filters server-side across all pages. A floating
  // filter row would look identical but silently filter the current page only,
  // so this grid opts out of it.
  const gridColDef = useMemo<ColDef>(() => ({ ...defaultTableColDef, floatingFilter: false, filter: false, suppressHeaderMenuButton: true }), []);

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
      { field: "modelName", colId: "modelName", headerName: "车款", minWidth: 160, flex: 1 },
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
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "customer", colId: "customer", headerName: "客户", minWidth: 160, flex: 1 },
      {
        colId: "createdAt",
        headerName: "建立日期",
        width: 150,
        valueGetter: ({ data }) => formatStamp(data?.createdAt),
        valueFormatter: ({ value }) => value || "—"
      },
      {
        field: "bomCount",
        colId: "bomCount",
        headerName: "BOM",
        width: 95,
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
      <section className="card data-card kit-issue-card product-directory-card" aria-label="产品资料列表">
        <div className="product-directory-toolbar">
          <form className="product-search-form" onSubmit={submitSearch}>
            <label className="grid-search product-main-search" htmlFor="businessProductQuery">
              <Search size={15} />
              <input id="businessProductQuery" ref={searchRef} value={queryDraft}
                onChange={(event) => setQueryDraft(event.target.value)} disabled={loading}
                aria-label="搜索产品" placeholder="搜索产品编号、名称、车款、客户" title="按 / 聚焦搜索" />
            </label>
            <button className="btn primary" type="submit" disabled={loading}>搜索</button>
          </form>
          <button className={`btn ${sort === "recent" ? "secondary" : "ghost"}`} type="button" aria-pressed={sort === "recent"}
            disabled={loading} title="按建立日期由新到旧排列全部产品，再点一次恢复默认顺序"
            onClick={() => { if (!loading) void onSortChange(sort === "recent" ? "default" : "recent"); }}>
            <ArrowDownWideNarrow size={15} />最近创建
          </button>
          <button ref={filterButtonRef} className={`btn ${activeFilters.length ? "secondary" : "ghost"}`}
            type="button" aria-expanded={filtersOpen} aria-controls="product-filters"
            onClick={() => setFiltersOpen((open) => !open)}>
            <SlidersHorizontal size={15} />筛选{activeFilters.length > 0 ? ` · ${activeFilters.length}` : ""}
          </button>
          <div className="column-menu-wrap" ref={settingsRef}
            onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setColumnMenuOpen(false); }}>
            <button className="btn ghost" type="button" ref={settingsButtonRef}
              aria-expanded={columnMenuOpen} aria-controls="product-table-settings"
              onClick={() => { setColumnMenuOpen((open) => !open); setMoreOpen(false); }}>
              <Columns3 size={15} />表格设置
            </button>
            {columnMenuOpen && (
              <div className="column-menu product-settings-menu" id="product-table-settings" aria-label="表格设置">
                <div className="column-menu-head"><span>显示的列</span>
                  <button type="button" className="btn-link" onClick={resetLayout}>恢复默认</button>
                </div>
                <div className="column-menu-list">
                  {toggleableColumns.map((column) => (
                    <label key={column.colId} className="column-menu-item">
                      <input type="checkbox" checked={!hiddenColumns.includes(column.colId as string)}
                        onChange={(event) => toggleColumn(column.colId as string, event.target.checked)} />
                      <span>{column.headerName}</span>
                    </label>
                  ))}
                </div>
                <div className="product-settings-density">
                  <label htmlFor="product-row-density">行高</label>
                  <select id="product-row-density" value={density} onChange={(event) => changeDensity(event.target.value as Density)}>
                    <option value="comfortable">舒适</option><option value="compact">紧凑</option>
                  </select>
                </div>
                <div className="column-menu-foot">
                  <button type="button" className="btn-link" onClick={autoSizeColumns}>按内容自适应列宽</button>
                </div>
              </div>
            )}
          </div>
          <div className="column-menu-wrap" ref={moreRef}
            onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setMoreOpen(false); }}>
            <button className="btn ghost" type="button" ref={moreButtonRef} aria-expanded={moreOpen}
              aria-controls="product-more-actions" onClick={() => { setMoreOpen((open) => !open); setColumnMenuOpen(false); }}>
              <MoreHorizontal size={16} />更多
            </button>
            {moreOpen && <div className="column-menu product-more-menu" id="product-more-actions">
              <button className="btn ghost" type="button" disabled={loading || rows.length === 0}
                onClick={() => { exportCsv(); setMoreOpen(false); moreButtonRef.current?.focus(); }}>
                <Download size={15} />导出当前页 CSV
              </button>
            </div>}
          </div>
        </div>

        {filtersOpen && <form id="product-filters" className="product-filter-panel" onSubmit={submitSearch}>
          <fieldset disabled={loading}>
            <legend className="sr-only">筛选产品</legend>
            {FILTER_FIELDS.map(([key, label]) => <label key={key} className="product-filter-field">
              <span>{label}</span>
              <input className="filter-input" value={filterDraft[key]}
                onChange={(event) => setFilterDraft((current) => ({ ...current, [key]: event.target.value }))} />
            </label>)}
            <div className="product-filter-actions">
              <button className="btn primary" type="submit">应用筛选</button>
              <button className="btn ghost" type="button" onClick={() => setFilterDraft({ ...EMPTY_FILTERS })}>清空条件</button>
            </div>
          </fieldset>
        </form>}

        {(query.trim() || activeFilters.length > 0) && <div className="product-active-filters" aria-label="已生效的查询条件">
          {query.trim() && <span title={query}>搜索：{query}</span>}
          {activeFilters.map(([key, label]) => <span key={key} title={filters[key]}>{label}：{filters[key]}</span>)}
          <button className="btn-link" type="button" disabled={loading}
            onClick={() => void applySearch("", { ...EMPTY_FILTERS })}>清除全部</button>
        </div>}

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
            onColumnPinned={saveColumnState}
          />
        </div>

        <div className="kit-pager">
          <span className="kit-pager-range">
            第 {firstRow.toLocaleString("zh-CN")}–{lastRow.toLocaleString("zh-CN")} 条，共 {foundCount.toLocaleString("zh-CN")} 条
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
            <form className="page-jump" onSubmit={submitPageJump} noValidate>
              <span>第</span>
              <input
                aria-label="页码"
                disabled={loading || foundCount === 0}
                title="输入页码后按 Enter 跳转"
                min={1}
                max={totalPages}
                type="number"
                value={pageDraft}
                onChange={(event) => setPageDraft(event.target.value)}
              />
              <span>/ {totalPages.toLocaleString("zh-CN")} 页</span>
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
        <footer className="product-directory-footnote">
          <span>数据来源：{data?.layout || "—"}</span>
          {pageScoped && <span>排序仅作用于当前页</span>}
        </footer>
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

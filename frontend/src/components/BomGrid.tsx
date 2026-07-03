import { Download } from "lucide-react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, GridReadyEvent } from "ag-grid-community";
import { useCallback, useRef, useState } from "react";
import {
  adaptiveGridStyle,
  agGridZhCN,
  defaultAutoSizeStrategy,
  defaultTableColDef,
  gridFloatingFilterHeight,
  gridHeaderHeight,
  gridPageSize,
  paginationPageSizeOptions,
  gridRowHeight
} from "./grid-config";
import type { ProductBomRow } from "../types";

export type BomGridProps = {
  rows: ProductBomRow[];
  columns: ColDef<ProductBomRow>[];
  foundCount: number;
  loading?: boolean;
  stateKey?: string;
};

export default function BomGrid({ rows, columns, foundCount, loading, stateKey }: BomGridProps) {
  const gridRef = useRef<AgGridReact<ProductBomRow>>(null);
  const [visiblePageSize, setVisiblePageSize] = useState(gridPageSize);

  const restoreColumnState = useCallback(() => {
    if (!stateKey || !gridRef.current) return;
    try {
      const raw = localStorage.getItem(`ag-grid-state:${stateKey}`);
      if (raw) {
        gridRef.current.api.applyColumnState({ state: JSON.parse(raw), applyOrder: true });
      }
    } catch {
      // Ignore corrupted state
    }
  }, [stateKey]);

  const saveColumnState = useCallback(() => {
    if (!stateKey || !gridRef.current) return;
    try {
      const state = gridRef.current.api.getColumnState();
      localStorage.setItem(`ag-grid-state:${stateKey}`, JSON.stringify(state));
    } catch {
      // Ignore storage errors
    }
  }, [stateKey]);

  function onGridReady(event: GridReadyEvent<ProductBomRow>) {
    event.api.sizeColumnsToFit();
    setVisiblePageSize(event.api.paginationGetPageSize());
    restoreColumnState();
  }

  function syncPageSize() {
    const nextPageSize = gridRef.current?.api.paginationGetPageSize();
    if (!nextPageSize) return;
    setVisiblePageSize((current) => (current === nextPageSize ? current : nextPageSize));
  }

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({
      fileName: `product-bom-${new Date().toISOString().slice(0, 10)}.csv`
    });
  }

  return (
    <section className="card data-card">
      <div className="card-head">
        <div className="card-head-left">
          <h3>产品 BOM</h3>
          <span className="record-count">{foundCount} 条</span>
        </div>
        <button className="btn ghost" onClick={exportCsv} disabled={rows.length === 0}>
          <Download size={15} />
          导出 CSV
        </button>
      </div>
      <div className="grid full ag-theme-quartz" style={adaptiveGridStyle(rows.length, 4, visiblePageSize)}>
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
          pagination
          paginationPageSize={gridPageSize}
          paginationPageSizeSelector={paginationPageSizeOptions}
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
          onPaginationChanged={syncPageSize}
        />
      </div>
    </section>
  );
}

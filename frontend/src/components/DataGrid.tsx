import { AgGridReact } from "ag-grid-react";
import type { ColDef, ColumnState, GridReadyEvent, RowDoubleClickedEvent } from "ag-grid-community";
import { Columns3, Download } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adaptiveGridStyle,
  agGridZhCN,
  defaultAutoSizeStrategy,
  defaultTableColDef,
  gridFloatingFilterHeight,
  gridHeaderHeight,
  gridRowHeight
} from "./grid-config";

/**
 * Shared AG Grid wrapper for the demand-order and order tables: sortable, per-column
 * floating filters, resizable/reorderable columns, a column-visibility
 * picker ("调整字段") and CSV export. Column layout is persisted per grid
 * under its own localStorage key so every grid keeps its own saved
 * widths/order.
 */
export type DataGridProps<T> = {
  gridKey: string;
  columns: ColDef<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  loading?: boolean;
  csvFileName: string;
  onRowDoubleClicked?: (row: T) => void;
};

export default function DataGrid<T>({ gridKey, columns, rows, getRowId, loading, csvFileName, onRowDoubleClicked }: DataGridProps<T>) {
  const gridRef = useRef<AgGridReact<T>>(null);
  const stateKey = `ag-grid-state:${gridKey}:v1`;
  const menuRef = useRef<HTMLDivElement>(null);
  const [columnMenuOpen, setColumnMenuOpen] = useState(false);
  const [hiddenColumns, setHiddenColumns] = useState<string[]>([]);

  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setColumnMenuOpen(false);
    }
    function escape(event: KeyboardEvent) {
      if (event.key === "Escape") setColumnMenuOpen(false);
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, []);

  const saveColumnState = useCallback(() => {
    const api = gridRef.current?.api;
    if (!api) return;
    try {
      const state = api.getColumnState();
      localStorage.setItem(stateKey, JSON.stringify(state));
      setHiddenColumns(state.filter(column => column.hide).map(column => column.colId));
    } catch {
      // Ignore storage errors; the layout simply will not survive a reload.
    }
  }, [stateKey]);

  function onGridReady(event: GridReadyEvent<T>) {
    try {
      const raw = localStorage.getItem(stateKey);
      if (raw) event.api.applyColumnState({ state: JSON.parse(raw) as ColumnState[], applyOrder: true });
    } catch {
      // Corrupted state falls through to the column defaults.
    }
    event.api.sizeColumnsToFit();
    setHiddenColumns(event.api.getColumnState().filter(column => column.hide).map(column => column.colId));
  }

  function resetLayout() {
    try {
      localStorage.removeItem(stateKey);
    } catch {
      // Ignore storage errors; the in-memory reset below still applies.
    }
    gridRef.current?.api.resetColumnState();
    gridRef.current?.api.sizeColumnsToFit();
    setHiddenColumns([]);
  }

  function toggleColumn(colId: string, visible: boolean) {
    gridRef.current?.api.setColumnsVisible([colId], visible);
    saveColumnState();
  }

  function exportCsv() {
    gridRef.current?.api.exportDataAsCsv({ fileName: `${csvFileName}-${new Date().toISOString().slice(0, 10)}.csv` });
  }

  const toggleableColumns = useMemo(() => columns.filter(column => column.colId), [columns]);

  return (
    <div className="demand-grid-wrap">
      <div className="demand-grid-toolbar">
        <div className="column-menu-wrap" ref={menuRef}>
          <button className="btn ghost" type="button" aria-expanded={columnMenuOpen} aria-controls={`${gridKey}-fields`}
            onClick={() => setColumnMenuOpen(open => !open)}>
            <Columns3 size={15} />调整字段
          </button>
          {columnMenuOpen && (
            <div className="column-menu" id={`${gridKey}-fields`} aria-label="调整字段">
              <div className="column-menu-head"><span>显示的列</span>
                <button type="button" className="btn-link" onClick={resetLayout}>恢复默认</button>
              </div>
              <div className="column-menu-list">
                {toggleableColumns.map(column => (
                  <label key={column.colId} className="column-menu-item">
                    <input type="checkbox" checked={!hiddenColumns.includes(column.colId as string)}
                      onChange={event => toggleColumn(column.colId as string, event.target.checked)} />
                    <span>{column.headerName}</span>
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
        <button className="btn ghost" type="button" disabled={rows.length === 0} onClick={exportCsv}>
          <Download size={15} />导出 CSV
        </button>
      </div>
      <div className="demand-ag-grid ag-theme-quartz" style={adaptiveGridStyle(rows.length, 4, 25)}>
        <AgGridReact
          ref={gridRef}
          theme="legacy"
          rowData={rows}
          columnDefs={columns}
          defaultColDef={defaultTableColDef}
          localeText={agGridZhCN}
          getRowId={({ data }) => getRowId(data)}
          rowHeight={gridRowHeight}
          headerHeight={gridHeaderHeight}
          floatingFiltersHeight={gridFloatingFilterHeight}
          autoSizeStrategy={defaultAutoSizeStrategy}
          loading={loading}
          overlayLoadingTemplate={"<span class=\"ag-overlay-loading-center\">加载中...</span>"}
          overlayNoRowsTemplate={"<span class=\"ag-overlay-no-rows-center\">暂无数据</span>"}
          onGridReady={onGridReady}
          onRowDoubleClicked={onRowDoubleClicked ? (event: RowDoubleClickedEvent<T>) => { if (event.data) onRowDoubleClicked(event.data); } : undefined}
          onColumnResized={({ finished }) => finished && saveColumnState()}
          onColumnMoved={({ finished }) => finished && saveColumnState()}
          onSortChanged={saveColumnState}
          onColumnPinned={saveColumnState}
        />
      </div>
    </div>
  );
}

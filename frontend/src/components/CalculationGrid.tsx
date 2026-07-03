import { Check, Download, Search } from "lucide-react";
import { AgGridReact } from "ag-grid-react";
import type { CellClickedEvent, CellValueChangedEvent, ColDef, GridReadyEvent } from "ag-grid-community";
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
import type { CalculationLine } from "../types";

export type CalculationGridProps = {
  lines: CalculationLine[];
  columns: ColDef<CalculationLine>[];
  issueSearch: string;
  loading?: boolean;
  stateKey?: string;
  onIssueSearchChange: (value: string) => void;
  onCellClicked: (event: CellClickedEvent<CalculationLine>) => void;
  onCellValueChanged: (event: CellValueChangedEvent<CalculationLine>) => void;
  onConfirm: () => void;
  confirmDisabled: boolean;
};

function countStockShortage(lines: CalculationLine[]): number {
  return lines.filter(
    (line) =>
      line.stockSnapshot !== null &&
      line.stockSnapshot !== undefined &&
      line.stockSnapshot < line.calculatedQty
  ).length;
}

export default function CalculationGrid({
  lines,
  columns,
  issueSearch,
  loading,
  stateKey,
  onIssueSearchChange,
  onCellClicked,
  onCellValueChanged,
  onConfirm,
  confirmDisabled
}: CalculationGridProps) {
  const gridRef = useRef<AgGridReact<CalculationLine>>(null);
  const [visiblePageSize, setVisiblePageSize] = useState(gridPageSize);
  const shortageCount = countStockShortage(lines);

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

  function onGridReady(event: GridReadyEvent<CalculationLine>) {
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
      fileName: `bom-calculation-${new Date().toISOString().slice(0, 10)}.csv`
    });
  }

  return (
    <>
      <section className="card data-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>零件包发料分类明细</h3>
            <span className="record-count">{lines.length} 条</span>
            {shortageCount > 0 && <span className="badge danger">库存不足 {shortageCount} 项</span>}
          </div>
          <button className="btn ghost" onClick={exportCsv} disabled={lines.length === 0}>
            <Download size={15} />
            导出 CSV
          </button>
        </div>
        <div className="card-toolbar">
          <label className="grid-search" htmlFor="issueSearch">
            <Search size={15} />
            <input
              id="issueSearch"
              value={issueSearch}
              onChange={(event) => onIssueSearchChange(event.target.value)}
              placeholder="搜索零件编号、名称、仓库、位置"
            />
          </label>
        </div>
        <div className="grid full ag-theme-quartz" style={adaptiveGridStyle(lines.length, 4, visiblePageSize)}>
          <AgGridReact
            ref={gridRef}
            theme="legacy"
            rowData={lines}
            columnDefs={columns}
            defaultColDef={defaultTableColDef}
            localeText={agGridZhCN}
            getRowId={({ data }) => String(data.lineNo)}
            rowHeight={gridRowHeight}
            headerHeight={gridHeaderHeight}
            floatingFiltersHeight={gridFloatingFilterHeight}
            onCellClicked={onCellClicked}
            onCellValueChanged={onCellValueChanged}
            quickFilterText={issueSearch}
            pagination
            paginationPageSize={gridPageSize}
            paginationPageSizeSelector={paginationPageSizeOptions}
            stopEditingWhenCellsLoseFocus
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
        <div className="detail-submit-row">
          <button className="btn primary" onClick={onConfirm} disabled={confirmDisabled}>
            <Check size={16} />
            确认
          </button>
        </div>
      </section>
      <div className="page-footer-spacer" aria-hidden="true" />
    </>
  );
}

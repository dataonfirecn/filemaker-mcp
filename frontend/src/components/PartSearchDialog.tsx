import { Search } from "lucide-react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import {
  adaptiveGridStyle,
  agGridZhCN,
  defaultTableColDef,
  gridFloatingFilterHeight,
  gridHeaderHeight,
  gridRowHeight
} from "./grid-config";
import type { CalculationLine, PartInfo } from "../types";

export type PartSearchDialogProps = {
  line: CalculationLine | null;
  query: string;
  loading: boolean;
  error: string | null;
  results: PartInfo[];
  columns: ColDef<PartInfo>[];
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  onSelect: (part: PartInfo) => void;
  onCancel: () => void;
};

export default function PartSearchDialog({
  line,
  query,
  loading,
  error,
  results,
  columns,
  onQueryChange,
  onSearch,
  onSelect,
  onCancel
}: PartSearchDialogProps) {
  if (!line) return null;

  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal search-modal" role="dialog" aria-modal="true" aria-labelledby="part-search-title">
        <div className="modal-heading">
          <h2 id="part-search-title">零件库搜索</h2>
          <span className="pill">第 {line.lineNo} 行</span>
        </div>
        <div className="search-bar">
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSearch();
            }}
            placeholder="输入零件编号或名称"
            autoFocus
          />
          <button className="btn" onClick={onSearch} disabled={loading}>
            <Search size={16} />
            搜索
          </button>
        </div>
        {error && <div className="alert compact">{error}</div>}
        <div className="search-grid ag-theme-quartz">
          <AgGridReact
            theme="legacy"
            rowData={results}
            columnDefs={columns}
            defaultColDef={defaultTableColDef}
            localeText={agGridZhCN}
            getRowId={({ data }) => data.partNo}
            rowHeight={gridRowHeight}
            headerHeight={gridHeaderHeight}
            floatingFiltersHeight={gridFloatingFilterHeight}
            onRowClicked={({ data }) => {
              if (data) onSelect(data);
            }}
            overlayNoRowsTemplate={loading ? "搜索中..." : "无匹配零件"}
          />
        </div>
        <div className="modal-actions">
          <button className="btn" onClick={onCancel}>
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

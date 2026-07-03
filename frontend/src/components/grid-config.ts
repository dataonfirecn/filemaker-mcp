import type { ColDef } from "ag-grid-community";

export const gridPageSize = 50;
export const paginationPageSizeOptions = [50, 100, 200];
export const gridRowHeight = 38;
export const gridHeaderHeight = 36;
export const gridFloatingFilterHeight = 34;
export const gridPaginationHeight = 38;
export const gridHeightBuffer = 2;

export const textFilterParams = {
  buttons: ["reset", "apply"],
  closeOnApply: true,
  debounceMs: 150,
  trimInput: true
};

export const numberFilterParams = {
  buttons: ["reset", "apply"],
  closeOnApply: true,
  debounceMs: 150
};

export const defaultTableColDef: ColDef = {
  sortable: true,
  filter: "agTextColumnFilter",
  floatingFilter: true,
  resizable: true,
  suppressMovable: false,
  filterParams: textFilterParams
};

export const defaultAutoSizeStrategy = {
  type: "fitGridWidth" as const,
  defaultMinWidth: 80
};

export function adaptiveGridStyle(rowCount: number, minRows = 4, maxRows?: number) {
  const visibleRows = Math.min(Math.max(rowCount, minRows), maxRows ?? gridPageSize);
  const height =
    gridHeaderHeight +
    gridFloatingFilterHeight +
    visibleRows * gridRowHeight +
    gridPaginationHeight +
    gridHeightBuffer;
  return {
    height: `${height}px`,
    minHeight: `${height}px`
  };
}

export const agGridZhCN: Record<string, string> = {
  applyFilter: "应用",
  clearFilter: "清除",
  resetFilter: "重置",
  cancelFilter: "取消",
  textFilter: "文本筛选",
  numberFilter: "数字筛选",
  dateFilter: "日期筛选",
  setFilter: "集合筛选",
  filterOoo: "筛选...",
  empty: "请选择",
  equals: "等于",
  notEqual: "不等于",
  lessThan: "小于",
  greaterThan: "大于",
  inRange: "介于",
  inRangeStart: "从",
  inRangeEnd: "到",
  lessThanOrEqual: "小于等于",
  greaterThanOrEqual: "大于等于",
  contains: "包含",
  notContains: "不包含",
  startsWith: "开头为",
  endsWith: "结尾为",
  blank: "空白",
  notBlank: "非空白",
  before: "之前",
  after: "之后",
  andCondition: "并且",
  orCondition: "或者",
  dateFormatOoo: "yyyy-mm-dd",
  page: "第",
  more: "更多",
  to: "到",
  of: "共",
  nextPage: "下一页",
  lastPage: "末页",
  firstPage: "首页",
  previousPage: "上一页",
  pageSizeSelectorLabel: "每页:",
  ariaPageSizeSelectorLabel: "每页行数",
  loadingOoo: "加载中...",
  noRowsToShow: "暂无数据",
  columns: "列",
  filters: "筛选",
  pinColumn: "固定列",
  pinLeft: "固定在左侧",
  pinRight: "固定在右侧",
  noPin: "不固定",
  valueAggregation: "值汇总",
  autosizeThiscolumn: "自适应当前列",
  autosizeAllColumns: "自适应所有列",
  groupBy: "按此列分组",
  ungroupBy: "取消分组",
  resetColumns: "重置列",
  expandAll: "全部展开",
  collapseAll: "全部收起",
  copy: "复制",
  copyWithHeaders: "复制含表头",
  paste: "粘贴",
  export: "导出",
  csvExport: "导出 CSV",
  excelExport: "导出 Excel",
  ariaFilterMenuOpen: "打开筛选菜单",
  ariaFilterInput: "筛选输入",
  ariaFilterColumn: "按 Ctrl Enter 打开筛选",
  ariaFilterValue: "筛选值",
  ariaFilterFromValue: "筛选起始值",
  ariaFilterToValue: "筛选结束值",
  ariaFilteringOperator: "筛选条件",
  ariaColumnFiltered: "已筛选",
  ariaLabelColumnFilter: "列筛选",
  ariaLabelColumnMenu: "列菜单",
  ariaSortableColumn: "可排序列",
  ariaSortAscending: "升序",
  ariaSortDescending: "降序",
  ariaSortNone: "无排序",
  thousandSeparator: ",",
  decimalSeparator: "."
};

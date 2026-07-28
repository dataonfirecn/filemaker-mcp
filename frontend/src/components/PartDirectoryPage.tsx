import {
  AlertTriangle,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsLeft,
  ChevronsRight,
  CircleDollarSign,
  Eye,
  ImageIcon,
  ListFilter,
  LoaderCircle,
  PackageSearch,
  RotateCcw,
  Search,
  SlidersHorizontal
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";

export type PartDirectoryRow = {
  id: string;
  partId: string;
  partNumber: string;
  nameInternal: string;
  nameExternal: string;
  lifecycleStatus: string;
  materialCategory: string;
  partCategory: string;
  materialSpec: string;
  materialProperties: string;
  stock: number;
  safetyStock: number;
  orderedQuantity: number;
  turnoverDays: number | null;
  unitPriceTwd?: number | null;
  manufacturer: string;
  department: string;
  warehouseDivision: string;
  warehouseCode: string;
  locationPrimary: string;
  locationSecondary: string;
  auditStatus: string;
  status: string;
  updatedAt: string;
  assetCount: number;
  photoCount: number;
  drawingCount: number;
  thumbnailUrl: string;
};

type PartDirectoryResponse = {
  rows: PartDirectoryRow[];
  foundCount: number;
  returnedCount: number;
  totalCount: number | null;
  page: number;
  pageSize: number;
  totalPages: number;
  query: string;
  filters: {
    materialCategory: string;
    partCategory: string;
    lifecycleStatus: string;
    auditStatus: string;
    manufacturer: string;
    department: string;
    warehouseDivision: string;
    warehouseCode: string;
    timeField: PartTimeField;
    dateFrom: string;
    dateTo: string;
  };
  requiresFilter: boolean;
  sourceTables: string[];
};

type OptionItem = {
  value: string;
  label: string;
};

type PartDirectoryOptions = {
  materialCategories: OptionItem[];
  partCategories: OptionItem[];
  lifecycleStatuses: OptionItem[];
  departmentDivisions: OptionItem[];
  warehouseDivisions: OptionItem[];
  warehouseCodes: OptionItem[];
  auditStatuses: OptionItem[];
};

type PartTimeField = "created" | "updated" | "drawing";
type PartTimePreset = "" | "today" | "7d" | "30d" | "90d" | "month" | "custom";

type PartDirectoryFilters = {
  query: string;
  materialCategory: string;
  partCategory: string;
  lifecycleStatus: string;
  auditStatus: string;
  manufacturer: string;
  department: string;
  warehouseDivision: string;
  warehouseCode: string;
  timeField: PartTimeField;
  timePreset: PartTimePreset;
  dateFrom: string;
  dateTo: string;
};

const EMPTY_FILTERS: PartDirectoryFilters = {
  query: "",
  materialCategory: "",
  partCategory: "",
  lifecycleStatus: "",
  auditStatus: "",
  manufacturer: "",
  department: "",
  warehouseDivision: "",
  warehouseCode: "",
  timeField: "updated",
  timePreset: "",
  dateFrom: "",
  dateTo: ""
};

const FILTER_URL_KEYS: Record<keyof PartDirectoryFilters, string> = {
  query: "partQuery",
  materialCategory: "partMaterial",
  partCategory: "partCategory",
  lifecycleStatus: "partLifecycle",
  auditStatus: "partAudit",
  manufacturer: "partManufacturer",
  department: "partDepartment",
  warehouseDivision: "partWarehouseDivision",
  warehouseCode: "partWarehouse",
  timeField: "partTimeField",
  timePreset: "partTimePreset",
  dateFrom: "partDateFrom",
  dateTo: "partDateTo"
};

type PartDirectoryPageProps = {
  apiBase?: string;
  token: string;
  onOpenPart: (part: PartDirectoryRow) => void;
};

function pageNumbers(current: number, total: number): number[] {
  if (total <= 5) return Array.from({ length: total }, (_, index) => index + 1);
  const start = Math.min(Math.max(1, current - 2), total - 4);
  return Array.from({ length: 5 }, (_, index) => start + index);
}

function responseError(body: string): string {
  try {
    const payload = JSON.parse(body) as { detail?: string | { message?: string } };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Fall through to the raw body.
  }
  return body || "零件资料读取失败";
}

function display(value: string): string {
  return value.trim() || "—";
}

function readFiltersFromUrl(): PartDirectoryFilters {
  const params = new URLSearchParams(window.location.search);
  const timeField = params.get(FILTER_URL_KEYS.timeField);
  const timePreset = params.get(FILTER_URL_KEYS.timePreset);
  return {
    query: params.get(FILTER_URL_KEYS.query) ?? "",
    materialCategory: params.get(FILTER_URL_KEYS.materialCategory) ?? "",
    partCategory: params.get(FILTER_URL_KEYS.partCategory) ?? "",
    lifecycleStatus: params.get(FILTER_URL_KEYS.lifecycleStatus) ?? "",
    auditStatus: params.get(FILTER_URL_KEYS.auditStatus) ?? "",
    manufacturer: params.get(FILTER_URL_KEYS.manufacturer) ?? "",
    department: params.get(FILTER_URL_KEYS.department) ?? "",
    warehouseDivision: params.get(FILTER_URL_KEYS.warehouseDivision) ?? "",
    warehouseCode: params.get(FILTER_URL_KEYS.warehouseCode) ?? "",
    timeField:
      timeField === "created" || timeField === "drawing" ? timeField : "updated",
    timePreset:
      timePreset === "today" ||
      timePreset === "7d" ||
      timePreset === "30d" ||
      timePreset === "90d" ||
      timePreset === "month" ||
      timePreset === "custom"
        ? timePreset
        : "",
    dateFrom: params.get(FILTER_URL_KEYS.dateFrom) ?? "",
    dateTo: params.get(FILTER_URL_KEYS.dateTo) ?? ""
  };
}

function writeFiltersToUrl(filters: PartDirectoryFilters | null) {
  const url = new URL(window.location.href);
  Object.values(FILTER_URL_KEYS).forEach((key) => url.searchParams.delete(key));
  if (filters) {
    (Object.keys(FILTER_URL_KEYS) as Array<keyof PartDirectoryFilters>).forEach((key) => {
      const value = filters[key];
      if (value && !(key === "timeField" && !filters.dateFrom && !filters.dateTo)) {
        url.searchParams.set(FILTER_URL_KEYS[key], value);
      }
    });
  }
  window.history.replaceState({}, "", url);
}

function hasEffectiveFilter(filters: PartDirectoryFilters): boolean {
  return Boolean(
    filters.query.trim() ||
      filters.materialCategory ||
      filters.partCategory ||
      filters.lifecycleStatus ||
      filters.auditStatus ||
      filters.manufacturer.trim() ||
      filters.department ||
      filters.warehouseDivision ||
      filters.warehouseCode ||
      filters.dateFrom ||
      filters.dateTo
  );
}

function activeFilterCount(filters: PartDirectoryFilters | null): number {
  if (!filters) return 0;
  return [
    filters.query.trim(),
    filters.materialCategory,
    filters.partCategory,
    filters.lifecycleStatus,
    filters.auditStatus,
    filters.manufacturer.trim(),
    filters.department,
    filters.warehouseDivision,
    filters.warehouseCode,
    filters.dateFrom || filters.dateTo
  ].filter(Boolean).length;
}

function localDateValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function dateRangeForPreset(
  preset: Exclude<PartTimePreset, "" | "custom">
): Pick<PartDirectoryFilters, "dateFrom" | "dateTo"> {
  const today = new Date();
  const start = new Date(today);
  if (preset === "7d") start.setDate(today.getDate() - 6);
  if (preset === "30d") start.setDate(today.getDate() - 29);
  if (preset === "90d") start.setDate(today.getDate() - 89);
  if (preset === "month") start.setDate(1);
  return {
    dateFrom: localDateValue(start),
    dateTo: localDateValue(today)
  };
}

function statusTone(value: string): "success" | "pending" | "muted" {
  if (/可量产|正常|confirm|已审核|已審核/i.test(value)) return "success";
  if (/停用|作废|未完成|取消/i.test(value)) return "muted";
  return "pending";
}

function PartThumbnail({ part }: { part: PartDirectoryRow }) {
  if (part.thumbnailUrl) {
    return (
      <span className="part-directory-thumb">
        <img src={part.thumbnailUrl} alt="" loading="lazy" />
      </span>
    );
  }
  return (
    <span className="part-directory-thumb" aria-hidden="true">
      <svg viewBox="0 0 96 72">
        <rect width="96" height="72" rx="10" fill="#eef3f4" />
        <path d="M0 18h96M0 36h96M0 54h96M24 0v72M48 0v72M72 0v72" stroke="#7f919c" strokeOpacity=".16" />
        <g transform="translate(11 12)">
          <path
            d="M21 8h34c6 0 10 5 10 10v6h7c5 0 9 4 9 9v10c0 5-4 9-9 9H55v6H21v-6H4c-5 0-9-4-9-9V33c0-5 4-9 9-9h7v-6c0-5 4-10 10-10Z"
            fill="#29343d"
            stroke="#12191f"
            strokeWidth="2"
          />
          <circle cx="11" cy="38" r="8" fill="#10171d" stroke="#5f6c75" strokeWidth="3" />
          <circle cx="65" cy="38" r="8" fill="#10171d" stroke="#5f6c75" strokeWidth="3" />
          <rect x="25" y="32" width="26" height="11" rx="5" fill="#14b8a6" />
        </g>
      </svg>
    </span>
  );
}

export default function PartDirectoryPage({
  apiBase = "",
  token,
  onOpenPart
}: PartDirectoryPageProps) {
  const initialFilters = useMemo(readFiltersFromUrl, []);
  const [data, setData] = useState<PartDirectoryResponse | null>(null);
  const [options, setOptions] = useState<PartDirectoryOptions>({
    materialCategories: [],
    partCategories: [],
    lifecycleStatuses: [],
    departmentDivisions: [],
    warehouseDivisions: [],
    warehouseCodes: [],
    auditStatuses: []
  });
  const [draftFilters, setDraftFilters] = useState<PartDirectoryFilters>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<PartDirectoryFilters | null>(
    hasEffectiveFilter(initialFilters) ? initialFilters : null
  );
  const [advancedOpen, setAdvancedOpen] = useState(
    Boolean(
      initialFilters.auditStatus ||
        initialFilters.manufacturer ||
        initialFilters.department ||
        initialFilters.warehouseDivision ||
        initialFilters.warehouseCode ||
        initialFilters.dateFrom ||
        initialFilters.dateTo
    )
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    void fetch(`${apiBase}/api/part-directory/options`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(responseError(await response.text()));
        return response.json() as Promise<PartDirectoryOptions>;
      })
      .then(setOptions)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        // The list remains usable if FileMaker value-list metadata is unavailable.
      });
    return () => controller.abort();
  }, [apiBase, token]);

  useEffect(() => {
    if (!token || !appliedFilters) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      page: String(page),
      pageSize: String(pageSize)
    });
    const filters = appliedFilters;
    if (filters.query) params.set("q", filters.query);
    if (filters.materialCategory) params.set("materialCategory", filters.materialCategory);
    if (filters.partCategory) params.set("partCategory", filters.partCategory);
    if (filters.lifecycleStatus) params.set("lifecycleStatus", filters.lifecycleStatus);
    if (filters.auditStatus) params.set("auditStatus", filters.auditStatus);
    if (filters.manufacturer) params.set("manufacturer", filters.manufacturer);
    if (filters.department) params.set("department", filters.department);
    if (filters.warehouseDivision) {
      params.set("warehouseDivision", filters.warehouseDivision);
    }
    if (filters.warehouseCode) params.set("warehouseCode", filters.warehouseCode);
    if (filters.dateFrom || filters.dateTo) params.set("timeField", filters.timeField);
    if (filters.dateFrom) params.set("dateFrom", filters.dateFrom);
    if (filters.dateTo) params.set("dateTo", filters.dateTo);
    setLoading(true);
    setError(null);
    void fetch(`${apiBase}/api/part-directory?${params.toString()}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(responseError(await response.text()));
        return response.json() as Promise<PartDirectoryResponse>;
      })
      .then((nextData) => {
        setData(nextData);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "零件资料读取失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [
    apiBase,
    appliedFilters,
    page,
    pageSize,
    token
  ]);

  const rows = data?.rows ?? [];
  const totalPages = data?.totalPages ?? 1;
  const safePage = Math.min(page, totalPages);
  const firstRow = data?.foundCount ? (safePage - 1) * pageSize + 1 : 0;
  const lastRow = data?.foundCount ? firstRow + rows.length - 1 : 0;
  const lowStockPageCount = rows.filter(
    (part) => part.safetyStock > 0 && part.stock < part.safetyStock
  ).length;
  const assetPageCount = rows.filter((part) => part.assetCount > 0).length;
  const materialCategoryOptions = useMemo(
    () => mergeOptions(options.materialCategories, rows.map((row) => row.materialCategory)),
    [options.materialCategories, rows]
  );
  const partCategoryOptions = useMemo(
    () => mergeOptions(options.partCategories, rows.map((row) => row.partCategory)),
    [options.partCategories, rows]
  );
  const lifecycleOptions = useMemo(
    () => mergeOptions(options.lifecycleStatuses, rows.map((row) => row.lifecycleStatus)),
    [options.lifecycleStatuses, rows]
  );
  const auditOptions = useMemo(
    () => mergeOptions(options.auditStatuses, rows.map((row) => row.auditStatus)),
    [options.auditStatuses, rows]
  );
  const departmentOptions = useMemo(
    () => mergeOptions(options.departmentDivisions, rows.map((row) => row.department)),
    [options.departmentDivisions, rows]
  );
  const warehouseDivisionOptions = useMemo(
    () => mergeOptions(options.warehouseDivisions, rows.map((row) => row.warehouseDivision)),
    [options.warehouseDivisions, rows]
  );
  const invalidDateRange = Boolean(
    draftFilters.dateFrom &&
      draftFilters.dateTo &&
      draftFilters.dateTo < draftFilters.dateFrom
  );
  const canSearch = hasEffectiveFilter(draftFilters) && !invalidDateRange;
  const searched = appliedFilters !== null;
  const filterCount = activeFilterCount(appliedFilters);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSearch || loading) return;
    const nextFilters = {
      ...draftFilters,
      query: draftFilters.query.trim(),
      manufacturer: draftFilters.manufacturer.trim()
    };
    setPage(1);
    setData(null);
    setAppliedFilters(nextFilters);
    writeFiltersToUrl(nextFilters);
  }

  function resetFilters() {
    setDraftFilters(EMPTY_FILTERS);
    setAppliedFilters(null);
    setData(null);
    setError(null);
    setPage(1);
    writeFiltersToUrl(null);
  }

  function updateFilter<K extends keyof PartDirectoryFilters>(
    key: K,
    value: PartDirectoryFilters[K]
  ) {
    setDraftFilters((current) => ({ ...current, [key]: value }));
  }

  function updateTimePreset(preset: PartTimePreset) {
    if (!preset) {
      setDraftFilters((current) => ({
        ...current,
        timePreset: "",
        dateFrom: "",
        dateTo: ""
      }));
      return;
    }
    if (preset === "custom") {
      setDraftFilters((current) => ({ ...current, timePreset: "custom" }));
      return;
    }
    const range = dateRangeForPreset(preset);
    setDraftFilters((current) => ({
      ...current,
      timePreset: preset,
      ...range
    }));
  }

  return (
    <div className="part-directory-page">
      <section className="part-directory-summary" aria-label="零件资料摘要">
        <div>
          <span className="part-directory-summary-icon teal"><ListFilter size={18} /></span>
          <span><small>查询状态</small><strong>{searched ? "已查询" : "待查询"}</strong></span>
        </div>
        <div>
          <span className="part-directory-summary-icon blue"><PackageSearch size={18} /></span>
          <span><small>当前结果</small><strong>{data?.foundCount.toLocaleString("zh-CN") ?? "—"}</strong></span>
        </div>
        <div>
          <span className="part-directory-summary-icon amber"><AlertTriangle size={18} /></span>
          <span><small>本页低于安全库存</small><strong>{lowStockPageCount}</strong></span>
        </div>
        <div>
          <span className="part-directory-summary-icon purple"><ImageIcon size={18} /></span>
          <span><small>本页存在 COS 资料</small><strong>{assetPageCount}</strong></span>
        </div>
      </section>

      <section className="part-directory-panel">
        <header className="part-directory-heading">
          <div>
            <span><SlidersHorizontal size={15} />FileMaker OData 实时资料</span>
            <h2>零件资料列表</h2>
            <p>先设置条件再查询；页面打开时不会读取四万多条零件记录。</p>
          </div>
          <span className="part-directory-count">
            {loading ? (
              <><LoaderCircle className="spin" size={13} />读取中</>
            ) : data ? (
              `${firstRow}-${lastRow} / ${data.foundCount.toLocaleString("zh-CN")} 条`
            ) : (
              "等待查询"
            )}
          </span>
        </header>

        <form className="part-directory-filter-shell" onSubmit={submitSearch}>
          <div className="part-directory-filter-primary">
            <label className="part-directory-filter-field part-directory-query-field">
              <span>关键词</span>
              <span className="part-directory-search">
                <Search size={16} />
                <input
                  id="part-directory-query"
                  value={draftFilters.query}
                  onChange={(event) => updateFilter("query", event.target.value)}
                  placeholder="零件编号、系统 ID 或名称"
                />
              </span>
            </label>
            <label className="part-directory-filter-field">
              <span>零件性质</span>
              <select
                value={draftFilters.materialCategory}
                onChange={(event) => updateFilter("materialCategory", event.target.value)}
                aria-label="零件性质"
              >
                <option value="">全部性质</option>
                {materialCategoryOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="part-directory-filter-field">
              <span>零件品种</span>
              <select
                value={draftFilters.partCategory}
                onChange={(event) => updateFilter("partCategory", event.target.value)}
                aria-label="零件品种"
              >
                <option value="">全部品种</option>
                {partCategoryOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <label className="part-directory-filter-field">
              <span>生命周期</span>
              <select
                value={draftFilters.lifecycleStatus}
                onChange={(event) => updateFilter("lifecycleStatus", event.target.value)}
                aria-label="生命周期"
              >
                <option value="">全部状态</option>
                {lifecycleOptions.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <div className="part-directory-filter-actions">
              <button
                className="part-directory-button primary"
                type="submit"
                disabled={loading || !canSearch}
              >
                {loading ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}
                查询
              </button>
              <button
                className="part-directory-button"
                type="button"
                onClick={resetFilters}
                disabled={loading}
              >
                <RotateCcw size={15} />重置
              </button>
            </div>
          </div>

          <div className="part-directory-filter-secondary">
            <label className="part-directory-filter-field">
              <span>时间字段</span>
              <select
                value={draftFilters.timeField}
                onChange={(event) => updateFilter("timeField", event.target.value as PartTimeField)}
                aria-label="时间字段"
              >
                <option value="updated">最后修改</option>
                <option value="created">创建时间</option>
                <option value="drawing">图面修改</option>
              </select>
            </label>
            <label className="part-directory-filter-field">
              <span>快捷范围</span>
              <select
                value={draftFilters.timePreset}
                onChange={(event) => updateTimePreset(event.target.value as PartTimePreset)}
                aria-label="快捷时间范围"
              >
                <option value="">不限时间</option>
                <option value="today">今天</option>
                <option value="7d">最近 7 天</option>
                <option value="30d">最近 30 天</option>
                <option value="90d">最近 90 天</option>
                <option value="month">本月</option>
                <option value="custom">自定义</option>
              </select>
            </label>
            <label className="part-directory-filter-field">
              <span>开始日期</span>
              <input
                type="date"
                value={draftFilters.dateFrom}
                onChange={(event) =>
                  setDraftFilters((current) => ({
                    ...current,
                    timePreset: "custom",
                    dateFrom: event.target.value
                  }))
                }
                aria-label="开始日期"
              />
            </label>
            <label className="part-directory-filter-field">
              <span>结束日期</span>
              <input
                type="date"
                value={draftFilters.dateTo}
                onChange={(event) =>
                  setDraftFilters((current) => ({
                    ...current,
                    timePreset: "custom",
                    dateTo: event.target.value
                  }))
                }
                aria-label="结束日期"
              />
            </label>
            <button
              className="part-directory-advanced-toggle"
              type="button"
              onClick={() => setAdvancedOpen((current) => !current)}
              aria-expanded={advancedOpen}
            >
              <ListFilter size={14} />
              更多筛选
              {advancedOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>

          {advancedOpen && (
            <div className="part-directory-filter-advanced">
              <label className="part-directory-filter-field">
                <span>制造商</span>
                <input
                  value={draftFilters.manufacturer}
                  onChange={(event) => updateFilter("manufacturer", event.target.value)}
                  placeholder="输入制造商名称"
                  aria-label="制造商"
                />
              </label>
              <label className="part-directory-filter-field">
                <span>部门分工</span>
                <select
                  value={draftFilters.department}
                  onChange={(event) => updateFilter("department", event.target.value)}
                  aria-label="部门分工"
                >
                  <option value="">全部部门</option>
                  {departmentOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="part-directory-filter-field">
                <span>仓库分工</span>
                <select
                  value={draftFilters.warehouseDivision}
                  onChange={(event) => updateFilter("warehouseDivision", event.target.value)}
                  aria-label="仓库分工"
                >
                  <option value="">全部分工</option>
                  {warehouseDivisionOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="part-directory-filter-field">
                <span>仓库</span>
                <select
                  value={draftFilters.warehouseCode}
                  onChange={(event) => updateFilter("warehouseCode", event.target.value)}
                  aria-label="仓库"
                >
                  <option value="">全部仓库</option>
                  {options.warehouseCodes.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label className="part-directory-filter-field">
                <span>审核状态</span>
                <select
                  value={draftFilters.auditStatus}
                  onChange={(event) => updateFilter("auditStatus", event.target.value)}
                  aria-label="审核状态"
                >
                  <option value="">全部审核状态</option>
                  {auditOptions.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
            </div>
          )}

          <div className="part-directory-filter-hint">
            <CalendarDays size={14} />
            {invalidDateRange
              ? "结束日期不能早于开始日期。"
              : canSearch
              ? `已设置 ${activeFilterCount(draftFilters)} 个条件，点击“查询”后才读取 FileMaker。`
              : "请至少输入关键词、选择一个分类/状态，或设置时间范围。"}
          </div>
        </form>

        {error && <div className="part-directory-error">{error}</div>}

        <div className="part-directory-table-wrap">
          <table className="part-directory-table">
            <thead>
              <tr>
                <th>零件</th>
                <th>品种 / 材料</th>
                <th>库存</th>
                <th>采购信息</th>
                <th>最新单价</th>
                <th>资料</th>
                <th>状态</th>
                <th><span className="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((part) => {
                const lowStock = part.safetyStock > 0 && part.stock < part.safetyStock;
                const hasUnitPrice = typeof part.unitPriceTwd === "number";
                const partLabel = part.partNumber || part.partId;
                return (
                  <tr key={part.id}>
                    <td>
                      <div className="part-directory-identity">
                        <PartThumbnail part={part} />
                        <span>
                          <button type="button" onClick={() => onOpenPart(part)}>{partLabel}</button>
                          <strong>{display(part.nameInternal)}</strong>
                          <small>{display(part.nameExternal)}</small>
                        </span>
                      </div>
                    </td>
                    <td>
                      <span className="part-directory-stack">
                        <strong>{display(part.partCategory)}</strong>
                        <small>{[part.materialCategory, part.materialSpec].filter(Boolean).join(" · ") || "—"}</small>
                      </span>
                    </td>
                    <td>
                      <span className="part-directory-stock">
                        <strong className={lowStock ? "low" : ""}>{part.stock.toLocaleString("zh-CN")}</strong>
                        <small>安全 {part.safetyStock.toLocaleString("zh-CN")}</small>
                        {part.orderedQuantity > 0 && <em>已下单 {part.orderedQuantity.toLocaleString("zh-CN")}</em>}
                      </span>
                    </td>
                    <td>
                      <span className="part-directory-stack">
                        <strong>{display(part.manufacturer)}</strong>
                        <small>{[part.department, part.warehouseDivision].filter(Boolean).join(" · ") || "—"}</small>
                      </span>
                    </td>
                    <td>
                      <span className="part-directory-price">
                        <CircleDollarSign size={14} />
                        <strong>{hasUnitPrice ? `¥${part.unitPriceTwd!.toFixed(2)}` : "—"}</strong>
                        {hasUnitPrice && <small>TWD</small>}
                      </span>
                    </td>
                    <td>
                      <span className="part-directory-files">
                        <span><ImageIcon size={13} />照片 {part.photoCount}</span>
                        <span>图面 {part.drawingCount}</span>
                      </span>
                    </td>
                    <td>
                      <span className={`part-directory-status ${statusTone(part.lifecycleStatus)}`}>
                        {display(part.lifecycleStatus)}
                      </span>
                      <small className="part-directory-audit">{display(part.auditStatus)}</small>
                    </td>
                    <td>
                      <button
                        className="part-directory-open"
                        type="button"
                        onClick={() => onOpenPart(part)}
                        aria-label={`查看 ${partLabel} 详情`}
                      >
                        <Eye size={15} />查看详情
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!loading && !searched && (
                <tr>
                  <td colSpan={8}>
                    <div className="part-directory-empty part-directory-empty-ready">
                      <ListFilter size={30} />
                      <strong>设置条件后查询零件</strong>
                      <span>首屏不会自动读取零件数据。可按编号、分类、状态、制造商或时间范围组合查询。</span>
                    </div>
                  </td>
                </tr>
              )}
              {!loading && searched && data && rows.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="part-directory-empty">
                      <PackageSearch size={28} />
                      <strong>没有符合条件的零件</strong>
                      <span>调整搜索关键词或筛选条件后再试。</span>
                    </div>
                  </td>
                </tr>
              )}
              {loading && rows.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="part-directory-empty">
                      <LoaderCircle className="spin" size={28} />
                      <strong>正在读取 FileMaker</strong>
                      <span>只请求当前页的核心字段和 COS 主图。</span>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {data && (
          <footer className="part-directory-pagination">
            <label>
              每页
              <select
                value={pageSize}
                onChange={(event) => {
                  setPageSize(Number(event.target.value));
                  setPage(1);
                }}
                aria-label="每页显示数量"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
              条
            </label>
            <span>{firstRow}-{lastRow} / {data.foundCount.toLocaleString("zh-CN")}</span>
            <span className="part-directory-pagination-filters">{filterCount} 个筛选条件</span>
            <div>
              <button type="button" aria-label="首页" onClick={() => setPage(1)} disabled={safePage <= 1 || loading}><ChevronsLeft size={16} /></button>
              <button type="button" aria-label="上一页" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={safePage <= 1 || loading}><ChevronLeft size={16} /></button>
              {pageNumbers(safePage, totalPages).map((pageNumber) => (
                <button
                  key={pageNumber}
                  type="button"
                  className={safePage === pageNumber ? "active" : ""}
                  aria-label={`第 ${pageNumber} 页`}
                  aria-current={safePage === pageNumber ? "page" : undefined}
                  onClick={() => setPage(pageNumber)}
                  disabled={loading}
                >
                  {pageNumber}
                </button>
              ))}
              <button type="button" aria-label="下一页" onClick={() => setPage((current) => Math.min(totalPages, current + 1))} disabled={safePage >= totalPages || loading}><ChevronRight size={16} /></button>
              <button type="button" aria-label="末页" onClick={() => setPage(totalPages)} disabled={safePage >= totalPages || loading}><ChevronsRight size={16} /></button>
            </div>
          </footer>
        )}
      </section>
    </div>
  );
}

function mergeOptions(configured: OptionItem[], rowValues: string[]): OptionItem[] {
  const items = new Map<string, OptionItem>();
  configured.forEach((item) => {
    if (item.value) items.set(item.value, item);
  });
  rowValues.forEach((value) => {
    if (value && !items.has(value)) items.set(value, { value, label: value });
  });
  return Array.from(items.values()).sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
}

import { useEffect, useMemo, useRef, useState } from "react";
import type { CellClickedEvent, CellValueChangedEvent, ColDef, ICellRendererParams } from "ag-grid-community";
import { ClipboardList, Database, PackageSearch, Play } from "lucide-react";
import AppShell from "./components/AppShell";
import SidebarNav, { type SidebarNavGroup } from "./components/SidebarNav";
import StepIndicator from "./components/StepIndicator";
import ProductInfoCard from "./components/ProductInfoCard";
import DocumentHeaderCard from "./components/DocumentHeaderCard";
import BomGrid from "./components/BomGrid";
import CalculationGrid from "./components/CalculationGrid";
import KitIssueRecordsPage from "./components/KitIssueRecordsPage";
import HomePage from "./components/HomePage";
import GenerateDialog from "./components/GenerateDialog";
import PartSearchDialog from "./components/PartSearchDialog";
import LoadingOverlay from "./components/LoadingOverlay";
import ConfirmDialog from "./components/ConfirmDialog";
import SuccessAlert from "./components/SuccessAlert";
import { numberFilterParams } from "./components/grid-config";
import { parseError } from "./utils/error";
import type {
  CalculationLine,
  CalculationPreview,
  ConfirmedDocument,
  KitIssueRecordsResponse,
  KitIssueRow,
  Page,
  PartInfo,
  ProductBomRow,
  ProductBomResponse,
  SessionResponse
} from "./types";

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

const pageMeta: Record<Page, { title: string; subtitle: string }> = {
  home: {
    title: "Star-RC",
    subtitle: "企业运营导航中心"
  },
  product: {
    title: "产品 BOM",
    subtitle: "读取 FileMaker 产品 BOM，生成后进入待确认计算单。"
  },
  issue: {
    title: "BOM 计算单",
    subtitle: "以计算单 ID 为主键，确认后写入本地 PostgreSQL。"
  },
  kitIssue: {
    title: "零件包发料",
    subtitle: "读取 FileMaker 零件包发料分类明细，按订单号筛选。"
  }
};

async function fetchJson<T>(path: string, token?: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

function queryValue(params: URLSearchParams, key: string, fallback: string): string {
  const value = params.get(key);
  return value && value.trim() ? value.trim() : fallback;
}

function formatQty(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return Number.isInteger(num) ? String(num) : num.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export default function App() {
  const didInit = useRef(false);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [productBom, setProductBom] = useState<ProductBomResponse | null>(null);
  const [page, setPage] = useState<Page>("home");
  const [preview, setPreview] = useState<CalculationPreview | null>(null);
  const [calcLines, setCalcLines] = useState<CalculationLine[]>([]);
  const [document, setDocument] = useState<ConfirmedDocument | null>(null);
  const [generateDialogOpen, setGenerateDialogOpen] = useState(false);
  const [generateQty, setGenerateQty] = useState("100");
  const [partSearchLine, setPartSearchLine] = useState<CalculationLine | null>(null);
  const [partSearchQuery, setPartSearchQuery] = useState("");
  const [partSearchResults, setPartSearchResults] = useState<PartInfo[]>([]);
  const [partSearchLoading, setPartSearchLoading] = useState(false);
  const [partSearchError, setPartSearchError] = useState<string | null>(null);
  const [issueSearch, setIssueSearch] = useState("");
  const [kitIssueData, setKitIssueData] = useState<KitIssueRecordsResponse | null>(null);
  const [kitIssueOrderNo, setKitIssueOrderNo] = useState("");
  const [kitIssueLoading, setKitIssueLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const calcStatus = useMemo<"未计算" | "待确认" | "已确认">(() => {
    if (document) return "已确认";
    if (preview) return "待确认";
    return "未计算";
  }, [document, preview]);

  const currentStep = useMemo<1 | 2 | 3>(() => {
    if (document) return 3;
    if (preview) return 2;
    return 1;
  }, [document, preview]);

  async function startSession() {
    const params = new URLSearchParams(window.location.search);
    const productSku = queryValue(params, "productSku", "STRX-202");
    const orderNo = queryValue(params, "orderNo", "");
    const orderId = queryValue(params, "orderId", orderNo);
    const operatorAccount = queryValue(params, "operatorAccount", "mock.operator");
    const operatorName = queryValue(params, "operatorName", "本地测试操作员");
    const initialPage: Page = params.get("page") === "kitIssue" ? "kitIssue" : "home";
    const ctx = params.get("ctx");
    const sig = params.get("sig");

    setKitIssueOrderNo(orderId);
    setPage(initialPage);
    const nextSession = await postJson<SessionResponse>("/api/webviewer/session", {
      ctx,
      sig,
      mock: !(ctx && sig),
      productSku,
      orderId,
      operator: {
        account: operatorAccount,
        name: operatorName,
        privilege: "mock"
      }
    });
    setSession(nextSession);
    await loadProduct(nextSession);
  }

  async function loadProduct(activeSession = session) {
    if (!activeSession) return;
    setLoading(true);
    setError(null);
    try {
      const productSku = activeSession.context.productSku || "STRX-202";
      const data = await fetchJson<ProductBomResponse>(
        `/api/products/${encodeURIComponent(productSku)}/bom-view`,
        activeSession.token
      );
      setProductBom(data);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
  }

  async function loadKitIssueRecords(
    nextPage = kitIssueData?.page ?? 1,
    orderNo = kitIssueOrderNo,
    activeSession = session
  ) {
    if (!activeSession) return;
    setKitIssueLoading(true);
    setError(null);
    try {
      const pageNumber = Math.max(1, Math.trunc(nextPage));
      const params = new URLSearchParams({ page: String(pageNumber) });
      const normalizedOrderNo = orderNo.trim();
      if (normalizedOrderNo) params.set("orderNo", normalizedOrderNo);
      const data = await fetchJson<KitIssueRecordsResponse>(
        `/api/kit-issue-records?${params.toString()}`,
        activeSession.token
      );
      setKitIssueData(data);
      setKitIssueOrderNo(data.orderNo);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setKitIssueLoading(false);
    }
  }

  async function previewCalculation() {
    if (!session) return;
    const qty = Number(generateQty);
    if (!Number.isFinite(qty) || qty <= 0) {
      setError("生成数量必须大于 0。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await postJson<CalculationPreview>(
        "/api/bom-calculations/preview",
        {
          productSku: session.context.productSku,
          generateQty: qty
        },
        session.token
      );
      setPreview(data);
      setCalcLines(data.lines);
      setDocument(null);
      setPage("issue");
      setGenerateDialogOpen(false);
      setSuccess(null);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
  }

  async function confirmDocument() {
    if (!session || !preview || !preview.product) return;
    setLoading(true);
    setError(null);
    try {
      const data = await postJson<ConfirmedDocument>(
        "/api/bom-documents/confirm",
        {
          calculationId: preview.calculationId,
          product: preview.product,
          generateQty: preview.generateQty,
          lines: calcLines
        },
        session.token
      );
      setDocument(data);
      setCalcLines(data.lines);
      setSuccess(`计算单 ${data.documentNo} 已确认并写入本地数据库。`);
      setConfirmOpen(false);
    } catch (err) {
      setError(parseError(err));
      setConfirmOpen(false);
    } finally {
      setLoading(false);
    }
  }

  async function hydratePart(lineNo: number, partNo: string) {
    if (!session || !partNo.trim()) return;
    try {
      const part = await fetchJson<PartInfo>(`/api/parts/${encodeURIComponent(partNo.trim())}`, session.token);
      setCalcLines((current) =>
        current.map((line) =>
          line.lineNo === lineNo
            ? {
                ...line,
                partNo: part.partNo || partNo,
                partName: part.partName || line.partName,
                stockSnapshot: part.stockSnapshot,
                warehouse: part.warehouse || line.warehouse,
                position1: part.position1 || line.position1,
                position2: part.position2 || line.position2
              }
            : line
        )
      );
    } catch {
      // Part lookup is a convenience. Keep the user-entered part number if lookup fails.
    }
  }

  function handleLineChange(event: CellValueChangedEvent<CalculationLine>) {
    const data = event.data;
    if (!data) return;
    setCalcLines((current) =>
      current.map((line) =>
        line.lineNo === data.lineNo
          ? {
              ...line,
              partNo: data.partNo,
              calculatedQty: Number(data.calculatedQty) || 0
            }
          : line
      )
    );
    if (event.colDef.field === "partNo") {
      void hydratePart(data.lineNo, data.partNo);
    }
  }

  function handleLineClick(event: CellClickedEvent<CalculationLine>) {
    if (calcStatus !== "待确认") return;
    if (event.colDef.field !== "partNo" || !event.data) return;
    openPartSearch(event.data);
  }

  function openPartSearch(line: CalculationLine) {
    setPartSearchLine(line);
    setPartSearchQuery(line.partNo);
    setPartSearchResults([]);
    setPartSearchError(null);
  }

  function closePartSearch() {
    setPartSearchLine(null);
    setPartSearchQuery("");
    setPartSearchResults([]);
    setPartSearchError(null);
    setPartSearchLoading(false);
  }

  async function searchParts(query = partSearchQuery) {
    if (!session) return;
    setPartSearchLoading(true);
    setPartSearchError(null);
    try {
      const params = new URLSearchParams({
        q: query.trim(),
        limit: "50"
      });
      const data = await fetchJson<{ rows: PartInfo[]; foundCount: number; returnedCount: number }>(
        `/api/parts/search?${params.toString()}`,
        session.token
      );
      setPartSearchResults(data.rows);
    } catch (err) {
      setPartSearchError(parseError(err));
    } finally {
      setPartSearchLoading(false);
    }
  }

  function selectPart(part: PartInfo) {
    if (!partSearchLine) return;
    setCalcLines((current) =>
      current.map((line) =>
        line.lineNo === partSearchLine.lineNo
          ? {
              ...line,
              partNo: part.partNo,
              partName: part.partName,
              stockSnapshot: part.stockSnapshot,
              warehouse: part.warehouse,
              position1: part.position1,
              position2: part.position2
            }
          : line
      )
    );
    closePartSearch();
  }

  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    void startSession().catch((err) => {
      setError(parseError(err));
    });
  }, []);

  useEffect(() => {
    if (!partSearchLine || !session) return;
    const timer = window.setTimeout(() => {
      void searchParts(partSearchQuery);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [partSearchLine, partSearchQuery, session]);

  useEffect(() => {
    if (page !== "kitIssue" || !session || kitIssueData || kitIssueLoading) return;
    void loadKitIssueRecords(1, kitIssueOrderNo, session);
  }, [page, session, kitIssueData, kitIssueLoading, kitIssueOrderNo]);

  useEffect(() => {
    if (!success) return;
    const timer = window.setTimeout(() => setSuccess(null), 5000);
    return () => window.clearTimeout(timer);
  }, [success]);

  function handleKitIssueSearch() {
    void loadKitIssueRecords(1, kitIssueOrderNo);
  }

  function handleKitIssueReset() {
    setKitIssueOrderNo("");
    void loadKitIssueRecords(1, "");
  }

  function handleKitIssuePageChange(nextPage: number) {
    const currentOrderNo = kitIssueData?.orderNo ?? kitIssueOrderNo;
    const totalPages = kitIssueData?.totalPages ?? 1;
    const pageNumber = Math.min(Math.max(1, nextPage), totalPages);
    void loadKitIssueRecords(pageNumber, currentOrderNo);
  }

  const bomColumns = useMemo<ColDef<ProductBomRow>[]>(
    () => [
      {
        headerName: "序号",
        valueGetter: ({ node }) => (node?.rowIndex ?? 0) + 1,
        width: 70,
        pinned: "left",
        sortable: false,
        filter: false,
        headerClass: "row-number-header",
        cellClass: "row-number-cell"
      },
      { field: "partNo", headerName: "零件编号", width: 150, pinned: "left" },
      { field: "partName", headerName: "零件名称", minWidth: 320, flex: 1 },
      {
        field: "requiredQty",
        headerName: "BOM 数量",
        width: 120,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "costQty",
        headerName: "成本 BOM",
        width: 120,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      }
    ],
    []
  );

  const calculationColumns = useMemo<ColDef<CalculationLine>[]>(() => {
    const editable = calcStatus === "待确认";
    return [
      {
        headerName: "序号",
        valueGetter: ({ node }) => (node?.rowIndex ?? 0) + 1,
        width: 70,
        pinned: "left",
        sortable: false,
        filter: false,
        headerClass: "row-number-header",
        cellClass: "row-number-cell"
      },
      {
        field: "partNo",
        headerName: "零件编号",
        width: 150,
        pinned: "left",
        cellClass: editable ? "lookup-cell" : undefined,
        cellRenderer: ({ value }: ICellRendererParams<CalculationLine, string>) =>
          editable ? <span className="part-lookup-value">{value || "搜索零件"}</span> : value
      },
      { field: "partName", headerName: "零件名称", minWidth: 360, flex: 1 },
      {
        field: "bomQty",
        headerName: "BOM",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "stockSnapshot",
        headerName: "库存",
        width: 105,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: ({ data }) => {
          if (!data) return "numeric-cell";
          const stock = data.stockSnapshot ?? null;
          if (stock !== null && stock < data.calculatedQty) return "numeric-cell stock-shortage";
          return "numeric-cell";
        },
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "calculatedQty",
        headerName: "计算数量",
        width: 125,
        editable,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: editable ? "numeric-cell editable-cell" : "numeric-cell",
        headerClass: "numeric-header",
        valueParser: ({ newValue }) => Number(newValue) || 0,
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "actualQty",
        headerName: "实发数量",
        width: 115,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "issueTime", headerName: "发料时间", width: 150 },
      { field: "warehouse", headerName: "仓库", width: 105 },
      { field: "position1", headerName: "位置1", width: 110 },
      { field: "position2", headerName: "位置2", width: 110 }
    ];
  }, [calcStatus]);

  const kitIssueColumns = useMemo<ColDef<KitIssueRow>[]>(
    () => [
      {
        field: "lineNo",
        headerName: "序号",
        width: 78,
        pinned: "left",
        sortable: false,
        filter: false,
        headerClass: "row-number-header",
        cellClass: "row-number-cell"
      },
      { field: "orderNo", headerName: "订单号", width: 120, pinned: "left" },
      { field: "partNo", headerName: "零件编号", width: 150, pinned: "left" },
      { field: "partName", headerName: "零件名称", minWidth: 330, flex: 1 },
      {
        field: "warehouseDivision",
        headerName: "分类",
        width: 105,
        cellRenderer: ({ value }: ICellRendererParams<KitIssueRow, string>) =>
          value ? (
            <span className={`status-chip ${value.includes("不") ? "muted" : "success"}`}>{value}</span>
          ) : (
            ""
          )
      },
      { field: "position1", headerName: "位置", width: 120 },
      {
        field: "ratedQty",
        headerName: "额定",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "stockQty",
        headerName: "库存",
        width: 105,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: ({ data }) => {
          const stock = Number(data?.stockQty);
          const quantity = Number(data?.quantity);
          if (Number.isFinite(stock) && Number.isFinite(quantity) && stock < quantity) {
            return "numeric-cell stock-shortage";
          }
          return "numeric-cell";
        },
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "quantity",
        headerName: "需求",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "actualQty",
        headerName: "实发",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "productionReceiptStatus", headerName: "收料状态", width: 120 },
      { field: "customer", headerName: "客户", width: 140 },
      { field: "orderDate", headerName: "日期", width: 115 },
      { field: "productSku", headerName: "产品编号", width: 130 },
      { field: "productNameCn", headerName: "产品名称", minWidth: 240 },
      {
        field: "productQty",
        headerName: "产品数",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "position2", headerName: "位置2", width: 110 },
      { field: "outboundId", headerName: "出库单", width: 130 },
      { field: "issueTime", headerName: "发料时间", width: 150 },
      {
        field: "returnQty",
        headerName: "退料",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      }
    ],
    []
  );

  const partSearchColumns = useMemo<ColDef<PartInfo>[]>(
    () => [
      { field: "partNo", headerName: "零件编号", width: 150, pinned: "left" },
      { field: "partName", headerName: "零件名称", minWidth: 260, flex: 1 },
      {
        field: "stockSnapshot",
        headerName: "库存",
        width: 100,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "warehouse", headerName: "仓库", width: 110 },
      { field: "position1", headerName: "位置1", width: 120 },
      { field: "position2", headerName: "位置2", width: 120 }
    ],
    []
  );

  const product = productBom?.product ?? preview?.product ?? null;
  const effectiveGenerateQty = preview?.generateQty ?? null;
  const calculationPrimaryId = document?.id ?? preview?.calculationId ?? "-";
  const calculationDate = document?.createdAt ?? preview?.createdAt ?? null;
  const operatorLabel = session?.context.operator
    ? `${session.context.operator.name} / ${session.context.operator.account}`
    : "-";
  const calculationPageReady = Boolean(preview || document || calcLines.length > 0);
  const sidebarGroups = useMemo<SidebarNavGroup[]>(
    () => [
      {
        id: "bom-center",
        label: "BOM 计算中心",
        items: [
          {
            id: "product",
            label: "产品 BOM",
            description: "FileMaker 产品与物料清单",
            Icon: PackageSearch,
            badge: productBom ? `${productBom.foundCount} 条` : undefined
          },
          {
            id: "issue",
            label: "BOM 计算单",
            description: "计算结果、替换零件与确认写入",
            Icon: ClipboardList,
            badge: calculationPageReady ? calcStatus : "待生成",
            disabled: !calculationPageReady,
            disabledReason: "生成 BOM 后可进入"
          }
        ]
      },
      {
        id: "issue-center",
        label: "发料管理",
        items: [
          {
            id: "kitIssue",
            label: "零件包发料",
            description: "FileMaker 发料分类明细",
            Icon: Database,
            badge: kitIssueData ? `${kitIssueData.foundCount} 条` : "100/页"
          }
        ]
      }
    ],
    [calcStatus, calculationPageReady, kitIssueData, productBom]
  );

  function handleNavigate(nextPage: Page) {
    if (nextPage === page) return;
    if (nextPage === "issue" && !calculationPageReady) {
      setError("请先生成 BOM 计算单。");
      return;
    }
    setPage(nextPage);
    setError(null);
    if (nextPage === "kitIssue" && session && !kitIssueData) {
      void loadKitIssueRecords(1, kitIssueOrderNo, session);
    }
  }

  const homeNavItems = useMemo(
    () => [
      {
        id: "product" as const,
        label: "产品 BOM",
        description: "FileMaker 产品与物料清单",
        Icon: PackageSearch
      },
      {
        id: "kitIssue" as const,
        label: "零件包发料",
        description: "FileMaker 发料分类明细",
        Icon: Database
      }
    ],
    []
  );

  return (
    <main className={`app app-${page}`}>
      {page === "home" ? (
        <HomePage navItems={homeNavItems} onNavigate={handleNavigate} operatorLabel={operatorLabel} />
      ) : (
        <div className="app-layout">
          <SidebarNav
            groups={sidebarGroups}
            activePage={page}
            onNavigate={handleNavigate}
            onGoHome={() => handleNavigate("home")}
          />

          <div className="app-main">
            <AppShell
              title={pageMeta[page].title}
              subtitle={pageMeta[page].subtitle}
              calcStatus={calcStatus}
              readOnly={session?.readOnly ?? false}
              operatorLabel={operatorLabel}
            />

            {page !== "kitIssue" && <StepIndicator currentStep={currentStep} />}

            {error && <div className="alert">{error}</div>}
            {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}

            {page === "product" && (
              <ProductInfoCard
                product={product}
                fallbackSku={session?.context.productSku ?? "STRX-202"}
                generateQty={effectiveGenerateQty}
                formatQty={formatQty}
              />
            )}

            {page === "issue" && (
              <DocumentHeaderCard
                calculationPrimaryId={calculationPrimaryId}
                calculationDate={calculationDate}
                calcStatus={calcStatus}
                product={product}
                generateQty={effectiveGenerateQty}
                formatDateTime={formatDateTime}
                formatQty={formatQty}
              />
            )}

            {page === "product" && (
              <>
                <div className="command-row">
                  <button className="btn primary" onClick={() => setGenerateDialogOpen(true)} disabled={loading}>
                    <Play size={16} />
                    生成 BOM
                  </button>
                </div>
                <BomGrid
                  rows={productBom?.rows ?? []}
                  columns={bomColumns}
                  foundCount={productBom?.foundCount ?? 0}
                  loading={loading && page === "product"}
                  stateKey="product-bom"
                />
              </>
            )}

            {page === "issue" && (
              <>
                <CalculationGrid
                  lines={calcLines}
                  columns={calculationColumns}
                  issueSearch={issueSearch}
                  loading={loading && page === "issue"}
                  stateKey="bom-calculation"
                  onIssueSearchChange={setIssueSearch}
                  onCellClicked={handleLineClick}
                  onCellValueChanged={handleLineChange}
                  onConfirm={() => setConfirmOpen(true)}
                  confirmDisabled={loading || calcStatus !== "待确认" || calcLines.length === 0}
                />
              </>
            )}

            {page === "kitIssue" && (
              <KitIssueRecordsPage
                data={kitIssueData}
                columns={kitIssueColumns}
                orderNo={kitIssueOrderNo}
                loading={kitIssueLoading}
                onOrderNoChange={setKitIssueOrderNo}
                onSearch={handleKitIssueSearch}
                onReset={handleKitIssueReset}
                onPageChange={handleKitIssuePageChange}
              />
            )}

            <GenerateDialog
              open={generateDialogOpen}
              qty={generateQty}
              loading={loading}
              onQtyChange={setGenerateQty}
              onGenerate={() => void previewCalculation()}
              onCancel={() => setGenerateDialogOpen(false)}
            />

            <PartSearchDialog
              line={partSearchLine}
              query={partSearchQuery}
              loading={partSearchLoading}
              error={partSearchError}
              results={partSearchResults}
              columns={partSearchColumns}
              onQueryChange={setPartSearchQuery}
              onSearch={() => void searchParts()}
              onSelect={selectPart}
              onCancel={closePartSearch}
            />

            <ConfirmDialog
              open={confirmOpen}
              title="确认 BOM 计算单"
              message={`确认后将把 ${calcLines.length} 条发料明细写入本地 PostgreSQL，确认后不可再编辑。`}
              confirmLabel="确认"
              cancelLabel="取消"
              loading={loading}
              onConfirm={() => void confirmDocument()}
              onCancel={() => setConfirmOpen(false)}
            />
          </div>
        </div>
      )}

      <LoadingOverlay loading={loading} />
    </main>
  );
}

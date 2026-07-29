import { useEffect, useMemo, useRef, useState } from "react";
import {
  AllCommunityModule,
  ModuleRegistry,
  type CellClickedEvent,
  type CellValueChangedEvent,
  type ColDef,
  type ICellRendererParams
} from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";
import { Boxes, BrainCircuit, ClipboardList, Database, Eye, KeyRound, LogIn, MessageCircle, Play, RotateCcw, ShieldCheck, ShoppingCart, UserRound } from "lucide-react";
import AppShell from "./components/AppShell";
import SidebarNav, { type SidebarNavGroup } from "./components/SidebarNav";
import StepIndicator from "./components/StepIndicator";
import ProductInfoCard from "./components/ProductInfoCard";
import DocumentHeaderCard from "./components/DocumentHeaderCard";
import BomGrid from "./components/BomGrid";
import BomProductPicker from "./components/BomProductPicker";
import CalculationGrid from "./components/CalculationGrid";
import KitIssueRecordsPage from "./components/KitIssueRecordsPage";
import BusinessProductsPage from "./components/BusinessProductsPage";
import BusinessProductDetailPage from "./components/BusinessProductDetailPage";
import PartDirectoryPage, { type PartDirectoryRow } from "./components/PartDirectoryPage";
import PartDetailPrototypePage from "./components/PartDetailPrototypePage";
import DashboardPage from "./components/DashboardPage";
import HomePage from "./components/HomePage";
import RagControlPage from "./components/RagControlPage";
import OrderDetailPage from "./components/OrderDetailPage";
import ProductInventoryPage from "./components/ProductInventoryPage";
import InternalOrderMergePage from "./components/InternalOrderMergePage";
import InternalAccountAdminPage from "./components/InternalAccountAdminPage";
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
  BomStep,
  BusinessProductDetailResponse,
  BusinessProductFilters,
  BusinessProductRow,
  BusinessProductsResponse,
  ConfirmedDocument,
  KitIssueRecordsResponse,
  KitIssueRow,
  NaturalLanguageQueryResponse,
  NaturalQueryExchange,
  NaturalQueryTopQuestionsResponse,
  ODataRelationshipsResponse,
  Page,
  PartInfo,
  ProductBomRow,
  ProductBomResponse,
  RagIndexRefreshResponse,
  RagIndexStatusResponse,
  RagSearchResponse,
  SessionResponse,
  ThemeMode
} from "./types";

ModuleRegistry.registerModules([AllCommunityModule]);

const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
const THEME_STORAGE_KEY = "starrc-theme";

const emptyBusinessProductFilters: BusinessProductFilters = {
  category: "",
  model: "",
  audit: "",
  client: ""
};

const pageMeta: Record<Page, { title: string; subtitle: string }> = {
  home: {
    title: "Star-RC",
    subtitle: "企业运营导航中心"
  },
  chat: {
    title: "智能对话",
    subtitle: "使用自然语言查询 FileMaker 产品、零件、库存和日期数据。"
  },
  productInventory: {
    title: "出入库记录",
    subtitle: "当前产品的只读库存流水。"
  },
  internalOrderMerge: {
    title: "内部订单合并",
    subtitle: "选择当前客户的内部订单并交给 FileMaker 汇总生成新订单。"
  },
  orderDetail: {
    title: "订单详情",
    subtitle: "查看出货单与出货单明细，选择产品并生成 BOM 临时计算清单。"
  },
  bom: {
    title: "BOM 计算",
    subtitle: "选产品 → 读 BOM → 计算数量 → 微调 → 确认，全流程一页完成。"
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
  },
  businessProducts: {
    title: "产品资料",
    subtitle: "读取 FileMaker @products，支持产品搜索、条件过滤和详情查看。"
  },
  businessProductDetail: {
    title: "产品资料详情",
    subtitle: "查看 FileMaker 产品核心字段、商务分类和原始字段。"
  },
  parts: {
    title: "零件资料",
    subtitle: "搜索、筛选和浏览零件主数据，默认每页显示 10 条。"
  },
  partDetail: {
    title: "零件详细资料",
    subtitle: "采购视角的零件主数据、图片、图面、成本、包装和质量信息。"
  },
  ragControl: {
    title: "RAG 控制",
    subtitle: "查看 FileMaker RAG 索引状态，手动刷新并调试语义搜索命中。"
  },
  accessAdmin: {
    title: "账号与权限",
    subtitle: "将 FileMaker 权限集同步为 StarRC 功能授权，单独控制价格查看。"
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

function orderIdQueryValue(params: URLSearchParams): string {
  return queryValue(params, "orderId", queryValue(params, "id", ""));
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

function initialTheme(): ThemeMode {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const didInit = useRef(false);
  const [theme, setTheme] = useState<ThemeMode>(() => initialTheme());
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [remoteLoginRequired, setRemoteLoginRequired] = useState(false);
  const [remoteUsername, setRemoteUsername] = useState("");
  const [remotePassword, setRemotePassword] = useState("");
  const [remoteLoginLoading, setRemoteLoginLoading] = useState(false);
  const [remoteLoginError, setRemoteLoginError] = useState<string | null>(null);
  const [productBom, setProductBom] = useState<ProductBomResponse | null>(null);
  const [page, setPage] = useState<Page>(() => {
    const requestedPage = new URLSearchParams(window.location.search).get("page");
    return requestedPage === "productInventory"
      ? "productInventory"
      : requestedPage === "internalOrderMerge"
        ? "internalOrderMerge"
        : requestedPage === "chat"
          ? "chat"
        : requestedPage === "parts"
          ? "parts"
          : requestedPage === "partDetail" || requestedPage === "partDetailPrototype"
            ? "partDetail"
          : "home";
  });
  // BOM 单页工作台阶段与 SKU 输入
  const [bomStep, setBomStep] = useState<BomStep>("select");
  const [bomSkuInput, setBomSkuInput] = useState("");
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
  const [businessProductsData, setBusinessProductsData] = useState<BusinessProductsResponse | null>(null);
  const [businessProductQuery, setBusinessProductQuery] = useState("");
  const [businessProductFilters, setBusinessProductFilters] = useState<BusinessProductFilters>(
    emptyBusinessProductFilters
  );
  const [businessProductsLoading, setBusinessProductsLoading] = useState(false);
  const [businessProductDetail, setBusinessProductDetail] = useState<BusinessProductRow | null>(null);
  const [businessProductDetailLoading, setBusinessProductDetailLoading] = useState(false);
  const [selectedPartIdentifier, setSelectedPartIdentifier] = useState(
    () => new URLSearchParams(window.location.search).get("partId") ?? ""
  );
  const [naturalQueryPrompt, setNaturalQueryPrompt] = useState("");
  const [naturalQueryLoading, setNaturalQueryLoading] = useState(false);
  const [naturalQueryExchanges, setNaturalQueryExchanges] = useState<NaturalQueryExchange[]>([]);
  const [ragStatus, setRagStatus] = useState<RagIndexStatusResponse | null>(null);
  const [ragStatusLoading, setRagStatusLoading] = useState(false);
  const [ragRefreshing, setRagRefreshing] = useState(false);
  const [ragError, setRagError] = useState<string | null>(null);
  const [ragSearchQuery, setRagSearchQuery] = useState("昨天新增的零件，价格分别是多少");
  const [ragSearchLayout, setRagSearchLayout] = useState("Parts");
  const [ragSearchResponse, setRagSearchResponse] = useState<RagSearchResponse | null>(null);
  const [ragSearchLoading, setRagSearchLoading] = useState(false);
  const [topQuestionsData, setTopQuestionsData] = useState<NaturalQueryTopQuestionsResponse | null>(null);
  const [topQuestionsLoading, setTopQuestionsLoading] = useState(false);
  const [relationshipMappingData, setRelationshipMappingData] = useState<ODataRelationshipsResponse | null>(null);
  const [relationshipMappingLoading, setRelationshipMappingLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const calcStatus = useMemo<"未计算" | "待确认" | "已确认">(() => {
    if (document) return "已确认";
    if (preview) return "待确认";
    return "未计算";
  }, [document, preview]);

  // 单页工作台的流程指示：bom 页由 bomStep 主导；旧页保留原派生
  const currentStep = useMemo<1 | 2 | 3>(() => {
    if (page === "bom") {
      if (bomStep === "done") return 3;
      if (bomStep === "calc") return 2;
      return 1;
    }
    if (document) return 3;
    if (preview) return 2;
    return 1;
  }, [page, bomStep, document, preview]);

  async function startSession(credentials?: { username: string; password: string }) {
    const params = new URLSearchParams(window.location.search);
    const productSku = queryValue(params, "productSku", "STRX-202");
    const orderId = orderIdQueryValue(params);
    const operatorAccount = queryValue(params, "operatorAccount", "mock.operator");
    const operatorName = queryValue(params, "operatorName", "本地测试操作员");
    const customerId = queryValue(params, "customerId", "");
    const customerName = queryValue(params, "customerName", "");
    const currency = queryValue(params, "currency", "USD");
    const pageParam = params.get("page");
    const initialPage: Page =
      pageParam === "productInventory"
        ? "productInventory"
        : pageParam === "internalOrderMerge"
        ? "internalOrderMerge"
        : pageParam === "chat"
        ? "chat"
        : pageParam === "orderDetail"
        ? "orderDetail"
        : pageParam === "bom" || pageParam === "product"
        ? "bom"
        : pageParam === "kitIssue"
          ? "kitIssue"
          : pageParam === "businessProducts"
            ? "businessProducts"
            : pageParam === "parts"
              ? "parts"
              : pageParam === "partDetail" || pageParam === "partDetailPrototype"
                ? "partDetail"
            : pageParam === "ragControl"
              ? "ragControl"
              : "home";
    const ctx = params.get("ctx");
    const sig = params.get("sig");

    setKitIssueOrderNo(orderId);
    setPage(initialPage);
    setBomSkuInput(productSku);
    setBomStep("select");
    const nextSession = await postJson<SessionResponse>("/api/webviewer/session", {
      ctx,
      sig,
      mock: !credentials && !(ctx && sig),
      productSku,
      orderId,
      customerId,
      customerName,
      currency,
      operator: {
        account: operatorAccount,
        name: operatorName,
        privilege: "mock"
      },
      username: credentials?.username ?? "",
      password: credentials?.password ?? ""
    });
    setSession(nextSession);
    if (initialPage === "ragControl") {
      await loadRagStatus(nextSession);
      await loadTopQuestions(nextSession);
      await loadRelationshipMapping(nextSession);
    }
  }

  async function submitRemoteLogin() {
    if (!remoteUsername.trim() || !remotePassword) {
      setRemoteLoginError("请输入用户名和密码。");
      return;
    }
    setRemoteLoginLoading(true);
    setRemoteLoginError(null);
    try {
      await startSession({ username: remoteUsername.trim(), password: remotePassword });
      setRemotePassword("");
      setRemoteLoginRequired(false);
    } catch (err) {
      setRemoteLoginError(parseError(err));
    } finally {
      setRemoteLoginLoading(false);
    }
  }

  // 按 SKU 加载产品 BOM（单页工作台第 1 步）。成功后推进到 BOM 展示阶段。
  async function loadProductBySku(sku: string, activeSession = session) {
    if (!activeSession) return;
    const normalized = sku.trim();
    if (!normalized) {
      setError("请输入产品编号。");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchJson<ProductBomResponse>(
        `/api/products/${encodeURIComponent(normalized)}/bom-view`,
        activeSession.token
      );
      setProductBom(data);
      // 切换产品即重置后续计算/确认态
      setPreview(null);
      setCalcLines([]);
      setDocument(null);
      setBomStep("bom");
    } catch (err) {
      setError(parseError(err));
    } finally {
      setLoading(false);
    }
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

  async function loadBusinessProducts(
    nextPage = businessProductsData?.page ?? 1,
    activeSession = session,
    query = businessProductQuery,
    filters = businessProductFilters
  ) {
    if (!activeSession) return;
    setBusinessProductsLoading(true);
    setError(null);
    try {
      const pageNumber = Math.max(1, Math.trunc(nextPage));
      const params = new URLSearchParams({ page: String(pageNumber) });
      const normalizedQuery = query.trim();
      if (normalizedQuery) params.set("q", normalizedQuery);
      (Object.entries(filters) as [keyof BusinessProductFilters, string][]).forEach(([key, value]) => {
        const normalized = value.trim();
        if (normalized) params.set(key, normalized);
      });
      const data = await fetchJson<BusinessProductsResponse>(
        `/api/business-products?${params.toString()}`,
        activeSession.token
      );
      setBusinessProductsData(data);
      setBusinessProductQuery(data.query);
      setBusinessProductFilters(data.filters);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setBusinessProductsLoading(false);
    }
  }

  async function loadBusinessProductDetail(recordId: string, fallback?: BusinessProductRow) {
    if (!session) return;
    setBusinessProductDetailLoading(true);
    setError(null);
    if (fallback) setBusinessProductDetail(fallback);
    try {
      const data = await fetchJson<BusinessProductDetailResponse>(
        `/api/business-products/${encodeURIComponent(recordId)}`,
        session.token
      );
      setBusinessProductDetail(data.product);
    } catch (err) {
      setError(parseError(err));
    } finally {
      setBusinessProductDetailLoading(false);
    }
  }

  async function submitNaturalQuery(prompt = naturalQueryPrompt) {
    if (!session) {
      setError("WebViewer 会话尚未初始化，请稍后再试。");
      return;
    }
    const normalizedPrompt = prompt.trim();
    if (!normalizedPrompt) {
      setError("请输入查询内容。");
      return;
    }
    if (!session.context.access.canUseNaturalQuery) {
      setError("当前账号没有使用智能问答的权限。");
      return;
    }
    if (
      !session.context.access.canViewPrice
      && /(价格|價格|单价|單價|售价|售價|成本|price|unit[ _-]?price|cost)/i.test(normalizedPrompt)
    ) {
      setError("当前账号没有查看价格的权限。");
      return;
    }
    const exchangeId =
      window.crypto?.randomUUID?.() ?? `query-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setNaturalQueryPrompt("");
    setNaturalQueryExchanges((current) => [
      ...current,
      {
        id: exchangeId,
        prompt: normalizedPrompt
      }
    ]);
    setNaturalQueryLoading(true);
    setError(null);
    try {
      const data = await postJson<NaturalLanguageQueryResponse>(
        "/api/natural-query",
        {
          prompt: normalizedPrompt,
          limit: 10
        },
        session.token
      );
      setNaturalQueryExchanges((current) =>
        current.map((exchange) =>
          exchange.id === exchangeId ? { ...exchange, response: data } : exchange
        )
      );
    } catch (err) {
      const message = parseError(err);
      setNaturalQueryExchanges((current) =>
        current.map((exchange) =>
          exchange.id === exchangeId ? { ...exchange, error: message } : exchange
        )
      );
    } finally {
      setNaturalQueryLoading(false);
    }
  }

  async function loadRagStatus(activeSession = session) {
    if (!activeSession) return;
    setRagStatusLoading(true);
    setRagError(null);
    try {
      const data = await fetchJson<RagIndexStatusResponse>("/api/rag-index/status", activeSession.token);
      setRagStatus(data);
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setRagStatusLoading(false);
    }
  }

  async function refreshRagIndex() {
    if (!session) return;
    setRagRefreshing(true);
    setRagError(null);
    try {
      const data = await postJson<RagIndexRefreshResponse>("/api/rag-index/refresh", {}, session.token);
      setRagStatus(data.status);
      setSuccess(data.message);
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setRagRefreshing(false);
    }
  }

  async function searchRagIndex() {
    if (!session) return;
    const normalizedQuery = ragSearchQuery.trim();
    if (!normalizedQuery) {
      setRagError("请输入 RAG 搜索内容。");
      return;
    }
    setRagSearchLoading(true);
    setRagError(null);
    try {
      const params = new URLSearchParams({ q: normalizedQuery, limit: "10" });
      const normalizedLayout = ragSearchLayout.trim();
      if (normalizedLayout) params.set("layout", normalizedLayout);
      const data = await fetchJson<RagSearchResponse>(`/api/rag-index/search?${params.toString()}`, session.token);
      setRagSearchResponse(data);
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setRagSearchLoading(false);
    }
  }

  async function loadTopQuestions(activeSession = session) {
    if (!activeSession) return;
    setTopQuestionsLoading(true);
    setRagError(null);
    try {
      const data = await fetchJson<NaturalQueryTopQuestionsResponse>(
        "/api/natural-query/analytics/top-questions?days=30&limit=20&analyzePending=true&pendingLimit=100",
        activeSession.token
      );
      setTopQuestionsData(data);
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setTopQuestionsLoading(false);
    }
  }

  async function loadRelationshipMapping(activeSession = session) {
    if (!activeSession) return;
    setRelationshipMappingLoading(true);
    setRagError(null);
    try {
      const data = await fetchJson<ODataRelationshipsResponse>("/api/odata/relationships", activeSession.token);
      setRelationshipMappingData(data);
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setRelationshipMappingLoading(false);
    }
  }

  async function reloadRelationshipMapping(activeSession = session) {
    if (!activeSession) return;
    setRelationshipMappingLoading(true);
    setRagError(null);
    try {
      const data = await postJson<ODataRelationshipsResponse>("/api/odata/relationships/reload", {}, activeSession.token);
      setRelationshipMappingData(data);
      setSuccess("关系映射配置已重新读取。");
    } catch (err) {
      setRagError(parseError(err));
    } finally {
      setRelationshipMappingLoading(false);
    }
  }

  async function previewCalculation() {
    if (!session) return;
    const qty = Number(generateQty);
    if (!Number.isFinite(qty) || qty <= 0) {
      setError("生成数量必须大于 0。");
      return;
    }
    // 以实际加载的产品 SKU 为准（单页工作台可能切换了产品）
    const productSku = productBom?.product?.productSku ?? bomSkuInput.trim() ?? session.context.productSku;
    setLoading(true);
    setError(null);
    try {
      const data = await postJson<CalculationPreview>(
        "/api/bom-calculations/preview",
        {
          productSku,
          generateQty: qty
        },
        session.token
      );
      setPreview(data);
      setCalcLines(data.lines);
      setDocument(null);
      setGenerateDialogOpen(false);
      setSuccess(null);
      if (page === "bom") {
        setBomStep("calc");
      } else {
        setPage("issue");
      }
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

  // 单页工作台的本地确认：暂不写入 FileMaker / PostgreSQL，仅标记完成并锁定编辑。
  function confirmBomLocal() {
    if (!preview) return;
    const product = preview.product;
    const localDocument: ConfirmedDocument = {
      id: preview.calculationId,
      documentNo: preview.calculationId,
      status: "confirmed",
      productSku: product?.productSku ?? "",
      productName: product?.productName ?? "",
      productNameCn: product?.productNameCn ?? "",
      generateQty: preview.generateQty,
      lineCount: calcLines.length,
      createdAt: preview.createdAt,
      lines: calcLines
    };
    setDocument(localDocument);
    setBomStep("done");
    setSuccess("BOM 计算单已确认（暂未写入 FileMaker）。");
    setConfirmOpen(false);
  }

  // 「重新计算」：保留已加载的产品 BOM，仅重置计算/确认结果，回到可编辑的计算阶段。
  function resetBomWorkflow() {
    setPreview(null);
    setCalcLines([]);
    setDocument(null);
    setSuccess(null);
    setBomStep("bom");
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
    const editable = page === "bom" ? bomStep === "calc" : calcStatus === "待确认";
    if (!editable) return;
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
      const params = new URLSearchParams(window.location.search);
      if (!(params.get("ctx") && params.get("sig"))) {
        setRemoteLoginRequired(true);
        setRemoteLoginError(null);
      } else {
        setError(parseError(err));
      }
    });
  }, []);

  useEffect(() => {
    window.document.documentElement.dataset.theme = theme;
    window.document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    if (page !== "parts" && page !== "partDetail") return;
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
    });
  }, [page, selectedPartIdentifier]);

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

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
    if (page !== "businessProducts" || !session || businessProductsData || businessProductsLoading) return;
    void loadBusinessProducts(1, session);
  }, [page, session, businessProductsData, businessProductsLoading]);

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

  function handleBusinessProductFilterChange(key: keyof BusinessProductFilters, value: string) {
    setBusinessProductFilters((current) => ({
      ...current,
      [key]: value
    }));
  }

  function handleBusinessProductsSearch() {
    void loadBusinessProducts(1);
  }

  function handleBusinessProductsReset() {
    setBusinessProductQuery("");
    setBusinessProductFilters(emptyBusinessProductFilters);
    void loadBusinessProducts(1, session, "", emptyBusinessProductFilters);
  }

  function handleBusinessProductsPageChange(nextPage: number) {
    const totalPages = businessProductsData?.totalPages ?? 1;
    const pageNumber = Math.min(Math.max(1, nextPage), totalPages);
    void loadBusinessProducts(pageNumber);
  }

  function openBusinessProductDetail(row: BusinessProductRow) {
    setBusinessProductDetail(row);
    setPage("businessProductDetail");
    void loadBusinessProductDetail(row.recordId, row);
  }

  function setPartPageUrl(nextPage: "parts" | "partDetail", part?: PartDirectoryRow) {
    const url = new URL(window.location.href);
    url.searchParams.set("page", nextPage);
    if (nextPage === "partDetail" && part) {
      url.searchParams.set("partId", part.partId || part.partNumber);
    } else {
      url.searchParams.delete("partId");
    }
    window.history.pushState({}, "", url);
  }

  function openPartDetail(part: PartDirectoryRow) {
    setSelectedPartIdentifier(part.partId || part.partNumber);
    setPage("partDetail");
    setError(null);
    setPartPageUrl("partDetail", part);
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
  }

  function returnToParts() {
    setPage("parts");
    setError(null);
    setPartPageUrl("parts");
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
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
    // 单页工作台：bomStep === "calc" 时可编辑；done 时只读。
    // 旧页：calcStatus === "待确认" 时可编辑。
    const editable = page === "bom" ? bomStep === "calc" : calcStatus === "待确认";
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
  }, [calcStatus, page, bomStep]);

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

  const businessProductColumns = useMemo<ColDef<BusinessProductRow>[]>(
    () => [
      {
        headerName: "操作",
        width: 92,
        pinned: "left",
        sortable: false,
        filter: false,
        cellRenderer: ({ data }: ICellRendererParams<BusinessProductRow>) =>
          data ? (
            <button className="grid-action-button" type="button" onClick={() => openBusinessProductDetail(data)}>
              <Eye size={14} />
              查看
            </button>
          ) : null
      },
      { field: "productSku", headerName: "产品编号", width: 145, pinned: "left" },
      { field: "productNameCn", headerName: "中文名称", minWidth: 250, flex: 1 },
      { field: "productName", headerName: "英文名称", minWidth: 260, flex: 1 },
      { field: "modelName", headerName: "车款", width: 150 },
      { field: "scale", headerName: "比例", width: 90 },
      { field: "category", headerName: "类别", width: 110 },
      {
        field: "auditStatus",
        headerName: "审核",
        width: 105,
        cellRenderer: ({ value }: ICellRendererParams<BusinessProductRow, string>) =>
          value ? <span className="status-chip success">{value}</span> : ""
      },
      {
        field: "bomCount",
        headerName: "BOM",
        width: 95,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      {
        field: "stock",
        headerName: "库存",
        width: 100,
        filter: "agNumberColumnFilter",
        filterParams: numberFilterParams,
        cellClass: "numeric-cell",
        headerClass: "numeric-header",
        valueFormatter: ({ value }) => formatQty(value)
      },
      { field: "client", headerName: "Client", width: 120 },
      { field: "customer", headerName: "客户", width: 150 },
      { field: "category1", headerName: "分类 1", width: 140 },
      { field: "category2", headerName: "分类 2", width: 140 },
      { field: "category3", headerName: "分类 3", width: 160 },
      { field: "bomDate", headerName: "BOM 日期", width: 120 }
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
  const operatorDisplayName = session?.context.operator.name?.trim() || "";
  const operatorAccount = session?.context.operator.account?.trim() || "";
  const operatorLabel = operatorDisplayName || operatorAccount
    ? operatorDisplayName && operatorAccount && operatorDisplayName.localeCompare(operatorAccount, undefined, { sensitivity: "accent" }) !== 0
      ? `${operatorDisplayName} / ${operatorAccount}`
      : operatorDisplayName || operatorAccount
    : "-";
  const operatorName =
    session?.context.operator.name || session?.context.operator.account || "";
  const access = session?.context.access;
  const requestedOrderId =
    session?.context.orderId || orderIdQueryValue(new URLSearchParams(window.location.search));
  const calculationPageReady = Boolean(preview || document || calcLines.length > 0);
  const activeNavPage: Page = page === "businessProductDetail"
    ? "businessProducts"
    : page === "partDetail"
      ? "parts"
      : page;
  const showBOMWorkflow = page === "bom" || page === "product" || page === "issue";
  const sidebarGroups = useMemo<SidebarNavGroup[]>(
    () => [
      {
        id: "order-center",
        label: "订单管理",
        items: [
          {
            id: "orderDetail",
            label: "订单详情",
            description: "出货单明细与整单 BOM 计算",
            Icon: ShoppingCart,
            disabled: access ? !access.canViewOrders : false,
            disabledReason: "当前 FileMaker 权限集未开放订单资料"
          }
        ]
      },
      {
        id: "bom-center",
        label: "BOM 计算中心",
        items: [
          {
            id: "bom",
            label: "BOM 计算",
            description: "选产品 → 读 BOM → 计算 → 微调 → 确认",
            Icon: ClipboardList,
            disabled: access ? !access.canViewBom : false,
            disabledReason: "当前 FileMaker 权限集未开放 BOM / 发料",
            badge: productBom
              ? bomStep === "done"
                ? "已确认"
                : preview
                  ? `${preview.lines.length} 条`
                  : `${productBom.foundCount} 条`
              : undefined
          }
        ]
      },
      {
        id: "product-master",
        label: "产品资料",
        items: [
          {
            id: "businessProducts",
            label: "产品资料",
            description: "@products 列表与详情",
            Icon: Boxes,
            disabled: access ? !access.canViewProducts : false,
            disabledReason: "当前 FileMaker 权限集未开放产品资料",
            badge: businessProductsData ? `${businessProductsData.foundCount} 条` : undefined
          },
          {
            id: "parts",
            label: "零件资料",
            description: "零件主表、关联资料与 COS 多图详情",
            Icon: Boxes,
            disabled: access ? !access.canViewProducts : false,
            disabledReason: "当前 FileMaker 权限集未开放产品资料",
            badge: "筛选查询"
          }
        ]
      },
      {
        id: "ai-search",
        label: "智能搜索",
        items: [
          {
            id: "chat",
            label: "智能对话",
            description: "用自然语言查询 FileMaker 数据",
            Icon: MessageCircle,
            disabled: access ? !access.canUseNaturalQuery : false,
            disabledReason: "当前 FileMaker 权限集未开放智能问答"
          },
          {
            id: "ragControl",
            label: "RAG 控制",
            description: "索引状态、刷新与搜索调试",
            Icon: BrainCircuit,
            disabled: access ? !access.canManageRag : false,
            disabledReason: "当前 FileMaker 权限集未开放 RAG 管理",
            badge: ragStatus?.running ? "刷新中" : ragStatus ? `${ragStatus.recordCount} 条` : undefined
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
            disabled: access ? !access.canViewBom : false,
            disabledReason: "当前 FileMaker 权限集未开放 BOM / 发料",
            badge: kitIssueData ? `${kitIssueData.foundCount} 条` : "100/页"
          }
        ]
      },
      ...(access?.canManageAccounts
        ? [{
            id: "system-admin",
            label: "系统管理",
            items: [{
              id: "accessAdmin" as Page,
              label: "账号与权限",
              description: "FileMaker 权限集与 StarRC 授权",
              Icon: ShieldCheck,
              badge: access.canViewPrice ? "可看价格" : "价格受限"
            }]
          }]
        : [])
    ],
    [access, businessProductsData, bomStep, kitIssueData, preview, productBom, ragStatus]
  );

  function handleNavigate(nextPage: Page) {
    if (nextPage === page) return;
    if (nextPage === "issue" && !calculationPageReady) {
      setError("请先生成 BOM 计算单。");
      return;
    }
    setPage(nextPage);
    setError(null);
    if (nextPage === "parts") {
      setPartPageUrl("parts");
    }
    if (nextPage === "bom") {
      // 首次进入工作台：从产品选择开始；若已有数据则恢复到对应阶段
      if (!productBom && !preview && !document) {
        setBomStep("select");
        if (!bomSkuInput && session?.context.productSku) setBomSkuInput(session.context.productSku);
      } else if (document) {
        setBomStep("done");
      } else if (preview) {
        setBomStep("calc");
      } else {
        setBomStep("bom");
      }
    }
    if (nextPage === "kitIssue" && session && !kitIssueData) {
      void loadKitIssueRecords(1, kitIssueOrderNo, session);
    }
    if (nextPage === "businessProducts" && session && !businessProductsData) {
      void loadBusinessProducts(1, session);
    }
    if (nextPage === "ragControl" && session && !ragStatus) {
      void loadRagStatus(session);
    }
    if (nextPage === "ragControl" && session && !topQuestionsData) {
      void loadTopQuestions(session);
    }
    if (nextPage === "ragControl" && session && !relationshipMappingData) {
      void loadRelationshipMapping(session);
    }
  }

  if (!session && remoteLoginRequired) {
    return (
      <main className="remote-login-page">
        <section className="remote-login-card" aria-labelledby="remote-login-title">
          <div className="remote-login-brand">
            <span>STAR RC</span>
            <small>FileMaker Web 工作台</small>
          </div>
          <div className="remote-login-icon" aria-hidden="true"><KeyRound size={23} /></div>
          <h1 id="remote-login-title">内部员工登录</h1>
          <p>线上工作台仅供授权同事使用。登录后会保留当前 FileMaker 客户与订单上下文。</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submitRemoteLogin();
            }}
          >
            <label className="remote-login-field">
              <span>用户名</span>
              <span className="remote-login-input"><UserRound size={17} /><input autoComplete="username" value={remoteUsername} onChange={(event) => setRemoteUsername(event.target.value)} autoFocus /></span>
            </label>
            <label className="remote-login-field">
              <span>密码</span>
              <span className="remote-login-input"><KeyRound size={17} /><input type="password" autoComplete="current-password" value={remotePassword} onChange={(event) => setRemotePassword(event.target.value)} /></span>
            </label>
            {remoteLoginError && <div className="remote-login-error">{remoteLoginError}</div>}
            <button className="remote-login-submit" type="submit" disabled={remoteLoginLoading}>
              {remoteLoginLoading ? "正在登录…" : "进入工作台"}<LogIn size={17} />
            </button>
          </form>
          <small className="remote-login-note">访问及合并操作会记录操作账号和时间。</small>
        </section>
      </main>
    );
  }

  if (page === "productInventory") {
    return (
      <main className="app app-productInventory">
        <ProductInventoryPage
          apiBase={apiBase}
          token={session?.token ?? ""}
          productSku={session?.context.productSku || bomSkuInput}
          sessionError={error}
        />
      </main>
    );
  }

  if (page === "internalOrderMerge") {
    return (
      <main className="app app-internalOrderMerge">
        <InternalOrderMergePage
          apiBase={apiBase}
          token={session?.token ?? ""}
          customerId={session?.context.customerId ?? ""}
          customerName={session?.context.customerName ?? ""}
          currency={session?.context.currency ?? "USD"}
          canViewPrice={session?.context.access.canViewPrice ?? false}
          canMergeOrders={session?.context.access.canMergeOrders ?? false}
          sessionError={error}
        />
      </main>
    );
  }

  return (
    <main className={`app app-${page}`}>
      {page === "chat" ? (
        <HomePage
          operatorName={operatorName}
          naturalQueryPrompt={naturalQueryPrompt}
          naturalQueryLoading={naturalQueryLoading}
          naturalQueryExchanges={naturalQueryExchanges}
          canUseNaturalQuery={session?.context.access.canUseNaturalQuery ?? false}
          canViewPrice={session?.context.access.canViewPrice ?? false}
          onNaturalQueryPromptChange={setNaturalQueryPrompt}
          onNaturalQuerySubmit={(prompt) => void submitNaturalQuery(prompt)}
          onOpenBusinessProduct={openBusinessProductDetail}
          onOpenDashboard={() => handleNavigate("home")}
        />
      ) : (
        <div className={`app-layout ${page === "orderDetail" ? "app-layout-standalone" : ""}`}>
          {page !== "orderDetail" && (
            <SidebarNav
              groups={sidebarGroups}
              activePage={activeNavPage}
              onNavigate={handleNavigate}
              onGoHome={() => handleNavigate("home")}
            />
          )}

          <div className="app-main">
            <AppShell
              title={pageMeta[page].title}
              subtitle={pageMeta[page].subtitle}
              calcStatus={showBOMWorkflow ? calcStatus : null}
              readOnly={session?.readOnly ?? false}
              controlledWrite={page === "orderDetail" && (session?.bomWriteEnabled ?? false)}
              operatorLabel={operatorLabel}
              theme={theme}
              onThemeToggle={toggleTheme}
            />

            {showBOMWorkflow && <StepIndicator currentStep={currentStep} />}

            {error && <div className="alert">{error}</div>}
            {success && <SuccessAlert message={success} onClose={() => setSuccess(null)} />}

            {page === "home" && (
              <DashboardPage
                groups={sidebarGroups}
                operatorName={operatorName}
                canViewPrice={session?.context.access.canViewPrice ?? false}
                readOnly={session?.readOnly ?? true}
                onNavigate={handleNavigate}
              />
            )}

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

            {/* BOM 单页工作台：选产品 → 读 BOM → 计算数量 → 微调 → 确认（渐进展开） */}
            {page === "bom" && (
              <>
                <BomProductPicker
                  sku={bomSkuInput}
                  defaultSku={session?.context.productSku}
                  loading={loading && bomStep === "select"}
                  onSkuChange={setBomSkuInput}
                  onLoad={() => void loadProductBySku(bomSkuInput)}
                />

                {productBom && (
                  <>
                    <ProductInfoCard
                      product={product}
                      fallbackSku={bomSkuInput || session?.context.productSku || "STRX-202"}
                      generateQty={effectiveGenerateQty}
                      formatQty={formatQty}
                    />
                    <div className="command-row">
                      <button
                        className="btn primary"
                        onClick={() => setGenerateDialogOpen(true)}
                        disabled={loading || bomStep === "done"}
                      >
                        <Play size={16} />
                        {bomStep === "calc" || bomStep === "done" ? "重新生成" : "生成 BOM"}
                      </button>
                    </div>
                    <BomGrid
                      rows={productBom.rows}
                      columns={bomColumns}
                      foundCount={productBom.foundCount}
                      loading={loading && bomStep === "select"}
                      stateKey="product-bom"
                    />
                  </>
                )}

                {(preview || calcLines.length > 0) && (
                  <>
                    <DocumentHeaderCard
                      calculationPrimaryId={calculationPrimaryId}
                      calculationDate={calculationDate}
                      calcStatus={calcStatus}
                      product={product}
                      generateQty={effectiveGenerateQty}
                      formatDateTime={formatDateTime}
                      formatQty={formatQty}
                    />
                    <CalculationGrid
                      lines={calcLines}
                      columns={calculationColumns}
                      issueSearch={issueSearch}
                      loading={loading && bomStep === "calc"}
                      stateKey="bom-calculation"
                      onIssueSearchChange={setIssueSearch}
                      onCellClicked={handleLineClick}
                      onCellValueChanged={handleLineChange}
                      onConfirm={() => setConfirmOpen(true)}
                      confirmDisabled={loading || bomStep !== "calc" || calcLines.length === 0}
                    />
                  </>
                )}

                {bomStep === "done" && document && (
                  <section className="card bom-stage bom-stage-done">
                    <div className="bom-done-banner">
                      <div className="bom-done-text">
                        <strong>BOM 计算单已确认</strong>
                        <span>暂未写入 FileMaker。共 {document.lineCount} 条发料明细。</span>
                      </div>
                      <button className="btn" type="button" onClick={resetBomWorkflow}>
                        <RotateCcw size={15} />
                        重新计算
                      </button>
                    </div>
                  </section>
                )}
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

            {page === "orderDetail" && (
              <OrderDetailPage
                orderId={requestedOrderId}
                token={session?.token ?? ""}
                apiBase={apiBase}
                operatorAccount={session?.context.operator.account ?? ""}
                operatorName={session?.context.operator.name ?? ""}
                canViewPrice={session?.context.access.canViewPrice ?? false}
                bomWriteEnabled={session?.bomWriteEnabled ?? false}
                onSuccess={setSuccess}
              />
            )}

            {page === "businessProducts" && (
              <BusinessProductsPage
                data={businessProductsData}
                columns={businessProductColumns}
                query={businessProductQuery}
                filters={businessProductFilters}
                loading={businessProductsLoading}
                onQueryChange={setBusinessProductQuery}
                onFilterChange={handleBusinessProductFilterChange}
                onSearch={handleBusinessProductsSearch}
                onReset={handleBusinessProductsReset}
                onPageChange={handleBusinessProductsPageChange}
                onOpenDetail={openBusinessProductDetail}
              />
            )}

            {page === "businessProductDetail" && (
              <BusinessProductDetailPage
                product={businessProductDetail}
                loading={businessProductDetailLoading}
                formatQty={formatQty}
                onBack={() => handleNavigate("businessProducts")}
              />
            )}

            {page === "parts" && (
              <PartDirectoryPage
                apiBase={apiBase}
                token={session?.token ?? ""}
                onOpenPart={openPartDetail}
              />
            )}

            {page === "partDetail" && (
              <PartDetailPrototypePage
                apiBase={apiBase}
                token={session?.token ?? ""}
                identifier={selectedPartIdentifier}
                onBack={returnToParts}
              />
            )}

            {page === "ragControl" && (
              <RagControlPage
                status={ragStatus}
                searchResponse={ragSearchResponse}
                topQuestions={topQuestionsData}
                relationshipMapping={relationshipMappingData}
                query={ragSearchQuery}
                layout={ragSearchLayout}
                loading={ragStatusLoading}
                refreshing={ragRefreshing}
                searching={ragSearchLoading}
                topQuestionsLoading={topQuestionsLoading}
                relationshipMappingLoading={relationshipMappingLoading}
                error={ragError}
                onQueryChange={setRagSearchQuery}
                onLayoutChange={setRagSearchLayout}
                onLoadStatus={() => void loadRagStatus()}
                onRefresh={() => void refreshRagIndex()}
                onSearch={() => void searchRagIndex()}
                onLoadTopQuestions={() => void loadTopQuestions()}
                onLoadRelationshipMapping={() => void loadRelationshipMapping()}
                onReloadRelationshipMapping={() => void reloadRelationshipMapping()}
              />
            )}

            {page === "accessAdmin" && session && (
              <InternalAccountAdminPage
                apiBase={apiBase}
                token={session.token}
                currentUsername={session.context.operator.account}
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
              message={
                page === "bom"
                  ? `确认后将标记本单为已确认（暂未写入 FileMaker），明细将锁定为只读。共 ${calcLines.length} 条。`
                  : `确认后将把 ${calcLines.length} 条发料明细写入本地 PostgreSQL，确认后不可再编辑。`
              }
              confirmLabel="确认"
              cancelLabel="取消"
              loading={loading}
              onConfirm={() => (page === "bom" ? confirmBomLocal() : void confirmDocument())}
              onCancel={() => setConfirmOpen(false)}
            />
          </div>
        </div>
      )}

      <LoadingOverlay loading={loading} />
    </main>
  );
}

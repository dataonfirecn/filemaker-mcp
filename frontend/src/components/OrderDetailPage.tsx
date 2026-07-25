import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Factory,
  Image as ImageIcon,
  LoaderCircle,
  Maximize2,
  PackageCheck,
  PackageSearch,
  Replace,
  RotateCcw,
  Search,
  Sparkles,
  Undo2,
  X
} from "lucide-react";

type OrderItem = {
  id: string;
  sku: string;
  name: string;
  englishName: string;
  hasImage: boolean;
  client: string;
  stock: number;
  unitPrice?: number;
  systemProductSku: string;
  scale: string;
  category: string;
  auditStatus: string;
  availability: string;
  moq: number;
  bomCount: number;
  bomDate: string;
  barcode: string;
  labelSpec: string;
  salesNotes: string;
  vendor: string;
  specification: string;
  quantity: number;
  unit: string;
  shipDate: string;
  selected: boolean;
};

type ProductMasterDetail = Pick<OrderItem,
  "sku" | "name" | "englishName" | "hasImage" | "client" | "stock" | "unitPrice" |
  "systemProductSku" | "scale" | "category" | "auditStatus" | "availability" | "moq" |
  "bomCount" | "bomDate" | "barcode" | "labelSpec" | "salesNotes" | "vendor"
>;

type OrderInfo = {
  orderId: string;
  internalOrderNo: string;
  piNo: string;
  customerPo: string;
  customer: string;
  orderDate: string;
  shipDate: string;
  salesOwner: string;
  status: string;
  notes: string;
  bomCalculationId: string;
};

type OrderDetailResponse = {
  order: OrderInfo;
  items: Omit<OrderItem, "selected">[];
};

type ProductBomResponse = {
  rows: Array<{
    partNo: string;
    partName: string;
    requiredQty: number | string | null;
  }>;
};

type PartDetail = {
  partNo: string;
  partName: string;
  englishName: string;
  externalName: string;
  stock: number;
  supplyStatus: string;
  status: string;
  auditStatus: string;
  partType: string;
  supplier: string;
  buyer: string;
  warehouseDivision: string;
  department: string;
  customer: string;
  turnoverTime: number;
  position1: string;
  position2: string;
  hasImage: boolean;
};

type PartDetailsResponse = {
  rows: PartDetail[];
};

type BomDefinition = {
  partNo: string;
  partName: string;
  specification: string;
  unit: string;
  qtyPerProduct: number;
};

type BomSource = {
  itemId: string;
  sku: string;
  productName: string;
  orderQuantity: number;
  qtyPerProduct: number;
  subtotal: number;
};

type BomLine = {
  partNo: string;
  partName: string;
  specification: string;
  unit: string;
  requiredQty: number;
  calculatedQty: number;
  selected: boolean;
  sources: BomSource[];
  replacement?: PartReplacement;
};

type BomWriteLine = {
  partNo: string;
  originalPartNo: string;
  ratedQty: number;
  quantity: number;
  productSku: string;
  productQty: number;
  orderItemId: string;
  replacementReason: string;
};

type BomWriteResponse = {
  ok: boolean;
  duplicate: boolean;
  requestId: string;
  orderId: string;
  bomCalculationId: string;
  headerRecordId: string;
  detailCount: number;
  partCount: number;
  orderLinked: boolean;
};

type PartSearchItem = {
  partNo: string;
  partName: string;
  stockSnapshot: number | null;
  warehouse: string;
  position1: string;
  position2: string;
  raw: Record<string, unknown>;
};

type PartSearchResponse = {
  rows: PartSearchItem[];
  foundCount: number;
};

type PartReplacement = {
  partNo: string;
  partName: string;
  quantity: number;
  stockSnapshot: number | null;
  warehouse: string;
  position1: string;
  position2: string;
  reason: string;
  unit: string;
  specification: string;
  partType: string;
  supplyStatus: string;
  conflictMode?: "merge" | "separate";
};

type LoadDiagnosticStatus = "pending" | "running" | "success" | "error" | "skipped";
type LoadDiagnosticEntry = {
  id: string;
  sequence: number;
  phase: "订单读取" | "产品 BOM" | "零件资料";
  target: string;
  status: LoadDiagnosticStatus;
  startedAt: number | null;
  durationMs: number | null;
  httpStatus: number | null;
  detail: string;
};

type BomSortKey = "partNo" | "sourceCount" | "requiredQty" | "calculatedQty";
type SortDirection = "asc" | "desc";
type BomColumnKey = "select" | "expand" | "part" | "specification" | "sources" | "required" | "calculated" | "unit" | "actions";
type DetailModal =
  | { type: "product"; item: OrderItem }
  | { type: "part"; line: BomLine }
  | null;

function buildBomLines(items: OrderItem[], bomBySku: Record<string, BomDefinition[]>): BomLine[] {
  const grouped = new Map<string, BomLine>();

  items.filter((item) => item.selected).forEach((item) => {
    (bomBySku[item.sku] ?? []).forEach((part) => {
      const subtotal = item.quantity * part.qtyPerProduct;
      const source: BomSource = {
        itemId: item.id,
        sku: item.sku,
        productName: item.name,
        orderQuantity: item.quantity,
        qtyPerProduct: part.qtyPerProduct,
        subtotal
      };
      const existing = grouped.get(part.partNo);
      if (existing) {
        existing.requiredQty += subtotal;
        existing.calculatedQty += subtotal;
        existing.sources.push(source);
      } else {
        grouped.set(part.partNo, {
          partNo: part.partNo,
          partName: part.partName,
          specification: part.specification,
          unit: part.unit,
          requiredQty: subtotal,
          calculatedQty: subtotal,
          selected: true,
          sources: [source]
        });
      }
    });
  });

  return Array.from(grouped.values());
}

function roundFileMakerQuantity(value: number): number {
  return Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
}

function buildBomWriteLines(lines: BomLine[]): BomWriteLine[] {
  const result: BomWriteLine[] = [];
  lines.filter((line) => line.selected).forEach((line) => {
    const finalQuantity = line.replacement?.quantity ?? line.calculatedQty;
    if (!Number.isFinite(finalQuantity) || finalQuantity < 0) {
      throw new Error(`零件 ${line.partNo} 的计算数量不能小于 0`);
    }
    const sources = line.sources.filter((source) => source.orderQuantity > 0);
    if (!sources.length) {
      throw new Error(`零件 ${line.partNo} 缺少有效的订单产品来源`);
    }
    const sourceWeightTotal = sources.reduce(
      (sum, source) => sum + Math.max(0, source.subtotal),
      0
    );
    let remaining = roundFileMakerQuantity(finalQuantity);
    sources.forEach((source, index) => {
      const isLast = index === sources.length - 1;
      const rawAllocation = sourceWeightTotal > 0
        ? finalQuantity * Math.max(0, source.subtotal) / sourceWeightTotal
        : finalQuantity / sources.length;
      const quantity = isLast
        ? remaining
        : Math.min(remaining, roundFileMakerQuantity(rawAllocation));
      remaining = roundFileMakerQuantity(remaining - quantity);
      result.push({
        partNo: line.replacement?.partNo ?? line.partNo,
        originalPartNo: line.partNo,
        ratedQty: roundFileMakerQuantity(quantity / source.orderQuantity),
        quantity,
        productSku: source.sku,
        productQty: source.orderQuantity,
        orderItemId: source.itemId,
        replacementReason: line.replacement?.reason ?? ""
      });
    });
  });
  if (!result.length) throw new Error("没有可写入 FileMaker 的 BOM 明细");
  return result;
}

export type OrderDetailPageProps = {
  orderId: string;
  token: string;
  apiBase?: string;
  operatorAccount?: string;
  operatorName?: string;
  canViewPrice?: boolean;
  bomWriteEnabled?: boolean;
  onSuccess?: (message: string) => void;
};

const REPLACEMENT_REASON_TEMPLATES = ["原零件缺货", "客户指定", "产品升级", "成本调整", "临时替代", "其他"];
const DEFAULT_BOM_COLUMN_WIDTHS: Record<BomColumnKey, number> = {
  select: 44,
  expand: 34,
  part: 340,
  specification: 130,
  sources: 115,
  required: 120,
  calculated: 130,
  unit: 68,
  actions: 110
};
const MIN_BOM_COLUMN_WIDTHS: Record<BomColumnKey, number> = {
  select: 38,
  expand: 30,
  part: 220,
  specification: 80,
  sources: 90,
  required: 90,
  calculated: 105,
  unit: 55,
  actions: 96
};

function isDistinctDescription(primary: string, secondary: string): boolean {
  const normalize = (value: string) => value.normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase("zh-CN");
  return Boolean(secondary.trim()) && normalize(primary) !== normalize(secondary);
}

async function responseFailureDetail(response: Response): Promise<string> {
  const text = (await response.text()).trim();
  if (!text) return `HTTP ${response.status} ${response.statusText}`.trim();
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown };
    const detail = typeof payload.detail === "object" && payload.detail !== null && "message" in payload.detail
      ? (payload.detail as { message?: unknown }).message
      : payload.detail ?? payload.message;
    const normalized = typeof detail === "string" ? detail : JSON.stringify(detail);
    return (normalized || text).replace(/\s+/g, " ").slice(0, 600);
  } catch {
    return text.replace(/\s+/g, " ").slice(0, 600);
  }
}

function formatDiagnosticDuration(durationMs: number | null): string {
  if (durationMs === null) return "-";
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(durationMs < 10000 ? 1 : 0)} 秒`;
}

function diagnosticStatusLabel(status: LoadDiagnosticStatus): string {
  return { pending: "等待", running: "进行中", success: "成功", error: "失败", skipped: "未执行" }[status];
}

function rawText(part: PartSearchItem | null, keys: string[]): string {
  if (!part) return "";
  for (const key of keys) {
    const value = part.raw[key];
    if (value !== null && value !== undefined && String(value).trim()) return String(value).trim();
  }
  return "";
}

export default function OrderDetailPage({
  orderId,
  token,
  apiBase = "",
  operatorAccount = "",
  operatorName = "",
  canViewPrice = false,
  bomWriteEnabled = false,
  onSuccess
}: OrderDetailPageProps) {
  const [order, setOrder] = useState<OrderInfo | null>(null);
  const [items, setItems] = useState<OrderItem[]>([]);
  const [bomLines, setBomLines] = useState<BomLine[]>([]);
  const [expandedParts, setExpandedParts] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [submittingBom, setSubmittingBom] = useState(false);
  const [submittedBomId, setSubmittedBomId] = useState("");
  const [sortKey, setSortKey] = useState<BomSortKey>("partNo");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [bomSearch, setBomSearch] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [loadingOrder, setLoadingOrder] = useState(false);
  const [orderTimedOut, setOrderTimedOut] = useState(false);
  const [orderProgress, setOrderProgress] = useState(0);
  const [bomProgress, setBomProgress] = useState(0);
  const [generatingBom, setGeneratingBom] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [productImages, setProductImages] = useState<Record<string, string>>({});
  const [productImageLoading, setProductImageLoading] = useState<Record<string, boolean>>({});
  const [productDetails, setProductDetails] = useState<Record<string, ProductMasterDetail>>({});
  const [productDetailLoading, setProductDetailLoading] = useState<Record<string, boolean>>({});
  const productImageObjectUrls = useRef<string[]>([]);
  const [partDetails, setPartDetails] = useState<Record<string, PartDetail>>({});
  const [partImages, setPartImages] = useState<Record<string, string>>({});
  const [partImageLoading, setPartImageLoading] = useState<Record<string, boolean>>({});
  const partImageObjectUrls = useRef<string[]>([]);
  const [detailModal, setDetailModal] = useState<DetailModal>(null);
  const [replacementModalLine, setReplacementModalLine] = useState<BomLine | null>(null);
  const [replacementQuery, setReplacementQuery] = useState("");
  const [replacementResults, setReplacementResults] = useState<PartSearchItem[]>([]);
  const [replacementSelected, setReplacementSelected] = useState<PartSearchItem | null>(null);
  const [replacementQty, setReplacementQty] = useState("");
  const [replacementReason, setReplacementReason] = useState("");
  const [replacementConflictMode, setReplacementConflictMode] = useState<"merge" | "separate" | null>(null);
  const [replacementSearching, setReplacementSearching] = useState(false);
  const [replacementError, setReplacementError] = useState<string | null>(null);
  const [submitConfirmOpen, setSubmitConfirmOpen] = useState(false);
  const [regenerateConfirmOpen, setRegenerateConfirmOpen] = useState(false);
  const [selectionAdjustConfirmOpen, setSelectionAdjustConfirmOpen] = useState(false);
  const [loadDiagnostics, setLoadDiagnostics] = useState<LoadDiagnosticEntry[]>([]);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [diagnosticClock, setDiagnosticClock] = useState(Date.now());
  const [bomColumnWidths, setBomColumnWidths] = useState<Record<BomColumnKey, number>>(DEFAULT_BOM_COLUMN_WIDTHS);
  const bomColumnResize = useRef<{ column: BomColumnKey; startX: number; startWidth: number } | null>(null);

  const selectedItems = items.filter((item) => item.selected);
  const selectedBomLines = bomLines.filter((line) => line.selected);
  const sharedPartCount = bomLines.filter((line) => line.sources.length > 1).length;
  const replacedLineCount = selectedBomLines.filter((line) => line.replacement).length;
  const totalCalculatedQty = selectedBomLines.reduce(
    (sum, line) => sum + (line.replacement?.quantity ?? line.calculatedQty),
    0
  );
  const allItemsSelected = items.length > 0 && items.every((item) => item.selected);
  const allBomSelected = bomLines.length > 0 && bomLines.every((line) => line.selected);
  const bomTableWidth = Object.values(bomColumnWidths).reduce((sum, width) => sum + width, 0);
  const excludedItemsAfterCalculation = bomLines.length > 0 ? items.filter((item) => !item.selected) : [];
  const runningDiagnostic = [...loadDiagnostics].reverse().find((entry) => entry.status === "running") ?? null;
  const completedDiagnosticCount = loadDiagnostics.filter((entry) => entry.status === "success" || entry.status === "error").length;
  const failedDiagnosticCount = loadDiagnostics.filter((entry) => entry.status === "error").length;
  const slowDiagnosticCount = loadDiagnostics.filter((entry) => (entry.durationMs ?? 0) >= 3000).length;
  const runningDiagnosticDuration = runningDiagnostic?.startedAt ? diagnosticClock - runningDiagnostic.startedAt : null;
  const activeOperationDiagnostics = generatingBom
    ? loadDiagnostics.filter((entry) => entry.phase !== "订单读取")
    : loadDiagnostics.filter((entry) => entry.phase === "订单读取");
  const activeOperationCompleted = activeOperationDiagnostics.filter((entry) => entry.status === "success" || entry.status === "error").length;
  const sortedBomLines = useMemo(() => {
    const keyword = bomSearch.trim().toLocaleLowerCase("zh-CN");
    const filteredLines = keyword
      ? bomLines.filter((line) => [
          line.partNo,
          line.partName,
          line.specification,
          line.replacement?.partNo ?? "",
          line.replacement?.partName ?? "",
          ...line.sources.flatMap((source) => [source.sku, source.productName])
        ].some((value) => value.toLocaleLowerCase("zh-CN").includes(keyword)))
      : bomLines;
    const direction = sortDirection === "asc" ? 1 : -1;
    return [...filteredLines].sort((left, right) => {
      if (sortKey === "partNo") {
        return left.partNo.localeCompare(right.partNo, "zh-CN", { numeric: true }) * direction;
      }
      const leftValue = sortKey === "sourceCount" ? left.sources.length : sortKey === "calculatedQty" ? (left.replacement?.quantity ?? left.calculatedQty) : left[sortKey];
      const rightValue = sortKey === "sourceCount" ? right.sources.length : sortKey === "calculatedQty" ? (right.replacement?.quantity ?? right.calculatedQty) : right[sortKey];
      const result = leftValue - rightValue;
      return (result || left.partNo.localeCompare(right.partNo, "zh-CN", { numeric: true })) * direction;
    });
  }, [bomLines, bomSearch, sortDirection, sortKey]);
  const confirmationGroups = useMemo(() => {
    const selectedLines = bomLines.filter((line) => line.selected);
    const mergeTargets = new Set(selectedLines.filter((line) => line.replacement?.conflictMode === "merge").map((line) => line.replacement?.partNo));
    const groups = new Map<string, {
      key: string;
      partNo: string;
      partName: string;
      quantity: number;
      unit: string;
      lines: BomLine[];
      merged: boolean;
    }>();
    selectedLines.forEach((line) => {
      const partNo = line.replacement?.partNo ?? line.partNo;
      const merged = mergeTargets.has(partNo);
      const key = merged ? `merged:${partNo}` : `${partNo}:${line.partNo}`;
      const existing = groups.get(key);
      const quantity = line.replacement?.quantity ?? line.calculatedQty;
      if (existing) {
        existing.quantity += quantity;
        existing.lines.push(line);
      } else {
        groups.set(key, {
          key,
          partNo,
          partName: line.replacement?.partName ?? line.partName,
          quantity,
          unit: line.replacement?.unit || line.unit,
          lines: [line],
          merged
        });
      }
    });
    return Array.from(groups.values());
  }, [bomLines]);
  const confirmationWarningCount = selectedBomLines.filter((line) => {
    if (!line.replacement) return false;
    const inventoryWarning = line.replacement.stockSnapshot !== null && line.replacement.quantity > line.replacement.stockSnapshot;
    const unitWarning = Boolean(line.unit && line.replacement.unit && line.unit !== line.replacement.unit);
    const sourceType = partDetails[line.partNo]?.partType ?? "";
    const typeWarning = Boolean(sourceType && line.replacement.partType && sourceType !== line.replacement.partType);
    return inventoryWarning || unitWarning || typeWarning;
  }).length;
  const modalProductItem = detailModal?.type === "product"
    ? { ...detailModal.item, ...(productDetails[detailModal.item.sku] ?? {}) }
    : null;
  const modalPartDetail = detailModal?.type === "part" ? partDetails[detailModal.line.partNo] : null;
  const replacementCandidateUnit = rawText(replacementSelected, ["unit", "單位", "单位", "計量單位", "计量单位"]);
  const replacementCandidateSpec = rawText(replacementSelected, ["specification", "規格", "规格", "零件規格", "零件规格"]);
  const replacementCandidateType = rawText(replacementSelected, ["part_type", "零件性質", "零件性质", "零件類別", "零件类别"]);
  const replacementCandidateSupply = rawText(replacementSelected, ["supply_status", "供應狀況", "供应状况", "供應狀態", "供应状态"]);
  const replacementConflicts = replacementModalLine && replacementSelected
    ? bomLines.filter((line) => line.partNo !== replacementModalLine.partNo && (line.replacement?.partNo ?? line.partNo) === replacementSelected.partNo)
    : [];
  const replacementQtyNumber = Number(replacementQty);
  const replacementStockShortage = replacementSelected?.stockSnapshot !== null && replacementSelected?.stockSnapshot !== undefined && Number.isFinite(replacementQtyNumber) && replacementQtyNumber > replacementSelected.stockSnapshot
    ? replacementQtyNumber - replacementSelected.stockSnapshot
    : 0;
  const originalPartType = replacementModalLine ? partDetails[replacementModalLine.partNo]?.partType ?? "" : "";
  const replacementUnitMismatch = Boolean(replacementModalLine?.unit && replacementCandidateUnit && replacementModalLine.unit !== replacementCandidateUnit);
  const replacementTypeMismatch = Boolean(originalPartType && replacementCandidateType && originalPartType !== replacementCandidateType);

  function updateLoadDiagnostic(id: string, patch: Partial<LoadDiagnosticEntry>) {
    setLoadDiagnostics((current) => current.map((entry) => entry.id === id ? { ...entry, ...patch } : entry));
  }

  useEffect(() => {
    const controller = new AbortController();
    const timeoutMs = 120000;
    const diagnosticId = `order-${Date.now()}`;
    const diagnosticStartedAt = Date.now();
    let orderHttpStatus: number | null = null;
    let progressTimer = 0;
    let timeoutTimer = 0;

    if (!orderId) {
      setOrder(null);
      setItems([]);
      setLoadingOrder(false);
      setPageError("URL 缺少出貨單 ID（orderId）。");
      return () => controller.abort();
    }
    if (!token) {
      setLoadingOrder(true);
      setOrderProgress(5);
      setPageError(null);
      return () => controller.abort();
    }

    setLoadingOrder(true);
    setOrderTimedOut(false);
    setOrderProgress(8);
    setPageError(null);
    setDiagnosticsOpen(false);
    setLoadDiagnostics([{
      id: diagnosticId,
      sequence: 1,
      phase: "订单读取",
      target: orderId,
      status: "running",
      startedAt: diagnosticStartedAt,
      durationMs: null,
      httpStatus: null,
      detail: "仅查询出货单、出货单明细与数量；产品资料和 BOM 暂不读取"
    }]);
    progressTimer = window.setInterval(() => {
      setOrderProgress((current) => Math.min(88, current + Math.max(2, Math.round((88 - current) / 7))));
    }, 450);
    timeoutTimer = window.setTimeout(() => {
      controller.abort();
      setOrderTimedOut(true);
      setLoadingOrder(false);
      setPageError("读取 FileMaker 超过 2 分钟，请重新加载。");
      updateLoadDiagnostic(diagnosticId, {
        status: "error",
        durationMs: timeoutMs,
        detail: "请求超过 120 秒后由前端中止，可能是 FileMaker 查询、网络或产品资料逐项补充过慢"
      });
      setDiagnosticsOpen(true);
    }, timeoutMs);

    fetch(`${apiBase}/api/orders/${encodeURIComponent(orderId)}`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        orderHttpStatus = response.status;
        if (!response.ok) throw new Error(await responseFailureDetail(response));
        return response.json() as Promise<OrderDetailResponse>;
      })
      .then((data) => {
        window.clearTimeout(timeoutTimer);
        updateLoadDiagnostic(diagnosticId, {
          status: "success",
          durationMs: Date.now() - diagnosticStartedAt,
          httpStatus: orderHttpStatus,
          detail: `读取成功：${data.items.length} 条出货单明细；未查询产品主档与 BOM`
        });
        setOrderProgress(100);
        setOrder(data.order);
        setSubmitted(Boolean(data.order.bomCalculationId));
        setSubmittedBomId(data.order.bomCalculationId || "");
        setItems(data.items.map((item) => ({ ...item, selected: true })));
        productImageObjectUrls.current.forEach((url) => URL.revokeObjectURL(url));
        productImageObjectUrls.current = [];
        setProductImages({});
        setProductImageLoading({});
        setProductDetails({});
        setProductDetailLoading({});
        setSelectionAdjustConfirmOpen(false);
        setBomLines([]);
        setPartDetails({});
        setPartImages({});
        setPartImageLoading({});
        setExpandedParts(new Set());
        window.setTimeout(() => setLoadingOrder(false), 220);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        window.clearTimeout(timeoutTimer);
        setLoadingOrder(false);
        setOrder(null);
        setItems([]);
        const message = error instanceof Error ? error.message : "订单读取失败";
        updateLoadDiagnostic(diagnosticId, {
          status: "error",
          durationMs: Date.now() - diagnosticStartedAt,
          httpStatus: orderHttpStatus,
          detail: message
        });
        setDiagnosticsOpen(true);
        setPageError(message);
      })
      .finally(() => window.clearInterval(progressTimer));

    return () => {
      controller.abort();
      window.clearInterval(progressTimer);
      window.clearTimeout(timeoutTimer);
    };
  }, [apiBase, orderId, reloadKey, token]);

  useEffect(() => {
    if (!detailModal) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setDetailModal(null);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [detailModal]);

  useEffect(() => {
    if (!replacementModalLine) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setReplacementModalLine(null);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [replacementModalLine]);

  useEffect(() => {
    if (!submitConfirmOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !submittingBom) setSubmitConfirmOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [submitConfirmOpen, submittingBom]);

  useEffect(() => {
    if (!regenerateConfirmOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setRegenerateConfirmOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [regenerateConfirmOpen]);

  useEffect(() => {
    if (!selectionAdjustConfirmOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setSelectionAdjustConfirmOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [selectionAdjustConfirmOpen]);

  useEffect(() => {
    if (!loadingOrder && !generatingBom) return;
    setDiagnosticClock(Date.now());
    const timer = window.setInterval(() => setDiagnosticClock(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [generatingBom, loadingOrder]);

  useEffect(() => {
    if (!loadingOrder && !generatingBom) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [generatingBom, loadingOrder]);

  useEffect(() => () => {
    productImageObjectUrls.current.forEach((url) => URL.revokeObjectURL(url));
    partImageObjectUrls.current.forEach((url) => URL.revokeObjectURL(url));
    document.body.classList.remove("resizing-bom-columns");
  }, []);

  async function loadProductImage(productSku: string) {
    if (!token || productImages[productSku] || productImageLoading[productSku]) return;
    setProductImageLoading((current) => ({ ...current, [productSku]: true }));
    try {
      const response = await fetch(`${apiBase}/api/orders/products/${encodeURIComponent(productSku)}/image`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(await responseFailureDetail(response));
      const objectUrl = URL.createObjectURL(await response.blob());
      productImageObjectUrls.current.push(objectUrl);
      setProductImages((current) => ({ ...current, [productSku]: objectUrl }));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "产品图片读取失败");
    } finally {
      setProductImageLoading((current) => ({ ...current, [productSku]: false }));
    }
  }

  async function loadProductDetail(item: OrderItem, loadImage = false) {
    const cached = productDetails[item.sku];
    if (cached) {
      if (loadImage && cached.hasImage) void loadProductImage(item.sku);
      return;
    }
    if (!token || productDetailLoading[item.sku]) return;
    setProductDetailLoading((current) => ({ ...current, [item.sku]: true }));
    try {
      const response = await fetch(`${apiBase}/api/orders/products/${encodeURIComponent(item.sku)}/detail`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error(await responseFailureDetail(response));
      const detail = await response.json() as ProductMasterDetail;
      setProductDetails((current) => ({ ...current, [item.sku]: detail }));
      if (loadImage && detail.hasImage) void loadProductImage(item.sku);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "产品资料读取失败");
    } finally {
      setProductDetailLoading((current) => ({ ...current, [item.sku]: false }));
    }
  }

  function openProductDetail(item: OrderItem, loadImage = false) {
    setDetailModal({ type: "product", item });
    void loadProductDetail(item, loadImage);
  }

  async function loadPartImage(partNo: string) {
    if (!token || partImages[partNo] || partImageLoading[partNo] || !partDetails[partNo]?.hasImage) return;
    setPartImageLoading((current) => ({ ...current, [partNo]: true }));
    try {
      const response = await fetch(`${apiBase}/api/orders/parts/${encodeURIComponent(partNo)}/image`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("零件图片读取失败");
      const objectUrl = URL.createObjectURL(await response.blob());
      partImageObjectUrls.current.push(objectUrl);
      setPartImages((current) => ({ ...current, [partNo]: objectUrl }));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "零件图片读取失败");
    } finally {
      setPartImageLoading((current) => ({ ...current, [partNo]: false }));
    }
  }

  function openPartDetail(line: BomLine, loadImage = false) {
    setDetailModal({ type: "part", line });
    if (loadImage) void loadPartImage(line.partNo);
  }

  function openReplacementModal(line: BomLine) {
    if (submittedBomId) return;
    setReplacementModalLine(line);
    setReplacementQuery(line.replacement?.partNo ?? "");
    setReplacementResults([]);
    setReplacementSelected(line.replacement ? {
      partNo: line.replacement.partNo,
      partName: line.replacement.partName,
      stockSnapshot: line.replacement.stockSnapshot,
      warehouse: line.replacement.warehouse,
      position1: line.replacement.position1,
      position2: line.replacement.position2,
      raw: {
        unit: line.replacement.unit,
        specification: line.replacement.specification,
        part_type: line.replacement.partType,
        supply_status: line.replacement.supplyStatus
      }
    } : null);
    setReplacementQty(String(line.replacement?.quantity ?? line.calculatedQty));
    setReplacementReason(line.replacement?.reason ?? "");
    setReplacementConflictMode(line.replacement?.conflictMode ?? null);
    setReplacementError(null);
  }

  async function searchReplacementParts() {
    const query = replacementQuery.trim();
    if (query.length < 2) {
      setReplacementError("请输入至少 2 个字符搜索零件编号或名称。");
      return;
    }
    setReplacementSearching(true);
    setReplacementError(null);
    setReplacementSelected(null);
    setReplacementConflictMode(null);
    try {
      const params = new URLSearchParams({ q: query, limit: "30" });
      const response = await fetch(`${apiBase}/api/parts/search?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("零件库搜索失败");
      const data = await response.json() as PartSearchResponse;
      setReplacementResults(data.rows);
      if (!data.rows.length) setReplacementError("零件库中没有找到匹配结果。");
    } catch (error) {
      setReplacementResults([]);
      setReplacementError(error instanceof Error ? error.message : "零件库搜索失败");
    } finally {
      setReplacementSearching(false);
    }
  }

  function applyReplacement() {
    if (!replacementModalLine) return;
    if (!replacementSelected) {
      setReplacementError("必须从零件库搜索结果中选择一个零件。");
      return;
    }
    if (replacementSelected.partNo === replacementModalLine.partNo) {
      setReplacementError("替换零件不能与原零件相同。");
      return;
    }
    const normalizedQty = replacementQty.trim();
    if (!/^\d+(\.\d{1,3})?$/.test(normalizedQty)) {
      setReplacementError("数量必须为正数，最多保留 3 位小数。");
      return;
    }
    const quantity = Number(normalizedQty);
    if (!Number.isFinite(quantity) || quantity <= 0 || quantity > 999999999) {
      setReplacementError("数量必须大于 0 且不能超过 999,999,999。");
      return;
    }
    const reason = replacementReason.trim();
    if (reason.length < 2 || reason.length > 200) {
      setReplacementError("请填写 2–200 字的替换原因。");
      return;
    }
    if (replacementConflicts.length > 0 && !replacementConflictMode) {
      setReplacementError("该替换零件已在清单中出现，请选择合并数量或保持分行。");
      return;
    }

    const replacement: PartReplacement = {
      partNo: replacementSelected.partNo,
      partName: replacementSelected.partName,
      quantity,
      stockSnapshot: replacementSelected.stockSnapshot,
      warehouse: replacementSelected.warehouse,
      position1: replacementSelected.position1,
      position2: replacementSelected.position2,
      reason,
      unit: replacementCandidateUnit,
      specification: replacementCandidateSpec,
      partType: replacementCandidateType,
      supplyStatus: replacementCandidateSupply,
      conflictMode: replacementConflicts.length > 0 ? replacementConflictMode ?? undefined : undefined
    };
    setBomLines((lines) => lines.map((line) => line.partNo === replacementModalLine.partNo ? { ...line, replacement } : line));
    if (!submittedBomId) setSubmitted(false);
    setReplacementModalLine(null);
  }

  function removeReplacement(partNo: string) {
    if (submittedBomId) return;
    setBomLines((lines) => lines.map((line) => line.partNo === partNo ? { ...line, replacement: undefined } : line));
    setSubmitted(false);
  }

  function changeSort(nextKey: BomSortKey) {
    if (nextKey === sortKey) {
      setSortDirection((current) => current === "asc" ? "desc" : "asc");
    } else {
      setSortKey(nextKey);
      setSortDirection("asc");
    }
  }

  function SortIcon({ column }: { column: BomSortKey }) {
    if (sortKey !== column) return <ArrowUpDown size={12} />;
    return sortDirection === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />;
  }

  function beginColumnResize(event: ReactPointerEvent<HTMLSpanElement>, column: BomColumnKey) {
    event.preventDefault();
    event.stopPropagation();
    bomColumnResize.current = { column, startX: event.clientX, startWidth: bomColumnWidths[column] };
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing-bom-columns");
  }

  function moveColumnResize(event: ReactPointerEvent<HTMLSpanElement>) {
    const active = bomColumnResize.current;
    if (!active) return;
    const nextWidth = Math.max(MIN_BOM_COLUMN_WIDTHS[active.column], active.startWidth + event.clientX - active.startX);
    setBomColumnWidths((current) => ({ ...current, [active.column]: Math.round(nextWidth) }));
  }

  function endColumnResize(event: ReactPointerEvent<HTMLSpanElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    bomColumnResize.current = null;
    document.body.classList.remove("resizing-bom-columns");
  }

  function resizeColumnWithKeyboard(event: ReactKeyboardEvent<HTMLSpanElement>, column: BomColumnKey) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const delta = event.key === "ArrowRight" ? 12 : -12;
    setBomColumnWidths((current) => ({
      ...current,
      [column]: Math.max(MIN_BOM_COLUMN_WIDTHS[column], current[column] + delta)
    }));
  }

  function ColumnResizeHandle({ column }: { column: BomColumnKey }) {
    return <span
      className="bom-column-resize-handle"
      role="separator"
      aria-label="调整列宽"
      aria-orientation="vertical"
      aria-valuenow={bomColumnWidths[column]}
      tabIndex={0}
      title="左右拖动调整列宽，双击恢复默认宽度"
      onPointerDown={(event) => beginColumnResize(event, column)}
      onPointerMove={moveColumnResize}
      onPointerUp={endColumnResize}
      onPointerCancel={endColumnResize}
      onKeyDown={(event) => resizeColumnWithKeyboard(event, column)}
      onDoubleClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        setBomColumnWidths((current) => ({ ...current, [column]: DEFAULT_BOM_COLUMN_WIDTHS[column] }));
      }}
    />;
  }

  function invalidatePreview(nextItems: OrderItem[]) {
    if (submittedBomId) return;
    setItems(nextItems);
    setBomLines([]);
    setPartDetails({});
    setPartImages({});
    setPartImageLoading({});
    setExpandedParts(new Set());
    setSubmitted(false);
  }

  function toggleItem(id: string) {
    if (submittedBomId) return;
    const nextItems = items.map((item) => (item.id === id ? { ...item, selected: !item.selected } : item));
    if (bomLines.length > 0) return;
    invalidatePreview(nextItems);
  }

  function toggleAllItems() {
    if (submittedBomId) return;
    const nextValue = !allItemsSelected;
    const nextItems = items.map((item) => ({ ...item, selected: nextValue }));
    if (bomLines.length > 0) return;
    invalidatePreview(nextItems);
  }

  async function generatePreview() {
    if (submittedBomId) {
      setPageError(`该订单已关联 BOM 计算单 ${submittedBomId}，不能重复生成。`);
      return;
    }
    setGeneratingBom(true);
    setBomProgress(4);
    setPageError(null);
    setDiagnosticsOpen(true);
    const diagnosticRunId = Date.now();
    const productDiagnostics: LoadDiagnosticEntry[] = selectedItems.map((item, index) => ({
      id: `bom-${diagnosticRunId}-${index}`,
      sequence: index + 1,
      phase: "产品 BOM",
      target: item.sku,
      status: "pending",
      startedAt: null,
      durationMs: null,
      httpStatus: null,
      detail: `等待读取（订单需求 ${item.quantity.toLocaleString()} ${item.unit}）`
    }));
    setLoadDiagnostics((current) => [
      ...current.filter((entry) => entry.phase === "订单读取"),
      ...productDiagnostics
    ]);
    try {
      const bomBySku: Record<string, BomDefinition[]> = {};
      for (let index = 0; index < selectedItems.length; index += 1) {
        const item = selectedItems[index];
        const diagnostic = productDiagnostics[index];
        const startedAt = Date.now();
        let responseStatus: number | null = null;
        updateLoadDiagnostic(diagnostic.id, {
          status: "running",
          startedAt,
          detail: `正在查询产品 BOM（第 ${index + 1} / ${selectedItems.length} 项）`
        });
        let data: ProductBomResponse;
        try {
          const response = await fetch(`${apiBase}/api/products/${encodeURIComponent(item.sku)}/bom-view`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          responseStatus = response.status;
          if (!response.ok) throw new Error(await responseFailureDetail(response));
          data = await response.json() as ProductBomResponse;
        } catch (error) {
          const reason = error instanceof Error ? error.message : "未知请求错误";
          updateLoadDiagnostic(diagnostic.id, {
            status: "error",
            durationMs: Date.now() - startedAt,
            httpStatus: responseStatus,
            detail: reason
          });
          setLoadDiagnostics((current) => current.map((entry) => entry.phase === "产品 BOM" && entry.status === "pending"
            ? { ...entry, status: "skipped", detail: `因 ${item.sku} 读取失败，本项未执行` }
            : entry));
          throw new Error(`产品 ${item.sku} 的 BOM 读取失败：${reason}`);
        }
        updateLoadDiagnostic(diagnostic.id, {
          status: "success",
          durationMs: Date.now() - startedAt,
          httpStatus: responseStatus,
          detail: `读取成功：${data.rows.length} 条 BOM 零件`
        });
        bomBySku[item.sku] = data.rows.map((row) => ({
          partNo: row.partNo,
          partName: row.partName,
          specification: "",
          unit: "件",
          qtyPerProduct: Number(row.requiredQty) || 0
        }));
        setBomProgress(Math.round(((index + 1) / selectedItems.length) * 92));
      }
      const nextLines = buildBomLines(items, bomBySku);
      setBomProgress(94);
      let nextPartDetails: Record<string, PartDetail> = {};
      if (nextLines.length) {
        const partDiagnosticId = `parts-${diagnosticRunId}`;
        const partStartedAt = Date.now();
        setLoadDiagnostics((current) => [...current, {
          id: partDiagnosticId,
          sequence: selectedItems.length + 1,
          phase: "零件资料",
          target: `${nextLines.length} 种零件`,
          status: "running",
          startedAt: partStartedAt,
          durationMs: null,
          httpStatus: null,
          detail: "正在批量补充零件名称、库存、状态及图片标记"
        }]);
        let partStatus: number | null = null;
        try {
          const partResponse = await fetch(`${apiBase}/api/orders/parts/details`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json"
            },
            body: JSON.stringify({ partNos: nextLines.map((line) => line.partNo) })
          });
          partStatus = partResponse.status;
          if (!partResponse.ok) throw new Error(await responseFailureDetail(partResponse));
          const partData = await partResponse.json() as PartDetailsResponse;
          nextPartDetails = Object.fromEntries(partData.rows.map((part) => [part.partNo, part]));
          updateLoadDiagnostic(partDiagnosticId, {
            status: "success",
            durationMs: Date.now() - partStartedAt,
            httpStatus: partStatus,
            detail: `补充成功：返回 ${partData.rows.length} 种零件资料`
          });
        } catch (error) {
          const reason = error instanceof Error ? error.message : "未知请求错误";
          updateLoadDiagnostic(partDiagnosticId, {
            status: "error",
            durationMs: Date.now() - partStartedAt,
            httpStatus: partStatus,
            detail: reason
          });
          setPageError(`BOM 数量已生成，但零件详细资料读取失败：${reason}`);
        }
      }
      setPartDetails(nextPartDetails);
      setBomProgress(100);
      setBomLines(nextLines);
      setExpandedParts(new Set(nextLines.filter((line) => line.sources.length > 1).map((line) => line.partNo)));
      if (!submittedBomId) setSubmitted(false);
      if (!nextLines.length) setPageError("所选产品没有可计算的 BOM 明细。");
      requestAnimationFrame(() => document.getElementById("order-bom-preview")?.scrollIntoView({ behavior: "smooth" }));
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "BOM 计算失败");
    } finally {
      window.setTimeout(() => setGeneratingBom(false), 250);
    }
  }

  function togglePart(partNo: string) {
    if (submittedBomId) return;
    setBomLines((lines) => lines.map((line) => line.partNo === partNo ? { ...line, selected: !line.selected } : line));
    setSubmitted(false);
  }

  function toggleAllBomLines() {
    if (submittedBomId) return;
    const nextValue = !allBomSelected;
    setBomLines((lines) => lines.map((line) => ({ ...line, selected: nextValue })));
    setSubmitted(false);
  }

  function toggleExpanded(partNo: string) {
    setExpandedParts((current) => {
      const next = new Set(current);
      if (next.has(partNo)) next.delete(partNo);
      else next.add(partNo);
      return next;
    });
  }

  function updateCalculatedQty(partNo: string, value: string) {
    if (submittedBomId) return;
    const quantity = Math.max(0, Number(value) || 0);
    setBomLines((lines) => lines.map((line) => line.partNo === partNo ? { ...line, calculatedQty: quantity } : line));
    setSubmitted(false);
  }

  async function submitTemporaryBom() {
    if (!bomWriteEnabled) {
      setPageError("BOM Data API 写入尚未启用，请联系管理员检查专用布局配置。");
      return;
    }
    setSubmittingBom(true);
    setPageError(null);
    try {
      const writeLines = buildBomWriteLines(bomLines);
      const requestId = `bom_${Date.now()}_${crypto.randomUUID().replace(/-/g, "")}`;
      const response = await fetch(
        `${apiBase}/api/orders/${encodeURIComponent(orderId)}/bom-calculations`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ requestId, lines: writeLines })
        }
      );
      if (!response.ok) throw new Error(await responseFailureDetail(response));
      const result = await response.json() as BomWriteResponse;
      setSubmitted(true);
      setSubmittedBomId(result.bomCalculationId);
      setOrder((current) => current
        ? { ...current, bomCalculationId: result.bomCalculationId }
        : current);
      setSubmitConfirmOpen(false);
      onSuccess?.(
        result.duplicate
          ? `订单已关联 BOM 计算单 ${result.bomCalculationId}，系统未重复创建。`
          : `BOM 计算单 ${result.bomCalculationId} 已写入 FileMaker：${result.detailCount} 条产品明细，汇总为 ${result.partCount} 种零件。`
      );
    } catch (error) {
      setSubmitConfirmOpen(false);
      setPageError(error instanceof Error ? error.message : "BOM 写入 FileMaker 失败");
    } finally {
      setSubmittingBom(false);
    }
  }

  const activeProgress = loadingOrder ? orderProgress : bomProgress;
  const loadingStageMessage = loadingOrder
    ? activeProgress < 30
      ? "正在连接 FileMaker 并定位出货单…"
      : activeProgress < 75
        ? "正在读取订单基础资料与明细产品…"
        : "正在整理产品资料，即将完成…"
    : activeProgress < 35
      ? "正在逐项读取所选产品的 BOM…"
      : activeProgress < 94
        ? "正在计算需求数量并合并共用零件…"
        : "正在补充零件库资料，即将生成清单…";

  return (
    <div className="order-detail-page">
      {(loadingOrder || generatingBom) && (
        <div className="order-loading-overlay" role="dialog" aria-modal="true" aria-live="polite" aria-labelledby="order-loading-title">
          <div className="order-progress-panel" role="status">
            <div className="order-loading-icon"><LoaderCircle className="spin" size={28} /></div>
            <div className="order-loading-heading">
              <span>{loadingOrder ? "正在加载订单" : "正在生成 BOM 临时清单"}</span>
              <h2 id="order-loading-title">{loadingOrder ? "请稍候，正在读取 FileMaker 数据" : `正在计算 ${selectedItems.length} 个产品的 BOM`}</h2>
              <p>{loadingStageMessage}</p>
            </div>
            <div className="order-progress-copy">
              <span>处理进度</span>
              <strong>{activeProgress}%</strong>
            </div>
            <div className="order-progress-track"><span style={{ width: `${activeProgress}%` }} /></div>
            {runningDiagnostic && <div className="order-loading-debug">
              <div><span>当前步骤</span><strong>{runningDiagnostic.phase} · {runningDiagnostic.target}</strong></div>
              <div><span>完成项目</span><strong>{activeOperationCompleted} / {activeOperationDiagnostics.length}</strong></div>
              <div><span>当前耗时</span><strong>{formatDiagnosticDuration(runningDiagnosticDuration)}</strong></div>
            </div>}
            <div className="order-loading-footnote">
              <strong>请不要关闭页面或重复点击</strong>
              <small>{loadingOrder ? `正在查询出貨單 ID：${orderId}；超过 2 分钟可重新加载。` : "系统正在读取各产品 BOM、汇总数量并补充零件资料。"}</small>
            </div>
          </div>
        </div>
      )}
      {pageError && (
        <div className="order-page-alert">
          <span>{pageError}</span>
          {(orderTimedOut || (!loadingOrder && !order)) && (
            <button className="btn" type="button" onClick={() => setReloadKey((current) => current + 1)}>
              <RotateCcw size={14} />重新加载
            </button>
          )}
        </div>
      )}
      {loadDiagnostics.length > 0 && <section className={failedDiagnosticCount > 0 ? "order-diagnostics-card has-error" : "order-diagnostics-card"}>
        <header className="order-diagnostics-head">
          <div><span>DEBUG</span><div><strong>加载诊断</strong><small>记录 FileMaker 查询、逐产品 BOM 与零件资料的耗时和返回结果</small></div></div>
          <div className="order-diagnostics-head-actions">
            <em>{completedDiagnosticCount} 已完成</em>
            <em className={slowDiagnosticCount ? "slow" : ""}>{slowDiagnosticCount} 慢请求</em>
            <em className={failedDiagnosticCount ? "failed" : ""}>{failedDiagnosticCount} 失败</em>
            <button type="button" onClick={() => setDiagnosticsOpen((current) => !current)}>{diagnosticsOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}{diagnosticsOpen ? "收起" : "展开详情"}</button>
          </div>
        </header>
        {diagnosticsOpen && <div className="order-diagnostics-table-scroll">
          <table className="order-diagnostics-table">
            <thead><tr><th>#</th><th>阶段</th><th>查询对象</th><th>状态</th><th>耗时</th><th>HTTP</th><th>结果 / 失败原因</th></tr></thead>
            <tbody>{loadDiagnostics.map((entry, index) => {
              const duration = entry.durationMs ?? (entry.status === "running" && entry.startedAt ? diagnosticClock - entry.startedAt : null);
              return <tr key={entry.id} className={`diagnostic-${entry.status}`}>
                <td>{index + 1}</td><td>{entry.phase}</td><td><strong>{entry.target}</strong></td>
                <td><span className={`diagnostic-status ${entry.status}`}>{entry.status === "running" && <LoaderCircle className="spin" size={11} />}{diagnosticStatusLabel(entry.status)}</span></td>
                <td className={(duration ?? 0) >= 3000 ? "diagnostic-duration slow" : "diagnostic-duration"}>{formatDiagnosticDuration(duration)}</td>
                <td>{entry.httpStatus ?? "-"}</td><td className="diagnostic-detail">{entry.detail}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>}
      </section>}
      <section className="order-overview-card">
        <div className="order-overview-main">
          <div className="order-number-block">
            <span className="order-eyebrow">内部订单单据编号</span>
            <strong>{loadingOrder ? "读取中…" : order?.internalOrderNo || "-"}</strong>
            <span className="order-status-badge"><PackageCheck size={14} /> {order?.status || "-"}</span>
          </div>
          <div className="order-field"><span>出貨單 ID</span><strong>{order?.orderId || orderId || "-"}</strong></div>
          <div className="order-field"><span>客户</span><strong>{order?.customer || "-"}</strong></div>
          <div className="order-field"><span>客户订单号</span><strong>{order?.customerPo || "-"}</strong></div>
          <div className="order-field order-pi-field"><span>PI 编号</span><strong>{order?.piNo || "-"}</strong></div>
          <div className="order-field"><span>销售负责人</span><strong>{order?.salesOwner || "-"}</strong></div>
          <div className="order-field order-note"><span>订单备注</span><strong>{order?.notes || "-"}</strong></div>
        </div>
      </section>

      <section className="card order-items-card">
        <div className="card-head order-section-head">
          <div>
            <div className="order-section-title"><span>01</span><h3>出货单明细</h3></div>
            <p>选择本次需要参与 BOM 计算的产品</p>
          </div>
          <div className="order-count-chip">已选 {selectedItems.length} / {items.length} 项</div>
        </div>
        <div className="order-table-scroll">
          <table className="order-table">
            <thead><tr>
              <th className="order-check-cell"><input type="checkbox" checked={allItemsSelected} disabled={bomLines.length > 0 || Boolean(submittedBomId)} onChange={toggleAllItems} aria-label="选择全部产品" title={submittedBomId ? `已写入 BOM 计算单 ${submittedBomId}` : bomLines.length > 0 ? "BOM 已生成，请先点击重新选择并计算" : "选择全部产品"} /></th>
              <th className="order-line-column">行号</th><th>产品编号 / 名称</th><th>规格</th><th className="numeric">订单需求</th><th>单位</th><th>计划出货</th>
            </tr></thead>
            <tbody>
              {loadingOrder && <tr className="order-empty-row"><td colSpan={7}><LoaderCircle className="spin" size={18} />正在读取 FileMaker 出貨單…</td></tr>}
              {items.map((item, index) => <tr key={item.id} className={item.selected ? "selected" : ""}>
                <td className="order-check-cell"><input type="checkbox" checked={item.selected} disabled={bomLines.length > 0 || Boolean(submittedBomId)} onChange={() => toggleItem(item.id)} aria-label={`选择 ${item.sku}`} title={submittedBomId ? `已写入 BOM 计算单 ${submittedBomId}` : bomLines.length > 0 ? "BOM 已生成，请先点击重新选择并计算" : `选择 ${item.sku}`} /></td>
                <td className="order-line-number">{String(index + 1).padStart(2, "0")}</td>
                <td><div className="order-product-cell">
                  <button className="order-product-thumb" type="button" onClick={() => openProductDetail(item, true)} aria-label={`按需加载并查看 ${item.sku} 产品资料`} title={productImages[item.sku] ? "查看产品大图" : "点击后按需读取产品资料和图片"}>
                    {productImages[item.sku] ? <img src={productImages[item.sku]} alt={item.name || productDetails[item.sku]?.englishName || item.sku} /> : productImageLoading[item.sku] || productDetailLoading[item.sku] ? <LoaderCircle className="spin" size={17} /> : <ImageIcon size={18} />}
                    <span className="order-thumb-zoom"><Maximize2 size={11} /></span>
                  </button>
                  <div className="order-product-copy">
                    <strong className="order-product-sku">{item.sku}</strong>
                    <span className="order-product-name">{item.name || "-"}</span>
                    {isDistinctDescription(item.name, productDetails[item.sku]?.englishName || item.englishName) && <span className="order-product-name-en">{productDetails[item.sku]?.englishName || item.englishName}</span>}
                  </div>
                </div></td>
                <td>{item.specification}</td>
                <td className="numeric order-demand-qty">{item.quantity.toLocaleString()}</td>
                <td>{item.unit}</td><td>{item.shipDate}</td>
              </tr>)}
              {!loadingOrder && !items.length && <tr className="order-empty-row"><td colSpan={7}>该出貨單没有明细产品</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="order-generate-bar">
          <div>
            <strong>准备计算 {selectedItems.length} 个产品</strong>
          </div>
          <div className="order-generate-actions">
            {bomLines.length > 0 && <button className="btn" type="button" disabled={Boolean(submittedBomId)} onClick={() => setSelectionAdjustConfirmOpen(true)}><RotateCcw size={16} />重新选择并计算</button>}
            <button className="btn primary order-generate-button" type="button" disabled={!selectedItems.length || generatingBom || Boolean(submittedBomId)} onClick={() => bomLines.length > 0 ? setRegenerateConfirmOpen(true) : void generatePreview()}>
              {generatingBom ? <LoaderCircle className="spin" size={17} /> : bomLines.length > 0 ? <RotateCcw size={17} /> : <Sparkles size={17} />}
              {submittedBomId ? `已写入 ${submittedBomId}` : generatingBom ? "正在计算 BOM…" : bomLines.length > 0 ? "重新生成 BOM 计算清单" : "生成 BOM 临时计算清单"}
            </button>
          </div>
        </div>
        {excludedItemsAfterCalculation.length > 0 && <div className="order-excluded-products-warning" role="status">
          <AlertTriangle size={17} />
          <div><strong>{excludedItemsAfterCalculation.length} 个产品未参与本次 BOM 计算</strong><span>{excludedItemsAfterCalculation.slice(0, 4).map((item) => item.sku).join("、")}{excludedItemsAfterCalculation.length > 4 ? ` 等 ${excludedItemsAfterCalculation.length} 个产品` : ""}。产品勾选已锁定，如需调整请点击“重新选择并计算”。</span></div>
        </div>}
      </section>

      {bomLines.length > 0 && <section id="order-bom-preview" className="card order-bom-card">
        <div className="card-head order-section-head">
          <div>
            <div className="order-section-title"><span>02</span><h3>BOM 计算清单</h3><em>{submittedBomId ? `已写入 ${submittedBomId}` : "未提交"}</em></div>
            <p>相同零件已自动合并；展开行可核对每个来源产品及计算过程</p>
          </div>
          <div className="order-bom-stats">
            <span><strong>{bomLines.length}</strong> 种零件</span>
            <span><strong>{sharedPartCount}</strong> 个共用零件</span>
          </div>
        </div>
        <div className="order-preview-notice"><Factory size={16} /><span>计算依据：订单需求数量 × 产品 BOM 单台用量。可临时更换零件，原零件与原计算数量会保留显示。</span></div>
        <div className="order-bom-toolbar">
          <label className="order-bom-search">
            <Search size={15} />
            <input type="search" value={bomSearch} onChange={(event) => setBomSearch(event.target.value)} placeholder="搜索零件编号、名称、规格或来源产品" aria-label="搜索 BOM 零件" />
            {bomSearch && <button type="button" onClick={() => setBomSearch("")} aria-label="清除搜索"><X size={14} /></button>}
          </label>
          <span>显示 {sortedBomLines.length} / {bomLines.length} 种零件</span>
        </div>
        <div className="order-table-scroll">
          <table className="order-table bom-preview-table" style={{ width: `${bomTableWidth}px` }}>
            <colgroup>
              <col style={{ width: bomColumnWidths.select }} />
              <col style={{ width: bomColumnWidths.expand }} />
              <col style={{ width: bomColumnWidths.part }} />
              <col style={{ width: bomColumnWidths.specification }} />
              <col style={{ width: bomColumnWidths.sources }} />
              <col style={{ width: bomColumnWidths.required }} />
              <col style={{ width: bomColumnWidths.calculated }} />
              <col style={{ width: bomColumnWidths.unit }} />
              <col style={{ width: bomColumnWidths.actions }} />
            </colgroup>
            <thead><tr>
              <th className="order-check-cell bom-resizable-column"><input type="checkbox" checked={allBomSelected} disabled={Boolean(submittedBomId)} onChange={toggleAllBomLines} aria-label="选择全部 BOM 零件" /><ColumnResizeHandle column="select" /></th>
              <th className="expand-cell bom-resizable-column"><ColumnResizeHandle column="expand" /></th>
              <th className="bom-resizable-column" aria-sort={sortKey === "partNo" ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}><button className="order-sort-button" type="button" onClick={() => changeSort("partNo")}>零件编号 / 名称 <SortIcon column="partNo" /></button><ColumnResizeHandle column="part" /></th>
              <th className="bom-resizable-column">规格<ColumnResizeHandle column="specification" /></th>
              <th className="bom-resizable-column" aria-sort={sortKey === "sourceCount" ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}><button className="order-sort-button" type="button" onClick={() => changeSort("sourceCount")}>来源产品 <SortIcon column="sourceCount" /></button><ColumnResizeHandle column="sources" /></th>
              <th className="numeric bom-resizable-column" aria-sort={sortKey === "requiredQty" ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}><button className="order-sort-button numeric" type="button" onClick={() => changeSort("requiredQty")}>需求数量 <SortIcon column="requiredQty" /></button><ColumnResizeHandle column="required" /></th>
              <th className="numeric calculation-column bom-resizable-column" aria-sort={sortKey === "calculatedQty" ? (sortDirection === "asc" ? "ascending" : "descending") : "none"}><button className="order-sort-button numeric" type="button" onClick={() => changeSort("calculatedQty")}>计算数量 <SortIcon column="calculatedQty" /></button><ColumnResizeHandle column="calculated" /></th>
              <th className="bom-resizable-column">单位<ColumnResizeHandle column="unit" /></th>
              <th className="bom-action-column bom-resizable-column">操作<ColumnResizeHandle column="actions" /></th>
            </tr></thead>
            <tbody>
              {sortedBomLines.map((line) => {
                const expanded = expandedParts.has(line.partNo);
                return [
                  <tr key={line.partNo} className={line.selected ? "selected" : ""}>
                    <td className="order-check-cell"><input type="checkbox" checked={line.selected} disabled={Boolean(submittedBomId)} onChange={() => togglePart(line.partNo)} aria-label={`选择 ${line.partName}`} /></td>
                    <td className="expand-cell"><button type="button" onClick={() => toggleExpanded(line.partNo)} aria-label={expanded ? "收起来源" : "展开来源"}>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button></td>
                    <td><div className={line.replacement ? "order-part-cell has-replacement" : "order-part-cell"}>
                      <button className="order-part-thumb" type="button" onClick={() => openPartDetail(line, true)} aria-label={`加载并查看 ${line.partNo} 零件图片`} title={partImages[line.partNo] ? "查看零件大图" : partDetails[line.partNo]?.hasImage ? "点击加载零件图片" : "查看零件详情"}>
                        {partImages[line.partNo] ? <img src={partImages[line.partNo]} alt={line.partName || line.partNo} /> : partImageLoading[line.partNo] ? <LoaderCircle className="spin" size={15} /> : partDetails[line.partNo]?.hasImage ? <ImageIcon size={17} /> : <PackageSearch size={17} />}
                        <span className="order-thumb-zoom"><Maximize2 size={10} /></span>
                      </button>
                      <div className="order-part-replacement-copy">
                        <button className="order-part-detail-button" type="button" onClick={() => openPartDetail(line)}>
                          {line.replacement && <span className="part-state-label original">原零件</span>}
                          <strong className="order-product-sku">{line.partNo}</strong>
                          <span className="order-product-name">{partDetails[line.partNo]?.partName || line.partName}</span>
                          {partDetails[line.partNo]?.englishName && <span className="order-product-name-en">{partDetails[line.partNo].englishName}</span>}
                        </button>
                        {line.replacement && <div className="replacement-part-summary">
                          <div><span className="part-state-label replacement">临时替换</span><strong>{line.replacement.partNo}</strong></div>
                          <span>{line.replacement.partName || "-"}</span>
                          <small title={line.replacement.reason}>原因：{line.replacement.reason}</small>
                        </div>}
                      </div>
                    </div></td>
                    <td>{line.specification}</td>
                    <td><button className={line.sources.length > 1 ? "source-count shared" : "source-count"} type="button" onClick={() => toggleExpanded(line.partNo)}>{line.sources.length} 个产品{line.sources.length > 1 && <small>共用</small>}</button></td>
                    <td className="numeric required-qty">{line.requiredQty.toLocaleString()}</td>
                    <td className="numeric calculation-column">{line.replacement ? <div className="replacement-qty-summary"><span>原计算 <s>{line.calculatedQty.toLocaleString()}</s></span><strong>{line.replacement.quantity.toLocaleString()}</strong></div> : <input className="calculated-qty-input" type="number" min="0" step="1" value={line.calculatedQty} disabled={Boolean(submittedBomId)} onChange={(event) => updateCalculatedQty(line.partNo, event.target.value)} aria-label={`${line.partName}计算数量`} />}</td>
                    <td>{line.unit}</td>
                    <td className="bom-action-column"><div className="replacement-actions">
                      <button className="replacement-button" type="button" disabled={Boolean(submittedBomId)} onClick={() => openReplacementModal(line)}><Replace size={13} />{line.replacement ? "编辑替换" : "更换零件"}</button>
                      {line.replacement && <button className="replacement-undo-button" type="button" disabled={Boolean(submittedBomId)} onClick={() => removeReplacement(line.partNo)}><Undo2 size={13} />撤销</button>}
                    </div></td>
                  </tr>,
                  expanded && <tr key={`${line.partNo}-sources`} className="bom-source-row"><td></td><td></td><td colSpan={7}>
                    <div className="bom-source-panel">
                      <div className="bom-source-title">来源产品计算明细</div>
                      <div className="bom-source-list">
                        <div className="bom-source-list-head"><span>产品编号 / 名称</span><span>订单需求</span><span>BOM 单台用量</span><span>零件需求小计</span></div>
                        {line.sources.map((source) => <div className="bom-source-item" key={source.itemId}>
                          <span><strong>{source.sku}</strong><small>{source.productName}</small></span>
                          <span>{source.orderQuantity.toLocaleString()} 台</span><span>× {source.qtyPerProduct} {line.unit}</span><span>= {source.subtotal.toLocaleString()} {line.unit}</span>
                        </div>)}
                      </div>
                    </div>
                  </td></tr>
                ];
              })}
              {sortedBomLines.length === 0 && <tr className="order-empty-row"><td colSpan={9}>没有找到匹配的 BOM 零件</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="order-submit-bar">
          <div className="order-submit-summary">
            <span>本次提交</span><strong>{selectedBomLines.length} 种零件</strong>{replacedLineCount > 0 && <><span className="order-summary-divider"></span><span>临时替换</span><strong className="replacement-count">{replacedLineCount} 项</strong></>}<span className="order-summary-divider"></span><span>计算数量合计</span><strong>{totalCalculatedQty.toLocaleString()}</strong>
          </div>
          <div className="order-submit-actions">
            <span className="local-only-note">{submittedBomId ? `已关联 FileMaker：${submittedBomId}` : bomWriteEnabled ? "确认后将实际写入 FileMaker" : "Data API 写入尚未启用"}</span>
            <button className="btn primary order-submit-button" type="button" onClick={() => setSubmitConfirmOpen(true)} disabled={!selectedBomLines.length || submitted || submittingBom || !bomWriteEnabled}>
              {submitted ? <><Check size={17} />已写入 FileMaker</> : submittingBom ? <><LoaderCircle className="spin" size={17} />写入中…</> : <><ClipboardCheck size={17} />写入 BOM 计算单</>}
            </button>
          </div>
        </div>
      </section>}

      {selectionAdjustConfirmOpen && (
        <div className="order-detail-modal-backdrop" role="presentation" onMouseDown={() => setSelectionAdjustConfirmOpen(false)}>
          <section className="order-detail-modal regenerate-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="selection-change-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="order-detail-modal-head">
              <div><span>参与产品已锁定</span><h2 id="selection-change-title">修改勾选后需要重新计算 BOM</h2></div>
              <button type="button" onClick={() => setSelectionAdjustConfirmOpen(false)} aria-label="关闭修改产品选择确认"><X size={19} /></button>
            </header>
            <div className="regenerate-confirm-body">
              <div className="regenerate-warning-icon"><AlertTriangle size={28} /></div>
              <div><h3>先清空当前 BOM，再重新选择参与产品</h3><p>确认后产品复选框会恢复可用。您可以重新勾选产品，然后点击“生成 BOM 临时计算清单”。</p></div>
              <dl className="selection-change-summary">
                <div><dt>当前参与计算</dt><dd>{selectedItems.length} 个产品</dd></div>
                <div><dt>当前未参与</dt><dd>{items.length - selectedItems.length} 个产品</dd></div>
              </dl>
              <div className="regenerate-loss-note"><strong>当前输入内容将被清空</strong><span>包含计算数量调整、零件替换、替换原因、合并方式以及 BOM 零件勾选状态。</span></div>
            </div>
            <footer className="replacement-modal-footer regenerate-confirm-footer">
              <span>点击取消将保持当前产品选择和 BOM 清单不变。</span>
              <div><button className="btn" type="button" onClick={() => setSelectionAdjustConfirmOpen(false)}>取消，保持不变</button><button className="btn danger" type="button" onClick={() => { setSelectionAdjustConfirmOpen(false); invalidatePreview(items); }}><RotateCcw size={15} />清空 BOM 并重新选择</button></div>
            </footer>
          </section>
        </div>
      )}

      {regenerateConfirmOpen && (
        <div className="order-detail-modal-backdrop" role="presentation" onMouseDown={() => setRegenerateConfirmOpen(false)}>
          <section className="order-detail-modal regenerate-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="regenerate-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="order-detail-modal-head">
              <div><span>操作确认</span><h2 id="regenerate-confirm-title">确定要重新生成 BOM 吗？</h2></div>
              <button type="button" onClick={() => setRegenerateConfirmOpen(false)} aria-label="关闭重新生成确认"><X size={19} /></button>
            </header>
            <div className="regenerate-confirm-body">
              <div className="regenerate-warning-icon"><AlertTriangle size={28} /></div>
              <div>
                <h3>当前临时清单中的修改将被清空</h3>
                <p>系统会重新读取所选产品的 BOM，并生成一份全新的计算清单。此操作暂时无法撤销。</p>
              </div>
              <dl className="regenerate-impact-list">
                <div><dt>当前 BOM 零件</dt><dd>{bomLines.length} 种</dd></div>
                <div><dt>临时替换记录</dt><dd>{bomLines.filter((line) => line.replacement).length} 项</dd></div>
                <div><dt>手动调整数量</dt><dd>{bomLines.filter((line) => line.calculatedQty !== line.requiredQty).length} 项</dd></div>
                <div><dt>已取消选择</dt><dd>{bomLines.filter((line) => !line.selected).length} 项</dd></div>
              </dl>
              <div className="regenerate-loss-note"><strong>将被清空的内容</strong><span>计算数量调整、替换零件型号、替换数量、替换原因、合并方式及零件勾选状态。</span></div>
            </div>
            <footer className="replacement-modal-footer regenerate-confirm-footer">
              <span>如需保留当前内容，请点击“取消，保留当前清单”。</span>
              <div>
                <button className="btn" type="button" onClick={() => setRegenerateConfirmOpen(false)}>取消，保留当前清单</button>
                <button className="btn danger" type="button" onClick={() => { setRegenerateConfirmOpen(false); void generatePreview(); }}><RotateCcw size={15} />确认清空并重新生成</button>
              </div>
            </footer>
          </section>
        </div>
      )}

      {replacementModalLine && (
        <div className="order-detail-modal-backdrop" role="presentation" onMouseDown={() => setReplacementModalLine(null)}>
          <section className="order-detail-modal order-replacement-modal" role="dialog" aria-modal="true" aria-labelledby="replacement-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="order-detail-modal-head">
              <div><span>BOM 临时调整</span><h2 id="replacement-modal-title">更换零件</h2></div>
              <button type="button" onClick={() => setReplacementModalLine(null)} aria-label="关闭更换零件弹窗"><X size={19} /></button>
            </header>
            <div className="replacement-modal-body">
              <section className="replacement-original-card">
                <span className="part-state-label original">原零件（保留记录）</span>
                <div className="replacement-original-main">
                  <div><strong>{replacementModalLine.partNo}</strong><span>{partDetails[replacementModalLine.partNo]?.partName || replacementModalLine.partName}</span></div>
                  <dl><div><dt>需求数量</dt><dd>{replacementModalLine.requiredQty.toLocaleString()} {replacementModalLine.unit}</dd></div><div><dt>原计算数量</dt><dd>{replacementModalLine.calculatedQty.toLocaleString()} {replacementModalLine.unit}</dd></div></dl>
                </div>
              </section>

              <section className="replacement-search-section">
                <div className="replacement-section-title"><div><strong>1. 从零件库选择替换型号</strong><span>不能手动输入零件编号，必须从搜索结果中选择</span></div></div>
                <form className="replacement-search-form" onSubmit={(event) => { event.preventDefault(); void searchReplacementParts(); }}>
                  <label><Search size={16} /><input autoFocus type="search" value={replacementQuery} onChange={(event) => { setReplacementQuery(event.target.value); setReplacementSelected(null); setReplacementConflictMode(null); setReplacementError(null); }} placeholder="输入零件编号或名称（至少 2 个字符）" aria-label="搜索零件库" /></label>
                  <button className="btn" type="submit" disabled={replacementSearching}>{replacementSearching ? <LoaderCircle className="spin" size={15} /> : <Search size={15} />}{replacementSearching ? "搜索中…" : "搜索零件库"}</button>
                </form>
                {replacementResults.length > 0 && <div className="replacement-result-list" role="listbox" aria-label="零件库搜索结果">
                  {replacementResults.map((part) => {
                    const isOriginal = part.partNo === replacementModalLine.partNo;
                    const selected = replacementSelected?.partNo === part.partNo;
                    return <button key={part.partNo} className={selected ? "replacement-result selected" : "replacement-result"} type="button" disabled={isOriginal} onClick={() => { setReplacementSelected(part); setReplacementConflictMode(null); setReplacementError(null); }} role="option" aria-selected={selected}>
                      <span className="replacement-result-check">{selected ? <Check size={15} /> : null}</span>
                      <span className="replacement-result-main"><strong>{part.partNo}</strong><span>{part.partName || "未命名零件"}</span></span>
                      <span className="replacement-result-meta"><small>库存 {part.stockSnapshot?.toLocaleString() ?? "-"}</small><small>{rawText(part, ["供應狀況", "供应状况", "supply_status"]) || "供应状态未标注"}</small><small>{rawText(part, ["單位", "单位", "unit"]) || "单位未标注"}</small><small>{part.warehouse || "仓库未标注"}</small><small>{[part.position1, part.position2].filter(Boolean).join(" / ") || "位置未标注"}</small></span>
                      {isOriginal && <em>原零件，不可选择</em>}
                    </button>;
                  })}
                </div>}
                {replacementSelected && <div className="replacement-selected-card"><Check size={16} /><div><span>已从零件库选择</span><strong>{replacementSelected.partNo} · {replacementSelected.partName || "未命名零件"}</strong><small>单位 {replacementCandidateUnit || "未标注"} · 规格 {replacementCandidateSpec || "未标注"} · 性质 {replacementCandidateType || "未标注"} · {replacementCandidateSupply || "供应状态未标注"}</small></div></div>}
                {replacementSelected && (replacementUnitMismatch || replacementTypeMismatch) && <div className="replacement-warning compatibility"><AlertTriangle size={17} /><div><strong>规格兼容性提醒</strong>{replacementUnitMismatch && <span>单位不同：原零件 {replacementModalLine.unit}，替换零件 {replacementCandidateUnit}</span>}{replacementTypeMismatch && <span>零件性质不同：原零件 {originalPartType}，替换零件 {replacementCandidateType}</span>}<small>请确认替换后仍适用于该产品。</small></div></div>}
                {replacementSelected && replacementConflicts.length > 0 && <div className="replacement-conflict-card">
                  <div className="replacement-warning conflict"><AlertTriangle size={17} /><div><strong>替换冲突：{replacementSelected.partNo} 已在清单中出现</strong><span>{replacementConflicts.map((line) => line.partNo).join("、")} 当前也使用这个零件，请选择处理方式。</span></div></div>
                  <div className="replacement-conflict-options">
                    <button className={replacementConflictMode === "merge" ? "selected" : ""} type="button" onClick={() => { setReplacementConflictMode("merge"); setReplacementError(null); }}><strong>自动合并数量</strong><span>确认清单按同一型号汇总，同时保留每个原零件来源</span></button>
                    <button className={replacementConflictMode === "separate" ? "selected" : ""} type="button" onClick={() => { setReplacementConflictMode("separate"); setReplacementError(null); }}><strong>保持分行</strong><span>型号相同但仍按原 BOM 行分别列出</span></button>
                  </div>
                </div>}
              </section>

              <section className="replacement-input-section">
                <div className="replacement-section-title"><div><strong>2. 填写替换数量与原因</strong><span>数量与原因均为必填项</span></div></div>
                <div className="replacement-fields">
                  <label><span>替换数量 <em>*</em></span><div className="replacement-qty-field"><input type="text" inputMode="decimal" value={replacementQty} onChange={(event) => { setReplacementQty(event.target.value); setReplacementError(null); }} placeholder="大于 0" aria-label="替换数量" /><b>{replacementModalLine.unit}</b></div><small>最多 3 位小数，上限 999,999,999</small></label>
                  <label><span>替换原因 <em>*</em></span><div className="replacement-reason-templates">{REPLACEMENT_REASON_TEMPLATES.map((reason) => <button key={reason} className={replacementReason === reason ? "selected" : ""} type="button" onClick={() => { setReplacementReason(reason === "其他" ? "" : reason); setReplacementError(null); }}>{reason}</button>)}</div><textarea value={replacementReason} onChange={(event) => { setReplacementReason(event.target.value); setReplacementError(null); }} maxLength={200} rows={3} placeholder="请选择常用原因或补充说明（2–200 字）" aria-label="替换原因" /><small>{replacementReason.trim().length} / 200 字</small></label>
                </div>
                {replacementSelected && replacementStockShortage > 0 && <div className="replacement-warning stock"><AlertTriangle size={17} /><div><strong>库存不足，缺口 {replacementStockShortage.toLocaleString()} {replacementModalLine.unit}</strong><span>当前库存 {replacementSelected.stockSnapshot?.toLocaleString()}，替换需求 {replacementQtyNumber.toLocaleString()}；仍可继续，但请确认采购或补货安排。</span></div></div>}
              </section>

              {replacementError && <div className="replacement-validation-error" role="alert">{replacementError}</div>}
            </div>
            <footer className="replacement-modal-footer">
              <span>本次调整会随最终 BOM 计算单一起写入 FileMaker</span>
              <div><button className="btn" type="button" onClick={() => setReplacementModalLine(null)}>取消</button><button className="btn primary" type="button" onClick={applyReplacement}><Check size={15} />确认临时替换</button></div>
            </footer>
          </section>
        </div>
      )}

      {submitConfirmOpen && (
        <div className="order-detail-modal-backdrop" role="presentation" onMouseDown={() => { if (!submittingBom) setSubmitConfirmOpen(false); }}>
          <section className="order-detail-modal order-submit-confirm-modal" role="dialog" aria-modal="true" aria-labelledby="submit-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="order-detail-modal-head">
              <div><span>最终核对</span><h2 id="submit-confirm-title">确认写入 BOM 计算单</h2></div>
              <button type="button" disabled={submittingBom} onClick={() => setSubmitConfirmOpen(false)} aria-label="关闭提交确认"><X size={19} /></button>
            </header>
            <div className="submit-confirm-body">
              <div className="submit-confirm-overview">
                <div><span>内部订单</span><strong>{order?.internalOrderNo || "-"}</strong></div>
                <div><span>提交型号</span><strong>{confirmationGroups.length} 种</strong></div>
                <div><span>临时替换</span><strong>{replacedLineCount} 项</strong></div>
                <div className={confirmationWarningCount ? "has-warning" : ""}><span>需留意</span><strong>{confirmationWarningCount} 项</strong></div>
              </div>
              {confirmationWarningCount > 0 && <div className="replacement-warning stock"><AlertTriangle size={17} /><div><strong>清单中仍有库存或兼容性提醒</strong><span>系统允许继续确认，请再次核对下方替换记录。</span></div></div>}
              <div className="submit-confirm-list">
                {confirmationGroups.map((group) => <section className="submit-confirm-group" key={group.key}>
                  <header><div><strong>{group.partNo}</strong><span>{group.partName || "-"}</span></div><div><strong>{group.quantity.toLocaleString()} {group.unit}</strong>{group.merged && <em>已合并 {group.lines.length} 个来源</em>}</div></header>
                  {group.lines.map((line) => <div className={line.replacement ? "submit-confirm-line replaced" : "submit-confirm-line"} key={line.partNo}>
                    <span className="submit-confirm-original"><small>原零件</small><strong>{line.partNo}</strong><span>{line.partName}</span></span>
                    <span className="submit-confirm-arrow">→</span>
                    <span className="submit-confirm-final"><small>{line.replacement ? "替换后" : "保持原零件"}</small><strong>{line.replacement?.partNo ?? line.partNo}</strong><span>{(line.replacement?.quantity ?? line.calculatedQty).toLocaleString()} {line.replacement?.unit || line.unit}</span></span>
                    <span className="submit-confirm-difference"><small>数量变化</small><strong>{line.replacement ? `${line.replacement.quantity - line.calculatedQty >= 0 ? "+" : ""}${(line.replacement.quantity - line.calculatedQty).toLocaleString()}` : "0"}</strong></span>
                    <span className="submit-confirm-reason"><small>替换原因</small><strong>{line.replacement?.reason || "—"}</strong></span>
                  </div>)}
                </section>)}
              </div>
              <div className="submit-confirm-audit"><span>操作人：{operatorName || operatorAccount || "-"}</span><span>账号：{operatorAccount || "-"}</span><span>确认时间：{new Date().toLocaleString("zh-CN", { hour12: false })}</span></div>
            </div>
            <footer className="replacement-modal-footer">
              <span>确认后会创建计算单、逐产品明细和零件汇总，并回填出货单关联</span>
              <div><button className="btn" type="button" disabled={submittingBom} onClick={() => setSubmitConfirmOpen(false)}>返回修改</button><button className="btn primary" type="button" disabled={submittingBom} onClick={() => void submitTemporaryBom()}>{submittingBom ? <LoaderCircle className="spin" size={15} /> : <ClipboardCheck size={15} />}{submittingBom ? "正在写入…" : "确认写入 FileMaker"}</button></div>
            </footer>
          </section>
        </div>
      )}

      {detailModal && (
        <div className="order-detail-modal-backdrop" role="presentation" onMouseDown={() => setDetailModal(null)}>
          <section className="order-detail-modal" role="dialog" aria-modal="true" aria-labelledby="order-detail-modal-title" onMouseDown={(event) => event.stopPropagation()}>
            <header className="order-detail-modal-head">
              <div>
                <span>{detailModal.type === "product" ? "订单产品" : "BOM 零件"}</span>
                <h2 id="order-detail-modal-title">{detailModal.type === "product" ? "产品详细资料" : "零件计算明细"}</h2>
              </div>
              <button type="button" onClick={() => setDetailModal(null)} aria-label="关闭详情"><X size={19} /></button>
            </header>

            {detailModal.type === "product" ? (
              <div className="order-product-modal-body">
                <div className="order-product-modal-image">
                  {productImages[detailModal.item.sku] ? (
                    <img src={productImages[detailModal.item.sku]} alt={modalProductItem?.name || modalProductItem?.englishName || detailModal.item.sku} />
                  ) : productDetailLoading[detailModal.item.sku] ? (
                    <button className="order-modal-image-load" type="button" disabled><LoaderCircle className="spin" size={30} /><span>正在读取产品资料…</span><small>首次进入订单时不会预先查询产品主档</small></button>
                  ) : modalProductItem?.hasImage ? (
                    <button className="order-modal-image-load" type="button" onClick={() => void loadProductImage(detailModal.item.sku)} disabled={productImageLoading[detailModal.item.sku]}>
                      {productImageLoading[detailModal.item.sku] ? <LoaderCircle className="spin" size={30} /> : <ImageIcon size={34} />}
                      <span>{productImageLoading[detailModal.item.sku] ? "正在下载产品图片…" : "点击加载产品图片"}</span>
                      <small>仅在需要查看时下载</small>
                    </button>
                  ) : !productDetails[detailModal.item.sku] ? (
                    <button className="order-modal-image-load" type="button" onClick={() => void loadProductDetail(detailModal.item, true)}><ImageIcon size={34} /><span>重新读取产品资料</span><small>产品主档加载失败或尚未读取</small></button>
                  ) : (
                    <div className="order-modal-image-empty"><ImageIcon size={34} /><span>暂无产品图片</span></div>
                  )}
                </div>
                <div className="order-modal-details">
                  <div className="order-modal-product-title">
                    <strong>{modalProductItem?.sku || detailModal.item.sku}</strong>
                    <h3>{modalProductItem?.name || detailModal.item.name || "-"}</h3>
                    {isDistinctDescription(modalProductItem?.name || detailModal.item.name, modalProductItem?.englishName || "") && <p>{modalProductItem?.englishName}</p>}
                  </div>
                  <dl className="order-modal-data-grid">
                    <div><dt>系统产品编号</dt><dd>{modalProductItem?.systemProductSku || detailModal.item.sku}</dd></div>
                    <div><dt>Client</dt><dd>{modalProductItem?.client || "-"}</dd></div>
                    <div><dt>类别</dt><dd>{modalProductItem?.category || "-"}</dd></div>
                    <div><dt>比例</dt><dd>{modalProductItem?.scale || "-"}</dd></div>
                    <div><dt>审核状态</dt><dd>{modalProductItem?.auditStatus || "-"}</dd></div>
                    <div><dt>库存状态</dt><dd>{modalProductItem?.availability || "-"}</dd></div>
                    <div><dt>当前库存</dt><dd>{productDetails[detailModal.item.sku] ? modalProductItem?.stock.toLocaleString() : "-"}</dd></div>
                    <div><dt>MOQ</dt><dd>{productDetails[detailModal.item.sku] ? modalProductItem?.moq.toLocaleString() : "-"}</dd></div>
                    <div>
                      <dt>产品单价</dt>
                      <dd>
                        {canViewPrice
                          ? modalProductItem?.unitPrice
                            ? `$${modalProductItem.unitPrice.toLocaleString()}`
                            : "-"
                          : "无查看权限"}
                      </dd>
                    </div>
                    <div><dt>BOM 零件数</dt><dd>{productDetails[detailModal.item.sku] ? modalProductItem?.bomCount.toLocaleString() : "-"}</dd></div>
                    <div><dt>BOM 日期</dt><dd>{modalProductItem?.bomDate || "-"}</dd></div>
                    <div><dt>BOM 厂商</dt><dd>{modalProductItem?.vendor || "-"}</dd></div>
                    <div><dt>条形码</dt><dd>{modalProductItem?.barcode || "-"}</dd></div>
                    <div><dt>标签规格</dt><dd>{modalProductItem?.labelSpec || "-"}</dd></div>
                    <div className="order-modal-data-wide"><dt>销售记录</dt><dd>{modalProductItem?.salesNotes || "-"}</dd></div>
                  </dl>
                </div>
              </div>
            ) : (
              <div className="order-part-modal-body">
                <div className="order-part-modal-overview">
                  <div className="order-part-modal-image">
                    {partImages[detailModal.line.partNo] ? (
                      <img src={partImages[detailModal.line.partNo]} alt={modalPartDetail?.partName || detailModal.line.partName} />
                    ) : modalPartDetail?.hasImage ? (
                      <button className="order-modal-image-load" type="button" onClick={() => void loadPartImage(detailModal.line.partNo)} disabled={partImageLoading[detailModal.line.partNo]}>
                        {partImageLoading[detailModal.line.partNo] ? <LoaderCircle className="spin" size={30} /> : <ImageIcon size={34} />}
                        <span>{partImageLoading[detailModal.line.partNo] ? "正在下载零件图片…" : "点击加载零件图片"}</span>
                        <small>仅在需要查看时下载</small>
                      </button>
                    ) : (
                      <div className="order-modal-image-empty"><PackageSearch size={34} /><span>暂无零件图片</span></div>
                    )}
                  </div>
                  <div>
                    <div className="order-part-modal-summary">
                      <div className="order-part-modal-icon"><PackageSearch size={24} /></div>
                      <div><strong>{detailModal.line.partNo}</strong><h3>{modalPartDetail?.partName || detailModal.line.partName}</h3><p>{modalPartDetail?.englishName || modalPartDetail?.externalName || "暂无英文名称"}</p></div>
                    </div>
                    <dl className="order-modal-data-grid part-master-data-grid">
                      <div><dt>当前库存</dt><dd>{modalPartDetail?.stock.toLocaleString() ?? "-"}</dd></div>
                      <div><dt>供应状态</dt><dd>{modalPartDetail?.supplyStatus || "-"}</dd></div>
                      <div><dt>零件状态</dt><dd>{modalPartDetail?.status || "-"}</dd></div>
                      <div><dt>审核状态</dt><dd>{modalPartDetail?.auditStatus || "-"}</dd></div>
                      <div><dt>零件性质</dt><dd>{modalPartDetail?.partType || "-"}</dd></div>
                      <div><dt>供应商</dt><dd>{modalPartDetail?.supplier || "-"}</dd></div>
                      <div><dt>采购员</dt><dd>{modalPartDetail?.buyer || "-"}</dd></div>
                      <div><dt>专属客户</dt><dd>{modalPartDetail?.customer || "-"}</dd></div>
                      <div><dt>仓库分工</dt><dd>{modalPartDetail?.warehouseDivision || "-"}</dd></div>
                      <div><dt>部门分工</dt><dd>{modalPartDetail?.department || "-"}</dd></div>
                      <div><dt>周转时间</dt><dd>{modalPartDetail?.turnoverTime ? `${modalPartDetail.turnoverTime} 天` : "-"}</dd></div>
                      <div><dt>位置</dt><dd>{[modalPartDetail?.position1, modalPartDetail?.position2].filter(Boolean).join(" / ") || "-"}</dd></div>
                    </dl>
                  </div>
                </div>
                <dl className="order-modal-data-grid part-data-grid">
                  <div><dt>需求数量</dt><dd>{detailModal.line.requiredQty.toLocaleString()} {detailModal.line.unit}</dd></div>
                  <div><dt>计算数量</dt><dd>{detailModal.line.calculatedQty.toLocaleString()} {detailModal.line.unit}</dd></div>
                  <div><dt>来源产品</dt><dd>{detailModal.line.sources.length} 个</dd></div>
                  <div><dt>是否共用</dt><dd>{detailModal.line.sources.length > 1 ? "共用零件" : "单一产品"}</dd></div>
                </dl>
                <div className="order-part-modal-sources">
                  <h4>来源产品与计算过程</h4>
                  {detailModal.line.sources.map((source) => (
                    <div className="order-part-modal-source" key={source.itemId}>
                      <span><strong>{source.sku}</strong><small>{source.productName}</small></span>
                      <span>{source.orderQuantity.toLocaleString()} × {source.qtyPerProduct}</span>
                      <strong>{source.subtotal.toLocaleString()} {detailModal.line.unit}</strong>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

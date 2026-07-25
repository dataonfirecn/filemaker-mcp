import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent as ReactFormEvent, PointerEvent as ReactPointerEvent } from "react";
import {
  ArrowDown,
  ArrowDownAZ,
  ArrowLeft,
  ArrowUp,
  ArrowUpAZ,
  BarChart3,
  Bot,
  Boxes,
  CheckCircle2,
  ChevronsUpDown,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  FileText,
  FileSpreadsheet,
  GripVertical,
  History,
  Home,
  Eye,
  EyeOff,
  ImageIcon,
  Loader2,
  KeyRound,
  LockKeyhole,
  LogOut,
  Mail,
  Moon,
  PackageSearch,
  Palette,
  Pencil,
  Search,
  SendHorizontal,
  Settings,
  ShieldCheck,
  Sun,
  Power,
  RefreshCw,
  RotateCcw,
  ShoppingCart,
  Trash2,
  UserPlus,
  Wrench,
  Users,
  X,
  ZoomIn,
  ZoomOut
} from "lucide-react";
import type { ThemeMode } from "../types";
import {
  ApiError,
  customerAccessRolePermissions,
  normalizeCustomerAdminAccount,
  requestAsset,
  requestJson,
  type CustomerBomLine,
  type CustomerCatalogPage,
  type CustomerCatalogOrder,
  type CustomerCatalogPart,
  type CustomerCatalogProduct,
  type CustomerOrderSummary,
  type CustomerChatHistoryResponse,
  type CustomerAccessRole,
  type CustomerAccountBulkStatusResponse,
  type CustomerAdminAccount,
  type CustomerAdminAccountsResponse,
  type CustomerOrderQueryRow,
  type CustomerPartDetail,
  type CustomerProductDetail,
  type CustomerPasswordChangeResponse,
  type CustomerProfile,
  type CustomerQueryResponse,
  type CustomerQuestionSummaryResponse
} from "./customerPortalApi";

type PortalRoute =
  | { page: "home" }
  | { page: "orders" }
  | { page: "products" }
  | { page: "product-detail"; recordId: string }
  | { page: "parts" }
  | { page: "part-detail"; recordId: string }
  | { page: "admin-analytics" }
  | { page: "admin-accounts" }
  | { page: "settings-appearance" }
  | { page: "change-password" };

type OrderShippingStatusFilter = "all" | "shipped" | "notShipped";

type CustomerPortalContentProps = {
  token: string;
  profile: CustomerProfile;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  onSessionRenewed: (response: CustomerPasswordChangeResponse) => void;
  onLogout: (message?: string) => void;
};

const homeSuggestions = [
  "View order history",
  "Orders shipped this month",
  "Check inventory for PT-Tent-MYK01",
  "Check inventory for MYB0377-24",
  "View product list",
  "View part list"
];

function routeFromPath(pathname = window.location.pathname): PortalRoute {
  const productMatch = pathname.match(/^\/customer-chat\/products\/(\d+)$/);
  if (productMatch) return { page: "product-detail", recordId: productMatch[1] };
  const partMatch = pathname.match(/^\/customer-chat\/parts\/(\d+)$/);
  if (partMatch) return { page: "part-detail", recordId: partMatch[1] };
  if (pathname === "/customer-chat/products") return { page: "products" };
  if (pathname === "/customer-chat/parts") return { page: "parts" };
  if (pathname === "/customer-chat/orders") return { page: "orders" };
  if (pathname === "/customer-chat/admin/analytics") return { page: "admin-analytics" };
  if (pathname === "/customer-chat/admin/accounts") return { page: "admin-accounts" };
  if (pathname === "/customer-chat/settings" || pathname === "/customer-chat/settings/appearance") {
    return { page: "settings-appearance" };
  }
  if (pathname === "/customer-chat/account/password" || pathname === "/customer-chat/settings/password") {
    return { page: "change-password" };
  }
  return { page: "home" };
}

function pathForRoute(route: PortalRoute): string {
  if (route.page === "orders") return "/customer-chat/orders";
  if (route.page === "products") return "/customer-chat/products";
  if (route.page === "parts") return "/customer-chat/parts";
  if (route.page === "product-detail") return `/customer-chat/products/${route.recordId}`;
  if (route.page === "part-detail") return `/customer-chat/parts/${route.recordId}`;
  if (route.page === "admin-analytics") return "/customer-chat/admin/analytics";
  if (route.page === "admin-accounts") return "/customer-chat/admin/accounts";
  if (route.page === "settings-appearance") return "/customer-chat/settings/appearance";
  if (route.page === "change-password") return "/customer-chat/settings/password";
  return "/customer-chat";
}

function displayValue(value: number | string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function displayCurrency(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = typeof value === "number" ? value : Number(String(value).replace(/[$,]/g, ""));
  if (!Number.isFinite(numeric)) return String(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  }).format(numeric);
}

function numericValue(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
  return Number.isFinite(numeric) ? numeric : null;
}

function StockBadge({ value, verbose = false }: { value: number | string | null | undefined; verbose?: boolean }) {
  const numeric = numericValue(value);
  if (numeric === null) return <>—</>;
  const level = numeric <= 0 ? "out" : numeric < 10 ? "low" : "in";
  const formatted = numeric.toLocaleString("en-US");
  const label = verbose
    ? numeric <= 0 ? "Out of stock" : numeric < 10 ? `Low · ${formatted} left` : `${formatted} in stock`
    : formatted;
  return <span className={`cp-stock-badge ${level}`}>{label}</span>;
}

function AccountAvatar({
  initial,
  isAdmin,
  className = ""
}: {
  initial: string;
  isAdmin: boolean;
  className?: string;
}) {
  return (
    <span className={`cp-avatar-wrap ${className}`.trim()}>
      <span className="cp-avatar" aria-hidden="true">{initial}</span>
      {isAdmin && (
        <span
          className="cp-avatar-admin-badge"
          aria-label="Administrator account"
          title="Administrator account"
        >
          <ShieldCheck size={10} aria-hidden="true" />
        </span>
      )}
    </span>
  );
}

function timeStamp(): string {
  return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function OrderChatResult({ order }: { order: CustomerOrderQueryRow }) {
  return (
    <div className="cp-order-chat-item">
      <div className="cp-order-chat-top">
        <span className="cp-order-chat-icon"><FileText size={17} /></span>
        <div>
          <strong>{order.orderNumber || "Order"}</strong>
          <small>{order.clientName || "Mayako"}</small>
        </div>
        <span className="cp-order-chat-date">{order.shippedDate || order.shippingStatus || "Date pending"}</span>
      </div>
      <div className="cp-order-chat-meta">
        <span>Amount <b>{displayCurrency(order.orderAmount)}</b></span>
        <span>Shipping <b>{order.shippingCompany || "—"}</b></span>
        <span>Tracking <b>{order.trackingNumber || "—"}</b></span>
        <span>Cost <b>{displayCurrency(order.shippingCost)}</b></span>
        <span>Status <b>{order.shippingStatus || "—"}</b></span>
      </div>
      {order.remarks && <p>{order.remarks}</p>}
    </div>
  );
}

function visiblePages(current: number, total: number): number[] {
  const start = Math.max(1, Math.min(current - 2, total - 4));
  const end = Math.min(total, start + 4);
  return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
}

type CustomerTableColumn = {
  id: string;
  label: string;
  width: number;
  minWidth: number;
  sortKey?: string;
  numeric?: boolean;
  centered?: boolean;
};

type CustomerTableLayout = {
  order: string[];
  widths: Record<string, number>;
};

const PRODUCT_COLUMNS: CustomerTableColumn[] = [
  { id: "image", label: "Image", width: 82, minWidth: 72 },
  { id: "productSku", label: "Product No.", width: 170, minWidth: 120, sortKey: "productSku" },
  { id: "productName", label: "Product Name", width: 280, minWidth: 160, sortKey: "productName" },
  { id: "modelName", label: "Model", width: 150, minWidth: 100, sortKey: "modelName" },
  { id: "scale", label: "Scale", width: 90, minWidth: 74, sortKey: "scale" },
  { id: "category", label: "Category", width: 135, minWidth: 95, sortKey: "category" },
  { id: "stock", label: "Inventory", width: 105, minWidth: 85, sortKey: "stock", numeric: true },
  { id: "bomCount", label: "BOM", width: 84, minWidth: 68, sortKey: "bomCount", numeric: true },
  { id: "actions", label: "", width: 92, minWidth: 82 }
];

const PART_COLUMNS: CustomerTableColumn[] = [
  { id: "image", label: "Image", width: 82, minWidth: 72 },
  { id: "partNumber", label: "Part No.", width: 190, minWidth: 130, sortKey: "partNumber" },
  { id: "partName", label: "Part Name", width: 330, minWidth: 180, sortKey: "partName" },
  { id: "status", label: "Status", width: 145, minWidth: 100, sortKey: "status" },
  { id: "stock", label: "Inventory", width: 115, minWidth: 90, sortKey: "stock", numeric: true },
  { id: "actions", label: "", width: 92, minWidth: 82 }
];

const ORDER_COLUMNS: CustomerTableColumn[] = [
  { id: "clientName", label: "Client", width: 155, minWidth: 120 },
  { id: "orderNumber", label: "Order #", width: 210, minWidth: 150, sortKey: "orderNumber" },
  { id: "orderAmount", label: "Order Amount", width: 135, minWidth: 115, sortKey: "orderAmount", numeric: true },
  { id: "shippingCompany", label: "Shipping", width: 145, minWidth: 110, sortKey: "shippingCompany", centered: true },
  { id: "trackingNumber", label: "Tracking", width: 170, minWidth: 140, sortKey: "trackingNumber" },
  { id: "shippingCost", label: "Shipping Cost", width: 120, minWidth: 110, numeric: true },
  { id: "shippingStatus", label: "Status", width: 130, minWidth: 110, centered: true },
  { id: "shippedDate", label: "Shipped Date", width: 130, minWidth: 120, sortKey: "shippedDate", centered: true },
  { id: "remarks", label: "Remarks", width: 390, minWidth: 220 }
];

const BOM_COLUMNS: CustomerTableColumn[] = [
  { id: "bomQuantity", label: "BOM Qty", width: 105, minWidth: 82, sortKey: "bomQuantity", numeric: true },
  { id: "clientPartNumber", label: "Client No.", width: 140, minWidth: 100, sortKey: "clientPartNumber" },
  { id: "partNumber", label: "Part No.", width: 165, minWidth: 115, sortKey: "partNumber" },
  { id: "partName", label: "Part Name", width: 250, minWidth: 150, sortKey: "partName" },
  { id: "requiredQuantity", label: "Required", width: 110, minWidth: 84, sortKey: "requiredQuantity", numeric: true },
  { id: "stock", label: "Part Inventory", width: 125, minWidth: 95, sortKey: "stock", numeric: true },
  { id: "status", label: "Status", width: 130, minWidth: 95, sortKey: "status" },
  { id: "sparePartNumber", label: "Spare Part", width: 155, minWidth: 110, sortKey: "sparePartNumber" },
  { id: "spareStock", label: "Spare Inventory", width: 135, minWidth: 105, sortKey: "spareStock", numeric: true }
];

const RELATED_PRODUCT_COLUMNS: CustomerTableColumn[] = [
  { id: "productSku", label: "Product No.", width: 220, minWidth: 145, sortKey: "productSku" },
  { id: "productName", label: "Product Name", width: 520, minWidth: 220, sortKey: "productName" },
  { id: "actions", label: "", width: 130, minWidth: 110 }
];

function defaultTableLayout(columns: CustomerTableColumn[]): CustomerTableLayout {
  return {
    order: columns.map((column) => column.id),
    widths: Object.fromEntries(columns.map((column) => [column.id, column.width]))
  };
}

function loadTableLayout(storageKey: string, columns: CustomerTableColumn[]): CustomerTableLayout {
  const fallback = defaultTableLayout(columns);
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return fallback;
    const stored = JSON.parse(raw) as Partial<CustomerTableLayout>;
    const validIds = new Set(columns.map((column) => column.id));
    const storedOrder = Array.isArray(stored.order)
      ? stored.order.filter((id): id is string => typeof id === "string" && validIds.has(id))
      : [];
    const order = [...storedOrder, ...fallback.order.filter((id) => !storedOrder.includes(id))];
    const widths = { ...fallback.widths };
    for (const column of columns) {
      const width = stored.widths?.[column.id];
      if (typeof width === "number" && Number.isFinite(width)) widths[column.id] = Math.max(column.minWidth, width);
    }
    return { order, widths };
  } catch {
    return fallback;
  }
}

function useCustomerTableLayout(storageKey: string, definitions: CustomerTableColumn[]) {
  const [layout, setLayout] = useState<CustomerTableLayout>(() => loadTableLayout(storageKey, definitions));

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(layout));
    } catch {
      // The table remains usable when browser storage is unavailable.
    }
  }, [layout, storageKey]);

  const byId = new Map(definitions.map((column) => [column.id, column]));
  const columns = layout.order.map((id) => byId.get(id)).filter((column): column is CustomerTableColumn => Boolean(column));
  const totalWidth = columns.reduce((sum, column) => sum + (layout.widths[column.id] ?? column.width), 0);

  function resizeColumn(id: string, width: number) {
    const column = byId.get(id);
    if (!column) return;
    setLayout((current) => ({ ...current, widths: { ...current.widths, [id]: Math.max(column.minWidth, Math.round(width)) } }));
  }

  function moveColumn(sourceId: string, targetId: string) {
    if (sourceId === targetId) return;
    setLayout((current) => {
      const order = current.order.filter((id) => id !== sourceId);
      const targetIndex = order.indexOf(targetId);
      order.splice(targetIndex < 0 ? order.length : targetIndex, 0, sourceId);
      return { ...current, order };
    });
  }

  function resetColumns() {
    setLayout(defaultTableLayout(definitions));
  }

  return { columns, widths: layout.widths, totalWidth, resizeColumn, moveColumn, resetColumns };
}

function CustomerTableHeader({
  columns,
  widths,
  sortBy,
  sortOrder,
  onSort,
  onResize,
  onMove
}: {
  columns: CustomerTableColumn[];
  widths: Record<string, number>;
  sortBy: string;
  sortOrder: "asc" | "desc";
  onSort: (sortKey: string) => void;
  onResize: (id: string, width: number) => void;
  onMove: (sourceId: string, targetId: string) => void;
}) {
  const [draggedColumn, setDraggedColumn] = useState("");
  const [dropTarget, setDropTarget] = useState("");

  function startResize(event: ReactPointerEvent<HTMLSpanElement>, column: CustomerTableColumn) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = widths[column.id] ?? column.width;
    document.body.classList.add("resizing-customer-columns");
    const handleMove = (moveEvent: PointerEvent) => onResize(column.id, startWidth + moveEvent.clientX - startX);
    const handleUp = () => {
      document.body.classList.remove("resizing-customer-columns");
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  }

  return (
    <thead>
      <tr>
        {columns.map((column) => {
          const activeSort = Boolean(column.sortKey && column.sortKey === sortBy);
          return (
            <th
              key={column.id}
              className={`${column.numeric ? "cp-num " : ""}${column.centered ? "cp-center " : ""}${dropTarget === column.id ? "cp-drop-target" : ""}`}
              draggable
              onDragStart={(event) => {
                setDraggedColumn(column.id);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", column.id);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                setDropTarget(column.id);
              }}
              onDragLeave={() => setDropTarget((current) => current === column.id ? "" : current)}
              onDrop={(event) => {
                event.preventDefault();
                const sourceId = event.dataTransfer.getData("text/plain") || draggedColumn;
                if (sourceId) onMove(sourceId, column.id);
                setDraggedColumn("");
                setDropTarget("");
              }}
              onDragEnd={() => { setDraggedColumn(""); setDropTarget(""); }}
              aria-sort={activeSort ? (sortOrder === "asc" ? "ascending" : "descending") : undefined}
            >
              <div className="cp-col-head">
                <GripVertical className="cp-col-grip" size={13} aria-hidden="true" />
                {column.sortKey ? (
                  <button className={activeSort ? "cp-sorted" : ""} type="button" onClick={() => onSort(column.sortKey!)} title={`Sort by ${column.label}`}>
                    <span>{column.label}</span>
                    {activeSort ? (sortOrder === "asc" ? <ArrowUp size={13} /> : <ArrowDown size={13} />) : <ChevronsUpDown size={13} />}
                  </button>
                ) : <span>{column.label}</span>}
              </div>
              <span
                className="cp-col-resize"
                role="separator"
                aria-label={`Resize ${column.label || "column"}`}
                onPointerDown={(event) => startResize(event, column)}
              />
            </th>
          );
        })}
      </tr>
    </thead>
  );
}

function tableStyle(totalWidth: number) {
  return { width: `max(100%, ${totalWidth}px)` };
}

function compareTableValues(left: unknown, right: unknown): number {
  if (left === null || left === undefined || left === "") return right === null || right === undefined || right === "" ? 0 : 1;
  if (right === null || right === undefined || right === "") return -1;
  const leftText = String(left).trim();
  const rightText = String(right).trim();
  const leftNumber = Number(leftText.replace(/,/g, ""));
  const rightNumber = Number(rightText.replace(/,/g, ""));
  if (leftText && rightText && Number.isFinite(leftNumber) && Number.isFinite(rightNumber)) return leftNumber - rightNumber;
  return leftText.localeCompare(rightText, "en", { numeric: true, sensitivity: "base" });
}

function bomValue(line: CustomerBomLine, columnId: string) {
  return line[columnId as keyof CustomerBomLine];
}

function AssetButton({
  token,
  path,
  alt,
  large = false,
  onUnauthorized
}: {
  token: string;
  path: string;
  alt: string;
  large?: boolean;
  onUnauthorized: () => void;
}) {
  const [state, setState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [url, setUrl] = useState("");
  const [contentType, setContentType] = useState("");
  const [lightboxOpen, setLightboxOpen] = useState(false);

  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  async function load() {
    if (state === "loading") return;
    setState("loading");
    try {
      const blob = await requestAsset(path, token);
      const nextUrl = URL.createObjectURL(blob);
      setUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return nextUrl;
      });
      setContentType(blob.type);
      setState("loaded");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onUnauthorized();
        return;
      }
      setState("error");
    }
  }

  if (state === "loaded" && url) {
    if (contentType === "application/pdf") {
      return (
        <a className={`cp-asset-pdf ${large ? "large" : ""}`} href={url} target="_blank" rel="noreferrer">
          <FileText size={large ? 24 : 15} />
          <span>Open PDF</span>
        </a>
      );
    }
    return (
      <>
        <button className={`cp-asset-image ${large ? "large" : ""}`} type="button" onClick={() => setLightboxOpen(true)} aria-label={`Enlarge image: ${alt}`} title="Click to enlarge">
          <img src={url} alt={alt} />
        </button>
        {lightboxOpen && <ImageLightbox url={url} alt={alt} onClose={() => setLightboxOpen(false)} />}
      </>
    );
  }

  return (
    <button className={`cp-asset-load ${large ? "large" : ""}`} type="button" onClick={() => void load()} disabled={state === "loading"}>
      {state === "loading" ? <Loader2 className="spin" size={large ? 24 : 15} /> : <ImageIcon size={large ? 24 : 15} />}
      <span>{state === "error" ? "Retry" : large ? "Load image" : "View"}</span>
    </button>
  );
}

function ImageLightbox({ url, alt, onClose }: { url: string; alt: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKey);
    };
  }, [onClose]);

  const zoomIn = () => setZoom((current) => Math.min(5, Math.round((current + 0.25) * 100) / 100));
  const zoomOut = () => setZoom((current) => Math.max(0.25, Math.round((current - 0.25) * 100) / 100));

  return (
    <div
      className="cp-lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={`Image preview: ${alt}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="cp-lightbox-toolbar">
        <button type="button" onClick={zoomOut} disabled={zoom <= 0.25} aria-label="Zoom out"><ZoomOut size={16} /></button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" onClick={zoomIn} disabled={zoom >= 5} aria-label="Zoom in"><ZoomIn size={16} /></button>
        <button type="button" onClick={() => setZoom(1)}>Fit</button>
        <button className="cp-lightbox-close" type="button" onClick={onClose} aria-label="Close image preview"><X size={17} /></button>
      </div>
      <div className="cp-lightbox-stage">
        <img src={url} alt={alt} style={{ maxWidth: `${zoom * 88}vw`, maxHeight: `${zoom * 82}vh` }} draggable={false} />
      </div>
    </div>
  );
}

function TableThumb({ hasImage, token, path, alt, onUnauthorized }: { hasImage: boolean; token: string; path: string; alt: string; onUnauthorized: () => void }) {
  return (
    <div className="cp-thumb">
      {hasImage ? <AssetButton token={token} path={path} alt={alt} onUnauthorized={onUnauthorized} /> : <ImageIcon size={16} />}
    </div>
  );
}

function ProductImageGallery({
  token,
  product,
  images,
  onUnauthorized
}: {
  token: string;
  product: CustomerProductDetail["product"];
  images: CustomerProductDetail["images"];
  onUnauthorized: () => void;
}) {
  return (
    <section className="cp-product-gallery" aria-labelledby="product-gallery-title">
      <div className="cp-section-head">
        <h2 id="product-gallery-title">Product Images</h2>
        <span>{images.length ? `${images.length} image${images.length === 1 ? "" : "s"} · Click an image to load it` : "No customer-visible images"}</span>
      </div>
      {images.length > 0 && (
        <div className="cp-product-gallery-grid">
          {images.map((image, index) => {
            const label = image.title || `Image ${index + 1}`;
            return (
              <article className="cp-product-gallery-card" key={image.assetRef}>
                <div className="cp-product-gallery-media">
                  <AssetButton
                    large
                    token={token}
                    path={`/api/customer-chat/products/${product.productRef}/images/${image.assetRef}`}
                    alt={`${product.productName || product.productSku} · ${label}`}
                    onUnauthorized={onUnauthorized}
                  />
                </div>
                <div className="cp-product-gallery-caption">
                  <strong>{label}</strong>
                  <span>{image.isPrimary ? "Primary image" : `Image ${image.sortOrder || index + 1}`}</span>
                  {image.filename && <small title={image.filename}>{image.filename}</small>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function CustomerPortalContent({
  token,
  profile,
  theme,
  onThemeChange,
  onSessionRenewed,
  onLogout
}: CustomerPortalContentProps) {
  const [route, setRoute] = useState<PortalRoute>(() => routeFromPath());
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const accountMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePopState = () => setRoute(routeFromPath());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!accountMenuOpen) return;
    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (!accountMenuRef.current?.contains(event.target as Node)) setAccountMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountMenuOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [accountMenuOpen]);

  function navigate(nextRoute: PortalRoute) {
    const path = pathForRoute(nextRoute);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setAccountMenuOpen(false);
    setRoute(nextRoute);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const activeSection = route.page === "settings-appearance" || route.page === "change-password"
    ? "account"
    : route.page === "admin-analytics"
    ? "admin"
    : route.page === "admin-accounts"
    ? "accounts"
    : route.page === "orders"
    ? "orders"
    : route.page.startsWith("product")
      ? "products"
      : route.page.startsWith("part") ? "parts" : "home";
  const sessionExpired = () => onLogout("Your session has expired. Please sign in again.");
  const avatarInitial = (profile.displayName || profile.username || "?").trim().charAt(0).toUpperCase() || "?";

  return (
    <main className="cp-root">
      <header className="cp-topbar">
        <button className="cp-brand" type="button" onClick={() => navigate({ page: "home" })}>
          <span className="cp-brand-mark" aria-hidden="true"><PackageSearch size={18} /></span>
          <span><strong>Customer Portal</strong><small>Orders, Products &amp; Parts</small></span>
        </button>
        <nav className="cp-nav" aria-label="Customer portal">
          <button className={activeSection === "home" ? "active" : ""} type="button" onClick={() => navigate({ page: "home" })}>
            <Home size={15} /><span>Home</span>
          </button>
          {profile.canViewOrders && (
            <button className={activeSection === "orders" ? "active" : ""} type="button" onClick={() => navigate({ page: "orders" })}>
              <ShoppingCart size={15} /><span>Orders</span>
            </button>
          )}
          <button className={activeSection === "products" ? "active" : ""} type="button" onClick={() => navigate({ page: "products" })}>
            <Boxes size={15} /><span>Products</span>
          </button>
          <button className={activeSection === "parts" ? "active" : ""} type="button" onClick={() => navigate({ page: "parts" })}>
            <Wrench size={15} /><span>Parts</span>
          </button>
          {profile.isAdmin && (
            <>
              <button className={activeSection === "admin" ? "active" : ""} type="button" onClick={() => navigate({ page: "admin-analytics" })}>
                <BarChart3 size={15} /><span>Chat analytics</span>
              </button>
              <button className={activeSection === "accounts" ? "active" : ""} type="button" onClick={() => navigate({ page: "admin-accounts" })}>
                <Users size={15} /><span>Accounts</span>
              </button>
            </>
          )}
        </nav>
        <div className="cp-topbar-right">
          <div className="cp-account-menu-wrap" ref={accountMenuRef}>
            <button
              className={`cp-account-button ${activeSection === "account" || accountMenuOpen ? "active" : ""}`}
              type="button"
              onClick={() => setAccountMenuOpen((current) => !current)}
              aria-haspopup="menu"
              aria-expanded={accountMenuOpen}
              aria-controls="customer-account-menu"
            >
              <AccountAvatar initial={avatarInitial} isAdmin={profile.isAdmin} />
              <span className="cp-user-name">{profile.displayName}</span>
              <ChevronDown className="cp-account-chevron" size={15} aria-hidden="true" />
            </button>
            {accountMenuOpen && (
              <div className="cp-account-menu" id="customer-account-menu" role="menu" aria-label="Account menu">
                <div className="cp-account-menu-head">
                  <AccountAvatar initial={avatarInitial} isAdmin={profile.isAdmin} />
                  <span>
                    <strong>{profile.displayName}</strong>
                    <small>{profile.username}</small>
                  </span>
                </div>
                <div className="cp-account-menu-divider" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAccountMenuOpen(false);
                    navigate({ page: "settings-appearance" });
                  }}
                >
                  <Settings size={16} aria-hidden="true" />
                  <span>Settings</span>
                </button>
                <div className="cp-account-menu-divider" />
                <button
                  className="cp-account-menu-danger"
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAccountMenuOpen(false);
                    onLogout();
                  }}
                >
                  <LogOut size={16} aria-hidden="true" />
                  <span>Sign out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div
        className={[
          "cp-main",
          route.page === "orders" || route.page.startsWith("admin-") ? "cp-main-wide" : "",
          route.page === "settings-appearance" || route.page === "change-password" ? "cp-main-settings" : ""
        ].filter(Boolean).join(" ")}
      >
        {route.page === "home" && (
          <CustomerHome token={token} profile={profile} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "orders" && profile.canViewOrders && (
          <OrdersPage token={token} canViewPrice={profile.canViewPrice} onUnauthorized={sessionExpired} />
        )}
        {route.page === "orders" && !profile.canViewOrders && (
          <CustomerHome token={token} profile={profile} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "products" && (
          <CatalogPage key="products" kind="product" token={token} canViewDetails={profile.canViewDetails} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "parts" && (
          <CatalogPage key="parts" kind="part" token={token} canViewDetails={profile.canViewDetails} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "product-detail" && profile.canViewDetails && (
          <ProductDetailPage
            token={token}
            recordId={route.recordId}
            canViewPrice={profile.canViewPrice}
            onNavigate={navigate}
            onUnauthorized={sessionExpired}
          />
        )}
        {route.page === "part-detail" && profile.canViewDetails && (
          <PartDetailPage token={token} recordId={route.recordId} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {(route.page === "product-detail" || route.page === "part-detail") && !profile.canViewDetails && (
          <CustomerHome token={token} profile={profile} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "admin-analytics" && profile.isAdmin && (
          <AdminChatAnalyticsPage token={token} onUnauthorized={sessionExpired} />
        )}
        {route.page === "admin-analytics" && !profile.isAdmin && (
          <CustomerHome token={token} profile={profile} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {route.page === "admin-accounts" && profile.isAdmin && (
          <AdminAccountsPage
            token={token}
            currentUsername={profile.username}
            onUnauthorized={sessionExpired}
          />
        )}
        {route.page === "admin-accounts" && !profile.isAdmin && (
          <CustomerHome token={token} profile={profile} onNavigate={navigate} onUnauthorized={sessionExpired} />
        )}
        {(route.page === "settings-appearance" || route.page === "change-password") && (
          <SettingsPage
            activeSection={route.page === "settings-appearance" ? "appearance" : "password"}
            token={token}
            profile={profile}
            theme={theme}
            onThemeChange={onThemeChange}
            onSessionRenewed={onSessionRenewed}
            onUnauthorized={sessionExpired}
            onNavigate={navigate}
          />
        )}
      </div>
    </main>
  );
}

type SettingsSection = "appearance" | "password";

function SettingsPage({
  activeSection,
  token,
  profile,
  theme,
  onThemeChange,
  onSessionRenewed,
  onUnauthorized,
  onNavigate
}: {
  activeSection: SettingsSection;
  token: string;
  profile: CustomerProfile;
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
  onSessionRenewed: (response: CustomerPasswordChangeResponse) => void;
  onUnauthorized: () => void;
  onNavigate: (route: PortalRoute) => void;
}) {
  const avatarInitial = (profile.displayName || profile.username || "?").trim().charAt(0).toUpperCase() || "?";

  return (
    <section className="cp-settings-page" aria-labelledby="settings-page-title">
      <aside className="cp-settings-sidebar">
        <div className="cp-settings-profile">
          <AccountAvatar initial={avatarInitial} isAdmin={profile.isAdmin} className="cp-settings-avatar" />
          <span>
            <strong>{profile.displayName}</strong>
            <small>{profile.username}</small>
          </span>
        </div>

        <nav className="cp-settings-nav" aria-label="Settings navigation">
          <div className="cp-settings-nav-group">
            <span>Personal settings</span>
            <button
              className={activeSection === "appearance" ? "active" : ""}
              type="button"
              onClick={() => onNavigate({ page: "settings-appearance" })}
              aria-current={activeSection === "appearance" ? "page" : undefined}
            >
              <Palette size={16} aria-hidden="true" />
              <span>Appearance</span>
            </button>
          </div>
          <div className="cp-settings-nav-group">
            <span>Access</span>
            <button
              className={activeSection === "password" ? "active" : ""}
              type="button"
              onClick={() => onNavigate({ page: "change-password" })}
              aria-current={activeSection === "password" ? "page" : undefined}
            >
              <ShieldCheck size={16} aria-hidden="true" />
              <span>Password and authentication</span>
            </button>
          </div>
        </nav>
      </aside>

      <div className="cp-settings-detail">
        {activeSection === "appearance" ? (
          <AppearanceSettings theme={theme} onThemeChange={onThemeChange} />
        ) : (
          <ChangePasswordPage
            token={token}
            username={profile.username}
            onSessionRenewed={onSessionRenewed}
            onUnauthorized={onUnauthorized}
          />
        )}
      </div>
    </section>
  );
}

function AppearanceSettings({
  theme,
  onThemeChange
}: {
  theme: ThemeMode;
  onThemeChange: (theme: ThemeMode) => void;
}) {
  const options: { id: ThemeMode; label: string; description: string; Icon: typeof Sun }[] = [
    {
      id: "light",
      label: "Light",
      description: "A bright interface for daylight and well-lit spaces.",
      Icon: Sun
    },
    {
      id: "dark",
      label: "Dark",
      description: "A dimmed interface that is easier on the eyes at night.",
      Icon: Moon
    }
  ];

  return (
    <>
      <header className="cp-settings-content-head">
        <span className="cp-eyebrow">Personal settings</span>
        <h1 id="settings-page-title">Appearance</h1>
        <p>Choose how the customer portal looks on this device.</p>
      </header>

      <section className="cp-settings-section" aria-labelledby="appearance-theme-title">
        <div className="cp-settings-section-head">
          <div>
            <h2 id="appearance-theme-title">Theme</h2>
            <p>Select the color mode you want to use.</p>
          </div>
          <span className="cp-settings-save-state">Saved automatically</span>
        </div>

        <div className="cp-theme-options" role="radiogroup" aria-label="Color mode">
          {options.map(({ id, label, description, Icon }) => {
            const selected = theme === id;
            return (
              <button
                key={id}
                className={`cp-theme-option ${selected ? "selected" : ""}`}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => onThemeChange(id)}
              >
                <span className="cp-theme-option-icon" aria-hidden="true"><Icon size={21} /></span>
                <span className="cp-theme-option-copy">
                  <strong>{label}</strong>
                  <small>{description}</small>
                </span>
                <span className="cp-theme-option-check" aria-hidden="true">
                  {selected && <CheckCircle2 size={19} />}
                </span>
              </button>
            );
          })}
        </div>
      </section>
    </>
  );
}

function PasswordInput({
  label,
  value,
  autoComplete,
  placeholder,
  disabled,
  onChange
}: {
  label: string;
  value: string;
  autoComplete: "current-password" | "new-password";
  placeholder: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <label className="cp-field">
      <span>{label}</span>
      <span className="cp-control">
        <LockKeyhole size={17} />
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          disabled={disabled}
          maxLength={200}
        />
        <button
          className="cp-eye"
          type="button"
          onClick={() => setVisible((current) => !current)}
          aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          title={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </span>
    </label>
  );
}

function ChangePasswordPage({
  token,
  username,
  onSessionRenewed,
  onUnauthorized
}: {
  token: string;
  username: string;
  onSessionRenewed: (response: CustomerPasswordChangeResponse) => void;
  onUnauthorized: () => void;
}) {
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    if (!oldPassword || !newPassword || !confirmNewPassword) {
      setError("Complete all three password fields.");
      return;
    }
    if (newPassword.length < 12) {
      setError("The new password must contain at least 12 characters.");
      return;
    }
    if (newPassword !== confirmNewPassword) {
      setError("The two new passwords do not match.");
      return;
    }
    if (oldPassword === newPassword) {
      setError("The new password must be different from the current password.");
      return;
    }

    setLoading(true);
    try {
      const response = await requestJson<CustomerPasswordChangeResponse>(
        "/api/customer-chat/change-password",
        {
          method: "POST",
          body: JSON.stringify({ oldPassword, newPassword, confirmNewPassword })
        },
        token
      );
      onSessionRenewed(response);
      setOldPassword("");
      setNewPassword("");
      setConfirmNewPassword("");
      setSuccess(response.message);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "The password could not be changed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <header className="cp-settings-content-head">
        <span className="cp-eyebrow">Access</span>
        <h1 id="settings-page-title">Password and authentication</h1>
        <p>Update the password used to sign in to this customer portal.</p>
      </header>
      <section className="cp-account-card cp-settings-account-card">
        <div className="cp-account-heading">
          <span className="cp-account-icon"><KeyRound size={24} /></span>
          <div>
            <div className="cp-eyebrow">Account security</div>
            <h2>Change password</h2>
            <p>Signed in as <strong>{username}</strong></p>
          </div>
        </div>
        <form onSubmit={submit}>
          <PasswordInput
            label="Current password"
            value={oldPassword}
            onChange={setOldPassword}
            autoComplete="current-password"
            placeholder="Enter your current password"
            disabled={loading}
          />
          <PasswordInput
            label="New password"
            value={newPassword}
            onChange={setNewPassword}
            autoComplete="new-password"
            placeholder="At least 12 characters"
            disabled={loading}
          />
          <PasswordInput
            label="Confirm new password"
            value={confirmNewPassword}
            onChange={setConfirmNewPassword}
            autoComplete="new-password"
            placeholder="Enter the new password again"
            disabled={loading}
          />
          <p className="cp-password-hint">Use at least 12 characters. Your new password must be different from the current one.</p>
          {error && <div className="cp-login-error" role="alert">{error}</div>}
          {success && <div className="cp-password-success" role="status"><CheckCircle2 size={17} /> {success}</div>}
          <button className="cp-btn-primary" type="submit" disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : <KeyRound size={17} />}
            {loading ? "Changing password…" : "Change password"}
          </button>
        </form>
      </section>
    </>
  );
}

type CustomerAccountDraft = {
  username: string;
  displayName: string;
  email: string;
  password: string;
  enabled: boolean;
  accessRole: CustomerAccessRole;
  sendCredentials: boolean;
};

const customerAccessRoles: Array<{
  value: CustomerAccessRole;
  label: string;
  description: string;
}> = [
  { value: "admin", label: "Admin", description: "Full access to content, prices, orders, accounts, and analytics" },
  { value: "manager", label: "Manager", description: "Products, details, prices, and all orders; no account administration" },
  { value: "team", label: "Team member", description: "Products, details, and orders with all prices and totals hidden" },
  { value: "agent", label: "Agent", description: "Inventory lookup only; no order, detail, or price access" }
];

function generateTemporaryPassword(): string {
  const groups = [
    "ABCDEFGHJKLMNPQRSTUVWXYZ",
    "abcdefghijkmnopqrstuvwxyz",
    "23456789",
    "!@#$%&*+-_?"
  ];
  const all = groups.join("");
  const randomIndex = (length: number) => {
    const value = new Uint32Array(1);
    crypto.getRandomValues(value);
    return value[0] % length;
  };
  const characters = groups.map((group) => group[randomIndex(group.length)]);
  while (characters.length < 12) characters.push(all[randomIndex(all.length)]);
  for (let index = characters.length - 1; index > 0; index -= 1) {
    const swapIndex = randomIndex(index + 1);
    [characters[index], characters[swapIndex]] = [characters[swapIndex], characters[index]];
  }
  return characters.join("");
}

function newCustomerAccountDraft(sendCredentials = false): CustomerAccountDraft {
  return {
    username: "",
    displayName: "",
    email: "",
    password: generateTemporaryPassword(),
    enabled: true,
    accessRole: "team",
    sendCredentials
  };
}

function accountDraft(account: CustomerAdminAccount): CustomerAccountDraft {
  return {
    username: account.username,
    displayName: account.displayName,
    email: account.email,
    password: "",
    enabled: account.enabled,
    accessRole: account.accessRole,
    sendCredentials: false
  };
}

function accountUpdatePayload(
  account: CustomerAdminAccount,
  overrides: Partial<CustomerAccountDraft> = {}
) {
  const accessRole = overrides.accessRole ?? account.accessRole;
  const permissions = customerAccessRolePermissions(accessRole);
  const email = overrides.email ?? account.email;
  return {
    displayName: overrides.displayName ?? account.displayName,
    ...(email ? { email } : {}),
    enabled: overrides.enabled ?? account.enabled,
    accessRole,
    canViewPrice: permissions.canViewPrice,
    isAdmin: permissions.isAdmin,
    newPassword: overrides.password || null,
    sendCredentials: overrides.sendCredentials ?? false
  };
}

function AdminAccountsPage({
  token,
  currentUsername,
  onUnauthorized
}: {
  token: string;
  currentUsername: string;
  onUnauthorized: () => void;
}) {
  const [accounts, setAccounts] = useState<CustomerAdminAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingUsername, setSavingUsername] = useState("");
  const [editor, setEditor] = useState<{ mode: "create" | "edit"; draft: CustomerAccountDraft } | null>(null);
  const [deletingAccount, setDeletingAccount] = useState<CustomerAdminAccount | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [clipboardNotice, setClipboardNotice] = useState("");
  const [emailDeliveryEnabled, setEmailDeliveryEnabled] = useState(false);
  const [selectedUsernames, setSelectedUsernames] = useState<string[]>([]);
  const [bulkAction, setBulkAction] = useState<"" | "enable" | "disable">("");
  const [bulkActionMenuOpen, setBulkActionMenuOpen] = useState(false);
  const [bulkStatusOpen, setBulkStatusOpen] = useState(false);
  const [bulkUpdating, setBulkUpdating] = useState(false);
  const bulkActionMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void requestJson<CustomerAdminAccountsResponse>("/api/customer-chat/admin/accounts", {}, token)
      .then((result) => {
        if (!active) return;
        setAccounts(result.accounts.map(normalizeCustomerAdminAccount));
        setEmailDeliveryEnabled(result.emailDeliveryEnabled);
      })
      .catch((requestError) => {
        if (!active) return;
        if (requestError instanceof ApiError && requestError.status === 401) {
          onUnauthorized();
          return;
        }
        setError(requestError instanceof Error ? requestError.message : "Accounts could not be loaded.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [onUnauthorized, token]);

  useEffect(() => {
    if (!bulkActionMenuOpen) return;
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!bulkActionMenuRef.current?.contains(event.target as Node)) {
        setBulkActionMenuOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBulkActionMenuOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [bulkActionMenuOpen]);

  function handleRequestError(requestError: unknown, fallback: string) {
    if (requestError instanceof ApiError && requestError.status === 401) {
      onUnauthorized();
      return;
    }
    setError(requestError instanceof Error ? requestError.message : fallback);
  }

  function openCreateEditor() {
    setClipboardNotice("");
    setEditor({
      mode: "create",
      draft: newCustomerAccountDraft(emailDeliveryEnabled)
    });
  }

  async function copyEditorCredentials() {
    if (!editor?.draft.username.trim() || !editor.draft.password) {
      setClipboardNotice("Enter a username and generate a password first.");
      return;
    }
    const text = `Username: ${editor.draft.username.trim()}\nTemporary password: ${editor.draft.password}`;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand("copy");
        textarea.remove();
      }
      setClipboardNotice("Username and temporary password copied.");
    } catch {
      setClipboardNotice("Could not copy. Select the credentials and copy them manually.");
    }
  }

  async function updateAccount(account: CustomerAdminAccount, overrides: Partial<CustomerAccountDraft>) {
    setSavingUsername(account.username);
    setError("");
    setNotice("");
    try {
      const response = await requestJson<CustomerAdminAccount>(
        `/api/customer-chat/admin/accounts/${encodeURIComponent(account.username)}`,
        { method: "PATCH", body: JSON.stringify(accountUpdatePayload(account, overrides)) },
        token
      );
      const updated = normalizeCustomerAdminAccount(response);
      setAccounts((current) => current.map((item) => item.username === updated.username ? updated : item));
      setNotice(`${updated.displayName} was updated.`);
      if (updated.username.toLocaleLowerCase() === currentUsername.toLocaleLowerCase()) {
        onUnauthorized();
      }
    } catch (requestError) {
      handleRequestError(requestError, "The account could not be updated.");
    } finally {
      setSavingUsername("");
    }
  }

  async function saveEditor(event: ReactFormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      const isCreate = editor.mode === "create";
      const permissions = customerAccessRolePermissions(editor.draft.accessRole);
      const previousAccount = accounts.find((account) => account.username === editor.draft.username);
      const path = isCreate
        ? "/api/customer-chat/admin/accounts"
        : `/api/customer-chat/admin/accounts/${encodeURIComponent(editor.draft.username)}`;
      const body = isCreate
        ? {
            ...editor.draft,
            username: editor.draft.username.trim(),
            password: editor.draft.password,
            canViewPrice: permissions.canViewPrice,
            isAdmin: permissions.isAdmin
          }
        : {
            displayName: editor.draft.displayName,
            email: editor.draft.email,
            enabled: editor.draft.enabled,
            accessRole: editor.draft.accessRole,
            canViewPrice: permissions.canViewPrice,
            isAdmin: permissions.isAdmin,
            newPassword: editor.draft.password || null,
            sendCredentials: editor.draft.sendCredentials
          };
      const response = await requestJson<CustomerAdminAccount>(
        path,
        { method: isCreate ? "POST" : "PATCH", body: JSON.stringify(body) },
        token
      );
      const saved = normalizeCustomerAdminAccount(response);
      setAccounts((current) => (
        isCreate
          ? [...current, saved].sort((left, right) => left.username.localeCompare(right.username))
          : current.map((item) => item.username === saved.username ? saved : item)
      ));
      setEditor(null);
      if (saved.credentialsEmailSent === true) {
        setNotice(`${saved.displayName} was ${isCreate ? "created" : "updated"} and the login email was sent.`);
      } else {
        setNotice(`${saved.displayName} was ${isCreate ? "created" : "updated"}.`);
      }
      if (saved.credentialsEmailSent === false) {
        setError(`The account was saved, but the login email was not sent. ${saved.credentialsEmailError || "Please check the SMTP configuration."}`);
      }
      const currentSessionChanged = previousAccount && (
        previousAccount.displayName !== saved.displayName ||
        previousAccount.accessRole !== saved.accessRole ||
        Boolean(editor.draft.password)
      );
      if (
        !isCreate &&
        currentSessionChanged &&
        saved.username.toLocaleLowerCase() === currentUsername.toLocaleLowerCase()
      ) {
        onUnauthorized();
      }
    } catch (requestError) {
      handleRequestError(requestError, "The account could not be saved.");
    } finally {
      setSubmitting(false);
    }
  }

  async function deleteAccount() {
    if (!deletingAccount) return;
    setSubmitting(true);
    setError("");
    setNotice("");
    try {
      await requestJson<void>(
        `/api/customer-chat/admin/accounts/${encodeURIComponent(deletingAccount.username)}`,
        { method: "DELETE" },
        token
      );
      setAccounts((current) => current.filter((account) => account.username !== deletingAccount.username));
      setSelectedUsernames((current) => current.filter((username) => username !== deletingAccount.username));
      setNotice(`${deletingAccount.displayName} was deleted.`);
      setDeletingAccount(null);
    } catch (requestError) {
      handleRequestError(requestError, "The account could not be deleted.");
    } finally {
      setSubmitting(false);
    }
  }

  const bulkEligibleAccounts = accounts.filter(
    (account) => account.username.toLocaleLowerCase() !== currentUsername.toLocaleLowerCase()
  );
  const selectedSet = new Set(selectedUsernames);
  const selectedAccounts = bulkEligibleAccounts.filter((account) => selectedSet.has(account.username));
  const canEnableSelected = selectedAccounts.some((account) => !account.enabled);
  const canDisableSelected = selectedAccounts.some((account) => account.enabled);
  const allEligibleSelected = bulkEligibleAccounts.length > 0
    && bulkEligibleAccounts.every((account) => selectedSet.has(account.username));

  function toggleAccountSelection(username: string) {
    setSelectedUsernames((current) => (
      current.includes(username)
        ? current.filter((item) => item !== username)
        : [...current, username]
    ));
  }

  function toggleAllEligibleAccounts() {
    setSelectedUsernames(
      allEligibleSelected
        ? []
        : bulkEligibleAccounts.map((account) => account.username)
    );
  }

  async function bulkUpdateAccountStatus() {
    if (selectedUsernames.length === 0 || !bulkAction) return;
    const enabled = bulkAction === "enable";
    setBulkUpdating(true);
    setError("");
    setNotice("");
    try {
      const response = await requestJson<CustomerAccountBulkStatusResponse>(
        "/api/customer-chat/admin/accounts/bulk-status",
        {
          method: "POST",
          body: JSON.stringify({ usernames: selectedUsernames, enabled })
        },
        token
      );
      const updatedAccounts = response.accounts.map(normalizeCustomerAdminAccount);
      const updatedByUsername = new Map(updatedAccounts.map((account) => [account.username, account]));
      setAccounts((current) => current.map((account) => updatedByUsername.get(account.username) ?? account));
      setSelectedUsernames([]);
      setBulkAction("");
      setBulkActionMenuOpen(false);
      setBulkStatusOpen(false);
      const action = enabled ? "enabled" : "disabled";
      setNotice(`${response.updatedCount} ${response.updatedCount === 1 ? "account was" : "accounts were"} ${action}.`);
    } catch (requestError) {
      handleRequestError(requestError, "The selected accounts could not be updated.");
    } finally {
      setBulkUpdating(false);
    }
  }

  const bulkActionLabel = bulkAction === "enable"
    ? "Enable selected"
    : bulkAction === "disable"
      ? "Disable selected"
      : "Choose action";
  const roleCount = (role: CustomerAccessRole) => accounts.filter((account) => account.accessRole === role).length;

  return (
    <section className="cp-admin-page">
      <div className="cp-page-head">
        <span className="cp-fi"><Users size={21} /></span>
        <div>
          <h1>Account management</h1>
          <p>Create, review, edit, and remove customer access from one place</p>
        </div>
        <div className="cp-page-actions">
          <span className="cp-count">{accounts.length} accounts</span>
          <button
            className="cp-btn-mini"
            type="button"
            onClick={openCreateEditor}
          >
            <UserPlus size={15} /> Add account
          </button>
        </div>
      </div>

      <div className="cp-admin-metrics">
        <div><small>Admin</small><strong>{roleCount("admin")}</strong></div>
        <div><small>Managers</small><strong>{roleCount("manager")}</strong></div>
        <div><small>Team members</small><strong>{roleCount("team")}</strong></div>
        <div><small>Agents</small><strong>{roleCount("agent")}</strong></div>
      </div>

      {error && <div className="cp-error" role="alert">{error}</div>}
      {notice && <div className="cp-password-success" role="status"><CheckCircle2 size={17} /> {notice}</div>}

      <div className="cp-admin-section">
        <div className="cp-admin-section-head">
          <div><Users size={17} /><strong>Customer accounts</strong></div>
          <small>Role, password, and permission changes invalidate affected sessions</small>
        </div>
        <div className="cp-account-bulk-toolbar">
          <label className="cp-account-bulk-select">
            <input
              type="checkbox"
              checked={allEligibleSelected}
              disabled={bulkEligibleAccounts.length === 0 || bulkUpdating}
              onChange={toggleAllEligibleAccounts}
            />
            <span>Select all accounts</span>
          </label>
          <span className="cp-account-selected-count">
            {selectedUsernames.length} selected
          </span>
          <div className="cp-account-bulk-actions">
            <div className="cp-account-bulk-menu" ref={bulkActionMenuRef}>
              <button
                className="cp-bulk-menu-trigger"
                type="button"
                aria-haspopup="menu"
                aria-expanded={bulkActionMenuOpen}
                aria-label="Choose bulk action"
                disabled={selectedUsernames.length === 0 || bulkUpdating}
                onClick={() => setBulkActionMenuOpen((current) => !current)}
              >
                <span>{bulkActionLabel}</span>
                <ChevronDown size={14} />
              </button>
              {bulkActionMenuOpen && selectedUsernames.length > 0 && (
                <div className="cp-bulk-menu-popover" role="menu">
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canEnableSelected}
                    onClick={() => {
                      setBulkAction("enable");
                      setBulkActionMenuOpen(false);
                    }}
                  >
                    <Power size={14} />
                    <span>Enable selected</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canDisableSelected}
                    onClick={() => {
                      setBulkAction("disable");
                      setBulkActionMenuOpen(false);
                    }}
                  >
                    <Power size={14} />
                    <span>Disable selected</span>
                  </button>
                  <div className="cp-bulk-menu-divider" />
                  <button type="button" role="menuitem" disabled>
                    <SendHorizontal size={14} />
                    <span>Send login emails</span>
                    <span className="cp-coming-soon-badge">Coming soon</span>
                  </button>
                  <button type="button" role="menuitem" disabled>
                    <KeyRound size={14} />
                    <span>Reset passwords</span>
                    <span className="cp-coming-soon-badge">Coming soon</span>
                  </button>
                </div>
              )}
            </div>
            <button
              className="cp-btn-ghost cp-bulk-apply-button"
              type="button"
              disabled={
                selectedUsernames.length === 0
                || bulkUpdating
                || !bulkAction
                || (bulkAction === "enable" ? !canEnableSelected : !canDisableSelected)
              }
              onClick={() => setBulkStatusOpen(true)}
            >
              Apply
            </button>
          </div>
        </div>
        <div className="cp-table-wrap cp-account-table-wrap">
          <table className="cp-table cp-account-admin-table">
            <thead>
              <tr>
                <th className="cp-account-select-cell"><span className="sr-only">Select</span></th>
                <th>Account</th>
                <th>Email</th>
                <th>Status</th>
                <th>Permission set</th>
                <th>Last successful login</th>
                <th>Login totals</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {!loading && accounts.map((account) => {
                const saving = savingUsername === account.username;
                const isCurrent = account.username.toLocaleLowerCase() === currentUsername.toLocaleLowerCase();
                const canBulkUpdate = !isCurrent;
                const isSelected = selectedSet.has(account.username);
                return (
                  <tr className={isSelected ? "cp-account-row-selected" : ""} key={account.username}>
                    <td className="cp-account-select-cell">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={!canBulkUpdate || bulkUpdating}
                        aria-label={`Select ${account.displayName}`}
                        onChange={() => toggleAccountSelection(account.username)}
                      />
                    </td>
                    <td>
                      <span className="cp-account-cell-title">
                        <strong>{account.displayName}</strong>
                        {account.isAdmin && <span className="cp-role-badge"><ShieldCheck size={11} /> Admin</span>}
                      </span>
                      <small className="cp-admin-intent">{account.username}</small>
                    </td>
                    <td>
                      <span className={account.email ? "cp-account-email" : "cp-account-email missing"}>
                        {account.email || "No email"}
                      </span>
                    </td>
                    <td>
                      <button
                        className={`cp-account-toggle ${account.enabled ? "enabled" : "disabled"}`}
                        type="button"
                        disabled={saving || (isCurrent && account.enabled)}
                        title={isCurrent && account.enabled ? "You cannot disable your current administrator account" : "Change account status"}
                        onClick={() => void updateAccount(account, { enabled: !account.enabled })}
                      >
                        {saving ? <Loader2 className="spin" size={14} /> : <Power size={14} />}
                        {account.enabled ? "Enabled" : "Disabled"}
                      </button>
                    </td>
                    <td>
                      <span className={`cp-permission-badge role-${account.accessRole}`}>
                        {customerAccessRoles.find((role) => role.value === account.accessRole)?.label ?? account.accessRole}
                      </span>
                    </td>
                    <td>
                      {formatAccountDate(account.lastSuccessfulLoginAt)}
                      {account.lastLoginStatus && <small className={`cp-login-state ${account.lastLoginStatus}`}>Last attempt: {account.lastLoginStatus}</small>}
                    </td>
                    <td><strong>{account.successfulLoginCount} successful</strong><small className="cp-admin-intent">{account.failedLoginCount} failed</small></td>
                    <td>{formatAccountDate(account.updatedAt)}<small className="cp-admin-intent">by {account.updatedBy}</small></td>
                    <td>
                      <span className="cp-account-actions">
                        <button
                          className="cp-btn-ghost cp-account-edit-button"
                          type="button"
                          title={`Edit ${account.displayName}`}
                          aria-label={`Edit ${account.displayName}`}
                          onClick={() => {
                            setClipboardNotice("");
                            setEditor({ mode: "edit", draft: accountDraft(account) });
                          }}
                        >
                          <Pencil size={14} /> Edit
                        </button>
                        <button
                          className="cp-icon-btn cp-danger-icon-btn"
                          type="button"
                          title={isCurrent ? "You cannot delete your current account" : `Delete ${account.displayName}`}
                          aria-label={`Delete ${account.displayName}`}
                          disabled={isCurrent}
                          onClick={() => setDeletingAccount(account)}
                        >
                          <Trash2 size={15} />
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {loading && <div className="cp-table-state"><Loader2 className="spin" size={18} /> Loading accounts…</div>}
          {!loading && !error && accounts.length === 0 && <div className="cp-table-state">No customer accounts are configured.</div>}
        </div>
      </div>

      {editor && (
        <div className="cp-modal-backdrop" role="presentation">
          <div className="cp-modal cp-account-editor" role="dialog" aria-modal="true" aria-labelledby="cp-account-editor-title">
            <div className="cp-modal-header">
              <div>
                <div className="cp-eyebrow">{editor.mode === "create" ? "New customer access" : "Customer access"}</div>
                <h2 id="cp-account-editor-title">{editor.mode === "create" ? "Add account" : `Edit ${editor.draft.displayName}`}</h2>
                <p>Create a MayakoFM login and choose its permission set.</p>
              </div>
              <button className="cp-icon-btn" type="button" aria-label="Close" disabled={submitting} onClick={() => setEditor(null)}><X size={17} /></button>
            </div>
            <form onSubmit={(event) => void saveEditor(event)}>
              <div className="cp-modal-body cp-account-form">
                <label>
                  <span>Username</span>
                  <input
                    value={editor.draft.username}
                    required
                    minLength={3}
                    maxLength={64}
                    pattern="[A-Za-z0-9._-]+"
                    disabled={editor.mode === "edit"}
                    autoComplete="off"
                    onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, username: event.target.value } })}
                  />
                </label>
                <label>
                  <span>Display name</span>
                  <input value={editor.draft.displayName} required maxLength={120} onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, displayName: event.target.value } })} />
                </label>
                <label className="cp-account-form-wide">
                  <span>Email address</span>
                  <input
                    type="email"
                    value={editor.draft.email}
                    required
                    maxLength={254}
                    autoComplete="email"
                    placeholder="customer@example.com"
                    onChange={(event) => setEditor({
                      ...editor,
                      draft: { ...editor.draft, email: event.target.value }
                    })}
                  />
                  <small>Used only to deliver account credentials and access notifications.</small>
                </label>
                <label className="cp-account-form-wide">
                  <span>{editor.mode === "create" ? "Temporary password" : "Reset password"} {editor.mode === "edit" && <em>Optional</em>}</span>
                  <div className="cp-password-control">
                    <input
                      type={editor.mode === "create" ? "text" : "password"}
                      value={editor.draft.password}
                      required={editor.mode === "create"}
                      minLength={12}
                      maxLength={256}
                      autoComplete="new-password"
                      onChange={(event) => {
                        setClipboardNotice("");
                        setEditor({
                          ...editor,
                          draft: {
                            ...editor.draft,
                            password: event.target.value,
                            sendCredentials: event.target.value ? editor.draft.sendCredentials : false
                          }
                        });
                      }}
                    />
                    <button
                      className="cp-btn-ghost"
                      type="button"
                      title="Generate a new 12-character complex password"
                      onClick={() => {
                        setClipboardNotice("");
                        setEditor({ ...editor, draft: { ...editor.draft, password: generateTemporaryPassword() } });
                      }}
                    >
                      <RefreshCw size={14} /> Generate
                    </button>
                    <button className="cp-btn-ghost" type="button" onClick={() => void copyEditorCredentials()}>
                      <Copy size={14} /> Copy login
                    </button>
                  </div>
                  <small>{editor.mode === "create" ? "A 12-character complex password is generated automatically." : "Leave blank to keep the current password, or generate a temporary reset password."}</small>
                  {clipboardNotice && <small className="cp-clipboard-notice" role="status">{clipboardNotice}</small>}
                </label>
                <div className={`cp-send-email-option cp-account-form-wide ${emailDeliveryEnabled ? "ready" : "unavailable"}`}>
                  <label>
                    <input
                      type="checkbox"
                      checked={editor.draft.sendCredentials}
                      disabled={!emailDeliveryEnabled || !editor.draft.email || !editor.draft.password}
                      onChange={(event) => setEditor({
                        ...editor,
                        draft: { ...editor.draft, sendCredentials: event.target.checked }
                      })}
                    />
                    <Mail size={17} />
                    <span>
                      <strong>Email login credentials after saving</strong>
                      <small>
                        {emailDeliveryEnabled
                          ? "Send the username and temporary password to this email address."
                          : "SMTP is not configured. Add the mail server credentials to enable delivery."}
                      </small>
                    </span>
                  </label>
                </div>
                <div className="cp-account-enabled cp-account-form-wide">
                  <label><input type="checkbox" checked={editor.draft.enabled} disabled={editor.mode === "edit" && editor.draft.username.toLocaleLowerCase() === currentUsername.toLocaleLowerCase()} onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, enabled: event.target.checked } })} /><span><strong>Enabled</strong><small>Allow this account to sign in</small></span></label>
                </div>
                <fieldset className="cp-permission-set cp-account-form-wide">
                  <legend>Permission set</legend>
                  <div className="cp-permission-set-grid">
                    {customerAccessRoles.map((role) => (
                      <label className={editor.draft.accessRole === role.value ? "selected" : ""} key={role.value}>
                        <input
                          type="radio"
                          name="customer-access-role"
                          value={role.value}
                          checked={editor.draft.accessRole === role.value}
                          disabled={editor.mode === "edit" && editor.draft.username.toLocaleLowerCase() === currentUsername.toLocaleLowerCase()}
                          onChange={() => setEditor({ ...editor, draft: { ...editor.draft, accessRole: role.value } })}
                        />
                        <span><strong>{role.label}</strong><small>{role.description}</small></span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </div>
              <div className="cp-modal-footer">
                <button className="cp-btn-ghost" type="button" disabled={submitting} onClick={() => setEditor(null)}>Cancel</button>
                <button className="cp-btn-mini" type="submit" disabled={submitting}>
                  {submitting ? <Loader2 className="spin" size={15} /> : editor.mode === "create" ? <UserPlus size={15} /> : <Pencil size={15} />}
                  {submitting ? "Saving…" : editor.mode === "create" ? "Create account" : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deletingAccount && (
        <div className="cp-modal-backdrop" role="presentation">
          <div className="cp-modal cp-account-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="cp-delete-account-title">
            <div className="cp-modal-header">
              <div>
                <div className="cp-eyebrow">Permanent access removal</div>
                <h2 id="cp-delete-account-title">Delete {deletingAccount.displayName}?</h2>
                <p>The account will be signed out and will no longer be able to log in.</p>
              </div>
            </div>
            <div className="cp-modal-footer">
              <button className="cp-btn-ghost" type="button" disabled={submitting} onClick={() => setDeletingAccount(null)}>Cancel</button>
              <button className="cp-btn-mini cp-danger-button" type="button" disabled={submitting} onClick={() => void deleteAccount()}>
                {submitting ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
                {submitting ? "Deleting…" : "Delete account"}
              </button>
            </div>
          </div>
        </div>
      )}

      {bulkStatusOpen && bulkAction && (
        <div className="cp-modal-backdrop" role="presentation">
          <div className="cp-modal cp-account-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="cp-bulk-status-title">
            <div className="cp-modal-header">
              <div>
                <div className="cp-eyebrow">Bulk account update</div>
                <h2 id="cp-bulk-status-title">
                  {bulkAction === "enable" ? "Enable" : "Disable"} {selectedUsernames.length} {selectedUsernames.length === 1 ? "account" : "accounts"}?
                </h2>
                <p>
                  {bulkAction === "enable"
                    ? "Selected users will be able to sign in again immediately."
                    : "Selected users will be signed out immediately and will not be able to log in until re-enabled."}
                </p>
              </div>
            </div>
            <div className="cp-modal-footer">
              <button className="cp-btn-ghost" type="button" disabled={bulkUpdating} onClick={() => setBulkStatusOpen(false)}>Cancel</button>
              <button
                className={`cp-btn-mini ${bulkAction === "disable" ? "cp-danger-button" : ""}`}
                type="button"
                disabled={bulkUpdating}
                onClick={() => void bulkUpdateAccountStatus()}
              >
                {bulkUpdating ? <Loader2 className="spin" size={15} /> : <Power size={15} />}
                {bulkUpdating
                  ? "Updating…"
                  : `${bulkAction === "enable" ? "Enable" : "Disable"} accounts`}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function formatAccountDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

function AdminChatAnalyticsPage({
  token,
  onUnauthorized
}: {
  token: string;
  onUnauthorized: () => void;
}) {
  const [history, setHistory] = useState<CustomerChatHistoryResponse | null>(null);
  const [summary, setSummary] = useState<CustomerQuestionSummaryResponse | null>(null);
  const [domain, setDomain] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const historyParams = new URLSearchParams({
      page: String(page),
      pageSize: "50",
      domain,
      status: statusFilter,
      q: query
    });
    void Promise.all([
      requestJson<CustomerChatHistoryResponse>(`/api/customer-chat/admin/history?${historyParams}`, {}, token),
      requestJson<CustomerQuestionSummaryResponse>("/api/customer-chat/admin/question-summary?days=30&limit=50", {}, token)
    ]).then(([historyData, summaryData]) => {
      if (!active) return;
      setHistory(historyData);
      setSummary(summaryData);
    }).catch((requestError) => {
      if (!active) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "Chat analytics could not be loaded.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [domain, onUnauthorized, page, query, statusFilter, token]);

  const totals = (summary?.questions ?? []).reduce((current, item) => ({
    questions: current.questions + item.totalCount,
    noResult: current.noResult + item.noResultCount,
    blocked: current.blocked + item.blockedCount,
    errors: current.errors + item.errorCount
  }), { questions: 0, noResult: 0, blocked: 0, errors: 0 });

  return (
    <section className="cp-admin-page">
      <div className="cp-page-head">
        <span className="cp-fi"><BarChart3 size={21} /></span>
        <div>
          <h1>Chat analytics</h1>
          <p>Customer questions, answers and improvement signals stored in PostgreSQL</p>
        </div>
        <span className="cp-count">Last 30 days</span>
      </div>

      <div className="cp-admin-metrics">
        <div><small>Questions</small><strong>{totals.questions.toLocaleString("en-US")}</strong></div>
        <div><small>No result</small><strong>{totals.noResult.toLocaleString("en-US")}</strong></div>
        <div><small>Blocked</small><strong>{totals.blocked.toLocaleString("en-US")}</strong></div>
        <div><small>Errors</small><strong>{totals.errors.toLocaleString("en-US")}</strong></div>
      </div>

      {error && <div className="cp-error" role="alert">{error}</div>}
      <div className="cp-admin-section">
        <div className="cp-admin-section-head">
          <div><BarChart3 size={17} /><strong>Question summary</strong></div>
          <small>Grouped to reveal repeated questions and failure patterns</small>
        </div>
        <div className="cp-table-wrap">
          <table className="cp-table cp-admin-table">
            <thead><tr><th>Question</th><th>Domain</th><th>Asked</th><th>Success</th><th>No result</th><th>Blocked</th><th>Error</th><th>Last asked</th></tr></thead>
            <tbody>
              {!loading && (summary?.questions ?? []).map((item) => (
                <tr key={`${item.normalizedKey}-${item.domain}`}>
                  <td><strong>{item.canonicalQuestion}</strong><small className="cp-admin-intent">{item.intent}</small></td>
                  <td><span className="cp-admin-tag">{item.domain || "unknown"}</span></td>
                  <td>{item.totalCount}</td><td>{item.successCount}</td><td>{item.noResultCount}</td>
                  <td>{item.blockedCount}</td><td>{item.errorCount}</td>
                  <td>{new Date(item.lastAskedAt).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {loading && <div className="cp-table-state"><Loader2 className="spin" size={18} /> Loading analytics…</div>}
          {!loading && !error && !summary?.questions.length && <div className="cp-table-state">No customer questions have been recorded yet.</div>}
        </div>
      </div>

      <div className="cp-admin-section">
        <div className="cp-admin-section-head">
          <div><History size={17} /><strong>Conversation history</strong></div>
          <small>Test traffic is excluded by default</small>
        </div>
        <form className="cp-admin-filters" onSubmit={(event) => { event.preventDefault(); setPage(1); setQuery(draft.trim()); }}>
          <div className="cp-control"><Search size={16} /><input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Search question text" /></div>
          <select value={domain} onChange={(event) => { setDomain(event.target.value); setPage(1); }} aria-label="Domain filter">
            <option value="">All domains</option><option value="product">Products</option><option value="part">Parts</option><option value="order">Orders</option><option value="unknown">Unknown</option>
          </select>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1); }} aria-label="Status filter">
            <option value="">All statuses</option><option value="success">Success</option><option value="no_result">No result</option><option value="clarification">Clarification</option><option value="blocked">Blocked</option><option value="error">Error</option>
          </select>
          <button className="cp-btn-mini" type="submit">Search</button>
        </form>
        <div className="cp-table-wrap">
          <table className="cp-table cp-admin-table">
            <thead><tr><th>Time</th><th>Account</th><th>Question and answer</th><th>Domain</th><th>Status</th><th>Results</th><th>Latency</th></tr></thead>
            <tbody>
              {!loading && (history?.rows ?? []).map((item) => (
                <tr key={item.id}>
                  <td>{new Date(item.createdAt).toLocaleString()}</td>
                  <td><strong>{item.operatorName}</strong><small className="cp-admin-intent">{item.operatorAccount} · {item.channel}</small></td>
                  <td className="cp-admin-question"><strong>{item.prompt}</strong><small>{item.answer}</small></td>
                  <td><span className="cp-admin-tag">{item.domain || "unknown"}</span></td>
                  <td><span className={`cp-admin-status ${item.status}`}>{item.status.replace("_", " ")}</span></td>
                  <td>{item.returnedCount}/{item.foundCount}</td><td>{item.durationMs} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && !error && !history?.rows.length && <div className="cp-table-state">No matching history was found.</div>}
          {history && history.totalPages > 1 && (
            <nav className="cp-pager" aria-label="Chat history pages">
              <span>Page {history.page} of {history.totalPages}</span>
              <div className="cp-page-buttons">
                <button type="button" onClick={() => setPage((current) => current - 1)} disabled={loading || page <= 1}><ChevronLeft size={14} /> Prev</button>
                <button type="button" onClick={() => setPage((current) => current + 1)} disabled={loading || page >= history.totalPages}>Next <ChevronRight size={14} /></button>
              </div>
            </nav>
          )}
        </div>
      </div>
    </section>
  );
}

function CustomerHome({
  token,
  profile,
  onNavigate,
  onUnauthorized
}: {
  token: string;
  profile: CustomerProfile;
  onNavigate: (route: PortalRoute) => void;
  onUnauthorized: () => void;
}) {
  type Message =
    | { id: string; role: "user"; text: string; at: string }
    | { id: string; role: "assistant"; response?: CustomerQueryResponse; error?: string; at: string };
  const [prompt, setPrompt] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  const visibleHomeSuggestions = profile.canViewOrders
    ? homeSuggestions
    : homeSuggestions.filter((item) => !/order/i.test(item));

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function submit(value = prompt) {
    const normalized = value.trim();
    if (!normalized || loading) return;
    setPrompt("");
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: "user", text: normalized, at: timeStamp() }]);
    setLoading(true);
    try {
      const response = await requestJson<CustomerQueryResponse>(
        "/api/customer-chat/query",
        { method: "POST", body: JSON.stringify({ prompt: normalized, page: 1, pageSize: 4 }) },
        token
      );
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: "assistant", response, at: timeStamp() }]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onUnauthorized();
        return;
      }
      setMessages((current) => [...current, {
        id: crypto.randomUUID(),
        role: "assistant",
        error: error instanceof Error ? error.message : "The search could not be completed.",
        at: timeStamp()
      }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="cp-home">
      <section className="cp-home-intro">
        <span className="cp-pill"><ShieldCheck size={13} /> Secure account workspace</span>
        <h1>Welcome back,<br /><span>{profile.displayName}</span></h1>
        <p>{profile.canViewDetails ? "Use the catalogs for browsing and detailed records." : "This account is limited to product and part inventory lookup."} Use chat for quick checks.</p>
        <div className="cp-entry-cards">
          {profile.canViewOrders && (
            <button className="cp-entry-card" type="button" onClick={() => onNavigate({ page: "orders" })}>
              <span className="cp-fi"><ShoppingCart size={20} /></span>
              <span><strong>Order history</strong><small>Browse shipment, tracking and delivery details</small></span>
              <span className="cp-go"><ChevronRight size={18} /></span>
            </button>
          )}
          <button className="cp-entry-card" type="button" onClick={() => onNavigate({ page: "products" })}>
            <span className="cp-fi"><Boxes size={20} /></span>
            <span><strong>Product catalog</strong><small>{profile.canViewDetails ? "Browse products, inventory and BOM details" : "Check product inventory"}</small></span>
            <span className="cp-go"><ChevronRight size={18} /></span>
          </button>
          <button className="cp-entry-card" type="button" onClick={() => onNavigate({ page: "parts" })}>
            <span className="cp-fi"><Wrench size={20} /></span>
            <span><strong>Part catalog</strong><small>{profile.canViewDetails ? "Browse parts, inventory and basic details" : "Check part inventory"}</small></span>
            <span className="cp-go"><ChevronRight size={18} /></span>
          </button>
        </div>
      </section>

      <section className="cp-chat" aria-label="Quick account assistant">
        <div className="cp-chat-head">
          <span className="cp-fi"><Bot size={18} /></span>
          <div><strong>Quick account assistant</strong><small>{profile.canViewOrders ? "Orders, products, parts and inventory" : "Product and part inventory only"}</small></div>
        </div>
        <div className="cp-chat-body" aria-live="polite">
          <article className="cp-msg bot">
            <div className="cp-text"><p>{profile.canViewOrders ? "Ask about an order, tracking number, product or part" : "Ask for product or part inventory"}, or select a suggestion below.</p></div>
          </article>
          <div className="cp-chips">
            {visibleHomeSuggestions.map((item) => (
              <button className="cp-chip" key={item} type="button" onClick={() => void submit(item)} disabled={loading}>{item}</button>
            ))}
          </div>
          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <article className="cp-msg user" key={message.id}>
                  {message.text}
                  <span className="cp-stamp">{message.at}</span>
                </article>
              );
            }
            const response = message.response;
            const first = response?.rows[0];
            return (
              <article className={`cp-msg bot ${message.error ? "error" : ""}`} key={message.id}>
                {message.error ? <div className="cp-text"><p>{message.error}</p></div> : response && <>
                  <div className="cp-text"><p>{response.answer}</p></div>
                  {response.resultType === "order" && response.rows.some((row) => row.entityType === "order") ? (
                    <div className="cp-order-chat-results">
                      {response.rows.map((row) => row.entityType === "order" && (
                        <OrderChatResult key={row.orderRef} order={row} />
                      ))}
                      <button className="cp-btn-ghost" type="button" onClick={() => onNavigate({ page: "orders" })}>
                        <ShoppingCart size={14} /> Open order history
                      </button>
                    </div>
                  ) : response.foundCount === 1 && first && first.entityType !== "order" ? (
                    <div className="cp-result-card">
                      <div className="cp-rc-head">
                        <TableThumb
                          hasImage={first.hasImage}
                          token={token}
                          path={first.entityType === "part" ? `/api/customer-chat/parts/${first.productRef}/image` : `/api/customer-chat/products/${first.productRef}/image`}
                          alt={first.productName || first.productSku}
                          onUnauthorized={onUnauthorized}
                        />
                        <div>
                          <div className="cp-sku">{first.productSku || "—"}</div>
                          <div className="cp-name">{first.productName || "—"}</div>
                          {profile.canViewPrice && first.price !== undefined && first.price !== null && (
                            <div className="cp-chat-price">Unit price {displayCurrency(first.price)}</div>
                          )}
                        </div>
                        <StockBadge value={first.stock} verbose />
                      </div>
                      <div className="cp-rc-foot">
                        <button className="cp-btn-mini" type="button" onClick={() => onNavigate(
                          first.entityType === "part"
                            ? { page: "part-detail", recordId: first.productRef }
                            : { page: "product-detail", recordId: first.productRef }
                        )}>View details <ChevronRight size={14} /></button>
                      </div>
                    </div>
                  ) : response.foundCount > 1 ? (
                    <div style={{ marginTop: 10 }}>
                      <button className="cp-btn-ghost" type="button" onClick={() => onNavigate(
                        response.resultType === "part" ? { page: "parts" } : { page: "products" }
                      )}><Boxes size={14} /> Open {response.resultType === "part" ? "part" : "product"} catalog</button>
                    </div>
                  ) : null}
                  {response.requiresClarification && response.clarificationOptions.length > 0 && (
                    <div className="cp-chips" style={{ marginTop: 10 }}>
                      {response.clarificationOptions.slice(0, 4).map((item) => (
                        <button className="cp-chip" key={item} type="button" onClick={() => void submit(item)}>{item}</button>
                      ))}
                    </div>
                  )}
                </>}
                <span className="cp-stamp">{message.at}</span>
              </article>
            );
          })}
          {loading && (
            <article className="cp-msg bot">
              <div className="cp-text"><span className="cp-typing"><Loader2 className="spin" size={15} /> Checking live records…</span></div>
            </article>
          )}
          <div ref={endRef} />
        </div>
        <form className="cp-chat-input" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
          <div className="cp-control">
            <input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              maxLength={240}
              placeholder="Enter an order, product or part number"
              aria-label="Quick account question"
            />
          </div>
          <button className="cp-send-btn" type="submit" disabled={loading || !prompt.trim()} aria-label="Send">
            <SendHorizontal size={18} />
          </button>
        </form>
      </section>
    </div>
  );
}

function CatalogPage({
  kind,
  token,
  canViewDetails,
  onNavigate,
  onUnauthorized
}: {
  kind: "product" | "part";
  token: string;
  canViewDetails: boolean;
  onNavigate: (route: PortalRoute) => void;
  onUnauthorized: () => void;
}) {
  const defaultSort = kind === "product" ? "productSku" : "partNumber";
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [searchHint, setSearchHint] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(() => {
    const stored = Number(window.localStorage.getItem(`customer-${kind}-page-size-v2`));
    return [10, 20, 50, 100].includes(stored) ? stored : 10;
  });
  const [sortBy, setSortBy] = useState(defaultSort);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [data, setData] = useState<CustomerCatalogPage<CustomerCatalogProduct | CustomerCatalogPart> | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false);
  const [error, setError] = useState("");
  const actionsMenuRef = useRef<HTMLDivElement>(null);
  const catalogDefinitions = useMemo(() => {
    const definitions = kind === "product" ? PRODUCT_COLUMNS : PART_COLUMNS;
    if (canViewDetails) return definitions;
    const inventoryColumns = kind === "product"
      ? new Set(["productSku", "productName", "stock"])
      : new Set(["partNumber", "partName", "stock"]);
    return definitions.filter((column) => inventoryColumns.has(column.id));
  }, [canViewDetails, kind]);
  const columnLayout = useCustomerTableLayout(
    `customer-${kind}-columns-${canViewDetails ? "v1" : "inventory-v1"}`,
    catalogDefinitions
  );

  useEffect(() => {
    if (!actionsMenuOpen) return;
    const handlePointerDown = (event: globalThis.PointerEvent) => {
      if (!actionsMenuRef.current?.contains(event.target as Node)) setActionsMenuOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setActionsMenuOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [actionsMenuOpen]);

  useEffect(() => {
    try {
      window.localStorage.setItem(`customer-${kind}-page-size-v2`, String(pageSize));
    } catch {
      // Keep the current page size for this session when storage is unavailable.
    }
  }, [kind, pageSize]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      q: query,
      page: String(page),
      pageSize: String(pageSize),
      sortBy,
      sortOrder
    });
    void requestJson<CustomerCatalogPage<CustomerCatalogProduct | CustomerCatalogPart>>(
      `/api/customer-chat/catalog/${kind === "product" ? "products" : "parts"}?${params}`,
      {},
      token
    ).then((result) => {
      if (active) setData(result);
    }).catch((requestError) => {
      if (!active) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "The catalog could not be loaded.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [kind, onUnauthorized, page, pageSize, query, sortBy, sortOrder, token]);

  const rows = data?.rows ?? [];
  const first = data?.foundCount ? ((data.page - 1) * data.pageSize) + 1 : 0;
  const last = first ? first + data!.returnedCount - 1 : 0;
  const sortOptions = (kind === "product"
    ? [["productSku", "Product No."], ["productName", "Product Name"], ["stock", "Inventory"], ["modelName", "Model"], ["scale", "Scale"], ["category", "Category"], ["bomCount", "BOM"]]
    : [["partNumber", "Part No."], ["partName", "Part Name"], ["stock", "Inventory"], ["status", "Status"]])
    .filter(([value]) => canViewDetails || catalogDefinitions.some((column) => column.sortKey === value));

  function openRow(row: CustomerCatalogProduct | CustomerCatalogPart) {
    if (!canViewDetails) return;
    if (kind === "product") {
      onNavigate({ page: "product-detail", recordId: (row as CustomerCatalogProduct).productRef });
    } else {
      onNavigate({ page: "part-detail", recordId: (row as CustomerCatalogPart).partRef });
    }
  }

  function changeSort(nextSort: string) {
    if (nextSort === sortBy) {
      setSortOrder((current) => current === "asc" ? "desc" : "asc");
    } else {
      setSortBy(nextSort);
      setSortOrder("asc");
    }
    setPage(1);
  }

  function submitSearch() {
    const value = draft.trim();
    if (value.length === 1) {
      setSearchHint("Enter at least 2 characters to search.");
      return;
    }
    setSearchHint("");
    setPage(1);
    setQuery(value);
  }

  function clearSearch() {
    setDraft("");
    setQuery("");
    setSearchHint("");
    setPage(1);
  }

  async function exportCatalog() {
    if (exporting) return;
    setExporting(true);
    setError("");
    try {
      const params = new URLSearchParams({ q: query });
      const catalogName = kind === "product" ? "products" : "parts";
      const blob = await requestAsset(`/api/customer-chat/catalog/${catalogName}/export.xlsx?${params}`, token);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `mayako-${catalogName}-inventory-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "The Excel export could not be created.");
    } finally {
      setExporting(false);
    }
  }

  return (
    <section>
      <div className="cp-page-head">
        <span className="cp-fi">{kind === "product" ? <Boxes size={21} /> : <Wrench size={21} />}</span>
        <div>
          <h1>{kind === "product" ? "Products" : "Parts"}</h1>
          <p>{canViewDetails ? (kind === "product" ? "Approved products, inventory and BOM details" : "Account parts, inventory and basic details") : `${kind === "product" ? "Product" : "Part"} inventory lookup`}</p>
        </div>
        <div className="cp-page-actions">
          <span className="cp-count">{data?.foundCount.toLocaleString("en-US") ?? "—"} records</span>
          <div className="cp-actions-menu-wrap" ref={actionsMenuRef}>
            <button
              className="cp-btn-ghost cp-actions-button"
              type="button"
              onClick={() => setActionsMenuOpen((current) => !current)}
              disabled={exporting}
              aria-haspopup="menu"
              aria-expanded={actionsMenuOpen}
              aria-controls={`customer-${kind}-actions-menu`}
            >
              {exporting && <Loader2 className="spin" size={14} aria-hidden="true" />}
              <span>Actions</span>
              <ChevronDown className="cp-actions-chevron" size={14} aria-hidden="true" />
            </button>
            {actionsMenuOpen && (
              <div
                className="cp-actions-menu"
                id={`customer-${kind}-actions-menu`}
                role="menu"
                aria-label={`${kind === "product" ? "Product" : "Part"} actions`}
              >
                <button
                  type="button"
                  role="menuitem"
                  disabled={loading || exporting || !data?.foundCount}
                  onClick={() => {
                    setActionsMenuOpen(false);
                    void exportCatalog();
                  }}
                >
                  <FileSpreadsheet size={17} aria-hidden="true" />
                  <span>
                    <strong>Export Excel</strong>
                    <small>Export the current search results</small>
                  </span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="cp-toolbar">
        <form onSubmit={(event) => { event.preventDefault(); submitSearch(); }}>
          <div className="cp-control">
            <Search size={16} />
            <input value={draft} onChange={(event) => { setDraft(event.target.value); setSearchHint(""); }} placeholder={`Search by ${kind === "product" ? "product number, name or model" : "part number or English name"}`} />
            {(draft || query) && (
              <button className="cp-clear" type="button" onClick={clearSearch} aria-label="Clear search" title="Clear search"><X size={14} /></button>
            )}
          </div>
          <button className="cp-btn-mini" type="submit" disabled={loading}>Search</button>
        </form>
        <div className="cp-sort">
          <span>Sort by</span>
          <select value={sortBy} onChange={(event) => { setSortBy(event.target.value); setPage(1); }} aria-label="Sort field">
            {sortOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button className="cp-btn-ghost" type="button" onClick={() => setSortOrder((current) => current === "asc" ? "desc" : "asc")}>
            {sortOrder === "asc" ? <ArrowDownAZ size={15} /> : <ArrowUpAZ size={15} />}
            {sortOrder === "asc" ? "Ascending" : "Descending"}
          </button>
          <button className="cp-btn-ghost" type="button" onClick={columnLayout.resetColumns} title="Restore the default column order and widths">
            <RotateCcw size={14} /> Reset columns
          </button>
        </div>
      </div>

      <p className="cp-table-hint">Click a field name to sort. Drag a header to reorder it, or drag its right edge to resize.</p>

      {searchHint && <div className="cp-search-hint" role="alert">{searchHint}</div>}
      {error && <div className="cp-error" role="alert">{error}</div>}
      <div className="cp-table-wrap">
        <table className="cp-table" style={tableStyle(columnLayout.totalWidth)}>
          <colgroup>{columnLayout.columns.map((column) => <col key={column.id} style={{ width: columnLayout.widths[column.id] ?? column.width }} />)}</colgroup>
          <CustomerTableHeader
            columns={columnLayout.columns}
            widths={columnLayout.widths}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={changeSort}
            onResize={columnLayout.resizeColumn}
            onMove={columnLayout.moveColumn}
          />
          <tbody>
            {!loading && rows.map((row) => kind === "product" ? (
              <ProductTableRow key={(row as CustomerCatalogProduct).productRef} columns={columnLayout.columns} row={row as CustomerCatalogProduct} token={token} canViewDetails={canViewDetails} onOpen={() => openRow(row)} onUnauthorized={onUnauthorized} />
            ) : (
              <PartTableRow key={(row as CustomerCatalogPart).partRef} columns={columnLayout.columns} row={row as CustomerCatalogPart} token={token} canViewDetails={canViewDetails} onOpen={() => openRow(row)} onUnauthorized={onUnauthorized} />
            ))}
          </tbody>
        </table>
        {loading && <div className="cp-table-state"><Loader2 className="spin" size={18} /> Loading live catalog…</div>}
        {!loading && !error && rows.length === 0 && <div className="cp-table-state">No matching records were found.</div>}
        {data && !loading && (
          <nav className="cp-pager" aria-label="Catalog pages">
            <div className="cp-page-summary">
              <span>{first.toLocaleString("en-US")}–{last.toLocaleString("en-US")} of {data.foundCount.toLocaleString("en-US")}</span>
              <label>Rows per page
                <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} disabled={loading}>
                  <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
                </select>
              </label>
            </div>
            {data.totalPages > 1 && <div className="cp-page-buttons">
              <button type="button" onClick={() => setPage((current) => current - 1)} disabled={loading || data.page <= 1}><ChevronLeft size={14} /> Prev</button>
              {visiblePages(data.page, data.totalPages).map((pageNumber) => (
                <button key={pageNumber} className={pageNumber === data.page ? "active" : ""} type="button" onClick={() => setPage(pageNumber)} disabled={loading || pageNumber === data.page}>{pageNumber}</button>
              ))}
              <button type="button" onClick={() => setPage((current) => current + 1)} disabled={loading || data.page >= data.totalPages}>Next <ChevronRight size={14} /></button>
            </div>}
          </nav>
        )}
      </div>
    </section>
  );
}

function OrdersPage({
  token,
  canViewPrice,
  onUnauthorized
}: {
  token: string;
  canViewPrice: boolean;
  onUnauthorized: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const [searchHint, setSearchHint] = useState("");
  const [draftMonth, setDraftMonth] = useState("");
  const [month, setMonth] = useState("");
  const [draftShippingStatus, setDraftShippingStatus] = useState<OrderShippingStatusFilter>("all");
  const [shippingStatus, setShippingStatus] = useState<OrderShippingStatusFilter>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(() => {
    const stored = Number(window.localStorage.getItem("customer-order-page-size-v1"));
    return [10, 20, 50, 100].includes(stored) ? stored : 10;
  });
  const [sortBy, setSortBy] = useState("orderNumber");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [data, setData] = useState<CustomerCatalogPage<CustomerCatalogOrder> | null>(null);
  const [summary, setSummary] = useState<CustomerOrderSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [error, setError] = useState("");
  const [summaryError, setSummaryError] = useState("");
  const orderDefinitions = useMemo(
    () => canViewPrice
      ? ORDER_COLUMNS
      : ORDER_COLUMNS.filter((column) => !["orderAmount", "shippingCost"].includes(column.id)),
    [canViewPrice]
  );
  const columnLayout = useCustomerTableLayout(
    `customer-order-columns-${canViewPrice ? "v2" : "no-price-v1"}`,
    orderDefinitions
  );

  useEffect(() => {
    try {
      window.localStorage.setItem("customer-order-page-size-v1", String(pageSize));
    } catch {
      // Keep the current page size for this session when storage is unavailable.
    }
  }, [pageSize]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const params = new URLSearchParams({
      q: query,
      page: String(page),
      pageSize: String(pageSize),
      sortBy,
      sortOrder,
      month,
      shippingStatus
    });
    void requestJson<CustomerCatalogPage<CustomerCatalogOrder>>(
      `/api/customer-chat/catalog/orders?${params}`,
      {},
      token
    ).then((result) => {
      if (active) setData(result);
    }).catch((requestError) => {
      if (!active) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setError(requestError instanceof Error ? requestError.message : "The order list could not be loaded.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [month, onUnauthorized, page, pageSize, query, shippingStatus, sortBy, sortOrder, token]);

  useEffect(() => {
    let active = true;
    setSummaryLoading(true);
    setSummaryError("");
    const params = new URLSearchParams({ q: query, month, shippingStatus });
    void requestJson<CustomerOrderSummary>(
      `/api/customer-chat/catalog/orders/summary?${params}`,
      {},
      token
    ).then((result) => {
      if (active) setSummary(result);
    }).catch((requestError) => {
      if (!active) return;
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized();
        return;
      }
      setSummaryError(requestError instanceof Error ? requestError.message : "The order summary could not be loaded.");
    }).finally(() => {
      if (active) setSummaryLoading(false);
    });
    return () => { active = false; };
  }, [month, onUnauthorized, query, shippingStatus, token]);

  const rows = data?.rows ?? [];
  const first = data?.foundCount ? ((data.page - 1) * data.pageSize) + 1 : 0;
  const last = first ? first + data!.returnedCount - 1 : 0;
  const summaryPeriod = month
    ? new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(`${month}-01T00:00:00Z`))
    : "All order dates";

  function changeSort(nextSort: string) {
    if (nextSort === sortBy) {
      setSortOrder((current) => current === "asc" ? "desc" : "asc");
    } else {
      setSortBy(nextSort);
      setSortOrder("asc");
    }
    setPage(1);
  }

  function applyFilters() {
    const value = draft.trim();
    if (value.length === 1) {
      setSearchHint("Enter at least 2 characters to search.");
      return;
    }
    setSearchHint("");
    setPage(1);
    setQuery(value);
    setMonth(draftMonth);
    setShippingStatus(draftShippingStatus);
  }

  function resetFilters() {
    setDraft("");
    setQuery("");
    setSearchHint("");
    setDraftMonth("");
    setMonth("");
    setDraftShippingStatus("all");
    setShippingStatus("all");
    setPage(1);
  }

  return (
    <section>
      <div className="cp-page-head">
        <span className="cp-fi"><ShoppingCart size={21} /></span>
        <div>
          <h1>Orders</h1>
          <p>{canViewPrice ? "Order totals, shipment progress, tracking and customer-visible remarks" : "Shipment progress, tracking and customer-visible remarks"}</p>
        </div>
        <span className="cp-count">{data?.foundCount.toLocaleString("en-US") ?? "—"} records</span>
      </div>

      <div className={`cp-order-summary ${summaryLoading ? "loading" : ""}`} aria-live="polite">
        {canViewPrice && (
          <div className="cp-metric money">
            <small>Order amount</small>
            <strong>{summary ? displayCurrency(summary.orderAmountTotal) : "—"}</strong>
            <span>{summaryPeriod}</span>
          </div>
        )}
        <div className="cp-metric">
          <small>Orders</small>
          <strong>{summary?.orderCount.toLocaleString("en-US") ?? "—"}</strong>
          <span>Matching current filters</span>
        </div>
        <div className="cp-metric">
          <small>Shipped</small>
          <strong>{summary?.shippedCount.toLocaleString("en-US") ?? "—"}</strong>
          <span>Has a shipped date</span>
        </div>
        <div className="cp-metric">
          <small>Not shipped</small>
          <strong>{summary?.notShippedCount.toLocaleString("en-US") ?? "—"}</strong>
          <span>No shipped date yet</span>
        </div>
      </div>

      <form className="cp-order-filter-panel" onSubmit={(event) => { event.preventDefault(); applyFilters(); }}>
        <div className="cp-order-filter-head">
          <div>
            <strong>Filters</strong>
            <span>Combine multiple conditions, then apply them together.</span>
          </div>
        </div>
        <div className="cp-order-filter-grid">
          <label className="cp-order-filter-field cp-order-filter-keyword">
            <span>Keyword</span>
            <div className="cp-control">
              <Search size={16} />
              <input
                value={draft}
                onChange={(event) => { setDraft(event.target.value); setSearchHint(""); }}
                placeholder="Order, shipping company, tracking or remarks"
                aria-label="Order keyword"
              />
              {draft && (
                <button className="cp-clear" type="button" onClick={() => setDraft("")} aria-label="Clear keyword" title="Clear keyword"><X size={14} /></button>
              )}
            </div>
          </label>
          <label className="cp-order-filter-field cp-order-month">
            <span>Order month</span>
            <input
              type="month"
              value={draftMonth}
              onChange={(event) => setDraftMonth(event.target.value)}
              aria-label="Order month"
            />
          </label>
          <div className="cp-order-filter-field">
            <span>Shipping status</span>
            <div className="cp-status-filter" role="group" aria-label="Shipping status">
              <button type="button" className={draftShippingStatus === "all" ? "active" : ""} aria-pressed={draftShippingStatus === "all"} onClick={() => setDraftShippingStatus("all")}>All</button>
              <button type="button" className={draftShippingStatus === "shipped" ? "active" : ""} aria-pressed={draftShippingStatus === "shipped"} onClick={() => setDraftShippingStatus("shipped")}>Shipped</button>
              <button type="button" className={draftShippingStatus === "notShipped" ? "active" : ""} aria-pressed={draftShippingStatus === "notShipped"} onClick={() => setDraftShippingStatus("notShipped")}>Not shipped</button>
            </div>
          </div>
          <div className="cp-order-filter-actions">
            <button className="cp-btn-ghost" type="button" onClick={resetFilters}>
              <RotateCcw size={14} /> Reset
            </button>
            <button className="cp-btn-mini" type="submit" disabled={loading}>
              {loading ? <Loader2 className="spin" size={14} /> : <Search size={14} />}
              Apply filters
            </button>
          </div>
        </div>
      </form>

      <div className="cp-table-tools">
        <p className="cp-table-hint">Click a sortable field name to sort. Drag a header to reorder it, or drag its right edge to resize.</p>
        <button className="cp-btn-ghost" type="button" onClick={columnLayout.resetColumns} title="Restore the default column order and widths">
          <RotateCcw size={14} /> Reset columns
        </button>
      </div>
      {searchHint && <div className="cp-search-hint" role="alert">{searchHint}</div>}
      {error && <div className="cp-error" role="alert">{error}</div>}
      {summaryError && <div className="cp-error" role="alert">{summaryError}</div>}
      <div className="cp-table-wrap">
        <table className="cp-table cp-orders-table" style={tableStyle(columnLayout.totalWidth)}>
          <colgroup>{columnLayout.columns.map((column) => <col key={column.id} style={{ width: columnLayout.widths[column.id] ?? column.width }} />)}</colgroup>
          <CustomerTableHeader
            columns={columnLayout.columns}
            widths={columnLayout.widths}
            sortBy={sortBy}
            sortOrder={sortOrder}
            onSort={changeSort}
            onResize={columnLayout.resizeColumn}
            onMove={columnLayout.moveColumn}
          />
          <tbody>
            {!loading && rows.map((row) => <OrderTableRow key={row.orderRef} columns={columnLayout.columns} row={row} />)}
          </tbody>
        </table>
        {loading && <div className="cp-table-state"><Loader2 className="spin" size={18} /> Loading live orders…</div>}
        {!loading && !error && rows.length === 0 && <div className="cp-table-state">No matching orders were found.</div>}
        {data && !loading && (
          <nav className="cp-pager" aria-label="Order pages">
            <div className="cp-page-summary">
              <span>{first.toLocaleString("en-US")}–{last.toLocaleString("en-US")} of {data.foundCount.toLocaleString("en-US")}</span>
              <label>Rows per page
                <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }} disabled={loading}>
                  <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
                </select>
              </label>
            </div>
            {data.totalPages > 1 && <div className="cp-page-buttons">
              <button type="button" onClick={() => setPage((current) => current - 1)} disabled={loading || data.page <= 1}><ChevronLeft size={14} /> Prev</button>
              {visiblePages(data.page, data.totalPages).map((pageNumber) => (
                <button key={pageNumber} className={pageNumber === data.page ? "active" : ""} type="button" onClick={() => setPage(pageNumber)} disabled={loading || pageNumber === data.page}>{pageNumber}</button>
              ))}
              <button type="button" onClick={() => setPage((current) => current + 1)} disabled={loading || data.page >= data.totalPages}>Next <ChevronRight size={14} /></button>
            </div>}
          </nav>
        )}
      </div>
    </section>
  );
}

function OrderTableRow({ columns, row }: { columns: CustomerTableColumn[]; row: CustomerCatalogOrder }) {
  function content(column: CustomerTableColumn) {
    if (column.id === "clientName") return displayValue(row.clientName);
    if (column.id === "orderNumber") return <span className="cp-mono">{displayValue(row.orderNumber)}</span>;
    if (column.id === "orderAmount") return displayCurrency(row.orderAmount);
    if (column.id === "shippingCompany") return displayValue(row.shippingCompany);
    if (column.id === "trackingNumber") return <span className="cp-mono">{displayValue(row.trackingNumber)}</span>;
    if (column.id === "shippingCost") return displayCurrency(row.shippingCost);
    if (column.id === "shippingStatus") return (
      <span className={`cp-order-status ${row.shippingStatus === "Shipped" ? "shipped" : "not-shipped"}`}>
        {displayValue(row.shippingStatus)}
      </span>
    );
    if (column.id === "shippedDate") return displayValue(row.shippedDate);
    return <span className="cp-order-remarks">{displayValue(row.remarks)}</span>;
  }

  return (
    <tr>
      {columns.map((column) => <td key={column.id} data-label={column.label} className={`${column.numeric ? "cp-num " : ""}${column.centered ? "cp-center" : ""}`}>{content(column)}</td>)}
    </tr>
  );
}

function ProductTableRow({ columns, row, token, canViewDetails, onOpen, onUnauthorized }: { columns: CustomerTableColumn[]; row: CustomerCatalogProduct; token: string; canViewDetails: boolean; onOpen: () => void; onUnauthorized: () => void }) {
  function content(column: CustomerTableColumn) {
    if (column.id === "image") return <TableThumb hasImage={row.hasImage} token={token} path={`/api/customer-chat/products/${row.productRef}/image`} alt={row.productName || row.productSku} onUnauthorized={onUnauthorized} />;
    if (column.id === "productSku") return canViewDetails ? <button className="cp-sku-link" type="button" onClick={onOpen}>{row.productSku || "—"}</button> : <span className="cp-mono">{row.productSku || "—"}</span>;
    if (column.id === "productName") return row.productName || "—";
    if (column.id === "modelName") return row.modelName || "—";
    if (column.id === "scale") return row.scale || "—";
    if (column.id === "category") return row.category ? <span className="cp-cat-tag">{row.category}</span> : "—";
    if (column.id === "stock") return <StockBadge value={row.stock} />;
    if (column.id === "bomCount") return displayValue(row.bomCount);
    return <button className="cp-btn-ghost" type="button" onClick={onOpen}>Details</button>;
  }

  return (
    <tr>
      {columns.map((column) => <td key={column.id} data-label={column.label || "Action"} className={column.numeric ? "cp-num" : ""}>{content(column)}</td>)}
    </tr>
  );
}

function PartTableRow({ columns, row, token, canViewDetails, onOpen, onUnauthorized }: { columns: CustomerTableColumn[]; row: CustomerCatalogPart; token: string; canViewDetails: boolean; onOpen: () => void; onUnauthorized: () => void }) {
  function content(column: CustomerTableColumn) {
    if (column.id === "image") return <TableThumb hasImage={row.hasImage} token={token} path={`/api/customer-chat/parts/${row.partRef}/image`} alt={row.partName || row.partNumber} onUnauthorized={onUnauthorized} />;
    if (column.id === "partNumber") return canViewDetails ? <button className="cp-sku-link" type="button" onClick={onOpen}>{row.partNumber || "—"}</button> : <span className="cp-mono">{row.partNumber || "—"}</span>;
    if (column.id === "partName") return row.partName || "—";
    if (column.id === "status") return row.status || "—";
    if (column.id === "stock") return <StockBadge value={row.stock} />;
    return <button className="cp-btn-ghost" type="button" onClick={onOpen}>Details</button>;
  }

  return (
    <tr>
      {columns.map((column) => <td key={column.id} data-label={column.label || "Action"} className={column.numeric ? "cp-num" : ""}>{content(column)}</td>)}
    </tr>
  );
}

function ProductDetailPage({ token, recordId, canViewPrice, onNavigate, onUnauthorized }: { token: string; recordId: string; canViewPrice: boolean; onNavigate: (route: PortalRoute) => void; onUnauthorized: () => void }) {
  const [data, setData] = useState<CustomerProductDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [bomSortBy, setBomSortBy] = useState("partNumber");
  const [bomSortOrder, setBomSortOrder] = useState<"asc" | "desc">("asc");
  const [bomPage, setBomPage] = useState(1);
  const [bomPageSize, setBomPageSize] = useState<number>(() => {
    const stored = Number(window.localStorage.getItem("customer-bom-page-size-v2"));
    return [10, 20, 50, 100].includes(stored) ? stored : 10;
  });
  const bomColumnLayout = useCustomerTableLayout("customer-bom-columns-v1", BOM_COLUMNS);

  useEffect(() => {
    let active = true;
    setLoading(true);
    void requestJson<CustomerProductDetail>(`/api/customer-chat/catalog/products/${recordId}`, {}, token)
      .then((result) => { if (active) setData(result); })
      .catch((requestError) => {
        if (!active) return;
        if (requestError instanceof ApiError && requestError.status === 401) return onUnauthorized();
        setError(requestError instanceof Error ? requestError.message : "The product could not be loaded.");
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [onUnauthorized, recordId, token]);

  useEffect(() => {
    try {
      window.localStorage.setItem("customer-bom-page-size-v2", String(bomPageSize));
    } catch {
      // Keep the current page size for this session when storage is unavailable.
    }
  }, [bomPageSize]);

  const sortedBom = useMemo(() => {
    if (!data) return [];
    const direction = bomSortOrder === "asc" ? 1 : -1;
    return [...data.bom].sort((left, right) => direction * compareTableValues(bomValue(left, bomSortBy), bomValue(right, bomSortBy)));
  }, [bomSortBy, bomSortOrder, data]);
  const bomTotalPages = Math.max(1, Math.ceil(sortedBom.length / bomPageSize));
  const visibleBom = sortedBom.slice((bomPage - 1) * bomPageSize, bomPage * bomPageSize);
  const bomFirst = sortedBom.length ? ((bomPage - 1) * bomPageSize) + 1 : 0;
  const bomLast = bomFirst ? Math.min(sortedBom.length, bomFirst + visibleBom.length - 1) : 0;

  useEffect(() => {
    setBomPage((current) => Math.min(current, bomTotalPages));
  }, [bomTotalPages]);

  if (loading) return <PageLoading label="Loading product details…" />;
  if (error || !data) return <DetailError message={error || "Product not found."} onBack={() => onNavigate({ page: "products" })} />;
  const product = data.product;

  function changeBomSort(nextSort: string) {
    if (nextSort === bomSortBy) {
      setBomSortOrder((current) => current === "asc" ? "desc" : "asc");
    } else {
      setBomSortBy(nextSort);
      setBomSortOrder("asc");
    }
    setBomPage(1);
  }

  return (
    <section>
      <button className="cp-back-link" type="button" onClick={() => onNavigate({ page: "products" })}><ArrowLeft size={15} /> Back to products</button>
      <div className="cp-detail-hero">
        <div className="cp-thumb">
          {product.hasImage ? <AssetButton large token={token} path={`/api/customer-chat/products/${product.productRef}/image`} alt={product.productName || product.productSku} onUnauthorized={onUnauthorized} /> : <ImageIcon size={30} />}
        </div>
        <div>
          <div className="cp-eyebrow">Product</div>
          <h1>{product.productSku || "Product details"}</h1>
          <p>{product.productName || "—"}</p>
        </div>
        <div className="cp-hero-stock"><small>Current inventory</small><strong>{displayValue(product.stock)}</strong></div>
      </div>
      <div className="cp-metrics" aria-label="Product inventory overview">
        <ProductMetric label="Stock" value={product.stock} />
        <ProductMetric label="Sold Total" value={product.soldTotal} />
        {canViewPrice && <ProductMetric label="Price" value={product.price} currency />}
        {canViewPrice && <ProductMetric label="Stock Value" value={product.stockValue} currency />}
        {canViewPrice && <ProductMetric label="Prepaid Stock" value={product.prepaidStock} currency />}
        <ProductMetric label="Prod. Calc" value={product.productionCalculation} />
      </div>
      <div className="cp-detail-facts">
        <DetailFact label="Model" value={product.modelName} /><DetailFact label="Scale" value={product.scale} /><DetailFact label="Category" value={product.category} /><DetailFact label="BOM lines" value={data.bomFoundCount} />
      </div>
      <ProductImageGallery token={token} product={product} images={data.images ?? []} onUnauthorized={onUnauthorized} />
      <div className="cp-section-head">
        <h2>Bill of Materials</h2>
        <span>Parts and inventory required for this product</span>
        <div className="cp-right">
          <span>{data.bomReturnedCount} of {data.bomFoundCount} lines</span>
          <button className="cp-btn-ghost" type="button" onClick={bomColumnLayout.resetColumns}><RotateCcw size={13} /> Reset columns</button>
        </div>
      </div>
      {data.bomTruncated && <div className="cp-detail-warning" role="status">{data.warnings.find((warning) => warning.includes("BOM"))}</div>}
      <p className="cp-table-hint">Click a field name to sort. Drag a header to reorder it, or drag its right edge to resize.</p>
      <div className="cp-table-wrap">
        <table className="cp-table" style={tableStyle(bomColumnLayout.totalWidth)}>
          <colgroup>{bomColumnLayout.columns.map((column) => <col key={column.id} style={{ width: bomColumnLayout.widths[column.id] ?? column.width }} />)}</colgroup>
          <CustomerTableHeader
            columns={bomColumnLayout.columns}
            widths={bomColumnLayout.widths}
            sortBy={bomSortBy}
            sortOrder={bomSortOrder}
            onSort={changeBomSort}
            onResize={bomColumnLayout.resizeColumn}
            onMove={bomColumnLayout.moveColumn}
          />
          <tbody>{visibleBom.map((line, index) => <tr key={line.lineRef || `${line.partNumber}-${index}`}>
            {bomColumnLayout.columns.map((column) => (
              <td key={column.id} data-label={column.label || "Field"} className={column.numeric ? "cp-num" : ""}>
                {column.id === "partNumber"
                  ? <span className="cp-mono">{displayValue(bomValue(line, column.id))}</span>
                  : column.id === "stock"
                    ? <StockBadge value={line.stock} />
                    : displayValue(bomValue(line, column.id))}
              </td>
            ))}
          </tr>)}</tbody>
        </table>
        {data.bom.length === 0 && <div className="cp-table-state">No BOM lines are available for this product.</div>}
        {data.bom.length > 0 && <nav className="cp-pager" aria-label="BOM pages">
          <div className="cp-page-summary">
            <span>{bomFirst.toLocaleString("en-US")}–{bomLast.toLocaleString("en-US")} of {data.bom.length.toLocaleString("en-US")}</span>
            <label>Rows per page
              <select value={bomPageSize} onChange={(event) => { setBomPageSize(Number(event.target.value)); setBomPage(1); }}>
                <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
              </select>
            </label>
          </div>
          {bomTotalPages > 1 && <div className="cp-page-buttons">
            <button type="button" onClick={() => setBomPage((current) => current - 1)} disabled={bomPage <= 1}><ChevronLeft size={14} /> Prev</button>
            {visiblePages(bomPage, bomTotalPages).map((pageNumber) => <button key={pageNumber} className={pageNumber === bomPage ? "active" : ""} type="button" onClick={() => setBomPage(pageNumber)} disabled={pageNumber === bomPage}>{pageNumber}</button>)}
            <button type="button" onClick={() => setBomPage((current) => current + 1)} disabled={bomPage >= bomTotalPages}>Next <ChevronRight size={14} /></button>
          </div>}
        </nav>}
      </div>
    </section>
  );
}

function ProductMetric({ label, value, currency = false }: { label: string; value: number | string | null | undefined; currency?: boolean }) {
  return <div className={`cp-metric ${currency ? "money" : ""}`}><small>{label}</small><strong>{currency ? displayCurrency(value) : displayValue(value)}</strong></div>;
}

function PartDetailPage({ token, recordId, onNavigate, onUnauthorized }: { token: string; recordId: string; onNavigate: (route: PortalRoute) => void; onUnauthorized: () => void }) {
  const [data, setData] = useState<CustomerPartDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [relatedSortBy, setRelatedSortBy] = useState("productSku");
  const [relatedSortOrder, setRelatedSortOrder] = useState<"asc" | "desc">("asc");
  const [relatedPage, setRelatedPage] = useState(1);
  const [selectedRelatedProduct, setSelectedRelatedProduct] = useState<CustomerPartDetail["relatedProducts"][number] | null>(null);
  const [relatedProductPreview, setRelatedProductPreview] = useState<CustomerProductDetail | null>(null);
  const [relatedProductPreviewLoading, setRelatedProductPreviewLoading] = useState(false);
  const [relatedProductPreviewError, setRelatedProductPreviewError] = useState("");
  const [relatedPageSize, setRelatedPageSize] = useState<number>(() => {
    const stored = Number(window.localStorage.getItem("customer-related-products-page-size-v2"));
    return [10, 20, 50, 100].includes(stored) ? stored : 10;
  });
  const relatedColumnLayout = useCustomerTableLayout("customer-related-products-columns-v1", RELATED_PRODUCT_COLUMNS);

  useEffect(() => {
    let active = true;
    void requestJson<CustomerPartDetail>(`/api/customer-chat/catalog/parts/${recordId}`, {}, token)
      .then((result) => { if (active) setData(result); })
      .catch((requestError) => {
        if (!active) return;
        if (requestError instanceof ApiError && requestError.status === 401) return onUnauthorized();
        setError(requestError instanceof Error ? requestError.message : "The part could not be loaded.");
      }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [onUnauthorized, recordId, token]);

  useEffect(() => {
    try {
      window.localStorage.setItem("customer-related-products-page-size-v2", String(relatedPageSize));
    } catch {
      // Keep the current page size for this session when storage is unavailable.
    }
  }, [relatedPageSize]);

  const sortedRelatedProducts = useMemo(() => {
    if (!data) return [];
    const direction = relatedSortOrder === "asc" ? 1 : -1;
    const key = relatedSortBy as "productSku" | "productName";
    return [...data.relatedProducts].sort((left, right) => direction * compareTableValues(left[key], right[key]));
  }, [data, relatedSortBy, relatedSortOrder]);
  const relatedTotalPages = Math.max(1, Math.ceil(sortedRelatedProducts.length / relatedPageSize));
  const visibleRelatedProducts = sortedRelatedProducts.slice((relatedPage - 1) * relatedPageSize, relatedPage * relatedPageSize);
  const relatedFirst = sortedRelatedProducts.length ? ((relatedPage - 1) * relatedPageSize) + 1 : 0;
  const relatedLast = relatedFirst ? Math.min(sortedRelatedProducts.length, relatedFirst + visibleRelatedProducts.length - 1) : 0;

  useEffect(() => {
    setRelatedPage((current) => Math.min(current, relatedTotalPages));
  }, [relatedTotalPages]);

  useEffect(() => {
    if (!selectedRelatedProduct) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedRelatedProduct(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectedRelatedProduct]);

  useEffect(() => {
    if (!selectedRelatedProduct) {
      setRelatedProductPreview(null);
      setRelatedProductPreviewError("");
      return;
    }
    let active = true;
    setRelatedProductPreview(null);
    setRelatedProductPreviewError("");
    setRelatedProductPreviewLoading(true);
    void requestJson<CustomerProductDetail>(`/api/customer-chat/catalog/products/${selectedRelatedProduct.productRef}`, {}, token)
      .then((result) => { if (active) setRelatedProductPreview(result); })
      .catch((requestError) => {
        if (!active) return;
        if (requestError instanceof ApiError && requestError.status === 401) return onUnauthorized();
        setRelatedProductPreviewError(requestError instanceof Error ? requestError.message : "The product preview could not be loaded.");
      })
      .finally(() => { if (active) setRelatedProductPreviewLoading(false); });
    return () => { active = false; };
  }, [onUnauthorized, selectedRelatedProduct, token]);

  if (loading) return <PageLoading label="Loading part details…" />;
  if (error || !data) return <DetailError message={error || "Part not found."} onBack={() => onNavigate({ page: "parts" })} />;
  const part = data.part;

  function changeRelatedSort(nextSort: string) {
    if (nextSort === relatedSortBy) {
      setRelatedSortOrder((current) => current === "asc" ? "desc" : "asc");
    } else {
      setRelatedSortBy(nextSort);
      setRelatedSortOrder("asc");
    }
    setRelatedPage(1);
  }

  function openRelatedProductDetail() {
    if (!selectedRelatedProduct) return;
    const productRef = selectedRelatedProduct.productRef;
    setSelectedRelatedProduct(null);
    onNavigate({ page: "product-detail", recordId: productRef });
  }

  return (
    <>
      <section>
        <button className="cp-back-link" type="button" onClick={() => onNavigate({ page: "parts" })}><ArrowLeft size={15} /> Back to parts</button>
        <div className="cp-detail-hero">
          <div className="cp-thumb">
            {part.hasImage ? <AssetButton large token={token} path={`/api/customer-chat/parts/${part.partRef}/image`} alt={part.partName || part.partNumber} onUnauthorized={onUnauthorized} /> : <ImageIcon size={30} />}
          </div>
          <div>
            <div className="cp-eyebrow">Part</div>
            <h1>{part.partNumber || "Part details"}</h1>
            <p>{part.partName || "—"}</p>
          </div>
          <div className="cp-hero-stock"><small>Current inventory</small><strong>{displayValue(part.stock)}</strong></div>
        </div>
        <div className="cp-detail-facts">
          <DetailFact label="Part No." value={part.partNumber} /><DetailFact label="Safety Stock Qty" value={part.safetyStock} /><DetailFact label="Inventory" value={part.stock} /><DetailFact label="Turnover" value={part.turnover} /><DetailFact label="Created" value={part.created} /><DetailFact label="Status" value={part.status} />
        </div>
        <div className="cp-section-head">
          <h2>Related Products</h2>
          <span>Products that use this part in their bill of materials</span>
          <div className="cp-right">
            <span>{data.relatedProducts.length} products</span>
            <button className="cp-btn-ghost" type="button" onClick={relatedColumnLayout.resetColumns}><RotateCcw size={13} /> Reset columns</button>
          </div>
        </div>
        <p className="cp-table-hint">Click a product to preview it. Click a field name to sort, drag a header to reorder it, or drag its right edge to resize.</p>
        <div className="cp-table-wrap">
          <table className="cp-table" style={tableStyle(relatedColumnLayout.totalWidth)}>
            <colgroup>{relatedColumnLayout.columns.map((column) => <col key={column.id} style={{ width: relatedColumnLayout.widths[column.id] ?? column.width }} />)}</colgroup>
            <CustomerTableHeader
              columns={relatedColumnLayout.columns}
              widths={relatedColumnLayout.widths}
              sortBy={relatedSortBy}
              sortOrder={relatedSortOrder}
              onSort={changeRelatedSort}
              onResize={relatedColumnLayout.resizeColumn}
              onMove={relatedColumnLayout.moveColumn}
            />
            <tbody>{visibleRelatedProducts.map((product) => <tr key={product.productRef || product.productSku}>
              {relatedColumnLayout.columns.map((column) => <td key={column.id} data-label={column.label || "Action"}>
                {column.id === "productSku" ? <button className="cp-sku-link" type="button" onClick={() => setSelectedRelatedProduct(product)}>{product.productSku || "—"}</button>
                  : column.id === "productName" ? product.productName || "—"
                    : <button className="cp-btn-ghost" type="button" onClick={() => setSelectedRelatedProduct(product)}>Preview</button>}
              </td>)}
            </tr>)}</tbody>
          </table>
          {data.relatedProducts.length === 0 && <div className="cp-table-state">No related products were found for this part.</div>}
          {data.relatedProducts.length > 0 && <nav className="cp-pager" aria-label="Related product pages">
            <div className="cp-page-summary">
              <span>{relatedFirst.toLocaleString("en-US")}–{relatedLast.toLocaleString("en-US")} of {data.relatedProducts.length.toLocaleString("en-US")}</span>
              <label>Rows per page
                <select value={relatedPageSize} onChange={(event) => { setRelatedPageSize(Number(event.target.value)); setRelatedPage(1); }}>
                  <option value={10}>10</option><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option>
                </select>
              </label>
            </div>
            {relatedTotalPages > 1 && <div className="cp-page-buttons">
              <button type="button" onClick={() => setRelatedPage((current) => current - 1)} disabled={relatedPage <= 1}><ChevronLeft size={14} /> Prev</button>
              {visiblePages(relatedPage, relatedTotalPages).map((pageNumber) => <button key={pageNumber} className={pageNumber === relatedPage ? "active" : ""} type="button" onClick={() => setRelatedPage(pageNumber)} disabled={relatedPage === relatedPage}>{pageNumber}</button>)}
              <button type="button" onClick={() => setRelatedPage((current) => current + 1)} disabled={relatedPage >= relatedTotalPages}>Next <ChevronRight size={14} /></button>
            </div>}
          </nav>}
        </div>
      </section>

      {selectedRelatedProduct && (
        <div className="cp-modal-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelectedRelatedProduct(null);
        }}>
          <section className="cp-modal" role="dialog" aria-modal="true" aria-labelledby="cp-related-modal-title">
            <header className="cp-modal-header">
              <div>
                <span className="cp-eyebrow">Product preview</span>
                <h2 id="cp-related-modal-title">{selectedRelatedProduct.productSku || "Product"}</h2>
                <p>{selectedRelatedProduct.productName || "—"}</p>
              </div>
              <button className="cp-icon-btn" type="button" onClick={() => setSelectedRelatedProduct(null)} aria-label="Close product preview" autoFocus><X size={17} /></button>
            </header>
            <div className="cp-modal-body">
              {relatedProductPreviewLoading && <div className="cp-modal-loading"><Loader2 className="spin" size={18} /> Loading product preview…</div>}
              {relatedProductPreviewError && <div className="cp-error" role="alert">{relatedProductPreviewError}</div>}
              {relatedProductPreview && (
                <div className="cp-modal-main">
                  <div className="cp-thumb">
                    {relatedProductPreview.product.hasImage
                      ? <AssetButton large token={token} path={`/api/customer-chat/products/${relatedProductPreview.product.productRef}/image`} alt={relatedProductPreview.product.productName || relatedProductPreview.product.productSku} onUnauthorized={onUnauthorized} />
                      : <ImageIcon size={28} />}
                  </div>
                  <div className="cp-modal-facts">
                    <DetailFact label="Product No." value={relatedProductPreview.product.productSku} />
                    <DetailFact label="Inventory" value={relatedProductPreview.product.stock} />
                    <DetailFact label="Scale" value={relatedProductPreview.product.scale} />
                    <DetailFact label="Category" value={relatedProductPreview.product.category} />
                    <DetailFact label="BOM Lines" value={relatedProductPreview.product.bomCount} />
                    <DetailFact label="Prod. Calc" value={relatedProductPreview.product.productionCalculation} />
                  </div>
                </div>
              )}
            </div>
            <footer className="cp-modal-footer">
              <button className="cp-btn-ghost" type="button" onClick={() => setSelectedRelatedProduct(null)}>Close</button>
              <button className="cp-btn-mini" type="button" onClick={openRelatedProductDetail}>Open product detail <ChevronRight size={14} /></button>
            </footer>
          </section>
        </div>
      )}
    </>
  );
}

function DetailFact({ label, value }: { label: string; value: number | string | null | undefined }) {
  return <div className="cp-fact"><small>{label}</small><strong>{displayValue(value)}</strong></div>;
}

function PageLoading({ label }: { label: string }) {
  return <div className="cp-page-loading"><Loader2 className="spin" size={20} /> {label}</div>;
}

function DetailError({ message, onBack }: { message: string; onBack: () => void }) {
  return <div className="cp-detail-error"><p>{message}</p><button className="cp-back-link" type="button" onClick={onBack}><ArrowLeft size={15} /> Back to catalog</button></div>;
}

export type SessionResponse = {
  token: string;
  sessionId: string;
  context: {
    sessionId: string;
    productSku: string;
    orderId: string;
    bomCalcId: string;
    customerId: string;
    customerName: string;
    currency: string;
    operator: {
      account: string;
      name: string;
      privilege: string;
    };
    access: WebViewerPermissions;
  };
  readOnly: boolean;
  bomWriteEnabled: boolean;
};

export type WebViewerPermissions = {
  canViewPrice: boolean;
  canManageAccounts: boolean;
  canViewProducts: boolean;
  canViewOrders: boolean;
  canViewInventory: boolean;
  canViewBom: boolean;
  canUseNaturalQuery: boolean;
  canManageRag: boolean;
  canMergeOrders: boolean;
};

export type WebViewerAdminAccount = {
  username: string;
  displayName: string;
  filemakerPrivilegeSet: string;
  enabled: boolean;
  permissions: WebViewerPermissions;
  inheritsPrivilegeSet: boolean;
  origin: string;
  lastSeenAt: string | null;
  updatedAt: string;
  updatedBy: string;
};

export type WebViewerAdminPrivilegeSet = {
  name: string;
  enabled: boolean;
  permissions: WebViewerPermissions;
  accountCount: number;
  updatedAt: string;
  updatedBy: string;
};

export type WebViewerAccountAdminResponse = {
  accounts: WebViewerAdminAccount[];
  privilegeSets: WebViewerAdminPrivilegeSet[];
};

export type ProductInfo = {
  productSku: string;
  productName: string;
  productNameCn: string;
  raw?: Record<string, unknown>;
};

export type ProductBomRow = {
  recordId: string;
  productSku: string;
  partNo: string;
  partName: string;
  requiredQty: number | string | null;
  costQty: number | string | null;
};

export type ProductBomResponse = {
  product: ProductInfo | null;
  rows: ProductBomRow[];
  foundCount: number;
};

export type CalcStatus = "未计算" | "待确认" | "已确认";
export type ThemeMode = "light" | "dark";
// BOM 单页工作台内的阶段：选产品 → 读BOM → 计算数量 → 微调 → 确认
export type BomStep = "select" | "bom" | "calc" | "done";
export type Page =
  | "home"
  | "productInventory"
  | "internalOrderMerge"
  | "orderDetail"
  | "bom" // 合并后的 BOM 计算单页工作台
  | "product" // 旧：产品 BOM 页（保留兼容，导航不再指向）
  | "issue" // 旧：计算单页（保留兼容，导航不再指向）
  | "kitIssue"
  | "businessProducts"
  | "businessProductDetail"
  | "ragControl"
  | "accessAdmin";

export type InternalOrderRow = {
  orderId: string;
  recordId: string;
  internalOrderNo: string;
  piNo: string;
  customerPo: string;
  orderDate: string;
  amount?: number;
  summary: string;
  orderCategory: string;
  orderConfirmation: string;
  tags: string[];
  packagingStatus: string;
  paymentStatus: string;
  elapsedDays: string;
  customerName: string;
};

export type OrderScope = "internal" | "all";

export type InternalOrdersResponse = {
  customerId: string;
  customerName: string;
  currency: string;
  scope: OrderScope;
  rows: InternalOrderRow[];
  foundCount: number;
  returnedCount: number;
  sourceFoundCount: number;
  unmergeableCount: number;
  truncated: boolean;
  layout: string;
  readOnly: boolean;
  webMergeEnabled: boolean;
};

export type InventoryMovementType = "in" | "out";

export type InventoryTransactionRow = {
  recordId: string;
  date: string;
  year: number;
  type: InventoryMovementType;
  orderBatchNo: string;
  description: string;
  inboundQty: number;
  outboundQty: number;
  signedQty: number;
  balance: number;
  operator: string;
};

export type InventoryTrendPoint = {
  date: string;
  balance: number;
};

export type ProductInventoryResponse = {
  productSku: string;
  layout: string;
  rows: InventoryTransactionRow[];
  trend: InventoryTrendPoint[];
  summary: {
    currentStock: number;
    inboundTotal: number;
    outboundTotal: number;
    netChange: number;
  };
  foundCount: number;
  returnedCount: number;
  readOnly: boolean;
};

export type BusinessProductFilters = {
  category: string;
  model: string;
  audit: string;
  client: string;
};

export type BusinessProductFieldGroup = {
  name: string;
  fields: Record<string, unknown>;
};

export type BusinessProductPortalGroup = {
  name: string;
  rows: Record<string, unknown>[];
};

export type BusinessProductRow = {
  recordId: string;
  modId?: string | null;
  productSku: string;
  systemProductSku: string;
  productName: string;
  productNameCn: string;
  imageUrl: string;
  selectedFileUrl: string;
  qrCodeUrl: string;
  modelName: string;
  scale: string;
  category: string;
  auditStatus: string;
  imageStatus: string;
  stock: number | string | null;
  stockUsd: number | string | null;
  prepaidStockUsd: number | string | null;
  bomCount: number | string | null;
  orderQty: number | string | null;
  bomDate: string;
  vendor: string;
  client: string;
  customer: string;
  privilege: string;
  category1: string;
  category2: string;
  category3: string;
  labelSpec: string;
  packagingHours: number | string | null;
  packageCheck: string;
  dmsStatus: string;
  raw: Record<string, unknown>;
  mainFields: Record<string, unknown>;
  relatedFieldGroups: BusinessProductFieldGroup[];
  portals: BusinessProductPortalGroup[];
};

export type BusinessProductsResponse = {
  layout: string;
  rows: BusinessProductRow[];
  foundCount: number;
  returnedCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  query: string;
  filters: BusinessProductFilters;
};

export type BusinessProductDetailResponse = {
  layout: string;
  product: BusinessProductRow;
};

export type NaturalLanguageDateRange = {
  label: string;
  start: string;
  end: string;
  field?: string | null;
};

export type NaturalLanguageQueryPlan = {
  domain: string;
  intent: string;
  layout: string;
  description: string;
  query: Record<string, unknown>[];
  sort: { fieldName: string; sortOrder: string }[];
  keywords: string[];
  filters: Record<string, string>;
  dateRange?: NaturalLanguageDateRange | null;
  warnings: string[];
};

export type NaturalLanguageQueryResponse = {
  answer: string;
  layout: string;
  rows: BusinessProductRow[];
  foundCount: number;
  returnedCount: number;
  plan: NaturalLanguageQueryPlan;
  source?: "filemaker" | "rag-cache" | string;
  requiresClarification?: boolean;
  clarificationQuestion?: string | null;
  clarificationOptions?: string[];
  ragHits?: {
    layout: string;
    recordId: string;
    title: string;
    snippet: string;
    score: number;
    fields: Record<string, unknown>;
    updatedAt: string;
  }[];
};

export type NaturalQueryExchange = {
  id: string;
  prompt: string;
  response?: NaturalLanguageQueryResponse;
  error?: string;
};

export type RagIndexRun = {
  id: number;
  status: string;
  reason: string;
  startedAt: string;
  completedAt?: string | null;
  error?: string | null;
  layoutsIndexed: number;
  recordsIndexed: number;
};

export type RagIndexStatusResponse = {
  enabled: boolean;
  ftsEnabled: boolean;
  databasePath: string;
  layoutCount: number;
  recordCount: number;
  refreshIntervalSeconds: number;
  latestRun?: RagIndexRun | null;
  running: boolean;
  profiledLayouts: number;
};

export type RagIndexRefreshResponse = {
  accepted: boolean;
  message: string;
  status: RagIndexStatusResponse;
};

export type RagSearchHit = {
  layout: string;
  recordId: string;
  title: string;
  snippet: string;
  score: number;
  fields: Record<string, unknown>;
  updatedAt: string;
};

export type RagSearchResponse = {
  query: string;
  hits: RagSearchHit[];
};

export type NaturalQueryAnalyticsRunResponse = {
  analyzed: number;
  meaningful: number;
  ignored: number;
};

export type NaturalQueryTopQuestion = {
  canonicalQuestion: string;
  normalizedKey: string;
  domain: string;
  intent: string;
  count: number;
  examplePrompts: string[];
  lastAskedAt: string;
};

export type NaturalQueryTopQuestionsResponse = {
  days: number;
  analyzedPending: NaturalQueryAnalyticsRunResponse;
  questions: NaturalQueryTopQuestion[];
};

export type ODataRelationshipInfo = {
  name: string;
  label: string;
  description: string;
  fromTable: string;
  fromField: string;
  linkTable: string;
  linkFromField: string;
  linkToField: string;
  targetTable: string;
  targetLookupFields: string[];
  source: string;
  confidence: number;
};

export type ODataRelationshipsResponse = {
  mappingPath: string;
  mappingSource: string;
  mappingVersion: string;
  entityCount: number;
  queryStrategyCount: number;
  warnings: string[];
  relationships: ODataRelationshipInfo[];
};

export type CalculationLine = {
  lineNo: number;
  sourceBomRecordId: string;
  partNo: string;
  partName: string;
  bomQty: number;
  stockSnapshot: number | null;
  calculatedQty: number;
  actualQty: number | null;
  warehouse: string;
  position1: string;
  position2: string;
  issueTime: string;
  raw: Record<string, unknown>;
};

export type CalculationPreview = {
  calculationId: string;
  createdAt: string;
  status: "待确认";
  product: ProductInfo | null;
  generateQty: number;
  lines: CalculationLine[];
};

export type ConfirmedDocument = {
  id: string;
  documentNo: string;
  status: "confirmed";
  productSku: string;
  productName: string;
  productNameCn: string;
  generateQty: number;
  lineCount: number;
  createdAt: string;
  lines: CalculationLine[];
};

export type PartInfo = {
  partNo: string;
  partName: string;
  stockSnapshot: number | null;
  warehouse: string;
  position1: string;
  position2: string;
};

export type PartSearchResponse = {
  rows: PartInfo[];
  foundCount: number;
  returnedCount: number;
};

export type KitIssueField = {
  source: string;
  label: string;
  role: string;
  result: string;
};

export type KitIssueRow = {
  recordId: string;
  modId?: string | null;
  lineNo: number;
  orderNo: string;
  orderDate: string;
  customer: string;
  productSku: string;
  productNameCn: string;
  productQty: number | string | null;
  partNo: string;
  partName: string;
  warehouseDivision: string;
  productWarehouseDivision: string;
  position1: string;
  position2: string;
  ratedQty: number | string | null;
  stockQty: number | string | null;
  quantity: number | string | null;
  shippingQty: number | string | null;
  actualQty: number | string | null;
  orderSummaryCn: string;
  productionReceiptStatus: string;
  outboundId: string;
  issueTime: string;
  batchPrice: number | string | null;
  returnQty: number | string | null;
  raw: Record<string, unknown>;
};

export type KitIssueRecordsResponse = {
  layout: string;
  rows: KitIssueRow[];
  foundCount: number;
  returnedCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  orderNo: string;
  fields: KitIssueField[];
};

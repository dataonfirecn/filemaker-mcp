export type SessionResponse = {
  token: string;
  sessionId: string;
  context: {
    sessionId: string;
    productSku: string;
    orderId: string;
    bomCalcId: string;
    operator: {
      account: string;
      name: string;
      privilege: string;
    };
  };
  readOnly: boolean;
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
export type Page = "home" | "product" | "issue" | "kitIssue";

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

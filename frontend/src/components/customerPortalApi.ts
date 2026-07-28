const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";

export type CustomerAccessRole = "admin" | "manager" | "team" | "agent";

export function customerAccessRolePermissions(role: CustomerAccessRole) {
  return {
    canViewOrders: role !== "agent",
    canViewDetails: role !== "agent",
    isAdmin: role === "admin"
  };
}

export type CustomerProfile = {
  username: string;
  displayName: string;
  clientName: string;
  accessRole: CustomerAccessRole;
  canViewPrice: boolean;
  canViewOrders: boolean;
  canViewDetails: boolean;
  isAdmin: boolean;
};

export function normalizeCustomerProfile(profile: CustomerProfile): CustomerProfile {
  const accessRole = profile.accessRole
    ?? (profile.isAdmin ? "admin" : "team");
  const permissions = customerAccessRolePermissions(accessRole);
  return {
    ...profile,
    accessRole,
    canViewPrice: profile.canViewPrice ?? false,
    canViewOrders: profile.canViewOrders ?? permissions.canViewOrders,
    canViewDetails: profile.canViewDetails ?? permissions.canViewDetails,
    isAdmin: profile.isAdmin ?? permissions.isAdmin
  };
}

export type CustomerPasswordChangeResponse = {
  token: string;
  expiresAt: number;
  customer: CustomerProfile;
  message: string;
};

export type CustomerProductQueryRow = {
  entityType: "product" | "part";
  productRef: string;
  productSku: string;
  productName: string;
  modelName: string;
  scale: string;
  category: string;
  stock: number | string | null;
  hasImage: boolean;
  price?: number | string | null;
};

export type CustomerOrderQueryRow = {
  entityType: "order";
  orderRef: string;
  clientName: string;
  orderNumber: string;
  orderAmount: number | string | null;
  shippingCompany: string;
  trackingNumber: string;
  shippingCost: number | string | null;
  shippedDate: string;
  shippingStatus: string;
  remarks: string;
};

export type CustomerQueryRow = CustomerProductQueryRow | CustomerOrderQueryRow;

export type CustomerQueryResponse = {
  resultType: "product" | "part" | "order";
  answer: string;
  rows: CustomerQueryRow[];
  foundCount: number;
  returnedCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  requiresClarification: boolean;
  clarificationOptions: string[];
  historyId?: number | null;
};

export type CustomerChatHistoryItem = {
  id: number;
  requestId: string;
  operatorAccount: string;
  operatorName: string;
  clientName: string;
  channel: string;
  prompt: string;
  domain: string;
  intent: string;
  resultType: string;
  status: string;
  httpStatus: number;
  blockedReason: string;
  answer: string;
  foundCount: number;
  returnedCount: number;
  durationMs: number;
  sourceLayout: string;
  isTest: boolean;
  createdAt: string;
};

export type CustomerChatHistoryResponse = {
  rows: CustomerChatHistoryItem[];
  foundCount: number;
  returnedCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
};

export type CustomerQuestionSummaryItem = {
  normalizedKey: string;
  canonicalQuestion: string;
  domain: string;
  intent: string;
  totalCount: number;
  successCount: number;
  noResultCount: number;
  clarificationCount: number;
  blockedCount: number;
  errorCount: number;
  lastAskedAt: string;
};

export type CustomerQuestionSummaryResponse = {
  days: number;
  questions: CustomerQuestionSummaryItem[];
};

export type CustomerAdminAccount = {
  username: string;
  displayName: string;
  email: string;
  clientName: string;
  productPrivilege: string;
  partCustomerId: string;
  shipmentCompanyId: string;
  enabled: boolean;
  accessRole: CustomerAccessRole;
  canViewPrice: boolean;
  canViewOrders: boolean;
  canViewDetails: boolean;
  isAdmin: boolean;
  lastLoginAt: string | null;
  lastLoginStatus: string;
  lastSuccessfulLoginAt: string | null;
  lastFailedLoginAt: string | null;
  successfulLoginCount: number;
  failedLoginCount: number;
  updatedAt: string;
  updatedBy: string;
  credentialsEmailAvailableAt: string | null;
  credentialsEmailSent?: boolean | null;
  credentialsEmailError?: string;
};

export type CustomerAdminAccountsResponse = {
  accounts: CustomerAdminAccount[];
  emailDeliveryEnabled: boolean;
};

export type CustomerCredentialsEmailLogItem = {
  id: number;
  username: string;
  recipientEmail: string;
  status: "success" | "failed" | "blocked";
  message: string;
  createdAt: string;
};

export type CustomerCredentialsEmailLogResponse = {
  logs: CustomerCredentialsEmailLogItem[];
};

export type CustomerAccountBulkStatusResponse = {
  accounts: CustomerAdminAccount[];
  updatedCount: number;
  enabled: boolean;
};

export function normalizeCustomerAdminAccount(account: CustomerAdminAccount): CustomerAdminAccount {
  const profile = normalizeCustomerProfile(account);
  return { ...account, ...profile };
}

export type CustomerCatalogProduct = {
  productRef: string;
  productSku: string;
  productName: string;
  modelName: string;
  scale: string;
  category: string;
  stock: number | string | null;
  bomCount: number | string | null;
  hasImage: boolean;
};

export type CustomerCatalogPart = {
  partRef: string;
  partNumber: string;
  partName: string;
  stock: number | string | null;
  safetyStock: number | string | null;
  turnover: string;
  created: string;
  status: string;
  hasImage: boolean;
};

export type CustomerCatalogOrder = {
  orderRef: string;
  clientName: string;
  orderNumber: string;
  orderAmount: number | string | null;
  shippingCompany: string;
  trackingNumber: string;
  shippingCost: number | string | null;
  shippedDate: string;
  shippingStatus: string;
  remarks: string;
};

export type CustomerOrderSummary = {
  orderAmountTotal: number | null;
  orderCount: number;
  shippedCount: number;
  notShippedCount: number;
  month: string;
  shippingStatus: "all" | "shipped" | "notShipped";
};

export type CustomerCatalogPage<T> = {
  rows: T[];
  foundCount: number;
  returnedCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  query: string;
  sortBy: string;
  sortOrder: "asc" | "desc";
};

export type CustomerBomLine = {
  lineRef: string;
  partNumber: string;
  clientPartNumber: string;
  partName: string;
  bomQuantity: number | string | null;
  requiredQuantity: number | string | null;
  stock: number | string | null;
  status: string;
  sparePartNumber: string;
  spareStock: number | string | null;
};

export type CustomerProductDetail = {
  product: CustomerCatalogProduct & {
    soldTotal: number | string | null;
    price?: number | string | null;
    stockValue: number | string | null;
    prepaidStock: number | string | null;
    productionCalculation: number | string | null;
  };
  images: Array<{
    assetRef: string;
    filename: string;
    title: string;
    sortOrder: number;
    isPrimary: boolean;
  }>;
  imageCount: number;
  bom: CustomerBomLine[];
  bomFoundCount: number;
  bomReturnedCount: number;
  bomTruncated: boolean;
  warnings: string[];
};

export type CustomerPartDetail = {
  part: CustomerCatalogPart;
  relatedProducts: Array<{
    productRef: string;
    productSku: string;
    productName: string;
  }>;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function requestJson<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {})
    }
  });
  if (!response.ok) {
    let message = "The request could not be completed. Please try again.";
    try {
      const payload = await response.json() as { detail?: { message?: string } | string };
      if (typeof payload.detail === "string" && payload.detail) message = payload.detail;
      if (typeof payload.detail === "object" && payload.detail?.message) message = payload.detail.message;
    } catch {
      // Keep the customer-safe fallback for non-JSON responses.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function requestAsset(path: string, token: string): Promise<Blob> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { Accept: "image/*, application/pdf, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    let message = "The file could not be loaded.";
    try {
      const payload = await response.json() as { detail?: { message?: string } };
      if (payload.detail?.message) message = payload.detail.message;
    } catch {
      // Keep the customer-safe fallback for non-JSON responses.
    }
    throw new ApiError(response.status, message);
  }
  return response.blob();
}

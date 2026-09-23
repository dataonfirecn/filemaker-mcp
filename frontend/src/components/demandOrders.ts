export type DemandOrder = {
  id: string; recordId: string; internalOrderNo: string; summary: string; company: string;
  orderDate: string; dueDate: string; completedDate: string; reviewStatus: string;
  purchaseStatus: string; type: string; createdBy: string; modifiedBy: string;
  modifiedAt: string; notes: string; method: string; bomId: string;
};
export type DemandLine = {
  id: string; partNo: string; partName: string; quantity: number | null;
  extraQuantity: number | null; receivedQuantity: number | null; dueDate: string;
  status: string; purchaseStatus: string; supplier: string; notes: string; extraNotes: string;
};
export type DemandList = { rows: DemandOrder[]; foundCount: number; page: number; pageSize: number; totalPages: number };
export type DemandDetail = { order: DemandOrder; items: DemandLine[]; foundCount: number; page: number; totalPages: number };

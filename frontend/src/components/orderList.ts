export type OrderListRow = {
  orderId: string; recordId: string; internalOrderNo: string; piNo: string; customerPo: string;
  customerName: string; orderDate: string; summary: string; orderCategory: string;
  orderConfirmation: string; packagingStatus: string; paymentStatus: string; elapsedDays: string;
  amount: number | null;
};
export type OrderList = { rows: OrderListRow[]; foundCount: number; page: number; pageSize: number; totalPages: number };

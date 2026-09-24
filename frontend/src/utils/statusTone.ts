import type { Tone } from "../components/ui";

const demandTones: Record<string, Tone> = {
  已審核: "success", 已审核: "success", 未審核: "warning", 未审核: "warning",
  已轉採購單: "success", 已转采购单: "success", 已完成: "success", 完成: "success",
  未完成: "warning", 未下單: "warning", 未下单: "warning", 已下單: "success", 已下单: "success",
  取消: "neutral", 已取消: "neutral", 缺料: "warning"
};
export function demandStatusTone(status: string): Tone { return demandTones[status] ?? "neutral"; }

// 订单列表的包装 / 付款状态来自 FileMaker 文字，只映射明确的完成与待办词，其余保持中性。
const orderTones: Record<string, Tone> = {
  已包装: "success", 已包裝: "success", 已完成: "success", 已收款: "success", 已付款: "success", 已结清: "success",
  还没好: "warning", 還沒好: "warning", 未包装: "warning", 未包裝: "warning", 未收款: "warning", 未付款: "warning", 部分收款: "warning",
  取消: "neutral", 已取消: "neutral"
};
export function orderStatusTone(status: string): Tone { return orderTones[status] ?? "neutral"; }

import type { Tone } from "../components/ui";

const demandTones: Record<string, Tone> = {
  已審核: "success", 已审核: "success", 未審核: "warning", 未审核: "warning",
  已轉採購單: "success", 已转采购单: "success", 已完成: "success", 完成: "success",
  未完成: "warning", 未下單: "warning", 未下单: "warning", 已下單: "success", 已下单: "success",
  取消: "neutral", 已取消: "neutral", 缺料: "warning"
};
export function demandStatusTone(status: string): Tone { return demandTones[status] ?? "neutral"; }

import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { CalcStatus } from "../types";

function statusClass(status: CalcStatus): string {
  switch (status) {
    case "未计算":
      return "pill";
    case "待确认":
      return "pill pending";
    case "已确认":
      return "pill success";
    default:
      return "pill";
  }
}

export type AppShellProps = {
  title: string;
  subtitle: string;
  calcStatus: CalcStatus;
  readOnly: boolean;
  operatorLabel: string;
  children?: ReactNode;
};

export default function AppShell({ title, subtitle, calcStatus, readOnly, operatorLabel, children }: AppShellProps) {
  return (
    <>
      <header className="app-shell">
        <div className="app-shell-top">
          <div>
            <h1>{title}</h1>
            <p className="app-shell-subtitle">{subtitle}</p>
          </div>
          <div className="app-shell-meta">
            {operatorLabel !== "-" && (
              <div className="meta-group">
                <span className="meta-label">操作员</span>
                <span className="meta-value">{operatorLabel}</span>
              </div>
            )}
            <span className={statusClass(calcStatus)}>{calcStatus}</span>
            {readOnly && (
              <span className="pill readonly">
                <ShieldCheck size={14} />
                FileMaker 只读
              </span>
            )}
          </div>
        </div>
      </header>
      {children}
    </>
  );
}

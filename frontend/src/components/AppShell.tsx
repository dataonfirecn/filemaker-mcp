import { ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { CalcStatus, ThemeMode } from "../types";
import ThemeToggle from "./ThemeToggle";

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
  calcStatus?: CalcStatus | null;
  readOnly: boolean;
  controlledWrite?: boolean;
  operatorLabel: string;
  theme: ThemeMode;
  onThemeToggle: () => void;
  children?: ReactNode;
};

export default function AppShell({
  title,
  subtitle,
  calcStatus,
  readOnly,
  controlledWrite = false,
  operatorLabel,
  theme,
  onThemeToggle,
  children
}: AppShellProps) {
  return (
    <>
      <header className="app-shell">
        <div className="app-shell-top">
          <div>
            <h1>{title}</h1>
            <p className="app-shell-subtitle">{subtitle}</p>
          </div>
          <div className="app-shell-meta">
            <ThemeToggle theme={theme} onToggle={onThemeToggle} />
            {operatorLabel !== "-" && (
              <div className="meta-group">
                <span className="meta-label">操作员</span>
                <span className="meta-value">{operatorLabel}</span>
              </div>
            )}
            {calcStatus && <span className={statusClass(calcStatus)}>{calcStatus}</span>}
            {controlledWrite ? (
              <span className="pill pending">
                <ShieldCheck size={14} />
                FileMaker 受控写入
              </span>
            ) : readOnly && (
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

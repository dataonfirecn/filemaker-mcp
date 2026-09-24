import { PanelLeftClose, PanelLeftOpen, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import type { CalcStatus, ThemeMode } from "../types";
import InternalUserMenu, { type InternalUserMenuUser } from "./InternalUserMenu";

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
  sidebarCollapsed?: boolean;
  onSidebarToggle?: () => void;
  title: string;
  subtitle: string;
  calcStatus?: CalcStatus | null;
  controlledWrite?: boolean;
  user: InternalUserMenuUser | null;
  canManageAccounts: boolean;
  theme: ThemeMode;
  onThemeToggle: () => void;
  onOpenSettings: () => void;
  onOpenAccountAdmin?: () => void;
  onSignOut: () => void;
  children?: ReactNode;
};

export default function AppShell({
  sidebarCollapsed = false,
  onSidebarToggle,
  title,
  subtitle,
  calcStatus,
  controlledWrite = false,
  user,
  canManageAccounts,
  theme,
  onThemeToggle,
  onOpenSettings,
  onOpenAccountAdmin,
  onSignOut,
  children
}: AppShellProps) {
  return (
    <>
      <header className="app-shell">
        <div className="app-shell-top">
          <div className="app-shell-title">
            {onSidebarToggle && <button className="app-sidebar-toggle" type="button"
              onClick={onSidebarToggle} aria-controls="main-navigation" aria-expanded={!sidebarCollapsed}
              aria-label={sidebarCollapsed ? "展开导航" : "收起导航"}
              title={sidebarCollapsed ? "展开导航" : "收起导航"}>
              {sidebarCollapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
            </button>}
            <div className="app-shell-heading">
              <h1>{title}</h1>
              {subtitle && <p className="app-shell-subtitle">{subtitle}</p>}
            </div>
          </div>
          <div className="app-shell-meta">
            {user && (
              <InternalUserMenu
                user={user}
                canManageAccounts={canManageAccounts}
                theme={theme}
                onThemeToggle={onThemeToggle}
                onOpenSettings={onOpenSettings}
                onOpenAccountAdmin={onOpenAccountAdmin}
                onSignOut={onSignOut}
              />
            )}
            {calcStatus && <span className={statusClass(calcStatus)}>{calcStatus}</span>}
            {controlledWrite ? (
              <span className="pill pending">
                <ShieldCheck size={14} />
                FileMaker 受控写入
              </span>
            ) : null}
          </div>
        </div>
      </header>
      {children}
    </>
  );
}

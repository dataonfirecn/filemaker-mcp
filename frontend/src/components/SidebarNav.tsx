import type { LucideIcon } from "lucide-react";
import { ChevronLeft, ChevronRight, Home, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import type { Page } from "../types";

export type SidebarNavItem = {
  id: Page;
  label: string;
  description: string;
  Icon: LucideIcon;
  badge?: string;
  disabled?: boolean;
  disabledReason?: string;
};

export type SidebarNavGroup = {
  id: string;
  label: string;
  items: SidebarNavItem[];
};

export type SidebarNavProps = {
  groups: SidebarNavGroup[];
  activePage: Page;
  onNavigate: (page: Page) => void;
  onGoHome?: () => void;
};

const storageKey = "starrc-sidebar-collapsed";

export default function SidebarNav({ groups, activePage, onNavigate, onGoHome }: SidebarNavProps) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(storageKey) === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(collapsed));
    } catch {
      // Ignore storage errors
    }
  }, [collapsed]);

  function toggle() {
    setCollapsed((prev) => !prev);
  }

  return (
    <aside className={["sidebar-nav", collapsed ? "collapsed" : ""].join(" ")} aria-label="主导航">
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <div className="sidebar-logo" aria-hidden="true">
            <img src="/starrc-mark.svg" alt="" />
          </div>
          <div className="sidebar-brand-text">
            <strong>StarRC</strong>
            <span>运营导航中心</span>
          </div>
        </div>
      </div>

      {onGoHome && (
        <button
          className={["sidebar-home-button", activePage === "home" ? "active" : ""].join(" ")}
          type="button"
          onClick={onGoHome}
          aria-current={activePage === "home" ? "page" : undefined}
          title="导航首页"
        >
          <span className="sidebar-item-icon" aria-hidden="true">
            <Home size={18} />
          </span>
          <span>导航首页</span>
        </button>
      )}

      <nav className="sidebar-groups" aria-label="模块导航">
        <div className="sidebar-channel-label">
          <Monitor size={13} />
          <span>浏览器工作台</span>
        </div>
        {groups.map((group) => (
          <div key={group.id} className="sidebar-group">
            <div className="sidebar-group-header">
              <span className="sidebar-group-label">{group.label}</span>
            </div>
            <ul className="sidebar-group-items">
              {group.items.map((item) => {
                const Icon = item.Icon;
                const isActive = item.id === activePage;
                const title = item.disabled ? item.disabledReason : `${item.label} · ${item.description}`;

                return (
                  <li key={item.id}>
                    <button
                      className={["sidebar-item", isActive ? "active" : "", item.disabled ? "disabled" : ""].join(
                        " "
                      )}
                      type="button"
                      onClick={() => {
                        if (!item.disabled) onNavigate(item.id);
                      }}
                      aria-current={isActive ? "page" : undefined}
                      aria-disabled={item.disabled}
                      title={title}
                    >
                      <span className="sidebar-item-icon" aria-hidden="true">
                        <Icon size={18} />
                      </span>
                      <span className="sidebar-item-body">
                        <span className="sidebar-item-label">{item.label}</span>
                        {item.badge && <span className="sidebar-item-badge">{item.badge}</span>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">
        <button
          className="sidebar-footer-toggle"
          type="button"
          onClick={toggle}
          title={collapsed ? "展开导航" : "折叠导航"}
          aria-label={collapsed ? "展开导航" : "折叠导航"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          <span>收起导航</span>
        </button>
      </div>
    </aside>
  );
}

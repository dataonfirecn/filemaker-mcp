import type { LucideIcon } from "lucide-react";
import { ChevronDown, ChevronRight, Home, Monitor } from "lucide-react";
import { useEffect, useState } from "react";
import type { Page } from "../types";

export type SidebarNavItem = {
  label: string;
  description: string;
  Icon: LucideIcon;
  badge?: string;
  disabled?: boolean;
  disabledReason?: string;
} & ({ id: Page; onOpen?: never } | { id: string; onOpen: () => void });

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
  collapsed: boolean;
};

const groupStorageKey = "starrc-sidebar-groups:v1";

function readGroupState(): Record<string, boolean> {
  try {
    const saved = JSON.parse(localStorage.getItem(groupStorageKey) || "{}");
    if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
    return Object.fromEntries(Object.entries(saved).filter(([, value]) => typeof value === "boolean")) as Record<string, boolean>;
  } catch {
    return {};
  }
}

export default function SidebarNav({ groups, activePage, onNavigate, onGoHome, collapsed }: SidebarNavProps) {
  const [closedGroups, setClosedGroups] = useState(readGroupState);
  const activeGroupId = groups.find((group) => group.items.some((item) => item.id === activePage))?.id;

  // Entering a page reveals its group, including navigation from the home page.
  useEffect(() => {
    if (activeGroupId) setClosedGroups((current) => current[activeGroupId] === false
      ? current : { ...current, [activeGroupId]: false });
  }, [activePage, activeGroupId]);

  useEffect(() => {
    try {
      localStorage.setItem(groupStorageKey, JSON.stringify(closedGroups));
    } catch {
      // Folding still works when storage is unavailable.
    }
  }, [closedGroups]);

  return (
    <aside id="main-navigation" className={["sidebar-nav", collapsed ? "collapsed" : ""].join(" ")} aria-label="主导航">
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
        {groups.map((group) => {
          const isActiveGroup = group.id === activeGroupId;
          const isClosed = closedGroups[group.id] ?? !isActiveGroup;
          return (
            <div key={group.id} className="sidebar-group">
              <button className={`sidebar-group-header${isActiveGroup ? " has-active-page" : ""}`}
                type="button" aria-expanded={!isClosed} aria-controls={`sidebar-group-${group.id}`}
                onClick={() => setClosedGroups((current) => ({ ...current, [group.id]: !isClosed }))}>
                <span className="sidebar-group-label">{group.label}</span>
                {isClosed ? <ChevronRight size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
              </button>
              <ul id={`sidebar-group-${group.id}`} className="sidebar-group-items" hidden={!collapsed && isClosed}>
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
                          if (!item.disabled) {
                            if (item.onOpen) item.onOpen();
                            else onNavigate(item.id);
                          }
                        }}
                        aria-label={item.label}
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
          );
        })}
      </nav>
    </aside>
  );
}

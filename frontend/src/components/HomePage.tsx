import type { LucideIcon } from "lucide-react";
import { ArrowRight, Database, PackageSearch } from "lucide-react";
import type { Page } from "../types";

export type HomePageNavItem = {
  id: Page;
  label: string;
  description: string;
  Icon: LucideIcon;
  disabled?: boolean;
  disabledReason?: string;
};

export type HomePageProps = {
  navItems: HomePageNavItem[];
  onNavigate: (page: Page) => void;
  operatorLabel?: string;
};

export default function HomePage({ navItems, onNavigate, operatorLabel }: HomePageProps) {
  return (
    <div className="home-page">
      <header className="home-hero">
        <div className="home-logo" aria-hidden="true">
          <span className="home-logo-star">★</span>
          <span className="home-logo-text">RC</span>
        </div>
        <h1>Star-RC</h1>
        <p className="home-tagline">企业运营导航中心</p>
        {operatorLabel && operatorLabel !== "-" && (
          <p className="home-operator">当前操作员：{operatorLabel}</p>
        )}
      </header>

      <nav className="home-nav" aria-label="应用导航">
        {navItems.map((item) => {
          const Icon = item.Icon;
          const title = item.disabled ? item.disabledReason : item.description;

          return (
            <button
              key={item.id}
              className={["home-nav-card", item.disabled ? "disabled" : ""].join(" ")}
              type="button"
              onClick={() => {
                if (!item.disabled) onNavigate(item.id);
              }}
              aria-disabled={item.disabled}
              title={title}
            >
              <span className="home-nav-icon" aria-hidden="true">
                <Icon size={26} />
              </span>
              <span className="home-nav-body">
                <span className="home-nav-label">{item.label}</span>
                <span className="home-nav-desc">{item.disabled ? item.disabledReason : item.description}</span>
              </span>
              <span className="home-nav-arrow" aria-hidden="true">
                <ArrowRight size={18} />
              </span>
            </button>
          );
        })}
      </nav>

      <footer className="home-footer">
        <p>Star-RC 内部系统 · 更多模块持续接入中</p>
      </footer>
    </div>
  );
}

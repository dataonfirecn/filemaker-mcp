import { ArrowRight, Eye, LayoutGrid, MessageCircle, ShieldCheck } from "lucide-react";
import type { Page } from "../types";
import type { SidebarNavGroup } from "./SidebarNav";

export type DashboardPageProps = {
  groups: SidebarNavGroup[];
  operatorName: string;
  canViewPrice: boolean;
  readOnly: boolean;
  onNavigate: (page: Page) => void;
};

export default function DashboardPage({
  groups,
  operatorName,
  canViewPrice,
  readOnly,
  onNavigate
}: DashboardPageProps) {
  const items = groups.flatMap((group) => group.items);
  const enabledItems = items.filter((item) => !item.disabled);
  const chatItem = items.find((item) => item.id === "chat");

  return (
    <div className="dashboard-page">
      <section className="dashboard-hero" aria-labelledby="dashboard-welcome">
        <div className="dashboard-hero-copy">
          <span className="dashboard-eyebrow">STAR-RC 工作台</span>
          <h2 id="dashboard-welcome">欢迎回来，{operatorName || "同事"}</h2>
          <p>从这里进入订单、BOM、产品、零件和 FileMaker 智能查询。</p>
        </div>
        <button
          className="dashboard-chat-cta"
          type="button"
          onClick={() => onNavigate("chat")}
          disabled={chatItem?.disabled}
          title={chatItem?.disabled ? chatItem.disabledReason : "进入 FileMaker 智能对话"}
        >
          <span className="dashboard-chat-icon"><MessageCircle size={22} /></span>
          <span>
            <strong>智能对话</strong>
            <small>{chatItem?.disabled ? "当前账号未开放" : "直接查询 FileMaker 数据"}</small>
          </span>
          <ArrowRight size={18} />
        </button>
      </section>

      <section className="dashboard-metrics" aria-label="工作台状态">
        <article>
          <span className="dashboard-metric-icon"><LayoutGrid size={20} /></span>
          <div>
            <strong>{enabledItems.length}</strong>
            <span>可用业务模块</span>
          </div>
        </article>
        <article>
          <span className="dashboard-metric-icon"><Eye size={20} /></span>
          <div>
            <strong>{canViewPrice ? "已开放" : "受限制"}</strong>
            <span>价格查看权限</span>
          </div>
        </article>
        <article>
          <span className="dashboard-metric-icon"><ShieldCheck size={20} /></span>
          <div>
            <strong>{readOnly ? "只读保护" : "受控写入"}</strong>
            <span>FileMaker 连接状态</span>
          </div>
        </article>
      </section>

      <section className="dashboard-navigation" aria-labelledby="dashboard-navigation-title">
        <div className="dashboard-section-head">
          <div>
            <span>快速入口</span>
            <h2 id="dashboard-navigation-title">业务导航</h2>
          </div>
          <p>功能入口会根据当前 FileMaker 账号权限自动开放。</p>
        </div>

        <div className="dashboard-group-grid">
          {groups.map((group) => (
            <section className="dashboard-group" key={group.id} aria-labelledby={`dashboard-group-${group.id}`}>
              <h3 id={`dashboard-group-${group.id}`}>{group.label}</h3>
              <div className="dashboard-card-grid">
                {group.items.map((item) => {
                  const Icon = item.Icon;
                  return (
                    <button
                      className={`dashboard-nav-card ${item.disabled ? "disabled" : ""}`}
                      key={item.id}
                      type="button"
                      onClick={() => {
                        if (!item.disabled) onNavigate(item.id);
                      }}
                      disabled={item.disabled}
                      title={item.disabled ? item.disabledReason : item.description}
                    >
                      <span className="dashboard-nav-icon"><Icon size={20} /></span>
                      <span className="dashboard-nav-copy">
                        <span className="dashboard-nav-title">
                          <strong>{item.label}</strong>
                          {item.badge && <small>{item.badge}</small>}
                        </span>
                        <span>{item.disabled ? item.disabledReason : item.description}</span>
                      </span>
                      <ArrowRight className="dashboard-nav-arrow" size={17} />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}

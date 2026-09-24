import { AlertTriangle, ArrowRight, CheckCircle2, Eye, FileText, LayoutGrid, MessageCircle, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import type { Page, ReportDashboardResponse, ReportStatus } from "../types";
import type { SidebarNavGroup } from "./SidebarNav";
import ReportTrendChart from "./ReportTrendChart";
import "./DashboardPage.css";

export type DashboardPageProps = {
  groups: SidebarNavGroup[];
  operatorName: string;
  canViewPrice: boolean;
  readOnly: boolean;
  apiBase: string;
  token: string;
  onNavigate: (page: Page) => void;
};

const statusCopy: Record<ReportStatus, string> = {
  success: "正常",
  warning: "需关注",
  failed: "失败"
};

export default function DashboardPage({
  groups,
  operatorName,
  canViewPrice,
  readOnly,
  apiBase,
  token,
  onNavigate
}: DashboardPageProps) {
  const items = groups.flatMap((group) => group.items);
  const enabledItems = items.filter((item) => !item.disabled);
  const chatItem = items.find((item) => item.id === "chat");
  const [reportData, setReportData] = useState<ReportDashboardResponse | null>(null);
  const [reportLoading, setReportLoading] = useState(true);
  const [reportError, setReportError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setReportLoading(true);
    fetch(`${apiBase}/api/reports/dashboard?days=14`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json() as Promise<ReportDashboardResponse>;
      })
      .then((payload) => {
        setReportData(payload);
        setReportError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setReportError("夜间报告摘要暂时无法读取。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setReportLoading(false);
      });
    return () => controller.abort();
  }, [apiBase, token]);

  return (
    <div className="dashboard-page">
      <section className="dashboard-hero" aria-labelledby="dashboard-welcome">
        <div className="dashboard-hero-copy">
          <span className="dashboard-eyebrow">StarRC 工作台</span>
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

      <section className="dashboard-report-panel" aria-labelledby="dashboard-report-title">
        <header className="dashboard-report-heading">
          <div>
            <span>昨夜运行概览</span>
            <h2 id="dashboard-report-title">管理层报告摘要</h2>
          </div>
          <button type="button" onClick={() => onNavigate("reports")}>
            查看报告中心<ArrowRight size={16} />
          </button>
        </header>

        {reportLoading ? (
          <div className="dashboard-report-empty">正在读取夜间报告摘要…</div>
        ) : reportError ? (
          <div className="dashboard-report-empty warning"><AlertTriangle size={17} />{reportError}</div>
        ) : !reportData?.hasReports ? (
          <div className="dashboard-report-empty"><FileText size={18} />夜间任务运行后，重要指标和异常会显示在这里。</div>
        ) : (
          <div className="dashboard-report-content">
            <div className="dashboard-report-overview">
              <article className={`dashboard-report-state ${reportData.overallStatus}`}>
                <span className="dashboard-report-state-icon">
                  {reportData.overallStatus === "success"
                    ? <CheckCircle2 size={22} />
                    : <AlertTriangle size={22} />}
                </span>
                <div>
                  <small>截至 {reportData.latestDate} 的最新夜间任务</small>
                  <strong>{statusCopy[reportData.overallStatus]}</strong>
                  <span>{reportData.reportCount} 份报告 · 数据完整度 {reportData.dataCompleteness}%</span>
                </div>
              </article>
              <div className="dashboard-report-counts">
                <div><strong>{reportData.successCount}</strong><span>正常</span></div>
                <div><strong>{reportData.warningCount}</strong><span>需关注</span></div>
                <div><strong>{reportData.failedCount}</strong><span>失败</span></div>
              </div>
            </div>

            <div className="dashboard-report-metrics">
              {reportData.metrics.slice(0, 6).map((metric) => (
                <article className={metric.severity} key={`${metric.reportType}-${metric.metricCode}`}>
                  <span>{metric.metricName}</span>
                  <strong>{metric.displayValue || `${metric.metricValue ?? "-"}${metric.unit}`}</strong>
                  <small>{metric.reportTitle}</small>
                </article>
              ))}
            </div>

            <div className="dashboard-report-bottom">
              <section className="dashboard-report-exceptions">
                <header><strong>重要异常</strong><span>{reportData.exceptions.length} 项</span></header>
                {reportData.exceptions.length ? reportData.exceptions.slice(0, 4).map((item) => (
                  <button type="button" key={item.id} onClick={() => onNavigate("reports")}>
                    <span className={`report-status-dot ${item.severity === "critical" ? "failed" : "warning"}`} />
                    <span><strong>{item.title}</strong><small>{item.reportTitle || item.category}</small></span>
                    <ArrowRight size={14} />
                  </button>
                )) : <div className="dashboard-report-no-exception"><CheckCircle2 size={16} />没有未处理的重要异常</div>}
              </section>
              <section className="dashboard-report-trend">
                <header><strong>最近运行</strong><span>14天</span></header>
                <ReportTrendChart trends={reportData.trends} />
              </section>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

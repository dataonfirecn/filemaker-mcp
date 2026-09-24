import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ReportDashboardResponse } from "../types";
import "./ReportTrendChart.css";

type Trend = ReportDashboardResponse["trends"][number];

/** 状态色固定：正常 / 需关注 / 失败，不与其他序列共用。 */
const SERIES = [
  { key: "successCount", label: "正常", color: "var(--color-success)" },
  { key: "warningCount", label: "需关注", color: "var(--color-warning)" },
  { key: "failedCount", label: "失败", color: "var(--color-danger)" }
] as const;

type TooltipProps = { active?: boolean; payload?: ReadonlyArray<{ payload: Trend }> };

function TrendTooltip({ active, payload }: TooltipProps) {
  const item = active ? payload?.[0]?.payload : undefined;
  if (!item) return null;
  return (
    <div className="report-trend-tooltip">
      <strong>{item.reportDate}</strong>
      {SERIES.map(series => (
        <div key={series.key}>
          <span className="report-trend-dot" style={{ background: series.color }} />
          <span>{series.label}</span>
          <b>{item[series.key]}</b>
        </div>
      ))}
      <small>数据完整度 {item.dataCompleteness}%</small>
    </div>
  );
}

/** 最近运行：每天各状态的报告数量（堆叠柱状图）。悬停看当天明细，屏幕阅读器可读同一份数据表。 */
export default function ReportTrendChart({ trends }: { trends: Trend[] }) {
  if (!trends.length) return <div className="report-trend-empty">暂无运行记录</div>;
  return (
    <div className="report-trend">
      <ul className="report-trend-legend" aria-label="图例">
        {SERIES.map(series => (
          <li key={series.key}><span className="report-trend-dot" style={{ background: series.color }} />{series.label}</li>
        ))}
      </ul>
      <div className="report-trend-plot" role="img" aria-label={`最近 ${trends.length} 天每日报告状态数量`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={trends} margin={{ top: 4, right: 4, bottom: 0, left: -20 }} barCategoryGap="30%">
            <CartesianGrid vertical={false} stroke="var(--color-divider)" />
            <XAxis dataKey="reportDate" tickFormatter={value => String(value).slice(5)} tick={{ fill: "var(--color-text-muted)", fontSize: 12 }}
              axisLine={{ stroke: "var(--color-border)" }} tickLine={false} minTickGap={8} />
            <YAxis allowDecimals={false} tick={{ fill: "var(--color-text-muted)", fontSize: 12 }} axisLine={false} tickLine={false} width={40} />
            <Tooltip content={<TrendTooltip />} cursor={{ fill: "var(--color-surface-hover)" }} isAnimationActive={false} />
            {SERIES.map(series => (
              <Bar key={series.key} dataKey={series.key} stackId="status" fill={series.color} maxBarSize={20} radius={2}
                stroke="var(--color-surface)" strokeWidth={2} isAnimationActive={false} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="report-trend-table">
        <caption>最近 {trends.length} 天每日报告状态数量</caption>
        <thead><tr><th>日期</th>{SERIES.map(series => <th key={series.key}>{series.label}</th>)}<th>数据完整度</th></tr></thead>
        <tbody>{trends.map(item => (
          <tr key={item.reportDate}><td>{item.reportDate}</td>{SERIES.map(series => <td key={series.key}>{item[series.key]}</td>)}<td>{item.dataCompleteness}%</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

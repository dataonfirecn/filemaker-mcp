import { DatabaseZap, RefreshCw, Search } from "lucide-react";
import type { FormEvent } from "react";
import type {
  NaturalQueryTopQuestionsResponse,
  ODataRelationshipsResponse,
  RagIndexStatusResponse,
  RagSearchResponse
} from "../types";

export type RagControlPageProps = {
  status: RagIndexStatusResponse | null;
  searchResponse: RagSearchResponse | null;
  topQuestions: NaturalQueryTopQuestionsResponse | null;
  relationshipMapping: ODataRelationshipsResponse | null;
  query: string;
  layout: string;
  loading?: boolean;
  refreshing?: boolean;
  searching?: boolean;
  topQuestionsLoading?: boolean;
  relationshipMappingLoading?: boolean;
  error?: string | null;
  onQueryChange: (value: string) => void;
  onLayoutChange: (value: string) => void;
  onLoadStatus: () => void;
  onRefresh: () => void;
  onSearch: () => void;
  onLoadTopQuestions: () => void;
  onLoadRelationshipMapping: () => void;
  onReloadRelationshipMapping: () => void;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function intervalText(seconds: number): string {
  if (!seconds) return "-";
  if (seconds % 86400 === 0) return `${seconds / 86400} 天`;
  if (seconds % 3600 === 0) return `${seconds / 3600} 小时`;
  return `${seconds} 秒`;
}

function fieldPreview(fields: Record<string, unknown>): string {
  const entries = Object.entries(fields)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .slice(0, 6);
  if (!entries.length) return "无字段摘要";
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(" / ");
}

export default function RagControlPage({
  status,
  searchResponse,
  topQuestions,
  relationshipMapping,
  query,
  layout,
  loading,
  refreshing,
  searching,
  topQuestionsLoading,
  relationshipMappingLoading,
  error,
  onQueryChange,
  onLayoutChange,
  onLoadStatus,
  onRefresh,
  onSearch,
  onLoadTopQuestions,
  onLoadRelationshipMapping,
  onReloadRelationshipMapping
}: RagControlPageProps) {
  const run = status?.latestRun ?? null;
  const hits = searchResponse?.hits ?? [];
  const questions = topQuestions?.questions ?? [];
  const relationships = relationshipMapping?.relationships ?? [];

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSearch();
  }

  return (
    <>
      <section className="rag-summary" aria-label="RAG 索引状态">
        <div>
          <span className="meta-label">状态</span>
          <strong className={["meta-value", status?.running ? "pending-text" : "success-text"].join(" ")}>
            {status?.running ? "刷新中" : status?.enabled ? "已启用" : "未启用"}
          </strong>
        </div>
        <div>
          <span className="meta-label">布局</span>
          <strong className="meta-value qty">{(status?.layoutCount ?? 0).toLocaleString("zh-CN")}</strong>
        </div>
        <div>
          <span className="meta-label">记录块</span>
          <strong className="meta-value qty">{(status?.recordCount ?? 0).toLocaleString("zh-CN")}</strong>
        </div>
        <div>
          <span className="meta-label">语义画像</span>
          <strong className="meta-value qty">{(status?.profiledLayouts ?? 0).toLocaleString("zh-CN")}</strong>
        </div>
      </section>

      {error && <div className="alert">{error}</div>}

      <section className="card data-card rag-control-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>索引控制</h3>
            <span className="record-count">定时刷新：{intervalText(status?.refreshIntervalSeconds ?? 0)}</span>
          </div>
          <div className="rag-actions">
            <button className="btn ghost" type="button" onClick={onLoadStatus} disabled={loading || refreshing}>
              <RefreshCw size={15} className={loading ? "spin" : ""} />
              重新读取
            </button>
            <button className="btn primary" type="button" onClick={onRefresh} disabled={refreshing || status?.running}>
              <DatabaseZap size={15} />
              刷新 RAG
            </button>
          </div>
        </div>

        <div className="rag-run-grid">
          <div>
            <span>最近运行</span>
            <strong>{run ? `#${run.id} ${run.status}` : "-"}</strong>
          </div>
          <div>
            <span>原因</span>
            <strong>{run?.reason || "-"}</strong>
          </div>
          <div>
            <span>开始时间</span>
            <strong>{formatDateTime(run?.startedAt)}</strong>
          </div>
          <div>
            <span>完成时间</span>
            <strong>{formatDateTime(run?.completedAt)}</strong>
          </div>
          <div>
            <span>已索引布局</span>
            <strong>{(run?.layoutsIndexed ?? 0).toLocaleString("zh-CN")}</strong>
          </div>
          <div>
            <span>已索引记录</span>
            <strong>{(run?.recordsIndexed ?? 0).toLocaleString("zh-CN")}</strong>
          </div>
        </div>

        {run?.error && <div className="alert compact">{run.error}</div>}
      </section>

      <section className="card data-card rag-control-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>RAG 搜索调试</h3>
            <span className="record-count">{hits.length.toLocaleString("zh-CN")} 条命中</span>
          </div>
        </div>

        <form className="rag-search-form" onSubmit={submitSearch}>
          <label className="grid-search rag-search-input" htmlFor="ragQuery">
            <Search size={15} />
            <input
              id="ragQuery"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="输入要测试的自然语言或关键词"
            />
          </label>
          <input
            className="filter-input"
            value={layout}
            onChange={(event) => onLayoutChange(event.target.value)}
            placeholder="布局，可留空"
            aria-label="RAG 搜索布局"
          />
          <button className="btn primary" type="submit" disabled={searching || !query.trim()}>
            <Search size={15} />
            搜索
          </button>
        </form>

        <div className="rag-hit-list">
          {hits.length === 0 ? (
            <div className="empty-state compact">暂无搜索结果</div>
          ) : (
            hits.map((hit) => (
              <article className="rag-hit" key={`${hit.layout}-${hit.recordId}`}>
                <div className="rag-hit-head">
                  <strong>{hit.title || hit.recordId}</strong>
                  <span>{hit.layout}</span>
                </div>
                <p>{hit.snippet || fieldPreview(hit.fields)}</p>
                <small>
                  Record #{hit.recordId} · 更新 {formatDateTime(hit.updatedAt)}
                </small>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="card data-card rag-control-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>关系映射</h3>
            <span className="record-count">
              {relationshipMapping?.mappingSource || "未加载"} · {relationships.length.toLocaleString("zh-CN")} 条关系
              {relationshipMapping?.mappingVersion ? ` · ${relationshipMapping.mappingVersion}` : ""}
            </span>
          </div>
          <div className="rag-actions">
            <button
              className="btn ghost"
              type="button"
              onClick={onLoadRelationshipMapping}
              disabled={relationshipMappingLoading}
            >
              <RefreshCw size={15} className={relationshipMappingLoading ? "spin" : ""} />
              重新读取
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={onReloadRelationshipMapping}
              disabled={relationshipMappingLoading}
            >
              <DatabaseZap size={15} />
              刷新配置
            </button>
          </div>
        </div>

        <div className="rag-mapping-meta">
          <span>实体 {relationshipMapping?.entityCount ?? 0}</span>
          <span>策略 {relationshipMapping?.queryStrategyCount ?? 0}</span>
          <span title={relationshipMapping?.mappingPath || ""}>{relationshipMapping?.mappingPath || "-"}</span>
        </div>

        {relationshipMapping?.warnings && relationshipMapping.warnings.length > 0 && (
          <div className="home-query-warning rag-mapping-warning">
            {relationshipMapping.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        )}

        <div className="rag-mapping-list">
          {relationships.length === 0 ? (
            <div className="empty-state compact">暂无关系映射</div>
          ) : (
            relationships.map((item) => (
              <article className="rag-mapping-item" key={item.name}>
                <div className="rag-mapping-head">
                  <strong>{item.label || item.name}</strong>
                  <span>{item.source} · {(item.confidence * 100).toFixed(0)}%</span>
                </div>
                <p>{item.description || "未填写说明"}</p>
                <small>
                  {item.fromTable}.{item.fromField} → {item.linkTable}.{item.linkFromField} /{" "}
                  {item.linkToField} → {item.targetTable}
                  {item.targetLookupFields.length > 0 ? ` (${item.targetLookupFields.join(", ")})` : ""}
                </small>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="card data-card rag-control-card">
        <div className="card-head">
          <div className="card-head-left">
            <h3>高频有效问题</h3>
            <span className="record-count">
              最近 {topQuestions?.days ?? 30} 天 · 过滤无意义输入
              {topQuestions?.analyzedPending
                ? ` · 新分析 ${topQuestions.analyzedPending.analyzed} 条`
                : ""}
            </span>
          </div>
          <button className="btn ghost" type="button" onClick={onLoadTopQuestions} disabled={topQuestionsLoading}>
            <RefreshCw size={15} className={topQuestionsLoading ? "spin" : ""} />
            重新统计
          </button>
        </div>

        <div className="rag-top-list">
          {questions.length === 0 ? (
            <div className="empty-state compact">暂无有效问题统计</div>
          ) : (
            questions.map((item) => (
              <article className="rag-top-question" key={item.normalizedKey}>
                <div className="rag-top-rank">
                  <strong>{item.count.toLocaleString("zh-CN")}</strong>
                  <span>次</span>
                </div>
                <div className="rag-top-body">
                  <strong>{item.canonicalQuestion}</strong>
                  <small>
                    {item.domain || "unknown"} · {item.intent || "查询"} · 最近 {formatDateTime(item.lastAskedAt)}
                  </small>
                  {item.examplePrompts.length > 0 && (
                    <p>{item.examplePrompts.slice(0, 3).join(" / ")}</p>
                  )}
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <div className="page-footer-spacer" aria-hidden="true" />
    </>
  );
}

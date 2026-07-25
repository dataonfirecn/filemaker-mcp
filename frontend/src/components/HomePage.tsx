import { Fragment, useEffect, useRef } from "react";
import { ExternalLink, Loader2, Search, SendHorizontal } from "lucide-react";
import type { BusinessProductRow, NaturalQueryExchange } from "../types";

export type HomePageProps = {
  operatorName?: string;
  naturalQueryPrompt: string;
  naturalQueryLoading?: boolean;
  naturalQueryExchanges: NaturalQueryExchange[];
  canUseNaturalQuery: boolean;
  canViewPrice: boolean;
  onNaturalQueryPromptChange: (value: string) => void;
  onNaturalQuerySubmit: (prompt?: string) => void;
  onOpenBusinessProduct: (row: BusinessProductRow) => void;
};

const queryExamples = [
  "昨天新增的零件，价格分别是多少",
  "今天新增的零件有哪些，库存还有多少",
  "近7天新增的零件",
  "查询 STRX-202 产品"
];
const dateFieldLabels: [string, string][] = [
  ["Date Created", "创建日期"],
  ["Created Time", "创建时间"],
  ["Time Created", "创建时间"],
  ["CreationTimestamp", "创建时间戳"],
  ["RecordCreationTimestamp", "创建时间戳"],
  ["createdAt", "创建时间戳"],
  ["created_at", "创建时间戳"],
  ["Upload_Date", "上传日期"],
  ["修改日期", "更新日期"],
  ["更新日期", "更新日期"],
  ["修改時間", "更新时间"],
  ["修改时间", "更新时间"],
  ["更新時間", "更新时间"],
  ["更新时间", "更新时间"],
  ["updatedAt", "更新时间戳"],
  ["updated_at", "更新时间戳"]
];
const stockFieldLabels: [string, string][] = [
  ["Stock", "库存"],
  ["current_stock", "库存"],
  ["stock", "库存"],
  ["stockQty", "库存"],
  ["stock_qty", "库存"],
  ["零件_BOM::current_stock", "库存"],
  ["库存", "库存"],
  ["庫存", "库存"]
];
const priceFieldLabels: [string, string][] = [
  ["Price", "价格"],
  ["price", "价格"],
  ["unit_price", "单价"],
  ["unit price", "单价"],
  ["Unit Price", "单价"],
  ["价格", "价格"],
  ["價格", "价格"],
  ["单价", "单价"],
  ["單價", "单价"],
  ["售价", "售价"],
  ["售價", "售价"],
  ["成本价", "成本价"],
  ["成本價", "成本价"]
];
const creatorFieldLabels: [string, string][] = [
  ["Created By", "创建人"],
  ["创建人", "创建人"],
  ["創建人", "创建人"],
  ["created_by", "创建人"],
  ["createdBy", "创建人"],
  ["creator", "创建人"],
  ["Creator", "创建人"],
  ["录入人", "录入人"],
  ["錄入人", "录入人"],
  ["建档人", "建档人"],
  ["建檔人", "建档人"],
  ["操作员", "操作员"],
  ["操作員", "操作员"]
];

function hasValue(value: unknown): boolean {
  return value !== null && value !== undefined && value !== "";
}

function dateMeta(row: BusinessProductRow): { label: string; value: string }[] {
  const raw = row.raw ?? {};
  const seen = new Set<string>();
  const items: { label: string; value: string }[] = [];
  dateFieldLabels.forEach(([field, label]) => {
    const value = raw[field];
    if (!hasValue(value) || seen.has(field)) return;
    seen.add(field);
    items.push({ label, value: String(value) });
  });
  return items;
}

function stockMeta(row: BusinessProductRow, showEmptyStock: boolean): { label: string; value: string }[] {
  if (hasValue(row.stock)) {
    return [{ label: "库存", value: String(row.stock) }];
  }

  const raw = row.raw ?? {};
  for (const [field, label] of stockFieldLabels) {
    const value = raw[field];
    if (hasValue(value)) {
      return [{ label, value: String(value) }];
    }
  }

  if (showEmptyStock && ("current_stock" in raw || "Stock" in raw || row.stock !== null)) {
    return [{ label: "库存", value: "未填" }];
  }
  return [];
}

function priceMeta(row: BusinessProductRow): { label: string; value: string }[] {
  const raw = row.raw ?? {};
  for (const [field, label] of priceFieldLabels) {
    const value = raw[field];
    if (hasValue(value)) {
      return [{ label, value: String(value) }];
    }
  }
  return [];
}

function creatorMeta(row: BusinessProductRow): { label: string; value: string }[] {
  const raw = row.raw ?? {};
  for (const [field, label] of creatorFieldLabels) {
    const value = raw[field];
    if (hasValue(value)) {
      return [{ label, value: String(value) }];
    }
  }
  return [];
}

type QueryResponseMessageProps = {
  exchange: NaturalQueryExchange;
  loading?: boolean;
  onNaturalQuerySubmit: (prompt?: string) => void;
  onOpenBusinessProduct: (row: BusinessProductRow) => void;
  canViewPrice: boolean;
};

function QueryResponseMessage({
  exchange,
  loading,
  onNaturalQuerySubmit,
  onOpenBusinessProduct,
  canViewPrice
}: QueryResponseMessageProps) {
  const response = exchange.response;
  if (!response) return null;

  const rows = response.rows ?? [];
  const clarificationOptions = response.clarificationOptions ?? [];
  const canOpenRows = response.plan.domain !== "part";
  const shouldShowEmptyStock =
    response.plan.domain === "part" &&
    /库存|庫存|stock|current_stock|还有多少|還有多少|剩余|剩餘/i.test(exchange.prompt);
  const entityFallbackName = response.plan.domain === "part" ? "未命名零件" : "未命名产品";

  return (
    <article className="home-chat-message assistant">
      <div className="home-chat-bubble">
        <div className="home-query-answer">
          <strong>{response.clarificationQuestion || response.answer}</strong>
          {!response.requiresClarification && <span>{response.plan.description}</span>}
        </div>
        {response.requiresClarification && clarificationOptions.length > 0 && (
          <div className="home-clarification-options" aria-label="反问选项">
            {clarificationOptions.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onNaturalQuerySubmit(option)}
                disabled={loading}
              >
                {option}
              </button>
            ))}
          </div>
        )}
        {response.plan.warnings.length > 0 && (
          <div className="home-query-warning">
            {response.plan.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        )}
        {rows.length > 0 && (
          <div className="home-query-list">
            {rows.slice(0, 10).map((row) => {
              const meta = [
                ...dateMeta(row),
                ...stockMeta(row, shouldShowEmptyStock),
                ...(canViewPrice ? priceMeta(row) : []),
                ...creatorMeta(row)
              ];
              return (
                <button
                  key={row.recordId}
                  className="home-query-row"
                  type="button"
                  onClick={() => {
                    if (canOpenRows) onOpenBusinessProduct(row);
                  }}
                  disabled={!canOpenRows}
                >
                  <span>
                    <strong>{row.productSku || row.systemProductSku || entityFallbackName}</strong>
                    <em>{row.productNameCn || row.productName || row.modelName || "-"}</em>
                    {meta.length > 0 && (
                      <small className="home-query-meta">
                        {meta.map((item) => (
                          <span key={`${item.label}-${item.value}`}>{`${item.label}: ${item.value}`}</span>
                        ))}
                      </small>
                    )}
                  </span>
                  {canOpenRows && <ExternalLink size={15} />}
                </button>
              );
            })}
          </div>
        )}
        <div className="home-query-plan">
          <span>布局</span>
          <strong>{response.layout}</strong>
        </div>
      </div>
    </article>
  );
}

export default function HomePage({
  operatorName,
  naturalQueryPrompt,
  naturalQueryLoading,
  naturalQueryExchanges,
  canUseNaturalQuery,
  canViewPrice,
  onNaturalQueryPromptChange,
  onNaturalQuerySubmit,
  onOpenBusinessProduct
}: HomePageProps) {
  const threadEndRef = useRef<HTMLDivElement>(null);
  const visibleExamples = canViewPrice
    ? queryExamples
    : queryExamples.filter((example) => !/价格|價格|单价|單價|售价|售價|成本/.test(example));

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [naturalQueryExchanges, naturalQueryLoading]);

  return (
    <div className="home-page">
      <header className="home-chat-topbar" aria-label="当前用户">
        <strong className="home-chat-user">{operatorName || "-"}</strong>
      </header>

      <main className="home-chat-main" aria-label="FileMaker 对话">
        <section className="home-chat-thread">
          <article className="home-chat-message assistant">
            <div className="home-chat-bubble">
              <strong>FileMaker 问答</strong>
              <p className="home-chat-retention">
                {canUseNaturalQuery
                  ? `输入产品、零件、库存或日期等查询。${canViewPrice ? "本账号已获价格查看权限。" : "本账号的价格字段已由后台屏蔽。"}`
                  : "当前 FileMaker 权限集未开放智能问答。"}
              </p>
              <div className="home-query-examples" aria-label="预设问题">
                {visibleExamples.map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => onNaturalQuerySubmit(example)}
                    disabled={naturalQueryLoading || !canUseNaturalQuery}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          </article>

          {naturalQueryExchanges.map((exchange) => (
            <Fragment key={exchange.id}>
              <article className="home-chat-message user">
                <div className="home-chat-bubble">{exchange.prompt}</div>
              </article>
              {exchange.error && (
                <article className="home-chat-message assistant">
                  <div className="home-chat-bubble">
                    <div className="alert compact home-query-alert">{exchange.error}</div>
                  </div>
                </article>
              )}
              <QueryResponseMessage
                exchange={exchange}
                loading={naturalQueryLoading}
                onNaturalQuerySubmit={onNaturalQuerySubmit}
                onOpenBusinessProduct={onOpenBusinessProduct}
                canViewPrice={canViewPrice}
              />
            </Fragment>
          ))}

          {naturalQueryLoading && (
            <article className="home-chat-message assistant">
              <div className="home-chat-bubble loading">
                <Loader2 className="spin" size={16} />
                <span>查询中</span>
              </div>
            </article>
          )}
          <div ref={threadEndRef} aria-hidden="true" />
        </section>

        <form
          className="home-chat-composer"
          onSubmit={(event) => {
            event.preventDefault();
            onNaturalQuerySubmit();
          }}
        >
          <label className="home-query-input" htmlFor="naturalQueryPrompt">
            <Search size={16} />
            <textarea
              id="naturalQueryPrompt"
              value={naturalQueryPrompt}
              onChange={(event) => onNaturalQueryPromptChange(event.target.value)}
              placeholder="直接输入要查询的 FileMaker 问题"
              disabled={naturalQueryLoading || !canUseNaturalQuery}
              rows={2}
            />
          </label>
          <button className="btn primary home-query-submit" type="submit" disabled={naturalQueryLoading || !canUseNaturalQuery}>
            {naturalQueryLoading ? <Loader2 className="spin" size={16} /> : <SendHorizontal size={16} />}
            发送
          </button>
        </form>
      </main>
    </div>
  );
}

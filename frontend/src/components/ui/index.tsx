import type { ButtonHTMLAttributes, FormEvent, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Inbox } from "lucide-react";
import "./ui.css";
import "./pagination.css";
export { Modal } from './Modal';

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";
export function Button({ variant = "secondary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  return <button type="button" className={`ui-button ui-button-${variant} ${className}`} {...props} />;
}
export function IconButton({ label, loading = false, className = "", children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; loading?: boolean }) {
  return <button type="button" className={`ui-button ui-icon-button${loading ? " is-loading" : ""} ${className}`} aria-label={label} title={label} {...props}>{children}</button>;
}
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`ui-badge ui-tone-${tone}`}>{children}</span>;
}
export function Card({ children, className = "", ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={`ui-card ${className}`} {...props}>{children}</section>;
}
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`ui-input ${props.className ?? ""}`} />;
}
export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`ui-input ${props.className ?? ""}`} />;
}
export function EmptyState({ title, description }: { title: string; description?: string }) {
  return <div className="ui-empty"><Inbox size={20} strokeWidth={1.75} /><h2>{title}</h2>{description && <p>{description}</p>}</div>;
}
export function Loading({ label = "正在读取数据" }: { label?: string }) {
  return <div className="ui-loading" role="status" aria-label={label}><span>{label}</span>{[0, 1, 2, 3].map(n => <div className="ui-skeleton" key={n} />)}</div>;
}
export function Alert({ children }: { children: ReactNode }) {
  return <div className="ui-alert" role="alert"><AlertCircle size={16} strokeWidth={1.75} /><div>{children}</div></div>;
}
export type TableColumn<T> = { key: string; label: string; numeric?: boolean; render: (row: T) => ReactNode };
export function Table<T>({ columns, rows, rowKey, caption }: { columns: TableColumn<T>[]; rows: T[]; rowKey: (row: T) => string; caption: string }) {
  return <div className="ui-table-wrap"><table className="ui-table"><caption>{caption}</caption><thead><tr>{columns.map(col => <th key={col.key} scope="col" className={col.numeric ? "ui-numeric" : undefined}>{col.label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={rowKey(row)}>{columns.map(col => <td key={col.key} data-label={col.label} className={col.numeric ? "ui-numeric" : undefined}><div>{col.render(row)}</div></td>)}</tr>)}</tbody></table></div>;
}

/** 每页条数：记在浏览器本地，只接受 options 里的值。 */
export function usePageSize(storageKey: string, options: readonly number[], fallback: number) {
  const [pageSize, setPageSize] = useState(() => {
    try {
      const stored = Number(localStorage.getItem(storageKey));
      if (options.includes(stored)) return stored;
    } catch {
      // 存储不可用时使用默认值。
    }
    return fallback;
  });
  const update = useCallback((next: number) => {
    setPageSize(next);
    try { localStorage.setItem(storageKey, String(next)); } catch { /* 存储不可用时只在本次会话生效 */ }
  }, [storageKey]);
  return [pageSize, update] as const;
}

export type PaginationProps = {
  page: number; pageSize: number; totalCount: number; rowCount: number; loading?: boolean;
  onPageChange: (page: number) => void;
  /** 两个都传才显示「每页」下拉。 */
  pageSizeOptions?: readonly number[]; onPageSizeChange?: (pageSize: number) => void;
};
/** 卡片底部分页：第 x–y 条，共 N 条 / 每页 / 首页 上一页 第 [n] / 总页数 页 下一页 末页。 */
export function Pagination({ page, pageSize, totalCount, rowCount, loading = false, onPageChange, pageSizeOptions, onPageSizeChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const firstRow = totalCount === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastRow = totalCount === 0 ? 0 : firstRow + rowCount - 1;
  const [draft, setDraft] = useState(String(page));
  useEffect(() => { setDraft(String(page)); }, [page]);
  function jump(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const target = Number(draft);
    if (loading || !draft.trim() || !Number.isFinite(target)) { setDraft(String(page)); return; }
    const bounded = Math.min(Math.max(1, Math.trunc(target)), totalPages);
    setDraft(String(bounded));
    if (bounded !== page) onPageChange(bounded);
  }
  const atStart = loading || page <= 1;
  const atEnd = loading || page >= totalPages;
  return (
    <div className="ui-pagination">
      <span className="ui-pagination-range">第 {firstRow.toLocaleString("zh-CN")}–{lastRow.toLocaleString("zh-CN")} 条，共 {totalCount.toLocaleString("zh-CN")} 条</span>
      <div className="ui-pagination-actions">
        {pageSizeOptions && onPageSizeChange && (
          <label className="ui-pagination-size">每页
            <Select value={pageSize} disabled={loading} aria-label="每页条数" onChange={event => onPageSizeChange(Number(event.target.value))}>
              {pageSizeOptions.map(option => <option key={option} value={option}>{option}</option>)}
            </Select>
          </label>
        )}
        <Button aria-label="首页" title="首页" disabled={atStart} onClick={() => onPageChange(1)}><ChevronsLeft /></Button>
        <Button aria-label="上一页" title="上一页" disabled={atStart} onClick={() => onPageChange(page - 1)}><ChevronLeft /></Button>
        <form className="ui-pagination-jump" onSubmit={jump} noValidate>
          <span>第</span>
          <Input aria-label="页码" title="输入页码后按 Enter 跳转" type="number" min={1} max={totalPages} value={draft}
            disabled={loading || totalCount === 0} onChange={event => setDraft(event.target.value)} />
          <span>/ {totalPages.toLocaleString("zh-CN")} 页</span>
        </form>
        <Button aria-label="下一页" title="下一页" disabled={atEnd} onClick={() => onPageChange(page + 1)}><ChevronRight /></Button>
        <Button aria-label="末页" title="末页" disabled={atEnd} onClick={() => onPageChange(totalPages)}><ChevronsRight /></Button>
      </div>
    </div>
  );
}

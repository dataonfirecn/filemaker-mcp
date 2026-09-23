import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { AlertCircle, Inbox } from "lucide-react";
import "./ui.css";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";
export function Button({ variant = "secondary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  return <button type="button" className={`ui-button ui-button-${variant} ${className}`} {...props} />;
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

import { useId, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { SessionResponse } from '../types';
import { Button } from './ui';
import './ProductDebug.css';

type Props = {
  operator?: SessionResponse['context']['operator'];
  permissions: Record<string, boolean>;
  productId?: string;
  version?: number;
  locked: boolean;
  canEdit: boolean;
  preview: boolean;
};
const permissionLabels = [
  ['canViewProducts', '查看产品'], ['canEditProducts', '编辑产品'],
  ['canApproveProducts', '审核产品'], ['canViewPrice', '查看价格'],
  ['canEditProductPrices', '编辑产品价格'], ['canManageProductSync', '管理产品同步'],
] as const;

export default function ProductDebug({ operator, permissions, productId, version, locked, canEdit, preview }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const privilege = operator?.privilege?.trim();
  const placeholder = !privilege || ['filemaker', 'unknown', 'mock', 'internal_remote'].includes(privilege.toLowerCase());
  return <div className="product-debug" ref={root} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }} onKeyDown={event => {
    if (event.key === 'Escape') { setOpen(false); root.current?.querySelector('button')?.focus(); }
  }}>
    <Button variant="ghost" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>
      Debug {open ? <ChevronUp size={14} strokeWidth={1.75} /> : <ChevronDown size={14} strokeWidth={1.75} />}
    </Button>
    {open && <section id={id} className="product-debug-panel" aria-label="产品调试信息" tabIndex={-1}>
      <h2>当前会话</h2>
      <dl>
        <div><dt>账号</dt><dd translate="no">{operator?.account || '—'}</dd></div>
        <div><dt>用户名</dt><dd translate="no">{operator?.name || '—'}</dd></div>
        <div><dt>传入权限集</dt><dd translate="no">{privilege || '未提供'}</dd></div>
      </dl>
      {placeholder && <p>当前会话未提供真实 FileMaker 权限集，请检查入口签名参数。</p>}
      <h2>产品权限</h2>
      <dl>{permissionLabels.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{permissions[key] === undefined ? '未返回' : permissions[key] ? '允许' : '不允许'}</dd></div>)}</dl>
      <h2>当前产品</h2>
      <dl>
        <div><dt>产品 UUID</dt><dd translate="no">{productId || '—'}</dd></div>
        <div><dt>Web 版本</dt><dd>{version ?? '—'}</dd></div>
        <div><dt>页面状态</dt><dd>{preview ? '草稿预览' : locked ? '已审核 · 已锁定' : canEdit ? '可编辑' : '只读'}</dd></div>
      </dl>
      <p>权限项来自产品接口；权限集名称来自登录会话。更改 FileMaker 权限集后请重新打开页面。</p>
    </section>}
  </div>;
}

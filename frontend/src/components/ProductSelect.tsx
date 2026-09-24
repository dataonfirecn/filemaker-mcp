import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Search } from 'lucide-react';
import './ProductSelect.css';

export type SelectOption = { value: string; label: string };

/** 选项超过这个数量就出现搜索栏；更短的列表直接点选即可。 */
const SEARCH_FROM = 8;
const GAP = 4;

type Place = { left: number; top: number; width: number; maxHeight: number; up: boolean };

/**
 * 产品资料里的下拉选择：与原生 select 一样存取同一个值，
 * 长列表带搜索栏（按显示文字或值过滤），支持键盘上下选择、回车确认、Esc 关闭。
 * 弹层挂在 .product-master 下用 fixed 定位，不会被卡片的 overflow 裁掉。
 */
export default function ProductSelect({ value, options, onChange, disabled, ariaLabel, placeholder = '请选择', className = '' }: {
  value: string; options: SelectOption[]; onChange: (value: string) => void; disabled?: boolean; ariaLabel: string; placeholder?: string; className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState<Place | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const listId = useId();

  // 库里存着的旧值不在选项里时仍显示出来，不能被悄悄丢掉。
  const all = useMemo(() => value && !options.some(o => o.value === value) ? [{ value, label: value }, ...options] : options, [value, options]);
  const searchable = all.length > SEARCH_FROM;
  const q = query.trim().toLowerCase();
  const rows = useMemo<SelectOption[]>(() => q
    ? all.filter(o => o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q))
    : [{ value: '', label: placeholder }, ...all], [all, q, placeholder]);
  const current = all.find(o => o.value === value)?.label ?? value;

  function measure() {
    const r = trigger.current?.getBoundingClientRect(); if (!r) return;
    const below = window.innerHeight - r.bottom - GAP - 8, above = r.top - GAP - 8;
    const up = below < 240 && above > below;
    setPlace({ left: Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 240) - 8)), top: up ? r.top - GAP : r.bottom + GAP, width: Math.max(r.width, 240), maxHeight: Math.min(up ? above : below, 380), up });
  }
  function show() {
    if (disabled) return;
    setQuery(''); setActive(Math.max(0, all.findIndex(o => o.value === value) + 1)); measure(); setOpen(true);
  }
  function close(refocus = false) { setOpen(false); if (refocus) trigger.current?.focus(); }
  function choose(option: SelectOption) { if (option.value !== value) onChange(option.value); close(true); }

  useLayoutEffect(() => { if (open) (searchable ? search : list).current?.focus({ preventScroll: true }); }, [open, searchable]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => { const t = e.target as Node; if (!pop.current?.contains(t) && !trigger.current?.contains(t)) close(); };
    const onMove = () => measure();
    document.addEventListener('pointerdown', onDown); window.addEventListener('resize', onMove); window.addEventListener('scroll', onMove, true);
    return () => { document.removeEventListener('pointerdown', onDown); window.removeEventListener('resize', onMove); window.removeEventListener('scroll', onMove, true); };
  }, [open]);
  useEffect(() => { if (open) list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' }); }, [open, active, rows]);
  useEffect(() => { setActive(0); }, [q]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);

  function onPopKey(e: KeyboardEvent) {
    if (e.nativeEvent.isComposing) return; // 中文输入法选词时的回车不算确认
    const last = rows.length - 1;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, last)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)); }
    else if (e.key === 'Home' && !searchable) { e.preventDefault(); setActive(0); }
    else if (e.key === 'End' && !searchable) { e.preventDefault(); setActive(last); }
    else if (e.key === 'Enter') { e.preventDefault(); if (rows[active]) choose(rows[active]); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === 'Tab') close();
  }

  const host = open ? trigger.current?.closest('.product-master') ?? document.body : null;
  return <>
    <button ref={trigger} type="button" className={`pm-picker pm-select-trigger ${className}`.trim()} role="combobox" aria-haspopup="listbox" aria-expanded={open} aria-controls={open ? listId : undefined}
      aria-label={ariaLabel} disabled={disabled} onClick={() => open ? close() : show()}
      onKeyDown={e => { if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); show(); } }}>
      <span className={value ? '' : 'ps-placeholder'}>{value ? current : placeholder}</span>
      <ChevronDown size={14} aria-hidden="true" className={open ? 'ps-caret is-open' : 'ps-caret'} />
    </button>
    {open && place && host && createPortal(
      <div ref={pop} className={`ps-pop${place.up ? ' is-up' : ''}`} style={{ left: place.left, width: place.width, maxHeight: place.maxHeight, ...(place.up ? { bottom: window.innerHeight - place.top } : { top: place.top }) }} onKeyDown={onPopKey}>
        {searchable && <div className="ps-search">
          <Search size={14} aria-hidden="true" />
          <input ref={search} type="text" value={query} placeholder="搜索…" aria-label={`搜索 ${ariaLabel}`} aria-controls={listId} autoComplete="off" spellCheck={false} onChange={e => setQuery(e.target.value)} />
        </div>}
        <ul ref={list} id={listId} className="ps-list" role="listbox" aria-label={ariaLabel} tabIndex={searchable ? -1 : 0}>
          {rows.map((o, i) => <li key={o.value || '__empty'} role="option" aria-selected={o.value === value} data-active={i === active} className={`ps-row${o.value === value ? ' is-selected' : ''}${o.value === '' ? ' is-empty' : ''}`}
            onMouseMove={() => active !== i && setActive(i)} onClick={() => choose(o)}>
            <span>{o.label}</span>{o.value === value && <Check size={14} aria-hidden="true" />}
          </li>)}
          {!rows.length && <li className="ps-none" role="presentation">没有匹配的选项</li>}
        </ul>
        {searchable && <div className="ps-foot" role="status">{q ? `匹配 ${rows.length} / ${all.length} 项` : `共 ${all.length} 项`}</div>}
      </div>, host)}
  </>;
}

import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Save, Search, Image as ImageIcon, FileText, LockKeyhole, RotateCw, Download, X, CircleCheck, AlertCircle, Plus, Layers, Camera, History, RefreshCw } from 'lucide-react';
import { productPhotoFields, nativeTabs, basicSections, fieldLabels, sectionFields, assetGroup, fieldPresentation, recordMetaFields, draftFlags, isEditorField, measureGroups, priceBands, foldedGroups } from './productMasterLayout';
import './ProductMasterPage.css';
import ProductQuotes from './ProductQuotes';

type Choice = { value: string; label: string; name?: string; code?: string };
type Control = { type: string; options: Choice[]; searchable: boolean };
type Field = { name: string; result: string; writable: boolean; maxRepeat: number; required?: boolean; writePermission?: string };
type Asset = { id: string; field: string; repetition: number; filename: string; mimeType: string; size: number; sortOrder?: number };
function unsupportedPreviewReason(asset: Asset, compact = false): string {
  if (/^(image\/(png|jpeg|webp|gif)|application\/pdf)$/.test(asset.mimeType)) return '';
  const format = ({ 'image/bmp': 'BMP', 'image/mpo': 'MPO' } as Record<string, string>)[asset.mimeType]
    ?? asset.filename.match(/\.([a-z0-9]{1,10})$/i)?.[1].toUpperCase();
  if (compact) return format ? `${format} 格式暂不支持预览` : '此格式暂不支持预览';
  return format ? `当前页面不支持 ${format} 格式预览，请下载原文件查看。` : '当前页面不支持此文件格式预览，请下载原文件查看。';
}
type Product = { previewMode?: boolean; pendingAssetFields?: string[]; assetImportError?: string; id: string; version: number; fields: Record<string, unknown>; assets: Asset[] };
type Revision = { version: number; created_at: string; actor: { account: string; name: string; origin: string }; before_data: Product; after_data: Product };
type Status = { writeEnabled?: boolean; drift?: Array<{ id: number; observed: unknown }>; filemaker: Array<{ version: number; status: string; error?: string }>; dms: Array<{ consumer: string; synced: boolean }> };

const TAB_ICONS: Record<string, ReactNode> = {
  '基础资料': <Layers size={14} />,
  '產品照片': <Camera size={14} />,
  '产品规格书': <FileText size={14} />,
  '生產注意事項': <FileText size={14} />,
  '修改历史': <History size={14} />,
  '同步状态': <RefreshCw size={14} />,
};

export default function ProductMasterPage({ apiBase, token, initialRef = '', readOnly = false }: { apiBase: string; token: string; initialRef?: string; readOnly?: boolean }) {
  const [controls, setControls] = useState<Record<string, Control>>({});
  const [picker, setPicker] = useState<{ field: string; repetition: number } | null>(null);
  const [query, setQuery] = useState('');
  const [choices, setChoices] = useState<Choice[]>([]);
  const [choiceTotal, setChoiceTotal] = useState(0);
  const [choiceOffset, setChoiceOffset] = useState(0);
  const [choiceRetry, setChoiceRetry] = useState(0);
  const choiceBusy = useRef(false);
  const choiceList = useRef<HTMLDivElement>(null);
  const [choiceLoading, setChoiceLoading] = useState(false);
  const [choiceError, setChoiceError] = useState('');
  const [schema, setSchema] = useState<Field[]>([]);
  const [permissions, setPermissions] = useState<Record<string, boolean>>({});
  const [product, setProduct] = useState<Product | null>(null);
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const localFiles = useRef(new Map<string, File>());
  const [dragSlot, setDragSlot] = useState('');
  const [assets, setAssets] = useState<Asset[]>([]);
  const [history, setHistory] = useState<Revision[]>([]);
  const [sync, setSync] = useState<Status | null>(null);
  const [tab, setTab] = useState('基础资料');
  const [openFolds, setOpenFolds] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const [skuError, setSkuError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<Product | null>(null);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [selectedAsset, setSelectedAsset] = useState<Asset | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});
  const loadSequence = useRef(0);
  const closing = useRef(false);
  const pending = useRef({ fingerprint: '', id: crypto.randomUUID() });
  const [quoteDirty, setQuoteDirty] = useState(false);
  const [quoteBusy, setQuoteBusy] = useState(false);
  const productDirty = JSON.stringify(fields) !== JSON.stringify(product?.fields ?? {}) || JSON.stringify(assets) !== JSON.stringify(product?.assets ?? []);
  const dirty = productDirty || quoteDirty;
  const canEdit = !readOnly && !!permissions.canEditProducts && !product?.previewMode;

  async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    if (readOnly && method !== 'GET') throw new Error('产品浏览页不支持修改');
    const response = await fetch(`${apiBase}/api/product-master${path}`, { method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 409 && data.detail?.current) setConflict(data.detail.current);
      if (data.detail?.field === 'product_sku') { setSkuError(data.detail.message); setTab('基础资料'); }
      throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.message ?? JSON.stringify(data.detail));
    }
    return data as T;
  }
  useEffect(() => {
    if (!picker) return;
    let active = true; choiceBusy.current = true; setChoiceLoading(true); setChoiceError(''); if (choiceOffset === 0) { setChoices([]); setChoiceTotal(0); if (choiceList.current) choiceList.current.scrollTop = 0; }
    const timer = window.setTimeout(() => {
      const endpoint = ['Client', 'id_client'].includes(picker.field) ? '/customers' : `/editor-options/${encodeURIComponent(picker.field)}`;
      api<{ rows: Choice[]; total: number }>(`${endpoint}?q=${encodeURIComponent(query)}&offset=${choiceOffset}`).then(r => { if (active) { setChoices(old => choiceOffset === 0 ? r.rows : [...old, ...r.rows.filter(row => !old.some(item => item.value === row.value))]); setChoiceTotal(r.total); } }).catch(e => { if (active) setChoiceError(e instanceof Error ? e.message : '读取失败'); }).finally(() => { if (active) { choiceBusy.current = false; setChoiceLoading(false); } });
    }, 250);
    return () => { active = false; clearTimeout(timer); };
  }, [picker, query, choiceOffset, choiceRetry, token]);
  function openPicker(field: string, repetition: number) { setChoices([]); setChoiceTotal(0); setChoiceError(''); choiceBusy.current = true; setChoiceLoading(true); setQuery(''); setChoiceOffset(0); setPicker({ field, repetition }); }
  function loadMoreChoices(element: HTMLDivElement) { if (!choiceBusy.current && !choiceError && choiceOffset + 50 < choiceTotal && element.scrollHeight - element.scrollTop - element.clientHeight < 80) { choiceBusy.current = true; setChoiceLoading(true); setChoiceOffset(offset => offset + 50); } }
  function choose(option: Choice) {
    if (!picker) return;
    if (['Client', 'id_client'].includes(picker.field)) setFields(p => ({ ...p, Client: option.name ?? option.label, id_client: option.value }));
    else setFields(p => { const f = schema.find(f => f.name === picker.field); if (!f || f.maxRepeat <= 1) return { ...p, [picker.field]: option.value }; const values = Array.isArray(p[picker.field]) ? [...p[picker.field] as unknown[]] : [p[picker.field] ?? '']; while (values.length < picker.repetition) values.push(''); values[picker.repetition - 1] = option.value; return { ...p, [picker.field]: values }; });
    setPicker(null);
  }
  function show(p: Product) { localFiles.current.clear(); setProduct(p); setFields(p.fields); setAssets(p.assets); setConflict(null); setError(''); setSkuError(''); }
  async function load(ref: string) {
    if (quoteBusy) { setError('报价正在保存，请稍后切换产品。'); return; }
    if (dirty && !window.confirm('当前修改尚未保存，是否放弃并切换产品？')) return;
    const sequence = ++loadSequence.current; setLoading(true); setError('');
    try { const result = await api<Product>(`/products/${encodeURIComponent(ref)}`); if (sequence === loadSequence.current) { show(result); setSelectedAsset(null); } } catch (e) { if (sequence === loadSequence.current) setError(String(e)); } finally { if (sequence === loadSequence.current) setLoading(false); }
  }
  useEffect(() => {
    if (!token) return;
    let active = true;
    api<{ fields: Field[]; permissions: Record<string, boolean> }>('/schema').then(s => { if (active) { setSchema(s.fields.filter(f => isEditorField(f.name))); setPermissions(s.permissions); } }).catch(e => { if (active) setError(String(e)); });
    api<{ controls: Record<string, Control> }>('/editor-controls').then(r => { if (active) setControls(r.controls); }).catch(e => { if (active) setError(e instanceof Error ? e.message : '选项读取失败'); });
    setTab('基础资料');
    if (initialRef) void load(initialRef);
    return () => { active = false; loadSequence.current++; };
  }, [token, initialRef]);
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => { if (dirty && !closing.current) { e.preventDefault(); e.returnValue = ''; } };
    window.addEventListener('beforeunload', guard); return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);
  useEffect(() => {
    if (!product || readOnly) return;
    if (product.previewMode) { setHistory([]); setSync({ writeEnabled: false, filemaker: [], dms: [] }); return; }
    let active = true;
    const poll = () => api<Status>(`/products/${product.id}/status`).then(s => { if (active) setSync(s); }).catch(e => { if (active) setError(String(e)); });
    void poll(); const timer = window.setInterval(poll, 5000);
    api<{ rows: Revision[] }>(`/products/${product.id}/history`).then(r => { if (active) setHistory(r.rows); }).catch(e => { if (active) setError(String(e)); });
    return () => { active = false; clearInterval(timer); };
  }, [product?.id, product?.version, token]);
  useEffect(() => {
    const controller = new AbortController(); const urls: string[] = [];
    setPreviews({}); setPreviewErrors({});
    if (product) assets.filter(a => isEditorField(a.field) && !unsupportedPreviewReason(a)).forEach(a => {
      const draftFile = localFiles.current.get(a.id); if (draftFile) { const url = URL.createObjectURL(draftFile); urls.push(url); setPreviews(p => ({ ...p, [a.id]: url })); return; }
      fetch(`${apiBase}/api/product-master/products/${product.id}/assets/${a.id}`, { signal: controller.signal, headers: { Authorization: `Bearer ${token}` } }).then(async r => {
        if (!r.ok) throw new Error('附件读取失败'); const blob = await r.blob(); if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob); urls.push(url); setPreviews(p => ({ ...p, [a.id]: url }));
      }).catch(() => { if (!controller.signal.aborted) setPreviewErrors(p => ({ ...p, [a.id]: '预览加载失败，请重新打开页面或下载原文件查看。' })); });
    });
    return () => { controller.abort(); urls.forEach(URL.revokeObjectURL); };
  }, [product?.id, product?.version, assets, token]);
  useEffect(() => {
    const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelectedAsset(null); };
    window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close);
  }, []);
  function cancelEditing() {
    if (busy || quoteBusy) return;
    if (!window.confirm(dirty
      ? '确定取消编辑并关闭窗口吗？尚未保存的修改将被放弃。'
      : '确定取消编辑并关闭窗口吗？')) return;
    closing.current = true;
    try {
      if (window.FileMaker?.PerformScript) {
        window.FileMaker.PerformScript('StarRC_CloseWebViewer', JSON.stringify({
          action: 'close', source: 'productMaster', productId: product?.id ?? initialRef
        }));
      } else {
        window.close();
        window.setTimeout(() => {
          if (!window.closed) {
            closing.current = false;
            setError('浏览器未允许自动关闭，请手动关闭此标签页；当前修改尚未保存。');
          }
        }, 300);
      }
    } catch {
      closing.current = false;
      setError('无法关闭编辑窗口，请重试取消或使用窗口关闭按钮。');
    }
  }
  async function save() {
    setError(''); setMessage(''); setSkuError('');
    if (!String(fields.product_sku ?? '').trim()) { setSkuError('SKU 不能为空，请填写产品 SKU。'); setError('SKU 不能为空，请填写产品 SKU。'); setTab('基础资料'); return; }
    setBusy(true);
    const changes = Object.fromEntries(Object.entries(fields).filter(([name, v]) => JSON.stringify(product?.fields[name]) !== JSON.stringify(v)));
    const body = { expectedVersion: product?.version ?? 0, changes, assets: product ? assets : null }; const fingerprint = JSON.stringify(body);
    if (pending.current.fingerprint !== fingerprint) pending.current = { fingerprint, id: crypto.randomUUID() };
    try { show(await api<Product>(product ? `/products/${product.id}` : '/products', product ? 'PATCH' : 'POST', { ...body, requestId: pending.current.id })); setMessage('Web 已保存，已进入同步队列'); } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请稍后重试。'); } finally { setBusy(false); }
  }
  async function upload(file: File, field: Field, repetition: number) {
    if (readOnly || !product || busy) return;
    if (['產品照片', '产品规格书'].includes(assetGroup(field.name)) && !/^image\/(png|jpeg|webp|gif)$/.test(file.type)) { setError('产品图片只支持 JPG、PNG、WebP 或 GIF。'); return; }
    if (file.size > 100 * 1024 * 1024) { setError('文件不能超过 100 MB。'); return; }
    if (product.previewMode) { const id = crypto.randomUUID(); localFiles.current.set(id, file); setAssets(old => [...old.filter(a => a.field !== field.name || a.repetition !== repetition), { id, field: field.name, repetition, filename: file.name, mimeType: file.type, size: file.size }]); setError(''); setMessage('图片已加入当前草稿，尚未保存。'); return; }
    setBusy(true); setError('');
    try {
      const hash = await crypto.subtle.digest('SHA-256', await file.arrayBuffer()); const sha256 = Array.from(new Uint8Array(hash)).map(v => v.toString(16).padStart(2, '0')).join('');
      const response = await api<{ id: string; url: string; headers: Record<string, string> }>(`/products/${product.id}/uploads`, 'POST', { requestId: crypto.randomUUID(), filename: file.name, mimeType: file.type || 'application/octet-stream', size: file.size, sha256, field: field.name, repetition });
      const put = await fetch(response.url, { method: 'PUT', headers: response.headers, body: file }); if (!put.ok) throw new Error('文件上传失败');
      const attachment = await api<Asset>(`/products/${product.id}/uploads/${response.id}/complete`, 'POST', {});
      setAssets(old => [...old.filter(a => a.field !== field.name || a.repetition !== repetition), attachment]); setMessage('附件已校验，请保存本次修改');
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }
  async function download(a: Asset) {
    try {
      const local = localFiles.current.get(a.id); if (local) { const url = URL.createObjectURL(local); const link = document.createElement('a'); link.href = url; link.download = a.filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000); return; }
      const r = await fetch(`${apiBase}/api/product-master/products/${product?.id}/assets/${a.id}`, { headers: { Authorization: `Bearer ${token}` } }); if (!r.ok) throw new Error('附件尚未保存或无法读取');
      const url = URL.createObjectURL(await r.blob()); const link = document.createElement('a'); link.href = url; link.download = a.filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) { setError(String(e)); }
  }
  async function restore(version: number) {
    if (!product || !window.confirm(`恢复到版本 ${version}？这会生成新版本并自动同步。`)) return;
    setBusy(true); try { show(await api<Product>(`/products/${product.id}/restore/${version}`, 'POST', { requestId: crypto.randomUUID(), expectedVersion: product.version })); } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  const value = (name: string) => String(fields[name] ?? '');
  const containers = schema.filter(f => f.result === 'container').sort((a, b) => { const ai = productPhotoFields.indexOf(a.name), bi = productPhotoFields.indexOf(b.name); return ai >= 0 || bi >= 0 ? (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) : a.name.localeCompare(b.name, 'zh-Hant', { numeric: true }); });
  const visibleAssets = assets.filter(a => isEditorField(a.field));
  const currentAsset = selectedAsset && assets.some(a => a.id === selectedAsset.id) ? selectedAsset : null;
  const changeCount = Object.entries(fields).filter(([name, v]) => JSON.stringify(product?.fields[name]) !== JSON.stringify(v)).length
    + (JSON.stringify(assets) !== JSON.stringify(product?.assets ?? []) ? 1 : 0);
  const heroAsset = assets.find(a => a.field === 'image_main');
  const canViewQuotes = !!permissions.canManageAccounts && !!permissions.canViewPrice;
  const quoteTabs = product && canViewQuotes ? ['客户群报价'] : [];
  const tabs = readOnly ? ['基础资料', ...nativeTabs, ...quoteTabs] : ['基础资料', ...nativeTabs, ...quoteTabs, '修改历史', '同步状态'];
  const find = (name: string) => schema.find(f => f.name === name && f.result !== 'container');
  const writableField = (f: Field) => !readOnly && f.writable && f.name !== 'ID' && (product?.previewMode || (canEdit && permissions[f.writePermission ?? 'canEditProducts']));
  const label = (name: string) => fieldLabels[name] ?? name;

  function readOnlyTag(f: Field) {
    if (f.name === 'ID') return '标识';
    if (/CBM|Stock_USD|PrePaid_stock_USD|^stock$|建議報價|報價積數|組裝成本/.test(f.name)) return '计算';
    return '只读';
  }

  function inputFor(f: Field, i: number, cls = '') {
    const v = String(Array.isArray(fields[f.name]) ? (fields[f.name] as unknown[])[i] ?? '' : i === 0 ? fields[f.name] ?? '' : '');
    const change = (input: string) => { if (f.name === 'product_sku') setSkuError(''); setFields(p => { if (f.maxRepeat <= 1) return { ...p, [f.name]: input }; const values = Array.isArray(p[f.name]) ? [...p[f.name] as unknown[]] : [p[f.name] ?? '']; while (values.length < f.maxRepeat) values.push(''); values[i] = input; return { ...p, [f.name]: values }; }); };
    const writable = writableField(f);
    const presentation = fieldPresentation(f, controls[f.name]?.type === 'checkBox');
    const long = presentation === 'name' || presentation === 'notes';
    const props = { 'aria-label': `${f.name} ${i + 1}`, 'aria-invalid': f.name === 'product_sku' && !!skuError, 'aria-describedby': f.name === 'product_sku' && skuError ? 'pm-sku-error' : undefined, readOnly: !writable, disabled: busy || loading, value: v, placeholder: '—', onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => change(e.target.value) };
    const control = controls[f.name] ?? (draftFlags[f.name] ? { type: 'checkBox', options: [{ value: draftFlags[f.name], label: '是' }], searchable: false } : undefined);

    if (!writable && presentation !== 'meta') {
      if (control?.type === 'checkBox') return <div className="pm-val" key={i}>{v ? <span className="pm-chip pm-chip-ok">{v.split('\n').filter(Boolean).join(' · ') || '是'}</span> : <span className="pm-val-empty">—</span>}</div>;
      return <div className={`pm-val ${cls}`} key={i} title={v}>{v || <span className="pm-val-empty">—</span>}</div>;
    }
    if (presentation === 'meta') return <output className="pm-val" key={i} title={v}>{v || '—'}</output>;
    if (control?.searchable) return <button type="button" key={i} className="pm-picker" disabled={!writable || busy || loading} aria-label={`选择 ${label(f.name)}`} onClick={() => openPicker(f.name, i + 1)}><span>{v || '请选择'}</span><Search size={14} /></button>;
    if (control?.type === 'checkBox') return <div className="pm-checks" key={i}>{control.options.map(o => <label key={o.value}><input type="checkbox" aria-label={`${label(f.name)} ${i + 1}`} disabled={!writable || busy || loading} checked={v.split('\n').includes(o.value)} onChange={e => change(e.target.checked ? [...v.split('\n').filter(Boolean), o.value].join('\n') : v.split('\n').filter(x => x !== o.value).join('\n'))} />{o.label === '1' ? '是' : o.label}</label>)}</div>;
    if (control && ['popupList', 'popupMenu', 'radioButtons'].includes(control.type)) return <select key={i} className={cls} aria-label={`${f.name} ${i + 1}`} disabled={!writable || busy || loading} value={v} onChange={e => change(e.target.value)}><option value="">请选择</option>{v && !control.options.some(o => o.value === v) && <option value={v}>{v}</option>}{control.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>;
    if (control?.type === 'calendar') {
      const match = v.match(/^(\d{2})\/(\d{2})\/(\d{4})$/); const date = match ? `${match[3]}-${match[1]}-${match[2]}` : v;
      return <input key={i} className={cls} {...props} type="date" value={date} />;
    }
    return long
      ? <textarea key={i} className={cls} {...props} rows={presentation === 'name' ? 1 : 3} />
      : <input key={i} className={cls} {...props} inputMode={f.result === 'number' ? 'decimal' : undefined} />;
  }

  function fieldControl(f: Field) {
    if (f.name === 'id_client' && schema.some(field => field.name === 'Client')) return null;
    if (f.name === 'Client') {
      const customerFields = schema.filter(field => ['Client', 'id_client'].includes(field.name));
      const editable = !readOnly && customerFields.length === 2 && customerFields.every(field => field.writable && (product?.previewMode || (canEdit && permissions[field.writePermission ?? 'canEditProducts'])));
      return <section className="pm-customer" key={f.name} aria-label="客户资料">
        <div className="pm-customer-main"><span className="k">客户</span><span className="v">{value('Client') || '未选择客户'}</span></div>
        {customerFields.some(field => field.name === 'id_client') && <div className="pm-customer-code"><span className="k">编号</span><span className="v">{value('id_client') || '—'}</span></div>}
        {!readOnly && <button type="button" disabled={!editable || busy || loading} onClick={() => openPicker('Client', 1)}>{value('Client') ? '更换' : '选择客户'}</button>}
      </section>;
    }
    const writable = writableField(f);
    const presentation = fieldPresentation(f, controls[f.name]?.type === 'checkBox');
    return <div className={`pm-f pm-f-${presentation}${f.name === '審核' ? ' pm-f-review' : ''}${writable ? '' : ' is-readonly'}`} key={f.name} title={f.name}>
      <span className="pm-f-label">
        {label(f.name)}
        {!readOnly && f.required && <em className="pm-req"> *</em>}
        {!readOnly && !writable && <span className="pm-chip pm-chip-calc">{readOnlyTag(f)}</span>}
      </span>
      {!readOnly && f.name === '系統產品編號' ? <div className="pm-field-action">
        {inputFor(f, 0)}
        <button type="button" disabled={!writable || busy || loading || !value('product_sku').trim()}
          title={value('product_sku').trim() ? '将 SKU 复制到系统编号' : '请先填写 SKU'}
          onClick={() => setFields(previous => {
            const sku = String(previous.product_sku ?? '');
            return sku.trim() ? { ...previous, 系統產品編號: sku } : previous;
          })}>同 SKU</button>
      </div> : Array.from({ length: f.maxRepeat || 1 }, (_, i) => inputFor(f, i))}
      {f.name === 'product_sku' && skuError && <small id="pm-sku-error" className="pm-f-error" role="alert">{skuError}</small>}
    </div>;
  }

  function measureBlock(group: typeof measureGroups[string][number], key: string) {
    const fs = group.fields.map(find).filter((f): f is Field => !!f);
    if (!fs.length) return null;
    const derived = group.derived ? find(group.derived) : undefined;
    return <section className="pm-measure" key={key}>
      <div className="pm-measure-head"><span className="k">{group.title}</span>{group.unit && <span className="pm-chip pm-chip-calc">{group.unit}</span>}</div>
      <div className="pm-measure-row">
        {fs.flatMap((f, index) => [
          ...(index > 0 ? [<span className="pm-measure-sep" key={`sep-${f.name}`}>{group.separators?.[index - 1] ?? '·'}</span>] : []),
          <div className="pm-measure-cell" key={f.name} title={f.name}>{inputFor(f, 0, 'pm-num')}</div>,
        ])}
        {derived && <div className="pm-measure-derived"><b>{value(derived.name) || '—'}</b><span>{group.derivedLabel ?? label(derived.name)}</span></div>}
      </div>
      {group.note && <div className="pm-measure-note"><span>{group.note}</span>{derived && <span>{label(derived.name)} 由系统计算</span>}</div>}
    </section>;
  }

  function foldBlock(section: string, group: { title: string; fields: string[]; hint: string }, index: number) {
    const fs = group.fields.map(find).filter((f): f is Field => !!f);
    if (!fs.length) return null;
    const key = `${section}:${index}`;
    const open = !!openFolds[key];
    const filled = fs.filter(f => value(f.name).trim()).length;
    return <div className={`pm-fold${open ? ' is-open' : ''}`} key={key}>
      <button type="button" className="pm-fold-toggle" aria-expanded={open} onClick={() => setOpenFolds(p => ({ ...p, [key]: !p[key] }))}>
        <Plus size={12} />
        <b>{group.title}</b>
        <span>已填 {filled} / {fs.length} 项 · {group.hint}</span>
      </button>
      {open && <div className="pm-grid pm-fold-body">{fs.map(fieldControl)}</div>}
    </div>;
  }

  function sectionInner(title: string, names: string[]) {
    const measures = measureGroups[title] ?? [];
    const folds = foldedGroups[title] ?? [];
    const bands = title === '报价信息' ? priceBands : [];
    const claimed = new Set<string>([
      ...measures.flatMap(g => [...g.fields, ...(g.derived ? [g.derived] : [])]),
      ...folds.flatMap(g => g.fields),
      ...bands.flatMap(b => b.fields),
    ]);
    const rest = names.filter(n => !claimed.has(n)).map(find).filter((f): f is Field => !!f);
    const bandBlocks = bands.map(band => ({ title: band.title, fs: band.fields.map(find).filter((f): f is Field => !!f) })).filter(b => b.fs.length);
    const total = names.map(find).filter(Boolean).length;
    if (!total) return null;
    return <>
      {!!rest.length && <div className="pm-grid">{rest.map(fieldControl)}</div>}
      {!!measures.length && <div className="pm-measures">{measures.map((g, i) => measureBlock(g, `${title}:${i}`))}</div>}
      {bandBlocks.map(band => <div className="pm-band" key={band.title}>
        <div className="pm-band-head"><span>{band.title}</span><i /></div>
        <div className="pm-grid pm-grid-bands">{band.fs.map(fieldControl)}</div>
      </div>)}
      {folds.map((g, i) => foldBlock(title, g, i))}
    </>;
  }

  function formCard(title: string, names: string[], caption?: string) {
    const inner = sectionInner(title, names);
    if (!inner) return null;
    return <section className="pm-card" id={`pm-section-${title}`} key={title}>
      <div className="pm-card-head"><i className="pm-card-rule" /><h2>{title}</h2></div>
      {caption && <p className="pm-caption">{caption}</p>}
      <div className="pm-card-body">{inner}</div>
    </section>;
  }

  /** 报价信息（左）与库存信息（右）合并为一个区域，紧跟在产品信息之后展示。 */
  function splitCard(id: string, left: { title: string; names: string[] }, right: { title: string; names: string[] }) {
    const leftInner = sectionInner(left.title, left.names);
    const rightInner = sectionInner(right.title, right.names);
    if (!leftInner && !rightInner) return null;
    return <section className="pm-card" id={`pm-section-${id}`} key={id}>
      <div className="pm-card-head"><i className="pm-card-rule" /><h2>{left.title} · {right.title}</h2></div>
      <div className="pm-card-body pm-split">
        {leftInner && <div className="pm-split-col" id={`pm-section-${left.title}`}>
          <div className="pm-split-col-head">{left.title}</div>
          {leftInner}
        </div>}
        {rightInner && <div className="pm-split-col" id={`pm-section-${right.title}`}>
          <div className="pm-split-col-head">{right.title}</div>
          {rightInner}
        </div>}
      </div>
    </section>;
  }

  function slotLabel(f: Field, repetition: number) {
    const photo = assetGroup(f.name) === '產品照片';
    if (photo) return f.name === 'image_main' ? '主图' : String(productPhotoFields.indexOf(f.name) + 1).padStart(2, '0');
    return f.name + (f.maxRepeat > 1 ? ` · ${repetition}` : '');
  }

  function photoSlot(f: Field, repetition: number, hero = false) {
    const a = assets.find(a => a.field === f.name && a.repetition === repetition);
    const reason = a ? unsupportedPreviewReason(a) || previewErrors[a.id] : '';
    const editable = !readOnly && f.writable && (canEdit || (!!product?.previewMode && ['產品照片', '产品规格书'].includes(assetGroup(f.name))));
    const slot = `${f.name}:${repetition}`;
    const pendingFile = product?.pendingAssetFields?.includes(f.name);
    const onDrop = (e: React.DragEvent) => { e.preventDefault(); setDragSlot(''); if (!editable || busy) return; const files = Array.from(e.dataTransfer.files); if (files.length !== 1) { setError('每个图片位置请拖入一张图片。'); return; } void upload(files[0], f, repetition); };
    const dragProps = {
      onDragOver: (e: React.DragEvent) => { if (editable) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setDragSlot(slot); } },
      onDragLeave: () => setDragSlot(''),
      onDrop,
    };
    if (!a) return <label className={`pm-slot pm-slot-empty${hero ? ' pm-slot-hero' : ''}${dragSlot === slot ? ' is-drag' : ''}`} key={slot} title={f.name} {...dragProps}>
      {readOnly ? <ImageIcon size={hero ? 24 : 16} /> : <Plus size={hero ? 24 : 16} />}
      <span className="pm-slot-n">{slotLabel(f, repetition)}</span>
      {pendingFile && <span className="pm-slot-pending">待复制</span>}
      {editable && <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" aria-label={`上传 ${f.name}`} disabled={!product || busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file, f, repetition); e.target.value = ''; }} />}
    </label>;
    return <figure className={`pm-slot${hero ? ' pm-slot-hero' : ''}${dragSlot === slot ? ' is-drag' : ''}`} key={slot} title={f.name} {...dragProps}>
      <span className="pm-slot-badge">{slotLabel(f, repetition)}</span>
      {hero && <span className="pm-slot-hero-tag">主图</span>}
      {!reason && previews[a.id] && a.mimeType.startsWith('image/')
        ? <img src={previews[a.id]} alt={f.name} onError={() => setPreviewErrors(p => ({ ...p, [a.id]: '图片解码失败，请下载原文件查看。' }))} />
        : <span className="pm-slot-placeholder" title={reason}>{reason ? unsupportedPreviewReason(a, true) || '预览加载失败，请查看说明' : (a.mimeType === 'application/pdf' ? 'PDF' : '载入中…')}</span>}
      <div className="pm-slot-tools">
        <button type="button" onClick={() => setSelectedAsset(a)}>{reason ? '查看说明' : '预览'}</button>
        {editable && <label className="pm-slot-replace">替换<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" aria-label={`替换 ${f.name}`} disabled={!product || busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file, f, repetition); e.target.value = ''; }} /></label>}
        {editable && <button type="button" disabled={busy} onClick={() => setAssets(p => p.filter(x => x.id !== a.id))}>移除</button>}
      </div>
    </figure>;
  }

  function photoGallery(title: string, fs: Field[]) {
    if (!fs.length) return null;
    const slots = fs.flatMap(f => Array.from({ length: f.maxRepeat || 1 }, (_, i) => ({ f, repetition: i + 1 })));
    const used = slots.filter(s => assets.some(a => a.field === s.f.name && a.repetition === s.repetition)).length;
    return <section className="pm-card" key={title}>
      <div className="pm-card-head"><i className="pm-card-rule" /><h2>{title}</h2>
        <div className="pm-progress"><span className="track"><span className="fill" style={{ width: `${slots.length ? Math.round(used / slots.length * 100) : 0}%` }} /></span>{used} / {slots.length} 位置</div>
      </div>
      <div className="pm-card-body pm-slots">
        {slots.map(s => photoSlot(s.f, s.repetition, s.f.name === 'image_main'))}
        <p className="pm-slots-note">{readOnly ? '点击预览查看图片，可下载原文件。' : '主图独立管理，其余为产品图片 02–18。'}</p>
      </div>
    </section>;
  }

  function docList(title: string, fs: Field[]) {
    if (!fs.length) return null;
    const slots = fs.flatMap(f => Array.from({ length: f.maxRepeat || 1 }, (_, i) => ({ f, repetition: i + 1 })));
    const used = slots.filter(s => assets.some(a => a.field === s.f.name && a.repetition === s.repetition)).length;
    return <section className="pm-card" key={title}>
      <div className="pm-card-head"><i className="pm-card-rule" /><h2>{title}</h2><div className="pm-card-meta">{used} / {slots.length} 位置</div></div>
      <div className="pm-card-body pm-docs">
        {slots.map(({ f, repetition }) => {
          const a = assets.find(a => a.field === f.name && a.repetition === repetition);
          const editable = !readOnly && f.writable && (canEdit || (!!product?.previewMode && assetGroup(f.name) === '产品规格书'));
          const slot = `${f.name}:${repetition}`;
          return <div className={`pm-doc${a ? ' has-file' : ''}`} key={slot} title={f.name}>
            <span className="pm-doc-icon">{a && a.mimeType === 'application/pdf' ? <FileText size={18} /> : a ? <ImageIcon size={18} /> : <Plus size={18} />}</span>
            <div className="pm-doc-text">
              <b>{slotLabel(f, repetition)}</b>
              <span>{a ? `${a.filename} · ${(a.size / 1024).toFixed(0)} KB` : editable ? '拖入文件或点击上传' : '此位置暂无文件'}</span>
              {a && (unsupportedPreviewReason(a) || previewErrors[a.id]) && <span>{unsupportedPreviewReason(a) || previewErrors[a.id]}</span>}
            </div>
            <div className="pm-doc-actions">
              {a && <button type="button" className="pm-btn pm-btn-sm" onClick={() => setSelectedAsset(a)}>{unsupportedPreviewReason(a) || previewErrors[a.id] ? '查看说明' : '预览'}</button>}
              {a && !localFiles.current.has(a.id) && <button type="button" className="pm-btn pm-btn-sm" onClick={() => void download(a)}><Download size={12} /> 下载</button>}
              {editable && <label className="pm-btn pm-btn-sm pm-upload">{a ? '替换' : '上传'}<input type="file" accept={assetGroup(f.name) === '产品规格书' ? 'image/jpeg,image/png,image/webp,image/gif' : undefined} aria-label={`上传 ${f.name}`} disabled={!product || busy} onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file, f, repetition); e.target.value = ''; }} /></label>}
              {a && editable && <button type="button" className="pm-btn pm-btn-sm" disabled={busy} onClick={() => setAssets(p => p.filter(x => x.id !== a.id))}>移除</button>}
            </div>
          </div>;
        })}
      </div>
    </section>;
  }

  if (!token) return <main className="product-master"><p className="pm-boot">正在验证登录信息，请从 FileMaker 打开。</p></main>;

  return <main className={`product-master${readOnly ? " pm-browser" : ""}`}>
    <header className="pm-bar">
      <div className="pm-thumb" title={heroAsset ? unsupportedPreviewReason(heroAsset) || previewErrors[heroAsset.id] : undefined}>
        {heroAsset && !unsupportedPreviewReason(heroAsset) && !previewErrors[heroAsset.id] && previews[heroAsset.id]
          ? <img src={previews[heroAsset.id]} alt="产品主图" onError={() => setPreviewErrors(p => ({ ...p, [heroAsset.id]: '图片解码失败，请下载原文件查看。' }))} />
          : <ImageIcon size={18} aria-hidden="true" />}
      </div>
      <div className="pm-identity">
        <div className="pm-identity-top">
          <span className="pm-sku">{value('product_sku') || '当前产品'}</span>
          {value('審核') && <span className={`pm-chip ${value('審核') === '已審核' ? 'pm-chip-ok' : 'pm-chip-warn'}`}>{value('審核')}</span>}
        </div>
        <div className="pm-identity-sub">
          {[value('產品名稱_中文') || value('product_name'), value('Client') && `${value('Client')}${value('id_client') ? ` (${value('id_client')})` : ''}`, value('系統產品編號') && `系统编号 ${value('系統產品編號')}`].filter(Boolean).join(' · ') || '—'}
        </div>
      </div>
      <div className="pm-bar-actions">
        {readOnly ? <span className="pm-chip"><LockKeyhole size={12} />只读浏览</span> : <>
        <div className="pm-save-state">
          <b className={dirty ? 'is-dirty' : ''}>{loading ? '正在载入' : quoteDirty ? '报价尚未保存' : dirty ? `${changeCount} 处未保存` : product ? `Web 版本 ${product.version}` : '新产品'}</b>
          <span>{product?.previewMode ? '草稿预览 · 本地' : canEdit ? '可保存' : '只读'}</span>
        </div>
        <button type="button" className="pm-btn" disabled={busy || quoteBusy} onClick={cancelEditing}>取消</button>
        <button type="button" className="pm-btn pm-btn-primary" disabled={!canEdit || busy || loading || (!productDirty && !!product)} onClick={() => void save()}><Save size={14} />{busy ? '处理中…' : '保存产品资料'}</button></>}
      </div>
    </header>

    {error && <div role="alert" className="pm-notice pm-notice-error"><AlertCircle size={15} />{error}</div>}
    {message && <div className="pm-notice pm-notice-ok" role="status"><CircleCheck size={15} />{message}</div>}
    {!readOnly && product?.previewMode && <div className="pm-notice"><LockKeyhole size={14} /><span>产品资料预览：基础字段可试填，产品保存与回写尚未开放；客户群报价使用独立保存权限。</span></div>}
    {product?.assetImportError && <div role="alert" className="pm-notice pm-notice-error"><AlertCircle size={15} />{product.assetImportError}</div>}
    {loading && <div className="pm-notice" role="status"><RotateCw className="pm-spin" size={15} /> 正在读取当前产品并校验全部容器；首次加载图片可能需要较长时间。</div>}

    <div className="pm-shell">
      <nav className="pm-rail" aria-label={readOnly ? "产品资料导航" : "编辑器导航"}>
        <div className="pm-rail-label">模块</div>
        {tabs.map(t => <button type="button" key={t} className="pm-rail-tab" aria-current={tab === t} disabled={quoteBusy} onClick={() => { if (t !== tab && quoteDirty && !window.confirm('当前报价尚未保存，是否放弃修改并切换栏目？')) return; setTab(t); window.scrollTo(0, 0); }}>
          {TAB_ICONS[t] ?? <Layers size={14} />}<span>{t}</span>
        </button>)}
        {tab === '基础资料' && <>
          <div className="pm-rail-label">本页分区</div>
          {Object.keys(basicSections).map(section => <button type="button" key={section} className="pm-rail-anchor" onClick={() => document.getElementById(`pm-section-${section}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}>
            <span>{section}</span>
          </button>)}
        </>}
        {product && <div className="pm-rail-foot">
          {readOnly ? '产品资料' : product.previewMode ? '草稿预览' : `Web 版本 ${product.version}`}<br />
          <code>{value('ID') || product.id}</code>
        </div>}
      </nav>

      <div className="pm-main" id="pm-tab-content" role="tabpanel" aria-label={tab}>
        {conflict && <section className="pm-conflict"><h2>此产品已有新修改</h2><p>你的输入仍保留，请比较差异后载入最新版本。</p><pre>{JSON.stringify({ 当前已保存: conflict.fields, 本次输入: fields }, null, 2)}</pre><button type="button" className="pm-btn" onClick={() => show(conflict)}>加载最新版本</button></section>}

        {tab === '基础资料' && <>
          {(() => {
            const nodes: ReactNode[] = [];
            for (const [title, names] of Object.entries(basicSections)) {
              if (title === '报价信息' || title === '库存信息') continue;
              nodes.push(formCard(title, names));
              if (title === '产品信息') nodes.push(splitCard('报价与库存', { title: '报价信息', names: basicSections['报价信息'] }, { title: '库存信息', names: basicSections['库存信息'] }));
            }
            return nodes;
          })()}
          <section className="pm-record-meta" aria-label="记录信息">
            {schema.filter(f => recordMetaFields.includes(f.name)).map(f => <div className="pm-meta-item" key={f.name}><span>{label(f.name)}</span><b>{value(f.name) || '—'}</b></div>)}
            {schema.some(f => f.name === 'ID') && <div className="pm-meta-item"><span>UUID</span><code>{value('ID')}</code></div>}
          </section>
        </>}

        {nativeTabs.includes(tab as typeof nativeTabs[number]) && <>
          {tab === '產品照片'
            ? photoGallery(tab, containers.filter(f => assetGroup(f.name) === tab))
            : docList(tab, containers.filter(f => assetGroup(f.name) === tab))}
          {formCard(tab + '资料', (sectionFields[tab] ?? []).filter(n => !['審核', '新產品'].includes(n)))}
          {tab === '生產注意事項' && docList('包装与标签', containers.filter(f => assetGroup(f.name) === '包装与标签'))}
        </>}

        {tab === '客户群报价' && product && canViewQuotes && <ProductQuotes key={`${product.id}:${token}`} apiBase={apiBase} token={token} productId={product.id} readOnly={readOnly} onDirty={setQuoteDirty} onBusy={setQuoteBusy} />}
        {tab === '修改历史' && <section className="pm-card"><div className="pm-card-head"><i className="pm-card-rule" /><h2>修改历史</h2></div><div className="pm-card-body">
          {history.length ? history.map(h => <details className="pm-history" key={h.version}><summary>版本 {h.version} · {h.actor.name || h.actor.account} · {new Date(h.created_at).toLocaleString()}</summary><pre>{JSON.stringify({ 修改前: h.before_data, 修改后: h.after_data }, null, 2)}</pre><div className="pm-history-actions"><button type="button" className="pm-btn pm-btn-sm" disabled={!canEdit || busy} onClick={() => void restore(h.version)}>恢复为新版本</button>{h.after_data.assets.map(a => <button type="button" className="pm-btn pm-btn-sm" key={a.id} onClick={() => void download(a)}>下载 {a.filename}</button>)}</div></details>)
            : <p className="pm-empty-text">预览期间未开放编辑；启用后，每次保存的修改与原文件都可在这里追溯。</p>}
        </div></section>}

        {tab === '同步状态' && <section className="pm-card"><div className="pm-card-head"><i className="pm-card-rule" /><h2>同步状态</h2></div><div className="pm-card-body pm-sync">
          {!!sync?.drift?.length && <div className="pm-conflict"><h2>发现 FileMaker 本地变更</h2><p>Web 资料和文件已保留。请选择处理方式。</p><pre>{JSON.stringify(sync.drift.map(d => d.observed), null, 2)}</pre>{permissions.canManageProductSync && <><button type="button" className="pm-btn" onClick={async () => { const reason = window.prompt('以当前 Web 完整版本覆盖 FileMaker，请填写原因'); if (reason) try { await api(`/products/${product?.id}/rewrite-filemaker`, 'POST', { requestId: crypto.randomUUID(), reason }); if (product) show(await api<Product>(`/products/${product.id}`)); } catch (e) { setError(String(e)); } }}>重新回写完整 Web 版本</button><button type="button" className="pm-btn" onClick={async () => { const names = window.prompt('填写要采用的 FileMaker 字段名，用换行分隔'); if (!names) return; const reason = window.prompt('填写采用本地变更的原因'); if (reason) try { show(await api<Product>(`/products/${product?.id}/adopt-filemaker`, 'POST', { requestId: crypto.randomUUID(), expectedVersion: product?.version, fields: names.split('\n').filter(Boolean), reason })); } catch (e) { setError(String(e)); } }}>采用指定字段为新版本</button></>}</div>}
          <h3>FileMaker</h3>
          {sync && !sync.writeEnabled && <p className="pm-empty-text">FileMaker 回写尚未启用，已保存的修改会保留在同步队列。</p>}
          {sync?.filemaker.map(j => <div className="pm-sync-row" key={j.version}><p>版本 {j.version} · {({ pending: '等待同步', retry: '重试中', synced: '已同步', conflict: '需要处理冲突', superseded: '已由新的完整回写替代' } as Record<string, string>)[j.status] ?? j.status} {j.error}</p>{j.status !== 'synced' && permissions.canManageProductSync && <button type="button" className="pm-btn pm-btn-sm" onClick={() => { const reason = window.prompt('确认以 Web 版本重新回写，请填写处理原因'); if (reason) api(`/products/${product?.id}/retry/${j.version}`, 'POST', { requestId: crypto.randomUUID(), reason }).catch(e => setError(String(e))); }}>重新回写 Web 版本</button>}</div>)}
          <h3>DMS</h3>
          {sync?.dms.length ? sync.dms.map(c => <p className="pm-sync-row" key={c.consumer}>{c.consumer} · {c.synced ? '已同步' : '等待同步'}</p>) : <p className="pm-empty-text">尚无 DMS 同步确认</p>}
        </div></section>}
      </div>
    </div>

    <footer className="pm-foot"><span>{readOnly ? '产品资料 · 只读浏览' : quoteDirty ? '客户群报价尚未保存，请使用“保存此报价”' : dirty ? `有 ${changeCount} 处尚未保存的修改` : product?.previewMode ? '当前为草稿预览' : '产品资料和客户群报价分别保存并保留历史'} · {visibleAssets.length} 个附件</span></footer>

    {picker && <div className="pm-modal" role="dialog" aria-modal="true" aria-label={['Client', 'id_client'].includes(picker.field) ? '选择客户' : '选择 ' + picker.field} onKeyDown={e => { if (e.key === 'Escape') setPicker(null); }}>
      <section className="pm-choice">
        <header><h2>{['Client', 'id_client'].includes(picker.field) ? '选择客户' : '选择 ' + (fieldLabels[picker.field] ?? picker.field)}</h2><button type="button" aria-label="关闭选择" onClick={() => setPicker(null)}><X size={19} /></button></header>
        <label className="pm-choice-search"><Search size={17} /><input autoFocus aria-label="搜索选项" placeholder="输入名称或编号" value={query} onChange={e => { choiceBusy.current = true; setChoiceLoading(true); setChoices([]); setChoiceTotal(0); setChoiceError(''); setQuery(e.target.value); setChoiceOffset(0); }} /></label>
        <div className="pm-choice-list" ref={choiceList} aria-busy={choiceLoading} onScroll={e => loadMoreChoices(e.currentTarget)}>
          {choices.map(o => <button type="button" key={o.value} onClick={() => choose(o)}><strong>{o.name ?? o.label}</strong><small>{o.code ? `${o.code} · ${o.value}` : o.value}</small></button>)}
          {choiceLoading && <p role="status">{choices.length ? '正在加载更多…' : '正在读取…'}</p>}
          {choiceError && <div role="alert"><p>{choiceError}</p><button type="button" className="pm-btn pm-btn-sm" onClick={() => setChoiceRetry(n => n + 1)}>重试加载</button></div>}
          {!choiceLoading && !choiceError && !choices.length && <p>没有匹配的记录</p>}
        </div>
        <footer><span>{choiceLoading && !choices.length ? '搜索中…' : `已显示 ${choices.length} / ${choiceTotal} 条`}</span>{!choiceLoading && !choiceError && choices.length > 0 && <small>{choiceOffset + 50 < choiceTotal ? '向下滚动加载更多' : '已显示全部结果'}</small>}</footer>
      </section>
    </div>}

    {currentAsset && <div className="pm-modal" role="dialog" aria-modal="true" aria-label={currentAsset.field} onClick={() => setSelectedAsset(null)}>
      <div className="pm-preview" onClick={e => e.stopPropagation()}>
        <header>
          <div><h2>{currentAsset.field}</h2><p>{currentAsset.filename} · {(currentAsset.size / 1024).toFixed(0)} KB</p></div>
          <button type="button" className="pm-btn pm-btn-sm" onClick={() => void download(currentAsset)}><Download size={14} /> 下载原文件</button>
          <button type="button" autoFocus aria-label="关闭预览" className="pm-icon-btn" onClick={() => setSelectedAsset(null)}><X size={19} /></button>
        </header>
        {!unsupportedPreviewReason(currentAsset) && !previewErrors[currentAsset.id] && previews[currentAsset.id]
          ? currentAsset.mimeType.startsWith('image/')
            ? <img src={previews[currentAsset.id]} alt={currentAsset.field} onError={() => setPreviewErrors(p => ({ ...p, [currentAsset.id]: '图片解码失败，请下载原文件查看。' }))} />
            : <iframe title={currentAsset.field} src={previews[currentAsset.id]} />
          : <div className="pm-preview-empty"><FileText size={36} /><p>{unsupportedPreviewReason(currentAsset) || previewErrors[currentAsset.id] || '正在加载预览…'}</p></div>}
      </div>
    </div>}
  </main>;
}

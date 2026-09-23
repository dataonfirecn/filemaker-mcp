import { useEffect, useRef, useState } from 'react';
import './ProductQuotes.css';

type Customer = { id: string; name: string; code: string };
type Quote = {
  id: string; productId: string; version: number; title: string; amount: string;
  currency: string; enabled: boolean; customers: Customer[];
  updatedAt: string; updatedBy: { name?: string; account?: string };
  sourceId?: string; sourceData?: { fields?: { title?: string; customer?: string; status?: string } };
};
type Revision = { version: number; actor: Quote['updatedBy']; createdAt: string; before: Quote | null; after: Quote };
type Draft = { id?: string; version: number; title: string; amount: string; currency: string; enabled: boolean; customers: Customer[] };
type Choice = { value: string; name: string; code: string; label?: string; selectable?: boolean };

export default function ProductQuotes({ apiBase, token, productId, readOnly, onDirty, onBusy }: {
  apiBase: string; token: string; productId: string; readOnly: boolean; onDirty: (dirty: boolean) => void; onBusy: (busy: boolean) => void;
}) {
  const [rows, setRows] = useState<Quote[]>([]);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [baseline, setBaseline] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [total, setTotal] = useState(0);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [searchRetry, setSearchRetry] = useState(0);
  const [reload, setReload] = useState(0);
  const [history, setHistory] = useState<{ title: string; rows: Revision[] } | null>(null);
  const [conflict, setConflict] = useState<Quote | null>(null);
  const request = useRef({ fingerprint: '', id: '' });
  const historySequence = useRef(0);
  const dirty = draft !== null && JSON.stringify(draft) !== baseline;
  const canEdit = !readOnly && writeEnabled;
  const root = `${apiBase}/api/product-master`;
  const path = `/products/${productId}/quotes`;

  async function api<T>(url: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
    const response = await fetch(root + url, { method, signal,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    const value = await response.json();
    if (!response.ok) {
      if (response.status === 409 && value.detail?.current) setConflict(value.detail.current);
      throw new Error(typeof value.detail === 'string' ? value.detail : value.detail?.message ?? '报价操作失败，请重试');
    }
    return value as T;
  }

  useEffect(() => { onDirty(dirty || busy); }, [dirty, busy, onDirty]);
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  useEffect(() => () => { onDirty(false); onBusy(false); historySequence.current++; }, [onDirty, onBusy]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    api<{ rows: Quote[]; writeEnabled: boolean }>(path, 'GET', undefined, controller.signal)
      .then(result => { setRows(result.rows); setWriteEnabled(result.writeEnabled); })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [productId, token, reload]);
  useEffect(() => {
    if (!draft) return;
    const controller = new AbortController(); setSearchBusy(true); setSearchError(''); setChoices([]);
    const timer = window.setTimeout(() => {
      api<{ rows: Choice[]; total: number }>(`/customers?q=${encodeURIComponent(query)}&offset=${offset}`, 'GET', undefined, controller.signal)
        .then(result => { setChoices(result.rows); setTotal(result.total); })
        .catch(e => { if (!controller.signal.aborted) setSearchError(e.message); })
        .finally(() => { if (!controller.signal.aborted) setSearchBusy(false); });
    }, 250);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [!!draft, query, offset, token, searchRetry]);

  function open(row?: Quote) {
    if (dirty && !window.confirm('当前报价尚未保存，是否放弃修改？')) return;
    const next: Draft = row ? { id: row.id, version: row.version, title: row.title, amount: row.amount,
      currency: row.currency, enabled: row.enabled, customers: row.customers }
      : { version: 0, title: '', amount: '', currency: 'USD', enabled: true, customers: [] };
    setDraft(next); setBaseline(JSON.stringify(next)); setConflict(null); setError(''); setMessage(''); setQuery(''); setOffset(0);
  }
  function cancel() {
    if (dirty && !window.confirm('放弃当前报价的未保存修改？')) return;
    setDraft(null); setConflict(null);
  }
  async function save() {
    if (!draft || busy || !canEdit) return;
    if (!draft.title.trim() || !draft.amount.trim() || !draft.customers.length) {
      setError('请填写报价名称、金额并至少选择一个客户'); return;
    }
    const body = { expectedVersion: draft.version, title: draft.title, amount: draft.amount,
      currency: draft.currency, enabled: draft.enabled, customerIds: draft.customers.map(c => c.id) };
    const fingerprint = JSON.stringify([draft.id, body]);
    if (request.current.fingerprint !== fingerprint) request.current = { fingerprint, id: crypto.randomUUID() };
    setBusy(true); setError(''); setMessage(''); setConflict(null);
    try {
      const saved = await api<Quote>(draft.id ? `${path}/${draft.id}` : path, draft.id ? 'PATCH' : 'POST',
        { ...body, requestId: request.current.id });
      setRows(current => [...current.filter(r => r.id !== saved.id), saved]);
      setDraft(null); setHistory(null); historySequence.current++;
      setMessage('报价已保存到 Web，未回写 FileMaker 或用于订单取价。');
      request.current = { fingerprint: '', id: '' };
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败，请重试'); }
    finally { setBusy(false); }
  }
  async function showHistory(row: Quote) {
    const sequence = ++historySequence.current; setError('');
    try {
      const result = await api<{ rows: Revision[] }>(`${path}/${row.id}/history`);
      if (sequence === historySequence.current) setHistory({ title: row.title, rows: result.rows });
    } catch (e) { if (sequence === historySequence.current) setError(e instanceof Error ? e.message : '读取历史失败'); }
  }
  function describe(q: Quote | null) {
    return q ? `${q.title} · ${q.currency} ${q.amount} · ${q.enabled ? '启用' : '停用'}\n客户：${q.customers.map(c => `${c.name} (${c.code})`).join('、')}` : '尚未创建';
  }

  return <section className="pm-card pq-section" aria-label="客户群报价">
    <div className="pm-card-head"><h2>客户群报价</h2>
      <button type="button" className="pm-btn pm-btn-primary" disabled={!canEdit || busy || loading} onClick={() => open()}>新增报价</button></div>
    <div className="pm-card-body">
      <p className="pq-notice">Web 独立维护 · 修改尚未同步至 FileMaker 旧报价和订单。每条报价的客户成员独立保存。</p>
      {!loading && !canEdit && <p>当前为只读查看；报价保存需价格编辑权限及报价写入开关。</p>}
      {error && <div role="alert" className="pq-error">{error} <button type="button" className="pm-btn pm-btn-sm" disabled={busy || dirty} onClick={() => setReload(r => r + 1)}>刷新列表</button></div>}
      {message && <p role="status">{message}</p>}
      {loading ? <p role="status">正在加载报价…</p> : <div className="pq-table-wrap"><table className="pq-table">
        <thead><tr><th>报价名称／原权限标识</th><th>金额</th><th>适用客户群</th><th>状态</th><th>最后修改</th><th>操作</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}>
          <td>{row.title}{row.sourceId && <small>原报价：{row.sourceData?.fields?.title || row.title}</small>}</td>
          <td className="pq-money">{row.currency} {row.amount}</td>
          <td>{row.customers.map(c => <span className="pq-member" key={c.id}>{c.name} <small>{c.code}</small></span>)}</td>
          <td>{row.enabled ? '启用' : '停用'}</td>
          <td>{row.updatedBy.name || row.updatedBy.account}<small>{new Date(row.updatedAt).toLocaleString()}</small></td>
          <td><div className="pq-actions"><button type="button" className="pm-btn pm-btn-sm" disabled={!canEdit || busy} onClick={() => open(row)}>编辑</button>
            <button type="button" className="pm-btn pm-btn-sm" disabled={busy} onClick={() => void showHistory(row)}>历史</button></div></td>
        </tr>)}</tbody>
      </table>{!rows.length && <p>暂无客户群报价。可新增报价，或先导入原 FileMaker 报价。</p>}</div>}
      {draft && <form className="pq-editor" onSubmit={event => { event.preventDefault(); void save(); }}>
        <h3>{draft.id ? '编辑报价' : '新增报价'}</h3>
        <fieldset disabled={busy || !canEdit}>
          <div className="pq-fields">
            <label>报价名称／权限标识<input required maxLength={200} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} /></label>
            <label>金额<input required inputMode="decimal" maxLength={80} value={draft.amount} onChange={e => setDraft({ ...draft, amount: e.target.value })} /></label>
            <label>币种<select aria-label="币种" value={draft.currency} onChange={e => setDraft({ ...draft, currency: e.target.value })}>{['USD', 'CNY', 'TWD'].map(c => <option key={c}>{c}</option>)}</select></label>
            <label>状态<select aria-label="状态" value={draft.enabled ? 'enabled' : 'disabled'} onChange={e => setDraft({ ...draft, enabled: e.target.value === 'enabled' })}><option value="enabled">启用</option><option value="disabled">停用（保留历史）</option></select></label>
          </div>
          <h4>适用客户群 · 已选 {draft.customers.length} 位</h4>
          <div className="pq-selected">{draft.customers.map(c => <button type="button" className="pq-member" key={c.id} aria-label={`移除客户 ${c.name}`} onClick={() => setDraft({ ...draft, customers: draft.customers.filter(m => m.id !== c.id) })}>{c.name} ({c.code}) ×</button>)}</div>
          <label>搜索客户<input value={query} placeholder="客户名称或代码" onChange={e => { setQuery(e.target.value); setOffset(0); }} /></label>
          {searchBusy ? <p role="status">正在搜索…</p> : searchError ? <p role="alert">{searchError} <button type="button" onClick={() => setSearchRetry(r => r + 1)}>重试</button></p> : <div className="pq-choices">
            {choices.map(c => <label key={c.value}><input type="checkbox" disabled={c.selectable === false && !draft.customers.some(m => m.id === c.value)} checked={draft.customers.some(m => m.id === c.value)} onChange={e => setDraft({ ...draft, customers: e.target.checked ? [...draft.customers, { id: c.value, name: c.name, code: c.code }] : draft.customers.filter(m => m.id !== c.value) })} />{c.label || c.name} <small>{c.code}</small></label>)}
            {!choices.length && <p>未找到客户</p>}
          </div>}
          <div className="pq-actions"><button type="button" className="pm-btn pm-btn-sm" disabled={searchBusy || offset === 0} onClick={() => setOffset(n => n - 50)}>上一页</button>
            <span>共 {total} 位客户</span><button type="button" className="pm-btn pm-btn-sm" disabled={searchBusy || offset + 50 >= total} onClick={() => setOffset(n => n + 50)}>下一页</button></div>
        </fieldset>
        {conflict && <div role="alert" className="pq-error"><p>这条报价已被其他人修改。你的输入仍保留；请核对最新版本。</p><pre>{describe(conflict)}</pre>
          <button type="button" className="pm-btn" onClick={() => open(conflict)}>载入最新版本（放弃当前输入）</button></div>}
        <div className="pq-actions"><button type="submit" className="pm-btn pm-btn-primary" disabled={busy || !canEdit || !dirty || !!conflict}>{busy ? '保存中…' : '保存此报价'}</button>
          <button type="button" className="pm-btn" disabled={busy} onClick={cancel}>取消</button></div>
      </form>}
      {history && <section className="pq-history" aria-label="报价修改历史"><h3>{history.title} · 修改历史</h3>
        <button type="button" className="pm-btn pm-btn-sm" onClick={() => { historySequence.current++; setHistory(null); }}>收起历史</button>
        {history.rows.map(r => <details key={r.version}><summary>版本 {r.version} · {r.actor.name || r.actor.account} · {new Date(r.createdAt).toLocaleString()}</summary>
          <div className="pq-history-diff"><div><b>修改前</b><pre>{describe(r.before)}</pre></div><div><b>修改后</b><pre>{describe(r.after)}</pre></div></div></details>)}
      </section>}
    </div>
  </section>;
}

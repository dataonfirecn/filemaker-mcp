import { useEffect, useState, type FormEvent } from 'react';
import './CustomerDirectoryPage.css';

type Customer = { id: string; code: string | null; name: string; company: string | null; country: string | null; owner: string | null; status: 'ready' | 'incomplete' | 'missing'; issues: string[]; updatedAt: string; version: number };
type Detail = Customer & { fields: Record<string, string | null>; lastSyncAt: string | null };
type Result = { rows: Customer[]; total: number; page: number; pageSize: number; lastSyncAt: string | null };
const statuses = { ready: '标识完整', incomplete: '待完善', missing: '来源缺失' };
const groups = [
  ['基本资料', ['客戶代號', '客戶公司簡稱', '公司', '客戶分類', '國家/地區', '地區', 'currency']],
  ['联系人与地址', ['聯絡人', '聯絡人郵件', '電話 1', '電話 2', '網站', '出貨地址', '辦公地址']],
  ['业务与备注', ['業務負責人', '業務負責人2', '業務負責人3', '業務負責人4', '客戶備註']]
] as const;
const labels: Record<string, string> = { 客戶代號: '客户代码', 客戶公司簡稱: '客户简称', 公司: '公司', 客戶分類: '客户分类', '國家/地區': '国家/地区', 地區: '地区', currency: '默认币种', 聯絡人: '联系人', 聯絡人郵件: '联系人邮箱', '電話 1': '电话 1', '電話 2': '电话 2', 網站: '网站', 出貨地址: '出货地址', 辦公地址: '办公地址', 業務負責人: '业务负责人', 業務負責人2: '业务负责人 2', 業務負責人3: '业务负责人 3', 業務負責人4: '业务负责人 4', 客戶備註: '客户备注' };
const show = (value: string | null | undefined) => value?.trim() ? value : '未填写';
const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无记录';
async function read<T>(url: string, token: string, signal: AbortSignal): Promise<T> {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` }, signal, cache: 'no-store' });
  if (!res.ok) throw new Error(res.status === 403 ? '仅管理员可查看客户资料。' : res.status === 401 ? '登录已失效，请重新登录。' : res.status === 404 ? '客户不存在。' : '客户资料读取失败，请重试。');
  return res.json();
}
export default function CustomerDirectoryPage({ apiBase, token }: { apiBase: string; token: string }) {
  const [query, setQuery] = useState(''); const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all'); const [page, setPage] = useState(1); const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<Result | null>(null); const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setDetail(null); setResult(null);
    const path = selected ? `/${encodeURIComponent(selected)}` : `?${new URLSearchParams({ q: search, status, page: String(page) })}`;
    read<Result | Detail>(`${apiBase}/api/admin/customers${path}`, token, controller.signal)
      .then(data => { if (!controller.signal.aborted) { if (selected) setDetail(data as Detail); else setResult(data as Result); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [apiBase, token, search, status, page, selected, retry]);
  function submit(event: FormEvent) { event.preventDefault(); setPage(1); setSearch(query.trim()); }
  return <section className="cd-page" aria-label="客户资料">
    <header className="cd-heading"><div><h2>{selected ? '客户详情' : '客户资料'}</h2><p>FileMaker 已导入资料 · 仅管理员查看 · 只读</p></div>{selected && <button type="button" onClick={() => setSelected(null)}>返回客户列表</button>}</header>
    {!selected && <form className="cd-search" onSubmit={submit}>
      <label>搜索客户<input value={query} maxLength={100} onChange={e => setQuery(e.target.value)} placeholder="代码、名称、公司、国家或负责人" /></label>
      <label>资料状态<select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="all">全部</option>{Object.entries(statuses).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>
      <button type="submit">搜索</button>
    </form>}
    {loading && <p role="status">正在读取客户资料…</p>}
    {error && <div className="cd-error" role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>重试</button></div>}
    {result && !selected && <>
      <div className="cd-meta"><span>共 {result.total} 条客户</span><span>最后同步：{date(result.lastSyncAt)}</span><span>标识完整：代码与简称齐全，代码无重复。</span></div>
      <div className="cd-table-scroll"><table><caption className="cd-sr-only">客户资料列表</caption><thead><tr>{['客户代码', '客户名称 / 公司', '国家/地区', '业务负责人', '资料状态', '操作'].map(t => <th scope="col" key={t}>{t}</th>)}</tr></thead><tbody>
        {result.rows.map(c => <tr key={c.id}><td>{show(c.code)}</td><td><strong>{c.name}</strong><small>{show(c.company)}</small></td><td>{show(c.country)}</td><td>{show(c.owner)}</td><td><span className={`cd-status ${c.status}`}>{statuses[c.status]}</span>{c.issues.length > 0 && <small>{c.issues.join('、')}</small>}</td><td><button onClick={() => setSelected(c.id)} aria-label={`查看客户 ${c.code || c.id}`}>查看</button></td></tr>)}
      </tbody></table></div>
      {!result.rows.length && <p className="cd-empty">没有符合条件的客户。</p>}
      <footer className="cd-pagination"><button disabled={page <= 1} onClick={() => setPage(n => n - 1)}>上一页</button><span>第 {page} / {Math.max(1, Math.ceil(result.total / result.pageSize))} 页</span><button disabled={page * result.pageSize >= result.total} onClick={() => setPage(n => n + 1)}>下一页</button></footer>
    </>}
    {detail && selected && <>
      <div className="cd-detail-title"><h3>{detail.name}</h3><span className={`cd-status ${detail.status}`}>{statuses[detail.status]}</span></div>
      {detail.issues.length > 0 && <p className="cd-warning">{detail.issues.join('；')}。此记录保留供核对，不能新增到报价客户群。</p>}
      <p className="cd-meta">来源 ID：{detail.id} · 资料版本：{detail.version} · 资料更新时间：{date(detail.updatedAt)} · 最后同步：{date(detail.lastSyncAt)}</p>
      {groups.map(([title, fields]) => <section className="cd-card" key={title}><h3>{title}</h3><dl>{fields.map(field => <div key={field}><dt>{labels[field]}</dt><dd>{show(detail.fields[field])}</dd></div>)}</dl></section>)}
    </>}
  </section>;
}

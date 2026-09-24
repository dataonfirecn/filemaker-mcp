import { useEffect, useRef, useState } from 'react';
import { Copy } from 'lucide-react';
import { Alert, Button, Modal } from './ui';
import { ProgressSteps } from './ui/ProgressSteps';
import './ProductSaveFeedback.css';

export type SaveFeedbackProps = {
  saving: boolean; saveError: string; saved: { id: string; version: number } | null;
  job?: { status: string; error?: string }; syncError: string; writeEnabled?: boolean;
  closeError: string; quoteDirty: boolean; onComplete: () => void; onDismiss: () => void;
};
export default function ProductSaveFeedback(props: SaveFeedbackProps) {
  const { saving, saveError, saved, job, syncError, writeEnabled, closeError, quoteDirty, onComplete, onDismiss } = props;
  const [slow, setSlow] = useState(false);
  const [copyState, setCopyState] = useState('');
  const errorText = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { const timer = window.setTimeout(() => setSlow(true), 30000); return () => clearTimeout(timer); }, []);
  const success = !!saved && job?.status === 'synced' && !syncError;
  const problem = saveError || syncError || (job?.status === 'conflict' ? 'FileMaker 记录存在版本冲突，请联系管理员核对。'
    : job?.status === 'superseded' ? '本次版本已被后续版本接替，请在同步状态中核对最新结果。'
    : job?.status === 'retry' ? '本次回写未成功，后台会自动重试。'
    : job?.error && !success ? '回写遇到错误，请联系管理员核对。'
    : writeEnabled === false && !success ? 'FileMaker 回写尚未开启，请联系管理员开启。' : '');
  const report = [problem, job?.error, saved && `产品 UUID：${saved.id}\nWeb 版本：${saved.version}`, `阶段：${saveError ? '保存资料' : '回写 FileMaker'}`, `状态：${job?.status ?? '尚未确认'}`].filter(Boolean).join('\n');
  useEffect(() => setCopyState(''), [report]);
  async function copyError() {
    try { await navigator.clipboard.writeText(report); setCopyState('已复制'); }
    catch {
      errorText.current?.focus(); errorText.current?.select();
      try { if (document.execCommand('copy')) { setCopyState('已复制'); return; } } catch { /* 保留选中的内容供手动复制 */ }
      setCopyState('无法自动复制，请复制下方已选中的内容。');
    }
  }
  const canReturn = !saving && (!!problem || slow);
  return <Modal title={success ? '产品资料已回写' : problem ? '保存需要处理' : '正在保存产品资料'}
    onClose={() => { if (success) onComplete(); else if (canReturn) onDismiss(); }}
    footer={<>
      {canReturn && <Button onClick={onDismiss}>返回编辑</Button>}
      {problem && <Button onClick={() => void copyError()}><Copy size={16} strokeWidth={1.75} />{copyState === '已复制' ? '已复制' : '复制错误'}</Button>}
      {success && <Button variant="primary" autoFocus onClick={onComplete}>完成</Button>}
    </>}>
    <div role="status" aria-live="polite"><p>{success ? '修改已写回 FileMaker，点击完成关闭窗口。' : saving ? '正在提交本次修改，请稍候。' : problem ? problem : '资料已保存，正在等待 FileMaker 确认。'}</p></div>
    <ProgressSteps steps={[
      { label: '保存资料', detail: saved ? '本次修改已保存在 Web' : saveError ? '未收到保存成功确认' : '正在提交本次修改', state: saved ? 'done' : saveError ? 'error' : 'active' },
      { label: '回写 FileMaker', detail: success ? 'FileMaker 已确认本次版本' : saved ? problem ? '回写尚未确认成功' : '后台正在处理，请稍候' : '等待资料保存', state: success ? 'done' : saved ? problem ? 'error' : 'active' : 'waiting' },
      { label: '确认完成', detail: success ? '可以安全关闭窗口' : '收到成功结果后显示完成按钮', state: success ? 'done' : 'waiting' },
    ]} />
    {problem && <label className="pm-save-error">错误详情<textarea ref={errorText} readOnly value={report} rows={5} translate="no" /></label>}
    {copyState && <p role="status">{copyState}</p>}
    {slow && !problem && !success && <p>处理时间较长。{saving ? '请保留此窗口，等待保存结果。' : '可以返回编辑，后台会继续回写；稍后可在同步状态中查看结果。'}</p>}
    {quoteDirty && <Alert>客户群报价尚未保存，完成并关闭窗口会放弃未保存的报价修改。</Alert>}
    {closeError && <Alert>{closeError}</Alert>}
  </Modal>;
}

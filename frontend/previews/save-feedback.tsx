import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import ProductSaveFeedback from '../src/components/ProductSaveFeedback';
import { Button } from '../src/components/ui';
import '../src/styles/tokens.css';
function Preview() {
  const q = new URLSearchParams(location.search);
  const [stage, setStage] = useState(q.get('state') || 'saving');
  const [open, setOpen] = useState(true);
  document.documentElement.dataset.theme = q.get('theme') || 'light';
  useEffect(() => {
    if (q.get('state')) return;
    const a = setTimeout(() => setStage('pending'), 2000);
    const b = setTimeout(() => setStage('synced'), 6500);
    return () => { clearTimeout(a); clearTimeout(b); };
  }, []);
  return <main style={{padding: 'var(--space-8)', fontFamily:'var(--font-sans)', color:'var(--color-text)', background:'var(--color-bg)', minHeight:'90vh'}}>
    <h1>保存反馈 · 交互预览</h1><p>模拟数据，不会修改 FileMaker。</p>
    <Button onClick={() => { setStage('pending'); setOpen(true); }}>等待回写</Button>{' '}
    <Button onClick={() => { setStage('synced'); setOpen(true); }}>回写成功</Button>{' '}
    <Button onClick={() => { setStage('retry'); setOpen(true); }}>回写错误</Button>
    <p><label>粘贴检查（可选）<input aria-label="粘贴检查" /></label></p>
    {open && <ProductSaveFeedback key={stage === 'saving' ? 'start' : 'saved'} saving={stage === 'saving'} saveError={stage === 'failed' ? '网络连接中断，未收到保存成功确认。' : ''}
      saved={stage === 'saving' || stage === 'failed' ? null : {id:'4747fe0e-08d0-4632-bc64-0dc353f5ecb7', version:7}}
      job={stage === 'saving' ? undefined : {status:stage, error:stage === 'retry' ? 'FileMakerError: 960 · Parameter invalid（模拟错误）' : undefined}}
      syncError="" closeError="" quoteDirty={false} onComplete={() => setOpen(false)} onDismiss={() => setOpen(false)} />}
  </main>;
}
createRoot(document.getElementById('root')!).render(<Preview />);

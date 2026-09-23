// Browser regression against deterministic API fixtures. Requires Playwright;
// set PLAYWRIGHT_MODULE to its package entry point when using a bundled runtime.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('..', import.meta.url)).replace(/\/$/, '');
const pid = '00000000-0000-4000-8000-000000000001';
const harness = `${root}/__quote_harness.tsx`;
const server = await createServer({ root, configFile: false, server: { host: '127.0.0.1', port: 5187, strictPort: true },
  esbuild: { jsx: 'automatic' }, plugins: [{ name: 'quote-test-harness',
    configureServer(s) { s.middlewares.use((req, res, next) => {
      if (req.url !== '/__quotes_test') return next();
      res.setHeader('Content-Type', 'text/html');
      res.end('<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="root"></div><script type="module" src="/__quote_harness.tsx"></script></body></html>');
    }); },
    resolveId(id) { if (id === '/__quote_harness.tsx') return harness; },
    load(id) { if (id === harness) return `import React from 'react'; import {createRoot} from 'react-dom/client';
      import Page from '/src/components/ProductMasterPage.tsx'; import '/src/styles.css';
      createRoot(document.getElementById('root')).render(<Page apiBase="" token="fixture" initialRef="${pid}" />);`; }
  }] });
await server.listen();
let browser;
try {
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') console.error('Console:', msg.text()); });
  page.on('response', response => { if (response.status() >= 400) console.error('HTTP:', response.status(), response.url()); });
  page.on('pageerror', e => { errors.push(e.message); console.error('Browser error:', e.message); });
  page.setDefaultTimeout(10000);
  let rows = [], revisions = [], writes = 0, forceConflict = false, writeEnabled = true, admin = true;
  const customers = [{ value: 'c1', name: '客户甲', code: '001' }, { value: 'c2', name: '客户乙', code: '002' },
    { value: 'c3', name: '公司全称', code: '003', label: '公司全称（待完善：简称缺失）', selectable: false }];
  const schema = [{ name: 'product_sku', result: 'text', writable: true, maxRepeat: 1 },
    { name: 'Client', result: 'text', writable: true, maxRepeat: 1 }, { name: 'id_client', result: 'text', writable: true, maxRepeat: 1 }];
  await page.route('**/api/product-master/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace('/api/product-master', '');
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    if (path === '/schema') return send({ fields: schema, permissions: { canManageAccounts: admin, canViewProducts: true, canViewPrice: true, canEditProductPrices: true, canEditProducts: true } });
    if (path === '/editor-controls') return send({ controls: {} });
    if (path === '/customers') return send({ rows: customers, total: customers.length });
    if (path === `/products/${pid}`) return send({ id: pid, version: 1, previewMode: true, fields: { product_sku: 'TEST-QUOTE' }, assets: [] });
    if (path === `/products/${pid}/status`) return send({ filemaker: [], dms: [] });
    if (path === `/products/${pid}/history`) return send({ rows: [] });
    if (path.endsWith('/quotes/q1/history')) return send({ rows: revisions });
    if (path.endsWith('/quotes') && request.method() === 'GET') return send({ rows, writeEnabled });
    if (['POST', 'PATCH'].includes(request.method()) && path.includes('/quotes')) {
      if (forceConflict) { forceConflict = false; return send({ detail: { message: '版本冲突', current: rows[0] } }, 409); }
      const body = request.postDataJSON(); assert.equal(typeof body.amount, 'string'); writes++;
      const before = rows[0] || null;
      const saved = { ...body, id: 'q1', productId: pid, version: (before?.version || 0) + 1,
        updatedAt: new Date().toISOString(), updatedBy: { name: '测试操作员' },
        customers: body.customerIds.map(id => { const c = customers.find(c => c.value === id); return { id, name: c.name, code: c.code }; }) };
      rows = [saved]; revisions.unshift({ version: saved.version, actor: saved.updatedBy, createdAt: saved.updatedAt, before, after: saved });
      return send(saved);
    }
    return send({ detail: `Unexpected fixture path ${path}` }, 404);
  });
  await page.goto('http://127.0.0.1:5187/__quotes_test');
  console.log('Harness loaded');
  try { await page.getByRole('button', { name: '客户群报价', exact: true }).click(); }
  catch (e) { console.error((await page.locator('body').innerText()).slice(0,2000)); throw e; }
  await page.getByRole('button', { name: '新增报价', exact: true }).click();
  await page.getByLabel('报价名称／权限标识', { exact: true }).fill('经销商组');
  await page.getByLabel('金额', { exact: true }).fill('0.123456789012');
  await page.getByRole('checkbox', { name: '客户甲' }).check();
  assert.equal(await page.getByRole('checkbox', { name: /公司全称（待完善/ }).isDisabled(), true);
  await page.getByRole('button', { name: '保存此报价' }).click();
  await page.getByText('USD 0.123456789012', { exact: true }).waitFor();
  assert.equal(writes, 1);
  await page.reload();
  await page.getByRole('button', { name: '客户群报价', exact: true }).click();
  await page.getByText('USD 0.123456789012', { exact: true }).waitFor();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('金额', { exact: true }).fill('22.50');
  await page.getByLabel('币种', { exact: true }).selectOption('CNY');
  await page.getByRole('checkbox', { name: '客户乙' }).check();
  await page.getByRole('button', { name: '移除客户 客户甲', exact: true }).click();
  await page.getByLabel('状态', { exact: true }).selectOption('disabled');
  await page.getByRole('button', { name: '保存此报价' }).click();
  await page.getByText('CNY 22.50', { exact: true }).waitFor();
  assert.equal(rows[0].enabled, false); assert.deepEqual(rows[0].customerIds, ['c2']);
  await page.getByRole('button', { name: '历史', exact: true }).click();
  await page.getByText(/版本 2 ·/).click();
  await page.getByText(/经销商组 · USD 0.123456789012/).first().waitFor();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByLabel('金额', { exact: true }).fill('99');
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: '基础资料', exact: true }).click();
  assert.equal(await page.getByLabel('金额', { exact: true }).inputValue(), '99');
  forceConflict = true;
  await page.getByRole('button', { name: '保存此报价' }).click();
  await page.getByText('这条报价已被其他人修改。你的输入仍保留；请核对最新版本。').waitFor();
  assert.equal(await page.getByLabel('金额', { exact: true }).inputValue(), '99');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: '载入最新版本（放弃当前输入）' }).click();
  assert.equal(await page.getByLabel('金额', { exact: true }).inputValue(), '22.50');
  await page.setViewportSize({ width: 768, height: 900 });
  await page.screenshot({ path: '/tmp/starrc-quotes-tablet.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  writeEnabled = false;
  await page.reload(); await page.getByRole('button', { name: '客户群报价', exact: true }).click();
  await page.getByText('CNY 22.50', { exact: true }).waitFor();
  assert(await page.getByRole('button', { name: '新增报价', exact: true }).isDisabled());
  assert(await page.getByRole('button', { name: '编辑', exact: true }).isDisabled());
  admin = false;
  await page.reload();
  await page.getByRole('button', { name: '基础资料', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '客户群报价', exact: true }).count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS quote create, exact decimals, reload, members, currency, disable, history, leave guard, conflict, tablet layout and read-only switch');
} finally { await browser?.close(); await server.close(); }

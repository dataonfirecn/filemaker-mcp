// Render every browser tab with editable permissions and preview mode enabled.
// This catches accidental draft inputs and upload controls in the read-only view.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/components/ProductMasterPage.tsx'), 'utf8');
const stateNames = [...source.matchAll(/const \[(\w+),[^\]]+\] = useState/g)].map(m => m[1]);
let stateIndex = 0;
let overrides = {};
function load(file) {
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText;
  const module = { exports: {} };
  const localRequire = name => name === 'react' ? { ...React, useState: initial => [overrides[stateNames[stateIndex++]] ?? initial, () => {}], useEffect: () => {}, useRef: current => ({ current }) }
    : name.endsWith('.css') ? {} : name.startsWith('.') ? load(['.ts', '.tsx', '/index.ts', '/index.tsx'].map(ext => path.resolve(path.dirname(file), name + ext)).find(candidate => fs.existsSync(candidate))) : require(name);
  vm.runInNewContext(js, { require: localRequire, module, exports: module.exports, crypto: globalThis.crypto, console });
  return module.exports;
}
const layout = load(path.join(root, 'src/components/productMasterLayout.ts'));
const Page = load(path.join(root, 'src/components/ProductMasterPage.tsx')).default;
const schema = JSON.parse(fs.readFileSync(path.join(root, '../backend/config/product_master_web_schema.json'))).fields.filter(f => layout.isEditorField(f.name));
const fields = Object.fromEntries(schema.filter(f => f.result !== 'container').map(f => [f.name, 'test-value']));
const assets = schema.filter(f => f.result === 'container').map((f, i) => ({ id: String(i), field: f.name, repetition: 1, filename: 'test.png', mimeType: 'image/png', size: 1024 }));
for (const previewMode of [true, false]) for (const tab of ['基础资料', ...layout.nativeTabs]) {
  stateIndex = 0;
  overrides = { schema, fields, assets, product: { id: 'test-product', version: 1, previewMode, fields, assets }, permissions: { canEditProducts: true, canManageProductSync: true }, tab,
    openFolds: Object.fromEntries(Object.entries(layout.foldedGroups).flatMap(([section, groups]) => groups.map((_, i) => [`${section}:${i}`, true]))) };
  const html = renderToStaticMarkup(React.createElement(Page, { apiBase: '', token: 'test', initialRef: 'test-product', readOnly: true }));
  assert(!/<(?:input|textarea|select)\b/.test(html), `${tab}: editable control found`);
  assert(!/>(?:保存|取消|上传|替换|移除|选择客户|更换|同 SKU|恢复为新版本)</.test(html), `${tab}: write action found`);
  assert(html.includes('只读浏览'));
  if (tab === '基础资料') assert(html.includes('test-value'));
  else assert(html.includes('预览'));
  console.log(`PASS ${tab}, previewMode=${previewMode}: no form inputs or write actions`);
}

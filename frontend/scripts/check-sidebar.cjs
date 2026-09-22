// Navigation state and accessibility regression checks; no browser/account data.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const React = require('react');
const storage = new Map();
let state = [], cursor = 0, effects = [], props, tree;
const hooks = { ...React,
  useState(initial) { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial; return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
  useEffect(fn, deps) { const i = cursor++; if (!state[i] || deps.some((value, n) => !Object.is(value, state[i][n]))) { state[i] = deps; effects.push(fn); } }
};
function load(file) {
  const module = { exports: {} };
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText;
  const localRequire = name => name === 'react' ? hooks : name.startsWith('.') ? load(path.resolve(path.dirname(file), name + '.tsx')) : require(name);
  vm.runInNewContext(js, { module, exports: module.exports, require: localRequire, localStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) } });
  return module.exports.default;
}
const Sidebar = load(path.resolve(__dirname, '../src/components/SidebarNav.tsx'));
const Shell = load(path.resolve(__dirname, '../src/components/AppShell.tsx'));
const item = (id, label, extra = {}) => ({ id, label, description: label, Icon: () => null, ...extra });
let visited = [];
props = { groups: [ { id: 'products', label: '产品资料', items: [item('businessProducts', '产品列表')] }, { id: 'orders', label: '订单管理', items: [item('orderDetail', '订单详情'), item('blocked', '无权限', { disabled: true }), item('preview', '预览', { onOpen: () => visited.push('preview') })] } ], activePage: 'businessProducts', collapsed: false, onNavigate: id => visited.push(id), onGoHome: () => visited.push('home') };
function render(Component = Sidebar, input = props) { cursor = 0; effects = []; tree = Component(input); effects.forEach(fn => fn()); return tree; }
function nodes(node = tree, result = []) { if (!node) return result; if (Array.isArray(node)) node.forEach(n => { if (n != null) nodes(n, result); }); else if (typeof node === 'object') { result.push(node); if (node.props?.children !== undefined) nodes(node.props.children, result); } return result; }
function find(predicate) { const n = nodes().find(predicate); assert(n, 'Control missing'); return n; }
const group = id => find(n => n.type === 'button' && n.props['aria-controls'] === `sidebar-group-${id}`);
const list = id => find(n => n.type === 'ul' && n.props.id === `sidebar-group-${id}`);
render(); render();
assert.equal(list('products').props.hidden, false); assert.equal(list('orders').props.hidden, true);
group('orders').props.onClick(); render(); assert.equal(group('orders').props['aria-expanded'], true);
state = []; render(); render(); assert.equal(list('orders').props.hidden, false);
group('orders').props.onClick(); render(); assert.equal(list('orders').props.hidden, true);
props = { ...props, activePage: 'orderDetail' }; render(); render(); assert.equal(list('orders').props.hidden, false);
console.log('PASS independent group folding, persisted preferences and revealing active group');
group('orders').props.onClick(); render(); props = { ...props, collapsed: true }; render(); assert.equal(list('orders').props.hidden, false);
props = { ...props, collapsed: false }; render(); assert.equal(list('orders').props.hidden, true);
for (const label of ['无权限', '预览', '订单详情']) find(n => n.type === 'button' && n.props['aria-label'] === label).props.onClick();
assert.deepEqual(visited, ['preview', 'orderDetail']);
assert(!nodes().some(n => n.props.className === 'sidebar-footer-toggle'));
console.log('PASS icon rail keeps entries reachable, restores group state and preserves permissions/preview callbacks');
let toggled = 0;
const shellProps = { title: '产品资料', subtitle: '', readOnly: true, user: null, theme: 'light', canManageAccounts: false, onThemeToggle() {}, onOpenSettings() {}, onSignOut() {}, onSidebarToggle: () => toggled++ };
render(Shell, shellProps);
const toggle = find(n => n.type === 'button' && n.props['aria-controls'] === 'main-navigation');
assert.equal(toggle.props['aria-expanded'], true); assert.equal(toggle.props['aria-label'], '收起导航'); toggle.props.onClick(); assert.equal(toggled, 1);
render(Shell, { ...shellProps, sidebarCollapsed: true }); assert.equal(find(n => n.type === 'button' && n.props['aria-controls'] === 'main-navigation').props['aria-label'], '展开导航');
render(Shell, { ...shellProps, onSidebarToggle: undefined }); assert(!nodes().some(n => n.props['aria-controls'] === 'main-navigation'));
console.log('PASS header toggle labels/state and standalone page exclusion');
storage.set('starrc-sidebar-groups:v1', 'invalid'); state = []; props = { ...props, activePage: 'businessProducts' }; render(); render(); assert.equal(list('products').props.hidden, false);
console.log('PASS corrupted storage falls back safely');

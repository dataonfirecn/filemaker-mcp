// Component-level interaction regression checks. AG Grid is represented by its
// public props/API; browser verification separately covers layout and real grid.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const React = require('react');
let states, index, effects, tree, props;
const storage = new Map();
const gridApi = { getColumnState: () => [], exportDataAsCsv: options => { gridApi.exported = options; }, getAllDisplayedColumns: () => [{getColId:()=> 'thumbnail'}, {getColId:()=> 'productSku'}] };
const hooks = { ...React,
 useState(initial) { const id=index++; if (!(id in states)) states[id]=typeof initial==='function'?initial():initial; return [states[id],value=>{states[id]=typeof value==='function'?value(states[id]):value;}]; },
 useRef(initial) {const id=index++; return states[id] ??= {current:initial};},
 useMemo(fn) {return fn();}, useCallback(fn) {return fn;},
 useEffect(fn,deps) {const id=index++; const old=states[id]; if(!old||deps.some((v,i)=>!Object.is(v,old[i]))) {states[id]=deps; effects.push(fn);} }
};
function load(file) {
 const module = {exports:{}};
 const js = ts.transpileModule(fs.readFileSync(file,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2020}}).outputText;
 const localRequire=name=>name==='react'?hooks:name==='ag-grid-react'?{AgGridReact:'test-grid'}:name.startsWith('.')?load(path.resolve(path.dirname(file),name+'.ts')):require(name);
 vm.runInNewContext(js,{module,exports:module.exports,require:localRequire,localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},window:{addEventListener(){},removeEventListener(){}},document:{addEventListener(){},removeEventListener(){}},console});
 return module.exports;
}
const Page=load(path.resolve(__dirname,'../src/components/BusinessProductsPage.tsx')).default;
const empty={model:'',category:'',audit:'',client:''};
function render() {index=0;effects=[];tree=Page(props);effects.forEach(fn=>fn());return tree;}
function all(node=tree,result=[]) {if(!node)return result;if(Array.isArray(node))node.forEach(n=>all(n,result));else if(typeof node==='object'){result.push(node);if(node.props?.children!==undefined)all(node.props.children,result);}return result;}
function text(node){if(node==null||typeof node==='boolean')return '';if(Array.isArray(node))return node.map(text).join('');if(typeof node==='object')return text(node.props?.children);return String(node);}
function find(predicate){const node=all().find(predicate);assert(node,'Expected control missing');return node;}
const button=label=>find(n=>n.type==='button'&&(text(n)===label||n.props['aria-label']===label));
const aria=label=>find(n=>n.props?.['aria-label']===label);
function click(label){button(label).props.onClick();render();}
const submit=className=>find(n=>n.type==='form'&&n.props.className===className).props.onSubmit({preventDefault(){}});
async function settle(){await new Promise(resolve=>setImmediate(resolve));render();}
function setup({count=20443,page=1,query='',filters=empty,success=true}={}) {
 states=[];let calls=[];
 props={apiBase:'',token:'test',query,filters,loading:false,pageSizeOptions:[50,100,200],data:{page,pageSize:100,totalPages:Math.max(1,Math.ceil(count/100)),foundCount:count,layout:'Web 产品库',rows:count?[{recordId:'r1',productSku:'SKU'}]:[]},onSearch:async(q,f)=>{calls.push([q,{...f}]);if(success){props={...props,query:q,filters:f};}return success;},onPageChange:p=>calls.push(p),onPageSizeChange:p=>calls.push(p),onOpenDetail:r=>calls.push(r)};
 render(); return calls;
}
(async()=>{
 let calls=setup();assert(!all().some(n=>n.props?.id==='product-filters'));assert(!text(tree).includes('产品记录'));
 const grid=find(n=>n.type==='test-grid');assert.equal(grid.props.defaultColDef.filter,false);assert(grid.props.columnDefs.every(c=>!c.filter));grid.props.ref.current={api:gridApi};
 click('筛选');const field=find(n=>n.type==='input'&&!n.props.id&&!n.props['aria-label']);field.props.onChange({target:{value:'ZX'}});render();click('筛选');click('下一页');assert.equal(calls[0],2);assert.equal(props.filters.model,'');click('筛选');assert.equal(find(n=>n.type==='input'&&!n.props.id&&!n.props['aria-label']).props.value,'ZX');
 submit('product-filter-panel');await settle();assert.equal(calls[1][1].model,'ZX');assert(!all().some(n=>n.props?.id==='product-filters'));assert(text(tree).includes('车款：ZX'));click('清除全部');await settle();assert.equal(props.filters.model,'');
 console.log('PASS collapsed filters, draft preserved across paging, apply, auto-close, clear');
 calls=setup({query:'old',success:false});click('筛选');aria('搜索产品').props.onChange({target:{value:'error'}});render();submit('product-filter-panel');await settle();assert.equal(aria('搜索产品').props.value,'error');assert(all().some(n=>n.props?.id==='product-filters'));assert.equal(props.query,'old');
 console.log('PASS failed search retains draft, applied conditions and expanded panel');
 calls=setup();aria('页码').props.onChange({target:{value:'999'}});render();submit('page-jump');assert.equal(calls.pop(),205);aria('页码').props.onChange({target:{value:'-5'}});render();submit('page-jump');assert.equal(calls.pop(),1);aria('页码').props.onChange({target:{value:''}});render();submit('page-jump');assert.equal(calls.length,0);
 setup({count:0});assert(aria('下一页').props.disabled);assert(aria('首页').props.disabled);assert(aria('页码').props.disabled);setup({count:1});assert(aria('下一页').props.disabled);setup({page:205});assert(aria('末页').props.disabled);
 console.log('PASS page jump clamping, blank input, empty/single/last page boundaries');
 setup();click('更多');assert(button('导出当前页 CSV'));click('表格设置');assert(!all().some(n=>n.props?.id==='product-more-actions'));find(n=>n.props?.id==='product-row-density').props.onChange({target:{value:'compact'}});render();assert.equal(find(n=>n.type==='test-grid').props.rowHeight,40);assert.equal(storage.get('business-products:density'),'compact');
 const exportGrid=find(n=>n.type==='test-grid');exportGrid.props.ref.current={api:gridApi};click('更多');click('导出当前页 CSV');assert.deepEqual(Array.from(gridApi.exported.columnKeys),['productSku']);
 console.log('PASS exclusive settings/more menus, density preference and current-page CSV columns');
})().catch(err=>{console.error(err);process.exitCode=1;});

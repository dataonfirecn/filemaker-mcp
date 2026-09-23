import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = fileURLToPath(new URL('..', import.meta.url)).replace(/\/$/, '');
const pid='00000000-0000-4000-8000-000000000001';
const registered=JSON.parse(readFileSync(`${root}/../backend/config/product_master_web_schema.json`));
const names=['ID','product_sku','系統產品編號','產品名稱_中文','MOQ','RMB成本','美金成本','EX-Price','台幣出廠','RMB出廠','Retail_Price_USD','組裝成本'];
const fields={ ID:pid, product_sku:'TEST-FINANCE', 系統產品編號:'TEST-FINANCE', 產品名稱_中文:'测试产品', MOQ:'12', RMB成本:'123.4567', 美金成本:'17.4321', 'EX-Price':'25.123456789012', 台幣出廠:'800', RMB出廠:'170', Retail_Price_USD:'40', 組裝成本:'3' };
let canViewPrice=true, costReads=0, costFailure=false;
const output=`${root}/../artifacts/product-finance-ui`;
mkdirSync(output,{recursive:true});
const server=await createServer({root,configFile:false,server:{host:'127.0.0.1',port:5188,strictPort:true},esbuild:{jsx:'automatic'},plugins:[{
 name:'finance-harness',configureServer(s){s.middlewares.use((req,res,next)=>{if(req.url!=='/__finance')return next();res.setHeader('Content-Type','text/html');res.end('<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="root"></div><script type="module" src="/__finance.tsx"></script></body></html>');});},
 resolveId(id){if(id==='/__finance.tsx')return root+'/__finance.tsx';},
 load(id){if(id===root+'/__finance.tsx')return `import React from 'react'; import {createRoot} from 'react-dom/client'; import Page from '/src/components/ProductMasterPage.tsx'; import '/src/styles.css'; import '/src/styles/tokens.css'; createRoot(document.getElementById('root')).render(<Page apiBase="" token="fixture" initialRef="${pid}" />);`;}
}]});
await server.listen();let browser;
try{
 browser=await chromium.launch({headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/product-master/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace('/api/product-master','');
  const send=data=>route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  const schema=registered.fields.filter(f=>names.includes(f.name)&&(canViewPrice||f.readPermission!=='canViewPrice'));
  if(path==='/schema')return send({fields:schema,permissions:{canViewProducts:true,canViewPrice,canEditProducts:false,canEditProductPrices:false}});
  if(path===`/products/${pid}/costs`) {
   costReads++;
   if(costFailure)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'实时成本读取失败，请重试'})});
   return send({fields:{RMB成本:costReads===1?'123.4567':'124.4567',美金成本:'17.4321'},issues:{},calculatedAt:new Date().toISOString()});
  }
  if(path==='/editor-controls')return send({controls:{}});
  if(path===`/products/${pid}`)return send({id:pid,version:1,previewMode:true,financeImported:true,fields:Object.fromEntries(schema.map(f=>[f.name,fields[f.name]])),assets:[]});
  return send({rows:[],filemaker:[],dms:[]});
 });
 for(const width of [1068,1440,390])for(const theme of ['light','dark']){
  costReads=0;
  await page.setViewportSize({width,height:1100});await page.goto('http://127.0.0.1:5188/__finance');
  await page.getByText('123.4567',{exact:true}).waitFor();await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
  assert.equal(await page.getByText('17.4321',{exact:true}).count(),1);
  assert.equal(await page.getByText('25.123456789012',{exact:true}).count(),1);
  assert.equal(await page.getByText('待接入',{exact:true}).count(),0);
  assert.equal(await page.getByLabel('EX-Price 1',{exact:true}).count(),0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),`overflow ${width} ${theme}`);
  await page.screenshot({path:`${output}/${width}-${theme}.png`,fullPage:true});
 }
 const beforeRefresh=costReads;
 await page.getByRole('button',{name:'刷新成本',exact:true}).click();
 await page.getByText('124.4567',{exact:true}).waitFor();assert.equal(costReads,beforeRefresh+1);
 assert.equal(await page.getByText('123.4567',{exact:true}).count(),0);
 costFailure=true;await page.getByRole('button',{name:'刷新成本',exact:true}).click();
 await page.getByRole('alert').waitFor();assert.equal(await page.getByText('124.4567',{exact:true}).count(),0);
 const beforeHidden=costReads;
 canViewPrice=false;await page.reload();await page.getByText('测试产品',{exact:true}).first().waitFor();
 assert.equal(await page.getByText('123.4567',{exact:true}).count(),0);
 assert.equal(await page.getByText('RMB成本',{exact:true}).count(),0);
 assert.equal(costReads,beforeHidden);
 assert.equal(await page.getByRole('button',{name:'刷新成本',exact:true}).count(),0);
 assert.equal(errors.length,0,errors.join('\n'));console.log('PASS finance fields, permission filtering, 3 widths × 2 themes');
}finally{await browser?.close();await server.close();}

// Real shared day component, synthetic amounts; no API, browser profile or data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom'));
const ts=require(path.join(deps,'typescript')),m={exports:{}};
new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/ActionDayCell.tsx'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)(n=>require(path.join(deps,n)),m,m.exports);
const {ActionDayContent}=m.exports,day='2026-11-15',box=document.body.appendChild(document.createElement('div')),root=createRoot(box);
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const group=()=>walk(box).find(n=>props(n).className==='action-ad-group');
const numbers=()=>walk(group()).filter(n=>n.tagName==='STRONG');
const row={mp:'wb',orders:{[day]:5},actions:{},ad_metrics:{[day]:{all:{campaigns:1,spent:1298.1,budget:0,daily_limit:5000,
 usage_limit:.26,usage_balance:.4,bids:{cpm:100,cpc:5},partial:[],observed_at:[],classification_estimated:true}}}};
const before=JSON.stringify(row),metric=row.ad_metrics[day].all;
function render(basis='limit'){flushSync(()=>root.render(React.createElement(ActionDayContent,{row,day,kinds:{},drr:[],deepAds:false,
 dayPrices:false,adStats:true,adGroups:['all'],adBasis:basis})));}
try{
 render();
 assert.deepEqual(numbers().map(n=>n.textContent),['—','1 298,1','5 000','26%','100','5']);
 assert.ok(group().textContent.includes('— / 1 298,1 / 5 000 / 26% / 100 / 5'));
 assert.ok(!group().textContent.includes('Потрачено'),'names are in tooltips, not repeated in every day');
 assert.ok(!group().textContent.includes('Группировка по последним настройкам'));assert.ok(group().textContent.includes('≈'));
 assert.equal(props(numbers()[0]).title,'Остаток бюджета РК: 0 ₽');
 assert.equal(props(numbers()[1])['aria-label'],'Потрачено · товар: 1 298,1 ₽');
 assert.equal(JSON.stringify(row),before,'formatting does not change original amounts');
 render('balance');assert.equal(numbers()[3].textContent,'40%');
 metric.budget=null;metric.spent=0;metric.daily_limit=undefined;metric.usage_limit=0;metric.bids={cpm:0,cpc:null};
 render();assert.deepEqual(numbers().map(n=>n.textContent),Array(6).fill('—'));
 assert.equal(props(numbers()[0]).title,'Остаток бюджета РК: нет данных');
 assert.equal(props(numbers()[1]).title,'Потрачено · товар: 0 ₽');
 metric.spent=0.04;metric.partial=['spent'];metric.bids.cpc=12345678.9;
 render();assert.equal(numbers()[1].textContent,'0,04*','small nonzero amounts are not hidden as zero');
 assert.equal(numbers()[5].textContent,'12 345 678,9');
 assert.ok(props(numbers()[1]).title.includes('Неполные данные'));
 console.log('Compact ad values: six stable positions, visible spend, both percent bases, zero vs missing, small values and partial/source markers OK');
}finally{flushSync(()=>root.unmount());}

// Real React and shared action cells; synthetic responses only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map([['entry_view','detail'],['entry_chart','0']]);
global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const days=['2026-11-12','2026-11-11','2026-11-10'],requests=[];
const periods=days.map(d=>({id:d,d_from:d,d_to:d,n_days:1}));
const metrics={views:100,clicks:20,carts:4,orders:3,ctr:.2,conv_cart:.2,conv_order:.75};
const detail={reports:[],periods,points:[{point:'Search',section:'Search',cells:Object.fromEntries(days.map(d=>[d,metrics]))}],articles:[],can_edit:false};
const metric={campaigns:1,spent:20,campaign_spent:100,budget:900,daily_limit:1000,usage_limit:.1,usage_balance:.1,bids:{cpm:100,cpc:null},partial:[],observed_at:[]};
function payload(nm){
 return{days,kinds:[{key:'ads_on',title:'Запуск рекламы',color:'#000'}],demand_note:'Заказы из воронки',rows:[{
  nm_id:nm,mp:'wb',orders_source:'wb_funnel',orders:{[days[0]]:5,[days[1]]:0},price_spp_days:{[days[0]]:100},
  actions:{[days[0]]:[{id:1,kind:'ads_on',value:'TEST-'+nm,created_at:'2026-11-12T12:34:00Z'},
    {id:2,kind:'auto:ad_kw_bid',value:'DEEP-KEY',auto:true,detected_at:'2026-11-12T10:00:00Z'}]},
  ads:{[days[0]]:{all:20,ark:0,prk:20,search:20,rec:0,osum:1000}},
  ad_metrics:{[days[0]]:{all:metric,cpm:metric}}
 }]};
}
let defer=null,fail=false,legacy=null;
function historical(nm){
 const p=payload(nm),total={...metric,spent:1298.1,budget:null,daily_limit:null,usage_limit:null,usage_balance:null,bids:{cpm:null,cpc:null},classification_estimated:legacy==='cpc'};
 const part=v=>({spent:v,campaigns:1,partial:true,classification_estimated:legacy==='cpc'});
 const model=legacy==='cpc'?'cpc':'unknown';
 p.rows[0].ad_metrics[days[0]]={all:total,[model]:total,
   search:{...total,spent:1143,payment_spend:{[model]:part(1143)}},
   rest:{...total,spent:155.1,payment_spend:{[model]:part(155.1)}}};
 return p;
}
const http={get:async url=>{
 requests.push(url);
 if(url.includes('/entry_points?')){
  if(url.includes('mode=weeks'))return{...detail,periods:[{id:'week',d_from:'2026-11-06',d_to:'2026-11-12',n_days:7}]};
  return detail;
 }
 if(url.includes('/manager/day-cells?')){
  const nm=+new URLSearchParams(url.split('?')[1]).get('nm_id');
  if(defer){const f=defer;defer=null;return new Promise((resolve,reject)=>f(resolve,reject));}
  if(fail){fail=false;throw Error('test failure');}
  return legacy?historical(nm):payload(nm);
 }
 throw Error(url);
}};
const modules=new Map();function load(file){
 if(modules.has(file))return modules.get(file).exports;
 const mod={exports:{}};modules.set(file,mod);const p=path.join(base,'web/frontend/src',file);
 const code=ts.transpileModule(fs.readFileSync(p+(fs.existsSync(p+'.tsx')?'.tsx':'.ts'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(n=>{
  if(n==='react')return React;if(n==='react/jsx-runtime')return require(path.join(deps,n));
  if(n==='./api')return{http};if(n==='echarts-for-react')return{__esModule:true,default:()=>null};
  if(n.startsWith('./'))return load(n.slice(2));throw Error(n);
 },mod,mod.exports);return mod.exports;
}
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const old=console.error;console.error=(...a)=>{warnings.push(a.join(' '));old(...a)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],nodes=()=>walk(box),props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const tick=()=>new Promise(r=>setTimeout(r,30)),settle=async()=>{await tick();await tick()};
const render=async(nm='100',shop=7,hideChg=false)=>{flushSync(()=>root.render(h(load('EntryPoints').EntryPoints,{shop,nm,hideChg})));await settle()};
const button=t=>nodes().find(n=>n.tagName==='BUTTON'&&(n.textContent===t||props(n)['aria-label']===t));
const click=async(n)=>{assert.ok(n,'button present');assert.ok(!props(n).disabled,'enabled');flushSync(()=>props(n).onClick({currentTarget:n}));await settle()};
const adRequests=()=>requests.filter(u=>u.includes('/manager/day-cells?'));
const actionRow=()=>nodes().find(n=>props(n).className==='entry-actions-row');
const dialog=()=>nodes().find(n=>props(n).role==='dialog');
(async()=>{
 await render('');
 assert.ok(props(button('Показать действия')).disabled);assert.equal(adRequests().length,0);
 await render('100,101');assert.ok(props(button('Показать действия')).disabled);assert.equal(adRequests().length,0);
 await render();
 assert.equal(adRequests().length,0,'opt-in only');
 assert.ok(nodes().indexOf(button('Показать график'))<nodes().indexOf(button('Показать действия')));
 await click(button('Показать действия'));
 assert.equal(adRequests().length,1,'one batch for every column');
 const q=new URLSearchParams(adRequests()[0].split('?')[1]);
 assert.equal(q.get('nm_id'),'100');assert.equal(q.get('date_from'),'2026-11-10');assert.equal(q.get('date_to'),'2026-11-12');
 const row=actionRow();assert.ok(row);assert.deepEqual(row.childNodes.slice(2).map(n=>props(n).colSpan),[2,2,1]);
 assert.ok(button('Действия за 2026-11-12').textContent.includes('ДРР 2 %'));
 assert.ok(button('Действия за 2026-11-11').textContent.includes('Заказы: 0'));
 assert.ok(button('Действия за 2026-11-10').textContent.includes('Заказы: —'));
 await click(button('Действия за 2026-11-12'));assert.ok(dialog());
 assert.ok(dialog().textContent.includes('15:34 МСК'));assert.ok(!dialog().textContent.includes('DEEP-KEY'));
 assert.ok(dialog().textContent.includes('Цена с СПП: 100 ₽'));assert.ok(dialog().textContent.includes('CPM'));
 assert.ok(dialog().textContent.includes('ДРР 2%'));assert.ok(nodes().some(n=>props(n).title==='Остаток бюджета РК: 900 ₽'));
 assert.equal(document.activeElement,button('Закрыть действия'));
 const {ActionDayContent,DRR,AD_GROUPS}=load('ActionDayCell');
 const cellBox=document.body.appendChild(document.createElement('div')),cellRoot=createRoot(cellBox);
 flushSync(()=>cellRoot.render(h(ActionDayContent,{row:payload(100).rows[0],day:days[0],
  kinds:{ads_on:payload(100).kinds[0]},drr:DRR.map(([k])=>k),deepAds:false,dayPrices:true,adStats:true,adGroups:AD_GROUPS.map(([k])=>k),adBasis:'limit'})));
 assert.ok(dialog().textContent.includes(cellBox.textContent),'exact same daily content as board');
 flushSync(()=>cellRoot.unmount());
 await click(button('Показать глубокие изменения РК'));assert.ok(dialog().textContent.includes('DEEP-KEY'));assert.ok(dialog().textContent.includes('13:00 МСК'));
 await click(button('Закрыть действия'));assert.equal(dialog(),undefined);
 assert.equal(document.activeElement,button('Действия за 2026-11-12'));
 await click(button('Показы'));assert.deepEqual(actionRow().childNodes.slice(2).map(n=>props(n).colSpan),[4,4,2]);
 await render('100',7,true);assert.deepEqual(actionRow().childNodes.slice(2).map(n=>props(n).colSpan),[2,2,2]);
 const before=adRequests().length;
 await click(button('Неделя к неделе'));assert.equal(actionRow(),undefined);assert.ok(box.textContent.includes('Действия доступны по дням'));assert.equal(adRequests().length,before);
 await click(button('По дням (30)'));assert.ok(actionRow());
 await click(button('Действия за 2026-11-10'));assert.ok(dialog().textContent.includes('Нет сохранённых действий'));assert.ok(!dialog().textContent.includes('TEST-100'));
 await click(button('Закрыть действия'));
 // A late success from a previous SKU must not overwrite the next SKU.
 let resolveOld;defer=r=>{resolveOld=r};
 await render('101');assert.ok(button('Действия за 2026-11-12').textContent.includes('Загрузка'));
 await render('102');resolveOld(payload(101));await settle();
 await click(button('Действия за 2026-11-12'));assert.ok(dialog().textContent.includes('TEST-102'));assert.ok(!dialog().textContent.includes('TEST-101'));
 // A late error from a different shop must not replace current data.
 let rejectOld;defer=(r,j)=>{rejectOld=j};
 await render('102',8);assert.equal(dialog(),undefined);
 await render('102',7);rejectOld(Error('OLD-SHOP'));await settle();assert.ok(!box.textContent.includes('OLD-SHOP'));
 // Own error/retry never removes the entry table.
 fail=true;await render('103');assert.ok(box.textContent.includes('test failure'));assert.ok(box.textContent.includes('Search'));
 await click(button('Повторить загрузку действий'));await click(button('Действия за 2026-11-12'));assert.ok(dialog().textContent.includes('TEST-103'));
 await click(button('Закрыть действия'));await click(button('Скрыть действия'));assert.equal(actionRow(),undefined);
 const last=adRequests().length;await render('104');assert.equal(adRequests().length,last);
 await click(button('Показать действия'));await render('104,105');assert.equal(actionRow(),undefined);assert.equal(dialog(),undefined);
 legacy='cpc';await render('106');
 await click(button('Действия за 2026-11-12'));
 const group=title=>walk(dialog()).find(n=>props(n).className==='action-ad-group'&&n.childNodes.some(b=>b.tagName==='B'&&b.textContent===title));
 assert.ok(group('CPC').textContent.includes('— / 1 298,1 / — / — / — / —'),'old CPC spend remains visible');
 assert.ok(walk(group('CPC')).some(n=>props(n).title?.includes('Группировка по последним настройкам')));
 assert.ok(group('Поиск').textContent.includes('CPM / CPC— / 1 143*'));
 assert.ok(group('Вне поиска · оценка').textContent.includes('CPM / CPC— / 155,1*'));
 assert.ok(dialog().textContent.includes('CPM/CPC — способ оплаты'));
 await click(button('Закрыть действия'));
 legacy='unknown';await render('107');await click(button('Действия за 2026-11-12'));
 assert.ok(group('Тип оплаты неизвестен').textContent.includes('1 298,1'));
 assert.ok(walk(group('Вся реклама')).some(n=>props(n).title?.includes('Не распределено по CPM/CPC')));
 flushSync(()=>root.unmount());await settle();assert.deepEqual(warnings,[]);
 console.log('entry actions: opt-in, guards, date columns, shared content, times, missing data, deep toggle, selection races and retry OK');
})().catch(e=>{console.error(e);process.exitCode=1});

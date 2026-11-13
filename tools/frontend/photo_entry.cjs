// Real React components with synthetic read-only API responses; no live shops.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')), {createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map([['entry_view','detail'],['entry_split',JSON.stringify({ad:true,org:true})]]);
global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const m={views:100,clicks:20,carts:4,orders:2,ctr:.2,conv_cart:.2,conv_order:.5,ad_views:30,org_views:70};
const day='2026-11-10',per={from:day,to:day,days:1,ctr:.2,conv_cart:.2,conv_order:.5,orders_day:2};
const pair={from:day+'T00:00:00Z',to:day+'T12:00:00Z',before_spp:1234.56,after_spp:987.65,coverage:.75};
const full={nm_id:77,own:true,current:[],current_period:{...per,prices:pair},taken_at:null,
 events:[{day,summary:'Смена фото',before:[],after:[],period:{...per,prices:null},period_before:{...per,prices:{...pair,before_spp:800,after_spp:600,coverage:1}}}]};
const detail={reports:[],periods:[{id:'one',d_from:day,d_to:day},{id:'two',d_from:'2026-11-09',d_to:'2026-11-09'}],points:[{section:'Поиск',point:'Запрос',cells:{one:m}}],
 total:{one:m},articles:[],can_edit:false,ads:{one:{total:m,search:m,rest:m,organic:m}}};
const sources={periods:[{key:day,d_from:day,d_to:day,n_days:1}],sources:[{...m,section:'Поиск',points:[{...m,point:'Запрос'}]}],
 sources_total:m,sources_days:[{section:'Поиск',all:m,days:{[day]:m}}],days:[day],d_from:day,d_to:day,n_days:1};
const http={get:async url=>{
 if(url.endsWith('/photo_funnel'))return [{nm_id:77,vendor_code:'DEMO',kind:'own',changes:1,has_snap:true}];
 if(url.endsWith('/photo_funnel/77'))return full;
 if(url.includes('/entry_points?'))return detail;
 if(url.includes('/entry_views?'))return sources;
 throw Error(url);
}};
const modules=new Map();
function load(file){if(modules.has(file))return modules.get(file).exports;
 const mod={exports:{}};modules.set(file,mod);
 const source=path.join(base,'web/frontend/src',file);
 const code=ts.transpileModule(fs.readFileSync(source+(fs.existsSync(source+'.tsx')?'.tsx':'.ts'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(name=>{
  if(name==='react')return React;if(name==='react/jsx-runtime')return require(path.join(deps,name));
  if(name==='./api')return {http};if(name==='echarts-for-react')return {__esModule:true,default:()=>h('div',{'data-test-chart':'true'})};
  if(name==='./EntryViews'||name==='./entryGrowth')return load(name.slice(2));throw Error(name);
 },mod,mod.exports);return mod.exports;
}
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const oldError=console.error;console.error=(...args)=>{warnings.push(args.join(' '));oldError(...args)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const nodes=()=>walk(box),find=s=>nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===s);
const settle=()=>new Promise(r=>setTimeout(r,30));
async function render(component,p){flushSync(()=>root.render(h(component,p)));await settle();await settle()}
async function click(n){assert.ok(n);flushSync(()=>props(n).onClick());await settle();await settle()}
const tables=()=>nodes().filter(n=>n.tagName==='TABLE'),pinned=()=>nodes().filter(n=>props(n).className==='entry-point-cell');
(async()=>{try{
 const {PhotoFunnel}=load('PhotoFunnel'),{EntryPoints}=load('EntryPoints');
 await render(PhotoFunnel,{shop:7});
 const kpis=nodes().filter(n=>props(n).className==='pf-kpi');assert.equal(kpis.length,3);
 assert.ok(kpis[0].textContent.includes('1 234,56 ₽'));assert.ok(kpis[0].textContent.includes('987,65 ₽'));
 assert.ok(kpis[0].textContent.includes('75,0 %'));assert.ok(kpis[1].textContent.includes('800 ₽'));
 assert.ok(kpis[2].textContent.includes('Нет истории цен'));assert.ok(!kpis[2].textContent.includes('0 ₽'));
 assert.ok(nodes().filter(n=>n.tagName==='DETAILS'&&props(n).className==='hint pf-price-note').every(n=>!props(n).open),'price explanations collapsed by default');
 await render(EntryPoints,{shop:7,nm:''});
 assert.ok(nodes().some(n=>props(n)['data-test-chart']));
 await click(find('Скрыть график'));assert.ok(!nodes().some(n=>props(n)['data-test-chart']));assert.equal(store.get('entry_chart'),'0');
 await click(find('Показать график'));assert.ok(nodes().some(n=>props(n)['data-test-chart']));
 assert.ok(pinned().filter(n=>n.tagName==='TD').every(n=>!props(n).colSpan),'totals and ad subtotals use the same single label column');
 assert.ok(!props(tables()[0]).className.includes('entry-pin'));
 await click(find('📌 Закрепить точки входа'));
 assert.equal(store.get('entry_pin_points'),'1');assert.ok(props(tables()[0]).className.includes('entry-pin'));
 assert.ok(pinned().some(n=>n.textContent==='Точка входа'));assert.ok(pinned().some(n=>n.textContent==='Запрос'));
 assert.ok(pinned().some(n=>n.textContent.includes('Итого')));assert.ok(pinned().some(n=>n.textContent.includes('органика')));
 assert.ok(!pinned().some(n=>n.textContent==='Поиск'),'detail section is not the pinned point');
 await click(find('Источники трафика'));
 assert.ok(props(tables()[0]).className.includes('entry-pin'));
 assert.ok(pinned().some(n=>n.textContent.includes('органика')));
 await click(nodes().find(n=>n.tagName==='TR'&&props(n).onClick));
 assert.ok(pinned().some(n=>n.textContent==='Запрос'));
 await click(find('Источники трафика по дням'));
 assert.ok(pinned().some(n=>props(n).rowSpan>1));
 assert.ok(pinned().every(n=>['Источник трафика','Поиск'].includes(n.textContent)),'rowspan leaves numeric subrows unpinned');
 flushSync(()=>root.render(null));await render(EntryPoints,{shop:7,nm:''});
 assert.ok(props(tables()[0]).className.includes('entry-pin'),'pin survives remount');
 await click(find('📌 Открепить точки входа'));assert.equal(store.get('entry_pin_points'),'0');
 assert.ok(!props(tables()[0]).className.includes('entry-pin'));
 await render(EntryPoints,{shop:7,nm:'',enablePin:false});assert.ok(!find('📌 Закрепить точки входа'));
 assert.deepEqual(warnings,[]);console.log('Photo prices and entry pin: rendering, coverage, missing values, all source views, summary/subrows and persistence OK');
}finally{flushSync(()=>root.unmount());console.error=oldError}})().catch(e=>{console.error(e);process.exitCode=1});

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
const entry={from:'2026-11-08',to:day,expected_days:3,covered_days:2,report_days:3,missing_days:['2026-11-09'],coverage:2/3,status:'partial',
 ctr:.25,conv_cart:.3,conv_order:.4,conv_view_order:.00125,views:400,clicks:100,carts:30,orders:12};
const recent={...per,from:'2026-11-09',to:'2026-11-09',prices:{...pair,before_spp:800,after_spp:600,coverage:1},entry:{...entry,status:'complete',covered_days:3,coverage:1,missing_days:[]}};
const oldest={...per,from:'2026-11-08',to:'2026-11-08',prices:null,entry:{...entry,status:'empty',covered_days:0,ctr:null,conv_cart:null,conv_order:null}};
const effect={before:{views:100,conv_cart:.2,conv_order:.5,orders_day:2,covered_days:7,conversion_days:7},
 after:{views:120,conv_cart:.3,conv_order:.6,orders_day:3,covered_days:7,conversion_days:7}};
const full={nm_id:77,own:true,current:['current-photo'],current_period:{...per,prices:pair,entry},taken_at:null,
 events:[{day,summary:'Смена фото',before:['recent-photo'],after:['current-photo'],period:{...per,prices:pair,entry},period_before:recent,effect},
 {day:'2026-11-09',summary:'Предыдущая смена',before:['oldest-photo'],after:['recent-photo'],period:recent,period_before:oldest,effect}]};
const detail={reports:[],periods:[{id:'one',d_from:day,d_to:day},{id:'two',d_from:'2026-11-09',d_to:'2026-11-09'}],points:[{section:'Поиск',point:'Запрос',cells:{one:m}}],
 total:{one:m},articles:[],can_edit:false,ads:{one:{total:m,search:m,rest:m,organic:m}}};
const sources={periods:[{key:day,d_from:day,d_to:day,n_days:1}],sources:[{...m,section:'Поиск',points:[{...m,point:'Запрос'}]}],
 sources_total:m,sources_days:[{section:'Поиск',all:m,days:{[day]:m}}],days:[day],d_from:day,d_to:day,n_days:1};
let holdPhotos=false;const photoRequests=[];
const http={get:async url=>{
 if(holdPhotos&&url.includes('/photo_funnel'))return new Promise(resolve=>photoRequests.push({url,resolve}));
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
  if(name==='./EntryActions')return {useEntryActions:()=>({enabled:false,controls:null,dialog:null})};if(name==='./api')return {http};if(name==='echarts-for-react')return {__esModule:true,default:()=>h('div',{'data-test-chart':'true'})};
  if(['./EntryViews','./entryGrowth','./entryCompleteness'].includes(name))return load(name.slice(2));throw Error(name);
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
 const entries=()=>nodes().filter(n=>props(n)['aria-label']==='Показатели из точек входа');
 assert.equal(entries().length,3);assert.ok(entries()[0].textContent.includes('Показ → заказ0,13 %'));assert.ok(entries()[0].textContent.includes('25 %'));
 const photoLinks=()=>nodes().filter(n=>n.tagName==='A'&&String(props(n).href).startsWith('/api/photo/')).map(n=>props(n).href);
 assert.deepEqual(photoLinks(),['/api/photo/current-photo','/api/photo/recent-photo','/api/photo/oldest-photo'],'each period shown once, newest first');
 assert.ok(kpis[0].textContent.startsWith('10.11–10.11'));assert.ok(kpis[1].textContent.startsWith('09.11–09.11'));assert.ok(kpis[2].textContent.startsWith('08.11–08.11'));
 assert.equal(nodes().filter(n=>n.tagName==='B'&&n.textContent==='Было').length,2);
 const comparisons=nodes().filter(n=>n.tagName==='DETAILS'&&props(n).className==='pf-eff');
 assert.equal(comparisons.length,2);assert.ok(comparisons.every(n=>!props(n).open),'seven-day effects remain available but collapsed');
 assert.ok(comparisons[0].textContent.includes('100 → 120'));
 for(const kpi of kpis){
  const columns=walk(kpi).find(n=>props(n).className==='pf-kpi-sources');
  const sections=columns.childNodes.filter(n=>n.tagName==='SECTION');
  assert.equal(sections.length,2);
  assert.equal(props(sections[0])['aria-label'],'Показатели рекламы и воронки WB');
  assert.equal(props(sections[1])['aria-label'],'Показатели из точек входа','entry is the right sibling for each period');
 }
 assert.ok(entries()[0].textContent.includes('30 %'));assert.ok(entries()[0].textContent.includes('40 %'));
 assert.ok(kpis[0].textContent.includes('CTR рекламы20,00 %'),'old advertising CTR retained independently');
 assert.ok(entries()[0].textContent.includes('2 из 3'));assert.ok(entries()[0].textContent.includes('не полностью'));
 assert.ok(entries()[0].textContent.includes('09.11.2026'));assert.ok(entries()[0].textContent.includes('Показы: 400'));
 assert.ok(entries()[2].textContent.includes('Нет дневных данных'));assert.ok(!entries()[2].textContent.includes('CTR0 %'));
 for(const [status,message] of [['intraday','нельзя разделить'],['pending','нет завершённых дней']]){
  full.current_period.entry={...entry,status,expected_days:0,covered_days:0,to:null,ctr:null,conv_cart:null,conv_order:null};
  flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});assert.ok(entries()[0].textContent.includes(message));
 }
 full.current_period={...full.current_period,orders_day:null,conv_cart:null,conv_order:null,covered_days:2,expected_days:3,conversion_days:1};
 flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});
 const partial=nodes().find(n=>props(n).className==='pf-kpi').textContent;
 assert.ok(partial.includes('заказы 2/3'));assert.ok(!partial.includes('Заказов в день0'));
 assert.ok(!partial.includes('Конв. в заказ0 %'));
 delete full.current_period.entry;for(const e of full.events){delete e.period.entry;delete e.period_before.entry;}
 flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});assert.equal(entries().length,0,'legacy demo payload stays compatible');
 assert.ok(nodes().filter(n=>n.tagName==='DETAILS'&&props(n).className==='hint pf-price-note').every(n=>!props(n).open),'price explanations collapsed by default');
 // Same photos can return in a different period; do not deduplicate by hash or date.
 const history=[...full.events],current=[...full.current];
 full.current=['oldest-photo'];full.events[1].day=day;
 flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});
 assert.deepEqual(photoLinks(),['/api/photo/oldest-photo','/api/photo/recent-photo','/api/photo/oldest-photo']);
 assert.equal(nodes().filter(n=>props(n).className==='pf-ev').length,2,'two changes in one day remain separate');
 full.events=[];flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});
 assert.equal(photoLinks().length,1);assert.ok(box.textContent.includes('История начинается с первого успешного слепка'));
 full.events=[{...history[0],before:null,period_before:null}];
 flushSync(()=>root.render(null));await render(PhotoFunnel,{shop:7});
 assert.equal(photoLinks().length,1,'missing historical snapshot must not reuse the after photos');
 assert.ok(box.textContent.includes('слепка ещё нет'));
 full.events=history;full.current=current;
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
 // Switching shop/article cannot display delayed photo KPIs from old requests.
 holdPhotos=true;await render(PhotoFunnel,{shop:7});const oldList=photoRequests.at(-1);
 await render(PhotoFunnel,{shop:8});const newList=photoRequests.at(-1);
 newList.resolve([{nm_id:77,vendor_code:'NEW-77',kind:'own'},{nm_id:88,vendor_code:'NEW-88',kind:'own'}]);await settle();await settle();
 const oldItem=photoRequests.at(-1);assert.ok(oldItem.url.endsWith('/77'));
 oldList.resolve([{nm_id:99,vendor_code:'OLD',kind:'own'}]);await settle();assert.ok(!box.textContent.includes('OLD'));
 await click(nodes().find(n=>n.tagName==='BUTTON'&&n.textContent.includes('NEW-88')));
 photoRequests.at(-1).resolve({...full,nm_id:88});await settle();await settle();
 const heading=()=>nodes().find(n=>props(n).className==='board-bar');assert.ok(heading().textContent.startsWith('88'));
 oldItem.resolve({...full,nm_id:77});await settle();assert.ok(heading().textContent.startsWith('88'));
 assert.deepEqual(warnings,[]);console.log('Photo prices and entry pin: rendering, coverage, missing values, all source views, summary/subrows and persistence OK');
}finally{flushSync(()=>root.unmount());console.error=oldError}})().catch(e=>{console.error(e);process.exitCode=1});

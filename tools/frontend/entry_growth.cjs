// Relative growth/decline boundaries and real React entry tables, synthetic data only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map([['entry_view','detail'],['entry_split',JSON.stringify({ad:true,org:true})]]);
global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const days=['2026-11-12','2026-11-11'];
const old={views:100,clicks:100,orders:10,carts:20,ctr:.01,conv_cart:.2,conv_order:.5,cr_cart:.2,cr_order:.5,ad_views:100,org_views:100,ad_orders:10,org_orders:2,ad_ctr:.01,org_ctr:1,ad_cr_cart:.25,org_cr_cart:.2,ad_cr_order:.4,org_cr_order:.5,ad_cro:.1,org_cro:.1};
const current={...old,views:400,clicks:800,orders:6,ctr:.04,cr_cart:.14,cr_order:.1,ad_views:400,org_views:400,ad_orders:6,org_orders:0,ad_ctr:0,org_ctr:0,ad_cr_cart:.5,org_cr_cart:.1,ad_cr_order:.2,org_cr_order:null,ad_cro:.1,org_cro:null};
const periodCells={[days[0]]:current,[days[1]]:old,all:current};
const point=(point,a,b)=>({point,section:'Поиск',cells:{[days[0]]:{...current,clicks:a},[days[1]]:{...old,clicks:b}}});
const detail={reports:[],periods:days.map((d,i)=>({id:d,d_from:d,d_to:d,n_days:i?1:2})),
 points:[point('Порог',800,100),point('Меньше порога',799.98,100),point('Ноль',900,0),point('Нет прошлого',900,null),point('Снижение',100,900),
 point('Ровно минус 30',140,100),point('Больше минус 30',139.998,100),point('Падение до нуля',0,100),point('Одна штука',0,1)],
 total:periodCells,articles:[],can_edit:false,ads:Object.fromEntries(days.map((d,i)=>[d,Object.fromEntries(['total','search','rest','organic'].map(k=>[k,i?old:current]))]))};
const views={periods:days.map(d=>({key:d,d_from:d,d_to:d,n_days:1})),days,
 funnel:{total:periodCells,articles:[{nm_id:77,vendor_code:'DEMO',cells:periodCells}],articles_n:1},
 sources:[{...current,section:'Поиск',points:[]}],sources_total:current,
 sources_days:[{section:'Поиск',all:current,days:periodCells}],n_days:2,d_from:days[1],d_to:days[0]};
const http={get:async url=>{if(url.includes('/entry_points?'))return detail;if(url.includes('/entry_views?'))return views;throw Error(url)}};
const modules=new Map();function load(file){if(modules.has(file))return modules.get(file).exports;
 const mod={exports:{}};modules.set(file,mod);const p=path.join(base,'web/frontend/src',file);
 const code=ts.transpileModule(fs.readFileSync(p+(fs.existsSync(p+'.tsx')?'.tsx':'.ts'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(n=>{if(n==='react')return React;if(n==='react/jsx-runtime')return require(path.join(deps,n));
 if(n==='./api')return{http};if(n==='echarts-for-react')return{__esModule:true,default:()=>null};if(n.startsWith('./'))return load(n.slice(2));throw Error(n);
 },mod,mod.exports);return mod.exports;
}
const {growthCell,growthThreshold}=load('entryGrowth');
const {changeCell,declineThreshold}=load('entryGrowth');
assert.equal(typeof changeCell,'function','entry cells must support a separate decline threshold');
const falling=(a,b,t=30)=>changeCell(a,b,null,t,'n').className==='n entry-decline';
assert.ok(falling(69,100));assert.ok(!falling(70,100));assert.ok(!falling(.07,.1));assert.ok(falling(69.999,100));
assert.ok(falling(0,100));assert.ok(!falling(0,100,100));assert.ok(!falling(100,100));assert.ok(!falling(400,100));
assert.ok(!falling(0,1));assert.ok(falling(0,2));assert.ok(falling(0,1.0001));assert.ok(falling(.01,1));
assert.equal(changeCell(0,.01,300,30,'',true,100).className,'','1% → 0% neutral');
assert.equal(changeCell(0,1,300,30,'',true,100).className,'entry-decline','100% → 0% still signals');
// Independent luminance/contrast check across both complete color scales.
const lum=c=>{const v=c.match(/\d+/g).map(Number).map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return .2126*v[0]+.7152*v[1]+.0722*v[2]};
for(const up of [true,false]){
 let previous=[1,1];
 for(let step=1;step<=100;step++){
  const a=up?100+step*100:100-step,style=changeCell(a,100,.1,.1,'n',true).style;
  assert.ok(style,'valid signal has gradient');
  const levels=[lum(style['--entry-fill-light']),lum(style['--entry-fill-dark'])];
  levels.forEach((l,i)=>assert.ok(l<=previous[i],`stronger ${up?'growth':'decline'} cannot get lighter`));previous=levels;
  const ink=style['--entry-ink']==='#fff'?1:0;
  assert.ok((Math.max(ink,levels[0])+.05)/(Math.min(ink,levels[0])+.05)>=4.5,'light text contrast');
  const darkInk=lum(up?'rgb(220,252,231)':'rgb(254,226,226)');
  assert.ok((darkInk+.05)/(levels[1]+.05)>=4.5,'dark text contrast');
 }
}
assert.equal(changeCell(0,1,300,30,'',true).style,undefined);
assert.equal(changeCell(400,100,300,30).style,undefined,'uniform mode retained');
for(const b of [0,-1,null,undefined,NaN,Infinity])assert.ok(!falling(0,b));
for(const a of [-1,null,undefined,NaN,Infinity])assert.ok(!falling(a,100));
for(const t of [null,0,-1,NaN,Infinity,101])assert.ok(!falling(0,100,t));
assert.equal(declineThreshold('30.5'),30.5);assert.equal(declineThreshold('100'),100);
for(const t of ['',null,'-2','0','NaN','Infinity','oops','101'])assert.equal(declineThreshold(t),null);
assert.equal(changeCell(400,100,300,30).className,'entry-growth');
assert.ok(changeCell(50,100,null,30).title.includes('−50'));
const marked=(a,b,t=300)=>growthCell(a,b,t).className==='entry-growth';
assert.ok(marked(400,100));assert.ok(!marked(300,100));assert.ok(!marked(399.999,100));assert.ok(marked(.3,.1,200));
for(const b of [0,-1,null,undefined,NaN,Infinity])assert.ok(!marked(400,b));
for(const a of [0,10,null,undefined,NaN,Infinity])assert.ok(!marked(a,100));
for(const t of [null,0,-1,NaN,Infinity])assert.ok(!marked(400,100,t));
assert.equal(growthThreshold('300.5'),300.5);
for(const t of ['',null,'-2','0','NaN','Infinity','oops'])assert.equal(growthThreshold(t),null);
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const error=console.error;console.error=(...args)=>{warnings.push(args.join(' '));error(...args)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const nodes=()=>walk(box),tick=()=>new Promise(r=>setTimeout(r,30));
const cells=(node=box)=>walk(node).filter(n=>n.tagName==='TD'&&(props(n).className||'').includes('entry-growth'));
const drops=(node=box)=>walk(node).filter(n=>n.tagName==='TD'&&(props(n).className||'').includes('entry-decline'));
const row=s=>nodes().find(n=>n.tagName==='TR'&&n.textContent.includes(s));
const button=s=>nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===s);
const input=()=>nodes().find(n=>props(n)['aria-label']==='Порог роста, %');
const toggle=()=>nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes('Подсвечивать рост')).childNodes.find(n=>n.tagName==='INPUT');
const dropInput=()=>nodes().find(n=>props(n)['aria-label']==='Порог падения, %');
const dropToggle=()=>nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes('Подсвечивать падение')).childNodes.find(n=>n.tagName==='INPUT');
const gradientToggle=()=>nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes('Градиентная заливка')).childNodes.find(n=>n.tagName==='INPUT');
const gradients=()=>[...cells(),...drops()].filter(n=>props(n).style?.['--entry-fill-light']);
async function act(fn){flushSync(fn);await tick();await tick()}
async function click(s){const n=button(s);assert.ok(n,s);await act(()=>props(n).onClick())}
async function change(value){await act(()=>props(input()).onChange({target:{value}}))}
async function changeDrop(value){await act(()=>props(dropInput()).onChange({target:{value}}))}
const {EntryPoints}=load('EntryPoints');
async function mount(p={}){await act(()=>root.render(h(EntryPoints,{shop:7,nm:'',...p})))}
(async()=>{try{
 await mount();assert.equal(props(input()).value,'300');assert.equal(props(toggle()).checked,true);
 assert.equal(props(dropInput()).value,'30');assert.equal(props(dropToggle()).checked,true);
 assert.equal(drops(row('Ровно минус 30')).length,0);assert.equal(drops(row('Больше минус 30')).length,1);
 assert.equal(drops(row('Падение до нуля')).length,1);assert.equal(drops(row('Нет прошлого')).length,0);
 assert.equal(drops(row('Одна штука')).length,0);
 assert.ok(!walk(row('Одна штука')).some(n=>(props(n).className||'').includes('t-bad')),'1 → 0 delta stays neutral');
 assert.equal(props(gradientToggle()).checked,false);assert.equal(gradients().length,0);
 await act(()=>props(gradientToggle()).onChange({target:{checked:true}}));assert.ok(gradients().length);assert.equal(store.get('entry_gradient'),'1');
 await changeDrop('95');assert.equal(drops(row('Снижение')).length,0);assert.equal(drops(row('Падение до нуля')).length,1);
 await changeDrop('101');assert.equal(drops().length,0);assert.ok(cells().length,'invalid decline does not disable growth');
 assert.equal(store.get('entry_decline_threshold'),'95');await changeDrop('30');
 assert.equal(cells(row('Порог')).length,1);assert.equal(cells(row('Меньше порога')).length,0);
 for(const label of ['Ноль','Нет прошлого','Снижение'])assert.equal(cells(row(label)).length,0,label);
 assert.ok(cells(row('Итого')).length);assert.ok(cells(row('органика')).length);assert.ok(cells(row('реклама (вся)')).length);
 await change('500');assert.equal(cells(row('Порог')).length,0,'daily normalization is respected');
 const daily=nodes().find(n=>n.tagName==='LABEL'&&n.textContent===' в день').childNodes.find(n=>n.tagName==='INPUT');
 await act(()=>props(daily).onChange({target:{checked:false}}));assert.equal(cells(row('Порог')).length,1,'raw period totals use raw comparison');
 await change('');assert.equal(cells().length,0);assert.ok(nodes().some(n=>props(n).role==='alert'));assert.equal(store.get('entry_growth_threshold'),'500');
 await change('300');await click('CTR');assert.equal(cells(row('Порог')).length,2,'relative CTR growth is compared separately');
 assert.ok(cells(row('Порог')).some(n=>props(n).title.includes('+300')));
 await click('Показы');await click('Добавления в корзину');await click('Заказы');
 let heads=()=>nodes().filter(n=>n.tagName==='TH'&&(props(n).className||'').includes('rnp-month'));
 assert.deepEqual(heads().map(n=>props(n).colSpan),[10,5],'five metrics, deltas only in newer period');
 const dividers=()=>{
  const table=nodes().find(n=>n.tagName==='TABLE'&&(props(n).className||'').includes('entry-detail-table'));
  assert.ok(table);
  const rows=walk(table).filter(n=>n.tagName==='TR');
  for(const r of rows)assert.equal(r.childNodes.filter(n=>(props(n).className||'').includes('entry-period-start')).length,2,'every row and both headers separate both days');
 };
 dividers();await mount({hideChg:true});dividers();assert.deepEqual(heads().map(n=>props(n).colSpan),[5,5]);await mount();dividers();
 assert.equal(row('Порог').childNodes.filter(n=>n.tagName==='TD').length,17,'label columns and all five values/deltas');
 await click('Конверсия в корзину');assert.deepEqual(heads().map(n=>props(n).colSpan),[10,5],'sixth replaces oldest, limit five');
 for(const s of ['CTR','Показы','Добавления в корзину','Заказы'])await click(s);
 await click('Конверсия в корзину');assert.deepEqual(heads().map(n=>props(n).colSpan),[2,1],'at least one metric');
 await click('Источники трафика по дням');assert.ok(cells().length);assert.ok(cells(row('↳ из них реклама')).length);
 assert.ok(gradients().length,'sources preserve gradient together with nowrap');
 const percentSignals=()=>{
  const rows=nodes().filter(n=>n.tagName==='TR');
  const ctrIndex=rows.findIndex(n=>n.childNodes.some(c=>c.tagName==='TD'&&c.textContent==='CTR'));
  assert.ok(ctrIndex>=0);
  assert.equal(drops(rows[ctrIndex+1]).length,0,'advertising CTR 1% → 0% neutral');
  assert.ok(!walk(rows[ctrIndex+1]).some(n=>props(n).className==='t-bad'));
  assert.equal(drops(rows[ctrIndex+2]).length,1,'organic CTR 100% → 0% red');
 };
 percentSignals();
 assert.ok(drops().length);assert.ok(drops().some(n=>props(n).title.includes('−100')));
 const n=cells().length;assert.ok(n>0);
 await click('Воронка артикулов');assert.ok(cells().length);assert.ok(cells(row('CTR')).length);
 assert.ok(gradients().length,'funnel preserves gradient together with nowrap');
 percentSignals();
 const rows=nodes().filter(n=>n.tagName==='TR');
 for(const [title,advertising,organic] of [['Конверсия в корзину','50,00 %','10,00 %'],['Конверсия в заказ','20,00 %','—'],['CRO (переход → заказ)','10,00 %','—']]){
   const idx=rows.findIndex(n=>n.childNodes.some(c=>c.tagName==='TD'&&c.textContent===title));assert.ok(idx>=0);
   assert.ok(rows[idx+1].textContent.startsWith('↳ реклама'));assert.ok(rows[idx+1].textContent.includes(advertising));
   assert.ok(rows[idx+2].textContent.startsWith('↳ органика (расч.)'));assert.ok(rows[idx+2].textContent.includes(organic));
 }
 assert.ok(drops().length);assert.equal(drops(row('Конверсия в корзину')).length,0,'exact relative 30% boundary stays unmarked');
 assert.ok(drops(row('Конверсия в заказ')).length,'relative decline in ratio, not percentage points');
 assert.ok(cells(row('CTR'))[0].textContent.includes('3,00'),'old percentage-point difference remains unchanged');
 await click('Источники трафика');assert.equal(input(),undefined);assert.equal(dropInput(),undefined);assert.equal(drops().length,0);
 assert.equal(cells().length,0,'single-period summary has no artificial comparison');
 await click('Точки входа подробно');await act(()=>props(toggle()).onChange({target:{checked:false}}));assert.equal(cells().length,0);
 assert.ok(drops().length,'decline independent from growth switch');
 await changeDrop('45');await act(()=>props(dropToggle()).onChange({target:{checked:false}}));assert.equal(drops().length,0);
 await act(()=>root.render(null));await mount();assert.equal(props(toggle()).checked,false);assert.equal(props(input()).value,'300');
 assert.equal(props(gradientToggle()).checked,true,'gradient survives remount');
 assert.equal(props(dropToggle()).checked,false);assert.equal(props(dropInput()).value,'45');
 await act(()=>props(dropToggle()).onChange({target:{checked:true}}));assert.ok(drops().length);
 await act(()=>props(toggle()).onChange({target:{checked:true}}));assert.ok(cells().length);
 await act(()=>props(gradientToggle()).onChange({target:{checked:false}}));assert.equal(gradients().length,0);assert.ok(cells().length,'uniform highlighting restored');
 await mount({enableGrowth:false});assert.equal(input(),undefined);assert.equal(cells().length,0,'frozen demo does not gain new coloring');
 assert.equal(dropInput(),undefined);assert.equal(drops().length,0);
 assert.deepEqual(warnings,[]);console.log('Growth/decline: inclusive/strict boundaries, invalid/missing/zero values, daily totals, relative ratios, all time-series views, independent toggles and persistence OK');
}finally{flushSync(()=>root.unmount());console.error=error}})().catch(e=>{console.error(e);process.exitCode=1});

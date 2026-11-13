// Relative-growth boundary cases and real React entry tables, synthetic data only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map([['entry_view','detail'],['entry_split',JSON.stringify({ad:true,org:true})]]);
global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const days=['2026-11-12','2026-11-11'];
const old={views:100,clicks:100,orders:10,carts:20,ctr:.01,conv_cart:.2,conv_order:.5,ad_views:100,org_views:100};
const current={...old,views:400,clicks:800,ctr:.04,ad_views:400,org_views:400};
const periodCells={[days[0]]:current,[days[1]]:old,all:current};
const point=(point,a,b)=>({point,section:'Поиск',cells:{[days[0]]:{...current,clicks:a},[days[1]]:{...old,clicks:b}}});
const detail={reports:[],periods:days.map((d,i)=>({id:d,d_from:d,d_to:d,n_days:i?1:2})),
 points:[point('Порог',800,100),point('Меньше порога',799.98,100),point('Ноль',900,0),point('Нет прошлого',900,null),point('Снижение',100,900)],
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
const row=s=>nodes().find(n=>n.tagName==='TR'&&n.textContent.includes(s));
const button=s=>nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===s);
const input=()=>nodes().find(n=>props(n)['aria-label']==='Порог роста, %');
const toggle=()=>nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes('Подсвечивать рост')).childNodes.find(n=>n.tagName==='INPUT');
async function act(fn){flushSync(fn);await tick();await tick()}
async function click(s){const n=button(s);assert.ok(n,s);await act(()=>props(n).onClick())}
async function change(value){await act(()=>props(input()).onChange({target:{value}}))}
const {EntryPoints}=load('EntryPoints');
async function mount(p={}){await act(()=>root.render(h(EntryPoints,{shop:7,nm:'',...p})))}
(async()=>{try{
 await mount();assert.equal(props(input()).value,'300');assert.equal(props(toggle()).checked,true);
 assert.equal(cells(row('Порог')).length,1);assert.equal(cells(row('Меньше порога')).length,0);
 for(const label of ['Ноль','Нет прошлого','Снижение'])assert.equal(cells(row(label)).length,0,label);
 assert.ok(cells(row('Итого')).length);assert.ok(cells(row('органика')).length);assert.ok(cells(row('реклама (вся)')).length);
 await change('500');assert.equal(cells(row('Порог')).length,0,'daily normalization is respected');
 const daily=nodes().find(n=>n.tagName==='LABEL'&&n.textContent===' в день').childNodes.find(n=>n.tagName==='INPUT');
 await act(()=>props(daily).onChange({target:{checked:false}}));assert.equal(cells(row('Порог')).length,1,'raw period totals use raw comparison');
 await change('');assert.equal(cells().length,0);assert.ok(nodes().some(n=>props(n).role==='alert'));assert.equal(store.get('entry_growth_threshold'),'500');
 await change('300');await click('CTR');assert.equal(cells(row('Порог')).length,2,'relative CTR growth is compared separately');
 assert.ok(cells(row('Порог')).some(n=>props(n).title.includes('+300')));
 await click('Источники трафика по дням');assert.ok(cells().length);assert.ok(cells(row('↳ из них реклама')).length);
 const n=cells().length;assert.ok(n>0);
 await click('Воронка артикулов');assert.ok(cells().length);assert.ok(cells(row('CTR')).length);
 assert.ok(cells(row('CTR'))[0].textContent.includes('3,00'),'old percentage-point difference remains unchanged');
 await click('Источники трафика');assert.equal(input(),undefined);assert.equal(cells().length,0,'single-period summary has no artificial comparison');
 await click('Точки входа подробно');await act(()=>props(toggle()).onChange({target:{checked:false}}));assert.equal(cells().length,0);
 await act(()=>root.render(null));await mount();assert.equal(props(toggle()).checked,false);assert.equal(props(input()).value,'300');
 await act(()=>props(toggle()).onChange({target:{checked:true}}));assert.ok(cells().length);
 await mount({enableGrowth:false});assert.equal(input(),undefined);assert.equal(cells().length,0,'frozen demo does not gain new coloring');
 assert.deepEqual(warnings,[]);console.log('Growth: exact boundary, invalid/missing/zero values, normalized totals, relative CTR, all time-series views, split rows, toggle and persistence OK');
}finally{flushSync(()=>root.unmount());console.error=error}})().catch(e=>{console.error(e);process.exitCode=1});

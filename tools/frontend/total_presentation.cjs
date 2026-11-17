// Real Total component, synthetic identities and financials, no network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map();global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const v={orders:12345,buyouts:10000,margin:4500,ads:-500,profit:4000,cost_sold:2000},series={'2026-11-11':{...v,profit:-500,cost_sold:0},'2026-11-12':v};
const names=['SECRET-WB','SECRET-OZ','SECRET-YM','SECRET-ACCOUNT','SECRET-SECOND','SECRET-PERSON','SECRET-ERROR'];
const staff=[{id:8,name:'SECRET-PERSON',workspace:'SECRET-ACCOUNT'},{id:9,name:'SECOND-PERSON',workspace:'SECRET-SECOND'}];
const data={days:['2026-11-11','2026-11-12'],today:'2026-11-13',staff,shops:[
 {id:10,title:'SECRET-WB',workspace:'SECRET-ACCOUNT',mp:'wb',series},
 {id:30,title:'SECRET-OZ',workspace:'SECRET-SECOND',mp:'ozon',series:{'2026-11-11':{...v,profit:0,cost_sold:0},'2026-11-12':{...v,profit:1000,cost_sold:8000}}},
 {id:90,title:'SECRET-YM',workspace:'SECRET-SECOND',mp:'ym',error:'SECRET-ERROR'}]};
const pending=[],calls=[],http={get:url=>{calls.push(url);return new Promise((resolve,reject)=>pending.push({resolve,reject,url}))}};
const code=ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/Total.tsx'),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const pick={exports:{}};new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/ManagerPicker.tsx'),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)(n=>require(path.join(deps,n)),pick,pick.exports);
const mod={exports:{}};new Function('require','module','exports',code)(n=>{
 if(n==='./ManagerPicker')return pick.exports; if(n==='react')return React;if(n==='react/jsx-runtime')return require(path.join(deps,n));if(n==='./api')return{http};
 if(n==='echarts-for-react')return{__esModule:true,default:p=>h('div',{'data-chart':JSON.stringify(p.option.series.map(s=>({name:s.name,data:s.data,yAxisIndex:s.yAxisIndex})))})};throw Error(n);
},mod,mod.exports);
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const error=console.error;console.error=(...args)=>warnings.push(args.join(' '));
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{},nodes=()=>walk(box),tick=()=>new Promise(r=>setTimeout(r,25));
async function act(fn){flushSync(fn);await tick();await tick()}
function Screen(){const[p,set]=React.useState(false);return h(mod.exports.Total,{dark:false,presentation:p,onPresentationChange:set,shopIds:[10,30,90]})}
async function click(text){const n=nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===text);assert.ok(n,text);await act(()=>props(n).onClick())}
const labels=()=>nodes().filter(n=>n.tagName==='LABEL'&&String(props(n).className||'').startsWith('total-shop')),manager=i=>walk(nodes().find(n=>props(n).className==='manager-picker-list')).filter(n=>n.tagName==='INPUT')[i];
const money=()=>nodes().filter(n=>(props(n).className||'')==='total-kpi'||props(n)['data-chart']).map(n=>n.textContent+String(props(n)['data-chart']||''));
const tableRow=title=>nodes().find(n=>n.tagName==='TR'&&n.childNodes.find(c=>c.tagName==='TD')?.textContent===title);
const values=title=>tableRow(title).childNodes.filter(n=>n.tagName==='TD').slice(1).map(n=>n.textContent.replace(/[\s\u00a0]/g,''));
const tile=title=>nodes().find(n=>props(n).className==='total-tile'&&n.textContent.startsWith(title));
const hidden=()=>{const visible=box.textContent+nodes().map(n=>[props(n).title,props(n)['aria-label'],props(n).alt].join(' ')).join(' ');for(const name of [...names,'SECOND-PERSON'])assert.ok(!visible.includes(name),name+' leaked');};
(async()=>{try{
 await act(()=>root.render(h(Screen)));await click('Версия для демонстрации');hidden();assert.ok(box.textContent.includes('Складываю магазины'));
 await act(()=>pending.shift().resolve(data));hidden();
 assert.ok(labels()[0].textContent.includes('1 WB'));assert.ok(labels()[1].textContent.includes('2 Ozon'));assert.ok(labels()[2].textContent.includes('3 Маркет'));
 assert.ok(props(labels()[2]).title==='Данные магазина пока недоступны');
 assert.deepEqual(values('Себестоимость проданного, ₽'),['10000','10000','0']);
 assert.deepEqual(values('Рентабельность, %'),['45,0%','50,0%','—'],'ratio of sums, not average daily or shop percentages');
 assert.ok(tile('Рентабельность').textContent.includes('45,0 %'));
 assert.ok(tile('Себестоимость проданного').textContent.includes('10 000 ₽'));
 const charts=JSON.parse(props(nodes().find(n=>props(n)['data-chart']))['data-chart']);
 assert.deepEqual(charts.find(s=>s.name==='Рентабельность, %').data,[null,.5]);
 assert.equal(charts.find(s=>s.name==='Рентабельность, %').yAxisIndex,1);
 assert.deepEqual(charts.find(s=>s.name==='Себестоимость проданного, ₽').data,[0,10000]);
 const original=money();await click('Обычная версия');assert.ok(box.textContent.includes('SECRET-WB'));assert.ok(box.textContent.includes('SECRET-PERSON'));assert.deepEqual(money(),original);
 await click('Версия для демонстрации');hidden();assert.deepEqual(money(),original);
 const check=labels()[0].childNodes.find(n=>n.tagName==='INPUT');await act(()=>props(check).onChange({target:{checked:false}}));hidden();
 const selected=money();assert.notDeepEqual(selected,original);assert.equal(store.get('total_off'),'[10]');
 assert.equal(values('Рентабельность, %')[0],'12,5%','shop selection recalculates denominator');
 await click('Обычная версия');assert.deepEqual(money(),selected);await click('Версия для демонстрации');assert.deepEqual(money(),selected);
 await act(()=>props(manager(0)).onChange({target:{checked:true}}));hidden();assert.ok(box.textContent.includes('Складываю магазины'), JSON.stringify({calls,text:box.textContent,warnings}));
 await act(()=>pending.shift().resolve({...data,shops:[data.shops[1]]}));hidden();assert.ok(labels()[0].textContent.includes('2 Ozon'),'number stable under staff filter');
 await act(()=>props(manager(1)).onChange({target:{checked:true}}));assert.ok(calls.at(-1).includes('staff=8,9'));const stale=pending.shift();
 await click('Обычная версия');await click('Версия для демонстрации');hidden();
 await act(()=>stale.reject(Error('SECRET-ERROR')));hidden();assert.ok(box.textContent.includes('Не удалось загрузить показатели'));
 await click('Обычная версия');assert.ok(box.textContent.includes('SECRET-ERROR'));
 // Unmounted request cannot replace the next visit or report a stale error.
 await act(()=>root.render(null));await act(()=>root.render(h(Screen)));const abandoned=pending.shift();
 await act(()=>root.render(null));await act(()=>root.render(h(Screen)));const current=pending.shift();
 await act(()=>current.resolve(data));await click('Версия для демонстрации');hidden();
 await act(()=>abandoned.reject(Error('SECRET-ERROR')));hidden();assert.ok(!box.textContent.includes('Не удалось загрузить показатели'));
 // Missing/old fields must not become zero or a partial portfolio denominator.
 for(const [cost,profit,expected] of [[undefined,1000,'—'],[null,1000,'—'],[0,1000,'—'],[-100,1000,'—'],[2000,-500,'−25,0%']]){
  store.clear();await act(()=>root.render(null));await act(()=>root.render(h(Screen)));
  const one={...data,days:['2026-11-12'],shops:[{...data.shops[0],series:{'2026-11-12':{...v,cost_sold:cost,profit}}}]};
  await act(()=>pending.shift().resolve(one));
  assert.equal(values('Рентабельность, %')[0].replace('-', '−'),expected);
  if(cost==null)assert.equal(values('Себестоимость проданного, ₽')[0],'—');
  if(profit<0)assert.ok(tableRow('Рентабельность, %').childNodes.some(n=>props(n).className==='neg'));
  assert.ok(!box.textContent.includes('NaN'));assert.ok(!box.textContent.includes('Infinity'));
 }
 store.clear();await act(()=>root.render(null));await act(()=>root.render(h(Screen)));
 await act(()=>pending.shift().resolve({...data,shops:[{...data.shops[0],series:{'2026-11-12':{...v,cost_sold:null}}},data.shops[1]]}));
 assert.equal(values('Себестоимость проданного, ₽')[0],'—');assert.equal(values('Рентабельность, %')[0],'—');
 assert.ok(values('Прибыль, ₽')[0]==='5000','missing cost does not change the existing profit');
 assert.deepEqual(warnings,[]);console.log('Cost/return: weighted ratios, daily/shop/portfolio totals, selection, graph, losses, zero and unknown cost OK');console.log('Total presentation: identities/tooltips/errors masked, stable numbering, same money/charts/selection, filters and stale responses OK');
}finally{flushSync(()=>root.unmount());console.error=error}})().catch(e=>{console.error(e);process.exitCode=1});

// Real React DOM/components, synthetic API; no live shop writes or browser cookies.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document,window}=require('./test_dom.cjs');
const base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),
 {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map(),events=new Map();global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
window.location={pathname:'/compare',search:''};window.history={pushState:(_a,_b,url)=>{window.location.pathname=url}};
window.addEventListener=(k,f)=>{if(!events.has(k))events.set(k,new Set());events.get(k).add(f)};
window.removeEventListener=(k,f)=>events.get(k)?.delete(f);
document.documentElement.dataset={};
const modules=new Map(),calls=[],writes=[];let blockShop7=false,resolveOld;
const board=shop=>({days:['2026-11-13','2026-11-12'],month:'2026-11-01',me:99,can_edit:true,kinds:[],rows:[{
 nm_id:shop*10,vendor_code:'SHOP-'+shop,title:'Synthetic',orders:{'2026-11-13':12,'2026-11-12':10},actions:{},
 stock_wb:25,stock_fbs:3,stock:28,price:1000,price_spp:800,margin_pct:.2,rating:4.8,orders_avg:11,stock_days:2.5,spp:.2,plan:50,drr_orders:.1,drr_buyouts:.15,conv_cart:.1,conv_order:.2}]});
const list={mine:[{id:5,nm_ids:[],photos:{},brands:{},period_from:'2026-11-01',period_to:'2026-11-10'}],team:[],saved:[],subs:[],seen:[],quota:{shared:0,allowed:0,used:0,left:0},client:true};
const http={get:async url=>{calls.push(url);
 if(url.includes('/manager/board')){const shop=Number(url.split('/')[3]);if(blockShop7&&shop===7)return new Promise(r=>resolveOld=r);return board(shop)}
 if(url.includes('/manager/charts')){const shop=Number(url.split('/')[3]);return {days:['2026-11-12','2026-11-13'],price_label:'Цена с СПП, ₽',note:'test sources',rows:{[shop*10]:{orders:[1,2],buyouts:[0,1],ads:[30,40],price_spp:[null,800],profit:[10,-20]}}}}
 if(url==='/api/compare/mine')return list;
 if(url==='/api/compare/5')throw Error('Не найден тестовый отчёт');
 throw Error(url);
},put:async(url,payload)=>{writes.push([url,payload]);return{};}};
function load(file){if(modules.has(file))return modules.get(file).exports;
 const mod={exports:{}};modules.set(file,mod);const filename=path.join(base,'web/frontend/src',file+'.tsx');
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(name=>{
  if(name==='react')return React;if(name==='react/jsx-runtime')return require(path.join(deps,name));
  if(name==='./api')return{http,api:{}};
  if(name==='./Logo')return{Logo:()=>h('i',null,'logo')};if(name==='./PhotoFunnel')return{Slides:()=>null};
  if(name==='echarts-for-react')return{__esModule:true,default:()=>null};
  if(name==='./ActionSparks')return load('ActionSparks');throw Error(name);
 },mod,mod.exports);return mod.exports;}
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const old=console.error;console.error=(...args)=>{warnings.push(args.join(' '));old(...args)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],nodes=()=>walk(box),props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const tick=()=>new Promise(r=>setTimeout(r,25)),settle=async()=>{await tick();await tick()};
const render=async(c,p)=>{flushSync(()=>root.render(h(c,p)));await settle()};
const button=t=>nodes().find(n=>n.tagName==='BUTTON'&&(n.textContent===t||props(n).title===t));
const check=t=>walk(nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes(t))).find(n=>n.tagName==='INPUT');
const change=async(n,target)=>{assert.ok(n);flushSync(()=>props(n).onChange({target}));await settle()};
const click=async(n)=>{assert.ok(n);flushSync(()=>props(n).onClick());await settle()};
(async()=>{try{
 const {ActionsBoard}=load('ActionsBoard'),{ComparePage}=load('Compare');
 await render(ActionsBoard,{shop:7,shops:[{id:7,title:'One'}]});
 let fields=nodes().filter(n=>props(n).className==='action-key-item');assert.equal(fields.length,15);
 assert.equal(fields[0].textContent,'Ост. WB25');assert.ok(fields[14].textContent.includes('Конв. зак.'));
 assert.equal(calls.filter(x=>x.includes('/manager/charts')).length,0,'charts are opt-in');
 await change(check('графики за 30 дней'),{checked:true});
 assert.equal(store.get('act_charts'),'1');assert.equal(nodes().filter(n=>props(n).role==='img').length,5);
 assert.equal(nodes().find(n=>n.tagName==='THEAD').textContent,'АртикулКлючевые данныеГрафики · 30 дней13.11пт12.11чт');
 await click(button('План продаж на ноябрь, шт'));
 const input=nodes().find(n=>props(n)['aria-label']==='План SHOP-7');assert.ok(input);
 flushSync(()=>props(input).onBlur({target:{value:'60'}}));await settle();
 assert.deepEqual(writes,[['/api/shops/7/nm_plan',{nm_id:70,month:'2026-11-01',qty:60}]]);
 await change(check('ключевые данные'),{checked:false});assert.equal(nodes().filter(n=>props(n).className==='action-key-item').length,0);
 assert.equal(nodes().filter(n=>props(n).role==='img').length,5,'independent chart visibility');
 await change(check('графики за 30 дней'),{checked:false});assert.equal(nodes().filter(n=>props(n).role==='img').length,0);
 flushSync(()=>root.render(null));blockShop7=true;
 await render(ActionsBoard,{shop:7,shops:[{id:7,title:'One'}]});assert.ok(resolveOld);
 await render(ActionsBoard,{shop:8,shops:[{id:8,title:'Two'}]});assert.ok(box.textContent.includes('SHOP-8'));
 resolveOld(board(7));await settle();assert.ok(!box.textContent.includes('SHOP-7'),'late old-shop response ignored');
 await render(ComparePage,{embedded:true});
 assert.ok(nodes().some(n=>props(n).className==='cmp-embedded'));assert.ok(!nodes().some(n=>props(n).className==='cmp-wrap'));
 assert.ok(!box.textContent.includes('logo'),'embedded comparison has no duplicate site header');
 await click(nodes().find(n=>props(n).className==='cmp-item'));assert.equal(window.location.pathname,'/compare/5');
 assert.ok(box.textContent.includes('Не найден тестовый отчёт'));await click(button('← к списку'));
 assert.equal(window.location.pathname,'/compare');assert.ok(box.textContent.includes('Сравнение карточек'));
 assert.deepEqual(warnings,[]);console.log('Actions: 3×5, optional charts, plan editing, shop race; embedded comparison and report navigation OK');
 }finally{flushSync(()=>root.unmount());console.error=old;}})().catch(e=>{console.error(e);process.exitCode=1});

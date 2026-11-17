// Real components, saved synthetic data; no live services or credentials.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const store=new Map();global.localStorage={getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)};
const rnp={month:'2026-11',days:['2026-11-17'],weeks:[],current:true,elapsed:17,dim:30,
 total:{articles:0,stock:0,month:{},forecast:{},plan:null,plan_day:null,weeks:[{},{},{}],days:{},spark:{}},
 blocks:[],count:0,offset:0,page:100,has_plan:false,sorts:{orders_sum:'Orders'},brands:[],subjects:[],buyout_shop:0};
rnp.weeks=[['2026-11-02','2026-11-08'],['2026-11-09','2026-11-15'],['2026-11-16','2026-11-17']];rnp.current=true;
const heat={status:'ready',months:['2026-09-01','2026-10-01','2026-11-01'],rows:[{query:'candle',values:{'2026-09-01':0,'2026-11-01':1200}}],queries:['candle'],limit:100,completed:1};
const entry={id:1,workspace_id:1,kind:'link',url:'https://www.wildberries.ru/catalog/123/detail.aspx',title:'Liked card',author:'Synthetic',created_at:'2026-11-17',can_change:true};
const kb={tree:[],items:[entry,{...entry,id:2,url:'https://example.test/reference',title:'Other link'}],shops:[],can_add:true,can_admin:true};
let heatStatus='ready',kbStatus='ready',hold=false;const calls=[],pending=[],writes=[];
const http={get:async url=>{calls.push(url);if(hold)return new Promise(resolve=>pending.push({url,resolve}));
 if(url.includes('/query_heatmap/'))return{...heat,status:heatStatus};
 if(url.includes('/rnp?'))return rnp;
 if(url.startsWith('/api/workspaces/'))return kb;
 if(url==='/api/kb/items/1/slides')return{status:kbStatus,hashes:['slide1','slide2'],captured_at:'2026-11-17T10:00:00Z'};
 throw Error(url);
},post:async url=>{writes.push(url);if(url.includes('/query_heatmap/'))heatStatus='ready';else kbStatus='failed';return{}}};
const modules=new Map();function load(file){if(modules.has(file))return modules.get(file).exports;
 const mod={exports:{}};modules.set(file,mod);const filename=path.join(base,'web/frontend/src',file+'.tsx');
 const code=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(name=>{
 if(name==='react')return React;if(name==='react/jsx-runtime')return require(path.join(deps,name));
 if(name==='./api')return {http,api:{groups:async()=>[]}};
 if(name==='./PhotoFunnel')return load('PhotoFunnel');throw Error(name);
 },mod,mod.exports);return mod.exports;}
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const original=console.error;console.error=(...args)=>{warnings.push(args.join(' '));original(...args)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],nodes=()=>walk(box),props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{},tick=()=>new Promise(r=>setTimeout(r,30));
async function act(fn){flushSync(fn);await tick();await tick()}
async function render(C,p){await act(()=>root.render(h(C,p)))}
const button=text=>nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===text);
async function click(text){const n=button(text);assert.ok(n,text);await act(()=>props(n).onClick())}
(async()=>{try{
 const {ManagerPicker}=load('ManagerPicker');let last='';function Pick(){const[v,set]=React.useState('');return h(ManagerPicker,{value:v,items:[{id:8,name:'First'},{id:3,name:'Second'}],onChange:x=>{last=x;set(x)}})}
 await render(Pick,{});
 const inputs=()=>nodes().filter(n=>n.tagName==='INPUT');
 await act(()=>props(inputs()[0]).onChange({target:{checked:true}}));assert.equal(last,'8');
 await act(()=>props(inputs()[1]).onChange({target:{checked:true}}));assert.equal(last,'3,8');assert.ok(box.textContent.includes('Менеджеры: 2'));
 await act(()=>props(inputs()[0]).onChange({target:{checked:false}}));assert.equal(last,'3');
 await click('Все менеджеры');assert.equal(last,'');
 const {Rnp}=load('Rnp');await render(Rnp,{shop:3,staff:'3,8'});
 assert.ok(calls.at(-1).includes('staff=3,8'));
 const headers=nodes().filter(n=>n.tagName==='TH').map(n=>n.textContent);
 assert.ok(headers.some(x=>x.includes('1 Нед')&&x.includes('02.11–08.11')));
 assert.ok(headers.some(x=>x.includes('3 Нед')&&x.includes('16.11–17.11')));
 const {QueryHeatmap}=load('QueryHeatmap');await render(QueryHeatmap,{shop:1,nm:'123'});
 assert.ok(box.textContent.includes('Частотность'));const cells=nodes().filter(n=>n.tagName==='TD');
 assert.deepEqual(cells.map(x=>x.textContent),['0','—','1 200']);assert.ok(!props(cells[0]).style?.backgroundColor);assert.ok(props(cells[2]).style.backgroundColor);
 await click('Загрузить / обновить из Wildbox');assert.deepEqual(writes,['/api/shops/1/query_heatmap/123']);
 await render(QueryHeatmap,{shop:1,nm:'123,456'});assert.ok(box.textContent.includes('Выберите один товар'));assert.ok(!box.textContent.includes('candle'));
 hold=true;await render(QueryHeatmap,{shop:1,nm:'123'});const old=pending.shift();
 await render(QueryHeatmap,{shop:2,nm:'456'});const current=pending.shift();
 await act(()=>current.resolve({...heat,rows:[{query:'current',values:{}}]}));await act(()=>old.resolve(heat));assert.ok(box.textContent.includes('current'));assert.ok(!box.textContent.includes('candle'));
 hold=false;const {Kb}=load('Kb');await render(Kb,{wsId:1});
 const images=()=>nodes().filter(n=>n.tagName==='IMG').map(n=>props(n).src);
 assert.deepEqual(images(),['/api/photo/slide1','/api/photo/slide2']);assert.ok(box.textContent.includes('Слайды сохранены'));
 assert.ok(nodes().some(n=>n.tagName==='A'&&props(n).href===entry.url));assert.ok(!calls.includes('/api/kb/items/2/slides'));
 await click('Обновить слайды');assert.ok(box.textContent.includes('Не удалось получить слайды'));assert.equal(images().length,2,'old gallery remains on refresh failure');
 hold=true;await render(Kb,{wsId:2});const oldKb=pending.shift();await render(Kb,{wsId:3});const newKb=pending.shift();
 await act(()=>newKb.resolve({...kb,items:[]}));await act(()=>oldKb.resolve(kb));assert.equal(images().length,0);assert.ok(!box.textContent.includes('Liked card'));
 assert.deepEqual(warnings,[]);console.log('Batch UI: manager union, calendar week dates, frequency heatmap/null/zero, saved KB gallery, failed refresh and stale workspace replies OK');
}finally{flushSync(()=>root.unmount());console.error=original}})().catch(e=>{console.error(e);process.exitCode=1});

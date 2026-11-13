// Real useTabData + App's actual retry effect. Virtual timers; no production API.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const {document}=require('./test_dom.cjs'),React=require(path.join(deps,'react'));
const {createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom'));
const ts=require(path.join(deps,'typescript')),h=React.createElement;
const requests=[],timers=new Map();let timerId=0;
const setTimer=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},clearTimer=id=>timers.delete(id);
const api={tab:(shop,tab,query,signal)=>new Promise((resolve,reject)=>requests.push({shop,tab,signal,resolve,reject}))};
const mod={exports:{}};
const code=ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/useTabData.ts'),'utf8'),
 {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports','setTimeout','clearTimeout',code)(n=>n==='react'?React:{api},mod,mod.exports,setTimer,clearTimer);
const source=fs.readFileSync(path.join(base,'web/frontend/src/App.tsx'),'utf8');
const ast=ts.createSourceFile('App.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let retry;
function visit(n){if(ts.isExpressionStatement(n)&&n.getText(ast).startsWith('useEffect(')&&n.getText(ast).includes('if (!data?.retry)'))retry=n.getText(ast);ts.forEachChild(n,visit)}
visit(ast);assert.ok(retry,'test must exercise the actual App polling effect');
const effect=ts.transpileModule(retry,{compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText;
const Screen=new Function('React','useTabData','setTimeout','clearTimeout',`return function Screen({shop,tab}){
 const {useState,useEffect}=React;const [reload,setReload]=useState(0);
 const {data,error,loading}=useTabData(shop,tab,{from:'2026-10-15',to:'2026-11-13'},true,reload);
 ${effect}
 return React.createElement('div',null,error||data?.note||(loading?'loading':JSON.stringify(data?.rows)));
}`)(React,mod.exports.useTabData,setTimer,clearTimer);
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const tick=()=>new Promise(r=>setImmediate(r));
async function act(fn){flushSync(fn);await tick();await tick();await tick()}
async function render(shop=3,tab='opiu_wb'){await act(()=>root.render(h(Screen,{shop,tab})))}
const pending=tab=>({key:tab,columns:[],rows:[],note:'Ожидаем пересчёта себестоимости',retry:15});
const poll=()=>[...timers].find(([,t])=>t.ms===15000);
(async()=>{try{
 await render();assert.equal(requests.length,1);
 await act(()=>requests[0].resolve(pending('opiu_wb')));assert.ok(box.textContent.includes('Ожидаем'));assert.ok(poll());
 const [id,t]=poll();timers.delete(id);await act(()=>t.fn());assert.equal(requests.length,2);
 await act(()=>requests[1].resolve({key:'opiu_wb',columns:[],rows:[{profit:500}]}));
 assert.ok(box.textContent.includes('500'));assert.equal(poll(),undefined,'poll stops when data is ready');
 await render(3,'pnl_alt_m');await act(()=>requests.at(-1).resolve(pending('pnl_alt_m')));assert.ok(poll());
 const [costId,costPoll]=poll();timers.delete(costId);await act(()=>costPoll.fn());
 await act(()=>requests.at(-1).resolve({...pending('pnl_alt_m'),retry:10,note:'Считаем альтернативный PnL'}));
 assert.equal(poll(),undefined);const [altId,altPoll]=[...timers].find(([,v])=>v.ms===10000);
 timers.delete(altId);await act(()=>altPoll.fn());
 await act(()=>requests.at(-1).resolve({key:'pnl_alt_m',columns:[],rows:[{profit:750}]}));
 assert.ok(box.textContent.includes('750'));assert.equal(timers.size,0);
 await render(3,'pnl_alt_nm');await act(()=>requests.at(-1).resolve(pending('pnl_alt_nm')));assert.ok(poll());
 await render(8,'pnl_real_w');assert.equal(poll(),undefined,'previous shop/tab polling is cancelled');
 await act(()=>requests.at(-1).resolve({key:'pnl_real_w',columns:[],rows:[],note:'Другой тип ожидания'}));
 assert.equal(poll(),undefined,'generic waiting is not polled without server instruction');
 await render(3,'pnl_alt_nm');await act(()=>requests.at(-1).resolve(pending('pnl_alt_nm')));assert.ok(poll());
 await act(()=>root.unmount());assert.equal(timers.size,0,'unmount clears polling and request deadline');
 console.log('Financial waiting: actual App poll -> ready, no stale amounts, stops on ready/navigation/shop/unmount OK');
}finally{flushSync(()=>root.unmount())}})().catch(e=>{console.error(e);process.exitCode=1});

// Real React reconciliation, synthetic backend; no credentials or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs');
const base=process.argv[2]||path.resolve(__dirname,'../..'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const requests=[];const http=Object.fromEntries(['get','post','put'].map(name=>[name,(...args)=>new Promise((resolve,reject)=>requests.push({name,args,resolve,reject}))]));
const src=fs.readFileSync(path.join(base,'web/frontend/src/PersonalAI.tsx'),'utf8'),mod={exports:{}};
const js=ts.transpileModule(src,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',js)(name=>name==='react'?React:name==='react/jsx-runtime'?require(path.join(deps,'react/jsx-runtime')):name==='./api'?{http}:(()=>{throw Error(name)})(),mod,mod.exports);
const tick=()=>new Promise(r=>setTimeout(r,20)),walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const button=(box,title)=>{const n=walk(box).find(n=>n.tagName==='BUTTON'&&n.textContent===title);assert.ok(n,title);return n;};
const click=async(box,title)=>{flushSync(()=>props(button(box,title)).onClick());await tick();};
(async()=>{
 const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);let saved=0;
 flushSync(()=>root.render(React.createElement(mod.exports.PersonalAI,{onSaved(){saved++}})));await tick();
 requests.at(-1).resolve({config:{},workspaces:[{id:7,name:'Synthetic'}],shops:[{id:1,name:'Own',workspace_id:7},{id:2,name:'Foreign',workspace_id:9}]});await tick();
 assert.ok(!box.textContent.includes('Foreign'));
 const save='Включить VIP / сохранить выбор';assert.ok(props(button(box,save)).disabled);
 const checkbox=walk(box).find(n=>n.tagName==='INPUT');flushSync(()=>props(checkbox).onChange({target:{checked:true}}));
 await click(box,'Проверить подключение');requests.at(-1).resolve({text_ready:false,image_ready:false,reason:'No login'});await tick();
 assert.ok(props(button(box,save)).disabled);assert.ok(box.textContent.includes('No login'));
 await click(box,'Проверить подключение');requests.at(-1).resolve({text_ready:true,image_ready:false,image_reason:'No image capability'});await tick();
 assert.ok(!props(button(box,save)).disabled);assert.ok(box.textContent.includes('No image capability'));
 await click(box,save);assert.deepEqual(requests.at(-1).args[1],{workspace_id:7,shop_ids:[1],enabled:true});
 requests.at(-1).reject(Error('Access revoked'));await tick();assert.equal(saved,0);assert.ok(box.textContent.includes('Access revoked'));
 await click(box,save);requests.at(-1).resolve({config:{enabled:true,workspace_id:7,shop_ids:[1],text_ready:true,image_ready:false}});await tick();assert.equal(saved,1);assert.ok(box.textContent.includes('VIP включён'));
 await click(box,'Проверить подключение');flushSync(()=>root.unmount());requests.at(-1).resolve({text_ready:true,image_ready:true});await tick();assert.equal(saved,1);
 console.log('Personal VIP React scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1});

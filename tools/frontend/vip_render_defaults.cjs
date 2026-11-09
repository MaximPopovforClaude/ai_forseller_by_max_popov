// Real React state: VIP adoption, unavailable image capability, explicit opt-out.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs');
const base=process.argv[2]||path.resolve(__dirname,'../..'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const mod={exports:{}},source=fs.readFileSync(path.join(base,'web/frontend/src/visualBilling.tsx'),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',js)(name=>name==='react'?React:name==='react/jsx-runtime'?require(path.join(deps,'react/jsx-runtime')):name==='./api'?{http:{post(){throw Error('Opening/choosing must not generate')}}}:(()=>{throw Error(name)})(),mod,mod.exports);
const {useRenderSelection,modelsReady,RenderModels}=mod.exports;
let selected,choose,ready;
function View({scope,models}){[selected,choose]=useRenderSelection(scope,models);ready=modelsReady(models,selected);return React.createElement(RenderModels,{models,value:selected,onChange:choose});}
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const api={id:'api',provider:'openai',title:'API',ready:true,why:null},hf={id:'hf',provider:'higgsfield',title:'Higgsfield',ready:true,why:null};
const vip={id:'vip_chatgpt_image',provider:'chatgpt',title:'Personal GPT Image',ready:true,default:true,why:null};
const show=(models,scope='shop/project')=>flushSync(()=>root.render(React.createElement(View,{scope,models})));
show([api,hf]);assert.deepEqual(selected,[]);flushSync(()=>choose(['api']));assert.deepEqual(selected,['api']);
show([vip,hf]);assert.deepEqual(selected,[vip.id]);assert.ok(ready);assert.ok(box.textContent.includes('Codex на сервере вашей установки'));
show([{...vip,ready:false,why:'Connect personal Codex'},hf]);assert.deepEqual(selected,[vip.id]);assert.equal(ready,false);assert.ok(box.textContent.includes('Connect personal Codex'));
flushSync(()=>choose([]));show([vip,hf]);assert.deepEqual(selected,[]);assert.equal(ready,false);
show([vip,hf],'shop/new-project');assert.deepEqual(selected,[vip.id]);
flushSync(()=>choose(['hf']));show([vip,hf],'shop/new-project');assert.deepEqual(selected,['hf']);
show([vip],'shop/new-project');assert.deepEqual(selected,[]);assert.equal(ready,false);
show([vip,hf],'shop/another-project');assert.deepEqual(selected,[vip.id]);
show([api,hf],'client/project');assert.deepEqual(selected,[]);
flushSync(()=>root.unmount());console.log('VIP render defaults: adoption, all readiness states, opt-out, project/client isolation passed');

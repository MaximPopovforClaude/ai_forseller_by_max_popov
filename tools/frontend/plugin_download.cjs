// Real PluginBox: configured ZIP download and visible setup errors.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs');
const base=path.resolve(process.argv[2]||path.resolve(__dirname,'../..')),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const requests=[],clicks=[],blobs=[];global.fetch=()=>new Promise(resolve=>requests.push(resolve));
const create=document.createElement.bind(document);document.createElement=name=>{const n=create(name);if(name==='a')n.click=()=>clicks.push({href:n.href,name:n.download});return n;};
global.URL={createObjectURL:blob=>{blobs.push(blob);return 'blob:fixture';},revokeObjectURL(){}};
const source=fs.readFileSync(path.join(base,'web/frontend/src/Plugin.tsx'),'utf8'),mod={exports:{}};
const js=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',js)(name=>name==='react'?React:name==='react/jsx-runtime'?require(path.join(deps,'react/jsx-runtime')):name==='./api'?{http:{post(){throw Error('No token requests expected')}}}:name==='./copy'?{copyCell(){}}:(()=>{throw Error(name)})(),mod,mod.exports);
const tick=()=>new Promise(r=>setTimeout(r,15)),walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const button=()=>walk(box).find(n=>n.tagName==='BUTTON'&&n.textContent==='⬇ Скачать плагин');
(async()=>{
 flushSync(()=>root.render(React.createElement(mod.exports.PluginBox,{wsId:1,wsName:'Synthetic'})));await tick();
 flushSync(()=>props(button()).onClick());requests.at(-1)({ok:false,json:async()=>({detail:'Configure SITE_URL'})});await tick();assert.ok(box.textContent.includes('Configure SITE_URL'));assert.equal(clicks.length,0);
 flushSync(()=>props(button()).onClick());requests.at(-1)({ok:true,headers:{get:()=> 'text/html'}});await tick();assert.ok(box.textContent.includes('HTTPS-прокси'));assert.equal(clicks.length,0);
 flushSync(()=>props(button()).onClick());requests.at(-1)({ok:true,headers:{get:()=> 'application/zip'},blob:async()=>({synthetic:true})});await tick();
 assert.equal(clicks.length,1);assert.equal(clicks[0].name,'seller-analytics-plugin.zip');assert.equal(blobs.length,1);assert.ok(!box.textContent.includes('Configure SITE_URL'));
 flushSync(()=>root.unmount());console.log('Plugin download React: invalid site, proxy HTML, successful ZIP PASS');
})().catch(e=>{console.error(e);process.exitCode=1});

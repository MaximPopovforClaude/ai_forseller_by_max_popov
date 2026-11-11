// Real About component: public attribution survives empty and customised settings.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
let about={},requests=[];const modules=new Map();
function load(name){if(modules.has(name))return modules.get(name).exports;const mod={exports:{}};modules.set(name,mod);
 const code=ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src',name+'.tsx'),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
 new Function('require','module','exports',code)(n=>n==='react'?React:n==='react/jsx-runtime'?require(path.join(deps,n)):n==='./Logo'?{Logo:()=>null}:n==='./AuthorChannel'?load('AuthorChannel'):n==='./api'?{http:{get:async p=>{requests.push(p);return about;}}}:(()=>{throw Error(n);})(),mod,mod.exports);return mod.exports;}
const {AboutPage}=load('Legal'),box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
(async()=>{try{let id=0;for(const channel of [null,'https://t.me/installation_support','https://t.me/maxim_popov_wb']){
 about={about:'Independent installation',ready:false,channel,support_bot:'https://t.me/installation_support',email:'support@example.invalid'};
 flushSync(()=>root.render(React.createElement(AboutPage,{key:++id})));await new Promise(r=>setTimeout(r,30));
 const team=walk(box).find(n=>n.tagName==='SECTION'&&n.textContent.includes('Команда'));assert.ok(team);
 const links=walk(team).filter(n=>n.tagName==='A'),author=links.filter(n=>props(n).href==='https://t.me/maxim_popov_wb');
 assert.equal(author.length,1);assert.equal(props(author[0]).target,'_blank');assert.match(props(author[0]).rel,/noopener/);
 assert.equal(links.length,channel==='https://t.me/installation_support'?2:1);
 assert.ok(box.textContent.includes('support@example.invalid'));assert.ok(walk(box).some(n=>props(n).href==='https://t.me/installation_support'));
 }assert.deepEqual(requests,Array(3).fill('/api/public/about'));console.log('About: author channel on fresh/update settings, one link, support preserved, no writes OK');
 }finally{flushSync(()=>root.unmount());}})().catch(e=>{console.error(e);process.exitCode=1;});

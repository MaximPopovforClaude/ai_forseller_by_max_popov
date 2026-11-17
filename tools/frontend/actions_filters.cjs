// Actual MainApp query/props, useTabData, picker and board. Synthetic API only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
global.localStorage={getItem:()=>null,setItem(){}};
const articles=Array.from({length:110},(_,i)=>({nm_id:101+i,vendor_code:'DEMO-'+(101+i),subject:i<2?'Категория A':'Категория B'}));
const gets=[],tabs=[],modules=new Map();
const api={articles:async()=>articles,tab:async(shop,tab,q)=>{tabs.push({shop,tab,q});return{key:tab,custom:'actions',columns:[],rows:[]}}};
const http={get:async url=>{gets.push(url);if(url.includes('/manager/charts'))return{days:[],rows:{},note:''};
 if(!url.includes('/manager/board'))throw Error(url);
 return{days:['2026-11-15','2026-11-14'],month:'2026-11-01',mp:'wb',me:99,can_edit:true,kinds:[],rows:articles.map(a=>({...a,
  orders:{'2026-11-15':1},price_spp_days:{'2026-11-15':80},ads:{'2026-11-15':{all:10,ark:2,prk:8,search:7,rec:3,osum:100}},
  actions:{'2026-11-15':[{id:'d'+a.nm_id,kind:'auto:promo_day',auto:true,value:'В акции: Учебная'},
   {id:'e'+a.nm_id,kind:'auto:entry',auto:true,value:'Точка входа: Учебная'},
   {id:'t'+a.nm_id,kind:'auto:ad_status',auto:true,value:'Реклама',detected_at:'2026-11-15T09:15:00Z'}]}}))};}};
function compile(source,imports={}){const mod={exports:{}};new Function('require','module','exports',ts.transpileModule(source,
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)(n=>{
 if(n==='react')return React;if(n==='react/jsx-runtime')return require(path.join(deps,n));
 if(n==='./api')return{api,http};if(imports[n])return imports[n];return load(n.slice(2));
 },mod,mod.exports);return mod.exports;}
function load(name){if(modules.has(name))return modules.get(name);const ext=name==='useTabData'?'.ts':'.tsx';
 const result=compile(fs.readFileSync(path.join(base,'web/frontend/src',name+ext),'utf8'));modules.set(name,result);return result;}
const src=fs.readFileSync(path.join(base,'web/frontend/src/App.tsx'),'utf8');
const ast=ts.createSourceFile('App.tsx',src,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),expressions={};let queryCall;
function visit(n){if(ts.isJsxSelfClosingElement(n)&&['ArtPicker','ActionsBoard'].includes(n.tagName.getText(ast))){
 let e=n;while(e&&!ts.isJsxExpression(e))e=e.parent;expressions[n.tagName.getText(ast)]=e.getText(ast);}
 if(ts.isCallExpression(n)&&n.expression.getText(ast)==='useTabData')queryCall=n.getText(ast);ts.forEachChild(n,visit);}
visit(ast);assert.ok(queryCall);assert.equal(Object.keys(expressions).length,2);
const {Screen}=compile(`import {useState} from 'react';import {ArtPicker} from './ArtPicker';
 import {ActionsBoard} from './ActionsBoard';import {useTabData} from './useTabData';
 export function Screen({shop=7,staffOnly=null}){const [nm,setNm]=useState(''),from='2026-10-18',to='2026-11-16',reload=0,page='tab',tab='mgr_actions',
  demoMode=false,wsId=1,me={shops:[{id:7,title:'Test',workspace_id:1}]},tabQ={from,to,nm,staff:staffOnly?9:null};
 const {data,loading}=${queryCall};return <>${expressions.ArtPicker}${expressions.ActionsBoard}</>;}`);
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const original=console.error;console.error=(...a)=>{warnings.push(a.join(' '));original(...a)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],nodes=()=>walk(box),props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const tick=()=>new Promise(r=>setTimeout(r,25));async function act(fn){flushSync(fn);await tick();await tick();}
const button=t=>nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===t);
const body=()=>nodes().find(n=>n.tagName==='TBODY'),visible=()=>walk(body()).filter(n=>n.tagName==='B'&&n.textContent.startsWith('DEMO-')).map(n=>n.textContent);
async function select(value){await act(()=>props(nodes().find(n=>props(n).className==='nm')).onChange({target:{value}}))}
async function click(n){assert.ok(n);await act(()=>props(n).onClick())}
async function render(staffOnly=null){await act(()=>root.render(h(Screen,{staffOnly})));await tick();}
(async()=>{try{
 await render();assert.equal(tabs.length,1);assert.equal(gets.filter(x=>x.includes('/manager/board')).length,1);
 assert.equal(visible().length,50,'large catalogs have bounded mounted rows');assert.equal(visible()[0],'DEMO-101');
 assert.ok(!box.textContent.includes('Итог дня'));assert.ok(!box.textContent.includes('без времени события'));
 for(const chip of nodes().filter(n=>props(n).className==='chip auto'&&/Учебная/.test(n.textContent))){
  assert.equal(walk(chip).filter(n=>props(n).className==='action-time').length,0,'daily totals have no empty timestamp badge');
  assert.ok(!props(chip).title.includes('Итог дня'));}
 assert.ok(box.textContent.includes('Замечено: 12:15 МСК'),'actual event time preserved');
 const count=gets.length;
 const header=nodes().find(n=>n.tagName==='THEAD'),pickAll=walk(header).find(n=>n.tagName==='INPUT');
 await act(()=>props(pickAll).onChange());assert.ok(button('+ Действие для выбранных (110)'),'selection covers every filtered page');
 const search=()=>nodes().find(n=>props(n).className==='q');
 await act(()=>props(search()).onChange({target:{value:'DEMO-102'}}));assert.ok(button('+ Действие для выбранных (1)'));
 await act(()=>props(search()).onChange({target:{value:'absent'}}));assert.ok(!nodes().some(n=>n.tagName==='BUTTON'&&n.textContent.startsWith('+ Действие')));
 await act(()=>props(search()).onChange({target:{value:''}}));
 await click(button('Следующие'));assert.equal(visible()[0],'DEMO-151');assert.equal(visible().length,50);
 await click(button('Следующие'));assert.equal(visible().length,10);assert.equal(gets.length,count);
 await select('180');assert.deepEqual(visible(),['DEMO-180'],'selection outside old page resets the page');
 await select('101,103');assert.deepEqual(visible(),['DEMO-101','DEMO-103']);
 await select('');
 await click(nodes().find(n=>props(n).className==='ap-btn'));
 await click(nodes().find(n=>n.tagName==='BUTTON'&&n.textContent.startsWith('Категория A')));assert.deepEqual(visible(),['DEMO-101','DEMO-102']);
 await select('');await render(new Set([102,103]));assert.deepEqual(visible(),['DEMO-102','DEMO-103']);
 await select('101,103');assert.deepEqual(visible(),['DEMO-103']);
 await render(new Set());assert.deepEqual(visible(),[]);await render();
 await select('invalid');assert.deepEqual(visible(),[]);await select('');assert.equal(visible().length,50);
 assert.equal(tabs.length,1,'MainApp does not reopen the custom tab on item/staff filters');
 assert.equal(gets.length,count,'all selection and pagination changes reuse prepared board/charts');
 assert.deepEqual(warnings,[]);console.log('Actions actual MainApp: local filters, manager/category intersection, no refetch/remount, bounded rows and daily labels OK');
 }finally{flushSync(()=>root.unmount());console.error=original;}
})().catch(e=>{console.error(e);process.exitCode=1});

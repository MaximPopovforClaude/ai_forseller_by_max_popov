const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom'));
const ts=require(path.join(deps,'typescript')),writes=[],applied=[];let rejectSave=false,store={items:[],revision:null},late=null;
let reads=0;const http={get:async()=>{reads++;return late?late():structuredClone(store);},put:async(url,body)=>{
 writes.push({url,body:structuredClone(body)});store={...body.value,revision:'v'+writes.length};return structuredClone(store);
}};
const mod={exports:{}};new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/LayoutEditor.tsx'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)
 (n=>n==='./api'?{http}:require(path.join(deps,n)),mod,mod.exports);
const data={key:'svodwb',metrics:['Сумма налога','Кол-во выкупов','разница'],periods:['вчера','текущая неделя','предыдущая неделя'],
 col_layout:[['A','Сумма налога','вчера'],['B','Кол-во выкупов','предыдущая неделя'],['','разница','']],
 col_hidden:[['H','Сумма налога','вчера',2]]};
const host=document.body.appendChild(document.createElement('div')),root=createRoot(host),walk=n=>[n,...n.childNodes.flatMap(walk)];
const nodes=()=>walk(host),p=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
const button=t=>{const n=nodes().find(n=>n.tagName==='BUTTON'&&(n.textContent===t||n.textContent.includes(t)));assert.ok(n,t);return n;};
const input=t=>{const n=nodes().find(n=>p(n)['aria-label']===t);assert.ok(n,t);return n;};
const click=async t=>{flushSync(()=>p(button(t)).onClick());await tick();};
const change=async(t,value)=>{flushSync(()=>p(input(t)).onChange({target:{value}}));await tick();};
const render=(shop,presetsEnabled=true)=>flushSync(()=>root.render(React.createElement(mod.exports.LayoutEditor,{key:shop,shop,data,presetsEnabled,onSave:async v=>{
 if(rejectSave)throw Error('Сохранение не удалось');applied.push(structuredClone(v));
}})));
(async()=>{try{
 render(7);await tick();await click('Колонки и периоды');
 await change('Период для всех колонок','текущая неделя');await click('Выбрать для всех');
 const metricPeriods=nodes().filter(n=>n.tagName==='SELECT'&&!p(n)['aria-label']).map(n=>p(n).value).filter(v=>data.periods.includes(v));
 assert.deepEqual(metricPeriods,['текущая неделя','текущая неделя']);
 await change('Название пресета','Моя неделя');await click('Сохранить пресет');
 assert.equal(writes.length,1);assert.equal(applied.length,0,'saving a preset does not silently change the displayed report');
 assert.equal(writes[0].url,'/api/shops/7/prefs/svodwb_presets');
 const saved=store.items[0];assert.equal(saved.cols[2][2],'');assert.equal(saved.hidden[0][2],'текущая неделя');assert.equal(saved.hidden[0][3],2);
 // A fresh editor reloads persisted presets; applying one updates the real table preference.
 render(8);await tick();render(7);await tick();await click('Колонки и периоды');
 await change('Пресет периодов','Моя неделя');await click('Применить пресет');
 assert.deepEqual(applied[0],{cols:saved.cols,hidden:saved.hidden});
 await click('Колонки и периоды');rejectSave=true;await click('Сохранить');
 assert.ok(host.textContent.includes('Сохранение не удалось'));assert.ok(nodes().some(n=>p(n).className==='layout-list layout-settings'),'failed save keeps editor open');
 rejectSave=false;await click('Сбросить к стандартным');assert.equal(applied.at(-1),null);assert.equal(store.items.length,1);
 // A late read for the old shop must not expose its presets in the new editor.
 let resolve;late=()=>new Promise(r=>{resolve=r});await click('Колонки и периоды');
 render(9);await tick();resolve({items:[{...saved,name:'OLD-SHOP'}],revision:'old'});await tick();
 assert.ok(!host.textContent.includes('OLD-SHOP'));
 const before=reads;render(10,false);await tick();await click('Колонки и периоды');
 assert.equal(reads,before);assert.ok(!host.textContent.includes('Мои пресеты'),'demo does not request working account preferences');
 console.log('Summary presets: bulk/hidden/difference, server persistence, apply/reset, failed-save and late-scope isolation OK');
}finally{flushSync(()=>root.unmount());}})().catch(e=>{console.error(e);process.exitCode=1;});

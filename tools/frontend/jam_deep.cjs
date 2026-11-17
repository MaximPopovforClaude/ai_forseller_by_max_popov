// Real React, synthetic read-only API. No browser session or live network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),
 {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
const storage=new Map();global.localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
const calls=[];let block=false,resolveOld,fail=false,extraDay=false;
const http={get:async url=>{calls.push(url);if(block)return new Promise(r=>resolveOld=r);if(fail)throw Error('Ошибка загрузки');return {rows:[
 {day:'2026-11-14',state:'observed',pos:12.5,clicks:100,carts:20,orders:5,freq:1000},
 {day:'2026-11-13',state:'outside_top'},{day:'2026-11-12',state:extraDay?'observed':'missing_day',orders:extraDay?321:undefined}]};}};
const mod={exports:{}};const code=ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/JamDeep.tsx'),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',code)(name=>{if(name==='react')return React;if(name==='react/jsx-runtime')return require(path.join(deps,name));if(name==='./api')return {http};throw Error(name);},mod,mod.exports);
const {JamDeep,JamLoading}=mod.exports,box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const old=console.error;console.error=(...a)=>{warnings.push(a.join(' '));old(...a)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],nodes=()=>walk(box),props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const tick=()=>new Promise(r=>setTimeout(r,20)),settle=async()=>{await tick();await tick()};
const render=async(Component,p)=>{flushSync(()=>root.render(h(Component,p)));await settle()};
const click=async(text)=>{const n=nodes().find(n=>n.tagName==='BUTTON'&&n.textContent===text);assert.ok(n,text);flushSync(()=>props(n).onClick());await settle()};
const cols=[['query','Запрос','text'],['pos','Последняя позиция','num'],['last_day','Дата позиции','date'],['clicks','Клики','int']].map(([field,title,type])=>({field,title,type}));
const metrics=[['pos','Средняя позиция','num'],['clicks','Клики общие','int'],['carts','Корзин, шт','int'],['orders','Заказали, шт','int'],['freq','Частота за период','int']].map(([field,title,type])=>({field,title,type}));
const data={key:'jam_deep',columns:cols,total_row:{pos:8,clicks:777},rules:{pos:[{gt:null,le:30,color:'#57bb8a'}]},rows:[{query:'свеча',pos:12.5,last_day:'2026-11-14',clicks:100}],jam_deep:{nm_id:10,from:'2026-11-12',to:'2026-11-14',days:['2026-11-12','2026-11-13','2026-11-14'],missing_days:['2026-11-12'],loaded_days:2,expected_days:3,metrics}};
(async()=>{try{
 await render(JamLoading,{text:'Загружаю новый период; пока предыдущий'});assert.ok(nodes().some(n=>props(n).role==='status'));assert.ok(box.textContent.includes('пока предыдущий'));
 await render(JamLoading,{});assert.equal(box.textContent,'');
 await render(JamDeep,{key:'3:10:period1',shop:3,data});assert.equal(calls.length,0);assert.ok(box.textContent.includes('Дневная история: 2 из 3 дней'));
 assert.equal(nodes().filter(n=>n.tagName==='INPUT'&&props(n).checked).length,4);assert.ok(nodes().some(n=>props(n).style?.backgroundColor==='#57bb8a'));await click('Клики');assert.ok(nodes().some(n=>props(n)['aria-sort']==='descending'));await click('Клики ▾');assert.ok(nodes().some(n=>props(n)['aria-sort']==='ascending'));
 await click('▸ свеча');assert.equal(calls.length,1);assert.ok(calls[0].includes('nm_id=10'));assert.equal(new URL(calls[0],'https://example.test').searchParams.get('query'),'свеча');assert.ok(box.textContent.includes('ИТОГО по отчёту'));assert.ok(box.textContent.includes('777'));assert.ok(box.textContent.includes('Нет в топе WB'));assert.ok(box.textContent.includes('День не загружен'));
 const checkbox=nodes().find(n=>n.tagName==='LABEL'&&n.textContent===' Частота за день').childNodes.find(n=>n.tagName==='INPUT');
 flushSync(()=>props(checkbox).onChange());await settle();assert.equal(calls.length,1);assert.ok(storage.get('jam_deep_metrics').includes('freq'));
 const daily=nodes().find(n=>props(n).className==='jam-daily-table');assert.ok(daily.textContent.includes('Частота за день'));assert.ok(daily.textContent.includes('1 000'));
 await click('▾ свеча');assert.ok(!nodes().some(n=>props(n).className==='jam-daily-table'));
 fail=true;await click('▸ свеча');assert.ok(box.textContent.includes('Ошибка загрузки'));fail=false;await click('Повторить');assert.ok(box.textContent.includes('Нет в топе WB'));
 await click('▾ свеча');block=true;await click('▸ свеча');assert.ok(box.textContent.includes('Открываю сохранённые'));
 await render(JamDeep,{key:'4:20:period2',shop:4,data:{...data,jam_deep:{...data.jam_deep,nm_id:20},rows:[{query_id:2,query:'сироп',last_day:'2026-11-14'}]}});
 resolveOld({rows:[{day:'2026-11-14',state:'observed',pos:999999}]});await settle();assert.ok(!box.textContent.includes('999'));assert.ok(!box.textContent.includes('свеча'));assert.ok(box.textContent.includes('сироп'));
 assert.equal(nodes().filter(n=>n.tagName==='INPUT'&&props(n).checked).length,5);
 block=false;await click('▸ сироп');assert.ok(calls.at(-1).includes('/shops/4/jam/query-days?nm_id=20'));
 // The real 23-column ordinary report, including fields absent from the old daily summary.
 const ordinaryCols=[['query','Поисковый запрос','text'],['freq','Частота за период','int'],['cover','Охват','share'],['pos','Средняя позиция','num'],['views','Показы','int'],['clicks','Клики общие','int'],['cr_cart','Конверсия в корзину','share'],['carts','Корзины','int'],['cr_order','Конверсия в заказ','share'],['orders','Заказали, шт','int'],['cr_card','Конверсия карточки','share'],['ad_views','Показы РК','int'],['ad_clicks','Клики РК','int'],['ctr','CTR','share'],['cpc','CPC','money'],['spend','Затраты РК','money'],['cart_cost','Цена корзины','money'],['order_cost','Цена заказа','money'],['ad_share','Доля РК','share'],['profit','Прибыль с ДРР','money'],['pot_clicks','Потенциал кликов','int'],['pot_orders','Потенциал заказов','num'],['pot_profit','Потенциал прибыли','money']].map(([field,title,type])=>({field,title,type}));
 const full={...data,columns:ordinaryCols,total_row:{orders:99,profit:10000},rows:[{query:'отчёт & ключ',orders:77,profit:7500},{query:'ещё запрос',orders:22,profit:2500}],jam_deep:{...data.jam_deep,period_from:'2026-11-01',period_to:'2026-11-14'}};
 const before=calls.length;await render(JamDeep,{key:'full',shop:3,data:full});assert.equal(calls.length,before);
 const summary=nodes().find(n=>props(n).className==='jam-summary');const header=walk(summary).find(n=>n.tagName==='THEAD');
 assert.equal(walk(header).filter(n=>n.tagName==='TH').length,23);assert.ok(box.textContent.includes('Отчёт за 01.11.2026–14.11.2026'));
 assert.ok(summary.textContent.includes('7 500 ₽'));assert.ok(summary.textContent.includes('10 000 ₽'));
 const search=nodes().find(n=>props(n)['aria-label']==='Найти запрос');flushSync(()=>props(search).onChange({target:{value:'отчёт &'}}));await settle();
 assert.ok(!summary.textContent.includes('ещё запрос'));assert.ok(summary.textContent.includes('10 000 ₽')); // total belongs to whole report
 await click('▸ отчёт & ключ');assert.equal(new URL(calls.at(-1),'https://example.test').searchParams.get('query'),'отчёт & ключ');
 // Same open query stays expanded while a newly saved day triggers a fresh read.
 const beforeUpdate=calls.length;extraDay=true;
 await render(JamDeep,{key:'full',shop:3,data:{...full,jam_deep:{...full.jam_deep,daily_revision:'v2',loaded_days:3,missing_days:[]}}});
 assert.equal(calls.length,beforeUpdate+1);assert.ok(box.textContent.includes('▾ отчёт & ключ'));
 assert.ok(nodes().find(n=>props(n).className==='jam-daily-table').textContent.includes('321'));
 assert.ok(!box.textContent.includes('День не загружен'));
 fail=true;await render(JamDeep,{key:'full',shop:3,data:{...full,jam_deep:{...full.jam_deep,daily_revision:'v3'}}});
 assert.ok(box.textContent.includes('Ошибка загрузки'));assert.ok(nodes().find(n=>props(n).className==='jam-daily-table').textContent.includes('321'));
 fail=false;
 await render(JamDeep,{key:'preview',shop:3,data:{...full,total_row:undefined,jam_deep:{...full.jam_deep,summary_source:'daily_preview'}}});
 assert.ok(box.textContent.includes('только к доступным наблюдениям'));assert.ok(!box.textContent.includes('ИТОГО по отчёту'));
 await click('▸ отчёт & ключ');assert.ok(nodes().some(n=>props(n).className==='jam-daily-table'));
 const previewCalls=calls.length;
 await render(JamDeep,{key:'preview',shop:3,data:{...full,jam_deep:{...full.jam_deep,summary_source:'period'}}});
 assert.ok(box.textContent.includes('▾ отчёт & ключ'));assert.ok(box.textContent.includes('ИТОГО по отчёту'));
 assert.equal(calls.length,previewCalls); // period availability alone does not reload the same days
 assert.deepEqual(warnings,[]);console.log('Jam DOM: ordinary 23 columns/totals, sorting/filter, lazy daily expansion, defaults/preferences, gaps, retry and old response isolation passed');
 }finally{flushSync(()=>root.unmount());console.error=old;}})().catch(e=>{console.error(e);process.exitCode=1});

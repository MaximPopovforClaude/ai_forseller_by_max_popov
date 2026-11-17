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
const modules=new Map(),calls=[],writes=[];let blockShop7=false,resolveOld,extraRows=false;
const board=(shop,url='')=>({days:['2026-11-13','2026-11-12'],month:'2026-11-01',mp:shop===9?'ozon':'wb',me:99,can_edit:true,kinds:[],rows:[{
 nm_id:shop*10,vendor_code:'SHOP-'+shop,title:'Synthetic',orders:{'2026-11-13':12,'2026-11-12':10},actions:{'2026-11-13':[
 {id:'k1',kind:'auto:ad_kw_bid',auto:true,value:'Ключ «свеча», РК 42: ставка 200 ₽ → 250 ₽'},
 {id:'k2',kind:'auto:ad_kw_minus',auto:true,value:'Ключ «набор»: добавлен в минус-фразы'},
 {id:'k3',kind:'auto:ad_kw_status',auto:true,value:'Ключ «сироп»: активен → исключён'},
 {id:'a1',kind:'auto:ad_command',auto:true,value:'WB принял команду «Остановить кампанию»',detected_at:'2026-11-13T10:25:00Z'},
 {id:'a2',kind:'auto:ad_setting',auto:true,value:'РК 42: Поиск: да → нет'},
 {id:'a3',kind:'auto:ad_budget',auto:true,value:'РК 42: Остаток бюджета: 5 000 ₽ → 4 000 ₽'},
 {id:'a4',kind:'auto:ad_product',auto:true,value:'РК 42: товар добавлен'},
 {id:'a5',kind:'auto:ad_limit',auto:true,value:'РК 42: дневной лимит 1 000 ₽ → 2 000 ₽'},
 {id:'a6',kind:'auto:ad_config',auto:true,value:'Настройка блока рекламы: изменена'},
 {id:'base1',kind:'auto:ad_status',auto:true,value:'РК 42: работает → пауза',detected_at:'2026-11-12T21:30:00Z',wb_updated_at:'2026-11-12T20:20:00Z'},
 {id:'base2',kind:'auto:ad_bid',auto:true,value:'Ставка РК 42: 300 → 350 ₽'},
 {id:123,kind:'other',value:'Ручная пометка',who:'Тест',user_id:99,created_at:'2026-11-14T08:15:00Z'}]},
 ...(url.includes('ad_metrics=true')?{ad_metrics:{'2026-11-13':Object.fromEntries(['all','cpm','cpc','search','prk'].map(key=>[key,
   {campaigns:2,spent:25,budget:900,daily_limit:1000,campaign_spent:100,usage_limit:.1,usage_balance:.1,bids:{cpm:100,cpc:5},partial:['budget'],observed_at:['2026-11-13T12:00:00Z']}]))}}:{}),
 ...(url.includes('prices=true')?{price_spp_days:{'2026-11-13':864.49,'2026-11-12':null}}:{}),
 ...(url.includes('ads=true')?{ads:{'2026-11-13':{all:100,ark:100,prk:0,search:100,rec:0,osum:1000}}}:{}),
 stock_wb:25,stock_fbs:3,stock:28,price:1000,price_spp:800,margin_pct:.2,rating:4.8,orders_avg:11,stock_days:2.5,spp:.2,plan:50,drr_orders:.1,drr_buyouts:.15,conv_cart:.1,conv_order:.2}]});
const list={mine:[{id:5,nm_ids:[],photos:{},brands:{},period_from:'2026-11-01',period_to:'2026-11-10'}],team:[],saved:[],subs:[],seen:[],quota:{shared:0,allowed:0,used:0,left:0},client:true};
const http={get:async url=>{calls.push(url);
 if(url.includes('/manager/board')){const shop=Number(url.split('/')[3]);if(blockShop7&&shop===7)return new Promise(r=>resolveOld=r);
  const b=board(shop,url);if(extraRows)b.rows.push({...b.rows[0],nm_id:shop*10+1,vendor_code:'DEEP-ONLY',
   actions:{'2026-11-13':[{id:'deep',kind:'auto:ad_kw_bid',auto:true,value:'Скрытый ключ'}]}});return b}
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
  if(name==='./ActionSparks')return load('ActionSparks');if(name==='./ActionDayCell')return load('ActionDayCell');throw Error(name);
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
 assert.equal(nodes().filter(n=>props(n).className==='chip auto').length,2,'deep hidden; regular status/bid visible');
 assert.ok(box.textContent.includes('Ручная пометка'),'manual actions visible');
 assert.ok(box.textContent.includes('Замечено: 00:30 МСК'),'MSK day boundary');
 assert.ok(box.textContent.includes('Карточка обновлена МП: 12.11.2026 23:20 МСК'));
 assert.ok(box.textContent.includes('Записано: 14.11.2026 11:15 МСК'),'backdated action does not claim wrong occurrence date');
 assert.ok(!calls.some(x=>x.includes('ad_metrics=true')),'advertising metrics are opt-in');
 assert.equal(nodes().filter(n=>props(n).className==='hint action-day-price').length,0,'daily prices opt-in');
 const boardCalls=calls.length;
 await click(button('Показать глубокие изменения РК'));
 assert.equal(store.get('act_deep_ads'),'1');assert.equal(calls.length,boardCalls,'display toggle needs no new request');
 const keywords=nodes().filter(n=>props(n).className==='chip auto');assert.equal(keywords.length,11);
 assert.ok(keywords.some(n=>n.textContent.includes('ставка 200 ₽ → 250 ₽')));
 assert.ok(keywords.every(n=>props(n).style.borderColor==='#ca8a04'));
 assert.ok(keywords.filter(n=>!n.textContent.includes('WB принял')&&!n.textContent.includes('Настройка блока')).every(n=>props(n).title.startsWith('Заметили сами (API):')));
 assert.ok(props(keywords.find(n=>n.textContent.includes('Настройка блока'))).title.startsWith('Настройка платформы:'));
 assert.ok(props(keywords.find(n=>n.textContent.includes('WB принял'))).title.startsWith('WB принял команду через платформу:'));
 assert.ok(box.textContent.includes('Принято WB: 13:25 МСК'));
 let fields=nodes().filter(n=>props(n).className==='action-key-item');assert.equal(fields.length,15);
 assert.equal(fields[0].textContent,'Ост. WB25');assert.ok(fields[14].textContent.includes('Конв. зак.'));
 assert.equal(calls.filter(x=>x.includes('/manager/charts')).length,1,'chart data loaded once independently of display');
 const displayCalls=calls.length;
 await change(check('графики за 30 дней'),{checked:true});
 assert.equal(calls.length,displayCalls,'showing charts only uses the prepared response');
 assert.equal(store.get('act_charts'),'1');assert.equal(nodes().filter(n=>props(n).role==='img').length,5);
 assert.equal(nodes().find(n=>n.tagName==='THEAD').textContent,'АртикулКлючевые данныеГрафики · 30 дней13.11пт12.11чт');
 await click(button('План продаж на ноябрь, шт'));
 const input=nodes().find(n=>props(n)['aria-label']==='План SHOP-7');assert.ok(input);
 flushSync(()=>props(input).onBlur({target:{value:'60'}}));await settle();
 assert.deepEqual(writes,[['/api/shops/7/nm_plan',{nm_id:70,month:'2026-11-01',qty:60}]]);
 await change(check('ключевые данные'),{checked:false});assert.equal(nodes().filter(n=>props(n).className==='action-key-item').length,0);
 assert.equal(nodes().filter(n=>props(n).role==='img').length,5,'independent chart visibility');
 await change(check('графики за 30 дней'),{checked:false});assert.equal(nodes().filter(n=>props(n).role==='img').length,0);
 const optionCalls=calls.length;
 await change(check('цена с СПП по дням'),{checked:true});assert.equal(store.get('act_day_prices'),'1');
 assert.deepEqual(nodes().filter(n=>props(n).className==='hint action-day-price').map(n=>n.textContent),['Цена с СПП: 864 ₽','Цена с СПП: —']);
 assert.equal(calls.length,optionCalls,'price visibility never reloads the board');
 await change(check('общий'),{checked:true});assert.equal(store.get('act_drr'),'all');
 assert.equal(calls.length,optionCalls,'first DRR checkbox also uses existing data');assert.ok(box.textContent.includes('ДРР 10%'));
 for(const label of ['АРК','ПРК','поиск','рекомендации']) {
   await change(check(label),{checked:true}); await change(check(label),{checked:false});
 }
 await change(check('общий'),{checked:false});await change(check('общий'),{checked:true});
 assert.equal(calls.length,optionCalls,'all DRR combinations are local');
 await change(check('цена с СПП по дням'),{checked:false});assert.ok(box.textContent.includes('ДРР 10%'),'DRR independent');
 assert.equal(nodes().filter(n=>props(n).className==='hint action-day-price').length,0);
 await click(button('Показать статистику РК'));assert.equal(store.get('act_ad_stats'),'1');
 assert.ok(calls.at(-1).includes('ad_metrics=true'));assert.ok(box.textContent.includes('900* / 25 / 1 000 / 10% / 100 / 5'));
 assert.ok(nodes().some(n=>props(n).title==='Средняя ставка CPM: 100 ₽/1000 показов'));assert.ok(nodes().some(n=>props(n).title==='Средняя ставка CPC: 5 ₽/клик'));
 const metricsCalls=calls.length;
 await change(check('CPM'),{checked:true});await change(check('CPC'),{checked:true});
 assert.equal(calls.length,metricsCalls,'group visibility uses same response');
 assert.equal(nodes().filter(n=>props(n).className==='action-ad-group').length,6,'three groups × two days including missing day');
 const basis=nodes().find(n=>n.tagName==='SELECT'&&props(n).value==='limit');
 await change(basis,{value:'balance'});assert.equal(store.get('act_ad_basis'),'balance');
 assert.equal(calls.length,metricsCalls);
 await click(button('Скрыть статистику РК'));assert.equal(nodes().filter(n=>props(n).className==='action-ad-group').length,0);
 await click(button('Показать статистику РК'));
 assert.equal(calls.length,metricsCalls,'hide/show detailed metrics retains the response');
 await click(button('Скрыть статистику РК'));
 await change(check('ключевые данные'),{checked:true});
 await click(button('План продаж на ноябрь, шт'));
 const freshPlan=nodes().find(n=>props(n)['aria-label']==='План SHOP-7');
 flushSync(()=>props(freshPlan).onBlur({target:{value:'65'}}));await settle();
 const afterEdit=calls.length;
 await click(button('Показать статистику РК'));
 assert.equal(calls.length,afterEdit+1,'manual edit invalidates prior detailed response; it is loaded again once');
 assert.ok(box.textContent.includes('900* / 25 / 1 000 / 10% / 100 / 5'));
 await click(button('Скрыть глубокие изменения РК'));assert.equal(nodes().filter(n=>props(n).className==='chip auto').length,2);
 const day=nodes().find(n=>n.tagName==='TD'&&props(n).className==='day click');await click(day);
 assert.ok(!box.textContent.includes('Ключ «свеча»'),'editor respects hidden deep changes');assert.ok(box.textContent.includes('Ручная пометка'));
 flushSync(()=>root.render(null));extraRows=true;await render(ActionsBoard,{shop:7,shops:[{id:7,title:'One'}]});
 assert.ok(button('Показать глубокие изменения РК'),'hidden preference survives remount');
 assert.ok(box.textContent.includes('DEEP-ONLY'));await change(check('только с действиями'),{checked:true});
 assert.ok(!box.textContent.includes('DEEP-ONLY'),'filter considers only visible changes');
 await click(button('Показать глубокие изменения РК'));assert.ok(box.textContent.includes('DEEP-ONLY'));
 await change(check('цена с СПП по дням'),{checked:true});extraRows=false;
 flushSync(()=>root.render(null));blockShop7=true;
 await render(ActionsBoard,{shop:7,shops:[{id:7,title:'One'}]});assert.ok(resolveOld);
 await render(ActionsBoard,{shop:8,shops:[{id:8,title:'Two'}]});assert.ok(box.textContent.includes('SHOP-8'));
 assert.ok(button('Скрыть глубокие изменения РК'),'enabled preference survives remount');
 assert.ok(props(check('цена с СПП по дням')).checked,'daily price preference survives remount');
 assert.ok(button('Скрыть статистику РК'),'advertising preference survives shop change');
 resolveOld(board(7));await settle();assert.ok(!box.textContent.includes('SHOP-7'),'late old-shop response ignored');
 assert.equal(nodes().filter(n=>props(n).className==='hint action-day-price').length,2);
 await render(ActionsBoard,{shop:9,shops:[{id:9,title:'Ozon'}]});
 assert.equal(nodes().filter(n=>props(n).className==='hint action-day-price').length,0,'WB price is not claimed for Ozon');
 assert.ok(!box.textContent.includes('цена с СПП по дням'));
 assert.equal(nodes().filter(n=>props(n).className==='action-ad-group').length,0,'WB statistics not claimed for Ozon');
 assert.ok(!button('Скрыть статистику РК'));
 await render(ComparePage,{embedded:true});
 assert.ok(nodes().some(n=>props(n).className==='cmp-embedded'));assert.ok(!nodes().some(n=>props(n).className==='cmp-wrap'));
 assert.ok(!box.textContent.includes('logo'),'embedded comparison has no duplicate site header');
 await click(nodes().find(n=>props(n).className==='cmp-item'));assert.equal(window.location.pathname,'/compare/5');
 assert.ok(box.textContent.includes('Не найден тестовый отчёт'));await click(button('← к списку'));
 assert.equal(window.location.pathname,'/compare');assert.ok(box.textContent.includes('Сравнение карточек'));
 assert.deepEqual(warnings,[]);console.log('Actions: 3×5, optional charts, plan editing, shop race; embedded comparison and report navigation OK');
 }finally{flushSync(()=>root.unmount());console.error=old;}})().catch(e=>{console.error(e);process.exitCode=1});

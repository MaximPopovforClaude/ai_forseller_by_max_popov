// Real Promo component, controlled HTTP and synthetic files. Never contacts WB.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document,TestNode}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript')),h=React.createElement;
global.localStorage={getItem:()=>null,setItem(){}};
let picks=0;TestNode.prototype.click=function(){picks++};
const gets=[],posts=[],http={get:url=>new Promise((resolve,reject)=>gets.push({url,resolve,reject}))};
global.fetch=(url,options)=>new Promise((resolve,reject)=>posts.push({url,options,resolve,reject}));
const mod={exports:{}};
new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/Promo.tsx'),'utf8'),
 {compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)(n=>{
 if(n==='react')return React;if(n==='react/jsx-runtime')return require(path.join(deps,n));if(n==='./api')return{http};throw Error(n);
},mod,mod.exports);
const {Promo}=mod.exports,box=document.body.appendChild(document.createElement('main')),root=createRoot(box),warnings=[];
const error=console.error;console.error=(...a)=>{warnings.push(a.join(' '));error(...a)};
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const nodes=()=>walk(box),tick=()=>new Promise(r=>setTimeout(r,20));
const input=()=>nodes().find(n=>props(n)['aria-label']==='Название акции');
const file=()=>nodes().find(n=>props(n).type==='file');
const add=()=>nodes().find(n=>n.tagName==='BUTTON'&&(/Добавить акцию|Загружаю/.test(n.textContent)));
const data=(name='',can_edit=true)=>({rows:[],promos:name?[{key:'up:8',name,source:'file',eligible:1}]:[],can_edit});
const reply=(value,status=200)=>new Response(JSON.stringify(value),{status});
async function act(fn){flushSync(fn);await tick();await tick()}
async function render(shop){await act(()=>root.render(h(Promo,{shop})))}
async function title(value){await act(()=>props(input()).onChange({target:{value}}))}
async function choose(f={name:'offer.xlsx',size:42}){const target={files:[f],value:'offer.xlsx'};await act(()=>props(file()).onChange({target}));assert.equal(target.value,'')}
(async()=>{try{
 await render(7);await act(()=>gets.at(-1).resolve(data()));
 assert.equal(props(add()).disabled,false,'empty title must explain itself instead of a silent disabled button');
 await act(()=>props(add()).onClick());assert.equal(document.activeElement,input());assert.equal(picks,0);
 assert.ok(box.textContent.includes('Сначала введите название'));assert.ok(box.textContent.includes('1. Укажите название'));
 await title(' Акция ');await act(()=>props(add()).onClick());assert.equal(picks,1);
 await choose({name:'offer.xls',size:42});assert.equal(posts.length,0);assert.ok(box.textContent.includes('.xlsx'));
 await choose({name:'offer.xlsx',size:0});assert.equal(posts.length,0);assert.ok(box.textContent.includes('пустой файл'));
 await choose();assert.equal(posts.length,1);assert.equal(props(add()).disabled,true);assert.equal(props(input()).disabled,true);
 assert.ok(posts[0].url.includes('/shops/7/promo/upload'));assert.ok(posts[0].url.endsWith('title='+encodeURIComponent('Акция')));
 await act(()=>posts[0].resolve(reply({ok:true,id:8,items:1})));assert.equal(gets.length,2);
 await act(()=>gets[1].resolve(data('Акция')));assert.ok(box.textContent.includes('добавлена: 1 товаров'));assert.equal(props(input()).value,'');
 await title('Повтор');await choose();await act(()=>posts.at(-1).resolve(new Response('<html>large</html>',{status:413})));
 assert.ok(box.textContent.includes('слишком большой'));assert.equal(props(input()).value,'Повтор');assert.equal(props(add()).disabled,false);
 await choose();await act(()=>posts.at(-1).resolve(reply({detail:'Нужен XLSX списка товаров'},400)));
 assert.ok(box.textContent.includes('Нужен XLSX списка товаров'));
 await choose();await act(()=>posts.at(-1).resolve(new Response('<html>unknown</html>')));
 assert.ok(box.textContent.includes('не подтвердил результат'));assert.equal(gets.length,2,'unknown result is not automatically retried');
 await choose();await act(()=>posts.at(-1).reject(new TypeError('Failed to fetch')));
 assert.ok(box.textContent.includes('Результат загрузки неизвестен'));assert.equal(posts.length,5);
 await choose();await act(()=>posts.at(-1).resolve(reply({ok:true,rows:0,message:'Учебный расчёт акции.'})));
 assert.ok(box.textContent.includes('Учебный расчёт'));assert.ok(!box.textContent.includes('undefined товаров'));
 // Completing a previous shop's POST cannot overwrite the new shop's form/data.
 await choose();const pending=posts.at(-1);await render(8);await act(()=>gets.at(-1).resolve(data('Магазин 8')));await title('Новая акция');
 const getCount=gets.length;await act(()=>pending.resolve(reply({ok:true,id:9,items:2})));
 assert.equal(props(input()).value,'Новая акция');assert.equal(gets.length,getCount);assert.ok(box.textContent.includes('Магазин 8'));
 // Late GETs and read-only viewers.
 await render(9);const late=gets.at(-1);await render(10);await act(()=>gets.at(-1).resolve(data('Магазин 10',false)));
 await act(()=>late.resolve(data('Старый магазин')));assert.ok(box.textContent.includes('Магазин 10'));assert.ok(!box.textContent.includes('Старый магазин'));
 assert.equal(add(),undefined);
 // API announcements are visible, without fabricating auto-promo products/prices.
 const withCalendar={...data(),auto_promos:[{key:'api:4',name:'Автоакция ноября',from:'2026-11-13T21:00:00Z',to:'2026-11-20T21:00:00Z'}],
  hidden_count:2,collection:{status:'error',last_ok_at:'2026-11-13T09:00:00Z',last_run_at:'2026-11-13T15:00:00Z',catalog_at:'2026-11-13T15:00:00Z',interval_minutes:360,future_days:30}};
 await render(11);await act(()=>gets.at(-1).resolve(withCalendar));
 assert.ok(box.textContent.includes('Автоакция ноября'));assert.ok(box.textContent.includes('14.11.2026'));
 assert.ok(box.textContent.includes('12:00'));assert.ok(box.textContent.includes('Последняя попытка завершилась ошибкой'));
 assert.ok(box.textContent.includes('Акций скрыто после'));assert.ok(box.textContent.includes('30 дней вперёд'));
 assert.equal(nodes().filter(n=>n.tagName==='INPUT'&&props(n).type==='checkbox').length,7,'no invented auto product checkboxes');
 await act(()=>props(nodes().find(n=>n.tagName==='BUTTON'&&n.textContent==='Подставить название')).onClick());
 assert.equal(props(input()).value,'Автоакция ноября');assert.equal(document.activeElement,input());
 const beforePosts=posts.length;
 await act(()=>props(nodes().find(n=>n.tagName==='BUTTON'&&n.textContent==='Обновить таблицу')).onClick());
 assert.equal(props(add()).disabled,true);assert.equal(posts.length,beforePosts,'refresh only reads stored data');
 await act(()=>gets.at(-1).resolve({...withCalendar,collection:{...withCalendar.collection,status:'stale'}}));
 assert.ok(box.textContent.includes('Данные старше интервала'));assert.equal(props(add()).disabled,false);
 await render(12);await act(()=>gets.at(-1).resolve({...withCalendar,can_edit:false,collection:{...withCalendar.collection,status:'disabled'}}));
 assert.ok(box.textContent.includes('для магазина выключен'));assert.equal(nodes().find(n=>n.tagName==='BUTTON'&&n.textContent==='Подставить название'),undefined);
 assert.deepEqual(warnings,[]);
 console.log('Promo: visible title validation, file selection, success, format/empty/HTTP/network errors, demo notice, shop races and viewer permissions OK');
}finally{flushSync(()=>root.unmount());console.error=error}})().catch(e=>{console.error(e);process.exitCode=1});

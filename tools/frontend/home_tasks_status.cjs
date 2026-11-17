// Actual HomeTasks, real React DOM; deferred API and polling, no generation.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document,window}=require('./test_dom.cjs');
const base=process.argv[2],deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const gets=[],posts=[],timers=new Map();let timerId=0;
window.setInterval=fn=>{timers.set(++timerId,fn);return timerId;};window.clearInterval=id=>timers.delete(id);
const http={get:url=>new Promise((resolve,reject)=>gets.push({url,resolve,reject})),
  post:(url,body)=>new Promise((resolve,reject)=>posts.push({url,body,resolve,reject}))};
const source=fs.readFileSync(path.join(base,'web/frontend/src/HomeTasks.tsx'),'utf8');
const mod={exports:{}},js=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',js)(name=>{
  if(name==='react')return React;
  if(name==='react/jsx-runtime')return require(path.join(deps,'react/jsx-runtime'));
  if(name==='./api')return {http};throw Error(name);
},mod,mod.exports);
const {HomeTasks}=mod.exports,box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const tick=()=>new Promise(r=>setTimeout(r,20));
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const button=text=>{const b=walk(box).find(n=>n.tagName==='BUTTON'&&n.textContent.includes(text));assert.ok(b,text);return b;};
const click=async text=>{flushSync(()=>props(button(text)).onClick());await tick();};
const task=(i,run=81)=>({id:i,run_id:run,day:'2026-11-05',title:`Task ${i}`,why:'Evidence',tag:'stock',certainty:'probable',
  nm_ids:[],status:'new',status_by:null,status_note:null,feedback:null,outcome:null});
const result=(status='ok',id=81)=>({enabled:true,today:'2026-11-05',can_edit:true,marketplace:'wb',entry_day:'2026-11-04',entry_present:true,
  runs:{'2026-11-05':{id,status,day:'2026-11-05',started_at:'2026-11-05T08:50:00Z',finished_at:status==='ok'?'2026-11-05T09:00:03Z':null,entry_ok:true,summary:'Fresh summary'}},
  tasks:Array.from({length:id===80?1:11},(_,i)=>task(i+1,id)),tags:{stock:'Остатки'},cert:{probable:'Вероятно'},status_t:{new:'Новая'}});
const respond=async data=>{gets.at(-1).resolve(data);await tick();};
const poll=async data=>{timers.values().next().value();await respond(data);};
(async()=>{
  flushSync(()=>root.render(React.createElement(HomeTasks,{shop:8})));await tick();await respond(result('ok',80));
  const rebuild=props(button('пересобрать')).onClick;
  flushSync(()=>{rebuild();rebuild();});await tick();assert.equal(posts.length,1,'Double click must not send two requests');
  posts.at(-1).resolve({message:'Поставил в очередь: разбор начнётся в течение 10 минут.',run_id:81,status:'requested',created:true});await tick();
  await respond({...result('requested'),tasks:[task(1,80)]});
  assert.ok(box.textContent.includes('Пока показаны задачи предыдущего разбора'));
  await poll({...result('running'),tasks:[task(1,80)]});
  await poll(result());
  assert.ok(!box.textContent.includes('Поставил в очередь'),'Queue acknowledgement must disappear after completion');
  assert.ok(box.textContent.includes('Разбор завершён'));assert.ok(box.textContent.includes('12:00'));assert.ok(box.textContent.includes('МСК'));
  assert.ok(box.textContent.includes('задач: 11'));
  // A later rejected request is not hidden by polling a previous successful run.
  await click('пересобрать');posts.at(-1).reject(new Error('Нет права на повтор'));await tick();await poll(result());
  assert.ok(box.textContent.includes('Нет права на повтор'));
  timers.values().next().value();gets.at(-1).reject(new Error('Нет связи'));await tick();
  assert.ok(box.textContent.includes('Не удалось обновить'));assert.ok(box.textContent.includes('Task 11'));
  await poll(result());assert.ok(!box.textContent.includes('Не удалось обновить'));
  flushSync(()=>root.unmount());assert.equal(timers.size,0);
  // An initial load failure must be visible and retryable instead of a blank block.
  const other=document.body.appendChild(document.createElement('main')),root2=createRoot(other);
  flushSync(()=>root2.render(React.createElement(HomeTasks,{shop:8})));await tick();
  gets.at(-1).reject(new Error('Нет связи'));await tick();assert.ok(other.textContent.includes('Не удалось загрузить'));
  const retry=walk(other).find(n=>n.tagName==='BUTTON'&&n.textContent.includes('Обновить задачи'));
  flushSync(()=>props(retry).onClick());await tick();await respond(result());
  assert.ok(other.textContent.includes('Task 11'));assert.ok(!other.textContent.includes('Не удалось загрузить'));
  flushSync(()=>root2.unmount());console.log('HomeTasks rebuild acknowledgement, completion, errors and retry: passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

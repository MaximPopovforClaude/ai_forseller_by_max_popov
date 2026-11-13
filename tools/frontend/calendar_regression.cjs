// Real React/DOM, actual Calendar.tsx, controlled API responses; no network.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const {document,window} = require('./test_dom.cjs');
const base=process.argv[2], deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react'));
const {createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom'));
const ts=require(path.join(deps,'typescript'));
const timers=new Set(), storage=new Map();
window.setInterval=fn=>{const id=setInterval(fn,60000);timers.add(id);return id;};
window.clearInterval=id=>{clearInterval(id);timers.delete(id);};
global.localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)};
global.crypto=require('node:crypto').webcrypto;
const entry=(id=1)=>({id,kind:'task',title:`Task ${id}`,description:'Details',day:'2026-11-05',shop_id:10,shop:'WB',assignee_id:2,
  assignee:'Editor',author:'Owner',status:'open',version:1,can_edit:true,reminder_state:null});
const result={items:[entry()],today:'2026-11-04',me:2,members:[{id:2,name:'Editor',shop_ids:[10]}],shops:[{id:10,title:'WB'}],
  can_add:true,stometric_connected:true,truncated:false,action_counts:[{day:'2026-11-04',n:1}]};
const calls=[], posts=[], pending=[];
let deferred=false, saveError=false;
const http={
  get(url){calls.push(url); const u=new URL(url,'https://example.test');
    if(deferred && url.includes('/1/calendar/due'))return new Promise(resolve=>pending.push(resolve));
    if(u.pathname.endsWith('/due'))return Promise.resolve({items:[entry(url.includes('/2/')?2:1)],today:result.today,truncated:false});
    if(u.pathname.endsWith('/actions'))return Promise.resolve({items:[{id:'a1',source:'manual',title:'Article action',description:'note',nm_id:123,shop:'WB',shop_id:10}],more:false});
    return Promise.resolve({...result,items:[entry(url.includes('/2/')?2:1)]});
  },
  post(url,body){posts.push({url,body});return saveError?Promise.reject(new Error('Конфликт версии')):Promise.resolve({id:9});},
  put(url,body){return this.post(url,body);}
};
const source=fs.readFileSync(path.join(base,'web/frontend/src/Calendar.tsx'),'utf8');
const out=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const mod={exports:{}};
new Function('require','module','exports',out)(name=>{
  if(name==='react')return React;
  if(name==='react/jsx-runtime')return require(path.join(deps,'react/jsx-runtime'));
  if(name==='./api')return {http};
  if(name.endsWith('.css'))return {};
  throw Error(name);
},mod,mod.exports);
const {Calendar,HomeCalendar,monthDays,mskDay}=mod.exports;
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const walk=(node)=>[node,...node.childNodes.flatMap(walk)];
const props=node=>node[Object.keys(node).find(k=>k.startsWith('__reactProps$'))]||{};
const find=(tag,text)=>{const n=walk(box).find(n=>n.tagName===tag.toUpperCase()&&n.textContent===text);assert.ok(n,`${tag}: ${text}`);return n;};
const tick=async()=>{await new Promise(r=>setTimeout(r,20));};
const change=async(node,event)=>{flushSync(()=>props(node).onChange({target:event}));await tick();};
const click=async text=>{flushSync(()=>props(find('button',text)).onClick());await tick();};
const render=async(element)=>{flushSync(()=>root.render(React.createElement(React.StrictMode,null,element)));await tick();};
const originalError=console.error,warnings=[];
console.error=(...x)=>warnings.push(x.join(' '));
(async()=>{
  try {
    const leap=monthDays('2028-02');
    assert.equal(leap.length,42);assert.ok(leap.includes('2028-02-29'));
    assert.equal(new Date(leap[0]+'T00:00:00Z').getUTCDay(),1);
    assert.match(mskDay(),/^\d{4}-\d{2}-\d{2}$/);
    const workspaces=[{id:1,name:'Team 1'},{id:2,name:'Team 2'}];
    await render(React.createElement(Calendar,{wsId:1,workspaces,initialDay:'2026-11-04'}));
    assert.ok(box.textContent.includes('Календарь'));
    assert.ok(box.textContent.includes('Task 1'));
    assert.ok(!calls.some(u=>u.includes('/actions?')),'No action fetch until shown');
    const actionToggle=walk(box).find(n=>n.tagName==='INPUT'&&n.parentNode.textContent.includes('Действия по артикулам'));
    await change(actionToggle,{checked:true});await tick();
    assert.ok(box.textContent.includes('Article action'));
    await change(walk(box).find(n=>n.tagName==='INPUT'&&n.parentNode.textContent.includes('Действия по артикулам')),{checked:false});
    assert.ok(!box.textContent.includes('Article action'));
    await click('+ Задача');
    await change(walk(box).find(n=>n.tagName==='INPUT'&&props(n).maxLength===200),{value:'Check stock'});
    saveError=true;
    const form=find('form',walk(box).find(n=>n.tagName==='FORM').textContent);
    await props(form).onSubmit({preventDefault(){}});await tick();
    assert.ok(box.textContent.includes('Конфликт версии'));
    assert.equal(posts[0].body.title,'Check stock');assert.equal(posts[0].body.assignee_id,2);
    assert.equal(posts[0].body.day,'2026-11-04');assert.match(posts[0].body.request_key,/^[a-f0-9-]{36}$/);
    saveError=false;
    await props(form).onSubmit({preventDefault(){}});await tick();
    assert.equal(posts[1].body.request_key,posts[0].body.request_key,'Retry uses same creation key');
    assert.ok(!box.textContent.includes('Добавить задачу'));
    // Switching account unmounts its editor/resource and clears its content.
    const ws=walk(box).find(n=>n.tagName==='SELECT'&&n.parentNode.textContent.startsWith('Аккаунт'));
    await change(ws,{value:'2'});
    assert.ok(box.textContent.includes('Task 2'));assert.ok(!box.textContent.includes('Task 1'));
    deferred=true;
    await render(React.createElement(HomeCalendar,{wsId:1,onOpen(){}}));
    assert.ok(!box.textContent.includes('Task 1'));
    await render(React.createElement(HomeCalendar,{wsId:2,onOpen(){}}));
    assert.ok(box.textContent.includes('Task 2'));
    pending.forEach(resolve=>resolve({items:[entry(1)],today:result.today}));await tick();
    assert.ok(box.textContent.includes('Task 2'));assert.ok(!box.textContent.includes('Task 1'),'Late account response ignored');
    flushSync(()=>root.unmount());await tick();assert.equal(timers.size,0,'All polling cleaned up');
    assert.ok(!warnings.some(w=>/same key|unique.*key|unmounted|error occurred/i.test(w)),warnings.join('\n'));
    console.log('Calendar React scenarios: passed');
  } finally { console.error=originalError;for(const id of timers)clearInterval(id); }
})().catch(error=>{console.error(error);process.exitCode=1;});

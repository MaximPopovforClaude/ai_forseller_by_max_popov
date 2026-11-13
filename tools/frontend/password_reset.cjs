// Real React DOM, synthetic API/clipboard, no browser session or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document,window}=require('./test_dom.cjs');
const base=process.argv[2],deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client'));
const {flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const posts=[],copies=[],history=[];
const http={post:(url,body)=>new Promise((resolve,reject)=>posts.push({url,body,resolve,reject}))};
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async s=>copies.push(s)}},configurable:true});
window.location={hash:'#'+'a'.repeat(43)};
window.history={replaceState:(a,b,url)=>history.push(url)};
const source=fs.readFileSync(path.join(base,'web/frontend/src/PasswordReset.tsx'),'utf8');
const js=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const mod={exports:{}};
new Function('require','module','exports',js)(name=>{
  if(name==='react')return React;
  if(name==='react/jsx-runtime')return require(path.join(deps,'react/jsx-runtime'));
  if(name==='./api')return {http};
  throw Error(name);
},mod,mod.exports);
const {PasswordResetControl:Control,PasswordResetPage:Page}=mod.exports;
const tick=()=>new Promise(r=>setTimeout(r,20));
const walk=n=>[n,...n.childNodes.flatMap(walk)],props=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const find=(box,tag,text)=>{const n=walk(box).find(n=>n.tagName===tag&&n.textContent.includes(text));assert.ok(n,tag+': '+text);return n;};
const click=async(box,text)=>{flushSync(()=>props(find(box,'BUTTON',text)).onClick());await tick();};
const mount=async(Component,data)=>{
  const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
  flushSync(()=>root.render(React.createElement(Component,data)));await tick();
  return {box,root,unmount:()=>flushSync(()=>root.unmount())};
};
const link={url:'https://platform.example.org/reset-password#'+'a'.repeat(43),expires_at:'2026-11-09T12:30:00Z'};
(async()=>{
  let f=await mount(Control,{id:2,email:'member@example.test',manual:true});
  await click(f.box,'Сбросить');
  assert.ok(f.box.textContent.includes('всего аккаунта'));
  const issue=props(find(f.box,'BUTTON','Создать ссылку')).onClick;
  flushSync(()=>{issue();issue();});await tick();
  assert.equal(posts.length,1);assert.equal(posts[0].url,'/api/admin/users/2/password-reset');
  assert.deepEqual(posts[0].body,{delivery:'manual',confirm_email:'member@example.test'});
  posts[0].resolve(link);await tick();
  assert.equal(props(walk(f.box).find(n=>n.tagName==='INPUT')).value,link.url);
  await click(f.box,'Копировать');assert.deepEqual(copies,[link.url]);assert.ok(f.box.textContent.includes('Скопировано'));
  navigator.clipboard.writeText=async()=>{throw Error('denied');};
  await click(f.box,'Скопировано');assert.ok(f.box.textContent.includes('скопируйте вручную'));
  await click(f.box,'Отправить в Telegram');assert.equal(posts.at(-1).body.delivery,'telegram');
  assert.ok(!walk(f.box).some(n=>n.tagName==='INPUT')); // discard old manual token immediately
  posts.at(-1).reject(Error('Telegram не привязан'));await tick();assert.ok(f.box.textContent.includes('не привязан'));
  await click(f.box,'Закрыть');assert.ok(!walk(f.box).some(n=>n.tagName==='INPUT'));f.unmount();

  f=await mount(Control,{id:2,email:'member@example.test',workspace:7});
  await click(f.box,'Сбросить');assert.ok(!f.box.textContent.includes('Создать ссылку'));
  await click(f.box,'Отправить');assert.equal(posts.at(-1).url,'/api/workspaces/7/members/2/password-reset');
  posts.at(-1).resolve({expires_at:link.expires_at});await tick();
  assert.ok(f.box.textContent.includes('Ссылка отправлена'));assert.ok(!f.box.textContent.includes('Копировать'));f.unmount();

  f=await mount(Control,{id:2,email:'member@example.test',manual:true});
  await click(f.box,'Сбросить');await click(f.box,'Создать ссылку');const pending=posts.at(-1);f.unmount();
  f=await mount(Control,{id:3,email:'other@example.test',manual:true});
  pending.resolve(link);await tick();assert.ok(!walk(f.box).some(n=>n.tagName==='INPUT'));f.unmount();

  f=await mount(Page,{});
  assert.equal(history.at(-1),'/reset-password');
  assert.equal(posts.at(-1).url,'/api/auth/password-reset/info');
  assert.deepEqual(posts.at(-1).body,{token:'a'.repeat(43)});
  posts.at(-1).resolve({email:'member@example.test'});await tick();
  const inputs=walk(f.box).filter(n=>n.tagName==='INPUT');
  assert.ok(inputs.every(n=>props(n).type==='password'&&props(n).autoComplete==='new-password'));
  flushSync(()=>{props(inputs[0]).onChange({target:{value:'new-password-value'}});props(inputs[1]).onChange({target:{value:'different-password'}});});
  const submit=()=>props(find(f.box,'FORM','')).onSubmit({preventDefault(){}});
  const before=posts.length;flushSync(submit);await tick();
  assert.equal(posts.length,before);assert.ok(f.box.textContent.includes('не совпадают'));
  flushSync(()=>props(inputs[1]).onChange({target:{value:'new-password-value'}}));
  flushSync(()=>{submit();submit();});await tick();assert.equal(posts.length,before+1);
  assert.equal(posts.at(-1).url,'/api/auth/password-reset/confirm');
  posts.at(-1).resolve({ok:true});await tick();
  assert.ok(f.box.textContent.includes('Прежние входы закрыты'));
  assert.ok(!walk(f.box).some(n=>n.tagName==='INPUT'));f.unmount();
  window.location.hash='';f=await mount(Page,{});
  assert.ok(f.box.textContent.includes('полную ссылку'));f.unmount();
  console.log('Password recovery React scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

// Actual Home component: unknown is not zero and has no invented trend.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs');
const base=path.resolve(process.argv[2]||path.resolve(__dirname,'../..')),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom')),ts=require(path.join(deps,'typescript'));
const mod={exports:{}};const js=ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/Home.tsx'),'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
new Function('require','module','exports',js)(name=>name==='react/jsx-runtime'?require(path.join(deps,'react/jsx-runtime')):name==='./trend'?{rowDir:()=>1}:(()=>{throw Error(name)})(),mod,mod.exports);
const box=document.body.appendChild(document.createElement('main')),root=createRoot(box);
const data={columns:[{title:'Indicators'},{title:'Today'},{title:'Yesterday'},{title:'Before'}],rows:[{label:'Unknown customer sum',fmt:'money',C:null,D:null,F:100}],ozon:true};
flushSync(()=>root.render(React.createElement(mod.exports.Home,{data})));
assert.ok(box.textContent.includes('Нет данных'));assert.equal((box.textContent.match(/Нет данных/g)||[]).length,2);assert.ok(!box.textContent.includes('к позавчера'));
data.rows=[{label:'Confirmed zero',fmt:'money',C:0,D:0,F:100}];
flushSync(()=>root.render(React.createElement(mod.exports.Home,{data})));
assert.ok(box.textContent.includes('0 ₽'));assert.ok(box.textContent.includes('к позавчера'));
flushSync(()=>root.unmount());console.log('Home order prices: unknown, genuine zero and comparison PASS');

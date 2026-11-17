const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {document}=require('./test_dom.cjs'),base=path.resolve(process.argv[2]||'.'),deps=path.join(base,'web/frontend/node_modules');
const React=require(path.join(deps,'react')),{createRoot}=require(path.join(deps,'react-dom/client')),{flushSync}=require(path.join(deps,'react-dom'));
const ts=require(path.join(deps,'typescript'));global.crypto=require('node:crypto').webcrypto;
const mod={exports:{}};new Function('require','module','exports',ts.transpileModule(fs.readFileSync(path.join(base,'web/frontend/src/Balance.tsx'),'utf8'),
{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText)(n=>require(path.join(deps,n)),mod,mod.exports);
const meta={today:'2026-11-17',can_edit:true,common_access:true,categories:{cash:'Деньги',loan:'Основной долг кредита'},
 shops:[{id:10,title:'WB Store',marketplace:'wb'},{id:11,title:'OZ Store',marketplace:'ozon'}],companies:[{id:1,title:'Company A',shops:[10,11]}]};
const batch={id:4,kind:'assets',label:'Активы и обязательства',day:'2026-11-16',payload:{rows:[{code:'A',name:'Cash',category:'cash',amount:'100'}]}};
const sum={inventory_cost:30,seller_stock_cost:0,other_assets:100,receivables:50,liabilities:20,assets:180,net:160,gaps:['Нет сверки'],partial_companies:[],fbs_replaced:[]};
const val=(known,missing=0)=>({known,total:missing?null:known,missing});
const inventory={note:'Saved stock',groups:[
 {kind:'to_buyer',title:'В пути к покупателю',at:'2026-11-17T10:00:00Z',complete:true,gaps:[],values:{quantity:val(100),cost:val(1836955,1),seller:val(2000000),buyer:val(1900000)}},
 {kind:'fbs',title:'FBS',at:null,complete:false,gaps:['Полнота снимка не подтверждена'],values:{quantity:val(5),cost:val(100,1),seller:val(200),buyer:val(150)}}
],rows:[
 {kind:'to_buyer',nm_id:101,code:'MissingCost',name:'Первый товар',quantity:3,cost:null,gaps:{cost:'Нет себестоимости на выбранную дату'}},
 {kind:'fbs',nm_id:102,code:'FbsOnly',name:'Товар FBS',quantity:2,cost:null,gaps:{cost:'Нет себестоимости FBS'}}
]};
sum.stock_totals={10:inventory.groups[0].values};
sum.gap_details={inventory_cost:[{message:'Нет себестоимости у товара',shop_id:10,kind:'to_buyer',metric:'cost'}],liabilities:[{message:'Нет сверки обязательств'}]};
const calls=[],writes=[];let delayReport=null,detailReply=null;
global.fetch=async (url,opts={})=>{calls.push(url);let body;
 if(url.endsWith('/balance'))body=meta;
 else if(url.includes('/report?')){if(delayReport)return delayReport(url);body={shops:{10:inventory},errors:{},companies:[{company:meta.companies[0],batches:[batch]}],variants:{with_fbs:{...sum,net:190},without_fbs:sum}};}
 else if(url.includes('/shops/10?')){if(detailReply)return detailReply();body=inventory;}
 else if(url.includes('/batches')){writes.push(JSON.parse(opts.body));body={id:5,added:true};}
 else if(url.includes('/preview/'))body={rows:[{code:'X',name:'Imported',category:'cash',amount:'222'}]};
 else throw Error('Unexpected '+url);
 return{ok:true,json:async()=>structuredClone(body)};
};
const host=document.body.appendChild(document.createElement('div')),root=createRoot(host);
const walk=n=>[n,...n.childNodes.flatMap(walk)],p=n=>n[Object.keys(n).find(k=>k.startsWith('__reactProps$'))]||{};
const nodes=()=>walk(host),text=()=>host.textContent;
const find=(tag,t)=>nodes().find(n=>n.tagName===tag&&n.textContent===t);
const button=t=>{const n=find('BUTTON',t);assert.ok(n,'Button '+t);return n;};
const label=t=>nodes().find(n=>n.tagName==='LABEL'&&n.textContent.includes(t));
const input=t=>walk(label(t)).find(n=>n.tagName==='INPUT'||n.tagName==='SELECT');
const tick=async()=>{for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));};
async function change(n,value){flushSync(()=>p(n).onChange({target:{value,checked:value}}));await tick();}
async function click(t){flushSync(()=>p(button(t)).onClick());await tick();}
(async()=>{try{
 flushSync(()=>root.render(React.createElement(mod.exports.Balance,{wsId:1})));await tick();
 assert.ok(text().includes('Выбери компанию'));assert.equal(calls.filter(x=>x.includes('/report?')).length,0);
 const company=nodes().find(n=>n.tagName==='SELECT'&&p(n)['aria-label']==='Компания');await change(company,'1');
 assert.ok(calls.some(x=>x.endsWith('shops=10,11')));assert.ok(text().includes('160 ₽'));
 // Partial value is the main figure. Details show affected products/reasons only.
 assert.ok(nodes().some(n=>n.tagName==='STRONG'&&n.textContent==='1 836 955'&&p(n).className==='balance-value'));
 const gapButton=label=>nodes().find(n=>n.tagName==='BUTTON'&&p(n)['aria-label']===label);
 async function gap(label){const n=gapButton(label);assert.ok(n);flushSync(()=>p(n).onClick());await tick();}
 await gap('Пробелы: Итого · Себестоимость');
 const dialog=()=>nodes().find(n=>p(n).role==='dialog'&&p(n)['aria-label']==='Расшифровка пробелов');
 assert.ok(dialog().textContent.includes('MissingCost'));assert.ok(dialog().textContent.includes('Нет себестоимости на выбранную дату'));
 assert.ok(!dialog().textContent.includes('FbsOnly'),'excluded FBS not in total drilldown');await click('Закрыть');
 await gap('Пробелы: FBS · Себестоимость');assert.ok(dialog().textContent.includes('FbsOnly'));
 assert.ok(dialog().textContent.includes('Полнота снимка'));assert.ok(!dialog().textContent.includes('MissingCost'));await click('Закрыть');
 assert.ok(!gapButton('Пробелы: В пути к покупателю · Количество'),'complete metric needs no gap button');
 const card=nodes().find(n=>p(n).className==='balance-card'&&n.textContent.includes('Товары МП по себестоимости'));
 flushSync(()=>p(walk(card).find(n=>n.tagName==='BUTTON')).onClick());await tick();
 assert.ok(dialog().textContent.includes('Нет себестоимости у товара'));await click('Товары и причины · магазин 10');
 assert.ok(dialog().textContent.includes('MissingCost'));await click('Закрыть');
 // A failed read stays visible and can be retried; updated sources are not mixed silently.
 detailReply=async()=>({ok:false,json:async()=>({detail:'Не удалось прочитать расшифровку'})});
 await gap('Пробелы: Итого · Себестоимость');assert.ok(dialog().textContent.includes('Не удалось прочитать'));
 detailReply=null;await click('Повторить чтение');assert.ok(dialog().textContent.includes('MissingCost'));await click('Закрыть');
 const refreshed=structuredClone(inventory);refreshed.groups[0].at='2026-11-17T11:00:00Z';
 detailReply=async()=>({ok:true,json:async()=>refreshed});
 await gap('Пробелы: Итого · Себестоимость');assert.ok(dialog().textContent.includes('обновились после открытия баланса'));
 await click('Закрыть');detailReply=null;
 const count=calls.length;await change(input('Не учитывать FBS'),false);assert.equal(calls.length,count,'visibility reads prepared variant');assert.ok(text().includes('190 ₽'));
 await click('Открыть реестр');assert.ok(text().includes('Cash'));await click('Изменить строку');
 await change(input('Сумма, ₽'),'120');assert.equal(p(button('Предпросмотр перед сохранением')).disabled,true);
 await click('Применить правку к черновику');await click('Предпросмотр перед сохранением');
 assert.equal(writes.length,0);assert.equal(p(button('Подтвердить и сохранить')).disabled,true);
 await change(input('Подтверждаю полный состав'),true);await click('Подтвердить и сохранить');
 assert.equal(writes.length,1);assert.equal(writes[0].previous_id,4);assert.equal(writes[0].payload.rows[0].amount,'120');assert.ok(writes[0].request_key);
 // Excel is preview only, replacement is visible and requires a second explicit action.
 await click('Открыть реестр');const file=nodes().find(n=>n.tagName==='INPUT'&&p(n).type==='file');
 const {File}=require('node:buffer');flushSync(()=>p(file).onChange({target:{files:[new File(['fake'],'balance.xlsx')],value:'x'}}));await tick();
 assert.ok(text().includes('Imported'));assert.equal(writes.length,1);assert.equal(p(button('Подтвердить и сохранить')).disabled,true);
 await click('Закрыть');
 // Late old-scope responses cannot restore a previous workspace's figures.
 let resolve;delayReport=()=>new Promise(r=>{resolve=r;});await change(input('WB · WB Store'),false);
 assert.ok(!text().includes('190 ₽'));flushSync(()=>root.render(React.createElement(mod.exports.Balance,{wsId:2})));await tick();
 resolve({ok:true,json:async()=>({shops:{},errors:{},companies:[],variants:{with_fbs:{...sum,net:999999},without_fbs:{...sum,net:999999}}})});await tick();
 assert.ok(!text().includes('999 999'));
 console.log('Balance: company/multi-shop scope, prepared FBS switch, snapshot preview/confirmation, Excel, version and late-response isolation OK');
}finally{flushSync(()=>root.unmount());}})().catch(e=>{console.error(e);process.exitCode=1;});

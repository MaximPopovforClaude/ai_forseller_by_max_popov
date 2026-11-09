// Actual shipped service worker and popup with fake Chrome and HTTP only.
const assert=require('node:assert/strict'),vm=require('node:vm');
const {background,flush,read}=require('./plugin_regression.cjs');
const request=b=>b.message({type:'api',path:'/api/plugin/me'});
function popup(mode) {
 const nodes=Object.fromEntries(['who','recst','save','out','tok','rec','stop','now','nowst','auto','platform-host'].map(id=>[id,{textContent:'',value:'',disabled:false}]));
 nodes['platform-host'].textContent='https://plugin.test';const stored={},pending=[],timers=[];
 const chrome={runtime:{lastError:null,sendMessage(m,cb){
   if(m.type==='rec_state'){cb({on:false});return;}
   if(mode==='dead'){chrome.runtime.lastError={message:'synthetic-private-runtime-text'};cb();chrome.runtime.lastError=null;return;}
   if(mode==='deferred'){pending.push(cb);return;}
   cb(mode==='bad'?{ok:true,data:'html'}:{ok:true,data:{name:'Synthetic',shops:[{title:'Own shop'}]}});
 }},storage:{local:{get:async k=>({[k]:stored[k]}),set:async x=>Object.assign(stored,x),remove:async keys=>{for(const key of keys)delete stored[key];}}},tabs:{query:async()=>[]}};
 const context=vm.createContext({chrome,document:{getElementById:id=>nodes[id]},setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){}});
 vm.runInContext(read('popup.js'),context);return {nodes,stored,pending,timers};
}
(async()=>{
 const raw=background({origin:'https://platform.example.org'});await flush();
 assert.equal((await request(raw)).error,'platform_not_configured');assert.equal(raw.fetches.length,0);
 const b=background();await flush();
 b.context.fetch=async(url,opt)=>{b.fetches.push({url,opt});return {ok:true,status:200,json:async()=>({name:'Synthetic',shops:[]})}};
 const connected=await request(b);assert.ok(connected.ok);assert.equal(b.fetches.at(-1).url,'https://plugin.test/api/plugin/me');
 assert.equal(b.fetches.at(-1).opt.credentials,'omit');assert.equal(b.fetches.at(-1).opt.redirect,'error');
 const count=b.fetches.length;b.stored.token_origin='https://other.test';assert.equal((await request(b)).ok,false);assert.equal(b.fetches.length,count);
 delete b.stored.token_origin;assert.equal((await request(b)).ok,false);assert.equal(b.fetches.length,count);b.stored.token_origin='https://plugin.test';
 for(const url of ['https://foreign.test/api/plugin/me','/api/plugin/\\evil','/api/admin/settings','/api/plugin/../admin/settings'])assert.equal((await b.message({type:'api',path:url})).ok,false);
 assert.equal(b.fetches.length,count);
 b.context.fetch=async()=>{throw Error('synthetic-private-error-token')};const network=await request(b);
 assert.equal(network.error,'service_network');assert.ok(network.data.detail.includes('https://plugin.test'));assert.ok(!JSON.stringify(network).includes('private-error'));
 b.context.fetch=async()=>({ok:false,status:401,json:async()=>({detail:'old provider name'})});assert.ok((await request(b)).data.detail.includes('Код плагина не принят'));
 b.context.fetch=async()=>({ok:false,status:403,json:async()=>({detail:'Недостаточно прав'})});assert.equal((await request(b)).data.detail,'Недостаточно прав');
 b.context.fetch=async()=>({ok:true,status:200,json:async()=>{throw Error('HTML page')}});assert.equal((await request(b)).error,'service_response');
 const dead=popup('dead');await flush();assert.ok(dead.nodes.who.textContent.includes('Фон плагина'));assert.ok(!dead.nodes.who.textContent.includes('private-runtime'));
 const bad=popup('bad');await flush();assert.ok(bad.nodes.who.textContent.includes('не похож'));
 const good=popup('good');await flush();assert.ok(good.nodes.who.textContent.includes('Подключено: Synthetic'));
 good.nodes.tok.value='synthetic-code';await good.nodes.save.onclick();assert.equal(good.stored.token_origin,'https://plugin.test');assert.equal(good.nodes.tok.value,'');
 const race=popup('deferred');await flush();race.nodes.tok.value='synthetic-next-code';const saving=race.nodes.save.onclick();await flush();
 race.pending[1]({ok:false,data:{detail:'new error'}});await saving;race.pending[0]({ok:true,data:{name:'old',shops:[]}});await flush();assert.equal(race.nodes.who.textContent,'new error');
 console.log('Plugin connection: site binding, placeholder, origin scope, network/401/403/HTML, missing worker, saved scope and stale replies PASS');
})().catch(e=>{console.error(e);process.exitCode=1});

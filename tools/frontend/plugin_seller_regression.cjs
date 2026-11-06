// Execute the shipped seller script, with simulated WB/100MC and Chrome events.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {read, flush} = require('./plugin_regression.cjs');
function seller(options = {}) {
  const calls = [], messages = [], timers = [], nodes = new Map();
  const stored = {token: 'synthetic-plugin', entry_auto: true, entry_map: {'shop-A': 9}, ...options.stored};
  let listener, auth = options.noAuth ? null : {headers: {AuthorizeV3: 'synthetic-session-old'}, revision: 'old'},
    supplier = 'shop-A', reportId, rejected = 0, completed = false;
  const document = {
    get cookie() {return `x-supplier-id-external=${supplier}`;},
    getElementById: id => nodes.get(id),
    createElement: () => ({style: {}, remove() {}}),
    body: {append(d) {nodes.set(d.id, d);}}
  };
  const chrome = {
    runtime: {onMessage: {addListener(fn) {listener = fn;}}, sendMessage(m, done) {
      messages.push(structuredClone(m));
      let result = {ok: true};
      if (m.type === 'seller_context') completed = false;
      if (m.type === 'auth_headers') result = auth || {headers: {}};
      if (m.type === 'auth_rejected') {auth = null; rejected++;}
      if (m.type === 'api' && m.path === '/api/plugin/entry_days') result = {ok: true, data: {days: {}, expected_days: ['2026-11-05']}};
      if (m.type === 'api' && m.path === '/api/plugin/trace') completed = true;
      if (m.type === 'fetch_bin') {
        assert.equal(m.url, `https://downloads-content-analytics.wildberries.ru/api/v1/file-manager/download/${reportId}`);
        assert.equal(m.downloadToken, 'synthetic-download-token');
        assert.equal(m.headers, undefined, 'Seller session must not go to download host');
        result = options.downloadFailure ? {ok: false, status: 401} : {ok: true, status: 200, b64: btoa('fake-xlsx')};
        if (options.switchAfterDownload) supplier = 'shop-B';
      }
      if (m.type === 'upload') result = {ok: true, data: {shop_id: 9, shop: 'Fixture', rows: 3}};
      queueMicrotask(() => done(result));
    }},
    storage: {local: {
      get: async keys => Object.fromEntries((Array.isArray(keys) ? keys : [keys]).map(k => [k, structuredClone(stored[k])])),
      set: async data => Object.assign(stored, structuredClone(data))
    }}
  };
  const context = vm.createContext({chrome, document, Date, URL, AbortSignal, crypto: require('node:crypto').webcrypto, btoa, Uint8Array,
    location: {href: 'https://seller.wildberries.ru/?private=must-not-appear'},
    setTimeout(fn, ms) {timers.push({fn, ms}); return timers.length;}, setInterval() {},
    fetch: async (url, opt) => {
      calls.push({url, opt});
      let stage, data = {};
      if (url.endsWith('/download')) {stage = 'create'; reportId = JSON.parse(opt.body).id;}
      else if (url.includes('/downloads?')) {stage = 'poll'; data = {data: [{id: reportId, status: options.timeout ? 'PENDING' : 'SUCCESS', downloadUrl: 'https://evil.test/must-ignore'}]};}
      else {stage = 'token'; data = {result: {token: 'synthetic-download-token'}};}
      const attempts = calls.filter(x => x.url === url).length;
      const fail = options.failStage === stage && (!options.refresh || attempts === 1);
      if (options.switchAt === stage) supplier = 'shop-B';
      if (options.networkAt === stage) throw Error('synthetic-secret-must-not-leak');
      return {status: fail ? (options.status || 401) : 200, ok: !fail,
        json: async () => fail ? {secret: 'synthetic-secret-must-not-leak'} : data};
    }
  });
  vm.runInContext(read('seller.js'), context);
  function click() {let result; listener({type: 'entry_now'}, {}, r => result = r); return result;}
  async function finish() {
    for (let n = 0; n < 120; n++) {
      await flush();
      const index = timers.findIndex(x => x.ms !== 8000);
      if (index < 0) return;
      const [t] = timers.splice(index, 1);
      if (t.ms === 500 && options.refresh) auth = {headers: {AuthorizeV3: 'synthetic-session-fresh'}, revision: 'fresh'};
      t.fn();
    }
    throw Error('Unbounded request/poll loop');
  }
  return {click, finish, calls, messages, stored, text: () => nodes.get('mc100-toast')?.textContent || '', rejected: () => rejected, done: () => completed};
}
(async () => {
  for (const failStage of ['create', 'poll', 'token']) {
    const s = seller({failStage, refresh: true});
    assert.equal(s.click().busy, false); assert.equal(s.click().busy, true);
    await s.finish();
    assert.equal(s.rejected(), 1);
    assert.equal(s.messages.filter(m => m.type === 'upload').length, 1, `${failStage} recovery`);
    assert.equal(s.calls.filter(c => c.opt.headers.AuthorizeV3 === 'synthetic-session-fresh').length > 0, true);
    if (failStage === 'create') {
      const created = s.calls.filter(c => c.url.endsWith('/download'));
      assert.equal(created.length, 2); assert.equal(created[0].opt.body, created[1].opt.body, 'Retry changed report id');
    }
    assert.match(s.text(), /загружено дней — 1/);
    assert.ok(s.stored.entry_last['shop-A']);
    const trace = JSON.stringify(s.messages.filter(m => m.path === '/api/plugin/trace'));
    for (const secret of ['synthetic-session', 'synthetic-download', 'synthetic-secret', 'must-not-appear']) assert.ok(!trace.includes(secret));
  }
  for (const failStage of ['create', 'poll', 'token']) {
    const s = seller({failStage}); s.click(); await s.finish();
    assert.equal(s.rejected(), 1); assert.match(s.text(), /401/);
    assert.equal(s.messages.filter(m => m.type === 'upload').length, 0);
    assert.equal(s.stored.entry_last, undefined, 'Failed run postponed further checks for an hour');
    assert.equal(s.click().busy, false, 'Failure did not release the run lock'); await s.finish();
  }
  for (const extra of [{status: 403}, {status: 429}, {networkAt: 'create'}, {noAuth: true}]) {
    const s = seller({failStage: 'create', ...extra}); s.click(); await s.finish();
    assert.equal(s.messages.filter(m => m.type === 'upload').length, 0);
    assert.equal(s.rejected(), 0); assert.ok(!s.text().includes('synthetic-secret'));
  }
  const timeout = seller({timeout: true}); timeout.click(); await timeout.finish();
  assert.match(timeout.text(), /отведённое время/);
  assert.equal(timeout.calls.length, 61); // create + 60 polls, no token/download
  assert.equal(timeout.messages.filter(m => m.type === 'fetch_bin').length, 0);
  for (const extra of [{switchAt: 'create'}, {switchAt: 'poll'}, {switchAfterDownload: true}, {downloadFailure: true}]) {
    const s = seller(extra); s.click(); await s.finish();
    assert.equal(s.messages.filter(m => m.type === 'upload').length, 0, 'Failed/other-supplier report was uploaded');
  }
  console.log('Plugin seller: full pipeline, one fresh retry at each stage, concurrent click, timeout, permissions, supplier changes and secret-free diagnostics PASS');
})().catch(e => {console.error(e); process.exitCode = 1;});

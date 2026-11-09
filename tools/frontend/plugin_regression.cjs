// Execute shipped extension scripts with deferred Chrome/DOM events; no live credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.argv[2] || path.resolve(__dirname, '../..');
const read = file => fs.readFileSync(path.join(root, 'extension', file), 'utf8');
const flush = async () => { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)); };
const match = (pattern, url) => new RegExp('^' + pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replaceAll('*', '.*') + '$').test(url);
const search = 'https://www.wildberries.ru/catalog/0/search.aspx?search=tea';
const product = 'https://www.wildberries.ru/catalog/123/detail.aspx';

function background(options = {}) {
  const events = {}, registrations = [], calls = [], writes = [], gets = [], stored = {
    rec: {start: Date.now(), items: [], byId: {}, page: 'fixture'}, auth: {}, token: 'fixture-plugin-token', token_origin: 'https://plugin.test'
  };
  const listeners = {};
  const event = name => ({addListener(callback, filter, extra = []) {
    (listeners[name] ||= []).push(callback);
    events[name] = (...args) => listeners[name].map(fn => fn(...args));
    if (filter) registrations.push({name, callback, filter, extra});
  }});
  const chrome = {
    runtime: {onMessage: event('message')},
    tabs: {onUpdated: event('tab'), onRemoved: event('removed'), get: async id => { gets.push(id); return {url: chrome.currentUrl}; }},
    scripting: {
      executeScript: async spec => { calls.push(spec); return [{result: false, documentId: 'fixture-doc'}]; },
      insertCSS: async spec => { calls.push(spec); }
    },
    storage: Object.fromEntries(['session', 'local'].map(name => [name, {
      get: async key => Object.fromEntries((Array.isArray(key) ? key : [key]).map(k => [k, stored[k]])),
      set: async data => { writes.push(data); Object.assign(stored, data); },
      remove: async key => { delete stored[key]; }
    }])),
    webRequest: Object.fromEntries(['onBeforeRequest','onCompleted','onSendHeaders','onErrorOccurred'].map(name => [name, event(name)]))
  };
  const fetches = [];
  const context = vm.createContext({chrome, URL, TextDecoder, Uint8Array, atob, btoa, Date, AbortSignal, crypto: require('node:crypto').webcrypto,
    setTimeout: () => 1, clearTimeout() {},
    fetch: async (url, options) => {fetches.push({url, options}); return {ok: true, status: 200, json: async () => ({ok: true})};}
  });
  vm.runInContext(read('bg.js').replace(/^const API = .*?;/m, 'const API = ' + JSON.stringify(options.origin || 'https://plugin.test') + ';'), context);
  const request = async (name, d) => {
    for (const r of registrations.filter(r => r.name === name)) {
      if (r.filter.urls.some(p => match(p, d.url)) && (!r.filter.types || r.filter.types.includes(d.type))) await r.callback(d);
    }
  };
  const message = (body, sender = {}) => new Promise(resolve => events.message(body, sender, resolve));
  return {chrome, events, registrations, calls, writes, gets, stored, request, message, fetches, context};
}

function storefront(initialPath) {
  const nodes = new Map(), calls = [], listeners = [], timers = [];
  let domWrites = 0;
  class Element {
    constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.classList = {toggle() {}}; }
    setAttribute(key, value) { this[key] = value; if (key === 'id') nodes.set(value, this); }
    append(...items) { domWrites++; this.children.push(...items); }
    replaceChildren(...items) { domWrites++; this.children = items; }
    remove() { domWrites++; nodes.delete(this.id); }
    set textContent(value) { this.text = value; }
    get textContent() { return this.text || this.children.map(x => typeof x === 'string' ? x : x.textContent).join(' '); }
  }
  const location = {origin: 'https://www.wildberries.ru', pathname: initialPath};
  const chrome = {runtime: {sendMessage: (message, resolve) => calls.push({message, resolve})}};
  const context = vm.createContext({chrome, location, Intl, Date,
    document: {getElementById: id => nodes.get(id), createElement: tag => new Element(tag), body: new Element('body')},
    navigation: {addEventListener: (name, fn) => { assert.equal(name, 'currententrychange'); listeners.push(fn); }},
    setInterval: fn => timers.push(fn)
  });
  const run = () => vm.runInContext(read('wb.js'), context);
  const go = pathname => { location.pathname = pathname; for (const fn of listeners) void fn(); };
  return {run, go, calls, nodes, listeners, timers, chrome, domWrites: () => domWrites};
}

module.exports = {background, flush, read};
if (require.main === module) (async () => {
  const manifest = JSON.parse(read('manifest.json'));
  for (const url of [search, 'https://www.wildberries.ru/', 'https://www.wildberries.ru/catalog/food']) {
    assert.ok(!manifest.content_scripts.some(s => s.matches.some(p => match(p, url))), `Unwanted static injection: ${url}`);
  }
  assert.ok(manifest.content_scripts.some(s => s.js.includes('seller.js') && s.matches.some(p => match(p, 'https://seller.wildberries.ru/'))));
  assert.ok(manifest.permissions.includes('scripting'));
  let b = background(); await flush();
  for (const r of b.registrations) {
    for (const url of [search, 'https://www.wildberries.ru/', 'https://search.wildberries.ru/exactmatch', 'https://wbaas.wildberries.ru/challenge']) {
      assert.ok(!r.filter.urls.some(p => match(p, url)), `Consumer request observed: ${r.name} ${url}`);
    }
    assert.ok(!r.extra.includes('extraHeaders'), 'Unnecessary sensitive-header observation');
  }
  // Report request recording and custom header capture still work, with exact seller origin.
  const seller = {url: 'https://seller-content.wildberries.ru/ns/analytics-api/content-analytics/api/v1/file-manager/download',
    initiator: 'https://seller.wildberries.ru', type: 'xmlhttprequest', requestId: 'fixture-1', method: 'POST',
    tabId: 1, frameId: 0, documentId: 'seller-doc',
    requestHeaders: [{name: 'AuthorizeV3', value: 'fixture-session'}, {name: 'Cookie', value: 'fixture-cookie'}]};
  const sellerSender = {tab: {id: 1}, frameId: 0, documentId: 'seller-doc', url: 'https://seller.wildberries.ru/'};
  await b.message({type: 'seller_context', supplier: 'fixture-shop'}, sellerSender);
  await b.request('onBeforeRequest', seller);
  await b.request('onSendHeaders', seller);
  await b.request('onCompleted', {...seller, statusCode: 200});
  assert.equal(b.stored.rec.items.length, 1); assert.equal(b.stored.rec.items[0].status, 200);
  let headers = await b.message({type: 'auth_headers', host: 'seller-content.wildberries.ru', supplier: 'fixture-shop'}, sellerSender);
  assert.equal(headers.headers.AuthorizeV3, 'fixture-session'); assert.equal(headers.headers.Cookie, undefined);
  const before = b.writes.length;
  for (const initiator of ['https://www.wildberries.ru', 'https://seller.wildberries.ru.example.org']) {
    await b.request('onBeforeRequest', {...seller, requestId: 'foreign', initiator});
    await b.request('onSendHeaders', {...seller, initiator});
  }
  assert.equal(b.writes.length, before); assert.equal(b.stored.rec.items.length, 1);
  const upload = await b.message({type: 'upload', path: '/api/plugin/entry/0', b64: btoa('fixture-xlsx')});
  assert.equal(upload.ok, true); assert.equal(b.fetches.at(-1).url, 'https://plugin.test/api/plugin/entry/0');
  // Searching never injects code or styles; a product opened via SPA does.
  b.chrome.currentUrl = search;
  b.events.tab(1, {url: search}, {url: search}); await flush();
  assert.equal(b.calls.length, 0); assert.equal(b.gets.length, 0);
  b.chrome.currentUrl = product;
  b.events.tab(1, {url: product}, {url: product});
  b.events.tab(1, {status: 'complete'}, {url: product}); await flush();
  assert.equal(b.calls.filter(x => x.files?.includes('wb.js')).length, 1);
  assert.equal(b.calls.filter(x => x.files?.includes('panel.css')).length, 1);
  for (const c of b.calls.filter(x => x.files)) assert.deepEqual(Array.from(c.target.documentIds), ['fixture-doc']);
  const count = b.calls.length;
  b.chrome.currentUrl = search;
  b.events.tab(1, {url: product}, {url: product}); await flush();
  assert.equal(b.calls.length, count, 'Route changed before injection');
  // Closing a tab during a pending injection must not raise an unhandled rejection.
  b.chrome.tabs.get = async () => {throw Error('fixture closed tab');};
  b.events.tab(2, {url: product}, {url: product}); await flush();

  for (const pathname of ['/', '/catalog/0/search.aspx', '/catalog/food', '/catalog/123/detail.aspx/extra']) {
    const f = storefront(pathname); f.run(); await flush();
    assert.equal(f.calls.length, 0); assert.equal(f.domWrites(), 0); assert.equal(f.timers.length, 0);
  }
  const f = storefront('/catalog/123/detail.aspx'); f.run(); f.run(); await flush();
  assert.equal(f.calls.length, 1); assert.equal(f.listeners.length, 1); assert.equal(f.timers.length, 0);
  assert.ok(f.nodes.has('mc100-panel'));
  f.go('/catalog/0/search.aspx'); await flush(); assert.ok(!f.nodes.has('mc100-panel'));
  f.calls[0].resolve({ok: true, data: {own: null, shelves: null}}); await flush();
  assert.ok(!f.nodes.has('mc100-panel'), 'Late product response leaked onto search');
  f.go('/catalog/456/detail.aspx'); await flush();
  f.calls[1].resolve({ok: true, data: {own: null, shelves: null}}); await flush();
  assert.match(f.nodes.get('mc100-panel').textContent, /456/);
  f.go('/catalog/123/detail.aspx'); await flush();
  const old = f.calls.at(-1);
  f.go('/catalog/0/search.aspx'); f.go('/catalog/123/detail.aspx'); await flush();
  f.calls.at(-1).resolve({ok: false, data: {detail: 'new response'}}); await flush();
  old.resolve({ok: false, data: {detail: 'stale response'}}); await flush();
  assert.match(f.nodes.get('mc100-panel').textContent, /new response/);
  f.go('/catalog/789/detail.aspx'); await flush();
  f.chrome.runtime.lastError = {message: 'fixture removed extension'};
  f.calls.at(-1).resolve(undefined); await flush();
  assert.match(f.nodes.get('mc100-panel').textContent, /Нет связи/);
  console.log('Plugin: storefront isolation, seller headers/upload, SPA injection, cleanup, races and disconnected runtime PASS');
})().catch(e => {console.error(e); process.exitCode = 1;});

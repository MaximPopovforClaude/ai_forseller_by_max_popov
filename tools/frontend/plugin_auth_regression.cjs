// Real background script, fake Chrome events and synthetic credentials only.
const assert = require('node:assert/strict');
const {background, flush} = require('./plugin_regression.cjs');
const host = 'seller-content.wildberries.ru';
const sender = (tab = 1, doc = 'doc-1') => ({tab: {id: tab}, frameId: 0, documentId: doc, url: 'https://seller.wildberries.ru/'});
const message = (b, type, extra = {}, who = sender()) => b.message({type, supplier: 'shop-A', host, ...extra}, who);
const request = (id, value = 'synthetic-session-A', extra = {}) => ({
  requestId: id, tabId: 1, frameId: 0, documentId: 'doc-1', type: 'xmlhttprequest',
  url: `https://${host}/ns/analytics-api/content-analytics/api/v1/file-manager/downloads`,
  initiator: 'https://seller.wildberries.ru', timeStamp: Date.now(),
  requestHeaders: [{name: 'AuthorizeV3', value}, {name: 'Seller-Lk', value: 'synthetic-lk'}], ...extra
});
(async () => {
  const b = background(); await flush();
  await message(b, 'seller_context');
  const first = request('first');
  await b.request('onSendHeaders', first);
  await b.request('onCompleted', {...first, statusCode: 200});
  let a = await message(b, 'auth_headers');
  assert.equal(a.headers.AuthorizeV3, 'synthetic-session-A');
  // The previous implementation exposes tab A's session to any other tab.
  const other = await message(b, 'auth_headers', {}, sender(2, 'doc-2'));
  assert.equal(Object.keys(other.headers).length, 0, 'Session from a different tab was reused');
  await message(b, 'auth_rejected', {revision: a.revision});
  await b.request('onSendHeaders', request('failed-replay'));
  await b.request('onCompleted', {...request('failed-replay'), statusCode: 401});
  a = await message(b, 'auth_headers');
  assert.equal(Object.keys(a.headers).length, 0, '401 repopulated rejected credentials');
  assert.equal(b.stored.auth, undefined, 'Legacy shared cache survived');
  async function accepted(id, value, extra = {}) {
    const req = request(id, value, extra);
    await b.request('onSendHeaders', req);
    await b.request('onCompleted', {...req, statusCode: 200});
    return message(b, 'auth_headers');
  }
  a = await accepted('fresh', 'synthetic-fresh');
  await message(b, 'auth_rejected', {revision: 'older-revision'});
  assert.equal((await message(b, 'auth_headers')).revision, a.revision, 'Late rejection removed newer session');
  const pending = request('pending-before-switch');
  await b.request('onSendHeaders', pending);
  await message(b, 'seller_context', {supplier: 'shop-B'});
  await b.request('onCompleted', {...pending, statusCode: 200});
  assert.equal(Object.keys((await message(b, 'auth_headers', {supplier: 'shop-B'})).headers).length, 0);
  await accepted('shop-B', 'synthetic-B');
  assert.equal((await message(b, 'auth_headers', {supplier: 'shop-B'})).headers.AuthorizeV3, 'synthetic-B');
  await message(b, 'seller_context', {}, sender(1, 'new-doc'));
  await accepted('obsolete-document', 'synthetic-obsolete');
  assert.equal(Object.keys((await message(b, 'auth_headers', {}, sender(1, 'new-doc'))).headers).length, 0);
  await message(b, 'seller_context');
  const old = request('slow-old', 'synthetic-old', {timeStamp: Date.now() - 1000});
  await b.request('onSendHeaders', old);
  await accepted('quick-new', 'synthetic-new');
  await b.request('onCompleted', {...old, statusCode: 200});
  assert.equal((await message(b, 'auth_headers')).headers.AuthorizeV3, 'synthetic-new');
  const slowReplay = request('slow-replay', 'synthetic-new', {timeStamp: Date.now() - 1});
  await b.request('onSendHeaders', slowReplay);
  a = await message(b, 'auth_headers');
  await message(b, 'auth_rejected', {revision: a.revision});
  await b.request('onCompleted', {...slowReplay, statusCode: 200});
  assert.equal(Object.keys((await message(b, 'auth_headers')).headers).length, 0, 'Late success restored rejected session');
  // New scheme is a coherent snapshot, never the union of two auth schemes.
  a = await accepted('new-scheme', '', {requestHeaders: [{name: 'Authorization', value: 'synthetic-bearer'}]});
  assert.equal(a.headers.AuthorizeV3, undefined);
  assert.equal(a.headers['Seller-Lk'], undefined);
  assert.equal(a.headers.Authorization, 'synthetic-bearer');
  for (const who of [{}, {...sender(), frameId: 1}, {...sender(), url: 'https://www.wildberries.ru/'}, {...sender(), documentLifecycle: 'cached'}]) {
    assert.equal(Object.keys((await message(b, 'auth_headers', {}, who)).headers).length, 0);
  }
  b.stored.authV2[1].entry.saved -= 31 * 60000;
  assert.equal(Object.keys((await message(b, 'auth_headers')).headers).length, 0, 'Expired cache reused');
  await accepted('before-close', 'synthetic-close');
  b.events.removed(1); await flush();
  assert.equal(Object.keys((await message(b, 'auth_headers')).headers).length, 0);
  const count = b.fetches.length;
  for (const url of ['https://example.test/report', 'https://downloads-content-analytics.wildberries.ru.evil.test/api/v1/file-manager/download/id',
    'https://downloads-content-analytics.wildberries.ru/api/v1/file-manager/download/id?token=secret']) {
    const r = await message(b, 'fetch_bin', {url, downloadToken: 'synthetic-download'});
    assert.equal(r.ok, false);
  }
  assert.equal(b.fetches.length, count, 'Download credential sent to an unapproved URL');
  console.log('Plugin auth: tabs/documents/suppliers, rejected replay, races, TTL, logout, coherent headers and download boundary PASS');
})().catch(e => {console.error(e); process.exitCode = 1;});

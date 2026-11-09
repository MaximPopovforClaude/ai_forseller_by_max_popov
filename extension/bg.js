// Плагин seller-analytics: фон. Запросы к platform.example.org (код плагина — в chrome.storage), запись запросов кабинета WB по кнопке в окне плагина.
const API = "https://platform.example.org";
const REC_MAX = 2000, REC_MINUTES = 10;
const SKIP_TYPES = new Set(["image", "script", "stylesheet", "font", "media", "imageset", "csp_report"]);
// Apply the restriction in Chrome's request filter, before callbacks are invoked.
// Storefront/search/challenge requests never need to wake the report collector.
const SELLER_HOSTS = new Set(["seller.wildberries.ru", "seller-content.wildberries.ru", "downloads-content-analytics.wildberries.ru"]);
const SELLER_FILTER = { urls: [...SELLER_HOSTS].map((host) => `https://${host}/*`), types: ["xmlhttprequest", "other"] };

function cardUrl(url) {
  try {
    const u = new URL(url);
    return u.origin === "https://www.wildberries.ru" && /^\/catalog\/[1-9]\d*\/detail\.aspx$/.test(u.pathname);
  } catch { return false; }
}

// WB changes product URLs without a document reload. Only inject on product
// routes; the content script cleans up its panel when the user leaves a product.
const cardLoads = new Set();
chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (change.status === "loading" || (!change.url && change.status !== "complete") || !cardUrl(tab.url) || cardLoads.has(tabId)) return;
  cardLoads.add(tabId);
  (async () => {
    try {
      if (!cardUrl((await chrome.tabs.get(tabId)).url)) return;
      const [probe] = await chrome.scripting.executeScript({ target: { tabId }, func: () => {
        if (globalThis.__mc100CardPanel) { globalThis.__mc100CardPanel(); return true; }
        return false;
      } });
      if (!probe || probe.result) return;
      // Pin the document: navigation during awaits must not inject into its replacement.
      const target = { tabId, documentIds: [probe.documentId] };
      await chrome.scripting.insertCSS({ target, files: ["panel.css"] });
      await chrome.scripting.executeScript({ target, files: ["wb.js"] });
    } catch {
      // Closed/replaced tab or removed extension access: leave the WB page alone.
    } finally { cardLoads.delete(tabId); }
  })();
});

async function token() {
  const saved = await chrome.storage.local.get(["token", "token_origin"]);
  return saved.token_origin === API && typeof saved.token === "string" ? saved.token : "";
}

function serviceOrigin() {
  try {
    const u = new URL(API);
    if (u.protocol !== "https:" || u.username || u.password || u.origin !== API ||
        /(^|\.)(example\.(org|com|net)|localhost)$/.test(u.hostname)) return null;
    return u.origin;
  } catch { return null; }
}
async function serviceRequest(path, options = {}, timeout = 15000) {
  const site = serviceOrigin();
  if (!site) return {ok: false, status: 0, error: "platform_not_configured", data: {detail:
    "Плагин не настроен на ваш сайт. Скачайте новый архив в разделе «Плагин Chrome» своей платформы и обновите расширение."}};
  if (typeof path !== "string" || !path.startsWith("/api/plugin/") || /[\\\x00-\x20]/.test(path) || new URL(path, site).origin !== site || !new URL(path, site).pathname.startsWith("/api/plugin/"))
    return {ok: false, status: 0, data: {detail: "Недопустимый запрос плагина."}};
  const t = await token();
  if (!t) return {ok: false, status: 0, data: {detail: "Введите код заново для " + site + ". Код из другой установки не подходит."}};
  try {
    const r = await fetch(site + path, {...options, credentials: "omit", redirect: "error", signal: AbortSignal.timeout(timeout),
      headers: {...(options.headers || {}), Authorization: "Bearer " + t}});
    let data = null;
    try { data = await r.json(); } catch {}
    if (r.status === 401) return {ok: false, status: 401, data: {detail: "Код плагина не принят. Получите новый код на " + site + " в нужном кабинете."}};
    if (!data || typeof data !== "object") return {ok: false, status: r.status, error: "service_response", data: {detail:
      "Сайт " + site + " ответил не как платформа (HTTP " + r.status + "). Проверьте адрес и настройку HTTPS-прокси."}};
    return {ok: r.ok, status: r.status, data};
  } catch {
    return {ok: false, status: 0, error: "service_network", data: {detail:
      "Нет соединения с " + site + ". Проверьте, открывается ли этот сайт, HTTPS и доступ расширения к нему. После обновления файлов перезагрузите плагин."}};
  }
}
async function api(path, { method = "GET", body } = {}) {
  return serviceRequest(path, {method, headers: body ? {"Content-Type": "application/json"} : {},
    body: body ? JSON.stringify(body) : undefined});
}

// ── запись запросов кабинета продавца (включает пользователь; заголовки и cookie не берём) ──
// фоновый скрипт Chrome усыпляет через ~30 с тишины — запись держим в storage.session, а не только в памяти
let rec = null;   // {start, page, items: [], byId: {}}
const ready = chrome.storage.session.get("rec").then((x) => { rec = x.rec || null; });
let saveT = null;
function save() { clearTimeout(saveT); saveT = setTimeout(() => chrome.storage.session.set({ rec }), 300); }
function sellerReq(d) {
  try {
    const u = new URL(d.url);
    return u.protocol === "https:" && SELLER_HOSTS.has(u.hostname) && d.initiator === "https://seller.wildberries.ru" && !SKIP_TYPES.has(d.type);
  } catch { return false; }
}
function bodyOf(rb) {
  if (!rb) return null;
  if (rb.formData) return rb.formData;
  if (rb.raw && rb.raw[0] && rb.raw[0].bytes) {
    const s = new TextDecoder().decode(rb.raw[0].bytes).slice(0, 20000);
    try { return JSON.parse(s); } catch { return s; }
  }
  return null;
}
chrome.webRequest.onBeforeRequest.addListener(async (d) => {
  await ready;
  if (rec && Date.now() - rec.start > REC_MINUTES * 60000) { recStop(); return; }
  if (!rec || !sellerReq(d) || rec.items.length >= REC_MAX) return;
  const it = { t: Math.round((Date.now() - rec.start) / 100) / 10, method: d.method, url: d.url, type: d.type, body: bodyOf(d.requestBody) };
  rec.byId[d.requestId] = rec.items.length;     // номер, а не сам объект: запись переживает сохранение в storage
  rec.items.push(it);
  save();
}, SELLER_FILTER, ["requestBody"]);
chrome.webRequest.onCompleted.addListener(async (d) => {
  await ready;
  const it = rec && rec.items[rec.byId[d.requestId]];
  if (!it) return;
  it.status = d.statusCode;
  const h = (d.responseHeaders || []).find((x) => x.name.toLowerCase() === "content-type");
  it.ctype = h ? h.value : "";
  save();
}, SELLER_FILTER, ["responseHeaders"]);

// Session credentials stay in browser session storage. Never share them across
// tabs, documents or suppliers, and never promote a request before WB accepts it.
const STD = /^(access-control-[\w-]+|accept|accept-[\w-]+|content-type|content-length|cookie|user-agent|referer|origin|sec-[\w-]+|priority|cache-control|pragma|connection|host|dnt)$/i;
const AUTH_HOST = "seller-content.wildberries.ru", AUTH_TTL = 30 * 60000;
let authTabs = {};
const pendingAuth = new Map();
const authReady = chrome.storage.session.get("authV2").then(async (x) => {
  authTabs = x.authV2 || {};
  await chrome.storage.session.remove("auth"); // legacy global cache must not survive the update
});
function saveAuth() { return chrome.storage.session.set({authV2: authTabs}); }
function sellerSender(sender) {
  try {
    return Number.isInteger(sender.tab?.id) && sender.frameId === 0 && !!sender.documentId &&
      (!sender.documentLifecycle || sender.documentLifecycle === "active") &&
      new URL(sender.url).origin === "https://seller.wildberries.ru";
  } catch { return false; }
}
function authContext(sender, supplier) {
  if (!sellerSender(sender) || typeof supplier !== "string" || !supplier || supplier.length > 256) return null;
  const c = authTabs[sender.tab.id];
  return c && c.documentId === sender.documentId && c.supplier === supplier ? c : null;
}
async function setContext(sender, supplier) {
  if (!sellerSender(sender) || typeof supplier !== "string" || !supplier || supplier.length > 256) return false;
  if (!authContext(sender, supplier)) {
    authTabs[sender.tab.id] = {documentId: sender.documentId, supplier, generation: crypto.randomUUID(), saved: Date.now()};
    for (const [tab, c] of Object.entries(authTabs)) if (Date.now() - c.saved > AUTH_TTL) delete authTabs[tab];
    await saveAuth();
  }
  return true;
}
function sameHeaders(a, b) {
  const normalized = h => JSON.stringify(Object.entries(h).map(([k, v]) => [k.toLowerCase(), v]).sort());
  return normalized(a) === normalized(b);
}
chrome.webRequest.onSendHeaders.addListener(async (d) => {
  if (!sellerReq(d) || new URL(d.url).hostname !== AUTH_HOST || d.frameId !== 0) return;
  await authReady;
  const c = authTabs[d.tabId];
  if (!c || c.documentId !== d.documentId) return;
  const h = {};
  for (const x of d.requestHeaders || []) if (!STD.test(x.name) && x.value) h[x.name] = x.value;
  if (!Object.keys(h).some(n => /^(authorizev3|authorization)$/i.test(n))) return;
  pendingAuth.set(d.requestId, {tab: d.tabId, generation: c.generation, headers: h, started: d.timeStamp || Date.now()});
  if (pendingAuth.size > 512) pendingAuth.delete(pendingAuth.keys().next().value);
}, SELLER_FILTER, ["requestHeaders"]);
chrome.webRequest.onCompleted.addListener(async (d) => {
  await authReady;
  const p = pendingAuth.get(d.requestId); pendingAuth.delete(d.requestId);
  if (!p) return;
  const c = authTabs[p.tab];
  if (!c || c.generation !== p.generation) return;
  if (d.statusCode === 401 && c.entry && sameHeaders(c.entry.headers, p.headers)) {
    c.lastStarted = Math.max(c.lastStarted || 0, p.started);
    c.rejected = {headers: p.headers, before: Date.now()};
    delete c.entry;
    await saveAuth();
  } else if (d.statusCode >= 200 && d.statusCode < 300 && p.started >= (c.lastStarted || 0) &&
      !(c.rejected && p.started <= c.rejected.before && sameHeaders(c.rejected.headers, p.headers))) {
    // Replace the snapshot: do not mix an old AuthorizeV3/Seller-Lk with new headers.
    c.saved = Date.now();
    c.lastStarted = p.started;
    c.entry = {headers: p.headers, started: p.started, saved: c.saved, revision: crypto.randomUUID()};
    await saveAuth();
  }
}, SELLER_FILTER);
chrome.webRequest.onErrorOccurred.addListener(d => { pendingAuth.delete(d.requestId); }, SELLER_FILTER);
chrome.tabs.onRemoved.addListener(async tabId => { await authReady; delete authTabs[tabId]; await saveAuth(); });

async function recStop() {
  if (!rec) return { ok: false, data: { detail: "Запись не идёт" } };
  const r = rec; rec = null;
  clearTimeout(saveT);
  await chrome.storage.session.remove("rec");
  if (!r.items.length) return { ok: false, data: { detail: "Ничего не записалось — запросы кабинета не поймались" } };
  return api("/api/plugin/trace", { method: "POST", body: { page: r.page, items: r.items } });
}

chrome.runtime.onMessage.addListener((m, sender, reply) => {
  (async () => {
    await ready;
    if (m.type === "api") return reply(await api(m.path, m));
    if (m.type === "upload") {            // файл из кабинета (base64) → seller-analytics
      const bin = Uint8Array.from(atob(m.b64), (ch) => ch.charCodeAt(0));
      return reply(await serviceRequest(m.path, {method: "POST", headers: {"Content-Type": "application/octet-stream"}, body: bin}, 120000));
    }
    if (m.type === "rec_start") {
      rec = { start: Date.now(), page: m.page || "", items: [], byId: {} };
      await chrome.storage.session.set({ rec });
      return reply({ ok: true });
    }
    if (m.type === "fetch_bin") {          // скачать файл кабинета из фона (у фона нет ограничений CORS страницы)
      try {
        const u = new URL(m.url);
        if (!sellerSender(sender) || u.origin !== "https://downloads-content-analytics.wildberries.ru" ||
            !/^\/api\/v1\/file-manager\/download\/[\w-]+$/.test(u.pathname) || u.username || u.password || u.search || u.hash ||
            typeof m.downloadToken !== "string" || !m.downloadToken) return reply({ok: false, status: 0});
        const r = await fetch(u.href, { credentials: "omit", redirect: "error", signal: AbortSignal.timeout(60000), headers: {"x-download-token": m.downloadToken} });
        const ct = r.headers.get("content-type") || "";
        if (!r.ok || /json|html/.test(ct)) return reply({ ok: false, status: r.status, ctype: ct });
        const buf = new Uint8Array(await r.arrayBuffer());
        let s = "";
        for (let i = 0; i < buf.length; i += 0x8000) s += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        return reply({ ok: true, status: r.status, ctype: ct, b64: btoa(s) });
      } catch { return reply({ ok: false, err: "download_network" }); }
    }
    if (m.type === "seller_context") { await authReady; return reply({ok: await setContext(sender, m.supplier)}); }
    if (m.type === "auth_headers" || m.type === "auth_rejected") {
      await authReady;
      const c = authContext(sender, m.supplier);
      if (m.type === "auth_rejected") {
        if (c?.entry?.revision === m.revision) {
          c.rejected = {headers: c.entry.headers, before: Date.now()};
          delete c.entry; await saveAuth();
        }
        return reply({ok: true});
      }
      const a = c?.entry;
      return reply(a && m.host === AUTH_HOST && Date.now() - a.saved < AUTH_TTL
        ? {headers: a.headers, revision: a.revision} : {headers: {}});
    }
    if (m.type === "rec_stop") return reply(await recStop());
    if (m.type === "rec_state") return reply({ on: !!rec, n: rec ? rec.items.length : 0, min: rec ? Math.floor((Date.now() - rec.start) / 60000) : 0 });
    reply({ ok: false });
  })().catch(() => reply({ok: false, status: 0, data: {detail: "Нет связи с плагином или сервисом. Повторите позже."}}));
  return true;
});

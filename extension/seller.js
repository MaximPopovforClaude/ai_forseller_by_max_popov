// Плагин seller-analytics в кабинете продавца WB: автоскачивание отчёта «Точки входа» по дням в seller-analytics .
// Те же запросы, что делает сам кабинет при «Скачать» (записаны 29.10): заказать отчёт → дождаться → взять ключ скачивания → скачать xlsx.
// Работает в сессии пользователя: пароли, cookie и ключи кабинета никуда не отправляются — в seller-analytics уходит только сам отчёт.
(() => {
  const BASE = "https://seller-content.wildberries.ru/ns/analytics-api/content-analytics/api/v1/file-manager";
  const TOKENS = "https://seller-content.wildberries.ru/ns/suppliers-auth-tokens/suppliers-portal-core/api/v1/tokensjrpc";
  const DL = "https://downloads-content-analytics.wildberries.ru/api/v1/file-manager/download/";
  const TYPE = "CUSTOMER_PROFILE_ENTRY_POINTS_REPORT_V2";
  const BACK_DAYS = 30, PER_RUN = 7, EVERY_MIN = 60;

  const send = (m) => new Promise((resolve, reject) => chrome.runtime.sendMessage(m, r => {
    if (chrome.runtime.lastError || !r) reject(new Error("Нет связи с плагином. Обновите вкладку кабинета после обновления расширения."));
    else resolve(r);
  }));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const diag = [];
  const note = (step, x) => diag.push({ t: new Date().toISOString(), method: "DIAG", url: step, body: x });

  function toast(text, bad) {
    let d = document.getElementById("mc100-toast");
    if (!d) {
      d = document.createElement("div");
      d.id = "mc100-toast";
      d.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:2147483000;max-width:360px;padding:8px 12px;border-radius:10px;" +
        "font:13px/1.4 system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.18);cursor:pointer";
      d.onclick = () => d.remove();
      document.body.append(d);
    }
    d.style.background = bad ? "#fef2f2" : "#f5f3ff";
    d.style.color = bad ? "#991b1b" : "#4c1d95";
    d.textContent = "seller-analytics: " + text;
  }
  function supplierKey() {
    const m = document.cookie.match(/(?:^|;\s*)x-supplier-id-external=([^;]+)/);
    try { return m ? decodeURIComponent(m[1]) : "default"; } catch { return "default"; }
  }
  // поиск в ответе без знания точной схемы: объект с нашим id / первая строка под ключом *token*
  function findById(o, id) {
    if (!o || typeof o !== "object") return null;
    if (o.id === id) return o;
    for (const v of Object.values(o)) { const r = findById(v, id); if (r) return r; }
    return null;
  }
  function findToken(o) {
    if (!o || typeof o !== "object") return null;
    for (const [k, v] of Object.entries(o)) {
      if (/token/i.test(k) && typeof v === "string" && v.length > 10) return v;
      const r = findToken(v); if (r) return r;
    }
    return null;
  }
  const AUTH_HELP = "откройте «Аналитика» → «Портрет покупателя» → «Точки входа» в этом кабинете WB, дождитесь загрузки и нажмите «Скачать сейчас». Если WB просит войти, войдите заново";
  let AUTH = {}, revision = "", supplier = "", running = false;
  function checkSupplier() {
    if (supplierKey() !== supplier) throw new Error("выбран другой кабинет WB. Дождитесь его загрузки и нажмите «Скачать сейчас» заново");
  }
  async function loadAuth() {
    checkSupplier();
    const a = await send({ type: "auth_headers", host: "seller-content.wildberries.ru", supplier });
    checkSupplier();
    AUTH = a.headers || {}; revision = a.revision || "";
    return !!revision && Object.keys(AUTH).length > 0;
  }
  async function j(stage, url, opt = {}) {
    for (let attempt = 0; attempt < 2; attempt++) {
      checkSupplier();
      if (!(await loadAuth())) throw new Error(`${stage}: нет действующей сессии WB — ${AUTH_HELP}`);
      const used = revision;
      let r;
      try { r = await fetch(url, { credentials: "include", redirect: "error", signal: AbortSignal.timeout(30000), ...opt, headers: { "Content-Type": "application/json", ...AUTH } }); }
      catch { throw new Error(`${stage}: нет связи с WB. Повторите скачивание позже`); }
      note(stage, {status: r.status, attempt});
      checkSupplier();
      if (r.status === 401) {
        await send({type: "auth_rejected", supplier, revision: used});
        AUTH = {}; revision = "";
        if (!attempt) {
          toast("WB отклонил сессию. Жду её обновления кабинетом…");
          let fresh = false;
          for (let i = 0; i < 20; i++) {
            await sleep(500);
            if (await loadAuth()) { fresh = true; break; }
          }
          if (fresh) continue; // exactly one retry, with the original report id/body
        }
        throw new Error(`${stage}: WB отклонил сессию (401) — ${AUTH_HELP}`);
      }
      if (r.status === 403) throw new Error(`${stage}: WB не разрешил доступ к отчёту (403). Проверьте права сотрудника на аналитику в кабинете WB`);
      if (!r.ok) throw new Error(`${stage}: WB вернул HTTP ${r.status}. Повторите позже`);
      try { return await r.json(); } catch { throw new Error(`${stage}: WB вернул ответ в неизвестном формате`); }
    }
  }

  async function oneDay(day) {
    const id = crypto.randomUUID();
    const params = { nmsIDs: [], tagIds: [], endDate: day, orderBy: { mode: "desc", field: "addToCart" }, startDate: day,
                     brandNames: [], subjectIDs: [], vendorCodes: [] };
    await j("заказ отчёта", BASE + "/download", { method: "POST", body: JSON.stringify({ id, params, reportType: TYPE, userReportName: "seller-analytics " + day }) });
    let complete = false;
    const deadline = Date.now() + 180000;
    for (let i = 0; i < 60 && Date.now() < deadline; i++) {
      await sleep(3000);
      if (Date.now() >= deadline) break;
      const l = await j("ожидание отчёта", BASE + "/downloads?report_types=" + TYPE);
      const it = findById(l, id);
      const st = it ? String(it.status || it.state || "") : "";
      if (/SUCC|DONE|READY|COMPLET/i.test(st)) { complete = true; break; }
      if (/FAIL|ERR|CANCEL/i.test(st)) throw new Error("WB не смог собрать отчёт. Повторите позже");
    }
    if (!complete) throw new Error("WB не подготовил отчёт за отведённое время. Повторите скачивание позже");
    const t = await j("ключ скачивания", TOKENS, { method: "POST", body: JSON.stringify({ id: "json-rpc_" + Date.now(), method: "generateToken", params: { team: "content-analytics" }, jsonrpc: "2.0" }) });
    const tok = t && !t.error && findToken(t);
    if (!tok) throw new Error("WB не выдал ключ скачивания отчёта. Проверьте доступ к аналитике в кабинете WB");
    checkSupplier();
    // The recorded WB protocol uses x-download-token, not the seller session.
    // Background fetch avoids page CORS; destination and redirects are restricted there.
    const r = await send({type: "fetch_bin", url: DL + id, downloadToken: tok});
    note("скачивание", {status: r.status, ok: !!r.ok});
    if (r.ok) return r.b64;
    throw new Error(`скачивание файла: ${r.status ? "WB вернул HTTP " + r.status : "нет связи с WB"}. Повторите позже`);
  }

  async function collect(force) {
    const k = supplier = supplierKey();
    await send({type: "seller_context", supplier});
    const store = await chrome.storage.local.get(["token", "entry_auto", "entry_map", "entry_last"]);
    if (!store.token) return;
    if (store.entry_auto === false && !force) return;
    const last = (store.entry_last || {})[k] || 0;
    if (!force && Date.now() - last < EVERY_MIN * 60000) return;
    const map = store.entry_map || {};
    const have = await send({ type: "api", path: "/api/plugin/entry_days" });
    if (!have.ok) { toast((have.data && have.data.detail) || "нет связи с seller-analytics", true); return; }
    const shop = k === "default" ? null : map[k];
    const got = new Set(shop ? (have.data.days[shop] || []) : []);
    const todo = [];
    // Server dates use Moscow time, matching analytics rather than the browser timezone.
    const expected = have.data.expected_days || Array.from({ length: BACK_DAYS }, (_, i) =>
      new Date(Date.now() + 3 * 3600000 - (i + 1) * 86400000).toISOString().slice(0, 10));
    for (const day of expected.slice(0, shop ? BACK_DAYS : 1)) {
      if (!got.has(day)) todo.push(day);
    }
    if (!todo.length) { await markLast(k); if (force) toast(`точки входа загружены за ${expected[expected.length - 1]} — ${expected[0]} (магазин ${shop}); готовность ИИ-разбора проверяется отдельно`); return; }
    if (!(await loadAuth())) {
      toast(AUTH_HELP, true);
      return;
    }
    let ok = 0;
    for (const day of todo.slice(0, PER_RUN)) {
      try {
        toast(`скачиваю «Точки входа» за ${day}…`);
        const b64 = await oneDay(day);
        checkSupplier();
        const r = await send({ type: "upload", path: `/api/plugin/entry/0?name=${encodeURIComponent("entry_" + day + ".xlsx")}`, b64 });
        if (!r.ok) throw new Error((r.data && r.data.detail) || `HTTP ${r.status}`);
        if (k !== "default") {
          const current = (await chrome.storage.local.get("entry_map")).entry_map || {};
          await chrome.storage.local.set({ entry_map: {...current, [k]: r.data.shop_id} });
        }
        ok++;
        toast(`«Точки входа» за ${day} → ${r.data.shop} (${r.data.rows} строк)`);
      } catch (e) {
        toast(`точки входа за ${day}: ${e.message}`, true);
        return;
      }
      await sleep(5000);
    }
    if (ok) await markLast(k);
    if (ok) toast(`«Точки входа»: загружено дней — ${ok}${todo.length > PER_RUN ? `, остальные докачаю позже` : ""}`);
  }

  async function markLast(k) {
    const current = (await chrome.storage.local.get("entry_last")).entry_last || {};
    await chrome.storage.local.set({entry_last: {...current, [k]: Date.now()}});
  }
  async function run(force) {
    if (running) return;
    running = true; diag.length = 0;
    try { await collect(force); }
    catch (e) { toast(e.message || "Не удалось скачать отчёты. Повторите позже", true); }
    finally {
      try {
        if (diag.length) await send({type: "api", path: "/api/plugin/trace", method: "POST",
          body: {page: "diag:entry v0.2.8", items: diag.splice(0)}});
      } catch { /* diagnostics must not prevent the next manual attempt */ }
      running = false; AUTH = {}; revision = "";
    }
  }

  chrome.runtime.onMessage.addListener((m, _s, reply) => {
    if (m.type === "entry_now") { const busy = running; void run(true); reply({ ok: true, busy }); }
  });
  // Register the document before WB's first API request; no DOM work at document_start.
  void send({type: "seller_context", supplier: supplierKey()}).catch(() => {});
  setTimeout(() => run(false), 8000);                    // кабинет открыт — раз в час проверить, есть ли вчерашний день
  setInterval(() => run(false), 15 * 60000);
})();

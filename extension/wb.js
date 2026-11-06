// Плагин seller-analytics на витрине WB: на карточке товара — панель с полками и нашими данными (если товар наш).
(() => {
  function productId() {
    return location.origin === "https://www.wildberries.ru" ? location.pathname.match(/^\/catalog\/([1-9]\d*)\/detail\.aspx$/)?.[1] || null : null;
  }
  // A route may have changed while the background script was preparing injection.
  if (!productId()) return;
  if (globalThis.__mc100CardPanel) { globalThis.__mc100CardPanel(); return; }
  const send = (m) => new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(m, (r) => {
        const error = chrome.runtime.lastError;
        resolve(error || !r ? { ok: false, data: { detail: "Нет связи с плагином. Обновите вкладку после обновления расширения." } } : r);
      });
    } catch {
      resolve({ ok: false, data: { detail: "Плагин обновлён. Обновите эту вкладку." } });
    }
  });
  const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
  let shown = null, minimized = false, generation = 0;

  function el(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else if (k.startsWith("on")) e[k] = v; else e.setAttribute(k, v);
    }
    for (const k of kids) if (k) e.append(k);
    return e;
  }
  function panel() {
    let p = document.getElementById("mc100-panel");
    if (!p) {
      p = el("div", { id: "mc100-panel" });
      document.body.append(p);
    }
    p.classList.toggle("mc-min", minimized);
    return p;
  }
  function head(title) {
    return el("div", { class: "mc-h", onclick: () => { minimized = !minimized; panel(); } }, el("b", { text: title }), el("span", { text: minimized ? "▢" : "—" }));
  }
  function move(c) {
    if (c.pos == null || c.pos_was === undefined) return null;
    if (c.pos_was == null) return el("span", { class: "mc-up", text: " новый" });
    const d = c.pos_was - c.pos;
    return d ? el("span", { class: d > 0 ? "mc-up" : "mc-down", text: ` ${d > 0 ? "↑" : "↓"}${Math.abs(d)}` }) : null;
  }
  function row(c, hasWas) {
    const name = `${c.brand ? c.brand + " · " : ""}${(c.name || "").slice(0, 45)}`;
    return el("div", { class: "mc-row" + (c.ours ? " mc-ours" : "") },
      el("span", { class: "mc-pos", text: String(c.pos ?? "") }),
      c.photo ? el("img", { src: c.photo, loading: "lazy" }) : null,
      el("div", {}, el("a", { href: `https://www.wildberries.ru/catalog/${c.nm_id}/detail.aspx`, text: name || String(c.nm_id) }),
        el("div", { class: "mc-hint", text: `${c.price != null ? nf.format(c.price) + " ₽" : ""}${c.rating ? " · ★" + c.rating : ""}${c.ours ? " · наш" : ""}` }),
        hasWas ? move(c) : null));
  }

  function render(nm, r) {
    const p = panel();
    p.replaceChildren(head("seller-analytics · " + nm));
    const b = el("div", { class: "mc-b" });
    p.append(b);
    if (!r.ok) {
      b.append(el("div", { class: "mc-hint", text: (r.data && r.data.detail) || `Ошибка ${r.status}` }));
      return;
    }
    const d = r.data, o = d.own, s = d.shelves;
    if (o) {
      b.append(el("div", { class: "mc-sec", text: `Наш товар · ${o.shop}` }),
        el("div", { text: `${o.vendor_code || ""} · ${o.subject || ""}` }));
      const sc = o.showcase;
      if (sc) b.append(el("div", { class: "mc-hint", text: `Витрина: ${nf.format(sc.price)} ₽${sc.spp != null ? `, СПП ${sc.spp} %` : ""}` }));
      if (o.mrc) b.append(el("div", { class: sc && sc.price < o.mrc ? "mc-down" : "mc-hint", text: `МРЦ: ${nf.format(o.mrc)} ₽${sc && sc.price < o.mrc ? " — ⚠️ ниже МРЦ" : ""}` }));
    }
    if (!s) {
      b.append(el("div", { class: "mc-hint", text: "Полки ещё не собирались." }));
      return;
    }
    const hasWas = !!s.was_day;
    b.append(el("div", { class: "mc-sec", text: "У кого в полках «Смотрите также»" }),
      el("div", {}, el("span", { class: "mc-big", text: String(s.where_n) }), el("span", { class: "mc-hint", text: ` карточек · снимок ${new Date(s.day).toLocaleDateString("ru-RU")}` })));
    if (s.hist && s.hist.length > 1) {
      const max = Math.max(1, ...s.hist.map((h) => h.n));
      const bars = el("div", { class: "mc-bars" });
      for (const h of s.hist) { const x = el("div", { title: `${new Date(h.day).toLocaleDateString("ru-RU")}: ${h.n}` }); x.style.height = `${(h.n / max) * 100}%`; bars.append(x); }
      b.append(bars);
    }
    if (!s.where_n) b.append(el("div", { class: "mc-hint", text: "Среди снятых карточек ни у кого в полке (топ-100) не найден." }));
    for (const c of s.where.slice(0, 10)) b.append(row(c, hasWas));
    b.append(el("div", { class: "mc-sec", text: "Кто в полке у этого товара" }));
    if (!s.taken) b.append(el("div", { class: "mc-hint", text: "Полку этой карточки мы ещё не снимали." }));
    for (const c of s.shelf.slice(0, 10)) b.append(row(c, hasWas));
    b.append(el("div", { class: "mc-hint", text: "Полностью — platform.example.org → вкладка «Полки»." }));
  }

  async function tick() {
    const nm = productId();
    if (nm === shown) return;
    shown = nm;
    const current = ++generation;
    const old = document.getElementById("mc100-panel");
    if (!nm) { if (old) old.remove(); return; }
    const p = panel();
    p.replaceChildren(head("seller-analytics · " + nm), el("div", { class: "mc-b mc-hint", text: "Загрузка…" }));
    const r = await send({ type: "api", path: `/api/plugin/card/${nm}` });
    if (generation === current && shown === nm && productId() === nm) render(nm, r);
  }
  globalThis.__mc100CardPanel = tick;
  // Observe completed history entry changes; never intercept navigation, patch
  // history, change location, or poll the storefront on an interval.
  navigation.addEventListener("currententrychange", tick);
  tick();
})();

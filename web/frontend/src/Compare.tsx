import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { api, http } from "./api";
import { Logo } from "./Logo";
import { Slides } from "./PhotoFunnel";

type M = { cur: number | string | null; prev: number | string | null };
type Card = { nm_id: number; title?: string; brand?: string; subject?: string; category?: string; created?: string; metrics: Record<string, M> };
type Q = { query: string; nm_id: number; freq: number | null; pos: number | null; clicks: number | null; carts: number | null; orders: number | null;
  conv_cart: number | null; conv_order: number | null; prev_pos: number | null; prev_clicks: number | null; prev_orders: number | null };
type Brief = { id: number; uploaded_at: string; file_name: string | null; period_from: string | null; period_to: string | null; nm_ids: number[];
  is_public: boolean; photos: Record<string, string | null>; titles: Record<string, string | undefined>; brands: Record<string, string | undefined>; seen?: boolean;
  author?: string };
type Quota = { shared: number; allowed: number; used: number; left: number };
type Full = Brief & { data: { cards: Card[]; metric_order: string[]; queries: Q[]; period: { from: string; to: string } | null;
  prev_period: { from: string; to: string } | null }; own: boolean; team_author: string | null; saved: boolean; slides: Record<string, string[]>; mine_nm: number | null; ai_text: string | null; client: boolean; quota: Quota };
type Sub = { nm_id: number; created_at: string; n: number };
type Lists = { mine: Brief[]; team: Brief[]; saved: Brief[]; subs: Sub[]; seen: Brief[]; quota: Quota; client: boolean };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const d = (s: string | null | undefined) => (s ? s.slice(0, 10).split("-").reverse().join(".") : "");
const n = (v: unknown) => (typeof v === "number" ? nf.format(v) : v == null ? "—" : String(v));
const LOWER_BETTER = /отмен|позиция|время доставки/i;
const NO_BEST = /статус продвижения|рейтинг карточки/i;
const wb = (nm: number) => `https://www.wildberries.ru/catalog/${nm}/detail.aspx`;

function Thumb({ src, nm }: { src?: string | null; nm: number }) {
  return src ? <img className="cmp-ph" src={src} alt="" loading="lazy" /> : <div className="cmp-ph none">{nm}</div>;
}

function Landing() {
  const [reg, setReg] = useState<string | null>(null);
  const [email, setEmail] = useState(""), [pw, setPw] = useState(""), [err, setErr] = useState("");
  useEffect(() => { http.get<{ bot_link: string | null }>("/api/ref/-").then((r) => setReg(r.bot_link)).catch(() => undefined); }, []);
  return (
    <div className="cmp-land">
      <Logo kind="vertical" height={110} />
      <h1>Сравнение карточек WB — бесплатно и навсегда</h1>
      <p>WB продаёт отчёт «Сравнение карточек» (2–5 артикулов), но хранит его 5 дней и отдаёт в неудобном Excel. Загрузите файл сюда —
        и смотрите сравнение наглядно в любой момент: воронка, цены, рейтинг, позиции и все поисковые запросы по каждой карточке.</p>
      <ul>
        <li>📊 Наглядно: лучшее и худшее значение в каждой строке, динамика к прошлому периоду.</li>
        <li>🔎 Поисковые запросы: где конкуренты выше вас и по каким запросам забирают переходы.</li>
        <li>🤝 Обмен: откройте свои сравнения — и смотрите чужие по любому артикулу (2 чужих за каждое своё).</li>
        <li>🤖 Клиентам Seller Analytics — ИИ-разбор сравнения.</li>
      </ul>
      <form className="cmp-login" onSubmit={async (e) => { e.preventDefault(); setErr("");
        try { await api.login(email, pw); window.location.reload(); } catch (x) { setErr((x as Error).message === "401" ? "Неверный логин или пароль" : (x as Error).message); } }}>
        <b>Войти</b>
        <input placeholder="E-mail" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input placeholder="Пароль" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
        <button>Войти</button>
        {err && <div className="err">{err}</div>}
        {reg && <a className="reg-link" href={reg} target="_blank" rel="noreferrer">Нет аккаунта? Регистрация за минуту в Telegram →</a>}
      </form>
    </div>
  );
}

function Charts({ c }: { c: Full }) {
  const cards = c.data.cards;
  const numeric = c.data.metric_order.filter((l) => cards.some((k) => typeof k.metrics[l]?.cur === "number"));
  const [metric, setMetric] = useState(numeric.includes("Заказы, шт") ? "Заказы, шт" : numeric[0]);
  const [qn, setQn] = useState(10);
  const dark = document.documentElement.dataset.theme === "dark";
  const txt = dark ? "#e6e8ee" : "#1d2330";
  const names = cards.map((k) => `${k.brand || ""}\n${k.nm_id}`);
  const opt = {
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: txt } }, grid: { left: 60, right: 20, top: 40, bottom: 50 },
    xAxis: { type: "category", data: names, axisLabel: { color: txt } }, yAxis: { type: "value", axisLabel: { color: txt } },
    series: [
      { name: `${d(c.data.period?.from)}–${d(c.data.period?.to)}`, type: "bar", data: cards.map((k) => k.metrics[metric]?.cur ?? null), itemStyle: { color: "#7c3aed" },
        label: { show: true, position: "top", color: txt } },
      { name: `прошлый период`, type: "bar", data: cards.map((k) => (typeof k.metrics[metric]?.prev === "number" ? k.metrics[metric]?.prev : null)), itemStyle: { color: "#a5b4fc" } },
    ],
  };
  const top: Record<string, { freq: number; per: Record<number, number> }> = {};
  for (const q of c.data.queries) { top[q.query] ||= { freq: Number(q.freq || 0), per: {} }; top[q.query].per[q.nm_id] = Number(q.clicks || 0); }
  const tq = Object.entries(top).sort((a, b) => b[1].freq - a[1].freq).slice(0, qn);
  const COLORS = ["#7c3aed", "#16a34a", "#ea580c", "#0891b2", "#db2777"];
  const opt2 = {
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: txt } }, grid: { left: 200, right: 20, top: 40, bottom: 20 },
    yAxis: { type: "category", data: tq.map(([q]) => q).reverse(), axisLabel: { color: txt, width: 190, overflow: "truncate" } },
    xAxis: { type: "value", axisLabel: { color: txt } },
    series: cards.map((k, i) => ({ name: `${k.brand || ""} ${k.nm_id}`, type: "bar", data: tq.map(([, v]) => v.per[k.nm_id] ?? 0).reverse(), itemStyle: { color: COLORS[i % 5] } })),
  };
  return (
    <div className="acc-box">
      <div className="board-bar"><b>График</b>
        <select value={metric} onChange={(e) => setMetric(e.target.value)}>{numeric.map((l) => <option key={l} value={l}>{l}</option>)}</select>
        <span className="hint">карточки рядом, текущий и прошлый период</span></div>
      <ReactECharts option={opt} style={{ height: 320 }} notMerge />
      <div className="board-bar"><b>Переходы из поиска по главным запросам</b>
        <select value={qn} onChange={(e) => setQn(Number(e.target.value))}>{[10, 20, 30].map((x) => <option key={x} value={x}>топ-{x} по частотности</option>)}</select></div>
      <ReactECharts option={opt2} style={{ height: Math.max(300, qn * 26) }} notMerge />
    </div>
  );
}

function Viewer({ id, onBack }: { id: number; onBack: () => void }) {
  const [c, setC] = useState<Full | null>(null);
  const [err, setErr] = useState("");
  const [qf, setQf] = useState(""), [minFreq, setMinFreq] = useState(1000), [lose, setLose] = useState(false), [limit, setLimit] = useState(100);
  const [ai, setAi] = useState<string | null>(null), [aiBusy, setAiBusy] = useState(false), [aiErr, setAiErr] = useState("");
  useEffect(() => { http.get<Full>(`/api/compare/${id}`).then((x) => { setC(x); setAi(x.ai_text); }).catch((e) => setErr(e.message)); }, [id]);
  const pivot = useMemo(() => {
    if (!c) return [];
    const by: Record<string, { query: string; freq: number; per: Record<number, Q> }> = {};
    for (const q of c.data.queries) {
      const k = q.query;
      by[k] ||= { query: k, freq: Number(q.freq || 0), per: {} };
      by[k].per[q.nm_id] = q;
      by[k].freq = Math.max(by[k].freq, Number(q.freq || 0));
    }
    const first = c.nm_ids[0];
    return Object.values(by).filter((r) => r.freq >= minFreq && (!qf || r.query.includes(qf.toLowerCase())) && (!lose || (() => {
      const mine = r.per[first]?.pos;
      return c.nm_ids.slice(1).some((nm) => r.per[nm]?.pos != null && (mine == null || Number(r.per[nm].pos) < Number(mine)));
    })())).sort((a, b) => b.freq - a.freq);
  }, [c, qf, minFreq, lose]);
  if (err) return <div className="cmp"><button className="link" onClick={onBack}>← к списку</button><div className="err">{err}</div></div>;
  if (!c) return <div className="hint">Загрузка…</div>;
  const cards = c.data.cards;
  const best = (label: string) => {
    if (NO_BEST.test(label)) return { hi: null, lo: null };
    const vals = cards.map((k) => k.metrics[label]?.cur).filter((v): v is number => typeof v === "number");
    if (vals.length < 2) return { hi: null, lo: null };
    const mx = Math.max(...vals), mn = Math.min(...vals);
    return LOWER_BETTER.test(label) ? { hi: mn, lo: mx } : { hi: mx, lo: mn };
  };
  const posCls = (p: number | null | undefined) => (p == null ? "" : p <= 10 ? "p-top" : p <= 50 ? "p-mid" : "p-low");
  const fun = (k: Card) => ["Показы", "Переходы в карточку, шт", "Добавления в корзину, шт", "Заказы, шт", "Выкупы, шт"].map((l) => Number(k.metrics[l]?.cur || 0));
  const maxShow = Math.max(...cards.map((k) => fun(k)[0] || 0), 1);
  return (
    <div className="cmp">
      <div className="board-bar">
        <button className="link" onClick={onBack}>← к списку</button>
        <b>Период {d(c.data.period?.from)}–{d(c.data.period?.to)}</b>
        <span className="hint">прошлый: {d(c.data.prev_period?.from)}–{d(c.data.prev_period?.to)} · загружено {new Date(c.uploaded_at).toLocaleDateString("ru-RU")}</span>
        {c.team_author && <span className="badge" title="Сравнение загрузил коллега по кабинету — видно всей команде, лимит не тратится">команда: {c.team_author}</span>}
        {!c.own && !c.team_author && <button onClick={() => (c.saved ? http.del(`/api/compare/${id}/save`) : http.post<{ ai_started: boolean }>(`/api/compare/${id}/save`))
          .then((x) => { setC({ ...c, saved: !c.saved }); if (!c.saved && (x as { ai_started?: boolean })?.ai_started) setAiErr("Добавлено. Нейросеть делает разбор — обновите страницу через минуту."); })
          .catch((e) => setAiErr(e.message))}>{c.saved ? "★ В моих (убрать)" : "☆ Добавить к себе"}</button>}
        {c.own && <label title="Другие смогут найти его по артикулу; вы — смотреть чужие (2 за каждое своё открытое)">
          <input type="checkbox" checked={c.is_public} onChange={(e) => http.put(`/api/compare/${id}/public`, { is_public: e.target.checked })
            .then(() => setC({ ...c, is_public: e.target.checked }))} /> открыть для других</label>}
      </div>
      <div className="cmp-cards">
        {cards.map((k, i) => (
          <a key={k.nm_id} className={"cmp-card" + (((c.own || c.team_author) && i === 0) || c.mine_nm === k.nm_id ? " first" : "")} href={wb(k.nm_id)} target="_blank" rel="noreferrer">
            <Thumb src={c.photos[String(k.nm_id)]} nm={k.nm_id} />
            <div><b>{k.brand || "—"}</b>{(((c.own || c.team_author) && i === 0) || c.mine_nm === k.nm_id) && <span className="badge">ваша</span>}<div className="hint">{k.nm_id} · создана {k.created || "—"}</div>
              <div className="cmp-t">{k.title}</div></div>
          </a>
        ))}
      </div>
      <div className="acc-box">
        <b>Фотоворонка на момент загрузки (первые 7 фото)</b>
        {cards.map((k) => (
          <div key={k.nm_id} className="pf-row"><span className="cmp-fn">{k.brand || k.nm_id}</span>
            {c.slides?.[String(k.nm_id)] ? <Slides hashes={c.slides[String(k.nm_id)]} small /> : <span className="hint">слепок снимается, обновите страницу через минуту</span>}</div>))}
      </div>
      <div className="acc-box">
        <b>Воронка за период</b>
        {cards.map((k) => { const f = fun(k); return (
          <div key={k.nm_id} className="cmp-fun"><span className="cmp-fn">{k.brand || k.nm_id}</span>
            <div className="cmp-bar"><div style={{ width: `${(f[0] / maxShow) * 100}%` }} /></div>
            <span className="hint">показы {nf.format(f[0])} → переходы {nf.format(f[1])} ({f[0] ? nf.format(f[1] / f[0] * 100) : 0} %) → корзина {nf.format(f[2])} ({f[1] ? nf.format(f[2] / f[1] * 100) : 0} %) → заказы {nf.format(f[3])} ({f[2] ? nf.format(f[3] / f[2] * 100) : 0} %) → выкупы {nf.format(f[4])}</span>
          </div>); })}
      </div>
      <Charts c={c} />
      <div className="board-wrap"><table className="board-t cmp-t1">
        <thead><tr><th className="sx c1">Показатель</th>{cards.map((k) => <th key={k.nm_id}>{k.brand || k.nm_id}<div className="hint">{k.nm_id}</div></th>)}</tr></thead>
        <tbody>{c.data.metric_order.map((l) => { const b = best(l); return (
          <tr key={l}><td className="sx c1">{l}</td>{cards.map((k) => {
            const m = k.metrics[l] || { cur: null, prev: null };
            const cls = typeof m.cur === "number" && b.hi != null && m.cur === b.hi ? " best" : typeof m.cur === "number" && b.lo != null && m.cur === b.lo ? " worst" : "";
            const ch = typeof m.cur === "number" && typeof m.prev === "number" && m.prev ? (m.cur / m.prev - 1) * 100 : null;
            const good = ch == null ? null : LOWER_BETTER.test(l) ? ch < 0 : ch > 0;
            return <td key={k.nm_id} className={"n" + cls}>{n(m.cur)}{ch != null && Math.abs(ch) >= 1 && <div className={good ? "up" : "down"}>{ch > 0 ? "+" : ""}{nf.format(ch)} %</div>}</td>;
          })}</tr>); })}</tbody>
      </table></div>
      <div className="acc-box">
        <b>🤖 ИИ-разбор сравнения</b>
        {ai ? <pre className="cmp-ai">{ai}</pre> : c.client
          ? <button disabled={aiBusy} onClick={() => { setAiBusy(true); http.post<{ ai_text: string }>(`/api/compare/${id}/ai`).then((x) => setAi(x.ai_text))
            .catch((e) => setAiErr(e.message)).finally(() => setAiBusy(false)); }}>{aiBusy ? "Разбираю… (до минуты)" : "Сделать ИИ-разбор"}</button>
          : <div className="hint">Доступно клиентам Seller Analytics: подключите магазин WB — и нейросеть разберёт, где вы проигрываете и что сделать.</div>}
        {aiErr && <div className="err">{aiErr}</div>}
      </div>
      <div className="board-bar">
        <b>Поисковые запросы</b>
        <input className="q" placeholder="Фильтр по запросу" value={qf} onChange={(e) => setQf(e.target.value)} />
        <label>частотность от <input className="w80" value={minFreq} onChange={(e) => setMinFreq(Number(e.target.value) || 0)} /></label>
        {(c.own || c.team_author) && <label><input type="checkbox" checked={lose} onChange={(e) => setLose(e.target.checked)} /> только где ваша карточка ниже конкурентов</label>}
        <span className="hint">{pivot.length} запросов · позиция: <span className="p-top">1–10</span> <span className="p-mid">11–50</span> <span className="p-low">51+</span></span>
      </div>
      <div className="board-wrap"><table className="board-t cmp-q">
        <thead><tr><th className="sx c1">Запрос</th><th>Частотность</th>{cards.map((k) => <th key={k.nm_id}>{k.brand || k.nm_id}<div className="hint">поз. · перех. · заказы</div></th>)}</tr></thead>
        <tbody>{pivot.slice(0, limit).map((r) => (
          <tr key={r.query}><td className="sx c1">{r.query}</td><td className="n">{nf.format(r.freq)}</td>
            {cards.map((k) => { const q = r.per[k.nm_id]; return q ? (
              <td key={k.nm_id} className="n"><span className={"pos " + posCls(q.pos)}>{q.pos ?? "—"}</span> · {n(q.clicks)} · {n(q.orders)}
                {q.prev_pos != null && q.pos != null && q.prev_pos !== q.pos && q.prev_pos > 0 && <span className={q.pos < q.prev_pos ? "up" : "down"}> {q.pos < q.prev_pos ? "▲" : "▼"}{Math.abs(q.prev_pos - q.pos)}</span>}
              </td>) : <td key={k.nm_id} className="n hint">нет</td>; })}
          </tr>))}</tbody>
      </table></div>
      {pivot.length > limit && <button className="link" onClick={() => setLimit(limit + 200)}>показать ещё ({pivot.length - limit})</button>}
    </div>
  );
}

export function ComparePage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const idFromPath = () => Number(window.location.pathname.match(/^\/compare\/(\d+)/)?.[1]) || null;
  const [id, setId] = useState<number | null>(idFromPath);
  const [list, setList] = useState<Lists | null>(null);
  const [subNm, setSubNm] = useState("");
  const [found, setFound] = useState<Brief[] | null>(null);
  const [nm, setNm] = useState("");
  const [msg, setMsg] = useState(""), [err, setErr] = useState(""), [busy, setBusy] = useState(false);
  const load = () => http.get<Lists>("/api/compare/mine").then((x) => { setList(x); setAuthed(true); })
    .catch((e) => (e.message === "401" ? setAuthed(false) : setErr(e.message)));
  useEffect(() => { load(); const f = () => setId(idFromPath()); window.addEventListener("popstate", f); return () => window.removeEventListener("popstate", f); }, []);
  const go = (x: number | null) => { window.history.pushState(null, "", x ? `/compare/${x}` : "/compare"); setId(x); if (!x) load(); };
  if (authed === false) return <div className="cmp-wrap"><Landing /></div>;
  if (authed === null) return <div className="center">Загрузка…</div>;
  if (id) return <div className="cmp-wrap"><Viewer id={id} onBack={() => go(null)} /></div>;
  const upload = async (f: File) => {
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await fetch(`/api/compare/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f, credentials: "same-origin",
        headers: { "Content-Type": "application/octet-stream" } });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      if (j.repeat) {   // то же сравнение уже есть в базе у другого пользователя: у вас сохранено, но лимит не растёт
        setMsg("Сравнение сохранено у вас. Такое же (те же карточки и период) уже есть в базе, поэтому лимит просмотров чужих сравнений оно не увеличит.");
        load();
        return;
      }
      if (j.duplicate) setMsg(j.team ? "Это сравнение уже загрузил коллега по кабинету — открываю" : "Это сравнение у вас уже загружено — открываю");
      go(j.id);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const Item = ({ b }: { b: Brief }) => (
    <div className="cmp-item" onClick={() => go(b.id)}>
      <div className="cmp-ims">{b.nm_ids.map((x) => <Thumb key={x} src={b.photos[String(x)]} nm={x} />)}</div>
      <div><b>{d(b.period_from)}–{d(b.period_to)}</b> · {b.nm_ids.length} карточек{b.is_public && <span className="badge">открыто</span>}
        {b.author && <span className="badge">{b.author}</span>}
        <div className="hint">{b.nm_ids.map((x) => `${b.brands[String(x)] || ""} ${x}`).join(" · ")}</div></div>
    </div>
  );
  return (
    <div className="cmp-wrap"><div className="cmp">
      <div className="board-bar"><a href="/" title="На главную"><Logo kind="horizontal" height={30} /></a><h2 style={{ margin: 0 }}>Сравнение карточек</h2></div>
      <label className={"cmp-drop" + (busy ? " busy" : "")} onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) upload(f); }}>
        <input type="file" accept=".xlsx,.zip" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        {busy ? "Загружаю и разбираю…" : <>📥 Перетащите сюда файл «Сравнение карточек» из ЛК WB (xlsx или zip) или нажмите, чтобы выбрать</>}
      </label>
      {msg && <div className="ok">{msg}</div>}{err && <div className="err">{err}</div>}
      {list && <>
        <div className="acc-box">
          <b>Чужие сравнения</b>
          <div className="hint">Открыто ваших: {list.quota.shared} → можно посмотреть {list.quota.allowed} чужих, осталось {list.quota.left}. Откройте сравнение галочкой «открыть для других». Повторная загрузка того же сравнения (те же карточки и период) лимит не увеличивает.</div>
          <div className="acc-row"><input placeholder="Артикул WB" value={nm} onChange={(e) => setNm(e.target.value.replace(/\D/g, ""))} />
            <button disabled={!nm} onClick={() => http.get<{ rows: Brief[] }>(`/api/compare/search?nm=${nm}`).then((r) => setFound(r.rows)).catch((e) => setErr(e.message))}>Найти</button></div>
          {found && (found.length ? found.map((b) => <Item key={b.id} b={b} />) : <div className="hint">Открытых сравнений с этим артикулом пока нет.</div>)}
          {found && nm && !list.subs.some((x) => String(x.nm_id) === nm) && (
            <button onClick={() => http.post("/api/compare/subs", { nm_ids: [Number(nm)] }).then(() => { setMsg(`Подписка на ${nm}: пришлём в бот уведомлений, когда появится новое сравнение`); load(); })}>
              🔔 Подписаться на артикул {nm}</button>)}
        </div>
        {list.saved.length > 0 && <div className="acc-box"><b>★ Добавленные к себе ({list.saved.length})</b>{list.saved.map((b) => <Item key={b.id} b={b} />)}</div>}
        <div className="acc-box">
          <b>🔔 Подписки на артикулы</b>
          <div className="hint">Когда в сервисе появится открытое сравнение с этим артикулом — придёт сообщение в бот уведомлений (подключается в «Настройках аккаунта»).</div>
          <div className="acc-row"><input placeholder="Артикул WB" value={subNm} onChange={(e) => setSubNm(e.target.value.replace(/\D/g, ""))} />
            <button disabled={!subNm} onClick={() => http.post("/api/compare/subs", { nm_ids: [Number(subNm)] }).then(() => { setSubNm(""); load(); }).catch((e) => setErr(e.message))}>Подписаться</button>
            {list.client && <button onClick={() => http.post<{ added: number }>("/api/compare/subs/my_shops").then((x) => { setMsg(`Добавлено подписок: ${x.added}`); load(); }).catch((e) => setErr(e.message))}>
              на все артикулы моих магазинов</button>}</div>
          {list.subs.length > 0 && <div className="cmp-subs">{list.subs.map((x) => (
            <span key={x.nm_id} className="chip">{x.nm_id}{x.n ? ` · ${x.n} сравн.` : ""}
              <button className="link" title="Отписаться" onClick={() => http.del(`/api/compare/subs/${x.nm_id}`).then(load)}>✕</button></span>))}</div>}
        </div>
        <div className="acc-box"><b>Мои сравнения ({list.mine.length})</b>
          {list.mine.length ? list.mine.map((b) => <Item key={b.id} b={b} />) : <div className="hint">Пока пусто — загрузите первый файл.</div>}</div>
        {list.team?.length > 0 && <div className="acc-box"><b>Сравнения команды ({list.team.length})</b>
          <div className="hint">Загрузили коллеги по вашим кабинетам — видны всем участникам, лимит просмотров не тратят.</div>
          {list.team.map((b) => <Item key={b.id} b={b} />)}</div>}
        {list.seen.length > 0 && <div className="acc-box"><b>Просмотренные чужие</b>{list.seen.map((b) => <Item key={b.id} b={b} />)}</div>}
      </>}
    </div></div>
  );
}

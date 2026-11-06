import { Fragment, useEffect, useState } from "react";
import { http } from "./api";

type Bids = Record<string, number>;
type Outcome = { verdict: "better" | "worse" | "same"; delta: number | null;
  before: { orders: number; spend: number; profit: number; days?: number; carts?: number; ad_carts?: number };
  after: { orders: number; spend: number; profit: number; days?: number; carts?: number; ad_carts?: number } };
type Prop = { id: number; photo?: string | null; kind: string; kind_t: string; advert_id: number; nm_id: number | null; query: string | null; vc: string | null; camp: string | null;
  params: { before: unknown; after: unknown }; reason: string; effect_week: number | null; metrics: Record<string, unknown>; priority: number;
  source: "rules" | "user"; status: string; decided_at: string | null; error: string | null; batch_at: string; who: string | null; outcome: Outcome | null;
  feedback: { mine: { rating: number | null; comment: string | null } | null; up: number; down: number; comments: number } | null };
type Nm = { nm_id: number; vc: string | null; bids: Bids; spend_7d: number; orders_7d: number; clicks_7d: number; carts_7d: number };
type Camp = { id: number; status: number; status_t: string; name: string; bid_type: string | null; payment: string | null;
  placements: { search?: boolean; recommendations?: boolean }; can_change_nms: boolean; nms: Nm[]; spend_7d: number; orders_7d: number; carts_7d: number };
type Learn = { action: string; n: number; wins: number; avg_delta: number | null; step: number | null };
type SumRow = { key: string; title?: string; campaigns: number; spend: number; orders: number; profit: number; roi: number | null };
type State = { balance: Record<string, unknown> | null; balance_at: string | null; summary: { days: number; types: SumRow[]; managers: SumRow[];
  nocost: { spend_7d: number; n: number; top: { nm_id: number; vc: string | null; spend_7d: number }[] }; upd_14d: Record<string, number> } | null; summary_at: string | null };
type Res = { proposals: Prop[]; campaigns: Camp[]; note: { body: string; model: string; batch_at: string } | null; last_run: string | null;
  can_edit: boolean; can_admin: boolean; enabled: boolean; write_ok: boolean; write_why: string | null; settings: Record<string, number | boolean>;
  place_t: Record<string, string>; learn: Learn[]; state: State | null };
type Kw = { rows: { query: string; v: number; cl: number; atb: number; o: number; sp: number }[]; minus: string[];
  minus_hist?: Record<string, { verdict: "bad" | "good" | "weak" | "thin"; why: string }> };

const rub = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v).toLocaleString("ru-RU")} ₽`;
const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
const ST: Record<string, string> = { applied: "✅ применено", rejected: "отклонено", expired: "устарело", stale: "⚠️ устарело", error: "❌ ошибка" };
const VERDICT: Record<string, string> = { better: "📈 стало лучше", worse: "📉 стало хуже", same: "≈ без изменений" };
const ACT_T: Record<string, string> = { bid_down: "снижение ставки", bid_up: "повышение ставки", kw_bid_down: "ставка на ключ ↓", kw_bid_up: "ставка на ключ ↑",
  pause: "пауза", start: "запуск", nm_remove: "убрать артикул", kw_minus: "минус-фразы", deposit: "пополнение бюджета", placements: "места размещения" };

/** «было → станет» по-человечески. */
function change(p: Prop, place: Record<string, string>) {
  const { before: b, after: a } = p.params;
  if (p.kind === "bid") {
    const bb = (b || {}) as Bids, aa = (a || {}) as Bids;
    return Object.keys(aa).map((pl) => `${place[pl] || pl}: ${(bb[pl] || 0) / 100} → ${aa[pl] / 100} ₽`).join("; ");
  }
  if (p.kind === "placements") {
    const f = (x: unknown) => { const o = (x || {}) as Record<string, boolean>; return [o.search && "поиск", o.recommendations && "рекомендации"].filter(Boolean).join(" + ") || "—"; };
    return `${f(b)} → ${f(a)}`;
  }
  if (p.kind === "pause" || p.kind === "start") return p.kind === "pause" ? "активна → пауза" : "пауза → активна";
  if (p.kind === "kw_bid") return `${b} → ${a} ₽ за 1000 показов`;
  if (p.kind === "deposit") {
    const o = (a || {}) as { sum: number; type: number }, bb = (b || {}) as { budget?: number };
    return `бюджет ${rub(bb.budget ?? 0)} → +${rub(o.sum)} (${o.type === 0 ? "со счёта" : "с баланса"})`;
  }
  if (p.kind === "create") {
    const o = (a || {}) as { name: string; bid_type: string; placement_types?: string[] };
    const t = o.bid_type === "unified" ? "единая ставка" : `ручная ставка, ${(o.placement_types || []).map((x) => place[x] || x).join(" + ") || "поиск"}`;
    return `${p.query?.startsWith("test:") ? "тест типа: " : ""}новая кампания «${o.name}», ${t}`;
  }
  return `${b ?? ""} → ${a ?? ""}`;
}

/** 👍/👎 и комментарий к предложению  — по оценкам дорабатываем правила; в WB ничего не уходит. */
function Feedback({ p, shop, onDone }: { p: Prop; shop: number; onDone: () => void }) {
  const mine = p.feedback?.mine;
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(mine?.comment || "");
  const [busy, setBusy] = useState(false);
  const save = (rating: number | null, comment: string | null) => {
    setBusy(true);
    http.post(`/api/shops/${shop}/ads/feedback`, { id: p.id, rating, comment }).then(() => { setOpen(false); onDone(); })
      .catch((e) => alert((e as Error).message)).finally(() => setBusy(false));
  };
  const r = mine?.rating ?? null;
  const others = p.feedback ? { up: p.feedback.up - (r === 1 ? 1 : 0), down: p.feedback.down - (r === -1 ? 1 : 0) } : null;
  return <div className="ads-fb">
    <button className={"fb" + (r === 1 ? " on" : "")} disabled={busy} title="Хорошее предложение" onClick={() => save(r === 1 ? null : 1, mine?.comment || null)}>👍</button>
    <button className={"fb" + (r === -1 ? " on bad" : "")} disabled={busy} title="Плохое предложение" onClick={() => save(r === -1 ? null : -1, mine?.comment || null)}>👎</button>
    <button className={"fb" + (mine?.comment ? " on" : "")} disabled={busy} title="Комментарий: что не так или что сделать иначе" onClick={() => setOpen(!open)}>💬</button>
    {others && (others.up > 0 || others.down > 0) && <span className="hint"> ещё: {others.up > 0 && `👍${others.up}`} {others.down > 0 && `👎${others.down}`}</span>}
    {open && <div className="ads-fb-box">
      <textarea rows={3} value={text} placeholder="Почему хорошо или плохо, что предложить иначе" onChange={(e) => setText(e.target.value)} />
      <div><button disabled={busy} onClick={() => save(r, text)}>Сохранить</button> <button className="link" onClick={() => setOpen(false)}>отмена</button></div>
    </div>}
  </div>;
}

/** Бонусы WB (реклама ими не бесплатна) и реклама на товары без себестоимости . */
function StateBanner({ st }: { st: State | null }) {
  if (!st) return null;
  const b = (st.balance || {}) as Record<string, unknown>;
  const cbs = (Array.isArray(b.cashbacks) ? b.cashbacks : []) as Record<string, unknown>[];
  const bonus = cbs.reduce((s, x) => s + Number(x.sum || 0), 0) + Number(b.bonus || 0);
  const upd = st.summary?.upd_14d || {};
  const usedBonus = Number(upd["Кэшбэк"] || 0);
  const nc = st.summary?.nocost;
  const exp = cbs.map((x) => String(x.expiration_date || x.expirationDate || "")).filter(Boolean).sort()[0];
  return <>
    {st.balance && (bonus > 0 ? <div className="disclaimer">🎁 Бонусы WB на рекламу: <b>{rub(bonus)}</b>{exp && <>, сгорают {new Date(exp).toLocaleDateString("ru-RU", { timeZone: "UTC" })}</>}.
      Реклама бонусами не бесплатна — в расчётах сервиса весь расход (вкл. бонусы) считается расходом: когда бонусы кончатся, та же реклама пойдёт деньгами.</div>
      : usedBonus > 0 ? <div className="disclaimer">⚠️ Бонусы WB на рекламу закончились: за 14 дней ими оплачено {rub(usedBonus)}, теперь вся реклама — деньгами
        ({rub(Number(upd["Баланс"] || 0) + Number(upd["Счет"] || 0))} за 14 дней). Проверьте кампании в минусе.</div> : null)}
    {nc && nc.n > 0 && nc.spend_7d > 0 && <div className="disclaimer">💸 Реклама на товары без себестоимости: {nc.n} арт., {rub(nc.spend_7d)} за 7 дней —
      окупается ли она, посчитать нельзя. Задайте себестоимость; через 7 дней такой рекламы сервис предложит паузу.
      <div className="hint">{nc.top.slice(0, 8).map((x) => `${x.vc || x.nm_id} — ${rub(x.spend_7d)}`).join(" · ")}</div></div>}
  </>;
}

/** Итоги рекламы за 30 дней по типам и менеджерам (менеджер — имя в названии кампании). */
function Summary({ st }: { st: State | null }) {
  const sm = st?.summary;
  if (!sm) return <div className="hint">Сводка появится после следующего разбора.</div>;
  const t = (rows: SumRow[], head: string, title: (r: SumRow) => string) => <table className="acc-t"><thead><tr><th>{head}</th><th>Кампаний</th>
    <th>Расход (весь, вкл. бонусы)</th><th>Рекламных заказов по склейкам</th><th>Прибыль рекламы</th><th>На 1 ₽ рекламы</th></tr></thead>
    <tbody>{rows.map((r) => <tr key={r.key}><td>{title(r)}</td><td className="n">{r.campaigns}</td><td className="n">{rub(r.spend)}</td><td className="n">{r.orders}</td>
      <td className={"n " + (r.profit >= 0 ? "pos" : "neg")}>{rub(r.profit)}</td><td className="n">{r.roi == null ? "—" : `${r.roi > 0 ? "+" : ""}${Math.round(r.roi * 100)} %`}</td></tr>)}</tbody></table>;
  return <div className="acc-box">
    <b>Итоги рекламы за {sm.days} дней</b>
    <div className="hint">Прибыль рекламы = рекламные заказы склейки × прибыль с заказа до рекламы − расход (как в предложениях; без себестоимости не считается).
      «На 1 ₽ рекламы» — сколько прибыли сверх расхода даёт рубль: в каждом кабинете окупается свой тип — новые кампании сервис предлагает того типа, что окупается здесь.</div>
    <h4>По типам рекламы</h4>{t(sm.types, "Тип", (r) => r.title || r.key)}
    <h4>По менеджерам</h4>{t(sm.managers, "Менеджер", (r) => r.key)}
    <div className="hint">Менеджер — по имени в названии кампании; пишите имя в название, и его кампании попадут сюда. Свой список имён — в настройках блока.
      {st?.summary_at && <> Посчитано {dt(st.summary_at)}.</>}</div>
  </div>;
}

/** 📢 Реклама WB: предложения ИИ (код считает, нейросеть поясняет), применение по кнопке, итоги через 7 дней, ручное управление кампаниями. */
export function Ads({ shop, onSettings }: { shop: number; onSettings: () => void }) {
  const [r, setR] = useState<Res | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [sel, setSel] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<"props" | "camps" | "history" | "sum">("props");
  const load = () => http.get<Res>(`/api/shops/${shop}/ads`).then((x) => { setR(x); setErr(""); }).catch((e) => setErr(e.message));
  useEffect(() => { setR(null); setSel([]); load(); }, [shop]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="reviews"><h2>📢 Реклама</h2>{err ? <div className="err">{err}</div> : <div className="hint">Загружаю…</div>}</div>;

  const fresh = r.proposals.filter((p) => p.status === "new");
  const hist = r.proposals.filter((p) => p.status !== "new");
  const decide = async (ids: number[], apply: boolean, force = false) => {
    if (!ids.length) return;
    if (apply && !force && !confirm(`Отправить в WB ${ids.length === 1 ? "это изменение" : `${ids.length} изменений`}? Проверьте «было → станет» перед отправкой.`)) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const res = await http.post<Record<string, { status: string; error?: string }>>(`/api/shops/${shop}/ads/decide`, { ids, apply, force });
      const big = Object.entries(res).filter(([, v]) => v.status === "confirm");
      if (big.length) {
        const why = [...new Set(big.map(([, v]) => v.error))].join("; ");
        if (confirm(`Нужно отдельное подтверждение (${big.length}): ${why}. Отправить в WB?`)
          && confirm("Подтвердите ещё раз: это деньги, новая кампания или большое изменение ставки.")) {
          await http.post(`/api/shops/${shop}/ads/decide`, { ids: big.map(([k]) => Number(k)), apply: true, force: true });
        }
      }
      const bad = Object.values(res).filter((v) => v.error && v.status !== "confirm");
      setMsg(apply ? `Готово${bad.length ? `, но с замечаниями: ${bad.map((b) => b.error).join("; ")}` : ""}` : "Отклонено");
    } catch (e) { setErr((e as Error).message); }
    setBusy(false); setSel([]); load();
  };
  const refresh = () => { setBusy(true); http.post(`/api/shops/${shop}/ads/refresh`, {}).then(load).catch((e) => setErr(e.message)).finally(() => setBusy(false)); };
  const eff = fresh.reduce((s, p) => s + (p.effect_week || 0), 0);

  return (
    <div className="reviews ads">
      <div className="rv-head">
        <h2>📢 Реклама</h2>
        {r.can_edit && <button className="link" disabled={busy} onClick={refresh}>🔄 Обновить разбор</button>}
        <button className="link" onClick={onSettings}>⚙️ Настройки блока</button>
      </div>
      <div className="hint">
        Сервис разбирает рекламу WB утром и каждые 3 часа (9:30, 12:30, 15:30, 18:30, 21:30 МСК) и предлагает действия ради прибыли: ставки кампаний и ключей,
        пауза и запуск, минус-фразы, пополнение бюджета, новые кампании. Решения — по 7 дням (срочное — по 3), прибыль с заказа — из юнит-экономики
        (выкуп × прибыль с выкупа), в каждом предложении — <b>безубыточная реклама на заказ</b>; заказы — по всей склейке, расход — весь, включая бонусы WB.
        Цифры считает код, нейросеть только поясняет. В WB изменения уходят <b>только по кнопке «Применить»</b>; деньги и новые кампании — с двойным
        подтверждением. Через 3–7 дней сервис проверяет итог каждого действия (с поправкой на фон магазина) и по нему подстраивает шаги.
        Оценивайте предложения 👍/👎 — по ним дорабатываем правила.{r.last_run && <> Последний разбор: {dt(r.last_run)}.</>}
      </div>
      {!r.write_ok && <div className="disclaimer">ℹ️ Применять пока нельзя: {r.write_why}. Нужны: ключ на запись с разделом «Продвижение» и включённый блок «Реклама» —
        <button className="link" onClick={onSettings}>Взаимодействия</button>. Предложения можно смотреть уже сейчас.</div>}
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok">{msg}</div>}
      {r.note && <div className="acc-box"><b>🤖 Главное сегодня</b><div className="ai-note" style={{ whiteSpace: "pre-wrap" }}>{r.note.body}</div>
        <div className="hint">{r.note.model} · {dt(r.note.batch_at)}</div></div>}
      <StateBanner st={r.state} />
      <div className="rv-filters">
        <button className={"chip" + (view === "props" ? " on" : "")} onClick={() => setView("props")}>Предложения ({fresh.length})</button>
        <button className={"chip" + (view === "camps" ? " on" : "")} onClick={() => setView("camps")}>Кампании ({r.campaigns.length})</button>
        <button className={"chip" + (view === "history" ? " on" : "")} onClick={() => setView("history")}>История и итоги ({hist.length})</button>
        <button className={"chip" + (view === "sum" ? " on" : "")} onClick={() => setView("sum")}>По типам и менеджерам</button>
      </div>
      {view === "sum" && <Summary st={r.state} />}

      {view === "props" && <>
        {!fresh.length ? <div className="hint">Сейчас предложений нет — реклама в порядке или данных мало.</div> : <>
          <div className="hint">Предложений: <b>{fresh.length}</b>{eff > 0 && <> · оценка эффекта: до <b>+{rub(eff)}</b> к прибыли в неделю (там, где её можно посчитать)</>}</div>
          {r.can_edit && <div className="acc-row">
            <label><input type="checkbox" checked={sel.length === fresh.length} onChange={(e) => setSel(e.target.checked ? fresh.map((p) => p.id) : [])} /> выбрать все</label>
            <button disabled={busy || !sel.length || !r.write_ok} onClick={() => decide(sel, true)}>Применить выбранные ({sel.length})</button>
            <button className="link" disabled={busy || !sel.length} onClick={() => decide(sel, false)}>отклонить выбранные</button>
          </div>}
          <div className="as-table-wrap"><table className="board-t ads-t">
            <thead><tr>{r.can_edit && <th></th>}<th>Фото</th><th>Что</th><th>Где</th><th>Было → станет</th><th>Почему</th><th>Эффект ₽/нед</th><th>Действие и оценка</th></tr></thead>
            <tbody>{fresh.map((p) => <tr key={p.id} className={p.priority >= 90 ? "hot" : ""}>
              {r.can_edit && <td><input type="checkbox" checked={sel.includes(p.id)} onChange={(e) => setSel(e.target.checked ? [...sel, p.id] : sel.filter((x) => x !== p.id))} /></td>}
              <td>{p.photo ? (p.nm_id ? <a href={`https://www.wildberries.ru/catalog/${p.nm_id}/detail.aspx`} target="_blank" rel="noreferrer"
                title={p.vc || ""}><img className="thumb big" src={p.photo} alt="" loading="lazy" /></a>
                : <img className="thumb big" src={p.photo} alt="" loading="lazy" title="товар кампании" />) : null}</td>
              <td><b>{p.kind_t}</b>{p.metrics?.warmup ? <div className="hint">разгон новой кампании</div> : null}</td>
              <td>{p.camp || p.advert_id || "новая"}<div className="hint">{p.advert_id ? `№${p.advert_id}` : ""}{p.nm_id && <> · {p.vc || p.nm_id} ({p.nm_id})</>}{p.query && <> · «{p.query}»</>}</div></td>
              <td>{change(p, r.place_t)}</td>
              <td style={{ minWidth: 240, maxWidth: 380 }}>{p.reason}</td>
              <td className="n">{p.effect_week ? `+${rub(p.effect_week)}` : "—"}</td>
              <td>{r.can_edit && <div className="ads-btns">
                <button disabled={busy || !r.write_ok} onClick={() => decide([p.id], true)}>Применить</button>
                <button className="link" disabled={busy} onClick={() => decide([p.id], false)}>отклонить</button></div>}
                <Feedback p={p} shop={shop} onDone={load} /></td>
            </tr>)}</tbody></table></div>
        </>}
      </>}

      {view === "history" && <>
        {r.learn.length > 0 && <div className="acc-box"><b>🧠 Чему научился модуль (итоги за 90 дней; каждое действие проверяется через 3–7 дней с поправкой на фон магазина)</b>
          <table className="acc-t"><thead><tr><th>Действие</th><th>Проверено</th><th>Стало лучше</th><th>Средний эффект, ₽/нед</th><th>Шаг ставки сейчас</th></tr></thead>
            <tbody>{r.learn.map((l) => <tr key={l.action}><td>{ACT_T[l.action] || l.action}</td><td>{l.n}</td><td>{l.wins}</td><td>{rub(l.avg_delta)}</td>
              <td>{l.step != null ? `${Math.round(l.step * 100)} %` : "—"}</td></tr>)}</tbody></table></div>}
        {!hist.length ? <div className="hint">Пока пусто.</div> : <div className="as-table-wrap"><table className="board-t ads-t">
          <thead><tr><th>Когда</th><th>Что</th><th>Где</th><th>Было → станет</th><th>Статус</th><th>Итог (прибыль склейки, ₽/нед)</th><th>Оценка</th></tr></thead>
          <tbody>{hist.map((p) => <tr key={p.id}>
            <td>{p.decided_at ? dt(p.decided_at) : dt(p.batch_at)}<div className="hint">{p.source === "user" ? "вручную" : "предложение ИИ"}{p.who && <> · {p.who}</>}</div></td>
            <td>{p.kind_t}</td>
            <td>№{p.advert_id}{p.nm_id && <> · {p.vc || p.nm_id}</>}{p.query && <> · «{p.query}»</>}</td>
            <td>{change(p, r.place_t)}</td>
            <td>{ST[p.status] || p.status}{p.error && <div className="hint">{p.error}</div>}</td>
            <td>{p.outcome ? <>{VERDICT[p.outcome.verdict]}: {p.outcome.delta != null && p.outcome.delta > 0 ? "+" : ""}{rub(p.outcome.delta)}
              <div className="hint">за {p.outcome.after.days ?? 1} дн.: прибыль {rub(p.outcome.before.profit)} → {rub(p.outcome.after.profit)}, заказы склейки {p.outcome.before.orders} → {p.outcome.after.orders}
                {p.outcome.after.carts != null && <>, корзины склейки {p.outcome.before.carts ?? "—"} → {p.outcome.after.carts}, корзины из рекламы {p.outcome.before.ad_carts ?? "—"} → {p.outcome.after.ad_carts}</>}</div></>
              : p.status === "applied" ? <span className="hint">проверим через 3–7 дней</span> : "—"}</td>
            <td>{p.source === "rules" ? <Feedback p={p} shop={shop} onDone={load} /> : null}</td>
          </tr>)}</tbody></table></div>}
      </>}

      {view === "camps" && <Campaigns r={r} shop={shop} busy={busy} setBusy={setBusy} onDone={(m) => { setMsg(m); load(); }} onErr={setErr} />}
    </div>
  );
}

/** Ручное управление: пауза / запуск, ставки, места размещения, ключи (минус-фразы). Тоже через «Взаимодействия» и журнал. */
function Campaigns({ r, shop, busy, setBusy, onDone, onErr }: { r: Res; shop: number; busy: boolean; setBusy: (v: boolean) => void;
  onDone: (m: string) => void; onErr: (m: string) => void }) {
  const [open, setOpen] = useState<number | null>(null);
  const [kw, setKw] = useState<{ aid: number; nm: number; d: Kw } | null>(null);
  const act = async (body: Record<string, unknown>, text: string) => {
    if (!confirm(text)) return;
    setBusy(true); onErr("");
    try {
      const res = await http.post<{ status: string; error?: string }>(`/api/shops/${shop}/ads/manual`, body);
      onDone(res.status === "applied" ? "✅ Отправлено в WB" : `${res.status}: ${res.error || ""}`);
    } catch (e) { onErr((e as Error).message); }
    setBusy(false);
  };
  const setBid = (c: Camp, n: Nm) => {
    const pls = c.bid_type === "unified" ? ["combined"] : Object.keys(n.bids).filter((pl) => n.bids[pl] && (c.placements as Record<string, boolean>)[pl] !== false);
    const after: Record<string, number> = {};
    for (const pl of pls) {
      const cur = (c.bid_type === "unified" ? (n.bids.search || n.bids.recommendations) : n.bids[pl]) / 100;
      const v = prompt(`Новая ставка, ₽ — ${r.place_t[pl] || pl} (сейчас ${cur} ₽)`, String(cur));
      if (v == null) return;
      const x = Number(v.replace(",", "."));
      if (!(x > 0)) return onErr("Ставка должна быть числом больше 0");
      if (Math.abs(x - cur) / cur > Number(r.settings.max_step) / 100
        && !(confirm(`Изменение ставки ${cur} → ${x} ₽ больше ${r.settings.max_step} %. Точно?`) && confirm("Подтвердите ещё раз: большое изменение ставки."))) return;
      after[pl] = x;
    }
    if (Object.keys(after).length) act({ kind: "bid", advert_id: c.id, nm_id: n.nm_id, after }, `Отправить в WB новую ставку для ${n.vc || n.nm_id}?`);
  };
  const loadKw = (aid: number, nm: number) => http.get<Kw>(`/api/shops/${shop}/ads/keywords?advert_id=${aid}&nm_id=${nm}`).then((d) => setKw({ aid, nm, d })).catch((e) => onErr(e.message));
  return (
    <div className="as-table-wrap"><table className="board-t ads-t">
      <thead><tr><th>Кампания</th><th>Статус</th><th>Тип</th><th>Расход 7 дн.</th><th>Корзины 7 дн.</th><th>Заказы 7 дн.</th>{r.can_edit && <th></th>}</tr></thead>
      <tbody>{r.campaigns.map((c) => <Fragment key={c.id}>
        <tr onClick={() => setOpen(open === c.id ? null : c.id)} style={{ cursor: "pointer" }}>
          <td>{open === c.id ? "▾" : "▸"} {c.name}<div className="hint">№{c.id} · артикулов: {c.nms.length}</div></td>
          <td>{c.status_t}</td>
          <td>{c.bid_type === "unified" ? "единая ставка" : "ручная ставка"} · {c.payment === "cpc" ? "за клики" : "за показы"}
            {c.bid_type === "manual" && <div className="hint">{[c.placements.search && "поиск", c.placements.recommendations && "рекомендации"].filter(Boolean).join(" + ")}</div>}</td>
          <td className="n">{rub(c.spend_7d)}</td><td className="n">{c.carts_7d}</td><td className="n">{c.orders_7d}</td>
          {r.can_edit && <td style={{ whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
            {c.status === 9 && <button disabled={busy || !r.write_ok} onClick={() => act({ kind: "pause", advert_id: c.id }, `Поставить кампанию «${c.name}» на паузу?`)}>Пауза</button>}
            {(c.status === 11 || c.status === 4) && <button disabled={busy || !r.write_ok} onClick={() => act({ kind: "start", advert_id: c.id }, `Запустить кампанию «${c.name}»?`)}>Запустить</button>}
            <button className="link" disabled={busy || !r.write_ok} onClick={() => {
              const v = prompt(`Пополнить бюджет кампании «${c.name}», ₽ (не больше ${r.settings.deposit_max})`, "1000");
              if (v == null) return;
              const x = Math.round(Number(v.replace(",", ".")));
              if (!(x >= 1000) || x > Number(r.settings.deposit_max)) return onErr(`Сумма — от 1000 до ${r.settings.deposit_max} ₽ (лимит меняется в настройках блока)`);
              const src = confirm("Списать со СЧЁТА продвижения? (ОК — со счёта, Отмена — с баланса взаиморасчёта)") ? 0 : 1;
              if (!confirm(`Это деньги: пополнить бюджет на ${x} ₽ ${src === 0 ? "со счёта" : "с баланса"}?`)) return;
              act({ kind: "deposit", advert_id: c.id, after: { sum: x, type: src } }, "Подтвердите ещё раз пополнение бюджета.");
            }}>пополнить</button>
            {c.bid_type === "manual" && c.payment === "cpm" && <button className="link" disabled={busy || !r.write_ok} onClick={() => {
              const s = confirm("Показывать в ПОИСКЕ? (ОК — да, Отмена — нет)"), rc = confirm("Показывать в РЕКОМЕНДАЦИЯХ? (ОК — да, Отмена — нет)");
              if (!s && !rc) return onErr("Хотя бы одно место размещения должно остаться");
              act({ kind: "placements", advert_id: c.id, after: { search: s, recommendations: rc } }, `Места размещения: ${[s && "поиск", rc && "рекомендации"].filter(Boolean).join(" + ")}. Отправить в WB?`);
            }}>места</button>}
          </td>}
        </tr>
        {open === c.id && c.nms.map((n) => <tr key={`${c.id}-${n.nm_id}`} className="sub">
          <td style={{ paddingLeft: 24 }}>{n.vc || n.nm_id}<div className="hint">{n.nm_id}</div></td>
          <td colSpan={2}>{Object.entries(n.bids).filter(([, v]) => v).map(([pl, v]) => `${r.place_t[pl] || pl}: ${v / 100} ₽`).join(" · ") || "—"}</td>
          <td className="n">{rub(n.spend_7d)}</td><td className="n">{n.carts_7d}</td><td className="n">{n.orders_7d}<div className="hint">кликов {n.clicks_7d}</div></td>
          {r.can_edit && <td style={{ whiteSpace: "nowrap" }}>
            <button className="link" disabled={busy || !r.write_ok} onClick={() => setBid(c, n)}>ставка</button>
            <button className="link" onClick={() => loadKw(c.id, n.nm_id)}>ключи</button></td>}
        </tr>)}
        {open === c.id && kw && kw.aid === c.id && <tr key={`${c.id}-kw`} className="sub"><td colSpan={7}>
          <b>Ключи (поисковые кластеры) артикула {kw.nm} за 14 дней</b>
          <table className="acc-t"><thead><tr><th>Кластер</th><th>Показы</th><th>Клики</th><th>Корзины</th><th>Заказы</th><th>Расход</th><th></th></tr></thead>
            <tbody>{kw.d.rows.map((q) => <tr key={q.query}><td>{q.query}</td><td>{q.v}</td><td>{q.cl}</td><td>{q.atb}</td><td>{q.o}</td><td>{rub(q.sp)}</td>
              <td>{c.bid_type === "manual" && c.payment === "cpm" && !kw.d.minus.includes(q.query) && <button className="link" disabled={busy || !r.write_ok} onClick={() => {
                const v = prompt(`Ставка на ключ «${q.query}», ₽ за 1000 показов`, "");
                if (v == null) return;
                const x = Math.round(Number(v.replace(",", ".")));
                if (!(x > 0)) return onErr("Ставка — целое число рублей больше 0");
                act({ kind: "kw_bid", advert_id: kw.aid, nm_id: kw.nm, query: q.query, after: x }, `Ставка на ключ «${q.query}»: ${x} ₽ за 1000 показов. Отправить в WB?`);
              }}>ставка</button>}{" "}
                {kw.d.minus.includes(q.query) ? <button className="link" disabled={busy || !r.write_ok}
                onClick={() => { const h = kw.d.minus_hist?.[q.query];
                  act({ kind: "kw_unminus", advert_id: kw.aid, nm_id: kw.nm, query: q.query },
                    (h?.verdict === "bad" ? `⚠️ Возвращать нет смысла — ключ был дорогим без корзин и заказов.\n` : "") +
                    `История ключа «${q.query}»: ${h?.why || "нет данных"}.\n\nВернуть его (убрать из минус-фраз)?`); }}>вернуть</button>
                : <button className="link" disabled={busy || !r.write_ok}
                  onClick={() => act({ kind: "kw_minus", advert_id: kw.aid, nm_id: kw.nm, query: q.query }, `Добавить «${q.query}» в минус-фразы (реклама перестанет показываться по нему)?`)}>в минус</button>}</td></tr>)}</tbody></table>
          {kw.d.minus.length > 0 && <div className="hint">В минус-фразах: {kw.d.minus.join(", ")}</div>}
        </td></tr>}
      </Fragment>)}</tbody></table></div>
  );
}

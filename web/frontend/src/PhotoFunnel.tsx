import { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Item = { nm_id: number; vendor_code: string | null; title: string | null; photo: string | null; kind: "own" | "competitor";
  last_change: string | null; changes: number; has_snap: boolean };
type Eff = { views: number | null; cart: number | null; orders: number | null; conv_cart: number | null; conv_order: number | null; orders_day: number | null;
  covered_days?: number; expected_days?: number; conversion_days?: number };
type Prices = { from: string; to: string; before_spp: number | null; after_spp: number | null; coverage: number };
type Entry = { from: string; to: string | null; ctr: number | null; conv_cart: number | null; conv_order: number | null;
  views: number | null; clicks: number | null; carts: number | null; orders: number | null; expected_days: number;
  report_days: number; covered_days: number; missing_days: string[]; coverage: number;
  status: "complete" | "partial" | "empty" | "pending" | "intraday" };
type Per = { from: string; to: string; days: number; views: number | null; cart: number | null; orders: number | null; ctr: number | null; conv_cart: number | null;
  covered_days?: number; expected_days?: number; conversion_days?: number;
  conv_order: number | null; orders_day: number | null; prices?: Prices | null; entry?: Entry | null };
type Ev = { day: string; summary: string; before: string[] | null; after: string[] | null; effect?: { before: Eff; after: Eff }; period?: Per; period_before?: Per | null };
type Full = { nm_id: number; own: boolean; current: string[] | null; taken_at: string | null; events: Ev[]; current_period?: Per | null };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const num = (v: number | null | undefined) => v == null ? "—" : nf.format(v);
const money = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined) => (v == null ? "—" : nf.format(v * 100) + " %");
const dd = (s: string) => s.slice(0, 10).split("-").reverse().join(".");

export function Slides({ hashes, small }: { hashes: string[] | null | undefined; small?: boolean }) {
  if (!hashes?.length) return <span className="hint">слепка ещё нет</span>;
  return <div className={"slides" + (small ? " small" : "")}>{hashes.map((h, i) => (
    <a key={i} href={`/api/photo/${h}`} target="_blank" rel="noreferrer" className="slide"><img src={`/api/photo/${h}`} alt="" loading="lazy" /><span>{i + 1}</span></a>))}</div>;
}

function change(b: number | null | undefined, a: number | null | undefined) {
  if (b == null || a == null || !b) return null;
  const ch = (a / b - 1) * 100;
  return <span className={ch >= 0 ? "up" : "down"}> {ch >= 0 ? "+" : ""}{nf.format(ch)} %</span>;
}

/** Фотоворонка: слепки первых 7 фото, история изменений, по своим — конверсии до/после. */
export function PhotoFunnel({ shop }: { shop: number }) {
  const [list, setList] = useState<Item[] | null>(null);
  const [nm, setNm] = useState<number | null>(null);
  const [d, setD] = useState<Full | null>(null);
  const context = useRef(0);
  const [q, setQ] = useState(""), [err, setErr] = useState(""), [msg, setMsg] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    setList(null); setNm(null); setErr("");
    http.get<Item[]>(`/api/shops/${shop}/photo_funnel`).then((x) => { if (live) { setList(x); setNm(x[0]?.nm_id ?? null); } })
      .catch((e) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [shop]);
  const load = (x: number, stamp: number) => http.get<Full>(`/api/shops/${shop}/photo_funnel/${x}`)
    .then(value => { if (stamp === context.current) setD(value); }).catch(e => { if (stamp === context.current) setErr(e.message); });
  useEffect(() => {
    const stamp = ++context.current;
    setD(null); setMsg(""); setErr(""); setBusy(false); if (nm) load(nm, stamp);
    return () => { ++context.current; };
  }, [shop, nm]); // eslint-disable-line react-hooks/exhaustive-deps
  if (err && !list) return <div className="err">{err}</div>;
  if (!list) return <div className="hint">Загрузка…</div>;
  const shown = list.filter((r) => !q || `${r.vendor_code} ${r.nm_id} ${r.title}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="comp">
      <div className="comp-side">
        <input className="q" placeholder="Артикул…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="comp-list">{shown.map((r) => (
          <button key={r.kind + r.nm_id} className={"comp-art" + (r.nm_id === nm ? " on" : "")} onClick={() => setNm(r.nm_id)}>
            {r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}
            <span><b>{r.vendor_code || (r.title || "").slice(0, 26) || r.nm_id}</b>
              <span className="hint">{r.kind === "competitor" ? "конкурент · " : ""}{r.nm_id}{r.last_change ? ` · изм. ${dd(r.last_change)}` : r.has_snap ? "" : " · нет слепка"}</span></span>
            {r.changes ? <span className="badge">{r.changes}</span> : null}
          </button>))}</div>
      </div>
      <div className="comp-main">
        {!d ? <div className="hint">Выберите артикул</div> : <>
          <div className="board-bar"><b>{d.nm_id}</b>{d.own ? <span className="badge">ваш</span> : <span className="hint">конкурент</span>}
            {d.taken_at && <span className="hint">слепок от {new Date(d.taken_at).toLocaleString("ru-RU")}</span>}
            <button disabled={busy} onClick={() => { const stamp = context.current; setBusy(true); http.post<{ changed: boolean; summary: string | null }>(`/api/shops/${shop}/photo_funnel/${d.nm_id}/snap`)
              .then((r) => { if (stamp === context.current) { setMsg(r.summary || (r.changed ? "Слепок снят" : "Изменений нет")); load(d.nm_id, stamp); } })
              .catch(e => { if (stamp === context.current) setErr(e.message); }).finally(() => { if (stamp === context.current) setBusy(false); }); }}>
              {busy ? "Снимаю…" : "📸 Снять слепок сейчас"}</button>
            {msg && <span className="ok">{msg}</span>}</div>
          <div className="acc-box"><b>Сейчас (первые 7 фото)</b><div className="pf-row"><Slides hashes={d.current} /><Kpi p={d.current_period} /></div></div>
          <div className="acc-box">
            <b>История изменений фото</b>
            {!d.events.length && <div className="hint">Изменений пока не было. Слепки снимаются каждый день в 07:00 — как только фото поменяют, здесь появится запись.</div>}
            {d.events.map((e, i) => (
              <div key={i} className="pf-ev">
                <div><b>{dd(e.day)}</b> · {e.summary}</div>
                <div className="pf-cmp"><span className="hint">было</span><div className="pf-row"><Slides hashes={e.before} small /><Kpi p={e.period_before} /></div></div>
                <div className="pf-cmp"><span className="hint">стало</span><div className="pf-row"><Slides hashes={e.after} small /><Kpi p={e.period} /></div></div>
                {e.effect && <div className="pf-eff">7 дней до → после: переходы {num(e.effect.before.views)} → {num(e.effect.after.views)}
                  {e.effect.before.conversion_days === 7 && e.effect.after.conversion_days === 7 && change(e.effect.before.views, e.effect.after.views)}; конверсия в корзину {pct(e.effect.before.conv_cart)} → {pct(e.effect.after.conv_cart)}
                  {e.effect.before.conversion_days === 7 && e.effect.after.conversion_days === 7 && change(e.effect.before.conv_cart, e.effect.after.conv_cart)}; в заказ {pct(e.effect.before.conv_order)} → {pct(e.effect.after.conv_order)}
                  {e.effect.before.conversion_days === 7 && e.effect.after.conversion_days === 7 && change(e.effect.before.conv_order, e.effect.after.conv_order)}; заказов в день {num(e.effect.before.orders_day)} → {num(e.effect.after.orders_day)}
                  {change(e.effect.before.orders_day, e.effect.after.orders_day)}
                  {e.effect.before.covered_days !== undefined && <small> · Воронка: {e.effect.before.covered_days}/7 → {e.effect.after.covered_days}/7 дн.; сравнение частичных периодов ограничено.</small>}</div>}
              </div>))}
          </div>
        </>}
      </div>
    </div>
  );
}

/** Справа от набора фото — показатели за всё время, пока он стоял . */
function Kpi({ p }: { p?: Per | null }) {
  if (!p) return null;
  const pc = (v: number | null) => (v == null ? "—" : (v * 100).toFixed(2).replace(".", ",") + " %");
  const d = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}`;
  return (
    <div className="pf-kpi" title="CTR — по рекламным показам и кликам (другие показы WB по API не отдаёт); конверсии — воронка карточки">
      <div className="hint">{d(p.from)}–{d(p.to)} · {p.days ? `${p.days} дн.` : "смена в течение дня"}</div>
      <div><span>CTR рекламы</span><b>{pc(p.ctr)}</b></div>
      <div><span>Конв. в корзину</span><b>{pc(p.conv_cart)}</b></div>
      <div><span>Конв. в заказ</span><b>{pc(p.conv_order)}</b></div>
      <div><span>Заказов в день</span><b>{p.orders_day == null ? "—" : p.orders_day.toFixed(1).replace(".", ",")}</b></div>
      {p.covered_days !== undefined && <small className="hint">Воронка WB: заказы {p.covered_days}/{p.expected_days} дн.; конверсии {p.conversion_days}/{p.expected_days} дн.
        Пропуски не считаются нулями. Сегодня исключено.</small>}
      {p.entry !== undefined && <EntryKpi e={p.entry} />}
      {p.prices !== undefined && <>
        <div title="Цена со скидкой продавца, до СПП"><span>Средняя цена до СПП</span><b>{p.prices?.before_spp == null ? "—" : money.format(p.prices.before_spp) + " ₽"}</b></div>
        <div title="Цена на витрине для гостя в Москве, без скидки кошелька"><span>Средняя цена после СПП</span><b>{p.prices?.after_spp == null ? "—" : money.format(p.prices.after_spp) + " ₽"}</b></div>
        <details className="hint pf-price-note"><summary>Как рассчитаны показатели</summary>
        <small title={p.prices ? `Период цен, МСК: ${new Date(p.prices.from).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} — ${new Date(p.prices.to).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })}` : undefined}>
          {p.prices?.coverage ? `Среднее по времени · история цен покрывает ${(p.prices.coverage * 100).toFixed(1).replace(".", ",")} % периода.` : "Нет истории цен за этот период."}
          {" "}Между замерами цена считается неизменной. Границы — зафиксированные смены фото; CTR и конверсии считаются по дням.
        </small></details>
      </>}
    </div>
  );
}

function EntryKpi({ e }: { e: Entry | null }) {
  return <section className="pf-entry-kpi" aria-label="Показатели из точек входа">
    <b>Точки входа</b>
    <div title="Переходы / показы по отчётам точек входа"><span>CTR</span><b>{pct(e?.ctr)}</b></div>
    <div title="Добавления в корзину / переходы"><span>Переход → корзина</span><b>{pct(e?.conv_cart)}</b></div>
    <div title="Заказы / добавления в корзину"><span>Корзина → заказ</span><b>{pct(e?.conv_order)}</b></div>
    <small className="hint">
      {!e ? "Нет данных за период набора фото." : e.status === "intraday" ? "Набор сменился в тот же день: дневной отчёт нельзя разделить между фото."
        : e.status === "pending" ? "Ещё нет завершённых дней для этого набора фото."
        : <>Данные по артикулу: {e.covered_days} из {e.expected_days} дн. ({dd(e.from)}–{dd(e.to!)}).
          {e.status === "partial" ? " Показатели по доступным дням, период покрыт не полностью." : e.status === "empty" ? " Нет дневных данных по этому артикулу." : ""}</>}
    </small>
    <details className="hint pf-price-note"><summary>Как рассчитаны точки входа</summary>
      <small>Отношения сумм за доступные дни, без усреднения дневных процентов. Дневные отчёты по МСК; текущий день исключён.
        День обнаружения смены фото относится новому набору, разделить его по часам нельзя. Время обнаружения может отличаться от времени замены фото.</small>
      {e && e.expected_days > 0 && <small>Дневных отчётов магазина: {e.report_days} из {e.expected_days}.
        {e.missing_days.length > 0 && <> Дни без полных данных артикула: {e.missing_days.map(dd).join(", ")}.</>}
        {e.covered_days > 0 && <> Показы: {nf.format(e.views!)}; переходы: {nf.format(e.clicks!)}; корзины: {nf.format(e.carts!)}; заказы: {nf.format(e.orders!)}.</>}
        {" "}При нулевом знаменателе показатель не рассчитывается.</small>}
    </details>
  </section>;
}

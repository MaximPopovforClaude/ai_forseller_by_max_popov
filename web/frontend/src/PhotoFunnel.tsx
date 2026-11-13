import { useEffect, useState } from "react";
import { http } from "./api";

type Item = { nm_id: number; vendor_code: string | null; title: string | null; photo: string | null; kind: "own" | "competitor";
  last_change: string | null; changes: number; has_snap: boolean };
type Eff = { views: number; cart: number; orders: number; conv_cart: number | null; conv_order: number | null; orders_day: number };
type Prices = { from: string; to: string; before_spp: number | null; after_spp: number | null; coverage: number };
type Per = { from: string; to: string; days: number; views: number; cart: number; orders: number; ctr: number | null; conv_cart: number | null;
  conv_order: number | null; orders_day: number | null; prices?: Prices | null };
type Ev = { day: string; summary: string; before: string[] | null; after: string[] | null; effect?: { before: Eff; after: Eff }; period?: Per; period_before?: Per | null };
type Full = { nm_id: number; own: boolean; current: string[] | null; taken_at: string | null; events: Ev[]; current_period?: Per | null };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
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
  const [q, setQ] = useState(""), [err, setErr] = useState(""), [msg, setMsg] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => { setList(null); setNm(null); http.get<Item[]>(`/api/shops/${shop}/photo_funnel`).then((x) => { setList(x); setNm(x[0]?.nm_id ?? null); }).catch((e) => setErr(e.message)); }, [shop]);
  const load = (x: number) => http.get<Full>(`/api/shops/${shop}/photo_funnel/${x}`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); setMsg(""); if (nm) load(nm); }, [nm]);
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
            <button disabled={busy} onClick={() => { setBusy(true); http.post<{ changed: boolean; summary: string | null }>(`/api/shops/${shop}/photo_funnel/${d.nm_id}/snap`)
              .then((r) => { setMsg(r.summary || (r.changed ? "Слепок снят" : "Изменений нет")); load(d.nm_id); }).catch((e) => setErr(e.message)).finally(() => setBusy(false)); }}>
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
                {e.effect && <div className="pf-eff">7 дней до → после: переходы {nf.format(e.effect.before.views)} → {nf.format(e.effect.after.views)}
                  {change(e.effect.before.views, e.effect.after.views)}; конверсия в корзину {pct(e.effect.before.conv_cart)} → {pct(e.effect.after.conv_cart)}
                  {change(e.effect.before.conv_cart, e.effect.after.conv_cart)}; в заказ {pct(e.effect.before.conv_order)} → {pct(e.effect.after.conv_order)}
                  {change(e.effect.before.conv_order, e.effect.after.conv_order)}; заказов в день {nf.format(e.effect.before.orders_day)} → {nf.format(e.effect.after.orders_day)}
                  {change(e.effect.before.orders_day, e.effect.after.orders_day)}</div>}
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
      <div><span>CTR</span><b>{pc(p.ctr)}</b></div>
      <div><span>Конв. в корзину</span><b>{pc(p.conv_cart)}</b></div>
      <div><span>Конв. в заказ</span><b>{pc(p.conv_order)}</b></div>
      <div><span>Заказов в день</span><b>{p.orders_day == null ? "—" : p.orders_day.toFixed(1).replace(".", ",")}</b></div>
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

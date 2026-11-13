import { Fragment, useEffect, useState } from "react";
import { http } from "./api";
import { changeCell } from "./entryGrowth";

/** Точки входа — сводные виды : воронка артикулов, источники трафика, источники по дням.
 *  Данные — дневные отчёты «Точки входа» (их качает плагин) + наши заказы (₽, средняя цена, % выкупа). */
type M = { views: number; clicks: number; carts: number; orders: number; ctr: number | null; cr_cart: number | null; cr_order: number | null;
  cro: number | null; crf: number | null; crfl: number | null; orders_sum: number | null; avg_price: number | null; buyout_pct: number | null;
  per_day?: Record<"views" | "clicks" | "carts" | "orders", number | null>;
  share_views?: number | null; share_clicks?: number | null; share_carts?: number | null; share_orders?: number | null; point?: string;
  [k: `ad_${string}` | `org_${string}`]: number | null | undefined };
type Per = { key: string; d_from: string; d_to: string; n_days: number };
type Art = { nm_id: number; vendor_code: string | null; title: string | null; brand: string | null; photo: string | null; cells: Record<string, M> };
type Src = M & { section: string; points: M[]; ad_only?: boolean };
type Data = { periods: Per[]; funnel: { total: Record<string, M>; articles: Art[]; articles_n: number } | null; sources: Src[]; sources_total?: M;
  sources_days: { section: string; all: M; days: Record<string, M>; ad_only?: boolean }[]; days?: string[]; n_days?: number; d_from?: string; d_to?: string };
export type View = "funnel" | "sources" | "sources_days";

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const pc = (v: number | null | undefined, d = 1) => v == null ? "" : (v * 100).toFixed(d).replace(".", ",") + " %";
const dd = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}`;
const PERIODS = [1, 3, 7, 10, 14, 30];

type Row = [keyof M, string, "n" | "rub" | "p"];
const FUNNEL: Row[] = [["views", "Показы карточки", "n"], ["clicks", "Переходы", "n"], ["carts", "Корзины", "n"], ["orders", "Заказы, шт.", "n"],
  ["orders_sum", "Заказы, ₽", "rub"], ["avg_price", "Средняя цена", "rub"], ["ctr", "CTR", "p"], ["cr_cart", "Конверсия в корзину", "p"],
  ["cr_order", "Конверсия в заказ", "p"], ["cro", "CRO (переход → заказ)", "p"]];   // % выкупа убран 
const DAYROWS: Row[] = [["views", "Показы", "n"], ["clicks", "Переходы", "n"], ["carts", "Корзины", "n"], ["orders", "Заказы", "n"],
  ["ctr", "CTR", "p"], ["cr_cart", "Конверсия в корзину", "p"], ["cr_order", "Корзина → заказ", "p"], ["cro", "CRO переход → заказ", "p"],
  ["crf", "CRF показ → заказ", "p"], ["crfl", "CRF(L) показ → корзина", "p"]];

function fmt(kind: Row[2], v: number | null | undefined) {
  if (v == null) return "";
  return kind === "p" ? pc(v, 2) : kind === "rub" ? nf.format(v) + " ₽" : nf.format(v);
}
/** Изменение к прошлому столбцу: штуки и рубли — в %, доли — в п.п. */
function Chg({ kind, a, b }: { kind: Row[2]; a: number | null | undefined; b: number | null | undefined }) {
  if (a == null || b == null) return null;
  if (kind === "p") {
    const d = (a - b) * 100;
    if (Math.abs(d) < 0.005) return null;
    return <sup className={d > 0 ? "t-good" : "t-bad"}> {d > 0 ? "+" : "−"}{Math.abs(d).toFixed(2).replace(".", ",")}</sup>;
  }
  if (!b) return null;
  const d = (a - b) / b * 100;
  if (Math.abs(d) < 0.5) return null;
  return <sup className={d > 0 ? "t-good" : "t-bad"}> {d > 0 ? "+" : "−"}{Math.abs(d).toFixed(0)}%</sup>;
}
// «из них реклама / органика» : подстроки для штук и CTR, где есть данные рекламы
const SPLIT_KEYS = new Set(["views", "clicks", "carts", "orders", "ctr"]);
type Split = { ad: boolean; org: boolean };
function subRows(split: Split, k: string): [string, string][] {
  if (!SPLIT_KEYS.has(k)) return [];
  return [...(split.ad ? [["ad_" + k, "↳ из них реклама"]] : []), ...(split.org ? [["org_" + k, "↳ органика"]] : [])] as [string, string][];
}
const gv = (m: M | undefined, k: string) => (m ? (m as unknown as Record<string, number | null | undefined>)[k] : undefined);

function Spark({ vals }: { vals: (number | null)[] }) {
  const max = Math.max(0, ...vals.map((v) => v || 0));
  if (!max) return null;
  return <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 20 }}>
    {vals.map((v, i) => <div key={i} style={{ width: 4, height: `${((v || 0) / max) * 100}%`, minHeight: 1, background: "#93c5fd" }} />)}</div>;
}

export function EntryViews({ shop, nm, view, pinPoints = false, growth = null, decline = null }: { shop: number; nm: string; view: View; pinPoints?: boolean; growth?: number | null; decline?: number | null }) {
  const [days, setDays] = useState<number>(() => { try { return Number(localStorage.getItem("entry_days")) || 7; } catch { return 7; } });
  const [grain, setGrain] = useState<"day" | "week" | "month">("day");
  const [d, setD] = useState<Data | null>(null), [err, setErr] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [split, setSplit] = useState<Split>(() => { try { return JSON.parse(localStorage.getItem("entry_split") || "") as Split; } catch { return { ad: false, org: false }; } });
  const setSp = (x: Split) => { setSplit(x); try { localStorage.setItem("entry_split", JSON.stringify(x)); } catch { /* */ } };
  const nms = nm.replace(/\s+/g, "");
  useEffect(() => {
    setD(null); setErr("");
    const q = new URLSearchParams({ days: String(days), grain: view === "funnel" ? grain : "day", ...(nms ? { nm_ids: nms } : {}) });
    http.get<Data>(`/api/shops/${shop}/entry_views?${q}`).then(setD).catch((e) => setErr(e.message));
  }, [shop, nms, days, grain, view]);
  const setDaysS = (n: number) => { setDays(n); try { localStorage.setItem("entry_days", String(n)); } catch { /* */ } };
  const bar = <div className="rnp-bar">
    <span className="hint">Период:</span>
    {PERIODS.map((n) => <button key={n} className={days === n ? "on" : ""} onClick={() => setDaysS(n)}>{n} дн.</button>)}
    {view === "funnel" && <><span className="hint">Столбцы:</span>
      {([["day", "По дням"], ["week", "По неделям"], ["month", "По месяцам"]] as const).map(([g, t]) =>
        <button key={g} className={grain === g ? "on" : ""} onClick={() => setGrain(g)}>{t}</button>)}</>}
    <label className="chk" title="Реклама — статистика рекламы WB (показы, переходы, корзины, заказы с рекламы); в поиске — по поисковым кластерам"><input type="checkbox" checked={split.ad} onChange={(e) => setSp({ ...split, ad: e.target.checked })} /> из них рекламных</label>
    <label className="chk" title="Органика = всего по отчёту «Точки входа» − реклама"><input type="checkbox" checked={split.org} onChange={(e) => setSp({ ...split, org: e.target.checked })} /> из них органики</label>
    {d?.d_from && <span className="hint">Данные: {dd(d.d_from)}–{dd(d.d_to!)} ({d.n_days} дн. с отчётом){grain === "month" && view === "funnel" ? " · по месяцам — до 3 месяцев" : ""}</span>}
  </div>;
  if (err) return <>{bar}<div className="err">{err}</div></>;
  if (!d) return <>{bar}<div className="hint">Загрузка…</div></>;
  if (!d.periods.length) return <>{bar}<div className="hint">Дневных отчётов «Точки входа» пока нет — их качает плагин Chrome (Пользователи и права → «Плагин Chrome»).</div></>;

  if (view === "funnel" && d.funnel) {
    const per = d.periods;
    const lines: [string, string, Row[2], boolean][] = FUNNEL.flatMap(([k, t, kind]) =>
      [[k as string, t, kind, false] as [string, string, Row[2], boolean], ...subRows(split, k as string).map(([k2, t2]) => [k2, t2, kind, true] as [string, string, Row[2], boolean])]);
    const block = (cells: Record<string, M>, head: React.ReactNode, key: string) => lines.map(([k, t, kind, sub], i) => (
      <tr key={key + k} className={i === 0 ? "rnp-first" : ""}>
        {i === 0 && <td rowSpan={lines.length} style={{ verticalAlign: "top", minWidth: 150 }}>{head}</td>}
        <td style={{ whiteSpace: "nowrap", fontWeight: k === "views" || k === "ctr" ? 600 : undefined, paddingLeft: sub ? 18 : undefined }} className={sub ? "hint" : ""}>{t}</td>
        <td className={"n" + (sub ? " hint" : "")}>{sub ? fmt(kind, gv(cells.all, k)) : <b>{fmt(kind, gv(cells.all, k))}</b>}</td>
        {per.map((p, j) => { const a = gv(cells[p.key], k), b = j + 1 < per.length ? gv(cells[per[j + 1].key], k) : null;
          return <td key={p.key} {...changeCell(a, b, growth, decline, "n" + (sub ? " hint" : ""))} style={{ whiteSpace: "nowrap" }}>{fmt(kind, a)}<Chg kind={kind} a={a} b={b} /></td>; })}
      </tr>));
    return (<>{bar}
      <div className="rnp-wrap"><table className="rnp-t entry-t">
        <thead><tr><th>Артикул</th><th>Показатель</th><th>За период</th>
          {per.map((p) => <th key={p.key}>{grain === "day" ? dd(p.d_from) : grain === "week" ? `нед. с ${dd(p.d_from)}` : p.key.slice(5) + "." + p.key.slice(0, 4)}
            {grain !== "day" && <div className="hint">{p.n_days} дн.</div>}</th>)}</tr></thead>
        <tbody>
          {block(d.funnel.total, <b>Итого{nms ? " по выбранным" : " по магазину"}</b>, "tot")}
          {d.funnel.articles.map((a) => <Fragment key={a.nm_id}>{block(a.cells, <div>
            {a.photo && <img src={a.photo} className="thumb entry-photo" alt="" loading="lazy" />}
            <div><b>{a.vendor_code || a.nm_id}</b></div><div className="hint">{a.nm_id}{a.brand ? ` · ${a.brand}` : ""}</div>
            <div className="hint">{(a.title || "").slice(0, 40)}</div></div>, String(a.nm_id))}</Fragment>)}
        </tbody></table></div>
      {d.funnel.articles_n > d.funnel.articles.length && <div className="hint">Показаны {d.funnel.articles.length} артикулов с наибольшими показами из {d.funnel.articles_n} — остальные выберите вверху страницы.</div>}
      <div className="hint">Показы, переходы, корзины, заказы (шт) — из отчёта WB «Точки входа»; заказы в ₽ и средняя цена — по нашим заказам за те же дни.</div>
    </>);
  }

  if (view === "sources") {
    const T = d.sources_total!;
    const cols = (m: M) => <>
      <td className="n">{pc(m.cro, 2)}</td><td className="n">{pc(m.crf, 2)}</td><td className="n">{pc(m.crfl, 2)}</td>
      <td className="n">{nf.format(m.views)}</td><td className="n hint">{pc(m.share_views, 2)}</td>
      <td className="n">{nf.format(m.clicks)}</td><td className="n hint">{pc(m.share_clicks, 2)}</td><td className="n">{pc(m.ctr, 2)}</td>
      <td className="n">{m.carts ? nf.format(m.carts) : ""}</td><td className="n hint">{m.carts ? pc(m.share_carts, 2) : ""}</td><td className="n">{m.carts ? pc(m.cr_cart, 2) : ""}</td>
      <td className="n">{m.orders ? nf.format(m.orders) : ""}</td><td className="n hint">{m.orders ? pc(m.share_orders, 2) : ""}</td><td className="n">{m.orders ? pc(m.cr_order, 2) : ""}</td></>;
    const sub = (m: M, p: "ad" | "org"): M => ({ ...m, views: gv(m, p + "_views") || 0, clicks: gv(m, p + "_clicks") || 0, carts: gv(m, p + "_carts") || 0,
      orders: gv(m, p + "_orders") || 0, ctr: gv(m, p + "_ctr") ?? null, cro: null, crf: null, crfl: null, cr_cart: null, cr_order: null,
      share_views: T.views ? (gv(m, p + "_views") || 0) / T.views : null, share_clicks: T.clicks ? (gv(m, p + "_clicks") || 0) / T.clicks : null,
      share_carts: T.carts ? (gv(m, p + "_carts") || 0) / T.carts : null, share_orders: T.orders ? (gv(m, p + "_orders") || 0) / T.orders : null });
    const SplitRows = ({ m }: { m: M }) => <>
      {split.ad && <tr className="hint"><td className="entry-point-cell" style={{ paddingLeft: 24 }}>↳ из них реклама</td>{cols(sub(m, "ad"))}</tr>}
      {split.org && <tr className="hint"><td className="entry-point-cell" style={{ paddingLeft: 24 }}>↳ органика</td>{cols(sub(m, "org"))}</tr>}</>;
    return (<>{bar}
      <div className="rnp-wrap"><table className={"rnp-t entry-t" + (pinPoints ? " entry-pin" : "")}>
        <thead>
          <tr><th className="entry-point-cell" rowSpan={2}>Источник трафика</th><th colSpan={3}>Конверсия</th><th colSpan={5}>Трафик</th><th colSpan={3}>Корзины</th><th colSpan={3}>Заказы</th></tr>
          <tr><th>переход → заказ (CRO)</th><th>показ → заказ (CRF)</th><th>показ → корзина (CRF(L))</th><th>Показы</th><th>Доля показов</th><th>Переходы</th>
            <th>Доля переходов</th><th>CTR</th><th>Кол-во</th><th>Доля</th><th>CR в корзину</th><th>Кол-во</th><th>Доля</th><th>Корзина → заказ</th></tr></thead>
        <tbody>
          {d.sources.filter((s) => !s.ad_only || split.ad).map((s) => <Fragment key={s.section}>
            {s.ad_only ? <tr className="hint"><td className="entry-point-cell" title="Реклама в полках, каталоге и на главной: WB отдаёт её одной суммой, по разделам не делит. Уже входит в разделы выше.">
                <i>↳ {s.section}</i></td>{cols(s)}</tr>
              : <tr style={{ cursor: "pointer" }} onClick={() => setOpen((o) => ({ ...o, [s.section]: !o[s.section] }))}>
                <td className="entry-point-cell"><b>{s.points.length ? (open[s.section] ? "▾" : "▸") : ""} {s.section}</b></td>{cols(s)}</tr>}
            {!s.ad_only && s.ad_views !== undefined && <SplitRows m={s} />}
            {open[s.section] && s.points.map((p) => <tr key={p.point}><td className="entry-point-cell" style={{ paddingLeft: 24 }}>{p.point}</td>{cols(p)}</tr>)}
          </Fragment>)}
          <tr className="rnp-first"><td className="entry-point-cell"><b>Итого</b></td>{cols(T)}</tr>
          {T.ad_views !== undefined && <SplitRows m={T} />}
        </tbody></table></div>
      <div className="hint">За {d.n_days} дн. ({dd(d.d_from!)}–{dd(d.d_to!)}). Нажмите на источник — раскроются его точки входа.</div>
    </>);
  }

  const dl = d.days || [];
  return (<>{bar}
    <div className="rnp-wrap"><table className={"rnp-t entry-t" + (pinPoints ? " entry-pin" : "")}>
      <thead><tr><th className="entry-point-cell">Источник трафика</th><th>Показатель</th><th>За период</th><th>Ср. в день</th><th>График</th>
        {dl.map((x) => <th key={x}>{dd(x)}</th>)}</tr></thead>
      <tbody>{d.sources_days.filter((s) => !s.ad_only || split.ad).map((s) => {
        const hasAd = s.all.ad_views !== undefined && !s.ad_only;
        const rows: [string, string, Row[2], boolean][] = (s.ad_only ? DAYROWS.filter(([k]) => ["views", "clicks", "carts", "orders", "ctr"].includes(k as string)) : DAYROWS)
          .flatMap(([k, t, kind]) => [[k as string, t, kind, false] as [string, string, Row[2], boolean],
            ...(hasAd ? subRows(split, k as string).map(([k2, t2]) => [k2, t2, kind, true] as [string, string, Row[2], boolean]) : [])]);
        return rows.map(([k, t, kind, sub], i) => {
          const vals = [...dl].reverse().map((x) => gv(s.days[x], k) ?? null);
          return <tr key={s.section + k} className={(i === 0 ? "rnp-first" : "") + (sub || s.ad_only ? " hint" : "")}>
            {i === 0 && <td className="entry-point-cell" rowSpan={rows.length} style={{ verticalAlign: "middle" }} title={s.ad_only ? "Реклама в полках, каталоге и на главной: WB отдаёт её одной суммой, по разделам не делит. Уже входит в разделы выше." : ""}>
              {s.ad_only ? <i>{s.section}</i> : <b>{s.section}</b>}</td>}
            <td style={{ whiteSpace: "nowrap", paddingLeft: sub ? 18 : undefined }}>{t}</td>
            <td className="n">{sub ? fmt(kind, gv(s.all, k)) : <b>{fmt(kind, gv(s.all, k))}</b>}</td>
            <td className="n">{kind === "n" && !sub ? fmt("n", s.all.per_day?.[k as "views"]) : ""}</td>
            <td>{!sub && <Spark vals={vals} />}</td>
            {dl.map((x, j) => { const a = gv(s.days[x], k), b = j + 1 < dl.length ? gv(s.days[dl[j + 1]], k) : null;
              return <td key={x} {...changeCell(a, b, growth, decline, "n")} style={{ whiteSpace: "nowrap" }}>{fmt(kind, a)}<Chg kind={kind} a={a} b={b} /></td>; })}
          </tr>;
        });
      })}</tbody></table></div>
      {split.ad && <div className="hint">Реклама в поиске — по поисковым кластерам WB (у кампаний с оплатой за клик WB не отдаёт показы по кластерам — их показы не видны). Реклама вне поиска (полки, каталог, главная) — одной строкой: WB не делит её по разделам.</div>}
  </>);
}

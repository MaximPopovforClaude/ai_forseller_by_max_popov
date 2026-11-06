import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import { http } from "./api";
import { EntryViews, type View } from "./EntryViews";

/** Точки входа WB (отчёт из ЛК — загружает пользователь): откуда приходят в карточки и как меняется каждая точка входа по периодам. */
type M = { views: number; clicks: number; carts: number; orders: number; ctr: number | null; conv_cart: number | null; conv_order: number | null; share?: number | null };
type Per = { id: string; d_from: string; d_to: string; n_days?: number };
type Rep = { id: number; d_from: string; d_to: string; file_name: string | null; uploaded_at: string; who: string | null };
type Mode = "reports" | "days" | "weeks";
type Pt = { section: string; point: string; cells: Record<string, M> };
type Data = { reports: Rep[]; periods: Per[]; points: Pt[]; total?: Record<string, M>; articles: { nm_id: number; vendor_code: string | null; title: string | null; clicks: number }[];
  can_edit: boolean; has_daily?: boolean; ads?: Record<string, Record<"total" | "search" | "rest" | "organic", M>> };

const METRICS: [keyof M, string, "n" | "p"][] = [
  ["clicks", "Переходы в карточку", "n"], ["views", "Показы", "n"], ["ctr", "CTR", "p"], ["carts", "Добавления в корзину", "n"],
  ["conv_cart", "Конверсия в корзину", "p"], ["orders", "Заказы", "n"], ["conv_order", "Конверсия в заказ", "p"], ["share", "Доля переходов", "p"],
];
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const dd = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}`;
const days = (p: Per) => p.n_days ?? Math.round((new Date(p.d_to).getTime() - new Date(p.d_from).getTime()) / 86400000) + 1;

export function EntryPoints({ shop, nm, hideChg = false }: { shop: number; nm: string; hideChg?: boolean }) {
  const [view, setView] = useState<View | "detail">(() => { try { return (localStorage.getItem("entry_view") as View) || "funnel"; } catch { return "funnel"; } });
  const pickView = (v: View | "detail") => { setView(v); try { localStorage.setItem("entry_view", v); } catch { /* */ } };
  const tabs = <div className="rnp-bar entry-tabs">
    {([["funnel", "Воронка артикулов"], ["sources", "Источники трафика"], ["sources_days", "Источники трафика по дням"], ["detail", "Точки входа подробно"]] as const)
      .map(([v, t]) => <button key={v} className={view === v ? "on" : ""} onClick={() => pickView(v)}>{t}</button>)}
  </div>;
  if (view !== "detail") return <div className="entry">{tabs}<EntryViews shop={shop} nm={nm} view={view} /></div>;
  return <div className="entry">{tabs}<EntryDetail shop={shop} nm={nm} hideChg={hideChg} /></div>;
}

function EntryDetail({ shop, nm, hideChg = false }: { shop: number; nm: string; hideChg?: boolean }) {
  const [d, setD] = useState<Data | null>(null);
  const [mode, setMode] = useState<Mode>(() => { try { return (localStorage.getItem("entry_mode") as Mode) || "days"; } catch { return "days"; } });
  const [pick, setPick] = useState<number[]>([]);         // режим «отчёты»: выбранные для сравнения
  const [split, setSplit] = useState<{ ad: boolean; org: boolean }>(() => { try { return JSON.parse(localStorage.getItem("entry_split") || ""); } catch { return { ad: false, org: false }; } });
  const setSp = (x: { ad: boolean; org: boolean }) => { setSplit(x); try { localStorage.setItem("entry_split", JSON.stringify(x)); } catch { /* */ } };
  const [metrics, setMetrics] = useState<(keyof M)[]>(["clicks"]);     // до 3 показателей рядом
  const [perDay, setPerDay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const nms = nm.replace(/\s+/g, "");
  const q = new URLSearchParams({ mode, ...(nms ? { nm_ids: nms } : {}), ...(mode === "reports" && pick.length ? { reports: pick.join(",") } : {}) });
  const load = () => http.get<Data>(`/api/shops/${shop}/entry_points?${q}`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); }, [shop, nms, mode, pick.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps
  const setM = (m: Mode) => { setMode(m); try { localStorage.setItem("entry_mode", m); } catch { /* */ } };
  const upload = async (list: File[]) => {
    setErr(""); setMsg("");
    for (const f of list) {
      setBusy(true);
      try {
        const r = await fetch(`/api/shops/${shop}/entry_points?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f, credentials: "same-origin",
          headers: { "Content-Type": "application/octet-stream" } });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || r.statusText);
        setMsg(`Загружено: ${dd(j.d_from)}–${dd(j.d_to)}, ${j.articles} артикулов`);
      } catch (e) { setErr(`${f.name}: ${(e as Error).message}`); }
      setBusy(false);
    }
    load();
  };
  const kindOf = (k: keyof M) => METRICS.find((m) => m[0] === k)?.[2] || "n";
  const titleOf = (k: keyof M) => METRICS.find((m) => m[0] === k)?.[1] || k;
  const toggle = (k: keyof M) => setMetrics((xs) => xs.includes(k) ? (xs.length > 1 ? xs.filter((x) => x !== k) : xs)
    : [...(xs.length >= 3 ? xs.slice(1) : xs), k]);
  const anyN = metrics.some((k) => kindOf(k) === "n");
  const val = (metric: keyof M, m: M | undefined, p: Per): number | null => {
    if (!m) return null;
    const v = m[metric] as number | null | undefined;
    if (v == null) return null;
    return kindOf(metric) === "n" && perDay ? v / days(p) : v;
  };
  const fmt = (metric: keyof M, v: number | null) => v == null ? "—" : kindOf(metric) === "p" ? (v * 100).toFixed(1).replace(".", ",") + " %"
    : perDay && v < 100 ? v.toFixed(1).replace(".", ",") : nf.format(v);
  const dyn = (metric: keyof M, a: number | null, b: number | null) => {           // a — новее, b — старше
    const kind = kindOf(metric);
    if (a == null || b == null) return null;
    if (kind === "p") return { t: `${a - b >= 0 ? "+" : "−"}${(Math.abs(a - b) * 100).toFixed(1).replace(".", ",")} п.п.`, good: a >= b };
    if (!b) return null;
    const ch = (a - b) / b;
    return { t: `${ch >= 0 ? "+" : "−"}${Math.abs(ch * 100).toFixed(0)} %`, good: ch >= 0 };
  };
  const per = d?.periods || [];
  const chart = useMemo(() => {
    if (!d || mode !== "days" || per.length < 2) return null;
    const k = metrics[0], asc = [...per].reverse();
    const top = d.points.slice(0, 8);
    return {
      tooltip: { trigger: "axis", valueFormatter: (v: number) => fmt(k, v) },
      legend: { type: "scroll", bottom: 0 },
      grid: { left: 50, right: 20, top: 30, bottom: 50 },
      title: { text: titleOf(k) + " по дням", left: 0, textStyle: { fontSize: 13 } },
      xAxis: { type: "category", data: asc.map((p) => dd(p.d_to)) },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => kindOf(k) === "p" ? (v * 100).toFixed(0) + "%" : nf.format(v) } },
      series: top.map((r) => ({ name: r.point, type: "line", smooth: true, symbolSize: 4,
        data: asc.map((p) => { const m = r.cells[p.id]; return m ? (m[k] as number | null) : null; }) })),
    };
  }, [d, mode, metrics.join(",")]);   // eslint-disable-line react-hooks/exhaustive-deps
  const cells = (row: Record<string, M>, bold: boolean) => per.map((p, i) => <Fragment key={p.id}>{metrics.map((k) => {
    const a = val(k, row[String(p.id)], p), b = i + 1 < per.length ? val(k, row[String(per[i + 1].id)], per[i + 1]) : null;
    const x = dyn(k, a, b);
    return <Fragment key={k}><td>{bold ? <b>{fmt(k, a)}</b> : fmt(k, a)}</td>
      {i + 1 < per.length && !hideChg && <td className={x ? (x.good ? "t-good" : "t-bad") : ""}>{x?.t || ""}</td>}</Fragment>;
  })}</Fragment>);
  return (
    <div className="entry">
      <div className="rnp-bar">
        {d?.can_edit && <>
          <input ref={file} type="file" accept=".xlsx,.zip" multiple hidden onChange={(e) => { upload(Array.from(e.target.files || [])); e.target.value = ""; }} />
          <button disabled={busy} onClick={() => file.current?.click()}>{busy ? "Загружаю…" : "⬆ Загрузить отчёт из ЛК WB"}</button>
        </>}
        <span className="hint">Столбцы:</span>
        {([["days", "По дням (30)"], ["weeks", "Неделя к неделе"], ["reports", "Загруженные отчёты"]] as [Mode, string][]).map(([m, t]) =>
          <button key={m} className={mode === m ? "on" : ""} onClick={() => setM(m)}>{t}</button>)}
        <span className="hint">{nms ? "Выбранные артикулы (вверху страницы)" : "Весь магазин — артикулы выбираются вверху страницы"}</span>
        <span className="hint">Показатели (до 3):</span>
        {METRICS.map(([k, t]) => <button key={k} className={metrics.includes(k) ? "on" : ""} onClick={() => toggle(k)}>{t}</button>)}
        <label className="chk"><input type="checkbox" checked={split.ad} onChange={(e) => setSp({ ...split, ad: e.target.checked })} /> из них рекламных</label>
        <label className="chk"><input type="checkbox" checked={split.org} onChange={(e) => setSp({ ...split, org: e.target.checked })} /> из них органики</label>
        {anyN && <label className="chk" title="Периоды разной длины (неделя, 2 недели) — сравнивать удобнее в среднем за день">
          <input type="checkbox" checked={perDay} onChange={(e) => setPerDay(e.target.checked)} /> в день</label>}
        {msg && <span className="ok">{msg}</span>}
      </div>
      {err && <div className="err">{err}</div>}
      <div className="hint">Отчёта нет в API WB. Скачайте в ЛК WB: «Аналитика» → «Портрет покупателя» → «Точки входа» → период → «Скачать», и загрузите сюда
        (xlsx или zip), либо поставьте плагин Chrome — он качает отчёт сам за каждый день. Каждый период — отдельный столбец, повтор того же периода заменяет прошлый. CTR и конверсии считаем из штук (в файле WB они округлены).</div>
      {d && !per.length && <div className="hint">{mode !== "reports" && d.reports.length ? "Дневных отчётов пока нет — их качает плагин Chrome (Аккаунт → «Плагин Chrome») или загрузите отчёт за один день." : "Пока ничего не загружено."}</div>}
      {mode === "weeks" && per.length > 0 && <div className="hint">Окна по 7 дней от последнего загруженного дня; «в день» — среднее по дням, за которые есть отчёт.</div>}
      {chart && <div className="acc-box"><ReactECharts option={chart} style={{ height: 300 }} notMerge /></div>}
      {per.length > 0 && <div className="rnp-wrap">
        <table className="rnp-t entry-t">
          <thead><tr><th rowSpan={2}>Раздел</th><th rowSpan={2}>Точка входа</th>
            {per.map((p, i) => <th key={p.id} colSpan={metrics.length * (i + 1 < per.length && !hideChg ? 2 : 1)} className="rnp-month">
              {dd(p.d_from)}–{dd(p.d_to)} <span className="hint">{days(p)} дн.</span></th>)}</tr>
            <tr>{per.map((p, i) => <Fragment key={p.id}>{metrics.map((k) => <Fragment key={k}><th>{titleOf(k)}</th>
              {i + 1 < per.length && !hideChg && <th className="hint">изм.</th>}</Fragment>)}</Fragment>)}</tr></thead>
          <tbody>
            {d?.total && <tr className="rnp-first"><td colSpan={2}><b>Итого {nm ? "по артикулу" : "по магазину"}</b></td>
              {cells({ ...Object.fromEntries(per.filter((p) => d.total![p.id]).map((p) => [p.id, { ...d.total![p.id], share: 1 }])) }, true)}</tr>}
            {d?.ads && ([...(split.ad ? [["total", "↳ из них реклама (вся)"], ["search", "   ↳ реклама в поиске"], ["rest", "   ↳ реклама вне поиска (полки, каталог, главная)"]] : []),
              ...(split.org ? [["organic", "↳ органика"]] : [])] as ["total" | "search" | "rest" | "organic", string][]).map(([k, t]) =>
              <tr key={"ads" + k} className="hint"><td colSpan={2} style={{ whiteSpace: "pre" }}>{t}</td>
                {cells(Object.fromEntries(per.filter((p) => d.ads![p.id]).map((p) => [p.id, { ...d.ads![p.id][k], share: d.total![p.id]?.clicks ? d.ads![p.id][k].clicks / d.total![p.id].clicks : null }])), false)}</tr>)}
            {(d?.points || []).map((r) => (
              <tr key={r.section + r.point}>
                <td className="hint">{r.section}</td><td>{r.point}</td>
                {cells(r.cells, false)}
              </tr>))}
          </tbody>
        </table>
      </div>}
      {d && d.reports.length > 0 && <details className="acc-box"><summary>Загруженные отчёты ({d.reports.length})</summary>
        {mode === "reports" && <div className="hint">Отметьте отчёты, которые сравнить (до 30); без отметок — 8 последних.
          {pick.length > 0 && <button className="link" onClick={() => setPick([])}>сбросить выбор</button>}</div>}
        {d.reports.map((r) => <div key={r.id} className="acc-row"><span>
          {mode === "reports" && <input type="checkbox" checked={pick.includes(r.id)} onChange={(e) => setPick((xs) => e.target.checked ? [...xs, r.id].slice(-30) : xs.filter((x) => x !== r.id))} />}
          {dd(r.d_from)}–{dd(r.d_to)}</span>
          <span className="hint">{r.file_name} · {r.who || ""} · {new Date(r.uploaded_at).toLocaleString("ru-RU")}</span>
          {d.can_edit && <button className="link" onClick={() => { if (confirm("Удалить этот отчёт из сервиса?")) http.del(`/api/shops/${shop}/entry_points/${r.id}`).then(load); }}>удалить</button>}
        </div>)}</details>}
    </div>
  );
}

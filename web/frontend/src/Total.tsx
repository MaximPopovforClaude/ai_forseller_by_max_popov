import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { ManagerPicker } from "./ManagerPicker";
import { http } from "./api";

type K = "orders" | "buyouts" | "margin" | "ads" | "profit";
type V = Record<K, number> & { cost_sold?: number | null };
type Shop = { id: number; title: string; mp: string; workspace: string | null; series?: Record<string, V>; stale?: boolean; error?: string };
type Res = { days: string[]; today: string; shops: Shop[]; staff: { id: number; name: string; workspace: string }[] };

const KEYS: K[] = ["orders", "buyouts", "margin", "ads", "profit"];
// строки таблицы: суммы ₽ и доли (из сумм, не среднее процентов)
const ROWS: { key: string; title: string; pct?: boolean; f: (v: V) => number | null }[] = [
  { key: "orders", title: "Заказы, ₽", f: (v) => v.orders },
  { key: "buyouts", title: "Выкупы, ₽", f: (v) => v.buyouts },
  { key: "cost_sold", title: "Себестоимость проданного, ₽", f: (v) => v.cost_sold ?? null },
  { key: "margin", title: "Маржа, ₽", f: (v) => v.margin },
  { key: "margin_p", title: "Маржа, % от выкупов", pct: true, f: (v) => (v.buyouts ? v.margin / v.buyouts : 0) },
  { key: "ads", title: "Реклама, ₽", f: (v) => -v.ads },
  { key: "drr", title: "ДРР от заказов, %", pct: true, f: (v) => (v.orders ? -v.ads / v.orders : 0) },
  { key: "profit", title: "Прибыль, ₽", f: (v) => v.profit },
  { key: "profit_p", title: "Прибыль, % от выкупов", pct: true, f: (v) => (v.buyouts ? v.profit / v.buyouts : 0) },
  { key: "return_on_cost", title: "Рентабельность, %", pct: true, f: (v) => v.cost_sold != null && v.cost_sold > 0 ? v.profit / v.cost_sold : null },
];
const LINES: { key: string; color: string }[] = [
  { key: "orders", color: "#7c3aed" }, { key: "buyouts", color: "#0891b2" }, { key: "margin", color: "#ea580c" },
  { key: "cost_sold", color: "#a16207" }, { key: "return_on_cost", color: "#0d9488" },
  { key: "profit", color: "#16a34a" }, { key: "ads", color: "#db2777" }, { key: "drr", color: "#94a3b8" },
];
const rub = (x: number) => Math.round(x).toLocaleString("ru-RU");
const pct = (x: number | null | undefined) => x == null ? "—" : (x * 100).toFixed(1).replace(".", ",") + " %";
const zero = (): V => ({ orders: 0, buyouts: 0, margin: 0, ads: 0, profit: 0, cost_sold: 0 });
function add(target: V, value: V) {
  for (const key of KEYS) target[key] += value[key];
  // An old/missing cost field must not produce a partial total or NaN.
  target.cost_sold = target.cost_sold != null && Number.isFinite(value.cost_sold)
    ? target.cost_sold + value.cost_sold! : null;
}
function show(row: typeof ROWS[number], values: V, rubles = false) {
  const value = row.f(values);
  return value == null ? "—" : row.pct ? pct(value) : rub(value) + (rubles ? " ₽" : "");
}
const OFF = "total_off";

/** 📊 Сумма магазинов: ключевые показатели по дням за месяц, сложенные по выбранным магазинам (по умолчанию — все доступные). */
export function Total({ dark, presentation, onPresentationChange, shopIds }: {
  dark: boolean; presentation: boolean; onPresentationChange: (value: boolean) => void; shopIds: number[];
}) {
  const [r, setR] = useState<Res | null>(null);
  const [err, setErr] = useState("");
  const [off, setOff] = useState<number[]>(() => { try { return JSON.parse(localStorage.getItem(OFF) || "[]"); } catch { return []; } });
  const [staff, setStaff] = useState<string>("");            // менеджер: только его артикулы во всех его магазинах
  const [staffList, setStaffList] = useState<Res["staff"]>([]);
  useEffect(() => {
    let alive = true;
    setR(null); setErr("");
    http.get<Res>(`/api/total${staff ? `?staff=${staff}` : ""}`).then((x) => {
      if (!alive) return;
      setR(x); if (!staff) setStaffList(x.staff);
    }).catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [staff]);
  const save = (n: number[]) => { setOff(n); try { localStorage.setItem(OFF, JSON.stringify(n)); } catch { /* нет хранилища */ } };
  const on = useMemo(() => (r?.shops || []).filter((s) => s.series && !off.includes(s.id)), [r, off]);
  const sum = useMemo(() => {
    const by: Record<string, V> = {};
    const all = zero();
    for (const d of r?.days || []) by[d] = zero();
    for (const s of on) for (const [d, v] of Object.entries(s.series!)) {
      if (!by[d]) continue;
      add(by[d], v); add(all, v);
    }
    return { by, all };
  }, [r, on]);
  // All authorized shop IDs, rather than filtered row positions: numbers stay
  // stable when changing managers or toggling stores. No names in DOM titles.
  const numbered = [...new Set([...shopIds, ...(r?.shops || []).map(s => s.id)])].sort((a, b) => a - b);
  const name = (s: Shop) => presentation ? String(numbered.indexOf(s.id) + 1) : s.title;
  const error = (s: Shop) => s.error ? (presentation ? "Данные магазина пока недоступны" : s.error) : "";
  const toolbar = <div className="total-presentation-bar"><b>Сумма магазинов</b>
    <button className={presentation ? "on" : ""} aria-pressed={presentation} onClick={() => onPresentationChange(!presentation)}>
      {presentation ? "Обычная версия" : "Версия для демонстрации"}</button>
    {presentation && <span className="hint">Названия скрыты. Финансовые показатели настоящие.</span>}
  </div>;
  if (err) return <div className="total">{toolbar}<div className="err">{presentation ? "Не удалось загрузить показатели. Попробуйте открыть раздел позже." : err}</div></div>;
  if (!r) return <div className="total">{toolbar}<div className="hint">Складываю магазины…</div></div>;
  const days = r.days;
  const desc = [...days].reverse();
  const hasOz = on.some((s) => s.mp === "ozon");
  const wss = [...new Set(r.shops.map((s) => s.workspace || ""))];
  const txt = dark ? "#e6e8ee" : "#1d2330";
  const opt = {
    tooltip: { trigger: "axis" },
    legend: { type: "scroll", textStyle: { color: txt }, selected: { "Реклама, ₽": false, "ДРР от заказов, %": false, "Себестоимость проданного, ₽": false, "Рентабельность, %": false } },
    grid: { left: 70, right: 50, top: 40, bottom: 30 },
    xAxis: { type: "category", data: days.map((d) => `${d.slice(8)}.${d.slice(5, 7)}`), axisLabel: { color: txt } },
    yAxis: [{ type: "value", axisLabel: { color: txt, formatter: (x: number) => (Math.abs(x) >= 1e6 ? `${x / 1e6} млн` : Math.abs(x) >= 1e3 ? `${x / 1e3} тыс` : x) } },
      { type: "value", axisLabel: { color: txt, formatter: (x: number) => `${Math.round(x * 100)} %` }, splitLine: { show: false } }],
    series: LINES.map((l) => {
      const row = ROWS.find((x) => x.key === l.key)!;
      return { name: row.title, type: "line", smooth: true, yAxisIndex: row.pct ? 1 : 0, itemStyle: { color: l.color },
        tooltip: { valueFormatter: (x: number | null) => x == null ? "—" : (row.pct ? pct(x) : rub(x) + " ₽") },
        data: days.map((d) => row.f(sum.by[d])) };
    }),
  };
  return (
    <div className="total">
      {toolbar}
      <div className="acc-box">
        <div className="board-bar"><b>Магазины</b>
          <button className="link" onClick={() => save([])}>все</button>
          <button className="link" onClick={() => save(r.shops.map((s) => s.id))}>ни одного</button>
          <span className="hint">выбор запоминается</span>
          {staffList.length > 0 && <ManagerPicker value={staff} onChange={setStaff}
            items={staffList.map((s, i) => ({ id: s.id, name: presentation ? `Менеджер ${i + 1}` : `${s.name}${new Set(staffList.map(x => x.workspace)).size > 1 ? ` · ${s.workspace}` : ""}` }))} />}</div>
        {wss.map((w) => (
          <div key={w} className="total-shops">
            {!presentation && wss.length > 1 && <span className="total-ws">{w || "—"}</span>}
            {r.shops.filter((s) => (s.workspace || "") === w).map((s) => (
              <label key={s.id} className={"total-shop" + (s.error ? " dis" : "")} title={error(s)}>
                <input type="checkbox" disabled={!!s.error} checked={!s.error && !off.includes(s.id)}
                  onChange={(e) => save(e.target.checked ? off.filter((x) => x !== s.id) : [...off, s.id])} />
                {name(s)} <span className="total-mp">{s.mp === "ozon" ? "Ozon" : s.mp === "ym" ? "Маркет" : "WB"}</span>{s.error && <i> — {error(s)}</i>}
              </label>))}
          </div>))}
      </div>
      {!on.length ? <div className="hint">Выберите хотя бы один магазин.</div> : <>
        <div className="total-kpi">
          {ROWS.filter((x) => !x.key.endsWith("_p")).map((x) => (
            <div key={x.key} className="total-tile"><div className="t">{x.title.replace(", ₽", "").replace(", %", "")} за 30 дней</div>
              <div className="v">{show(x, sum.all, true)}</div>
              {(x.key === "margin" || x.key === "profit") && <div className="s">{pct(ROWS.find((y) => y.key === x.key + "_p")!.f(sum.all))} от выкупов</div>}
            </div>))}
        </div>
        <div className="acc-box"><ReactECharts option={opt} style={{ height: 340 }} notMerge /></div>
        <div className="hint">WB — как во вкладке «4#ДашбордПоДням» (выкупы, маржа и прибыль — по дню выкупа), Ozon — как в «3#Дашборд» (выкупы и
          оперативная прибыль — по начислениям Ozon). Сегодня — неполный день{hasOz ? "; Ozon за сегодня ещё не считается" : ""}.
          {on.some((s) => s.stale) && " Часть магазинов — по расчёту на утро, свежий считается фоном."}</div>
        <div className="hint">Себестоимость проданного — из того же дашборда, что и прибыль; в Ozon за вычетом возвратов.
          Рентабельность = прибыль / себестоимость проданного × 100 %. Итог считается из общих сумм выбранных магазинов.
          При неизвестной себестоимости или значении ≤ 0 рентабельность не рассчитывается.</div>
        <div className="board-wrap"><table className="board-t total-t">
          <thead><tr><th>Показатель</th><th>Итого</th>{desc.map((d) => <th key={d}>{d === r.today ? "сегодня" : `${d.slice(8)}.${d.slice(5, 7)}`}</th>)}</tr></thead>
          <tbody>{ROWS.map((x) => (
            <tr key={x.key} className={x.pct ? "pct" : ""}><td>{x.title}</td>
              <td><b>{show(x, sum.all)}</b></td>
              {desc.map((d) => { const v = x.f(sum.by[d]); return <td key={d} className={v != null && v < 0 ? "neg" : ""}>{show(x, sum.by[d])}</td>; })}
            </tr>))}</tbody>
        </table></div>
        <div className="board-wrap"><table className="board-t total-t">
          <thead><tr><th>Магазин за 30 дней</th>{ROWS.map((x) => <th key={x.key}>{x.title}</th>)}</tr></thead>
          <tbody>{on.map((s) => {
            const t = zero();
            for (const [d, v] of Object.entries(s.series!)) if (sum.by[d]) add(t, v);
            return <tr key={s.id}><td>{name(s)} <span className="total-mp">{s.mp === "ozon" ? "Ozon" : s.mp === "ym" ? "Маркет" : "WB"}</span></td>
              {ROWS.map((x) => { const v = x.f(t); return <td key={x.key} className={v != null && v < 0 ? "neg" : ""}>{show(x, t)}</td>; })}</tr>;
          })}</tbody>
        </table></div>
      </>}
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { TabData } from "./api";

const MAX = 5;
const NUMERIC = new Set(["int", "money", "num", "pct", "share"]);
const NOT_METRIC = new Set(["nm_id", "imt_id", "subject_id", "year_week", "year_month"]);
const ADDITIVE = new Set(["int", "money"]);

/** График к таблице: любой числовой столбец, до 5 одновременно. Доли (%) — на правой оси.
 *  Если на одну дату приходится несколько строк (например, артикул × день), суммы складываются,
 *  а доли выводить нельзя (их нельзя складывать) — такие столбцы недоступны, пока не выбран один артикул. */
export function ChartPanel({ data, dark }: { data: TabData; dark: boolean }) {
  const xCol = useMemo(() => data.columns.find((c) => c.type === "date")
    ?? data.columns.find((c) => c.type === "text"), [data.columns]);
  const metrics = useMemo(() => data.columns.filter((c) => NUMERIC.has(c.type) && !NOT_METRIC.has(c.field)), [data.columns]);
  // выбор артикулов для графика: все (сумма) / выбранные (сумма) / выбранные — каждый своей линией
  const hasNm = data.columns.some((c) => c.field === "nm_id") && xCol?.field !== "nm_id";
  const arts = useMemo(() => {
    if (!hasNm) return [];
    const m = new Map<number, string>();
    for (const r of data.rows) {
      const id = Number(r.nm_id);
      if (!id || m.has(id)) continue;
      const vc = r.vendor_code ?? r.supplier_article ?? r.title ?? "";
      m.set(id, vc ? `${id} · ${String(vc).slice(0, 40)}` : String(id));
    }
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [data.rows, hasNm]);
  const [artSel, setArtSel] = useState<number[]>([]);
  const [split, setSplit] = useState(false);
  const [artOpen, setArtOpen] = useState(false);
  const [artQ, setArtQ] = useState("");
  useEffect(() => { setArtSel((s) => s.filter((id) => arts.some(([a]) => a === id))); }, [arts]);
  const rows = useMemo(() => (artSel.length ? data.rows.filter((r) => artSel.includes(Number(r.nm_id))) : data.rows), [data.rows, artSel]);
  const splitOn = split && artSel.length > 0;
  const multi = useMemo(() => {
    if (!xCol) return false;
    const seen = new Set<string>();
    for (const r of rows) { const k = String(r[xCol.field]) + (splitOn ? "|" + r.nm_id : ""); if (seen.has(k)) return true; seen.add(k); }
    return false;
  }, [rows, xCol, splitOn]);
  const artName = (id: number) => arts.find(([a]) => a === id)?.[1] ?? String(id);

  const storeKey = `chart:${data.key}`;
  const defaults = () => {
    try { const v = JSON.parse(localStorage.getItem(storeKey) || "null"); if (Array.isArray(v)) return v as string[]; } catch { /* нет хранилища */ }
    return data.chart?.series.map((s) => s.field) ?? metrics.slice(0, 1).map((m) => m.field);
  };
  const [sel, setSel] = useState<string[]>(defaults);
  const [open, setOpen] = useState(false);
  // вид каждой линии: линия / столбцы / область (запоминается по столбцу)
  type Kind = "line" | "bar" | "area" | "step";
  const [kinds, setKinds] = useState<Record<string, Kind>>(() => { try { return JSON.parse(localStorage.getItem("chart_kinds") || "{}"); } catch { return {}; } });
  const setKind = (f: string, k: Kind) => setKinds((x) => { const n = { ...x, [f]: k }; try { localStorage.setItem("chart_kinds", JSON.stringify(n)); } catch { /* нет хранилища */ } return n; });
  const [show, setShowRaw] = useState<boolean>(() => { try { return localStorage.getItem("chart_show") !== "0"; } catch { return true; } });
  const setShow = (v: boolean) => { setShowRaw(v); try { localStorage.setItem("chart_show", v ? "1" : "0"); } catch { /* нет хранилища */ } };
  useEffect(() => { setSel(defaults()); }, [data.key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem(storeKey, JSON.stringify(sel)); } catch { /* нет хранилища */ } }, [sel, storeKey]);

  const usable = (t: string) => !multi || ADDITIVE.has(t);
  const active = sel.filter((f) => metrics.some((m) => m.field === f && usable(m.type)));

  const option = useMemo(() => {
    if (!xCol || !active.length || !rows.length) return null;
    const agg = new Map<string, Record<string, number | null>>();
    for (const r of rows) {
      const x = String(r[xCol.field] ?? "").slice(0, xCol.type === "date" ? 10 : 60);
      const acc = agg.get(x) ?? {};
      for (const f of active) {
        const v = r[f];
        if (v == null) continue;
        const key = splitOn ? `${r.nm_id}|${f}` : f;
        acc[key] = (acc[key] ?? 0) + Number(v);
      }
      agg.set(x, acc);
    }
    const xs = [...agg.keys()].sort();
    const fmtX = (x: string) => (xCol.type === "date" ? x.split("-").reverse().slice(0, 2).join(".") : x);
    // своя ось у каждой единицы измерения: рубли, штуки, проценты — иначе штуки (5) не видны рядом с рублями (40 000)
    const unit = (t: string) => (t === "share" || t === "pct" ? "pct" : t === "money" ? "money" : "count");
    const units = [...new Set(active.map((f) => unit(metrics.find((c) => c.field === f)!.type)))];
    const axisName: Record<string, string> = { money: "₽", count: "шт", pct: "%" };
    const yAxis = units.map((u, i) => ({
      type: "value", name: axisName[u], position: i === 0 ? "left" : "right", offset: i === 2 ? 64 : 0,
      splitLine: { show: i === 0 }, axisLabel: { formatter: u === "pct" ? "{value} %" : undefined },
    }));
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" }, legend: { top: 0 }, grid: { left: 64, right: units.length > 2 ? 128 : 64, top: 40, bottom: 28 },
      xAxis: { type: "category", data: xs.map(fmtX) },
      yAxis,
      series: (splitOn ? artSel.flatMap((id) => active.map((f, i) => ({ f, i, id }))) : active.map((f, i) => ({ f, i, id: 0 }))).map(({ f, i, id }) => {
        const m = metrics.find((c) => c.field === f)!;
        const k = m.type === "share" ? 100 : 1;
        const kind: Kind = kinds[f] ?? (i === 0 && unit(m.type) !== "pct" ? "bar" : "line");
        const key = splitOn ? `${id}|${f}` : f;
        return { name: splitOn ? `${artName(id)} · ${m.title}` : m.title, type: kind === "bar" ? "bar" : "line", smooth: kind === "line" || kind === "area",
          step: kind === "step" ? "middle" : undefined, areaStyle: kind === "area" ? { opacity: 0.25 } : undefined, yAxisIndex: units.indexOf(unit(m.type)),
          data: xs.map((x) => { const v = agg.get(x)?.[key]; return v == null ? null : Math.round(v * k * 100) / 100; }) };
      }),
    };
  }, [rows, xCol, active.join(","), metrics, kinds, splitOn, artSel.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!xCol || !metrics.length) return null;
  const toggle = (f: string) => setSel((s) => (s.includes(f) ? s.filter((x) => x !== f) : s.length >= MAX ? s : [...s, f]));

  return (
    <div className="chart">
      <div className="chart-bar">
        <button className="chart-toggle" onClick={() => setShow(!show)}>{show ? "▴ Скрыть график" : "▾ Показать график"}</button>
        {show && arts.length > 1 && (
          <button onClick={() => setArtOpen(!artOpen)} title="По каким артикулам строить график">
            Артикулы: {artSel.length ? `${artSel.length} из ${arts.length}${splitOn ? ", раздельно" : ""}` : "все"} ▾
          </button>
        )}
        {show && <button onClick={() => setOpen(!open)}>Столбцы: {active.length} из {MAX} ▾</button>}
        {show && active.map((f, i) => {
          const m = metrics.find((x) => x.field === f)!;
          const cur = kinds[f] ?? (i === 0 && m.type !== "share" && m.type !== "pct" ? "bar" : "line");
          return (
            <span key={f} className="chip">
              <select className="kind" title="Вид графика" value={cur} onChange={(e) => setKind(f, e.target.value as Kind)}>
                <option value="line">📈 линия</option><option value="bar">📊 столбцы</option>
                <option value="area">◭ область</option><option value="step">▙ ступени</option>
              </select>
              {m.title} <span className="x" title="Убрать с графика" onClick={() => toggle(f)}>✕</span>
            </span>
          );
        })}
        {multi && show && <span className="hint">несколько артикулов на дату — суммы сложены; доли (%) — выберите один артикул или «каждый отдельной линией»</span>}
      </div>
      {show && artOpen && (
        <div className="art-pick">
          <div className="art-bar">
            <input placeholder="Найти артикул…" value={artQ} onChange={(e) => setArtQ(e.target.value)} />
            <button onClick={() => setArtSel([])}>Все артикулы (сумма)</button>
            <label title="Каждый выбранный артикул — своей линией (до 10)"><input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} /> каждый отдельной линией</label>
          </div>
          <div className="art-list">
            {arts.filter(([, n]) => !artQ || n.toLowerCase().includes(artQ.toLowerCase())).map(([id, n]) => {
              const on = artSel.includes(id);
              const dis = !on && split && artSel.length >= 10;
              return (
                <label key={id} className={dis ? "dis" : ""}>
                  <input type="checkbox" checked={on} disabled={dis}
                    onChange={() => setArtSel((s) => (on ? s.filter((x) => x !== id) : [...s, id]))} /> {n}
                </label>
              );
            })}
          </div>
        </div>
      )}
      {show && open && (
        <div className="chart-pick">
          {metrics.map((m) => {
            const on = sel.includes(m.field);
            const dis = !usable(m.type) || (!on && sel.length >= MAX);
            return (
              <label key={m.field} className={dis ? "dis" : ""}>
                <input type="checkbox" checked={on} disabled={dis && !on} onChange={() => toggle(m.field)} /> {m.title}
              </label>
            );
          })}
        </div>
      )}
      {show && option && <ReactECharts option={option} theme={dark ? "dark" : undefined} style={{ height: 280 }} notMerge />}
      {show && !option && <div className="hint">Выберите столбцы для графика</div>}
    </div>
  );
}

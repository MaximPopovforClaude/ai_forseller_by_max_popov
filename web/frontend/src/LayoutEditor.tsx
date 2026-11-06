import { useEffect, useState } from "react";
import type { TabData } from "./api";

type Row = [string, string, string]; // группа, показатель, период
type Hid = [string, string, string, number?]; // + место, где колонка стояла

/** Настройка колонок сводной: как в таблице «Выберите показатель и период» — показатель листа БД и период для каждой колонки. */
export function LayoutEditor({ data, onSave }: { data: TabData; onSave: (v: { cols: Row[]; hidden: Hid[] } | null) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<Row[]>(data.col_layout || []);
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState<Hid[]>(data.col_hidden || []);
  const [showHid, setShowHid] = useState(false);
  useEffect(() => { setRows(data.col_layout || []); setHidden(data.col_hidden || []); }, [data.col_layout, data.col_hidden]);
  const hide = (i: number) => { setHidden((h) => [...h, [...rows[i], i] as Hid]); setRows(rows.filter((_, k) => k !== i)); };
  const restore = (j: number) => {
    const [g, m, p, at] = hidden[j];
    setRows((r) => { const a = [...r]; a.splice(Math.min(at ?? a.length, a.length), 0, [g, m, p]); return a; });
    setHidden((h) => h.filter((_, k) => k !== j));
  };
  const metrics = data.metrics || [];
  const periods = data.periods || [];
  const set = (i: number, j: number, v: string) => setRows((r) => r.map((x, k) => (k === i ? (x.map((y, m) => (m === j ? v : y)) as Row) : x)));
  const move = (i: number, d: number) => setRows((r) => {
    const a = [...r]; const j = i + d; if (j < 0 || j >= a.length) return a; [a[i], a[j]] = [a[j], a[i]]; return a;
  });
  const save = (v: { cols: Row[]; hidden: Hid[] } | null) => { setBusy(true); onSave(v).finally(() => { setBusy(false); setOpen(false); }); };

  return (
    <div className="chart">
      <div className="chart-bar">
        <button onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} Колонки и периоды ({rows.length})</button>
        {open && <>
          <button disabled={busy} onClick={() => save({ cols: rows, hidden })}>Сохранить</button>
          <button disabled={busy} onClick={() => save(null)} title="Стандартная раскладка">Сбросить к стандартным</button>
          <button onClick={() => setRows([...rows, ["", metrics[0] || "", periods[0] || "вчера"]])}>+ колонка</button>
        </>}
      </div>
      {open && (
        <div className="layout-list">
          {rows.map((r, i) => (
            <div key={i} className="layout-row">
              <input className="grp-in" placeholder="группа" value={r[0]} onChange={(e) => set(i, 0, e.target.value)} />
              <select value={r[1]} onChange={(e) => set(i, 1, e.target.value)}>
                {metrics.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
              {r[1] !== "разница" ? (
                <select value={r[2]} onChange={(e) => set(i, 2, e.target.value)}>
                  {periods.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              ) : <span className="hint">две предыдущие колонки</span>}
              <button onClick={() => move(i, -1)}>↑</button>
              <button onClick={() => move(i, 1)}>↓</button>
              <button title="Скрыть колонку (вернуть можно из «Скрытых»)" onClick={() => hide(i)}>✕</button>
            </div>
          ))}
          <button className="hid-h" onClick={() => setShowHid(!showHid)}>{showHid ? "▾" : "▸"} Скрытые ({hidden.length})</button>
          {showHid && (hidden.length ? hidden.map((h, j) => (
            <div key={j} className="layout-row hid-row">
              <span className="hid-t">{h[0] && <b>{h[0]} · </b>}{h[1]}{h[1] !== "разница" && h[2] ? ` · ${h[2]}` : ""}</span>
              <button title="Вернуть на прежнее место" onClick={() => restore(j)}>↩ вернуть</button>
            </div>
          )) : <div className="hint">Скрытых колонок нет. Нажмите ✕ у колонки — она попадёт сюда.</div>)}
          {(hidden.length > 0 || rows.length !== (data.col_layout || []).length) && <div className="hint">Изменения применятся после «Сохранить».</div>}
        </div>
      )}
    </div>
  );
}

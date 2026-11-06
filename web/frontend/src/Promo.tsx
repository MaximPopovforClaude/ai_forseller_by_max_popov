import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { http } from "./api";

/** Расчёт акций WB (видео 10X №16): по каждой акции — факт участия, «расчёт» (галочки для себя), цена по акции, маржа с акцией, разница. */
type Cell = { in_action: boolean; calc: boolean; price: number | null; margin: number | null; margin_rub: number | null; diff: number | null };
type Row = { nm_id: number; vendor_code: string | null; title: string | null; photo: string | null; turnover: number | null; stock: number | null;
  price: number | null; margin: number | null; margin_rub: number | null; no_cost: boolean; promos: Record<string, Cell> };
type P = { key: string; name: string; source: "api" | "file"; from?: string; to?: string; eligible: number; fact_pct: number | null; calc_pct: number | null };
type Data = { rows: Row[]; promos: P[]; can_edit: boolean };
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const pc = (v: number | null | undefined) => (v == null ? "" : (v * 100).toFixed(2).replace(".", ",") + " %");
const rub = (v: number | null | undefined) => (v == null ? "" : nf.format(v) + " ₽");
/** Маржа: рубли и проценты; нет себестоимости — так и пишем (иначе пустая ячейка непонятна). */
const Mg = ({ r, p, noCost }: { r: number | null | undefined; p: number | null | undefined; noCost: boolean }) =>
  noCost ? <span className="hint">нет себестоимости</span> : r == null && p == null ? null : <>{rub(r)}<div className="hint">{pc(p)}</div></>;
/** Левые столбцы, которые можно закрепить ; выбор — в браузере пользователя. */
const FIXED = [["photo", "Фото"], ["art", "Артикул"], ["turn", "Оборачиваемость"], ["stock", "Остаток"], ["price", "Цена до СПП"], ["margin", "Маржа актуал."]] as const;
const loadPins = (): string[] => { try { const v = JSON.parse(localStorage.getItem("promo_pins") || "null"); if (Array.isArray(v)) return v; } catch { /* */ } return ["photo", "art"]; };
const zone = (v: number | null | undefined) => (v == null ? "" : v >= 0.25 ? "z-good" : v >= 0.15 ? "z-mid" : "z-bad");

export function Promo({ shop }: { shop: number }) {
  const [d, setD] = useState<Data | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [onlyIn, setOnlyIn] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const [pins, setPins] = useState<string[]>(loadPins);
  const [lefts, setLefts] = useState<number[]>([]);
  const ths = useRef<(HTMLTableCellElement | null)[]>([]);
  const setPin = (k: string, on: boolean) => setPins((cur) => {
    const n = FIXED.map(([f]) => f).filter((f) => (f === k ? on : cur.includes(f)));
    try { localStorage.setItem("promo_pins", JSON.stringify(n)); } catch { /* */ }
    return n;
  });
  // отступ слева каждого закреплённого столбца = сумма ширин закреплённых левее
  useLayoutEffect(() => {
    let x = 0;
    setLefts(FIXED.map(([f], i) => { const l = x; if (pins.includes(f)) x += ths.current[i]?.offsetWidth || 0; return l; }));
  }, [d, pins, onlyIn]);
  const stick = (i: number, th = false) => (pins.includes(FIXED[i][0])
    ? { style: { position: "sticky" as const, left: lefts[i] || 0, zIndex: th ? 4 : 2 }, "data-pin": "" } : {});
  const load = () => http.get<Data>(`/api/shops/${shop}/promo`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const upload = async (f: File) => {
    setErr(""); setMsg(""); setBusy(true);
    try {
      const r = await fetch(`/api/shops/${shop}/promo/upload?name=${encodeURIComponent(f.name)}&title=${encodeURIComponent(title)}`,
        { method: "POST", body: f, credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" } });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      setMsg(`Акция «${title}» добавлена: ${j.items} товаров`); setTitle(""); load();
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const toggle = (p: string, nm: number, on: boolean) => {
    setD((x) => x && { ...x, rows: x.rows.map((r) => r.nm_id === nm ? { ...r, promos: { ...r.promos, [p]: { ...r.promos[p], calc: on } } } : r) });
    http.put(`/api/shops/${shop}/promo/calc`, { promo: p, nm_id: nm, on }).catch((e) => setErr(e.message));
  };
  if (!d) return <div className="hint">{err || "Загрузка…"}</div>;
  const rows = onlyIn ? d.rows.filter((r) => Object.keys(r.promos).length) : d.rows;
  const calcPct = (p: P) => { const el = d.rows.filter((r) => r.promos[p.key]); return el.length ? el.filter((r) => r.promos[p.key].calc).length / el.length : null; };
  return (
    <div className="promo">
      <div className="rnp-bar">
        {d.can_edit && <>
          <input placeholder="Название автоакции (из календаря акций WB)" value={title} onChange={(e) => setTitle(e.target.value)} style={{ minWidth: 280 }} />
          <input ref={file} type="file" accept=".xlsx,.zip" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <button disabled={busy || !title.trim()} title={title.trim() ? "" : "Сначала впишите название акции"} onClick={() => file.current?.click()}>
            {busy ? "Загружаю…" : "➕ Добавить акцию (файл из ЛК)"}</button>
          <button onClick={() => { if (confirm("Очистить расчёт: убрать все акции и галочки из таблицы?")) http.post(`/api/shops/${shop}/promo/clear`).then(load); }}>
            🗑 Очистить расчёт</button>
        </>}
        <details className="pin-pick">
          <summary title="Закрепить столбцы слева: они не уезжают при прокрутке вправо">📌 Закрепить ({pins.length})</summary>
          <div className="pin-list">{FIXED.map(([f, t]) => (
            <label key={f}><input type="checkbox" checked={pins.includes(f)} onChange={(e) => setPin(f, e.target.checked)} /> {t}</label>))}</div>
        </details>
        <label className="chk"><input type="checkbox" checked={onlyIn} onChange={(e) => setOnlyIn(e.target.checked)} /> только товары в акциях</label>
        {msg && <span className="ok">{msg}</span>}
      </div>
      {err && <div className="err">{err}</div>}
      <div className="hint">Обычные акции WB подтягиваются сами (API календаря акций). Автоакции WB по API не отдаёт: в ЛК → «Товары и цены» → «Календарь акций» →
        акция → «Настроить список товаров» → «Сформировать файл» → «Скачать», затем впишите название и «Добавить акцию». «Расчёт» — галочки только для себя:
        видно, какая доля товаров наберётся для бустинга WB. Маржа — до рекламы, как в «ОнлайнЦене».</div>
      <div className="rnp-wrap">
        <table className="rnp-t promo-t">
          <thead>
            <tr><th rowSpan={2} ref={(e) => { ths.current[0] = e; }} {...stick(0, true)}>Фото</th>
              <th rowSpan={2} ref={(e) => { ths.current[1] = e; }} {...stick(1, true)}>Артикул</th>
              <th rowSpan={2} ref={(e) => { ths.current[2] = e; }} {...stick(2, true)} title="За сколько дней продадутся остатки (с товаром в пути и % выкупа)">Оборачив. с % выкупа, дн</th>
              <th rowSpan={2} ref={(e) => { ths.current[3] = e; }} {...stick(3, true)}>Остаток</th>
              <th rowSpan={2} ref={(e) => { ths.current[4] = e; }} {...stick(4, true)}>Цена до СПП</th>
              <th rowSpan={2} ref={(e) => { ths.current[5] = e; }} {...stick(5, true)}>Маржа актуал., ₽ / %</th>
              {d.promos.map((p) => <th key={p.key} colSpan={5} className="rnp-month" title={p.source === "api" ? "из API WB" : "из файла"}>
                {p.name}{p.from && <div className="hint">{p.from.slice(8, 10)}.{p.from.slice(5, 7)}–{p.to?.slice(8, 10)}.{p.to?.slice(5, 7)}</div>}</th>)}</tr>
            <tr>{d.promos.map((p) => <Fragment key={p.key}>
              <th>Факт<div className="hint">{pc(p.fact_pct)}</div></th><th>Расчёт<div className="hint">{pc(calcPct(p))}</div></th>
              <th>Цена акции</th><th>Маржа с акцией, ₽ / %</th><th>Разница</th></Fragment>)}</tr>
          </thead>
          <tbody>{rows.map((r) => (
            <tr key={r.nm_id}>
              <td className="rnp-photo" {...stick(0)}>{r.photo && <img src={r.photo} alt="" loading="lazy" style={{ height: 40 }} />}</td>
              <td {...stick(1)}><b>{r.vendor_code || r.nm_id}</b><div className="hint">{r.nm_id}</div></td>
              <td {...stick(2)} className={r.turnover == null ? "" : r.turnover > 60 ? "z-bad" : r.turnover > 30 ? "z-mid" : "z-good"}>{r.turnover == null ? "" : r.turnover.toFixed(1).replace(".", ",")}</td>
              <td {...stick(3)}>{r.stock == null ? "" : nf.format(r.stock)}</td><td {...stick(4)}>{r.price == null ? "" : nf.format(r.price) + " ₽"}</td>
              <td {...stick(5)} className={zone(r.margin)}><Mg r={r.margin_rub} p={r.margin} noCost={r.no_cost} /></td>
              {d.promos.map((p) => { const x = r.promos[p.key]; return <Fragment key={p.key}>
                <td className={x ? (x.in_action ? "z-good" : "z-bad") : ""}>{x ? (x.in_action ? "Да" : "Нет") : ""}</td>
                <td>{x && <input type="checkbox" disabled={!d.can_edit} checked={x.calc} onChange={(e) => toggle(p.key, r.nm_id, e.target.checked)} />}</td>
                <td>{x?.price == null ? "" : nf.format(x.price) + " ₽"}</td>
                <td className={zone(x?.margin)}>{x && <Mg r={x.margin_rub} p={x.margin} noCost={r.no_cost} />}</td>
                <td className={x?.diff == null ? "" : x.diff < 0 ? "t-bad" : "t-good"}>{pc(x?.diff)}</td></Fragment>; })}
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}

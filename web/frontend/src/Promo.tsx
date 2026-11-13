import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { http } from "./api";

/** Расчёт акций WB (видео 10X №16): по каждой акции — факт участия, «расчёт» (галочки для себя), цена по акции, маржа с акцией, разница. */
type Cell = { in_action: boolean; calc: boolean; price: number | null; margin: number | null; margin_rub: number | null; diff: number | null };
type Row = { nm_id: number; vendor_code: string | null; title: string | null; photo: string | null; turnover: number | null; stock: number | null;
  price: number | null; margin: number | null; margin_rub: number | null; no_cost: boolean; promos: Record<string, Cell>;
  demand?: { covered_days: number; expected_days: number } };
type P = { key: string; name: string; source: "api" | "file"; from?: string; to?: string; eligible: number; fact_pct: number | null; calc_pct: number | null };
type Collection = { status: "ok" | "never" | "error" | "stale" | "disabled"; last_ok_at?: string; last_run_at?: string;
  catalog_at?: string; interval_minutes: number; future_days: number };
type Data = { rows: Row[]; promos: P[]; can_edit: boolean; auto_promos?: Pick<P, "key" | "name" | "from" | "to">[];
  collection?: Collection; hidden_count?: number; demand_note?: string };
const dateMsk = (value?: string) => value ? new Date(value).toLocaleString("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit",
  month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "ещё нет";
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

export function Promo({ shop, nm = "", only = null }: { shop: number; nm?: string; only?: Set<number> | null }) {
  const [d, setD] = useState<Data | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [onlyIn, setOnlyIn] = useState(false);
  // ArtPicker sends marketplace IDs for articles, categories and own groups.
  // Keep the full calculation for shop-wide boosting percentages and edits.
  const rows = useMemo(() => {
    const ids = nm.trim() ? new Set(nm.split(/[\s,;]+/).filter(x => /^\d+$/.test(x)).map(Number)) : null;
    return (d?.rows || []).filter(r => (!ids || ids.has(r.nm_id)) && (!only || only.has(r.nm_id))
      && (!onlyIn || Object.keys(r.promos).length > 0));
  }, [d, nm, only, onlyIn]);
  const file = useRef<HTMLInputElement>(null);
  const titleInput = useRef<HTMLInputElement>(null);
  const context = useRef(0);
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
  }, [rows, pins]);
  const stick = (i: number, th = false) => (pins.includes(FIXED[i][0])
    ? { style: { position: "sticky" as const, left: lefts[i] || 0, zIndex: th ? 4 : 2 }, "data-pin": "" } : {});
  const load = (stamp = context.current) => http.get<Data>(`/api/shops/${shop}/promo`)
    .then(x => { if (stamp === context.current) setD(x); })
    .catch(e => { if (stamp === context.current) setErr(e.message); });
  useEffect(() => {
    const stamp = ++context.current;
    setD(null); setTitle(""); setErr(""); setMsg(""); setBusy(false); setRefreshing(false); load(stamp);
    return () => { ++context.current; };
  }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const pickFile = () => {
    if (busy || refreshing) return;
    if (!title.trim()) { setErr("Сначала введите название акции в поле слева, затем выберите файл."); titleInput.current?.focus(); return; }
    setErr(""); file.current?.click();
  };
  const upload = async (f: File) => {
    if (busy || refreshing) return;
    const uploadTitle = title.trim(), stamp = context.current;
    if (!uploadTitle) { pickFile(); return; }
    if (!/\.(xlsx|zip)$/i.test(f.name)) { setErr("Выберите файл .xlsx или ZIP-архив с файлом .xlsx."); return; }
    if (!f.size) { setErr("Выбран пустой файл. Скачайте файл акции заново."); return; }
    setErr(""); setMsg(""); setBusy(true);
    try {
      const r = await fetch(`/api/shops/${shop}/promo/upload?name=${encodeURIComponent(f.name)}&title=${encodeURIComponent(uploadTitle)}`,
        { method: "POST", body: f, credentials: "same-origin", headers: { "Content-Type": "application/octet-stream" } });
      const j = await r.json().catch(() => null);
      if (!r.ok) {
        const fallback = r.status === 413 ? "Файл слишком большой для загрузки. Попробуйте отдельный XLSX из архива."
          : r.status === 401 ? "Сессия истекла. Войдите на сайт заново."
          : `Сервер не подтвердил загрузку (HTTP ${r.status}). Обновите таблицу перед повторной отправкой.`;
        throw new Error(typeof j?.detail === "string" ? j.detail : fallback);
      }
      if (j?.ok && typeof j.message === "string") {
        // The frozen demo returns an explicit educational notice, not an import.
        if (stamp === context.current) setMsg(j.message);
        return;
      }
      if (!j?.ok || !Number.isInteger(j.items) || j.items < 1)
        throw new Error("Сервер не подтвердил результат загрузки. Обновите таблицу перед повторной отправкой.");
      if (stamp === context.current) { setMsg(`Акция «${uploadTitle}» добавлена: ${j.items} товаров`); setTitle(""); await load(stamp); }
    } catch (e) {
      if (stamp === context.current) setErr(e instanceof TypeError
        ? "Связь прервалась. Результат загрузки неизвестен — обновите таблицу перед повторной отправкой." : (e as Error).message);
    } finally { if (stamp === context.current) setBusy(false); }
  };
  const toggle = (p: string, nm: number, on: boolean) => {
    setD((x) => x && { ...x, rows: x.rows.map((r) => r.nm_id === nm ? { ...r, promos: { ...r.promos, [p]: { ...r.promos[p], calc: on } } } : r) });
    http.put(`/api/shops/${shop}/promo/calc`, { promo: p, nm_id: nm, on }).catch((e) => setErr(e.message));
  };
  if (!d) return <div className="hint">{err || "Загрузка…"}</div>;
  const calcPct = (p: P) => { const el = d.rows.filter((r) => r.promos[p.key]); return el.length ? el.filter((r) => r.promos[p.key].calc).length / el.length : null; };
  return (
    <div className="promo">
      <div className="rnp-bar">
        <button disabled={busy || refreshing} title="Перечитать сохранённые данные. Сбор из WB выполняется по расписанию."
          onClick={async () => { const stamp = context.current; setRefreshing(true); setErr(""); await load(stamp);
            if (stamp === context.current) setRefreshing(false); }}>{refreshing ? "Обновляю таблицу…" : "Обновить таблицу"}</button>
        {d.can_edit && <>
          <input ref={titleInput} aria-label="Название акции" placeholder="Название автоакции (из календаря акций WB)" disabled={busy} maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} style={{ minWidth: 280 }} />
          <input ref={file} type="file" accept=".xlsx,.zip" disabled={busy || refreshing} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <button disabled={busy || refreshing} onClick={pickFile}>
            {busy ? "Загружаю…" : "➕ Добавить акцию (файл из ЛК)"}</button>
          {!title.trim() && <span className="hint">1. Укажите название акции. 2. Нажмите «Добавить акцию» и выберите XLSX или ZIP.</span>}
          <button disabled={busy || refreshing} onClick={() => { if (confirm("Очистить расчёт: убрать все акции и галочки из таблицы?")) { const stamp = context.current; http.post(`/api/shops/${shop}/promo/clear`).then(() => load(stamp)); } }}>
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
      {d.demand_note && <details className="hint"><summary>Источник спроса и полнота данных</summary>{d.demand_note}</details>}
      {d.collection && <div className={d.collection.status === "error" || d.collection.status === "stale" ? "err" : "hint"} role="status">
        Сбор из WB: {d.collection.status === "disabled" ? "для магазина выключен. " : `по расписанию раз в ${d.collection.interval_minutes / 60} ч. `}
        Последний успешный сбор: {dateMsk(d.collection.last_ok_at)} (МСК).
        {d.collection.last_run_at && <> Последняя завершённая попытка: {dateMsk(d.collection.last_run_at)} (МСК).</>}
        {d.collection.catalog_at && <> Сохранённый список акций: {dateMsk(d.collection.catalog_at)} (МСК).</>}
        {d.collection.status === "error" && <> Последняя попытка завершилась ошибкой. Список или товары акций могут быть неполными; показаны сохранённые данные.</>}
        {d.collection.status === "never" && <> Успешного сбора ещё не было.</>}
        {d.collection.status === "stale" && <> Данные старше интервала сбора; обновление пока не подтверждено.</>}
        {" "}Период запроса: от вчера до {d.collection.future_days} дней вперёд. Более поздних акций здесь может ещё не быть.
      </div>}
      {!!d.hidden_count && <div className="hint">Акций скрыто после «Очистить расчёт»: {d.hidden_count}. Обновление таблицы не возвращает скрытые акции.</div>}
      <div className="hint">Обычные акции WB подтягиваются сами (API календаря акций). Для автоакций API отдаёт названия и сроки, а товары и цены нужно загрузить файлом: в ЛК → «Товары и цены» → «Календарь акций» →
        акция → «Настроить список товаров» → «Сформировать файл» → «Скачать», затем впишите название и «Добавить акцию». «Расчёт» — галочки только для себя:
        видно, какая доля товаров наберётся для бустинга WB. Маржа — до рекламы, как в «ОнлайнЦене».</div>
      <div className="hint">Показано товаров: {rows.length} из {d.rows.length}. Фильтры артикула, категории и менеджера — вверху страницы.
        Доли «Факт» и «Расчёт» считаются по всем подходящим товарам магазина, независимо от фильтра.</div>
      {!!d.auto_promos?.length && <details open className="promo-auto">
        <summary>Автоакции из календаря WB ({d.auto_promos.length}) — товары загружаются файлом</summary>
        <ul>{d.auto_promos.map(p => <li key={p.key}>
          <b>{p.name}</b> · {dateMsk(p.from)} — {dateMsk(p.to)} (МСК){" "}
          {d.can_edit && <button disabled={busy} onClick={() => { setTitle(p.name); setErr(""); setMsg("Название подставлено. Нажмите «Добавить акцию» и выберите её файл из ЛК WB."); titleInput.current?.focus(); }}>Подставить название</button>}
        </li>)}</ul>
      </details>}
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
          <tbody>{!rows.length && <tr><td colSpan={FIXED.length + d.promos.length * 5} className="hint">
            Нет товаров по выбранным фильтрам. Измените выбор вверху страницы или снимите «только товары в акциях».
          </td></tr>}{rows.map((r) => (
            <tr key={r.nm_id}>
              <td className="rnp-photo" {...stick(0)}>{r.photo && <img src={r.photo} alt="" loading="lazy" style={{ height: 40 }} />}</td>
              <td {...stick(1)}><b>{r.vendor_code || r.nm_id}</b><div className="hint">{r.nm_id}</div></td>
              <td {...stick(2)} className={r.turnover == null ? "" : r.turnover > 60 ? "z-bad" : r.turnover > 30 ? "z-mid" : "z-good"}>{r.turnover == null ? "—" : r.turnover.toFixed(1).replace(".", ",")}
                {r.demand && <small className="hint">Воронка: {r.demand.covered_days}/{r.demand.expected_days} дн.</small>}</td>
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

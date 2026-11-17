import { Fragment, useEffect, useMemo, useState } from "react";
import { http, type Col, type TabData } from "./api";

const DEFAULTS = ["pos", "clicks", "carts", "orders"];
const dayLabel = (d: string) => d.split("-").reverse().join(".");
function fmt(v: unknown, type: string) {
  if (v == null) return "—";
  if (typeof v !== "number") return String(v);
  return (type === "share" ? v * 100 : v).toLocaleString("ru-RU", {
    maximumFractionDigits: type === "int" ? 0 : 2,
  }) + (type === "share" ? " %" : type === "money" ? " ₽" : "");
}
export function JamLoading({ text }: { text?: string }) {
  return text ? <div className="jam-loading" role="status"><span className="jam-spinner" aria-hidden="true" />{text}</div> : null;
}
type Daily = { financial_pending?: boolean; coverage?: Record<string, { conflicts: number }>; query: string | null; rows: (Record<string, unknown> & { day: string; state: string })[] };
function QueryDays({ shop, meta, query, metrics }: { shop: number; meta: NonNullable<TabData["jam_deep"]>; query: string; metrics: Col[] }) {
  const [data, setData] = useState<Daily | null>(null), [error, setError] = useState(""), [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true; setError("");
    const q = new URLSearchParams({ nm_id: String(meta.nm_id), query, date_from: meta.from, date_to: meta.to });
    http.get<Daily>(`/api/shops/${shop}/jam/query-days?${q}`).then(x => { if (live) setData(x); })
      .catch(e => { if (live) setError(String(e.message || e)); });
    return () => { live = false; };
  }, [shop, meta.nm_id, meta.from, meta.to, meta.daily_revision, query, retry]);
  const failure = error && <div role="alert">{error} <button onClick={() => setRetry(n => n + 1)}>Повторить</button></div>;
  if (error && !data) return failure;
  if (!data) return <JamLoading text="Открываю сохранённые показатели по дням…" />;
  if (!data.rows.length) return <div className="hint">Запроса нет в сохранённой истории за этот период.</div>;
  return <div>{failure}{data.financial_pending && <p className="hint">Себестоимость пересчитывается. Прибыль временно не показана.</p>}<div className="jam-daily-scroll"><table className="jam-daily-table"><thead><tr><th>Показатель</th>
    {data.rows.map(r => <th key={r.day}>{dayLabel(r.day)}</th>)}</tr></thead><tbody>
    <tr className="hint"><th>Данные WB</th>{data.rows.map(r => <td key={r.day}>{r.state === "missing_day" ? "День не загружен" : r.state === "outside_top" ? "Нет в топе WB" : data.coverage?.[r.day]?.conflicts ? "WB менял значения между замерами — сохранён первый ответ" : "Есть"}</td>)}</tr>
    {metrics.map(m => <tr key={m.field}><th>{m.title.replace("за период", "за день")}</th>{data.rows.map(r => <td key={r.day}>{fmt(r[m.field], m.type)}</td>)}</tr>)}
  </tbody></table></div></div>;
}

export function JamDeep({ shop, data }: { shop: number; data: TabData }) {
  const meta = data.jam_deep!;
  const [opened, setOpened] = useState<string | null>(null), [search, setSearch] = useState(""), [limit, setLimit] = useState(50);
  const [selected, setSelected] = useState<string[]>(() => {
    try { const v = JSON.parse(localStorage.getItem("jam_deep_metrics") || "null");
      if (Array.isArray(v)) { const valid = [...new Set(v.filter(k => typeof k === "string" && meta.metrics.some(m => m.field === k)))]; if (valid.length) return valid; }
    } catch { /* default for invalid preferences */ }
    return DEFAULTS;
  });
  const metrics = selected.flatMap(k => meta.metrics.filter(m => m.field === k));
  const [sort, setSort] = useState({ field: "orders", desc: true });
  const rows = useMemo(() => data.rows.filter(r => String(r.query).toLocaleLowerCase().includes(search.toLocaleLowerCase())).slice().sort((a, b) => {
    const x = a[sort.field], y = b[sort.field];
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    const n = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "ru");
    return sort.desc ? -n : n;
  }), [data.rows, search, sort]);
  const maxima = useMemo(() => Object.fromEntries((data.grad || []).map(k => [k, Math.max(0, ...data.rows.map(r => Number(r[k]) || 0))])), [data]);
  function cellStyle(r: Record<string, unknown>, field: string) {
    const v = r[field]; if (typeof v !== "number" || !v) return undefined;
    const rule = data.rules?.[field]?.find(x => (x.gt == null || v > x.gt) && (x.le == null || v <= x.le));
    if (rule) return { backgroundColor: rule.color, color: "#1f2937" };
    if (v > 0 && maxima[field]) {
      const mix = (n: number) => Math.round(255 - (255 - n) * (.15 + .85 * v / maxima[field]));
      return { backgroundColor: `rgb(${mix(0x57)}, ${mix(0xbb)}, ${mix(0x8a)})`, color: "#1f2937" };
    }
    return undefined;
  }
  function toggle(key: string) {
    const next = selected.includes(key) ? selected.filter(k => k !== key) : [...selected, key];
    if (!next.length) return;
    setSelected(next); try { localStorage.setItem("jam_deep_metrics", JSON.stringify(next)); } catch { /* optional browser storage */ }
  }
  return <section className="jam-deep">
    <div className="row"><b>Артикул {meta.nm_id}</b><span>{meta.summary_source === "daily_preview" ? "Выбранный период" : "Отчёт за"} {dayLabel(meta.period_from || meta.from)}–{dayLabel(meta.period_to || meta.to)}</span>
      <span>Дневная история: {meta.loaded_days} из {meta.expected_days} дней</span></div>
    <p className="hint">{meta.summary_source === "daily_preview" ? "В отчёте за период пока нет доступного списка запросов. Ниже запросы из загруженных дней; числа относятся только к доступным наблюдениям. Готовый отчёт WB отображается после загрузки." : "Сначала обычный отчёт Джема за период."} Нажми на запрос — под ним откроются сохранённые показатели по дням.</p>
    <p className="hint">{meta.expected_days ? `Дни за ${dayLabel(meta.from)}–${dayLabel(meta.to)}.` : "В выбранном периоде нет завершённых дней."} Догруженные данные появляются автоматически, пока вкладка открыта.</p>
    <details><summary>О дневной истории и пропусках</summary><p className="hint">{meta.daily_note} История собирается по всем товарам в работе, начиная со вчерашнего дня. Раскрытие показывает до 90 полных дней. Сегодняшний неполный день в дневную таблицу не входит.</p></details>
    {meta.access && meta.access !== "ok" && <p role="status">WB пока не подтвердил доступ к Джему. Проверь подписку Джем и раздел «Аналитика» у ключа магазина. Сохранённая история доступна.</p>}
    {meta.collection_error && <p role="status">Последний сбор завершился с ошибкой. Сохранённые дни показаны; состояние сбора — во вкладке «Статус обновления».</p>}
    {!!meta.missing_days.length && <details><summary>Не загружены {meta.missing_days.length} дней — показать даты</summary><p className="hint">{meta.missing_days.map(dayLabel).join(", ")}</p></details>}
    <details className="jam-metrics"><summary>Показатели по дням ({metrics.length})</summary><div>
      {meta.metrics.map(m => <label key={m.field}><input type="checkbox" checked={selected.includes(m.field)} onChange={() => toggle(m.field)} /> {m.title.replace("за период", "за день")}</label>)}
    </div></details>
    <label>Найти запрос <input aria-label="Найти запрос" value={search} onChange={e => { setSearch(e.target.value); setLimit(50); }} /></label>

    {!rows.length ? <p>Запросов пока нет. {data.rows.length ? "Измени поиск." : (data.empty || "WB не вернул запросов за этот период.")}</p> : <div className="jam-summary-scroll"><table className="jam-summary"><thead><tr>
      {data.columns.map(c => <th key={c.field} aria-sort={sort.field === c.field ? (sort.desc ? "descending" : "ascending") : "none"}><button className="link jam-sort" onClick={() => setSort({ field: c.field, desc: sort.field === c.field ? !sort.desc : c.type !== "text" })}>{c.title}{sort.field === c.field ? (sort.desc ? " ▾" : " ▴") : ""}</button></th>)}</tr></thead><tbody>{rows.slice(0, limit).map(r => {
        const id = String(r.query); return <Fragment key={id}><tr>
          {data.columns.map(c => <td key={c.field} style={cellStyle(r, c.field)}>{c.field === "query" ? <button className="link jam-query" aria-expanded={opened === id} onClick={() => setOpened(opened === id ? null : id)}>{opened === id ? "▾" : "▸"} {String(r.query)}</button> : c.field === "last_day" ? dayLabel(String(r.last_day)) : fmt(r[c.field], c.type)}</td>)}
        </tr>{opened === id && <tr className="jam-expanded"><td colSpan={data.columns.length}><QueryDays key={`${shop}:${meta.nm_id}:${meta.from}:${meta.to}:${id}`} shop={shop} meta={meta} query={id} metrics={metrics} /></td></tr>}</Fragment>;
      })}</tbody>{data.total_row && <tfoot><tr>{data.columns.map(c => <td key={c.field}>{c.field === "query" ? "ИТОГО по отчёту" : fmt(data.total_row![c.field], c.type)}</td>)}</tr></tfoot>}</table></div>}
    {rows.length > limit && <button onClick={() => setLimit(n => n + 50)}>Показать ещё 50 запросов</button>}
  </section>;
}

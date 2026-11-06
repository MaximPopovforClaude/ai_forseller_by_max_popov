import React, { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Cell = Record<string, number | null> & { src?: never };
type MonthVal = Record<string, number | null> & { src: { qty: string | null; price: string | null; cost: string | null } };
type Row = { nm_id: number; vendor_code: string; title: string; subject: string; photo: string | null; main_query: string | null; query_src: string | null;
  method: string | null; method_used: string | null;
  commission: number; logistics: number; ads_share: number; ads_share_src: string; base_qty: number | null; base_price: number | null;
  months: Record<string, MonthVal> };
type Plan = { base_month: string; months: string[]; metrics: [string, string, string][]; rows: Row[]; total: Record<string, Cell>;
  settings: { horizon: number; fixed_month: number }; tax: { regime: string; rate: number };
  run: { id: number; status: string; progress: Record<string, unknown>; started_at: string; finished_at: string | null } | null;
  can_edit: boolean; wildbox: boolean };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const MON = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const mlabel = (m: string) => `${MON[Number(m.slice(5, 7)) - 1]} ${m.slice(2, 4)}`;
const EDIT = ["qty", "price", "cost"];
const fmt = (v: number | null | undefined, t: string) => (v == null ? "" : t === "share" ? nf1.format(v * 100) + " %" : t === "money" ? nf.format(v) : nf1.format(v));
const MAX_METRICS = 5;
const SHORT: Record<string, string> = { qty: "шт", price: "чек", cost: "с/с ед", revenue: "выручка", commission: "комиссия", logistics: "логистика",
  cogs: "с/с", revenue_company: "выр. комп.", margin: "МД ₽", margin_pct: "МД %", ads: "реклама", fixed: "пост.", tax: "налог",
  profit: "ЧП ₽", profit_pct: "рент. %" };
const summable = (k: string, ty: string) => !(ty === "share" || k === "price" || k === "cost");
const METHOD: Record<string, string> = { auto: "авто", sales: "свои продажи год назад", query: "частотность запроса", manual: "ручные (таблица планирования)", flat: "без сезонности" };
type Cash = { months: string[]; rows: Record<string, number[]>; settings: { start_cash: number; goods_lead: number; loan_rate: number; tax_quarterly: boolean };
  inventory_start: number; vat_rate: number; manual_fields: [string, string][]; can_edit: boolean };
const CF: [string, string, number][] = [   // [ключ, подпись, уровень: 0 — итог, 1 — строка, 2 — ручная]
  ["cash_start", "Денег на начало месяца", 0], ["operating", "Операционная деятельность", 0], ["income", "Поступления от WB (выручка)", 1],
  ["commission", "Комиссия WB", 1], ["logistics", "Логистика", 1], ["ads", "Реклама", 1], ["goods", "Оплата товара (за продажи через N мес.)", 1],
  ["fixed", "Постоянные расходы", 1], ["interest", "Проценты по кредитам", 1], ["tax", "Налоги", 1], ["vat", "НДС", 1],
  ["financing", "Финансовая деятельность", 0], ["loan_in", "Получение кредитов и займов", 2], ["loan_out", "Возврат кредитов и займов", 2],
  ["invest_in", "Привлечение инвестиций", 2], ["invest_out", "Возврат инвестиций", 2], ["dividends", "Дивиденды", 2],
  ["investing", "Инвестиционная и прочая", 0], ["capex", "Покупка ОС", 2], ["other_in", "Прочие поступления", 2], ["other_out", "Прочие выплаты", 2],
  ["total", "Итого оборот денег за месяц", 0], ["cash_end", "Денег на конец месяца", 0]];
const BAL: [string, string, number][] = [
  ["assets", "АКТИВ", 0], ["cash_end", "Деньги", 1], ["inventory", "Товар на складе (в с/с)", 1], ["capex_acc", "Основные средства", 1],
  ["equity", "ПАССИВ: собственный капитал", 0], ["loans", "Кредиты и займы", 1], ["invest", "Инвестиции (привлечённые)", 1],
  ["retained", "Нераспределённая прибыль (с начала плана)", 1], ["profit", "Чистая прибыль месяца (после процентов)", 1]];

function CashView({ shop, kind }: { shop: number; kind: "cash" | "balance" }) {
  const [d, setD] = useState<Cash | null>(null);
  const [err, setErr] = useState("");
  const [edit, setEdit] = useState<string | null>(null);
  const load = () => http.get<Cash>(`/api/shops/${shop}/plan/cash`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [shop]);
  if (err) return <div className="err">{err}</div>;
  if (!d) return <div className="hint">Считаю…</div>;
  const manual = new Set(d.manual_fields.map(([k]) => k));
  const setS = (k: string, v: unknown) => http.put(`/api/shops/${shop}/plan/settings`, { [k]: v }).then(load).catch((e) => setErr(e.message));
  const rows = kind === "cash" ? CF : BAL;
  return (<>
    {kind === "cash" && d.can_edit && <div className="board-bar">
      <label>Денег на начало <input className="w80" defaultValue={d.settings.start_cash} onBlur={(e) => setS("start_cash", Number(e.target.value.replace(/\s/g, "")) || 0)} /> ₽</label>
      <label title="Товар оплачивается за столько месяцев до продажи (в ССП — 2)">Оплата товара за
        <select value={d.settings.goods_lead} onChange={(e) => setS("goods_lead", Number(e.target.value))}>{[0, 1, 2, 3, 4].map((x) => <option key={x} value={x}>{x}</option>)}</select> мес.</label>
      <label>Ставка по кредитам <input className="w60" defaultValue={d.settings.loan_rate * 100} onBlur={(e) => setS("loan_rate", (Number(e.target.value) || 0) / 100)} /> % годовых</label>
      <label><input type="checkbox" checked={d.settings.tax_quarterly} onChange={(e) => setS("tax_quarterly", e.target.checked)} /> налог поквартально</label>
    </div>}
    <div className="board-wrap"><table className="board-t">
      <thead><tr><th className="sx c1">{kind === "cash" ? "Движение денежных средств" : "Баланс на конец месяца"}</th>{d.months.map((m) => <th key={m}>{mlabel(m)}</th>)}</tr></thead>
      <tbody>{rows.map(([k, t, lvl]) => (
        <tr key={k} className={lvl === 0 ? "tot" : ""}>
          <td className="sx c1" style={{ paddingLeft: lvl ? 20 : 8 }}>{lvl === 0 ? <b>{t}</b> : t}</td>
          {d.rows[k].map((v, i) => {
            const key = `${k}|${i}`;
            const ed = kind === "cash" && manual.has(k) && d.can_edit;
            return (
              <td key={i} className={"n" + (v < 0 ? " down" : "") + (ed ? " click s-manual-soft" : "")} onClick={() => ed && setEdit(key)}>
                {edit === key ? <input autoFocus defaultValue={Math.abs(v) || ""} onBlur={(e) => { setEdit(null);
                  http.put(`/api/shops/${shop}/plan/cash`, { month: d.months[i], field: k, value: Number(e.target.value.replace(/\s/g, "")) || null }).then(load).catch((x) => setErr(x.message)); }}
                  onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEdit(null); }} />
                  : v ? nf.format(v) : ""}
              </td>);
          })}
        </tr>))}</tbody>
    </table></div>
    <div className="hint">{kind === "cash"
      ? `Как в ССП: товар оплачивается за ${d.settings.goods_lead} мес. до продажи, налоги ${d.settings.tax_quarterly ? "поквартально" : "помесячно"}, НДС ${nf1.format(d.vat_rate * 100)} %, проценты — по кредитам на начало месяца. Строки кредитов, инвестиций, дивидендов, ОС и прочего — вручную (клик по ячейке).`
      : `Склад на начало плана: текущие остатки × себестоимость = ${nf.format(d.inventory_start)} ₽; дальше + оплаченный товар − себестоимость проданного. Капитал = деньги + товар + ОС − кредиты − инвестиции.`}</div>
  </>);
}

type Scen = { months: string[]; articles: number; scenarios: Record<string, { covered: number; months: Record<string, { qty: number; revenue: number; margin: number; profit: number }> }> };
const SRC_T: Record<string, string> = { auto: "по сезонности (свои продажи год назад или частотность запроса)", flat: "как в базовом месяце (сезонности нет)", manual: "вручную" };

export function Planning({ shop }: { shop: number }) {
  const [p, setP] = useState<Plan | null>(null);
  const [err, setErr] = useState("");
  const [metrics, setMetrics] = useState<string[]>(() => {   // до 5 показателей в ячейке
    try {
      const a = JSON.parse(localStorage.getItem("plan_metrics") || "null");
      if (Array.isArray(a) && a.length) return a.slice(0, MAX_METRICS);
      return [localStorage.getItem("plan_metric") || "qty"];
    } catch { return ["qty"]; }
  });
  const [view, setView] = useState<"items" | "company" | "compare" | "cash" | "balance">("items");
  const [scen, setScen] = useState<Scen | null>(null);
  useEffect(() => { if (view === "compare") { setScen(null); http.get<Scen>(`/api/shops/${shop}/plan/scenarios`).then(setScen).catch((e) => setErr(e.message)); } }, [view, shop, p]);
  const [edit, setEdit] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [fixed, setFixed] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const load = () => http.get<Plan>(`/api/shops/${shop}/plan`).then((x) => { setP(x); setFixed(String(x.settings.fixed_month || 0)); setErr(""); })
    .catch((e) => setErr(e.message));
  useEffect(() => { setP(null); load(); }, [shop]);
  useEffect(() => { try { localStorage.setItem("plan_metrics", JSON.stringify(metrics)); } catch { /* нет хранилища */ } }, [metrics]);
  useEffect(() => {   // пока идёт авто-построение — обновляем раз в 5 с
    window.clearTimeout(timer.current);
    if (p?.run?.status === "running") timer.current = window.setTimeout(load, 5000);
    return () => window.clearTimeout(timer.current);
  }, [p]);
  if (err && !p) return <div className="err">{err}</div>;
  if (!p) return <div className="hint">Загрузка…</div>;
  const sel = p.metrics.filter(([k]) => metrics.includes(k));
  const shown = sel.length ? sel : [p.metrics[0]];
  const multi = shown.length > 1;
  const toggle = (k: string) => setMetrics((cur) => cur.includes(k) ? (cur.length > 1 ? cur.filter((x) => x !== k) : cur)
    : cur.length < MAX_METRICS ? [...cur, k] : cur);
  const save = (nm: number, month: string, metric: string, raw: string) => {
    setEdit(null);
    const v = raw.trim() === "" ? null : Number(raw.replace(",", ".").replace(/\s/g, ""));
    if (v !== null && !Number.isFinite(v)) return;
    http.put(`/api/shops/${shop}/plan/cell`, { nm_id: nm, month, field: metric, value: v }).then(load).catch((e) => setErr(e.message));
  };
  const saveItem = (nm: number, main_query: string) =>
    http.put(`/api/shops/${shop}/plan/item`, { nm_id: nm, main_query }).then(load).catch((e) => setErr(e.message));
  const run = p.run;
  const prog = run?.progress as { step?: string; done?: number; total?: number; note?: string; error?: string; cells_seasonal?: number; cells_flat?: number } | undefined;
  const rows = p.rows.filter((r) => !q.trim() || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.main_query}`.toLowerCase().includes(q.trim().toLowerCase()));
  const sum = (m: string, k: string, ty: string) => {
    if (!summable(k, ty)) return p.total[m]?.[k] ?? null;
    return rows.reduce((a, r) => a + Number(r.months[m]?.[k] ?? 0), 0);
  };
  const lines = (f: (k: string, t: string, ty: string) => React.ReactNode) =>
    multi ? shown.map(([k, t, ty]) => <div key={k} className="pm">{f(k, t, ty)}</div>) : f(...shown[0]);
  return (
    <div className="board plan">
      <div className="board-bar">
        <select value={view} onChange={(e) => setView(e.target.value as "items" | "company" | "compare" | "cash" | "balance")}>
          <option value="items">По артикулам</option><option value="company">Итог по компании (ССП)</option><option value="compare">Сравнение схем</option>
          <option value="cash">Движение денег (ДДС)</option><option value="balance">Баланс</option>
        </select>
        {p.can_edit && <select value="" title="Переключить схему у всех артикулов. Ручные коэффициенты и ручные ячейки не теряются"
          onChange={(e) => e.target.value && http.put(`/api/shops/${shop}/plan/method_all`, { method: e.target.value }).then(load).catch((x) => setErr(x.message))}>
          <option value="">Схема для всех…</option>
          {Object.entries(METHOD).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
        </select>}
        {view === "items" && <details className="pm-pick">
          <summary title={`В ячейке — до ${MAX_METRICS} показателей`}>Показатели: {shown.map(([k]) => SHORT[k] || k).join(", ")}</summary>
          <div className="pm-list">
            {p.metrics.map(([k, t]) => (
              <label key={k} className={!metrics.includes(k) && metrics.length >= MAX_METRICS ? "off" : ""}>
                <input type="checkbox" checked={metrics.includes(k)} disabled={!metrics.includes(k) && metrics.length >= MAX_METRICS}
                  onChange={() => toggle(k)} /> {t}{EDIT.includes(k) ? " ✎" : ""}</label>))}
            <div className="hint">До {MAX_METRICS} сразу; порядок строк в ячейке — как в списке.</div>
          </div>
        </details>}
        {view === "items" && <input className="q" placeholder="Поиск: артикул, запрос" value={q} onChange={(e) => setQ(e.target.value)} />}
        {p.can_edit && <>
          <select value={p.settings.horizon} onChange={(e) => http.put(`/api/shops/${shop}/plan/settings`, { horizon: Number(e.target.value), fixed_month: Number(fixed) || 0 }).then(load)}>
            <option value={6}>6 месяцев</option><option value={12}>12 месяцев</option>
          </select>
          <label title="ФОТ, аренда и прочие постоянные расходы в месяц — делятся на артикулы пропорционально штукам">Постоянные в мес
            <input className="w80" value={fixed} onChange={(e) => setFixed(e.target.value)}
              onBlur={() => http.put(`/api/shops/${shop}/plan/settings`, { horizon: p.settings.horizon, fixed_month: Number(fixed.replace(/\s/g, "")) || 0 }).then(load)} /> ₽</label>
          <button disabled={run?.status === "running"} onClick={() => http.post(`/api/shops/${shop}/plan/auto`).then(load).catch((e) => setErr(e.message))}>
            {run?.status === "running" ? "Строю…" : "⚙ Построить автоматически"}</button>
        </>}
      </div>
      <div className="hint">
        База — {mlabel(p.base_month)} (последний завершённый месяц): продажи = выкупы, цена = средний чек до СПП. СНО: {p.tax.regime}{p.tax.rate ? `, ${nf1.format(p.tax.rate * 100)} %` : ""}.
        {" "}Сезонность месяц к месяцу: по своим продажам артикула год назад (если история есть), иначе по частотности главного запроса{p.wildbox ? " (Wildbox)" : " — Wildbox не подключён, ключ в «Настройках аккаунта»"}; цена — по среднему чеку выдачи запроса.
        {run && <> · Авто-построение: {run.status === "running" ? `${prog?.step || ""} ${prog?.done ?? ""}${prog?.total ? "/" + prog.total : ""}` : run.status === "done"
          ? `готово ${new Date(run.finished_at || run.started_at).toLocaleString("ru-RU")}${prog?.cells_seasonal != null ? ` (по сезонности ${prog.cells_seasonal}, плоско ${prog.cells_flat})` : ""}`
          : `ошибка: ${prog?.error || ""}`}{prog?.note ? ` · ${prog.note}` : ""}</>}
      </div>
      {err && <div className="err">{err}</div>}
      {view === "cash" || view === "balance" ? <CashView shop={shop} kind={view} /> : view === "compare" ? (
        !scen ? <div className="hint">Считаю схемы…</div> : (
          <div className="board-wrap"><table className="board-t">
            <thead><tr><th className="sx c1">Схема</th><th>Показатель</th>{scen.months.map((m) => <th key={m}>{mlabel(m)}</th>)}<th>Итого</th></tr></thead>
            <tbody>{Object.entries(scen.scenarios).flatMap(([k, s]) => ([["qty", "Штуки", "int"], ["revenue", "Выручка ВБ, ₽", "money"], ["margin", "Маржинальный доход, ₽", "money"], ["profit", "Чистая прибыль, ₽", "money"]] as const).map(([f, t, ty], i) => {
              const vals = scen.months.map((m) => s.months[m][f]);
              return (
                <tr key={k + f} className={i === 0 ? "sc-first" : ""}>
                  <td className="sx c1">{i === 0 ? <><b>{METHOD[k]}</b><div className="hint">сезонность есть у {s.covered} из {scen.articles} арт.</div></> : ""}</td>
                  <td>{t}</td>{vals.map((v, j) => <td key={j} className={"n" + (f === "profit" && v < 0 ? " down" : "")}>{fmt(v, ty)}</td>)}
                  <td className="n"><b>{fmt(vals.reduce((a, v) => a + v, 0), ty)}</b></td>
                </tr>);
            }))}</tbody>
          </table>
          <div className="hint">Каждая схема — на всех артикулах плана, без ручных правок ячеек. «Авто»: свои продажи год назад, если есть, иначе частотность запроса.
            «Ручные» — коэффициенты и цели из таблицы планирования (формула «прошлый месяц × k» применяется к нашему факту, число — как цель).</div></div>)
      ) : view === "company" ? (
        <div className="board-wrap"><table className="board-t">
          <thead><tr><th className="sx c1">Показатель</th>{p.months.map((m) => <th key={m}>{mlabel(m)}</th>)}<th>Итого</th></tr></thead>
          <tbody>{p.metrics.filter(([k]) => k !== "cost").map(([k, t, ty]) => {
            const vals = p.months.map((m) => p.total[m]?.[k] ?? null);
            const tot = ty === "share" || k === "price" ? null : vals.reduce((a: number, v) => a + Number(v ?? 0), 0);
            return <tr key={k}><td className="sx c1">{t}</td>{vals.map((v, i) => <td key={i} className={"n" + (k === "profit" && Number(v) < 0 ? " down" : "")}>{fmt(v, ty)}</td>)}
              <td className="n"><b>{fmt(tot, ty)}</b></td></tr>;
          })}</tbody>
        </table></div>
      ) : (
        <div className="board-wrap"><table className="board-t">
          <thead><tr>
            <th className="sx c0"></th><th className="sx c1">Артикул</th>
            <th title="Откуда коэффициенты месяц к месяцу. «Авто»: свои продажи артикула год назад, если их хватает, иначе частотность запроса">Сезонность</th>
            <th title="Главный поисковый запрос — по нему сезонность. Клик — поменять">Главный запрос</th>
            <th title="Факт базового месяца">База: шт</th><th title="Факт базового месяца">База: цена</th>
            {multi && <th>Показатель</th>}
            {p.months.map((m) => <th key={m}>{mlabel(m)}</th>)}<th>Итого</th>
          </tr></thead>
          <tbody>
            <tr className="tot"><td className="sx c0"></td><td className="sx c1"><b>ИТОГО</b></td><td></td><td></td>
              <td className="n">{metrics.includes("qty") ? nf.format(rows.reduce((a, r) => a + (r.base_qty || 0), 0)) : ""}</td><td></td>
              {multi && <td className="pm-l">{lines((k) => SHORT[k] || k)}</td>}
              {p.months.map((m) => <td key={m} className="n"><b>{lines((k, _t, ty) => fmt(sum(m, k, ty), ty))}</b></td>)}
              <td className="n"><b>{lines((k, _t, ty) => summable(k, ty) ? fmt(p.months.reduce((a, m) => a + Number(sum(m, k, ty) ?? 0), 0), ty) : "")}</b></td></tr>
            {rows.map((r) => (
              <tr key={r.nm_id}>
                <td className="sx c0">{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
                <td className="sx c1" title={r.title}><b>{r.vendor_code}</b><div className="hint">{r.nm_id} · {r.subject}</div></td>
                <td className="mcell">
                  {p.can_edit ? (
                    <select value={r.method || "auto"} onChange={(e) => http.put(`/api/shops/${shop}/plan/item`, { nm_id: r.nm_id, method: e.target.value }).then(load).catch((x) => setErr(x.message))}>
                      {Object.entries(METHOD).map(([k, t]) => <option key={k} value={k}>{k === "auto" && r.method_used ? `авто (${METHOD[r.method_used] || r.method_used})` : t}</option>)}
                    </select>) : METHOD[r.method || r.method_used || "auto"]}
                </td>
                <td className={"qcell" + (r.query_src === "manual" ? " manual" : "")} onClick={() => p.can_edit && setEdit(`q${r.nm_id}`)}>
                  {edit === `q${r.nm_id}` ? <input autoFocus defaultValue={r.main_query || ""} onBlur={(e) => { setEdit(null); saveItem(r.nm_id, e.target.value); }}
                    onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEdit(null); }} />
                    : r.main_query ? <>{r.main_query}{r.query_src === "subject" && <span className="hint" title="Wildbox не отдал запросы артикула — временно взят предмет, при следующем построении определим заново"> (предмет)</span>}</> : <span className="hint">не задан</span>}</td>
                <td className="n">{r.base_qty == null ? "" : nf.format(r.base_qty)}</td><td className="n">{r.base_price == null ? "" : nf.format(r.base_price)}</td>
                {multi && <td className="pm-l">{lines((k) => SHORT[k] || k)}</td>}
                {p.months.map((m) => {
                  const v = r.months[m];
                  const one = (k: string, ty: string) => {
                    const src = EDIT.includes(k) ? v?.src?.[k as "qty" | "price" | "cost"] : null;
                    const ed = p.can_edit && EDIT.includes(k);
                    const key = `${r.nm_id}|${m}|${k}`;
                    return {
                      cls: (src ? " s-" + src : "") + (ed ? " click" : "") + ((k === "profit" || k === "margin") && Number(v?.[k]) < 0 ? " down" : ""),
                      title: src ? SRC_T[src] + (ed ? ". Клик — изменить, пусто — вернуть авто" : "") : undefined,
                      onClick: () => ed && setEdit(key),
                      body: edit === key ? <input autoFocus defaultValue={v?.[k] ?? ""} onBlur={(e) => save(r.nm_id, m, k, e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); if (e.key === "Escape") setEdit(null); }} />
                        : fmt(v?.[k], ty),
                    };
                  };
                  if (!multi) {
                    const o = one(shown[0][0], shown[0][2]);
                    return <td key={m} className={"n" + o.cls} title={o.title} onClick={o.onClick}>{o.body}</td>;
                  }
                  return (
                    <td key={m} className="n pm-c">{shown.map(([k, , ty]) => {
                      const o = one(k, ty);
                      return <div key={k} className={"pm" + o.cls} title={o.title} onClick={o.onClick}>{o.body}</div>;
                    })}</td>
                  );
                })}
                <td className="n">{lines((k, _t, ty) => summable(k, ty) ? fmt(p.months.reduce((a, m) => a + Number(r.months[m]?.[k] ?? 0), 0), ty) : "")}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      <div className="hint">✎ — штуки, цена и себестоимость правятся в ячейке. Цвет: <span className="s-auto lg">сезонность</span> <span className="s-flat lg">как в базе</span> <span className="s-manual lg">вручную</span>.
        Комиссия % и логистика — наши данные по артикулу, реклама — доля от выручки по факту базового месяца.</div>
    </div>
  );
}

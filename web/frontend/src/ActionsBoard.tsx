import { useEffect, useMemo, useRef, useState } from "react";
import { http } from "./api";
import { ActionSparks, type ActionChartData } from "./ActionSparks";
import { ActionDayContent, DRR, AD_GROUPS, AD_NOTE, AD_ORDER_NOTE, AD_CLASS_NOTE, PRICE_NOTE, visibleAct, chip, nf1, pct, num,
  type Kind, type Act, type AdMetric } from "./ActionDayCell";

type Row = {
  nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; photo: string | null;
  stock_wb: number | null; stock_fbs: number | null; stock: number | null; price: number | null; price_spp: number | null;
  margin_pct: number | null; rating: number | null; orders_avg: number | null; stock_days: number | null; spp: number | null; plan: number | null;
  orders_source?: string; demand?: { covered_days: number; expected_days: number };
  drr_orders: number | null; drr_buyouts: number | null; conv_cart: number | null; conv_order: number | null;
  orders: Record<string, number>; actions: Record<string, Act[]>;
  price_spp_days?: Record<string, number | null>;
  ad_metrics?: Record<string, Record<string, AdMetric>>;
  ads?: Record<string, { all: number; ark: number; prk: number; search: number; rec: number; osum: number | null }>;
  shop_id?: number; shop_title?: string; can_edit?: boolean; mp?: string;
};
type Target = { shop: number; nm: number };
const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const keyOf = (r: { shop_id?: number; nm_id: number }) => `${r.shop_id}:${r.nm_id}`;
type Board = { days: string[]; kinds: Kind[]; rows: Row[]; month: string; me: number; can_edit: boolean; mp?: string; demand_note?: string; ad_metrics_note?: string; stale?: boolean };

const dd = (s: string) => s.slice(8, 10) + "." + s.slice(5, 7);
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

function Editor({ targets, kinds, label, day0, existing, me, onClose, onSaved }: {
  targets: Target[]; kinds: Kind[]; label: string; day0: string; existing: Act[]; me: number;
  onClose: () => void; onSaved: () => void;
}) {
  const shop = targets[0].shop;
  const [day, setDay] = useState(day0);
  const [have, setHave] = useState<Act[]>(existing);
  const [sel, setSel] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const toggle = (k: string) => setSel((s) => { const n = { ...s }; if (k in n) delete n[k]; else n[k] = ""; return n; });
  const items = [...Object.entries(sel).map(([kind, value]) => ({ kind, value: value || null, note: note || null })),
    ...(custom.trim() ? [{ kind: "custom:" + custom.trim(), value: null, note: note || null }] : [])];
  const save = async () => {
    if (!items.length) { setErr("Выберите хотя бы одно действие"); return; }
    setBusy(true);
    try {
      const by: Record<number, number[]> = {};
      for (const t of targets) (by[t.shop] ||= []).push(t.nm);
      for (const [sh, nms] of Object.entries(by)) await http.post(`/api/shops/${sh}/actions`, { nm_ids: nms, day, items });
      onSaved(); onClose();
    }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="modal-shade" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => { if (e.key === "Escape") onClose(); if (e.key === "Enter" && e.ctrlKey) save(); }}>
        <div className="modal-h"><b>Действия</b> · {label}<button className="x" onClick={onClose}>✕</button></div>
        <label className="row">Дата <input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
        {have.length > 0 && (
          <div className="ex">
            {have.map((a) => (
              <div key={a.id} className="ex-row">
                {chip(a, Object.fromEntries(kinds.map((k) => [k.key, k])), day0)}
                {a.note && <span className="hint">{a.note}</span>}
                {!a.auto && a.who && <span className="hint">· {a.who}</span>}
                {!a.auto && a.user_id === me && (
                  <button className="link" title="Убрать запись" onClick={() => http.del(`/api/shops/${shop}/actions/${a.id}`).then(() => { setHave((h) => h.filter((x) => x.id !== a.id)); onSaved(); })
                    .catch((e) => setErr(e.message))}>убрать</button>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="kinds">
          {kinds.map((k) => (
            <button key={k.key} className={"kind" + (k.key in sel ? " on" : "")} style={{ borderColor: k.color, ...(k.key in sel ? { background: k.color, color: "#fff" } : { color: k.color }) }}
              onClick={() => toggle(k.key)}>{k.title}</button>
          ))}
        </div>
        {Object.keys(sel).length > 0 && (
          <div className="vals">
            {Object.keys(sel).map((k) => {
              const kk = kinds.find((x) => x.key === k)!;
              return (
                <label key={k} className="row"><span style={{ color: kk.color }}>{kk.title}</span>
                  <input placeholder={kk.unit ? `сколько, ${kk.unit} (необязательно)` : "уточнение (необязательно)"} value={sel[k]}
                    onChange={(e) => setSel((s) => ({ ...s, [k]: e.target.value }))} />
                </label>
              );
            })}
          </div>
        )}
        <label className="row">Своё <input placeholder="другое действие текстом" value={custom} onChange={(e) => setCustom(e.target.value)} /></label>
        <label className="row">Комментарий <input placeholder="необязательно" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        {err && <div className="err">{err}</div>}
        <div className="modal-f">
          <span className="hint">{targets.length > 1 ? `Запишем для ${targets.length} артикулов` : ""}</span>
          <button disabled={busy} onClick={save}>Записать{items.length > 1 ? ` (${items.length})` : ""}</button>
        </div>
      </div>
    </div>
  );
}

export function ActionsBoard({ shop, shops, enableCharts = true, nm = "", only = null }: {
  shop: number; shops: { id: number; title: string }[]; enableCharts?: boolean; nm?: string; only?: Set<number> | null;
}) {
  const [scope, setScope] = useState<"one" | "all">(() => (lsGet("act_scope") === "all" ? "all" : "one"));
  const [days, setDays] = useState<number>(() => Number(lsGet("act_days") || 14) || 14);
  const [b, setB] = useState<Board | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [onlyActs, setOnlyActs] = useState(false);
  const [chartsOn, setShowCharts] = useState(() => lsGet("act_charts") === "1");
  const showCharts = enableCharts && chartsOn;
  const [charts, setCharts] = useState<Record<number, ActionChartData>>({});
  const [chartsReload, setChartsReload] = useState(0);
  const request = useRef(0);
  const context = useRef("");
  const loadedContext = useRef("");
  const metricsAttempted = useRef("");
  const [page, setPage] = useState(0);
  const [showKey, setShowKey] = useState(() => lsGet("act_key") !== "0");
  const [drr, setDrr] = useState<string[]>(() => (lsGet("act_drr") || "").split(",").filter(Boolean));
  const [deepAds, setDeepAds] = useState(() => lsGet("act_deep_ads") === "1");
  const [dayPrices, setDayPrices] = useState(() => lsGet("act_day_prices") === "1");
  const [adStats, setAdStats] = useState(() => lsGet("act_ad_stats") === "1");
  const [adGroups, setAdGroups] = useState(() => (lsGet("act_ad_groups") ?? "all").split(",").filter(k => AD_GROUPS.some(([v]) => v === k)));
  const [adBasis, setAdBasis] = useState<"limit" | "balance">(() => lsGet("act_ad_basis") === "balance" ? "balance" : "limit");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<{ t: Target[]; label: string; day: string; existing: Act[] } | null>(null);
  const [planEdit, setPlanEdit] = useState<string | null>(null);
  const many = scope === "all" && shops.length > 1;
  const shopKey = (many ? shops.map(s => s.id) : [shop]).join(",");
  context.current = `${shopKey}:${days}`;
  const load = (withMetrics = adStats) => {
    const generation = ++request.current, key = context.current;
    if (withMetrics) metricsAttempted.current = key;
    const list = many ? shops : [{ id: shop, title: "" }];
    Promise.all(list.map((s) => http.get<Board>(`/api/shops/${s.id}/manager/board?days=${days}&prepared=true&ads=true&prices=true${withMetrics ? "&ad_metrics=true" : ""}`)
      .then((x) => ({ ...x, rows: x.rows.map((r) => ({ ...r, shop_id: s.id, shop_title: s.title, can_edit: x.can_edit, mp: x.mp || "wb" })) }))))
      .then((bs) => { if (generation !== request.current || key !== context.current) return; loadedContext.current = key; if (!withMetrics) metricsAttempted.current = ""; setB({ ...bs[0], can_edit: bs.some((x) => x.can_edit), rows: bs.flatMap((x) => x.rows) }); setErr(""); })
      .catch((e) => { if (generation === request.current && key === context.current) setErr(e.message); });
  };
  useEffect(() => { loadedContext.current = ""; metricsAttempted.current = ""; setB(null); setErr(""); setPicked(new Set()); setEdit(null); load(); return () => { request.current++; }; }, [shopKey, days]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (adStats && b && loadedContext.current === context.current && metricsAttempted.current !== context.current) load(true);
  }, [adStats, b, shopKey, days]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try {
    localStorage.setItem("act_ad_stats", adStats ? "1" : "0"); localStorage.setItem("act_ad_groups", adGroups.join(",")); localStorage.setItem("act_ad_basis", adBasis);
  } catch { /* нет хранилища */ } }, [adStats, adGroups, adBasis]);
  useEffect(() => { try { localStorage.setItem("act_days", String(days)); localStorage.setItem("act_key", showKey ? "1" : "0");
    localStorage.setItem("act_scope", scope); localStorage.setItem("act_drr", drr.join(",")); } catch { /* нет хранилища */ } }, [days, showKey, scope, drr]);
  useEffect(() => { try {
    localStorage.setItem("act_deep_ads", deepAds ? "1" : "0"); localStorage.setItem("act_day_prices", dayPrices ? "1" : "0");
  } catch { /* нет хранилища */ } }, [deepAds, dayPrices]);
  useEffect(() => {
    let live = true;
    setCharts({});
    if (enableCharts) for (const id of shopKey.split(",").map(Number)) {
      http.get<ActionChartData>(`/api/shops/${id}/manager/charts?prepared=true`).then(data => {
        if (live) setCharts(old => ({ ...old, [id]: data }));
      }).catch(e => { if (live) setCharts(old => ({ ...old, [id]: { days: [], rows: {}, price_label: "", note: "", error: e.message } })); });
    }
    return () => { live = false; };
  }, [shopKey, enableCharts, chartsReload]);
  const kinds = useMemo(() => Object.fromEntries((b?.kinds || []).map((k) => [k.key, k])), [b]);
  const selected = useMemo(() => nm.trim() ? new Set(nm.split(/[,;\s]+/).map(Number).filter(n => Number.isSafeInteger(n) && n > 0)) : null, [nm]);
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (b?.rows || []).filter((r) => (!(selected || only) || (r.shop_id === shop && (!selected || selected.has(r.nm_id)) && (!only || only.has(r.nm_id))))
      && (!ql || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.subject}`.toLowerCase().includes(ql))
      && (!onlyActs || b!.days.some(d => (r.actions[d] || []).some(a => visibleAct(a, deepAds)))));
  }, [b, q, onlyActs, deepAds, selected, only, shop]);
  useEffect(() => { setPage(0); }, [q, onlyActs, deepAds, selected, only, shopKey, days, adStats]);
  useEffect(() => { setPicked(new Set()); setEdit(null); }, [selected, only, shop]);
  if (!b || loadedContext.current !== context.current) return err ? <div className="err">{err} <button onClick={() => load()}>Повторить загрузку</button></div> : <div className="hint">Загрузка…</div>;
  const pageSize = adStats ? 20 : 50, maxPage = Math.max(0, Math.ceil(rows.length / pageSize)-1);
  const currentPage = Math.min(page, maxPage), pageRows = rows.slice(currentPage*pageSize, (currentPage+1)*pageSize);
  const oz = b.mp === "ozon";
  const editableRows = rows.filter(r => r.can_edit);
  const all = editableRows.length > 0 && editableRows.every((r) => picked.has(keyOf(r)));
  const flip = (k: string) => setPicked((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const savePlan = (r: Row, v: string) => {
    setPlanEdit(null);
    const qty = v.trim() === "" ? null : Number(v.replace(",", "."));
    if (qty !== null && !Number.isFinite(qty)) return;
    http.put(`/api/shops/${r.shop_id}/nm_plan`, { nm_id: r.nm_id, month: b.month, qty }).then(() => load()).catch((e) => setErr(e.message));
  };
  const pickedT: Target[] = editableRows.filter(r => picked.has(keyOf(r))).map(r => ({ shop: r.shop_id!, nm: r.nm_id }));
  const month = new Date(b.month).toLocaleString("ru-RU", { month: "long" });
  return (
    <div className="board">
      {err && <div className="err">{err} <button onClick={() => load()}>Повторить загрузку</button></div>}
      {b.stale && <div className="hint">Показан готовый расчёт; новые данные обновляются в фоне.</div>}
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 14, 21, 30, 45, 60].map((d) => <option key={d} value={d}>{d} дней</option>)}
        </select>
        <label><input type="checkbox" checked={onlyActs} onChange={(e) => setOnlyActs(e.target.checked)} /> только с действиями</label>
        <label><input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} /> ключевые данные</label>
        <button aria-pressed={deepAds} onClick={() => setDeepAds(x => !x)}
          title="Ставки и состав ключей, минус-фразы, товары и настройки РК, бюджет, лимиты и команды платформы. Обычные статусы и ставки кампаний видны всегда.">
          {deepAds ? "Скрыть" : "Показать"} глубокие изменения РК</button>
        {enableCharts && <label><input type="checkbox" checked={showCharts} onChange={e => { setShowCharts(e.target.checked); try { localStorage.setItem("act_charts", e.target.checked ? "1" : "0"); } catch { /* no storage */ } }} /> графики за 30 дней</label>}
        {showCharts && Object.values(charts).some(c => c.error) && <button onClick={() => setChartsReload(x => x+1)}>Повторить загрузку графиков</button>}
        {!oz && <span className="hint" title="ДРР дня = расход на рекламу ÷ сумма заказов артикула за день. АРК — единая ставка, ПРК — ручная (аукцион); поиск — траты по поисковым кластерам, рекомендации — остальное (полки, каталог)">ДРР в ячейках:</span>}
        {!oz && DRR.map(([k, t]) => <label key={k}><input type="checkbox" checked={drr.includes(k)}
          onChange={(e) => setDrr((xs) => e.target.checked ? DRR.map((x) => x[0]).filter((x) => x === k || xs.includes(x)) : xs.filter((x) => x !== k))} /> {t}</label>)}
        {(!oz || b.rows.some(r => r.mp === "wb")) && <label title={PRICE_NOTE}><input type="checkbox" checked={dayPrices}
          onChange={e => setDayPrices(e.target.checked)} /> цена с СПП по дням</label>}
        {b.rows.some(r => r.mp === "wb") && <button aria-pressed={adStats} onClick={() => setAdStats(x => !x)}>
          {adStats ? "Скрыть" : "Показать"} статистику РК</button>}
        {shops.length > 1 && (
          <select value={scope} onChange={(e) => setScope(e.target.value as "one" | "all")} title="Как в планфакте: несколько юрлиц на одной доске">
            <option value="one">Выбранный магазин</option><option value="all">Все магазины кабинета ({shops.length})</option>
          </select>
        )}
        {b.can_edit && pickedT.length > 0 && (
          <button onClick={() => setEdit({ t: pickedT, label: `выбрано артикулов: ${pickedT.length}`, day: b.days[0], existing: [] })}>
            + Действие для выбранных ({pickedT.length})
          </button>
        )}
        {picked.size > 0 && <button className="link" onClick={() => setPicked(new Set())}>снять выбор</button>}
        <span className="hint">Клик по дню — записать действия. ⚙ — изменения, которые мы заметили сами в API {oz ? "Ozon" : "WB"}.</span>
      </div>
      {adStats && b.rows.some(r => r.mp === "wb") && <div className="board-bar action-ad-controls">
        {!err && b.rows.some(r => r.mp === "wb" && !r.ad_metrics) && <span className="hint">Загрузка подготовленной статистики РК…</span>}
        <span>Реклама WB:</span>{AD_GROUPS.map(([key, title]) => <label key={key}><input type="checkbox" checked={adGroups.includes(key)}
          onChange={e => setAdGroups(xs => e.target.checked ? [...xs, key] : xs.filter(k => k !== key))} />{title}</label>)}
        <label>Использование бюджета <select value={adBasis} onChange={e => setAdBasis(e.target.value as "limit" | "balance")}>
          <option value="limit">Расход / дневной лимит</option><option value="balance">Расход / (расход + остаток)</option>
        </select></label>
        <span className="hint">{AD_CLASS_NOTE}</span>
        <details className="hint"><summary>Порядок значений и расчёт рекламы</summary><p>{AD_ORDER_NOTE}</p>{AD_NOTE}</details>
        {b.ad_metrics_note && <span className="hint">{b.ad_metrics_note}</span>}
      </div>}
      {b.demand_note && <details className="hint"><summary>Источник заказов и полнота данных</summary>{b.demand_note}</details>}
      {showCharts && <div className="hint">{[...new Set(Object.values(charts).map(c => c.note).filter(Boolean))].join(" ")}</div>}
      {many && (selected || only) && <div className="hint">Выбор артикулов и менеджера сверху относится к выбранному магазину.</div>}
      {rows.length > pageSize && <div className="board-bar" aria-label="Страницы действий">
        <span>Артикулы {currentPage*pageSize+1}–{Math.min((currentPage+1)*pageSize, rows.length)} из {rows.length}</span>
        <button disabled={currentPage === 0} onClick={() => setPage(currentPage-1)}>Предыдущие</button>
        <button disabled={currentPage === maxPage} onClick={() => setPage(currentPage+1)}>Следующие</button>
      </div>}
      <div className="board-wrap">
        <table className="board-t">
          <thead>
            <tr>
              <th className="sx c0">{b.can_edit && <input type="checkbox" checked={all} onChange={() => setPicked(all ? new Set() : new Set(rows.filter((r) => r.can_edit).map(keyOf)))} />}</th>
              <th className="sx c1">Артикул</th>
              {showKey && <th>Ключевые данные</th>}
              {showCharts && <th>Графики · 30 дней</th>}
              {b.days.map((d) => { const wd = new Date(d).getDay(); return <th key={d} className={"day" + (wd === 0 || wd === 6 ? " we" : "")}>{dd(d)}<br /><span className="hint">{WD[wd]}</span></th>; })}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => (
              <tr key={keyOf(r)} className={picked.has(keyOf(r)) ? "picked" : ""}>
                <td className="sx c0">{r.can_edit && <input type="checkbox" checked={picked.has(keyOf(r))} onChange={() => flip(keyOf(r))} />}
                  {r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
                <td className="sx c1" title={r.title || ""}><b>{r.vendor_code}</b><div className="hint">{many ? r.shop_title + " · " : ""}{r.nm_id} · {(r.title || "").slice(0, 34)}</div></td>
                {showKey && <td><div className="action-key-grid">
                  {[
                    [oz ? "Ост. FBO" : "Ост. WB", num(r.stock_wb)], ["Ост. ФБС", num(r.stock_fbs)], ["Ост. всего", num(r.stock)],
                    [oz ? "Цена продавца" : "Цена без СПП", num(r.price)], [oz ? "Цена с акциями" : "Цена с СПП", num(r.price_spp)],
                    ["Маржа %", pct(r.margin_pct)], ["Рейтинг", r.rating == null ? "" : nf1.format(r.rating)], [r.demand ? `Ср. зак. (${r.demand.covered_days}/${r.demand.expected_days} дн.)` : "Ср. заказы", r.orders_avg == null ? "—" : nf1.format(r.orders_avg)],
                    ["Ост. в днях", num(r.stock_days)], [oz ? "Скидка Ozon %" : "СПП %", pct(r.spp)],
                    [`План ${month}`, planEdit === keyOf(r) ? <input key="plan" autoFocus aria-label={`План ${r.vendor_code}`} defaultValue={r.plan ?? ""}
                      onBlur={e => savePlan(r, e.target.value)} onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setPlanEdit(null); }} />
                      : <button key="plan" className="link" disabled={!r.can_edit} title={`План продаж на ${month}, шт`} onClick={() => setPlanEdit(keyOf(r))}>{num(r.plan) || "—"}</button>],
                    ["ДРР зак.", pct(r.drr_orders)], ["ДРР вык.", pct(r.drr_buyouts)], ["Конв. корз.", pct(r.conv_cart)], ["Конв. зак.", pct(r.conv_order)],
                  ].map(([label, value], i) => <div className="action-key-item" key={i}
                    title={i === 7 || i >= 11 ? "За последние 7 полных дней" : String(label)}>
                    <span>{label}</span><b className={i === 5 && (r.margin_pct ?? 0) < 0 ? "down" : i === 8 && r.stock_days != null && r.stock_days < 14 ? "warn" : ""}>{value === "" ? "—" : value}</b>
                  </div>)}
                </div></td>}
                {showCharts && <td><ActionSparks data={charts[r.shop_id!]} nm={r.nm_id} /></td>}
                {b.days.map((d) => {
                  const acts = (r.actions[d] || []).filter(a => visibleAct(a, deepAds));
                  return (
                    <td key={d} className={"day" + (r.can_edit ? " click" : "")}
                      onClick={() => r.can_edit && setEdit({ t: [{ shop: r.shop_id!, nm: r.nm_id }], label: `${r.vendor_code} · ${dd(d)}`, day: d, existing: acts })}>
                      <ActionDayContent row={r} day={d} kinds={kinds} drr={drr} deepAds={deepAds}
                        dayPrices={dayPrices} adStats={adStats} adGroups={adGroups} adBasis={adBasis} />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!rows.length && <div className="hint">Нет артикулов по фильтру.</div>}
      {edit && <Editor targets={edit.t} kinds={b.kinds} label={edit.label} day0={edit.day} existing={edit.existing} me={b.me}
        onClose={() => setEdit(null)} onSaved={() => { load(); if (edit.t.length > 1) setPicked(new Set()); }} />}
    </div>
  );
}

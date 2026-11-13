import { useEffect, useMemo, useRef, useState } from "react";
import { http } from "./api";
import { ActionSparks, type ActionChartData } from "./ActionSparks";

type Kind = { key: string; title: string; color: string; unit?: string };
type Act = { id: number | string; kind: string; value: string | null; note?: string | null; who?: string; user_id?: number; auto?: boolean; color?: string | null };
type Row = {
  nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; photo: string | null;
  stock_wb: number | null; stock_fbs: number | null; stock: number | null; price: number | null; price_spp: number | null;
  margin_pct: number | null; rating: number | null; orders_avg: number; stock_days: number | null; spp: number | null; plan: number | null;
  drr_orders: number | null; drr_buyouts: number | null; conv_cart: number | null; conv_order: number | null;
  orders: Record<string, number>; actions: Record<string, Act[]>;
  ads?: Record<string, { all: number; ark: number; prk: number; search: number; rec: number; osum: number | null }>;
  shop_id?: number; shop_title?: string; can_edit?: boolean;
};
type Target = { shop: number; nm: number };
const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const keyOf = (r: { shop_id?: number; nm_id: number }) => `${r.shop_id}:${r.nm_id}`;
type Board = { days: string[]; kinds: Kind[]; rows: Row[]; month: string; me: number; can_edit: boolean; mp?: string };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const pct = (v: number | null) => (v == null ? "" : nf1.format(v * 100) + " %");
const num = (v: number | null) => (v == null ? "" : nf.format(v));
// ДРР в ячейках дня : общий, по виду рекламы (АРК / ПРК) и по направлению (поиск / рекомендации)
const DRR: [string, string, string][] = [["all", "общий", "ДРР"], ["ark", "АРК", "АРК"], ["prk", "ПРК", "ПРК"], ["search", "поиск", "Поиск"], ["rec", "рекомендации", "Реком."]];
const dd = (s: string) => s.slice(8, 10) + "." + s.slice(5, 7);
const WD = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];

const AUTO: Record<string, { title: string; color: string }> = {
  // цвета : цена ↑ зелёный / ↓ красный (приходит с сервера), акции розовый, фото и карточка синий, реклама жёлтый,
  // характеристики бирюзовый (с сервера), прочее — свои цвета
  "auto:price": { title: "Цена", color: "#16a34a" }, "auto:content": { title: "Карточка", color: "#2563eb" },
  "auto:photo": { title: "Фото", color: "#2563eb" }, "auto:size": { title: "Размеры", color: "#f97316" },
  "auto:ad_status": { title: "Реклама", color: "#ca8a04" }, "auto:ad_bid": { title: "Ставка", color: "#ca8a04" },
  "auto:promo": { title: "Акция", color: "#db2777" }, "auto:promo_day": { title: "В акции", color: "#f472b6" },
  "auto:entry": { title: "Точка входа", color: "#dc2626" },   // цвет с сервера: рост зелёный, просадка красный
};

function chip(a: Act, kinds: Record<string, Kind>) {
  const k = kinds[a.kind];
  const au = AUTO[a.kind];
  const title = k?.title || au?.title || a.kind.replace(/^custom:/, "");
  const color = a.color || k?.color || au?.color || "#6b7280";
  const label = a.auto ? a.value || title : title + (a.value ? " " + a.value + (k?.unit && !/[₽шт%]/.test(a.value) ? " " + k.unit : "") : "");
  return (
    <span key={a.id} className={"chip" + (a.auto ? " auto" : "")} style={{ borderColor: color, color }}
      title={(a.auto ? "Заметили сами (API): " : (a.who ? a.who + ": " : "")) + label + (a.note ? "\n" + a.note : "")}>
      {a.auto ? "⚙ " : ""}{label}
    </span>
  );
}

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
                {chip(a, Object.fromEntries(kinds.map((k) => [k.key, k])))}
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

export function ActionsBoard({ shop, shops, enableCharts = true }: { shop: number; shops: { id: number; title: string }[]; enableCharts?: boolean }) {
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
  const [showKey, setShowKey] = useState(() => lsGet("act_key") !== "0");
  const [drr, setDrr] = useState<string[]>(() => (lsGet("act_drr") || "").split(",").filter(Boolean));
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [edit, setEdit] = useState<{ t: Target[]; label: string; day: string; existing: Act[] } | null>(null);
  const [planEdit, setPlanEdit] = useState<string | null>(null);
  const many = scope === "all" && shops.length > 1;
  const shopKey = (many ? shops.map(s => s.id) : [shop]).join(",");
  context.current = `${shopKey}:${days}:${drr.length > 0}`;
  const load = () => {
    const generation = ++request.current, key = context.current;
    const list = many ? shops : [{ id: shop, title: "" }];
    Promise.all(list.map((s) => http.get<Board>(`/api/shops/${s.id}/manager/board?days=${days}${drr.length ? "&ads=true" : ""}`)
      .then((x) => ({ ...x, rows: x.rows.map((r) => ({ ...r, shop_id: s.id, shop_title: s.title, can_edit: x.can_edit })) }))))
      .then((bs) => { if (generation !== request.current || key !== context.current) return; setB({ ...bs[0], can_edit: bs.some((x) => x.can_edit), rows: bs.flatMap((x) => x.rows) }); setErr(""); })
      .catch((e) => { if (generation === request.current && key === context.current) setErr(e.message); });
  };
  const withAds = drr.length > 0;
  useEffect(() => { setB(null); setErr(""); setPicked(new Set()); load(); return () => { request.current++; }; }, [shopKey, days, withAds]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { try { localStorage.setItem("act_days", String(days)); localStorage.setItem("act_key", showKey ? "1" : "0");
    localStorage.setItem("act_scope", scope); localStorage.setItem("act_drr", drr.join(",")); } catch { /* нет хранилища */ } }, [days, showKey, scope, drr]);
  useEffect(() => {
    let live = true;
    setCharts({});
    if (showCharts) for (const id of shopKey.split(",").map(Number)) {
      http.get<ActionChartData>(`/api/shops/${id}/manager/charts`).then(data => {
        if (live) setCharts(old => ({ ...old, [id]: data }));
      }).catch(e => { if (live) setCharts(old => ({ ...old, [id]: { days: [], rows: {}, price_label: "", note: "", error: e.message } })); });
    }
    return () => { live = false; };
  }, [shopKey, showCharts, chartsReload]);
  const kinds = useMemo(() => Object.fromEntries((b?.kinds || []).map((k) => [k.key, k])), [b]);
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (b?.rows || []).filter((r) => (!ql || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.subject}`.toLowerCase().includes(ql))
      && (!onlyActs || Object.keys(r.actions).length > 0));
  }, [b, q, onlyActs]);
  if (err) return <div className="err">{err}</div>;
  if (!b) return <div className="hint">Загрузка…</div>;
  const oz = b.mp === "ozon";
  const all = rows.length > 0 && rows.every((r) => picked.has(keyOf(r)));
  const flip = (k: string) => setPicked((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const savePlan = (r: Row, v: string) => {
    setPlanEdit(null);
    const qty = v.trim() === "" ? null : Number(v.replace(",", "."));
    if (qty !== null && !Number.isFinite(qty)) return;
    http.put(`/api/shops/${r.shop_id}/nm_plan`, { nm_id: r.nm_id, month: b.month, qty }).then(load).catch((e) => setErr(e.message));
  };
  const pickedT = (): Target[] => [...picked].map((k) => { const [sh, nm] = k.split(":").map(Number); return { shop: sh, nm }; });
  const month = new Date(b.month).toLocaleString("ru-RU", { month: "long" });
  return (
    <div className="board">
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 14, 21, 30, 45, 60].map((d) => <option key={d} value={d}>{d} дней</option>)}
        </select>
        <label><input type="checkbox" checked={onlyActs} onChange={(e) => setOnlyActs(e.target.checked)} /> только с действиями</label>
        <label><input type="checkbox" checked={showKey} onChange={(e) => setShowKey(e.target.checked)} /> ключевые данные</label>
        {enableCharts && <label><input type="checkbox" checked={showCharts} onChange={e => { setShowCharts(e.target.checked); try { localStorage.setItem("act_charts", e.target.checked ? "1" : "0"); } catch { /* no storage */ } }} /> графики за 30 дней</label>}
        {showCharts && Object.values(charts).some(c => c.error) && <button onClick={() => setChartsReload(x => x+1)}>Повторить загрузку графиков</button>}
        {!oz && <span className="hint" title="ДРР дня = расход на рекламу ÷ сумма заказов артикула за день. АРК — единая ставка, ПРК — ручная (аукцион); поиск — траты по поисковым кластерам, рекомендации — остальное (полки, каталог)">ДРР в ячейках:</span>}
        {!oz && DRR.map(([k, t]) => <label key={k}><input type="checkbox" checked={drr.includes(k)}
          onChange={(e) => setDrr((xs) => e.target.checked ? DRR.map((x) => x[0]).filter((x) => x === k || xs.includes(x)) : xs.filter((x) => x !== k))} /> {t}</label>)}
        {shops.length > 1 && (
          <select value={scope} onChange={(e) => setScope(e.target.value as "one" | "all")} title="Как в планфакте: несколько юрлиц на одной доске">
            <option value="one">Выбранный магазин</option><option value="all">Все магазины кабинета ({shops.length})</option>
          </select>
        )}
        {b.can_edit && picked.size > 0 && (
          <button onClick={() => setEdit({ t: pickedT(), label: `выбрано артикулов: ${picked.size}`, day: b.days[0], existing: [] })}>
            + Действие для выбранных ({picked.size})
          </button>
        )}
        {picked.size > 0 && <button className="link" onClick={() => setPicked(new Set())}>снять выбор</button>}
        <span className="hint">Клик по дню — записать действия. ⚙ — изменения, которые мы заметили сами в API {oz ? "Ozon" : "WB"}.</span>
      </div>
      {showCharts && <div className="hint">{[...new Set(Object.values(charts).map(c => c.note).filter(Boolean))].join(" ")}</div>}
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
            {rows.map((r) => (
              <tr key={keyOf(r)} className={picked.has(keyOf(r)) ? "picked" : ""}>
                <td className="sx c0">{r.can_edit && <input type="checkbox" checked={picked.has(keyOf(r))} onChange={() => flip(keyOf(r))} />}
                  {r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
                <td className="sx c1" title={r.title || ""}><b>{r.vendor_code}</b><div className="hint">{many ? r.shop_title + " · " : ""}{r.nm_id} · {(r.title || "").slice(0, 34)}</div></td>
                {showKey && <td><div className="action-key-grid">
                  {[
                    [oz ? "Ост. FBO" : "Ост. WB", num(r.stock_wb)], ["Ост. ФБС", num(r.stock_fbs)], ["Ост. всего", num(r.stock)],
                    [oz ? "Цена продавца" : "Цена без СПП", num(r.price)], [oz ? "Цена с акциями" : "Цена с СПП", num(r.price_spp)],
                    ["Маржа %", pct(r.margin_pct)], ["Рейтинг", r.rating == null ? "" : nf1.format(r.rating)], ["Ср. заказы", nf1.format(r.orders_avg)],
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
                {b.days.map((d, i) => {
                  const o = r.orders[d] ?? 0;
                  const prevDay = b.days[i + 1] ?? new Date(new Date(d).getTime() - 864e5).toISOString().slice(0, 10);
                  const p = r.orders[prevDay];
                  const acts = r.actions[d] || [];
                  return (
                    <td key={d} className={"day" + (r.can_edit ? " click" : "")}
                      onClick={() => r.can_edit && setEdit({ t: [{ shop: r.shop_id!, nm: r.nm_id }], label: `${r.vendor_code} · ${dd(d)}`, day: d, existing: acts })}>
                      <div className={"o" + (p != null && o > p ? " up" : p != null && o < p ? " down" : "")}>{o}</div>
                      {drr.length > 0 && r.ads?.[d] && <div className="hint" style={{ fontSize: 11, lineHeight: 1.25, whiteSpace: "nowrap" }}>
                        {DRR.filter(([k]) => drr.includes(k)).map(([k, , short]) => { const a = r.ads![d], v = a[k as "all"];
                          return v ? <div key={k}>{short} {a.osum ? nf1.format(v / a.osum * 100) + "%" : nf.format(v) + " ₽"}</div> : null; })}</div>}
                      {acts.map((a) => chip(a, kinds))}
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

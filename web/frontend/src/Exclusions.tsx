import { useEffect, useMemo, useState } from "react";
import { http } from "./api";

type Item = { nm_id: number; vendor_code: string | null; title: string | null; brand: string; subject: string; photo: string | null;
  orders_30d: number; direct: boolean; off: boolean };
type Grp = { name: string; n: number; orders_30d: number; off: boolean };
type Data = { items: Item[]; brands: Grp[]; subjects: Grp[]; total: number; off: number; can_edit: boolean };

/** Настройки магазина → «Артикулы в работе»: отключить артикулы, бренды, предметы (по умолчанию включено всё). */
export function Exclusions({ shop }: { shop: number }) {
  const [d, setD] = useState<Data | null>(null);
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<"all" | "on" | "off">("all");
  const [msg, setMsg] = useState(""), [err, setErr] = useState("");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [pend, setPend] = useState<Record<string, boolean>>({});   // «вид|значение» → отключить? (ждёт «Сохранить»)
  const [saving, setSaving] = useState(false);
  const load = () => http.get<Data>(`/api/shops/${shop}/exclusions`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); setSel(new Set()); setPend({}); load(); }, [shop]);
  const items = useMemo(() => (d?.items || []).filter((r) => (only === "all" || (only === "off") === r.off)
    && (!q || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.brand} ${r.subject}`.toLowerCase().includes(q.toLowerCase()))), [d, q, only]);
  if (err && !d) return <div className="err">{err}</div>;
  if (!d) return <div className="hint">Загрузка…</div>;
  const set = (kind: string, values: (string | number)[], off: boolean) =>
    http.put<{ message: string }>(`/api/shops/${shop}/exclusions`, { kind, values: values.map(String), off })
      .then((r) => { setMsg(r.message); setSel(new Set()); load(); }).catch((e) => setErr(e.message));
  const offNow = (kind: string, value: string | number, cur: boolean) => { const k = `${kind}|${value}`; return k in pend ? pend[k] : cur; };
  const toggle = (kind: string, value: string | number, cur: boolean, off: boolean) => setPend((p) => {
    const n = { ...p }; const k = `${kind}|${value}`;
    if (off === cur) delete n[k]; else n[k] = off;
    return n;
  });
  const nPend = Object.keys(pend).length;
  const save = () => { setSaving(true); setErr("");
    http.put<{ message: string }>(`/api/shops/${shop}/exclusions/batch`, { changes: Object.entries(pend).map(([k, off]) => {
      const i = k.indexOf("|"); return { kind: k.slice(0, i), value: k.slice(i + 1), off }; }) })
      .then((r) => { setMsg(r.message); setPend({}); load(); }).catch((e) => setErr(e.message)).finally(() => setSaving(false)); };
  const Grp = ({ title, kind, list }: { title: string; kind: string; list: Grp[] }) => (
    <div className="acc-box">
      <b>{title}</b>
      <div className="excl-grp">{list.map((g) => (
        <label key={g.name} className={"chip" + (offNow(kind, g.name, g.off) ? " off" : "") + (`${kind}|${g.name}` in pend ? " pend" : "")} title={`${g.n} арт., заказов за 30 дней: ${g.orders_30d}`}>
          <input type="checkbox" disabled={!d.can_edit} checked={!offNow(kind, g.name, g.off)} onChange={(e) => toggle(kind, g.name, g.off, !e.target.checked)} />
          {g.name || "без названия"} <span className="hint">{g.n} · {g.orders_30d}</span>
        </label>))}</div>
    </div>
  );
  return (
    <div className="board">
      <div className="acc-box">
        <b>Артикулы в работе: {d.total - d.off} из {d.total}</b>
        <div className="hint">Отключённые артикулы (вручную, целым брендом или предметом) исчезают из всех вкладок, дашбордов, планов и сводок,
          по ним не собирается воронка WB. По умолчанию включено всё; вернуть можно в любой момент. После изменения цифры магазина
          пересчитываются несколько минут. Финансовый отчёт WB (5#PnL#Реализация…) остаётся полным — это документ WB по кабинету целиком.</div>
        {!d.can_edit && <div className="hint">Менять может админ или владелец кабинета.</div>}
        {msg && <div className="ok">{msg}</div>}{err && <div className="err">{err}</div>}
      </div>
      {nPend > 0 && <div className="excl-save">
        <b>Не сохранено: {nPend} изм.</b>
        <button className="pri" disabled={saving} onClick={save}>{saving ? "Сохраняю…" : "💾 Сохранить"}</button>
        <button disabled={saving} onClick={() => setPend({})}>Отменить</button>
      </div>}
      {d.brands.length > 1 && <Grp title="Бренды" kind="brand" list={d.brands} />}
      {d.subjects.length > 1 && <Grp title="Предметы" kind="subject" list={d.subjects} />}
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, бренд" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={only} onChange={(e) => setOnly(e.target.value as "all" | "on" | "off")}>
          <option value="all">Все</option><option value="on">Только в работе</option><option value="off">Только отключённые</option>
        </select>
        {d.can_edit && sel.size > 0 && <>
          <button onClick={() => set("nm", [...sel], true)}>Отключить выбранные ({sel.size})</button>
          <button onClick={() => set("nm", [...sel], false)}>Включить выбранные</button>
        </>}
        {d.can_edit && items.length > 0 && <button className="link" onClick={() => setSel(new Set(items.map((r) => r.nm_id)))}>выбрать все по фильтру ({items.length})</button>}
      </div>
      <div className="board-wrap"><table className="board-t">
        <thead><tr><th></th><th></th><th>Артикул</th><th>Бренд</th><th>Предмет</th><th>Заказов за 30 дн.</th><th>В работе</th></tr></thead>
        <tbody>{items.slice(0, 1500).map((r) => (
          <tr key={r.nm_id} className={r.off ? "excl-off" : ""}>
            <td>{d.can_edit && <input type="checkbox" checked={sel.has(r.nm_id)} onChange={() => setSel((s) => { const n = new Set(s); if (n.has(r.nm_id)) n.delete(r.nm_id); else n.add(r.nm_id); return n; })} />}</td>
            <td>{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
            <td><b>{r.vendor_code}</b><div className="hint">{r.nm_id} · {(r.title || "").slice(0, 50)}</div></td>
            <td>{r.brand}</td><td>{r.subject}</td><td className="n">{r.orders_30d}</td>
            <td>{d.can_edit ? <input type="checkbox" checked={!offNow("nm", r.nm_id, r.off && r.direct) && !(r.off && !r.direct)} disabled={r.off && !r.direct}
              title={r.off && !r.direct ? "Отключён брендом или предметом — включите их выше" : ""} onChange={(e) => toggle("nm", r.nm_id, r.off && r.direct, !e.target.checked)} />
              : r.off ? "нет" : "да"}{r.off && !r.direct && <span className="hint"> (бренд/предмет)</span>}</td>
          </tr>))}</tbody>
      </table></div>
      {items.length > 1500 && <div className="hint">Показаны первые 1500 из {items.length} — уточните поиск.</div>}
    </div>
  );
}

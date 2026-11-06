import { useEffect, useState } from "react";
import { api, http, type Article } from "./api";

/** Внешние расходы (блогеры, посевы) и раздачи — ручной ввод; в Чек-листе раскладываются по дням (внешка входит в ДРР). Видео 10X, обновление 1. */
type Row = { id: number; nm_id: number; vendor_code: string | null; kind: "ext" | "giveaway"; source: string | null; d_from: string; d_to: string | null;
  cost: number; qty: number | null; clicks: number | null; comment: string | null; who: string | null };
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const dd = (s: string | null) => (s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}` : "");

export function ExtCosts({ shop }: { shop: number }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [canEdit, setCanEdit] = useState(false);
  const [arts, setArts] = useState<Article[]>([]);
  const [kind, setKind] = useState<"ext" | "giveaway">("ext");
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ nm_id: "", source: "", d_from: today, d_to: "", cost: "", qty: "", clicks: "", comment: "" });
  const [err, setErr] = useState("");
  const load = () => http.get<{ rows: Row[]; can_edit: boolean }>(`/api/shops/${shop}/ext_costs`).then((d) => { setRows(d.rows); setCanEdit(d.can_edit); })
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); api.articles(shop).then(setArts).catch(() => setArts([])); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const n = (s: string) => (s.trim() ? Number(s.replace(",", ".").replace(/\s/g, "")) : null);
  const add = () => {
    setErr("");
    if (!f.nm_id) { setErr("Выберите артикул"); return; }
    http.post(`/api/shops/${shop}/ext_costs`, { nm_id: Number(f.nm_id), kind, source: f.source || null, d_from: f.d_from, d_to: f.d_to || null,
      cost: n(f.cost) || 0, qty: n(f.qty), clicks: n(f.clicks), comment: f.comment || null })
      .then(() => { setF({ ...f, source: "", cost: "", qty: "", clicks: "", comment: "" }); load(); }).catch((e) => setErr(e.message));
  };
  const list = rows.filter((r) => r.kind === kind);
  return (
    <div className="ext">
      <div className="rnp-bar">
        <button className={kind === "ext" ? "on" : ""} onClick={() => setKind("ext")}>📣 Внешние расходы (блогеры, посевы)</button>
        <button className={kind === "giveaway" ? "on" : ""} onClick={() => setKind("giveaway")}>🎁 Раздачи / самовыкупы</button>
        <span className="hint">{kind === "ext" ? "Затраты делятся поровну на дни с «Дата поста» по «Дата окончания» (без окончания — весь в день поста) и входят в ДРР Чек-листа."
          : "Раздачи по дням: штук и затраты — в Чек-листе отдельными столбцами."}</span>
      </div>
      {err && <div className="err">{err}</div>}
      {canEdit && <div className="acc-box ext-form">
        <select value={f.nm_id} onChange={(e) => setF({ ...f, nm_id: e.target.value })}><option value="">Артикул…</option>
          {arts.map((a) => <option key={a.nm_id} value={a.nm_id}>{a.vendor_code || a.nm_id} — {(a.title || "").slice(0, 30)}</option>)}</select>
        <input placeholder={kind === "ext" ? "Источник (блогер, канал)" : "Площадка / кто раздаёт"} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} />
        <label>{kind === "ext" ? "Дата поста" : "С"} <input type="date" value={f.d_from} onChange={(e) => setF({ ...f, d_from: e.target.value })} /></label>
        <label>{kind === "ext" ? "Дата окончания" : "По"} <input type="date" value={f.d_to} onChange={(e) => setF({ ...f, d_to: e.target.value })} /></label>
        <input placeholder="Затраты, ₽" inputMode="decimal" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} />
        {kind === "giveaway" ? <input placeholder="Штук" inputMode="decimal" value={f.qty} onChange={(e) => setF({ ...f, qty: e.target.value })} />
          : <input placeholder="Переходов (если знаете)" inputMode="decimal" value={f.clicks} onChange={(e) => setF({ ...f, clicks: e.target.value })} />}
        <input placeholder="Комментарий" value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} />
        <button onClick={add}>+ Добавить</button>
      </div>}
      <table className="rnp-t">
        <thead><tr><th>Артикул</th><th>{kind === "ext" ? "Источник" : "Площадка"}</th><th>С</th><th>По</th><th>Затраты</th>
          <th>{kind === "ext" ? "Переходов" : "Штук"}</th><th>Комментарий</th><th>Кто</th><th /></tr></thead>
        <tbody>{list.map((r) => <tr key={r.id}><td>{r.vendor_code || r.nm_id}</td><td>{r.source}</td><td>{dd(r.d_from)}</td><td>{dd(r.d_to)}</td>
          <td>{nf.format(r.cost)} ₽</td><td>{kind === "ext" ? (r.clicks ?? "") : (r.qty ?? "")}</td><td>{r.comment}</td><td className="hint">{r.who}</td>
          <td>{canEdit && <button className="link" onClick={() => { if (confirm("Удалить запись?")) http.del(`/api/shops/${shop}/ext_costs/${r.id}`).then(load); }}>✕</button>}</td></tr>)}
          {!list.length && <tr><td colSpan={9} className="hint">Записей пока нет.</td></tr>}</tbody>
      </table>
    </div>
  );
}

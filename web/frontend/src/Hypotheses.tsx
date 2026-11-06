import { useEffect, useState } from "react";
import { api, http, type Article } from "./api";

/** Гипотезы (видео 10X №10): что тестируем по артикулу, срок и итог; в Чек-листе видны в дни теста. */
type H = { id: number; nm_id: number; vendor_code: string | null; photo: string | null; kind: string; indicator: string | null; text: string;
  d_from: string; days: number | null; report: string | null; who: string | null; created_at: string };
type Data = { rows: H[]; kinds: string[]; indicators: string[]; can_edit: boolean };
const dd = (s: string) => `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}`;
const addDays = (s: string, n: number) => { const d = new Date(s); d.setDate(d.getDate() + n - 1); return d.toISOString().slice(0, 10); };

export function Hypotheses({ shop }: { shop: number }) {
  const [d, setD] = useState<Data | null>(null);
  const [arts, setArts] = useState<Article[]>([]);
  const today = new Date().toISOString().slice(0, 10);
  const empty = { nm_id: "", kind: "Гипотеза", indicator: "", text: "", d_from: today, days: "7", report: "" };
  const [f, setF] = useState(empty);
  const [edit, setEdit] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const load = () => http.get<Data>(`/api/shops/${shop}/hypotheses`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); api.articles(shop).then(setArts).catch(() => setArts([])); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const save = () => {
    setErr("");
    const body = { nm_id: Number(f.nm_id), kind: f.kind, indicator: f.indicator || null, text: f.text, d_from: f.d_from,
      days: f.days ? Number(f.days) : null, report: f.report || null };
    (edit ? http.put(`/api/shops/${shop}/hypotheses/${edit}`, body) : http.post(`/api/shops/${shop}/hypotheses`, body))
      .then(() => { setF(empty); setEdit(null); load(); }).catch((e) => setErr(e.message));
  };
  if (!d) return <div className="hint">{err || "Загрузка…"}</div>;
  return (
    <div className="hyp">
      {err && <div className="err">{err}</div>}
      {d.can_edit && <div className="acc-box ext-form">
        <select value={f.nm_id} onChange={(e) => setF({ ...f, nm_id: e.target.value })}><option value="">Артикул…</option>
          {arts.map((a) => <option key={a.nm_id} value={a.nm_id}>{a.vendor_code || a.nm_id} — {(a.title || "").slice(0, 30)}</option>)}</select>
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{d.kinds.map((k) => <option key={k}>{k}</option>)}</select>
        <select value={f.indicator} onChange={(e) => setF({ ...f, indicator: e.target.value })}><option value="">Тест показателя…</option>
          {d.indicators.map((k) => <option key={k}>{k}</option>)}</select>
        <input placeholder="Гипотеза: что меняем и чего ждём" value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} style={{ minWidth: 320 }} />
        <label>С <input type="date" value={f.d_from} onChange={(e) => setF({ ...f, d_from: e.target.value })} /></label>
        <label>Дней <input inputMode="numeric" value={f.days} onChange={(e) => setF({ ...f, days: e.target.value.replace(/\D/g, "") })} style={{ width: 60 }} /></label>
        <input placeholder="Отчёт (итог)" value={f.report} onChange={(e) => setF({ ...f, report: e.target.value })} style={{ minWidth: 240 }} />
        <button disabled={!f.nm_id || !f.text.trim()} onClick={save}>{edit ? "Сохранить" : "+ Добавить"}</button>
        {edit && <button className="link" onClick={() => { setEdit(null); setF(empty); }}>отмена</button>}
      </div>}
      <table className="rnp-t">
        <thead><tr><th>Фото</th><th>Артикул</th><th>Вид</th><th>Дата записи</th><th>Тест показателя</th><th>Гипотеза</th><th>Начало</th><th>Дней</th>
          <th>Окончание</th><th>Отчёт</th><th>Кто</th><th /></tr></thead>
        <tbody>{d.rows.map((h) => <tr key={h.id}>
          <td>{h.photo && <img src={h.photo} alt="" style={{ height: 36 }} loading="lazy" />}</td><td><b>{h.vendor_code || h.nm_id}</b></td>
          <td className={h.kind === "Подтвердилась" ? "z-good" : h.kind === "Не подтвердилась" ? "z-bad" : ""}>{h.kind}</td>
          <td>{dd(h.created_at)}</td><td>{h.indicator}</td><td style={{ maxWidth: 360 }}>{h.text}</td><td>{dd(h.d_from)}</td><td>{h.days ?? ""}</td>
          <td>{h.days ? dd(addDays(h.d_from, h.days)) : ""}</td><td style={{ maxWidth: 320 }}>{h.report}</td><td className="hint">{h.who}</td>
          <td>{d.can_edit && <><button className="link" onClick={() => { setEdit(h.id); setF({ nm_id: String(h.nm_id), kind: h.kind, indicator: h.indicator || "",
            text: h.text, d_from: h.d_from, days: h.days ? String(h.days) : "", report: h.report || "" }); }}>✎</button>
            <button className="link" onClick={() => { if (confirm("Удалить гипотезу?")) http.del(`/api/shops/${shop}/hypotheses/${h.id}`).then(load); }}>✕</button></>}</td>
        </tr>)}
        {!d.rows.length && <tr><td colSpan={12} className="hint">Гипотез пока нет. Подсказки, что тестировать, — в блоке «Опасности» Чек-листа.</td></tr>}</tbody>
      </table>
    </div>
  );
}

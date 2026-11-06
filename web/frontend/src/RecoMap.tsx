/** Карта рекомендаций товара : что советовать в ответах на отзывы и вопросы по этому товару — по смыслу, только свои товары.
 *  Нейросеть подбирает 3–5, менеджер правит: убрать, добавить артикул, закрепить. Серые — сейчас не советуем (нет в наличии / рейтинг < 4,5). */
import { useEffect, useState } from "react";
import { http } from "./api";

type It = { nm_id: number; kind: "pair" | "alt"; why: string; manual?: boolean; pinned?: boolean; removed?: boolean;
  vendor_code?: string | null; title?: string | null; photo?: string | null; ok?: boolean };
type Q = { nm_id: number; kind: string; kind_t: string; why: string; title: string; vendor_code: string | null; photo?: string | null };
type M = { items: It[]; source: string | null; updated_at: string | null; min_rating?: number; reg?: string | null; queue?: Q[] };

export function RecoMap({ shop, nm }: { shop: number; nm: number }) {
  const [m, setM] = useState<M | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [add, setAdd] = useState("");
  const [why, setWhy] = useState("");
  const url = `/api/shops/${shop}/reco/${nm}`;
  useEffect(() => { setM(null); http.get<M>(url).then(setM).catch((e) => setErr(e.message)); }, [url]);
  const save = (items: It[]) => { setBusy(true); http.put<M>(url, { items }).then((x) => { setM(x); setBusy(false); }).catch((e) => { setErr(e.message); setBusy(false); }); };
  const build = () => {        // подбор идёт в фоне (до 1–2 минут) — перечитываем карту, пока не обновится
    setBusy(true); setErr("");
    const was = m?.updated_at;
    http.post(`${url}/build`).then(() => {
      let n = 0;
      const t = window.setInterval(() => http.get<M>(url).then((x) => { n++; if (x.updated_at !== was || n > 30) { setM(x); setBusy(false); window.clearInterval(t); } }), 8000);
    }).catch((e) => { setErr(e.message); setBusy(false); });
  };
  if (!m) return <div className="hint">{err || "Загрузка…"}</div>;
  const live = m.items.filter((x) => !x.removed);
  const gone = m.items.filter((x) => x.removed);
  const upd = (i: It, p: Partial<It>) => save(m.items.map((x) => x.nm_id === i.nm_id ? { ...x, ...p } : x));
  return <div className="acc-box">
    <b>Что советовать в ответах по этому товару</b>
    <div className="hint">Работает, если в правилах отмечено «Советовать товары нашего магазина». Нейросеть подбирает по смыслу: дополняет
      (берут вместе) или замена. В ответ — один товар, не в каждом ответе. Серые сейчас не советуем: нет в наличии или рейтинг ниже {String(m.min_rating ?? 4.5).replace(".", ",")}.</div>
    {m.reg && <div className="acc-box"><b>📋 {m.reg}</b>
      <div className="hint">Очередь для ответов — по приоритетам; ниже в карте — сопутствующие (замены по регламенту не советуем). Локомотивы — тег «локомотив» в группах артикулов.</div>
      <table className="acc-t"><tbody>{(m.queue || []).map((x, i) => <tr key={x.nm_id}>
        <td>{i + 1}</td><td>{x.photo && <img className="thumb" src={x.photo} alt="" />}</td>
        <td>{x.vendor_code || x.nm_id}<div className="hint">{(x.title || "").slice(0, 60)} · арт. {x.nm_id}</div></td><td>{x.kind_t}</td><td>{x.why}</td></tr>)}
        {!(m.queue || []).length && <tr><td className="hint">Сейчас советовать нечего: нет подходящих товаров в наличии с рейтингом от 4,7.</td></tr>}</tbody></table></div>}
    {err && <div className="err">{err}</div>}
    <table className="acc-t"><tbody>
      {live.map((x) => <tr key={x.nm_id} style={{ opacity: x.ok === false ? 0.45 : 1 }}>
        <td>{x.photo && <img className="thumb" src={x.photo} alt="" />}</td>
        <td>{x.vendor_code || x.nm_id}<div className="hint">{(x.title || "").slice(0, 60)} · арт. {x.nm_id}</div></td>
        <td>{x.kind === "alt" ? (m.reg ? "замена — не советуем" : "замена") : m.reg ? "сопутствующий" : "дополняет"}</td>
        <td style={{ maxWidth: 260 }}>{x.why}</td>
        <td><label><input type="checkbox" checked={!!x.pinned} disabled={busy} onChange={(e) => upd(x, { pinned: e.target.checked })} /> закрепить</label>{" "}
          <button className="link" disabled={busy} onClick={() => upd(x, { removed: true, pinned: false })}>убрать</button></td>
      </tr>)}
      {!live.length && <tr><td className="hint">Пока пусто — нажмите «Подобрать нейросетью» или добавьте артикул.</td></tr>}
    </tbody></table>
    <div className="rnp-bar">
      <button disabled={busy} onClick={build}>{busy ? "⏳ подбираю (до 2 минут)…" : "✨ Подобрать нейросетью"}</button>
      <input placeholder="Артикул WB" value={add} onChange={(e) => setAdd(e.target.value.replace(/\D/g, ""))} style={{ width: 120 }} />
      <input placeholder="зачем (коротко)" value={why} onChange={(e) => setWhy(e.target.value)} />
      <button disabled={busy || !add} onClick={() => { save([...m.items.filter((x) => x.nm_id !== Number(add)), { nm_id: Number(add), kind: "pair", why, manual: true }]); setAdd(""); setWhy(""); }}>+ добавить</button>
    </div>
    {gone.length > 0 && <div className="hint">Убраны (нейросеть их не предложит): {gone.map((x) => <button key={x.nm_id} className="link"
      onClick={() => upd(x, { removed: false })} title="вернуть">{x.vendor_code || x.nm_id} ↺</button>)}</div>}
  </div>;
}

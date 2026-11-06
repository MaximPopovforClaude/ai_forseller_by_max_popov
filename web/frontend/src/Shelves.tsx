import { useEffect, useMemo, useState } from "react";
import { http } from "./api";

type Row = { nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; photo: string | null;
  in_n: number; in_n_was: number | null; best: number | null; avg: number | null; shelf_total: number | null; own_top20: number };
type Over = { day: string | null; was_day: string | null; rows: Row[] };
type Card = { nm_id: number; name: string | null; brand: string | null; supplier: string | null; price: number | null;
  rating: number | null; feedbacks: number | null; ours: boolean; photo: string | null; pos?: number; pos_was?: number | null };
type Detail = { day: string | null; was_day: string | null; card: Card; taken: boolean; shelf_total: number | null;
  shelf: Card[]; left: Card[]; where: Card[]; where_gone: Card[]; hist: { day: string; n: number; avg: number | null; top10: number }[] };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const dt = (s: string | null) => (s ? new Date(s).toLocaleDateString("ru-RU") : "—");
const wb = (nm: number) => `https://www.wildberries.ru/catalog/${nm}/detail.aspx`;

/** Сдвиг места: ↑ поднялся, ↓ опустился, «новый» — не было неделю назад. */
function Move({ pos, was, hasWas }: { pos?: number; was?: number | null; hasWas: boolean }) {
  if (!hasWas || pos == null) return null;
  if (was == null) return <span className="t-good"> новый</span>;
  const d = was - pos;
  return d === 0 ? null : <span className={d > 0 ? "t-good" : "t-bad"}> {d > 0 ? "↑" : "↓"}{Math.abs(d)}</span>;
}

function Cards({ rows, hasWas, gone }: { rows: Card[]; hasWas: boolean; gone?: boolean }) {
  return (
    <div className="board-wrap"><table className="board-t">
      <thead><tr><th>Место</th><th></th><th>Товар</th><th>Продавец</th><th>Цена</th><th>Рейтинг</th></tr></thead>
      <tbody>{rows.map((r) => (
        <tr key={r.nm_id} style={r.ours ? { background: "var(--ok-bg, #ecfdf5)" } : undefined}>
          <td className="n">{gone ? <>было {r.pos_was}</> : <>{r.pos}<Move pos={r.pos} was={r.pos_was} hasWas={hasWas} /></>}</td>
          <td>{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
          <td><a href={wb(r.nm_id)} target="_blank" rel="noreferrer">{r.nm_id}</a>{r.ours && <b> · наш</b>}
            <div className="hint">{r.brand ? `${r.brand} · ` : ""}{(r.name || "").slice(0, 60)}</div></td>
          <td>{r.supplier}</td>
          <td className="n">{r.price != null ? nf.format(r.price) + " ₽" : ""}</td>
          <td className="n">{r.rating ?? ""}{r.feedbacks != null && <div className="hint">{nf.format(r.feedbacks)} отз.</div>}</td>
        </tr>))}</tbody>
    </table></div>
  );
}

function NmDetail({ shop, nm, onBack }: { shop: number; nm: number; onBack: () => void }) {
  const [d, setD] = useState<Detail | null>(null), [err, setErr] = useState("");
  const [view, setView] = useState<"where" | "shelf">("where");
  useEffect(() => { setD(null); http.get<Detail>(`/api/shops/${shop}/shelves/${nm}`).then(setD).catch((e) => setErr(e.message)); }, [shop, nm]);
  if (err) return <div className="err">{err}</div>;
  if (!d) return <div className="hint">Загрузка…</div>;
  const hasWas = !!d.was_day;
  const max = Math.max(1, ...d.hist.map((h) => h.n));
  return (
    <div>
      <button onClick={onBack}>← Все товары</button>
      <div className="acc-box">
        <b><a href={wb(nm)} target="_blank" rel="noreferrer">{nm}</a> {d.card.brand ? `· ${d.card.brand} ` : ""}· {d.card.name}</b>
        <div className="hint">Снимок {dt(d.day)}{hasWas ? `, сравнение с ${dt(d.was_day)}` : " — сравнение появится через неделю сбора"}.</div>
        {d.hist.length > 0 && <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 70, marginTop: 8 }}
          title="У скольких карточек товар стоит в полке, по дням">
          {d.hist.map((h) => <div key={h.day} title={`${dt(h.day)}: в полках у ${h.n}, в топ-10 у ${h.top10}, ср. место ${h.avg?.toFixed(1)}`}
            style={{ width: 14, height: `${(h.n / max) * 100}%`, minHeight: 2, background: "var(--accent, #7c3aed)", borderRadius: 2 }} />)}
        </div>}
      </div>
      <div className="board-bar">
        <button className={view === "where" ? "pri" : ""} onClick={() => setView("where")}>У кого в полках этот товар ({d.where.length})</button>
        <button className={view === "shelf" ? "pri" : ""} onClick={() => setView("shelf")}>Кто в полке у этого товара{d.taken ? ` (${d.shelf.length})` : ""}</button>
      </div>
      {view === "where" ? <>
        {!d.where.length && <div className="hint">Среди снятых карточек этот товар ни у кого в полке «Смотрите также» (топ-100) не найден.</div>}
        {d.where.length > 0 && <Cards rows={d.where} hasWas={hasWas} />}
        {d.where_gone.length > 0 && <><h4>Пропал из полок за неделю ({d.where_gone.length})</h4><Cards rows={d.where_gone} hasWas={hasWas} gone /></>}
      </> : <>
        {!d.taken && <div className="hint">Полку этой карточки ещё не снимали.</div>}
        {d.taken && <div className="hint">Всего в полке по ответу WB: {d.shelf_total ?? "—"}, показаны первые 100. Зелёным — наши товары.</div>}
        {d.shelf.length > 0 && <Cards rows={d.shelf} hasWas={hasWas} />}
        {d.left.length > 0 && <><h4>Ушли из полки за неделю ({d.left.length})</h4><Cards rows={d.left} hasWas={hasWas} gone /></>}
      </>}
    </div>
  );
}

/** Мониторинг полок WB : полка «Смотрите также» — кто стоит у наших товаров и у кого стоят наши, по дням. */
export function Shelves({ shop }: { shop: number }) {
  const [d, setD] = useState<Over | null>(null), [err, setErr] = useState("");
  const [q, setQ] = useState(""), [nm, setNm] = useState<number | null>(null), [any, setAny] = useState("");
  useEffect(() => { setD(null); setNm(null); http.get<Over>(`/api/shops/${shop}/shelves`).then(setD).catch((e) => setErr(e.message)); }, [shop]);
  const rows = useMemo(() => (d?.rows || []).filter((r) => !q || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.subject}`.toLowerCase().includes(q.toLowerCase())), [d, q]);
  if (nm) return <NmDetail shop={shop} nm={nm} onBack={() => setNm(null)} />;
  if (err) return <div className="err">{err}</div>;
  if (!d) return <div className="hint">Загрузка…</div>;
  const hasWas = d.was_day != null;
  return (
    <div className="board">
      <div className="acc-box">
        <b>Полки WB «Смотрите также»{d.day ? ` — снимок ${dt(d.day)}` : ""}</b>
        <div className="hint">Раз в сутки ночью снимаем полку «Смотрите также» (первые 100 мест) у наших товаров в продаже и у их ближайших конкурентов —
          как её видит гость в Москве. «В полках у» — у скольких снятых карточек наш товар стоит в полке (весь WB не обходим, только этот круг).
          Нажмите на товар — увидите, у кого именно он стоит и кто стоит у него, с изменениями за неделю.</div>
        {!d.day && <div className="hint">Первый снимок ещё собирается.</div>}
      </div>
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет" value={q} onChange={(e) => setQ(e.target.value)} />
        <input style={{ width: 160 }} placeholder="Любой артикул WB" value={any} onChange={(e) => setAny(e.target.value.replace(/\D/g, ""))}
          onKeyDown={(e) => { if (e.key === "Enter" && any) setNm(Number(any)); }} />
        <button disabled={!any} onClick={() => setNm(Number(any))}>Открыть</button>
      </div>
      <div className="board-wrap"><table className="board-t">
        <thead><tr><th></th><th>Артикул</th><th>Предмет</th><th title="У скольких снятых карточек товар стоит в полке «Смотрите также» (топ-100)">В полках у</th>
          <th>Лучшее место</th><th>Ср. место</th><th title="Сколько наших товаров в первых 20 местах полки этого товара">Наших в своей полке (топ-20)</th></tr></thead>
        <tbody>{rows.slice(0, 1500).map((r) => {
          const dlt = hasWas && r.in_n_was != null ? r.in_n - r.in_n_was : 0;
          return (
            <tr key={r.nm_id} style={{ cursor: "pointer" }} onClick={() => setNm(r.nm_id)}>
              <td>{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
              <td><b>{r.vendor_code || r.nm_id}</b><div className="hint">{r.nm_id} · {(r.title || "").slice(0, 50)}</div></td>
              <td>{r.subject}</td>
              <td className="n"><b>{r.in_n}</b>{dlt !== 0 && <span className={dlt > 0 ? "t-good" : "t-bad"}> {dlt > 0 ? "+" : ""}{dlt}</span>}</td>
              <td className="n">{r.best ?? "—"}</td>
              <td className="n">{r.avg ?? "—"}</td>
              <td className="n">{r.shelf_total != null ? r.own_top20 : "—"}</td>
            </tr>);
        })}</tbody>
      </table></div>
      {rows.length > 1500 && <div className="hint">Показаны первые 1500 из {rows.length} — уточните поиск.</div>}
    </div>
  );
}

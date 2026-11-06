import { useEffect, useMemo, useState } from "react";
import { api, http, type Article } from "./api";

type CRow = {
  nm_id: number; mine: boolean; name: string | null; image: string | null; url: string; note: string | null; who: string | null; in_wildbox: boolean;
  proceeds: number | null; orders: number | null; price: number | null; old_price: number | null; discount: number | null; quantity: number | null;
  rating: number | null; reviews: number | null; reviews_diff: number | null; lost_proceeds: number | null; in_stock_percent: number | null;
  wh_avg_position: number | null; count_keywords: number | null; sales_percent: number | null; promos: { promo_name: string; end_date: string }[] | null;
};
type Cmp = { nm_id: number; vendor_code: string | null; period: number; rows: CRow[]; error: string | null; notes: string[] | null; pending?: boolean;
  ours: { orders: number | null; proceeds: number | null; proceeds_spp: number | null }; can_edit: boolean };
type Sug = { id: number; name: string; image: string; proceeds: number; orders: number; price: number; rating: number; reviews: number; quantity: number; added: boolean };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 });
const n = (v: number | null | undefined) => (v == null ? "—" : nf.format(v));

export function Competitors({ shop }: { shop: number }) {
  const [arts, setArts] = useState<Article[]>([]);
  const [counts, setCounts] = useState<Record<number, number>>({});
  const [nm, setNm] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [period, setPeriod] = useState(30);
  const [cmp, setCmp] = useState<Cmp | null>(null);
  const [loading, setLoading] = useState(false);
  const [sug, setSug] = useState<Sug[] | null>(null);
  const [sugBusy, setSugBusy] = useState(false);
  const [add, setAdd] = useState("");
  const [err, setErr] = useState("");
  const loadCounts = () => http.get<{ nm_id: number; n: number }[]>(`/api/shops/${shop}/competitors`)
    .then((x) => setCounts(Object.fromEntries(x.map((r) => [r.nm_id, r.n])))).catch(() => undefined);
  useEffect(() => {
    let live = true;
    setNm(null); setCmp(null); setSug(null); setArts([]);
    api.articles(shop).then((a) => { if (!live) return; setArts(a); setNm((cur) => cur ?? a[0]?.nm_id ?? null); }).catch((e) => { if (live) setErr(e.message); });
    loadCounts();
    return () => { live = false; };
  }, [shop]);
  const load = () => {
    if (!nm) return;
    setLoading(true); setErr("");
    http.get<Cmp>(`/api/shops/${shop}/competitors/${nm}?period=${period}`).then(setCmp).catch((e) => setErr(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => { setSug(null); load(); }, [nm, period]);
  useEffect(() => {    // Wildbox отвечает по очереди (1 запрос в 10 с) — данные грузятся фоном, переспрашиваем сами
    if (!cmp?.pending) return;
    const id = setTimeout(load, 11000);
    return () => clearTimeout(id);
  }, [cmp]);   // eslint-disable-line react-hooks/exhaustive-deps
  const list = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return arts.filter((a) => !ql || `${a.vendor_code} ${a.nm_id} ${a.title}`.toLowerCase().includes(ql))
      .sort((a, b) => (counts[b.nm_id] || 0) - (counts[a.nm_id] || 0) || b.orders_30d - a.orders_30d);
  }, [arts, q, counts]);
  const addIds = (ids: number[]) => {
    if (!nm || !ids.length) return;
    http.post(`/api/shops/${shop}/competitors/${nm}`, { comp_nm_ids: ids }).then(() => { setAdd(""); load(); loadCounts();
      setSug((s) => s && s.map((x) => (ids.includes(x.id) ? { ...x, added: true } : x))); }).catch((e) => setErr(e.message));
  };
  const parsed = [...add.matchAll(/(?:catalog\/)?(\d{5,12})/g)].map((m) => Number(m[1]));
  const mine = cmp?.rows.find((r) => r.mine);
  const best = (f: keyof CRow) => Math.max(...(cmp?.rows || []).map((r) => Number(r[f] ?? -Infinity)));
  return (
    <div className="comp">
      <div className="comp-side">
        <input className="q" placeholder="Наш артикул…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="comp-list">
          {list.map((a) => (
            <button key={a.nm_id} className={"comp-art" + (a.nm_id === nm ? " on" : "")} onClick={() => setNm(a.nm_id)}>
              {a.photo && <img src={a.photo} className="thumb" alt="" loading="lazy" />}
              <span><b>{a.vendor_code}</b><span className="hint">{a.nm_id} · {a.orders_30d} зак./30 дн.</span></span>
              {counts[a.nm_id] ? <span className="badge">{counts[a.nm_id]}</span> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="comp-main">
        <div className="board-bar">
          <b>{cmp?.vendor_code || nm}</b>
          <select value={period} onChange={(e) => setPeriod(Number(e.target.value))}>
            {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>за {d} дней</option>)}
          </select>
          {cmp?.can_edit && <>
            <input className="q" placeholder="Добавить: артикулы или ссылки WB через пробел" value={add} onChange={(e) => setAdd(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addIds(parsed)} />
            <button disabled={!parsed.length} onClick={() => addIds(parsed)}>+ Добавить {parsed.length > 1 ? `(${parsed.length})` : ""}</button>
            <button disabled={sugBusy} onClick={() => { if (!nm) return; setSugBusy(true);
              http.get<{ rows: Sug[]; error: string | null }>(`/api/shops/${shop}/competitors/${nm}/suggest`)
                .then((r) => { setSug(r.rows); if (r.error) setErr(r.error); }).catch((e) => setErr(e.message)).finally(() => setSugBusy(false)); }}>
              {sugBusy ? "Ищу похожие…" : "🔍 Подобрать похожих"}</button>
          </>}
        </div>
        {err && <div className="err">{err}</div>}
        {cmp?.error && <div className="err">{cmp.error}</div>}
        {cmp?.pending && <div className="hint">Загружаю данные Wildbox (по очереди, 1 запрос в 10 с) — таблица обновится сама…</div>}
        {loading && <div className="hint">Загрузка из Wildbox (до 10–20 секунд)…</div>}
        {cmp && (
          <>
            <div className="board-wrap">
              <table className="board-t comp-t">
                <thead><tr>
                  <th></th><th>Карточка</th><th>Выручка, ₽</th><th>Заказы, шт</th><th>Цена, ₽</th><th>До скидки, ₽</th><th>Скидка</th><th>Остаток</th>
                  <th>Рейтинг</th><th>Отзывы</th><th>+ отзывов</th><th title="Оценка Wildbox: сколько недополучено из-за отсутствия остатка">Упущ. выручка</th>
                  <th>% дней в наличии</th><th title="Средняя позиция в поиске (меньше — выше)">Ср. позиция</th><th>Запросов</th><th>Акции</th><th></th>
                </tr></thead>
                <tbody>
                  {cmp.rows.map((r) => (
                    <tr key={r.nm_id} className={r.mine ? "mine" : ""}>
                      <td>{r.image && <img src={r.image} className="thumb big" alt="" loading="lazy" />}</td>
                      <td className="cname"><a href={r.url} target="_blank" rel="noreferrer">{r.nm_id}</a>{r.mine && <span className="badge">наш</span>}
                        <div>{(r.name || "").slice(0, 60)}</div>{!r.in_wildbox && <div className="hint">нет в базе Wildbox за период</div>}
                        {r.note && <div className="hint">{r.note}</div>}</td>
                      <td className={"n" + (r.proceeds != null && r.proceeds === best("proceeds") ? " up" : "")}>{n(r.proceeds)}</td>
                      <td className={"n" + (r.orders != null && r.orders === best("orders") ? " up" : "")}>{n(r.orders)}</td>
                      <td className="n">{n(r.price)}</td><td className="n">{r.old_price ? n(r.old_price) : "—"}</td>
                      <td className="n">{r.discount == null ? "—" : nf.format(r.discount) + " %"}</td><td className="n">{n(r.quantity)}</td>
                      <td className="n">{r.rating == null ? "—" : nf1.format(r.rating)}</td><td className="n">{n(r.reviews)}</td>
                      <td className="n">{r.reviews_diff == null ? "—" : "+" + nf.format(r.reviews_diff)}</td>
                      <td className="n">{n(r.lost_proceeds)}</td><td className="n">{r.in_stock_percent == null ? "—" : nf.format(r.in_stock_percent) + " %"}</td>
                      <td className="n">{n(r.wh_avg_position)}</td><td className="n">{n(r.count_keywords)}</td>
                      <td className="promos">{(r.promos || []).slice(-2).map((p, i) => <span key={i} className="chip">{p.promo_name}</span>)}</td>
                      <td>{!r.mine && cmp.can_edit && <button className="link" title="Убрать из конкурентов"
                        onClick={() => http.del(`/api/shops/${shop}/competitors/${nm}/${r.nm_id}`).then(() => { load(); loadCounts(); })}>✕</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {mine && (
              <div className="hint comp-ours">
                Наш артикул по данным API WB за те же {cmp.period} дн.: заказов <b>{n(cmp.ours.orders)}</b>, сумма заказов <b>{n(cmp.ours.proceeds)} ₽</b>
                {" "}(с учётом СПП {n(cmp.ours.proceeds_spp)} ₽). Цифры конкурентов — оценка Wildbox по витрине WB; сравнивайте их с оценкой Wildbox по нашему артикулу (строка «наш»).
              </div>
            )}
            {cmp.rows.length === 1 && !cmp.error && <div className="hint">Конкурентов пока нет — подберите похожих или добавьте по артикулу. Мониторинг их цены, остатка,
              рейтинга и продаж идёт раз в сутки (вкладка «МониторингКонкурентов» и утренняя сводка).</div>}
          </>
        )}
        {sug && (
          <div className="acc-box">
            <b>Похожие товары WB (выручка за 30 дней, Wildbox)</b>
            <table className="board-t comp-t"><tbody>
              {sug.map((s) => (
                <tr key={s.id}>
                  <td><img src={s.image} className="thumb big" alt="" loading="lazy" /></td>
                  <td className="cname"><a href={`https://www.wildberries.ru/catalog/${s.id}/detail.aspx`} target="_blank" rel="noreferrer">{s.id}</a><div>{(s.name || "").slice(0, 70)}</div></td>
                  <td className="n">{n(s.proceeds)} ₽</td><td className="n">{n(s.orders)} шт</td><td className="n">{n(s.price)} ₽</td>
                  <td className="n">★ {s.rating ?? "—"} · {n(s.reviews)}</td><td className="n">ост. {n(s.quantity)}</td>
                  <td>{s.added ? <span className="hint">добавлен</span> : <button onClick={() => addIds([s.id])}>+ В конкуренты</button>}</td>
                </tr>
              ))}
            </tbody></table>
            {!sug.length && <div className="hint">Похожих не нашлось.</div>}
          </div>
        )}
      </div>
    </div>
  );
}

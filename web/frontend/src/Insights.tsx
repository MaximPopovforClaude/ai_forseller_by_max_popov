import { useEffect, useState } from "react";
import { http } from "./api";
import { describeAiAccess, type AiAccess } from "./aiAccess";

type Art = { nm_id: number; vendor_code: string; title: string; orders: number; orders_avg7: number; change_pct: number; why: string[] };
type F = { day: string; data_note?: string; shop: { orders: number | null; orders_avg7: number | null; orders_sum: number | null; orders_sum_avg7: number | null; ads: number; ads_avg7: number };
  articles: Art[]; low_stock: { vendor_code: string; stock: number; orders_avg7: number; days: number }[];
  no_cost: { vendor_code: string; orders: number }[]; negative: { vendor_code: string; orders: number; margin_orders: number }[]; competitors: string[] };
type Res = AiAccess & { findings: F; ai_text: string | null; ai_model: string | null; text: string; plan: string; built_at?: string };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const ch = (a: number, b: number) => (b ? Math.round((a - b) / b * 100) : 0);

export function Insights({ shop, staff }: { shop: number; staff?: number | null }) {
  const y = new Date(new Date().getTime() + 3 * 3600e3 - 864e5).toISOString().slice(0, 10);
  const [day, setDay] = useState(y);
  const [r, setR] = useState<Res | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = (rebuild = false) => {
    setBusy(true); setErr("");
    http.get<Res>(`/api/shops/${shop}/insights?day=${day}${rebuild ? "&rebuild=true" : ""}${staff ? `&staff=${staff}` : ""}`).then(setR).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  useEffect(() => { setR(null); load(); }, [shop, day, staff]); // eslint-disable-line react-hooks/exhaustive-deps
  const f = r?.findings;
  const card = (t: string, a: number | null, b: number | null, unit = "") => {
    if (a == null || b == null) return <div><span>{t}</span><b>{a == null ? "—" : nf.format(a) + unit}</b><div className="hint">Недостаточно данных воронки для сравнения</div></div>;
    const c = ch(a, b);
    return <div className="ins-card"><div className="hint">{t}</div><b>{nf.format(a)}{unit}</b>
      <div className={c > 0 ? "up" : c < 0 ? "down" : ""}>{c > 0 ? "+" : ""}{c} % к среднему ({nf.format(b)}{unit})</div></div>;
  };
  return (
    <div className="ins">
      <div className="board-bar">
        <label>День <input type="date" value={day} max={y} onChange={(e) => setDay(e.target.value)} /></label>
        <button disabled={busy} onClick={() => load(true)}>{busy ? "Считаю…" : "↻ Пересчитать"}</button>
        <span className="hint">Цифры и причины считает код по данным маркетплейса. {r ? describeAiAccess(r).detail : "Проверяем доступ к нейросети…"}</span>
      </div>
      {err && <div className="err">{err}</div>}
      {f && <>
        {f.data_note && <details className="hint"><summary>Источники и полнота данных</summary>{f.data_note}</details>}
        <div className="ins-cards">
          {card("Заказы, шт", f.shop.orders, f.shop.orders_avg7)}
          {card("Сумма заказов", f.shop.orders_sum, f.shop.orders_sum_avg7, " ₽")}
          {card("Реклама", f.shop.ads, f.shop.ads_avg7, " ₽")}
        </div>
        <div className="acc-box ins-text">
          <b>{r!.ai_text ? "🤖 Разбор нейросети" : "🔎 Что важно"}</b>
          <pre>{r!.text}</pre>
        </div>
        {f.articles.length > 0 && <div className="acc-box">
          <b>Артикулы с заметным изменением заказов</b>
          <table className="board-t"><thead><tr><th>Артикул</th><th>Заказы</th><th>Среднее за 7 дн.</th><th>Изменение</th><th>Возможные причины</th></tr></thead>
            <tbody>{f.articles.map((a) => (
              <tr key={a.nm_id}><td><b>{a.vendor_code}</b><div className="hint">{a.title}</div></td><td className="n">{nf.format(a.orders)}</td>
                <td className="n">{a.orders_avg7}</td><td className={"n " + (a.change_pct > 0 ? "up" : "down")}>{a.change_pct > 0 ? "+" : ""}{a.change_pct} %</td>
                <td>{a.why.length ? a.why.map((w, i) => <span key={i} className="chip">{w}</span>) : <span className="hint">в данных причины нет</span>}</td></tr>
            ))}</tbody></table>
        </div>}
        <div className="ins-cols">
          {f.low_stock.length > 0 && <div className="acc-box"><b>Остаток меньше чем на 10 дней</b>
            <table className="board-t"><tbody>{f.low_stock.map((x) => (
              <tr key={x.vendor_code}><td>{x.vendor_code}</td><td className="n">{nf.format(x.stock)} шт</td>
                <td className={"n" + (x.days < 5 ? " down" : "")}>{x.stock ? `${x.days} дн` : "нет в наличии"}</td><td className="n hint">~{x.orders_avg7}/день</td></tr>))}</tbody></table></div>}
          {f.negative.length > 0 && <div className="acc-box"><b>В минус по марже (по заказам дня)</b>
            <table className="board-t"><tbody>{f.negative.map((x) => (
              <tr key={x.vendor_code}><td>{x.vendor_code}</td><td className="n">{x.orders} шт</td><td className="n down">{nf.format(x.margin_orders)} ₽</td></tr>))}</tbody></table></div>}
          {f.no_cost.length > 0 && <div className="acc-box"><b>Нет себестоимости</b> <span className="hint">(вкладка «Себестоимость»)</span>
            <div>{f.no_cost.map((x) => <span key={x.vendor_code} className="chip">{x.vendor_code} · {x.orders} зак.</span>)}</div></div>}
          {f.competitors.length > 0 && <div className="acc-box"><b>Конкуренты</b>
            <div>{f.competitors.map((x, i) => <span key={i} className="chip">{x}</span>)}</div></div>}
        </div>
      </>}
    </div>
  );
}

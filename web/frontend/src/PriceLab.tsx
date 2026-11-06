import { useEffect, useMemo, useState } from "react";
import { http } from "./api";

type Row = {
  nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; photo: string | null;
  online: number | null; calc_price: number | null; new_base: number | null; base_price: number | null; discount: number;
  cost: number | null; logistics: number | null; commission: number; other: number; cost_total: number | null;
  margin_online: number | null; margin_online_pct: number | null; margin_calc: number | null; margin_calc_pct: number | null;
  stock: number | null; draft: number | null; draft_by: string | null; draft_at: string | null;
  show_price?: number | null; show_spp?: number | null; show_at?: string | null;
};
type Lab = { other_pct: number; rows: Row[]; can_edit: boolean; mp?: string };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const m = (v: number | null) => (v == null ? "" : nf.format(v));
const p = (v: number | null) => (v == null ? "" : nf2.format(v * 100) + " %");

/** Формулы листа ОнлайнЦена: N = с/с + с/с×прочие; маржа = цена − N − логистика − цена×комиссия; новая цена до скидки = E/(100−скидка)×100. */
function calc(r: Row, other: number, price: number | null) {
  const N = r.cost == null ? null : r.cost + r.cost * other;
  const K = r.logistics ?? 0;
  const mr = (x: number | null) => (x == null || N == null ? null : x - N - K - x * r.commission);
  const E = price ?? r.online;
  const R = mr(E);
  const P = mr(r.online);
  return { N, P, O: P != null && r.online ? P / r.online : null, E, R, Q: R != null && E ? R / E : null,
    F: E != null && r.discount < 100 ? E / (100 - r.discount) * 100 : null };
}

export function PriceLab({ shop }: { shop: number }) {
  const [lab, setLab] = useState<Lab | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [onlyDraft, setOnlyDraft] = useState(false);
  const [typed, setTyped] = useState<Record<number, string>>({});
  const [other, setOther] = useState<string>("");
  const load = () => http.get<Lab>(`/api/shops/${shop}/manager/prices`).then((x) => { setLab(x); setOther(nf2.format(x.other_pct * 100)); setErr(""); })
    .catch((e) => setErr(e.message));
  useEffect(() => { setLab(null); setTyped({}); load(); }, [shop]);
  const otherV = Number(other.replace(",", ".")) / 100;
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (lab?.rows || []).filter((r) => (!ql || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.subject}`.toLowerCase().includes(ql))
      && (!onlyDraft || r.draft != null || typed[r.nm_id]));
  }, [lab, q, onlyDraft, typed]);
  if (err) return <div className="err">{err}</div>;
  if (!lab) return <div className="hint">Загрузка…</div>;
  const oz = lab.mp === "ozon";
  const priceOf = (r: Row) => {
    const t = typed[r.nm_id];
    if (t !== undefined) { const v = Number(t.replace(",", ".").replace(/\s/g, "")); return t.trim() && Number.isFinite(v) && v > 0 ? v : null; }
    return r.draft;
  };
  const save = (r: Row) => {
    const t = typed[r.nm_id];
    if (t === undefined) return;
    const v = priceOf(r);
    http.put(`/api/shops/${shop}/manager/prices/${r.nm_id}`, { price: v }).then(() => {
      setLab((l) => l && { ...l, rows: l.rows.map((x) => (x.nm_id === r.nm_id ? { ...x, draft: v } : x)) });
      setTyped((s) => { const n = { ...s }; delete n[r.nm_id]; return n; });
    }).catch((e) => setErr("Не сохранилось: " + e.message));
  };
  const saveOther = () => {
    if (!Number.isFinite(otherV) || otherV < 0 || otherV > 0.5) { setErr("Прочие расходы — от 0 до 50 %"); return; }
    http.put(`/api/shops/${shop}/manager/other_pct`, { value: otherV }).then(load).catch((e) => setErr(e.message));
  };
  const drafts = lab.rows.filter((r) => r.draft != null).length;
  const oth = Number.isFinite(otherV) ? otherV : lab.other_pct;
  return (
    <div className="board">
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет" value={q} onChange={(e) => setQ(e.target.value)} />
        <label title="Доля от себестоимости (как ячейка M1 листа): С/ст общая = с/с + с/с × прочие">Прочие расходы
          <input className="w60" value={other} disabled={!lab.can_edit} onChange={(e) => setOther(e.target.value)} onBlur={saveOther}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} /> %</label>
        <label><input type="checkbox" checked={onlyDraft} onChange={(e) => setOnlyDraft(e.target.checked)} /> только с новой ценой ({drafts})</label>
        {drafts > 0 && <a className="btn" href={`/api/shops/${shop}/manager/prices.csv`}>⬇ Новые цены (CSV для ЛК {oz ? "Ozon" : "WB"})</a>}
        <span className="hint">Впишите «Расчётную цену» (со скидкой продавца) — маржа пересчитается сразу. В {oz ? "Ozon" : "WB"} цена не меняется.</span>
      </div>
      <div className="board-wrap">
        <table className="board-t lab">
          <thead><tr>
            <th className="sx c0"></th><th className="sx c1">Артикул</th><th>{oz ? "Ост. FBO" : "Ост. WB"}</th>
            <th title="Текущая базовая цена (до скидки)">Цена до скидки</th><th>Скидка %</th>
            <th title={oz ? "Цена продавца со скидкой сейчас (API цен Ozon)" : "Цена со скидкой продавца сейчас (API цен WB)"}>Онлайн цена</th>
            {!oz && <><th title="Цена, которую видит покупатель на витрине WB (Москва, без личных скидок и кошелька). Проверяем раз в 30 минут с сервера в РФ">Цена на витрине</th>
              <th title="СПП = 1 − цена на витрине / онлайн цена">СПП %</th></>}
            <th className="hl" title="Цена со скидкой, которую хотите поставить">Расчётная цена</th>
            <th title={`Что поставить в ${oz ? "Ozon" : "WB"} «до скидки» при текущей скидке`}>Новая цена до скидки</th>
            <th>С/ст закупа</th><th title={oz ? "Логистика + доставка + эквайринг Ozon на 1 проданную шт. (начисления за 28 дней; нет продаж — тарифы Ozon)" : "Логистика к клиенту за последнюю неделю, на 1 доставку"}>Логистика</th>
            <th title={oz ? "Комиссия Ozon: факт за 28 дней (комиссия / начислено за продажу); нет продаж — тариф FBO" : "Комиссия WB по предмету (оферта)"}>Комиссия</th><th>С/ст общая</th>
            <th>Маржа ₽ (онлайн)</th><th>Маржа % (онлайн)</th><th className="hl">Маржа ₽ (расчёт)</th><th className="hl">Маржа % (расчёт)</th><th>Δ маржи ₽</th>
          </tr></thead>
          <tbody>
            {rows.map((r) => {
              const price = priceOf(r);
              const x = calc(r, oth, price);
              const changed = price != null && price !== r.online;
              const d = x.R != null && x.P != null && changed ? x.R - x.P : null;
              return (
                <tr key={r.nm_id} className={changed ? "picked" : ""}>
                  <td className="sx c0">{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
                  <td className="sx c1" title={r.title || ""}><b>{r.vendor_code}</b><div className="hint">{r.nm_id} · {(r.title || "").slice(0, 30)}</div></td>
                  <td className="n">{m(r.stock)}</td><td className="n">{m(r.base_price)}</td><td className="n">{r.discount ? nf2.format(r.discount) : ""}</td>
                  <td className="n">{m(r.online)}</td>
                  {!oz && <><td className="n" title={r.show_at ? "Проверено " + new Date(r.show_at).toLocaleString("ru-RU") : "Нет данных витрины (нет остатка или ещё не проверяли)"}>{m(r.show_price ?? null)}</td>
                    <td className="n">{r.show_spp == null ? "" : nf2.format(r.show_spp) + " %"}</td></>}
                  <td className="n hl">
                    <input className="price-in" disabled={!lab.can_edit} placeholder={r.online == null ? "" : nf.format(r.online)}
                      value={typed[r.nm_id] ?? (r.draft == null ? "" : String(r.draft))}
                      onChange={(e) => setTyped((s) => ({ ...s, [r.nm_id]: e.target.value }))} onBlur={() => save(r)}
                      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                        if (e.key === "Escape") setTyped((s) => { const n = { ...s }; delete n[r.nm_id]; return n; }); }}
                      title={r.draft_by ? `Задал(а): ${r.draft_by}, ${new Date(r.draft_at!).toLocaleString("ru-RU")}` : "Пусто — считаем по онлайн-цене"} />
                  </td>
                  <td className="n">{changed ? m(x.F) : ""}</td>
                  <td className="n">{r.cost == null ? <span className="warn">нет</span> : m(r.cost)}</td>
                  <td className="n">{r.logistics == null ? "" : nf2.format(r.logistics)}</td><td className="n">{p(r.commission)}</td>
                  <td className="n">{m(x.N)}</td>
                  <td className={"n" + (x.P != null && x.P < 0 ? " down" : "")}>{m(x.P)}</td><td className="n">{p(x.O)}</td>
                  <td className={"n hl" + (x.R != null && x.R < 0 ? " down" : "")}>{m(x.R)}</td><td className="n hl">{p(x.Q)}</td>
                  <td className={"n" + (d == null ? "" : d > 0 ? " up" : d < 0 ? " down" : "")}>{d == null ? "" : (d > 0 ? "+" : "") + nf.format(d)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

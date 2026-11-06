import { useEffect, useMemo, useState } from "react";
import { http } from "./api";

type Row = { nm_id: number; vendor_code: string | null; title: string | null; subject: string | null; brand: string | null; photo: string | null;
  seller_price: number | null; shown: number | null; spp: number | null; checked_at: string | null;
  mrc: number | null; note: string | null; updated_at: string | null; who: string | null };
type Data = { rows: Row[]; can_edit: boolean };
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const rub = (v: number | null | undefined) => (v == null ? "" : nf.format(v) + " ₽");
const num = (s: string) => Number(s.replace(/\s/g, "").replace(",", "."));

/** Контроль МРЦ, первый шаг : задать МРЦ по товарам. Блок ничего не меняет в кабинете — МРЦ видна в уведомлениях о цене. */
export function Mrc({ shop }: { shop: number }) {
  const [d, setD] = useState<Data | null>(null);
  const [q, setQ] = useState("");
  const [only, setOnly] = useState(false);
  const [pend, setPend] = useState<Record<number, string>>({});      // артикул → новая МРЦ (пусто — убрать), ждёт «Сохранить»
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState(""), [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);
  const load = () => http.get<Data>(`/api/shops/${shop}/mrc`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); setPend({}); load(); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => (d?.rows || []).filter((r) => (!only || r.mrc != null || r.nm_id in pend)
    && (!q || `${r.vendor_code} ${r.nm_id} ${r.title} ${r.subject} ${r.brand}`.toLowerCase().includes(q.toLowerCase()))), [d, q, only, pend]);
  if (err && !d) return <div className="err">{err}</div>;
  if (!d) return <div className="hint">Загрузка…</div>;
  const nSet = d.rows.filter((r) => r.mrc != null).length;
  const send = (items: { nm_id: number; mrc: number | null }[]) => {
    setSaving(true); setErr(""); setMsg("");
    http.put<{ message: string }>(`/api/shops/${shop}/mrc`, { items })
      .then((r) => { setMsg(r.message); setPend({}); setPaste(""); load(); }).catch((e) => setErr(e.message)).finally(() => setSaving(false));
  };
  const save = () => {
    const items = Object.entries(pend).map(([nm, v]) => ({ nm_id: Number(nm), mrc: v.trim() ? num(v) : null }));
    const bad = items.find((x) => x.mrc != null && !(x.mrc > 0));
    if (bad) { setErr(`МРЦ для ${bad.nm_id} — не число`); return; }
    send(items);
  };
  // список «артикул МРЦ» построчно: артикул WB или артикул продавца, разделитель — таб, ; или пробел (копия из Excel)
  const fromPaste = () => {
    const byVc = new Map(d.rows.map((r) => [String(r.vendor_code || "").toLowerCase(), r.nm_id]));
    const own = new Set(d.rows.map((r) => r.nm_id));
    const items: { nm_id: number; mrc: number }[] = [], miss: string[] = [];
    for (const ln of paste.split(/\r?\n/)) {
      const p = ln.trim().split(/[\t;]+|\s{2,}|\s(?=[\d\s.,]+(?:₽|руб)?\s*$)/).map((x) => x.trim()).filter(Boolean);
      if (p.length < 2) { if (ln.trim()) miss.push(ln.trim()); continue; }
      const key = p[0], v = num(p[p.length - 1].replace(/₽|руб\.?/gi, ""));
      const nm = own.has(Number(key)) ? Number(key) : byVc.get(key.toLowerCase());
      if (!nm || !(v > 0)) { miss.push(ln.trim()); continue; }
      items.push({ nm_id: nm, mrc: v });
    }
    if (miss.length) { setErr(`Не разобрал ${miss.length} строк: ${miss.slice(0, 5).join(" | ")}${miss.length > 5 ? " …" : ""}`); if (!items.length) return; }
    if (items.length) send(items);
  };
  const nPend = Object.keys(pend).length;
  return (
    <div className="board">
      <div className="acc-box">
        <b>Контроль МРЦ: задано у {nSet} товаров</b>
        <div className="hint">МРЦ — минимальная цена на витрине (с СПП), ниже которой товар продаваться не должен. Пока блок ничего не меняет в кабинете:
          МРЦ и категория товара видны в уведомлениях гномика об изменении цены и СПП, а если цена ниже МРЦ — там будет ⚠️.</div>
        {!d.can_edit && <div className="hint">Задавать МРЦ может редактор, админ или владелец кабинета.</div>}
        {msg && <div className="ok">{msg}</div>}{err && <div className="err">{err}</div>}
      </div>
      {d.can_edit && <details className="acc-box">
        <summary><b>Задать списком</b> — вставьте из Excel два столбца: артикул (WB или продавца) и МРЦ</summary>
        <textarea rows={6} style={{ width: "100%", marginTop: 6 }} placeholder={"123456789\t4990\nEXAMPLE-SKU\t1290"} value={paste} onChange={(e) => setPaste(e.target.value)} />
        <button className="pri" disabled={saving || !paste.trim()} onClick={fromPaste}>Загрузить МРЦ</button>
      </details>}
      {nPend > 0 && <div className="excl-save">
        <b>Не сохранено: {nPend}</b>
        <button className="pri" disabled={saving} onClick={save}>{saving ? "Сохраняю…" : "💾 Сохранить"}</button>
        <button disabled={saving} onClick={() => setPend({})}>Отменить</button>
      </div>}
      <div className="board-bar">
        <input className="q" placeholder="Поиск: артикул, название, предмет, бренд" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="chk"><input type="checkbox" checked={only} onChange={(e) => setOnly(e.target.checked)} /> только с МРЦ</label>
      </div>
      <div className="board-wrap"><table className="board-t">
        <thead><tr><th></th><th>Артикул</th><th>Категория</th><th title="Наша цена со скидкой продавца (API цен WB)">Наша цена</th>
          <th title="Цена с СПП на витрине WB (Москва)">Витрина</th><th>МРЦ, ₽</th><th>Кто задал</th></tr></thead>
        <tbody>{rows.slice(0, 1500).map((r) => {
          const low = r.mrc != null && r.shown != null && r.shown < r.mrc;
          return (
            <tr key={r.nm_id}>
              <td>{r.photo && <img src={r.photo} className="thumb" alt="" loading="lazy" />}</td>
              <td><b>{r.vendor_code || r.nm_id}</b><div className="hint">{r.nm_id} · {(r.title || "").slice(0, 50)}</div></td>
              <td>{r.subject}</td>
              <td className="n">{rub(r.seller_price)}</td>
              <td className={"n" + (low ? " t-bad" : "")} title={r.checked_at ? `проверено ${new Date(r.checked_at).toLocaleString("ru-RU")}` : ""}>
                {rub(r.shown)}{r.spp != null && <div className="hint">СПП {r.spp} %</div>}{low && <div className="hint">⚠️ ниже МРЦ</div>}</td>
              <td>{d.can_edit
                ? <input style={{ width: 90 }} inputMode="decimal" value={r.nm_id in pend ? pend[r.nm_id] : r.mrc ?? ""} placeholder="—"
                    onChange={(e) => { const v = e.target.value; setPend((p) => {
                      const n = { ...p }; if (v === String(r.mrc ?? "")) delete n[r.nm_id]; else n[r.nm_id] = v; return n; }); }} />
                : rub(r.mrc)}</td>
              <td className="hint">{r.who}{r.updated_at && <div>{new Date(r.updated_at).toLocaleDateString("ru-RU")}</div>}</td>
            </tr>);
        })}</tbody>
      </table></div>
      {rows.length > 1500 && <div className="hint">Показаны первые 1500 из {rows.length} — уточните поиск.</div>}
    </div>
  );
}

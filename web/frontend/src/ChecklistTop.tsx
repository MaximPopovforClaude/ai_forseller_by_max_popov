import { useEffect, useState } from "react";
import { http } from "./api";

/** Над Чек-листом: «Опасности» (правила за крайние 3 дня → что делать) и пороги MAX артикула (видео 10X, обновление 1). */
export type Danger = { indicator: string; problem: string; hypothesis: string };
export type MaxEditor = { nm_id: number; fields: { key: string; title: string; value: number | null; auto?: number | null }[] };

export function ChecklistTop({ shop, dangers, editor, onSaved }: { shop: number; dangers: Danger[]; editor?: MaxEditor; onSaved: () => void }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { setVals(Object.fromEntries((editor?.fields || []).map((f) => [f.key, f.value == null ? "" : String(f.value)]))); }, [editor]);
  const save = () => {
    if (!editor) return;
    const values = Object.fromEntries(editor.fields.map((f) => [f.key, vals[f.key]?.trim() ? Number(vals[f.key].replace(",", ".")) : null]));
    http.put(`/api/shops/${shop}/checklist_max/${editor.nm_id}`, { values }).then(() => { setMsg("Сохранено"); setTimeout(() => setMsg(""), 2000); onSaved(); })
      .catch((e) => setErr(e.message));
  };
  return (
    <div className="ck-top">
      <div className={"acc-box ck-danger" + (dangers.length ? " on" : "")}>
        <b>⚠️ Опасности ({dangers.length})</b> <span className="hint">— по крайним 3 полным дням</span>
        {!dangers.length && <div className="hint">Всё в норме. MAX цены клика, ДРР, корзины и заказа — «в ноль» из юнит-экономики (справа), можно задать свои.</div>}
        {dangers.length > 0 && <table className="ck-dz"><thead><tr><th>Показатель</th><th>Проблема</th><th>Гипотеза — что сделать</th></tr></thead>
          <tbody>{dangers.map((d, i) => <tr key={i}><td><b>{d.indicator}</b></td><td>{d.problem}</td><td>{d.hypothesis}</td></tr>)}</tbody></table>}
      </div>
      {editor && <div className="acc-box ck-max">
        <b>MAX по артикулу</b>
        {editor.fields.map((f) => <div key={f.key} className="acc-row"><span>{f.title}</span>
          <input inputMode="decimal" value={vals[f.key] ?? ""} placeholder={f.auto != null ? `авто ${String(f.auto).replace(".", ",")}` : "не задан"}
            title="Пусто — MAX «в ноль» считается сам из юнит-экономики и конверсий за период; впишите свой, если нужен другой"
            onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} /></div>)}
        <div className="acc-row"><span />{msg ? <span className="ok">{msg}</span> : <button onClick={save}>Сохранить</button>}</div>
        {err && <div className="err">{err}</div>}
      </div>}
    </div>
  );
}

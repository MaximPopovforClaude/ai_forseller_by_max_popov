import { useEffect, useState } from "react";
import { http } from "./api";

/** SEO за 5 минут (видео 10X №19): слова запросов артикула, есть ли в карточке, отметки «добавить» / «убрать». */
type W = { word: string; freq: number; queries: number; clicks: number; in_card: boolean; mark: "add" | "remove" | null };
type Data = { rows: W[]; source: string | null; added: string[]; removed: string[]; has_jam: boolean; can_edit: boolean };
const nf = new Intl.NumberFormat("ru-RU");

export function Seo({ shop, nm }: { shop: number; nm: string }) {
  const id = Number(nm.split(",")[0]?.trim() || 0);
  const [d, setD] = useState<Data | null>(null);
  const [flt, setFlt] = useState<"all" | "missing" | "present">("all");
  const [err, setErr] = useState("");
  const load = () => id && http.get<Data>(`/api/shops/${shop}/seo/${id}`).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); }, [shop, id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!id) return <div className="hint">Выберите один артикул вверху страницы — SEO разбирается по одному товару.</div>;
  if (!d) return <div className="hint">{err || "Загрузка…"}</div>;
  const mark = (w: W, m: "add" | "remove") => {
    const next = w.mark === m ? null : m;
    setD({ ...d, rows: d.rows.map((x) => (x.word === w.word ? { ...x, mark: next } : x)),
      added: next === "add" ? [...d.added, w.word] : d.added.filter((x) => x !== w.word),
      removed: next === "remove" ? [...d.removed, w.word] : d.removed.filter((x) => x !== w.word) });
    http.put(`/api/shops/${shop}/seo/${id}`, { word: w.word, mark: next }).catch((e) => setErr(e.message));
  };
  const rows = d.rows.filter((w) => flt === "all" || (flt === "missing" ? !w.in_card : w.in_card));
  return (
    <div className="seo">
      {err && <div className="err">{err}</div>}
      <div className="hint">{d.source || "Нет запросов: включите Джем (вкладка «Джем») или рекламу в поиске."}
        {!d.has_jam && " Откройте этот артикул во вкладке «Джем» — после загрузки здесь будет частота запросов."}</div>
      <div className="acc-box"><div><b>Добавлено:</b> {d.added.join(", ") || "—"}</div><div><b>Убрано:</b> {d.removed.join(", ") || "—"}</div>
        <div className="hint">Список для согласования. Править карточку — во вкладке «Карточки» (черновик → «Применить»).</div></div>
      <div className="rnp-bar">
        <button className={flt === "all" ? "on" : ""} onClick={() => setFlt("all")}>Все слова ({d.rows.length})</button>
        <button className={flt === "missing" ? "on" : ""} onClick={() => setFlt("missing")}>Нет в карточке ({d.rows.filter((w) => !w.in_card).length})</button>
        <button className={flt === "present" ? "on" : ""} onClick={() => setFlt("present")}>Есть в карточке</button>
      </div>
      <table className="rnp-t">
        <thead><tr><th>Слово</th><th>Вхождения</th><th>Запросов</th><th>Переходов</th><th>В карточке</th><th>Отметка</th></tr></thead>
        <tbody>{rows.map((w) => <tr key={w.word} className={w.mark === "add" ? "z-good" : w.mark === "remove" ? "z-bad" : ""}>
          <td><b>{w.word}</b></td><td>{nf.format(w.freq)}</td><td>{w.queries}</td><td>{nf.format(w.clicks)}</td>
          <td className={w.in_card ? "t-good" : "t-bad"}>{w.in_card ? "есть" : "—"}</td>
          <td>{d.can_edit && <><button className={"link" + (w.mark === "add" ? " on" : "")} onClick={() => mark(w, "add")}>+ добавить</button>{" "}
            <button className={"link" + (w.mark === "remove" ? " on" : "")} onClick={() => mark(w, "remove")}>− убрать</button></>}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

import { useEffect, useState } from "react";
import { http } from "./api";

/** Лента новостей магазина: изменения цены, СПП / соинвеста и другие события — новые сверху (те же — уведомлением в бот). */
type Ev = { id: number; kind: string; nm_id: number | null; at: string; vc: string | null; title: string | null; text: string };
type Feed = { rows: Ev[]; kinds: { key: string; title: string }[]; more: boolean };

const ICON: Record<string, string> = { price: "🏷", spp: "💸" };

export function News({ shop }: { shop: number }) {
  const [kind, setKind] = useState("");
  const [rows, setRows] = useState<Ev[]>([]);
  const [kinds, setKinds] = useState<Feed["kinds"]>([]);
  const [more, setMore] = useState(false);
  const [err, setErr] = useState("");
  const load = (before?: number) =>
    http.get<Feed>(`/api/shops/${shop}/news?kind=${kind}${before ? `&before=${before}` : ""}`)
      .then((d) => { setKinds(d.kinds); setMore(d.more); setRows((r) => (before ? [...r, ...d.rows] : d.rows)); })
      .catch((e) => setErr(e.message));
  useEffect(() => { setRows([]); load(); }, [shop, kind]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="news">
      <div className="rnp-bar">
        <button className={kind === "" ? "on" : ""} onClick={() => setKind("")}>Все</button>
        {kinds.map((k) => <button key={k.key} className={kind === k.key ? "on" : ""} onClick={() => setKind(k.key)}>{ICON[k.key] || "•"} {k.title}</button>)}
        <span className="hint">Уведомления о событиях — в боте «Стометрик» (/settings) или в «Настройках аккаунта».</span>
      </div>
      {err && <div className="err">{err}</div>}
      {!rows.length && !err && <div className="hint">Событий пока нет. Лента ведётся с 20.10: изменения цены — с ближайших сборов цен;
        СПП / соинвест (цена покупателя) — после подключения сбора цен с витрины.</div>}
      <table className="news-t">
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="hint" style={{ whiteSpace: "nowrap" }}>{new Date(r.at).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</td>
              <td>{ICON[r.kind] || "•"}</td>
              <td>{r.text}{r.title && <div className="hint">{r.title}</div>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {more && <button onClick={() => load(rows[rows.length - 1]?.id)}>Показать ещё</button>}
    </div>
  );
}

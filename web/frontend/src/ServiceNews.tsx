import { useEffect, useState } from "react";
import { http } from "./api";

/** Новости сервиса: что изменилось и улучшилось . Открыл страницу — всё прочитано. */
type N = { id: number; created_at: string; title: string; body: string; tabs: string[] };
type Data = { rows: N[]; seen: number; can_edit: boolean };

export function ServiceNews({ tabTitle, onTab, onSeen }: { tabTitle: (k: string) => string | null; onTab: (k: string) => void; onSeen: () => void }) {
  const [d, setD] = useState<Data | null>(null);
  const [f, setF] = useState({ title: "", body: "", tabs: "" });
  const [err, setErr] = useState("");
  const load = () => http.get<Data>("/api/service_news").then((x) => { setD(x); http.post("/api/service_news/seen").then(onSeen).catch(() => {}); })
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!d) return <div className="hint">{err || "Загрузка…"}</div>;
  const add = () => http.post("/api/service_news", { title: f.title, body: f.body, tabs: f.tabs.split(/[\s,]+/).filter(Boolean) })
    .then(() => { setF({ title: "", body: "", tabs: "" }); load(); }).catch((e) => setErr(e.message));
  return (
    <div className="svc-news">
      <h2>📣 Новости сервиса</h2>
      <div className="hint">Что нового и что улучшили в сервисе и вкладках.</div>
      {err && <div className="err">{err}</div>}
      {d.can_edit && <div className="acc-box ext-form">
        <input placeholder="Заголовок" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} style={{ minWidth: 320 }} />
        <textarea placeholder="Текст (каждый пункт с новой строки)" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} rows={4} style={{ width: "100%" }} />
        <input placeholder="Ключи вкладок через запятую (необязательно)" value={f.tabs} onChange={(e) => setF({ ...f, tabs: e.target.value })} style={{ minWidth: 320 }} />
        <button disabled={!f.title.trim()} onClick={add}>Опубликовать</button>
      </div>}
      {d.rows.map((n) => <div key={n.id} className={"acc-box svc-news-item" + (n.id > d.seen ? " new" : "")}>
        <div className="hint">{new Date(n.created_at).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}
          {n.id > d.seen && <b className="badge-new"> новое</b>}</div>
        <h3>{n.title}</h3>
        <div style={{ whiteSpace: "pre-line" }}>{n.body}</div>
        {n.tabs.length > 0 && <div className="svc-news-tabs">{n.tabs.map((k) => tabTitle(k) &&
          <button key={k} className="link" onClick={() => onTab(k)}>→ {tabTitle(k)}</button>)}</div>}
        {d.can_edit && <button className="link" onClick={() => { if (confirm("Удалить новость?")) http.del(`/api/service_news/${n.id}`).then(load); }}>удалить</button>}
      </div>)}
      {!d.rows.length && <div className="hint">Пока новостей нет.</div>}
    </div>
  );
}

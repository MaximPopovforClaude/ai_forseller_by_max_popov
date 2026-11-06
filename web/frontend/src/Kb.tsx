import { useEffect, useMemo, useState } from "react";
import { http } from "./api";

type Sub = { id: number; title: string; n: number };
type Sec = Sub & { subs: Sub[]; total: number };
type Item = { id: number; workspace_id: number; shop_id: number | null; section_id: number | null; kind: "link" | "file" | "photo" | "note"; title: string;
  url: string | null; body: string | null; file_name: string | null; mime: string | null; size: number | null; description: string | null; source: string;
  created_at: string; author: string | null; section: string | null; parent: string | null; shop: string | null; can_change: boolean };
type Res = { tree: Sec[]; items: Item[]; can_add: boolean; can_admin: boolean; shops: { id: number; title: string; can_add: boolean }[] };

const ICON = { link: "🔗", file: "📄", photo: "🖼", note: "📝" };
const dt = (s: string) => new Date(s).toLocaleDateString("ru-RU");
const kbSize = (n: number | null) => (!n ? "" : n > 1048576 ? `${(n / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(n / 1024))} КБ`);
const fileUrl = (id: number, dl = false) => `/api/kb/items/${id}/file${dl ? "?dl=1" : ""}`;

/** База знаний пространства: разделы → подразделы, материалы (ссылка, файл, фото, заметка) с описанием; поиск. */
export function Kb({ wsId }: { wsId: number }) {
  const [r, setR] = useState<Res | null>(null);
  const [sec, setSec] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");
  const [edit, setEdit] = useState<Partial<Item> | null>(null);       // форма материала (новый — без id)
  const [open, setOpen] = useState<Item | null>(null);               // заметка целиком / фото крупно
  const load = () => http.get<Res>(`/api/workspaces/${wsId}/kb?${sec != null ? `section=${sec}&` : ""}q=${encodeURIComponent(q)}`)
    .then((x) => { setR(x); setErr(""); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [wsId, sec]);  // eslint-disable-line react-hooks/exhaustive-deps
  const flat = useMemo(() => (r?.tree || []).filter((s) => s.id).flatMap((s) => [{ id: s.id, title: s.title }, ...s.subs.map((x) => ({ id: x.id, title: `${s.title} → ${x.title}` }))]), [r]);
  const cur = r?.tree.find((s) => s.id === sec) || r?.tree.flatMap((s) => s.subs).find((x) => x.id === sec);
  const curTop = r?.tree.find((s) => s.id === sec);
  const addSection = (parent: number | null) => {
    const t = window.prompt(parent ? `Новый подраздел в «${curTop?.title}»` : "Новый раздел", "");
    if (!t?.trim()) return;
    http.post<{ id: number }>(`/api/workspaces/${wsId}/kb/sections`, { title: t, parent_id: parent }).then((x) => { setSec(x.id); load(); }).catch((e) => setErr(e.message));
  };
  if (!r) return <div className="kb">{err ? <div className="err">{err}</div> : <div className="hint">Загрузка…</div>}</div>;
  return (
    <div className="kb">
      <div className="rv-head"><h2>📚 База знаний</h2>
        {r.can_add && <button className="pri" onClick={() => setEdit({ kind: "link", section_id: sec && sec > 0 ? sec : null })}>+ Материал</button>}
        {r.can_add && <button onClick={() => addSection(null)}>+ Раздел</button>}
        {r.can_add && curTop && curTop.id > 0 && <button onClick={() => addSection(curTop.id)}>+ Подраздел в «{curTop.title}»</button>}
      </div>
      <div className="hint">Регламенты, документы, ссылки, фото, классные карточки конкурентов — для всей команды. По умолчанию материал видят все в рабочем
        пространстве; можно сделать «только для магазина». Добавлять можно и через гномика 🧙: киньте ссылку или файл и напишите, что это и «в базу знаний» —
        он сам опишет и разложит по разделам.{!r.can_add && " Добавлять материалы может редактор и выше."}</div>
      {err && <div className="err">{err}</div>}
      <div className="kb-cols">
        <div className="kb-tree">
          <button className={"kb-sec" + (sec == null ? " on" : "")} onClick={() => setSec(null)}>Все материалы</button>
          {r.tree.map((s) => <div key={s.id}>
            <button className={"kb-sec" + (sec === s.id ? " on" : "")} onClick={() => setSec(s.id)}>{s.title} <span className="hint">{s.total}</span></button>
            {s.subs.map((x) => <button key={x.id} className={"kb-sec sub" + (sec === x.id ? " on" : "")} onClick={() => setSec(x.id)}>{x.title} <span className="hint">{x.n}</span></button>)}
          </div>)}
          {!r.tree.length && <div className="hint">Разделов пока нет</div>}
          {cur && cur.id > 0 && r.can_add && <div className="kb-sec-act">
            <button className="link" onClick={() => { const t = window.prompt("Новое название", cur.title); if (t?.trim()) http.put(`/api/kb/sections/${cur.id}`, { title: t }).then(load).catch((e) => setErr(e.message)); }}>переименовать</button>
            {r.can_admin && <button className="link" onClick={() => { if (window.confirm(`Удалить раздел «${cur.title}»? (только пустой)`)) http.del(`/api/kb/sections/${cur.id}`).then(() => { setSec(null); load(); }).catch((e) => setErr(e.message)); }}>удалить</button>}
          </div>}
        </div>
        <div className="kb-main">
          <div className="rv-filters"><input placeholder="Поиск: название, описание, текст документа, раздел…" value={q} onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") load(); }} /><button onClick={load}>Найти</button></div>
          {!r.items.length ? <div className="hint">{q ? "Ничего не нашлось." : "Здесь пока пусто."}</div> : r.items.map((it) => (
            <div key={it.id} className="kb-item">
              {it.kind === "photo" && <img className="kb-thumb" src={fileUrl(it.id)} alt="" onClick={() => setOpen(it)} />}
              <div className="kb-body">
                <div className="kb-t">{ICON[it.kind]}{" "}
                  {it.kind === "link" && it.url ? <a href={it.url} target="_blank" rel="noreferrer">{it.title}</a>
                    : it.kind === "note" ? <button className="link" onClick={() => setOpen(it)}>{it.title}</button>
                    : it.kind === "photo" ? <button className="link" onClick={() => setOpen(it)}>{it.title}</button>
                    : <a href={fileUrl(it.id)} target="_blank" rel="noreferrer">{it.title}</a>}
                  {it.file_name && <span className="hint"> · {it.file_name} {kbSize(it.size)} · <a href={fileUrl(it.id, true)}>скачать</a></span>}
                </div>
                {it.description && <div>{it.description}</div>}
                {it.kind === "note" && it.body && <div className="hint kb-note">{it.body.slice(0, 220)}{it.body.length > 220 ? "…" : ""}</div>}
                <div className="hint">{[it.parent, it.section].filter(Boolean).join(" → ") || "без раздела"}{it.shop ? ` · 🔒 только ${it.shop}` : ""}
                  {" · "}{it.author || "—"}{it.source === "assistant" ? " через гномика" : ""}, {dt(it.created_at)}
                  {it.can_change && <> · <button className="link" onClick={() => setEdit(it)}>изменить</button>
                    {" "}<button className="link" onClick={() => { if (window.confirm(`Удалить «${it.title}»?`)) http.del(`/api/kb/items/${it.id}`).then(load).catch((e) => setErr(e.message)); }}>удалить</button></>}
                </div>
              </div>
            </div>))}
        </div>
      </div>
      {edit && <ItemForm wsId={wsId} it={edit} sections={flat} shops={r.shops} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
      {open && <div className="modal-shade" onClick={() => setOpen(null)}>
        <div className="modal kb-open" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h"><b>{open.title}</b><button className="link" onClick={() => setOpen(null)}>✕</button></div>
          {open.description && <div className="hint">{open.description}</div>}
          {open.kind === "photo" ? <img src={fileUrl(open.id)} alt="" className="kb-big" /> : <div className="kb-note-full">{open.body}</div>}
        </div>
      </div>}
    </div>
  );
}

function ItemForm({ wsId, it, sections, shops, onClose, onSaved }: { wsId: number; it: Partial<Item>; sections: { id: number; title: string }[];
  shops: { id: number; title: string; can_add: boolean }[]; onClose: () => void; onSaved: () => void }) {
  const isNew = !it.id;
  const [kind, setKind] = useState<"link" | "file" | "note">(it.kind === "photo" || it.kind === "file" ? "file" : (it.kind as "link" | "note") || "link");
  const [title, setTitle] = useState(it.title || "");
  const [url, setUrl] = useState(it.url || "");
  const [body, setBody] = useState(it.body || "");
  const [desc, setDesc] = useState(it.description || "");
  const [secId, setSecId] = useState<number | null>(it.section_id ?? null);
  const [shopId, setShopId] = useState<number | null>(it.shop_id ?? null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = () => {
    setBusy(true); setErr("");
    let p: Promise<unknown>;
    if (!isNew) p = http.put(`/api/kb/items/${it.id}`, { title, url: kind === "link" ? url : undefined, body: kind === "note" ? body : undefined, description: desc, section_id: secId, shop_id: shopId });
    else if (kind === "file") {
      if (!file) { setErr("Выберите файл"); setBusy(false); return; }
      const q = new URLSearchParams({ name: file.name, title, description: desc });
      if (secId) q.set("section_id", String(secId));
      if (shopId) q.set("shop_id", String(shopId));
      p = fetch(`/api/workspaces/${wsId}/kb/upload?${q}`, { method: "POST", credentials: "same-origin", body: file })
        .then(async (x) => { if (!x.ok) throw new Error((await x.json().catch(() => ({}))).detail || x.statusText); });
    } else p = http.post(`/api/workspaces/${wsId}/kb/items`, { kind, title, url, body, description: desc, section_id: secId, shop_id: shopId });
    p.then(onSaved).catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="modal-shade" onClick={onClose}>
      <div className="modal kb-form" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h"><b>{isNew ? "Новый материал" : "Изменить материал"}</b></div>
        {isNew && <div className="rv-filters">{([["link", "🔗 Ссылка"], ["file", "📄 Файл или фото"], ["note", "📝 Заметка / регламент"]] as const).map(([k, t]) =>
          <button key={k} className={"chip" + (kind === k ? " on" : "")} onClick={() => setKind(k)}>{t}</button>)}</div>}
        {kind === "link" && <input placeholder="Ссылка: https://…" value={url} onChange={(e) => setUrl(e.target.value)} />}
        {kind === "file" && isNew && <input type="file" accept=".png,.jpg,.jpeg,.webp,.gif,.heic,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.md,.ppt,.pptx,.rtf,.odt,.zip,.mp4,.mov"
          onChange={(e) => { const f = e.target.files?.[0] || null; setFile(f); if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, "")); }} />}
        <input placeholder="Название" value={title} onChange={(e) => setTitle(e.target.value)} />
        {kind === "note" && <textarea rows={8} placeholder="Текст заметки или регламента" value={body} onChange={(e) => setBody(e.target.value)} />}
        <textarea rows={3} placeholder="Краткое описание: что это и чем полезно" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <div className="acc-row"><span>Раздел</span>
          <select value={secId ?? ""} onChange={(e) => setSecId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">— без раздела —</option>
            {sections.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select></div>
        <div className="acc-row"><span>Кто видит</span>
          <select value={shopId ?? ""} onChange={(e) => setShopId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Всё рабочее пространство</option>
            {shops.filter((s) => s.can_add || s.id === shopId).map((s) => <option key={s.id} value={s.id}>Только магазин «{s.title}»</option>)}
          </select></div>
        {err && <div className="err">{err}</div>}
        <div className="full-btns">
          <button className="pri" disabled={busy} onClick={save}>{busy ? "Сохраняю…" : "Сохранить"}</button>
          <button onClick={onClose}>Отмена</button>
        </div>
      </div>
    </div>
  );
}

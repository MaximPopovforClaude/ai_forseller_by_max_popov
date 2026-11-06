import { useEffect, useMemo, useState } from "react";
import { api, http, type Article } from "./api";

type Media = { kind: "photo" | "video"; url: string; thumb: string | null };
type VisPh = { file_id: number; title: string; project_id: number | null; project: string | null };
type View = { nm_id: number; vendor_code: string; brand: string; subject_id: number; subject: string; title: string; description: string;
  characteristics: Record<string, unknown>; char_names: Record<string, string>; dimensions: Record<string, number | null>; media: Media[];
  price: number | null; discount: number | null; updated_at: string };
type Diff = { field: string; key?: string; title: string; before: unknown; after: unknown; source: string | null; note?: string | null };
type Hist = { id: number; status: string; changes: Record<string, unknown>; error: string | null; applied_at: string; rollback_of: number | null; who: string | null };
type St = { draft: { id: number; changes: Record<string, unknown>; sources: Record<string, string>; ai_notes: Record<string, string> } | null;
  base: View; diff: Diff[]; price_check: { before: number; after: number; drop: number; ai: boolean; needs_ack: boolean } | null;
  history: Hist[]; can_edit: boolean; why_not: string | null; ai: boolean; block: { enabled: boolean };
  ai_job: { scope: string; state: "running" | "done" | "error"; error: string | null; summary: string | null; finished_at: string | null } | null };
type Charc = { charcID: number; name: string; required: boolean; unitName: string; maxCount: number; charcType: number; popular: boolean };

const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
const rub = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n).toLocaleString("ru-RU")} ₽`);
const show = (v: unknown): string => Array.isArray(v) ? v.join(", ") : v && typeof v === "object" ? JSON.stringify(v) : v == null || v === "" ? "—" : String(v);
const FN: Record<string, string> = { length: "Длина, см", width: "Ширина, см", height: "Высота, см", weightBrutto: "Вес с упаковкой, кг" };

/** Карточки WB: правка → черновик → «было/стало» → «Применить на WB» (только по кнопке) → откат. */
export function Cards({ shop, initNm, onSettings }: { shop: number; initNm?: number | null; onSettings: () => void }) {
  const [arts, setArts] = useState<Article[]>([]);
  const [q, setQ] = useState("");
  const [nm, setNm] = useState<number | null>(initNm || null);
  useEffect(() => { if (initNm) setNm(initNm); }, [initNm]);
  useEffect(() => {
    let live = true;
    if (!initNm) setNm(null);
    setArts([]);
    api.articles(shop).then((a) => { if (live) setArts(a); }).catch(() => { if (live) setArts([]); });
    return () => { live = false; };
  }, [shop]);
  const ql = q.trim().toLowerCase();
  const list = useMemo(() => arts.filter((a) => !ql || String(a.nm_id).includes(ql) || (a.vendor_code || "").toLowerCase().includes(ql)
    || (a.title || "").toLowerCase().includes(ql)).slice(0, 200), [arts, ql]);
  if (nm) return <Editor shop={shop} nm={nm} onBack={() => setNm(null)} onSettings={onSettings} />;
  return (
    <div className="cards">
      <div className="rv-head"><h2>🃏 Карточки</h2><button className="link" onClick={onSettings}>⚙️ Настройки блока</button></div>
      <div className="hint">Выберите товар. Любые правки сначала попадают в черновик; в WB они уходят только когда вы нажмёте «Применить на WB».</div>
      <input className="cd-q" placeholder="Поиск: артикул WB, артикул продавца, название…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <div className="cd-list">{list.map((a) => (
        <button key={a.nm_id} className="cd-item" onClick={() => setNm(a.nm_id)}>
          {a.photo ? <img src={a.photo} alt="" /> : <span className="cd-noimg" />}
          <span><b>{a.vendor_code || a.nm_id}</b><br /><span className="hint">{a.nm_id} · {a.title || a.subject}</span></span>
        </button>))}</div>
    </div>
  );
}

function Editor({ shop, nm, onBack, onSettings }: { shop: number; nm: number; onBack: () => void; onSettings: () => void }) {
  const [s, setS] = useState<St | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [charcs, setCharcs] = useState<Charc[]>([]);
  const url = `/api/shops/${shop}/cards/${nm}`;
  useEffect(() => { http.get<St>(url).then(setS).catch((e) => setErr(e.message)); }, [url]);
  const running = s?.ai_job?.state === "running";
  useEffect(() => {              // нейросеть пишет в фоне — подтягиваем, пока не закончит
    if (!running) return;
    const t = window.setInterval(() => http.get<St>(url).then(setS).catch(() => undefined), 5000);
    return () => window.clearInterval(t);
  }, [running, url]);
  const ai = (scope: string) => { setErr(""); http.post(`${url}/ai`, { scope }).then(() => http.get<St>(url).then(setS)).catch((e) => setErr(e.message)); };
  const aiBtn = (scope: string, label = "✨ Предложить") => s?.ai && s.can_edit
    ? <button className="link" disabled={running} onClick={() => ai(scope)}>{running && s.ai_job?.scope === scope ? "✨ думаю…" : label}</button> : null;
  useEffect(() => { if (s?.base.subject_id) http.get<Charc[]>(`${url}/charcs?subject_id=${s.base.subject_id}`).then(setCharcs).catch(() => undefined); }, [s?.base.subject_id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return <div className="cards">{err ? <div className="err">{err}</div> : <div className="hint">Загружаю карточку из WB…</div>}</div>;
  const ch = s.draft?.changes || {};
  const cur = <T,>(f: string, base: T): T => (f in ch ? ch[f] as T : base);
  const set = (field: string, value: unknown) => { setErr("");
    return http.put<St>(`${url}/draft`, { field, value }).then(setS).catch((e) => setErr(e.message)); };
  const apply = (force = false, price_ack: number | null = null): Promise<void> => {
    setBusy(true); setErr(""); setMsg("");
    return http.post<{ status: string; errors: string[] }>(`${url}/apply`, { force, price_ack }).then((r) => {
      setMsg(r.status === "applied" ? "✅ Изменения отправлены в WB" : "");
      if (r.errors.length) setErr(r.errors.join("\n"));
      return http.get<St>(url).then(setS);
    }).catch((e: Error) => {
      const m = e.message;
      if (m.startsWith("PRICE_DROP:")) {          // снижение цены: несколько подтверждений + ввести итоговую цену руками
        const pc = s.price_check!;
        if (!window.confirm(`⚠️ ${m.slice(11)}.\n\nВы точно хотите так сильно снизить цену?`)) return;
        if (!window.confirm(`Ещё раз: итоговая цена для покупателя станет ${Math.round(pc.after)} ₽ вместо ${Math.round(pc.before)} ₽ (−${Math.round(pc.drop * 100)} %). Это не ошибка?`)) return;
        const typed = window.prompt(`Для подтверждения введите новую итоговую цену (${Math.round(pc.after)}):`);
        if (!typed) return;
        return apply(force, Number(typed.replace(/\s/g, "").replace(",", ".")));
      }
      if (m.startsWith("CHANGED:")) {
        if (window.confirm(m.slice(8) + "\n\nОК — обновить «было» из WB (ваши правки останутся, проверите и примените ещё раз).\nОтмена — ничего не делать."))
          return http.post<St>(`${url}/rebase`).then((x) => { setS(x); setMsg("«Было» обновлено из WB — проверьте изменения и примените."); });
        return;
      }
      setErr(m);
    }).finally(() => setBusy(false));
  };
  const b = s.base;
  const media = cur<Media[]>("media", b.media);
  const price = cur<number | null>("price", b.price), disc = cur<number | null>("discount", b.discount);
  const fin = price != null ? price * (1 - (disc || 0) / 100) : null;
  const dis = !s.can_edit;
  return (
    <div className="cards">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ к списку</button>
        <h2>{b.vendor_code} <span className="hint">{b.nm_id} · {b.subject} · {b.brand}</span></h2>
        <a className="link" href={`https://www.wildberries.ru/catalog/${b.nm_id}/detail.aspx`} target="_blank" rel="noreferrer">открыть на WB ↗</a></div>
      {s.ai && s.can_edit && <div className="cd-ai">
        <button className="pri" disabled={running} onClick={() => ai("all")}>{running ? "✨ Нейросеть изучает карточку…" : "✨ Улучшить карточку целиком"}</button>
        <span className="hint">ИИ учтёт поисковые запросы артикула, рекламные кластеры, отзывы, справочник WB и ваши правила — и положит предложения в черновик. Сам он ничего не отправляет.</span>
        <CardRules shop={shop} />
      </div>}
      {s.ai_job?.state === "done" && s.ai_job.summary && <div className="ok">✨ {s.ai_job.summary}</div>}
      {s.ai_job?.state === "error" && <div className="err">Нейросеть: {s.ai_job.error}</div>}
      {s.why_not && <div className="hint">ℹ️ Применить на WB пока нельзя: {s.why_not}. <button className="link" onClick={onSettings}>Настройки взаимодействий</button></div>}
      {err && <div className="err" style={{ whiteSpace: "pre-wrap" }}>{err}</div>}
      {msg && <div className="ok">{msg}</div>}

      <div className="cd-grid">
        <div className="cd-main">
          <Field title="Название" changed={"title" in ch} onReset={() => set("title", null)} ai={aiBtn("title")} note={s.draft?.ai_notes.title}>
            <TextEdit value={cur("title", b.title)} max={60} disabled={dis} onSave={(v) => set("title", v)} />
          </Field>
          <Field title="Описание" changed={"description" in ch} onReset={() => set("description", null)} ai={aiBtn("description")} note={s.draft?.ai_notes.description}>
            <TextEdit value={cur("description", b.description)} max={5000} rows={10} disabled={dis} onSave={(v) => set("description", v)} />
          </Field>
          <Field title="Фото и видео" changed={"media" in ch} onReset={() => set("media", null)} ai={aiBtn("media", "✨ Предложить порядок")} note={s.draft?.ai_notes.media}
            hint="Перетащите, чтобы поменять порядок слайдов. WB заменяет все медиа разом — порядок отправится целиком.">
            <MediaEdit media={media} disabled={dis} shop={shop} nm={nm} onChange={(m) => set("media", m)} onErr={setErr} />
          </Field>
          <Field title="Характеристики" changed={"characteristics" in ch} onReset={() => set("characteristics", null)} ai={aiBtn("characteristics", "✨ Дополнить")} note={s.draft?.ai_notes.characteristics}>
            <CharEdit b={b} charcs={charcs} changes={(ch.characteristics || {}) as Record<string, unknown>} disabled={dis}
              onSave={(k, v) => set("characteristics", { ...((ch.characteristics || {}) as object), [k]: v })} />
          </Field>
          <Field title="Габариты и вес" changed={"dimensions" in ch} onReset={() => set("dimensions", null)}>
            <div className="cd-dims">{Object.keys(FN).map((k) => (
              <label key={k}>{FN[k]}<input type="number" step="any" disabled={dis} defaultValue={String(cur<Record<string, number | null>>("dimensions", b.dimensions)[k] ?? "")}
                key={`${k}-${s.draft?.id}-${JSON.stringify(ch.dimensions || null)}`}
                onBlur={(e) => { const d = { ...b.dimensions, ...((ch.dimensions || {}) as object), [k]: e.target.value === "" ? null : Number(e.target.value) };
                  if (String((b.dimensions as Record<string, unknown>)[k] ?? "") !== e.target.value || "dimensions" in ch) set("dimensions", d); }} /></label>))}</div>
          </Field>
          <Field title="Цена и скидка" changed={"price" in ch || "discount" in ch} onReset={() => { set("price", null).then(() => set("discount", null)); }}
            hint={`Сейчас на WB: ${rub(b.price)}, скидка ${b.discount ?? 0} % → покупатель видит до СПП ${rub(b.price != null ? b.price * (1 - (b.discount || 0) / 100) : null)}`}>
            <div className="cd-dims">
              <label>Цена до скидки, ₽<input type="number" disabled={dis} defaultValue={price ?? ""} key={`p${price}`} onBlur={(e) => { if (e.target.value && Number(e.target.value) !== price) set("price", Number(e.target.value)); }} /></label>
              <label>Скидка, %<input type="number" min={0} max={95} disabled={dis} defaultValue={disc ?? ""} key={`d${disc}`} onBlur={(e) => { if (e.target.value !== "" && Number(e.target.value) !== disc) set("discount", Number(e.target.value)); }} /></label>
              <label>Итоговая цена<b className={s.price_check?.needs_ack ? "down" : ""}>{rub(fin)}</b></label>
            </div>
            {s.price_check && <div className={s.price_check.needs_ack ? "err" : "hint"}>Итоговая цена снижается на {Math.round(s.price_check.drop * 100)} %
              {s.price_check.needs_ack ? " — при применении попросим подтвердить несколько раз." : ""}</div>}
          </Field>
        </div>

        <div className="cd-side">
          <div className="acc-box">
            <b>Черновик: {s.diff.length ? `${s.diff.length} изм.` : "нет изменений"}</b>
            {s.diff.map((d, i) => (
              <div key={i} className="cd-diff">
                <div className="cd-diff-h"><b>{(d.key && charcs.find((x) => String(x.charcID) === d.key)?.name) || d.title}</b>
                  {d.source === "ai" && <span className="chip">✨ ИИ</span>}
                  {s.can_edit && <button className="link cd-drop" disabled={busy} title="Убрать эту правку из черновика — на WB останется как сейчас"
                    onClick={() => d.key ? set("characteristics", Object.fromEntries(Object.entries((ch.characteristics || {}) as object).filter(([k]) => k !== d.key)))
                      : set(d.field, null)}>✕ убрать</button>}</div>
                {d.field === "media" ? <div className="hint">{(d.before as Media[]).length} → {(d.after as Media[]).length} шт., порядок изменён</div>
                  : <><div className="cd-before">было: {show(d.before).slice(0, 300)}</div><div className="cd-after">стало: {show(d.after).slice(0, 300)}</div></>}
                {d.note && <div className="hint" title={d.note}>💡 {d.note.length > 160 ? d.note.slice(0, 160) + "… (полностью — у поля)" : d.note}</div>}
              </div>))}
            {s.diff.length > 0 && s.can_edit && <div className="row">
              <button className="pri" disabled={busy || !!s.why_not} title={s.why_not || ""} onClick={() => {
                if (window.confirm(`Применить ${s.diff.length} изм. на Wildberries? Покупатели увидят изменения после проверки WB.`)) apply(); }}>
                {busy ? "Отправляю…" : "✅ Применить на WB"}</button>
              <button onClick={() => { if (window.confirm("Удалить черновик со всеми правками?")) http.del(`${url}/draft`).then(() => http.get<St>(url).then(setS)); }}>Удалить черновик</button>
            </div>}
          </div>
          {s.history.length > 0 && <div className="acc-box">
            <b>История изменений через сервис</b>
            {s.history.map((h) => <div key={h.id} className="cd-hist">
              <div>{dt(h.applied_at)} · {h.who || "—"} · {h.status === "applied" ? "✅" : h.status === "partial" ? "⚠️ частично" : "❌"}{h.rollback_of ? " · откат" : ""}</div>
              <div className="hint">{Object.keys(h.changes).join(", ")}</div>
              {h.error && <div className="err">{h.error}</div>}
              {s.can_edit && h.status !== "error" && <button className="link" onClick={() => {
                if (window.confirm("Создать черновик, возвращающий эти поля как было? Применить его нужно будет отдельно."))
                  http.post<St>(`/api/shops/${shop}/cards/rollback/${h.id}`).then(setS).catch((e) => setErr(e.message)); }}>↩️ Откатить</button>}
            </div>)}
          </div>}
        </div>
      </div>
    </div>
  );
}

function Field({ title, changed, onReset, hint, ai, note, children }: { title: string; changed: boolean; onReset: () => void; hint?: string;
  ai?: React.ReactNode; note?: string; children: React.ReactNode }) {
  return <div className={"acc-box cd-field" + (changed ? " changed" : "")}>
    <div className="row"><b>{title}</b>{changed && <><span className="chip">в черновике</span><button className="link" onClick={onReset}>вернуть как было</button></>}
      <span style={{ marginLeft: "auto" }}>{ai}</span></div>
    {changed && note && <div className="cd-note">✨ {note}</div>}
    {hint && <div className="hint">{hint}</div>}
    {children}
  </div>;
}

function TextEdit({ value, max, rows, disabled, onSave }: { value: string; max: number; rows?: number; disabled: boolean; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <>
    {rows ? <textarea rows={rows} value={v} disabled={disabled} onChange={(e) => setV(e.target.value)} />
      : <input value={v} disabled={disabled} onChange={(e) => setV(e.target.value)} />}
    <div className="row"><span className={v.length > max ? "down" : "hint"}>{v.length} / {max}</span>
      {v !== value && <button className="pri" disabled={v.length > max} onClick={() => onSave(v)}>В черновик</button>}
      {v !== value && <button onClick={() => setV(value)}>Отмена</button>}</div>
  </>;
}

function MediaEdit({ media, disabled, shop, nm, onChange, onErr }: { media: Media[]; disabled: boolean; shop: number; nm: number;
  onChange: (m: Media[]) => void; onErr: (s: string) => void }) {
  const [drag, setDrag] = useState<number | null>(null);
  const [base, setBase] = useState<VisPh[] | null>(null);
  const [pick, setPick] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [big, setBig] = useState<string | null>(null);
  const inBase = (u: string) => !!base?.some((p) => u.includes(`/visual_file/${p.file_id}?`));
  const addMedia = (added: Media[]) => {
    const vi = media.findIndex((m) => m.kind === "video");
    if (added.length) onChange(vi >= 0 ? [...media.slice(0, vi), ...added, ...media.slice(vi)] : [...media, ...added]);
  };
  const openBase = () => http.get<{ photos: VisPh[] }>(`/api/shops/${shop}/cards/${nm}/vis_photos`).then((x) => { setBase(x.photos); setPick([]); })
    .catch((e) => onErr(e.message));
  const fromBase = () => { setBusy(true); http.post<{ media: Media[] }>(`/api/shops/${shop}/cards/${nm}/from_visual`, { file_ids: pick })
    .then((x) => { addMedia(x.media); setBase(null); setBusy(false); }).catch((e) => { onErr(e.message); setBusy(false); }); };
  const move = (from: number, to: number) => { const m = [...media]; const [x] = m.splice(from, 1); m.splice(to, 0, x); onChange(m); };
  return <div className="cd-media">
    {media.map((m, i) => (
      <div key={m.url + i} className={"cd-ph" + (drag === i ? " drag" : "")} draggable={!disabled}
        onDragStart={() => setDrag(i)} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (drag !== null && drag !== i) move(drag, i); setDrag(null); }}>
        {m.kind === "video" ? <div className="cd-video">🎬 видео</div> : <img src={m.thumb || m.url} alt="" onClick={() => setBig(m.url)} style={{ cursor: "zoom-in" }} />}
        {m.kind !== "video" && <button className="cd-zoom" title="Посмотреть крупно" onClick={() => setBig(m.url)}>🔍</button>}
        <span className="cd-n">{i + 1}</span>
        {!disabled && <div className="cd-ph-btns">
          {i > 0 && <button title="Левее" onClick={() => move(i, i - 1)}>‹</button>}
          {i < media.length - 1 && <button title="Правее" onClick={() => move(i, i + 1)}>›</button>}
          <button title="Убрать" onClick={() => onChange(media.filter((_, k) => k !== i))}>×</button></div>}
      </div>))}
    {!disabled && <label className="cd-add">＋ фото<input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden onChange={async (e) => {
      const files = Array.from(e.target.files || []);
      const added: Media[] = [];
      for (const f of files) {
        const r = await fetch(`/api/shops/${shop}/cards/${nm}/upload?name=${encodeURIComponent(f.name)}`, { method: "POST", body: f, credentials: "include" });
        if (!r.ok) { onErr((await r.json().catch(() => ({ detail: "Не загрузилось" }))).detail); continue; }
        added.push(await r.json());
      }
      addMedia(added);
      e.target.value = "";
    }} /></label>}
    {!disabled && <button className="cd-add" onClick={openBase}>＋ из базы фото</button>}
    {base && <div className="cd-base">
      <div className="rnp-bar"><b>База фото (раздел «Визуал»)</b>
        {base.length > 0 && <button className="link" onClick={() => setPick(pick.length === base.length ? [] : base.map((p) => p.file_id))}>
          {pick.length === base.length ? "снять все" : "выбрать все"}</button>}
        <button className="pri" disabled={!pick.length || busy} onClick={fromBase}>Добавить в карточку {pick.length || ""}</button>
        <button className="link" onClick={() => setBase(null)}>закрыть</button></div>
      {!base.length && <div className="hint">В базе пока нет фото этого товара — отрисуйте их в «Визуале» и нажмите «Добавить в базу фото товара».</div>}
      <div className="cd-media">{base.map((p) => <label key={p.file_id} className={"cd-ph" + (pick.includes(p.file_id) ? " on" : "")} title={p.title}>
        <img src={`/api/shops/${shop}/visual_file/${p.file_id}?thumb=1`} alt="" />
        <input type="checkbox" checked={pick.includes(p.file_id)} onChange={() => setPick(pick.includes(p.file_id) ? pick.filter((x) => x !== p.file_id) : [...pick, p.file_id])} />
        <button className="cd-zoom" title="Посмотреть крупно" onClick={(e) => { e.preventDefault(); setBig(`/api/shops/${shop}/visual_file/${p.file_id}?w=1`); }}>🔍</button>
        <span className="hint">{p.project_id ? "" : "общее · "}{p.title.slice(0, 30)}</span></label>)}</div>
      <div className="hint">🔍 — посмотреть крупно и там же выбрать (листать ‹ › или стрелками). Фото встанут в конец черновика — порядок поменяйте стрелками, в WB уйдут только по кнопке «Применить».</div></div>}
    {big && (inBase(big) && base
      ? <BigView urls={base.map((p) => `/api/shops/${shop}/visual_file/${p.file_id}?w=1`)} start={big} onClose={() => setBig(null)}
        isOn={(i) => pick.includes(base[i].file_id)}
        toggle={(i) => { const f = base[i].file_id; setPick(pick.includes(f) ? pick.filter((x) => x !== f) : [...pick, f]); }} />
      : <BigView urls={media.filter((m) => m.kind !== "video").map((m) => m.url)} start={big} onClose={() => setBig(null)} />)}
  </div>;
}

/** Фото крупно: ‹ › или стрелки клавиатуры — листать, Esc / клик по фону — закрыть. */
function BigView({ urls, start, onClose, isOn, toggle }: { urls: string[]; start: string; onClose: () => void;
  isOn?: (i: number) => boolean; toggle?: (i: number) => void }) {
  const [i, setI] = useState(Math.max(0, urls.indexOf(start)));
  const go = (d: number) => setI((x) => (x + d + urls.length) % urls.length);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); if (e.key === "ArrowLeft") go(-1); if (e.key === "ArrowRight") go(1); };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  });   // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="vis-lb" onClick={onClose}>
    <div className="vis-lb-in" onClick={(e) => e.stopPropagation()}><img src={urls[i]} alt="" /></div>
    <div className="vis-lb-bar" onClick={(e) => e.stopPropagation()}>
      {urls.length > 1 && <button onClick={() => go(-1)}>‹</button>}<span style={{ color: "#fff" }}>{i + 1} / {urls.length}</span>
      {urls.length > 1 && <button onClick={() => go(1)}>›</button>}
      {toggle && <button className={isOn?.(i) ? "pri" : ""} onClick={() => toggle(i)}>{isOn?.(i) ? "✓ Выбрано в карточку" : "＋ Выбрать в карточку"}</button>}
      <a href={urls[i]} target="_blank" rel="noreferrer">в новой вкладке ↗</a><button onClick={onClose}>✕ Закрыть</button></div>
  </div>;
}

function CharEdit({ b, charcs, changes, disabled, onSave }: { b: View; charcs: Charc[]; changes: Record<string, unknown>; disabled: boolean;
  onSave: (k: string, v: unknown) => void }) {
  const [all, setAll] = useState(false);
  const ids = new Set([...Object.keys(b.characteristics), ...charcs.filter((x) => x.required).map((x) => String(x.charcID))]);
  const rows = (all ? charcs.map((x) => String(x.charcID)) : [...ids]).filter((k, i, a) => a.indexOf(k) === i);
  const meta = Object.fromEntries(charcs.map((x) => [String(x.charcID), x]));
  return <>
    <table className="acc-t cd-chars"><tbody>{rows.map((k) => {
      const m = meta[k];
      const val = k in changes ? changes[k] : b.characteristics[k];
      const txt = Array.isArray(val) ? val.join("; ") : val == null ? "" : String(val);
      return <tr key={k} className={k in changes ? "changed" : ""}>
        <td>{m?.name || b.char_names[k] || k}{m?.required ? " *" : ""}{m?.unitName ? `, ${m.unitName}` : ""}</td>
        <td><input disabled={disabled} defaultValue={txt} key={txt} title={m?.maxCount ? `не больше ${m.maxCount} значений, через «;»` : "через «;»"}
          onBlur={(e) => {
            if (e.target.value === txt) return;
            const parts = e.target.value.split(";").map((x) => x.trim()).filter(Boolean);
            const v = m?.charcType === 4 ? (parts[0] ? Number(parts[0].replace(",", ".")) : null) : parts;
            onSave(k, v);
          }} /></td></tr>;
    })}</tbody></table>
    <div className="row"><button className="link" onClick={() => setAll(!all)}>{all ? "только заполненные и обязательные" : `показать все характеристики предмета (${charcs.length})`}</button>
      <span className="hint">Несколько значений — через «;». * — обязательная.</span></div>
  </>;
}

function CardRules({ shop }: { shop: number }) {
  const [open, setOpen] = useState(false);
  const [t, setT] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => { if (open && t === null) http.get<{ text: string }>(`/api/shops/${shop}/cards/rules`).then((r) => setT(r.text)).catch(() => setT("")); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) return <button className="link" onClick={() => setOpen(true)}>📝 Правила для карточек</button>;
  return <div className="cd-rules">
    <textarea rows={5} value={t ?? ""} onChange={(e) => { setT(e.target.value); setOk(false); }}
      placeholder={"Правила магазина для ИИ, например:\n- в названии всегда объём и аромат\n- не писать «натуральный», если нет в составе\n- тон: тёплый, без восклицаний"} />
    <div className="row"><button onClick={() => http.put(`/api/shops/${shop}/cards/rules`, { text: t || "" }).then(() => setOk(true))}>Сохранить правила</button>
      {ok && <span className="hint">✓ сохранено</span>}<button className="link" onClick={() => setOpen(false)}>свернуть</button></div>
  </div>;
}

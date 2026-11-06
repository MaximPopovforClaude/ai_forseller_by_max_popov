import { useEffect, useMemo, useState } from "react";
import { api, http, type Article } from "./api";

/** Блок «SEO» : ядро ключей → текст ИИ с полным вхождением (проверяет код) → согласование менеджером → загрузка в WB. */
type Key = { phrase: string; src: string[]; freq: number | null; opens?: number; orders?: number; ad_orders?: number; comp_share?: number;
  mark: "core" | "main" | "excluded" | null; rec: boolean; relevant: boolean; in_card: boolean; in_title: boolean; words_in_card: boolean };
type Check = { keys: { phrase: string; ok: boolean; in_title: boolean; main: boolean }[]; coverage: number; missing: string[]; main: string | null;
  main_in_lead: boolean; main_in_title: boolean; title_len: number; desc_len: number; len_ok: boolean; ok: boolean;
  copies?: { nm_id: number; share: number; examples: string[] }[] };
type Draft = { id: number; title: string | null; description: string | null; old_title: string; old_description: string; other: string[];
  seo: Check | null; review_state: "pending" | "approved" | "returned" | null; review_comment: string | null; reviewers: string[];
  reviewed_by: string; can_review: boolean };
type St = { rows: Key[]; notes: string[]; competitors: { id: number; name: string | null; src: string }[]; state: "running" | "done" | "error" | null;
  error: string | null; built_at: string | null; card: { title: string; description: string; subject: string; vendor_code: string | null; title_len: number; desc_len: number };
  draft: Draft | null; job: { state: "running" | "done" | "error"; error: string | null; summary: string | null } | null;
  can_edit: boolean; ai: boolean; why_not: string | null; will_review: string[] };
type Pend = { id: number; nm_id: number; vc: string | null; title: string | null; old_title: string; coverage: number | null; from: string;
  reviewers: string[]; mine: boolean; review_sent_at: string };

const nf = new Intl.NumberFormat("ru-RU");
const SRC: Record<string, string> = { jam: "Джем", ads: "Реклама", comp: "Конкуренты", suggest: "Подсказки WB", manual: "вручную" };
const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });

export function SeoBlock({ shop }: { shop: number }) {
  const [arts, setArts] = useState<Article[]>([]);
  const [q, setQ] = useState("");
  const [nm, setNm] = useState<number | null>(null);
  const [view, setView] = useState<"list" | "rules" | "pending">("list");
  const [pend, setPend] = useState<Pend[]>([]);
  const loadPend = () => http.get<{ rows: Pend[] }>(`/api/shops/${shop}/seo_pending`).then((r) => setPend(r.rows)).catch(() => setPend([]));
  useEffect(() => {
    let live = true;
    setNm(null); setArts([]); setView("list");
    api.articles(shop).then((a) => { if (live) setArts(a); }).catch(() => { if (live) setArts([]); });
    loadPend();
    return () => { live = false; };
  }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  const ql = q.trim().toLowerCase();
  const list = useMemo(() => arts.filter((a) => !ql || String(a.nm_id).includes(ql) || (a.vendor_code || "").toLowerCase().includes(ql)
    || (a.title || "").toLowerCase().includes(ql)).slice(0, 200), [arts, ql]);
  if (nm) return <Editor shop={shop} nm={nm} onBack={() => { setNm(null); loadPend(); }} />;
  if (view === "rules") return <Rules shop={shop} onBack={() => setView("list")} />;
  const head = (
    <div className="rv-head"><h2>🔎 SEO</h2>
      <button className={"link" + (view === "pending" ? " on" : "")} onClick={() => setView(view === "pending" ? "list" : "pending")}>
        📝 На согласовании{pend.length ? ` (${pend.length})` : ""}</button>
      <button className="link" onClick={() => setView("rules")}>📋 Правила SEO</button></div>);
  if (view === "pending") return (
    <div className="cards">{head}
      {!pend.length && <div className="hint">Сейчас ничего не ждёт согласования.</div>}
      <table className="rnp-t"><thead><tr><th>Товар</th><th>Новое название</th><th>Покрытие ключей</th><th>Отправил(а)</th><th>Согласует</th><th>Когда</th></tr></thead>
        <tbody>{pend.map((p) => <tr key={p.id} className={p.mine ? "z-good" : ""} style={{ cursor: "pointer" }} onClick={() => setNm(p.nm_id)}>
          <td><b>{p.vc || p.nm_id}</b><br /><span className="hint">{p.nm_id}</span></td><td>{p.title || <span className="hint">без изменений</span>}</td>
          <td>{p.coverage == null ? "—" : `${p.coverage} %`}</td><td>{p.from}</td><td>{p.reviewers.join(", ")}{p.mine && " · вы"}</td><td>{dt(p.review_sent_at)}</td></tr>)}</tbody></table>
    </div>);
  return (
    <div className="cards">{head}
      <div className="hint">Выберите товар: соберём ключи (Джем, реклама, конкуренты и подсказки WB через Wildbox), ИИ напишет текст с полным вхождением ключей,
        код проверит вхождения, менеджер артикула согласует - и только тогда текст уйдёт в карточку WB.</div>
      <input className="cd-q" placeholder="Поиск: артикул WB, артикул продавца, название…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      <div className="cd-list">{list.map((a) => (
        <button key={a.nm_id} className="cd-item" onClick={() => setNm(a.nm_id)}>
          {a.photo ? <img src={a.photo} alt="" /> : <span className="cd-noimg" />}
          <span><b>{a.vendor_code || a.nm_id}</b><br /><span className="hint">{a.nm_id} · {a.title || a.subject}</span></span>
        </button>))}</div>
    </div>
  );
}

function Editor({ shop, nm, onBack }: { shop: number; nm: number; onBack: () => void }) {
  const [s, setS] = useState<St | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [flt, setFlt] = useState<"core" | "rec" | "all" | "excluded">("all");
  const [own, setOwn] = useState("");
  const [title, setTitle] = useState<string | null>(null);
  const [desc, setDesc] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [back, setBack] = useState("");
  const [busy, setBusy] = useState(false);
  const url = `/api/shops/${shop}/seo/${nm}`;
  const load = () => http.get<St>(`${url}/core`).then((x) => { setS(x); setTitle(null); setDesc(null); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const running = s?.state === "running" || s?.job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => http.get<St>(`${url}/core`).then(setS).catch(() => undefined), 5000);
    return () => window.clearInterval(t);
  }, [running, url]);
  if (!s) return <div className="cards">{err ? <div className="err">{err}</div> : <div className="hint">Загрузка…</div>}</div>;
  const fail = (e: Error) => { setErr(e.message); setBusy(false); };
  const mark = (k: Key, m: Key["mark"]) => http.put(`${url}/mark`, { phrase: k.phrase, mark: k.mark === m ? null : m }).then(load).catch(fail);
  const addOwn = () => own.trim() && http.put(`${url}/mark`, { phrase: own, mark: "core" }).then(() => { setOwn(""); load(); }).catch(fail);
  const collect = () => { setErr(""); http.post(`${url}/collect`).then(load).catch(fail); };
  const write = (n?: string) => { setErr(""); setMsg(""); http.post(`${url}/write`, { note: n || null }).then(() => { setNote(""); load(); }).catch(fail); };
  const d = s.draft;
  const curTitle = title ?? d?.title ?? s.card.title;
  const curDesc = desc ?? d?.description ?? s.card.description;
  const dirty = title !== null || desc !== null;
  const saveText = async () => {
    setBusy(true); setErr("");
    try {
      if (title !== null) await http.put(`/api/shops/${shop}/cards/${nm}/draft`, { field: "title", value: title });
      if (desc !== null) await http.put(`/api/shops/${shop}/cards/${nm}/draft`, { field: "description", value: desc });
      await http.post(`${url}/recheck`).then((x) => setS(x as St));
      setTitle(null); setDesc(null); setMsg("Сохранено в черновик, проверка обновлена");
    } catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  const submit = () => { setBusy(true); setErr(""); http.post<{ reviewers: string[] }>(`${url}/submit`)
    .then((r) => { setMsg(`Отправлено на согласование: ${r.reviewers.join(", ")}`); setBusy(false); load(); }).catch(fail); };
  const approve = () => { if (!d) return; setBusy(true); setErr("");
    http.post<{ status: string; errors: string[] }>(`/api/shops/${shop}/seo_review/${d.id}/approve`).then((r) => {
      setMsg(r.status === "applied" ? "✅ Согласовано и загружено в WB" : ""); if (r.errors?.length) setErr(r.errors.join("\n")); setBusy(false); load();
    }).catch(fail); };
  const sendBack = () => { if (!d || !back.trim()) return; setBusy(true);
    http.post(`/api/shops/${shop}/seo_review/${d.id}/return`, { comment: back }).then(() => { setBack(""); setBusy(false); load(); }).catch(fail); };
  const rows = s.rows.filter((k) => flt === "all" ? k.mark !== "excluded" : flt === "core" ? k.mark === "core" || k.mark === "main"
    : flt === "rec" ? k.rec : k.mark === "excluded");
  const nCore = s.rows.filter((k) => k.mark === "core" || k.mark === "main").length;
  const chk = d?.seo;
  return (
    <div className="cards seo-ed">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ к товарам</button>
        <h2>🔎 SEO · {s.card.vendor_code || nm}</h2><a href={`https://www.wildberries.ru/catalog/${nm}/detail.aspx`} target="_blank" rel="noreferrer">на WB ↗</a></div>
      <div className="hint">{s.card.subject} · сейчас: название {s.card.title_len} зн., описание {s.card.desc_len} зн.</div>
      {err && <div className="err" style={{ whiteSpace: "pre-wrap" }}>{err}</div>}
      {msg && <div className="ok">{msg}</div>}

      <div className="acc-box">
        <b>1. Ядро ключей</b>{" "}
        {s.can_edit && <button disabled={s.state === "running"} onClick={collect}>{s.state === "running" ? "🔍 собираю… (до 2 минут)" : s.built_at ? "🔄 Пересобрать" : "🔍 Собрать ключи"}</button>}
        {s.built_at && <span className="hint"> собрано {dt(s.built_at)}</span>}
        {s.state === "error" && <div className="err">{s.error}</div>}
        {s.notes.length > 0 && <div className="hint">{s.notes.join(" · ")}</div>}
        {s.competitors.length > 0 && <details><summary className="hint">Конкуренты ({s.competitors.length})</summary>
          {s.competitors.map((x) => <div key={x.id} className="hint"><a href={`https://www.wildberries.ru/catalog/${x.id}/detail.aspx`} target="_blank" rel="noreferrer">{x.id}</a> · {x.name || ""} · {x.src}</div>)}</details>}
        <div className="hint">★ главный ключ (дословно в первых 1-2 предложениях), «в ядро» - каждый войдёт в текст дословно. Ничего не отмечено - ИИ возьмёт рекомендованные.
          Исключённые больше не предлагаем.</div>
        <div className="rnp-bar">
          <button className={flt === "all" ? "on" : ""} onClick={() => setFlt("all")}>Все ({s.rows.filter((k) => k.mark !== "excluded").length})</button>
          <button className={flt === "core" ? "on" : ""} onClick={() => setFlt("core")}>Ядро ({nCore})</button>
          <button className={flt === "rec" ? "on" : ""} onClick={() => setFlt("rec")}>Рекомендованные ({s.rows.filter((k) => k.rec).length})</button>
          <button className={flt === "excluded" ? "on" : ""} onClick={() => setFlt("excluded")}>Исключённые ({s.rows.filter((k) => k.mark === "excluded").length})</button>
          {s.can_edit && <><input placeholder="свой ключ" value={own} onChange={(e) => setOwn(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addOwn()} />
            <button disabled={!own.trim()} onClick={addOwn}>+ в ядро</button></>}
        </div>
        <div style={{ maxHeight: 460, overflow: "auto" }}>
          <table className="rnp-t">
            <thead><tr><th>Ключ</th><th>Частота / мес</th><th>Наши заказы</th><th>У конкурентов</th><th>Источник</th><th>В тексте</th><th></th></tr></thead>
            <tbody>{rows.map((k) => <tr key={k.phrase} className={k.mark === "main" || k.mark === "core" ? "z-good" : k.mark === "excluded" ? "z-bad" : ""}
              style={k.relevant ? undefined : { opacity: 0.55 }}>
              <td>{k.mark === "main" && "★ "}<b>{k.phrase}</b>{k.rec && !k.mark && <span className="hint"> · реком.</span>}</td>
              <td>{k.freq == null ? "—" : nf.format(k.freq)}</td>
              <td>{k.orders != null || k.ad_orders != null ? nf.format((k.orders || 0)) + (k.ad_orders ? ` / рекл. ${k.ad_orders}` : "") : "—"}</td>
              <td>{k.comp_share == null ? "—" : `${Math.round(k.comp_share * 100)} %`}</td>
              <td className="hint">{k.src.map((x) => SRC[x] || x).join(", ")}</td>
              <td className={k.in_card ? "t-good" : k.words_in_card ? "" : "t-bad"} title="полное вхождение = фраза слово в слово">
                {k.in_card ? (k.in_title ? "✅ в названии" : "✅ полное") : k.words_in_card ? "слова есть" : "—"}</td>
              <td>{s.can_edit && <span style={{ whiteSpace: "nowrap" }}>
                <button className={"link" + (k.mark === "main" ? " on" : "")} title="главный ключ" onClick={() => mark(k, "main")}>★</button>{" "}
                <button className={"link" + (k.mark === "core" ? " on" : "")} onClick={() => mark(k, "core")}>+ ядро</button>{" "}
                <button className={"link" + (k.mark === "excluded" ? " on" : "")} onClick={() => mark(k, "excluded")}>− искл.</button></span>}</td></tr>)}</tbody>
          </table>
        </div>
      </div>

      <div className="acc-box">
        <b>2. Текст</b>{" "}
        {s.can_edit && s.ai && <button disabled={running || !s.rows.length} onClick={() => write()}>
          {s.job?.state === "running" ? "✨ пишу и проверяю… (до 3 минут)" : d?.title || d?.description ? "✨ Переписать" : "✨ Написать SEO"}</button>}
        {!s.ai && <span className="hint"> нейросеть недоступна для этого кабинета</span>}
        {s.job?.state === "done" && s.job.summary && <div className="hint">{s.job.summary}</div>}
        {s.job?.state === "error" && <div className="err">{s.job.error}</div>}
        {chk && <div className="seo-chk">
          <div><b className={chk.ok ? "t-good" : "t-bad"}>{chk.ok ? "✅ Проверка пройдена" : "⚠️ Есть замечания"}</b> · покрытие ключей <b>{chk.coverage} %</b>
            · главный ключ «{chk.main}»: {chk.main_in_lead ? "✅ в первых 2 предложениях" : "❌ не в начале"}{chk.main_in_title ? ", ✅ в названии" : ""}
            · описание {chk.desc_len} зн. {chk.desc_len >= 800 && chk.desc_len <= 2000 ? "✅" : "❌ (нужно 800-2000)"} · название {chk.title_len} зн. {chk.title_len <= 60 ? "✅" : "❌"}</div>
          <div className="hint">{chk.keys.map((k) => <span key={k.phrase} className={k.ok ? "t-good" : "t-bad"} style={{ marginRight: 10 }}>{k.ok ? "✅" : "❌"} {k.phrase}</span>)}</div>
          {(chk.copies || []).length > 0 && <div className="hint">Совпадения с описаниями конкурентов: {chk.copies!.map((x) => `${x.nm_id} - ${x.share} % («${x.examples[0]}»)`).join("; ")}</div>}
        </div>}
        <label className="seo-f">Название ({curTitle.length}/60)
          <input value={curTitle} disabled={!s.can_edit} onChange={(e) => setTitle(e.target.value)} /></label>
        <label className="seo-f">Описание ({curDesc.length} зн., норма 800-2000)
          <textarea rows={16} value={curDesc} disabled={!s.can_edit} onChange={(e) => setDesc(e.target.value)} /></label>
        {dirty && <button className="pri" disabled={busy} onClick={saveText}>Сохранить правку и перепроверить</button>}
        {d && <details><summary className="hint">Как было в WB</summary><div className="hint"><b>{d.old_title}</b></div>
          <div className="hint" style={{ whiteSpace: "pre-wrap" }}>{d.old_description}</div></details>}
        {d && d.other.length > 0 && <div className="hint">В черновике есть и другие правки карточки ({d.other.join(", ")}) - они уйдут в WB вместе с текстом.</div>}
      </div>

      <div className="acc-box">
        <b>3. Согласование и загрузка в WB</b>
        {s.why_not && <div className="err">Загрузка в WB сейчас невозможна: {s.why_not}</div>}
        {!d && <div className="hint">Сначала напишите текст - он попадёт в черновик карточки.</div>}
        {d && !d.review_state && <div>
          <div className="hint">Согласует: {s.will_review.join(", ") || "некому - назначьте менеджера артикула"}. Ему придёт уведомление в Telegram.</div>
          {s.can_edit && <button className="pri" disabled={busy || dirty} onClick={submit}>📝 Отправить на согласование</button>}</div>}
        {d?.review_state === "pending" && <div>
          <div>⏳ Ждёт согласования: {d.reviewers.join(", ")}</div>
          {d.can_review && <div className="seo-rv">
            <button className="pri" disabled={busy || !!s.why_not} onClick={approve}>✅ Согласовать и загрузить в WB</button>
            <input placeholder="что исправить" value={back} onChange={(e) => setBack(e.target.value)} />
            <button disabled={busy || !back.trim()} onClick={sendBack}>↩️ Вернуть с комментарием</button></div>}
        </div>}
        {d?.review_state === "returned" && <div>
          <div className="t-bad">↩️ Вернули на доработку ({d.reviewed_by}): {d.review_comment}</div>
          {s.can_edit && s.ai && <button disabled={running} onClick={() => write(d.review_comment || "")}>✨ Переписать по замечанию</button>}
          {s.can_edit && <button className="pri" disabled={busy || dirty} onClick={submit}>📝 Отправить снова</button>}</div>}
        {s.can_edit && s.ai && d && <div className="seo-rv"><input placeholder="своё уточнение для ИИ (например: больше про подарок)" value={note}
          onChange={(e) => setNote(e.target.value)} /><button disabled={running || !note.trim()} onClick={() => write(note)}>✨ Переписать с уточнением</button></div>}
      </div>
    </div>
  );
}

function Rules({ shop, onBack }: { shop: number; onBack: () => void }) {
  type R = { nm_id: number; text: string; default: string; can_edit: boolean; custom: { nm_id: number; vendor_code: string | null; title: string | null }[] };
  const [nm, setNm] = useState(0);
  const [nmIn, setNmIn] = useState("");
  const [r, setR] = useState<R | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { http.get<R>(`/api/shops/${shop}/seo_rules?nm=${nm}`).then(setR).catch((e) => setErr(e.message)); }, [shop, nm]);
  if (!r) return <div className="hint">Загрузка…</div>;
  const save = () => http.put(`/api/shops/${shop}/seo_rules`, { nm_id: nm, text: r.text })
    .then(() => { setMsg("Сохранено"); setTimeout(() => setMsg(""), 2000); }).catch((e) => setErr(e.message));
  return (
    <div className="reviews rv-rules">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ к SEO</button><h2>📋 Правила SEO</h2></div>
      <div className="hint">ИИ перед каждым текстом читает эти правила. Правила товара дополняют правила магазина; свои правила важнее общих.</div>
      <div className="acc-box"><b>Общие правила (всегда)</b><div className="hint" style={{ whiteSpace: "pre-wrap" }}>{r.default}</div></div>
      <div className="rv-filters">
        <button className={"chip" + (nm === 0 ? " on" : "")} onClick={() => setNm(0)}>Весь магазин</button>
        {r.custom.map((x) => <button key={x.nm_id} className={"chip" + (nm === x.nm_id ? " on" : "")} onClick={() => setNm(x.nm_id)}>{x.vendor_code || x.nm_id}</button>)}
        <input placeholder="Артикул WB для своих правил" value={nmIn} onChange={(e) => setNmIn(e.target.value.replace(/\D/g, ""))} />
        <button disabled={!nmIn} onClick={() => { setNm(Number(nmIn)); setNmIn(""); }}>+ правила товара</button>
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok">{msg}</div>}
      <div className="acc-box">
        <b>{nm ? `Товар ${nm}` : "Весь магазин"}: свои правила и уточнения</b>
        <textarea rows={8} disabled={!r.can_edit} placeholder={"Например:\n- бренд писать «Example» без кавычек\n- не упоминать скидки и акции\n- в конце - призыв добавить в избранное\n- для этого товара подчеркнуть: подходит как подарок"}
          value={r.text} onChange={(e) => setR({ ...r, text: e.target.value })} />
        {r.can_edit && <div><button className="pri" onClick={save}>Сохранить правила</button></div>}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { api, http, type Article } from "./api";
import { copyCell } from "./copy";
import { RenderModels, useRenderSelection, modelsReady, estimateText, confirmRetouch, type RenderModel, type RenderEstimate } from "./visualBilling";

/** Модуль «Визуал» : по регламенту инфографики — исходники и паспорт → конкуренты → товар и ЦА → цели и воронки → ТЗ
 * (правка, согласование, «База ТЗ»). Отрисовка (Higgsfield) — следующим этапом. */
type Job = { state: "running" | "done" | "error"; error: string | null; summary: string | null; started_at: string; finished_at: string | null };
type QA = { q: string; a: string[] };
type Goal = { id: string; title: string; why?: string; headline?: string; kind?: string; applicable?: boolean };
type Funnel = { name: string; idea?: string; slides: string[] };
type FirstVar = { style: string; approach?: string; triggers?: string[]; why?: string };
type Comp = { id: number; name?: string; brand?: string; src?: string; proceeds?: number; rating?: number; reviews?: number; first_slide?: string;
  slides?: { n: number; goal: string; style?: string; emotion?: string; pain?: string }[]; weak?: string; tricks?: string[]; praise?: string[]; complaints?: string[] };
type Summary = Record<string, string[]>;
type Slide = { goal_id?: string; goal?: string; headline?: string; texts?: string[]; how?: string[]; needs?: string; composition?: string;
  background?: string; sources?: number[]; specs_check?: string[]; prompt?: string };
type First = { variant?: number; style?: string; headline?: string; triggers?: string[]; composition?: string; background?: string; sources?: number[];
  how?: string[]; prompt?: string };
type BriefData = { header?: Record<string, string | string[]>; first_slides?: First[]; slides?: Slide[]; funnels?: Funnel[]; adapted_from?: { brief: number; nm: number | null; title: string } };
type Brief = { id: number; version: number; state: "draft" | "pending" | "approved" | "returned"; data: BriefData; review_comment: string | null;
  reviewers_names: string[]; reviewed_by_name: string; can_review: boolean; updated_at: string };
type Ver = { id: number; version: number; state: string; kind: string; updated_at: string; slides: number };
type FileRow = { id: number; name: string; size: number; origin: string | null; meta: { w?: number; h?: number } };
type Pass = { id: number; name: string; models: { name: string }[] | null; state: string | null; used: number };
type St = {
  project: { id: number; nm_id: number | null; title: string; description: string; main_key: string | null; passport_model: string | null;
    passport_guess: { model?: string; why?: string } | null; competitors: { items?: Comp[]; summary?: Summary; main_key?: string; manual?: number[] };
    answers: Record<string, QA[] | string[] | string> & { pains?: string[] }; goals: { goals?: Goal[]; funnels?: Funnel[]; first_variants?: FirstVar[]; first_n?: number };
    note: string | null };
  vendor_code: string | null; sources: FileRow[]; passport: { id: number; name: string; models: string[]; state: string | null; specs: string | null } | null;
  passports: Pass[]; jobs: Record<string, Job>; brief: Brief | null; versions: Ver[]; questions: { groups: Record<string, string>; q: Record<string, string[]> };
  can_edit: boolean; ai: boolean; will_review: string[]; render_models: RenderModel[];
};
type Row = { id: number; nm_id: number | null; title: string; vendor_code: string | null; subject: string | null; sources: number; briefs: number | null;
  brief_state: string | null; passport: boolean; photo: string | null; updated_at: string };

const STEPS: [string, string][] = [["passport", "Паспорт"], ["competitors", "Конкуренты"], ["answers", "Товар и ЦА"], ["goals", "Цели и воронки"], ["brief", "ТЗ"],
  ["render", "Отрисовка"]];
const BST: Record<string, string> = { draft: "черновик", pending: "⏳ на согласовании", approved: "✅ согласовано", returned: "↩️ на доработке" };
const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export function VisualBlock({ shop }: { shop: number }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [pend, setPend] = useState(0);
  const [canEdit, setCanEdit] = useState(false);
  const [pid, setPid] = useState<number | null>(null);
  const [view, setView] = useState<"list" | "new" | "base" | "brand" | "gallery">("list");
  const [err, setErr] = useState("");
  const load = () => http.get<{ rows: Row[]; pending: number; can_edit: boolean }>(`/api/shops/${shop}/visual`)
    .then((r) => { setRows(r.rows); setPend(r.pending); setCanEdit(r.can_edit); }).catch((e) => setErr(e.message));
  useEffect(() => { setPid(null); setView("list"); load(); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const go = (e: Event) => setPid((e as CustomEvent<number>).detail);
    window.addEventListener("ais:vis-open", go); return () => window.removeEventListener("ais:vis-open", go);
  }, []);
  if (pid) return <Project key={pid} shop={shop} pid={pid} onBack={() => { setPid(null); load(); }} />;
  if (view === "new") return <NewProject shop={shop} onBack={() => setView("list")} onDone={(id) => { setView("list"); setPid(id); }} />;
  if (view === "base") return <Base shop={shop} onBack={() => setView("list")} onOpen={setPid} />;
  if (view === "brand") return <Brand shop={shop} onBack={() => setView("list")} />;
  if (view === "gallery") return <Gallery shop={shop} onBack={() => setView("list")} onOpen={setPid} />;
  return (
    <div className="cards">
      <div className="rv-head"><h2>🎨 Визуал</h2>
        {canEdit && <button className="pri" onClick={() => setView("new")}>＋ Новый товар</button>}
        <button className="link" onClick={() => setView("gallery")}>🖼 База фото</button>
        <button className="link" onClick={() => setView("base")}>📚 База ТЗ{pend ? ` (на согласовании: ${pend})` : ""}</button>
        <button className="link" onClick={() => setView("brand")}>🎨 Стиль бренда и паспорта</button></div>
      <div className="hint">Слайды карточки по регламенту инфографики: исходники и паспорт → разбор слайдов конкурентов → ответы на вопросы о товаре и ЦА →
        цели слайдов и воронки → ТЗ (менеджер правит и согласует). Дальше — отрисовка слайдов, доработка и «База фото».</div>
      {err && <div className="err">{err}</div>}
      {!rows.length && <div className="hint">Пока нет товаров в работе — нажмите «＋ Новый товар».</div>}
      <div className="cd-list">{rows.map((r) => (
        <button key={r.id} className="cd-item" onClick={() => setPid(r.id)}>
          {r.photo ? <img src={r.photo} alt="" /> : <span className="cd-noimg" />}
          <span><b>{r.vendor_code || r.title}</b><br />
            <span className="hint">{r.nm_id ? <span className="copy-cell" title="Нажмите, чтобы скопировать артикул"
              onClick={(e) => { e.stopPropagation(); copyCell(r.nm_id, e.nativeEvent); }}>{r.nm_id}</span> : "новый товар"} · исходников {r.sources}{r.passport ? " · паспорт" : ""}
              {r.briefs ? ` · ТЗ v${r.briefs} ${BST[r.brief_state || "draft"] || ""}` : ""}</span></span>
        </button>))}</div>
    </div>
  );
}

function NewProject({ shop, onBack, onDone }: { shop: number; onBack: () => void; onDone: (id: number) => void }) {
  const [arts, setArts] = useState<Article[]>([]);
  const [q, setQ] = useState("");
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api.articles(shop).then(setArts).catch(() => setArts([])); }, [shop]);
  const ql = q.trim().toLowerCase();
  const list = useMemo(() => arts.filter((a) => !ql || String(a.nm_id).includes(ql) || (a.vendor_code || "").toLowerCase().includes(ql)
    || (a.title || "").toLowerCase().includes(ql)).slice(0, 120), [arts, ql]);
  const make = (nm_id: number | null) => http.post<{ id: number }>(`/api/shops/${shop}/visual`, { nm_id, title, description: desc })
    .then((r) => onDone(r.id)).catch((e) => setErr(e.message));
  return (
    <div className="cards">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ назад</button><h2>＋ Новый товар для визуала</h2></div>
      {err && <div className="err">{err}</div>}
      <div className="acc-box"><b>Товар, которого ещё нет на сайте</b>
        <label className="seo-f">Что это за товар<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="например: Шуруповёрт аккумуляторный 18В" /></label>
        <label className="seo-f">Кратко о товаре<textarea rows={4} value={desc} onChange={(e) => setDesc(e.target.value)}
          placeholder="что умеет, для кого, комплектация, чем лучше конкурентов…" /></label>
        <button className="pri" disabled={!title.trim()} onClick={() => make(null)}>Создать</button></div>
      <div className="acc-box"><b>Или выберите артикул магазина</b>
        <input className="cd-q" placeholder="Поиск: артикул WB, артикул продавца, название…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="cd-list">{list.map((a) => (
          <button key={a.nm_id} className="cd-item" onClick={() => make(a.nm_id)}>
            {a.photo ? <img src={a.photo} alt="" /> : <span className="cd-noimg" />}
            <span><b>{a.vendor_code || a.nm_id}</b><br /><span className="hint">{a.nm_id} · {a.title || a.subject}</span></span>
          </button>))}</div></div>
    </div>
  );
}

function Project({ shop, pid, onBack }: { shop: number; pid: number; onBack: () => void }) {
  const paymentPending = useRef(false);
  const [s, setS] = useState<St | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState("");
  const [plink, setPlink] = useState("");
  const [firstN, setFirstN] = useState(3);
  const [autoMods, setAutoMods] = useRenderSelection(`${shop}/${pid}`, s?.render_models);
  const [autoScope, setAutoScope] = useState<"all" | "first">("all");
  const [tab, setTab] = useState<"src" | "comp" | "qa" | "goals" | "brief" | "render" | "photos" | "retouch">("src");
  const url = `/api/shops/${shop}/visual/${pid}`;
  const load = () => http.get<St>(url).then(setS).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const running = !!s && Object.values(s.jobs).some((j) => j.state === "running");
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => http.get<St>(url).then(setS).catch(() => undefined), 5000);
    return () => window.clearInterval(t);
  }, [running, url]);
  if (!s) return <div className="cards">{err ? <div className="err">{err}</div> : <div className="hint">Загрузка…</div>}</div>;
  const p = s.project;
  const fail = (e: Error) => { setErr(e.message); paymentPending.current = false; setBusy(false); };
  const ok = (m: string) => { setMsg(m); setErr(""); paymentPending.current = false; setBusy(false); setTimeout(() => setMsg(""), 4000); };
  const edit = (b: Record<string, unknown>) => http.put<St>(url, b).then(setS).catch(fail);
  const run = (steps: string[]) => { setErr(""); http.post<St>(`${url}/run`, { steps, first_n: firstN }).then(setS).catch(fail); };
  const ALL = ["competitors", "answers", "goals", "brief"];
  const runDraw = async () => {
    if (paymentPending.current) return;
    paymentPending.current = true; setBusy(true); setErr("");
    try {
      const e = await http.post<RenderEstimate>(`${url}/render/estimate`, { models: autoMods, edit_n: 1 });
      const price = estimateText(e);
      const what = autoScope === "first" ? `${firstN} вариантов первого слайда` : `${firstN} вариантов первого слайда + все слайды ТЗ (обычно 10–15)`;
      if (!window.confirm(`Пройти все шаги, считать ТЗ согласованным и сразу нарисовать: ${what} — по 1 картинке на каждую нейросеть.\n`
        + `Цена одной картинки: ${price}.\nЗапустить?`)) return;
      setS(await http.post<St>(`${url}/run`, { steps: ALL, first_n: firstN, render_models: autoMods, render_scope: autoScope }));
    } catch (e) { fail(e as Error); } finally { paymentPending.current = false; setBusy(false); }
  };
  const upload = async (fl: FileList | null, kind: "source" | "passport") => {
    if (!fl?.length) return;
    setBusy(true); setErr("");
    let n = 0;
    for (const f of Array.from(fl)) {
      const r = await fetch(`${url}/files?kind=${kind}&name=${encodeURIComponent(f.name)}`, { method: "POST", body: f, credentials: "same-origin" });
      if (!r.ok) { const t = await r.json().catch(() => ({ detail: r.statusText })); setErr(`${f.name}: ${t.detail}`); } else n++;
      if (kind === "passport") break;
    }
    ok(kind === "passport" ? "Паспорт загружен — ИИ разбирает модели" : `Загружено: ${n}`); load();
  };
  const fromLink = (kind: "source" | "passport") => { setBusy(true); setErr("");
    http.post<{ saved: number; skipped: string[] }>(`${url}/link`, { url: kind === "source" ? link : plink, kind }).then((r) => {
      ok(kind === "passport" ? "Паспорт скачан — ИИ разбирает модели" : `Скачано: ${r.saved}` + (r.skipped.length ? ` (пропущено: ${r.skipped.length})` : ""));
      setLink(""); setPlink(""); load(); }).catch(fail); };
  const fromCard = () => { setBusy(true); http.post<{ saved: number }>(`${url}/from_card`).then((r) => { ok(`Фото с карточки: ${r.saved}`); load(); }).catch(fail); };
  const delFile = (id: number) => http.del(`${url}/files/${id}`).then(load).catch(fail);
  const jobLine = (k: string) => { const j = s.jobs[k]; if (!j) return null;
    const min = j.started_at ? Math.max(0, Math.round((Date.now() - new Date(j.started_at).getTime()) / 60000)) : null;
    return <span className={j.state === "error" ? "t-bad" : "hint"}>{j.state === "running"
      ? `⏳ ${j.summary || "работаю…"}${j.summary !== "в очереди" && min != null ? ` · ${min} мин` : ""}` : j.state === "error" ? `❌ ${j.error}` : `✅ ${j.summary || ""}`}</span>; };
  const tabs: [typeof tab, string][] = [["src", "0. Исходники и паспорт"], ["comp", "1. Конкуренты"], ["qa", "2. Товар и ЦА"], ["goals", "3. Цели и воронки"],
    ["brief", "4. ТЗ"], ["render", "5. Отрисовка"], ["photos", "6. База фото"], ["retouch", "7. Доработка фото"]];
  return (
    <div className="cards vis">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ к товарам</button>
        <h2>🎨 {s.vendor_code || p.title}</h2>
        {p.nm_id && <><span className="copy-cell hint" title="Нажмите, чтобы скопировать артикул" onClick={(e) => copyCell(p.nm_id, e.nativeEvent)}>{p.nm_id}</span>
          <button className="link" onClick={() => window.dispatchEvent(new CustomEvent("ais:cards", { detail: p.nm_id }))}>🃏 Открыть в «Карточках»</button>
          <a href={`https://www.wildberries.ru/catalog/${p.nm_id}/detail.aspx`} target="_blank" rel="noreferrer">на WB ↗</a></>}</div>
      {err && <div className="err" style={{ whiteSpace: "pre-wrap" }}>{err}</div>}
      {msg && <div className="ok">{msg}</div>}
      <div className="acc-box vis-run">
        <b>Нейросеть</b>{" "}
        {s.can_edit && s.ai && <>
          <label className="hint">вариантов первого слайда <select value={firstN} onChange={(e) => setFirstN(Number(e.target.value))}>
            {[1, 2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>{" "}
          <button className="pri" disabled={running || busy} onClick={() => run(ALL)}>
            {running ? "⏳ работаю… (каждый шаг 1-5 минут)" : "▶ Все шаги до отрисовки: конкуренты → вопросы → цели → ТЗ"}</button>
          {!running && <div className="rnp-bar vis-auto">
            <button className="pri" disabled={busy || !modelsReady(s.render_models, autoMods)} onClick={runDraw}>🚀 Все шаги + отрисовка</button>
            <RenderModels models={s.render_models} value={autoMods} onChange={setAutoMods} disabled={busy} />
            <select value={autoScope} onChange={(e) => setAutoScope(e.target.value as "all" | "first")}>
              <option value="all">все слайды</option><option value="first">только первый слайд</option></select>
            <span className="hint">ТЗ будет считаться согласованным без менеджера</span></div>}</>}
        {!s.ai && <span className="hint"> нейросеть недоступна для этого кабинета</span>}
        <div className="vis-steps">{STEPS.map(([k, t]) => s.jobs[k] && <div key={k}><b>{t}:</b> {jobLine(k)}</div>)}</div>
      </div>
      <div className="rnp-bar">{tabs.map(([k, t]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{t}</button>)}</div>

      {tab === "src" && <>
        <div className="acc-box"><b>Товар</b>
          <label className="seo-f">Название<input defaultValue={p.title} disabled={!s.can_edit} onBlur={(e) => e.target.value !== p.title && edit({ title: e.target.value })} /></label>
          <label className="seo-f">Кратко о товаре<textarea rows={3} defaultValue={p.description} disabled={!s.can_edit}
            onBlur={(e) => e.target.value !== p.description && edit({ description: e.target.value })} /></label>
          <label className="seo-f">Основной поисковый запрос (крупно на первый слайд)<input defaultValue={p.main_key || ""} disabled={!s.can_edit}
            placeholder="ИИ возьмёт из SEO-ядра / Джема" onBlur={(e) => e.target.value !== (p.main_key || "") && edit({ main_key: e.target.value })} /></label>
          <label className="seo-f">Уточнения для нейросети<textarea rows={2} defaultValue={p.note || ""} disabled={!s.can_edit}
            placeholder="например: упор на подарок; не показывать детей; фирменный жёлтый" onBlur={(e) => e.target.value !== (p.note || "") && edit({ note: e.target.value })} /></label>
        </div>
        <div className="acc-box"><b>Исходники фото ({s.sources.length})</b>
          <div className="hint">Фото товара, коробки и комплектации — нейросеть будет рисовать слайды строго по ним, внешний вид товара не меняется.</div>
          {s.can_edit && <div className="rnp-bar">
            <label className="vis-up">📤 Загрузить фото<input type="file" accept="image/*" multiple hidden onChange={(e) => upload(e.target.files, "source")} /></label>
            <input placeholder="ссылка на папку/фото: Google Диск, Яндекс Диск" value={link} onChange={(e) => setLink(e.target.value)} style={{ minWidth: 280 }} />
            <button disabled={busy || !link.trim()} onClick={() => fromLink("source")}>Скачать</button>
            {p.nm_id && <button disabled={busy} onClick={fromCard}>📥 Фото с карточки WB</button>}</div>}
          <div className="vis-grid">{s.sources.map((f) => <div key={f.id} className="vis-th">
            <a href={`/api/shops/${shop}/visual_file/${f.id}`} target="_blank" rel="noreferrer">
              <img src={`/api/shops/${shop}/visual_file/${f.id}?thumb=1`} alt={f.name} loading="lazy" style={{ cursor: "zoom-in" }} /></a>
            <span className="hint">#{f.id} · {f.meta?.w}×{f.meta?.h}</span>
            {s.can_edit && <button className="link" title="удалить" onClick={() => delFile(f.id)}>✕</button>}</div>)}</div>
        </div>
        <div className="acc-box"><b>Паспорт товара</b> <span className="hint">(необязательно) — характеристики на слайды берём только из него</span>
          {s.passport ? <div>
            📄 <a href={`/api/shops/${shop}/visual_file/${s.passport.id}`} target="_blank" rel="noreferrer">{s.passport.name}</a>{" "}
            {s.jobs.passport?.state === "running" && <span className="hint">⏳ ИИ разбирает паспорт…</span>}
            {s.passport.models.length > 0 && <div className="seo-f">
              <span>Наша модель {p.passport_model ? "✅" : "— подтвердите"}{p.passport_guess?.model && !p.passport_model &&
                <span className="hint"> (ИИ думает: «{p.passport_guess.model}» — {p.passport_guess.why})</span>}</span>
              <select value={p.passport_model || ""} disabled={!s.can_edit} onChange={(e) => edit({ passport_model: e.target.value })}>
                <option value="">— выберите модель —</option>
                {s.passport.models.map((m) => <option key={m} value={m}>{m}</option>)}</select>
              {p.passport_guess?.model && !p.passport_model && s.can_edit &&
                <button onClick={() => edit({ passport_model: p.passport_guess!.model })}>✅ Да, это «{p.passport_guess.model}»</button>}
              {s.passport.specs && <details><summary className="hint">Характеристики модели</summary>
                <div className="hint" style={{ whiteSpace: "pre-wrap" }}>{s.passport.specs}</div></details>}</div>}
            {s.can_edit && <button className="link" onClick={() => http.put<St>(`${url}/passport`, { file_id: null }).then(setS).catch(fail)}>отвязать</button>}
          </div> : <div className="hint">Паспорта нет — характеристики возьмём из карточки и пометим «проверить».</div>}
          {s.can_edit && <div className="rnp-bar">
            <label className="vis-up">📤 Загрузить паспорт<input type="file" accept=".pdf,.docx,.xlsx,.txt,image/*" hidden onChange={(e) => upload(e.target.files, "passport")} /></label>
            <input placeholder="или ссылка: Google Диск/Документ, Яндекс Диск" value={plink} onChange={(e) => setPlink(e.target.value)} style={{ minWidth: 260 }} />
            <button disabled={busy || !plink.trim()} onClick={() => fromLink("passport")}>Скачать</button>
            {s.passports.filter((x) => x.id !== s.passport?.id).length > 0 &&
              <select value="" onChange={(e) => e.target.value && http.put<St>(`${url}/passport`, { file_id: Number(e.target.value) }).then(setS).catch(fail)}>
                <option value="">общий паспорт магазина…</option>
                {s.passports.filter((x) => x.id !== s.passport?.id).map((x) => <option key={x.id} value={x.id}>{x.name} ({x.used} тов.)</option>)}</select>}</div>}
        </div>
      </>}

      {tab === "comp" && <Competitors s={s} edit={edit} run={run} running={running} />}
      {tab === "qa" && <Answers s={s} edit={edit} run={run} running={running} />}
      {tab === "goals" && <Goals s={s} edit={edit} run={run} running={running} />}
      {tab === "brief" && <BriefView shop={shop} s={s} setS={setS} url={url} run={run} running={running} fail={fail} ok={ok} toRender={() => setTab("render")} />}
      {tab === "render" && <Render shop={shop} url={url} />}
      {tab === "photos" && <Photos shop={shop} s={s} url={url} />}
      {tab === "retouch" && <Retouch shop={shop} s={s} url={url} />}
    </div>
  );
}

type Sub = { s: St; edit: (b: Record<string, unknown>) => Promise<void>; run: (steps: string[]) => void; running: boolean };

function Competitors({ s, edit, run, running }: Sub) {
  const c = s.project.competitors || {};
  const [add, setAdd] = useState("");
  const sm = c.summary || {};
  const SUM: [string, string][] = [["styles", "Стили первых слайдов в нише"], ["common_goals", "Частые цели слайдов"], ["gaps", "Что никто не закрывает — наша возможность"],
    ["best_tricks", "Лучшие необычные ходы"], ["praise", "Что хвалят"], ["complaints", "За что ругают"], ["stand_out", "Как нам отстроиться"]];
  return (<>
    <div className="acc-box"><b>1. Разбор слайдов конкурентов</b>{" "}
      {s.can_edit && s.ai && <button disabled={running} onClick={() => run(["competitors"])}>{c.items ? "🔄 Разобрать заново" : "🔍 Разобрать"}</button>}
      <div className="hint">Берём лидеров выдачи по основному запросу{c.main_key ? ` «${c.main_key}»` : ""}, похожие товары с наибольшей выручкой (Wildbox)
        и ваш список конкурентов. ИИ смотрит первые 8 слайдов каждого и отзывы.</div>
      {s.can_edit && <div className="rnp-bar"><input placeholder="артикул WB конкурента" value={add} onChange={(e) => setAdd(e.target.value.replace(/\D/g, ""))} />
        <button disabled={!add} onClick={() => { edit({ comp_add: Number(add) }); setAdd(""); }}>+ добавить в разбор</button></div>}
      {SUM.map(([k, t]) => (sm[k] || []).length > 0 && <div key={k}><b>{t}:</b><ul>{sm[k].map((x, i) => <li key={i}>{x}</li>)}</ul></div>)}
    </div>
    {(c.items || []).map((x) => <details key={x.id} className="acc-box">
      <summary><b>{x.name || x.id}</b> <span className="hint">{x.brand} · {x.src}{x.rating ? ` · ★${x.rating} (${x.reviews})` : ""}</span>{" "}
        <a href={`https://www.wildberries.ru/catalog/${x.id}/detail.aspx`} target="_blank" rel="noreferrer">{x.id} ↗</a>
        {s.can_edit && <button className="link" onClick={(e) => { e.preventDefault(); edit({ comp_remove: x.id }); }}>убрать</button>}</summary>
      {x.first_slide && <div><b>Первый слайд:</b> {x.first_slide}</div>}
      <table className="rnp-t"><thead><tr><th>№</th><th>Цель</th><th>Стиль</th><th>Эмоция</th><th>Боль</th></tr></thead>
        <tbody>{(x.slides || []).map((y) => <tr key={y.n}><td>{y.n}</td><td>{y.goal}</td><td>{y.style}</td><td>{y.emotion}</td><td>{y.pain}</td></tr>)}</tbody></table>
      {x.weak && <div><b>Слабое:</b> {x.weak}</div>}
      {(x.tricks || []).length > 0 && <div><b>Необычные ходы:</b> {x.tricks!.join("; ")}</div>}
      {(x.praise || []).length > 0 && <div><b>Хвалят:</b> {x.praise!.join("; ")}</div>}
      {(x.complaints || []).length > 0 && <div><b>Ругают:</b> {x.complaints!.join("; ")}</div>}
    </details>)}
  </>);
}

function Answers({ s, edit, run, running }: Sub) {
  const a = s.project.answers || {};
  const [d, setD] = useState<Record<string, string>>({});
  const key = (g: string, i: number) => `${g}:${i}`;
  const save = () => {
    const out: Record<string, unknown> = { ...a };
    for (const g of Object.keys(s.questions.q)) {
      out[g] = ((a[g] as QA[]) || []).map((x, i) => ({ q: x.q, a: d[key(g, i)] !== undefined ? lines(d[key(g, i)]) : x.a }));
    }
    if (d.pains !== undefined) out.pains = lines(d.pains);
    edit({ answers: out }).then(() => setD({}));
  };
  return (<div className="acc-box"><b>2. Товар и целевая аудитория</b>{" "}
    {s.can_edit && s.ai && <button disabled={running} onClick={() => run(["answers"])}>{a.product ? "🔄 Ответить заново" : "✨ Ответить на вопросы"}</button>}
    {Object.keys(d).length > 0 && <button className="pri" onClick={save}>Сохранить правки</button>}
    {!a.product && <div className="hint">ИИ ответит на все вопросы регламента — по карточке, паспорту, нашим отзывам и разбору конкурентов. Ответы можно править.</div>}
    {Object.entries(s.questions.groups).map(([g, t]) => ((a[g] as QA[]) || []).length > 0 && <div key={g}><h4>{t}</h4>
      {((a[g] as QA[]) || []).map((x, i) => <label key={i} className="seo-f">{x.q}
        <textarea rows={Math.min(8, (x.a || []).length + 1)} disabled={!s.can_edit} value={d[key(g, i)] ?? (x.a || []).join("\n")}
          onChange={(e) => setD({ ...d, [key(g, i)]: e.target.value })} /></label>)}</div>)}
    {(a.pains as string[] | undefined)?.length ? <label className="seo-f"><b>Боли клиента — от самой сильной к слабой (из них воронка 1)</b>
      <textarea rows={6} disabled={!s.can_edit} value={d.pains ?? (a.pains as string[]).join("\n")} onChange={(e) => setD({ ...d, pains: e.target.value })} /></label> : null}
  </div>);
}

function Goals({ s, edit, run, running }: Sub) {
  const g = s.project.goals || {};
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const cur = goals ?? g.goals ?? [];
  const byId = Object.fromEntries(cur.map((x) => [x.id, x]));
  const upd = (i: number, f: keyof Goal, v: string) => setGoals(cur.map((x, k) => k === i ? { ...x, [f]: v } : x));
  return (<>
    <div className="acc-box"><b>3. Цели слайдов и воронки</b>{" "}
      {s.can_edit && s.ai && <button disabled={running} onClick={() => run(["goals"])}>{g.goals ? "🔄 Пересобрать цели" : "✨ Сформулировать цели"}</button>}
      {goals && <button className="pri" onClick={() => edit({ goals: { ...g, goals } }).then(() => setGoals(null))}>Сохранить правки</button>}
      <div className="hint">Первый слайд всегда один: завлекающее фото товара + основной запрос. Целей — от 12, чтобы быстро менять слайды местами.
        Обязательно: товар в использовании; если есть подсветка — светится; сложная техника — футуристичные «внутренности».</div>
      {cur.length > 0 && <table className="rnp-t"><thead><tr><th>id</th><th>Цель</th><th>Надпись сверху</th><th>Зачем (боль/вопрос)</th><th>Тип</th></tr></thead>
        <tbody>{cur.map((x, i) => <tr key={x.id} style={x.applicable === false ? { opacity: 0.5 } : undefined}><td>{x.id}</td>
          <td><input value={x.title} disabled={!s.can_edit} onChange={(e) => upd(i, "title", e.target.value)} /></td>
          <td><input value={x.headline || ""} disabled={!s.can_edit} onChange={(e) => upd(i, "headline", e.target.value)} /></td>
          <td className="hint">{x.why}</td><td className="hint">{x.kind}{x.applicable === false ? " · не подходит" : ""}</td></tr>)}</tbody></table>}
    </div>
    {(g.funnels || []).length > 0 && <div className="acc-box"><b>Воронки (слайды 2–6)</b>
      {g.funnels!.map((f, i) => <div key={i} className="vis-funnel"><b>{f.name}</b> <span className="hint">{f.idea}</span>
        <ol start={2}>{f.slides.map((id) => <li key={id}>{byId[id]?.title || id} <span className="hint">«{byId[id]?.headline}»</span></li>)}</ol></div>)}</div>}
    {(g.first_variants || []).length > 0 && <div className="acc-box"><b>Варианты первого слайда ({g.first_variants!.length})</b>
      <ol>{g.first_variants!.map((f, i) => <li key={i}><b>{f.style}</b> — {f.approach} <span className="hint">{(f.triggers || []).join(", ")} · {f.why}</span></li>)}</ol></div>}
  </>);
}

/** «Применить это ТЗ к другому артикулу»: те же слайды и их суть, фото и характеристики — выбранного товара. */
function ApplyTo({ shop, bid, nm, fail }: { shop: number; bid: number; nm: number | null; fail: (e: Error) => void }) {
  const [open, setOpen] = useState(false);
  const [arts, setArts] = useState<Article[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open && !arts.length) api.articles(shop).then(setArts).catch(() => setArts([])); }, [open]);   // eslint-disable-line react-hooks/exhaustive-deps
  const ql = q.trim().toLowerCase();
  const list = arts.filter((a) => a.nm_id !== nm && (!ql || String(a.nm_id).includes(ql) || (a.vendor_code || "").toLowerCase().includes(ql)
    || (a.title || "").toLowerCase().includes(ql))).slice(0, 60);
  const go = (a: Article) => {
    if (!window.confirm(`Перенести это ТЗ на ${a.vendor_code || a.nm_id} (${a.nm_id})? Слайды и их суть останутся, фото и характеристики возьмутся с этого товара. ` +
      "Новое ТЗ придёт черновиком — его нужно проверить и согласовать.")) return;
    setBusy(true);
    http.post<{ project_id: number }>(`/api/shops/${shop}/visual_brief/${bid}/apply`, { nm_id: a.nm_id })
      .then((x) => { setBusy(false); setOpen(false); window.dispatchEvent(new CustomEvent("ais:vis-open", { detail: x.project_id })); })
      .catch((e) => { setBusy(false); fail(e); });
  };
  if (!open) return <div><button onClick={() => setOpen(true)}>📋 Применить это ТЗ к другому артикулу</button></div>;
  return <div className="acc-box"><b>На какой артикул перенести ТЗ?</b> <button className="link" onClick={() => setOpen(false)}>закрыть</button>
    <div className="hint">Слайды, их цели и стиль останутся теми же; фото-исходники (с карточки WB, если своих нет), характеристики и тексты — нового товара.
      Займёт несколько минут; откроется проект выбранного товара, ход — в шаге «ТЗ».</div>
    <input placeholder="Артикул, артикул продавца, название…" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
    <div className="cd-list">{list.map((a) => <button key={a.nm_id} className="cd-item" disabled={busy} onClick={() => go(a)}>
      <span><b>{a.vendor_code || a.nm_id}</b><br /><span className="hint">{a.nm_id} · {a.title || a.subject}</span></span></button>)}</div>
  </div>;
}

function BriefView({ shop, s, setS, url, run, running, fail, ok, toRender }: { shop: number; s: St; setS: (x: St) => void; url: string; run: (st: string[]) => void;
  running: boolean; fail: (e: Error) => void; ok: (m: string) => void; toRender: () => void }) {
  const b = s.brief;
  const [d, setD] = useState<BriefData | null>(null);
  const [back, setBack] = useState("");
  useEffect(() => { setD(null); }, [b?.id, b?.version]);
  const cur = d ?? b?.data ?? null;
  const save = () => d && http.put<St>(`${url}/brief`, { data: d }).then((x) => { setS(x); setD(null); ok("ТЗ сохранено"); }).catch(fail);
  const setSlide = (i: number, f: keyof Slide, v: string) => cur && setD({ ...cur, slides: (cur.slides || []).map((x, k) => k === i ? { ...x, [f]: f === "texts" ? lines(v) : v } : x) });
  const setFirst = (i: number, f: keyof First, v: string) => cur && setD({ ...cur, first_slides: (cur.first_slides || []).map((x, k) => k === i ? { ...x, [f]: f === "triggers" ? lines(v) : v } : x) });
  const review = (okk: boolean) => http.post<St>(`${url}/brief/review`, { ok: okk, comment: back }).then((x) => { setS(x); setBack(""); }).catch(fail);
  const h = cur?.header || {};
  return (<>
    <div className="acc-box"><b>4. ТЗ на отрисовку</b>{" "}
      {s.can_edit && s.ai && <button disabled={running} onClick={() => run(["brief"])}>{b ? "🔄 Собрать новую версию" : "✨ Собрать ТЗ"}</button>}
      {b && <> <span className="hint">версия {b.version} · {BST[b.state]} · {dt(b.updated_at)}</span>{" "}
        <a href={`/api/shops/${shop}/visual_brief/${b.id}/zip`}>⬇️ Скачать для дизайнера (ТЗ + исходники, архив)</a>{" "}
        <a href={`/api/shops/${shop}/visual_brief/${b.id}/text`}>⬇️ только текст</a></>}
      {b && s.can_edit && s.ai && <ApplyTo shop={shop} bid={b.id} nm={s.project.nm_id} fail={fail} />}
      {b?.data.adapted_from && <div className="hint">📋 Перенесено с ТЗ товара «{b.data.adapted_from.title}»{b.data.adapted_from.nm ? ` (${b.data.adapted_from.nm})` : ""} —
        проверьте тексты и цифры и отправьте на согласование.</div>}
      {d && <div><button className="pri" onClick={save}>Сохранить правки ТЗ</button>
        {b && b.state !== "draft" && b.state !== "returned" && <span className="hint"> — сохранится новой версией</span>}</div>}
      {!b && <div className="hint">Сначала шаги 1–3 (или «▶ Всё по порядку» сверху).</div>}
      {b?.state === "returned" && <div className="t-bad">↩️ Вернули ({b.reviewed_by_name}): {b.review_comment}</div>}
      {b && (b.state === "draft" || b.state === "returned") && s.can_edit && !d && <div>
        <span className="hint">Согласует: {s.will_review.join(", ") || "некому — назначьте менеджера артикула"}.</span>{" "}
        <button className="pri" onClick={() => http.post<St>(`${url}/brief/submit`).then(setS).catch(fail)}>📝 Отправить на согласование</button></div>}
      {b && b.state !== "approved" && s.can_edit && !d && <div><button className="pri" onClick={() => {
        if (window.confirm("Отправить ТЗ в отрисовку без согласования менеджером? ТЗ будет считаться согласованным вами."))
          http.post<St>(`${url}/brief/to_render`).then((x) => { setS(x); toRender(); }).catch(fail); }}>🎨 Отправить в отрисовку</button></div>}
      {b?.state === "pending" && <div>⏳ Ждёт согласования: {b.reviewers_names.join(", ")}
        {b.can_review && <div className="seo-rv"><button className="pri" onClick={() => review(true)}>✅ Согласовать ТЗ</button>
          <input placeholder="что исправить" value={back} onChange={(e) => setBack(e.target.value)} />
          <button disabled={!back.trim()} onClick={() => review(false)}>↩️ Вернуть</button></div>}</div>}
      {b?.state === "approved" && <div className="t-good">✅ Согласовано ({b.reviewed_by_name}) — <button className="pri" onClick={toRender}>🎨 К отрисовке</button></div>}
    </div>
    {cur && <div className="acc-box"><b>Шапка ТЗ</b>
      <ul>{((h.rules as string[]) || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
      {(["style", "palette", "fonts", "keep", "main_key"] as const).map((k) => h[k] ? <div key={k}><b>{({ style: "Стилистика", palette: "Палитра",
        fonts: "Шрифты", keep: "Нельзя менять", main_key: "Основной запрос" } as Record<string, string>)[k]}:</b> {String(h[k])}</div> : null)}</div>}
    {cur && (cur.first_slides || []).map((f, i) => <div key={`f${i}`} className="acc-box vis-slide"><b>Слайд 1 — вариант {f.variant ?? i + 1}: {f.style}</b>
      <label className="seo-f">Надпись (основной запрос)<input value={f.headline || ""} disabled={!s.can_edit} onChange={(e) => setFirst(i, "headline", e.target.value)} /></label>
      <label className="seo-f">Триггеры (1–2, по строке)<textarea rows={2} value={(f.triggers || []).join("\n")} disabled={!s.can_edit} onChange={(e) => setFirst(i, "triggers", e.target.value)} /></label>
      <label className="seo-f">Композиция<textarea rows={2} value={f.composition || ""} disabled={!s.can_edit} onChange={(e) => setFirst(i, "composition", e.target.value)} /></label>
      <label className="seo-f">Фон<input value={f.background || ""} disabled={!s.can_edit} onChange={(e) => setFirst(i, "background", e.target.value)} /></label>
      {(f.how || []).length > 0 && <ul className="hint">{f.how!.map((x, k) => <li key={k}>{x}</li>)}</ul>}
      <div className="hint">Исходники: {(f.sources || []).map((x) => `#${x}`).join(", ") || "—"}</div>
      <details><summary className="hint">Промпт для нейросети</summary><textarea rows={5} value={f.prompt || ""} disabled={!s.can_edit}
        onChange={(e) => setFirst(i, "prompt", e.target.value)} /></details></div>)}
    {cur && (cur.slides || []).map((x, i) => <div key={i} className="acc-box vis-slide"><b>Слайд {i + 2}: {x.goal}</b>
      <label className="seo-f">Надпись сверху<input value={x.headline || ""} disabled={!s.can_edit} onChange={(e) => setSlide(i, "headline", e.target.value)} /></label>
      <label className="seo-f">Другие тексты (по строке)<textarea rows={3} value={(x.texts || []).join("\n")} disabled={!s.can_edit} onChange={(e) => setSlide(i, "texts", e.target.value)} /></label>
      <label className="seo-f">Что нарисовать<textarea rows={3} value={x.composition || ""} disabled={!s.can_edit} onChange={(e) => setSlide(i, "composition", e.target.value)} /></label>
      <label className="seo-f">Фон / окружение<input value={x.background || ""} disabled={!s.can_edit} onChange={(e) => setSlide(i, "background", e.target.value)} /></label>
      {(x.how || []).length > 0 && <ul className="hint">{x.how!.map((y, k) => <li key={k}>{y}</li>)}</ul>}
      {x.needs && <div className="hint">Нужно: {x.needs}</div>}
      {(x.specs_check || []).length > 0 && <div className="t-bad">Сверить цифры: {x.specs_check!.join("; ")}</div>}
      <div className="hint">Исходники: {(x.sources || []).map((y) => `#${y}`).join(", ") || "—"}</div>
      <details><summary className="hint">Промпт для нейросети</summary><textarea rows={5} value={x.prompt || ""} disabled={!s.can_edit}
        onChange={(e) => setSlide(i, "prompt", e.target.value)} /></details></div>)}
    {s.versions.length > 1 && <div className="acc-box"><b>Все версии ТЗ</b>
      {s.versions.map((v) => <div key={v.id} className="hint">v{v.version} · {BST[v.state] || v.state} · слайдов {v.slides} · {dt(v.updated_at)}{" "}
        <a href={`/api/shops/${shop}/visual_brief/${v.id}/zip`}>⬇️ архив для дизайнера</a>{" "}
        <a href={`/api/shops/${shop}/visual_brief/${v.id}/text`}>⬇️ текстом</a></div>)}</div>}
  </>);
}

/** «🖼 База фото» магазина: всё отрисованное и доработанное по товарам, отметка «в базе», добавить в базу, открыть товар. */
function Gallery({ shop, onBack, onOpen }: { shop: number; onBack: () => void; onOpen: (pid: number) => void }) {
  type G = { file_id: number; title: string; model: string | null; task: string | null; project_id: number | null; project: string | null;
    nm_id: number | null; vendor_code: string | null; in_base: boolean; at: string; so: number };
  const [rows, setRows] = useState<G[] | null>(null);
  const [canEdit, setCanEdit] = useState(false);
  const [only, setOnly] = useState(false);
  const [q, setQ] = useState("");
  const [big, setBig] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const load = () => http.get<{ rows: G[]; can_edit: boolean }>(`/api/shops/${shop}/visual_gallery`).then((r) => { setRows(r.rows); setCanEdit(r.can_edit); })
    .catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [shop]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows) return <div className="hint">{err || "Загрузка…"}</div>;
  const ql = q.trim().toLowerCase();
  const list = rows.filter((x) => (!only || x.in_base) && (!ql || `${x.nm_id} ${x.vendor_code} ${x.project} ${x.title}`.toLowerCase().includes(ql)));
  const groups: [string, G[]][] = [];
  for (const x of list) { const k = String(x.project_id ?? "shared"); const g = groups.find((y) => y[0] === k); if (g) g[1].push(x); else groups.push([k, [x]]); }
  for (const [, g] of groups) g.sort((x, y) => x.so - y.so || x.at.localeCompare(y.at));
  const seq = groups.flatMap(([, g]) => g.map((x) => x.file_id));
  const toBase = (x: G) => x.project_id && http.post(`/api/shops/${shop}/visual/${x.project_id}/photos`, { file_ids: [x.file_id], shared: false }).then(load)
    .catch((e) => setErr(e.message));
  return (<div className="cards vis">
    <div className="rv-head"><button className="link" onClick={onBack}>‹ к товарам</button><h2>🖼 База фото</h2></div>
    <div className="hint">Всё, что отрисовано и доработано, по товарам. «✅ в базе» — одобрено: такие фото ставятся в карточку из «Карточек» → «＋ из базы фото».</div>
    {err && <div className="err">{err}</div>}
    <div className="rnp-bar"><input placeholder="Артикул, название…" value={q} onChange={(e) => setQ(e.target.value)} />
      <label><input type="checkbox" checked={only} onChange={() => setOnly(!only)} /> только одобренные в базу</label>
      <span className="hint">фото: {list.length}</span></div>
    {!list.length && <div className="hint">Пока ничего нет.</div>}
    {groups.map(([k, g]) => <div key={k} className="acc-box">
      <b>{g[0].project_id ? (g[0].vendor_code || g[0].project) : "Общие фото магазина"}</b>{g[0].nm_id && <span className="hint"> {g[0].nm_id}</span>}{" "}
      {g[0].project_id && <button className="link" onClick={() => onOpen(g[0].project_id!)}>открыть товар ›</button>}
      <div className="vis-grid">{g.map((x) => <div key={x.file_id} className="vis-th">
        <img src={`/api/shops/${shop}/visual_file/${x.file_id}?thumb=1`} alt="" onClick={() => setBig(x.file_id)} style={{ cursor: "zoom-in" }} />
        <span className="hint">{x.task ? `✏️ ${x.task.slice(0, 40)}` : x.title.slice(0, 50)}</span>
        {x.in_base ? <span className="t-good">✅ в базе</span>
          : canEdit && x.project_id && <button className="link vis-in" onClick={() => toBase(x)}>✅ в базу фото</button>}
      </div>)}</div></div>)}
    {big && <Lightbox shop={shop} fid={big} list={seq} onClose={() => setBig(null)} />}
  </div>);
}

function Base({ shop, onBack, onOpen }: { shop: number; onBack: () => void; onOpen: (pid: number) => void }) {
  type B = { id: number; project_id: number; nm_id: number | null; kind: string; version: number; state: string; title: string; vendor_code: string | null;
    slides: number; updated_at: string };
  const [rows, setRows] = useState<B[]>([]);
  useEffect(() => { http.get<{ rows: B[] }>(`/api/shops/${shop}/visual_briefs`).then((r) => setRows(r.rows)).catch(() => setRows([])); }, [shop]);
  const KIND: Record<string, string> = { graphics: "графика", rich: "рич-контент", video: "видео" };
  return (<div className="cards">
    <div className="rv-head"><button className="link" onClick={onBack}>‹ назад</button><h2>📚 База ТЗ</h2></div>
    <div className="hint">Все ТЗ по товарам со всеми версиями: графика (сейчас), рич-контент и видео (следующие этапы).</div>
    <table className="rnp-t"><thead><tr><th>Товар</th><th>Тип</th><th>Версия</th><th>Статус</th><th>Слайдов</th><th>Изменено</th><th></th></tr></thead>
      <tbody>{rows.map((r) => <tr key={r.id} className={r.state === "pending" ? "z-good" : ""}>
        <td><button className="link" onClick={() => onOpen(r.project_id)}><b>{r.vendor_code || r.title}</b></button><br /><span className="hint">{r.nm_id || "новый товар"}</span></td>
        <td>{KIND[r.kind] || r.kind}</td><td>v{r.version}</td><td>{BST[r.state] || r.state}</td><td>{r.slides}</td><td>{dt(r.updated_at)}</td>
        <td><a href={`/api/shops/${shop}/visual_brief/${r.id}/text`}>⬇️ текстом</a></td></tr>)}</tbody></table>
  </div>);
}

function Brand({ shop, onBack }: { shop: number; onBack: () => void }) {
  type Bd = { colors: string; fonts: string; notes: string; can_edit: boolean; passports: Pass[] };
  const [b, setB] = useState<Bd | null>(null);
  const [msg, setMsg] = useState("");
  useEffect(() => { http.get<Bd>(`/api/shops/${shop}/visual_brand`).then(setB).catch(() => setB(null)); }, [shop]);
  if (!b) return <div className="hint">Загрузка…</div>;
  const save = () => http.put(`/api/shops/${shop}/visual_brand`, b).then(() => { setMsg("Сохранено"); setTimeout(() => setMsg(""), 2000); });
  return (<div className="cards">
    <div className="rv-head"><button className="link" onClick={onBack}>‹ назад</button><h2>🎨 Стиль бренда и паспорта</h2></div>
    {msg && <div className="ok">{msg}</div>}
    <div className="acc-box"><b>Стиль бренда магазина</b> <span className="hint">— попадает в шапку каждого ТЗ</span>
      <label className="seo-f">Фирменные цвета<input value={b.colors} disabled={!b.can_edit} onChange={(e) => setB({ ...b, colors: e.target.value })}
        placeholder="например: жёлтый #FFD400, графит #2B2B2B" /></label>
      <label className="seo-f">Шрифты<input value={b.fonts} disabled={!b.can_edit} onChange={(e) => setB({ ...b, fonts: e.target.value })} placeholder="например: Montserrat Bold для заголовков" /></label>
      <label className="seo-f">Посыл, тон, что важно<textarea rows={4} value={b.notes} disabled={!b.can_edit} onChange={(e) => setB({ ...b, notes: e.target.value })}
        placeholder="например: премиальный, без кислотных цветов; логотип в правом нижнем углу не ставить" /></label>
      {b.can_edit && <button className="pri" onClick={save}>Сохранить</button>}</div>
    <div className="acc-box"><b>Паспорта магазина ({b.passports.length})</b> <span className="hint">— один паспорт можно привязать к нескольким товарам</span>
      {b.passports.map((x) => <div key={x.id} className="hint">📄 <a href={`/api/shops/${shop}/visual_file/${x.id}`} target="_blank" rel="noreferrer">{x.name}</a>
        {" "}· моделей {(x.models || []).length} · товаров {x.used}</div>)}</div>
  </div>);
}

type RItem = { slot: string; title: string; prompt: string; sources: number[] };
type RModel = RenderModel;
type Rend = { id: number; batch: string; slot: string; title: string; model: string; model_title?: string; state: "queued" | "running" | "done" | "error" | "canceled"; error: string | null;
  file_id: number | null; parent_id: number | null; task: string | null; zone?: number[] | null; created_at: string;
  check_res: { skipped?: boolean; product_ok?: boolean; product_diff?: string[]; text_ok?: boolean; text_errors?: string[]; corners_ok?: boolean } | null };
type Ph = { id: number; file_id: number; title: string; project_id: number | null; created_at: string; name: string };
type RSt = { plan: { brief: { id: number; version: number; state: string } | null; items: RItem[] }; models: RModel[]; renders: Rend[];
  photos: Ph[]; shared: Ph[]; can_edit: boolean };

function Render({ shop, url }: { shop: number; url: string }) {
  const paymentPending = useRef(false);
  const [r, setR] = useState<RSt | null>(null);
  const [mods, setMods] = useRenderSelection(url, r?.models);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [slots, setSlots] = useState<string[] | null>(null);
  const [per, setPer] = useState(1);
  const [est, setEst] = useState<{ key: string; quote: RenderEstimate } | null>(null);
  const [sel, setSel] = useState<number[]>([]);
  const [task, setTask] = useState("");
  const [busy, setBusy] = useState(false);
  const [big, setBig] = useState<number | null>(null);
  const load = () => http.get<RSt>(`${url}/render`).then(setR).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const live = !!r && r.renders.some((x) => x.state === "queued" || x.state === "running" || (x.state === "done" && !x.check_res));
  useEffect(() => { if (!live) return; const t = window.setInterval(load, 6000); return () => window.clearInterval(t); }, [live]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="hint">{err || "Загрузка…"}</div>;
  const items = r.plan.items;
  const picked = slots ?? items.map((x) => x.slot);
  const fail = (e: Error) => { setErr(e.message); paymentPending.current = false; setBusy(false); };
  const approved = r.plan.brief?.state === "approved";
  const quoteKey = JSON.stringify({ url, slots: picked, models: mods, per });
  const estimate = async () => { if (paymentPending.current) return; paymentPending.current = true; setBusy(true); setErr(""); setEst(null);
    try { const quote = await http.post<RenderEstimate>(`${url}/render/estimate`, { slots: picked, models: mods, per });
      setEst({ key: quoteKey, quote }); } catch (e) { fail(e as Error); } finally { paymentPending.current = false; setBusy(false); } };
  const draw = () => { if (paymentPending.current || est?.key !== quoteKey) return; paymentPending.current = true; setBusy(true); setErr(""); http.post(`${url}/render`, { slots: picked, models: mods, per })
    .then(() => { setMsg("Рисую — картинки появятся ниже по мере готовности (1–3 минуты каждая)"); setEst(null); paymentPending.current = false; setBusy(false); load(); }).catch(fail); };
  const doEdit = async () => { if (paymentPending.current) return; paymentPending.current = true; setBusy(true); setErr("");
    try { if (!await confirmRetouch(url, mods, sel.length)) return;
      await http.post(`${url}/render/edit`, { file_ids: sel, task, models: mods });
      setMsg(`Дорабатываю ${sel.length} фото`); setSel([]); setTask(""); load();
    } catch (e) { fail(e as Error); } finally { paymentPending.current = false; setBusy(false); } };
  const toBase = (shared: boolean) => http.post(`${url}/photos`, { file_ids: sel, shared })
    .then(() => { setMsg((shared ? "Добавлено в «Общие фото» магазина" : "Добавлено в «Базу фото» товара")
      + " — поставить в карточку: «Карточки» → «＋ из базы фото» (или вкладка «6. База фото» → «В карточку»)"); setSel([]); load(); }).catch(fail);
  const tog = (fid: number) => setSel(sel.includes(fid) ? sel.filter((x) => x !== fid) : [...sel, fid]);
  const groups: [string, Rend[]][] = [];
  for (const x of r.renders) { const g = groups.find((y) => y[0] === x.slot); if (g) g[1].push(x); else groups.push([x.slot, [x]]); }
  const order = (k: string) => k.startsWith("first:") ? Number(k.slice(6)) : k.startsWith("slide:") ? 100 + Number(k.slice(6)) : 999;
  groups.sort((a, b) => order(a[0]) - order(b[0]));
  const MT = Object.fromEntries(r.models.map((m) => [m.id, m.title]));
  const inBase = new Set(r.photos.map((p) => p.file_id));
  const ready = (list: Rend[]) => list.filter((x) => x.file_id && x.state === "done").map((x) => x.file_id!);
  const allReady = ready(r.renders);
  const selAll = (ids: number[]) => setSel(ids.every((f) => sel.includes(f)) ? sel.filter((f) => !ids.includes(f)) : [...new Set([...sel, ...ids])]);
  return (<>
    {err && <div className="err" style={{ whiteSpace: "pre-wrap" }}>{err}</div>}
    {msg && <div className="ok">{msg}</div>}
    <div className="acc-box"><b>5. Отрисовка по ТЗ</b>
      {!r.plan.brief && <div className="hint">Сначала соберите ТЗ (вкладка «4. ТЗ»).</div>}
      {r.plan.brief && !approved && <div className="t-bad">ТЗ v{r.plan.brief.version} ещё не согласовано — рисуем только по согласованному ТЗ.</div>}
      {r.can_edit && <RenderModels models={r.models} value={mods} disabled={busy} onChange={v => { setEst(null); setMods(v); }} />}
      {r.plan.brief && r.can_edit && <>
        <div className="rnp-bar">
          <label>вариантов на слайд <select value={per} onChange={(e) => { setPer(Number(e.target.value)); setEst(null); }}>{[1, 2, 3].map((n) => <option key={n}>{n}</option>)}</select></label></div>
        <div className="vis-slots">{items.map((it) => <label key={it.slot}><input type="checkbox" checked={picked.includes(it.slot)}
          onChange={() => { setEst(null); setSlots(picked.includes(it.slot) ? picked.filter((x) => x !== it.slot) : [...picked, it.slot]); }} /> {it.title}</label>)}</div>
        <div className="hint">Варианты первого слайда — в разных стилях для теста CTR; сколько их — задаётся на шаге «Цели» (1–6).
          Всего картинок: {picked.length * mods.length * per}.</div>
        {live && <button className="danger" disabled={busy} onClick={() => { if (window.confirm("Остановить отрисовку? Картинки в очереди и в работе будут отменены (уже начатые запросы могут быть оплачены у выбранного провайдера)."))
          http.post<{ stopped: number }>(`${url}/render/stop`).then((x) => { setMsg(`Остановлено: ${x.stopped}`); load(); }).catch(fail); }}>⏹ Остановить отрисовку</button>}{" "}
        <button disabled={busy || !approved || !picked.length || !modelsReady(r.models, mods)} onClick={estimate}>💰 Сколько стоит</button>{" "}
        {est?.key === quoteKey && <><div className="hint" style={{ whiteSpace: "pre-wrap" }}>{estimateText(est.quote)}</div>
          <button className="pri" disabled={busy} onClick={draw}>🎨 Рисовать {picked.length * mods.length * per} картинок</button></>}
      </>}
    </div>
    {allReady.length > 0 && r.can_edit && <div className="rnp-bar">
      <button onClick={() => selAll(allReady)}>{allReady.every((f) => sel.includes(f)) ? "☐ Снять все" : `☑ Выбрать все готовые (${allReady.length})`}</button>
      <span className="hint">в базе фото товара: {allReady.filter((f) => inBase.has(f)).length} из {allReady.length} · из базы фото ставятся в карточку в «Карточках» → «＋ из базы фото»</span></div>}
    {sel.length > 0 && r.can_edit && <div className="acc-box vis-selbar"><b>Выбрано фото: {sel.length}</b>
      <textarea rows={2} placeholder="Что сделать: например «перерисуй, добавив элементы для праздника Новый год» или «сделай фон светлее, надпись крупнее»"
        value={task} onChange={(e) => setTask(e.target.value)} />
      <div className="rnp-bar"><button className="pri" disabled={busy || !task.trim() || !modelsReady(r.models, mods)} onClick={doEdit}>✏️ Доработать выбранные</button>
        <button onClick={() => toBase(false)}>✅ Добавить в базу фото товара ({sel.length})</button><button onClick={() => toBase(true)}>⭐ В общие фото магазина</button>
        <button className="link" onClick={() => setSel([])}>снять выбор</button></div></div>}
    {groups.map(([slot, list]) => <div key={slot} className="acc-box"><b>{list[list.length - 1].title.replace(" · доработка", "")}</b>
      {r.can_edit && ready(list).length > 1 && <> <button className="link" onClick={() => selAll(ready(list))}>выбрать все в слайде</button></>}
      <div className="vis-grid">{list.map((x) => <div key={x.id} className={"vis-th" + (x.file_id && sel.includes(x.file_id) ? " on" : "")}>
        {x.file_id ? <img src={`/api/shops/${shop}/visual_file/${x.file_id}?thumb=1`} alt="" onClick={() => setBig(x.file_id)} style={{ cursor: "zoom-in" }} />
          : <div className="vis-wait">{x.state === "error" ? "❌" : x.state === "canceled" ? "⏹" : "⏳"}</div>}
        {x.file_id && r.can_edit && <label className="vis-pick"><input type="checkbox" checked={sel.includes(x.file_id)} onChange={() => tog(x.file_id!)} /> выбрать</label>}
        <span className="hint">{x.model_title || MT[x.model] || x.model}{x.task ? ` · ✏️ ${x.task.slice(0, 40)}` : ""}</span>
        {x.file_id && (inBase.has(x.file_id) ? <span className="t-good">✅ в базе</span>
          : r.can_edit && x.state === "done" && <button className="link vis-in" onClick={() => http.post(`${url}/photos`, { file_ids: [x.file_id], shared: false })
            .then(() => { setMsg("Добавлено в «Базу фото» товара"); load(); }).catch(fail)}>✅ в базу фото</button>)}
        {x.state === "error" && <span className="t-bad">{x.error}</span>}
        {x.check_res?.skipped && <span className="hint">Автопроверка недоступна — проверьте фото вручную</span>}
        {x.check_res && !x.check_res.skipped && <span className={x.check_res.product_ok && x.check_res.text_ok ? "t-good" : "t-bad"}
          title={[...(x.check_res.product_diff || []), ...(x.check_res.text_errors || [])].join("\n")}>
          {x.check_res.product_ok ? "товар ✓" : "товар изменён ⚠️"} · {x.check_res.text_ok ? "текст ✓" : "ошибки в тексте ⚠️"}</span>}
        {x.state === "done" && !x.check_res && <span className="hint">проверяю…</span>}
        {x.file_id && <a className="hint" href={`/api/shops/${shop}/visual_file/${x.file_id}`} target="_blank" rel="noreferrer">в новой вкладке ↗</a>}
        {r.can_edit && x.state !== "queued" && x.state !== "running" && <button className="link t-bad" onClick={() => {
          if (window.confirm("Удалить эту картинку насовсем?")) http.del(`${url}/render/${x.id}`).then(load).catch(fail); }}>🗑 удалить</button>}
      </div>)}</div></div>)}
    {big && <Lightbox shop={shop} fid={big} list={groups.flatMap(([, l]) => ready(l))} onClose={() => setBig(null)} />}
    {!r.renders.length && r.plan.brief && <div className="hint">Пока ничего не нарисовано. Нажмите на картинку, чтобы выбрать её для доработки или в базу.</div>}
    <div className="hint">Исходники тоже можно доработать: выберите их во вкладке «6. База фото».</div>
  </>);
}

function Photos({ shop, s, url }: { shop: number; s: St; url: string }) {
  const paymentPending = useRef(false);
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<RSt | null>(null);
  const [mods, setMods] = useRenderSelection(url, r?.models);
  const [sel, setSel] = useState<number[]>([]);
  const [task, setTask] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [big, setBig] = useState<number | null>(null);
  const load = () => http.get<RSt>(`${url}/render`).then(setR).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [url]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="hint">{err || "Загрузка…"}</div>;
  const tog = (fid: number) => setSel(sel.includes(fid) ? sel.filter((x) => x !== fid) : [...sel, fid]);
  const fail = (e: Error) => setErr(e.message);
  const card = (first: boolean) => http.post<{ added: number; nm_id: number }>(`${url}/to_card`, { file_ids: sel, first })
    .then((x) => { setMsg(`Добавлено в черновик карточки ${x.nm_id}: ${x.added} фото. Порядок и загрузка в WB — в «Карточках» (кнопка «Применить»).`); setSel([]); }).catch(fail);
  const edit = async () => { if (paymentPending.current) return; paymentPending.current = true; setBusy(true); setErr("");
    try { if (!await confirmRetouch(url, mods, sel.length)) return;
      await http.post(`${url}/render/edit`, { file_ids: sel, task, models: mods });
      setMsg("Дорабатываю — результат во вкладке «5. Отрисовка»"); setSel([]); setTask("");
    } catch (e) { fail(e as Error); } finally { paymentPending.current = false; setBusy(false); } };
  const del = (phid: number) => http.del(`/api/shops/${shop}/visual_photo/${phid}`).then(load).catch(fail);
  const grid = (list: { fid: number; ph?: number; label: string }[]) => <div className="vis-grid">{list.map((x) =>
    <div key={`${x.fid}-${x.ph || 0}`} className={"vis-th" + (sel.includes(x.fid) ? " on" : "")}>
      <img src={`/api/shops/${shop}/visual_file/${x.fid}?thumb=1`} alt="" onClick={() => setBig(x.fid)} style={{ cursor: "zoom-in" }} />
      {r.can_edit && <label className="vis-pick"><input type="checkbox" checked={sel.includes(x.fid)} onChange={() => tog(x.fid)} /> выбрать</label>}
      <span className="hint">{x.label}</span>
      <a className="hint" href={`/api/shops/${shop}/visual_file/${x.fid}`} target="_blank" rel="noreferrer">в новой вкладке ↗</a>
      {x.ph && r.can_edit && <button className="link t-bad" onClick={() => { if (window.confirm("Убрать это фото из базы?")) del(x.ph!); }}>🗑 убрать из базы</button>}</div>)}</div>;
  return (<>
    {err && <div className="err">{err}</div>}
    {msg && <div className="ok">{msg}</div>}
    {sel.length > 0 && r.can_edit && <div className="acc-box vis-selbar"><b>Выбрано: {sel.length}</b>
      <div className="rnp-bar">{s.project.nm_id && <><button className="pri" onClick={() => card(false)}>🖼 В карточку (в конец)</button>
        <button onClick={() => card(true)}>🖼 В карточку (в начало)</button></>}</div>
      <textarea rows={2} placeholder="или задание на доработку: «добавь новогодние элементы», «другой фон»…" value={task} onChange={(e) => setTask(e.target.value)} />
      <RenderModels models={r.models} value={mods} onChange={setMods} disabled={busy} />
      <div className="rnp-bar"><button disabled={busy || !task.trim() || !modelsReady(r.models, mods)} onClick={edit}>✏️ Доработать выбранные</button>
        <button className="link" onClick={() => setSel([])}>снять выбор</button></div></div>}
    <div className="acc-box"><b>Одобренные фото товара ({r.photos.length})</b>
      {r.can_edit && r.photos.length > 1 && <> <button className="link" onClick={() => { const ids = r.photos.map((p) => p.file_id);
        setSel(ids.every((f) => sel.includes(f)) ? sel.filter((f) => !ids.includes(f)) : [...new Set([...sel, ...ids])]); }}>выбрать все</button></>}
      {r.photos.length ? grid(r.photos.map((p) => ({ fid: p.file_id, ph: p.id, label: p.title }))) : <div className="hint">Одобрите картинки во вкладке «5. Отрисовка».</div>}</div>
    <div className="acc-box"><b>Общие фото магазина ({r.shared.length})</b> <span className="hint">— подходят к любому товару (например «Сервисные центры по России»)</span>
      {r.shared.length ? grid(r.shared.map((p) => ({ fid: p.file_id, ph: p.id, label: p.title }))) : <div className="hint">Пока пусто.</div>}</div>
    <div className="acc-box"><b>Исходники ({s.sources.length})</b>
      {grid(s.sources.map((f) => ({ fid: f.id, label: `#${f.id}` })))}</div>
    {big && <Lightbox shop={shop} fid={big} list={[...r.photos.map((p) => p.file_id), ...r.shared.map((p) => p.file_id), ...s.sources.map((f) => f.id)]} onClose={() => setBig(null)} />}
  </>);
}

/** «Доработка фото» : выбрать любые фото товара (нарисованные, одобренные, исходники и фото карточки), написать, что изменить, —
 *  нейросеть перерисует каждое от него самого; товар сверяется с исходниками. Результаты — ниже, их можно доработать ещё раз или взять в базу. */
function Retouch({ shop, s, url }: { shop: number; s: St; url: string }) {
  const paymentPending = useRef(false);
  const [r, setR] = useState<RSt | null>(null);
  const [mods, setMods] = useRenderSelection(url, r?.models);
  const [sel, setSel] = useState<number[]>([]);
  const [task, setTask] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [big, setBig] = useState<number | null>(null);
  const [zones, setZones] = useState<Record<number, number[]>>({});
  const [zfid, setZfid] = useState<number | null>(null);
  const load = () => http.get<RSt>(`${url}/render`).then(setR).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [url]);   // eslint-disable-line react-hooks/exhaustive-deps
  const edits = (r?.renders || []).filter((x) => x.task).reverse();
  const live = edits.some((x) => x.state === "queued" || x.state === "running" || (x.state === "done" && !x.check_res));
  useEffect(() => { if (!live) return; const t = window.setInterval(load, 6000); return () => window.clearInterval(t); }, [live]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="hint">{err || "Загрузка…"}</div>;
  const tog = (fid: number) => setSel(sel.includes(fid) ? sel.filter((x) => x !== fid) : [...sel, fid]);
  const zoneOf = (fid: number) => sel.includes(fid) ? zones[fid] : undefined;
  /** Рамка выделенной области поверх миниатюры + кнопка «выделить область». */
  const zoneUi = (fid: number) => <>
    {zoneOf(fid) && <div className="vis-zone" style={{ left: `${zoneOf(fid)![0] * 100}%`, top: `${zoneOf(fid)![1] * 100}%`,
      width: `${zoneOf(fid)![2] * 100}%`, height: `${zoneOf(fid)![3] * 100}%` }} />}
    {r.can_edit && sel.includes(fid) && <button className="link vis-zone-btn" onClick={() => setZfid(fid)}>
      🔲 {zones[fid] ? "изменить область" : "выделить область"}</button>}</>;
  const fail = (e: Error) => { setErr(e.message); paymentPending.current = false; setBusy(false); };
  const go = async () => { if (paymentPending.current) return; paymentPending.current = true; setBusy(true); setErr("");
    try { if (!await confirmRetouch(url, mods, sel.length)) return;
      await http.post(`${url}/render/edit`, { file_ids: sel, task, models: mods,
        zones: Object.fromEntries(sel.filter((f) => zones[f]).map((f) => [String(f), zones[f]])) });
      setMsg(`Дорабатываю ${sel.length} фото — результат появится ниже`); setSel([]); setZones({}); load();
    } catch (e) { fail(e as Error); } finally { paymentPending.current = false; setBusy(false); } };
  const toBase = (fid: number) => http.post(`${url}/photos`, { file_ids: [fid], shared: false }).then(() => { setMsg("Добавлено в «Базу фото» товара"); load(); }).catch(fail);
  const MT = Object.fromEntries(r.models.map((m) => [m.id, m.title]));
  const pick = (title: string, list: { fid: number; label: string }[]) => list.length > 0 && <div className="acc-box"><b>{title} ({list.length})</b>
    <div className="vis-grid">{list.map((x) => <div key={x.fid} className={"vis-th" + (sel.includes(x.fid) ? " on" : "")}>
      <div className="vis-zbox"><img src={`/api/shops/${shop}/visual_file/${x.fid}?thumb=1`} alt="" onClick={() => setBig(x.fid)} style={{ cursor: "zoom-in" }} />
        {zoneUi(x.fid)}</div>
      {r.can_edit && <label className="vis-pick"><input type="checkbox" checked={sel.includes(x.fid)} onChange={() => tog(x.fid)} /> выбрать</label>}
      <span className="hint">{x.label}</span></div>)}</div></div>;
  const drawn = r.renders.filter((x) => x.file_id && x.state === "done" && !x.task).map((x) => ({ fid: x.file_id!, label: `${x.title.slice(0, 40)} · ${x.model_title || MT[x.model] || x.model}` }));
  return (<>
    {err && <div className="err" style={{ whiteSpace: "pre-wrap" }}>{err}</div>}
    {msg && <div className="ok">{msg}</div>}
    <div className="acc-box vis-selbar"><b>Что изменить</b>
      <div className="hint">Выберите одно или несколько фото ниже (галочка «выбрать») и опишите изменения — каждое фото перерисуется от себя.
        Чтобы поменять только часть фото — «🔲 выделить область» под выбранным фото: нейросеть меняет только внутри рамки, остальное остаётся как было.
        Товар остаётся нашим: нейросеть сверяет его с исходниками и не меняет форму, цвет, этикетку и упаковку.</div>
      <textarea rows={3} placeholder="Например: «добавь элементы для праздника Новый год», «сделай фон светлее», «увеличь надпись сверху», «убери лишний текст справа»"
        value={task} onChange={(e) => setTask(e.target.value)} />
      <RenderModels models={r.models} value={mods} onChange={setMods} disabled={busy || !r.can_edit} />
      <div className="rnp-bar"><button className="pri" disabled={busy || !sel.length || !task.trim() || !modelsReady(r.models, mods) || !r.can_edit} onClick={go}>
        ✏️ Доработать {sel.length ? `${sel.length} фото` : "выбранные"}</button>
        {sel.length > 0 && <button className="link" onClick={() => setSel([])}>снять выбор</button>}</div></div>
    {edits.length > 0 && <div className="acc-box"><b>Результаты доработки</b>
      <div className="vis-grid">{edits.map((x) => <div key={x.id} className={"vis-th" + (x.file_id && sel.includes(x.file_id) ? " on" : "")}>
        {x.file_id ? <div className="vis-zbox"><img src={`/api/shops/${shop}/visual_file/${x.file_id}?thumb=1`} alt="" onClick={() => setBig(x.file_id)} style={{ cursor: "zoom-in" }} />
          {zoneUi(x.file_id)}</div>
          : <div className="vis-wait">{x.state === "error" ? "❌" : x.state === "canceled" ? "⏹" : "⏳"}</div>}
        <span className="hint">✏️ {x.zone ? "🔲 " : ""}{(x.task || "").slice(0, 60)} · {x.model_title || MT[x.model] || x.model}</span>
        {x.state === "error" && <span className="t-bad">{x.error}</span>}
        {x.check_res?.skipped && <span className="hint">Автопроверка недоступна — проверьте фото вручную</span>}
        {x.check_res && !x.check_res.skipped && <span className={x.check_res.product_ok && x.check_res.text_ok ? "t-good" : "t-bad"}
          title={[...(x.check_res.product_diff || []), ...(x.check_res.text_errors || [])].join("\n")}>
          {x.check_res.product_ok ? "товар ✓" : "товар изменён ⚠️"} · {x.check_res.text_ok ? "текст ✓" : "ошибки в тексте ⚠️"}</span>}
        {x.file_id && r.can_edit && <div className="rnp-bar"><label className="vis-pick"><input type="checkbox" checked={sel.includes(x.file_id)} onChange={() => tog(x.file_id!)} /> доработать ещё</label>
          {r.photos.some((p) => p.file_id === x.file_id) ? <span className="t-good">✅ в базе</span>
            : <button className="link vis-in" onClick={() => toBase(x.file_id!)}>✅ в базу фото</button>}</div>}
        {r.can_edit && x.state !== "queued" && x.state !== "running" && <button className="link t-bad" onClick={() => {
          if (window.confirm("Удалить эту картинку насовсем?")) http.del(`${url}/render/${x.id}`).then(load).catch(fail); }}>🗑 удалить</button>}
      </div>)}</div></div>}
    {pick("Нарисованные слайды", drawn)}
    {pick("Одобренные фото товара", r.photos.map((p) => ({ fid: p.file_id, label: p.title })))}
    {pick("Исходники и фото карточки", s.sources.map((f) => ({ fid: f.id, label: `#${f.id} ${f.name}`.slice(0, 40) })))}
    {pick("Общие фото магазина", r.shared.map((p) => ({ fid: p.file_id, label: p.title })))}
    {big && <Lightbox shop={shop} fid={big} list={[...edits.filter((x) => x.file_id).map((x) => x.file_id!), ...drawn.map((x) => x.fid),
      ...r.photos.map((p) => p.file_id), ...s.sources.map((f) => f.id), ...r.shared.map((p) => p.file_id)]} onClose={() => setBig(null)} />}
    {zfid && <ZonePick shop={shop} fid={zfid} zone={zones[zfid]} onClose={() => setZfid(null)}
      onSave={(z) => { const n = { ...zones }; if (z) n[zfid] = z; else delete n[zfid]; setZones(n); setZfid(null); }} />}
  </>);
}

/** Выделить область на фото: тянем рамку мышкой или пальцем. Область — доли картинки [x, y, w, h]. */
function ZonePick({ shop, fid, zone, onClose, onSave }: { shop: number; fid: number; zone?: number[]; onClose: () => void; onSave: (z: number[] | null) => void }) {
  const [z, setZ] = useState<number[] | null>(zone || null);
  const start = useRef<[number, number] | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const pt = (e: React.PointerEvent): [number, number] => {
    const b = box.current!.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - b.left) / b.width, 0), 1), Math.min(Math.max((e.clientY - b.top) / b.height, 0), 1)];
  };
  const move = (e: React.PointerEvent) => {
    if (!start.current) return;
    const [a, b] = start.current, [c, d] = pt(e);
    setZ([Math.min(a, c), Math.min(b, d), Math.abs(c - a), Math.abs(d - b)]);
  };
  const ok = z && z[2] >= 0.02 && z[3] >= 0.02;
  return <div className="vis-lb" onClick={onClose}>
    <div className="vis-lb-in" onClick={(e) => e.stopPropagation()}>
      <div ref={box} className="vis-zpick" onPointerDown={(e) => { e.preventDefault(); (e.target as Element).setPointerCapture?.(e.pointerId); start.current = pt(e); setZ(null); }}
        onPointerMove={move} onPointerUp={(e) => { move(e); start.current = null; }}>
        <img src={`/api/shops/${shop}/visual_file/${fid}?w=1`} alt="" draggable={false} />
        {z && <div className="vis-zone" style={{ left: `${z[0] * 100}%`, top: `${z[1] * 100}%`, width: `${z[2] * 100}%`, height: `${z[3] * 100}%` }} />}
      </div>
    </div>
    <div className="vis-lb-bar" onClick={(e) => e.stopPropagation()}>
      <span>Обведите рамкой, что поменять</span>
      <button className="pri" disabled={!ok} onClick={() => onSave(z)}>✓ Готово</button>
      {zone && <button onClick={() => onSave(null)}>Без области</button>}
      <button onClick={onClose}>✕ Отмена</button></div>
  </div>;
}

/** Картинка в полном размере поверх страницы: колёсиком/кликом — крупнее, Esc или клик по фону — закрыть. */
function Lightbox({ shop, fid: fid0, list, onClose }: { shop: number; fid: number; list?: number[]; onClose: () => void }) {
  const [zoom, setZoom] = useState(false);
  const [fid, setFid] = useState(fid0);
  const L = list && list.includes(fid0) ? list : [fid0];
  const i = L.indexOf(fid);
  const go = (d: number) => { setFid(L[(i + d + L.length) % L.length]); setZoom(false); };
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); if (e.key === "ArrowLeft") go(-1); if (e.key === "ArrowRight") go(1); };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  });   // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="vis-lb" onClick={onClose}>
    <div className={"vis-lb-in" + (zoom ? " zoom" : "")} onClick={(e) => e.stopPropagation()}>
      {/* на весь экран — лёгкая JPEG-копия 1600 px (быстро); «100 %» — оригинал */}
      <img src={`/api/shops/${shop}/visual_file/${fid}${zoom ? "" : "?w=1"}`} alt="" onClick={() => setZoom(!zoom)} style={{ cursor: zoom ? "zoom-out" : "zoom-in" }} />
    </div>
    <div className="vis-lb-bar" onClick={(e) => e.stopPropagation()}>
      {L.length > 1 && <><button onClick={() => go(-1)}>‹ пред.</button><span style={{ color: "#fff" }}>{i + 1} / {L.length}</span>
        <button onClick={() => go(1)}>след. ›</button></>}
      <button onClick={() => setZoom(!zoom)}>{zoom ? "Вписать в экран" : "100 %"}</button>
      <a href={`/api/shops/${shop}/visual_file/${fid}`} target="_blank" rel="noreferrer">в новой вкладке ↗</a>
      <button onClick={onClose}>✕ Закрыть</button></div>
  </div>;
}

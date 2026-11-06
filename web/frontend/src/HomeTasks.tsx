import { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Fb = { mine: { rating: number | null; comment: string | null } | null; up: number; down: number; comments: string[] } | null;
type Side = { days: number; orders: number; sum: number; ads: number; profit: number };
type Task = { id: number; run_id: number | null; day: string; title: string; why: string; steps: string | null; tag: string; certainty: string; effect_week: number | null;
  priority: number; nm_ids: number[]; vc: string | null; status: string; status_by: string | null; status_note: string | null; status_who: string | null;
  outcome: { before: Side; after: Side; delta_profit_week: number; final: boolean; pending?: boolean; note?: string } | null; feedback: Fb; photo: string | null };
type Coverage = { day: string; ready: boolean; warnings: string[]; fingerprint: string };
type Run = { id: number; day: string; status: string; entry_ok: boolean | null; data_coverage?: Coverage | null; summary: string | null; started_at: string; finished_at: string | null };
type Res = { enabled: boolean; today: string; runs: Record<string, Run>; tasks: Task[]; tags: Record<string, string>; cert: Record<string, string>;
  marketplace?: string; coverage?: Coverage | null; entry_day: string; entry_present: boolean | null; status_t: Record<string, string>; can_edit: boolean };

const rub = (v: number | null | undefined) => v == null ? "—" : `${Math.round(v).toLocaleString("ru-RU")} ₽`;
const dd = (s: string) => s.slice(8, 10) + "." + s.slice(5, 7);
const finished = (s: string | null) => s && Number.isFinite(new Date(s).getTime())
  ? new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Moscow", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(s)) + " МСК" : "";
const TAG_I: Record<string, string> = { ads: "📢", card: "🃏", price: "🏷", stock: "📦", promo: "🎯", reviews: "⭐", other: "🔧" };
const ST_I: Record<string, string> = { new: "⏳", done: "✅", partial: "◐", not_done: "✖️", skipped: "—" };

/** 🧠 Задачи от нейросети : на сегодня — по итогам вчерашнего дня; вчера — что сделано и как сработало; неделя — все задачи
 *  со статусами и итогом. Выполнение отмечается само по журналу изменений; 👍/👎 и комментарии — нейросеть видит их каждое утро. */
export function HomeTasks({ shop }: { shop: number }) {
  const [r, setR] = useState<Res | null>(null);
  const [view, setView] = useState<"today" | "yesterday" | "week">("today");
  const [tag, setTag] = useState("");
  const [msg, setMsg] = useState("");
  const [requestedRun, setRequestedRun] = useState<number | null>(null);
  const [refreshError, setRefreshError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const contextRef = useRef({ shop, active: true, request: 0, rebuilding: false });
  if (contextRef.current.shop !== shop) {
    contextRef.current.active = false;
    contextRef.current = { shop, active: true, request: 0, rebuilding: false };
  }
  const context = contextRef.current;
  const isCurrent = () => contextRef.current === context && context.active;
  const load = () => {
    if (!isCurrent()) return Promise.resolve();
    const request = ++context.request;
    return http.get<Res>(`/api/shops/${shop}/ai_tasks`)
      .then((data) => { if (isCurrent() && request === context.request) { setR(data); setRefreshError(""); } })
      .catch((e) => { if (isCurrent() && request === context.request) setRefreshError((e as Error).message || "Нет связи с сервером"); });
  };
  useEffect(() => {
    context.active = true;
    setR(null); setMsg(""); setRequestedRun(null); setRefreshError(""); setSubmitting(false);
    setView("today"); setTag(""); void load();
    const timer = window.setInterval(() => { void load(); }, 30000);
    const onVis = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { context.active = false; context.request++; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVis); };
  }, [shop]); // eslint-disable-line react-hooks/exhaustive-deps
  const rebuild = () => {
    if (!isCurrent() || context.rebuilding) return Promise.resolve();
    context.rebuilding = true; setSubmitting(true); setMsg(""); setRequestedRun(null);
    return http.post<{ message: string; run_id?: number | null }>(`/api/shops/${shop}/ai_tasks/rebuild`, {})
      .then((x) => { if (isCurrent()) { setMsg(x.message); setRequestedRun(x.run_id ?? null); setView("today"); setTag(""); void load(); } })
      .catch((e) => { if (isCurrent()) setMsg((e as Error).message); })
      .finally(() => { context.rebuilding = false; if (isCurrent()) setSubmitting(false); });
  };
  if (!r) return refreshError ? <div className="ai-home tasks-home">
    <div className="err">Не удалось загрузить задачи: {refreshError}</div><button className="link" onClick={load}>Обновить задачи</button>
  </div> : null;
  if (!r.enabled) return null;
  const y = new Date(new Date(r.today).getTime() - 86400000).toISOString().slice(0, 10);
  const run = r.runs[r.today];
  // The POST acknowledgement is temporary. Once GET reflects that run (or a
  // newer one), only the actual server state is shown. Unrelated errors remain.
  const notice = requestedRun != null && run?.id >= requestedRun ? "" : msg;
  const pending = run?.status === "requested" || run?.status === "running";
  const saved = r.tasks.filter((t) => t.run_id === run?.id && t.day === r.today).length;
  const previous = !!run && r.tasks.some((t) => t.day === r.today && t.run_id !== run.id);
  const ozon = r.marketplace === "ozon";
  const list = r.tasks.filter((t) => (view === "today" ? t.day === r.today : view === "yesterday" ? t.day === y : true) && (!tag || t.tag === tag));
  const week = r.tasks.filter((t) => t.day < r.today);
  const cnt = (s: string) => week.filter((t) => t.status === s).length;
  const eff = week.filter((t) => t.outcome && !t.outcome.pending).reduce((s, t) => s + (t.outcome?.delta_profit_week || 0), 0);
  const tags = [...new Set(r.tasks.map((t) => t.tag))];
  return (
    <div className="ai-home tasks-home">
      <div className="ai-h"><b>🧠 Задачи от нейросети</b>
        <span className="hint">{ozon
          ? "каждое утро — разбор Ozon за вчера: воронка, реклама, поисковые запросы, цена продавца, остатки по кластерам и начисления"
          : "каждое утро — глубокий разбор вчерашнего дня: воронка, точки входа, реклама, цены и СПП, остатки, журнал изменений"}</span>
        {r.can_edit && <button className="link" disabled={submitting || pending} onClick={rebuild}>↻ пересобрать на сегодня</button>}{notice && <span className="hint">{notice}</span>}</div>
      {refreshError && <div className="disclaimer">Не удалось обновить статус и задачи: {refreshError}. Показаны ранее загруженные данные.{" "}
        <button className="link" onClick={load}>Обновить задачи</button></div>}
      <div className="rv-filters">
        <button className={"chip" + (view === "today" ? " on" : "")} onClick={() => setView("today")}>На сегодня ({r.tasks.filter((t) => t.day === r.today).length})</button>
        <button className={"chip" + (view === "yesterday" ? " on" : "")} onClick={() => setView("yesterday")}>Вчера ({r.tasks.filter((t) => t.day === y).length})</button>
        <button className={"chip" + (view === "week" ? " on" : "")} onClick={() => setView("week")}>Неделя ({r.tasks.length})</button>
        <span className="hint" style={{ marginLeft: 8 }}>тег:</span>
        <button className={"chip" + (!tag ? " on" : "")} onClick={() => setTag("")}>все</button>
        {tags.map((g) => <button key={g} className={"chip" + (tag === g ? " on" : "")} onClick={() => setTag(tag === g ? "" : g)}>{TAG_I[g]} {r.tags[g] || g}</button>)}
      </div>
      {view === "today" && (run ? <div className="ai-sub">
        {run.status === "ok" ? <><div className="hint">✓ Разбор завершён{finished(run.finished_at) && ` ${finished(run.finished_at)}`}. Сохранено задач: {saved}.</div>
          {run.summary && <div className="tasks-sum">{run.summary}</div>}
          {!ozon && run.entry_ok === false && <div className="disclaimer">{r.entry_present
            ? `Точки входа за ${dd(r.entry_day)} уже загружены, но текущие задачи были собраны без них. Нужна пересборка: автоматически до 18:00 МСК или по кнопке «пересобрать на сегодня».`
            : `⚠️ Точки входа за ${dd(r.entry_day)} ещё не загружены. Текущие задачи собраны без них; загрузите отчёт плагином и пересоберите задачи.`}</div>}</>
          : run.status === "error" ? <span className="hint">Не удалось подтвердить завершение разбора. Сохранённые задачи показаны ниже; при повторном запросе сервер проверит возможность запуска.</span>
          : <span className="hint">⏳ Разбор идёт ({run.status === "requested" ? "в очереди" : "ИИ читает досье кабинета"}) — обычно 10–30 минут.
            {previous && " Пока показаны задачи предыдущего разбора."}</span>}
      </div> : <div className="hint">Задачи на сегодня появятся после утреннего разбора (с 9:40 МСК).</div>)}
      {ozon && view === "today" && <div className="hint">
        Начисления и прибыль Ozon дополняются после доставки. Заказы и начисления относятся к разным датам.
        {r.coverage?.ready === false && <div className="disclaimer">За {dd(r.entry_day)} ещё нет достаточных данных о заказах для нового разбора.</div>}
        {(r.coverage?.warnings || []).length > 0 && <details><summary>Полнота данных за {dd(r.entry_day)} сейчас</summary>
          <ul>{r.coverage!.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
        {(run?.data_coverage?.warnings || []).length > 0 && <details><summary>Данные, доступные при последнем разборе</summary>
          <ul>{run!.data_coverage!.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></details>}
      </div>}
      {view === "week" && week.length > 0 && <div className="tasks-sum">За неделю: {week.length} задач — ✅ {cnt("done")} · ◐ {cnt("partial")} · ✖️ {cnt("not_done")}
        {cnt("skipped") > 0 && <> · не делаем {cnt("skipped")}</>}{!ozon && eff !== 0 && <> · итог выполненных: <b className={eff >= 0 ? "pos" : "neg"}>{eff > 0 ? "+" : ""}{rub(eff)}</b> прибыли в неделю (до/после, без поправки на фон)</>}</div>}
      {view === "yesterday" && r.runs[y]?.summary && <div className="tasks-sum">{r.runs[y].summary}</div>}
      {!list.length ? <div className="hint">Задач нет.</div> : <div className="tasks-list">
        {list.map((t) => <TaskCard key={t.id} t={t} r={r} shop={shop} showDay={view === "week"} onDone={load} isCurrent={isCurrent} />)}
      </div>}
      <div className="hint">Точность: <b>точно</b> — видно в данных, <b>вероятно</b> — сильная связь, <b>гипотеза</b> — проверить. Выполнение отмечается само по журналу
        изменений (кнопкой в сервисе или руками в кабинете — неважно), итог — заказы и прибыль артикулов до и после. {ozon && "Изменения ставок, описаний и акций подтверждаются вручную; денежная разница до/после не доказывает эффект действия. "}👍/👎 и комментарии нейросеть читает каждое утро.</div>
    </div>
  );
}

function TaskCard({ t, r, shop, showDay, onDone, isCurrent }: { t: Task; r: Res; shop: number; showDay: boolean; onDone: () => void; isCurrent: () => boolean }) {
  const [open, setOpen] = useState(false);
  const [txt, setTxt] = useState(t.feedback?.mine?.comment || "");
  const [busy, setBusy] = useState(false);
  const mine = t.feedback?.mine;
  const fb = (rating: number | null, comment: string | null) => {
    if (!isCurrent()) return;
    setBusy(true);
    http.post(`/api/shops/${shop}/ai_tasks/feedback`, { id: t.id, rating, comment })
      .then(() => { if (isCurrent()) { setOpen(false); onDone(); } })
      .catch((e) => { if (isCurrent()) alert((e as Error).message); })
      .finally(() => { if (isCurrent()) setBusy(false); });
  };
  const mark = (status: string) => {
    if (!isCurrent()) return Promise.resolve();
    return http.post(`/api/shops/${shop}/ai_tasks/status`, { id: t.id, status })
      .then(() => { if (isCurrent()) onDone(); })
      .catch((e) => { if (isCurrent()) alert((e as Error).message); });
  };
  const o = t.outcome;
  return <div className={"task-card st-" + t.status}>
    <div className="task-top">
      {t.photo && <img className="thumb" src={t.photo} alt="" loading="lazy" />}
      <div className="task-main">
        <div className="task-badges">
          <span className={"badge tag-" + t.tag}>{TAG_I[t.tag]} {r.tags[t.tag] || t.tag}</span>
          <span className={"badge cert-" + t.certainty}>{r.cert[t.certainty] || t.certainty}</span>
          {t.effect_week ? <span className="badge eff">≈ +{rub(t.effect_week)}/нед</span> : null}
          {showDay && <span className="hint">{dd(t.day)}</span>}
          <span className={"badge st"} title={t.status_note || ""}>{ST_I[t.status]} {r.status_t[t.status]}{t.status_by === "auto" ? " (авто)" : t.status_by === "manual" ? ` (${t.status_who || "вручную"})` : ""}</span>
        </div>
        <div className="task-title">{t.title}</div>
        {t.vc && <div className="hint">{t.vc}{t.nm_ids?.length ? ` · ${t.nm_ids.slice(0, 4).join(", ")}` : ""}</div>}
        <div className="task-why">{t.why}</div>
        {t.steps && <div className="task-steps">{t.steps}</div>}
        {t.status_note && <div className="hint">{t.status_note}</div>}
        {o?.pending && <div className="task-out hint">Итог ожидает полных данных или пересчёта. Отметка выполнения сохранена.</div>}
        {o && !o.pending && <div className="task-out">Итог ({o.final ? "" : "предварительно, "}в день, до → после): заказы {o.before.orders} → {o.after.orders}, сумма {rub(o.before.sum)} → {rub(o.after.sum)},
          реклама {rub(o.before.ads)} → {rub(o.after.ads)}, прибыль {rub(o.before.profit)} → {rub(o.after.profit)}
          <b className={o.delta_profit_week >= 0 ? "pos" : "neg"}> ({o.delta_profit_week > 0 ? "+" : ""}{rub(o.delta_profit_week)}/нед)</b></div>}
        {o?.note && <div className="hint">{o.note}</div>}
        {!o && r.marketplace === "ozon" && ["done", "partial"].includes(t.status) && <div className="hint">Итог появится после поступления полных данных за периоды до и после изменения.</div>}
      </div>
    </div>
    <div className="task-act">
      <div className="ads-fb">
        <button className={"fb" + (mine?.rating === 1 ? " on" : "")} disabled={busy} title="Хорошая задача" onClick={() => fb(mine?.rating === 1 ? null : 1, mine?.comment || null)}>👍</button>
        <button className={"fb" + (mine?.rating === -1 ? " on bad" : "")} disabled={busy} title="Плохая задача" onClick={() => fb(mine?.rating === -1 ? null : -1, mine?.comment || null)}>👎</button>
        <button className={"fb" + (mine?.comment ? " on" : "")} disabled={busy} title="Комментарий: что не так, что сделать иначе" onClick={() => setOpen(!open)}>💬</button>
        {t.feedback && (t.feedback.up - (mine?.rating === 1 ? 1 : 0) > 0 || t.feedback.down - (mine?.rating === -1 ? 1 : 0) > 0) &&
          <span className="hint">ещё: 👍{t.feedback.up - (mine?.rating === 1 ? 1 : 0)} 👎{t.feedback.down - (mine?.rating === -1 ? 1 : 0)}</span>}
      </div>
      {r.can_edit && <div className="task-mark">
        <span className="hint">отметить:</span>
        {(["done", "partial", "not_done", "skipped"] as const).map((s) => <button key={s} className={"link" + (t.status === s && t.status_by === "manual" ? " on" : "")}
          onClick={() => mark(s)}>{r.status_t[s]}</button>)}
        {t.status_by === "manual" && <button className="link" onClick={() => mark("new")}>авто</button>}
      </div>}
      {open && <div className="ads-fb-box">
        <textarea rows={3} value={txt} placeholder="Почему задача хорошая или плохая, что сделать иначе" onChange={(e) => setTxt(e.target.value)} />
        <div><button disabled={busy} onClick={() => fb(mine?.rating ?? null, txt)}>Сохранить</button> <button className="link" onClick={() => setOpen(false)}>отмена</button></div>
      </div>}
      {t.feedback && t.feedback.comments.length > 0 && <div className="hint">💬 {t.feedback.comments.join(" · ")}</div>}
    </div>
  </div>;
}

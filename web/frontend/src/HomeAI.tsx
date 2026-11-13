import { useEffect, useRef, useState } from "react";
import { http } from "./api";
import { reportProgress, reportUncertain, type ReportPending } from "./homeAiWait";

type Sec = { section: string; title: string; body: string; source: string; model: string | null; created_at: string; day: string; kind: "day" | "week" };
const ICON: Record<string, string> = { day: "📅", money: "💸", cabinet: "🧰", competitors: "⚔️", niche: "📰", search: "🔎" };

/** ИИ-сводка на главной: «Главное за вчера» (каждый день) и итоги недели — деньги, ошибки, конкуренты, ниша (по понедельникам). */
export function HomeAI({ shop }: { shop: number }) {
  type Cmp = { id: number; period_from: string | null; period_to: string | null; ai_text: string; cards: string[] };
  type Rep = { day: string | null; sections: Sec[]; has_key: boolean; can_build: boolean; compare: Cmp | null; building?: boolean; expected_sections?: string[]; ai_reason?: string | null };
  const [r, setR] = useState<Rep | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [building, setBuilding] = useState(false);
  const [retryAllowed, setRetryAllowed] = useState(false);
  const pending = useRef<ReportPending | null>(null);
  const generation = useRef(0);
  const storageKey = `ai-report-pending:${shop}`;
  const persist = () => {
    try {
      if (pending.current) sessionStorage.setItem(storageKey, JSON.stringify(pending.current));
      else sessionStorage.removeItem(storageKey);
    } catch { /* storage can be unavailable */ }
  };
  useEffect(() => {
    const current = ++generation.current;
    let active = true, loading = false;
    setR(null); setMsg(""); setRetryAllowed(false);
    pending.current = null;
    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
      if (saved && Number.isFinite(saved.started) && saved.before && typeof saved.before === "object" && !Array.isArray(saved.before)) {
        pending.current = { started: saved.started, before: saved.before,
          expected: Array.isArray(saved.expected) ? saved.expected.filter((s: unknown) => typeof s === "string") : undefined };
      }
    } catch { /* ignore invalid or unavailable storage */ }
    setBuilding(!!pending.current);
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const y = await http.get<Rep>(`/api/shops/${shop}/ai_report`);
        if (!active || generation.current !== current) return;
        setR(y);
        const job = pending.current;
        if (!job) {
          setBuilding(y.building === true); setRetryAllowed(false);
          if (y.building) setMsg("Сводка этого магазина уже собирается. Готовые разделы появятся автоматически.");
          else setMsg((value) => value.startsWith("Сводка этого магазина уже собирается.") ? "" : value);
          return;
        }
        const progress = reportProgress(job, y, Date.now());
        if (progress.state === "done") {
          pending.current = null; persist(); setBuilding(false); setRetryAllowed(false);
          setMsg("Сводка обновлена.");
        } else {
          pending.current = progress.job; persist();
          setBuilding(progress.state !== "retry"); setRetryAllowed(progress.state === "retry");
          setMsg(progress.state === "retry"
            ? "Сервер больше не собирает сводку, но обновились не все разделы. Можно повторить обновление кнопкой; автоматически повтор не запускается."
            : Date.now() - job.started >= 30 * 60_000
              ? "Обновление занимает больше 30 минут. Проверяем состояние сервера; повторный запуск пока заблокирован."
              : "Собираю сводку. Это может занять 15–20 минут или дольше; готовые разделы появятся автоматически.");
        }
      } catch {
        if (active && generation.current === current && pending.current) {
          pending.current = { ...pending.current, idleSince: undefined, retry: false }; persist(); setBuilding(true); setRetryAllowed(false);
          setMsg("Не удалось проверить состояние сборки. Проверку повторим автоматически; новую сборку пока не запускаем.");
        }
      } finally { loading = false; }
    };
    void load();
    // Continue checking after slow builds, and when returning to this page.
    const timer = window.setInterval(() => { void load(); }, 15000);
    const onVis = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVis);
    return () => { active = false; generation.current += 1; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVis); };
  }, [shop]);
  const rebuild = async () => {
    if ((pending.current && !pending.current.retry) || r?.building) return;
    const current = generation.current;
    const started = Date.now();
    pending.current = { started, before: Object.fromEntries((r?.sections || []).map((s) => [s.section, s.created_at])),
      expected: r?.expected_sections, requestPending: true };
    persist(); setBuilding(true); setRetryAllowed(false); setMsg("Запускаю обновление сводки…");
    try {
      const x = await http.post<{ message: string; expected_sections?: string[]; frozen?: boolean }>(`/api/shops/${shop}/ai_report/build`);
      if (generation.current === current && pending.current?.started === started && x.frozen) {
        pending.current = null; persist(); setBuilding(false); setRetryAllowed(false); setMsg(x.message); return;
      }
      if (generation.current === current && pending.current?.started === started) {
        pending.current = { ...pending.current, requestPending: false, expected: x.expected_sections || pending.current.expected };
        persist(); setMsg(x.message);
      }
    } catch (e) {
      if (generation.current !== current || pending.current?.started !== started) return;
      pending.current = reportUncertain(pending.current); persist(); setBuilding(true); setRetryAllowed(false);
      setMsg("Ответ на запуск не получен: сборка могла начаться. Проверяем сервер; повтор автоматически не отправляем. " + (e instanceof Error ? e.message : ""));
    }
  };
  if (!r) return null;
  const build = r.has_key && r.can_build && (
    <button className="link" disabled={building} onClick={rebuild}>{building ? "⏳ сводка собирается" : retryAllowed ? "↻ повторить обновление" : "↻ обновить сводку"}</button>);
  const cmp = r.compare && (() => {
    const lines = r.compare.ai_text.split("\n");
    const long = lines.length > 7 && !open.cmp;
    const dd = (x: string | null) => (x ? x.slice(0, 10).split("-").reverse().join(".") : "");
    return (
      <div className="ai-sec">
        <div className="ai-t">⚖️ Сравнение карточек ({dd(r.compare.period_from)}–{dd(r.compare.period_to)})</div>
        <div className="hint">{r.compare.cards.join(" · ")}</div>
        <div className="ai-b">{(long ? lines.slice(0, 7) : lines).map((l, i) => <p key={i}>{l}</p>)}</div>
        {lines.length > 7 && <button className="link" onClick={() => setOpen((o) => ({ ...o, cmp: !o.cmp }))}>{open.cmp ? "свернуть" : "читать полностью"}</button>}
        <a className="link" href={`/compare/${r.compare.id}`}>открыть сравнение →</a>
      </div>);
  })();
  if (!r.sections.length && cmp) return <div className="ai-home"><div className="ai-h"><b>🤖 Сводка ИИ</b></div><div className="ai-grid">{cmp}</div></div>;
  if (!r.sections.length) return r.has_key ? <div className="hint">ИИ-сводки ещё нет. {build} {msg}</div>
    : <div className="hint">🤖 {r.ai_reason || "ИИ-сводка для этого магазина пока недоступна. Проверьте доступ к нейросети в настройках кабинета."}</div>;
  const test = r.sections.some((s) => s.source === "kit-test");
  const dd = (x: string) => new Date(x).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
  const days = r.sections.filter((s) => s.kind === "day"), weeks = r.sections.filter((s) => s.kind !== "day");
  const sec = (s: Sec) => {
    const lines = s.body.split("\n");
    const long = lines.length > 7 && !open[s.section];
    return (
      <div key={s.section} className="ai-sec">
        <div className="ai-t">{ICON[s.section]} {s.title}</div>
        <div className="ai-b">{(long ? lines.slice(0, 7) : lines).map((l, i) => <p key={i}>{l}</p>)}</div>
        {lines.length > 7 && <button className="link" onClick={() => setOpen((o) => ({ ...o, [s.section]: !o[s.section] }))}>{open[s.section] ? "свернуть" : "читать полностью"}</button>}
      </div>
    );
  };
  return (
    <div className="ai-home">
      <div className="ai-h"><b>🤖 Сводка ИИ</b><span className="hint">по данным на {new Date(r.day!).toLocaleDateString("ru-RU")}{test ? " · тестовый вариант" : ""}</span>{build}{msg && <span className="hint">{msg}</span>}</div>
      {days.length > 0 && <><div className="ai-sub">📅 За день <span className="hint">· {dd(days[0].day)} · обновляется каждое утро</span></div>
        <div className="ai-grid">{days.map(sec)}</div></>}
      {(weeks.length > 0 || cmp) && <><div className="ai-sub">🗓 Итоги недели {weeks[0] && <span className="hint">· неделя по {dd(weeks[0].day)} · обновляется по понедельникам</span>}</div>
        <div className="ai-grid">{weeks.map(sec)}{cmp}</div></>}
    </div>
  );
}

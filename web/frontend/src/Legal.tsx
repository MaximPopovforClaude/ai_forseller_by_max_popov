import { useEffect, useState } from "react";
import { http } from "./api";
import { Logo } from "./Logo";

type About = { ready: boolean; version: string; about: string; support_bot: string | null; channel: string | null; email: string | null; org: string | null };
type Doc = { title: string; ready: boolean; version: string; sections: { h: string; p: string[] }[] };
type LegalAdmin = { fields: { key: string; title: string; required: boolean }[]; value: Record<string, string | boolean> };

const tgName = (u: string) => "@" + u.replace(/^https?:\/\/t\.me\//, "").replace(/\/$/, "");

/** «О сервисе» — поддержка, команда, канал, документы. */
export function AboutPage() {
  const [a, setA] = useState<About | null>(null);
  useEffect(() => { http.get<About>("/api/public/about").then(setA).catch(() => undefined); }, []);
  if (!a) return <div className="hint">Загрузка…</div>;
  return (
    <div className="about">
      <h2>О сервисе</h2>
      <section className="about-card">
        <h3>💬 Поддержка</h3>
        {a.support_bot
          ? <p>Вопросы, ошибки, идеи — пишите в бот поддержки: <a href={a.support_bot} target="_blank" rel="noreferrer">{tgName(a.support_bot)}</a></p>
          : <p className="hint">Бот поддержки скоро появится.</p>}
        {a.email && <p>E-mail: <a href={`mailto:${a.email}`}>{a.email}</a></p>}
      </section>
      <section className="about-card">
        <h3>👋 Команда</h3>
        <p>{a.about}</p>
        {a.channel && <p><a className="about-btn" href={a.channel} target="_blank" rel="noreferrer">Канал в Telegram: {tgName(a.channel)} →</a></p>}
      </section>
      <section className="about-card">
        <h3>📄 Документы</h3>
        <p><a href="/legal/offer" target="_blank" rel="noreferrer">Публичная оферта</a></p>
        <p><a href="/legal/privacy" target="_blank" rel="noreferrer">Согласие на обработку персональных данных и Политика</a></p>
        {!a.ready && <p className="hint">Документы публикуются после заполнения реквизитов.</p>}
      </section>
    </div>
  );
}

/** Публичная страница документа: /legal/offer, /legal/privacy. */
export function LegalPage() {
  const doc = window.location.pathname.match(/^\/legal\/(offer|privacy)/)?.[1] || "offer";
  const [d, setD] = useState<Doc | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { http.get<Doc>(`/api/public/legal/${doc}`).then((x) => { setD(x); document.title = `${x.title} · Seller Analytics`; }).catch((e) => setErr(e.message)); }, [doc]);
  return (
    <div className="legal">
      <a href="/"><Logo kind="horizontal" height={30} /></a>
      {err && <div className="err">{err}</div>}
      {d && <>
        <h1>{d.title}</h1>
        {!d.sections.length ? <p className="hint">Документ готовится и скоро будет опубликован.</p> : <>
          {!d.ready && <p className="err">Черновик: реквизиты не заполнены (видно только суперадмину).</p>}
          <p className="hint">Редакция от {d.version.slice(0, 10).split("-").reverse().join(".")}</p>
          {d.sections.map((s) => <section key={s.h}><h2>{s.h}</h2>{s.p.map((x, i) => <p key={i}>{x}</p>)}</section>)}
        </>}
        <p className="legal-nav"><a href="/legal/offer">Публичная оферта</a> · <a href="/legal/privacy">Согласие и Политика</a> · <a href="/">На сайт</a></p>
      </>}
    </div>
  );
}

/** Ссылки на документы мелким шрифтом — под формой входа. */
export function LegalNote({ verb = "Входя" }: { verb?: string }) {
  const [ready, setReady] = useState(false);
  useEffect(() => { http.get<About>("/api/public/about").then((a) => setReady(a.ready)).catch(() => undefined); }, []);
  if (!ready) return null;
  return <div className="legal-note">{verb}, вы принимаете <a href="/legal/offer" target="_blank" rel="noreferrer">оферту</a> и даёте{" "}
    <a href="/legal/privacy" target="_blank" rel="noreferrer">согласие на обработку персональных данных</a>.</div>;
}

/** Один раз после публикации (или новой редакции) документов — принять условия. */
export function TermsGate({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <div className="modal-back">
      <div className="modal terms">
        <h3>Условия сервиса</h3>
        <p>Мы опубликовали документы сервиса. Чтобы продолжить, ознакомьтесь и примите их:</p>
        <p>• <a href="/legal/offer" target="_blank" rel="noreferrer">Публичная оферта</a><br />
          • <a href="/legal/privacy" target="_blank" rel="noreferrer">Согласие на обработку персональных данных</a></p>
        {err && <div className="err">{err}</div>}
        <button disabled={busy} onClick={() => { setBusy(true); http.post("/api/me/terms").then(onDone).catch((e) => { setErr(e.message); setBusy(false); }); }}>
          ✅ Принимаю</button>
      </div>
    </div>
  );
}

/** Админка → «Документы»: реквизиты исполнителя и ссылки. */
export function LegalAdminForm({ onSaved, onErr }: { onSaved: () => void; onErr: (e: Error) => void }) {
  const [d, setD] = useState<LegalAdmin | null>(null);
  const [v, setV] = useState<Record<string, string>>({});
  useEffect(() => {
    http.get<LegalAdmin>("/api/admin/legal").then((x) => { setD(x); setV(Object.fromEntries(x.fields.map((f) => [f.key, String(x.value[f.key] ?? "")]))); }).catch(onErr);
  }, []);
  if (!d) return <div className="hint">Загрузка…</div>;
  return (
    <div className="legal-admin">
      <p className="hint">Пока обязательные поля (*) не заполнены, документы не публикуются, а согласие при входе и регистрации не спрашивается.
        Сейчас: <b>{d.value.ready ? "опубликованы" : "не опубликованы"}</b>, редакция {String(d.value.version)}.
        {" "}Черновики: <a href="/legal/offer" target="_blank" rel="noreferrer">оферта</a>, <a href="/legal/privacy" target="_blank" rel="noreferrer">согласие</a>.</p>
      {d.fields.map((f) => (
        <label key={f.key} className="acc-row"><span>{f.title}{f.required ? " *" : ""}</span>
          <input value={v[f.key] || ""} onChange={(e) => setV({ ...v, [f.key]: e.target.value })} /></label>))}
      <button onClick={() => http.put<LegalAdmin["value"]>("/api/admin/legal", v).then((x) => { setD({ ...d, value: x }); onSaved(); }).catch(onErr)}>Сохранить</button>
    </div>
  );
}

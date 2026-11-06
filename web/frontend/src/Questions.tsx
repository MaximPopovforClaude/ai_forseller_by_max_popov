import { useEffect, useRef, useState } from "react";
import { RecoMap } from "./RecoMap";
import { http } from "./api";
import { MODE_T } from "./Actions";

type Ans = { id: number; text: string; source: "ai" | "manual"; status: "draft" | "sent" | "error"; auto: boolean; created_at: string; sent_at: string | null;
  error: string | null; comment: string | null; sent_by_name: string | null; comment_by_name: string | null };
type Q = { id: string; nm_id: number; vendor_code: string | null; product_name: string | null; brand: string | null; photo: string | null; text: string | null;
  created_at: string; state: string | null; answer_text: string | null; answer_editable: boolean | null; answered: boolean; answers: Ans[]; busy: boolean };
type Res = { rows: Q[]; total: number; counts: { unanswered: number; week: number; total: number; updated: string | null };
  collected: { last_ok_at: string | null; last_error: string | null } | null; block: { enabled: boolean; settings: Record<string, string> };
  can_send: boolean; why_not: string | null; can_edit: boolean; ai: boolean; tones: Record<string, string> };

const dt = (s: string) => new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
const wbUrl = (nm: number) => `https://www.wildberries.ru/catalog/${nm}/detail.aspx`;

/** Вопросы покупателей WB: фильтры, черновик ИИ (по карточке и правилам, без выдумок), ручной ответ, журнал ответов с пометками; правила. */
export function Questions({ shop, onSettings }: { shop: number; onSettings: () => void }) {
  const [view, setView] = useState<"list" | "rules">("list");
  const [state, setState] = useState("unanswered");
  const [ours, setOurs] = useState(false);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [r, setR] = useState<Res | null>(null);
  const [err, setErr] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const load = () => http.get<Res>(`/api/shops/${shop}/questions?state=${ours ? "all" : state}&ours=${ours}&q=${encodeURIComponent(q)}&limit=30&offset=${page * 30}`)
    .then((x) => { setR(x); setErr(""); }).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [shop, state, ours, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {          // черновик ИИ пишется в фоне — подтягиваем, пока есть «пишется…»
    window.clearInterval(timer.current);
    if (r?.rows.some((x) => x.busy)) timer.current = window.setInterval(load, 4000);
    return () => window.clearInterval(timer.current);
  }, [r]); // eslint-disable-line react-hooks/exhaustive-deps
  if (view === "rules") return <Rules shop={shop} onBack={() => setView("list")} />;
  const st = r?.block.settings;
  return (
    <div className="reviews">
      <div className="rv-head">
        <h2>❓ Вопросы</h2>
        <button className="link" onClick={() => setView("rules")}>📝 Правила ответов</button>
        <button className="link" onClick={onSettings}>⚙️ Настройки блока</button>
      </div>
      {r && <div className="hint">
        Без ответа: <b>{r.counts.unanswered}</b> · вопросов за 7 дней: <b>{r.counts.week}</b> · всего вопросов: {r.counts.total.toLocaleString("ru-RU")}
        {r.collected?.last_ok_at && <> · обновлено {dt(r.collected.last_ok_at)}</>}
        {st && <><br />Режим: {MODE_T[st.mode]}{r.block.enabled ? "" : " (блок выключен)"}</>}
      </div>}
      {r && !r.collected?.last_ok_at && !r.collected?.last_error && <div className="hint">Вопросы ещё не загружены — подтянутся в течение ~10 минут.</div>}
      {r?.collected?.last_error && <div className="err">Последняя загрузка вопросов не удалась: {r.collected.last_error}</div>}
      {r?.why_not && <div className="hint">ℹ️ Отправка из сервиса не подключена ({r.why_not.replace(/\.$/, "")}). Черновики ИИ работают:
        нажмите «📋 Скопировать» и опубликуйте ответ в личном кабинете WB — вопрос сам перейдёт в «С ответом» при следующем обновлении (~10 мин).
        Где ответ не тот — напишите пометку и «Переписать»: ИИ учтёт её и в следующих ответах.</div>}
      {err && <div className="err">{err}</div>}
      <div className="rv-filters">
        {[["unanswered", "Без ответа"], ["answered", "С ответом"], ["all", "Все"]].map(([k, t]) => <button key={k} className={"chip" + (!ours && state === k ? " on" : "")} onClick={() => { setState(k); setOurs(false); setPage(0); }}>{t}</button>)}
        <button className={"chip" + (ours ? " on" : "")} onClick={() => { setOurs(!ours); setPage(0); }} title="Ответы, которые отправил сервис (ИИ или сотрудники) — с пометками">Ответы сервиса</button>
        <input placeholder="Поиск: текст, артикул…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { setPage(0); load(); } }} />
      </div>
      {!r ? <div className="hint">Загрузка…</div> : !r.rows.length ? <div className="hint">Вопросов по фильтру нет.</div> :
        r.rows.map((x) => <Card key={x.id} f={x} r={r} shop={shop} reload={load} onErr={setErr} />)}
      {r && r.total > 30 && <div className="rv-pages">
        <button disabled={!page} onClick={() => setPage(page - 1)}>‹</button> {page * 30 + 1}–{Math.min(r.total, page * 30 + 30)} из {r.total}
        <button disabled={(page + 1) * 30 >= r.total} onClick={() => setPage(page + 1)}>›</button></div>}
    </div>
  );
}

function Card({ f, r, shop, reload, onErr }: { f: Q; r: Res; shop: number; reload: () => void; onErr: (s: string) => void }) {
  const draft = [...f.answers].reverse().find((a) => a.status === "draft");
  const lastErr = [...f.answers].reverse().find((a) => a.status === "error");
  const [text, setText] = useState(draft?.text || "");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const done = () => { setCopied(true); setTimeout(() => setCopied(false), 2000); };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(done).catch(() => onErr("Не удалось скопировать — выделите текст вручную"));
    else { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); done(); }
  };
  const redraft = () => { setBusy(true); http.post(`/api/shops/${shop}/questions/${f.id}/draft`).then(reload).catch((e) => onErr(e.message)).finally(() => setBusy(false)); };
  const redraftWithNote = () => {
    if (!draft || !note.trim()) return;
    setBusy(true);
    http.put(`/api/shops/${shop}/questions/answers/${draft.id}/comment`, { comment: note.trim() }).then(() => { setNote(""); redraft(); })
      .catch((e) => { onErr(e.message); setBusy(false); });
  };
  useEffect(() => { if (draft) setText(draft.text); }, [draft?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const mode = r.block.settings.mode;
  const aiOk = r.ai && (mode === "draft" || mode === "auto");     // черновики — и без ключа на запись
  const canAnswer = r.can_edit && mode !== "off" && (!f.answer_text || !!f.answer_editable);
  const sent = f.answers.filter((a) => a.status === "sent");
  return (
    <div className={"rv-card" + (!f.answered ? " neg" : "")}>
      <div className="qa-top">
        {f.photo ? <a href={wbUrl(f.nm_id)} target="_blank" rel="noreferrer"><img className="thumb big" src={f.photo} alt="" loading="lazy" /></a> : null}
        <div className="qa-meta">
          <div className="rv-prod" title={f.product_name || ""}>{f.vendor_code || "—"} · <a href={wbUrl(f.nm_id)} target="_blank" rel="noreferrer">{f.nm_id}</a>
            {f.product_name ? <span className="hint"> · {f.product_name}</span> : null}</div>
          <div className="hint">{dt(f.created_at)}{f.state === "none" ? " · вопрос отклонён" : ""}</div>
        </div>
      </div>
      {f.text && <p><b>Вопрос:</b> {f.text}</p>}
      {f.answer_text && <div className="rv-ans"><b>Ответ магазина:</b> {f.answer_text}</div>}
      {sent.map((a) => <SentNote key={a.id} a={a} shop={shop} canEdit={r.can_edit} onErr={onErr} />)}
      {lastErr && !sent.length && <div className="err">Не получилось: {lastErr.error}</div>}
      {canAnswer && (open || !!draft || f.busy) && <div className="rv-reply">
        <textarea rows={4} placeholder={f.answer_text ? "Новый текст ответа (WB даёт изменить ответ один раз)" : "Ответ покупателю…"} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row">
          <button className={r.can_send ? "" : "pri"} disabled={text.trim().length < 2} onClick={copy}>{copied ? "✓ Скопировано" : "📋 Скопировать"}</button>
          {aiOk && <button disabled={f.busy || busy} onClick={redraft}>
            {f.busy ? "✨ ИИ пишет…" : draft ? "✨ Другой вариант" : "✨ Черновик ИИ"}</button>}
          {r.can_send ? <button className="pri" disabled={text.trim().length < 2 || busy}
            onClick={() => { if (!window.confirm("Отправить ответ на Wildberries? Его увидят покупатели.")) return; setBusy(true);
              http.post(`/api/shops/${shop}/questions/${f.id}/send`, { text, answer_id: draft?.id ?? null }).then(() => { setText(""); reload(); })
                .catch((e) => onErr(e.message)).finally(() => setBusy(false)); }}>Отправить в WB</button>
            : <button disabled title={r.why_not || "Нужна роль «редактор»"}>Отправить в WB</button>}
          {draft && <span className="hint">черновик ИИ от {dt(draft.created_at)} — можно поправить перед {r.can_send ? "отправкой" : "копированием"}</span>}
        </div>
        {draft && aiOk && <div className="rv-cm">
          <input placeholder="Что не так в черновике? Например: «короче», «размер в карточке указан в см» — ИИ учтёт и в следующих ответах"
            value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") redraftWithNote(); }} />
          <button disabled={!note.trim() || busy || f.busy} onClick={redraftWithNote}>✨ Переписать с пометкой</button>
        </div>}
      </div>}
      {!r.can_edit && draft && <div className="rv-reply"><div className="rv-ans"><b>Черновик ИИ:</b> {draft.text}</div>
        <div className="row"><button onClick={copy}>{copied ? "✓ Скопировано" : "📋 Скопировать"}</button></div></div>}
      {canAnswer && !open && !draft && !f.busy && <div className="row"><button onClick={() => setOpen(true)}>{f.answer_text ? "Изменить ответ" : "Ответить"}</button>
        {aiOk && !f.answer_text && <button disabled={busy} onClick={redraft}>✨ Черновик ИИ</button>}</div>}
    </div>
  );
}

function SentNote({ a, shop, canEdit, onErr }: { a: Ans; shop: number; canEdit: boolean; onErr: (s: string) => void }) {
  const [c, setC] = useState(a.comment || "");
  const [saved, setSaved] = useState(false);
  return (
    <div className="rv-note">
      <div className="hint">Ответ сервиса: {a.source === "ai" ? (a.auto ? "🤖 ИИ сам" : "✨ ИИ, отправил " + (a.sent_by_name || "")) : "✍️ " + (a.sent_by_name || "сотрудник")} · {a.sent_at && dt(a.sent_at)}</div>
      <div className="rv-cm">
        <input placeholder="Пометка для ИИ: где ответ неточный, как правильно (учтётся в следующих ответах)" value={c} disabled={!canEdit}
          onChange={(e) => { setC(e.target.value); setSaved(false); }} />
        {canEdit && c !== (a.comment || "") && <button onClick={() => http.put(`/api/shops/${shop}/questions/answers/${a.id}/comment`, { comment: c })
          .then(() => { setSaved(true); a.comment = c; }).catch((e) => onErr(e.message))}>Сохранить</button>}
        {saved && <span className="hint">✓ учтём</span>}
      </div>
      {a.comment && a.comment_by_name && <div className="hint">пометку оставил(а) {a.comment_by_name}</div>}
    </div>
  );
}

function Rules({ shop, onBack }: { shop: number; onBack: () => void }) {
  type R = { nm_id: number; tones: string[]; text: string; tones_all: Record<string, string>; custom: { nm_id: number; vendor_code: string | null; title: string | null }[] };
  const [nm, setNm] = useState(0);
  const [nmIn, setNmIn] = useState("");
  const [r, setR] = useState<R | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { http.get<R>(`/api/shops/${shop}/questions/rules?nm=${nm}`).then(setR).catch((e) => setErr(e.message)); }, [shop, nm]);
  if (!r) return <div className="hint">Загрузка…</div>;
  const save = () => http.put(`/api/shops/${shop}/questions/rules`, { nm_id: nm, tones: r.tones, text: r.text })
    .then(() => { setMsg("Сохранено"); setTimeout(() => setMsg(""), 2000); }).catch((e) => setErr(e.message));
  return (
    <div className="reviews rv-rules">
      <div className="rv-head"><button className="link" onClick={onBack}>‹ к вопросам</button><h2>📝 Правила ответов на вопросы</h2></div>
      <div className="hint">ИИ перед каждым ответом читает эти правила, карточку товара (характеристики, описание), прошлые вопросы и ответы по товару
        и пометки сотрудников. Отвечает только по этим данным; если ответа в них нет — честно пишет, что уточним. Правила товара дополняют правила магазина.</div>
      <div className="rv-filters">
        <button className={"chip" + (nm === 0 ? " on" : "")} onClick={() => setNm(0)}>Весь магазин</button>
        {r.custom.map((x) => <button key={x.nm_id} className={"chip" + (nm === x.nm_id ? " on" : "")} onClick={() => setNm(x.nm_id)}>{x.vendor_code || x.nm_id}</button>)}
        <input placeholder="Артикул WB для своих правил" value={nmIn} onChange={(e) => setNmIn(e.target.value.replace(/\D/g, ""))} />
        <button disabled={!nmIn} onClick={() => { setNm(Number(nmIn)); setNmIn(""); }}>+ правила товара</button>
      </div>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok">{msg}</div>}
      <div className="acc-box">
        <b>{nm ? `Товар ${nm}` : "Весь магазин"}: как отвечать</b>
        <div className="rv-tones">{Object.entries(r.tones_all).map(([k, t]) => <label key={k}><input type="checkbox" checked={r.tones.includes(k)}
          onChange={(e) => setR({ ...r, tones: e.target.checked ? [...r.tones, k] : r.tones.filter((x) => x !== k) })} /> {t}</label>)}</div>
        <textarea rows={7} placeholder={"Свои правила и факты, например:\n- подписываться «Команда Example»\n- доставка только через WB, сроки - как в карточке\n- материал чехла: экокожа, внутри микрофибра"}
          value={r.text} onChange={(e) => setR({ ...r, text: e.target.value })} />
        <div><button className="pri" onClick={save}>Сохранить правила</button></div>
      </div>
      {nm > 0 && <RecoMap shop={shop} nm={nm} />}
    </div>
  );
}

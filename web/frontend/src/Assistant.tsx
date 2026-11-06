import { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Table = { title: string; columns: { field: string; title: string; type: string }[]; rows: Record<string, unknown>[];
  draft?: { shop: number; id: number } };
type Msg = { id: number; role: "user" | "assistant"; content: string | null; status: "pending" | "done" | "error";
  data: { steps?: string[]; tables?: Table[] } | null; created_at: string; files?: { id: number; name: string; mime: string }[] | null };
type Att = { id?: number; name: string; mime?: string; busy?: boolean; err?: string; file: File };
type Chat = { id: number; title: string | null; updated_at: string };
type Status = { ok: boolean; plan: string; reason: string | null; limit: number | null; used: number | null; name: string };

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const fmt = (v: unknown) => (typeof v === "number" ? nf.format(v) : v == null ? "" : String(v));

/** Чем гномик занят, пока его не спрашивают . */
export const GNOME_ACTS: { act: string; say: string }[] = [
  { act: "laptop", say: "Смотрю цифры магазина…" }, { act: "write", say: "Пишу отчёт за вчера ✍️" },
  { act: "coffee", say: "Кофе-брейк ☕" }, { act: "sleep", say: "Тсс… разбуди вопросом 😴" },
  { act: "lens", say: "Ищу, где теряем деньги 🔍" },
  { act: "phone", say: "Звоню на склад 📞" }, { act: "calc", say: "Считаю юнитку 🧮" },
  { act: "book", say: "Читаю оферту WB 📖" }, { act: "tree", say: "Поливаю денежное дерево 🌱" },
  { act: "coins", say: "Жонглирую бюджетом 🪙" }, { act: "scope", say: "Подглядываю за конкурентами 🔭" },
  { act: "box", say: "Собираю поставку 📦" }, { act: "party", say: "Продажи растут! 🎉" },
  { act: "zen", say: "Медитирую на ДРР 🧘" }, { act: "music", say: "Слушаю отзывы покупателей 🎧" },
];

/** Гномик «Стометрик»: колпак, борода, моргает и покачивается; act — занятие (ноутбук, пишет, кофе, спит, лупа). */
export function Gnome({ size = 64, talking = false, act = "" }: { size?: number; talking?: boolean; act?: string }) {
  return (
    <svg className={"gnome" + (talking ? " talking" : "") + (act ? " act-" + act : "")} width={size} height={size} viewBox="0 0 64 64"
      style={{ overflow: "visible" }} aria-hidden="true">
      <g className="gnome-body">
        <path className="gnome-hat" d="M14 30 Q32 -6 50 30 Z" fill="#7c3aed" />
        <circle cx="47" cy="10" r="3.5" fill="#f9a8d4" className="gnome-pom" />
        <rect x="12" y="27" width="40" height="6" rx="3" fill="#5b21b6" />
        <ellipse cx="32" cy="38" rx="13" ry="10" fill="#fcd9b8" />
        <g className="gnome-eyes"><circle cx="27" cy="36" r="1.8" fill="#1f2937" /><circle cx="37" cy="36" r="1.8" fill="#1f2937" /></g>
        <circle cx="32" cy="40.5" r="3" fill="#f59e9e" />
        <path d="M18 41 Q20 62 32 62 Q44 62 46 41 Q39 47 32 46 Q25 47 18 41 Z" fill="#f3f4f6" stroke="#d1d5db" strokeWidth="0.8" />
        <path className="gnome-mouth" d="M29 49 Q32 51.5 35 49" stroke="#9ca3af" strokeWidth="1.2" fill="none" strokeLinecap="round" />
        {act === "coffee" && <g className="g-coffee">
          <g className="g-steam"><path d="M46 40 q-2 -3 0 -6 q2 -3 0 -6" stroke="#9ca3af" strokeWidth="1" fill="none" />
            <path d="M50 40 q-2 -3 0 -6 q2 -3 0 -6" stroke="#9ca3af" strokeWidth="1" fill="none" /></g>
          <rect x="43" y="42" width="10" height="11" rx="2" fill="#f97316" /><path d="M53 45 q4 0 4 3 q0 3 -4 3" stroke="#f97316" strokeWidth="1.8" fill="none" />
        </g>}
        {act === "phone" && <g className="g-phone"><rect x="41" y="31" width="6" height="11" rx="1.5" fill="#111827" /><rect x="42" y="32.5" width="4" height="7" rx="0.6" fill="#60a5fa" />
          <circle cx="45" cy="44" r="2.6" fill="#fcd9b8" /><g className="g-ring"><path d="M50 30 q3 3 0 6" stroke="#7c3aed" strokeWidth="1.2" fill="none" /><path d="M53 28 q5 5 0 10" stroke="#7c3aed" strokeWidth="1.2" fill="none" /></g></g>}
        {act === "music" && <g className="g-music"><path d="M17 33 Q32 14 47 33" stroke="#111827" strokeWidth="2.4" fill="none" />
          <rect x="13" y="31" width="6" height="9" rx="2.5" fill="#ef4444" /><rect x="45" y="31" width="6" height="9" rx="2.5" fill="#ef4444" />
          <g className="g-notes"><text x="52" y="22" fontSize="9" fill="#7c3aed">♪</text><text x="6" y="20" fontSize="8" fill="#ec4899">♫</text></g></g>}
        {act === "lens" && <g className="g-lens"><circle cx="40" cy="38" r="6.5" fill="rgba(191,219,254,.45)" stroke="#374151" strokeWidth="1.8" />
          <line x1="44.6" y1="42.6" x2="51" y2="49" stroke="#92400e" strokeWidth="2.6" strokeLinecap="round" /></g>}
      </g>
      {act === "laptop" && <g className="g-laptop">
        <rect x="16" y="43" width="32" height="15" rx="1.5" fill="#cbd5e1" stroke="#94a3b8" strokeWidth="0.8" />
        <circle cx="32" cy="50.5" r="2" fill="#f8fafc" /><rect x="10" y="58" width="44" height="3.5" rx="1.5" fill="#94a3b8" />
        <g className="g-glow"><ellipse cx="32" cy="42" rx="11" ry="3.5" fill="#bfdbfe" opacity=".5" /></g>
      </g>}
      {act === "write" && <g className="g-write">
        <rect x="4" y="55" width="56" height="5" rx="1.5" fill="#92400e" /><rect x="8" y="60" width="3" height="4" fill="#78350f" /><rect x="53" y="60" width="3" height="4" fill="#78350f" />
        <rect x="18" y="50" width="20" height="6" rx="0.8" fill="#fff" stroke="#e5e7eb" strokeWidth="0.6" transform="rotate(-4 28 53)" />
        <g className="g-lines"><line x1="21" y1="52.6" x2="33" y2="51.8" stroke="#9ca3af" strokeWidth="0.6" /></g>
        <g className="g-pencil"><line x1="38" y1="44" x2="33" y2="52" stroke="#f59e0b" strokeWidth="2.2" strokeLinecap="round" />
          <circle cx="44" cy="47" r="2.6" fill="#fcd9b8" /></g>
      </g>}
      {act === "calc" && <g className="g-calc"><rect x="20" y="46" width="24" height="17" rx="2" fill="#374151" /><rect x="23" y="48.5" width="18" height="4.5" rx="0.8" fill="#86efac" />
        <text className="g-calc-n" x="39.5" y="52.3" fontSize="4.2" textAnchor="end" fill="#14532d" fontWeight="700">+15%</text>
        {[0, 1, 2, 3].map((i) => <rect key={i} x={23.5 + i * 4.4} y="55.5" width="3.4" height="2.6" rx="0.6" fill="#9ca3af" />)}
        {[0, 1, 2, 3].map((i) => <rect key={"b" + i} x={23.5 + i * 4.4} y="59" width="3.4" height="2.6" rx="0.6" fill="#9ca3af" />)}
        <circle className="g-finger" cx="25" cy="55" r="2.4" fill="#fcd9b8" /></g>}
      {act === "book" && <g className="g-book"><path d="M14 47 L32 50 L32 63 L14 60 Z" fill="#2563eb" /><path d="M50 47 L32 50 L32 63 L50 60 Z" fill="#1d4ed8" />
        <path d="M16 48 L31 50.6 L31 61.5 L16 59 Z" fill="#fff" /><path d="M48 48 L33 50.6 L33 61.5 L48 59 Z" fill="#f8fafc" />
        <g className="g-page"><path d="M33 50.6 L46 48.5 L46 58.5 L33 61 Z" fill="#e5e7eb" /></g>
        <line x1="18" y1="52" x2="29" y2="53.7" stroke="#cbd5e1" strokeWidth="0.6" /><line x1="18" y1="55" x2="29" y2="56.7" stroke="#cbd5e1" strokeWidth="0.6" /></g>}
      {act === "tree" && <g className="g-tree"><rect x="-6" y="54" width="12" height="9" rx="1.5" fill="#b45309" /><rect x="-1" y="44" width="2" height="10" fill="#78350f" />
        <g className="g-leaves"><circle cx="-4" cy="44" r="4" fill="#22c55e" /><circle cx="3" cy="41" r="4.5" fill="#16a34a" /><circle cx="0" cy="38" r="3.5" fill="#4ade80" />
          <text x="-6.5" y="46" fontSize="4" fill="#fef08a">₽</text><text x="1.5" y="42" fontSize="4" fill="#fef08a">₽</text></g>
        <g className="g-can"><path d="M44 46 h10 v8 h-10 z" fill="#0ea5e9" /><path d="M44 47 l-8 -4" stroke="#0ea5e9" strokeWidth="2" /><circle cx="54" cy="50" r="2.5" fill="#fcd9b8" />
          <g className="g-drops"><circle cx="34" cy="45" r="0.9" fill="#38bdf8" /><circle cx="33" cy="48" r="0.9" fill="#38bdf8" /><circle cx="35" cy="50" r="0.9" fill="#38bdf8" /></g></g></g>}
      {act === "coins" && <g className="g-coins">{[0, 1, 2].map((i) => <g key={i} className={"g-coin g-coin" + i}><circle cx="32" cy="20" r="3.6" fill="#facc15" stroke="#ca8a04" strokeWidth="0.8" />
        <text x="30.4" y="21.6" fontSize="4.4" fill="#a16207" fontWeight="700">₽</text></g>)}
        <circle cx="20" cy="50" r="2.6" fill="#fcd9b8" /><circle cx="44" cy="50" r="2.6" fill="#fcd9b8" /></g>}
      {act === "scope" && <g className="g-scope"><g className="g-tube"><rect x="40" y="33" width="20" height="5" rx="1.5" fill="#6b7280" transform="rotate(-18 40 35)" />
        <rect x="56" y="25" width="5" height="7" rx="1" fill="#4b5563" transform="rotate(-18 58 28)" /></g>
        <line x1="48" y1="40" x2="44" y2="60" stroke="#78350f" strokeWidth="1.4" /><line x1="48" y1="40" x2="54" y2="60" stroke="#78350f" strokeWidth="1.4" /></g>}
      {act === "box" && <g className="g-box"><rect x="17" y="46" width="30" height="16" rx="1.2" fill="#d97706" /><rect x="17" y="46" width="30" height="4" fill="#b45309" />
        <rect x="29" y="46" width="6" height="16" fill="#fbbf24" opacity=".8" /><text x="20" y="59" fontSize="5" fill="#78350f" fontWeight="700">WB</text>
        <circle cx="17" cy="52" r="2.6" fill="#fcd9b8" /><circle cx="47" cy="52" r="2.6" fill="#fcd9b8" /></g>}
      {act === "party" && <g className="g-party">{["#ef4444", "#22c55e", "#3b82f6", "#eab308", "#ec4899", "#8b5cf6"].map((col, i) => (
        <rect key={i} className={"g-conf g-conf" + i} x={8 + i * 9} y="4" width="3" height="5" rx="0.6" fill={col} />))}
        <path d="M2 40 l10 -6 l-2 10 z" fill="#f97316" /><path d="M62 40 l-10 -6 l2 10 z" fill="#f97316" /></g>}
      {act === "zen" && <g className="g-zen"><ellipse cx="32" cy="63" rx="20" ry="3" fill="#7c3aed" opacity=".25" />
        <circle cx="12" cy="52" r="2.6" fill="#fcd9b8" /><circle cx="52" cy="52" r="2.6" fill="#fcd9b8" />
        <g className="g-om"><circle cx="22" cy="10" r="1.3" fill="#c4b5fd" /><circle cx="32" cy="5" r="1.7" fill="#a78bfa" /><circle cx="42" cy="10" r="1.3" fill="#c4b5fd" /></g></g>}
      {act === "sleep" && <g className="g-z"><text x="46" y="22" fontSize="8" fill="#7c3aed" fontWeight="700">z</text>
        <text x="52" y="14" fontSize="10" fill="#7c3aed" fontWeight="700">Z</text></g>}
    </svg>
  );
}

function csv(t: Table) {
  const esc = (v: unknown) => { const s = fmt(v).replace(/ /g, " "); return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const body = [t.columns.map((c) => esc(c.title)).join(";"), ...t.rows.map((r) => t.columns.map((c) => esc(typeof r[c.field] === "number" ? String(r[c.field]).replace(".", ",") : r[c.field])).join(";"))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob(["﻿" + body], { type: "text/csv;charset=utf-8" }));
  a.download = t.title.replace(/[^\wа-яё.\- ]+/gi, "_") + ".csv";
  a.click();
}

/** Черновик себестоимости от нейросети: записывает только человек этой кнопкой (у нейросети записи нет). */
function DraftApply({ d }: { d: { shop: number; id: number } }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const go = () => {
    if (!confirm(`Записать себестоимость из черновика №${d.id}? Проверьте таблицу перед записью.`)) return;
    setBusy(true); setErr("");
    http.post<{ updated: number; same: number; not_found: number }>(`/api/shops/${d.shop}/cost/drafts/${d.id}/apply`, {})
      .then((r) => setMsg(`✓ Записано: ${r.updated}, без изменений: ${r.same}, не найдено: ${r.not_found}`))
      .catch((e) => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="acc-row">
      {msg ? <span className="ok">{msg}</span> : <button disabled={busy} onClick={go}>{busy ? "Записываю…" : `Применить черновик №${d.id}`}</button>}
      {err && <span className="err">{err}</span>}
    </div>
  );
}

function TableView({ t }: { t: Table }) {
  return (
    <div className="as-table-wrap">{t.draft && <DraftApply key={t.draft.id} d={t.draft} />}<table className="board-t">
      <thead><tr>{t.columns.map((c) => <th key={c.field}>{c.title}</th>)}</tr></thead>
      <tbody>{t.rows.map((r, i) => <tr key={i} className={r[t.columns[0].field] === "ИТОГО" ? "tot" : ""}>
        {t.columns.map((c) => <td key={c.field} className={typeof r[c.field] === "number" ? "n" : ""}>{fmt(r[c.field])}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

/** Чат «Стометрика» справа + панель с таблицей ответа. */
export function Assistant({ shop, open, onClose, gnome, onGnome }: { shop: number | null; open: boolean; onClose: () => void;
  gnome: boolean; onGnome: (v: boolean) => void }) {
  const [st, setSt] = useState<Status | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [chat, setChat] = useState<number | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [side, setSide] = useState<Table | null>(null);
  const [att, setAtt] = useState<Att[]>([]);
  const fileIn = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const timer = useRef<number | undefined>(undefined);
  const pending = msgs.some((m) => m.status === "pending");

  const loadChats = () => shop && http.get<Chat[]>(`/api/assistant/chats?shop=${shop}`).then((x) => { setChats(x); setChat((c) => c ?? x[0]?.id ?? null); });
  const loadMsgs = (id: number) => http.get<{ messages: Msg[] }>(`/api/assistant/chats/${id}`).then((x) => {
    setMsgs((old) => {
      const was = new Set(old.filter((m) => m.status === "pending").map((m) => m.id));
      const fresh = x.messages.find((m) => was.has(m.id) && m.status === "done" && m.data?.tables?.length);
      if (fresh) setSide(fresh.data!.tables![fresh.data!.tables!.length - 1]);
      return x.messages;
    });
  }).catch((e) => setErr(e.message));
  useEffect(() => {
    if (!open || !shop) return;
    setChat(null); setMsgs([]); setSide(null); setErr("");
    http.get<Status>(`/api/assistant/status?shop=${shop}`).then(setSt).catch(() => undefined);
    loadChats();
  }, [open, shop]);
  useEffect(() => { if (chat) loadMsgs(chat); else setMsgs([]); }, [chat]);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (pending && chat) timer.current = window.setTimeout(() => loadMsgs(chat), 2000);
    return () => window.clearTimeout(timer.current);
  }, [msgs, chat]);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs.length, pending]);

  const ensureChat = async () => {
    if (chat) return chat;
    const id = (await http.post<{ id: number }>("/api/assistant/chats", { shop_id: shop })).id;
    setChat(id); loadChats();
    return id;
  };
  const addFiles = async (list: File[]) => {
    if (!shop || !list.length) return;
    setErr("");
    let id: number;
    try { id = await ensureChat(); } catch (e) { setErr((e as Error).message); return; }
    for (const f of list.slice(0, 5)) {
      const name = f.name && f.name !== "image.png" ? f.name : `скриншот-${new Date().toLocaleTimeString("ru-RU").replace(/:/g, "-")}.png`;
      const a: Att = { name, file: f, busy: true };
      setAtt((x) => [...x, a]);
      try {
        const r = await fetch(`/api/assistant/chats/${id}/files?name=${encodeURIComponent(name)}`, { method: "POST", body: f, credentials: "same-origin",
          headers: { "Content-Type": "application/octet-stream" } });
        const j = await r.json();
        if (!r.ok) throw new Error(j.detail || r.statusText);
        setAtt((x) => x.map((y) => (y === a ? { ...y, id: j.id, mime: j.mime, busy: false } : y)));
      } catch (e) { setAtt((x) => x.map((y) => (y === a ? { ...y, busy: false, err: (e as Error).message } : y))); }
    }
  };
  const send = async () => {
    const t = text.trim();
    const ready = att.filter((a) => a.id);
    if ((!t && !ready.length) || !shop || pending || att.some((a) => a.busy)) return;
    setErr("");
    try {
      const id = await ensureChat();
      await http.post(`/api/assistant/chats/${id}/messages`, { text: t, files: ready.map((a) => a.id) });
      setText(""); setAtt([]);
      loadMsgs(id);
      http.get<Status>(`/api/assistant/status?shop=${shop}`).then(setSt).catch(() => undefined);
    } catch (e) { setErr((e as Error).message); }
  };
  if (!open) return null;
  return (
    <>
      {side && <div className="as-side">
        <div className="as-head"><b>📊 {side.title}</b>
          <span><button onClick={() => csv(side)} title="Скачать для Excel">⬇ Excel</button><button onClick={() => setSide(null)}>✕</button></span></div>
        <TableView t={side} />
        <div className="hint">Цифры — из базы сервиса, посчитаны кодом.</div>
      </div>}
      <div className="as-panel">
        <div className="as-head">
          <span className="as-title"><Gnome size={34} talking={pending} /> <b>Стометрик</b></span>
          <span>
            <select value={chat ?? ""} onChange={(e) => setChat(e.target.value ? Number(e.target.value) : null)} title="История чатов">
              <option value="">+ Новый чат</option>
              {chats.map((c) => <option key={c.id} value={c.id}>{(c.title || "Чат").slice(0, 40)}</option>)}
            </select>
            <button onClick={onClose} title="Закрыть">✕</button>
          </span>
        </div>
        <div className="as-msgs" ref={box}>
          {!msgs.length && <div className="as-hello"><Gnome size={72} />
            <p>Привет! Я Стометрик, помощник по твоему магазину. Спроси, например:</p>
            {["Посчитай логистику за вчера по каждому артикулу", "Какие артикулы были в минусе на прошлой неделе?", "Сколько потратили на рекламу за месяц?"]
              .map((q) => <button key={q} className="as-sugg" onClick={() => setText(q)}>{q}</button>)}
          </div>}
          {msgs.map((m) => (
            <div key={m.id} className={"as-msg " + m.role + (m.status === "error" ? " error" : "")}>
              {m.status === "pending" ? <div className="as-wait"><span className="dots">Думаю</span>
                {(m.data?.steps || []).map((s, i) => <div key={i} className="hint">· {s}</div>)}</div>
                : <div className="as-text">{m.content}</div>}
              {!!m.files?.length && <div className="as-files">{m.files.map((f) => f.mime.startsWith("image/")
                ? <a key={f.id} href={`/api/assistant/files/${f.id}`} target="_blank" rel="noreferrer"><img src={`/api/assistant/files/${f.id}`} alt={f.name} /></a>
                : <a key={f.id} className="as-file" href={`/api/assistant/files/${f.id}`} target="_blank" rel="noreferrer">📄 {f.name}</a>)}</div>}
              {m.data?.tables?.map((t, i) => <button key={i} className="as-tbl" onClick={() => setSide(t)}>📊 {t.title} ({t.rows.length} стр.)</button>)}
            </div>))}
        </div>
        {err && <div className="err">{err}</div>}
        {st && !st.ok ? <div className="as-off">{st.reason}</div> : (
          <div className="as-in-wrap" onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); addFiles(Array.from(e.dataTransfer.files)); }}>
            {!!att.length && <div className="as-att">{att.map((a, i) => (
              <span key={i} className={"as-chip" + (a.err ? " bad" : "")} title={a.err || a.name}>
                {a.busy ? "⏳" : a.err ? "⚠️" : a.file.type.startsWith("image/") ? "🖼" : "📄"} {a.name.slice(0, 24)}
                <b onClick={() => setAtt((x) => x.filter((_, j) => j !== i))}>×</b></span>))}</div>}
            <div className="as-input">
              <button className="as-clip" title="Прикрепить фото, скриншот, PDF или Excel (можно вставить скриншот Ctrl+V или перетащить файл)"
                onClick={() => fileIn.current?.click()}>📎</button>
              <input ref={fileIn} type="file" multiple hidden accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.docx,.pptx,.xlsx,.xlsm,.csv,.txt"
                onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }} />
              <textarea value={text} placeholder="Спроси Стометрика… (скриншот — Ctrl+V)" rows={2} onChange={(e) => setText(e.target.value)}
                onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs); } }}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
              <button disabled={pending || att.some((a) => a.busy) || (!text.trim() && !att.some((a) => a.id))} onClick={send}>➤</button>
            </div>
          </div>)}
        <div className="as-foot hint">
          {st?.limit != null ? `Сегодня ${st.used} из ${st.limit} сообщений · ` : ""}
          <label><input type="checkbox" checked={gnome} onChange={(e) => onGnome(e.target.checked)} /> гномик в углу</label>
        </div>
      </div>
    </>
  );
}

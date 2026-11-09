import { useEffect, useState } from "react";
import { api } from "./api";

/** Telegram: бот «Стометрик» (помощник + уведомления) — подключить, утренняя сводка (время МСК), ИИ-сводка, предупреждения, тест. */
export function Notify() {
  const [s, setS] = useState<Awaited<ReturnType<typeof api.notify>> | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const load = () => api.notify().then(setS).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  useEffect(() => {   // ждём, пока человек нажмёт «Старт» в боте
    if (!s || s.connected) return;
    const t = setInterval(() => api.notify().then((x) => { if (x.connected) setS(x); }).catch(() => undefined), 5000);
    return () => clearInterval(t);
  }, [s?.connected]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!s) return <div className="acc-box"><b>Уведомления в Telegram</b>{err ? <div className="err">{err}</div> : <div className="hint">Загрузка…</div>}</div>;
  const save = (v: Partial<typeof s>) => {
    const n = { ...s, ...v };
    setS(n);
    api.setNotify({ daily: n.daily, daily_time: n.daily_time, alerts: n.alerts, ai: n.ai, kinds: Object.fromEntries(n.kinds.map((k) => [k.key, k.on])),
      send_from: n.send_from, send_to: n.send_to, daily_mine: n.daily_mine, muted_shops: n.shops.filter((x) => !x.on).map((x) => x.id) }).then(() => { setMsg("Сохранено"); setTimeout(() => setMsg(""), 2000); })
      .catch((e) => setErr(e.message));
  };
  return (
    <div className="acc-box">
      <b>{s.assistant ? "Стометрик и уведомления в Telegram" : "Уведомления в Telegram"}</b>
      {err && <div className="err">{err}</div>}
      {msg && <div className="ok">{msg}</div>}
      <div className="acc-row"><span>Бот</span>
        {s.connected ? <>✅ подключён {s.bot && <a href={`https://t.me/${s.bot}`} target="_blank" rel="noreferrer">@{s.bot}</a>}
          {s.link && <a className="hint" href={s.link} target="_blank" rel="noreferrer" title="Привязать этот Telegram к этому аккаунту заново"> · переподключить</a>}</> : (
          s.link ? <a className="tg-btn" href={s.link} target="_blank" rel="noreferrer">Подключить Telegram</a> : <span className="hint">бот не настроен</span>
        )}
      </div>
      {!s.connected && s.link && <div className="hint">Откроется бот — нажмите «Старт». Страница сама увидит подключение.</div>}
      {s.old_bot && <div className="hint">Сейчас уведомления приходят в старый бот. Подключите Стометрика: он и присылает сводки, и отвечает на вопросы по магазинам.</div>}
      {s.assistant && s.connected && <div className="hint">🧙 Пишите боту вопросы обычным текстом, как Стометрику на сайте: /shop — магазин, /new — новый разговор.</div>}
      <div className="acc-row"><span>Присылать</span>
        с <input type="time" value={s.send_from} onChange={(e) => save({ send_from: e.target.value })} />
        до <input type="time" value={s.send_to} onChange={(e) => save({ send_to: e.target.value })} /> МСК
      </div>
      <div className="hint">Вне этого времени уведомления копятся и приходят одной пачкой, когда время откроется. Одинаковое «с» и «до» — круглосуточно.
        Ответы Стометрика на ваши вопросы приходят всегда.</div>
      {s.shops.length > 1 && <div className="acc-row"><span>Магазины</span>
        <div className="notify-shops">{s.shops.map((x) => <label key={x.id} title={x.workspace || ""}>
          <input type="checkbox" checked={x.on} onChange={(e) => save({ shops: s.shops.map((y) => y.id === x.id ? { ...y, on: e.target.checked } : y) })} />
          {" "}{x.mp === "ozon" ? "🔵" : x.mp === "ym" ? "🟡" : "🟣"} {x.title}</label>)}</div>
      </div>}
      {s.shops.length > 1 && <div className="hint">По выключенным магазинам не приходят сводка, события и предупреждения. Ответы Стометрика — по любому магазину.</div>}
      <div className="acc-row"><span>Сводка</span>
        <label><input type="checkbox" checked={s.daily} onChange={(e) => save({ daily: e.target.checked })} /> каждое утро за вчера</label>
        <input type="time" value={s.daily_time} disabled={!s.daily} onChange={(e) => save({ daily_time: e.target.value })} /> МСК
      </div>
      {s.is_staff && <div className="acc-row"><span>Сводка по</span>
        <select value={s.daily_mine ? "1" : "0"} onChange={(e) => save({ daily_mine: e.target.value === "1" })}>
          <option value="0">всем артикулам магазинов</option><option value="1">только моим артикулам (я менеджер)</option></select>
      </div>}
      <div className="acc-row"><span>ИИ-сводка</span>
        <label><input type="checkbox" checked={s.ai} onChange={(e) => save({ ai: e.target.checked })} /> к утренней сводке — ошибки в кабинете от нейросети (неделя и вчера)</label>
      </div>
      <div className="acc-row"><span>Предупреждения</span>
        <label><input type="checkbox" checked={s.alerts} onChange={(e) => save({ alerts: e.target.checked })} /> ключ API истекает, данные не обновляются</label>
      </div>
      {s.kinds.map((k) => <div className="acc-row" key={k.key}><span>{k.key === s.kinds[0].key ? "События" : ""}</span>
        <label><input type="checkbox" checked={k.on} onChange={(e) => save({ kinds: s.kinds.map((x) => x.key === k.key ? { ...x, on: e.target.checked } : x) })} /> {k.title}</label>
      </div>)}
      {s.connected && <div className="acc-row"><span />
        <button onClick={() => api.notifyTest().then((r) => setMsg(r.ok ? "Сводка отправлена в Telegram" : "Не отправилось")).catch((e) => setErr(e.message))}>
          Прислать сводку сейчас</button></div>}
    </div>
  );
}

export function MagicPage({ tok, onDone }: { tok: string; onDone: () => void }) {
  const [info, setInfo] = useState<{ email: string; purpose: string } | null>(null);
  const [err, setErr] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  useEffect(() => { api.magicInfo(tok).then((i) => {
    setInfo(i);
    if (i.purpose === "login") api.magicUse(tok).then(() => { window.history.replaceState(null, "", "/"); onDone(); }).catch((e) => setErr(e.message));
  }).catch((e) => setErr(e.message)); }, [tok]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="login">
      <form onSubmit={async (e) => {
        e.preventDefault(); setErr("");
        if (pw !== pw2) { setErr("Пароли не совпадают"); return; }
        try { await api.magicUse(tok, pw); window.history.replaceState(null, "", "/"); onDone(); } catch (x) { setErr((x as Error).message); }
      }}>
        <h1>AI-100metric</h1>
        {!info && !err && <div className="hint">Проверяю ссылку…</div>}
        {info?.purpose === "login" && !err && <div className="hint">Входим…</div>}
        {info?.purpose === "set_password" && <>
          <div>Добро пожаловать! Логин: <b>{info.email}</b></div>
          <input type="password" placeholder="Придумайте пароль (от 10 символов)" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
          <input type="password" placeholder="Пароль ещё раз" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          <button>Сохранить и войти</button>
        </>}
        {err && <div className="err">{err}</div>}
        {err && <a href="/" className="hint">На страницу входа</a>}
      </form>
    </div>
  );
}

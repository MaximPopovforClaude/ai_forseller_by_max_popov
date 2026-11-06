import { useEffect, useState } from "react";
import { http } from "./api";
import { copyCell } from "./copy";

type Block = { key: string; title: string; scope: "platform" | "market" };
type Grant = { id: number; name: string; kind: string; token_hint: string | null; shops: number[] | null; level: string; blocks: string[];
  created_at: string; expires_at: string | null; revoked_at: string | null; last_used_at: string | null; calls: number; workspace_id: number };
type ShopR = { id: number; title: string; workspace_id: number; marketplace: string; role: string };
type St = { grants: Grant[]; blocks: Block[]; levels: Record<string, string>; url: string; workspaces: { id: number; name: string; ok: boolean }[]; shops: ShopR[] };
export type GrantVal = { workspace_id: number; name: string; level: string; blocks: string[]; shops: number[] | null; days: number | null };
type LogRow = { at: string; tool: string; shop_id: number | null; method: string | null; path: string | null; ok: boolean; error: string | null; ms: number | null };

const dt = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
const MP: Record<string, string> = { wb: "WB", ozon: "Ozon", ym: "Маркет" };

/** Права подключения: уровень, блоки, магазины, срок — и в настройках, и на странице входа claude.ai / ChatGPT. */
export function GrantForm({ st, v, set, noDays }: { st: St; v: GrantVal; set: (v: GrantVal) => void; noDays?: boolean }) {
  const shops = st.shops.filter((s) => s.workspace_id === v.workspace_id);
  const wss = st.workspaces.filter((w) => w.ok);
  const flip = <T,>(a: T[], x: T) => (a.includes(x) ? a.filter((y) => y !== x) : [...a, x]);
  const blk = (scope: "platform" | "market") => (
    <div className="mcp-blocks">
      {st.blocks.filter((b) => b.scope === scope).map((b) => (
        <label key={b.key}><input type="checkbox" checked={v.blocks.includes(b.key)} onChange={() => set({ ...v, blocks: flip(v.blocks, b.key) })} /> {b.title}</label>))}
    </div>);
  return (
    <div className="mcp-form">
      <div className="acc-row"><span>Название</span><input value={v.name} onChange={(e) => set({ ...v, name: e.target.value })} placeholder="Claude, ChatGPT…" /></div>
      {wss.length > 1 && <div className="acc-row"><span>Кабинет</span>
        <select value={v.workspace_id} onChange={(e) => set({ ...v, workspace_id: +e.target.value, shops: null })}>
          {wss.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></div>}
      <div className="mcp-levels">
        {Object.entries(st.levels).map(([k, t]) => (
          <label key={k}><input type="radio" checked={v.level === k} onChange={() => set({ ...v, level: k })} /> {t}</label>))}
      </div>
      {v.level !== "read" && <><b>Что можно менять в платформе</b>{blk("platform")}</>}
      {v.level === "market" && <><b>Что можно менять в кабинете маркетплейса</b>
        <div className="hint">Изменения идут через «Действия»: блок должен быть включён там и нужен ключ на запись. Всё — в журнале, «Стоп» работает.
          Снижение цены больше порога и траты в рекламе подтверждает только человек на сайте.</div>{blk("market")}</>}
      <b>Магазины</b>
      <div className="mcp-blocks">
        <label><input type="checkbox" checked={v.shops === null} onChange={() => set({ ...v, shops: v.shops === null ? shops.map((s) => s.id) : null })} /> все, к которым у меня есть доступ</label>
        {v.shops !== null && shops.map((s) => (
          <label key={s.id}><input type="checkbox" checked={v.shops!.includes(s.id)} onChange={() => set({ ...v, shops: flip(v.shops!, s.id) })} /> {s.title} · {MP[s.marketplace] || s.marketplace}</label>))}
      </div>
      {!noDays && <div className="acc-row"><span>Срок</span>
        <select value={v.days ?? 0} onChange={(e) => set({ ...v, days: +e.target.value || null })}>
          <option value={30}>30 дней</option><option value={90}>90 дней</option><option value={365}>год</option><option value={0}>без срока</option></select></div>}
    </div>);
}

function GrantLog({ id }: { id: number }) {
  const [rows, setRows] = useState<LogRow[] | null>(null);
  useEffect(() => { http.get<{ rows: LogRow[] }>(`/api/mcp/grants/${id}/log`).then((r) => setRows(r.rows)).catch(() => setRows([])); }, [id]);
  if (!rows) return <div className="hint">Загрузка…</div>;
  if (!rows.length) return <div className="hint">Вызовов ещё не было.</div>;
  return (
    <table className="mcp-log"><tbody>
      {rows.map((r, i) => (
        <tr key={i} className={r.ok ? "" : "bad"}><td>{dt(r.at)}</td><td>{r.tool === "api" ? `${r.method} ${r.path}` : r.tool}</td>
          <td>{r.shop_id ?? ""}</td><td>{r.ok ? "✓" : r.error}</td></tr>))}
    </tbody></table>);
}

/** «Нейросети (MCP)»: свои нейросети подключаются к данным платформы — права на каждое подключение . */
export function AiLinks({ wsId }: { wsId: number }) {
  const [st, setSt] = useState<St | null>(null);
  const [err, setErr] = useState("");
  const [nw, setNw] = useState<GrantVal | null>(null);
  const [edit, setEdit] = useState<(GrantVal & { id: number }) | null>(null);
  const [tok, setTok] = useState("");
  const [log, setLog] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => http.get<St>("/api/mcp/grants").then(setSt).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  if (!st) return <div className="hint">{err || "Загрузка…"}</div>;
  const ws0 = st.workspaces.find((w) => w.id === wsId && w.ok) || st.workspaces.find((w) => w.ok);
  const sname = (id: number) => st.shops.find((s) => s.id === id)?.title || `#${id}`;
  const run = async (f: () => Promise<unknown>) => { setBusy(true); setErr(""); try { await f(); await load(); } catch (e) { setErr((e as Error).message); } setBusy(false); };
  const active = st.grants.filter((g) => !g.revoked_at);
  const cfg = tok ? `claude mcp add --transport http seller-analytics ${st.url} --header "Authorization: Bearer ${tok}"` : "";
  return (
    <div className="acc mcp">
      <h2>🔌 Нейросети (MCP)</h2>
      <div className="hint">Подключите свою нейросеть — Claude, ChatGPT, Gemini и другие — к данным платформы. Она берёт вкладки, товары и таблицы
        за период; цифры считает платформа. На каждое подключение — свои права: только чтение, изменения в платформе, изменения в кабинете
        маркетплейса и какие именно блоки. Отозвать — одной кнопкой.</div>
      <div className="acc-box">
        <b>Адрес для подключения</b>
        <div className="acc-row"><code className="mcp-url" onClick={(e) => copyCell(st.url, e.nativeEvent)} title="Нажмите — скопировать">{st.url}</code></div>
        <ul className="hint">
          <li><b>claude.ai</b> (сайт и приложение): Настройки → Коннекторы → «Добавить свой коннектор» → вставьте адрес → «Подключить»: откроется
            наш сайт, выберите права. Нужен тариф Claude Pro / Max / Team.</li>
          <li><b>ChatGPT</b>: Настройки → Приложения и коннекторы → Расширенные → «Режим разработчика» → «Создать» → адрес, вход OAuth.</li>
          <li><b>Claude Code, Cursor, Gemini CLI и др.</b>: создайте токен ниже и добавьте адрес с заголовком <code>Authorization: Bearer токен</code>.</li>
        </ul>
      </div>
      {err && <div className="err">{err}</div>}
      {tok && <div className="acc-box mcp-tok">
        <b>Токен создан — скопируйте сейчас, больше он не покажется</b>
        <code onClick={(e) => copyCell(tok, e.nativeEvent)} title="Нажмите — скопировать">{tok}</code>
        <div className="hint">Claude Code:</div>
        <code onClick={(e) => copyCell(cfg, e.nativeEvent)} title="Нажмите — скопировать">{cfg}</code>
        <button onClick={() => setTok("")}>Скопировал, скрыть</button>
      </div>}
      {!ws0 ? <div className="hint">Подключение своих нейросетей — на тарифах с нейросетью («Наша нейросеть», «Ваша нейросеть»).</div>
        : nw ? <div className="acc-box">
          <b>Новый токен</b>
          <GrantForm st={st} v={nw} set={setNw} />
          <div className="acc-row">
            <button disabled={busy || !nw.name.trim()} onClick={() => run(async () => { const r = await http.post<{ token: string }>("/api/mcp/grants", nw); setTok(r.token); setNw(null); })}>Создать токен</button>
            <button onClick={() => setNw(null)}>Отмена</button></div>
        </div>
          : <button className="mcp-add" onClick={() => setNw({ workspace_id: ws0.id, name: "", level: "read", blocks: [], shops: null, days: 90 })}>＋ Новый токен</button>}
      <h3>Подключения</h3>
      {!st.grants.length && <div className="hint">Пока нет. Подключите claude.ai / ChatGPT по адресу выше или создайте токен.</div>}
      {st.grants.map((g) => (
        <div key={g.id} className={"acc-box mcp-g" + (g.revoked_at ? " off" : "")}>
          <div className="acc-row"><b>{g.name}</b><span className="mcp-kind">{g.kind === "oauth" ? "вход через сайт нейросети" : `токен …${g.token_hint || ""}`}</span>
            {g.revoked_at && <span className="mcp-kind">отозвано {dt(g.revoked_at)}</span>}</div>
          {edit?.id === g.id ? <>
            <GrantForm st={st} v={edit} set={(v) => setEdit({ ...v, id: g.id })} noDays />
            <div className="acc-row"><button disabled={busy} onClick={() => run(async () => { await http.put(`/api/mcp/grants/${g.id}`, edit); setEdit(null); })}>Сохранить</button>
              <button onClick={() => setEdit(null)}>Отмена</button></div></> : <>
            <div className="hint">{st.levels[g.level]}{g.blocks.length ? ": " + g.blocks.map((b) => st.blocks.find((x) => x.key === b)?.title || b).join("; ") : ""}</div>
            <div className="hint">Магазины: {g.shops ? g.shops.map(sname).join(", ") : "все доступные"} · создано {dt(g.created_at)}
              {g.expires_at && ` · до ${dt(g.expires_at)}`} · вызовов {g.calls}{g.last_used_at && `, последний ${dt(g.last_used_at)}`}</div>
            <div className="acc-row">
              {!g.revoked_at && <button onClick={() => setEdit({ ...g, days: null })}>Права</button>}
              <button onClick={() => setLog(log === g.id ? null : g.id)}>{log === g.id ? "Скрыть журнал" : "Журнал"}</button>
              {!g.revoked_at && <button disabled={busy} onClick={() => confirm(`Отозвать «${g.name}»? Нейросеть сразу потеряет доступ.`) && run(() => http.del(`/api/mcp/grants/${g.id}`))}>Отозвать</button>}
            </div></>}
          {log === g.id && <GrantLog id={g.id} />}
        </div>))}
      {active.length > 0 && <div className="hint">Активных подключений: {active.length}.</div>}
    </div>);
}

/** Страница входа для claude.ai / ChatGPT (OAuth): пользователь выбирает права — и возвращается в нейросеть. */
export function OAuthConsent({ wsId }: { wsId: number | null }) {
  const q = new URLSearchParams(window.location.search);
  const [st, setSt] = useState<St | null>(null);
  const [cl, setCl] = useState<{ name: string; host: string } | null>(null);
  const [v, setV] = useState<GrantVal | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (q.get("response_type") !== "code" || !q.get("client_id") || !q.get("redirect_uri") || !q.get("code_challenge")) {
      setErr("Неполная ссылка входа — начните подключение заново в нейросети"); return;
    }
    http.get<{ name: string; host: string }>(`/api/oauth/client?client_id=${encodeURIComponent(q.get("client_id")!)}&redirect_uri=${encodeURIComponent(q.get("redirect_uri")!)}`)
      .then(setCl).catch((e) => setErr(e.message));
    http.get<St>("/api/mcp/grants").then((s) => {
      setSt(s);
      const w = s.workspaces.find((x) => x.id === wsId && x.ok) || s.workspaces.find((x) => x.ok);
      if (w) setV({ workspace_id: w.id, name: "", level: "read", blocks: [], shops: null, days: 90 });
    }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => { if (cl && v && !v.name) setV({ ...v, name: cl.name }); }, [cl, v]);
  const go = async () => {
    setBusy(true); setErr("");
    try {
      const r = await http.post<{ redirect: string }>("/api/oauth/approve", { ...v, client_id: q.get("client_id"), redirect_uri: q.get("redirect_uri"),
        state: q.get("state"), code_challenge: q.get("code_challenge"), code_challenge_method: q.get("code_challenge_method") || "S256" });
      window.location.href = r.redirect;
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  return (
    <div className="acc mcp mcp-consent">
      <h2>🔌 Подключение нейросети</h2>
      {err && <div className="err">{err}</div>}
      {cl && st && (v ? <div className="acc-box">
        <div><b>{cl.name}</b> ({cl.host}) просит доступ к данным платформы platform.example.org. Выберите права — их можно изменить или отозвать
          в «Настройки → 🔌 Нейросети».</div>
        <GrantForm st={st} v={v} set={setV} />
        <div className="acc-row">
          <button disabled={busy || !v.name.trim()} onClick={go}>Разрешить</button>
          <button onClick={() => { const u = new URL(q.get("redirect_uri")!); u.searchParams.set("error", "access_denied"); if (q.get("state")) u.searchParams.set("state", q.get("state")!); window.location.href = u.toString(); }}>Отказать</button>
        </div></div>
        : <div className="hint">Подключение своих нейросетей — на тарифах с нейросетью.</div>)}
    </div>);
}

import { PersonalAI } from "./PersonalAI";
import { useEffect, useRef, useState } from "react";
import { http } from "./api";
import { copyCell } from "./copy";
import { LegalAdminForm } from "./Legal";
import { ShopArchive, type ArchiveShop } from "./ShopArchive";

type R = Record<string, unknown>;
const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const dt = (s: unknown) => (s ? new Date(String(s)).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");
const SECTIONS = [["overview", "Обзор"], ["users", "Пользователи"], ["workspaces", "Кабинеты и тарифы"], ["shops", "Магазины"],
  ["payments", "Платежи"], ["promo", "Промокоды"], ["plans", "Цены тарифов"], ["settings", "Настройки"], ["legal", "Документы"], ["audit", "Журнал"]] as const;

function Table({ rows, cols }: { rows: R[]; cols: [string, string, ((r: R) => React.ReactNode)?][] }) {
  return (
    <div className="board-wrap"><table className="board-t">
      <thead><tr>{cols.map(([k, t]) => <th key={k}>{t}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{cols.map(([k, , f]) => <td key={k}>{f ? f(r) : String(r[k] ?? "")}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

export function Admin({ onShopsChanged }: { onShopsChanged: () => void }) {
  const [sec, setSec] = useState<string>("overview");
  const [data, setData] = useState<R | R[] | null>(null);
  const [plans, setPlans] = useState<R[]>([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [archiveShop, setArchiveShop] = useState<ArchiveShop | null>(null);
  const section = useRef(sec); section.current = sec;
  const request = useRef(0);
  const [promo, setPromo] = useState({ code: "", kind: "percent", value: "", plan: "", max_uses: "", valid_until: "", note: "" });
  const load = () => {
    if (section.current !== sec) return;
    const seq = ++request.current;
    setErr(""); setData(null);
    if (sec === "legal") return;
    http.get<R | R[]>(`/api/admin/${sec === "audit" ? "audit?limit=300" : sec}`)
      .then(d => { if (seq === request.current && section.current === sec) setData(d); })
      .catch(e => { if (seq === request.current && section.current === sec) setErr(e.message); });
  };
  useEffect(() => { setArchiveShop(null); load(); return () => { request.current++; }; }, [sec]);
  useEffect(() => { http.get<R[]>("/api/admin/plans").then(setPlans).catch(() => undefined); }, []);
  const done = (m: string) => { setOk(m); setTimeout(() => setOk(""), 2500); load(); };
  const fail = (e: Error) => setErr(e.message);
  const rows = Array.isArray(data) ? data : [];
  return (
    <div className="acc admin">
      <h2>Админка сервиса</h2>
      <div className="adm-tabs">{SECTIONS.map(([k, t]) => <button key={k} className={sec === k ? "on" : ""} onClick={() => setSec(k)}>{t}</button>)}</div>
      {ok && <div className="ok">{ok}</div>}
      {err && <div className="err">{err}</div>}
      {!data && !err && sec !== "legal" && <div className="hint">Загрузка…</div>}
      {sec === "overview" && data && !Array.isArray(data) && (
        <div className="ins-cards">
          {([["users", "Пользователей"], ["users_7d", "Новых за 7 дней"], ["workspaces", "Кабинетов"], ["shops", "Магазинов"], ["tg_connected", "Подключили бота"],
            ["paid_30d", "Оплат за 30 дней, ₽"], ["paid_total", "Оплат всего, ₽"], ["pending", "Ждут оплаты"], ["stale_collectors", "Сборщиков с ошибкой >6 ч"]] as const)
            .map(([k, t]) => <div key={k} className="ins-card"><div className="hint">{t}</div><b>{nf.format(Number(data[k] ?? 0))}</b></div>)}
          <div className="ins-card"><div className="hint">По тарифам</div>
            {Object.entries((data.plans as Record<string, number>) || {}).map(([k, v]) => <div key={k}>{String(plans.find((p) => p.key === k)?.title || k)}: <b>{v}</b></div>)}</div>
        </div>
      )}
      {sec === "users" && <Table rows={rows} cols={[["id", "ID"], ["email", "E-mail"], ["name", "Имя"], ["workspaces", "Кабинеты"],
        ["tg", "Telegram", (r) => (r.tg ? "✓" : "")], ["created_at", "Создан", (r) => dt(r.created_at)], ["last_login_at", "Вход", (r) => dt(r.last_login_at)],
        ["referred_by", "Пригласил"], ["invited", "Привёл"], ["bonus_balance", "Бонусы", (r) => nf.format(Number(r.bonus_balance))],
        ["is_active", "Доступ", (r) => r.is_superadmin ? "суперадмин" : <button onClick={() => {
          if (r.is_active && !confirm(`Заблокировать ${r.email}? Сессии будут закрыты.`)) return;
          http.put(`/api/admin/users/${r.id}`, { is_active: !r.is_active }).then(() => done("Сохранено")).catch(fail); }}>{r.is_active ? "Заблокировать" : "Разблокировать"}</button>]]} />}
      {sec === "workspaces" && <Table rows={rows} cols={[["id", "ID"], ["name", "Кабинет"], ["owner", "Владелец"], ["members", "Людей"], ["shops", "Магазинов"],
        ["paid", "Оплачено, ₽", (r) => nf.format(Number(r.paid))],
        ["plan", "Тариф и срок", (r) => <WsPlan r={r} plans={plans} onSaved={() => done("Тариф сохранён")} onErr={fail} />],
        ["assistant_limit", "Стометрик, сообщ./день", (r) => <AsLimit r={r} onSaved={() => done("Лимит сохранён")} onErr={fail} />]]} />}
      {sec === "workspaces" && <PersonalAI onSaved={() => done("Настройки VIP сохранены")} />}
      {sec === "shops" && <>
        <label><input type="checkbox" checked={showArchived} onChange={e => { setShowArchived(e.target.checked); setArchiveShop(null); }} /> Показать удалённые магазины</label>
        {archiveShop && <ShopArchive key={`${archiveShop.id}:${archiveShop.archived_at || "active"}`} shop={archiveShop}
          onCancel={() => setArchiveShop(null)} onDone={() => { setArchiveShop(current => current === archiveShop ? null : current);
            done(archiveShop.archived_at ? "Магазин восстановлен" : "Магазин удалён в архив"); onShopsChanged(); }} />}
        <Table rows={rows.filter(r => showArchived || !r.archived_at)} cols={[["id", "ID"], ["title", "Магазин", r => String(r.title || r.name)], ["workspace", "Кабинет"],
        ["marketplace", "Площадка"], ["state", "Статус", r => r.archived_at ? `Удалён ${dt(r.archived_at)}` : r.is_active ? "Активен" : "Выключен"], ["cards", "Карточек"],
        ["last_ok", "Последний сбор", (r) => dt(r.last_ok)], ["token_exp", "Ключ до", (r) => (r.token_exp ? new Date(String(r.token_exp)).toLocaleDateString("ru-RU") : "в .env")],
        ["stale", "Ошибки", (r) => (Number(r.stale) ? <span className="down" title={String(r.errors || "")}>{String(r.stale)} сборщ.</span> : "—")],
        ["actions", "Действия", r => <button onClick={() => setArchiveShop(r as ArchiveShop)}>{r.archived_at ? "Восстановить" : "Удалить"}</button>]]} />
      </>}
      {sec === "payments" && <Table rows={rows} cols={[["id", "№"], ["created_at", "Дата", (r) => dt(r.created_at)], ["workspace", "Кабинет"], ["email", "Кто"],
        ["plan", "Тариф"], ["months", "Мес."], ["amount", "Сумма, ₽", (r) => nf.format(Number(r.amount))], ["promo_code", "Промокод"], ["provider", "Способ"],
        ["status", "Статус", (r) => r.status === "pending" ? <>
          <button onClick={() => confirm(`Отметить платёж №${r.id} оплаченным? Тариф продлится.`) && http.post(`/api/admin/payments/${r.id}/paid`).then(() => done("Оплачено")).catch(fail)}>Оплачен</button>
          <button className="link" onClick={() => http.post(`/api/admin/payments/${r.id}/cancel`).then(() => done("Отменён")).catch(fail)}>отменить</button></> : String(r.status)]]} />}
      {sec === "promo" && <>
        <div className="acc-box">
          <b>Новый промокод</b>
          <div className="acc-row"><span>Код</span><input value={promo.code} onChange={(e) => setPromo({ ...promo, code: e.target.value.toUpperCase() })} placeholder="START30" /></div>
          <div className="acc-row"><span>Вид</span><select value={promo.kind} onChange={(e) => setPromo({ ...promo, kind: e.target.value })}>
            <option value="percent">скидка, %</option><option value="fixed">скидка, ₽</option><option value="days">бесплатные дни</option></select>
            <input className="w80" value={promo.value} onChange={(e) => setPromo({ ...promo, value: e.target.value })} placeholder="значение" /></div>
          <div className="acc-row"><span>Тариф</span><select value={promo.plan} onChange={(e) => setPromo({ ...promo, plan: e.target.value })}>
            <option value="">любой</option>{plans.map((p) => <option key={String(p.key)} value={String(p.key)}>{String(p.title)}</option>)}</select></div>
          <div className="acc-row"><span>Лимит</span><input className="w80" value={promo.max_uses} onChange={(e) => setPromo({ ...promo, max_uses: e.target.value })} placeholder="без лимита" />
            <span>до</span><input type="date" value={promo.valid_until} onChange={(e) => setPromo({ ...promo, valid_until: e.target.value })} /></div>
          <div className="acc-row"><span>Заметка</span><input value={promo.note} onChange={(e) => setPromo({ ...promo, note: e.target.value })} placeholder="для кого / откуда" /></div>
          <button onClick={() => http.post("/api/admin/promo", { code: promo.code, kind: promo.kind, value: Number(promo.value), plan: promo.plan || null,
            max_uses: promo.max_uses ? Number(promo.max_uses) : null, valid_until: promo.valid_until || null, note: promo.note || null })
            .then(() => { setPromo({ code: "", kind: "percent", value: "", plan: "", max_uses: "", valid_until: "", note: "" }); done("Промокод сохранён"); }).catch(fail)}>Сохранить</button>
        </div>
        <Table rows={rows} cols={[["code", "Код"], ["kind", "Вид", (r) => ({ percent: "%", fixed: "₽", days: "дней" } as R)[String(r.kind)] as string],
          ["value", "Значение"], ["plan", "Тариф"], ["used", "Использован", (r) => `${r.used}${r.max_uses != null ? " из " + r.max_uses : ""}`],
          ["valid_until", "До"], ["note", "Заметка"],
          ["active", "Активен", (r) => <button onClick={() => http.post("/api/admin/promo", { ...r, active: !r.active }).then(() => done("Сохранено")).catch(fail)}>{r.active ? "выключить" : "включить"}</button>]]} />
      </>}
      {sec === "plans" && <div className="plans">{rows.map((p) => <PlanEdit key={String(p.key)} p={p} onSaved={() => done("Тариф сохранён")} onErr={fail} />)}</div>}
      {sec === "settings" && data && !Array.isArray(data) && <Settings data={data} onSaved={() => done("Сохранено")} onErr={fail} />}
      {sec === "legal" && <LegalAdminForm onSaved={() => setOk("Сохранено")} onErr={fail} />}
      {sec === "audit" && <Table rows={rows} cols={[["at", "Когда", (r) => dt(r.at)], ["email", "Кто"], ["workspace", "Кабинет"], ["action", "Действие"],
        ["details", "Подробности", (r) => <code className="small">{JSON.stringify(r.details).slice(0, 200)}</code>]]} />}
      {sec === "support" && data && !Array.isArray(data) && <Support d={data} onDone={(m) => done(m)} onErr={fail} />}
      {sec !== "support" && <div className="hint" style={{ marginTop: 30 }}><button className="link" onClick={() => setSec("support")}>доступ к кабинету клиента…</button></div>}
    </div>
  );
}

/** Скрытый раздел : кабинет клиента — только после его устного согласия, на время, только просмотр; запись — в журналы. */
function Support({ d, onDone, onErr }: { d: R; onDone: (m: string) => void; onErr: (e: Error) => void }) {
  const [ws, setWs] = useState("");
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState("2");
  const list = (d.workspaces as R[]) || [];
  const log = (d.log as R[]) || [];
  return <div className="acc-box">
    <b>Доступ к кабинету клиента (поддержка)</b>
    <div className="disclaimer">⚠️ Открывать только после устного согласия клиента. Доступ — только просмотр, на время; запись о нём попадает
      в журнал админки и в журнал кабинета клиента. Магазины клиента появятся в выборе магазинов с пометкой «поддержка до …».</div>
    <div className="acc-row"><span>Кабинет</span><select value={ws} onChange={(e) => setWs(e.target.value)}><option value="">— выберите —</option>
      {list.map((w) => <option key={String(w.id)} value={String(w.id)}>{String(w.name)} · владелец {String(w.owner || "?")} · магазинов {String(w.shops)}</option>)}</select></div>
    <div className="acc-row"><span>Согласие</span><textarea rows={2} placeholder="Кто из клиента и когда дал согласие, зачем: например «Александр Кутин, звонок 27.10 16:40 — разобраться с ключом нейросети»"
      value={reason} onChange={(e) => setReason(e.target.value)} /></div>
    <div className="acc-row"><span>Срок</span><select value={hours} onChange={(e) => setHours(e.target.value)}>
      {[["0.5", "30 минут"], ["1", "1 час"], ["2", "2 часа"], ["4", "4 часа"], ["8", "8 часов"], ["24", "24 часа"]].map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></div>
    <div className="acc-row"><span /><button className="pri" disabled={!ws || reason.trim().length < 10}
      onClick={() => http.post("/api/admin/support", { workspace_id: Number(ws), reason, hours: Number(hours) })
        .then(() => { onDone("Доступ открыт — обновляю страницу"); setTimeout(() => location.reload(), 800); }).catch(onErr)}>Открыть доступ (только просмотр)</button></div>
    {log.length > 0 && <table className="acc-t"><thead><tr><th>Кабинет</th><th>Согласие</th><th>Открыт</th><th>До</th><th></th></tr></thead><tbody>
      {log.map((x) => <tr key={String(x.id)}><td>{String(x.ws)}</td><td>{String(x.reason)}</td><td>{dt(x.granted_at)}</td>
        <td>{x.revoked_at ? `закрыт ${dt(x.revoked_at)}` : dt(x.until)}</td>
        <td>{x.active ? <button onClick={() => http.del(`/api/admin/support/${x.id}`).then(() => { onDone("Доступ закрыт"); setTimeout(() => location.reload(), 800); }).catch(onErr)}>Закрыть</button> : null}</td></tr>)}
    </tbody></table>}
  </div>;
}

function WsPlan({ r, plans, onSaved, onErr }: { r: R; plans: R[]; onSaved: () => void; onErr: (e: Error) => void }) {
  const [plan, setPlan] = useState(String(r.plan));
  const [until, setUntil] = useState(r.plan_until ? String(r.plan_until) : "");
  const dirty = plan !== String(r.plan) || until !== (r.plan_until ? String(r.plan_until) : "");
  return (
    <span className="ws-plan">
      <select value={plan} onChange={(e) => setPlan(e.target.value)}>{plans.map((p) => <option key={String(p.key)} value={String(p.key)}>{String(p.title)}</option>)}</select>
      <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} title="Оплачено по (пусто — без срока)" />
      {dirty && <button onClick={() => http.put(`/api/admin/workspaces/${r.id}`, { plan, plan_until: until || null }).then(onSaved).catch(onErr)}>Сохранить</button>}
    </span>
  );
}

function PlanEdit({ p, onSaved, onErr }: { p: R; onSaved: () => void; onErr: (e: Error) => void }) {
  const [title, setTitle] = useState(String(p.title));
  const [about, setAbout] = useState(String(p.about || ""));
  const [price, setPrice] = useState(p.price_month == null ? "" : String(p.price_month));
  const [active, setActive] = useState(Boolean(p.active));
  return (
    <div className="plan cur">
      <input value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea rows={3} value={about} onChange={(e) => setAbout(e.target.value)} />
      <label>Цена, ₽/мес <input className="w80" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="не задана" /></label>
      <label><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> показывать</label>
      <button onClick={() => http.put(`/api/admin/plans/${p.key}`, { title, about, price_month: price.trim() ? Number(price.replace(",", ".")) : null, active })
        .then(onSaved).catch(onErr)}>Сохранить</button>
    </div>
  );
}

function Settings({ data, onSaved, onErr }: { data: R; onSaved: () => void; onErr: (e: Error) => void }) {
  const list = (data.settings as { key: string; title: string; value: unknown }[]) || [];
  const integ = (data.integrations as Record<string, unknown>) || {};
  const [vals, setVals] = useState<Record<string, string>>(Object.fromEntries(list.map((s) => [s.key, String(s.value ?? "")])));
  return (
    <>
      <div className="acc-box">
        <b>Настройки</b>
        {list.map((s) => (
          <div key={s.key} className="acc-row"><span>{s.title}</span>
            {typeof s.value === "boolean" ? (
              <input type="checkbox" checked={vals[s.key] === "true"} onChange={(e) => {
                setVals({ ...vals, [s.key]: String(e.target.checked) });
                http.put(`/api/admin/settings/${s.key}`, { value: e.target.checked }).then(onSaved).catch(onErr); }} />
            ) : <>
              <input className="w80" value={vals[s.key]} onChange={(e) => setVals({ ...vals, [s.key]: e.target.value })} />
              <button onClick={() => http.put(`/api/admin/settings/${s.key}`, { value: Number(vals[s.key].replace(",", ".")) }).then(onSaved).catch(onErr)}>Сохранить</button>
            </>}
          </div>
        ))}
      </div>
      <div className="acc-box">
        <b>Подключения</b>
        <div className="acc-row"><span>Wildbox (конкуренты)</span>{`ключ у каждого кабинета свой; подключили: ${integ.wildbox ?? 0}`}</div>
        <div className="acc-row"><span>ИИ Стометрика</span>Свой API-ключ нейросети в настройках каждого аккаунта</div>
        <div className="hint">Создайте своего бота в @BotFather. После сохранения токена перезапустите ai-stometric-bots. Плановые уведомления и платные ИИ-разборы включаются отдельно в настройках выше.</div>
        <BotToken title="Бот Стометрика (Telegram)" path="assistant_bot" name={integ.assistant_bot as string | null} onSaved={onSaved} onErr={onErr} />
        <GoogleDrive g={integ.google as GStatus | undefined} onSaved={onSaved} onErr={onErr} />
        <Offsite o={integ.offsite as OStatus | undefined} onSaved={onSaved} onErr={onErr} />
        <div className="acc-row"><span>ЮKassa (оплата картой)</span>{integ.yookassa ? "✓ подключена" : "нет YOOKASSA_SHOP_ID / YOOKASSA_SECRET в .env"}</div>
      </div>
    </>
  );
}

type GStatus = { client: boolean; connected: boolean; email: string | null; folder_url: string | null; redirect: string };

/** Google Таблицы: OAuth-клиент владельца (Client ID / secret) → «Подключить» → выгрузки в папке на его Диске */
function GoogleDrive({ g, onSaved, onErr }: { g?: GStatus; onSaved: () => void; onErr: (e: Error) => void }) {
  const [id, setId] = useState("");
  const [sec, setSec] = useState("");
  if (!g) return null;
  return (
    <div className="acc-row"><span>Google Таблицы (выгрузка вкладок)</span>
      {g.connected ? <>✓ {g.email}{g.folder_url && <> · <a href={g.folder_url} target="_blank" rel="noreferrer">папка выгрузок</a></>}</>
        : g.client ? "клиент сохранён — нажмите «Подключить Google»" : "не подключено"}
      <input autoComplete="off" placeholder="Client ID" value={id} onChange={(e) => setId(e.target.value)} />
      <input type="password" autoComplete="off" placeholder="Client secret" value={sec} onChange={(e) => setSec(e.target.value)} />
      <button disabled={!id.trim() || !sec.trim()} onClick={() => http.put("/api/admin/google", { client_id: id, client_secret: sec })
        .then(() => { setId(""); setSec(""); onSaved(); }).catch(onErr)}>Сохранить</button>
      {g.client && <button onClick={() => http.get<{ url: string }>("/api/admin/google/connect").then((r) => { location.href = r.url; }).catch(onErr)}>
        {g.connected ? "Переподключить Google" : "Подключить Google"}</button>}
      <span className="hint">URI перенаправления для Google Cloud: <code>{g.redirect}</code></span>
    </div>
  );
}

type OStatus = { configured: boolean; key_ok: boolean; endpoint: string | null; region: string | null; bucket: string | null; last_ok: string | null;
  last_file: string | null; last_size: number | null; last_error: string | null; last_at: string | null };

/** Вторая копия бэкапа базы в S3 (зашифрованная): доступ к бакету, ключ шифрования (один раз), итог последней отправки */
function Offsite({ o, onSaved, onErr }: { o?: OStatus; onSaved: () => void; onErr: (e: Error) => void }) {
  const [f, setF] = useState({ endpoint: "https://s3.twcstorage.ru", region: "ru-1", bucket: "", access_key: "", secret_key: "" });
  const [pass, setPass] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  if (!o) return null;
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  const when = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU") : "—");
  return (
    <div className="acc-row"><span>Бэкап базы в S3 (вторая копия, зашифрована)</span>
      {o.configured ? <>✓ {o.bucket}{o.last_ok ? ` · последняя копия ${when(o.last_ok)}${o.last_size ? `, ${(o.last_size / 1e9).toFixed(1)} ГБ` : ""}` : " · копий ещё не было"}
        {o.last_error && <div className="err">Ошибка {when(o.last_at)}: {o.last_error}</div>}</> : "не подключено"}
      <input autoComplete="off" placeholder="Адрес (endpoint)" value={f.endpoint} onChange={set("endpoint")} />
      <input autoComplete="off" placeholder="Регион" value={f.region} onChange={set("region")} />
      <input autoComplete="off" placeholder="Имя бакета" value={f.bucket} onChange={set("bucket")} />
      <input type="password" autoComplete="off" placeholder="Access key" value={f.access_key} onChange={set("access_key")} />
      <input type="password" autoComplete="off" placeholder="Secret key" value={f.secret_key} onChange={set("secret_key")} />
      <button disabled={busy || !f.bucket.trim() || !f.access_key.trim() || !f.secret_key.trim()} onClick={() => {
        setBusy(true);
        http.put<{ passphrase: string | null }>("/api/admin/offsite", f).then((r) => {
          setF({ ...f, access_key: "", secret_key: "" }); setPass(r.passphrase); onSaved(); }).catch(onErr).finally(() => setBusy(false)); }}>
        {busy ? "Проверяю…" : "Проверить и сохранить"}</button>
      {o.configured && <button onClick={() => http.post("/api/admin/offsite/run", {}).then(() => setMsg("Отправка запущена: 5–10 минут, итог появится здесь после обновления страницы")).catch(onErr)}>
        Отправить копию сейчас</button>}
      {msg && <span className="hint">{msg}</span>}
      {pass && <div className="err">🔑 Ключ шифрования копий — показывается <b>один раз</b>. Сохраните в менеджер паролей: без него бэкап не расшифровать.
        <div><code onClick={(e) => copyCell(pass, e.nativeEvent)} title="нажмите, чтобы скопировать">{pass}</code></div>
        Расшифровать: <code>gpg -d файл.dump.gpg &gt; файл.dump</code></div>}
    </div>
  );
}

function BotToken({ title, path, name, onSaved, onErr }: { title: string; path: string; name: string | null; onSaved: () => void; onErr: (e: Error) => void }) {
  const [v, setV] = useState("");
  return (
    <div className="acc-row"><span>{title}</span>
      {name ? <a href={`https://t.me/${name}`} target="_blank" rel="noreferrer">✓ @{name}</a> : "не подключён"}
      <input type="password" autoComplete="off" placeholder={name ? "новый токен" : "токен из @BotFather"} value={v} onChange={(e) => setV(e.target.value)} />
      <button disabled={!v.trim()} onClick={() => http.put(`/api/admin/${path}`, { token: v }).then(() => { setV(""); onSaved(); }).catch(onErr)}>Сохранить</button>
    </div>
  );
}

function AsLimit({ r, onSaved, onErr }: { r: R; onSaved: () => void; onErr: (e: Error) => void }) {
  const init = r.assistant_limit == null ? "" : String(r.assistant_limit);
  const [v, setV] = useState(init);
  return (
    <span className="ws-plan" title="Лимит сообщений Стометрику в день для кабинета на тарифе «Наша нейросеть». Пусто — общий лимит из «Настроек»">
      <input className="w60" value={v} placeholder="общий" onChange={(e) => setV(e.target.value.replace(/\D/g, ""))} />
      {v !== init && <button onClick={() => http.put(`/api/admin/workspaces/${r.id}/assistant_limit`, { limit: v === "" ? null : Number(v) }).then(onSaved).catch(onErr)}>Сохранить</button>}
    </span>
  );
}

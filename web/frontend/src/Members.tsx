import { useEffect, useRef, useState } from "react";
import { api, type Invite, type Member, type WorkspaceInfo } from "./api";
import { PasswordResetControl } from "./PasswordReset";

const GRANT = ["viewer", "editor", "admin"];
const dt = (s: string | null) => (s ? new Date(s).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }) : "—");

/** Выбор магазинов: «все» (null) или список. */
function ShopPick({ w, value, onChange, disabled = false }: { w: WorkspaceInfo; value: number[] | null; onChange: (v: number[] | null) => void; disabled?: boolean }) {
  return (
    <div className="shop-pick">
      <label><input type="checkbox" disabled={disabled} checked={value === null} onChange={(e) => onChange(e.target.checked ? null : w.shops.map((s) => s.id))} /> все магазины (включая будущие)</label>
      {value !== null && w.shops.map((s) => (
        <label key={s.id}><input type="checkbox" disabled={disabled} checked={value.includes(s.id)}
          onChange={(e) => onChange(e.target.checked ? [...value, s.id] : value.filter((x) => x !== s.id))} /> {s.title || s.name}</label>
      ))}
    </div>
  );
}

function Row({ w, m, onDone, setErr }: { w: WorkspaceInfo; m: Member; onDone: () => void; setErr: (s: string) => void }) {
  const [role, setRole] = useState(m.role);
  const [shops, setShops] = useState<number[] | null>(m.shop_ids);
  const dirty = role !== m.role || JSON.stringify(shops) !== JSON.stringify(m.shop_ids);
  const owner = m.role === "owner";
  return (
    <tr>
      <td>{m.name ? <><b>{m.name}</b><br /></> : null}{m.email}</td>
      <td>{owner ? w.roles.owner : (
        <select value={role} onChange={(e) => setRole(e.target.value)}>{GRANT.map((r) => <option key={r} value={r}>{w.roles[r]}</option>)}</select>
      )}</td>
      <td>{owner ? "все" : <ShopPick w={w} value={shops} onChange={setShops} />}</td>
      <td>{dt(m.last_login_at)}</td>
      <td className="acts">{!owner && <>
        {dirty && <button className="pri" onClick={() => api.setMember(w.id, m.id, { role, shop_ids: shops }).then(onDone).catch((e) => setErr(e.message))}>Сохранить</button>}
        <button onClick={() => { if (confirm(`Забрать доступ у ${m.email}?`)) api.removeMember(w.id, m.id).then(onDone).catch((e) => setErr(e.message)); }}>Убрать доступ</button>
        {w.can_reset_passwords && m.is_active && !m.is_superadmin && <PasswordResetControl key={`${w.id}:${m.id}`} id={m.id} email={m.email} workspace={w.id} />}
      </>}</td>
    </tr>
  );
}

export function Members({ w, reload }: { w: WorkspaceInfo; reload: () => void }) {
  const [inv, setInv] = useState<Invite[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [shops, setShops] = useState<number[] | null>([]);
  const [link, setLink] = useState("");
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);
  const [ok, setOk] = useState("");
  const loadInv = () => api.invites(w.id).then(setInv).catch(() => setInv([]));
  useEffect(() => { loadInv(); }, [w.id]);
  const done = () => { setErr(""); reload(); loadInv(); };
  const addExisting = async () => {
    if (sending.current) return;
    const scope = shops === null ? "все магазины" : w.shops.filter(s => shops.includes(s.id)).map(s => s.title || s.name).join(", ");
    if (!confirm(`Добавить ${email.trim()} в кабинет «${w.name}»?\nРоль: ${w.roles[role]}. Доступ: ${scope}.`)) return;
    sending.current = true; setBusy(true); setErr(""); setOk(""); setLink("");
    try {
      const result = await api.addExistingMember(w.id, { email, role, shop_ids: shops });
      setOk(`${result.email} добавлен в «${w.name}». Попросите пользователя обновить страницу и выбрать доступный магазин этого кабинета. Для плагина нужен код из настроек этого кабинета.`);
      setEmail(""); done();
    } catch (e) { setErr((e as Error).message); }
    finally { sending.current = false; setBusy(false); }
  };
  if (!w.members) return <div className="hint">Сотрудников добавляют админ и владелец кабинета. Ваша роль: {w.role_title}.</div>;
  return (
    <>
      {err && <div className="err">{err}</div>}
      {ok && <div className="ok">{ok}</div>}
      <div className="acc-box">
        <b>Добавить сотрудника</b>
        <div className="hint">Уже зарегистрирован? Укажите его e-mail входа и нажмите «Добавить существующего пользователя».
          Он получит доступ к выбранным магазинам по тарифу кабинета «{w.name}»: {w.plans[w.plan]?.title || w.plan}.
          Его личный кабинет и логин сохранятся. ИИ доступен только для разрешённых тарифом магазинов.</div>
        <div className="acc-row"><span>E-mail</span><input disabled={busy} className="w-email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="сотрудник@почта.ru — это его логин" /></div>
        <div className="acc-row"><span>Роль</span>
          <select disabled={busy} value={role} onChange={(e) => setRole(e.target.value)}>{GRANT.map((r) => <option key={r} value={r}>{w.roles[r]}</option>)}</select>
        </div>
        <div className="acc-row"><span>Магазины</span><ShopPick w={w} value={shops} onChange={setShops} disabled={busy} /></div>
        <div className="acc-row"><span />
          <button className="pri" disabled={busy || !email.includes("@") || shops?.length === 0} onClick={addExisting}>Добавить существующего пользователя</button>
          <button disabled={busy || !email.includes("@") || shops?.length === 0} onClick={() => api.invite(w.id, { email, role, shop_ids: shops })
            .then((r) => { setLink(r.link); setCopied(false); setEmail(""); done(); }).catch((e) => setErr(e.message))}>Создать приглашение</button>
        </div>
        {link && (
          <div className="invite-link">
            <div>Отправьте эту ссылку сотруднику (действует 7 дней, одноразовая). Новый пользователь задаст пароль, уже зарегистрированный введёт свой:</div>
            <div className="acc-row"><input readOnly value={link} onFocus={(e) => e.target.select()} />
              <button onClick={() => navigator.clipboard?.writeText(link).then(() => setCopied(true))}>{copied ? "Скопировано ✓" : "Копировать"}</button></div>
          </div>
        )}
      </div>
      <div className="acc-box">
        <b>У кого есть доступ</b>
        <table className="acc-t">
          <thead><tr><th>Пользователь</th><th>Роль</th><th>Магазины</th><th>Последний вход</th><th /></tr></thead>
          <tbody>{w.members.map((m) => <Row key={m.id + m.role + JSON.stringify(m.shop_ids)} w={w} m={m} onDone={done} setErr={setErr} />)}</tbody>
        </table>
      </div>
      {inv.length > 0 && (
        <div className="acc-box">
          <b>Ждут входа по приглашению</b>
          <table className="acc-t">
            <thead><tr><th>E-mail</th><th>Роль</th><th>Действует до</th><th /></tr></thead>
            <tbody>{inv.map((i) => (
              <tr key={i.id}><td>{i.email}</td><td>{w.roles[i.role]}</td><td>{dt(i.expires_at)}</td>
                <td className="acts"><button onClick={() => api.revokeInvite(w.id, i.id).then(done).catch((e) => setErr(e.message))}>Отозвать</button></td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </>
  );
}

export function InvitePage({ tok, onDone }: { tok: string; onDone: () => void }) {
  const [info, setInfo] = useState<{ email: string; workspace: string; role: string; has_account: boolean } | null>(null);
  const [err, setErr] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [name, setName] = useState("");
  useEffect(() => { api.inviteInfo(tok).then(setInfo).catch((e) => setErr(e.message)); }, [tok]);
  const go = () => { window.history.replaceState(null, "", "/"); onDone(); };
  return (
    <div className="login">
      <form onSubmit={async (e) => {
        e.preventDefault(); setErr("");
        if (!info?.has_account && pw !== pw2) { setErr("Пароли не совпадают"); return; }
        try { await api.acceptInvite(tok, pw, name); go(); } catch (x) { setErr((x as Error).message === "401" ? "Неверный пароль" : (x as Error).message); }
      }}>
        <h1>AI-100metric</h1>
        {!info && !err && <div className="hint">Проверяю приглашение…</div>}
        {info && <>
          <div>Вас пригласили в кабинет <b>«{info.workspace}»</b> с ролью <b>{info.role}</b>.</div>
          <div className="hint">Логин: {info.email}</div>
          {info.has_account ? (
            <input type="password" placeholder="Ваш пароль от AI-100metric" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
          ) : <>
            <input placeholder="Как вас зовут" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <input type="password" placeholder="Придумайте пароль (от 10 символов)" value={pw} onChange={(e) => setPw(e.target.value)} />
            <input type="password" placeholder="Пароль ещё раз" value={pw2} onChange={(e) => setPw2(e.target.value)} />
          </>}
          <button>Принять приглашение</button>
        </>}
        {err && <div className="err">{err}</div>}
        {err && <a href="/" className="hint">На страницу входа</a>}
      </form>
    </div>
  );
}

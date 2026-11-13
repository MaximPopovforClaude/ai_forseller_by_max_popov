import { useEffect, useRef, useState } from "react";
import { http } from "./api";

type Link = { url?: string; expires_at: string };

/** Only the service admin receives a manual link; members get delivery status. */
export function PasswordResetControl({ id, email, workspace, manual = false }: {
  id: number; email: string; workspace?: number; manual?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [link, setLink] = useState<Link | null>(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const sending = useRef(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  const request = async (delivery: "manual" | "telegram") => {
    if (sending.current) return;
    sending.current = true; setBusy(true); setErr(""); setLink(null); setCopied(false);
    const seq = generation.current;
    try {
      const result = await http.post<Link>(workspace === undefined ? `/api/admin/users/${id}/password-reset`
        : `/api/workspaces/${workspace}/members/${id}/password-reset`,
      workspace === undefined ? { delivery, confirm_email: email } : {});
      if (seq === generation.current) setLink(result);
    } catch (e) { if (seq === generation.current) setErr((e as Error).message); }
    finally { sending.current = false; if (seq === generation.current) setBusy(false); }
  };
  if (!open) return <button onClick={() => setOpen(true)}>Сбросить пароль</button>;
  return <div className="acc-box" style={{ minWidth: 270, maxWidth: 480 }}>
    <b>Смена пароля: {email}</b>
    <div className="hint">Пользователь сам задаст новый пароль. Ссылка действует 30 минут, один раз.
      Новый запрос отменит предыдущую ссылку восстановления. До смены пароля доступ продолжит работать.</div>
    {manual && <div className="disclaimer">Ссылка позволяет сменить пароль от всего аккаунта, включая другие кабинеты.
      Передавайте её лично только этому пользователю.</div>}
    <button disabled={busy} onClick={() => request("telegram")}>Отправить в Telegram</button>{" "}
    {manual && <button disabled={busy} onClick={() => request("manual")}>Создать ссылку для передачи</button>}
    {busy && <div className="hint">Создаю ссылку…</div>}
    {link && <div className="ok">
      {link.url ? <>
        <div>Ссылка готова. Передайте её пользователю до {new Date(link.expires_at).toLocaleTimeString("ru-RU")}.</div>
        <input aria-label="Ссылка для смены пароля" readOnly autoComplete="off" value={link.url} onFocus={e => e.target.select()} />
        <button onClick={async () => {
          setErr("");
          try {
            if (!navigator.clipboard) throw new Error("Буфер обмена недоступен. Выделите ссылку и скопируйте вручную.");
            await navigator.clipboard.writeText(link.url!); setCopied(true);
          } catch { setErr("Не удалось скопировать. Выделите ссылку в поле и скопируйте вручную."); }
        }}>{copied ? "Скопировано ✓" : "Копировать ссылку"}</button>
      </> : "Ссылка отправлена в привязанный Telegram через бот регистрации."}
    </div>}
    {err && <div className="err">{err}</div>}
    <button className="link" disabled={busy} onClick={() => { generation.current++; setOpen(false); setLink(null); setErr(""); }}>Закрыть</button>
  </div>;
}

export function PasswordResetPage() {
  const [token] = useState(() => window.location.hash.slice(1));
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const sending = useRef(false);
  useEffect(() => {
    let alive = true;
    window.history.replaceState(null, "", "/reset-password");
    if (!/^[\w-]{43}$/.test(token)) { setErr("Откройте полную ссылку из сообщения. Если срок истёк, запросите новую."); return; }
    http.post<{ email: string }>("/api/auth/password-reset/info", { token })
      .then(r => { if (alive) setEmail(r.email); }).catch(e => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [token]);
  return <div className="login"><form onSubmit={async e => {
    e.preventDefault(); if (sending.current || !email || done) return;
    setErr("");
    if (pw !== confirm) { setErr("Пароли не совпадают"); return; }
    if (pw.length < 10 || pw.length > 1024) { setErr("Пароль — от 10 до 1024 символов"); return; }
    sending.current = true; setBusy(true);
    try {
      await http.post("/api/auth/password-reset/confirm", { token, password: pw });
      setPw(""); setConfirm(""); setDone(true);
    } catch (e) { setErr((e as Error).message); }
    finally { sending.current = false; setBusy(false); }
  }}>
    <h1>Смена пароля</h1>
    {done ? <><div className="ok">Пароль сохранён. Прежние входы закрыты. Войдите с новым паролем.</div><a href="/">На страницу входа</a></> : <>
      {!email && !err && <div>Проверяю ссылку…</div>}
      {email && <>
        <div>Аккаунт: <b>{email}</b></div>
        <input aria-label="Новый пароль" type="password" autoComplete="new-password" required minLength={10} maxLength={1024}
          disabled={busy} value={pw} onChange={e => setPw(e.target.value)} placeholder="Новый пароль — от 10 символов" />
        <input aria-label="Повторите новый пароль" type="password" autoComplete="new-password" required minLength={10} maxLength={1024}
          disabled={busy} value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Повторите пароль" />
        <div className="hint">После сохранения все прежние входы в аккаунт будут закрыты.</div>
        <button disabled={busy}>{busy ? "Сохраняю…" : "Сохранить пароль"}</button>
      </>}
      {err && <div className="err">{err}</div>}
      <a href="/">Вернуться ко входу</a>
    </>}
  </form></div>;
}

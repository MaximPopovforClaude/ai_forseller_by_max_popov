"""Password recovery. Tokens stay hashed in PostgreSQL; no credentials in audit.

Manual delivery is restricted to the service owner. Workspace administrators can
only send to an existing registration Telegram binding. All mutations serialize
on the user's row, including magic-link login and password login.
"""
import hashlib
import html
import json
import re
import secrets

from fastapi import HTTPException

from . import auth

from .config import site_url
SITE = site_url()
MINUTES = 30
INVALID = "Ссылка недействительна, истекла или уже использована. Запросите новую ссылку."


def audit(c, actor, target, workspace, action, **details):
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,%s,%s)",
              (actor, workspace, "auth/password-reset:" + action,
               json.dumps({"target_user_id": target, **details})))


def lock_users(c, ids):
    return {r["id"]: r for r in c.execute(
        """SELECT id,email,is_active,is_superadmin,telegram_id FROM users
           WHERE id=ANY(%s) ORDER BY id FOR NO KEY UPDATE""", (sorted(set(ids)),))}


def authorize(c, actor, target_id, workspace=None):
    if actor.get("_mcp") or not actor.get("is_active", True):
        raise HTTPException(403, "Восстановление доступно только пользователям сайта")
    rows = lock_users(c, [actor["id"], target_id])
    me, target = rows.get(actor["id"]), rows.get(target_id)
    if not me or not me["is_active"]:
        raise HTTPException(403, "Нет доступа")
    if workspace is None:
        if not me["is_superadmin"]:
            raise HTTPException(403, "Скопировать ссылку может только владелец сервиса")
    else:
        member = c.execute("""SELECT role,shop_ids FROM memberships
                              WHERE workspace_id=%s AND user_id=%s FOR SHARE""",
                           (workspace, me["id"])).fetchone()
        if not member or not auth.can(member["role"], "admin") or member["shop_ids"] is not None:
            raise HTTPException(403, "Нужны права владельца или администратора всего кабинета")
        other = c.execute("SELECT role FROM memberships WHERE workspace_id=%s AND user_id=%s FOR SHARE",
                          (workspace, target_id)).fetchone()
        if not other or other["role"] == "owner":
            raise HTTPException(403, "Можно отправить ссылку только сотруднику этого кабинета")
    if not target:
        raise HTTPException(404, "Пользователь не найден")
    if not target["is_active"]:
        raise HTTPException(409, "Пользователь заблокирован. Сначала проверьте его статус.")
    if target["is_superadmin"]:
        raise HTTPException(403, "Владелец сервиса восстанавливает пароль через свой бот регистрации")
    return target


def issue(c, target, actor_id, delivery, workspace=None):
    """Caller holds actor + target user locks and has checked authority."""
    if delivery not in ("manual", "telegram"):
        raise HTTPException(400, "Выберите способ передачи ссылки")
    if delivery == "telegram" and not target["telegram_id"]:
        raise HTTPException(409, "Telegram регистрации не привязан. Обратитесь к владельцу сервиса за ссылкой.")
    rate = c.execute("""SELECT count(*) FILTER (WHERE created_at>clock_timestamp()-interval '1 minute') recent,
                               count(*) hour_count FROM password_reset_tokens
                        WHERE user_id=%s AND created_at>clock_timestamp()-interval '1 hour'""",
                     (target["id"],)).fetchone()
    issued = c.execute("""SELECT count(*) n FROM password_reset_tokens
                          WHERE issued_by=%s AND created_at>clock_timestamp()-interval '1 hour'""",
                       (actor_id,)).fetchone()["n"]
    if rate["recent"] or rate["hour_count"] >= 5 or issued >= 30:
        raise HTTPException(429, "Ссылку уже запрашивали. Повторите позже: не чаще раза в минуту и 5 раз в час на пользователя.")
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    c.execute("UPDATE password_reset_tokens SET used_at=clock_timestamp() WHERE user_id=%s AND used_at IS NULL",
              (target["id"],))
    row = c.execute("""INSERT INTO password_reset_tokens
        (token_hash,user_id,issued_by,workspace_id,delivery,status,expires_at)
        VALUES (%s,%s,%s,%s,%s,%s,clock_timestamp()+interval '30 minutes') RETURNING expires_at""",
        (digest, target["id"], actor_id, workspace, delivery, "ready" if delivery == "manual" else "pending")).fetchone()
    audit(c, actor_id, target["id"], workspace, "issued", delivery=delivery)
    c.commit()
    
    return {"url": f"{SITE}/reset-password#{token}", "expires_at": row["expires_at"], "digest": digest}


def deliver(c, target, actor_id, workspace, link, bot=None):
    """Explicit request only; no retry or alternative recipient after failure."""
    made_bot = bot is None
    ok = False
    try:
        if made_bot:
            from .bots import Bot
            bot = Bot("TG_BOT_REGISTER_TOKEN", quiet=True)
        if bot.token:
            result = bot.api("sendMessage", chat_id=target["telegram_id"], parse_mode="HTML",
                disable_web_page_preview=True,
                text=f"Смена пароля 100MC для <b>{html.escape(target['email'])}</b>.\n\n"
                     f"Ссылка одноразовая, действует {MINUTES} минут:\n{link['url']}\n\n"
                     "Если вы не просили менять пароль, не открывайте ссылку. Текущий пароль продолжит работать.")
            ok = bool(result and result.get("message_id"))
    except Exception:  
        ok = False
    finally:
        if made_bot and bot is not None:
            bot.http.close()
    c.execute("""UPDATE password_reset_tokens SET status=%s,
                 used_at=CASE WHEN %s THEN used_at ELSE clock_timestamp() END WHERE token_hash=%s""",
              ("ready" if ok else "failed", ok, link["digest"]))
    audit(c, actor_id, target["id"], workspace, "sent" if ok else "delivery-failed", delivery="telegram")
    c.commit()
    if not ok:
        raise HTTPException(502, "Не удалось отправить ссылку в Telegram. Откройте бот регистрации и нажмите «Старт»; затем запросите новую ссылку. Владелец сервиса также может передать ссылку лично.")


def token_hash(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise HTTPException(404, INVALID)
    return hashlib.sha256(token.encode()).hexdigest()


def info(c, token):
    row = c.execute("""SELECT u.email FROM password_reset_tokens t JOIN users u ON u.id=t.user_id
        WHERE t.token_hash=%s AND t.used_at IS NULL AND t.status='ready'
        AND t.expires_at>clock_timestamp() AND u.is_active""", (token_hash(token),)).fetchone()
    if not row:
        raise HTTPException(404, INVALID)
    return row


def complete(c, token, password):
    if not 10 <= len(password) <= 1024:
        raise HTTPException(400, "Пароль — от 10 до 1024 символов")
    digest = token_hash(token)
    row = c.execute("SELECT user_id FROM password_reset_tokens WHERE token_hash=%s", (digest,)).fetchone()
    if not row:
        raise HTTPException(404, INVALID)
    user = lock_users(c, [row["user_id"]]).get(row["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(404, INVALID)
    reset = c.execute("""UPDATE password_reset_tokens SET used_at=clock_timestamp()
        WHERE token_hash=%s AND used_at IS NULL AND status='ready'
        AND expires_at>clock_timestamp() RETURNING *""", (digest,)).fetchone()
    if not reset:
        raise HTTPException(404, INVALID)
    c.execute("UPDATE users SET password_hash=%s WHERE id=%s", (auth.hash_password(password), user["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=%s", (user["id"],))
    c.execute("UPDATE login_tokens SET used_at=clock_timestamp() WHERE user_id=%s AND used_at IS NULL", (user["id"],))
    c.execute("UPDATE password_reset_tokens SET used_at=clock_timestamp() WHERE user_id=%s AND used_at IS NULL", (user["id"],))
    audit(c, user["id"], user["id"], reset["workspace_id"], "completed", issued_by=reset["issued_by"], delivery=reset["delivery"])
    c.commit()
    return {"ok": True}

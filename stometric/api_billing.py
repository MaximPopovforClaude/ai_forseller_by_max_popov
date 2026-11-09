"""API: тарифы и оплата кабинета, реферальная программа пользователя, админка владельца сервиса (суперадмин)."""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import auth, billing, gdrive, offsite
from .bots import RESCUE_KEY, assistant_username, set_assistant_token
from .web import _audit, conn, current_user

router = APIRouter()



@router.get("/api/billing/{ws_id}")
def billing_info(ws_id: int, u=Depends(current_user), c=Depends(conn)):
    role = auth.workspace_role(c, u, ws_id)
    if not auth.can(role, "viewer"):
        raise HTTPException(403, "Нет доступа к кабинету")
    ws = c.execute("SELECT id,name,plan,plan_until FROM workspaces WHERE id=%s", (ws_id,)).fetchone()
    plans = c.execute("SELECT key,title,about,price_month FROM plans WHERE active ORDER BY sort").fetchall()
    from .web import PLANS
    route_plans = {key: PLANS[key]["title"] for key in ("owner", "ai", "mcp")}
    titles = {p["key"]: p["title"] for p in plans}
    ws = {**ws, "plan_title": route_plans.get(ws["plan"], titles.get(ws["plan"], ws["plan"]))}
    plans = [{**p, "title": route_plans.get(p["key"], p["title"]),
              "available": billing.purchase_unavailable(p["key"]) is None,
              "unavailable_reason": billing.purchase_unavailable(p["key"])} for p in plans]
    pays = c.execute("""SELECT id,plan,months,days,base_amount,discount,bonus_used,amount,promo_code,status,provider,pay_url,created_at,paid_at
                        FROM payments WHERE workspace_id=%s ORDER BY id DESC LIMIT 50""", (ws_id,)).fetchall() if auth.can(role, "admin") else []
    me = c.execute("SELECT bonus_balance FROM users WHERE id=%s", (u["id"],)).fetchone()
    return jsonable_encoder({"workspace": ws, "plans": plans, "payments": pays, "can_pay": auth.can(role, "admin"),
                             "months": billing.MONTHS, "bonus": float(me["bonus_balance"] or 0), "online": billing.yookassa_ready()})


class QuoteIn(BaseModel):
    plan: str
    months: int = 1
    promo: str | None = None
    use_bonus: bool = False


@router.post("/api/billing/{ws_id}/quote")
def billing_quote(ws_id: int, body: QuoteIn, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Оплачивает владелец или админ кабинета")
    u2 = c.execute("SELECT * FROM users WHERE id=%s", (u["id"],)).fetchone()
    return billing.quote(c, u2, body.plan, body.months, body.promo, body.use_bonus)


@router.post("/api/billing/{ws_id}/checkout")
def billing_checkout(ws_id: int, body: QuoteIn, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Оплачивает владелец или админ кабинета")
    u2 = c.execute("SELECT * FROM users WHERE id=%s", (u["id"],)).fetchone()
    res = billing.checkout(c, u2, ws_id, body.plan, body.months, body.promo, body.use_bonus)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    _audit(c, u, ws_id, "billing/checkout", {**body.model_dump(), "result": res.get("status"), "payment": res.get("payment_id")})
    c.commit()
    if res.get("manual"):
        try:
            from .bots import notify_admins
            notify_admins(c, f"💳 Заявка на оплату AI-100metric: {u['email']}, тариф {body.plan}, {body.months} мес. (платёж №{res['payment_id']})")
        except Exception:  
            pass
    return res


@router.post("/api/billing/yookassa/webhook")
async def yookassa_webhook(request: Request, c=Depends(conn)):
    """Уведомление ЮKassa. Тело не доверенное: берём только id платежа и перепроверяем статус у ЮKassa."""
    try:
        body = await request.json()
        pid = str(((body or {}).get("object") or {}).get("id") or "")[:64]
    except Exception:  
        pid = ""
    if pid:
        billing.yookassa_confirm(c, pid)
    return {"ok": True}



@router.get("/api/me/referral")
def referral(u=Depends(current_user), c=Depends(conn)):
    code = billing.ref_code(c, u["id"])
    from .bots import Bot
    try:
        reg = Bot("TG_BOT_REGISTER_TOKEN").username
    except Exception:  
        reg = None
    st = c.execute("""SELECT count(*) invited, count(*) FILTER (WHERE EXISTS (SELECT 1 FROM payments p WHERE p.user_id=x.id AND p.status='paid'
                      AND p.amount > 0)) paid FROM users x WHERE referred_by=%s""", (u["id"],)).fetchone()
    earned = c.execute("SELECT coalesce(sum(amount),0) s FROM ref_rewards WHERE referrer_id=%s", (u["id"],)).fetchone()["s"]
    bal = c.execute("SELECT bonus_balance FROM users WHERE id=%s", (u["id"],)).fetchone()["bonus_balance"]
    rows = c.execute("""SELECT x.email, x.created_at, coalesce((SELECT sum(amount) FROM ref_rewards r WHERE r.referee_id=x.id AND r.referrer_id=%s),0) reward
                        FROM users x WHERE x.referred_by=%s ORDER BY x.created_at DESC LIMIT 100""", (u["id"], u["id"])).fetchall()
    for r in rows:   
        name, _, dom = r["email"].partition("@")
        r["email"] = (name[:2] + "***@" + dom) if dom else "***"
    return jsonable_encoder({"code": code, "site_link": f"{billing.SITE}/?ref={code}",
                             "bot_link": f"https://t.me/{reg}?start=ref_{code}" if reg else None,
                             "percent": float(billing.setting(c, "ref_percent", 10) or 0), "invited": st["invited"], "paid": st["paid"],
                             "earned": float(earned), "balance": float(bal or 0), "rows": rows})


@router.get("/api/ref/{code}")
def ref_info(code: str, c=Depends(conn)):
    """Публично: ссылка на бот регистрации с реферальным кодом (для страницы входа по ссылке ?ref=)."""
    from .bots import Bot
    ok = billing.referrer_by_code(c, code) is not None
    try:
        reg = Bot("TG_BOT_REGISTER_TOKEN").username
    except Exception:  
        reg = None
    return {"ok": ok, "bot_link": f"https://t.me/{reg}?start=ref_{code.strip().upper()}" if reg and ok else (f"https://t.me/{reg}" if reg else None)}



def _sa(u):
    if not u["is_superadmin"]:
        raise HTTPException(403, "Только для владельца сервиса")


@router.get("/api/admin/overview")
def admin_overview(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    r = c.execute("""SELECT (SELECT count(*) FROM users) users, (SELECT count(*) FROM users WHERE created_at > now() - interval '7 days') users_7d,
                            (SELECT count(*) FROM workspaces) workspaces, (SELECT count(*) FROM accounts WHERE is_active) shops,
                            (SELECT count(*) FROM notify_settings WHERE chat_id IS NOT NULL) tg_connected,
                            (SELECT coalesce(sum(amount),0) FROM payments WHERE status='paid' AND paid_at > now() - interval '30 days') paid_30d,
                            (SELECT coalesce(sum(amount),0) FROM payments WHERE status='paid') paid_total,
                            (SELECT count(*) FROM payments WHERE status='pending') pending,
                            (SELECT count(*) FROM collector_state WHERE last_error IS NOT NULL AND last_error NOT ILIKE '%%лимит%%'
                               AND coalesce(last_ok_at,'epoch') < now() - interval '6 hours') stale_collectors""").fetchone()
    plans = c.execute("SELECT plan, count(*) n FROM workspaces GROUP BY 1").fetchall()
    return jsonable_encoder({**r, "plans": {p["plan"]: p["n"] for p in plans}})


@router.get("/api/admin/users")
def admin_users(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute(
        """SELECT x.id, x.email, x.name, x.is_superadmin, x.is_active, x.created_at, x.last_login_at, x.telegram_username,
                  (x.telegram_id IS NOT NULL) tg, x.bonus_balance, x.ref_code, r.email referred_by,
                  (SELECT count(*) FROM users y WHERE y.referred_by=x.id) invited,
                  (SELECT string_agg(w.name || ' (' || m.role || ')', ', ') FROM memberships m JOIN workspaces w ON w.id=m.workspace_id
                   WHERE m.user_id=x.id) workspaces
           FROM users x LEFT JOIN users r ON r.id=x.referred_by ORDER BY x.id DESC""").fetchall())


class AdminUserIn(BaseModel):
    is_active: bool | None = None
    bonus_balance: float | None = None


@router.put("/api/admin/users/{uid}")
def admin_user_set(uid: int, body: AdminUserIn, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    if uid == u["id"] and body.is_active is False:
        raise HTTPException(400, "Себя заблокировать нельзя")
    if body.is_active is not None:
        c.execute("UPDATE users SET is_active=%s WHERE id=%s", (body.is_active, uid))
        if not body.is_active:
            c.execute("DELETE FROM sessions WHERE user_id=%s", (uid,))
    if body.bonus_balance is not None:
        if not 0 <= body.bonus_balance <= 10_000_000:
            raise HTTPException(400, "Странный баланс")
        c.execute("UPDATE users SET bonus_balance=%s WHERE id=%s", (body.bonus_balance, uid))
    _audit(c, u, None, "admin/user", {"user": uid, **body.model_dump(exclude_none=True)})
    c.commit()
    return {"ok": True}


@router.get("/api/admin/workspaces")
def admin_workspaces(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute(
        """SELECT w.id, w.name, w.plan, w.plan_until, w.created_at, w.assistant_limit,
                  (SELECT string_agg(x.email, ', ') FROM memberships m JOIN users x ON x.id=m.user_id WHERE m.workspace_id=w.id AND m.role='owner') owner,
                  (SELECT count(*) FROM memberships m WHERE m.workspace_id=w.id) members,
                  (SELECT count(*) FROM accounts a WHERE a.workspace_id=w.id AND a.archived_at IS NULL) shops,
                  (SELECT coalesce(sum(amount),0) FROM payments p WHERE p.workspace_id=w.id AND p.status='paid') paid
           FROM workspaces w ORDER BY w.id DESC""").fetchall())


class AdminWsIn(BaseModel):
    plan: str
    plan_until: date | None = None


@router.put("/api/admin/workspaces/{ws_id}")
def admin_ws_set(ws_id: int, body: AdminWsIn, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    if not c.execute("SELECT 1 FROM plans WHERE key=%s", (body.plan,)).fetchone():
        raise HTTPException(400, "Нет такого тарифа")
    c.execute("UPDATE workspaces SET plan=%s, plan_until=%s, plan_changed_at=now() WHERE id=%s", (body.plan, body.plan_until, ws_id))
    _audit(c, u, ws_id, "admin/plan", body.model_dump(mode="json"))
    c.commit()
    return {"ok": True}


@router.get("/api/admin/shops")
def admin_shops(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute(
        """SELECT a.id, a.name, a.title, a.marketplace, a.workspace_id, w.name workspace, a.is_active, a.created_at,
                  a.archived_at, a.archived_was_active, t.info->>'exp' token_exp,
                  (SELECT max(last_ok_at) FROM collector_state s WHERE s.account_id=a.id) last_ok,
                  (SELECT count(*) FROM collector_state s WHERE s.account_id=a.id AND s.last_error IS NOT NULL
                     AND s.last_error NOT ILIKE '%%лимит%%' AND coalesce(s.last_ok_at,'epoch') < now() - interval '6 hours') stale,
                  (SELECT string_agg(s.collector || ': ' || left(s.last_error, 80), ' | ') FROM collector_state s WHERE s.account_id=a.id
                     AND s.last_error IS NOT NULL AND coalesce(s.last_ok_at,'epoch') < now() - interval '6 hours') errors,
                  (SELECT count(*) FROM nomenclature n WHERE n.account_id=a.id) cards
           FROM accounts a LEFT JOIN workspaces w ON w.id=a.workspace_id LEFT JOIN account_tokens t ON t.account_id=a.id
           ORDER BY a.id""").fetchall())


class AdminShopArchiveIn(BaseModel):
    confirm_name: str


def _archive_shop(c, u, shop_id: int, body: AdminShopArchiveIn, *, restore=False):
    _sa(u)
    shop = c.execute("""SELECT id, name, title, workspace_id, is_active, archived_at, archived_was_active
                        FROM accounts WHERE id=%s FOR UPDATE""", (shop_id,)).fetchone()
    if not shop:
        raise HTTPException(404, "Магазин не найден")
    if body.confirm_name != (shop["title"] or shop["name"]):
        raise HTTPException(409, "Название не совпало. Обновите список и подтвердите выбранный магазин.")
    if restore == (shop["archived_at"] is None):
        return {"ok": True, "changed": False, "archived": not restore}
    if restore:
        c.execute("""UPDATE accounts SET is_active=coalesce(archived_was_active,false),
                     archived_at=NULL, archived_by=NULL, archived_was_active=NULL WHERE id=%s""", (shop_id,))
    else:
        c.execute("""UPDATE accounts SET archived_was_active=is_active, is_active=false,
                     archived_at=now(), archived_by=%s WHERE id=%s""", (u["id"], shop_id))
    _audit(c, u, shop["workspace_id"], "admin/shop_restore" if restore else "admin/shop_archive",
           {"shop": shop_id, "title": shop["title"] or shop["name"], "was_active": shop["is_active"]})
    c.commit()
    return {"ok": True, "changed": True, "archived": not restore}


@router.post("/api/admin/shops/{shop_id}/archive")
def admin_shop_archive(shop_id: int, body: AdminShopArchiveIn, u=Depends(current_user), c=Depends(conn)):
    return _archive_shop(c, u, shop_id, body)


@router.post("/api/admin/shops/{shop_id}/restore")
def admin_shop_restore(shop_id: int, body: AdminShopArchiveIn, u=Depends(current_user), c=Depends(conn)):
    return _archive_shop(c, u, shop_id, body, restore=True)


@router.get("/api/admin/payments")
def admin_payments(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute(
        """SELECT p.*, w.name workspace, x.email FROM payments p JOIN workspaces w ON w.id=p.workspace_id
           LEFT JOIN users x ON x.id=p.user_id ORDER BY p.id DESC LIMIT 300""").fetchall())


@router.post("/api/admin/payments/{pid}/paid")
def admin_mark_paid(pid: int, u=Depends(current_user), c=Depends(conn)):
    """Ручная оплата (счёт/перевод): отметить оплаченной → тариф продлевается, бонусы начисляются как при онлайн-оплате."""
    _sa(u)
    p = c.execute("SELECT status FROM payments WHERE id=%s", (pid,)).fetchone()
    if not p or p["status"] != "pending":
        raise HTTPException(400, "Платёж не в ожидании")
    billing.activate(c, pid)
    _audit(c, u, None, "admin/payment_paid", {"payment": pid})
    c.commit()
    return {"ok": True}


@router.post("/api/admin/payments/{pid}/cancel")
def admin_cancel(pid: int, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    c.execute("UPDATE payments SET status='canceled' WHERE id=%s AND status='pending'", (pid,))
    _audit(c, u, None, "admin/payment_cancel", {"payment": pid})
    c.commit()
    return {"ok": True}


@router.get("/api/admin/promo")
def admin_promo(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute("SELECT * FROM promo_codes ORDER BY created_at DESC").fetchall())


class PromoIn(BaseModel):
    code: str
    kind: str
    value: float
    plan: str | None = None
    max_uses: int | None = None
    valid_until: date | None = None
    note: str | None = None
    active: bool = True


@router.post("/api/admin/promo")
def admin_promo_save(body: PromoIn, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    code = body.code.strip().upper()
    if not code.replace("_", "").replace("-", "").isalnum() or not 3 <= len(code) <= 32:
        raise HTTPException(400, "Код — 3–32 символа: буквы, цифры, - и _")
    if body.kind not in ("percent", "fixed", "days") or body.value <= 0 or (body.kind == "percent" and body.value > 100):
        raise HTTPException(400, "Вид: percent (1–100 %), fixed (₽), days (дней)")
    c.execute("""INSERT INTO promo_codes(code,kind,value,plan,max_uses,valid_until,note,active,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (code) DO UPDATE SET kind=EXCLUDED.kind, value=EXCLUDED.value, plan=EXCLUDED.plan, max_uses=EXCLUDED.max_uses,
                 valid_until=EXCLUDED.valid_until, note=EXCLUDED.note, active=EXCLUDED.active""",
              (code, body.kind, body.value, body.plan or None, body.max_uses, body.valid_until, body.note, body.active, u["id"]))
    _audit(c, u, None, "admin/promo", {**body.model_dump(mode="json"), "code": code})
    c.commit()
    return {"ok": True}


@router.get("/api/admin/plans")
def admin_plans(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute("SELECT * FROM plans ORDER BY sort").fetchall())


class PlanEdit(BaseModel):
    title: str
    about: str | None = None
    price_month: float | None = None
    active: bool = True


@router.put("/api/admin/plans/{key}")
def admin_plan_set(key: str, body: PlanEdit, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    if body.price_month is not None and not 0 <= body.price_month <= 1_000_000:
        raise HTTPException(400, "Странная цена")
    c.execute("UPDATE plans SET title=%s, about=%s, price_month=%s, active=%s WHERE key=%s",
              (body.title.strip()[:60], (body.about or "").strip()[:500] or None, body.price_month, body.active, key))
    _audit(c, u, None, "admin/plan_edit", {"key": key, **body.model_dump()})
    c.commit()
    return {"ok": True}


from .bot_runtime import JOB_SETTINGS

SETTINGS = {**JOB_SETTINGS, "ref_percent": "Бонус пригласившему, % от оплат", "trial_days": "Пробный период новым кабинетам, дней",
            "enforce_billing": "Ограничивать доступ после окончания оплаты",
            "assistant_daily_limit": "Стометрик: сообщений в день на кабинет («Наша нейросеть»), по умолчанию"}


@router.get("/api/admin/settings")
def admin_settings(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    vals = {r["key"]: r["value"] for r in c.execute("SELECT key, value FROM app_settings WHERE key = ANY(%s)", (list(SETTINGS),))}
    from . import insights, market
    from .config import env
    return {"settings": [{"key": k, "title": t, "value": vals.get(k, False) if k in JOB_SETTINGS else vals.get(k)} for k, t in SETTINGS.items()],
            "integrations": {"wildbox": c.execute("SELECT count(*) n FROM workspace_secrets WHERE kind='wildbox'").fetchone()["n"], "claude": bool(env().get("ANTHROPIC_API_KEY")), "claude_model": insights.MODEL, "codex_private": False,
                             "yookassa": billing.yookassa_ready(), "assistant_bot": assistant_username(c), "rescue_bot": assistant_username(c, RESCUE_KEY),
                             "google": gdrive.status(c), "offsite": offsite.status(c)}}


class BotTokenIn(BaseModel):
    token: str


@router.put("/api/admin/assistant_bot")
def admin_assistant_bot(body: BotTokenIn, u=Depends(current_user), c=Depends(conn)):
    """Токен Telegram-бота «Стометрик»: проверяем в Telegram и храним только зашифрованным; наружу не отдаём."""
    _sa(u)
    try:
        name = set_assistant_token(c, body.token)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, None, "admin/assistant_bot", {"username": name})
    c.commit()
    return {"ok": True, "username": name}


@router.put("/api/admin/rescue_bot")
def admin_rescue_bot(body: BotTokenIn, u=Depends(current_user), c=Depends(conn)):
    """Токен бота-спасателя (перезапуск бота разработки из Telegram, stometric/rescue.py): так же — только шифротекст."""
    _sa(u)
    try:
        name = set_assistant_token(c, body.token, RESCUE_KEY)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, None, "admin/rescue_bot", {"username": name})
    c.commit()
    return {"ok": True, "username": name}


class OffsiteIn(BaseModel):
    endpoint: str
    region: str = ""
    bucket: str
    access_key: str
    secret_key: str


@router.put("/api/admin/offsite")
def admin_offsite(body: OffsiteIn, u=Depends(current_user), c=Depends(conn)):
    """Хранилище S3 для второй копии бэкапа базы: проверяем пробным файлом, ключи храним шифротекстом. Первый раз — создаём ключ
    шифрования копий и отдаём его один раз (владелец сохраняет у себя, без него копию не расшифровать)."""
    _sa(u)
    try:
        key = offsite.configure(c, body.endpoint, body.region, body.bucket, body.access_key, body.secret_key)
    except offsite.OffsiteError as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, None, "admin/offsite", {"bucket": body.bucket.strip()})
    c.commit()
    return {"ok": True, "passphrase": key}


@router.post("/api/admin/offsite/run")
def admin_offsite_run(u=Depends(current_user), c=Depends(conn)):
    """Отправить последний бэкап сейчас (фоном, ~5–10 минут)."""
    _sa(u)
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    subprocess.Popen([sys.executable, "-m", "stometric", "offsite-backup", "latest"], cwd=root, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _audit(c, u, None, "admin/offsite_run", {})
    c.commit()
    return {"ok": True}


class GoogleIn(BaseModel):
    client_id: str
    client_secret: str


@router.put("/api/admin/google")
def admin_google(body: GoogleIn, u=Depends(current_user), c=Depends(conn)):
    """OAuth-клиент Google (для выгрузки в Google Таблицы): храним шифротекстом, наружу не отдаём."""
    _sa(u)
    try:
        gdrive.set_client(c, body.client_id, body.client_secret)
    except gdrive.GError as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, None, "admin/google_client", {})
    c.commit()
    return {"ok": True}


@router.get("/api/admin/google/connect")
def admin_google_connect(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    try:
        return {"url": gdrive.auth_url(c, u["id"])}
    except gdrive.GError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/api/admin/google/callback")
def admin_google_callback(state: str = "", code: str = "", error: str = "", u=Depends(current_user), c=Depends(conn)):
    """Возврат из Google после «Разрешить»: тот же суперадмин, что начал подключение."""
    from fastapi.responses import HTMLResponse
    from html import escape
    _sa(u)
    try:
        if error:
            raise gdrive.GError("Доступ не выдан в Google" + (" (отменено)" if error == "access_denied" else f": {error}"))
        if gdrive.check_state(state) != u["id"]:
            raise gdrive.GError("Подключение начинал другой пользователь")
        email = gdrive.finish(c, code)
        _audit(c, u, None, "admin/google_connect", {"email": email})
        c.commit()
        msg = f"✓ Google Диск подключён: {email}. Выгрузки будут в папке «{gdrive.FOLDER}»."
    except gdrive.GError as e:
        c.rollback()
        msg = f"Не получилось: {e}"
    return HTMLResponse(f'<meta charset="utf-8"><meta name="viewport" content="width=device-width"><body style="font:16px sans-serif;padding:24px">'
                        f'<p>{escape(msg)}</p><p><a href="/">Вернуться в сервис</a></p></body>')


class SettingIn(BaseModel):
    value: float | bool


@router.put("/api/admin/settings/{key}")
def admin_setting_set(key: str, body: SettingIn, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    if key not in SETTINGS:
        raise HTTPException(400, "Нет такой настройки")
    if key in JOB_SETTINGS and type(body.value) is not bool:
        raise HTTPException(400, "Для этой настройки выберите включено или выключено")
    c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (key, json.dumps(body.value)))
    _audit(c, u, None, "admin/setting", {"key": key, "value": body.value})
    c.commit()
    return {"ok": True}


@router.get("/api/admin/legal")
def admin_legal(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    from . import legal
    return {"fields": [{"key": k, "title": t, "required": r} for k, t, r in legal.FIELDS], "value": legal.get(c)}


@router.put("/api/admin/legal")
def admin_legal_set(body: dict, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    from . import legal
    v = legal.save(c, body)
    _audit(c, u, None, "admin/legal", v)
    c.commit()
    return legal.get(c)


@router.get("/api/admin/audit")
def admin_audit(limit: int = 200, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    return jsonable_encoder(c.execute(
        """SELECT a.id, a.at, x.email, w.name workspace, a.action, a.details FROM audit_log a LEFT JOIN users x ON x.id=a.user_id
           LEFT JOIN workspaces w ON w.id=a.workspace_id ORDER BY a.id DESC LIMIT %s""", (max(1, min(limit, 1000)),)).fetchall())



@router.get("/api/admin/support")
def admin_support(u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    ws = c.execute("""SELECT w.id, w.name, (SELECT count(*) FROM accounts a WHERE a.workspace_id=w.id AND a.is_active) shops,
                             (SELECT coalesce(x.name, x.email) FROM memberships m JOIN users x ON x.id=m.user_id
                              WHERE m.workspace_id=w.id AND m.role='owner' ORDER BY m.user_id LIMIT 1) owner
                      FROM workspaces w WHERE NOT EXISTS (SELECT 1 FROM memberships m WHERE m.workspace_id=w.id AND m.user_id=%s)
                      ORDER BY w.id""", (u["id"],)).fetchall()
    log = c.execute("""SELECT s.id, s.workspace_id, w.name ws, s.reason, s.granted_at, s.until, s.revoked_at,
                              (s.revoked_at IS NULL AND s.until > now()) active
                       FROM support_access s JOIN workspaces w ON w.id=s.workspace_id WHERE s.user_id=%s ORDER BY s.id DESC LIMIT 50""",
                    (u["id"],)).fetchall()
    return jsonable_encoder({"workspaces": ws, "log": log})


class SupportIn(BaseModel):
    workspace_id: int
    reason: str
    hours: float = 2


@router.post("/api/admin/support")
def admin_support_open(body: SupportIn, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(400, "Напишите, кто из клиента и когда дал согласие на доступ (не короче 10 знаков)")
    if not c.execute("SELECT 1 FROM workspaces WHERE id=%s", (body.workspace_id,)).fetchone():
        raise HTTPException(404, "Нет такого кабинета")
    h = max(0.25, min(24.0, float(body.hours or 2)))
    r = c.execute("""INSERT INTO support_access(user_id,workspace_id,reason,until) VALUES (%s,%s,%s,now() + make_interval(mins => %s))
                     RETURNING id, until""", (u["id"], body.workspace_id, reason[:1000], int(h * 60))).fetchone()
    
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'support/open',%s)",
              (u["id"], body.workspace_id, json.dumps({"reason": reason[:500], "hours": h, "until": r["until"].isoformat()}, ensure_ascii=False)))
    c.commit()
    return jsonable_encoder({"id": r["id"], "until": r["until"]})


@router.delete("/api/admin/support/{sid}")
def admin_support_close(sid: int, u=Depends(current_user), c=Depends(conn)):
    _sa(u)
    r = c.execute("UPDATE support_access SET revoked_at=now() WHERE id=%s AND user_id=%s AND revoked_at IS NULL RETURNING workspace_id",
                  (sid, u["id"])).fetchone()
    if r:
        c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'support/close','{}')", (u["id"], r["workspace_id"]))
    c.commit()
    return {"ok": True}

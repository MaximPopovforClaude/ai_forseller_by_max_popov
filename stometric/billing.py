"""Тарифы, оплата, промокоды и реферальная программа (дорожная карта п.6 и п.8).

Цена тарифа — plans.price_month (₽/мес), задаёт суперадмин в админке; NULL — тариф нельзя оплатить (цена не задана).
Оплата — ЮKassa (YOOKASSA_SHOP_ID + YOOKASSA_SECRET в .env): создаём платёж, человек платит на странице ЮKassa, подтверждение —
уведомлением ЮKassa (мы перепроверяем статус запросом к API, телу уведомления не верим). Без ключей — заявка «ручная оплата»,
суперадмин отмечает оплату в админке. Промокод: percent — скидка %, fixed — скидка ₽, days — N дней тарифа бесплатно.
Рефералка: с каждой оплаты приглашённого (владельца кабинета) пригласившему начисляются бонусы ref_percent % — бонусами
можно оплатить свой тариф (1 бонус = 1 ₽).
"""

import base64
import json
import secrets
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta

from . import config
from .config import today_msk

from .config import site_url
SITE = site_url()
MONTHS = (1, 3, 6, 12)


def purchase_unavailable(plan_key: str) -> str | None:
    """Availability only; leave stored prices, balances and existing plans intact."""
    from .ai_routing import FUTURE_ROUTES
    if plan_key in FUTURE_ROUTES:
        return "Этот тариф с нейросетью пока не активирован. Подключение через API появится позже."
    if plan_key == "owner":
        return "VIP-тариф подключает владелец сервиса; покупать его не нужно."
    return None


def setting(c, key: str, default=None):
    r = c.execute("SELECT value FROM app_settings WHERE key=%s", (key,)).fetchone()
    return r["value"] if r else default


def yookassa_ready() -> bool:
    e = config.env()
    return bool(e.get("YOOKASSA_SHOP_ID") and e.get("YOOKASSA_SECRET"))


def promo_check(c, code: str | None, plan: str) -> tuple[dict | None, str | None]:
    if not code:
        return None, None
    p = c.execute("SELECT * FROM promo_codes WHERE code=%s", (code.strip().upper(),)).fetchone()
    if not p or not p["active"]:
        return None, "Промокод не найден"
    if p["valid_until"] and p["valid_until"] < today_msk():
        return None, "Срок промокода истёк"
    if p["max_uses"] is not None and p["used"] >= p["max_uses"]:
        return None, "Промокод уже использован"
    if p["plan"] and p["plan"] != plan:
        return None, "Промокод для другого тарифа"
    return p, None


def quote(c, user: dict, plan_key: str, months: int, promo: str | None, use_bonus: bool) -> dict:
    unavailable = purchase_unavailable(plan_key)
    if unavailable:
        return {"error": unavailable}
    plan = c.execute("SELECT * FROM plans WHERE key=%s AND active", (plan_key,)).fetchone()
    if not plan:
        return {"error": "Нет такого тарифа"}
    p, perr = promo_check(c, promo, plan_key)
    if perr:
        return {"error": perr}
    if p and p["kind"] == "days":
        return {"plan": plan_key, "title": plan["title"], "months": 0, "days": int(p["value"]), "base": 0, "discount": 0, "bonus": 0,
                "amount": 0, "promo": p["code"]}
    if plan["price_month"] is None:
        return {"error": "Цена тарифа ещё не задана — напишите нам, подключим вручную"}
    if months not in MONTHS:
        return {"error": "Срок — 1, 3, 6 или 12 месяцев"}
    base = float(plan["price_month"]) * months
    disc = 0.0
    if p:
        disc = base * float(p["value"]) / 100 if p["kind"] == "percent" else min(base, float(p["value"]))
    left = round(base - disc, 2)
    bonus = round(min(float(user.get("bonus_balance") or 0), left), 2) if use_bonus else 0.0
    return {"plan": plan_key, "title": plan["title"], "months": months, "days": 0, "base": round(base, 2), "discount": round(disc, 2),
            "bonus": bonus, "amount": round(left - bonus, 2), "promo": p["code"] if p else None}


def _yk(method: str, path: str, body: dict | None = None, idem: str | None = None) -> dict:
    e = config.env()
    auth = base64.b64encode(f"{e['YOOKASSA_SHOP_ID']}:{e['YOOKASSA_SECRET']}".encode()).decode()
    h = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
    if idem:
        h["Idempotence-Key"] = idem
    req = urllib.request.Request("https://api.yookassa.ru/v3" + path, data=json.dumps(body).encode() if body else None, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def checkout(c, user: dict, ws_id: int, plan_key: str, months: int, promo: str | None, use_bonus: bool) -> dict:
    q = quote(c, user, plan_key, months, promo, use_bonus)
    if q.get("error"):
        return q
    provider = "free" if q["amount"] <= 0 else ("yookassa" if yookassa_ready() else "manual")
    pay = c.execute("""INSERT INTO payments(workspace_id,user_id,plan,months,days,base_amount,discount,bonus_used,amount,promo_code,provider)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (ws_id, user["id"], plan_key, q["months"], q["days"], q["base"], q["discount"], q["bonus"], q["amount"], q["promo"],
                     provider)).fetchone()
    c.commit()
    if provider == "free":
        activate(c, pay["id"])
        return {"ok": True, "status": "paid", "payment_id": pay["id"]}
    if provider == "yookassa":
        try:
            res = _yk("POST", "/payments", {
                "amount": {"value": f"{q['amount']:.2f}", "currency": "RUB"}, "capture": True,
                "confirmation": {"type": "redirect", "return_url": f"{SITE}/?paid={pay['id']}"},
                "description": f"Seller Analytics: тариф «{q['title']}», {q['months']} мес. (кабинет {ws_id})",
                "metadata": {"payment_id": pay["id"]}}, idem=str(uuid.uuid4()))
        except (urllib.error.URLError, KeyError) as e:
            c.execute("UPDATE payments SET status='canceled' WHERE id=%s", (pay["id"],))
            c.commit()
            return {"error": f"Платёжная система не ответила: {str(e)[:120]}"}
        url = (res.get("confirmation") or {}).get("confirmation_url")
        c.execute("UPDATE payments SET provider_id=%s, pay_url=%s WHERE id=%s", (res.get("id"), url, pay["id"]))
        c.commit()
        return {"ok": True, "status": "pending", "pay_url": url, "payment_id": pay["id"]}
    return {"ok": True, "status": "pending", "payment_id": pay["id"], "manual": True,
            "message": "Заявка на оплату принята. Онлайн-оплата картой скоро; пока мы пришлём счёт и подключим тариф вручную."}


def yookassa_confirm(c, provider_id: str) -> bool:
    """Уведомление ЮKassa → перепроверяем статус платежа у ЮKassa и только тогда активируем."""
    pay = c.execute("SELECT * FROM payments WHERE provider='yookassa' AND provider_id=%s", (provider_id,)).fetchone()
    if not pay or pay["status"] != "pending" or not yookassa_ready():
        return False
    res = _yk("GET", f"/payments/{provider_id}")
    if res.get("status") == "succeeded" and float(res["amount"]["value"]) >= float(pay["amount"]) - 0.01:
        activate(c, pay["id"])
        return True
    if res.get("status") == "canceled":
        c.execute("UPDATE payments SET status='canceled' WHERE id=%s", (pay["id"],))
        c.commit()
    return False


def activate(c, payment_id: int) -> None:
    """Оплачено: продлить тариф кабинета, списать промокод и бонусы, начислить бонусы пригласившему."""
    pay = c.execute("SELECT * FROM payments WHERE id=%s FOR UPDATE", (payment_id,)).fetchone()
    if not pay or pay["status"] == "paid":
        return
    ws = c.execute("SELECT * FROM workspaces WHERE id=%s", (pay["workspace_id"],)).fetchone()
    start = max(today_msk(), ws["plan_until"] + timedelta(days=1) if ws["plan_until"] and ws["plan"] == pay["plan"] else today_msk())
    until = _add_months(start, pay["months"]) + timedelta(days=pay["days"]) - timedelta(days=1)
    c.execute("UPDATE workspaces SET plan=%s, plan_until=%s, plan_changed_at=now() WHERE id=%s", (pay["plan"], until, ws["id"]))
    c.execute("UPDATE payments SET status='paid', paid_at=now() WHERE id=%s", (payment_id,))
    if pay["promo_code"]:
        c.execute("UPDATE promo_codes SET used=used+1 WHERE code=%s", (pay["promo_code"],))
    if pay["bonus_used"]:
        c.execute("UPDATE users SET bonus_balance=greatest(bonus_balance-%s, 0) WHERE id=%s", (pay["bonus_used"], pay["user_id"]))
    payer = c.execute("SELECT * FROM users WHERE id=%s", (pay["user_id"],)).fetchone()
    pct = float(setting(c, "ref_percent", 10) or 0)
    if payer and payer["referred_by"] and pay["amount"] and pct > 0:
        amount = round(float(pay["amount"]) * pct / 100, 2)
        r = c.execute("""INSERT INTO ref_rewards(referrer_id,referee_id,payment_id,amount) VALUES (%s,%s,%s,%s)
                         ON CONFLICT (payment_id) DO NOTHING RETURNING id""", (payer["referred_by"], payer["id"], payment_id, amount)).fetchone()
        if r:
            c.execute("UPDATE users SET bonus_balance=bonus_balance+%s WHERE id=%s", (amount, payer["referred_by"]))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'billing/paid',%s)",
              (pay["user_id"], ws["id"], json.dumps({"payment": payment_id, "plan": pay["plan"], "until": str(until), "amount": float(pay["amount"])})))
    c.commit()


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def ref_code(c, user_id: int) -> str:
    r = c.execute("SELECT ref_code FROM users WHERE id=%s", (user_id,)).fetchone()
    if r and r["ref_code"]:
        return r["ref_code"]
    for _ in range(5):
        code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:7].upper()
        if not c.execute("SELECT 1 FROM users WHERE ref_code=%s", (code,)).fetchone():
            c.execute("UPDATE users SET ref_code=%s WHERE id=%s", (code, user_id))
            c.commit()
            return code
    raise RuntimeError("не удалось выдать реферальный код")


def referrer_by_code(c, code: str | None) -> int | None:
    if not code:
        return None
    r = c.execute("SELECT id FROM users WHERE ref_code=%s AND is_active", (code.strip().upper(),)).fetchone()
    return r and r["id"]

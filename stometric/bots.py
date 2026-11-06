"""Telegram-боты Seller Analytics (один процесс, systemd ai-stometric-bots.service).

- Бот регистрации (TG_BOT_REGISTER_TOKEN): /start → e-mail → аккаунт + личный кабинет + Telegram привязан → одноразовая ссылка
  на сайт «задать пароль»; уже зарегистрированному — ссылка для входа. Чужой e-mail к Telegram не привязываем (только через сайт).
- Бот уведомлений (TG_BOT_NOTIFY_TOKEN): /start <код> с сайта (или /start, если Telegram уже привязан) → утренняя сводка
  по магазинам в заданное время (МСК) + предупреждения (ключ API истекает, сбор данных сломан). Без повторов: notify_log.
- Бот «Стометрик» (токен — в админке, зашифрован в app_settings): помощник как на сайте (тот же чат и лимиты, таблицы — xlsx)
  + те же уведомления; кто подключил его (/start), получает уведомления через него (notify_settings.bot='assistant').

Запуск: .venv/bin/python -m stometric.bots
"""

import hashlib
import html
import json
import re
import secrets
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

import httpx

from . import auth, config, db, legal
from .config import today_msk

from .config import site_url
SITE = site_url()
MSK = timezone(timedelta(hours=3))
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Bot:
    def __init__(self, token_env: str, token: str | None = None):
        self.token = token or config.env().get(token_env)
        self.http = httpx.Client(timeout=40)
        self.username = None
        if self.token:
            try:
                self.username = (self.api("getMe") or {}).get("username")
            except Exception as e:  
                print(f"{token_env}: {e}", flush=True)
                self.token = None

    def api(self, method: str, **params):
        r = self.http.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params)
        d = r.json()
        if not d.get("ok"):
            raise RuntimeError(f"{method}: {d.get('description')}")
        return d.get("result")

    def send(self, chat_id: int, text: str, **kw) -> bool:
        try:
            self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True, **kw)
            return True
        except Exception as e:  
            print("send failed", chat_id, str(e)[:200], flush=True)
            return False

    def send_id(self, chat_id: int, text: str, **kw) -> int | None:
        try:
            return self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True, **kw)["message_id"]
        except Exception as e:  
            print("send failed", chat_id, str(e)[:200], flush=True)
            return None

    def edit(self, chat_id: int, msg_id: int, text: str, **kw):
        try:
            self.api("editMessageText", chat_id=chat_id, message_id=msg_id, text=text, parse_mode="HTML", disable_web_page_preview=True, **kw)
        except Exception:  
            pass

    def doc(self, chat_id: int, name: str, raw: bytes, caption: str = "") -> bool:
        try:
            r = self.http.post(f"https://api.telegram.org/bot{self.token}/sendDocument", data={"chat_id": chat_id, "caption": caption[:1000]},
                               files={"document": (name, raw)})
            return bool(r.json().get("ok"))
        except Exception as e:  
            print("doc failed", chat_id, str(e)[:200], flush=True)
            return False

    def download(self, file_id: str) -> bytes:
        f = self.api("getFile", file_id=file_id)
        return self.http.get(f"https://api.telegram.org/file/bot{self.token}/{f['file_path']}").content

    def poll(self, handle, media: bool = False, on_cb=None):
        """media — пропускать сообщения с фото/файлами (не только текст); on_cb — обработчик нажатий инлайн-кнопок."""
        offset = 0
        while True:
            try:
                ups = self.api("getUpdates", offset=offset, timeout=25, allowed_updates=["message"] + (["callback_query"] if on_cb else []))
                for u in ups:
                    offset = u["update_id"] + 1
                    if u.get("callback_query") and on_cb:
                        try:
                            on_cb(self, u["callback_query"])
                        except Exception:  
                            traceback.print_exc()
                        continue
                    m = u.get("message")
                    if m and m.get("chat", {}).get("type") == "private" and (m.get("text") or media and (m.get("photo") or m.get("document"))):
                        try:
                            handle(self, m)
                        except Exception:  
                            traceback.print_exc()
                            self.send(m["chat"]["id"], "Что-то пошло не так 🙈 Попробуйте ещё раз чуть позже.")
            except Exception as e:  
                print("poll error:", str(e)[:200], flush=True)
                time.sleep(5)


def new_token(c, user_id: int, purpose: str, hours: int) -> str:
    tok = secrets.token_urlsafe(24)
    c.execute("INSERT INTO login_tokens(token_hash,user_id,purpose,expires_at) VALUES (%s,%s,%s, now() + make_interval(hours => %s))",
              (hashlib.sha256(tok.encode()).hexdigest(), user_id, purpose, hours))
    c.commit()
    return f"{SITE}/login/{tok}"



ACCEPT = "✅ Принимаю"


def _terms_prompt(bot: Bot, tg: int):
    bot.send(tg, "Перед регистрацией ознакомьтесь, пожалуйста:\n"
                 f"• <a href=\"{SITE}/legal/offer\">Публичная оферта</a>\n"
                 f"• <a href=\"{SITE}/legal/privacy\">Согласие на обработку персональных данных</a>\n\n"
                 f"Если согласны — нажмите «{ACCEPT}».",
             reply_markup={"keyboard": [[{"text": ACCEPT}]], "resize_keyboard": True, "one_time_keyboard": True})


def handle_register(bot: Bot, m: dict):
    tg = m["from"]["id"]
    text = m["text"].strip()
    name = " ".join(x for x in (m["from"].get("first_name"), m["from"].get("last_name")) if x) or None
    with db.connect() as c:
        u = c.execute("SELECT * FROM users WHERE telegram_id=%s", (tg,)).fetchone()
        if u:
            if not u["is_active"]:
                bot.send(tg, "Доступ к аккаунту отключён. Обратитесь к владельцу сервиса.")
                return
            link = new_token(c, u["id"], "login" if u["password_hash"] else "set_password", 1 if u["password_hash"] else 24)
            what = "войти" if u["password_hash"] else "задать пароль и войти"
            bot.send(tg, f"Вы уже зарегистрированы: <b>{html.escape(u['email'])}</b>.\n\nСсылка, чтобы {what} в Seller Analytics "
                         f"(одноразовая, {'1 час' if u['password_hash'] else '24 часа'}):\n{link}")
            return
        if text.startswith("/start") or text.startswith("/"):
            ref = text[len("/start ref_"):].strip() if text.startswith("/start ref_") else None   
            from .billing import referrer_by_code
            data = json.dumps({"ref": referrer_by_code(c, ref)} if ref else {})
            c.execute("""INSERT INTO reg_dialog(telegram_id,step,data) VALUES (%s,'email',%s) ON CONFLICT (telegram_id)
                         DO UPDATE SET step='email', data=CASE WHEN EXCLUDED.data <> '{}'::jsonb THEN EXCLUDED.data ELSE reg_dialog.data END,
                         updated_at=now()""", (tg, data))
            c.commit()
            if legal.get(c)["ready"]:
                c.execute("UPDATE reg_dialog SET step='terms' WHERE telegram_id=%s", (tg,))
                c.commit()
                bot.send(tg, "👋 Это <b>Seller Analytics</b> — аналитика магазина Wildberries и Ozon: все таблицы и графики по API.")
                _terms_prompt(bot, tg)
                return
            bot.send(tg, "👋 Это <b>Seller Analytics</b> — аналитика магазина Wildberries: все таблицы и графики по API WB.\n\n"
                         "Для регистрации напишите ваш <b>e-mail</b> — он будет логином на сайте.")
            return
        lg = legal.get(c)
        dlg = c.execute("SELECT step, data FROM reg_dialog WHERE telegram_id=%s", (tg,)).fetchone()
        terms_ok = bool(dlg and (dlg["data"] or {}).get("terms") == legal.VERSION)
        if lg["ready"] and not terms_ok:
            if text == ACCEPT or text.lower().strip("✅ ").startswith("принимаю"):
                c.execute("""INSERT INTO reg_dialog(telegram_id,step,data) VALUES (%s,'email',%s) ON CONFLICT (telegram_id) DO UPDATE
                             SET step='email', data=reg_dialog.data || EXCLUDED.data, updated_at=now()""",
                          (tg, json.dumps({"terms": legal.VERSION, "terms_at": datetime.now(timezone.utc).isoformat()})))
                c.commit()
                bot.send(tg, "Спасибо! Теперь напишите ваш <b>e-mail</b> — он будет логином на сайте.", reply_markup={"remove_keyboard": True})
            else:
                _terms_prompt(bot, tg)
            return
        email = text.lower()
        if not EMAIL.match(email):
            bot.send(tg, "Похоже, это не e-mail. Напишите адрес вида <i>name@mail.ru</i>.")
            return
        if c.execute("SELECT 1 FROM users WHERE email=%s", (email,)).fetchone():
            bot.send(tg, "Этот e-mail уже зарегистрирован. Войдите на сайте " + SITE + " — а Telegram можно подключить в «Настройках аккаунта».")
            return
        ref_by = (dlg["data"] or {}).get("ref") if dlg else None
        uid = c.execute("""INSERT INTO users(email,name,telegram_id,referred_by,terms_version,terms_accepted_at)
                           VALUES (%s,%s,%s,%s,%s,CASE WHEN %s::text IS NOT NULL THEN now() END) RETURNING id""",
                        (email, name, tg, ref_by, legal.VERSION if terms_ok else None, legal.VERSION if terms_ok else None)).fetchone()["id"]
        from .billing import setting
        trial = int(float(setting(c, "trial_days", 0) or 0))
        ws = c.execute("INSERT INTO workspaces(name, plan_until) VALUES (%s, CASE WHEN %s > 0 THEN current_date + %s END) RETURNING id",
                       (name or email.split("@")[0], trial, trial)).fetchone()["id"]
        c.execute("INSERT INTO memberships(user_id,workspace_id,role) VALUES (%s,%s,'owner')", (uid, ws))
        c.execute("INSERT INTO notify_settings(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
        c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'register/telegram',%s)",
                  (uid, ws, json.dumps({"email": email, "terms": legal.VERSION if terms_ok else None,
                                        "terms_at": (dlg["data"] or {}).get("terms_at") if dlg else None}, ensure_ascii=False)))
        c.execute("DELETE FROM reg_dialog WHERE telegram_id=%s", (tg,))
        c.commit()
        link = new_token(c, uid, "set_password", 24)
        bot.send(tg, f"✅ Готово! Аккаунт <b>{html.escape(email)}</b> создан.\n\n1) Задайте пароль и войдите (ссылка одноразовая, 24 часа):\n{link}\n\n"
                     "2) В «Настройках аккаунта» → «+ Добавить магазин» вставьте ключ API WB — данные начнут загружаться сами."
                     + (f"\n\n3) Помощник Стометрик, утренняя сводка и предупреждения: откройте @{bn} и нажмите «Start»."
                        if (bn := assistant_username(c) or notifier().username) else ""))
        notify_admins(c, f"🆕 Регистрация в Seller Analytics: {html.escape(email)} ({html.escape(name or '—')})"
                         + (" — по реферальной ссылке" if ref_by else ""))



NOTIFY: Bot | None = None



AS_KEY = "tg_assistant_bot"


RESCUE_KEY = "tg_rescue_bot"   


def assistant_token(c, key: str = AS_KEY) -> str | None:
    from . import vault
    r = c.execute("SELECT value FROM app_settings WHERE key=%s", (key,)).fetchone()
    if not r or not (r["value"] or {}).get("enc"):
        return None
    try:
        return vault.decrypt(r["value"]["enc"].encode())
    except Exception:  
        return None


def set_assistant_token(c, token: str, key: str = AS_KEY) -> str:
    """Проверить токен (getMe) и сохранить зашифрованным. Возвращает @имя бота."""
    from . import vault
    token = token.strip()
    if not re.match(r"^\d+:[\w-]{20,}$", token):
        raise ValueError("Не похоже на токен бота (вида 123456:ABC…)")
    try:
        me = httpx.post(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    except Exception:  
        raise ValueError("Telegram не ответил — попробуйте ещё раз") from None
    if not me.get("ok"):
        raise ValueError("Telegram не принял токен — проверьте в @BotFather")
    name = me["result"]["username"]
    if name in {assistant_username(c, k) for k in (AS_KEY, RESCUE_KEY) if k != key}:
        raise ValueError("Это токен другого нашего бота — нужен отдельный бот из @BotFather")
    c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
              (key, json.dumps({"enc": vault.encrypt(token).decode(), "username": name})))
    return name


def assistant_username(c, key: str = AS_KEY) -> str | None:
    r = c.execute("SELECT value FROM app_settings WHERE key=%s", (key,)).fetchone()
    return r and (r["value"] or {}).get("username")


def notifier() -> Bot:
    """Бот уведомлений (в процессе ботов — общий; из веба — создаётся по запросу)."""
    global NOTIFY
    if NOTIFY is None:
        NOTIFY = Bot("TG_BOT_NOTIFY_TOKEN")
    return NOTIFY


ASSIST: Bot | None = None   


def bot_of(c, uid: int) -> Bot:
    """Через какого бота писать человеку: «Стометрик», если он подключил его, иначе бот уведомлений."""
    r = c.execute("SELECT bot FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
    if r and r["bot"] == "assistant":
        global ASSIST
        if ASSIST is None:      
            tok = assistant_token(c)
            if tok:
                ASSIST = Bot("", tok)
        if ASSIST and ASSIST.token:
            return ASSIST
    return notifier()


def muted(c, uid: int) -> set[int]:
    """Магазины, по которым пользователь выключил уведомления (сводка, события, предупреждения)."""
    r = c.execute("SELECT muted_shops FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
    return set((r or {}).get("muted_shops") or [])


def notify_admins(c, text: str):
    for r in c.execute("SELECT s.user_id, s.chat_id FROM users u JOIN notify_settings s ON s.user_id=u.id WHERE u.is_superadmin AND s.chat_id IS NOT NULL").fetchall():
        notify(c, r["user_id"], r["chat_id"], text)



def in_window(s: dict, now: datetime | None = None) -> bool:
    t = (now or datetime.now(MSK)).time()
    a, b = s.get("send_from"), s.get("send_to")
    if not a or not b or a == b:
        return True
    return a <= t < b if a < b else (t >= a or t < b)


def notify(c, uid: int, chat_id: int, text: str) -> bool:
    """Уведомление пользователю: в его окне — сразу, вне окна — в очередь (уйдёт, когда окно откроется)."""
    if not c.execute("SELECT 1 FROM users WHERE id=%s AND is_active", (uid,)).fetchone():
        return False
    s = c.execute("SELECT send_from, send_to FROM notify_settings WHERE user_id=%s", (uid,)).fetchone() or {}
    if in_window(s):
        b = bot_of(c, uid)
        return bool(b.token) and b.send(chat_id, text)
    c.execute("INSERT INTO notify_queue(user_id,chat_id,text) VALUES (%s,%s,%s)", (uid, chat_id, text))
    c.commit()
    return True


def flush_queue(c) -> int:
    """Накопленное за ночь — тем, у кого окно открылось: по порядку, склеивая в сообщения до ~3500 знаков."""
    n = 0
    for s in c.execute("""SELECT DISTINCT ON (q.user_id) q.user_id, ns.send_from, ns.send_to FROM notify_queue q
                          JOIN notify_settings ns ON ns.user_id=q.user_id
                          JOIN users u ON u.id=q.user_id AND u.is_active""").fetchall():
        if not in_window(s):
            continue
        rows = c.execute("SELECT id, chat_id, text FROM notify_queue WHERE user_id=%s ORDER BY id", (s["user_id"],)).fetchall()
        b = bot_of(c, s["user_id"])
        pack, ids, first = [], [], True
        for i, r in enumerate(rows):
            pack.append(r["text"]); ids.append(r["id"])
            last = i == len(rows) - 1
            if last or sum(len(x) for x in pack) + len(rows[i + 1]["text"]) > 3500 or rows[i + 1]["chat_id"] != r["chat_id"]:
                head = "🌙 <b>Пока вы отдыхали:</b>\n\n" if first else ""
                first = False
                if not c.execute("SELECT 1 FROM users WHERE id=%s AND is_active", (s["user_id"],)).fetchone():
                    break
                if b.token:
                    b.send(r["chat_id"], head + "\n\n— — —\n\n".join(pack))
                c.execute("DELETE FROM notify_queue WHERE id = ANY(%s)", (ids,))
                c.commit()
                n += 1
                pack, ids = [], []
    return n


def handle_notify(bot: Bot, m: dict):
    tg = m["from"]["id"]
    text = m["text"].strip()
    with db.connect() as c:
        uid = _link_user(bot, c, tg, text)
        if not uid:
            return
        if text in ("/stop", "стоп"):
            c.execute("UPDATE notify_settings SET chat_id=NULL, updated_at=now() WHERE user_id=%s", (uid,))
            c.commit()
            bot.send(tg, "Уведомления выключены. Включить снова — /start.")
            return
        c.execute("""INSERT INTO notify_settings(user_id,chat_id,bot) VALUES (%s,%s,'notify')
                     ON CONFLICT (user_id) DO UPDATE SET chat_id=EXCLUDED.chat_id, bot='notify', updated_at=now()""", (uid, tg))
        c.commit()
        s = c.execute("SELECT * FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
        if text.startswith("/summary") or text == "сводка":
            send_daily(c, uid, tg, force=True)
            return
        bot.send(tg, "🔔 Уведомления Seller Analytics подключены.\n\n"
                     f"• Утренняя сводка: {'в ' + s['daily_time'].strftime('%H:%M') + ' МСК' if s['daily'] else 'выключена'}\n"
                     f"• Предупреждения: {'включены' if s['alerts'] else 'выключены'}\n\n"
                     "Команды: /summary — сводка сейчас, /stop — выключить. Настройки — на сайте в «Настройках аккаунта».")


def _fmt(v, fmt):
    if v is None:
        return "—"
    if fmt == "pct":
        return f"{v * 100:.1f} %".replace(".", ",")
    return f"{v:,.0f}".replace(",", " ")


OZ_DAILY = [("o_sum", "Заказы, ₽", "money"), ("o_qty", "Заказы, шт", "int"), ("ads", "Реклама, ₽", "money"), ("drr", "ДРР от заказов", "pct"),
            ("o_profit", "Прибыль по заказам (оценка)", "money"), ("b_qty", "Выкупы, шт", "int"), ("b_sum", "Выкупы, ₽", "money"),
            ("f_profit", "Оперативная прибыль", "money")]


def _ozon_lines(c, shop: int, y, skus=None) -> str:
    from .sheets import ozdash
    res = ozdash.compute(c, shop, y - timedelta(days=1), y, skus)
    rows = {r["key"]: r for r in res["rows"]}
    out = []
    for k, lab, fmt in OZ_DAILY:
        d, f2 = rows[k].get("d0"), rows[k].get("d1")
        arrow = ""
        if fmt != "pct" and f2 and d is not None:
            ch = (d - f2) / abs(f2)
            arrow = f"  {'▲' if ch > 0 else '▼'} {abs(ch) * 100:.0f} %" if abs(ch) >= 0.005 else ""
        out.append(f"{lab}: <b>{_fmt(d, fmt)}</b>{arrow}")
    return "🟦 Ozon\n" + "\n".join(out)


def send_daily(c, uid: int, chat_id: int, force=False, only: int | None = None) -> bool:
    """Сводка за вчера — по сообщению на каждый магазин пользователя; цифры главной страницы магазина (формулы 5#Дашборд)."""
    from .tabs.basic import HOME_ROWS, home
    u = c.execute("SELECT * FROM users WHERE id=%s AND is_active", (uid,)).fetchone()
    if not u:
        return False
    shops = auth.shops_for(c, u)
    if not only:                                
        off = muted(c, uid)
        if shops and off and all(s["id"] in off for s in shops):
            return True
        shops = [s for s in shops if s["id"] not in off]
    y = today_msk() - timedelta(days=1)
    bot = bot_of(c, uid)
    ns = c.execute("SELECT ai, daily_mine FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
    want_ai = bool(ns and ns["ai"])
    from .staff import mine
    own = mine(c, uid) if ns and ns["daily_mine"] else {}     
    own_staff = {r["account_id"]: r["staff_id"] for r in c.execute(
        "SELECT DISTINCT a.account_id, a.staff_id FROM staff s JOIN staff_articles a ON a.staff_id=s.id WHERE s.user_id=%s", (uid,))} if own else {}
    if own:
        shops = [s for s in shops if s["id"] in own]
    if not shops:
        return bot.send(chat_id, "Магазинов пока нет — добавьте ключ API WB на сайте: «Настройки аккаунта» → «+ Добавить магазин».")
    shops = sorted(shops, key=lambda s: s["id"] != u.get("default_shop_id"))   
    if only:                                    
        shops = [s for s in shops if s["id"] == only] or shops
    ok = True
    for s in shops:   
        name = html.escape(s["title"] or s["name"])
        nms = own.get(s["id"])
        parts = [f"<b>📊 {name} — итоги {y:%d.%m.%Y}</b>" + (f"\n👤 только мои артикулы: {len(nms)}" if nms else "")]
        if s.get("marketplace") == "ozon":
            try:
                parts.append(_ozon_lines(c, s["id"], y, nms))
            except Exception as e:  
                c.rollback()
                parts.append(f"не удалось посчитать: {html.escape(str(e)[:120])}")
            try:                       
                from . import reviews
                neg = reviews.summary_lines(c, s["id"], y, nms)
                if neg:
                    parts.append("\n" + html.escape(neg))
            except Exception:  
                c.rollback()
                traceback.print_exc()
            parts.append(f"\n▲▼ — к позавчера. Подробно: {SITE}")
            ok = bot.send(chat_id, "\n".join(parts)) and ok
            if want_ai:
                _send_ai(c, bot, chat_id, s, y)
            continue
        if s.get("marketplace") == "ym":           
            try:
                from .tabs.ym import HOME_ROWS as YM_ROWS
                rows = {r["label"]: r for r in home(c, s["id"], {"nm_ids": nms})["rows"]}
                lines = []
                for lab, _, fmt in YM_ROWS:
                    d, f2 = rows[lab]["D"], rows[lab]["F"]
                    arrow = ""
                    if fmt != "pct" and f2 and d is not None:
                        ch = (d - f2) / abs(f2)
                        arrow = f"  {'▲' if ch > 0 else '▼'} {abs(ch) * 100:.0f} %" if abs(ch) >= 0.005 else ""
                    lines.append(f"{html.escape(lab)}: <b>{_fmt(d, fmt)}</b>{arrow}")
                parts.append("🟨 Яндекс Маркет\n" + "\n".join(lines))
            except Exception as e:  
                c.rollback()
                parts.append(f"не удалось посчитать: {html.escape(str(e)[:120])}")
            parts.append(f"\n▲▼ — к позавчера. Подробно: {SITE}")
            ok = bot.send(chat_id, "\n".join(parts)) and ok
            continue
        try:
            res = home(c, s["id"], {"nm_ids": nms})
            rows = {r["label"]: r for r in res["rows"]}
            lines = []
            for lab, _, fmt in HOME_ROWS:
                r = rows.get(lab)
                if not r:
                    continue
                d, f2 = r["D"], r["F"]
                arrow = ""
                if fmt != "pct" and f2 and d is not None:
                    ch = (d - f2) / abs(f2)
                    arrow = f"  {'▲' if ch > 0 else '▼'} {abs(ch) * 100:.0f} %" if abs(ch) >= 0.005 else ""
                lines.append(f"{html.escape(lab.split(' (')[0])}: <b>{_fmt(d, fmt)}</b>{arrow}")
            parts.append("\n".join(lines))
            try:
                from . import insights
                ins = insights.get(c, s["id"], y, staff_id=own_staff.get(s["id"]) if nms else None, actor_id=uid)   
                head = "🤖 Разбор нейросети" if ins.get("ai_text") else "🔎 Что важно"
                parts.append(f"\n<b>{head}</b>\n{html.escape(ins['text'][:3000])}")
            except Exception:  
                c.rollback()
                traceback.print_exc()
            try:                       
                from . import reviews
                neg = reviews.summary_lines(c, s["id"], y, nms)
                if neg:
                    parts.append("\n" + html.escape(neg))
            except Exception:  
                c.rollback()
                traceback.print_exc()
        except Exception as e:  
            c.rollback()
            parts.append(f"не удалось посчитать: {html.escape(str(e)[:120])}")
        parts.append(f"\n▲▼ — к позавчера. Подробно: {SITE}")
        ok = bot.send(chat_id, "\n".join(parts)) and ok
        if want_ai:
            _send_ai(c, bot, chat_id, s, y)
    return ok


def _send_ai(c, bot: Bot, chat_id: int, s: dict, y):
    """Self-hosted application component."""
    secs = ["day"]
    if y.weekday() == 6:          
        secs += ["money", "cabinet", "search", "competitors", "niche"]
    for sec in secs:
        r = c.execute("SELECT title, body FROM ai_reports WHERE account_id=%s AND day=%s AND section=%s", (s["id"], y, sec)).fetchone()
        if not r:
            continue
        body = r["body"] if len(r["body"]) <= 3300 else r["body"][:3300].rsplit("\n", 1)[0] + "\n…"
        head = "итоги недели · " if sec != "day" else ""
        bot.send(chat_id, f"<b>🤖 {html.escape(s['title'] or s['name'])}: {head}{html.escape(r['title'].lower())}</b>\n\n{html.escape(body)}\n\n"
                          f"Вся ИИ-сводка — на главной: {SITE}")


def _once(c, uid: int, kind: str, ref: str) -> bool:
    """True — ещё не отправляли (и сразу помечаем)."""
    r = c.execute("INSERT INTO notify_log(user_id,kind,ref) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id", (uid, kind, ref)).fetchone()
    c.commit()
    return r is not None


def _live_collectors() -> set[str]:
    from .collectors import registry
    from .collectors_ozon import REGISTRY
    return set(registry()) | set(REGISTRY)


def alerts_for(c, u: dict) -> list[tuple[str, str, str]]:
    """(код, ключ-дня, текст) — предупреждения по магазинам пользователя (роль админ+ для ключей)."""
    from . import vault
    out = []
    today = today_msk().isoformat()
    off = muted(c, u["id"])
    for s in auth.shops_for(c, u):
        if s["id"] in off:
            continue
        name = html.escape(s["title"] or s["name"])
        if auth.can(s["role"], "admin"):
            t = c.execute("SELECT info FROM account_tokens WHERE account_id=%s", (s["id"],)).fetchone()
            exp = None
            if t and t["info"].get("exp"):
                exp = datetime.fromisoformat(str(t["info"]["exp"]))
            elif not t:
                env_name = c.execute("SELECT token_env FROM accounts WHERE id=%s", (s["id"],)).fetchone()["token_env"]
                tok = config.env().get(env_name or "")
                exp = vault.info(tok).get("exp") if tok else None
            if exp:
                days = (exp - datetime.now(timezone.utc)).days
                if days <= 14:
                    out.append((f"token:{s['id']}", today, f"🔑 <b>{name}</b>: ключ API WB истекает через {max(days, 0)} дн. ({exp:%d.%m.%Y}). "
                                                           f"Замените: «Настройки аккаунта» → «Заменить ключ»."))
        bad = c.execute("""SELECT collector, left(last_error, 160) err FROM collector_state WHERE account_id=%s AND last_error IS NOT NULL
                           AND last_error NOT ILIKE '%%лимит%%' AND coalesce(last_ok_at, 'epoch') < now() - interval '6 hours'""",
                        (s["id"],)).fetchall()
        bad = [b for b in bad if b["collector"] in _live_collectors()]   
        if bad:
            out.append((f"collect:{s['id']}", today, f"⚠️ <b>{name}</b>: не обновляются данные ({', '.join(b['collector'] for b in bad[:5])}). "
                                                     f"Ошибка: {html.escape(bad[0]['err'] or '')}"))
    return out


def _morning_jobs():
    """07:00 МСК: снимок конкурентов (Wildbox), затем ИИ-разбор вчерашнего дня по всем магазинам — к утренним сводкам."""
    from . import insights, market
    from .private_ai import scheduled_ai
    try:
        print("мониторинг конкурентов:", market.monitor_day(), flush=True)
    except Exception:  
        traceback.print_exc()
    def _photos():   
        try:
            from . import photos
            print("фотоворонка:", photos.daily(), flush=True)
        except Exception:  
            traceback.print_exc()
    threading.Thread(target=_photos, daemon=True).start()
    with db.connect() as c, scheduled_ai(c):
        for a in c.execute("SELECT id FROM accounts WHERE is_active AND marketplace='wb'").fetchall():
            try:
                insights.build(c, a["id"])
            except Exception:  
                c.rollback()
                traceback.print_exc()
            try:   
                from . import market, planning
                if market.shop_token(c, a["id"]) and (today_msk().day == 2 or c.execute(
                        "SELECT 1 FROM plan_items WHERE account_id=%s AND query_src='subject' LIMIT 1", (a["id"],)).fetchone()):
                    print("план:", a["id"], planning.auto_build(a["id"]), flush=True)
            except Exception:  
                c.rollback()
                traceback.print_exc()
            try:
                from . import aireport
                if aireport.shop_key(c, a["id"]):
                    print("ИИ-сводка:", a["id"], aireport.build(c, a["id"]), flush=True)
            except Exception:  
                c.rollback()
                traceback.print_exc()
        for a in c.execute("SELECT id FROM accounts WHERE is_active AND marketplace='ozon'").fetchall():
            try:   
                from . import aireport
                if aireport.shop_key(c, a["id"]):
                    print("ИИ-сводка Ozon:", a["id"], aireport.build(c, a["id"]), flush=True)
            except Exception:  
                c.rollback()
                traceback.print_exc()


ADS_HOURS = (9, 12, 15, 18, 21)      


def _ads_jobs(morning: bool):
    """Реклама WB по всем магазинам: утром — итоги прошлых действий, рекомендованные ставки WB и пояснение нейросети; днём — быстрый разбор."""
    from . import ads_ai
    from .private_ai import scheduled_ai
    with db.connect() as c, scheduled_ai(c):
        for a in c.execute("SELECT id FROM accounts WHERE is_active AND marketplace='wb'").fetchall():
            try:
                print("реклама:", a["id"], ads_ai.run(c, a["id"], note=morning, slow=morning), flush=True)
            except Exception:  
                c.rollback()
                traceback.print_exc()


def _calendar_jobs():
    """Calendar deliveries have their own connection; Telegram delays must not
    block summaries, news and other minute jobs in the main scheduler."""
    try:
        from .calendar import send_reminders
        with db.connect() as c:
            send_reminders(c, ASSIST)
    except Exception:  
        traceback.print_exc()


def scheduler():
    """Раз в минуту: утренние сводки (в своё время МСК, раз в день) и предупреждения (раз в день на каждое)."""
    calendar_thread = None
    while True:
        try:
            now = datetime.now(MSK)
            with db.connect() as c:
                if now.hour >= 7:
                    r = c.execute("""INSERT INTO app_settings(key,value) VALUES ('morning_jobs', %s) ON CONFLICT (key) DO UPDATE
                                     SET value=EXCLUDED.value WHERE app_settings.value <> EXCLUDED.value RETURNING key""",
                                  (json.dumps(now.date().isoformat()),)).fetchone()
                    c.commit()
                    if r:
                        threading.Thread(target=_morning_jobs, daemon=True).start()
                if now.hour in ADS_HOURS and now.minute >= 30:      
                    slot = f"{now.date()}:{now.hour}"
                    r = c.execute("""INSERT INTO app_settings(key,value) VALUES ('ads_slot', %s) ON CONFLICT (key) DO UPDATE
                                     SET value=EXCLUDED.value WHERE app_settings.value <> EXCLUDED.value RETURNING key""",
                                  (json.dumps(slot),)).fetchone()
                    c.commit()
                    if r:
                        threading.Thread(target=_ads_jobs, args=(now.hour == ADS_HOURS[0],), daemon=True).start()
                try:   
                    from . import news
                    news.sync_changes(c)
                    if now.minute % 5 == 0:     
                        news.sync_spp(c)
                    news.send_pending(c)
                except Exception:  
                    c.rollback()
                    traceback.print_exc()
                for r in c.execute("""SELECT s.*, u.email FROM notify_settings s JOIN users u ON u.id=s.user_id
                                      WHERE s.chat_id IS NOT NULL AND u.is_active""").fetchall():
                    
                    if r["daily"] and now.time() >= r["daily_time"] and in_window(r, now) and _once(c, r["user_id"], "daily", now.date().isoformat()):
                        send_daily(c, r["user_id"], r["chat_id"])
                    if r["alerts"] and now.minute % 30 == 0:
                        u = c.execute("SELECT * FROM users WHERE id=%s", (r["user_id"],)).fetchone()
                        for code, ref, text in alerts_for(c, u):
                            if _once(c, r["user_id"], "alert:" + code, ref):
                                notify(c, r["user_id"], r["chat_id"], text)
                try:
                    flush_queue(c)
                except Exception:  
                    c.rollback()
                    traceback.print_exc()
                if calendar_thread is None or not calendar_thread.is_alive():
                    calendar_thread = threading.Thread(target=_calendar_jobs, daemon=True)
                    calendar_thread.start()
        except Exception:  
            traceback.print_exc()
        time.sleep(60 - datetime.now().second + 1)


AS_HELP = ("🧙 Я Стометрик, помощник по твоим магазинам Wildberries и Ozon. Спрашивай обычным текстом, например:\n"
           "• «Сколько заказов было вчера на ВБ и на Озоне?»\n• «Какие товары просели за неделю?»\n• «Покажи юнитку по сиропам за октябрь»\n"
           "Можно прислать скрин или файл (фото, PDF, xlsx, csv).\n\n"
           "/shop — выбрать магазин\n/new — новый разговор\n/summary — сводка по выбранному магазину (/summary all — по всем)\n"
           "/settings — какие уведомления присылать\n/stop — выключить уведомления\n"
           "Настройки уведомлений — на сайте: «Настройки аккаунта».")
_BUSY: set[int] = set()
_BUSY_LOCK = threading.Lock()


def _settings_kb(c, uid: int) -> tuple[str, dict]:
    """/settings: какие уведомления присылать — галочки (кнопка переключает)."""
    from .news import KINDS
    s = c.execute("SELECT * FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
    kinds = (s or {}).get("kinds") or {}
    rows = [(f"daily", f"Утренняя сводка ({s['daily_time'].strftime('%H:%M')} МСК)", bool(s and s["daily"])),
            ("ai", "ИИ-сводка к утренней", bool(s and s["ai"])), ("alerts", "Предупреждения (ключ, сбор данных)", bool(s and s["alerts"]))]
    rows += [(k, t, kinds.get(k) is not False) for k, t, _ in KINDS]
    kb = {"inline_keyboard": [[{"text": ("✅ " if on else "⬜ ") + t, "callback_data": "nk:" + k}] for k, t, on in rows]}
    return "🔔 Какие уведомления присылать (нажми, чтобы включить или выключить). Время сводки — на сайте, «Настройки аккаунта».", kb


def _relink(c, tg: int, uid: int):
    """Код с сайта — Telegram переходит к этому аккаунту, даже если был привязан к другому (раньше молча оставался на старом)."""
    c.execute("UPDATE users SET telegram_id=NULL WHERE telegram_id=%s AND id<>%s", (tg, uid))
    c.execute("UPDATE users SET telegram_id=%s WHERE id=%s", (tg, uid))
    c.execute("UPDATE notify_settings SET chat_id=NULL WHERE chat_id=%s AND user_id<>%s", (tg, uid))   


def _link_user(bot: Bot, c, tg: int, text: str) -> int | None:
    """Кто пишет: /start <код> с сайта привязывает Telegram к аккаунту; иначе — по уже привязанному telegram_id."""
    if text.startswith("/start ") and len(text) > 7:
        r = c.execute("""UPDATE tg_link_codes l SET used_at=now() FROM users u
                         WHERE l.code=%s AND l.used_at IS NULL AND l.expires_at>now() AND u.id=l.user_id AND u.is_active
                         RETURNING l.user_id""",
                      (text[7:].strip(),)).fetchone()
        if not r:
            bot.send(tg, "Ссылка устарела. Откройте сайт → «Настройки аккаунта» → «Подключить Telegram» ещё раз.")
            return None
        _relink(c, tg, r["user_id"])
        c.commit()
        return r["user_id"]
    u = c.execute("SELECT id FROM users WHERE telegram_id=%s AND is_active", (tg,)).fetchone()
    if not u:
        bot.send(tg, "Этот Telegram пока не привязан к аккаунту Seller Analytics. Откройте " + SITE +
                     " → «Настройки аккаунта» → «Подключить Telegram».")
        return None
    return u["id"]


def _as_shops(c, uid: int) -> list[dict]:
    u = c.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    return auth.shops_for(c, u) if u else []


def _as_shop(c, uid: int) -> dict | None:
    """Магазин помощника: выбранный в боте (/shop), иначе магазин по умолчанию, иначе первый с доступным Стометриком."""
    from . import assistant
    shops = _as_shops(c, uid)
    if not shops:
        return None
    by = {x["id"]: x for x in shops}
    ns = c.execute("SELECT as_shop FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
    d = c.execute("SELECT default_shop_id FROM users WHERE id=%s", (uid,)).fetchone()["default_shop_id"]
    for sid in (ns and ns["as_shop"], d):
        if sid in by:
            return by[sid]
    return next((x for x in shops if assistant.access(c, x["id"], uid)["ok"]), shops[0])


def _shop_kb(c, uid: int, cur: int | None) -> dict:
    rows = [[{"text": ("✅ " if x["id"] == cur else "") + (x["title"] or x["name"]) + {"ozon": " · Ozon", "ym": " · Маркет"}.get(x.get("marketplace"), " · WB"),
              "callback_data": f"shop:{x['id']}"}] for x in _as_shops(c, uid)[:30]]
    return {"inline_keyboard": rows}


def _md_html(t: str) -> str:
    """Ответ нейросети → HTML Telegram: экранируем, **жирный** → <b>, `код` → <code>, заголовки # → жирные строки."""
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"(?m)^#{1,4}\s*(.+)$", r"<b>\1</b>", t)
    return t


def _xlsx(tb: dict) -> bytes:
    """Таблица помощника → xlsx (цифры из базы как есть, доли — процентами)."""
    import io
    import openpyxl
    from openpyxl.styles import Font
    from .export import literal_cell
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Стометрик"
    cols = tb["columns"]
    for j, x in enumerate(cols, 1):
        literal_cell(ws, 1, j, x["title"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for i, r in enumerate(tb["rows"], 2):
        for j, x in enumerate(cols, 1):
            literal_cell(ws, i, j, r.get(x["field"]))
    for j, x in enumerate(cols, 1):
        fmt = {"share": "0.0%", "pct": "0.0%", "money": "#,##0", "int": "#,##0"}.get(x.get("type"))
        width = max(10, min(45, len(str(x["title"])) + 2))
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = width
        if fmt:
            for row in ws.iter_rows(min_row=2, min_col=j, max_col=j):
                row[0].number_format = fmt
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _as_ask(bot: Bot, tg: int, uid: int, text: str, file_ids: list[tuple[str, str]]):
    """Фоном: вопрос Стометрику из Telegram — тот же чат и движок, что на сайте; шаги — правкой сообщения, таблицы — xlsx."""
    from . import assistant
    try:
        with db.connect() as c:
            shop = _as_shop(c, uid)
            if not shop:
                bot.send(tg, "Магазинов пока нет — добавьте магазин на сайте: «Настройки аккаунта» → «+ Добавить магазин».")
                return
            ns = c.execute("SELECT as_chat FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
            ch = None
            if ns and ns["as_chat"]:   
                ch = c.execute("""SELECT * FROM assistant_chats WHERE id=%s AND user_id=%s AND shop_id=%s
                                  AND updated_at > now() - interval '12 hours'""", (ns["as_chat"], uid, shop["id"])).fetchone()
            if not ch:
                a = assistant.access(c, shop["id"], uid)
                if not a["ok"]:
                    bot.send(tg, "🧙 " + html.escape(a["reason"]))
                    return
                ch = c.execute("INSERT INTO assistant_chats(user_id,shop_id) VALUES (%s,%s) RETURNING *", (uid, shop["id"])).fetchone()
                c.execute("UPDATE notify_settings SET as_chat=%s WHERE user_id=%s", (ch["id"], uid))
                c.commit()
            files = []
            for fid, name in file_ids:
                try:
                    files.append(assistant.save_file(c, ch["id"], uid, name, bot.download(fid))["id"])
                except assistant.AskError as e:
                    c.rollback()
                    bot.send(tg, f"📎 {html.escape(name)}: {html.escape(str(e))}")
                    return
                except Exception:  
                    c.rollback()
                    bot.send(tg, f"📎 Не получилось скачать файл {html.escape(name)} (Telegram отдаёт ботам файлы до 20 МБ).")
                    return
            try:
                pid, _ = assistant.ask(c, uid, ch, text, files, source="telegram")
            except assistant.AskError as e:
                c.rollback()
                bot.send(tg, "🧙 " + html.escape(str(e)))
                return
            c.commit()
        sname = html.escape(shop["title"] or shop["name"])
        head = f"🧙 Думаю… <i>({sname})</i>"
        mid = bot.send_id(tg, head)
        th = assistant.start(pid)
        shown = None
        while th and th.is_alive():
            try:
                bot.api("sendChatAction", chat_id=tg, action="typing")
            except Exception:  
                pass
            th.join(4)
            with db.connect() as c:
                d = c.execute("SELECT data FROM assistant_messages WHERE id=%s", (pid,)).fetchone()["data"] or {}
            steps = d.get("steps") or []
            if mid and steps and steps != shown:
                shown = list(steps)
                bot.edit(tg, mid, head + "\n" + "\n".join("• " + html.escape(x) for x in steps[-6:]))
        with db.connect() as c:
            r = c.execute("SELECT content, status, data FROM assistant_messages WHERE id=%s", (pid,)).fetchone()
        if mid:
            try:
                bot.api("deleteMessage", chat_id=tg, message_id=mid)
            except Exception:  
                pass
        body = _md_html(r["content"] or "Готово.")
        if r["status"] == "error":
            body = "😕 " + body
        chunks = [body[i:i + 3900] for i in range(0, len(body), 3900)] or [""]
        for ch_text in chunks:
            if not bot.send(tg, ch_text):          
                bot.send(tg, html.escape(re.sub(r"<[^>]+>", "", html.unescape(ch_text))))
        for tb in ((r["data"] or {}).get("tables") or [])[-1:]:     
            name = re.sub(r"[^\w\-. ]+", "", (tb.get("title") or "таблица").replace("·", "-"))[:80].strip() or "таблица"
            note = "\nЗаписать черновик — кнопкой «Применить» в этом чате на сайте platform.example.org (Стометрик)." if tb.get("draft") else ""
            bot.doc(tg, f"{name}.xlsx", _xlsx(tb), caption=f"📊 {tb.get('title') or ''} · {len(tb['rows'])} строк{note}")
    except Exception:  
        traceback.print_exc()
        bot.send(tg, "Что-то пошло не так 🙈 Попробуйте ещё раз чуть позже.")
    finally:
        with _BUSY_LOCK:
            _BUSY.discard(tg)


def handle_assistant(bot: Bot, m: dict):
    tg = m["from"]["id"]
    text = (m.get("text") or m.get("caption") or "").strip()
    with db.connect() as c:
        uid = _link_user(bot, c, tg, text)
        if not uid:
            return
        low = text.lower()
        if text.startswith("/start"):
            c.execute("""INSERT INTO notify_settings(user_id,chat_id,bot) VALUES (%s,%s,'assistant')
                         ON CONFLICT (user_id) DO UPDATE SET chat_id=EXCLUDED.chat_id, bot='assistant', updated_at=now()""", (uid, tg))
            c.commit()
            s = c.execute("SELECT * FROM notify_settings WHERE user_id=%s", (uid,)).fetchone()
            u = c.execute("SELECT name FROM users WHERE id=%s", (uid,)).fetchone()
            shop = _as_shop(c, uid)
            bot.send(tg, f"Привет{', ' + html.escape(u['name'].split()[0]) if u['name'] else ''}! 👋\n\n" + html.escape(AS_HELP) +
                     (f"\n\nСейчас магазин: <b>{html.escape(shop['title'] or shop['name'])}</b>" if shop else "") +
                     "\n\n🔔 Уведомления подключены: утренняя сводка " +
                     (f"в {s['daily_time'].strftime('%H:%M')} МСК" if s["daily"] else "выключена") +
                     (", ИИ-сводка" if s["ai"] else "") + (", предупреждения" if s["alerts"] else "") + ".")
            return
        if text in ("/help", "помощь"):
            bot.send(tg, html.escape(AS_HELP))
            return
        if text in ("/stop", "стоп"):
            c.execute("UPDATE notify_settings SET chat_id=NULL, updated_at=now() WHERE user_id=%s", (uid,))
            c.commit()
            bot.send(tg, "🔕 Уведомления выключены. На вопросы я по-прежнему отвечаю. Включить снова — /start.")
            return
        if text.startswith("/summary") or low in ("сводка", "сводка все"):
            every = "all" in low or "все" in low
            shop = None if every else _as_shop(c, uid)
            send_daily(c, uid, tg, force=True, only=shop and shop["id"])
            if shop and len(_as_shops(c, uid)) > 1:
                bot.send(tg, "Это сводка по выбранному магазину. По всем магазинам — /summary all, сменить магазин — /shop.")
            return
        if text.startswith("/new"):
            c.execute("UPDATE notify_settings SET as_chat=NULL WHERE user_id=%s", (uid,))
            c.commit()
            bot.send(tg, "🧙 Начинаем новый разговор. Спрашивай!")
            return
        if text.startswith("/shop"):
            shop = _as_shop(c, uid)
            bot.send(tg, "Выбери магазин — по нему я отвечаю по умолчанию (про другие магазины кабинета тоже можно спрашивать):",
                     reply_markup=_shop_kb(c, uid, shop and shop["id"]))
            return
        if text.startswith("/settings") or low in ("настройки", "уведомления"):
            c.execute("INSERT INTO notify_settings(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (uid,))
            c.commit()
            txt, kb = _settings_kb(c, uid)
            bot.send(tg, txt, reply_markup=kb)
            return
        if text.startswith("/"):
            bot.send(tg, html.escape(AS_HELP))
            return
    files = []
    if m.get("photo"):
        files.append((m["photo"][-1]["file_id"], f"photo_{m['message_id']}.jpg"))
    elif m.get("document"):
        files.append((m["document"]["file_id"], m["document"].get("file_name") or "file"))
    with _BUSY_LOCK:
        if tg in _BUSY:
            bot.send(tg, "🧙 Ещё думаю над прошлым вопросом — сейчас отвечу.")
            return
        _BUSY.add(tg)
    threading.Thread(target=_as_ask, args=(bot, tg, uid, text, files), daemon=True).start()


def handle_assistant_cb(bot: Bot, cb: dict):
    tg = cb["from"]["id"]
    data = cb.get("data") or ""
    try:
        bot.api("answerCallbackQuery", callback_query_id=cb["id"])
    except Exception:  
        pass
    if data.startswith("nk:"):
        from .news import KIND_KEYS
        k = data[3:]
        with db.connect() as c:
            u = c.execute("SELECT id FROM users WHERE telegram_id=%s AND is_active", (tg,)).fetchone()
            if not u:
                return
            if k in ("daily", "ai", "alerts"):
                c.execute(f"UPDATE notify_settings SET {k} = NOT {k}, updated_at=now() WHERE user_id=%s", (u["id"],))
            elif k in KIND_KEYS:
                c.execute("""UPDATE notify_settings SET kinds = kinds || jsonb_build_object(%s::text, NOT coalesce((kinds->>%s)::boolean, true)),
                             updated_at=now() WHERE user_id=%s""", (k, k, u["id"]))
            c.commit()
            txt, kb = _settings_kb(c, u["id"])
            msg = cb.get("message") or {}
            if msg.get("message_id"):
                bot.edit(tg, msg["message_id"], txt, reply_markup=kb)
        return
    if not data.startswith("shop:"):
        return
    with db.connect() as c:
        u = c.execute("SELECT id FROM users WHERE telegram_id=%s AND is_active", (tg,)).fetchone()
        if not u:
            return
        sid = int(data[5:])
        shop = next((x for x in _as_shops(c, u["id"]) if x["id"] == sid), None)
        if not shop:
            bot.send(tg, "Нет доступа к этому магазину.")
            return
        c.execute("""INSERT INTO notify_settings(user_id,as_shop) VALUES (%s,%s)
                     ON CONFLICT (user_id) DO UPDATE SET as_shop=EXCLUDED.as_shop, as_chat=NULL""", (u["id"], sid))
        c.commit()
        msg = cb.get("message") or {}
        if msg.get("message_id"):
            bot.edit(tg, msg["message_id"], f"✅ Магазин: <b>{html.escape(shop['title'] or shop['name'])}</b>. Новый разговор — спрашивай!")


def assistant_loop():
    """Ждём токен бота «Стометрик» (вводит суперадмин в админке) и слушаем его."""
    global ASSIST
    while True:
        try:
            with db.connect() as c:
                tok = assistant_token(c)
            if tok:
                ASSIST = Bot("", tok)
                if ASSIST.token:
                    print("бот Стометрик:", ASSIST.username, flush=True)
                    ASSIST.api("setMyCommands", commands=[
                        {"command": "shop", "description": "Выбрать магазин"}, {"command": "new", "description": "Новый разговор"},
                        {"command": "summary", "description": "Сводка сейчас"}, {"command": "help", "description": "Что я умею"},
                        {"command": "stop", "description": "Выключить уведомления"}])
                    ASSIST.poll(handle_assistant, media=True, on_cb=handle_assistant_cb)
        except Exception:  
            traceback.print_exc()
        time.sleep(30)



def main():
    global NOTIFY
    NOTIFY = Bot("TG_BOT_NOTIFY_TOKEN")
    reg = Bot("TG_BOT_REGISTER_TOKEN")
    print("бот уведомлений:", NOTIFY.username, "| бот регистрации:", reg.username, flush=True)
    th = []
    if NOTIFY.token:
        th.append(threading.Thread(target=NOTIFY.poll, args=(handle_notify,), daemon=True))
        th.append(threading.Thread(target=scheduler, daemon=True))
    if reg.token:
        th.append(threading.Thread(target=reg.poll, args=(handle_register,), daemon=True))
    th.append(threading.Thread(target=assistant_loop, daemon=True))
    for t in th:
        t.start()
    while all(t.is_alive() for t in th):
        time.sleep(10)
    raise SystemExit("поток бота остановился — перезапуск через systemd")


if __name__ == "__main__":
    main()

"""Self-hosted application component."""

import json
import time
from datetime import datetime, timezone

import httpx

from . import vault

DISCLAIMER_VERSION = "2026-10-20"
DISCLAIMER = ("С этим ключом сервис сможет вносить изменения в ваш кабинет маркетплейса — только в тех блоках, которые вы включите "
              "(например, отвечать на отзывы). Ответы и изменения, сделанные с помощью нейросети, могут содержать неточности: "
              "обязательно проверяйте и контролируйте их. Все действия сервиса записываются в журнал. Остановить всё можно кнопкой "
              "«Стоп» или удалением ключа; ключ также можно отозвать в личном кабинете маркетплейса.")

MODES = ("off", "manual", "draft", "auto")         
AI_MODES = ("draft", "auto")
MODE_KEYS = ("pos_mode", "neg_mode", "mode")       

BLOCKS = {
    "reviews": {
        "title": "Отзывы", "mp": ("wb", "ozon"), "scope": "Вопросы и отзывы",
        "about": "Ответы на отзывы покупателей: черновики ИИ работают и без ключа на запись (ответ можно скопировать и опубликовать в ЛК). "
                 "Включённый блок + ключ на запись — отправка из сервиса и авто-ответы ИИ. Негативные отзывы — в ежедневной сводке.",
        "writes": {("POST", "feedbacks", "/api/v1/feedbacks/answer"), ("PATCH", "feedbacks", "/api/v1/feedbacks/answer"),
                   ("POST", "ozon", "/v1/review/comment/create")},
        "defaults": {"pos_mode": "draft", "neg_mode": "draft", "auto_limit": 30, "notify_neg": True, "use_name": True,
                     "reco_every": 3, "reco_neg_alt": False, "reco_reg": ""},
    },
    "questions": {
        "title": "Вопросы", "mp": ("wb",), "scope": "Вопросы и отзывы",
        "about": "Ответы на вопросы покупателей о товарах: ИИ отвечает только по карточке, правилам и пометкам сотрудников, без выдумок. "
                 "Черновики ИИ работают и без ключа на запись (ответ можно скопировать и опубликовать в ЛК). "
                 "Включённый блок + ключ на запись — отправка из сервиса и авто-ответы ИИ.",
        "writes": {("PATCH", "feedbacks", "/api/v1/questions")},
        "defaults": {"mode": "draft", "auto_limit": 30, "reco_every": 3},
    },
    "cards": {
        "title": "Карточки", "mp": ("wb",), "scope": "Контент",
        "about": "Редактирование карточек: название, описание, характеристики, габариты, фото и их порядок, цена. Любая правка (своя или "
                 "предложение ИИ) — сначала черновик; в WB уходит только по кнопке «Применить» с подтверждением.",
        "writes": {("POST", "content", "/content/v2/cards/update"), ("POST", "content", "/content/v3/media/save"),
                   ("POST", "prices", "/api/v2/upload/task")},
        "defaults": {"ai": True},
    },
    "ads": {
        "title": "Реклама", "mp": ("wb",), "scope": "Продвижение",
        "about": "Управление рекламой WB ради прибыли: утром и днём сервис предлагает действия (пауза, запуск, ставки, артикулы в кампании, "
                 "ставки на ключи, минус-фразы, места размещения, пополнение бюджета, новые кампании) с цифрами и причиной; в WB уходит только "
                 "по кнопке «Применить», деньги и новые кампании — с двойным подтверждением. Раздел «📢 Реклама».",
        
        "writes": {("GET", "advert", "/adv/v0/start"), ("GET", "advert", "/adv/v0/pause"), ("PATCH", "advert", "/adv/v0/auction/nms"),
                   ("PATCH", "advert", "/api/advert/v1/bids"), ("PUT", "advert", "/adv/v0/auction/placements"),
                   ("POST", "advert", "/adv/v0/normquery/set-minus"), ("POST", "advert", "/adv/v0/normquery/bids"),
                   ("POST", "advert", "/adv/v2/seacat/save-ad"), ("POST", "advert", "/adv/v1/budget/deposit")},
        "defaults": {"loss_min_spend": 300, "stock_days_min": 3, "kw_min_clicks": 15, "max_step": 30, "deposit_max": 5000, "create": True,
                     "notify": True,
                     
                     
                     "window_days": 7, "loss_weeks": 2, "cooldown_h": 72, "up_stock_days": 21, "season_loss_pct": 20, "season_organic_pct": 20,
                     "managers": "", "seasons": ""},
    },
    "prices": {"title": "Цены", "soon": True, "about": "Цены и скидки — вручную, полуавтоматически, автоматически."},
}


class ActionDenied(RuntimeError):
    pass



def block(c, shop: int, key: str) -> dict:
    """{enabled, settings} блока; настройки — поверх значений по умолчанию."""
    r = c.execute("SELECT enabled, settings FROM action_blocks WHERE account_id=%s AND block=%s", (shop, key)).fetchone()
    return {"enabled": bool(r and r["enabled"]), "settings": {**BLOCKS[key].get("defaults", {}), **((r or {}).get("settings") or {})}}


def save_block(c, shop: int, key: str, enabled: bool, settings: dict, uid: int) -> dict:
    d = BLOCKS[key].get("defaults", {})
    clean = {k: settings[k] for k in d if k in settings}
    for k in MODE_KEYS:
        if k in clean and clean[k] not in MODES:
            raise ActionDenied(f"Неизвестный режим: {clean[k]}")
    for k, lo, hi in (("loss_min_spend", 0, 100000), ("stock_days_min", 0, 60), ("kw_min_clicks", 5, 1000), ("max_step", 5, 50),
                      ("deposit_max", 1000, 1000000), ("reco_every", 1, 20), ("window_days", 3, 14), ("loss_weeks", 1, 6),
                      ("cooldown_h", 0, 168), ("up_stock_days", 0, 120), ("season_loss_pct", 0, 100), ("season_organic_pct", 0, 200)):
        if k in clean:                      
            clean[k] = max(lo, min(hi, float(clean[k] or 0)))
    for k in ("managers", "seasons"):           
        if k in clean:
            clean[k] = str(clean[k] or "")[:2000]
    if "reco_reg" in clean and clean["reco_reg"] not in ("", "heat"):
        raise ActionDenied("Неизвестный регламент рекомендаций")
    if "auto_limit" in clean:
        clean["auto_limit"] = max(0, min(500, int(clean["auto_limit"] or 0)))
    old = block(c, shop, key)
    if enabled and not old["enabled"]:
        clean["enabled_at"] = datetime.now(timezone.utc).isoformat()    
    else:
        clean["enabled_at"] = old["settings"].get("enabled_at")
    for k in MODE_KEYS:                         
        if clean.get(k) == "auto" and old["settings"].get(k) != "auto":
            clean[k + "_since"] = datetime.now(timezone.utc).isoformat()
        elif clean.get(k) == "auto":
            clean[k + "_since"] = old["settings"].get(k + "_since")
    c.execute("""INSERT INTO action_blocks(account_id,block,enabled,settings,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,now())
                 ON CONFLICT (account_id,block) DO UPDATE SET enabled=EXCLUDED.enabled, settings=EXCLUDED.settings,
                   updated_by=EXCLUDED.updated_by, updated_at=now()""", (shop, key, enabled, json.dumps(clean), uid))
    return block(c, shop, key)


def paused(c, shop: int) -> bool:
    r = c.execute("SELECT actions_paused FROM accounts WHERE id=%s", (shop,)).fetchone()
    return bool(r and r["actions_paused"])



def _read_oid(c, shop: int):
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone()
    if acc.get("seller_oid"):
        return acc["seller_oid"]
    if acc["marketplace"] == "ozon":
        r = c.execute("SELECT info->>'seller_oid' o FROM account_tokens WHERE account_id=%s", (shop,)).fetchone()
        return r and r["o"]
    try:
        return vault.info(vault.token_for(c, acc)).get("seller_oid")
    except SystemExit:
        return None


PRICE_SCOPE = "Цены и скидки"


def split(c, shop: int) -> bool:
    """Раздельные ключи: основной — без цен, цены — только отдельным ключом."""
    r = c.execute("SELECT write_key_split FROM accounts WHERE id=%s", (shop,)).fetchone()
    return bool(r and r["write_key_split"])


def set_split(c, shop: int, on: bool, uid: int):
    if on:
        inf = write_info(c, shop)
        if inf and PRICE_SCOPE in (inf.get("scopes") or []):
            raise ActionDenied(f"В основном ключе есть раздел «{PRICE_SCOPE}». Чтобы разделить ключи, сначала замените основной ключ на ключ "
                               f"без этого раздела — иначе через него по-прежнему можно менять цены.")
    c.execute("UPDATE accounts SET write_key_split=%s WHERE id=%s", (on, shop))
    log(c, shop, "_key", "write_key/split_on" if on else "write_key/split_off", None, None, None, uid, ok=True)


def write_info(c, shop: int, purpose: str = "main") -> dict | None:
    r = c.execute("""SELECT t.info, t.added_at, t.agreed, u.email, u.name FROM account_write_tokens t LEFT JOIN users u ON u.id=t.added_by
                     WHERE t.account_id=%s AND t.purpose=%s""", (shop, purpose)).fetchone()
    if not r:
        return None
    return {**r["info"], "added_at": r["added_at"], "agreed": r["agreed"], "added_by": r["name"] or r["email"]}


def _set_ozon_token(c, shop: int, client_id: str, api_key: str, uid: int) -> dict:
    """Ozon: пара Client-Id + Api-Key; роль не «только чтение», тот же Client-Id, что у магазина."""
    from . import ozon
    inf = ozon.check(client_id, api_key)
    if inf.get("error"):
        raise ActionDenied(inf["error"])
    if inf.get("read_only"):
        raise ActionDenied("У ключа роль только на чтение — для взаимодействий нужен ключ с правом изменений (например, роль Admin)")
    oid = _read_oid(c, shop)
    if oid and str(oid) != str(inf["seller_oid"]):
        raise ActionDenied("Client-Id другого кабинета: не совпадает с ключом магазина")
    info = {"seller_oid": inf["seller_oid"], "scopes": inf.get("roles") or [], "kind": "Ozon", "exp": None}
    c.execute("""INSERT INTO account_write_tokens(account_id,enc,info,agreed,added_by) VALUES (%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id,purpose) DO UPDATE SET enc=EXCLUDED.enc, info=EXCLUDED.info, agreed=EXCLUDED.agreed,
                   added_by=EXCLUDED.added_by, added_at=now()""",
              (shop, vault.encrypt(json.dumps({"client_id": str(client_id).strip(), "api_key": api_key.strip()})), json.dumps(info),
               DISCLAIMER_VERSION, uid))
    log(c, shop, "_key", "write_key/set", None, None, {"roles": info["scopes"]}, uid, ok=True)
    return info


def set_write_token(c, shop: int, token: str, uid: int, client_id: str | None = None, purpose: str = "main") -> dict:
    """Проверка ключа на запись WB: боевой, не «только чтение», тот же кабинет продавца, что и ключ на чтение; WB его принимает.
    purpose='prices' — отдельный ключ для цен (режим раздельных ключей): обязан иметь раздел «Цены и скидки»;
    основной ключ в этом режиме этого раздела иметь не должен."""
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    if purpose not in ("main", "prices"):
        raise ActionDenied("Неизвестный ключ")
    if purpose == "prices" and (mp != "wb" or not split(c, shop)):
        raise ActionDenied("Отдельный ключ для цен — только в режиме «Раздельные ключи» (WB)")
    if mp == "ozon":
        if not client_id:
            raise ActionDenied("Укажите Client-Id")
        return _set_ozon_token(c, shop, client_id, token, uid)
    token = token.strip()
    inf = vault.info(token)
    if inf.get("error") and not inf["error"].startswith("В ключе не хватает"):
        raise ActionDenied(inf["error"])
    if inf.get("read_only"):
        raise ActionDenied("Это ключ «Только чтение» — для взаимодействий нужен ключ с правом записи")
    oid = _read_oid(c, shop)
    if oid and inf.get("seller_oid") and str(oid) != str(inf["seller_oid"]):
        raise ActionDenied("Ключ от другого кабинета продавца: номер кабинета не совпадает с ключом магазина")
    scopes = inf.get("scopes") or []
    if purpose == "prices" and PRICE_SCOPE not in scopes:
        raise ActionDenied(f"В ключе для цен нет раздела «{PRICE_SCOPE}»")
    if purpose == "main" and split(c, shop) and PRICE_SCOPE in scopes:
        raise ActionDenied(f"Включены раздельные ключи: в основном ключе не должно быть раздела «{PRICE_SCOPE}» — цены меняются только отдельным ключом")
    try:
        r = httpx.get("https://feedbacks-api.wildberries.ru/api/v1/feedbacks/count-unanswered", headers={"Authorization": token}, timeout=20)\
            if "Вопросы и отзывы" in inf.get("scopes", []) else httpx.get("https://common-api.wildberries.ru/ping", headers={"Authorization": token}, timeout=20)
    except httpx.HTTPError as e:
        raise ActionDenied(f"WB не ответил: {type(e).__name__}") from None
    if r.status_code == 401:
        raise ActionDenied("WB не принял ключ (401): ключ отозван или неверный")
    info = {k: inf.get(k) for k in ("seller_oid", "scopes", "kind")}
    info["exp"] = inf["exp"].isoformat() if inf.get("exp") else None
    c.execute("""INSERT INTO account_write_tokens(account_id,purpose,enc,info,agreed,added_by) VALUES (%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id,purpose) DO UPDATE SET enc=EXCLUDED.enc, info=EXCLUDED.info, agreed=EXCLUDED.agreed,
                   added_by=EXCLUDED.added_by, added_at=now()""", (shop, purpose, vault.encrypt(token), json.dumps(info), DISCLAIMER_VERSION, uid))
    log(c, shop, "_key", "write_key/set" if purpose == "main" else "write_key/set_prices", None, None,
        {"scopes": info["scopes"], "exp": info["exp"]}, uid, ok=True)
    return info


def drop_write_token(c, shop: int, uid: int, purpose: str = "main"):
    c.execute("DELETE FROM account_write_tokens WHERE account_id=%s AND purpose=%s", (shop, purpose))
    log(c, shop, "_key", "write_key/remove" if purpose == "main" else "write_key/remove_prices", None, None, None, uid, ok=True)


def _write_token(c, shop: int, purpose: str = "main") -> str | None:
    r = c.execute("SELECT enc FROM account_write_tokens WHERE account_id=%s AND purpose=%s", (shop, purpose)).fetchone()
    return vault.decrypt(r["enc"]) if r else None


def scopes_ok(c, shop: int, key: str) -> bool:
    inf = write_info(c, shop)
    if inf and inf.get("kind") == "Ozon":       
        return True
    return bool(inf) and BLOCKS[key].get("scope", "") in (inf.get("scopes") or [])



def log(c, shop: int, blk: str, action: str, target, before, after, uid, by_ai=False, ok=True, error=None):
    c.execute("""INSERT INTO action_log(account_id,block,action,target,before,after,user_id,by_ai,ok,error)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
              (shop, blk, action, target, json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
               json.dumps(after, ensure_ascii=False, default=str) if after is not None else None, uid, by_ai, ok, error))



def can_write(c, shop: int, key: str) -> str | None:
    """None — можно; иначе причина по-русски."""
    if paused(c, shop):
        return "Взаимодействия магазина остановлены кнопкой «Стоп»"
    if not block(c, shop, key)["enabled"]:
        return f"Блок «{BLOCKS[key]['title']}» выключен в настройках взаимодействий"
    if not _write_token(c, shop):
        return "Не добавлен ключ на запись (Взаимодействия → Ключ на запись)"
    if not scopes_ok(c, shop, key):
        return f"В ключе на запись нет раздела «{BLOCKS[key]['scope']}»"
    return None


HOST_SCOPE = {"prices": "Цены и скидки", "content": "Контент", "feedbacks": "Вопросы и отзывы", "advert": "Продвижение"}


def wb_write(c, shop: int, key: str, method: str, host: str, path: str, body, *, uid=None, by_ai=False,
             target=None, before=None, params: dict | None = None):
    """Единственная точка записи в WB. Проверки → лимит → вызов → api_log + action_log. Ошибка — ActionDenied с текстом."""
    from .wb import HOSTS, WB, RateLimited, WBError
    if (method, host, path) not in BLOCKS[key]["writes"]:
        raise ActionDenied(f"{method} {path}: метод не входит в блок «{BLOCKS[key]['title']}»")
    why = can_write(c, shop, key)
    if why:
        raise ActionDenied(why)
    purpose = "prices" if host == "prices" and split(c, shop) else "main"     
    if not _write_token(c, shop, purpose):
        raise ActionDenied("Не добавлен отдельный ключ для цен (Взаимодействия → Ключи на запись)")
    need = HOST_SCOPE.get(host)
    if need and need not in ((write_info(c, shop, purpose) or {}).get("scopes") or []):
        raise ActionDenied(f"В ключе {'для цен' if purpose == 'prices' else 'на запись'} нет раздела «{need}»")
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone()
    w = WB.__new__(WB)           
    w.c, w.acc = c, acc
    bucket = f"{host}:{path}"
    status, err = None, None
    t0 = time.monotonic()
    try:
        w._wait_slot(bucket, 30)
        r = httpx.request(method, HOSTS[host] + path, json=body, params=params, timeout=30, headers={"Authorization": _write_token(c, shop, purpose)})
        status = r.status_code
        if status == 429:
            raise ActionDenied("WB просит подождать (лимит запросов) — попробуйте через минуту")
        if status >= 400:
            err = r.text[:300]
            raise ActionDenied(f"WB вернул ошибку {status}: {err}")
        try:
            data = r.json() if r.content.strip() else None
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("error") is True:      
            err = str(data.get("errorText") or data.get("additionalErrors") or "ошибка")[:300]
            raise ActionDenied(f"WB не принял: {err}")
    except (RateLimited, WBError, httpx.HTTPError) as e:
        err = str(e)
        raise ActionDenied(f"WB: {e}") from None
    except ActionDenied as e:
        err = err or str(e)
        raise
    finally:
        c.execute("INSERT INTO api_log(account_id,method,params,status,rows,archive,error,duration_ms) VALUES (%s,%s,%s,%s,NULL,NULL,%s,%s)",
                  (shop, f"{method} {host}{path} [write]", json.dumps({"target": target}, ensure_ascii=False), status, err,
                   int((time.monotonic() - t0) * 1000)))
        log(c, shop, key, f"{method} {path}", target, before, body if body is not None else params, uid, by_ai=by_ai, ok=err is None, error=err)
        c.commit()
    return data


def oz_write(c, shop: int, key: str, path: str, body: dict, *, uid=None, by_ai=False, target=None, before=None) -> None:
    """Единственная точка записи в Ozon: те же проверки, что у WB; ключ — пара Client-Id + Api-Key на запись."""
    from .ozon import HOST
    if ("POST", "ozon", path) not in BLOCKS[key]["writes"]:
        raise ActionDenied(f"POST {path}: метод не входит в блок «{BLOCKS[key]['title']}»")
    why = can_write(c, shop, key)
    if why:
        raise ActionDenied(why)
    cr = json.loads(_write_token(c, shop))
    status, err = None, None
    t0 = time.monotonic()
    try:
        r = httpx.post(HOST + path, json=body, timeout=30,
                       headers={"Client-Id": cr["client_id"], "Api-Key": cr["api_key"], "Content-Type": "application/json"})
        status = r.status_code
        if status == 429:
            raise ActionDenied("Ozon просит подождать (лимит запросов) — попробуйте через минуту")
        if status >= 400:
            err = r.text[:300]
            if "existing subscription" in err:
                raise ActionDenied("Отвечать на отзывы через API Ozon можно только с подпиской Premium Pro")
            raise ActionDenied(f"Ozon вернул ошибку {status}: {err}")
    except httpx.HTTPError as e:
        err = str(e)
        raise ActionDenied(f"Ozon: {e}") from None
    except ActionDenied as e:
        err = err or str(e)
        raise
    finally:
        c.execute("INSERT INTO api_log(account_id,method,params,status,rows,archive,error,duration_ms) VALUES (%s,%s,%s,%s,NULL,NULL,%s,%s)",
                  (shop, f"ozon:{path} [write]", json.dumps({"target": target}, ensure_ascii=False), status, err,
                   int((time.monotonic() - t0) * 1000)))
        log(c, shop, key, f"POST {path}", target, before, body, uid, by_ai=by_ai, ok=err is None, error=err)
        c.commit()

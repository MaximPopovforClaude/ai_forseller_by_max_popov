"""Блок «Карточки» WB: черновик изменений → сравнение «было/стало» → «Применить на WB» (только по кнопке пользователя) → откат.

- «было» — карточка, прочитанная из WB заново в момент начала черновика (+ цена/скидка);
- перед применением карточку читаем из WB ещё раз: если её успели изменить в кабинете (updatedAt другой) — не затираем, просим обновить;
- /content/v2/cards/update требует карточку целиком — отправляем актуальную карточку из WB с изменёнными полями;
- медиа (/content/v3/media/save) заменяются целиком — отправляем полный список ссылок в нужном порядке (вместе с видео);
- новые фото пользователь загружает к нам, WB забирает их по ссылке со случайным токеном;
- цена/скидка — /api/v2/upload/task (раздел ключа «Цены и скидки»).
"""

import json
import secrets
import time
from decimal import Decimal
from pathlib import Path

from . import actions, config

AI_PRICE_DROP_MAX = 0.15     
USER_PRICE_DROP_WARN = 0.20  
TITLE_MAX = 60
DESC_MAX = 5000
FIELDS = ("title", "description", "characteristics", "dimensions", "media", "price", "discount")
MEDIA_DIR = config.DATA / "card_media"
from .config import site_url
SITE = site_url()



def _wb(c, shop: int):
    from .wb import WB
    return WB(c, c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone())


def live_card(c, shop: int, nm: int) -> dict:
    """Карточка прямо из WB (не из нашего снимка) + текущая цена/скидка."""
    body = {"settings": {"cursor": {"limit": 10}, "filter": {"textSearch": str(nm), "withPhoto": -1}}}
    data = _wb(c, shop).call("content", "/content/v2/get/cards/list", "POST", body=body) or {}
    card = next((x for x in data.get("cards") or [] if x.get("nmID") == nm), None)
    if not card:
        raise actions.ActionDenied(f"WB не вернул карточку {nm} — проверьте артикул")
    pr = c.execute("""SELECT price, discount FROM prices_snap WHERE account_id=%s AND nm_id=%s ORDER BY snap_at DESC LIMIT 1""",
                   (shop, nm)).fetchone()
    card["_price"] = {"price": float(pr["price"]) if pr and pr["price"] is not None else None,
                      "discount": int(pr["discount"]) if pr and pr["discount"] is not None else None}
    return card


def charcs(c, shop: int, subject_id: int) -> list[dict]:
    """Характеристики предмета WB (кэш на сутки)."""
    r = c.execute("SELECT data FROM wb_subject_charcs WHERE subject_id=%s AND fetched_at > now() - interval '1 day'", (subject_id,)).fetchone()
    if r:
        return r["data"]
    data = (_wb(c, shop).call("content", f"/content/v2/object/charcs/{subject_id}", bucket_path="/content/v2/object/charcs") or {}).get("data") or []
    c.execute("""INSERT INTO wb_subject_charcs(subject_id,data,fetched_at) VALUES (%s,%s,now())
                 ON CONFLICT (subject_id) DO UPDATE SET data=EXCLUDED.data, fetched_at=now()""", (subject_id, json.dumps(data, ensure_ascii=False)))
    c.commit()
    return data


def media_of(card: dict) -> list[dict]:
    """Медиа карточки по порядку: [{kind: photo|video, url, thumb}]."""
    out = [{"kind": "photo", "url": p.get("big") or p.get("hq"), "thumb": p.get("c246x328") or p.get("tm") or p.get("big")}
           for p in card.get("photos") or []]
    if card.get("video"):
        out.append({"kind": "video", "url": card["video"], "thumb": None})
    return out


def view(card: dict) -> dict:
    """Поля карточки в виде, удобном редактору."""
    return {"nm_id": card["nmID"], "vendor_code": card.get("vendorCode"), "brand": card.get("brand"), "subject_id": card.get("subjectID"),
            "subject": card.get("subjectName"), "title": card.get("title") or "", "description": card.get("description") or "",
            "characteristics": {str(x["id"]): x.get("value") for x in card.get("characteristics") or []},
            "char_names": {str(x["id"]): x.get("name") for x in card.get("characteristics") or []},
            "dimensions": {k: (card.get("dimensions") or {}).get(k) for k in ("length", "width", "height", "weightBrutto")},
            "media": media_of(card), "price": (card.get("_price") or {}).get("price"), "discount": (card.get("_price") or {}).get("discount"),
            "updated_at": card.get("updatedAt")}



def draft_get(c, shop: int, nm: int) -> dict | None:
    return c.execute("SELECT * FROM card_drafts WHERE account_id=%s AND nm_id=%s AND status='draft' ORDER BY id DESC LIMIT 1",
                     (shop, nm)).fetchone()


def draft_open(c, shop: int, nm: int, uid: int) -> dict:
    d = draft_get(c, shop, nm)
    if d:
        return d
    card = live_card(c, shop, nm)
    return c.execute("""INSERT INTO card_drafts(account_id,nm_id,base,created_by) VALUES (%s,%s,%s,%s) RETURNING *""",
                     (shop, nm, json.dumps(card, ensure_ascii=False), uid)).fetchone()


def _norm(field: str, v):
    if field == "title":
        v = (v or "").strip()
        if len(v) > TITLE_MAX:
            raise actions.ActionDenied(f"Название — не длиннее {TITLE_MAX} знаков (сейчас {len(v)})")
    elif field == "description":
        v = (v or "").strip()
        if len(v) > DESC_MAX:
            raise actions.ActionDenied(f"Описание — не длиннее {DESC_MAX} знаков (сейчас {len(v)})")
    elif field == "characteristics":
        v = {str(k): x for k, x in (v or {}).items()}
    elif field == "dimensions":
        v = {k: (float(v[k]) if k == "weightBrutto" else max(1, int(round(float(v[k]))))) for k in ("length", "width", "height", "weightBrutto")
             if v.get(k) not in (None, "")}
    elif field == "media":
        v = [{"kind": m.get("kind", "photo"), "url": m["url"], "thumb": m.get("thumb")} for m in v or [] if m.get("url")]
        if not any(m["kind"] == "photo" for m in v):
            raise actions.ActionDenied("В карточке должно остаться хотя бы одно фото")
        from .safe_images import image_url
        if len(v) > 30:
            raise actions.ActionDenied("В карточке не больше 30 медиа")
        for m in v:
            if m["kind"] == "photo":
                image_url(m["url"])
                if m["thumb"]:
                    image_url(m["thumb"])
    elif field == "price":
        v = int(round(float(v)))
        if v <= 0:
            raise actions.ActionDenied("Цена должна быть больше нуля")
    elif field == "discount":
        v = int(v)
        if not 0 <= v <= 95:
            raise actions.ActionDenied("Скидка — от 0 до 95 %")
    return v


def draft_set(c, shop: int, nm: int, field: str, value, uid: int, source: str = "manual", note: str | None = None) -> dict:
    """Изменить поле черновика. Значение, равное «было», убирает поле из изменений."""
    if field not in FIELDS:
        raise actions.ActionDenied("Неизвестное поле")
    d = draft_open(c, shop, nm, uid)
    base = view(d["base"])
    ch, src, notes = dict(d["changes"]), dict(d["sources"]), dict(d["ai_notes"])
    if value is None:
        ch.pop(field, None)
    else:
        v = _norm(field, value)
        if field == "characteristics":          
            v = {k: x for k, x in v.items() if x != base["characteristics"].get(k)}
            if not v:
                ch.pop(field, None)
            else:
                ch[field] = v
        elif v == base.get(field) or (field == "media" and [m["url"] for m in v] == [m["url"] for m in base["media"]]):
            ch.pop(field, None)
        else:
            ch[field] = v
    if field in ch:
        src[field] = source
        if note:
            notes[field] = note
    else:
        src.pop(field, None)
        notes.pop(field, None)
    
    return c.execute("""UPDATE card_drafts SET changes=%s, sources=%s, ai_notes=%s, updated_at=now(),
                          review_state=CASE WHEN review_state='pending' THEN NULL ELSE review_state END WHERE id=%s RETURNING *""",
                     (json.dumps(ch, ensure_ascii=False), json.dumps(src), json.dumps(notes, ensure_ascii=False), d["id"])).fetchone()


def rebase(c, shop: int, nm: int) -> dict:
    """Карточку поменяли в кабинете: «было» = актуальная карточка из WB, правки черновика остаются."""
    d = draft_get(c, shop, nm)
    if not d:
        raise actions.ActionDenied("Черновика нет")
    card = live_card(c, shop, nm)
    return c.execute("UPDATE card_drafts SET base=%s, updated_at=now() WHERE id=%s RETURNING *",
                     (json.dumps(card, ensure_ascii=False), d["id"])).fetchone()


def draft_discard(c, shop: int, nm: int):
    c.execute("UPDATE card_drafts SET status='discarded', updated_at=now() WHERE account_id=%s AND nm_id=%s AND status='draft'", (shop, nm))


def diff(d: dict) -> list[dict]:
    """Список изменений «было → стало» для экрана подтверждения."""
    base = view(d["base"])
    out = []
    for f, new in d["changes"].items():
        if f == "characteristics":
            for k, v in new.items():
                out.append({"field": f, "key": k, "title": base["char_names"].get(k) or f"Характеристика {k}",
                            "before": base["characteristics"].get(k), "after": v, "source": d["sources"].get(f)})
        else:
            out.append({"field": f, "title": {"title": "Название", "description": "Описание", "dimensions": "Габариты и вес",
                                               "media": "Фото и видео", "price": "Цена", "discount": "Скидка"}[f],
                        "before": base.get(f), "after": new, "source": d["sources"].get(f), "note": d["ai_notes"].get(f)})
    return out



def save_upload(c, shop: int, nm: int, name: str, raw: bytes, uid: int) -> dict:
    ext = Path(name or "").suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(ext)
    if not mime:
        raise actions.ActionDenied("Фото — JPG, PNG или WEBP")
    if len(raw) > 32 * 1024 * 1024:
        raise actions.ActionDenied("Фото — до 32 МБ")
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    tok = secrets.token_urlsafe(24)
    
    path = MEDIA_DIR.resolve() / f"{tok}{ext}"
    path.write_bytes(raw)
    c.execute("INSERT INTO card_media_uploads(token,account_id,nm_id,path,mime,created_by) VALUES (%s,%s,%s,%s,%s,%s)",
              (tok, shop, nm, str(path), mime, uid))
    url = f"{SITE}/api/public/card_media/{tok}{ext}"
    return {"kind": "photo", "url": url, "thumb": f"/api/public/card_media/{tok}{ext}"}



def _full_card(live: dict, ch: dict) -> dict:
    """Карточка для /content/v2/cards/update целиком: актуальная из WB + изменения черновика."""
    chars = {str(x["id"]): x.get("value") for x in live.get("characteristics") or []}
    for k, v in (ch.get("characteristics") or {}).items():
        if v in (None, "", []):
            chars.pop(k, None)
        else:
            chars[k] = v
    dims = {k: (live.get("dimensions") or {}).get(k) for k in ("length", "width", "height", "weightBrutto")}
    dims.update(ch.get("dimensions") or {})
    return {"nmID": live["nmID"], "vendorCode": live.get("vendorCode"), "brand": live.get("brand") or "",
            "title": ch.get("title", live.get("title") or ""), "description": ch.get("description", live.get("description") or ""),
            
            "dimensions": {k: (round(float(v), 3) if k == "weightBrutto" else max(1, int(round(float(v))))) for k, v in dims.items() if v is not None},
            "characteristics": [{"id": int(k), "value": v} for k, v in chars.items()],
            "sizes": [{k: s.get(k) for k in ("chrtID", "techSize", "wbSize", "skus") if k in s} for s in live.get("sizes") or []]}


def final_price(price, discount) -> float | None:
    if price is None:
        return None
    return round(float(price) * (1 - float(discount or 0) / 100), 2)


def _day_max_final(c, shop: int, nm: int) -> float | None:
    r = c.execute("""SELECT max(price * (1 - coalesce(discount,0) / 100.0)) f FROM prices_snap
                     WHERE account_id=%s AND nm_id=%s AND snap_at > now() - interval '24 hours'""", (shop, nm)).fetchone()
    out = [float(r["f"])] if r and r["f"] is not None else []
    for d in c.execute("""SELECT base FROM card_drafts WHERE account_id=%s AND nm_id=%s AND status IN ('applied','partial')
                          AND applied_at > now() - interval '24 hours'""", (shop, nm)).fetchall():   
        p = d["base"].get("_price") or {}
        f = final_price(p.get("price"), p.get("discount"))
        if f:
            out.append(f)
    return max(out) if out else None


def price_check(d: dict, c=None, *, by_ai: bool = False) -> dict | None:
    """Self-hosted application component."""
    ch = d["changes"]
    if "price" not in ch and "discount" not in ch:
        return None
    b = view(d["base"])
    f0 = final_price(b["price"], b["discount"])
    if c is not None and f0:
        f0 = max(f0, _day_max_final(c, d["account_id"], d["nm_id"]) or 0)
    f1 = final_price(ch.get("price", b["price"]), ch.get("discount", b["discount"]))
    if not f0 or f1 is None or f1 >= f0:
        return None
    ai = by_ai or "ai" in (d["sources"].get("price"), d["sources"].get("discount"))
    drop = 1 - f1 / f0
    lim = AI_PRICE_DROP_MAX if ai else USER_PRICE_DROP_WARN
    
    needs_ack = Decimal(str(f1)) < Decimal(str(f0)) * (1 - Decimal(str(lim)))
    return {"before": f0, "after": f1, "drop": round(drop, 4), "ai": ai, "limit": lim, "needs_ack": needs_ack}


def apply(c, shop: int, nm: int, uid: int, force: bool = False, price_ack: float | None = None, *, by_ai: bool = False) -> dict:
    if by_ai and (force or price_ack is not None):
        raise actions.ActionDenied("Подтверждение изменения цены делает только человек на сайте")
    d = draft_get(c, shop, nm)
    if not d or not d["changes"]:
        raise actions.ActionDenied("В черновике нет изменений")
    why = actions.can_write(c, shop, "cards")
    if why:
        raise actions.ActionDenied(why)
    pc = price_check(d, c, by_ai=by_ai)
    if pc and pc["needs_ack"] and (price_ack is None or abs(float(price_ack) - pc["after"]) > 1):   
        raise actions.ActionDenied(f"PRICE_DROP:Итоговая цена снижается на {pc['drop'] * 100:.0f} % за сутки: {pc['before']:.0f} → {pc['after']:.0f} ₽"
                                   + (" (предложение нейросети: без подтверждения нейросеть не может снижать итоговую цену больше чем на 15 % в сутки)" if pc["ai"] else ""))
    live = live_card(c, shop, nm)
    if live.get("updatedAt") != d["base"].get("updatedAt") and not force:
        raise actions.ActionDenied("CHANGED:Карточку изменили в кабинете WB после начала черновика. Обновите «было» и проверьте изменения "
                                   "(ваши правки сохранятся), или примените поверх.")
    ch = d["changes"]
    res, errs = {}, []
    tgt = f"карточка {nm} ({live.get('vendorCode')})"
    if any(k in ch for k in ("title", "description", "characteristics", "dimensions")):
        card = _full_card(live, ch)
        try:
            actions.wb_write(c, shop, "cards", "POST", "content", "/content/v2/cards/update", [card], uid=uid, target=tgt,
                             before={k: v for k, v in view(live).items() if k in ch}, by_ai=by_ai)
            res["card"] = "ok"
        except actions.ActionDenied as e:
            errs.append(f"Текст и характеристики: {e}")
    if "media" in ch:
        try:
            actions.wb_write(c, shop, "cards", "POST", "content", "/content/v3/media/save", {"nmId": nm, "data": [m["url"] for m in ch["media"]]},
                             uid=uid, target=tgt, before={"media": [m["url"] for m in media_of(live)]}, by_ai=by_ai)
            res["media"] = "ok"
        except actions.ActionDenied as e:
            errs.append(f"Фото и видео: {e}")
    if "price" in ch or "discount" in ch:
        p0 = live.get("_price") or {}
        row = {"nmID": nm, "price": int(ch.get("price", p0.get("price") or 0)), "discount": int(ch.get("discount", p0.get("discount") or 0))}
        try:
            r = actions.wb_write(c, shop, "cards", "POST", "prices", "/api/v2/upload/task", {"data": [row]}, uid=uid, target=tgt, before=p0, by_ai=by_ai)
            res["price"] = {"task": ((r or {}).get("data") or {}).get("id")}
        except actions.ActionDenied as e:
            errs.append(f"Цена: {e}")
    status = "applied" if not errs else ("partial" if res else "error")
    c.execute("""UPDATE card_drafts SET status=%s, result=%s, error=%s, applied_by=%s, applied_at=now(), updated_at=now() WHERE id=%s""",
              (status, json.dumps(res), "\n".join(errs) or None, uid, d["id"]))
    c.commit()
    if res.get("card"):                       
        time.sleep(4)
        e2 = card_errors(c, shop, live.get("vendorCode"), nm)
        if e2:
            errs.append("WB отклонил изменения карточки: " + "; ".join(e2))
            c.execute("UPDATE card_drafts SET status='partial', error=%s WHERE id=%s", ("\n".join(errs), d["id"]))
            c.commit()
    return {"status": status if not errs else ("partial" if res else "error"), "result": res, "errors": errs, "draft_id": d["id"]}


def card_errors(c, shop: int, vendor_code: str | None, nm: int) -> list[str]:
    """Ошибки WB по карточке после /cards/update (несозданные/неотредактированные карточки)."""
    try:
        data = _wb(c, shop).call("content", "/content/v2/cards/error/list", "POST", body={"cursor": {"limit": 100}, "order": {"ascending": False}}) or {}
    except Exception:  
        c.rollback()
        return []
    out = []
    items = (data.get("data") or {}).get("items") if isinstance(data.get("data"), dict) else data.get("data")
    for it in items or []:
        blob = json.dumps(it, ensure_ascii=False)
        if (vendor_code and vendor_code in blob) or str(nm) in blob:
            errs = it.get("errors") or it.get("errorText") or []
            if isinstance(errs, dict):
                errs = [x for v in errs.values() for x in (v if isinstance(v, list) else [v])]
            out += [str(x) for x in (errs if isinstance(errs, list) else [errs])]
    return out[:10]


def rollback(c, shop: int, draft_id: int, uid: int, *, source: str = "manual") -> dict:
    """Откат: новый черновик, где «стало» = «было» применённого черновика (по изменённым полям). Применяет пользователь."""
    d = c.execute("SELECT * FROM card_drafts WHERE id=%s AND account_id=%s AND status IN ('applied','partial')", (draft_id, shop)).fetchone()
    if not d:
        raise actions.ActionDenied("Нечего откатывать")
    draft_discard(c, shop, d["nm_id"])
    base = view(d["base"])
    nd = draft_open(c, shop, d["nm_id"], uid)
    c.execute("UPDATE card_drafts SET rollback_of=%s WHERE id=%s", (draft_id, nd["id"]))
    for f in d["changes"]:
        if f == "characteristics":
            draft_set(c, shop, d["nm_id"], f, {k: base["characteristics"].get(k, []) for k in d["changes"][f]}, uid, source=source)
        else:
            draft_set(c, shop, d["nm_id"], f, base.get(f), uid, source=source)
    return draft_get(c, shop, d["nm_id"])


def history(c, shop: int, nm: int) -> list[dict]:
    return c.execute("""SELECT d.id, d.status, d.changes, d.sources, d.error, d.applied_at, d.rollback_of, coalesce(u.name,u.email) who
                        FROM card_drafts d LEFT JOIN users u ON u.id=d.applied_by
                        WHERE d.account_id=%s AND d.nm_id=%s AND d.status IN ('applied','partial','error') ORDER BY d.id DESC LIMIT 20""",
                     (shop, nm)).fetchall()

"""Блок «Отзывы» (WB): правила ответов, черновики и авто-ответы ИИ, ручные ответы, журнал с комментариями сотрудников, негатив для сводки.

Положительные — 5★, отрицательные — 4★ и ниже; у каждой группы свой режим (actions.MODES).
ИИ перед ответом видит: правила магазина и товара, карточку товара, последние отзывы и ответы по товару, пометки сотрудников.
Имя покупателя берём из WB только в момент черновика (GET /api/v1/feedback) и в базе не храним.
"""

import json
import threading
from datetime import datetime, timedelta, timezone

from . import actions, reco

TONES = {
    "friendly": "Дружелюбно и тепло",
    "dry": "Точно и сухо, по делу",
    "name": "Обращаться по имени",
    "deep": "Вникать в суть: отвечать на конкретные моменты отзыва",
    "short": "Коротко: 1-3 предложения",
    "formal": "Официально, на «Вы»",
    "thanks": "Благодарить за фото и подробный отзыв",
    "cross": "Советовать товары нашего магазина по смыслу (не чаще настройки «каждый N-й ответ», один товар)",
    
    "emoji": "Смайлики по смыслу: 1-2 уместных эмодзи на ответ; в ответ на негатив - только сочувствующие, без весёлых",
}
SYSTEM = ("Ты пишешь ответ продавца на отзыв покупателя на маркетплейсе (Wildberries или Ozon). Пиши по-русски, от лица магазина, живым человеческим языком, "
          "без шаблонных канцелярских фраз и без markdown. ГЛАВНОЕ: не выдумывай факты. Любое утверждение о товаре, составе, упаковке, "
          "доставке, сроках, гарантии - только если оно прямо есть в карточке, правилах или пометках сотрудников; если данных нет - "
          "не утверждай, говори общими словами (например, «передадим команде»). Пометки сотрудников важнее всего остального. Не обещай компенсаций, возвратов денег и подарков, если этого нет в правилах. Не упоминай, что ты нейросеть. "
          "Не используй длинное тире: только дефис «-». Эмодзи - только если это есть в правилах ответов. Не используй ссылки, телефоны, e-mail и призывы связаться вне маркетплейса. "
          "Длина ответа - до 900 знаков. Верни ТОЛЬКО текст ответа.")
_BUSY: set = set()
_LOCK = threading.Lock()


def mp(c, shop: int) -> str:
    return c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]


def is_neg(v) -> bool:
    return v is not None and v <= 4


def mode_for(settings: dict, valuation) -> str:
    return settings["neg_mode" if is_neg(valuation) else "pos_mode"]



def rules(c, shop: int, nm: int = 0) -> dict:
    r = c.execute("SELECT tones, text, updated_at FROM review_rules WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    return {"nm_id": nm, "tones": (r or {}).get("tones") or ([] if nm else ["friendly", "deep"]), "text": (r or {}).get("text") or "",
            "updated_at": (r or {}).get("updated_at")}


def save_rules(c, shop: int, nm: int, tones: list, text: str, uid: int):
    tones = [t for t in tones if t in TONES]
    c.execute("""INSERT INTO review_rules(account_id,nm_id,tones,text,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,now())
                 ON CONFLICT (account_id,nm_id) DO UPDATE SET tones=EXCLUDED.tones, text=EXCLUDED.text, updated_by=EXCLUDED.updated_by,
                   updated_at=now()""", (shop, nm, json.dumps(tones), (text or "")[:4000], uid))



def rating_now(c, shop: int, nm) -> float | None:
    if mp(c, shop) == "ozon":     
        r = c.execute("SELECT avg(valuation) a FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s AND coalesce(in_rating,true)",
                      (shop, nm)).fetchone()
        return round(float(r["a"]), 2) if r and r["a"] is not None else None
    r = c.execute("""SELECT (data->>'feedbackRating')::numeric r FROM raw_rows WHERE account_id=%s AND source='funnel_day'
                     AND (data->>'nmId')::bigint=%s AND data->>'feedbackRating' IS NOT NULL ORDER BY row_date DESC LIMIT 1""",
                  (shop, nm)).fetchone()
    return float(r["r"]) if r and r["r"] is not None else None


def rating_drop(c, shop: int, f: dict) -> dict | None:
    """Рейтинг товара упал после негативного отзыва: {before, after}."""
    if not is_neg(f.get("valuation")) or f.get("rating_before") is None:
        return None
    now = rating_now(c, shop, f["nm_id"])
    b = round(float(f["rating_before"]), 1)        
    if now is not None and round(now, 1) < b:
        return {"before": b, "after": round(now, 1)}
    return None



def _card(c, shop: int, nm) -> str:
    if mp(c, shop) == "ozon":
        o = c.execute("SELECT offer_id, name, raw FROM oz_products WHERE account_id=%s AND sku=%s", (shop, nm)).fetchone()
        if not o:
            return ""
        raw = o["raw"] or {}
        attrs = "; ".join(f"{k}: {raw[k]}" for k in ("description_category_id", "volume_weight", "barcodes") if raw.get(k))
        return f"Товар: {o['name'] or ''}, артикул продавца {o['offer_id'] or '-'}, SKU Ozon {nm}." + (f"\nДанные: {attrs[:800]}" if attrs else "")
    r = c.execute("SELECT title, subject, brand, vendor_code, data FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    if not r:
        return ""
    d = r["data"] or {}
    ch = "; ".join(f"{x.get('name')}: {', '.join(map(str, x['value'])) if isinstance(x.get('value'), list) else x.get('value')}"
                   for x in d.get("characteristics") or [] if x.get("value") not in (None, "", []))
    desc = (d.get("description") or "")[:1500]
    return (f"Товар: {r['title'] or ''} ({r['subject'] or ''}), бренд {r['brand'] or '-'}, артикул продавца {r['vendor_code'] or '-'}, "
            f"артикул WB {nm}.\nХарактеристики: {ch[:1500]}\nОписание: {desc}")


def context(c, shop: int, f: dict) -> str:
    nm = f["nm_id"]
    shop_r, nm_r = rules(c, shop, 0), rules(c, shop, nm)
    tones = [TONES[t] for t in dict.fromkeys(shop_r["tones"] + nm_r["tones"]) if t in TONES]
    parts = ["ПРАВИЛА ОТВЕТОВ МАГАЗИНА:", "\n".join(f"- {t}" for t in tones) or "- (не заданы)"]
    if shop_r["text"]:
        parts.append(shop_r["text"])
    if nm_r["text"]:
        parts += ["Правила именно для этого товара:", nm_r["text"]]
    notes = c.execute("""SELECT r.text, r.comment, w.text fb, w.valuation, r.nm_id FROM review_answers r
                         LEFT JOIN wb_feedbacks w ON w.account_id=r.account_id AND w.id=r.feedback_id
                         WHERE r.account_id=%s AND r.comment IS NOT NULL AND r.comment<>''
                         ORDER BY (r.nm_id=%s) DESC, r.comment_at DESC LIMIT 15""", (shop, nm)).fetchall()
    if notes:
        parts.append("\nПОМЕТКИ СОТРУДНИКОВ К ПРОШЛЫМ ОТВЕТАМ (это исправления - обязательно учитывай, не повторяй ошибок):")
        for n in notes:
            parts.append(f"- {'этот товар' if n['nm_id'] == nm else 'другой товар'}; ответ был: «{(n['text'] or '')[:300]}»; "
                         f"пометка: {n['comment'][:500]}")
    card = _card(c, shop, nm)
    if card:
        parts += ["\nКАРТОЧКА ТОВАРА:", card]
    past = c.execute("""SELECT valuation, text, pros, cons, answer_text FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s AND id<>%s
                        AND coalesce(answer_text,'') <> '' ORDER BY created_at DESC LIMIT 12""", (shop, nm, f["id"])).fetchall()
    if past:
        parts.append("\nПРОШЛЫЕ ОТЗЫВЫ И ОТВЕТЫ МАГАЗИНА ПО ЭТОМУ ТОВАРУ (стиль и факты):")
        for p in past:
            body = " ".join(x for x in (p["text"], p["pros"] and f"Достоинства: {p['pros']}", p["cons"] and f"Недостатки: {p['cons']}") if x)
            parts.append(f"- {p['valuation']}★ «{body[:300]}» → ответ: «{p['answer_text'][:300]}»")
    neg = c.execute("""SELECT count(*) n, count(*) FILTER (WHERE valuation<=4) neg, round(avg(valuation)::numeric,2) avg
                       FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s""", (shop, nm)).fetchone()
    parts.append(f"\nВсего отзывов по товару: {neg['n']}, из них на 4★ и ниже: {neg['neg']}, средняя оценка {neg['avg']}.")
    return "\n".join(parts)


def _fb_text(f: dict, name: str | None) -> str:
    lines = [f"ОТЗЫВ ПОКУПАТЕЛЯ ({f['valuation']}★):"]
    if name:
        lines.append(f"Имя покупателя: {name}")
    for k, t in (("text", "Комментарий"), ("pros", "Достоинства"), ("cons", "Недостатки")):
        if f.get(k):
            lines.append(f"{t}: {f[k]}")
    if f.get("bables"):
        lines.append("Отмеченные теги: " + ", ".join(f["bables"]))
    if f.get("matching_size") and f["matching_size"] not in ("ok", ""):
        lines.append(f"Размер: {f['matching_size']}")
    if f.get("photos"):
        lines.append(f"Покупатель приложил фото: {f['photos']} шт.")
    if f.get("order_status"):
        lines.append(f"Статус заказа: {f['order_status']}")
    return "\n".join(lines)


def _buyer_name(c, shop: int, fid: str) -> str | None:
    """Имя покупателя — только в момент ответа, из WB (в базу не пишем). Ozon имя в API не отдаёт."""
    from .wb import WB
    if mp(c, shop) == "ozon":
        return None
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone()
    try:
        d = (WB(c, acc).call("feedbacks", "/api/v1/feedback", params={"id": fid}) or {}).get("data") or {}
        n = (d.get("userName") or "").strip()
        return n if n and n.lower() not in ("покупатель", "пользователь") else None
    except Exception:  
        c.rollback()
        return None


def ai_draft(c, shop: int, fid: str, uid: int | None) -> dict:
    """Черновик ИИ: прежние черновики этого отзыва — в «discarded», новый — draft."""
    from . import aireport, assistant
    acc = assistant.access(c, shop, uid)
    if not acc.get("ok"):
        raise actions.ActionDenied(acc.get("reason") or "Нет доступа к нейросети")
    f = c.execute("SELECT * FROM wb_feedbacks WHERE account_id=%s AND id=%s", (shop, fid)).fetchone()
    if not f:
        raise actions.ActionDenied("Отзыв не найден")
    st = actions.block(c, shop, "reviews")["settings"]
    name = _buyer_name(c, shop, fid) if st.get("use_name") and "name" in rules(c, shop, 0)["tones"] + rules(c, shop, f["nm_id"])["tones"] else None
    prompt = context(c, shop, f) + "\n\n" + _fb_text(f, name)
    rec = _reco(c, shop, f, st, acc["key"])
    if rec:
        prompt += reco.prompt_block(rec, is_neg(f["valuation"]))
    prompt += "\n\nНапиши ответ магазина на этот отзыв."
    text = aireport.complete(acc["key"], SYSTEM, prompt, max_tokens=700).strip().strip("«»\"")
    if len(text) < 2:
        raise actions.ActionDenied("Нейросеть вернула пустой ответ — попробуйте ещё раз")
    c.execute("UPDATE review_answers SET status='discarded' WHERE account_id=%s AND feedback_id=%s AND status='draft'", (shop, fid))
    r = c.execute("""INSERT INTO review_answers(account_id,feedback_id,nm_id,text,source,status,created_by,reco_nm)
                     VALUES (%s,%s,%s,%s,'ai','draft',%s,%s) RETURNING id""",
                  (shop, fid, f["nm_id"], text[:5000], uid, reco.used(text, rec) if rec else None)).fetchone()
    c.commit()
    return {"id": r["id"], "text": text}


def _reco(c, shop: int, f: dict, st: dict, key: str) -> list[dict]:
    """Что можно посоветовать в этом ответе: тон «советовать товары» включён (магазин или товар), очередь «каждый N-й»;
    на 5★ — дополняющие и замены, на негатив — только замена и только если включено «предлагать замену при негативе»."""
    if "cross" not in rules(c, shop, 0)["tones"] + rules(c, shop, f["nm_id"])["tones"] or not f["nm_id"]:
        return []
    neg = is_neg(f["valuation"])
    if neg and not st.get("reco_neg_alt"):
        return []
    if not reco.due(c, shop, "review_answers", int(st.get("reco_every") or 3)):
        return []
    return reco.pick(c, shop, f["nm_id"], key, allow_alt_only=neg)


def draft_async(shop: int, fid: str, uid: int | None) -> bool:
    """Черновик в фоне (Claude Code — до минуты); False — уже пишется."""
    from . import db
    k = (shop, fid)
    with _LOCK:
        if k in _BUSY:
            return False
        _BUSY.add(k)

    def run():
        try:
            with db.connect() as c2:
                try:
                    ai_draft(c2, shop, fid, uid)
                except Exception as e:  
                    c2.rollback()
                    c2.execute("""INSERT INTO review_answers(account_id,feedback_id,text,source,status,created_by,error)
                                  VALUES (%s,%s,'-','ai','error',%s,%s)""", (shop, fid, uid, str(e)[:300]))
                    c2.commit()
        finally:
            with _LOCK:
                _BUSY.discard(k)
    threading.Thread(target=run, daemon=True).start()
    return True


def busy(shop: int, fid: str) -> bool:
    return (shop, fid) in _BUSY


def send(c, shop: int, fid: str, text: str, uid: int | None, answer_id: int | None = None, auto: bool = False) -> dict:
    """Отправить ответ в WB (через actions.wb_write — все проверки там) и записать в журнал ответов."""
    text = (text or "").strip()
    if not 2 <= len(text) <= 5000:
        raise actions.ActionDenied("Ответ — от 2 до 5000 знаков")
    f = c.execute("SELECT * FROM wb_feedbacks WHERE account_id=%s AND id=%s", (shop, fid)).fetchone()
    if not f:
        raise actions.ActionDenied("Отзыв не найден")
    st = actions.block(c, shop, "reviews")["settings"]
    mode = mode_for(st, f["valuation"])
    if mode == "off":
        raise actions.ActionDenied(f"Ответы на {'отзывы 4★ и ниже' if is_neg(f['valuation']) else 'отзывы 5★'} выключены в настройках")
    edit = bool(f["answer_text"])
    oz = mp(c, shop) == "ozon"
    if edit and oz:
        raise actions.ActionDenied("У Ozon ответ на отзыв не редактируется — удалите прежний комментарий в кабинете Ozon и ответьте заново")
    if edit and not f["answer_editable"]:
        raise actions.ActionDenied("WB не даёт изменить этот ответ (редактировать можно один раз в течение 60 дней)")
    src = "manual"
    if answer_id:
        a = c.execute("SELECT * FROM review_answers WHERE id=%s AND account_id=%s AND feedback_id=%s", (answer_id, shop, fid)).fetchone()
        if a and a["source"] == "ai" and a["text"].strip() == text:
            src = "ai"                                  
    try:
        tgt = f"отзыв {fid} (арт. {f['nm_id']}, {f['valuation']}★)"
        if oz:
            actions.oz_write(c, shop, "reviews", "/v1/review/comment/create",
                             {"review_id": fid, "text": text, "mark_review_as_processed": True}, uid=uid, by_ai=auto, target=tgt)
        else:
            actions.wb_write(c, shop, "reviews", "PATCH" if edit else "POST", "feedbacks", "/api/v1/feedbacks/answer", {"id": fid, "text": text},
                             uid=uid, by_ai=auto, target=tgt, before={"answer": f["answer_text"]} if edit else None)
    except actions.ActionDenied as e:
        c.execute("""INSERT INTO review_answers(account_id,feedback_id,nm_id,text,source,status,auto,created_by,error)
                     VALUES (%s,%s,%s,%s,%s,'error',%s,%s,%s)""", (shop, fid, f["nm_id"], text, src, auto, uid, str(e)[:300]))
        c.commit()
        raise
    if answer_id and src == "ai":
        c.execute("UPDATE review_answers SET status='sent', sent_by=%s, sent_at=now(), auto=%s WHERE id=%s", (uid, auto, answer_id))
        aid = answer_id
    else:
        if answer_id:
            c.execute("UPDATE review_answers SET status='discarded' WHERE id=%s AND status='draft'", (answer_id,))
        aid = c.execute("""INSERT INTO review_answers(account_id,feedback_id,nm_id,text,source,status,auto,created_by,sent_by,sent_at)
                           VALUES (%s,%s,%s,%s,%s,'sent',%s,%s,%s,now()) RETURNING id""",
                        (shop, fid, f["nm_id"], text, src, auto, uid, uid)).fetchone()["id"]
    c.execute("UPDATE review_answers SET status='discarded' WHERE account_id=%s AND feedback_id=%s AND status='draft'", (shop, fid))
    c.execute("""UPDATE wb_feedbacks SET answer_text=%s, answered=true, answer_editable=%s, updated_at=now()
                 WHERE account_id=%s AND id=%s""", (text, not edit and not oz, shop, fid))
    c.commit()
    return {"ok": True, "answer_id": aid, "edited": edit}


def comment(c, shop: int, aid: int, text: str, uid: int):
    c.execute("UPDATE review_answers SET comment=%s, comment_by=%s, comment_at=now() WHERE id=%s AND account_id=%s",
              ((text or "").strip()[:2000] or None, uid, aid, shop))



MAX_PER_RUN = 5


def process(c, shop: int) -> dict:
    """Self-hosted application component."""
    from . import assistant
    b = actions.block(c, shop, "reviews")
    if actions.paused(c, shop):
        return {"skipped": "взаимодействия остановлены"}
    st = b["settings"]
    if not any(st[k] in actions.AI_MODES for k in ("pos_mode", "neg_mode")):
        return {"skipped": "без ИИ"}
    if not assistant.access(c, shop).get("ok"):
        return {"skipped": "нет нейросети"}
    todo = c.execute("""SELECT w.* FROM wb_feedbacks w WHERE w.account_id=%s AND NOT w.answered AND w.created_at > now() - interval '30 days'
                        AND NOT EXISTS (SELECT 1 FROM review_answers r WHERE r.account_id=w.account_id AND r.feedback_id=w.id
                                        AND r.status IN ('draft','sent','error'))
                        ORDER BY w.created_at DESC LIMIT 60""", (shop,)).fetchall()
    sent_today = c.execute("""SELECT count(*) n FROM review_answers WHERE account_id=%s AND auto AND status='sent'
                              AND sent_at >= (now() AT TIME ZONE 'Europe/Moscow')::date AT TIME ZONE 'Europe/Moscow'""", (shop,)).fetchone()["n"]
    out = {"drafts": 0, "sent": 0, "errors": 0}
    for f in todo:
        if out["drafts"] + out["sent"] + out["errors"] >= MAX_PER_RUN:
            break
        mode = mode_for(st, f["valuation"])
        if mode not in actions.AI_MODES:
            continue
        since = st.get(("neg_mode" if is_neg(f["valuation"]) else "pos_mode") + "_since")
        auto = mode == "auto" and since and f["created_at"] > datetime.fromisoformat(since) and sent_today < int(st.get("auto_limit") or 0)\
            and not actions.can_write(c, shop, "reviews")
        try:
            d = ai_draft(c, shop, f["id"], None)
            out["drafts"] += 1
            if auto:
                send(c, shop, f["id"], d["text"], None, answer_id=d["id"], auto=True)
                sent_today += 1
                out["sent"] += 1
        except Exception as e:  
            c.rollback()
            out["errors"] += 1
            c.execute("""INSERT INTO review_answers(account_id,feedback_id,nm_id,text,source,status,error)
                         VALUES (%s,%s,%s,'-','ai','error',%s)""", (shop, f["id"], f["nm_id"], str(e)[:300]))
            c.commit()
    return out



def negatives(c, shop: int, d_from, d_to) -> list[dict]:
    rows = c.execute("""SELECT * FROM wb_feedbacks WHERE account_id=%s AND valuation<=4
                        AND (created_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s ORDER BY valuation, created_at DESC""",
                     (shop, d_from, d_to)).fetchall()
    for r in rows:
        r["drop"] = rating_drop(c, shop, r)
    return rows


def summary_lines(c, shop: int, day, nms: list[int] | None = None) -> str | None:
    """Блок ежедневной сводки: негативные отзывы за день по товарам, 🔻 — рейтинг товара упал. None — отзывы не собираются."""
    if not c.execute("""SELECT 1 FROM collector_state WHERE account_id=%s AND collector IN ('feedbacks','oz_reviews') AND last_ok_at IS NOT NULL
                         AND NOT coalesce((cursor->>'no_subscription')::boolean, false)""", (shop,)).fetchone():
        return None
    if not actions.block(c, shop, "reviews")["settings"].get("notify_neg", True):
        return None
    neg = negatives(c, shop, day, day)
    if nms is not None:                         
        neg = [r for r in neg if r["nm_id"] in set(nms)]
    if not neg:
        return "⭐ Негативных отзывов (4★ и ниже) за день нет."
    by: dict = {}
    for r in neg:
        by.setdefault((r["nm_id"], r["vendor_code"]), []).append(r)
    lines = [f"⭐ Негативные отзывы за день: {len(neg)}"]
    for (nm, vc), rs in list(by.items())[:10]:
        drop = next((r["drop"] for r in rs if r["drop"]), None)
        stars = ", ".join(f"{r['valuation']}★" for r in rs)
        head = f"• {vc or nm} ({nm}): {stars}"
        if drop:
            head += f" 🔻 рейтинг {drop['before']:.1f} → {drop['after']:.1f}"
        lines.append(head)
        for r in rs[:2]:
            t = " ".join(x for x in (r["text"], r["cons"]) if x).strip()
            if t:
                lines.append(f"   «{t[:160]}{'…' if len(t) > 160 else ''}»")
    if len(by) > 10:
        lines.append(f"…и ещё {len(by) - 10} товаров — на сайте, раздел «Отзывы»")
    return "\n".join(lines)


def answered_recently(c, shop: int, hours: int = 24) -> int:
    t = datetime.now(timezone.utc) - timedelta(hours=hours)
    return c.execute("SELECT count(*) n FROM review_answers WHERE account_id=%s AND status='sent' AND sent_at>=%s", (shop, t)).fetchone()["n"]

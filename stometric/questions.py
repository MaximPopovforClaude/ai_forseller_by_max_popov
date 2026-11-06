"""Блок «Вопросы» (WB): ответы на вопросы покупателей о товарах — правила, черновики и авто-ответы ИИ, ручные ответы,
журнал с пометками сотрудников. По образцу reviews.py; оценки у вопроса нет — один режим блока (settings.mode).

ИИ перед ответом видит: правила магазина и товара, карточку товара (характеристики, описание), прошлые вопросы и ответы по товару,
пометки сотрудников. Отвечает только фактами оттуда; данных нет — честно говорит, что уточним (не выдумывает).
"""

import json
import threading
from datetime import datetime

from . import actions, reco
from .reviews import TONES, _card

SYSTEM = ("Ты пишешь ответ продавца на вопрос покупателя о товаре на Wildberries. Пиши по-русски, от лица магазина, живым человеческим "
          "языком, без шаблонных канцелярских фраз и без markdown. ГЛАВНОЕ: не выдумывай. Отвечай только фактами, которые прямо есть "
          "в карточке товара (характеристики, описание), в правилах ответов или в пометках сотрудников; можно опираться на прошлые ответы "
          "магазина по этому товару. Если точного ответа в этих данных нет - честно скажи, что уточним информацию, или предложи посмотреть "
          "нужный раздел карточки; не угадывай размеры, состав, совместимость, сроки, наличие и цены. Пометки сотрудников важнее всего "
          "остального. Не обещай скидок, подарков и компенсаций, если этого нет в правилах. Не упоминай, что ты нейросеть. "
          "Не используй длинное тире: только дефис «-». Эмодзи - только если это есть в правилах ответов. Не используй ссылки, телефоны, "
          "e-mail и призывы связаться вне маркетплейса. Длина ответа - до 900 знаков. Верни ТОЛЬКО текст ответа.")

TONES_Q = {k: v for k, v in TONES.items() if k not in ("name", "thanks")}
TONES_Q["deep"] = "Вникать в суть: отвечать именно на то, что спросили"
TONES_Q["emoji"] = "Смайлики по смыслу: 1-2 уместных эмодзи на ответ"
_BUSY: set = set()
_LOCK = threading.Lock()



def rules(c, shop: int, nm: int = 0) -> dict:
    r = c.execute("SELECT tones, text, updated_at FROM question_rules WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    return {"nm_id": nm, "tones": (r or {}).get("tones") or ([] if nm else ["friendly", "deep"]), "text": (r or {}).get("text") or "",
            "updated_at": (r or {}).get("updated_at")}


def save_rules(c, shop: int, nm: int, tones: list, text: str, uid: int):
    tones = [t for t in tones if t in TONES_Q]
    c.execute("""INSERT INTO question_rules(account_id,nm_id,tones,text,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,now())
                 ON CONFLICT (account_id,nm_id) DO UPDATE SET tones=EXCLUDED.tones, text=EXCLUDED.text, updated_by=EXCLUDED.updated_by,
                   updated_at=now()""", (shop, nm, json.dumps(tones), (text or "")[:4000], uid))



def context(c, shop: int, q: dict) -> str:
    nm = q["nm_id"]
    shop_r, nm_r = rules(c, shop, 0), rules(c, shop, nm)
    tones = [TONES_Q[t] for t in dict.fromkeys(shop_r["tones"] + nm_r["tones"]) if t in TONES_Q]
    parts = ["ПРАВИЛА ОТВЕТОВ МАГАЗИНА:", "\n".join(f"- {t}" for t in tones) or "- (не заданы)"]
    if shop_r["text"]:
        parts.append(shop_r["text"])
    if nm_r["text"]:
        parts += ["Правила именно для этого товара:", nm_r["text"]]
    notes = c.execute("""SELECT a.text, a.comment, a.nm_id FROM question_answers a
                         WHERE a.account_id=%s AND a.comment IS NOT NULL AND a.comment<>''
                         ORDER BY (a.nm_id=%s) DESC, a.comment_at DESC LIMIT 15""", (shop, nm)).fetchall()
    if notes:
        parts.append("\nПОМЕТКИ СОТРУДНИКОВ К ПРОШЛЫМ ОТВЕТАМ (это исправления и факты - обязательно учитывай, не повторяй ошибок):")
        for n in notes:
            parts.append(f"- {'этот товар' if n['nm_id'] == nm else 'другой товар'}; ответ был: «{(n['text'] or '')[:300]}»; "
                         f"пометка: {n['comment'][:500]}")
    card = _card(c, shop, nm)
    if card:
        parts += ["\nКАРТОЧКА ТОВАРА:", card]
    else:
        parts.append("\nКАРТОЧКА ТОВАРА: нет данных.")
    past = c.execute("""SELECT text, answer_text FROM wb_questions WHERE account_id=%s AND nm_id=%s AND id<>%s
                        AND coalesce(answer_text,'') <> '' ORDER BY created_at DESC LIMIT 15""", (shop, nm, q["id"])).fetchall()
    if past:
        parts.append("\nПРОШЛЫЕ ВОПРОСЫ И ОТВЕТЫ МАГАЗИНА ПО ЭТОМУ ТОВАРУ (стиль и факты):")
        for p in past:
            parts.append(f"- «{(p['text'] or '')[:300]}» → ответ: «{p['answer_text'][:300]}»")
    return "\n".join(parts)


def ai_draft(c, shop: int, qid: str, uid: int | None) -> dict:
    """Черновик ИИ: прежние черновики этого вопроса — в «discarded», новый — draft."""
    from . import aireport, assistant
    acc = assistant.access(c, shop, uid)
    if not acc.get("ok"):
        raise actions.ActionDenied(acc.get("reason") or "Нет доступа к нейросети")
    q = c.execute("SELECT * FROM wb_questions WHERE account_id=%s AND id=%s", (shop, qid)).fetchone()
    if not q:
        raise actions.ActionDenied("Вопрос не найден")
    prompt = context(c, shop, q) + f"\n\nВОПРОС ПОКУПАТЕЛЯ:\n{q['text'] or ''}"
    rec = []
    st = actions.block(c, shop, "questions")["settings"]
    if q["nm_id"] and "cross" in rules(c, shop, 0)["tones"] + rules(c, shop, q["nm_id"])["tones"]\
            and reco.due(c, shop, "question_answers", int(st.get("reco_every") or 3)):
        rec = reco.pick(c, shop, q["nm_id"], acc["key"])
        if rec:
            prompt += reco.prompt_block(rec, False)
    prompt += "\n\nНапиши ответ магазина на этот вопрос."
    text = aireport.complete(acc["key"], SYSTEM, prompt, max_tokens=700).strip().strip("«»\"")
    if len(text) < 2:
        raise actions.ActionDenied("Нейросеть вернула пустой ответ — попробуйте ещё раз")
    c.execute("UPDATE question_answers SET status='discarded' WHERE account_id=%s AND question_id=%s AND status='draft'", (shop, qid))
    r = c.execute("""INSERT INTO question_answers(account_id,question_id,nm_id,text,source,status,created_by,reco_nm)
                     VALUES (%s,%s,%s,%s,'ai','draft',%s,%s) RETURNING id""",
                  (shop, qid, q["nm_id"], text[:5000], uid, reco.used(text, rec) if rec else None)).fetchone()
    c.commit()
    return {"id": r["id"], "text": text}


def draft_async(shop: int, qid: str, uid: int | None) -> bool:
    """Черновик в фоне; False — уже пишется."""
    from . import db
    k = (shop, qid)
    with _LOCK:
        if k in _BUSY:
            return False
        _BUSY.add(k)

    def run():
        try:
            with db.connect() as c2:
                try:
                    ai_draft(c2, shop, qid, uid)
                except Exception as e:  
                    c2.rollback()
                    c2.execute("""INSERT INTO question_answers(account_id,question_id,text,source,status,created_by,error)
                                  VALUES (%s,%s,'-','ai','error',%s,%s)""", (shop, qid, uid, str(e)[:300]))
                    c2.commit()
        finally:
            with _LOCK:
                _BUSY.discard(k)
    threading.Thread(target=run, daemon=True).start()
    return True


def busy(shop: int, qid: str) -> bool:
    return (shop, qid) in _BUSY


def send(c, shop: int, qid: str, text: str, uid: int | None, answer_id: int | None = None, auto: bool = False) -> dict:
    """Отправить ответ в WB (через actions.wb_write — все проверки там) и записать в журнал ответов."""
    text = (text or "").strip()
    if not 2 <= len(text) <= 5000:
        raise actions.ActionDenied("Ответ — от 2 до 5000 знаков")
    q = c.execute("SELECT * FROM wb_questions WHERE account_id=%s AND id=%s", (shop, qid)).fetchone()
    if not q:
        raise actions.ActionDenied("Вопрос не найден")
    if actions.block(c, shop, "questions")["settings"].get("mode") == "off":
        raise actions.ActionDenied("Ответы на вопросы выключены в настройках")
    edit = bool(q["answer_text"])
    if edit and not q["answer_editable"]:
        raise actions.ActionDenied("WB не даёт изменить этот ответ (редактировать можно один раз в течение 60 дней)")
    src = "manual"
    if answer_id:
        a = c.execute("SELECT * FROM question_answers WHERE id=%s AND account_id=%s AND question_id=%s", (answer_id, shop, qid)).fetchone()
        if a and a["source"] == "ai" and a["text"].strip() == text:
            src = "ai"                                  
    try:
        actions.wb_write(c, shop, "questions", "PATCH", "feedbacks", "/api/v1/questions",
                         {"id": qid, "answer": {"text": text}, "state": "wbRu"}, uid=uid, by_ai=auto,
                         target=f"вопрос {qid} (арт. {q['nm_id']})", before={"answer": q["answer_text"]} if edit else None)
    except actions.ActionDenied as e:
        c.execute("""INSERT INTO question_answers(account_id,question_id,nm_id,text,source,status,auto,created_by,error)
                     VALUES (%s,%s,%s,%s,%s,'error',%s,%s,%s)""", (shop, qid, q["nm_id"], text, src, auto, uid, str(e)[:300]))
        c.commit()
        raise
    if answer_id and src == "ai":
        c.execute("UPDATE question_answers SET status='sent', sent_by=%s, sent_at=now(), auto=%s WHERE id=%s", (uid, auto, answer_id))
        aid = answer_id
    else:
        if answer_id:
            c.execute("UPDATE question_answers SET status='discarded' WHERE id=%s AND status='draft'", (answer_id,))
        aid = c.execute("""INSERT INTO question_answers(account_id,question_id,nm_id,text,source,status,auto,created_by,sent_by,sent_at)
                           VALUES (%s,%s,%s,%s,%s,'sent',%s,%s,%s,now()) RETURNING id""",
                        (shop, qid, q["nm_id"], text, src, auto, uid, uid)).fetchone()["id"]
    c.execute("UPDATE question_answers SET status='discarded' WHERE account_id=%s AND question_id=%s AND status='draft'", (shop, qid))
    c.execute("""UPDATE wb_questions SET answer_text=%s, answered=true, answer_editable=%s, state='wbRu', updated_at=now()
                 WHERE account_id=%s AND id=%s""", (text, not edit, shop, qid))
    c.commit()
    return {"ok": True, "answer_id": aid, "edited": edit}


def comment(c, shop: int, aid: int, text: str, uid: int):
    c.execute("UPDATE question_answers SET comment=%s, comment_by=%s, comment_at=now() WHERE id=%s AND account_id=%s",
              ((text or "").strip()[:2000] or None, uid, aid, shop))



MAX_PER_RUN = 5


def process(c, shop: int) -> dict:
    """Новые неотвеченные вопросы: режим «черновик» — черновик ИИ, «авто» — пишем и сразу отправляем (лимит в сутки).
    Авто — только по вопросам, пришедшим после включения авто-режима. Черновики — и без включённого блока и ключа на запись;
    отправка — только через actions.can_write (блок включён + ключ на запись)."""
    from . import assistant
    b = actions.block(c, shop, "questions")
    if actions.paused(c, shop):
        return {"skipped": "взаимодействия остановлены"}
    st = b["settings"]
    mode = st.get("mode")
    if mode not in actions.AI_MODES:
        return {"skipped": "без ИИ"}
    if not assistant.access(c, shop).get("ok"):
        return {"skipped": "нет нейросети"}
    todo = c.execute("""SELECT w.* FROM wb_questions w WHERE w.account_id=%s AND NOT w.answered AND w.created_at > now() - interval '30 days'
                        AND NOT EXISTS (SELECT 1 FROM question_answers r WHERE r.account_id=w.account_id AND r.question_id=w.id
                                        AND r.status IN ('draft','sent','error'))
                        ORDER BY w.created_at DESC LIMIT %s""", (shop, MAX_PER_RUN)).fetchall()
    sent_today = c.execute("""SELECT count(*) n FROM question_answers WHERE account_id=%s AND auto AND status='sent'
                              AND sent_at >= (now() AT TIME ZONE 'Europe/Moscow')::date AT TIME ZONE 'Europe/Moscow'""", (shop,)).fetchone()["n"]
    since = st.get("mode_since")
    out = {"drafts": 0, "sent": 0, "errors": 0}
    for q in todo:
        auto = mode == "auto" and since and q["created_at"] > datetime.fromisoformat(since) and sent_today < int(st.get("auto_limit") or 0)\
            and not actions.can_write(c, shop, "questions")
        try:
            d = ai_draft(c, shop, q["id"], None)
            out["drafts"] += 1
            if auto:
                send(c, shop, q["id"], d["text"], None, answer_id=d["id"], auto=True)
                sent_today += 1
                out["sent"] += 1
        except Exception as e:  
            c.rollback()
            out["errors"] += 1
            c.execute("""INSERT INTO question_answers(account_id,question_id,nm_id,text,source,status,error)
                         VALUES (%s,%s,%s,'-','ai','error',%s)""", (shop, q["id"], q["nm_id"], str(e)[:300]))
            c.commit()
    return out

"""Предложения нейросети по карточке WB (этап 2 блока «Карточки»): ИИ только предлагает — правки ложатся в черновик с пометкой «✨ ИИ»
и пояснением; применяет пользователь. Цену ИИ здесь не меняет (отдельный блок «Цены» с лимитом снижения).

Что видит нейросеть: карточку, справочник характеристик предмета, поисковые запросы артикула за 14 дней (частота, позиция, переходы,
заказы), рекламные кластеры с заказами, отзывы (что хвалят / за что ругают), правила магазина для карточек, сами фото (порядок слайдов).
"""

import json
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from . import actions, cards
from .config import today_msk

SCOPES = {"title": "название", "description": "описание", "characteristics": "характеристики", "media": "порядок фото", "all": "всю карточку"}
SYSTEM = ("Ты - сильный специалист по карточкам товаров на Wildberries (SEO, конверсия). Улучшаешь карточку продавца. Правила: "
          "1) не выдумывай свойства товара - только то, что есть в карточке, характеристиках, описании, отзывах или правилах магазина; "
          "2) ключевые слова бери из реальных поисковых запросов (данные даны), самые частотные и конверсионные - ближе к началу; "
          "без переспама и повторов; 3) название - до 60 знаков, без брендов конкурентов, без CAPS и восклицаний; "
          "4) описание - до 5000 знаков, живым языком, абзацами, без markdown и эмодзи, без длинного тире (только дефис «-»); "
          "5) характеристики - только из списка предмета (по id), значения в формате WB; 6) если менять нечего - так и скажи. "
          "Ответ - ТОЛЬКО JSON без пояснений вокруг.")


def _queries(c, shop: int, nm: int) -> list[dict]:
    from .wb import WB
    e = today_msk() - timedelta(days=1)
    body = {"currentPeriod": {"start": str(e - timedelta(days=13)), "end": str(e)}, "nmIds": [nm], "topOrderBy": "openCard",
            "includeSubstitutedSKUs": True, "includeSearchTexts": True, "orderBy": {"field": "openCard", "mode": "desc"}, "limit": 30}
    try:
        r = WB(c, c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone()).call(
            "analytics", "/api/v2/search-report/product/search-texts", "POST", body=body) or {}
    except Exception:  
        c.rollback()
        return []
    out = []
    for x in (r.get("data") or {}).get("items") or []:
        g = lambda k: (x.get(k) or {}).get("current") if isinstance(x.get(k), dict) else x.get(k)  
        out.append({"q": x.get("text"), "freq_month": g("frequency"), "pos": g("avgPosition"), "opens": g("openCard"), "orders": g("orders")})
    return out


def _context(c, shop: int, nm: int, d: dict) -> str:
    b = cards.view(d["base"])
    ch = d["changes"]
    cur = {**b, **{k: v for k, v in ch.items() if k != "characteristics"}}
    chars = {**b["characteristics"], **(ch.get("characteristics") or {})}
    meta = cards.charcs(c, shop, b["subject_id"])
    parts = [f"ТОВАР: предмет «{b['subject']}», бренд {b['brand']}, артикул продавца {b['vendor_code']}, артикул WB {nm}.",
             f"НАЗВАНИЕ ({len(cur['title'])} зн.): {cur['title']}", f"ОПИСАНИЕ ({len(cur['description'])} зн.):\n{cur['description']}",
             "\nХАРАКТЕРИСТИКИ ПРЕДМЕТА (id | название | обязательная | ед. | макс. значений | тип 4 = число | текущее значение):"]
    for m in meta:
        k = str(m["charcID"])
        parts.append(f"{k} | {m['name']} | {'да' if m.get('required') else ''} | {m.get('unitName') or ''} | {m.get('maxCount') or ''} | "
                     f"{m.get('charcType')} | {json.dumps(chars.get(k), ensure_ascii=False) if k in chars else '—'}")
    qs = _queries(c, shop, nm)
    if qs:
        text = (cur["title"] + " " + cur["description"]).lower()
        parts.append("\nПОИСКОВЫЕ ЗАПРОСЫ АРТИКУЛА ЗА 14 ДНЕЙ (запрос | частота в мес | ср. позиция | переходы | заказы | есть ли все слова в тексте):")
        for q in qs:
            words = [w for w in re.findall(r"\w+", (q["q"] or "").lower()) if len(w) > 2]
            has = all(w[:max(4, len(w) - 2)] in text for w in words) if words else True
            parts.append(f"{q['q']} | {q['freq_month']} | {q['pos']} | {q['opens']} | {q['orders']} | {'да' if has else 'НЕТ'}")
    kw = c.execute("""SELECT query, sum(clicks) cl, sum(orders) o FROM wb_ad_kw_daily WHERE account_id=%s AND nm_id=%s AND day > current_date - 30
                      GROUP BY 1 HAVING sum(orders) > 0 ORDER BY 3 DESC LIMIT 15""", (shop, nm)).fetchall()
    if kw:
        parts.append("\nРЕКЛАМНЫЕ КЛАСТЕРЫ С ЗАКАЗАМИ ЗА 30 ДНЕЙ (кластер | клики | заказы): " + "; ".join(f"{k['query']} | {k['cl']} | {k['o']}" for k in kw))
    rv = c.execute("""SELECT valuation, text, pros, cons FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s
                      AND coalesce(text,'')||coalesce(pros,'')||coalesce(cons,'') <> '' ORDER BY created_at DESC LIMIT 60""", (shop, nm)).fetchall()
    if rv:
        st = c.execute("SELECT count(*) n, round(avg(valuation)::numeric,2) a FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
        parts.append(f"\nОТЗЫВЫ (всего {st['n']}, средняя {st['a']}); последние с текстом:")
        for r in rv:
            t = " ".join(x for x in (r["text"], r["pros"] and "+ " + r["pros"], r["cons"] and "- " + r["cons"]) if x)
            parts.append(f"{r['valuation']}★ {t[:220]}")
    rules = c.execute("SELECT text FROM card_rules WHERE account_id=%s", (shop,)).fetchone()
    if rules and rules["text"].strip():
        parts += ["\nПРАВИЛА МАГАЗИНА ДЛЯ КАРТОЧЕК (соблюдать обязательно):", rules["text"]]
    return "\n".join(parts)


def _ask_format(scope: str, n_media: int) -> str:
    keys = ["title", "description", "characteristics", "media"] if scope == "all" else [scope]
    spec = {"title": '"title": {"value": "новое название", "why": "почему так (какие запросы добавили)"}',
            "description": '"description": {"value": "новое описание целиком", "why": "что изменили и зачем"}',
            "characteristics": '"characteristics": {"value": {"<id>": ["значение"] или число}, "why": "что дополнили"} - только изменяемые',
            "media": f'"media": {{"value": [номера слайдов 1..{n_media} в новом порядке, все], "why": "почему такой порядок"}}'}
    return ("Верни JSON вида {" + ", ".join(spec[k] for k in keys) + ', "summary": "2-3 предложения: главное, что улучшили"}. '
            "Поле, которое менять не нужно, - не включай.")


@contextmanager
def _photos(c, shop: int, media: list[dict]):
    """Decode bounded public/store-owned images; remove files after success or error."""
    from . import safe_images
    with tempfile.TemporaryDirectory(prefix="cardai_") as folder:
        out, total = [], 0
        deadline = time.monotonic() + 120
        if len(media) > 30:
            raise actions.ActionDenied("Для разбора не больше 30 медиа")
        for i, m in enumerate(media):
            if m["kind"] != "photo":
                continue
            url = (m.get("thumb") or m["url"]).replace("/c246x328/", "/c516x688/")
            try:
                raw = safe_images.fetch(c, shop, url, cards.MEDIA_DIR, deadline=deadline)
                total += len(raw)
                if total > 96 * 1024 * 1024:
                    raise safe_images.ImageFetchError("Общий размер фото больше 96 МБ")
                p = Path(folder) / f"{i + 1:02d}.jpg"
                p.write_bytes(safe_images.normalized_jpeg(raw))
                out.append(str(p))
            except safe_images.ImageFetchError as e:
                raise actions.ActionDenied(f"Фото {i + 1}: {e}") from None
        yield out


def _complete(key: str, prompt: str, images: list[str] | None, system: str | None = None, max_tokens: int = 6000) -> str:
    from . import aireport
    system = system or SYSTEM
    if key == aireport.SUBSCRIPTION:
        return aireport._cli(system, prompt, timeout=600, files=images or None)
    content: list | str = prompt
    if images:
        import base64
        mt = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".pdf": "application/pdf"}
        content = [{"type": "document" if Path(p).suffix.lower() == ".pdf" else "image",
                    "source": {"type": "base64", "media_type": mt.get(Path(p).suffix.lower(), "image/webp"),
                               "data": base64.b64encode(Path(p).read_bytes()).decode()}} for p in images[:20]]
        content.append({"type": "text", "text": prompt})
    from . import llm
    return llm.text(llm.messages(key, {"max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": content}]}, timeout=600))


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise actions.ActionDenied("Нейросеть ответила не в том формате — попробуйте ещё раз")
    return json.loads(m.group(0))


def suggest(c, shop: int, nm: int, scope: str, uid: int) -> dict:
    from . import assistant
    acc = assistant.access(c, shop, uid)
    if not acc.get("ok"):
        raise actions.ActionDenied(acc.get("reason") or "Нет доступа к нейросети")
    d = cards.draft_open(c, shop, nm, uid)
    c.commit()
    b = cards.view(d["base"])
    media = d["changes"].get("media") or b["media"]
    prompt = _context(c, shop, nm, d)
    prompt += f"\n\nЗАДАЧА: улучши {SCOPES[scope]}.\n" + _ask_format(scope, len(media))
    with _photos(c, shop, media if scope in ("media", "all") else []) as imgs:
        if imgs:
            prompt += f"\n\nФОТО КАРТОЧКИ: приложены слайды по порядку (файлы 01..{len(media):02d}, номер = позиция слайда)."
        out = _parse(_complete(acc["key"], prompt, imgs))
    done = []
    for f in ("title", "description", "characteristics", "media"):
        x = out.get(f)
        if not isinstance(x, dict) or x.get("value") in (None, "", [], {}):
            continue
        v, why = x["value"], (x.get("why") or "")[:1500]
        try:
            if f == "title" and len(v) > cards.TITLE_MAX:
                v = v[:cards.TITLE_MAX].rsplit(" ", 1)[0]
            if f in ("title", "description"):
                v = v.replace("—", "-").replace("–", "-")
            if f == "characteristics":
                ids = {str(m["charcID"]): m for m in cards.charcs(c, shop, b["subject_id"])}
                v = {str(k): val for k, val in v.items() if str(k) in ids}
                v = {**(d["changes"].get("characteristics") or {}), **v}
                if not v:
                    continue
            if f == "media":
                order = [int(i) - 1 for i in v if str(i).isdigit()]
                if sorted(order) != list(range(len(media))):
                    continue                     
                v = [media[i] for i in order]
            d = cards.draft_set(c, shop, nm, f, v, uid, source="ai", note=why)
            done.append(f)
        except (actions.ActionDenied, ValueError, TypeError):
            continue
    c.commit()
    return {"fields": done, "summary": (out.get("summary") or "")[:800]}


def start(shop: int, nm: int, scope: str, uid: int) -> bool:
    """Запуск в фоне; False — уже идёт."""
    from . import db
    if scope not in SCOPES:
        raise actions.ActionDenied("Неизвестная часть карточки")
    with db.connect() as c:
        r = c.execute("""INSERT INTO card_ai_jobs(account_id,nm_id,scope,state) VALUES (%s,%s,%s,'running')
                         ON CONFLICT (account_id,nm_id) DO UPDATE SET scope=EXCLUDED.scope, state='running', error=NULL, summary=NULL,
                           started_at=now(), finished_at=NULL
                         WHERE card_ai_jobs.state<>'running' OR card_ai_jobs.started_at < now() - interval '15 minutes'
                         RETURNING 1""", (shop, nm, scope)).fetchone()
        c.commit()
        if not r:
            return False

    def run():
        with db.connect() as c2:
            try:
                res = suggest(c2, shop, nm, scope, uid)
                txt = res["summary"] or ("Изменения в черновике: " + ", ".join(res["fields"]) if res["fields"] else "Нейросеть не нашла, что улучшить.")
                c2.execute("UPDATE card_ai_jobs SET state='done', summary=%s, finished_at=now() WHERE account_id=%s AND nm_id=%s", (txt, shop, nm))
            except Exception as e:  
                c2.rollback()
                c2.execute("UPDATE card_ai_jobs SET state='error', error=%s, finished_at=now() WHERE account_id=%s AND nm_id=%s",
                           (str(e)[:400], shop, nm))
            c2.commit()
    threading.Thread(target=run, daemon=True).start()
    return True


def job(c, shop: int, nm: int) -> dict | None:
    return c.execute("SELECT scope, state, error, summary, started_at, finished_at FROM card_ai_jobs WHERE account_id=%s AND nm_id=%s",
                     (shop, nm)).fetchone()

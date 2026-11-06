"""Self-hosted application component."""

import json
import re
from datetime import datetime, timedelta, timezone

MIN_RATING = 4.5
FRESH_DAYS = 7



REGS = {"heat": "Регламент: тепловое оборудование → сопутствующий → локомотив (правило магазина)"}
HEAT_MIN_RATING = 4.7
HEAT_SUBJECTS = {"Тепловые пушки", "Конвекторы", "Обогреватели", "Тепловентиляторы", "Тепловые завесы", "Котлы газовые и топливные"}
LOCO_TAG = "локомотив"
KIND_T = {"pair": "дополняет", "alt": "замена", "heat": "тепловое оборудование (приоритет 1)", "comp": "сопутствующий (приоритет 2)",
          "loco": "товар-локомотив (приоритет 3)"}
SYSTEM = ("Ты помогаешь продавцу маркетплейса подобрать, какие товары ЕГО ЖЕ магазина посоветовать покупателю товара. Подбирай по смыслу: "
          "kind=pair — товар, который берут вместе / дополняет (свечи → диффузор, сироп → другой вкус линейки, подушка → наволочка); "
          "kind=alt — замена (другой объём, размер, цвет, набор того же типа). Не предлагай сам товар и почти одинаковые копии карточек. "
          "Только из списка кандидатов. Если подходящих нет — верни пустой список. Ответ — только JSON без пояснений.")


def reg(c, shop: int) -> str | None:
    """Регламент рекомендаций магазина (настройка блока «Отзывы», действует и на вопросы)."""
    from . import actions
    r = actions.block(c, shop, "reviews")["settings"].get("reco_reg")
    return r if r in REGS else None


def min_rating(c, shop: int) -> float:
    return HEAT_MIN_RATING if reg(c, shop) == "heat" else MIN_RATING


def _catalog(c, shop: int) -> list[dict]:
    """Товары магазина, которые можно советовать: в наличии (склады WB или свои), не «не в работе», рейтинг ≥ min_rating (если известен)."""
    from .exclusions import excluded
    ex = excluded(c, shop)
    rows = c.execute(
        """WITH st AS (SELECT nm_id, sum(quantity) q FROM stocks_wb_snap WHERE account_id=%(s)s
                       AND snap_at=(SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=%(s)s) GROUP BY 1),
                fbs AS (SELECT nm_id, sum(quantity) q FROM stocks_seller_snap WHERE account_id=%(s)s
                        AND snap_at=(SELECT max(snap_at) FROM stocks_seller_snap WHERE account_id=%(s)s) GROUP BY 1),
                rt AS (SELECT DISTINCT ON ((data->>'nmId')::bigint) (data->>'nmId')::bigint nm_id, (data->>'feedbackRating')::numeric r
                       FROM raw_rows WHERE account_id=%(s)s AND source='funnel_day' AND row_date > current_date - 30
                       AND data->>'feedbackRating' IS NOT NULL ORDER BY (data->>'nmId')::bigint, row_date DESC),
                o AS (SELECT nm_id, count(*) n FROM orders WHERE account_id=%(s)s AND order_dt > now() - interval '30 days' GROUP BY 1)
           SELECT n.nm_id, n.vendor_code, n.title, n.subject, n.brand, coalesce(st.q,0)+coalesce(fbs.q,0) stock, rt.r rating, coalesce(o.n,0) orders
           FROM nomenclature n LEFT JOIN st ON st.nm_id=n.nm_id LEFT JOIN fbs ON fbs.nm_id=n.nm_id LEFT JOIN rt ON rt.nm_id=n.nm_id
           LEFT JOIN o ON o.nm_id=n.nm_id WHERE n.account_id=%(s)s""", {"s": shop}).fetchall()
    mr = min_rating(c, shop)
    return [r for r in rows if r["nm_id"] not in ex and float(r["stock"] or 0) > 0 and (r["rating"] is None or float(r["rating"]) >= mr)]


def get(c, shop: int, nm: int) -> dict:
    r = c.execute("SELECT items, source, updated_at FROM reco_map WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    return {"items": (r or {}).get("items") or [], "source": (r or {}).get("source"), "updated_at": (r or {}).get("updated_at")}


def build(c, shop: int, nm: int, key: str) -> list[dict]:
    """Подобрать нейросетью 3–5 товаров к nm (ручные правки — закреплённые и добавленные — сохраняем)."""
    from . import aireport
    me = c.execute("SELECT nm_id, vendor_code, title, subject, brand FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    if not me:
        return []
    heat = reg(c, shop) == "heat"
    cat = [x for x in _catalog(c, shop) if x["nm_id"] != nm]
    if heat:                    
        cat = [x for x in cat if x["subject"] != me["subject"] and x["subject"] not in HEAT_SUBJECTS]
    cat.sort(key=lambda x: -int(x["orders"] or 0))
    cand = cat[:250]
    if not cand:
        return []
    lines = "\n".join(f"{x['nm_id']} | {x['subject'] or ''} | {x['brand'] or ''} | {(x['title'] or '')[:90]} | {x['vendor_code'] or ''}" for x in cand)
    prompt = (f"ТОВАР ПОКУПАТЕЛЯ: {me['nm_id']} | {me['subject'] or ''} | {me['brand'] or ''} | {me['title'] or ''} | {me['vendor_code'] or ''}\n\n"
              f"КАНДИДАТЫ (артикул | предмет | бренд | название | артикул продавца):\n{lines}\n\n"
              'Верни JSON: {"items": [{"nm_id": 123, "kind": "pair|alt", "why": "до 60 знаков, зачем покупателю"}]} — от 0 до 5 товаров, лучшие первыми.')
    if heat:
        prompt += ("\n\nПО РЕГЛАМЕНТУ МАГАЗИНА: только kind=pair и только СТРОГО сопутствующие к товару покупателя - аксессуар, расходник, "
                   "комплектующее (бензопила → цепь, шина для бензопилы; обогреватель → крепление, датчик). Запрещено: товар той же категории "
                   "(замена), аналоги, просто похожие или несопутствующие товары. Нет строго сопутствующих - пустой список.")
    try:
        txt = aireport.complete(key, SYSTEM, prompt, max_tokens=800)
        d = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
    except Exception:  
        return []
    ok = {x["nm_id"] for x in cand}
    ai = [{"nm_id": int(x["nm_id"]), "kind": "alt" if x.get("kind") == "alt" and not heat else "pair", "why": str(x.get("why") or "")[:120]}
          for x in d.get("items") or [] if str(x.get("nm_id", "")).isdigit() and int(x["nm_id"]) in ok][:5]
    old = get(c, shop, nm)["items"]
    manual = [x for x in old if x.get("manual") or x.get("pinned")]
    removed = {x["nm_id"] for x in old if x.get("removed")}
    items = manual + [x for x in ai if x["nm_id"] not in {m["nm_id"] for m in manual} | removed] + [x for x in old if x.get("removed")]
    c.execute("""INSERT INTO reco_map(account_id,nm_id,items,source,updated_at) VALUES (%s,%s,%s,'ai',now())
                 ON CONFLICT (account_id,nm_id) DO UPDATE SET items=EXCLUDED.items, updated_at=now()""", (shop, nm, json.dumps(items, ensure_ascii=False)))
    c.commit()
    return items


def save(c, shop: int, nm: int, items: list[dict], uid: int):
    """Ручная правка карты менеджером: добавленные — manual, закреплённые — pinned, убранные — removed (нейросеть их больше не предложит)."""
    clean = []
    for x in items[:20]:
        if not str(x.get("nm_id", "")).isdigit():
            continue
        clean.append({"nm_id": int(x["nm_id"]), "kind": "alt" if x.get("kind") == "alt" else "pair", "why": str(x.get("why") or "")[:120],
                      **{k: True for k in ("manual", "pinned", "removed") if x.get(k)}})
    c.execute("""INSERT INTO reco_map(account_id,nm_id,items,source,edited_by,updated_at) VALUES (%s,%s,%s,'manual',%s,now())
                 ON CONFLICT (account_id,nm_id) DO UPDATE SET items=EXCLUDED.items, source='manual', edited_by=EXCLUDED.edited_by, updated_at=now()""",
              (shop, nm, json.dumps(clean, ensure_ascii=False), uid))


def _recent(c, shop: int) -> dict:
    """Сколько раз товар советовали в последних 60 ответах — тепловое чередуем, чтобы советовать разное."""
    n: dict = {}
    for t in ("review_answers", "question_answers"):
        for r in c.execute(f"SELECT reco_nm FROM {t} WHERE account_id=%s AND reco_nm IS NOT NULL ORDER BY id DESC LIMIT 60", (shop,)):
            n[r["reco_nm"]] = n.get(r["reco_nm"], 0) + 1
    return n


def ordered(c, shop: int, nm: int, m: dict | None = None) -> list[dict]:
    """По регламенту «heat»: очередь кандидатов по приоритетам — тепловое (если товар не тепловой; разных видов, по очереди),
    сопутствующие из карты (без замен, не той же категории), локомотивы (тег «локомотив», не прямая замена, к тепловому — не тепловые)."""
    m = m or get(c, shop, nm)
    me = c.execute("SELECT subject FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone() or {}
    subj = me.get("subject")
    main_heat = subj in HEAT_SUBJECTS
    cat = [x for x in _catalog(c, shop) if x["nm_id"] != nm]
    good = {x["nm_id"]: x for x in cat}
    out = []
    if not main_heat:
        rec = _recent(c, shop)
        heats = sorted((x for x in cat if x["subject"] in HEAT_SUBJECTS), key=lambda x: (rec.get(x["nm_id"], 0), -int(x["orders"] or 0)))
        seen = set()
        for x in heats:                     
            if x["subject"] not in seen:
                seen.add(x["subject"])
                out.append({"nm_id": x["nm_id"], "kind": "heat", "why": f"{x['subject']} нашего магазина"})
            if len(seen) >= 2:
                break
    for x in sorted(m["items"], key=lambda x: not x.get("pinned")):
        g = good.get(x["nm_id"])
        if x.get("removed") or x.get("kind") == "alt" or not g or g["subject"] == subj or g["subject"] in HEAT_SUBJECTS:
            continue
        out.append({**x, "kind": "comp"})
    locos = [r["nm_id"] for r in c.execute("SELECT nm_id FROM article_groups WHERE account_id=%s AND lower(group_name) LIKE %s",
                                           (shop, f"%{LOCO_TAG}%"))]
    for n in locos:
        g = good.get(n)
        if g and g["subject"] != subj and not (main_heat and g["subject"] in HEAT_SUBJECTS) and n not in {y["nm_id"] for y in out}:
            out.append({"nm_id": n, "kind": "loco", "why": "продвигаемый товар магазина"})
    for x in out:
        g = good[x["nm_id"]]
        x.update(title=g["title"], vendor_code=g["vendor_code"], subject=g["subject"])
    return out


def pick(c, shop: int, nm: int, key: str, allow_alt_only: bool = False) -> list[dict]:
    """Кандидаты для ответа: карта (пересобираем, если старше недели), только в наличии и с хорошим рейтингом. → до 3 с названиями.
    По регламенту «heat» — очередь приоритетов (ordered), замен нет совсем."""
    heat = reg(c, shop) == "heat"
    if heat and allow_alt_only:
        return []
    m = get(c, shop, nm)
    if not m["items"] or (m["source"] != "manual" and (not m["updated_at"] or m["updated_at"] < datetime.now(timezone.utc) - timedelta(days=FRESH_DAYS))):
        build(c, shop, nm, key)
        m = get(c, shop, nm)
    if heat:
        q = ordered(c, shop, nm, m)
        by = {k: [x for x in q if x["kind"] == k] for k in ("heat", "comp", "loco")}
        return (by["heat"][:2] + by["comp"][:1] + by["loco"][:1])[:3] if by["heat"] else (by["comp"][:2] + by["loco"][:1])[:3]
    good = {x["nm_id"]: x for x in _catalog(c, shop)}
    out = []
    for x in sorted(m["items"], key=lambda x: not x.get("pinned")):
        if x.get("removed") or x["nm_id"] not in good or (allow_alt_only and x.get("kind") != "alt"):
            continue
        g = good[x["nm_id"]]
        out.append({**x, "title": g["title"], "vendor_code": g["vendor_code"], "subject": g["subject"]})
    return out[:3]


def due(c, shop: int, table: str, every: int) -> bool:
    """Пора ли советовать: в последних every-1 черновиках ИИ этого блока рекомендаций не было."""
    if every <= 1:
        return True
    rows = c.execute(f"SELECT reco_nm FROM {table} WHERE account_id=%s AND source='ai' AND status IN ('draft','sent') ORDER BY id DESC LIMIT %s",
                     (shop, every - 1)).fetchall()
    return not any(r["reco_nm"] for r in rows)


def prompt_block(items: list[dict], neg: bool) -> str:
    lines = "\n".join(f"- арт. {x['nm_id']}: {(x['title'] or '')[:80]} ({KIND_T.get(x.get('kind'), 'дополняет')}; {x.get('why') or ''})"
                      for x in items)
    if any(x.get("kind") in ("heat", "comp", "loco") for x in items):
        return (f"\n\nПОСОВЕТУЙ ОДИН ТОВАР НАШЕГО МАГАЗИНА ПО РЕГЛАМЕНТУ (список - в порядке приоритета):\n{lines}\n"
                "Бери первый по списку; следующий - только если первый совсем не к месту в этом ответе. Ровно один товар, одной фразой "
                "в конце ответа: коротко зачем и «арт. NNN». Никаких других товаров, магазинов и брендов.")
    head = ("МОЖНО ПРЕДЛОЖИТЬ ЗАМЕНУ (только если она решает проблему покупателя, иначе не советуй ничего):" if neg
            else "МОЖНО ПОСОВЕТОВАТЬ ОДИН ТОВАР НАШЕГО МАГАЗИНА (только если это к месту; если не к месту — не советуй ничего):")
    return (f"\n\n{head}\n{lines}\nЕсли советуешь — ровно один товар, одной фразой в конце ответа: коротко зачем и «арт. NNN». "
            "Никаких других товаров, магазинов и брендов.")


def used(text: str, items: list[dict]) -> int | None:
    for x in items:
        if str(x["nm_id"]) in (text or ""):
            return x["nm_id"]
    return None

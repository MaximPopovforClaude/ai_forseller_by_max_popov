"""Self-hosted application component."""

import re
from collections import defaultdict

STOP = {"для", "и", "в", "на", "с", "со", "из", "под", "по", "от", "до", "к", "ко", "или", "без", "не", "при", "а", "the", "of", "за", "про", "у",
        "о", "об", "шт", "штук", "см", "мл", "г", "кг", "л", "мм"}
WORD = re.compile(r"[a-zа-яё0-9]+", re.I)


def _stem(w: str) -> str:
    return w[:max(4, len(w) - 2)] if len(w) > 5 else w


def words(text: str) -> list[str]:
    return [w for w in WORD.findall((text or "").lower().replace("ё", "е")) if len(w) >= 3 and w not in STOP and not w.isdigit()]


def card_text(c, shop: int, nm: int) -> str:
    r = c.execute("SELECT data FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    d = (r or {}).get("data") or {}
    parts = [d.get("title") or "", d.get("description") or "", d.get("subjectName") or ""]
    for ch in d.get("characteristics") or []:
        v = ch.get("value")
        parts.append(" ".join(map(str, v)) if isinstance(v, list) else str(v or ""))
    return " ".join(parts)


def view(c, shop: int, nm: int) -> dict:
    j = c.execute("""SELECT items, date_from, date_to FROM jam_cache WHERE account_id=%s AND nm_id=%s AND state='done'
                     ORDER BY fetched_at DESC LIMIT 1""", (shop, nm)).fetchone()
    queries, src = [], None
    if j and j["items"]:
        queries = [(i["text"], float(i.get("frequency") or 0), float(i.get("openCard") or 0)) for i in j["items"]]
        src = f"Джем {j['date_from']:%d.%m}–{j['date_to']:%d.%m}: {len(queries)} запросов, вхождения — сумма частоты запросов"
    else:
        queries = [(r["query"], float(r["v"] or 0), float(r["cl"] or 0)) for r in c.execute(
            """SELECT query, sum(views) v, sum(clicks) cl FROM wb_ad_kw_daily WHERE account_id=%s AND nm_id=%s AND day > current_date - 30
               GROUP BY 1 ORDER BY 2 DESC LIMIT 500""", (shop, nm))]
        if queries:
            src = f"Джема нет — поисковые кластеры рекламы за 30 дней: {len(queries)} запросов, вхождения — сумма показов рекламы"
    card = " ".join(words(card_text(c, shop, nm)))
    have = {_stem(w) for w in card.split()}
    agg = defaultdict(lambda: [0.0, 0, 0.0])
    for text, freq, clicks in queries:
        for w in set(words(text)):
            a = agg[w]
            a[0] += freq; a[1] += 1; a[2] += clicks
    marks = {r["word"]: r for r in c.execute("SELECT word, mark, updated_at FROM seo_marks WHERE account_id=%s AND nm_id=%s", (shop, nm))}
    rows = [{"word": w, "freq": round(a[0]), "queries": a[1], "clicks": round(a[2]), "in_card": _stem(w) in have,
             "mark": (marks.get(w) or {}).get("mark")} for w, a in agg.items()]
    rows.sort(key=lambda r: -r["freq"])
    return {"rows": rows[:600], "source": src, "added": sorted(w for w, m in marks.items() if m["mark"] == "add"),
            "removed": sorted(w for w, m in marks.items() if m["mark"] == "remove"), "has_jam": bool(j)}

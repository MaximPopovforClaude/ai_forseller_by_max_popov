"""Рейтинг товара WB по отзывам (отчёт «Оценка товара», wb_item_rating): сколько оценок нужно, чтобы поднять рейтинг до цели.

Новая оценка s сдвигает рейтинг как в среднем: (R·N + s·k) / (N + k). Какие R и N брать (basis, калибровка 22.10 по 1 129 артикулам):
- «точно»: рейтинг WB = простому среднему оценок отчёта (±0,01) — так у ~70 % товаров, чьи оценки моложе года; считаем от точной суммы звёзд;
- «по факту»: иначе (старые товары — WB, видимо, даёт свежим оценкам больший вес) N берём из ежедневных снимков: как реально сдвинулся
  рейтинг от новых оценок (N = (сумма новых звёзд − R₂·новых) / (R₂ − R₁));
- «приблизительно»: снимков мало — от рейтинга WB и всех оценок (верхняя граница: со свежими весами нужно меньше).
"""

import math
from datetime import timedelta

STAR = (5, 4, 3, 2, 1)


def need(r: float, n: int, target: float, star: int = 5) -> int | None:
    """Сколько оценок star нужно добавить к N оценкам с рейтингом R, чтобы стало не ниже target. None — недостижимо этой оценкой."""
    if r >= target:
        return 0
    if star <= target:
        return None
    return math.ceil(n * (target - r) / (star - target) - 1e-9)


def drop(r: float, n: int, floor: float, star: int = 1) -> int | None:
    """Сколько оценок star (низких) опустят рейтинг ниже floor."""
    if r < floor:
        return 0
    if star >= floor:
        return None
    return math.floor(n * (r - floor) / (floor - star)) + 1


EXACT = 0.011          
CAL_DAYS, CAL_DR = 45, 0.03     


def basis(c, shop: int, rows: list[dict]) -> None:
    """Каждой строке latest(): r_eff, n_eff — от чего считать «сколько оценок нужно», и method (точно / по факту / приблизительно)."""
    old = {}
    if rows:
        d = rows[0]["day"]
        old = {r["nm_id"]: r for r in c.execute(
            """SELECT DISTINCT ON (nm_id) nm_id, day, rating, s5, s4, s3, s2, s1 FROM wb_item_rating
               WHERE account_id=%s AND nm_id = ANY(%s) AND day >= %s AND day < %s AND rating > 0 ORDER BY nm_id, day""",
            (shop, [r["nm_id"] for r in rows], d - timedelta(days=CAL_DAYS), d)).fetchall()}
    for r in rows:
        r["r_eff"], r["n_eff"], r["method"] = (float(r["rating"]) if r["rating"] else None), r["total"], "приблизительно"
        if not r["rating"] or not r["total"]:
            continue
        if abs(float(r["rating"]) - r["avg"]) <= EXACT:
            r["r_eff"], r["method"] = r["avg"], "точно"
            continue
        o = old.get(r["nm_id"])
        if not o:
            continue
        r1, r2 = float(o["rating"]), float(r["rating"])
        dn = r["total"] - sum(o[f"s{s}"] or 0 for s in STAR)
        ds = sum(s * ((r[f"s{s}"] or 0) - (o[f"s{s}"] or 0)) for s in STAR)
        if dn > 0 and abs(r2 - r1) >= CAL_DR:
            n = (ds - r2 * dn) / (r2 - r1)
            if 0.05 * r["total"] <= n <= 5 * r["total"]:
                r["n_eff"], r["method"] = round(n), f"по факту за {(r['day'] - o['day']).days} дн."


def latest(c, shop: int, nm_ids=None, day=None) -> list[dict]:
    """Последний снимок по артикулам (на день day или раньше) + рейтинг 7 дней назад + оценки за 30 дней по своим отзывам (m5…m1)."""
    p = {"s": shop, "d": day, "nms": list(nm_ids) if nm_ids else None}
    rows = c.execute(
        """WITH last AS (SELECT max(day) d FROM wb_item_rating WHERE account_id=%(s)s AND (%(d)s::date IS NULL OR day <= %(d)s::date))
           SELECT r.*, m.m5, m.m4, m.m3, m.m2, m.m1, n.vendor_code, n.title, n.subject, n.imt_id, n.data->'photos'->0->>'tm' AS photo,
                  (SELECT p.rating FROM wb_item_rating p WHERE p.account_id=r.account_id AND p.nm_id=r.nm_id AND p.day <= r.day - 7
                   ORDER BY p.day DESC LIMIT 1) AS rating_7
           FROM wb_item_rating r JOIN last ON r.day=last.d
           LEFT JOIN LATERAL (SELECT count(*) FILTER (WHERE valuation=5) m5, count(*) FILTER (WHERE valuation=4) m4,
                                     count(*) FILTER (WHERE valuation=3) m3, count(*) FILTER (WHERE valuation=2) m2,
                                     count(*) FILTER (WHERE valuation=1) m1
                              FROM wb_feedbacks w WHERE w.account_id=r.account_id AND w.nm_id=r.nm_id
                                AND w.created_at >= r.day - 30) m ON true
           LEFT JOIN nomenclature n ON n.account_id=r.account_id AND n.nm_id=r.nm_id
           WHERE r.account_id=%(s)s AND (%(nms)s::bigint[] IS NULL OR r.nm_id = ANY(%(nms)s::bigint[]))
           ORDER BY (coalesce(r.s5,0)+coalesce(r.s4,0)+coalesce(r.s3,0)+coalesce(r.s2,0)+coalesce(r.s1,0)) DESC""", p).fetchall()
    for r in rows:
        r["total"] = sum(r[f"s{s}"] or 0 for s in STAR)
        r["month"] = sum(r[f"m{s}"] or 0 for s in STAR)
        r["avg"] = sum(s * (r[f"s{s}"] or 0) for s in STAR) / r["total"] if r["total"] else None
        if r["rating"] is not None and float(r["rating"]) == 0:        
            r["rating"] = None
    basis(c, shop, rows)
    return rows


def step_up(r: float) -> float:
    """Следующая ступень рейтинга: 4,57 → 4,6; 4,6 → 4,7."""
    return round(math.floor(r * 10 + 1e-9) / 10 + 0.1, 1)


def history(c, shop: int, nm: int, days: int = 30) -> list[dict]:
    from .config import today_msk
    return c.execute("SELECT day, rating FROM wb_item_rating WHERE account_id=%s AND nm_id=%s AND day >= %s ORDER BY day",
                     (shop, nm, today_msk() - timedelta(days=days))).fetchall()

"""Self-hosted application component."""

import time
from datetime import timedelta

from ..config import today_msk

WINDOW = (42, 14)            
MIN_ORDERS = 5
_CACHE: dict = {}
TTL = 3600


def needed(c, shop: int) -> bool:
    """В отчёте реализации за 8 недель доставок к покупателю почти нет при сотнях продаж — эталонная формула не работает."""
    k = ("need", shop)
    hit = _CACHE.get(k)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    d0 = today_msk() - timedelta(days=56)
    r = c.execute("""SELECT count(*) FILTER (WHERE data->>'sellerOperName'='Продажа') s,
                            coalesce(sum((data->>'deliveryAmount')::numeric) FILTER (WHERE data->>'sellerOperName'='Доставка'
                              AND coalesce(data->>'bonusTypeName','') NOT ILIKE '%%к продавцу%%'), 0) d
                     FROM raw_rows WHERE account_id=%s AND source='realization' AND row_date >= %s""", (shop, d0)).fetchone()
    res = bool(r["s"] >= 50 and float(r["d"]) < r["s"] * 0.1)
    _CACHE[k] = (time.time(), res)
    return res


def by_orders(c, shop: int) -> tuple[dict[int, float], float]:
    """(% выкупа по артикулу, общий по магазину) из заказов и продаж (связь по srid)."""
    k = ("rate", shop)
    hit = _CACHE.get(k)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    rows = c.execute("""
        WITH o AS (SELECT nm_id, srid FROM orders WHERE account_id=%(s)s
                     AND order_dt BETWEEN now() - make_interval(days => %(a)s) AND now() - make_interval(days => %(b)s)),
             sl AS (SELECT srid, bool_or(sale_id LIKE 'S%%') s, bool_or(sale_id LIKE 'R%%') r FROM sales
                    WHERE account_id=%(s)s AND srid IN (SELECT srid FROM o) GROUP BY 1)
        SELECT o.nm_id, count(*) n, count(*) FILTER (WHERE sl.s AND NOT sl.r) b FROM o LEFT JOIN sl USING (srid) GROUP BY 1""",
                     {"s": shop, "a": WINDOW[0], "b": WINDOW[1]}).fetchall()
    per = {r["nm_id"]: r["b"] / r["n"] for r in rows if r["n"] >= MIN_ORDERS}
    n, b = sum(r["n"] for r in rows), sum(r["b"] for r in rows)
    res = (per, b / n if n else 1.0)
    _CACHE[k] = (time.time(), res)
    return res


def for_nms(c, shop: int, nm_ids: list[int] | None) -> float:
    """Общий % выкупа по заказам для набора артикулов (или всего магазина)."""
    if not nm_ids:
        return by_orders(c, shop)[1]
    rows = c.execute("""
        WITH o AS (SELECT srid FROM orders WHERE account_id=%(s)s AND nm_id = ANY(%(nm)s)
                     AND order_dt BETWEEN now() - make_interval(days => %(a)s) AND now() - make_interval(days => %(b)s)),
             sl AS (SELECT srid, bool_or(sale_id LIKE 'S%%') s, bool_or(sale_id LIKE 'R%%') r FROM sales
                    WHERE account_id=%(s)s AND srid IN (SELECT srid FROM o) GROUP BY 1)
        SELECT count(*) n, count(*) FILTER (WHERE sl.s AND NOT sl.r) b FROM o LEFT JOIN sl USING (srid)""",
                     {"s": shop, "nm": list(nm_ids), "a": WINDOW[0], "b": WINDOW[1]}).fetchone()
    return rows["b"] / rows["n"] if rows["n"] else by_orders(c, shop)[1]

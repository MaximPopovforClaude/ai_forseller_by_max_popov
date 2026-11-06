"""Яндекс Маркет: деньги по артикулам за период — из «Отчёта по платежам» (ym_netting, по дате транзакции).

Выручка = платежи покупателей + баллы за скидку Маркета (возмещение скидки Маркета); возвраты — возвраты платежей и баллов.
Услуги Маркета — деньгами («Оплата услуг Маркета», удерживаются из платежей) и баллами («Скидка за участие в совместных акциях»).
«К оплате на р/с» — только деньги: платежи покупателей − возвраты − услуги деньгами. Баллы на р/с не приходят, ими Маркет оплачивает услуги.
Себестоимость — по проданным минус возвращённым штукам (количество из строк платежей покупателей).
"""

from collections import defaultdict
from datetime import date

from .ymdash import X_KEYS, costs, svc_key, tax_of


def by_sku(c, shop: int, a: date, b: date, month: bool = False) -> dict:
    """→ {(market_sku | 0, «YYYY-MM» | None): {показатель: сумма}}; 0 — строки без товара (магазин целиком)."""
    m2s = {r["offer_id"]: r["market_sku"] for r in c.execute("SELECT offer_id, market_sku FROM ym_offers WHERE account_id=%s", (shop,))}
    cost = costs(c, shop)
    A = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""SELECT to_char(tx_day,'YYYY-MM') ym, shop_sku, kind, source, service, sum(qty) q, sum(amount) a FROM ym_netting
                          WHERE account_id=%s AND tx_day BETWEEN %s AND %s GROUP BY 1,2,3,4,5""", (shop, a, b)):
        sku = m2s.get(r["shop_sku"]) or 0
        x = A[(sku, r["ym"] if month else None)]
        amt, q = float(r["a"] or 0), float(r["q"] or 0)
        ret = (r["source"] or "").lower().startswith("возврат")
        if r["kind"] == "buyer":
            if ret:
                x["returns"] += amt
                x["returns_qty"] += q
            else:
                x["buyer"] += amt
                x["buyouts_qty"] += q
        elif r["kind"] == "points":
            x["points_ret" if ret else "points"] += amt
        elif r["kind"] in ("serv", "serv_pts"):
            k = svc_key(r["service"])
            x[k] += amt
            x["serv_money" if r["kind"] == "serv" else "serv_pts"] += amt
        else:
            x["x_other"] += amt
    for (sku, _), x in A.items():
        x["buyouts"] = x["buyer"] + x["points"]
        x["returns"] += x["points_ret"]
        x["x_total"] = sum(x[k] for k in X_KEYS)
        x["cost"] = (x["buyouts_qty"] - x["returns_qty"]) * cost.get(sku, 0) if sku else 0.0
        x["to_pay"] = x["buyer"] + x["returns"] - x["points_ret"] + x["serv_money"]
        x["margin"] = x["buyouts"] + x["returns"] + x["x_total"] - x["cost"]
    return A


def tax_for(regime: str, rate: float, x: dict) -> float:
    if regime == "УСН доход":
        return max(x["buyouts"] + x["returns"], 0) * rate
    if regime == "УСН доходы-расходы":
        base = x["margin"]
        return max(base * rate, (x["buyouts"] + x["returns"]) * 0.01) if base > 0 else 0.0
    return 0.0


COLS = [("tag", "Тег (группа)", "text"), ("category", "Категория", "text"), ("offer_id", "Артикул продавца", "text"),
        ("sku", "SKU на Маркете", "int"), ("buyouts", "Выкупы (платежи покупателей + баллы за скидку Маркета), ₽", "money"),
        ("buyer", "в т. ч. оплачено покупателями, ₽", "money"), ("points", "в т. ч. баллы за скидку Маркета, ₽", "money"),
        ("buyouts_qty", "Выкупы, шт", "int"), ("returns", "Возвраты, ₽", "money"), ("returns_qty", "Возвраты, шт", "int"),
        ("x_fee", "Размещение (комиссия)", "money"), ("x_deliv", "Доставка", "money"), ("x_deliv_pct", "Доставка, % выкупов", "share"),
        ("x_pay", "Приём и перевод платежа", "money"), ("x_boost", "Буст продаж", "money"), ("x_loyal", "Лояльность и отзывы за баллы", "money"),
        ("x_proc", "Невыкупы, возвраты, обработка", "money"), ("x_other", "Штрафы и прочее", "money"),
        ("x_total", "Итого услуги Маркета", "money"), ("serv_pts", "из них оплачено баллами", "money"),
        ("cost", "Себестоимость", "money"), ("give", "Раздачи", "money"), ("ads_ext", "Внешняя реклама", "money"),
        ("to_pay", "Итого к оплате на р/с (деньги)", "money"), ("tax", "Налог", "money"), ("profit", "Доход до пост. расходов", "money"),
        ("ros", "ROS", "share"), ("roi", "ROI", "share")]


def compute(c, shop: int, d_from: date, d_to: date) -> dict:
    regime, rate = tax_of(c, shop, d_to)
    A = by_sku(c, shop, d_from, d_to)
    ext = defaultdict(lambda: {"ext": 0.0, "give": 0.0})
    for e in c.execute("SELECT * FROM ext_costs WHERE account_id=%s AND coalesce(d_to, d_from) >= %s AND d_from <= %s", (shop, d_from, d_to)):
        a, z = e["d_from"], e["d_to"] or e["d_from"]
        n = (z - a).days + 1
        inside = sum(1 for i in range(n) if d_from <= date.fromordinal(a.toordinal() + i) <= d_to)
        ext[e["nm_id"]]["give" if e["kind"] == "giveaway" else "ext"] += float(e["cost"] or 0) * inside / n
    off = {r["market_sku"]: r for r in c.execute("SELECT market_sku, offer_id, category FROM ym_offers WHERE account_id=%s", (shop,))}
    grp = {r["nm_id"]: r["group_name"] for r in c.execute("SELECT nm_id, group_name FROM article_groups WHERE account_id=%s", (shop,))}
    rows = []
    for sku in {k for k, _ in A} | set(ext):
        x = A.get((sku, None)) or defaultdict(float)
        o = off.get(sku) or {}
        tax = tax_for(regime, rate, x)
        give, ad = ext[sku]["give"], ext[sku]["ext"]
        profit = x["margin"] - tax - give - ad
        rows.append({"sku": sku or None, "offer_id": o.get("offer_id") if sku else "Без товара (магазин целиком)", "category": o.get("category"),
                     "tag": grp.get(sku), **{k: round(x[k], 2) for k, *_ in COLS if k in x},
                     "x_deliv_pct": x["x_deliv"] / x["buyouts"] if x["buyouts"] else None,
                     "give": give, "ads_ext": ad, "tax": round(tax, 2), "profit": round(profit, 2),
                     "ros": profit / x["buyouts"] if x["buyouts"] else None, "roi": profit / x["cost"] if x["cost"] > 0 else None})
    rows.sort(key=lambda r: (r["sku"] is None, -(r.get("buyouts") or 0)))
    return {"rows": rows, "tax": regime}

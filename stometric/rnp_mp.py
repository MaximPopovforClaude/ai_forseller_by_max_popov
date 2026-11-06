"""Данные РНП для магазинов не-WB (Яндекс Маркет, Ozon) в полях агрегата WB, чтобы rnp.compute и экран РНП работали как у WB.

Маркет (по артикулу = SKU на Маркете, по дню):
  orders_sum = сумма заказов по цене продажи (покупатель + скидка Маркета), orders_sum_spp = то же (скидка Маркета — тоже выручка продавца),
  orders — заказано шт, buyouts / buyouts_sum_before_spp — выкупы по дню доставки,
  commission_offer_orders — услуги Маркета (кроме буста) на заказы дня: доля услуг в выкупах артикула за 60 дней × сумма заказов,
  ads_upd — буст продаж так же (доля буста × сумма заказов), cost_orders — себестоимость заказанного.
  Логистика, хранение, приёмка, НДС — 0 (у Маркета логистика — в услугах). % выкупа — заказы 15–60 дней назад (финальные статусы).
"""

from collections import defaultdict
from datetime import date, timedelta


def _ym(c, shop: int, lo: date, end: date) -> dict:
    from .sheets import ymdash
    cost = ymdash.costs(c, shop)
    nom = {r["market_sku"]: {"vendor_code": r["offer_id"], "title": r["name"], "brand": r["vendor"], "subject": r["category"], "photo": r["photo"]}
           for r in c.execute("SELECT market_sku, offer_id, name, vendor, category, photo FROM ym_offers WHERE account_id=%s AND market_sku IS NOT NULL",
                              (shop,))}
    
    t = end - timedelta(days=60)
    rate, brate = {}, {}
    sales = defaultdict(float)
    for r in ymdash.items(c, shop, t, end, "status_day"):
        if r["status"] in ymdash.DONE and r["sku"]:
            sales[r["sku"]] += float(r["total"])
    from .sheets import ymfin
    serv = ymfin.by_sku(c, shop, t, end)
    S0 = B0 = X0 = 0.0
    for (sku, _), x in serv.items():
        if not sku:
            continue
        s = sales.get(sku) or x["buyouts"]
        if s > 0:
            rate[sku] = -(x["x_total"] - x["x_boost"]) / s
            brate[sku] = -x["x_boost"] / s
        S0 += s
        X0 += -(x["x_total"] - x["x_boost"])
        B0 += -x["x_boost"]
    r0, b0 = (X0 / S0, B0 / S0) if S0 else (0.0, 0.0)
    
    fin = defaultdict(lambda: [0.0, 0.0])
    for r in ymdash.items(c, shop, end - timedelta(days=60), end - timedelta(days=15), "order_day"):
        if r["sku"] and r["status"] in ymdash.FINAL:
            q0 = float(r["initial_qty"] or r["qty"] or 0)
            fin[r["sku"]][0] += q0
            fin[r["sku"]][1] += float(r["qty"] or 0) if r["status"] in ymdash.DONE else 0
    bp = {s: v[1] / v[0] for s, v in fin.items() if v[0] >= 5}
    T = sum(v[0] for v in fin.values())
    bp0 = sum(v[1] for v in fin.values()) / T if T else 1.0
    uprice = ymdash._unit_prices(c, shop)
    day = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in ymdash.items(c, shop, lo, end, "order_day"):
        if not r["sku"]:
            continue
        q0 = float(r["initial_qty"] or r["qty"] or 0)
        s0 = (r["unit"] if r["unit"] is not None else uprice.get(r["sku"], 0)) * q0
        x = day[r["sku"]][r["order_day"]]
        x["orders_sum"] += s0
        x["orders_sum_spp"] += s0
        x["orders"] += q0
        x["commission_offer_orders"] += s0 * rate.get(r["sku"], r0)
        x["ads_upd"] += s0 * brate.get(r["sku"], b0)
        x["cost_orders"] += q0 * cost.get(r["sku"], 0)
    for r in ymdash.items(c, shop, lo, end, "status_day"):
        if r["sku"] and r["status"] in ymdash.DONE:
            x = day[r["sku"]][r["status_day"]]
            x["buyouts"] += float(r["qty"] or 0)
            x["buyouts_sum_before_spp"] += float(r["total"])
    stock, fbs = defaultdict(lambda: {"q": 0.0, "wt": 0.0, "wf": 0.0}), defaultdict(float)
    for r in c.execute("""SELECT f.market_sku sku, s.placement, sum(coalesce(s.available,0)) q FROM ym_stocks s
                          JOIN ym_offers f ON f.account_id=s.account_id AND f.offer_id=s.offer_id
                          WHERE s.account_id=%s AND s.snap_at=(SELECT max(snap_at) FROM ym_stocks WHERE account_id=%s) GROUP BY 1,2""", (shop, shop)):
        if r["placement"] in ("FBS", "DBS"):
            fbs[r["sku"]] += float(r["q"] or 0)
        else:
            stock[r["sku"]]["q"] += float(r["q"] or 0)
    price = {r["sku"]: {"discounted_price": r["price"]} for r in c.execute(
        """SELECT f.market_sku sku, p.price FROM ym_prices p JOIN ym_offers f ON f.account_id=p.account_id AND f.offer_id=p.offer_id
           WHERE p.account_id=%s""", (shop,))}
    return {"nom": nom, "day": {k: dict(v) for k, v in day.items()}, "bp": bp, "bp0": bp0, "stock": dict(stock), "fbs": dict(fbs), "price": price,
            "groups": lambda grp: [r["nm_id"] for r in c.execute("SELECT nm_id FROM article_groups WHERE account_id=%s AND group_name=%s", (shop, grp))]}


def _oz(c, shop: int, lo: date, end: date) -> dict:
    """Ozon: заказы — отправления по дню заказа (цена × шт); комиссия и логистика заказов — по тарифам карточки (% и ₽/шт по схеме
    FBO/FBS, как «3#Дашборд»); выкупы — начисления Ozon «за продажу» по дню операции; реклама — расход по SKU из отчётов кампаний
    (oz_ad_sku), без них — расход кампании поровну на её товары; % выкупа — отправления 15–60 дней назад (доставлено / финальные)."""
    from .sheets import ozdash
    cost = ozdash._costs(c, shop, end)
    com = ozdash._commission(c, shop)
    nom = {r["sku"]: {"vendor_code": r["offer_id"], "title": r["name"], "brand": None, "subject": r["type_name"], "photo": r["photo"]}
           for r in c.execute("""SELECT p.sku, p.offer_id, p.name, p.photo, t.type_name FROM oz_products p LEFT JOIN oz_types t ON t.type_id=p.type_id
                                 WHERE p.account_id=%s AND p.sku IS NOT NULL""", (shop,))}
    day = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for p in c.execute("SELECT order_day, sku, scheme, qty, price FROM oz_postings WHERE account_id=%s AND order_day BETWEEN %s AND %s",
                       (shop, lo, end)):
        q, s0 = float(p["qty"] or 0), float(p["qty"] or 0) * float(p["price"] or 0)
        pc, dl = com.get(p["sku"], {}).get(p["scheme"], (0, 0))
        x = day[p["sku"]][p["order_day"]]
        x["orders_sum"] += s0
        x["orders_sum_spp"] += s0
        x["orders"] += q
        x["commission_offer_orders"] += s0 * pc / 100
        x["logistics_orders"] += q * dl
        x["cost_orders"] += q * cost.at(p["sku"], p["order_day"])
    for t in c.execute("""SELECT op_day, skus, qty, accruals_for_sale, raw FROM oz_transactions
                          WHERE account_id=%s AND op_day BETWEEN %s AND %s AND tx_type='orders'""", (shop, lo, end)):
        for s_, (q, share) in ozdash.transaction_parts(t).items():
            x = day[s_][t["op_day"]]
            x["buyouts"] += q
            x["buyouts_sum_before_spp"] += float(t["accruals_for_sale"] or 0) * share
    if c.execute("SELECT 1 FROM oz_ad_sku WHERE account_id=%s LIMIT 1", (shop,)).fetchone():
        for r in c.execute("SELECT day, sku, sum(spent) s FROM oz_ad_sku WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2", (shop, lo, end)):
            day[r["sku"]][r["day"]]["ads_upd"] += float(r["s"] or 0)
    else:
        for r in c.execute("""SELECT d.day, d.spent, k.skus FROM oz_ad_daily d LEFT JOIN oz_ad_campaigns k ON k.account_id=d.account_id
                              AND k.campaign_id=d.campaign_id WHERE d.account_id=%s AND d.day BETWEEN %s AND %s""", (shop, lo, end)):
            sk = r["skus"] or []
            for s_ in sk:
                day[s_][r["day"]]["ads_upd"] += float(r["spent"] or 0) / len(sk)
    fin = defaultdict(lambda: [0.0, 0.0])
    for p in c.execute("""SELECT sku, qty, status FROM oz_postings WHERE account_id=%s AND order_day BETWEEN %s AND %s
                          AND status IN ('delivered','cancelled')""", (shop, end - timedelta(days=60), end - timedelta(days=15))):
        fin[p["sku"]][0] += float(p["qty"] or 0)
        fin[p["sku"]][1] += float(p["qty"] or 0) if p["status"] == "delivered" else 0
    bp = {s_: v[1] / v[0] for s_, v in fin.items() if v[0] >= 5}
    T = sum(v[0] for v in fin.values())
    bp0 = sum(v[1] for v in fin.values()) / T if T else 1.0
    stock = defaultdict(lambda: {"q": 0.0, "wt": 0.0, "wf": 0.0})
    for r in c.execute("""SELECT sku, sum(coalesce(available,0)) q FROM oz_stocks WHERE account_id=%s
                          AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s) GROUP BY 1""", (shop, shop)):
        stock[r["sku"]]["q"] += float(r["q"] or 0)
    price = {r["sku"]: {"discounted_price": r["price"]} for r in c.execute(
        """SELECT p.sku, pr.price FROM oz_products p JOIN oz_prices pr ON pr.account_id=p.account_id AND pr.product_id=p.product_id
           WHERE p.account_id=%s AND p.sku IS NOT NULL""", (shop,))}
    from .sheets import ozv2
    return {"nom": nom, "day": {k: dict(v) for k, v in day.items()}, "bp": bp, "bp0": bp0, "stock": dict(stock), "fbs": {}, "price": price,
            "groups": lambda grp: ozv2._skus_of_group(c, shop, grp)}


def source(c, shop: int, mp: str, lo: date, end: date) -> dict:
    if mp == "ym":
        return _ym(c, shop, lo, end)
    if mp == "ozon":
        return _oz(c, shop, lo, end)
    raise ValueError(f"РНП для {mp} пока нет")

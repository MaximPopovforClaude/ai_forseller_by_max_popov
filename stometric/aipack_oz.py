"""Self-hosted application component."""

from collections import defaultdict
from datetime import timedelta

from .config import today_msk
from .sheets import ozv2

WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
KEYS = ("views", "clicks", "cart", "ordered", "ordered_sum", "sold_qty", "sold_amt", "ret_qty", "cost", "profit", "ads_filter",
        "commission", "svc_total", "st_av", "st_way", "st_money", "st_turn", "ad.spent", "ozz.spent")


def _ads(v) -> float:
    """Расход на рекламу (кампании + ОЗЗ) — и по SKU, и по магазину целиком."""
    return v["ad.spent"] + v["ozz.spent"]


def _r(x, n=0):
    return round(float(x or 0), n) if n else round(float(x or 0))


def _periods(y):
    return [("m30", y - timedelta(days=29), y), ("w1", y - timedelta(days=6), y), ("w0", y - timedelta(days=13), y - timedelta(days=7)),
            ("d1", y, y), ("d0", y - timedelta(days=1), y - timedelta(days=1)), ("d7", y - timedelta(days=7), y - timedelta(days=7))]


def per_sku(c, shop: int) -> tuple[dict, dict, dict]:
    """sku → {период → показатели}; итог магазина по периодам; названия. Те же расчёты, что в Version2."""
    y = today_msk() - timedelta(days=1)
    per = _periods(y)
    cc = ozv2.Cached(c)
    names = {r["sku"]: r for r in c.execute("SELECT sku, offer_id, name FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,))}
    skus = [r["sku"] for r in c.execute(
        """SELECT sku FROM oz_analytics WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1
           HAVING sum(coalesce((m->>'ordered_units')::numeric,0)) > 0
           UNION SELECT sku FROM oz_realization_day WHERE account_id=%s AND day BETWEEN %s AND %s AND sale_amount <> 0""",
        (shop, per[0][1], y, shop, per[0][1], y))]
    out = {}
    for sku in skus:
        r = ozv2.compute(cc, shop, "day", per[0][1], y, [sku], per=per)
        out[sku] = {p[0]: {k: float(v.get(k) or 0) for k in KEYS} for p, v in zip(per, r["cols"])}
    shop_tot = ozv2.compute(cc, shop, "day", per[0][1], y, None, per=per)
    tot = {p[0]: {k: float(v.get(k) or 0) for k in KEYS} for p, v in zip(per, shop_tot["cols"])}
    return out, tot, names


def _vc(names, sku):
    return (names.get(sku) or {}).get("offer_id") or str(sku)


def _stock_now(c, shop: int) -> dict:
    """sku → доступно + в пути (последний снимок Ozon)."""
    return {r["sku"]: float(r["q"] or 0) for r in c.execute(
        """SELECT sku, sum(coalesce(available,0) + coalesce((raw->>'transit_stock_count')::numeric,0)) q FROM oz_stocks
           WHERE account_id=%s AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s) GROUP BY 1""", (shop, shop))}


def money_leaks(c, shop: int, data=None) -> dict:
    nm, tot, names = data or per_sku(c, shop)
    y = today_msk() - timedelta(days=1)
    stock = _stock_now(c, shop)
    m = {s: v["m30"] for s, v in nm.items()}
    t = tot["m30"]
    loss, ads_eat, slow, oos, returns, no_cost = [], [], [], [], [], []
    for s, v in m.items():
        vc = _vc(names, s)
        ads = _ads(v)
        before = v["profit"] + ads
        if v["sold_qty"] and not v["cost"]:
            no_cost.append({"offer_id": vc, "sold_qty": _r(v["sold_qty"])})
            continue
        if v["profit"] < -300:
            loss.append({"offer_id": vc, "profit": _r(v["profit"]), "sales": _r(v["sold_amt"]), "sold_qty": _r(v["sold_qty"]),
                         "ads": _r(ads), "logistics": _r(-v["svc_total"]), "commission": _r(-v["commission"])})
        if ads > 3000 and before > 0 and ads > before * 0.6:
            ads_eat.append({"offer_id": vc, "ads": _r(ads), "margin_before_ads": _r(before), "profit": _r(v["profit"]),
                            "drr_sales_pct": _r(ads / v["sold_amt"] * 100, 1) if v["sold_amt"] else None})
        if v["st_money"] > 20000 and (v["st_turn"] > 90 or (not v["sold_qty"] and v["st_av"])):
            slow.append({"offer_id": vc, "stock_qty": _r(v["st_av"] + v["st_way"]), "stock_at_cost_rub": _r(v["st_money"]),
                         "turnover_days": _r(v["st_turn"]) if v["sold_qty"] else None, "sold_qty_30d": _r(v["sold_qty"])})
        if stock.get(s, None) == 0 and v["ordered"] >= 30 * 1.5:
            oos.append({"offer_id": vc, "orders_per_day": _r(v["ordered"] / 30, 1), "lost_per_day_rub": _r(v["ordered_sum"] / 30)})
        if v["sold_qty"] + v["ret_qty"] >= 20 and v["ret_qty"] / (v["sold_qty"] + v["ret_qty"]) > 0.1:
            returns.append({"offer_id": vc, "returns": _r(v["ret_qty"]), "sold_qty": _r(v["sold_qty"]),
                            "return_pct": _r(v["ret_qty"] / (v["sold_qty"] + v["ret_qty"]) * 100, 1)})
    return {"period": f"{y - timedelta(days=29):%d.%m}–{y:%d.%m}",
            "totals": {"orders_sum": _r(t["ordered_sum"]), "sales_minus_returns": _r(t["sold_amt"]), "profit": _r(t["profit"]),
                       "ads": _r(_ads(t)), "logistics": _r(-t["svc_total"]), "commission": _r(-t["commission"])},
            "unprofitable": sorted(loss, key=lambda x: x["profit"])[:10], "ads_eat_margin": sorted(ads_eat, key=lambda x: -x["ads"])[:10],
            "frozen_stock": sorted(slow, key=lambda x: -x["stock_at_cost_rub"])[:10],
            "out_of_stock": sorted(oos, key=lambda x: -x["lost_per_day_rub"])[:10],
            "high_returns": sorted(returns, key=lambda x: -x["return_pct"])[:10], "no_cost": sorted(no_cost, key=lambda x: -x["sold_qty"])[:10],
            "note": "Хранение на Ozon начисляется без привязки к артикулу - по SKU показываем стоимость остатка по себестоимости."}


def _pct(a, b):
    return _r((a / b - 1) * 100) if b else None


def _drops(nm, names, top, a, b, min_base):
    """Падение заказов и конверсий воронки по ключевым SKU: период a к периоду b."""
    orders, conv = [], []
    for s in top:
        x, z = nm[s][a], nm[s][b]
        vc = _vc(names, s)
        if z["ordered"] >= min_base and x["ordered"] < z["ordered"] * 0.75:
            orders.append({"offer_id": vc, "orders": _r(x["ordered"]), "orders_before": _r(z["ordered"]), "change_pct": _pct(x["ordered"], z["ordered"]),
                           "views": _r(x["views"]), "views_before": _r(z["views"])})
        for k, num, den, lab in (("ctr", "clicks", "views", "показы→клик"), ("cart", "cart", "clicks", "клик→корзина"),
                                 ("order", "ordered", "cart", "корзина→заказ")):
            if x[den] < 300 and k == "ctr" or x[den] < 50:
                continue
            cx, cz = (x[num] / x[den] if x[den] else None), (z[num] / z[den] if z[den] else None)
            if cx is not None and cz and cx < cz * 0.8:
                conv.append({"offer_id": vc, "step": lab, "now_pct": _r(cx * 100, 2), "before_pct": _r(cz * 100, 2)})
    return orders, conv


def _shop_line(t, a, b):
    return {k: {"now": _r(t[a][k]), "before": _r(t[b][k]), "change_pct": _pct(t[a][k], t[b][k])}
            for k in ("ordered", "ordered_sum", "views", "sold_amt", "profit") if t[b][k] or t[a][k]} |\
        {"ads": {"now": _r(_ads(t[a])), "before": _r(_ads(t[b])), "change_pct": _pct(_ads(t[a]), _ads(t[b]))}}


def cabinet_issues(c, shop: int, data=None) -> dict:
    nm, tot, names = data or per_sku(c, shop)
    y = today_msk() - timedelta(days=1)
    top_w = sorted(nm, key=lambda s: -nm[s]["w1"]["ordered_sum"])[:20]          
    top_d = sorted(nm, key=lambda s: -(nm[s]["d0"]["ordered_sum"] + nm[s]["d7"]["ordered_sum"]))[:20]
    w_orders, w_conv = _drops(nm, names, top_w, "w1", "w0", 20)
    d_orders, d_conv = _drops(nm, names, top_d, "d1", "d0", 5)
    d7_orders, _ = _drops(nm, names, top_d, "d1", "d7", 5)

    
    low = []
    for r in c.execute("""SELECT sku, cluster, sum(coalesce(available,0)) a, sum(coalesce((raw->>'transit_stock_count')::numeric,0)) o,
                                 avg((raw->>'ads_cluster')::numeric) ads FROM oz_stocks
                          WHERE account_id=%s AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s) GROUP BY 1,2""", (shop, shop)):
        ads = float(r["ads"] or 0)
        if r["sku"] in top_w and ads >= 0.5:
            days = (float(r["a"] or 0) + float(r["o"] or 0)) / ads
            if days < 14:
                low.append({"offer_id": _vc(names, r["sku"]), "cluster": r["cluster"], "stock": _r(r["a"]), "in_transit": _r(r["o"]),
                            "sales_per_day": _r(ads, 1), "days_left": _r(days, 1)})
    low.sort(key=lambda x: x["days_left"])

    
    spend = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""SELECT campaign_id, day, spent, orders FROM oz_ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s""",
                       (shop, y - timedelta(days=13), y)):
        w = "w1" if r["day"] > y - timedelta(days=7) else "w0"
        spend[r["campaign_id"]][w] += float(r["spent"] or 0)
        spend[r["campaign_id"]][w + "_orders"] += float(r["orders"] or 0)
        if r["day"] == y:
            spend[r["campaign_id"]]["d1"] += float(r["spent"] or 0)
    stopped, autostop, no_orders = [], [], []
    for r in c.execute("SELECT campaign_id, title, state, kind, skus, raw FROM oz_ad_campaigns WHERE account_id=%s AND kind NOT IN ('Блогеры','VK')", (shop,)):
        sp = spend.get(r["campaign_id"]) or {}
        on_top = [_vc(names, s) for s in (r["skus"] or []) if s in top_w][:5]
        if r["state"] != "CAMPAIGN_STATE_RUNNING" and sp.get("w0", 0) > 1000 and sp.get("d1", 0) == 0 and on_top:
            stopped.append({"campaign": r["title"], "type": r["kind"], "spent_prev_week": _r(sp["w0"]), "spent_this_week": _r(sp.get("w1")),
                            "articles": on_top})
        a = str((r["raw"] or {}).get("autostopStatus") or "AUTOSTOP_STATUS_NONE")
        if r["state"] == "CAMPAIGN_STATE_RUNNING" and a != "AUTOSTOP_STATUS_NONE":
            autostop.append({"campaign": r["title"], "type": r["kind"], "autostop": a})
        if sp.get("w1", 0) > 2000 and not sp.get("w1_orders"):
            no_orders.append({"campaign": r["title"], "type": r["kind"], "spent_week": _r(sp["w1"])})
    return {"week": f"{y - timedelta(days=6):%d.%m}–{y:%d.%m}", "prev_week": f"{y - timedelta(days=13):%d.%m}–{y - timedelta(days=7):%d.%m}",
            "yesterday": f"{y:%d.%m}, {WEEKDAYS[y.weekday()]}", "day_before": f"{y - timedelta(days=1):%d.%m}", "same_day_last_week": f"{y - timedelta(days=7):%d.%m}",
            "note": "Заказы (ordered) - по дате заказа; продажи и прибыль (sold_amt, profit) - по начислениям Ozon после доставки, "
                    "отстают от заказов на срок доставки. Рост заказов при падении продаж за неделю - чаще всего этот сдвиг, а не потери.",
            "weekly": {"shop": _shop_line(tot, "w1", "w0"), "orders_drop": w_orders, "conversion_drop": w_conv[:10]},
            "daily": {"shop_vs_day_before": _shop_line(tot, "d1", "d0"), "shop_vs_same_day_last_week": _shop_line(tot, "d1", "d7"),
                      "orders_drop_vs_day_before": d_orders, "orders_drop_vs_same_day_last_week": d7_orders, "conversion_drop": d_conv[:10]},
            "low_stock_clusters": low[:15], "ads_stopped_on_top": stopped[:10], "ads_autostop": autostop[:10],
            "ads_spend_no_orders_week": sorted(no_orders, key=lambda x: -x["spent_week"])[:10],
            "ad_items_week": _ad_items(c, shop, y)}


def _ad_items(c, shop, y):
    """Товары в кампаниях: расход без продаж и дорогие продажи за неделю (tabs/ozads.ad_problems)."""
    from .tabs.ozads import ad_problems
    try:
        return ad_problems(c, shop, y - timedelta(days=6), y)
    except Exception as e:  
        c.rollback()
        return {"error": str(e)[:100]}


def search_pack(c, shop: int, data=None) -> dict:
    nm, _, names = data or per_sku(c, shop)
    mx = c.execute("SELECT max(day) d FROM oz_queries WHERE account_id=%s", (shop,)).fetchone()["d"]
    if not mx:
        return {"error": "Нет данных «Продажи по запросам»"}
    top = set(sorted(nm, key=lambda s: -nm[s]["m30"]["ordered_sum"])[:20])
    q = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""SELECT day, sku, query, position, searchers, viewers, conv, orders, gmv FROM oz_queries
                          WHERE account_id=%s AND day BETWEEN %s AND %s""", (shop, mx - timedelta(days=13), mx)):
        if r["sku"] not in top:
            continue
        w = "w1" if r["day"] > mx - timedelta(days=7) else "w0"
        d = q[(r["sku"], r["query"])]
        d[w + "_pos"] += float(r["position"] or 0)
        d[w + "_n"] += 1
        d[w + "_search"] += float(r["searchers"] or 0)
        d[w + "_view"] += float(r["viewers"] or 0)
        d[w + "_orders"] += float(r["orders"] or 0)
        d[w + "_gmv"] += float(r["gmv"] or 0)
        d[w + "_convw"] += float(r["conv"] or 0) * float(r["viewers"] or 0)
    pos_drop, weak = [], []
    for (s, qq), d in q.items():
        if d["w1_n"] and d["w0_n"]:
            p1, p0 = d["w1_pos"] / d["w1_n"], d["w0_pos"] / d["w0_n"]
            if p1 > p0 * 1.3 and p1 - p0 >= 5 and d["w1_search"] >= 500:
                pos_drop.append({"offer_id": _vc(names, s), "query": qq, "avg_position_week": _r(p1), "avg_position_prev_week": _r(p0),
                                 "searchers_week": _r(d["w1_search"]), "orders_week": _r(d["w1_orders"]), "orders_prev_week": _r(d["w0_orders"])})
        if d["w1_search"] >= 2000 and d["w1_view"]:
            weak.append({"offer_id": _vc(names, s), "query": qq, "searchers_week": _r(d["w1_search"]), "viewers_week": _r(d["w1_view"]),
                         "avg_position": _r(d["w1_pos"] / d["w1_n"]) if d["w1_n"] else None, "orders_week": _r(d["w1_orders"]),
                         "conv_pct": _r(d["w1_convw"] / d["w1_view"], 2)})
    weak = sorted([w for w in weak if w["orders_week"] <= 2], key=lambda x: -x["searchers_week"])[:10]
    best = sorted(({"offer_id": _vc(names, s), "query": qq, "orders_week": _r(d["w1_orders"]), "gmv_week": _r(d["w1_gmv"]),
                    "avg_position": _r(d["w1_pos"] / d["w1_n"]) if d["w1_n"] else None} for (s, qq), d in q.items() if d["w1_orders"]),
                  key=lambda x: -x["gmv_week"])[:8]

    
    ph = c.execute("""SELECT sku, lower(phrase) phrase, sum(clicks) clicks, sum(views) views FROM oz_ad_phrases
                      WHERE account_id=%s AND day > %s GROUP BY 1,2 HAVING sum(clicks) >= 30 ORDER BY 3 DESC""",
                   (shop, mx - timedelta(days=7))).fetchall()
    qo = {(s, qq.lower()): d for (s, qq), d in q.items()}
    idle = []
    for r in ph:
        d = qo.get((r["sku"], r["phrase"]))
        if d is not None and not d["w1_orders"]:
            idle.append({"offer_id": _vc(names, r["sku"]), "phrase": r["phrase"], "ad_clicks_week": _r(r["clicks"]), "ad_views_week": _r(r["views"]),
                         "orders_by_query_week": 0})
    return {"week": f"{mx - timedelta(days=6):%d.%m}–{mx:%d.%m}", "prev_week": f"{mx - timedelta(days=13):%d.%m}–{mx - timedelta(days=7):%d.%m}",
            "note": "Позиция - среднее место в выдаче (меньше - выше). Данные Ozon по запросам приходят с задержкой 1-2 дня.",
            "position_drop": sorted(pos_drop, key=lambda x: -x["searchers_week"])[:10], "big_demand_weak_sales": weak,
            "best_queries": best, "ad_phrases_no_orders": idle[:10]}

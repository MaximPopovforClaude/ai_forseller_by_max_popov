"""Self-hosted application component."""

from collections import defaultdict
from datetime import timedelta

from . import rnp
from .config import today_msk

F = rnp.F + ["f_open", "f_cart", "ad_clicks", "rating", "buyouts_sum", "orders_sum_spp"]


def _d(a, b):
    a, b = float(a or 0), float(b or 0)
    return a / b if b else None


def compute(c, shop: int, nm: int, d_from, d_to) -> dict:
    from .agg import nm_day
    from .materialize import ensure_ready
    end = min(d_to, today_msk())
    lo = d_from - timedelta(days=14)            
    st = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (shop,)).fetchone()
    if not st or not st["covered_to"]:
        ensure_ready(c, shop, False)
    keys = sorted(set(F))
    sel = ", ".join(f"(data->>'{k}')::numeric {k}" for k in keys)
    day = {r["day"]: r for r in c.execute(f"SELECT day, {sel} FROM agg_nm_day WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s",
                                          (shop, nm, lo, end))}
    if st and st["covered_to"] and end > st["covered_to"]:
        for r in nm_day.compute(c, shop, st["covered_to"] + timedelta(days=1), end):    
            if r["nm_id"] == nm:
                day[r["day"]] = {k: r.get(k) for k in keys}
    
    bid = {}     
    for r in c.execute("SELECT (data->>'advertId')::bigint id, data->'info'->>'bid_type' bt FROM raw_rows WHERE account_id=%s AND source='adverts'",
                       (shop,)):
        bid[r["id"]] = "a" if r["bt"] == "unified" else "p"
    ad = defaultdict(lambda: {f"{t}_{k}": 0.0 for t in "aps" for k in ("views", "clicks", "sum")})
    
    
    pos = defaultdict(lambda: [0.0, 0.0])
    for r in c.execute("""SELECT day, advert_id, sum(views) v, sum(clicks) cl, sum(spend) s, sum(avg_pos * views) pv
                          FROM wb_ad_kw_daily WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s GROUP BY 1, 2""", (shop, nm, lo, end)):
        if bid.get(r["advert_id"]) == "a":
            x = ad[r["day"]]
            x["s_views"] += float(r["v"] or 0); x["s_clicks"] += float(r["cl"] or 0); x["s_sum"] += float(r["s"] or 0)
        if r["pv"] and r["v"]:
            pos[r["day"]][0] += float(r["pv"]); pos[r["day"]][1] += float(r["v"])
    for r in c.execute("""SELECT row_date d, (data->>'advertId')::bigint id, n
                          FROM raw_rows, jsonb_array_elements(data->'apps') a, jsonb_array_elements(a->'nms') n
                          WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s AND (n->>'nmId')::bigint=%s""",
                       (shop, lo, end, nm)):
        t = bid.get(r["id"], "p")
        x = ad[r["d"]]
        x[t + "_views"] += float(r["n"].get("views") or 0)
        x[t + "_clicks"] += float(r["n"].get("clicks") or 0)
        x[t + "_sum"] += float(r["n"].get("sum") or 0)
    low = {r["d"]: r["n"] for r in c.execute(
        """SELECT (created_at AT TIME ZONE 'Europe/Moscow')::date d, count(*) n FROM wb_feedbacks
           WHERE account_id=%s AND nm_id=%s AND valuation <= 3 AND created_at >= %s GROUP BY 1""", (shop, nm, lo))}
    ext = defaultdict(lambda: {"ext_sum": 0.0, "ext_clicks": 0.0, "ext_src": [], "give_qty": 0.0, "give_sum": 0.0})
    for e in c.execute("SELECT * FROM ext_costs WHERE account_id=%s AND nm_id=%s AND coalesce(d_to, d_from) >= %s AND d_from <= %s",
                       (shop, nm, lo, end)):
        a, z = e["d_from"], e["d_to"] or e["d_from"]
        n = (z - a).days + 1
        for i in range(n):
            x = ext[a + timedelta(days=i)]
            if e["kind"] == "giveaway":
                x["give_qty"] += float(e["qty"] or 0) / n; x["give_sum"] += float(e["cost"] or 0) / n
            else:
                x["ext_sum"] += float(e["cost"] or 0) / n; x["ext_clicks"] += float(e["clicks"] or 0) / n
                if e["source"] and e["source"] not in x["ext_src"]:
                    x["ext_src"].append(e["source"])
    
    ev = defaultdict(lambda: {k: 0.0 for k in ("cx_n", "cx_sum", "rt_n", "rt_sum", "ob_n", "ob_sum", "oc_n", "oc_sum", "or_n", "or_sum", "o_n")})
    for r in c.execute("""SELECT (cancel_dt AT TIME ZONE 'Europe/Moscow')::date d, count(*) n, sum(price_with_disc) s FROM orders
                          WHERE account_id=%s AND nm_id=%s AND is_cancel AND cancel_dt >= %s GROUP BY 1""", (shop, nm, lo)):
        ev[r["d"]]["cx_n"], ev[r["d"]]["cx_sum"] = float(r["n"]), float(r["s"] or 0)
    for r in c.execute("""SELECT sale_dt::date d, count(*) n, sum(price_with_disc) s FROM sales WHERE account_id=%s AND nm_id=%s
                          AND sale_id LIKE 'R%%' AND sale_dt >= %s GROUP BY 1""", (shop, nm, lo)):
        ev[r["d"]]["rt_n"], ev[r["d"]]["rt_sum"] = float(r["n"]), float(r["s"] or 0)
    for r in c.execute("""SELECT o.order_dt::date d, count(*) n,
                                 count(*) FILTER (WHERE o.is_cancel) cn, sum(o.price_with_disc) FILTER (WHERE o.is_cancel) cs,
                                 count(*) FILTER (WHERE NOT o.is_cancel AND s.b) bn, sum(o.price_with_disc) FILTER (WHERE NOT o.is_cancel AND s.b) bs,
                                 count(*) FILTER (WHERE NOT o.is_cancel AND s.r) rn, sum(o.price_with_disc) FILTER (WHERE NOT o.is_cancel AND s.r) rs
                          FROM orders o LEFT JOIN LATERAL (SELECT bool_or(sale_id LIKE 'S%%') AND NOT bool_or(sale_id LIKE 'R%%') b,
                                                                 bool_or(sale_id LIKE 'R%%') r
                                                          FROM sales x WHERE x.account_id=o.account_id AND x.srid=o.srid) s ON true
                          WHERE o.account_id=%s AND o.nm_id=%s AND o.order_dt >= %s GROUP BY 1""", (shop, nm, lo)):
        x = ev[r["d"]]
        x.update({"o_n": float(r["n"]), "oc_n": float(r["cn"] or 0), "oc_sum": float(r["cs"] or 0), "ob_n": float(r["bn"] or 0),
                  "ob_sum": float(r["bs"] or 0), "or_n": float(r["rn"] or 0), "or_sum": float(r["rs"] or 0)})
    stock = {}
    for r in c.execute("""SELECT DISTINCT ON (snap_at::date) snap_at::date d, snap_at FROM stocks_wb_snap WHERE account_id=%s
                          AND snap_at::date BETWEEN %s AND %s ORDER BY snap_at::date, snap_at DESC""", (shop, lo, end)):
        s = c.execute("""SELECT sum(quantity) q, sum(in_way_to_client) wt, sum(in_way_from_client) wf FROM stocks_wb_snap
                         WHERE account_id=%s AND snap_at=%s AND nm_id=%s""", (shop, r["snap_at"], nm)).fetchone()
        stock[r["d"]] = s
    bp_all, bp0 = rnp.buyout_pct(c, shop)
    b = bp_all.get(nm, bp0)
    tx = rnp._tax(c, shop, end)
    
    sr = c.execute("""SELECT sum(e.orders) FILTER (WHERE e.section='Поиск') s, sum(e.orders) t FROM entry_rows e
                      JOIN entry_reports r ON r.id=e.report_id WHERE r.account_id=%s AND e.nm_id=%s
                      AND r.id=(SELECT id FROM entry_reports WHERE account_id=%s ORDER BY d_to DESC, d_from LIMIT 1)""", (shop, nm, shop)).fetchone()
    search_share = float(sr["s"]) / float(sr["t"]) if sr and sr["t"] else None
    unit_price = c.execute("""SELECT cost FROM cost_price WHERE account_id=%s AND nm_id=%s AND valid_from <= %s ORDER BY valid_from DESC LIMIT 1""",
                           (shop, nm, end)).fetchone()
    unit_cost0 = float(unit_price["cost"]) if unit_price else None
    hyp = c.execute("""SELECT indicator, text, kind, d_from, coalesce(days, 1) days FROM hypotheses WHERE account_id=%s AND nm_id=%s
                       AND d_from <= %s ORDER BY d_from""", (shop, nm, end)).fetchall()
    rows = []
    d = end
    while d >= d_from:
        r = day.get(d) or {}
        g = lambda k: float(r.get(k) or 0)  
        prev = day.get(d - timedelta(days=1)) or {}
        S = {k: r.get(k) for k in rnp.F}
        p_with = rnp.profit(S, b, tx)
        p_pre = rnp.profit({**S, "ads_upd": 0}, b, tx)
        r15 = g("orders_sum") * b
        a = ad.get(d) or {}
        x = ext.get(d) or {}
        e = ev.get(d) or {}
        p_with -= float(x.get("ext_sum") or 0)                    
        ads = g("ads_upd") + float(x.get("ext_sum") or 0)       
        ad_cl = a.get("a_clicks", 0) + a.get("p_clicks", 0)          
        ad_sum = a.get("a_sum", 0) + a.get("p_sum", 0)
        speed = sum(float((day.get(d - timedelta(days=i)) or {}).get("orders") or 0) for i in range(14)) / 14
        s = stock.get(d) or {}
        q, wt, wf = s.get("q"), s.get("wt"), s.get("wf")
        hs = [h for h in hyp if h["d_from"] <= d < h["d_from"] + timedelta(days=h["days"])]
        rows.append({
            "day": d.isoformat(),
            "hyp_ind": "; ".join(h["indicator"] or "" for h in hs) or None, "hyp": "; ".join(h["text"] for h in hs) or None,
            "clicks": g("f_open") or None, "clicks_dyn": (g("f_open") / float(prev.get("f_open")) - 1) if prev.get("f_open") else None,
            "organic": 1 - min(1.0, ad_cl / g("f_open")) if g("f_open") else None,
            "a_views": a.get("a_views") or None, "p_views": a.get("p_views") or None,
            "avg_pos": round(pos[d][0] / pos[d][1], 1) if pos.get(d) and pos[d][1] else None,
            "a_clicks": a.get("a_clicks"), "a_ctr": _d(a.get("a_clicks"), a.get("a_views")), "a_cpc": _d(a.get("a_sum"), a.get("a_clicks")),
            "a_cpm": _d(a.get("a_sum", 0) * 1000, a.get("a_views")), "a_sum": a.get("a_sum"),
            "p_clicks": a.get("p_clicks"), "p_ctr": _d(a.get("p_clicks"), a.get("p_views")), "p_cpc": _d(a.get("p_sum"), a.get("p_clicks")),
            "p_cpm": _d(a.get("p_sum", 0) * 1000, a.get("p_views")), "p_sum": a.get("p_sum"),
            "s_clicks": a.get("s_clicks"), "s_ctr": _d(a.get("s_clicks"), a.get("s_views")), "s_cpc": _d(a.get("s_sum"), a.get("s_clicks")),
            "s_cpm": _d(a.get("s_sum", 0) * 1000, a.get("s_views")), "s_sum": a.get("s_sum"),
            "ext_clicks": x.get("ext_clicks") or None, "ext_sum": x.get("ext_sum") or None, "ext_src": ", ".join(x.get("ext_src") or []) or None,
            "a_share": _d(a.get("a_sum"), ad_sum), "drr": _d(ads, g("orders_sum")), "ads": ads or None,
            "bonus": g("ads_bonus") or None, "drr_bonus": _d(g("ads_bonus"), g("orders_sum")) if g("ads_bonus") else None,
            "drr_all": _d(ads + g("ads_bonus"), g("orders_sum")) if g("ads_bonus") else None,
            "low_reviews": low.get(d, 0), "rating": r.get("rating"), "local": r.get("local_share"),
            "to_client": wt, "from_client": wf,
            "ret_plan": round(float(wt or 0) * (1 - b) + float(wf or 0)) if wt is not None else None,
            "stock_total": (float(q or 0) + float(wt or 0) * (1 - b) + float(wf or 0)) if q is not None else None,
            "stock_rub": (float(q or 0) + float(wt or 0) * (1 - b) + float(wf or 0)) * unit_cost0 if q is not None and unit_cost0 else None,
            "speed14": round(speed, 2), "stock": q, "days_left": int(float(q) / speed) if q is not None and speed else None,
            "carts": g("f_cart") or None, "cart_cost": _d(ads, g("f_cart")), "cart_rate": _d(g("f_cart"), g("f_open")),
            "orders_sum": g("orders_sum") or None, "orders": g("orders") or None, "order_cost": _d(ads, g("orders")),
            "order_rate": _d(g("orders"), g("f_cart")),
            "give_qty": x.get("give_qty") or None, "give_sum": x.get("give_sum") or None,
            "buyouts_sum": g("buyouts_sum_before_spp") or None, "buyouts": g("buyouts") or None,
            "cx_sum": e.get("cx_sum") or None, "cx_n": e.get("cx_n") or None, "rt_sum": e.get("rt_sum") or None, "rt_n": e.get("rt_n") or None,
            "bp": b, "bp_day": _d(e.get("ob_sum"), (e.get("ob_sum") or 0) + (e.get("oc_sum") or 0) + (e.get("or_sum") or 0)),
            "ob_sum": e.get("ob_sum") or None, "ob_n": e.get("ob_n") or None, "oc_sum": e.get("oc_sum") or None, "oc_n": e.get("oc_n") or None,
            "or_sum": e.get("or_sum") or None, "or_n": e.get("or_n") or None,
            "done": _d((e.get("ob_n") or 0) + (e.get("oc_n") or 0) + (e.get("or_n") or 0), e.get("o_n")),
            "cr": _d(g("orders"), g("f_open")),
            "price": _d(g("orders_sum"), g("orders")), "spp": 1 - g("orders_sum_spp") / g("orders_sum") if g("orders_sum") else None,
            "price_spp": _d(g("orders_sum_spp"), g("orders")),
            "unit_cost": _d(g("orders_sum"), g("orders")) * (1 - p_pre / r15) if r15 and g("orders") else None,
            
            "u_cost": _d(g("cost_orders"), g("orders")), "u_comm": _d(g("commission_offer_orders"), g("orders")),
            "u_log": _d(g("logistics_orders"), g("orders") * b), "u_storage": _d(g("storage"), g("orders") * b),
            "u_accept": _d(g("acceptance_sum"), g("orders") * b), "u_vat": _d(g("vat_orders"), g("orders")),
            "sh_clicks": max(0.0, (a.get("a_clicks") or 0) - (a.get("s_clicks") or 0)) or None,
            "sh_sum": max(0.0, (a.get("a_sum") or 0) - (a.get("s_sum") or 0)) or None,
            "sh_cpc": _d(max(0.0, (a.get("a_sum") or 0) - (a.get("s_sum") or 0)), max(0.0, (a.get("a_clicks") or 0) - (a.get("s_clicks") or 0))),
            "order_cost_search": _d((a.get("s_sum") or 0) + (a.get("p_sum") or 0), g("orders") * search_share) if search_share else None,
            "order_cost_shelf": _d(max(0.0, (a.get("a_sum") or 0) - (a.get("s_sum") or 0)), g("orders") * (1 - search_share))
                                if search_share is not None and search_share < 1 and (a.get("a_sum") or 0) > (a.get("s_sum") or 0) else None,
            "margin_pre": _d(p_pre, r15), "margin": _d(p_with, r15), "profit_pre": round(p_pre) if r15 else None,
            "profit": round(p_with) if r15 else None, "kem": _d(p_with, p_pre) if p_pre > 0 else None,
        })
        d -= timedelta(days=1)
    return {"rows": rows, "bp": b}


GROUPS = [  
    ("", [("day", "Дата", "date")]),
    ("Гипотезы", [("hyp_ind", "Тест показателя", "text"), ("hyp", "Гипотеза", "text")]),
    ("Трафик", [("clicks", "Кликов", "int"), ("clicks_dyn", "Дин", "pct"), ("organic", "% орг.", "pct"), ("avg_pos", "Сред. позиция (реклама)", "num")]),
    ("АРК (единая ставка)", [("a_views", "Показов АРК", "int"), ("a_clicks", "Кликов АРК", "int"), ("a_ctr", "CTR АРК", "pct"), ("a_cpc", "CPC", "money"),
                             ("a_cpm", "CPM АРК", "money"), ("a_sum", "Расходы АРК", "money")]),
    ("ПРК (ручная ставка)", [("p_views", "Показов ПРК", "int"), ("p_clicks", "Кликов ПРК", "int"), ("p_ctr", "CTR ПРК", "pct"), ("p_cpc", "CPC", "money"),
                             ("p_cpm", "CPM ПРК", "money"), ("p_sum", "Расходы ПРК", "money")]),
    ("Каталог + полки АРК (расчёт)", [("sh_clicks", "Кликов полки", "int"), ("sh_cpc", "CPC полки", "money"), ("sh_sum", "Расход полки", "money"),
                                      ("order_cost_shelf", "Цена заказа полок", "money")]),
    ("Поиск в АРК", [("order_cost_search", "Цена заказа поиска", "money"), ("s_clicks", "Кликов П. АРК", "int"), ("s_cpc", "CPC П. АРК", "money"), ("s_ctr", "CTR П. АРК", "pct"),
                     ("s_cpm", "CPM П. АРК", "money"), ("s_sum", "Расход П. АРК", "money")]),
    ("Внешняя реклама", [("ext_clicks", "Внешка клики", "int"), ("ext_sum", "Внешка расходы", "money"), ("ext_src", "Внешка источники", "text")]),
    ("Реклама", [("a_share", "Доля АРК в расходах", "pct"), ("drr", "ДРР", "pct"), ("ads", "ДРР, ₽", "money"),
                 ("bonus", "Бонусы (Кэшбэк), ₽", "money"), ("drr_bonus", "ДРР бонусами", "pct"), ("drr_all", "ДРР всего (с бонусами)", "pct")]),
    ("Карточка", [("low_reviews", "Ниже 3 из 5, шт", "int"), ("rating", "Рейтинг", "num"), ("local", "% Лок.", "pct")]),
    ("Остатки", [("to_client", "Едет к клиенту", "int"), ("from_client", "Едет от клиента", "int"), ("ret_plan", "План возврата", "int"),
                 ("stock_total", "Итого в остатках", "int"), ("stock_rub", "Итого в остатках, ₽ (по с/с)", "money"),
                 ("speed14", "Скор. прод 14Д", "num"), ("stock", "Остатки", "int"), ("days_left", "Хватит на, дн", "int")]),
    ("Корзины", [("carts", "Корзин, шт", "int"), ("cart_cost", "Цена корз.", "money"), ("cart_rate", "% корз", "pct")]),
    ("Заказы", [("orders_sum", "Заказов, ₽", "money"), ("orders", "Заказов, шт", "int"), ("order_cost", "Цена заказа", "money"),
                ("order_rate", "% заказ", "pct")]),
    ("Раздачи", [("give_qty", "Раздачи, шт", "num"), ("give_sum", "Затраты на раздачи", "money"), ("cr", "CR карт", "pct")]),
    ("Выкупы, отмены, возвраты (в день события)", [("buyouts_sum", "Выкупы, ₽", "money"), ("buyouts", "Выкупы, шт", "int"),
                                                   ("cx_sum", "Отмены, ₽", "money"), ("cx_n", "Отмены, шт", "int"),
                                                   ("rt_sum", "Возвраты, ₽", "money"), ("rt_n", "Возвраты, шт", "int"),
                                                   ("bp", "% выкупа (4 нед.)", "pct"), ("bp_day", "% выкупа за день", "pct")]),
    ("Заказы дня — чем закончились", [("ob_sum", "Выкупы, ₽", "money"), ("ob_n", "Выкупы, шт", "int"), ("oc_sum", "Отмены, ₽", "money"),
                                      ("oc_n", "Отмены, шт", "int"), ("or_sum", "Возвраты, ₽", "money"), ("or_n", "Возвраты, шт", "int"),
                                      ("done", "Завершено", "pct")]),
    ("Расходы на 1 шт", [("u_cost", "Себестоимость", "money"), ("u_comm", "Комиссия WB", "money"), ("u_log", "Логистика", "money"),
                        ("u_storage", "Хранение", "money"), ("u_accept", "Приёмка", "money"), ("u_vat", "НДС", "money"), ("unit_cost", "Всего на шт", "money")]),
    ("Цена", [("price", "Цена без СПП", "money"), ("spp", "СПП", "pct"), ("price_spp", "Цена с СПП", "money")]),
    ("Прибыль (расчётная)", [("margin_pre", "Маржа до ДРР", "pct"), ("margin", "Маржа с ДРР", "pct"), ("profit_pre", "Прибыль до ДРР", "money"),
                             ("profit", "Прибыль с ДРР", "money"), ("kem", "КЭМ", "pct")]),
]
BONUS_FIELDS = {"bonus", "drr_bonus", "drr_all"}   
SUM = {"sh_clicks", "sh_sum", "clicks", "a_views", "p_views", "a_clicks", "a_sum", "p_clicks", "p_sum", "s_clicks", "s_sum", "ext_clicks", "ext_sum", "ads", "low_reviews", "carts",
       "orders_sum", "orders", "give_qty", "give_sum", "buyouts_sum", "buyouts", "cx_sum", "cx_n", "rt_sum", "rt_n", "ob_sum", "ob_n",
       "oc_sum", "oc_n", "or_sum", "or_n", "profit_pre", "profit", "bonus"}
HEAT = ["clicks", "a_clicks", "p_clicks", "s_clicks", "carts", "orders", "orders_sum", "profit", "profit_pre", "speed14", "organic", "cart_rate",
        "order_rate", "cr", "margin", "kem", "bp_day"]


MAX_FIELDS = [("a_cpc", "Цена клика АРК, ₽"), ("p_cpc", "Цена клика ПРК, ₽"), ("drr", "ДРР, %"), ("cart_cost", "Цена корзины, ₽"),
              ("order_cost", "Цена заказа, ₽")]
CUT = "Снизьте ставки CPM, почистите кластеры, сузьте количество продвигаемых нерелевантных кластеров"


def auto_max(t: dict) -> dict:
    """MAX «в ноль» (видео 10X №5: рассчитываются из юнит-экономики по конверсиям карточки): цена заказа = прибыль до рекламы на 1 заказ,
    цена корзины = цена заказа × конверсия корзина→заказ, цена клика = цена корзины × конверсия клик→корзина, ДРР = прибыль до рекламы / заказы ₽."""
    po = t["profit_pre"] / t["orders"] if t.get("orders") and t.get("profit_pre") else None
    cart = po * t["order_rate"] if po and t.get("order_rate") else None
    cpc = cart * t["cart_rate"] if cart and t.get("cart_rate") else None
    drr = t["profit_pre"] / t["orders_sum"] * 100 if t.get("orders_sum") and t.get("profit_pre") else None
    r = lambda v, k=2: round(v, k) if v is not None and v > 0 else None  
    return {"order_cost": r(po), "cart_cost": r(cart), "a_cpc": r(cpc), "p_cpc": r(cpc), "drr": r(drr)}


def dangers(t3: dict, mx: dict) -> list[dict]:
    out = []
    def add(ind, prob, hyp):
        out.append({"indicator": ind, "problem": prob, "hypothesis": hyp})
    if mx.get("a_cpc") and (t3.get("a_cpc") or 0) > mx["a_cpc"]:
        add("Цена клика", "Превышение MAX цены клика АРК за крайние 3 дня", "Снизьте ставки CPM АРК")
    if mx.get("p_cpc") and (t3.get("p_cpc") or 0) > mx["p_cpc"]:
        add("Цена клика", "Превышение MAX цены клика ПРК за крайние 3 дня", "Снизьте ставки CPM ПРК")
    if mx.get("drr") and (t3.get("drr") or 0) > mx["drr"] / 100:
        add("ДРР", "Превышение MAX ДРР за крайние 3 дня", CUT)
    if t3.get("local") is not None and t3["local"] < 0.4:
        add("Локализация", "% локализации менее 40 %", "Срочная допоставка, теряете продажи из-за отсутствия товаров на складах")
    if mx.get("cart_cost") and (t3.get("cart_cost") or 0) > mx["cart_cost"]:
        add("Цена корзины", "Превышение MAX цены корзины за крайние 3 дня", CUT)
    if mx.get("order_cost") and (t3.get("order_cost") or 0) > mx["order_cost"]:
        add("Цена заказа", "Превышение MAX цены заказа за крайние 3 дня", CUT)
    if t3.get("margin") is not None and t3["margin"] < 0.15:
        add("Маржа", "Маржинальность менее 15 % крайние 3 дня", "Повышайте цену, сокращайте себестоимость или распродавайте товар")
    if t3.get("kem") is not None and t3["kem"] < 0.5:
        add("КЭМ", "КЭМ ниже 50 % крайние 3 дня", "Оптимизируйте запросы через Джем. Оставьте только АРК или ПРК. Снизьте ставки CPM")
    return out


def total(rows: list[dict]) -> dict:
    """Строка «ИТОГО» периода: суммы, доли — по формулам из сумм (а не среднее процентов)."""
    t = {k: sum(float(r[k] or 0) for r in rows) for k in SUM}
    f = lambda a, b: a / b if b else None  
    a_v = t["a_views"]
    p_v = t["p_views"]
    s_v = sum(float(r["s_clicks"] or 0) / r["s_ctr"] for r in rows if r["s_ctr"])
    r15 = sum(float(r["orders_sum"] or 0) * float(r["bp"] or 0) for r in rows)
    t.update({"day": "ИТОГО", "organic": 1 - f(t["a_clicks"] + t["p_clicks"], t["clicks"]) if t["clicks"] else None,
              "a_ctr": f(t["a_clicks"], a_v), "a_cpc": f(t["a_sum"], t["a_clicks"]), "a_cpm": f(t["a_sum"] * 1000, a_v),
              "p_ctr": f(t["p_clicks"], p_v), "p_cpc": f(t["p_sum"], t["p_clicks"]), "p_cpm": f(t["p_sum"] * 1000, p_v),
              "s_ctr": f(t["s_clicks"], s_v), "s_cpc": f(t["s_sum"], t["s_clicks"]), "s_cpm": f(t["s_sum"] * 1000, s_v),
              "local": (sum(float(r["local"] or 0) * float(r["orders"] or 0) for r in rows) / t["orders"]) if t["orders"] else None,
              "bp_day": f(t["ob_sum"], t["ob_sum"] + t["oc_sum"] + t["or_sum"]),
              "done": f(t["ob_n"] + t["oc_n"] + t["or_n"], sum(float(r["orders"] or 0) for r in rows)),
              "a_share": f(t["a_sum"], t["a_sum"] + t["p_sum"]), "drr": f(t["ads"], t["orders_sum"]),
              "cart_cost": f(t["ads"], t["carts"]), "cart_rate": f(t["carts"], t["clicks"]), "order_cost": f(t["ads"], t["orders"]),
              "order_rate": f(t["orders"], t["carts"]), "cr": f(t["orders"], t["clicks"]), "price": f(t["orders_sum"], t["orders"]),
              "margin_pre": f(t["profit_pre"], r15), "margin": f(t["profit"], r15), "kem": f(t["profit"], t["profit_pre"]) if t["profit_pre"] > 0 else None,
              "drr_bonus": f(t["bonus"], t["orders_sum"]) if t["bonus"] else None,
              "drr_all": f(t["ads"] + t["bonus"], t["orders_sum"]) if t["bonus"] else None,
              "bp": rows[0]["bp"] if rows else None, "rating": rows[0]["rating"] if rows else None, "stock": rows[0]["stock"] if rows else None,
              "speed14": rows[0]["speed14"] if rows else None, "days_left": rows[0]["days_left"] if rows else None})
    return t






def _abc_cum(vals: dict) -> dict:
    tot = sum(v for v in vals.values() if v > 0)
    out, acc = {}, 0.0
    for nm, v in sorted(vals.items(), key=lambda x: -x[1]):
        if v <= 0 or not tot:
            out[nm] = "C"
            continue
        acc += v
        out[nm] = "A" if acc / tot <= 0.8 or acc - v == 0 else "B" if acc / tot <= 0.95 else "C"
    return out


def _grade(v, a, b):
    return None if v is None else "A" if v >= a else "B" if v >= b else "C"


def recommend(s, p, roi, kem) -> str:
    if None in (s, p, roi, kem):
        return "-"
    if roi == "C" or (s == p == kem == "C"):
        return "Сливать"
    if s == p == roi == "A" and kem in ("A", "B"):
        return "Удерживать"
    if kem == "A" or (roi == "A" and kem == "B" and s != "C") or (s == p == "A" and kem == "C"):
        return "ТОП Развивать"
    return "Развивать"


def summary(c, shop: int, d_from, d_to, nms: list[int] | None = None) -> list[dict]:
    from .materialize import ensure_ready
    st = c.execute("SELECT covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (shop,)).fetchone()
    if not st or not st["covered_to"]:
        ensure_ready(c, shop, False)
    keys = sorted(set(F))
    sel = ", ".join(f"sum((data->>'{k}')::numeric) {k}" for k in keys if k not in ("rating", "local_share"))
    S = {r["nm_id"]: r for r in c.execute(f"""SELECT nm_id, {sel},
                 sum((data->>'local_share')::numeric * (data->>'orders')::numeric) loc_w
                 FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, d_from, d_to))}
    rating = {r["nm_id"]: r["v"] for r in c.execute("""SELECT DISTINCT ON (nm_id) nm_id, (data->>'rating')::numeric v FROM agg_nm_day
                 WHERE account_id=%s AND day <= %s AND data->>'rating' IS NOT NULL ORDER BY nm_id, day DESC""", (shop, d_to))}
    bid = {r["id"]: ("a" if r["bt"] == "unified" else "p") for r in c.execute(
        "SELECT (data->>'advertId')::bigint id, data->'info'->>'bid_type' bt FROM raw_rows WHERE account_id=%s AND source='adverts'", (shop,))}
    ad = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""SELECT (data->>'advertId')::bigint id, (n->>'nmId')::bigint nm, sum((n->>'views')::numeric) v,
                                 sum((n->>'clicks')::numeric) cl, sum((n->>'sum')::numeric) s
                          FROM raw_rows, jsonb_array_elements(data->'apps') a, jsonb_array_elements(a->'nms') n
                          WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s GROUP BY 1, 2""", (shop, d_from, d_to)):
        t = bid.get(r["id"], "p")
        x = ad[r["nm"]]
        x[t + "_views"] += float(r["v"] or 0); x[t + "_clicks"] += float(r["cl"] or 0); x[t + "_sum"] += float(r["s"] or 0)
    ad = {k: dict(v) for k, v in ad.items()}
    ext = defaultdict(float)
    for e in c.execute("SELECT * FROM ext_costs WHERE account_id=%s AND kind='ext' AND coalesce(d_to, d_from) >= %s AND d_from <= %s",
                       (shop, d_from, d_to)):
        a, z = e["d_from"], e["d_to"] or e["d_from"]
        n = (z - a).days + 1
        ext[e["nm_id"]] += float(e["cost"] or 0) * sum(1 for i in range(n) if d_from <= a + timedelta(days=i) <= d_to) / n
    stock = {r["nm_id"]: r for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q, sum(in_way_to_client) wt, sum(in_way_from_client) wf FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t
           WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    nom = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, vendor_code, title, subject, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s", (shop,))}
    from .exclusions import excluded
    ex = excluded(c, shop)
    bp_all, bp0 = rnp.buyout_pct(c, shop)
    tx = rnp._tax(c, shop, d_to)
    days = (d_to - d_from).days + 1
    rows = []
    for nm, r in S.items():
        if nm in ex or (nms and nm not in nms):
            continue
        g = lambda k: float(r.get(k) or 0)  
        b = bp_all.get(nm, bp0)
        Sd = {k: r.get(k) for k in rnp.F}
        p_pre = rnp.profit({**Sd, "ads_upd": 0}, b, tx)
        p_with = rnp.profit(Sd, b, tx) - ext.get(nm, 0.0)
        r15 = g("orders_sum") * b
        a = ad.get(nm) or {}
        ads = g("ads_upd") + ext.get(nm, 0.0)
        ad_cl = a.get("a_clicks", 0) + a.get("p_clicks", 0)
        s = stock.get(nm) or {}
        q = float(s.get("q") or 0)
        speed = g("orders") / days
        have = q + float(s.get("wt") or 0) * (1 - b) + float(s.get("wf") or 0)
        cost_b = g("cost_orders") * b
        n = nom.get(nm) or {}
        rows.append({
            "nm_id": nm, "vendor_code": n.get("vendor_code"), "title": n.get("title"), "subject": n.get("subject"), "photo": n.get("photo"),
            "clicks": g("f_open"), "organic": 1 - min(1.0, ad_cl / g("f_open")) if g("f_open") else None,
            "a_clicks": a.get("a_clicks"), "a_ctr": _d(a.get("a_clicks"), a.get("a_views")), "a_cpc": _d(a.get("a_sum"), a.get("a_clicks")),
            "a_sum": a.get("a_sum"), "p_clicks": a.get("p_clicks"), "p_ctr": _d(a.get("p_clicks"), a.get("p_views")),
            "p_cpc": _d(a.get("p_sum"), a.get("p_clicks")), "p_sum": a.get("p_sum"), "ext_sum": ext.get(nm) or None,
            "drr": _d(ads, g("orders_sum")), "ads": ads, "rating": rating.get(nm), "local": _d(g("loc_w"), g("orders")),
            "bonus": g("ads_bonus") or None, "drr_bonus": _d(g("ads_bonus"), g("orders_sum")) if g("ads_bonus") else None,
            "drr_all": _d(ads + g("ads_bonus"), g("orders_sum")) if g("ads_bonus") else None,
            "stock": q, "speed": round(speed, 2), "days_left": round(have / speed) if speed else None, "days_left0": round(q / speed) if speed else None,
            "carts": g("f_cart"), "cart_cost": _d(ads, g("f_cart")), "cart_rate": _d(g("f_cart"), g("f_open")),
            "orders_sum": g("orders_sum"), "orders": g("orders"), "order_cost": _d(ads, g("orders")), "order_rate": _d(g("orders"), g("f_cart")),
            "buyouts_sum": g("buyouts_sum_before_spp"), "buyouts": g("buyouts"), "bp": b, "cr": _d(g("orders"), g("f_open")),
            "price": _d(g("orders_sum"), g("orders")), "spp": 1 - g("orders_sum_spp") / g("orders_sum") if g("orders_sum") else None,
            "margin_pre": _d(p_pre, r15), "margin": _d(p_with, r15), "profit_pre": round(p_pre), "profit": round(p_with),
            "kem": _d(p_with, p_pre) if p_pre > 0 else None, "roi_pre": _d(p_pre, cost_b) if cost_b > 0 else None,
            "buyouts_fc": round(r15),
        })
    _potentials(c, shop, rows, ad)
    sa = _abc_cum({x["nm_id"]: x["buyouts_fc"] for x in rows})
    pa = _abc_cum({x["nm_id"]: x["profit_pre"] for x in rows})
    for x in rows:
        x["abc_sum"], x["abc_profit"] = sa.get(x["nm_id"]), pa.get(x["nm_id"])
        x["abc_roi"], x["abc_kem"] = _grade(x["roi_pre"], 0.7, 0.3), _grade(x["kem"], 0.8, 0.5)
        x["rec"] = recommend(x["abc_sum"], x["abc_profit"], x["abc_roi"], x["abc_kem"]) if x["orders"] else "-"
    from . import xyz
    stability = xyz.orders(c, shop, d_from, d_to, [x["nm_id"] for x in rows])
    for x in rows:
        x.update(stability[x["nm_id"]])
        x["abcxyz"] = x["abc_sum"] + x["xyz"] if x["abc_sum"] and x["xyz"] else None
    _score10x(rows)
    rows.sort(key=lambda x: -x["orders_sum"])
    return rows


def _potentials(c, shop: int, rows: list[dict], ad: dict):
    """Джем и потенциал товара (видео 10X №9). Джем — последний загруженный отчёт поисковых запросов артикула (вкладка «Джем»,
    утром — топ артикулов сам): частота по кластерам, где был хотя бы один переход; показы ≈ частота × видимость кластера (Джем);
    % охвата = показы / частота. Потенциалы: работы с РК = маржа до ДРР / (КЭМ × охват); поставок = 70 % − локализация;
    показов в поиске = частота − показы → клики (× CTR) → заказы (× конверсии карточки) → ₽ и прибыль до ДРР (на заказ — как сейчас)."""
    jam = {}
    for r in c.execute("""SELECT DISTINCT ON (nm_id) nm_id, items, date_from, date_to FROM jam_cache WHERE account_id=%s AND state='done'
                          ORDER BY nm_id, fetched_at DESC""", (shop,)):
        jam[r["nm_id"]] = r
    for x in rows:
        j = jam.get(x["nm_id"])
        a = ad.get(x["nm_id"]) or {}
        v_ad, cl_ad = a.get("a_views", 0) + a.get("p_views", 0), a.get("a_clicks", 0) + a.get("p_clicks", 0)
        ctr = cl_ad / v_ad if v_ad and cl_ad else None
        if not j:
            continue
        items = [i for i in (j["items"] or []) if (i.get("openCard") or 0) > 0]
        freq = sum(float(i.get("frequency") or 0) for i in items)
        jclicks = sum(float(i.get("openCard") or 0) for i in items)
        
        views = sum(float(i.get("frequency") or 0) * float(i.get("visibility") or 0) / 100 for i in items) or (jclicks / ctr if ctr else None)
        ctr = jclicks / views if views else ctr
        cov = min(1.0, views / freq) if views and freq else None
        x.update({"jam_freq": freq or None, "jam_views": round(views) if views else None, "jam_cov": cov, "jam_clicks": jclicks or None,
                  "jam_period": f"{j['date_from']:%d.%m}–{j['date_to']:%d.%m}"})
        if cov and x.get("kem") and x.get("margin_pre") is not None:
            x["pot_ads"] = x["margin_pre"] / (x["kem"] * cov)
        if x.get("local") is not None:
            x["pot_supply"] = max(0.0, 0.7 - x["local"])
        if views is not None and freq and ctr:
            pv = max(0.0, freq - views)
            pc = pv * ctr
            po = pc * (x.get("cart_rate") or 0) * (x.get("order_rate") or 0)
            x.update({"pot_views": round(pv), "pot_clicks": round(pc), "pot_orders": round(po), "pot_sum": round(po * (x.get("price") or 0)),
                      "pot_profit": round(po * x["profit_pre"] / x["orders"]) if x.get("orders") else None})


def _score10x(rows: list[dict]):
    """«Потенциал» (0–100): средний процентиль по потенциалу прибыли, работы с РК, неохвату кластеров и буквам ABC."""
    def pct(key, rev=False):
        vals = sorted(x[key] for x in rows if x.get(key) is not None)
        out = {}
        for x in rows:
            v = x.get(key)
            if v is not None and vals:
                p = sum(1 for y in vals if y <= v) / len(vals)
                out[x["nm_id"]] = 1 - p if rev else p
        return out
    pp, pa, pc = pct("pot_profit"), pct("pot_ads"), pct("jam_cov", rev=True)
    let = {"A": 1.0, "B": 0.5, "C": 0.0}
    for x in rows:
        parts = [d[x["nm_id"]] for d in (pp, pa, pc) if x["nm_id"] in d]
        abc = [let[x[k]] for k in ("abc_sum", "abc_profit", "abc_roi", "abc_kem") if x.get(k) in let]
        if abc:
            parts.append(sum(abc) / len(abc))
        x["pot_10x"] = round(100 * sum(parts) / len(parts)) if len(parts) >= 3 else None


SUMMARY_COLS = [
    ("", [("vendor_code", "Артикул", "text"), ("nm_id", "SKU", "int"), ("subject", "Предмет", "text")]),
    ("ABC анализ", [("abc_sum", "Сумма выкупов", "text"), ("abc_profit", "Прибыль до ДРР", "text"), ("abc_roi", "ROI до ДРР", "text"),
                    ("abc_kem", "КЭМ", "text"), ("rec", "Рекомендация", "text")]),
    ("Джем", [("jam_freq", "Частота за период", "int"), ("jam_views", "Показы за период", "int"), ("jam_cov", "% охвата кластеров", "pct"),
              ("jam_clicks", "Клики по Джему", "int"), ("jam_period", "Период Джема", "text")]),
    ("XYZ анализ", [("xyz", "XYZ по заказам", "text"), ("xyz_cv", "CV заказов", "pct"),
                     ("abcxyz", "ABC выкупов × XYZ", "text"), ("xyz_days", "Дней XYZ", "num"), ("xyz_status", "Данные XYZ", "text")]),
    ("Потенциал товара", [("pot_ads", "Потенциал работы с РК", "pct"), ("pot_supply", "Потенциал поставок", "pct"),
                          ("pot_views", "Потенциал показов РК поиск", "int"), ("pot_clicks", "Потенциал кликов", "int"),
                          ("pot_orders", "Потенциал заказов, шт", "int"), ("pot_sum", "Потенциал заказов, ₽", "money"),
                          ("pot_profit", "Потенциал прибыли до ДРР", "money"), ("pot_10x", "Потенциал", "int")]),
    ("Прибыль (расчётная)", [("buyouts_fc", "Выкупы (прогноз), ₽", "money"), ("profit_pre", "Прибыль до ДРР", "money"), ("profit", "Прибыль с ДРР", "money"),
                             ("margin_pre", "Маржа до ДРР", "pct"), ("margin", "Маржа с ДРР", "pct"), ("roi_pre", "ROI до ДРР", "pct"), ("kem", "КЭМ", "pct")]),
    ("Трафик", [("clicks", "Кликов", "int"), ("organic", "% орг.", "pct")]),
    ("АРК", [("a_clicks", "Кликов АРК", "int"), ("a_ctr", "CTR АРК", "pct"), ("a_cpc", "CPC АРК", "money"), ("a_sum", "Расходы АРК", "money")]),
    ("ПРК", [("p_clicks", "Кликов ПРК", "int"), ("p_ctr", "CTR ПРК", "pct"), ("p_cpc", "CPC ПРК", "money"), ("p_sum", "Расходы ПРК", "money")]),
    ("Реклама", [("ext_sum", "Внешка", "money"), ("ads", "Реклама деньгами + внешка, ₽", "money"), ("drr", "ДРР", "pct"),
                 ("bonus", "Бонусы (Кэшбэк), ₽", "money"), ("drr_bonus", "ДРР бонусами", "pct"), ("drr_all", "ДРР всего (с бонусами)", "pct")]),
    ("Карточка", [("rating", "Рейтинг", "num"), ("local", "% Лок.", "pct")]),
    ("Остатки", [("stock", "Остатки", "int"), ("speed", "Скорость, шт/день", "num"), ("days_left", "Хватит на (с % выкупа)", "int"),
                 ("days_left0", "Хватит на (без)", "int")]),
    ("Воронка", [("carts", "Корзин", "int"), ("cart_cost", "Цена корз.", "money"), ("cart_rate", "% корз", "pct"), ("orders_sum", "Заказов, ₽", "money"),
                 ("orders", "Заказов, шт", "int"), ("order_cost", "Цена заказа", "money"), ("order_rate", "% заказ", "pct"), ("cr", "CR карт", "pct")]),
    ("Выкупы и цена", [("buyouts_sum", "Выкупы, ₽", "money"), ("buyouts", "Выкупы, шт", "int"), ("bp", "% выкупа", "pct"),
                       ("price", "Цена без СПП", "money"), ("spp", "СПП", "pct")]),
]

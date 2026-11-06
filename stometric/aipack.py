"""Self-hosted application component."""

from collections import defaultdict
from datetime import timedelta

from .config import today_msk


WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _f(x):
    return float(x) if x is not None else 0.0


def _per_nm(c, shop: int, df, dt) -> dict[int, dict]:
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    keys = ("orders", "orders_sum", "buyouts", "buyouts_sum", "returns", "profit", "margin", "ads", "ads_upd", "ads_bonus", "storage", "logistics",
            "acquiring", "cost", "cx_orders", "f_open", "f_cart", "f_orders")
    out: dict[int, dict] = {}
    for r in c.execute("SELECT nm_id, data FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, df, dt)):
        d = out.setdefault(r["nm_id"], {k: 0.0 for k in keys} | {"days": 0, "no_cost_days": 0})
        for k in keys:
            if k != "cost":
                d[k] += _f(r["data"].get(k))
        d["days"] += 1
        if r["data"].get("orders") and not r["data"].get("cost_orders"):   
            d["no_cost_days"] += 1
    return out


def money_leaks(c, shop: int, days: int = 30) -> dict:
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    from .manager import stocks
    y = today_msk() - timedelta(days=1)
    df = y - timedelta(days=days - 1)
    nm = _per_nm(c, shop, df, y)
    names = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    st = stocks(c, shop)
    alien = [n for n in nm if n not in names]           
    if alien:
        for r in c.execute("""SELECT DISTINCT ON (data->>'nmId') (data->>'nmId')::bigint n, data->>'vendorCode' v, data->>'subjectName' s
                              FROM raw_rows WHERE account_id=%s AND source IN ('realization','realization_daily') AND row_date >= %s
                                AND data->>'nmId' = ANY(%s)""", (shop, df - timedelta(days=30), [str(n) for n in alien])):
            names[r["n"]] = f"{r['n']} — нет среди карточек магазина, в отчёте WB: «{r['v'] or '—'}»" + (f" ({r['s']})" if r["s"] else "")
    vc = lambda n: names.get(n) or f"{n} — нет среди карточек магазина"  
    tot = {k: round(sum(v[k] for v in nm.values())) for k in ("orders_sum", "buyouts_sum", "profit", "ads", "ads_upd", "ads_bonus", "storage", "logistics")}
    loss = sorted([{"vendor_code": vc(n), "profit": round(v["profit"]), "buyouts": v["buyouts"], "ads": round(v["ads"]),
                    "storage": round(v["storage"]), "logistics": round(v["logistics"])}
                   for n, v in nm.items() if v["profit"] < -300 and not v["no_cost_days"]], key=lambda x: x["profit"])
    ads_eat = sorted([{"vendor_code": vc(n), "ads": round(v["ads"]), "ads_money": round(v["ads_upd"]), "ads_bonus": round(v["ads_bonus"]),
                       "margin_before_ads": round(v["margin"]),
                       "drr_buyouts": round(v["ads"] / v["buyouts_sum"] * 100, 1) if v["buyouts_sum"] else None, "profit": round(v["profit"])}
                      for n, v in nm.items() if v["ads"] > 3000 and v["margin"] > 0 and v["ads"] > v["margin"] * 0.6],
                     key=lambda x: -x["ads"])
    slow = []
    for n, v in nm.items():
        s = (st.get(n) or {}).get("total") or 0
        per_day = v["buyouts"] / days
        if v["storage"] > 500 and s > 0 and (per_day == 0 or s / per_day > 90):
            slow.append({"vendor_code": vc(n), "storage": round(v["storage"]), "stock": s,
                         "turnover_days": round(s / per_day) if per_day else None, "buyouts": v["buyouts"]})
    slow.sort(key=lambda x: -x["storage"])
    oos = []
    for n, v in nm.items():
        s = (st.get(n) or {}).get("total")
        if s == 0 and v["orders"] >= days * 1.5:
            avg_price = v["orders_sum"] / v["orders"] if v["orders"] else 0
            oos.append({"vendor_code": vc(n), "orders_per_day": round(v["orders"] / days, 1),
                        "lost_per_day_rub": round(v["orders"] / days * avg_price)})
    oos.sort(key=lambda x: -x["lost_per_day_rub"])
    returns = sorted([{"vendor_code": vc(n), "buyout_pct": round(v["buyouts"] / (v["buyouts"] + v["returns"]) * 100),
                       "returns": v["returns"], "logistics": round(v["logistics"])}
                      for n, v in nm.items() if v["buyouts"] + v["returns"] >= 20 and v["returns"] / (v["buyouts"] + v["returns"]) > 0.2],
                     key=lambda x: x["buyout_pct"])
    no_cost = [{"vendor_code": vc(n), "orders": v["orders"]} for n, v in nm.items() if v["no_cost_days"] and v["orders"]]
    return {"period": f"{df:%d.%m}–{y:%d.%m}", "totals": tot,
            "checked": "Каждый список ниже код проверил по всем артикулам за период (ДРР от выкупов, маржа, остатки — всё есть); "
                       "пустой список = таких артикулов нет, а не «нет данных». «Нет среди карточек магазина» — строки отчёта WB не по товару "
                       "продавца (например, «неопознанный товар» — WB возвращает продавцу чужой/неопознанный товар и берёт за это логистику): "
                       "так и объясни, не называй это товаром магазина.",
            "unprofitable": loss[:10], "ads_eat_margin": ads_eat[:10],
            "slow_stock_storage": slow[:10], "out_of_stock": oos[:10], "high_returns": returns[:10],
            "no_cost": sorted(no_cost, key=lambda x: -x["orders"])[:10]}


def rating_changes(c, shop: int, y, vc) -> list[dict]:
    """Self-hosted application component."""
    rows = c.execute("""SELECT a.nm_id, (a.data->>'rating')::numeric now, (b.data->>'rating')::numeric before, coalesce((a.data->>'orders')::numeric, 0) o
                        FROM agg_nm_day a JOIN agg_nm_day b ON b.account_id=a.account_id AND b.nm_id=a.nm_id AND b.day=%s
                        WHERE a.account_id=%s AND a.day=%s AND a.data->>'rating' IS NOT NULL AND b.data->>'rating' IS NOT NULL
                          AND (a.data->>'rating')::numeric > 0 AND (b.data->>'rating')::numeric > 0
                          AND round((a.data->>'rating')::numeric, 1) <> round((b.data->>'rating')::numeric, 1)
                        ORDER BY o DESC LIMIT 20""", (y - timedelta(days=1), shop, y)).fetchall()
    return [{"vendor_code": vc(r["nm_id"]), "nm_id": r["nm_id"], "rating_before": float(round(r["before"], 1)), "rating_now": float(round(r["now"], 1)),
             "direction": "вырос" if r["now"] > r["before"] else "упал", "orders_yesterday": int(r["o"])} for r in rows]


def cabinet_issues(c, shop: int) -> dict:
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    from . import insights
    from .manager import stocks
    y = today_msk() - timedelta(days=1)
    w1 = _per_nm(c, shop, y - timedelta(days=6), y)
    w0 = _per_nm(c, shop, y - timedelta(days=13), y - timedelta(days=7))
    names = {r["nm_id"]: r for r in c.execute(
        """SELECT nm_id, vendor_code, jsonb_array_length(coalesce(data->'photos','[]')) photos, coalesce(data->>'video','') <> '' video,
                  length(coalesce(data->>'description','')) descr, length(coalesce(title,'')) tlen
           FROM nomenclature WHERE account_id=%s""", (shop,))}
    rating = {r["nm_id"]: _f(r["r"]) for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, (data->>'rating')::numeric r FROM agg_nm_day WHERE account_id=%s AND data->>'rating' IS NOT NULL
           AND day >= %s ORDER BY nm_id, day DESC""", (shop, y - timedelta(days=30)))}
    st = stocks(c, shop)
    top = sorted(w1, key=lambda n: -w1[n]["orders_sum"])[:20]          
    vc = lambda n: (names.get(n) or {}).get("vendor_code") or str(n)  
    conv, drops, cards, low_rating, low_stock = [], [], [], [], []
    for n in top:
        a, b = w1[n], w0.get(n) or {}
        ca = a["f_cart"] / a["f_open"] if a["f_open"] else None
        cb = b.get("f_cart", 0) / b["f_open"] if b.get("f_open") else None
        if ca is not None and cb and ca < cb * 0.8 and a["f_open"] > 300:
            conv.append({"vendor_code": vc(n), "conv_cart_now": round(ca * 100, 1), "conv_cart_before": round(cb * 100, 1), "views": a["f_open"]})
        if b.get("orders") and a["orders"] < b["orders"] * 0.75 and b["orders"] >= 20:
            drops.append({"vendor_code": vc(n), "orders_week": a["orders"], "orders_prev_week": b["orders"],
                          "change_pct": round((a["orders"] / b["orders"] - 1) * 100)})
        info = names.get(n) or {}
        miss = [x for x, bad in (("фото меньше 5", info.get("photos", 0) < 5), ("нет видео", not info.get("video")),
                                 ("короткое описание", info.get("descr", 0) < 500)) if bad]
        if miss:
            cards.append({"vendor_code": vc(n), "problems": miss, "photos": info.get("photos")})
        if rating.get(n) and rating[n] < 4.7:
            low_rating.append({"vendor_code": vc(n), "rating": rating[n]})
        s = (st.get(n) or {}).get("total")
        per_day = a["orders"] / 7
        if s is not None and per_day and s / per_day < 14:
            low_stock.append({"vendor_code": vc(n), "stock": s, "days": round(s / per_day, 1), "orders_per_day": round(per_day, 1)})
    paused = [dict(r) for r in c.execute(
        """SELECT DISTINCT x.data->'info'->'settings'->>'name' campaign, (nm->>'nm_id')::bigint nm_id
           FROM raw_rows x, jsonb_array_elements(CASE WHEN jsonb_typeof(x.data->'info'->'nm_settings')='array' THEN x.data->'info'->'nm_settings' ELSE '[]'::jsonb END) nm
           WHERE x.account_id=%s AND x.source='adverts' AND (x.data->>'status')::int = 11""", (shop,))]
    paused = [{"campaign": p["campaign"], "vendor_code": vc(p["nm_id"])} for p in paused if p["nm_id"] in top][:10]
    f = insights.findings(c, shop, y)
    
    d1, d0, d7 = (_per_nm(c, shop, d, d) for d in (y, y - timedelta(days=1), y - timedelta(days=7)))
    top_d = sorted(set(d0) | set(d7), key=lambda n: -((d0.get(n) or {}).get("orders_sum", 0) + (d7.get(n) or {}).get("orders_sum", 0)))[:20]
    zero = {"orders": 0.0, "orders_sum": 0.0, "f_open": 0.0, "f_cart": 0.0, "ads": 0.0}

    def day_drops(b):
        out, cv = [], []
        for n in top_d:
            a, z = d1.get(n) or zero, b.get(n) or zero
            if z["orders"] >= 5 and a["orders"] < z["orders"] * 0.75:
                out.append({"vendor_code": vc(n), "orders": a["orders"], "orders_before": z["orders"],
                            "change_pct": round((a["orders"] / z["orders"] - 1) * 100), "views": a["f_open"], "views_before": z["f_open"]})
            ca = a["f_cart"] / a["f_open"] if a["f_open"] >= 100 else None
            cb = z["f_cart"] / z["f_open"] if z["f_open"] >= 100 else None
            if ca is not None and cb and ca < cb * 0.8:
                cv.append({"vendor_code": vc(n), "conv_cart_now": round(ca * 100, 1), "conv_cart_before": round(cb * 100, 1), "views": a["f_open"]})
        return out[:10], cv[:10]

    def shop_line(b):
        return {k: {"now": round(sum(v[k] for v in d1.values())), "before": round(sum(v[k] for v in b.values()))}
                for k in ("orders", "orders_sum", "f_open", "ads", "profit")}
    dd0, cv0 = day_drops(d0)
    dd7, cv7 = day_drops(d7)
    daily = {"yesterday": f"{y:%d.%m}, {WEEKDAYS[y.weekday()]}", "day_before": f"{y - timedelta(days=1):%d.%m}", "same_day_last_week": f"{y - timedelta(days=7):%d.%m}",
             "shop_vs_day_before": shop_line(d0), "shop_vs_same_day_last_week": shop_line(d7),
             "orders_drop_vs_day_before": dd0, "orders_drop_vs_same_day_last_week": dd7,
             "conversion_drop_vs_day_before": cv0, "conversion_drop_vs_same_day_last_week": cv7}
    return {"daily": daily, "rating_changes": rating_changes(c, shop, y, vc), "week": f"{y - timedelta(days=6):%d.%m}–{y:%d.%m}", "orders_drop_week": drops, "conversion_drop": conv, "card_quality": cards[:10],
            "low_rating": low_rating, "low_stock_top": sorted(low_stock, key=lambda x: x["days"]), "paused_ads_on_top": paused,
            "yesterday": {"shop": f["shop"], "articles": f["articles"][:6], "negative": f["negative"][:5]},
            "ad_keywords": ad_keywords(c, shop, y)}


def ad_keywords(c, shop: int, y) -> dict:
    """Ключи рекламы (поисковые кластеры, wb_ad_kw_daily) за неделю: расход без заказов, дорогие заказы, просевшие позиции;
    вчера — ключи с расходом без заказов. Названия кампаний и артикулы продавца — для понятного текста."""
    from .tabs.wbads import _campaigns
    a, a0, b0 = y - timedelta(days=6), y - timedelta(days=13), y - timedelta(days=7)
    if not c.execute("SELECT 1 FROM wb_ad_kw_daily WHERE account_id=%s AND day >= %s LIMIT 1", (shop, a)).fetchone():
        return {"note": "статистики по ключам за неделю нет"}
    camps = _campaigns(c, shop)
    ven = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    q = """SELECT advert_id, nm_id, query, sum(clicks) clicks, sum(orders) orders, sum(spend) spend,
                  sum(avg_pos * greatest(clicks,1)) / nullif(sum(greatest(clicks,1)) FILTER (WHERE avg_pos IS NOT NULL), 0) pos
           FROM wb_ad_kw_daily WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2,3"""
    w1 = {(r["advert_id"], r["nm_id"], r["query"]): r for r in c.execute(q, (shop, a, y))}
    w0 = {(r["advert_id"], r["nm_id"], r["query"]): r for r in c.execute(q, (shop, a0, b0))}
    d1 = {(r["advert_id"], r["nm_id"], r["query"]): r for r in c.execute(q, (shop, y, y))}

    def row(k, r, **extra):
        return {"campaign": (camps.get(k[0]) or {}).get("name", str(k[0])), "article": ven.get(k[1]) or k[1], "key": k[2],
                "clicks": int(r["clicks"]), "orders": int(r["orders"]), "spend": round(float(r["spend"])), **extra}
    total = sum(float(r["spend"]) for r in w1.values())
    waste = sorted(((k, r) for k, r in w1.items() if not r["orders"] and float(r["spend"]) >= 300), key=lambda x: -float(x[1]["spend"]))
    orders_all = sum(int(r["orders"]) for r in w1.values())
    avg_cpo = total / orders_all if orders_all else None
    camp_sp, camp_o = defaultdict(float), defaultdict(int)       
    for k, r in w1.items():
        camp_sp[k[0]] += float(r["spend"])
        camp_o[k[0]] += int(r["orders"])
    pricey = sorted(((k, r) for k, r in w1.items() if r["orders"] and camp_o[k[0]] and float(r["spend"]) >= 1000
                     and float(r["spend"]) / int(r["orders"]) > 2.5 * camp_sp[k[0]] / camp_o[k[0]]), key=lambda x: -float(x[1]["spend"]))
    pos_drop = []
    for k, r in w1.items():
        p0 = w0.get(k)
        if p0 and r["pos"] and p0["pos"] and int(r["clicks"]) + int(p0["clicks"]) >= 50 and float(r["pos"]) - float(p0["pos"]) >= 5\
                and float(r["pos"]) >= 1.5 * float(p0["pos"]):
            pos_drop.append((k, r, float(p0["pos"])))
    pos_drop.sort(key=lambda x: -(float(x[1]["pos"]) - x[2]))
    yd = sorted(((k, r) for k, r in d1.items() if not r["orders"] and float(r["spend"]) >= 200), key=lambda x: -float(x[1]["spend"]))
    return {"week": f"{a:%d.%m}–{y:%d.%m}", "spend_by_keys_week": round(total), "avg_cost_per_order": round(avg_cpo) if avg_cpo else None,
            "spend_no_orders_week": {"total": round(sum(float(r["spend"]) for _, r in waste)), "keys": len(waste),
                                     "top": [row(k, r) for k, r in waste[:8]]},
            "expensive_orders_week": [row(k, r, cost_per_order=round(float(r["spend"]) / int(r["orders"])),
                                          campaign_avg_cost_per_order=round(camp_sp[k[0]] / camp_o[k[0]])) for k, r in pricey[:5]],
            "position_drop_week": [row(k, r, pos_now=round(float(r["pos"]), 1), pos_before=round(p0, 1)) for k, r, p0 in pos_drop[:6]],
            "yesterday_spend_no_orders": [row(k, r) for k, r in yd[:5]],
            "where_to_look": "вкладка «Реклама: кампании и ключи» (клик по кампании) или «Ключи РК»"}


def key_articles(c, shop: int, n: int = 3) -> list[dict]:
    y = today_msk() - timedelta(days=1)
    return c.execute("""SELECT a.nm_id, n.vendor_code, n.title, sum((a.data->>'orders_sum')::numeric) s FROM agg_nm_day a
                        JOIN nomenclature n ON n.account_id=a.account_id AND n.nm_id=a.nm_id
                        WHERE a.account_id=%s AND a.day BETWEEN %s AND %s GROUP BY 1,2,3 ORDER BY s DESC NULLS LAST LIMIT %s""",
                     (shop, y - timedelta(days=29), y, n)).fetchall()


def market_pack(c, tok: str, shop: int, n_articles: int = 3, call=None, only: list[int] | None = None) -> dict:
    """Разделы 2–3 через Wildbox. call(tool, **args) — вызов Wildbox (по умолчанию — ключом кабинета через market._call)."""
    from . import market
    call = call or (lambda tool, **a: market._call(tok, tool, **a))
    own = {r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id=%s", (shop,))}
    out = []
    for art in key_articles(c, shop, n_articles):
        if only and art["nm_id"] not in only:
            continue
        item = {"vendor_code": art["vendor_code"], "nm_id": art["nm_id"], "title": art["title"], "queries": [], "competitors": [], "news": []}
        kw = call("get_external_analytics", schema_name="external.products.keywords", params={"product_id": art["nm_id"], "period": 7}, max_rows=10) or {}
        for r in kw.get("rows") or []:
            pos = [d.get("position") for d in r.get("dynamic") or []]
            item["queries"].append({"query": r["keyword"]["name"], "frequency_30d": r["keyword"]["frequency"], "products_in_search": r["keyword"]["products"],
                                    "our_positions_7d": pos, "ads": r.get("is_advert")})
        if not item["queries"]:
            out.append(item)
            continue
        def med(pos):
            p = sorted(x for x in pos if x)
            return p[len(p) // 2] if p else 10 ** 6
        
        subj = (c.execute("SELECT subject FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, art["nm_id"])).fetchone() or {}).get("subject")
        rel = [x for x in item["queries"] if med(x["our_positions_7d"]) <= 100]
        item["organic_weak"] = not rel            
        stem = (subj or "")[:4].lower()
        rel = rel or [x for x in item["queries"] if stem and stem in x["query"].lower()] or item["queries"]
        q = rel[0]["query"]
        top = call("get_external_analytics", schema_name="external.products.top", extra_fields="proceeds,orders,price,rating,reviews,subject",
                   params={"wb_search": q, "period": 30}, max_rows=20) or {}
        rows = [r for r in top.get("rows") or [] if int(r["id"]) not in own]
        rows = [r for r in rows if stem and str(r.get("subject") or "").lower().startswith(stem)]   
        item["subject"] = subj
        item["main_query"] = q
        item["search_top_by_revenue"] = [{"nm_id": r["id"], "name": (r.get("name") or "")[:60], "proceeds_30d": r.get("proceeds"),
                                          "orders_30d": r.get("orders"), "price": r.get("price"), "rating": r.get("rating"),
                                          "reviews": r.get("reviews"), "seller": r.get("seller"), "created": r.get("create_date")} for r in rows[:8]]
        comp = rows[:4]
        if comp:
            det = call("get_external_analytics", schema_name="external.products.top",
                       extra_fields="proceeds,orders,price,old_price,discount,quantity,rating,reviews,reviews_diff,promos,ea_ads_count,lost_proceeds",
                       params={"product_ids": ",".join(str(r["id"]) for r in comp), "period": 30}, max_rows=10) or {}
            for r in det.get("rows") or []:
                item["competitors"].append({k: r.get(k) for k in ("id", "name", "seller", "proceeds", "orders", "price", "old_price", "discount", "quantity",
                                                                   "rating", "reviews", "reviews_diff", "ea_ads_count", "lost_proceeds", "create_date")}
                                           | {"promos": [p.get("promo_name") for p in r.get("promos") or []][-3:]})
        cutoff = (today_msk() - timedelta(days=60)).isoformat()
        for s in list(dict.fromkeys(r.get("seller") for r in comp if r.get("seller")))[:3]:
            sp = call("get_external_analytics", schema_name="external.products.top", extra_fields="proceeds,orders,price",
                      params={"seller_ids": str(s), "period": 30}, max_rows=20) or {}
            new = [r for r in sp.get("rows") or [] if (r.get("create_date") or "") >= cutoff]
            item["news"].append({"seller": s, "products_shown": len(sp.get("rows") or []),
                                 "new_last_60d": [{"nm_id": r["id"], "name": (r.get("name") or "")[:60], "created": r.get("create_date"),
                                                   "proceeds_30d": r.get("proceeds"), "price": r.get("price")} for r in new[:5]]})
        out.append(item)
    return {"articles": out, "source": "Wildbox: external.products.keywords (7 дн.), external.products.top (wb_search, product_ids, seller_ids; 30 дн.)"}

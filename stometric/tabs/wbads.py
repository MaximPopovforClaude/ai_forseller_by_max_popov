"""Реклама WB: кампании с настройками и ключи (поисковые кластеры) со статистикой — сборщики adverts, ad_stats, ad_kw, ad_kw_lists."""

from collections import defaultdict

STATUS = {4: "готова к запуску", 7: "завершена", 8: "отказ", 9: "активна", 11: "на паузе", -1: "удаляется"}
BID = {"manual": "Ручная ставка", "unified": "Единая ставка"}
STATE = {"active": "активный", "excluded": "исключён", "archived": "архив", "minus": "минус-фраза"}


def _campaigns(c, shop):
    out = {}
    for r in c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts'", (shop,)):
        d = r["data"]
        info = d.get("info") or {}
        st = info.get("settings") or {}
        pl = st.get("placements") or {}
        out[int(d["advertId"])] = {"name": st.get("name") or "", "status": d.get("status"), "bid_type": info.get("bid_type"),
                                   "payment": (st.get("payment_type") or "").upper(), "nms": info.get("nm_settings") or [],
                                   "places": ", ".join(x for x, on in (("поиск", pl.get("search")), ("рекомендации", pl.get("recommendations"))) if on),
                                   "started": ((info.get("timestamps") or {}).get("started") or "")[:10], "changed": (d.get("changeTime") or "")[:10]}
    return out


def _by_nm(c, shop, a, b) -> dict:
    """(кампания, артикул) → статистика РК по артикулам: рекламируемые и «ассоциированные» (заказ другого товара после клика по рекламе)."""
    out = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""
        SELECT (data->>'advertId')::bigint a, (nm->>'nmId')::bigint nm, sum((nm->>'views')::numeric) views, sum((nm->>'clicks')::numeric) clicks,
               sum((nm->>'atbs')::numeric) atbs, sum((nm->>'orders')::numeric) orders, sum((nm->>'shks')::numeric) shks,
               sum((nm->>'sum_price')::numeric) sum_price, sum((nm->>'sum')::numeric) spend
        FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app,
             jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s GROUP BY 1, 2""", (shop, a, b)):
        out[(r["a"], r["nm"])].update({k: float(r[k] or 0) for k in ("views", "clicks", "atbs", "orders", "shks", "sum_price", "spend")})
    return out


ASSOC_COLS = [("advert_id", "ID кампании", "text"), ("campaign", "Кампания", "text"), ("photo", "Фото", "image"), ("vendor_code", "Артикул продавца", "text"),
              ("nm_id", "Артикул WB", "text"), ("kind", "Чей заказ", "text"), ("subject", "Предмет", "text"), ("views", "Показы", "int"),
              ("clicks", "Клики", "int"), ("atbs", "Корзины", "int"), ("orders", "Заказы", "int"), ("shks", "Заказано шт", "int"),
              ("sum_price", "Заказы, ₽", "money"), ("spend", "Расход, ₽", "money"), ("share", "Доля в заказах кампании", "share")]


def ads_assoc(c, shop, f):
    """Ассоциированные конверсии РК: какие артикулы заказывают после клика по рекламе кампании — сами рекламируемые и другие
    («ассоциированные»: другой цвет/размер той же склейки или вообще другой товар магазина). Клик по кампании во вкладке
    «Реклама: кампании и ключи» — только её артикулы. Расход WB относит только на рекламируемые артикулы."""
    camps = _campaigns(c, shop)
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, imt_id, subject, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s",
                                            (shop,))}
    st = _by_nm(c, shop, f["date_from"], f["date_to"])
    camp = int(f["campaign"]) if f.get("campaign") else None
    tot = defaultdict(float)
    for (aid, n), x in st.items():
        tot[aid] += x["orders"]
    rows = []
    for (aid, n), x in st.items():
        if camp and aid != camp or f.get("nm_ids") and n not in f["nm_ids"]:
            continue
        if not (x["orders"] or x["atbs"] or x["spend"]):
            continue
        cp = camps.get(aid) or {"name": "", "nms": []}
        own = {int(y["nm_id"]) for y in cp["nms"]}
        imts = {(nom.get(y) or {}).get("imt_id") for y in own}
        m = nom.get(n) or {}
        kind = "рекламируемый" if n in own else ("ассоциированный: та же склейка" if m.get("imt_id") and m.get("imt_id") in imts
                                                else "ассоциированный: другой товар")
        rows.append({"advert_id": str(aid), "campaign": cp["name"], "photo": m.get("photo"), "vendor_code": m.get("vendor_code"), "nm_id": str(n),
                     "kind": kind, "subject": m.get("subject"), **{k: x[k] for k in ("views", "clicks", "atbs", "orders", "shks")},
                     "sum_price": round(x["sum_price"], 2), "spend": round(x["spend"], 2), "share": x["orders"] / tot[aid] if tot[aid] else None})
    rows.sort(key=lambda r: (r["advert_id"] != str(camp), -r["orders"], -r["atbs"]))
    res = {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in ASSOC_COLS], "rows": rows, "plain": True,
           "empty": "За период по кампании нет заказов и корзин — ассоциированных конверсий пока нет."}
    if rows and not any(r["kind"] != "рекламируемый" for r in rows):
        res["note"] = "Ассоциированных конверсий пока нет: за период заказывали и клали в корзину только рекламируемые артикулы."
    return res


def _vendor(c, shop):
    return {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}


CAMP_COLS = [("advert_id", "ID кампании", "text"), ("name", "Кампания", "text"), ("status", "Статус", "text"), ("bid_type", "Тип ставки", "text"),
             ("payment", "Оплата", "text"), ("places", "Места", "text"), ("articles", "Артикулы", "text"), ("bid_search", "Ставка поиск, ₽", "money"),
             ("bid_rec", "Ставка рекомендации, ₽", "money"), ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "share"),
             ("atbs", "Корзины", "int"), ("orders", "Заказы (с ассоциированными)", "int"),
             ("sum_price", "Сумма заказов с ассоциированными, ₽", "money"), ("sum_own", "Сумма заказов рекламируемых артикулов, ₽", "money"),
             ("orders_own", "Заказы рекламируемых артикулов", "int"), ("orders_assoc", "Ассоциированные заказы (другие артикулы)", "int"),
             ("atbs_assoc", "Ассоциированные корзины", "int"), ("sum_assoc", "Ассоциированные заказы, ₽", "money"),
             ("assoc_share", "Доля ассоциированных в заказах", "share"), ("spend", "Расход, ₽", "money"),
             ("upd_money", "Списано деньгами (УПД), ₽", "money"), ("upd_bonus", "Списано бонусами (Кэшбэк), ₽", "money"), ("bonus_share", "Доля бонусов", "share"),
             ("cpc", "CPC, ₽", "money"), ("cpo", "Стоимость заказа, ₽", "money"), ("drr", "ДРР с ассоциированными (расход / сумма всех заказов РК)", "share"),
             ("drr_own", "ДРР без ассоциированных (расход / заказы рекламируемых)", "share"),
             ("kw_spend", "Расход по ключам (поиск), ₽", "money"), ("kw_active", "Ключей активных", "int"), ("kw_excluded", "Исключено", "int"), ("kw_minus", "Минус-фраз", "int"),
             ("kw_spend_no_orders", "Расход на ключи без заказов, ₽", "money")]


def ads_campaigns(c, shop, f):
    """Реклама: кампании — настройки (статус, тип ставки, оплата, места, артикулы и ставки) и статистика за период (показы, клики, CTR,
    корзины, заказы, расход, CPC, стоимость заказа, ДРР), сколько ключей активно/исключено/в минус-фразах и расход на ключи без заказов.
    Клик по кампании — ниже её ключи (поисковые кластеры) со статистикой. Фильтр артикулов — кампании с этими артикулами.
    Ключи WB отдаёт только по поиску: у кампаний «полки» (рекомендации) ключей нет, и расход по ключам бывает меньше расхода кампании."""
    camps = _campaigns(c, shop)
    ven = _vendor(c, shop)
    a, b = f["date_from"], f["date_to"]
    st = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""SELECT (data->>'advertId')::bigint id, sum((data->>'views')::numeric) views, sum((data->>'clicks')::numeric) clicks,
                                 sum((data->>'atbs')::numeric) atbs, sum((data->>'orders')::numeric) orders, sum((data->>'sum')::numeric) spend,
                                 sum((data->>'sum_price')::numeric) sum_price
                          FROM raw_rows WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s GROUP BY 1""", (shop, a, b)):
        st[r["id"]].update({k: float(r[k] or 0) for k in ("views", "clicks", "atbs", "orders", "spend", "sum_price")})
    assoc = _by_nm(c, shop, a, b)
    upd = defaultdict(lambda: [0.0, 0.0])       
    for r in c.execute("""SELECT (data->>'advertId')::bigint id, data->>'paymentType'='Кэшбэк' b, sum((data->>'updSum')::numeric) s FROM raw_rows
                          WHERE account_id=%s AND source='ad_upd' AND row_date BETWEEN %s AND %s GROUP BY 1,2""", (shop, a, b)):
        upd[r["id"]][1 if r["b"] else 0] += float(r["s"] or 0)
    kw = defaultdict(lambda: defaultdict(int))
    for r in c.execute("SELECT advert_id, state, count(DISTINCT query) n FROM wb_ad_kw_lists WHERE account_id=%s GROUP BY 1,2", (shop,)):
        kw[r["advert_id"]][r["state"]] = r["n"]
    waste, kws = {}, {}
    for r in c.execute("""SELECT advert_id, sum(spend) s, sum(spend) FILTER (WHERE o = 0) w FROM (SELECT advert_id, nm_id, query, sum(spend) spend,
                              sum(orders) o FROM wb_ad_kw_daily WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2,3) x GROUP BY 1""", (shop, a, b)):
        kws[r["advert_id"]], waste[r["advert_id"]] = float(r["s"] or 0), float(r["w"] or 0)
    rows = []
    for aid, cp in camps.items():
        s = st.get(aid, {})
        if not s.get("spend") and not s.get("views") and cp["status"] not in (9, 11):
            continue
        nms = [int(x["nm_id"]) for x in cp["nms"]]
        if f.get("nm_ids") and not set(nms) & set(f["nm_ids"]):
            continue
        bids = [x.get("bids_kopecks") or {} for x in cp["nms"]]
        bs = [x.get("search") for x in bids if x.get("search")]
        br = [x.get("recommendations") for x in bids if x.get("recommendations")]
        v, cl, o, sp, spr = s.get("views", 0), s.get("clicks", 0), s.get("orders", 0), s.get("spend", 0), s.get("sum_price", 0)
        own = set(nms)
        ao = sum(x["orders"] for (aa, n), x in assoc.items() if aa == aid and n not in own)
        oo = sum(x["orders"] for (aa, n), x in assoc.items() if aa == aid and n in own)
        so = sum(x["sum_price"] for (aa, n), x in assoc.items() if aa == aid and n in own)
        rows.append({"advert_id": str(aid), "name": cp["name"], "status": STATUS.get(cp["status"], str(cp["status"])),
                     "bid_type": BID.get(cp["bid_type"], cp["bid_type"] or ""), "payment": cp["payment"], "places": cp["places"],
                     "articles": ", ".join(str(ven.get(n) or n) for n in nms[:10]) + (f" +{len(nms) - 10}" if len(nms) > 10 else ""),
                     "bid_search": max(bs) / 100 if bs else None, "bid_rec": max(br) / 100 if br else None,
                     "views": v, "clicks": cl, "ctr": cl / v if v else None, "atbs": s.get("atbs", 0), "orders": o, "sum_price": spr,
                     "orders_own": oo, "orders_assoc": ao, "assoc_share": ao / (ao + oo) if ao + oo else None,
                     "atbs_assoc": sum(x["atbs"] for (aa, n), x in assoc.items() if aa == aid and n not in own),
                     "sum_assoc": round(sum(x["sum_price"] for (aa, n), x in assoc.items() if aa == aid and n not in own), 2),
                     "sum_own": round(so, 2), "drr_own": sp / so if so else None,
                     "spend": round(sp, 2), "upd_money": round(upd[aid][0], 2) if aid in upd else None,
                     "upd_bonus": round(upd[aid][1], 2) if aid in upd else None,
                     "bonus_share": upd[aid][1] / sum(upd[aid]) if aid in upd and sum(upd[aid]) else None, "cpc": round(sp / cl, 2) if cl else None, "cpo": round(sp / o, 2) if o else None,
                     "drr": sp / spr if spr else None, "kw_spend": round(kws[aid], 2) if aid in kws else None, "kw_active": kw[aid].get("active", 0), "kw_excluded": kw[aid].get("excluded", 0),
                     "kw_minus": kw[aid].get("minus", 0), "kw_spend_no_orders": round(waste.get(aid, 0), 2)})
    rows.sort(key=lambda r: (-r["spend"], r["status"] != "активна"))
    nb = not any(r["upd_bonus"] for r in rows)
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in CAMP_COLS if not (nb and k in ("upd_bonus", "bonus_share"))],
            "rows": rows, "plain": True,
            "empty": "Нет кампаний с расходом за период (или ключ API без раздела «Продвижение»)."}


KEY_COLS = [("advert_id", "ID кампании", "text"), ("campaign", "Кампания", "text"), ("vendor_code", "Артикул продавца", "text"), ("nm_id", "Артикул WB", "text"),
            ("query", "Ключ (поисковый кластер)", "text"), ("state", "Статус ключа", "text"), ("bid", "Ставка ключа, ₽", "money"),
            ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "share"), ("atbs", "Корзины", "int"), ("orders", "Заказы", "int"),
            ("shks", "Заказано шт", "int"), ("spend", "Расход, ₽", "money"), ("cpc", "CPC, ₽", "money"), ("cr_cart", "Клик → корзина", "share"),
            ("cr_order", "Клик → заказ", "share"), ("cpo", "Стоимость заказа, ₽", "money"), ("avg_pos", "Средняя позиция", "num"), ("days", "Дней с кликами", "int"),
            ("hist", "Исключённый ключ: вся история", "text")]


def ads_keys(c, shop, f):
    """Ключи РК — поисковые кластеры рекламных кампаний WB за период: статус (активный, исключён, архив, минус-фраза), своя ставка,
    показы (у кампаний за клики WB их не отдаёт), клики, CTR, корзины, заказы, расход, CPC, конверсии, стоимость заказа, средняя позиция.
    Фильтры: артикулы, кампания (клик по кампании во вкладке «Реклама: кампании и ключи»). Без заказов при расходе — кандидаты в минус.
    Заказы по ключу — по рекламируемому артикулу (в статистике кампании WB считает и заказы других товаров после клика)."""
    camps = _campaigns(c, shop)
    ven = _vendor(c, shop)
    p = {"shop": shop, "a": f["date_from"], "b": f["date_to"]}
    w = ""
    if f.get("campaign"):
        w += " AND advert_id = %(camp)s"
        p["camp"] = int(f["campaign"])
    if f.get("nm_ids"):
        w += " AND nm_id = ANY(%(nms)s)"
        p["nms"] = f["nm_ids"]
    rows = c.execute(f"""SELECT advert_id, nm_id, query, sum(views) views, sum(clicks) clicks, sum(atbs) atbs, sum(orders) orders, sum(shks) shks,
                                sum(spend) spend, sum(avg_pos * greatest(clicks, 1)) / nullif(sum(greatest(clicks, 1)) FILTER (WHERE avg_pos IS NOT NULL), 0) avg_pos,
                                count(*) FILTER (WHERE clicks > 0) days, bool_or(views IS NOT NULL) has_views
                         FROM wb_ad_kw_daily WHERE account_id=%(shop)s AND day BETWEEN %(a)s AND %(b)s{w} GROUP BY 1,2,3""", p).fetchall()
    lists = {}
    for r in c.execute(f"SELECT advert_id, nm_id, query, state, bid FROM wb_ad_kw_lists WHERE account_id=%(shop)s{w}", p):
        k = (r["advert_id"], r["nm_id"], r["query"])
        if k not in lists or r["state"] in ("minus", "excluded"):
            lists[k] = (r["state"], r["bid"] if r["bid"] is not None else (lists.get(k) or (None, None))[1])
    out = []
    for r in rows:
        cl, o, sp = int(r["clicks"] or 0), int(r["orders"] or 0), float(r["spend"] or 0)
        v = int(r["views"]) if r["has_views"] and r["views"] is not None else None
        state, bid = lists.get((r["advert_id"], r["nm_id"], r["query"]), (None, None))
        out.append({"advert_id": str(r["advert_id"]), "campaign": (camps.get(r["advert_id"]) or {}).get("name", ""),
                    "vendor_code": ven.get(r["nm_id"]), "nm_id": str(r["nm_id"]), "query": r["query"], "state": STATE.get(state, ""),
                    "bid": float(bid) if bid is not None else None, "views": v, "clicks": cl, "ctr": cl / v if v else None,
                    "atbs": int(r["atbs"] or 0), "orders": o, "shks": int(r["shks"] or 0), "spend": round(sp, 2),
                    "cpc": round(sp / cl, 2) if cl else None, "cr_cart": int(r["atbs"] or 0) / cl if cl else None, "cr_order": o / cl if cl else None,
                    "cpo": round(sp / o, 2) if o else None, "avg_pos": round(float(r["avg_pos"]), 1) if r["avg_pos"] is not None else None,
                    "days": r["days"]})
    off = [r for r in out if r["state"] in (STATE["minus"], STATE["excluded"])]
    if off:                  
        from ..ads_ai import _m, economics, kw_history, kw_merge, kw_verdict
        hist = kw_history(c, shop, sorted({int(r["nm_id"]) for r in off}), sorted({r["query"] for r in off}))
        eco = economics(c, shop)
        mark = {"bad": "❌ не возвращать", "good": "✓ можно вернуть", "weak": "≈ только на тест", "thin": "мало данных"}
        for r in off:
            n = int(r["nm_id"])
            v, why = kw_verdict(kw_merge({k: x for k, x in hist.items() if k[0] == n}, r["query"]), _m(eco, n), eco["k_ad"])
            r["hist"] = f"{mark[v]}: {why}"
    out.sort(key=lambda r: -r["spend"])
    note = None
    if not c.execute("SELECT 1 FROM wb_ad_kw_daily WHERE account_id=%s LIMIT 1", (shop,)).fetchone():
        note = "Ключи ещё загружаются (первый сбор — история до полугода)."
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in KEY_COLS], "rows": out, "note": note, "plain": True,
            "empty": "Нет статистики по ключам за период: WB отдаёт её для кампаний с ручной ставкой в поиске (CPM и CPC)."}

"""Реклама Ozon: кампании с настройками, внутри — товары кампании и поисковые фразы (Performance API: oz_ad_campaigns, oz_ad_daily,
oz_ad_sku, oz_ad_phrases; заказы и позиция по запросу — аналитика Seller API oz_queries)."""

from collections import defaultdict

SKIP_KINDS = ("Блогеры", "VK")
STATE = {"CAMPAIGN_STATE_RUNNING": "активна", "CAMPAIGN_STATE_STOPPED": "остановлена", "CAMPAIGN_STATE_INACTIVE": "неактивна",
         "CAMPAIGN_STATE_ARCHIVED": "в архиве", "CAMPAIGN_STATE_PLANNED": "запланирована", "CAMPAIGN_STATE_FINISHED": "завершена",
         "CAMPAIGN_STATE_MODERATION_DRAFT": "черновик", "CAMPAIGN_STATE_MODERATION_IN_PROGRESS": "на модерации",
         "CAMPAIGN_STATE_MODERATION_FAILED": "не прошла модерацию"}
PLACE = {"PLACEMENT_TOP_PROMOTION": "вывод в топ", "PLACEMENT_SEARCH_AND_CATEGORY": "поиск и категории", "PLACEMENT_PDP": "карточка товара", "PLACEMENT_TILE_MAIN": "плитка на главной",
         "PLACEMENT_INVALID": ""}
STRATEGY = {"NO_AUTO_STRATEGY": "ручная", "TARGET_BIDS": "целевые ставки", "MAX_CLICKS": "максимум кликов", "MIN_PRICE": "минимальная цена", "TOP_MAX_CLICKS": "максимум кликов"}


def _rub(v):
    try:
        return round(float(str(v).replace(",", ".")) / 1_000_000, 2) if v not in (None, "", "0") else None
    except ValueError:
        return None


def _num(v):
    try:
        return float(str(v).replace(",", ".").replace("\xa0", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


CAMP_COLS = [("advert_id", "ID кампании", "text"), ("name", "Кампания", "text"), ("kind", "Тип", "text"), ("status", "Статус", "text"),
             ("payment", "Оплата", "text"), ("places", "Места", "text"), ("budget", "Бюджет", "text"), ("strategy", "Стратегия", "text"),
             ("autostop", "Автостоп", "text"), ("dates", "Даты", "text"), ("skus", "Товаров", "int"),
             ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "share"), ("to_cart", "Корзины", "int"),
             ("spend", "Расход, ₽", "money"), ("cpc", "CPC, ₽", "money"), ("orders", "Продажи, шт", "int"), ("orders_money", "Продажи, ₽", "money"),
             ("drr", "ДРР", "share"), ("cpo", "Стоимость продажи, ₽", "money"), ("spend_no_sales", "Расход на товары без продаж, ₽", "money")]


def oz_campaigns(c, shop, f):
    """Реклама: кампании и фразы (Ozon) — кампании рекламного кабинета (кроме блогеров и VK): тип, статус, оплата, места, бюджет,
    стратегия, автостоп, даты и итоги за период (показы, клики, CTR, корзины, расход, CPC, продажи, ДРР, расход на товары без продаж).
    Клик по кампании — ниже её товары (ставка, расход, продажи, ДРР) и поисковые фразы (показы, клики, оценка расхода, заказы по запросу)."""
    a, b = f["date_from"], f["date_to"]
    st = {r["campaign_id"]: r for r in c.execute(
        """SELECT campaign_id, sum(views) views, sum(clicks) clicks, sum(spent) spend, sum(orders) orders, sum(orders_money) orders_money
           FROM oz_ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, a, b))}
    sk = {r["campaign_id"]: r for r in c.execute(
        """SELECT campaign_id, sum(to_cart) to_cart, count(DISTINCT sku) n,
                  sum(spent) FILTER (WHERE o = 0) waste FROM (SELECT campaign_id, sku, sum(to_cart) to_cart, sum(spent) spent,
                  sum(coalesce(orders,0) + coalesce(models,0)) o FROM oz_ad_sku WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2) x
           GROUP BY 1""", (shop, a, b))}
    rows = []
    for k in c.execute("SELECT * FROM oz_ad_campaigns WHERE account_id=%s AND coalesce(kind,'') <> ALL(%s)", (shop, list(SKIP_KINDS))).fetchall():
        s, x, raw = st.get(k["campaign_id"]) or {}, sk.get(k["campaign_id"]) or {}, k["raw"] or {}
        sp = float(s.get("spend") or 0)
        if not sp and not s.get("views") and k["state"] != "CAMPAIGN_STATE_RUNNING":
            continue
        if f.get("nm_ids") and not set(k["skus"] or []) & set(f["nm_ids"]):
            continue
        v, cl, o, om = float(s.get("views") or 0), float(s.get("clicks") or 0), float(s.get("orders") or 0), float(s.get("orders_money") or 0)
        wk, dl = _rub(raw.get("weeklyBudget")), _rub(raw.get("dailyBudget") or raw.get("budget"))
        budget = (f"{wk:,.0f} ₽ в неделю" if wk else f"{dl:,.0f} ₽ в день" if dl else "без ограничения").replace(",", " ")
        auto = (raw.get("autostopStatus") or "").replace("AUTOSTOP_STATUS_", "").lower()
        rows.append({"advert_id": str(k["campaign_id"]), "name": k["title"] or "", "kind": k["kind"] or k["adv_type"] or "",
                     "status": STATE.get(k["state"], k["state"] or ""), "payment": raw.get("PaymentType") or k["payment_type"] or "",
                     "places": ", ".join(filter(None, (PLACE.get(p, p) for p in raw.get("placement") or []))),
                     "budget": budget, "strategy": STRATEGY.get(raw.get("productAutopilotStrategy"), raw.get("productAutopilotStrategy") or ""),
                     "autostop": "" if auto in ("", "none") else auto,
                     "dates": f"с {raw.get('fromDate') or str(raw.get('createdAt') or '')[:10]}" + (f" по {raw['toDate']}" if raw.get("toDate") else ""),
                     "skus": x.get("n") or len(k["skus"] or []), "views": v, "clicks": cl, "ctr": cl / v if v else None,
                     "to_cart": float(x.get("to_cart") or 0), "spend": round(sp, 2), "cpc": round(sp / cl, 2) if cl else None, "orders": o,
                     "orders_money": om, "drr": sp / om if om else None, "cpo": round(sp / o, 2) if o else None,
                     "spend_no_sales": round(float(x.get("waste") or 0), 2)})
    rows.sort(key=lambda r: -r["spend"])
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in CAMP_COLS], "rows": rows, "plain": True,
            "empty": "Нет кампаний с расходом за период (или не добавлен ключ рекламного кабинета Ozon)."}


ITEM_COLS = [("advert_id", "ID кампании", "text"), ("campaign", "Кампания", "text"), ("sku", "SKU", "text"), ("offer_id", "Артикул", "text"),
             ("name", "Товар", "text"), ("bid", "Ставка (предельная цена), ₽", "money"), ("added", "Добавлен", "text"),
             ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "share"), ("to_cart", "Корзины", "int"),
             ("cpc", "CPC, ₽", "money"), ("spend", "Расход, ₽", "money"), ("orders", "Продано, шт", "int"), ("orders_money", "Продажи, ₽", "money"),
             ("models", "Продано модели, шт", "int"), ("models_money", "Продажи модели, ₽", "money"), ("drr", "ДРР", "share"),
             ("cpo", "Стоимость продажи, ₽", "money")]


def oz_ad_items(c, shop, f):
    """Товары РК (Ozon) — товары рекламных кампаний за период: ставка (предельная цена), дата добавления, показы, клики, CTR, корзины,
    CPC, расход, продажи (свои и модели), ДРР, стоимость продажи. Фильтры: кампания, артикулы. Расход без продаж — кандидаты на отключение."""
    p = {"shop": shop, "a": f["date_from"], "b": f["date_to"]}
    w = ""
    if f.get("campaign"):
        w += " AND s.campaign_id = %(camp)s"
        p["camp"] = int(f["campaign"])
    if f.get("nm_ids"):
        w += " AND s.sku = ANY(%(skus)s)"
        p["skus"] = f["nm_ids"]
    rows = c.execute(f"""SELECT s.campaign_id, s.sku, k.title, pr.offer_id, pr.name, sum(s.views) views, sum(s.clicks) clicks, sum(s.to_cart) to_cart,
                                sum(s.spent) spent, sum(s.orders) orders, sum(s.orders_money) om, sum(s.models) models, sum(s.models_money) mm,
                                (array_agg(s.raw ORDER BY s.day DESC))[1] last
                         FROM oz_ad_sku s LEFT JOIN oz_ad_campaigns k ON k.account_id=s.account_id AND k.campaign_id=s.campaign_id
                         LEFT JOIN oz_products pr ON pr.account_id=s.account_id AND pr.sku=s.sku
                         WHERE s.account_id=%(shop)s AND s.day BETWEEN %(a)s AND %(b)s{w} GROUP BY 1,2,3,4,5""", p).fetchall()
    out = []
    for r in rows:
        v, cl, sp = float(r["views"] or 0), float(r["clicks"] or 0), float(r["spent"] or 0)
        o, om = float(r["orders"] or 0) + float(r["models"] or 0), float(r["om"] or 0) + float(r["mm"] or 0)
        last = r["last"] or {}
        out.append({"advert_id": str(r["campaign_id"]), "campaign": r["title"] or "", "sku": str(r["sku"]), "offer_id": r["offer_id"],
                    "name": r["name"] or last.get("Название товара"), "bid": _num(last.get("Предельная цена, ₽")), "added": last.get("Дата добавления"),
                    "views": v, "clicks": cl, "ctr": cl / v if v else None, "to_cart": float(r["to_cart"] or 0), "cpc": round(sp / cl, 2) if cl else None,
                    "spend": round(sp, 2), "orders": float(r["orders"] or 0), "orders_money": float(r["om"] or 0), "models": float(r["models"] or 0),
                    "models_money": float(r["mm"] or 0), "drr": sp / om if om else None, "cpo": round(sp / o, 2) if o else None})
    out.sort(key=lambda r: -r["spend"])
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in ITEM_COLS], "rows": out, "plain": True,
            "empty": "Нет статистики по товарам кампаний за период."}


PHR_COLS = [("advert_id", "ID кампании", "text"), ("campaign", "Кампания", "text"), ("sku", "SKU", "text"), ("offer_id", "Артикул", "text"),
            ("phrase", "Поисковая фраза", "text"), ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "share"),
            ("spend_est", "Расход (оценка), ₽", "money"), ("q_orders", "Заказы по запросу (вся аналитика)", "int"),
            ("q_cpo_est", "Расход на заказ (оценка), ₽", "money"), ("q_position", "Позиция по запросу", "num"), ("days", "Дней с кликами", "int")]


def oz_ad_phrases(c, shop, f):
    """Фразы РК с расходом (Ozon) — поисковые фразы кампаний «Поиск» и «Вывод в топ» за период: показы, клики, CTR (отчёт Ozon);
    расход — ОЦЕНКА: клики фразы × CPC этого товара в кампании в тот же день (Ozon расход по фразам не отдаёт); заказы и позиция по запросу —
    из аналитики поисковых запросов Ozon по этому товару (все заказы по запросу, не только рекламные). Фильтры: кампания, артикулы."""
    p = {"shop": shop, "a": f["date_from"], "b": f["date_to"]}
    w = ""
    if f.get("campaign"):
        w += " AND p.campaign_id = %(camp)s"
        p["camp"] = int(f["campaign"])
    if f.get("nm_ids"):
        w += " AND p.sku = ANY(%(skus)s)"
        p["skus"] = f["nm_ids"]
    rows = c.execute(f"""SELECT p.campaign_id, p.sku, lower(p.phrase) phrase, sum(p.views) views, sum(p.clicks) clicks,
                                sum(p.clicks * coalesce(s.spent / nullif(s.clicks, 0), 0)) est, count(*) FILTER (WHERE p.clicks > 0) days
                         FROM oz_ad_phrases p LEFT JOIN oz_ad_sku s ON s.account_id=p.account_id AND s.day=p.day AND s.campaign_id=p.campaign_id AND s.sku=p.sku
                         WHERE p.account_id=%(shop)s AND p.day BETWEEN %(a)s AND %(b)s{w} GROUP BY 1,2,3""", p).fetchall()
    q = {(r["sku"], r["query"]): r for r in c.execute(
        """SELECT sku, lower(query) query, sum(orders) orders, avg(position) pos FROM oz_queries
           WHERE account_id=%(shop)s AND day BETWEEN %(a)s AND %(b)s GROUP BY 1,2""", p)}
    camps = {r["campaign_id"]: r["title"] for r in c.execute("SELECT campaign_id, title FROM oz_ad_campaigns WHERE account_id=%s", (shop,))}
    offers = {r["sku"]: r["offer_id"] for r in c.execute("SELECT sku, offer_id FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,))}
    out = []
    for r in rows:
        v, cl, est = float(r["views"] or 0), float(r["clicks"] or 0), float(r["est"] or 0)
        qq = q.get((r["sku"], r["phrase"])) or {}
        qo = float(qq["orders"]) if qq.get("orders") is not None else None
        out.append({"advert_id": str(r["campaign_id"]), "campaign": camps.get(r["campaign_id"], ""), "sku": str(r["sku"]),
                    "offer_id": offers.get(r["sku"]), "phrase": r["phrase"], "views": v, "clicks": cl, "ctr": cl / v if v else None,
                    "spend_est": round(est, 2), "q_orders": qo, "q_cpo_est": round(est / qo, 2) if qo else None,
                    "q_position": round(float(qq["pos"]), 1) if qq.get("pos") is not None else None, "days": r["days"]})
    out.sort(key=lambda r: (-r["spend_est"], -r["clicks"]))
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in PHR_COLS], "rows": out, "plain": True,
            "note": "Расход по фразе — оценка (клики × CPC товара в этот день): Ozon не отдаёт расход по фразам. Заказы по запросу — все, не только с рекламы.",
            "empty": "Нет фраз за период: Ozon отдаёт их для кампаний «Поиск» и «Вывод в топ»."}


def ad_problems(c, shop: int, a, y) -> dict:
    """Для ИИ-сводки: товары в кампаниях с расходом без продаж и дорогие продажи (к средней по кампании) за неделю."""
    it = oz_ad_items(c, shop, {"date_from": a, "date_to": y})["rows"]
    camp = defaultdict(lambda: [0.0, 0.0])
    for r in it:
        camp[r["advert_id"]][0] += r["spend"]
        camp[r["advert_id"]][1] += r["orders"] + r["models"]
    waste = [r for r in it if r["spend"] >= 300 and not (r["orders"] + r["models"])]
    pricey = [dict(r, campaign_avg_cpo=round(camp[r["advert_id"]][0] / camp[r["advert_id"]][1]))
              for r in it if r["cpo"] and r["spend"] >= 1000 and camp[r["advert_id"]][1] and r["cpo"] > 2.5 * camp[r["advert_id"]][0] / camp[r["advert_id"]][1]]
    keep = ("campaign", "offer_id", "spend", "clicks", "orders", "models", "cpo", "campaign_avg_cpo", "bid")
    return {"period": f"{a:%d.%m}–{y:%d.%m}", "spend_no_sales": {"total": round(sum(r["spend"] for r in waste)), "items": len(waste),
            "top": [{k: r.get(k) for k in keep} for r in waste[:8]]},
            "expensive_sales": [{k: r.get(k) for k in keep} for r in sorted(pricey, key=lambda r: -r["spend"])[:5]],
            "where_to_look": "вкладка «Реклама: кампании и фразы» (клик по кампании)"}

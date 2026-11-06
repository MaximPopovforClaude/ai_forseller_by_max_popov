"""Вкладки магазина Ozon (листы таблицы «STOMETRIC OZON v2») — на данных Seller API (stometric/collectors_ozon.py)."""

from datetime import timedelta

from ..config import today_msk


def _skus(f):
    return f.get("nm_ids") or None      


def _v2(c, shop, f, kind: str):
    from ..sheets import ozv2
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    a = f["date_from"]
    if kind == "day":
        a = max(a, y - timedelta(days=61))
    elif kind == "week":
        a = min(a, y - timedelta(days=7 * 8))
    else:
        a = min(a, (y.replace(day=1) - timedelta(days=150)).replace(day=1))
    skus = _skus(f)
    if f.get("group"):
        skus = ozv2._skus_of_group(c, shop, f["group"]) or [-1]
    res = ozv2.compute(c, shop, kind, a, y, skus)
    cols = [{"field": "label", "title": "Показатель", "type": "label"}, {"field": "total", "title": "Итого", "type": "rowfmt"},
            {"field": "avg", "title": "Среднее", "type": "rowfmt"}]
    cols += [{"field": f"p{i}", "title": t, "type": "rowfmt"} for i, t in enumerate(res["periods"])]
    src = res["sources"]
    note = []
    if not src["realization"]:
        note.append("финансы Ozon ещё загружаются")
    if not src["ads_by_sku"]:
        note.append("реклама — по кампаниям (отчёты по SKU ещё не собраны или нет ключа рекламы)")
    return {"columns": cols, "rows": res["rows"], "layout": "sheet", "empty": "; ".join(note) or None, "note": "; ".join(note) or None}


def v2_day(c, shop, f):
    """По дням (Version2) — простыня как в таблице «ПР TabLab Конверсии»: воронка, продажи, остатки, реклама по типам кампаний,
    финансы по статьям Ozon, себестоимость, налог, прибыль. Колонки — дни (до 62), «Итого» и «Среднее». Фильтр — артикулы или склейка."""
    return _v2(c, shop, f, "day")


def v2_week(c, shop, f):
    """По неделям (Version2) — та же простыня по неделям (не меньше 8 недель)."""
    return _v2(c, shop, f, "week")


def v2_month(c, shop, f):
    """По месяцам (Version2) — та же простыня по месяцам (не меньше 6 месяцев)."""
    return _v2(c, shop, f, "month")


def _grp_skus(c, shop, f):
    from ..sheets import ozv2
    skus = _skus(f)
    if f.get("group"):
        skus = ozv2._skus_of_group(c, shop, f["group"]) or [-1]
    return skus


def v2_unit(c, shop, f):
    """Юнитка (Version2) — по каждому SKU два периода и «Всего»: продажи, комиссия, баллы, себестоимость, доставка, расходы с привязкой
    и без (доля по продажам), реклама по типам и ОЗЗ, воронка, налог, прибыль, ROI; рядом — % от продаж. Оба периода настраиваются
    над таблицей (по умолчанию Период 2 — выбранные даты, Период 1 — столько же дней сразу перед ним); галочка «На 1 шт» — деньги
    в пересчёте на одну проданную штуку (продажи минус возвраты)."""
    from ..sheets import ozv2
    y0 = today_msk() - timedelta(days=1)
    y = min(f["date_to"], y0)
    a = f["date_from"]
    if (y - a).days > 92 or (y - a).days < 0:
        a = y - timedelta(days=6)
    n = (y - a).days + 1
    p1 = (a - timedelta(days=n), a - timedelta(days=1))
    if f.get("p1_from") and f.get("p1_to"):
        b1 = min(f["p1_to"], y0)
        if 0 <= (b1 - f["p1_from"]).days <= 92:
            p1 = (f["p1_from"], b1)
    per_unit = bool(f.get("per_unit"))
    res = ozv2.unit(c, shop, p1, (a, y), _grp_skus(c, shop, f), per_unit=per_unit)
    res["plain"] = True
    res["unit"] = {"p1_from": p1[0], "p1_to": p1[1], "p2_from": a, "p2_to": y, "per_unit": per_unit}
    res["note"] = (f"Период 1: {p1[0]:%d.%m}–{p1[1]:%d.%m.%Y}, Период 2: {a:%d.%m}–{y:%d.%m.%Y}. Расходы без привязки и ОЗЗ — доля по продажам / кампании ОЗЗ."
                   + (" Деньги — на 1 проданную штуку (продажи минус возвраты); воронка и % — как есть." if per_unit else ""))
    return res


def v2_opiu(c, shop, f):
    """ОПИУ (Version2) — отчёт о прибылях и убытках по месяцам и кварталам года (год — по дате «по»): продажи, выкупы Ozon, баллы,
    комиссия, доставка по услугам, расходы с привязкой и без, себестоимость, налоги, прибыль, ROI, к выплате; рядом — % от продаж."""
    from ..sheets import ozv2
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    r = ozv2.opiu(c, shop, y.year, y)
    cols = [{"field": "label", "title": "Показатель", "type": "label"}]
    for i, t in enumerate(r["periods"]):
        cols += [{"field": f"p{i}", "title": t, "type": "rowfmt"}, {"field": f"s{i}", "title": "%", "type": "share"}]
    d0 = c.execute("SELECT min(op_day) d FROM oz_transactions WHERE account_id=%s", (shop,)).fetchone()["d"]
    note = f"Начисления Ozon загружены с {d0:%d.%m.%Y}: первый месяц и квартал неполные." if d0 and d0.day > 1 else None
    return {"columns": cols, "rows": r["rows"], "layout": "sheet", "note": note}


def dash(c, shop, f):
    """3#Дашборд — показатели по дням: заказы и прибыль по заказам (оценка), выкупы и оперативная прибыль по начислениям Ozon,
    отмены и возвраты, расходы Ozon, остатки. Колонки — дни выбранного периода (по умолчанию 30 дней до вчера)."""
    from ..sheets import ozdash
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    res = ozdash.compute(c, shop, max(f["date_from"], y - timedelta(days=89)), y, _skus(f))
    cols = [{"field": "label", "title": f"ПОКАЗАТЕЛИ (СНО: {res['tax']})", "type": "label"}]
    cols += [{"field": f"d{i}", "title": f"{d[8:10]}.{d[5:7]}", "type": "rowfmt"} for i, d in enumerate(res["days"])]
    return {"columns": cols, "rows": res["rows"], "layout": "sheet"}


def svod(c, shop, f):
    """2#СводнаяПоАртикулам — SKU: заказы и отмены за период, выкупы и начисления, остатки FBO, текущая цена и себестоимость;
    последним — сумма всех заказов за последние 4 недели (по вчера), по ней сортировка."""
    y4 = today_msk() - timedelta(days=1)
    p = {"shop": shop, "a": f["date_from"], "b": f["date_to"], "a4": y4 - timedelta(days=27), "b4": y4}
    rows = c.execute(
        """WITH o AS (SELECT sku, sum(qty) q, sum(qty*price) s, sum(qty) FILTER (WHERE status LIKE 'cancel%%') cq
                      FROM oz_postings WHERE account_id=%(shop)s AND order_day BETWEEN %(a)s AND %(b)s GROUP BY 1),
                b AS (SELECT s.sku, sum(coalesce(t.qty,1)) FILTER (WHERE t.tx_type='orders') bq, sum(t.accruals_for_sale/greatest(cardinality(t.skus),1))
                             FILTER (WHERE t.tx_type='orders') bs, sum(coalesce(t.qty,1)) FILTER (WHERE t.tx_type='returns') rq,
                             sum(t.amount/greatest(cardinality(t.skus),1)) total
                      FROM oz_transactions t, unnest(t.skus) s(sku)
                      WHERE t.account_id=%(shop)s AND t.op_day BETWEEN %(a)s AND %(b)s AND t.tx_type IN ('orders','returns','delivery') GROUP BY 1),
                st AS (SELECT s.sku, sum(coalesce(available,0)) av, sum(coalesce(other,0)) ot FROM oz_stocks s
                       WHERE s.account_id=%(shop)s AND s.snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%(shop)s) GROUP BY 1),
                cp AS (SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%(shop)s ORDER BY nm_id, valid_from DESC),
                o4 AS (SELECT sku, sum(qty*price) s FROM oz_postings WHERE account_id=%(shop)s AND order_day BETWEEN %(a4)s AND %(b4)s GROUP BY 1)
           SELECT p.photo, p.offer_id, p.sku, p.name, p.model_id, pr.price, pr.marketing_price, cp.cost,
                  o.q orders_qty, o.s orders_sum, o.cq cancel_qty, b.bq buy_qty, b.bs buy_sum, b.rq ret_qty, b.total payout,
                  b.total - coalesce(cp.cost,0)*(coalesce(b.bq,0)-coalesce(b.rq,0)) profit, st.av stock, st.ot stock_other,
                  coalesce(o4.s, 0) orders_sum_4w
           FROM oz_products p LEFT JOIN oz_prices pr ON pr.account_id=p.account_id AND pr.product_id=p.product_id
           LEFT JOIN o ON o.sku=p.sku LEFT JOIN b ON b.sku=p.sku LEFT JOIN st ON st.sku=p.sku LEFT JOIN cp ON cp.nm_id=p.sku
           LEFT JOIN o4 ON o4.sku=p.sku
           WHERE p.account_id=%(shop)s AND (NOT p.archived OR o.q IS NOT NULL OR st.av > 0)
           ORDER BY o4.s DESC NULLS LAST, o.s DESC NULLS LAST, p.offer_id""", p).fetchall()
    if _skus(f):
        rows = [r for r in rows if r["sku"] in _skus(f)]
    cols = [("photo", "Фото", "image"), ("offer_id", "Артикул продавца", "text"), ("sku", "SKU", "int"), ("name", "Название", "text"),
            ("model_id", "Модель", "int"), ("price", "Цена продавца, ₽", "money"), ("marketing_price", "Цена на витрине, ₽", "money"),
            ("cost", "Себестоимость, ₽", "money"), ("orders_qty", "Заказы, шт", "int"), ("orders_sum", "Заказы, ₽", "money"),
            ("cancel_qty", "Отмены, шт", "int"), ("buy_qty", "Выкупы, шт", "int"), ("buy_sum", "Выкупы (начислено за продажу), ₽", "money"),
            ("ret_qty", "Возвраты, шт", "int"), ("payout", "Итого начислено Ozon по продажам, ₽", "money"),
            ("profit", "Прибыль по выкупам до налога и общих расходов, ₽", "money"),
            ("stock", "Остаток FBO доступно, шт", "int"), ("stock_other", "В пути / в обработке, шт", "int"),
            ("orders_sum_4w", f"Сумма всех заказов, руб, за последние 4 недели ({p['a4']:%d.%m}–{p['b4']:%d.%m})", "money")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows, "sort": {"field": "orders_sum_4w", "desc": True}}


def stocks(c, shop, f):
    """FBO#ТекущиеОстаткиПоКластерам — SKU × кластер Ozon: доступно к продаже (последний снимок)."""
    data = c.execute(
        """SELECT s.sku, coalesce(p.offer_id, s.offer_id) offer_id, p.name, s.cluster, sum(coalesce(s.available,0)) q, sum(coalesce(s.other,0)) o
           FROM oz_stocks s LEFT JOIN oz_products p ON p.account_id=s.account_id AND p.sku=s.sku
           WHERE s.account_id=%(shop)s AND s.snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%(shop)s)
           GROUP BY 1,2,3,4""", {"shop": shop}).fetchall()
    tot = {}
    for r in data:
        tot[r["cluster"]] = tot.get(r["cluster"], 0) + float(r["q"] or 0)
    cl = [k for k, _ in sorted(tot.items(), key=lambda x: -x[1])]
    rows = {}
    for r in data:
        row = rows.setdefault(r["sku"], {"offer_id": r["offer_id"], "sku": r["sku"], "name": r["name"], "total": 0, "other": 0})
        row[f"c{cl.index(r['cluster'])}"] = float(r["q"] or 0)
        row["total"] += float(r["q"] or 0)
        row["other"] += float(r["o"] or 0)
    cols = [{"field": "offer_id", "title": "Артикул продавца", "type": "text"}, {"field": "sku", "title": "SKU", "type": "int"},
            {"field": "name", "title": "Название", "type": "text"}, {"field": "total", "title": "ВСЕГО доступно, шт", "type": "int"},
            {"field": "other", "title": "В пути / в обработке, шт", "type": "int"}]
    cols += [{"field": f"c{i}", "title": k or "—", "type": "int"} for i, k in enumerate(cl)]
    out = sorted(rows.values(), key=lambda r: -r["total"])
    if _skus(f):
        out = [r for r in out if r["sku"] in _skus(f)]
    return {"columns": cols, "rows": out}


def accruals(c, shop, f):
    """БД#Начисления — все финансовые операции Ozon за период, сгруппированные по типу: сколько операций и на какую сумму,
    в какую статью дашборда попадает. Проверка: сумма = «Итого начислено Ozon»."""
    from ..sheets.ozdash import _cls
    rows = c.execute(
        """SELECT tx_type, operation_type, type_name, count(*) n, sum(amount) amount, sum(accruals_for_sale) accr, sum(sale_commission) com,
                  sum(coalesce(delivery_charge,0)+coalesce(return_delivery_charge,0)+coalesce(services_total,0)) logi,
                  min(op_day) d1, max(op_day) d2
           FROM oz_transactions WHERE account_id=%s AND op_day BETWEEN %s AND %s GROUP BY 1,2,3 ORDER BY sum(abs(amount)) DESC""",
        (shop, f["date_from"], f["date_to"])).fetchall()
    names = {"ads": "Реклама", "acquiring": "Эквайринг", "storage": "Хранение", "acceptance": "Приемка", "crossdock": "Кросс-докинг",
             "utilization": "Утилизация", "compensation": "Компенсации", "insurance": "Страхование", "logistics": "Логистика",
             "other": "Другие расходы Ozon"}
    for r in rows:
        r["article"] = ("Выкупы/возвраты (комиссия, логистика)" if (r["tx_type"] or "").lower() in ("orders", "returns")
                        else names[_cls(f"{r['operation_type']} {r['type_name']}")])
    cols = [("type_name", "Операция", "text"), ("operation_type", "Код Ozon", "text"), ("tx_type", "Тип", "text"),
            ("article", "Статья дашборда", "text"), ("n", "Операций", "int"), ("amount", "Итого, ₽", "money"),
            ("accr", "За продажу, ₽", "money"), ("com", "Комиссия, ₽", "money"), ("logi", "Логистика и услуги, ₽", "money"),
            ("d1", "С", "date"), ("d2", "По", "date")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def ads(c, shop, f):
    """Реклама — кампании рекламного кабинета Ozon (Performance API) за период: показы, клики, расход, заказы, ДРР."""
    if not c.execute("SELECT 1 FROM account_ad_tokens WHERE account_id=%s", (shop,)).fetchone():
        return {"columns": [{"field": "msg", "title": "Реклама Ozon", "type": "text"}],
                "rows": [{"msg": "Нет ключа рекламного кабинета. Добавьте его: Кабинет → Магазины → «Ключ рекламы» "
                                 "(Ozon → Продвижение → Настройки → API → Client ID и Client Secret)."}]}
    rows = c.execute(
        """SELECT k.campaign_id, k.title, k.adv_type, k.payment_type, k.state, k.daily_budget, k.skus,
                  sum(d.views) views, sum(d.clicks) clicks, sum(d.spent) spent, sum(d.bonus_spent) bonus, sum(d.orders) orders,
                  sum(d.orders_money) orders_money, max(d.day) last_day
           FROM oz_ad_campaigns k LEFT JOIN oz_ad_daily d ON d.account_id=k.account_id AND d.campaign_id=k.campaign_id
                AND d.day BETWEEN %s AND %s
           WHERE k.account_id=%s GROUP BY k.campaign_id, k.title, k.adv_type, k.payment_type, k.state, k.daily_budget, k.skus
           ORDER BY sum(d.spent) DESC NULLS LAST, k.campaign_id DESC""", (f["date_from"], f["date_to"], shop)).fetchall()
    st = {"CAMPAIGN_STATE_RUNNING": "идёт", "CAMPAIGN_STATE_STOPPED": "остановлена", "CAMPAIGN_STATE_INACTIVE": "неактивна",
          "CAMPAIGN_STATE_ARCHIVED": "архив", "CAMPAIGN_STATE_PLANNED": "запланирована", "CAMPAIGN_STATE_FINISHED": "завершена"}
    sk = _skus(f)
    out = []
    for r in rows:
        if sk and not any(x in sk for x in (r["skus"] or [])):
            continue
        v, cl, sp, om = float(r["views"] or 0), float(r["clicks"] or 0), float(r["spent"] or 0), float(r["orders_money"] or 0)
        r["state"] = st.get(r["state"], r["state"])
        r["skus"] = ", ".join(str(x) for x in (r["skus"] or [])[:10]) + (" …" if len(r["skus"] or []) > 10 else "")
        r["ctr"] = round(100 * cl / v, 2) if v else None        
        r["cpc"] = sp / cl if cl else None
        r["drr"] = round(100 * sp / om, 2) if om else None
        out.append(r)
    cols = [("campaign_id", "ID", "int"), ("title", "Кампания", "text"), ("adv_type", "Тип", "text"), ("payment_type", "Оплата", "text"),
            ("state", "Статус", "text"), ("daily_budget", "Дневной бюджет, ₽", "money"), ("skus", "Товары (SKU)", "text"),
            ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR, %", "pct"), ("cpc", "Цена клика, ₽", "money"),
            ("spent", "Расход, ₽", "money"), ("bonus", "Из них бонусами, ₽", "money"), ("orders", "Заказы, шт", "int"),
            ("orders_money", "Заказы, ₽", "money"), ("drr", "ДРР, %", "pct"), ("last_day", "Последний день", "date")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": out}

def cost_tab(c, shop, f):
    """Себестоимость (ручные данные) по SKU Ozon; правка — с датой начала действия (прошлое не переписывается)."""
    rows = c.execute(
        """SELECT p.sku nm_id, p.offer_id vendor_code, p.name title, p.photo, cp.cost, cp.valid_from, cp.note, g.group_name
           FROM oz_products p LEFT JOIN article_groups g ON g.account_id=p.account_id AND g.nm_id=p.sku
           LEFT JOIN LATERAL (SELECT cost, valid_from, note FROM cost_price x WHERE x.account_id=p.account_id AND x.nm_id=p.sku AND valid_from <= current_date
                                                 ORDER BY valid_from DESC LIMIT 1) cp ON true
           WHERE p.account_id=%s AND p.sku IS NOT NULL ORDER BY p.archived, (cp.cost IS NULL) DESC, p.offer_id""", (shop,)).fetchall()
    cols = [{"field": "photo", "title": "Фото", "type": "image"}, {"field": "nm_id", "title": "SKU", "type": "int"},
            {"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "title", "title": "Название", "type": "text"},
            {"field": "cost", "title": "Себестоимость, ₽ (двойной клик — изменить)", "type": "edit_money"},
            {"field": "valid_from", "title": "Действует с", "type": "date"}, {"field": "note", "title": "Источник", "type": "text"},
            {"field": "group_name", "title": "Склейка (двойной клик — изменить)", "type": "edit_text"}]
    return {"columns": cols, "rows": rows, "editable": "cost"}


def products(c, shop, f):
    """БД#Номенклатура — товары Ozon: артикул, SKU, product_id, модель, цены, комиссия FBO/FBS по карточке."""
    rows = c.execute(
        """SELECT p.photo, p.offer_id, p.sku, p.product_id, p.model_id, p.name, p.archived, pr.price, pr.old_price, pr.marketing_price,
                  (SELECT (x->>'percent')::numeric FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p.raw->'commissions')='array' THEN p.raw->'commissions' ELSE '[]'::jsonb END) x WHERE lower(x->>'sale_schema')='fbo') fbo_pct,
                  (SELECT (x->>'percent')::numeric FROM jsonb_array_elements(CASE WHEN jsonb_typeof(p.raw->'commissions')='array' THEN p.raw->'commissions' ELSE '[]'::jsonb END) x WHERE lower(x->>'sale_schema')='fbs') fbs_pct,
                  p.updated_at
           FROM oz_products p LEFT JOIN oz_prices pr ON pr.account_id=p.account_id AND pr.product_id=p.product_id
           WHERE p.account_id=%s ORDER BY p.archived, p.offer_id""", (shop,)).fetchall()
    cols = [("photo", "Фото", "image"), ("offer_id", "Артикул продавца", "text"), ("sku", "SKU", "int"), ("product_id", "product_id", "int"),
            ("model_id", "Модель", "int"), ("name", "Название", "text"), ("archived", "Архив", "text"), ("price", "Цена продавца, ₽", "money"),
            ("old_price", "Цена до скидки, ₽", "money"), ("marketing_price", "Цена на витрине, ₽", "money"),
            ("fbo_pct", "Комиссия FBO, %", "num"), ("fbs_pct", "Комиссия FBS, %", "num"), ("updated_at", "Обновлено", "datetime")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}



STATE_RU = {"CAMPAIGN_STATE_RUNNING": "активна", "CAMPAIGN_STATE_INACTIVE": "остановлена", "CAMPAIGN_STATE_ARCHIVED": "архив",
            "CAMPAIGN_STATE_FINISHED": "завершена", "CAMPAIGN_STATE_PLANNED": "запланирована", "CAMPAIGN_STATE_STOPPED": "остановлена",
            "CAMPAIGN_STATE_MODERATION_DRAFT": "черновик", "CAMPAIGN_STATE_MODERATION_IN_PROGRESS": "на модерации"}


def _names(c, shop):
    return {r["sku"]: r for r in c.execute("SELECT sku, offer_id, name FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,))}


def v2_turnover(c, shop, f):
    """Оборачиваемость (Version2) — SKU × кластер Ozon, как в таблице: доступно, в пути (поставка), оборачиваемость в днях =
    (доступно + в пути) / среднесуточные продажи в кластере по данным Ozon (ads_cluster, среднее по складам кластера). Последний снимок."""
    skus = _grp_skus(c, shop, f)
    st = c.execute("""SELECT sku, cluster, sum(coalesce(available,0)) a, sum(coalesce((raw->>'transit_stock_count')::numeric,0)) o,
                             avg((raw->>'ads_cluster')::numeric) ads, max((raw->>'ads')::numeric) ads_all
                      FROM oz_stocks WHERE account_id=%s AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s) GROUP BY 1,2""",
                   (shop, shop)).fetchall()
    tot_cl = {}
    for r in st:
        tot_cl[r["cluster"]] = tot_cl.get(r["cluster"], 0) + float(r["a"] or 0) + float(r["o"] or 0)
    cl = [k for k, _ in sorted(tot_cl.items(), key=lambda x: -x[1])]
    nm = _names(c, shop)
    rows = {}
    for r in st:
        if skus and r["sku"] not in skus:
            continue
        row = rows.setdefault(r["sku"], {"offer_id": (nm.get(r["sku"]) or {}).get("offer_id"), "sku": str(r["sku"]),
                                         "name": (nm.get(r["sku"]) or {}).get("name"), "a": 0.0, "o": 0.0, "ads": float(r["ads_all"] or 0)})
        i = cl.index(r["cluster"])
        a, o, d = float(r["a"] or 0), float(r["o"] or 0), float(r["ads"] or 0)
        row[f"a{i}"], row[f"o{i}"] = a, o
        row[f"t{i}"] = round((a + o) / d, 1) if d else None
        row["a"] += a
        row["o"] += o
    for row in rows.values():
        row["t"] = round((row["a"] + row["o"]) / row["ads"], 1) if row["ads"] else None
        row["ads"] = round(row["ads"], 2)
    cols = [{"field": "offer_id", "title": "Артикул", "type": "text"}, {"field": "sku", "title": "SKU", "type": "text"},
            {"field": "name", "title": "Название", "type": "text"}, {"field": "a", "title": "Доступно, всего", "type": "int", "group": "Всего"},
            {"field": "o", "title": "В пути", "type": "int"}, {"field": "ads", "title": "Продаж в день (Ozon)", "type": "num"},
            {"field": "t", "title": "Обор-ть, дней", "type": "num"}]
    for i, k in enumerate(cl):
        cols += [{"field": f"a{i}", "title": "Доступно", "type": "int", "group": k}, {"field": f"o{i}", "title": "В пути", "type": "int"},
                 {"field": f"t{i}", "title": "Обор-ть", "type": "num"}]
    return {"columns": cols, "rows": sorted(rows.values(), key=lambda r: -r["a"]),
            "note": "Обор-ть пустая — у Ozon нет продаж товара в кластере. Остатки и среднесуточные продажи — последний снимок Ozon."}


def v2_stocks_days(c, shop, f):
    """Остатки (Version2) — по артикулу и кластеру на каждый день (последний снимок дня): доступно к продаже + в пути. История копится
    с начала сбора (Ozon не отдаёт остатки задним числом)."""
    skus = _grp_skus(c, shop, f)
    data = c.execute("""WITH s AS (SELECT DISTINCT ON (snap_at::date) snap_at FROM oz_stocks WHERE account_id=%s
                                   AND snap_at::date BETWEEN %s AND %s ORDER BY snap_at::date, snap_at DESC)
                        SELECT x.snap_at::date d, x.sku, x.cluster, sum(coalesce(x.available,0)+coalesce(x.other,0)) q
                        FROM oz_stocks x JOIN s ON s.snap_at=x.snap_at WHERE x.account_id=%s GROUP BY 1,2,3""",
                     (shop, f["date_from"], f["date_to"], shop)).fetchall()
    days = sorted({r["d"] for r in data}, reverse=True)
    nm = _names(c, shop)
    rows = {}
    for r in data:
        if skus and r["sku"] not in skus:
            continue
        key = (r["sku"], r["cluster"])
        row = rows.setdefault(key, {"offer_id": (nm.get(r["sku"]) or {}).get("offer_id"), "sku": str(r["sku"]), "cluster": r["cluster"]})
        row[f"d{days.index(r['d'])}"] = float(r["q"] or 0)
    cols = [{"field": "offer_id", "title": "Артикул", "type": "text"}, {"field": "sku", "title": "SKU", "type": "text"},
            {"field": "cluster", "title": "Кластер", "type": "text"}]
    cols += [{"field": f"d{i}", "title": f"{d:%d.%m}", "type": "int"} for i, d in enumerate(days)]
    return {"columns": cols, "rows": sorted(rows.values(), key=lambda r: (r["offer_id"] or "", -(r.get("d0") or 0))),
            "note": f"Снимков остатков: {len(days)} дн. (история копится с начала сбора)." if days else "Снимков остатков за период ещё нет."}


def v2_campaigns(c, shop, f):
    """РК (Version2) — все рекламные кампании Ozon: ID, название, дата создания, статус, тип (как в таблице) и итоги за период:
    показы, клики, расход, заказы."""
    rows = c.execute("""SELECT k.campaign_id, k.title, (k.raw->>'createdAt')::timestamptz::date created, k.state, k.kind, k.daily_budget,
                               sum(d.views) views, sum(d.clicks) clicks, sum(d.spent) spent, sum(d.orders) orders, sum(d.orders_money) orders_money
                        FROM oz_ad_campaigns k LEFT JOIN oz_ad_daily d ON d.account_id=k.account_id AND d.campaign_id=k.campaign_id
                             AND d.day BETWEEN %s AND %s
                        WHERE k.account_id=%s GROUP BY 1,2,3,4,5,6 ORDER BY created DESC NULLS LAST""", (f["date_from"], f["date_to"], shop)).fetchall()
    for r in rows:
        r["campaign_id"] = str(r["campaign_id"])
        r["state"] = STATE_RU.get(r["state"], r["state"])
        r["ctr"] = round(float(r["clicks"]) / float(r["views"]) * 100, 2) if r["views"] else None
        r["drr"] = round(float(r["spent"]) / float(r["orders_money"]) * 100, 2) if r["orders_money"] else None
    cols = [("campaign_id", "ID РК", "text"), ("title", "Наименование", "text"), ("created", "Дата создания", "date"), ("state", "Статус", "text"),
            ("kind", "Тип", "text"), ("daily_budget", "Дневной бюджет, ₽", "money"), ("views", "Показы", "int"), ("clicks", "Клики", "int"),
            ("ctr", "CTR", "pct"), ("spent", "Расход, ₽", "money"), ("orders", "Заказы", "int"), ("orders_money", "Заказы, ₽", "money"), ("drr", "ДРР", "pct")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def v2_phrases(c, shop, f):
    """Фразы РК (Version2) — поисковые запросы, по которым показывались товары в кампаниях «Поиск» и «Вывод в топ»: показы, клики, CTR
    за период (отчёт рекламного кабинета Ozon по фразам)."""
    skus = _grp_skus(c, shop, f)
    rows = c.execute("""SELECT k.title, p.campaign_id, p.sku, p.phrase, sum(p.views) views, sum(p.clicks) clicks
                        FROM oz_ad_phrases p LEFT JOIN oz_ad_campaigns k ON k.account_id=p.account_id AND k.campaign_id=p.campaign_id
                        WHERE p.account_id=%s AND p.day BETWEEN %s AND %s GROUP BY 1,2,3,4 ORDER BY 1, 5 DESC""",
                     (shop, f["date_from"], f["date_to"])).fetchall()
    nm = _names(c, shop)
    out = []
    for r in rows:
        if skus and r["sku"] not in skus:
            continue
        out.append({"title": r["title"], "campaign_id": str(r["campaign_id"]), "offer_id": (nm.get(r["sku"]) or {}).get("offer_id"),
                    "phrase": r["phrase"], "views": r["views"], "clicks": r["clicks"],
                    "ctr": round(float(r["clicks"]) / float(r["views"]) * 100, 2) if r["views"] else None})
    cols = [("title", "Кампания", "text"), ("campaign_id", "ID РК", "text"), ("offer_id", "Артикул", "text"), ("phrase", "Поисковый запрос", "text"),
            ("views", "Показы", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR", "pct")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": out}


def v2_queries(c, shop, f):
    """Продажи по запросам (Version2) — по каждому SKU 15 главных поисковых запросов Ozon за период: средняя позиция, покупатели искали /
    увидели товар, конверсия из просмотра в заказ, заказы и продажи по запросу (сумма по дням)."""
    skus = _grp_skus(c, shop, f)
    rows = c.execute("""SELECT sku, query, avg(position) pos, sum(searchers) s, sum(viewers) v, sum(orders) o, sum(gmv) g, min(idx) idx,
                               sum(conv * viewers) / nullif(sum(viewers), 0) cv
                        FROM oz_queries WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2 ORDER BY 1, sum(viewers) DESC""",
                     (shop, f["date_from"], f["date_to"])).fetchall()
    nm = _names(c, shop)
    out = []
    for r in rows:
        if skus and r["sku"] not in skus:
            continue
        out.append({"offer_id": (nm.get(r["sku"]) or {}).get("offer_id"), "sku": str(r["sku"]), "query": r["query"],
                    "pos": round(float(r["pos"]), 1) if r["pos"] is not None else None, "s": r["s"], "v": r["v"],
                    "conv": round(float(r["cv"]), 2) if r["cv"] is not None else None, "o": r["o"], "g": r["g"]})
    cols = [("offer_id", "Артикул", "text"), ("sku", "SKU", "text"), ("query", "Текст запроса", "text"), ("pos", "Средняя позиция", "num"),
            ("s", "Покупатели искали", "int"), ("v", "Покупатели увидели товар", "int"), ("conv", "Конверсия из просмотра (Ozon)", "pct"),
            ("o", "Заказы по запросу", "int"), ("g", "Продажи по запросу, ₽", "money")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": out,
            "note": "Данные Ozon «Аналитика → Поисковые запросы» по дням: суммы покупателей — по дням, без учёта повторов."}


CHECK_FIELDS = [("rating", "Рейтинг товара"), ("review_pin", "Закрепление отзыва да/нет"), ("review_comments", "Комментарии к отзывам"),
                ("content_rating", "Контент рейтинг"), ("content_comments", "Комментарии контент рейтинг"), ("seo", "SEO"), ("rich", "РИЧ"),
                ("geo", "ГЕО (кол-во кластеров)"), ("price_index", "Индекс цен"), ("photo", "Фото/инфографика"), ("ads", "РК")]


def v2_check(c, shop, f):
    """Чек-лист (Version2) — ручные отметки по артикулу на дату: рейтинг, отзывы, контент, SEO, РИЧ, ГЕО, индекс цен, фото, реклама.
    Строки на дату «по» — для всех товаров (заполните ячейку двойным кликом), ниже — записи за выбранный период."""
    skus = _grp_skus(c, shop, f)
    nm = _names(c, shop)
    data = {}
    for r in c.execute("SELECT day, sku, field, value FROM oz_checklist WHERE account_id=%s AND day BETWEEN %s AND %s",
                       (shop, f["date_from"], f["date_to"])):
        data.setdefault((r["day"], r["sku"]), {})[r["field"]] = r["value"]
    d0 = min(f["date_to"], today_msk())
    active = [r["sku"] for r in c.execute("""SELECT p.sku FROM oz_products p LEFT JOIN (SELECT sku, sum(qty) n FROM oz_postings WHERE account_id=%s
                                             AND order_day >= current_date - 30 GROUP BY 1) o ON o.sku=p.sku WHERE p.account_id=%s
                                             AND p.sku IS NOT NULL AND NOT p.archived ORDER BY coalesce(o.n,0) DESC""", (shop, shop))]
    keys = [(d0, s) for s in active] + sorted((k for k in data if k[0] != d0), reverse=True)
    rows = []
    for day, sku in keys:
        if skus and sku not in skus:
            continue
        rows.append({"day": str(day), "nm_id": sku, "offer_id": (nm.get(sku) or {}).get("offer_id"), **(data.get((day, sku)) or {})})
    cols = [{"field": "day", "title": "Дата", "type": "date"}, {"field": "offer_id", "title": "Артикул", "type": "text"}]
    cols += [{"field": k, "title": t, "type": "edit_text"} for k, t in CHECK_FIELDS]
    return {"columns": cols, "rows": rows, "plain": True}


OZ_HOME_ROWS = [("Заказы, ₽", "ordered_sum", "money"), ("Заказы, шт", "ordered", "int"), ("Расход на рекламу, ₽", "ads", "money"),
                ("ДРР от заказов, %", "drr", "pct"), ("Продажи минус возвраты, ₽", "sold_amt", "money"), ("Продажи, шт", "sold_qty", "int"),
                ("Себестоимость продаж, ₽", "cost", "money"),     
                ("Прибыль (после рекламы, себестоимости и налога), ₽", "profit", "money")]


def home(c, shop, f):
    """Главная магазина Ozon: ключевые цифры за сегодня, вчера и позавчера (расчёт Version2 «По дням»). Сегодня — неполный день;
    продажи и прибыль Ozon дописывает по начислениям с задержкой."""
    from ..sheets import ozv2
    t = today_msk()
    per = [("today", t, t), ("y", t - timedelta(days=1), t - timedelta(days=1)), ("y2", t - timedelta(days=2), t - timedelta(days=2))]
    r = ozv2.compute(c, shop, "day", per[2][1], t, _grp_skus(c, shop, f) or None, per=per)
    V = {}
    for (k, _, _), v in zip(per, r["cols"]):
        ads = float(v.get("ad.spent") or 0) + float(v.get("ozz.spent") or 0)
        V[k] = {"ordered_sum": v.get("ordered_sum"), "ordered": v.get("ordered"), "ads": ads, "sold_amt": v.get("sold_amt"),
                "sold_qty": v.get("sold_qty"), "profit": v.get("profit"), "cost": -float(v.get("cost") or 0),
                "drr": ads / float(v["ordered_sum"]) if v.get("ordered_sum") else 0}
    rows = [{"label": lab, "fmt": fmt, "C": V["today"][k] or 0, "D": V["y"][k] or 0, "F": V["y2"][k] or 0} for lab, k, fmt in OZ_HOME_ROWS]
    fmtd = lambda d: d.strftime("%d.%m")  
    cols = [{"field": "label", "title": "Ключевые показатели Ozon", "type": "label"},
            {"field": "C", "title": f"Сегодня {fmtd(t)} (неполный)", "type": "rowfmt"},
            {"field": "D", "title": f"Вчера {fmtd(t - timedelta(days=1))}", "type": "rowfmt"},
            {"field": "F", "title": f"Позавчера {fmtd(t - timedelta(days=2))}", "type": "rowfmt"}]
    return {"columns": cols, "rows": rows, "layout": "sheet", "home": True, "ozon": True}

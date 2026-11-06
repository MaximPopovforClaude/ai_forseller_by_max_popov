"""Self-hosted application component."""

from collections import defaultdict
from datetime import date, timedelta


COLS = [
    ("nm_id", "Артикул WB", "int"), ("seller", "Продавец", "text"), ("day", "Дата", "date"),
    ("year_week", "Год/Неделя", "int"), ("year_month", "Год/месяц", "int"),
    ("orders", "Кол-во заказов ВСЕГО", "int"), ("orders_sum", "Сумма ВСЕХ заказов, руб", "money"),
    ("orders_sum_spp", "Сумма ВСЕХ заказов с учетом скидки ВБ (СПП)", "money"),
    ("orders_avg", "Средняя цена ВСЕХ заказов, руб", "money"),
    ("orders_avg_spp", "Средняя цена ВСЕХ заказов с учетом скидки ВБ (СПП)", "money"),
    ("orders_spp_share", "Скидка ВБ (СПП) по ВСЕМ заказам", "share"),
    ("buyouts", "Кол-во выкупов", "int"), ("buyouts_sum", "Сумма выкупов, руб", "money"),
    ("commission", "Сумма комиссии ВБ, руб", "money"), ("for_pay", "К оплате продавцу, руб", "money"),
    ("commission_share", "Комиссия ВБ, %", "share"), ("cost", "Сумма себестоимости, руб", "money"),
    ("margin", "Маржа, руб", "money"), ("margin_share", "Маржа, %", "share"),
    ("logistics", "Сумма расходов на логистику, руб", "money"), ("ads", "Сумма расходов на рекламу, руб", "money"),
    ("storage", "Сумма расходов на хранение, руб", "money"), ("profit", "Прибыль, руб", "money"),
    ("profit_share", "Прибыль, %", "share"), ("storage_units", "Хранение (кол-во тарифицируемых", "int"),
    ("logistics_unit", "Логистика на единицу, руб", "money"),
    ("ad_views", "Реклама (кол-во просмотров)", "int"), ("ad_clicks", "Реклама (кол-во кликов)", "int"),
    ("ad_carts", "Реклама (кол-во добавлений в корзину)", "int"), ("ad_orders", "Реклама (кол-во заказов)", "int"),
    ("ad_shks", "Реклама (кол-во товаров в заказах)", "int"), ("ad_orders_sum", "Реклама (сумма заказов)", "money"),
    ("ad_ctr", "Реклама (CTR", "share"), ("ad_cpc", "Реклама (CPC", "money"),
    ("f_open", "Конверсии (кол-во переходов в карточку", "int"), ("f_cart", "Конверсии (положили в корзину)", "int"),
    ("f_orders", "Конверсии (заказали товаров)", "int"), ("f_to_cart", "Конверсии (конверсия в корзину)", "share"),
    ("f_to_order", "Конверсии (конверсия в заказ)", "share"),
    ("ok_orders", "в т.ч. кол-во заказов со статусом НЕотменен", "int"),
    ("ok_orders_sum", "в т.ч. сумма заказов со статусом НЕотменен, руб", "money"),
    ("ok_orders_sum_spp", "в т.ч. сумма заказов со статусом НЕотменен с учетом", "money"),
    ("cx_orders", "в т.ч. кол-во заказов со статусом Отменен", "int"),
    ("cx_orders_sum", "в т.ч. сумма заказов со статусом Отменен, руб", "money"),
    ("cx_orders_sum_spp", "в т.ч. сумма заказов со статусом Отменен с учетом", "money"),
    ("cx_share", "в т.ч. доля заказов со статусом Отменен", "share"),
    ("returns", "Кол-во возвратов", "int"), ("returns_for_pay", "Сумма возвратов (к оплате продавцу)", "money"),
    ("cxd_orders", "Кол-во Отмененных/Невыкупленных заказов в дату отмены", "int"),
    ("cxd_sum", "Сумма Отмененных/Невыкупленных заказов в дату отмены, руб", "money"),
    ("cxd_sum_spp", "Сумма Отмененных/Невыкупленных заказов в дату отмены с учетом", "money"),
    ("cxd_share", "Доля Отмененных/Невыкупленных заказов в дату отмены", "share"),
    ("drr_orders", "ДРР от суммы заказов", "share"), ("drr_buyouts", "ДРР от суммы выкупов", "share"),
    ("acceptance_qty", "Платная приемка Количество", "int"), ("acceptance_sum", "Платная приемка Сумма", "money"),
    ("f_orders_sum", "Конверсии (заказали на сумму)", "money"),
    ("buyouts_sum_before_spp", "Сумма выкупов до скидки ВБ (СПП)", "money"),
    ("returns_cost", "Сумма себестоимости возвратов", "money"),
    ("profit_with_returns", "Прибыль с учетом возвратов до налогов", "money"),
    ("ads_upd", "Сумма расходов на рекламу по УПД", "money"),
    ("ads_bonus", "Расход на рекламу бонусами (Кэшбэк)", "money"),
    ("commission_offer_orders", "Сумма комиссии ВБ (оферта) по заказам", "money"),
    ("cost_orders", "Сумма себестоимости заказов", "money"), ("margin_orders", "Маржа по всем заказам", "money"),
    ("profit_orders", "Прибыль по всем заказам до налогов", "money"),
    ("vat_orders", "Сумма НДС к начислению с заказов", "money"), ("vat_deduct_orders", "Сумма НДС к вычету с себестоимости заказов", "money"),
    ("vat_buyouts", "Сумма НДС к начислению с выкупов", "money"), ("vat_deduct_buyouts", "Сумма НДС к вычету с себестоимости выкупов", "money"),
    ("vat_returns", "Сумма уменьшения начисления НДС с возвратов", "money"),
    ("vat_deduct_returns", "Сумма уменьшения вычета НДС с себестоимости возвратов", "money"),
    ("logistics_orders", "Сумма расходов на логистику по заказам", "money"),
    ("logistics_avg_orders", "Средняя стоимость логистики по заказам", "money"),
    ("rating", "Оценка пользователей", "num"), ("local_share", "Локальные заказы в рамках одного региона", "share"),
    ("f_wishlist", "Конверсии (добавили в Отложенные)", "int"), ("delivery_hours", "Среднее время доставки", "num"),
    ("acquiring", "Расходы на эквайринг по выкупам", "money"),
]
KEYS = [k for k, _, _ in COLS]


def _div(a, b):
    if a is not None and b:
        return round(float(a) / float(b), 4)
    return 0 if a is not None and b is not None else None


def compute(c, acc_id: int, date_from: date, date_to: date) -> list[dict]:
    """Строки артикул×день за период (только дни, где есть хоть что-то)."""
    P = {"a": acc_id, "df": date_from, "dt": date_to}
    rows: dict = defaultdict(dict)

    def put(nm, day, **kw):
        rows[(nm, day)].update(kw)

    
    
    vat_rate = {}
    tx = c.execute("SELECT vat_rate FROM tax_settings WHERE account_id=%(a)s ORDER BY valid_from DESC LIMIT 1", P).fetchone()
    for r in ([] if not tx or not float(tx["vat_rate"] or 0) else c.execute("""SELECT nm_id, x->'value'->>0 v FROM nomenclature,
                          jsonb_array_elements(CASE WHEN jsonb_typeof(data->'characteristics')='array' THEN data->'characteristics' ELSE '[]'::jsonb END) x WHERE account_id=%(a)s AND x->>'id'='15001405'""", P)):
        try:
            vat_rate[r["nm_id"]] = float(str(r["v"]).replace("%", "").replace(",", ".") or 0)
        except ValueError:
            pass

    
    for r in c.execute("""
        SELECT nm_id, order_dt::date d, count(*) n, sum(price_with_disc) s, sum(finished_price) ss,
               count(*) FILTER (WHERE NOT is_cancel) okn, sum(price_with_disc) FILTER (WHERE NOT is_cancel) oks,
               sum(finished_price) FILTER (WHERE NOT is_cancel) okss,
               count(*) FILTER (WHERE is_cancel) cxn, sum(price_with_disc) FILTER (WHERE is_cancel) cxs,
               sum(finished_price) FILTER (WHERE is_cancel) cxss
        FROM orders WHERE account_id=%(a)s AND order_dt::date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2""", P):
        put(r["nm_id"], r["d"], orders=r["n"], orders_sum=r["s"], orders_sum_spp=r["ss"], ok_orders=r["okn"], ok_orders_sum=r["oks"] or 0,
            ok_orders_sum_spp=r["okss"] or 0, cx_orders=r["cxn"], cx_orders_sum=r["cxs"] or 0, cx_orders_sum_spp=r["cxss"] or 0)
    
    
    
    tariffs: dict[int, list] = {}
    for r in c.execute("""SELECT DISTINCT ON ((data->>'subjectID')::int, row_date) (data->>'subjectID')::int sid, row_date td,
                                 (data->>'paidStorageKgvp')::numeric fbw
                          FROM raw_rows WHERE account_id=%(a)s AND source='tariffs_commission' ORDER BY 1, 2""", P):
        tariffs.setdefault(r["sid"], []).append((r["td"], r["fbw"]))

    def rate(sid, d):
        snaps = tariffs.get(sid)
        if not snaps:
            return None
        best = None
        for td, fbw in snaps:          
            if td <= d:
                best = fbw
            else:
                break
        return best if best is not None else snaps[0][1]
    com: dict[tuple, float] = {}
    for r in c.execute("""SELECT o.nm_id, o.order_dt::date d, n.subject_id sid, sum(o.price_with_disc) s
                          FROM orders o JOIN nomenclature n ON n.account_id=o.account_id AND n.nm_id=o.nm_id
                          WHERE o.account_id=%(a)s AND o.order_dt::date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2,3""", P):
        k = rate(r["sid"], r["d"])
        if k is None or r["s"] is None:
            continue
        com[(r["nm_id"], r["d"])] = com.get((r["nm_id"], r["d"]), 0.0) + float(r["s"]) * float(k) / 100
    for (nm, d), v in com.items():
        put(nm, d, commission_offer_orders=round(v, 2))
    
    for r in c.execute("""
        SELECT nm_id, cancel_dt::date d, count(*) n, sum(price_with_disc) s, sum(finished_price) ss
        FROM orders WHERE account_id=%(a)s AND is_cancel AND cancel_dt::date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2""", P):
        put(r["nm_id"], r["d"], cxd_orders=r["n"], cxd_sum=r["s"], cxd_sum_spp=r["ss"])
    
    for r in c.execute("""
        SELECT nm_id, sale_dt::date d,
               count(*) FILTER (WHERE sale_id LIKE 'S%%') n, sum(finished_price) FILTER (WHERE sale_id LIKE 'S%%') s,
               sum(price_with_disc) FILTER (WHERE sale_id LIKE 'S%%') sb, sum(for_pay) FILTER (WHERE sale_id LIKE 'S%%') fp,
               count(*) FILTER (WHERE sale_id LIKE 'R%%') rn, sum(for_pay) FILTER (WHERE sale_id LIKE 'R%%') rfp
        FROM sales WHERE account_id=%(a)s AND sale_dt::date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2""", P):
        put(r["nm_id"], r["d"], buyouts=r["n"], buyouts_sum=r["s"] or 0, buyouts_sum_before_spp=r["sb"] or 0, for_pay=r["fp"] or 0,
            returns=-(r["rn"] or 0), returns_for_pay=-abs(r["rfp"] or 0))  
    
    for r in c.execute("""
        SELECT (nm->>'nmId')::bigint nm, row_date d, sum((nm->>'views')::numeric) v, sum((nm->>'clicks')::numeric) cl,
               sum((nm->>'atbs')::numeric) atbs, sum((nm->>'orders')::numeric) o, sum((nm->>'shks')::numeric) shks,
               sum((nm->>'sum_price')::numeric) sp, sum((nm->>'sum')::numeric) spend
        FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app, jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%(a)s AND source='ad_stats' AND row_date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2""", P):
        put(r["nm"], r["d"], ad_views=r["v"], ad_clicks=r["cl"], ad_carts=r["atbs"], ad_orders=r["o"], ad_shks=r["shks"],
            ad_orders_sum=r["sp"], ads=r["spend"])
    
    
    
    
    
    for fld, pay in (("ads_upd", "<> 'Кэшбэк'"), ("ads_bonus", "= 'Кэшбэк'")):
      for r in c.execute(f"""
        WITH upd AS (SELECT (data->>'advertId')::bigint adv, row_date d, sum((data->>'updSum')::numeric) s
                     FROM raw_rows WHERE account_id=%(a)s AND source='ad_upd' AND row_date BETWEEN %(df)s AND %(dt)s
                       AND coalesce(data->>'paymentType','') {pay} GROUP BY 1,2),
             st AS (SELECT (r.data->>'advertId')::bigint adv, r.row_date d, (nm->>'nmId')::bigint nm, sum((nm->>'sum')::numeric) s
                    FROM raw_rows r, jsonb_array_elements(CASE WHEN jsonb_typeof(r.data->'apps')='array' THEN r.data->'apps' ELSE '[]'::jsonb END) app, jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
                    WHERE r.account_id=%(a)s AND r.source='ad_stats' AND r.row_date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2,3),
             tot AS (SELECT adv, d, sum(s) s, count(*) n FROM st GROUP BY 1,2),
             cfg AS (SELECT row_key::bigint adv, (x->>'nm_id')::bigint nm, count(*) OVER (PARTITION BY row_key) n
                     FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'info'->'nm_settings')='array' THEN data->'info'->'nm_settings' ELSE '[]'::jsonb END) x WHERE account_id=%(a)s AND source='adverts')
        SELECT nm, d, sum(v) v FROM (
            SELECT st.nm, u.d, u.s * CASE WHEN t.s > 0 THEN st.s / t.s ELSE 1.0 / t.n END v
            FROM upd u JOIN tot t ON t.adv=u.adv AND t.d=u.d JOIN st ON st.adv=u.adv AND st.d=u.d
            UNION ALL
            SELECT cfg.nm, u.d, u.s / cfg.n FROM upd u JOIN cfg ON cfg.adv=u.adv
            WHERE NOT EXISTS (SELECT 1 FROM tot WHERE tot.adv=u.adv AND tot.d=u.d)
        ) x GROUP BY 1,2""", P):
        put(r["nm"], r["d"], **{fld: round(r["v"], 2)})
    
    
    
    real_days = set()
    real_sale = {}
    for r in c.execute("""
        SELECT (data->>'nmId')::bigint nm, (data->>'rrDate')::date d,
               sum((data->>'deliveryService')::numeric) lg,
               sum(CASE WHEN data->>'docTypeName' ILIKE 'продажа' THEN (data->>'acquiringFee')::numeric ELSE 0 END) aq,
               sum((data->>'quantity')::numeric) FILTER (WHERE data->>'sellerOperName'='Продажа') bn,
               sum((data->>'retailAmount')::numeric) FILTER (WHERE data->>'sellerOperName'='Продажа') bs,
               sum((data->>'retailPriceWithDisc')::numeric * (data->>'quantity')::numeric) FILTER (WHERE data->>'sellerOperName'='Продажа') bsb,
               sum((data->>'forPay')::numeric + (data->>'acquiringFee')::numeric) FILTER (WHERE data->>'sellerOperName'='Продажа') fp,
               sum((data->>'quantity')::numeric) FILTER (WHERE data->>'sellerOperName'='Возврат') rn,
               sum((data->>'forPay')::numeric + (data->>'acquiringFee')::numeric) FILTER (WHERE data->>'sellerOperName'='Возврат') rfp
        FROM (SELECT data FROM raw_rows WHERE account_id=%(a)s AND source='realization' AND row_date BETWEEN %(df)s AND %(dt)s
              UNION ALL
              SELECT data FROM raw_rows WHERE account_id=%(a)s AND source='realization_daily' AND row_date BETWEEN %(df)s AND %(dt)s
                AND row_date > (SELECT coalesce(max(row_date), '2000-01-01') FROM raw_rows WHERE account_id=%(a)s AND source='realization')) x
        WHERE (data->>'rrDate')::date BETWEEN %(df)s AND %(dt)s
          AND coalesce((data->>'nmId')::bigint, 0) <> 0 GROUP BY 1,2""", P):
        real_days.add(r["d"])
        put(r["nm"], r["d"], logistics=round(r["lg"], 2), acquiring=round(r["aq"], 2))
        real_sale[(r["nm"], r["d"])] = r
    
    
    
    for (nm, d), row in rows.items():
        if d not in real_days:
            continue
        r = real_sale.get((nm, d))
        if r is None or not (r["bn"] or r["rn"]):
            if row.get("buyouts") or row.get("returns"):
                row.update(buyouts=0, buyouts_sum=0, buyouts_sum_before_spp=0, for_pay=0, returns=0, returns_for_pay=0)
            continue
        row.update(buyouts=int(r["bn"] or 0), buyouts_sum=r["bs"] or 0, buyouts_sum_before_spp=r["bsb"] or 0, for_pay=r["fp"] or 0,
                   returns=-int(r["rn"] or 0), returns_for_pay=-abs(r["rfp"] or 0))
    
    
    wk = c.execute("""
        SELECT (data->>'nmId')::bigint nm, date_trunc('week', (data->>'rrDate')::date)::date w,
               sum((data->>'deliveryService')::numeric) lg, sum((data->>'deliveryAmount')::numeric) n
        FROM raw_rows WHERE account_id=%(a)s AND source='realization' AND row_date BETWEEN %(df)s::date - 70 AND %(dt)s
          AND (data->>'rrDate')::date BETWEEN %(df)s::date - 70 AND %(dt)s
          AND coalesce((data->>'nmId')::bigint, 0) <> 0 AND data->>'bonusTypeName' ILIKE 'К клиенту%%' GROUP BY 1,2""", P).fetchall()
    acq_hist = defaultdict(dict)   
    for r in c.execute("""
        SELECT (data->>'nmId')::bigint nm, date_trunc('week', (data->>'rrDate')::date)::date w,
               sum((data->>'acquiringFee')::numeric) a, sum((data->>'retailAmount')::numeric) s
        FROM raw_rows WHERE account_id=%(a)s AND source='realization' AND row_date BETWEEN %(df)s::date - 70 AND %(dt)s
          AND (data->>'rrDate')::date BETWEEN %(df)s::date - 70 AND %(dt)s
          AND data->>'docTypeName' ILIKE 'продажа' GROUP BY 1,2""", P):
        if r["s"]:
            acq_hist[r["nm"]][r["w"]] = float(r["a"] or 0) / float(r["s"])
    log_hist = defaultdict(dict)
    for r in wk:
        if r["n"]:
            log_hist[r["nm"]][r["w"]] = float(r["lg"]) / float(r["n"])
    last_real = max(real_days) if real_days else None

    
    shop_wk = defaultdict(list)
    for nm_, ws in log_hist.items():
        for w, val in ws.items():
            shop_wk[w].append(val)

    
    
    alt_nm, alt_shop = {}, None
    if not log_hist:
        tot_l = tot_q = 0.0
        for r in c.execute("""
            SELECT (data->>'nmId')::bigint nm, sum(coalesce((data->>'rebillLogisticCost')::numeric, 0) + coalesce((data->>'deliveryService')::numeric, 0)) l,
                   sum((data->>'quantity')::numeric) FILTER (WHERE data->>'docTypeName' ILIKE 'продажа') q
            FROM raw_rows WHERE account_id=%(a)s AND source='realization' AND row_date BETWEEN %(dt)s::date - 70 AND %(dt)s
              AND coalesce((data->>'nmId')::bigint, 0) <> 0 GROUP BY 1""", P):
            l, q = float(r["l"] or 0), float(r["q"] or 0)
            tot_l += l; tot_q += q
            if q >= 3:
                alt_nm[r["nm"]] = l / q
        alt_shop = tot_l / tot_q if tot_q else None

    def avg_log(nm, day):
        cur_w = day - timedelta(days=day.isoweekday() - 1)
        prev = [w for w in log_hist.get(nm, {}) if w < cur_w]
        if prev:
            return log_hist[nm][max(prev)]
        sw = [w for w in shop_wk if w < cur_w]
        if sw:
            return sum(shop_wk[max(sw)]) / len(shop_wk[max(sw)])
        return alt_nm.get(nm, alt_shop)
    
    for r in c.execute("""
        SELECT (data->>'nmId')::bigint nm, row_date d, sum((data->>'warehousePrice')::numeric) s, sum((data->>'barcodesCount')::numeric) n
        FROM raw_rows WHERE account_id=%(a)s AND source='paid_storage' AND row_date BETWEEN %(df)s AND %(dt)s GROUP BY 1,2""", P):
        put(r["nm"], r["d"], storage=round(r["s"], 2), storage_units=r["n"])
    
    for src in ("funnel", "funnel_day"):   
        for r in c.execute("""
            SELECT (data->>'nmId')::bigint nm, row_date d, data FROM raw_rows
            WHERE account_id=%(a)s AND source=%(src)s AND row_date BETWEEN %(df)s AND %(dt)s""", {**P, "src": src}):
            x = r["data"]
            if src == "funnel":
                put(r["nm"], r["d"], f_open=x.get("openCount"), f_cart=x.get("cartCount"), f_orders=x.get("orderCount"),
                    f_orders_sum=x.get("orderSum"), f_wishlist=x.get("addToWishlistCount"))
            else:
                ttr = x.get("timeToReady") or {}
                put(r["nm"], r["d"], f_open=x.get("openCount"), f_cart=x.get("cartCount"), f_orders=x.get("orderCount"),
                    f_orders_sum=x.get("orderSum"), f_wishlist=x.get("addToWishlist"), rating=x.get("feedbackRating"),
                    local_share=(x.get("localizationPercent") or 0) / 100,   
                    delivery_hours=(ttr.get("days", 0) * 24 + ttr.get("hours", 0)) if ttr else None)

    
    costs = defaultdict(list)
    for r in c.execute("SELECT nm_id, valid_from, cost FROM cost_price WHERE account_id=%(a)s ORDER BY nm_id, valid_from", P):
        costs[r["nm_id"]].append((r["valid_from"], r["cost"]))

    def cost_at(nm, day):
        cur = None
        for vf, cst in costs.get(nm, []):
            if vf <= day:
                cur = cst
        return cur

    out = []
    for (nm, day), m in sorted(rows.items(), key=lambda x: (x[0][1], x[0][0])):
        iso = day.isocalendar()
        row = {k: m.get(k) for k in KEYS}
        row.update(nm_id=nm, day=day, year_week=iso[0] * 100 + iso[1], year_month=day.year * 100 + day.month)
        o, s, ss = row["orders"] or 0, row["orders_sum"], row["orders_sum_spp"]
        row["orders_avg"] = round(s / o, 2) if o else None
        row["orders_avg_spp"] = round(ss / o, 2) if o else None
        row["orders_spp_share"] = round(1 - ss / s, 4) if s else None
        if row["buyouts_sum"] is not None and row["for_pay"] is not None:
            row["commission"] = round(row["buyouts_sum"] - row["for_pay"], 2)
            row["commission_share"] = _div(row["commission"], row["buyouts_sum_before_spp"])
        row["cx_share"] = _div(row["cx_orders"], o) if o else None
        row["cxd_share"] = _div(row["cxd_orders"], o) if o and row["cxd_orders"] is not None else None
        if row["ad_views"] is not None:
            row["ad_ctr"] = _div(row["ad_clicks"], row["ad_views"])
            row["ad_cpc"] = round(row["ads"] / row["ad_clicks"], 2) if row["ad_clicks"] else 0
        if row["f_open"] is not None:
            row["f_to_cart"] = _div(row["f_cart"], row["f_open"])
            row["f_to_order"] = _div(row["f_orders"], row["f_cart"])
        al = avg_log(nm, day)
        if row["logistics"] is None and (last_real is None or day > last_real) and row["buyouts"]:
            row["logistics"] = round(al * row["buyouts"], 2) if al is not None else None   
        if row["acquiring"] is None and (last_real is None or day > last_real) and row["buyouts"]:
            cw = day - timedelta(days=day.isoweekday() - 1)
            prev = [w for w in acq_hist.get(nm, {}) if w < cw]
            if prev:
                row["acquiring"] = round(float(row["buyouts_sum"] or 0) * acq_hist[nm][max(prev)], 2)
        if row["logistics"] is not None and row["buyouts"]:
            row["logistics_unit"] = round(row["logistics"] / row["buyouts"], 2)
        if o and al is not None:
            row["logistics_avg_orders"] = round(al, 2)
            row["logistics_orders"] = round(round(al, 2) * o, 2)   
        cu = cost_at(nm, day)
        if cu is not None:
            row["cost"] = round(cu * (row["buyouts"] or 0), 2)
            row["cost_orders"] = round(cu * o, 2)
            row["returns_cost"] = round(cu * (row["returns"] or 0), 2)
        z = lambda k: float(row.get(k) or 0)  
        if any(row.get(k) for k in ("buyouts", "for_pay", "logistics", "cost")):
            row["margin"] = round(z("for_pay") - z("cost") - z("logistics"), 2)
            row["margin_share"] = _div(row["margin"], row["buyouts_sum_before_spp"]) if row["buyouts_sum_before_spp"] else 0
        if any(row.get(k) for k in ("buyouts", "ads_upd", "storage", "acquiring", "logistics")):
            row["profit"] = round(z("margin") - z("ads_upd") - z("storage") - z("acquiring") - z("acceptance_sum"), 2)
            row["profit_share"] = _div(row["profit"], row["buyouts_sum_before_spp"]) if row["buyouts_sum_before_spp"] else 0
            row["profit_with_returns"] = round(row["profit"] + z("returns_for_pay") - z("returns_cost"), 2)
        if o or row.get("ads_upd") or row.get("storage"):
            row["margin_orders"] = round(z("orders_sum") - z("commission_offer_orders") - z("cost_orders") - z("logistics_orders"), 2)
            row["profit_orders"] = round(row["margin_orders"] - z("ads_upd") - z("storage") - z("acceptance_sum"), 2)
        
        
        r_ = vat_rate.get(nm, 0.0)
        k_ = r_ / (100 + r_)
        row["vat_orders"] = round(z("orders_sum_spp") * k_, 2)
        row["vat_deduct_orders"] = round(z("cost_orders") * k_, 2)
        row["vat_deduct_buyouts"] = round(z("cost") * k_, 2)
        row["vat_deduct_returns"] = round(z("returns_cost") * k_, 2)
        row["vat_buyouts"] = row["vat_returns"] = 0 if not r_ else None
        if row["ads"] is not None:
            row["drr_orders"] = _div(row["ads"], s) if s else None
            row["drr_buyouts"] = _div(row["ads"], row["buyouts_sum_before_spp"]) if row["buyouts_sum_before_spp"] else None
        out.append(row)
    from ..exclusions import drop, excluded
    return drop(out, excluded(c, acc_id))     


def cached(c, acc_id: int, date_from: date, date_to: date, nm_ids: list[int] | None = None) -> list[dict]:
    """Готовый агрегат из agg_nm_day, если период покрыт; иначе — расчёт на лету.
    nm_ids — только эти артикулы (фильтр в базе: у большого магазина не разбираем JSON всех артикулов)."""
    from ..materialize import ensure_cost_ready
    ensure_cost_ready(c, acc_id)
    st = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (acc_id,)).fetchone()
    if not st or not st["covered_from"] or date_from < st["covered_from"] or date_from > st["covered_to"]:
        from ..materialize import ensure_ready
        ensure_ready(c, acc_id, False)       
        return _only(compute(c, acc_id, date_from, date_to), nm_ids)
    out = []
    flt = " AND nm_id = ANY(%s)" if nm_ids else ""
    for r in c.execute("SELECT data FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s" + flt + " ORDER BY day, nm_id",
                       (acc_id, date_from, min(date_to, st["covered_to"])) + ((list(nm_ids),) if nm_ids else ())):
        d = r["data"]
        d["day"] = date.fromisoformat(d["day"])
        out.append(d)
    if date_to > st["covered_to"]:   
        from datetime import timedelta
        out += _only(compute(c, acc_id, st["covered_to"] + timedelta(days=1), date_to), nm_ids)
    from ..exclusions import drop, excluded
    return drop(out, excluded(c, acc_id))     


def _only(rows: list[dict], nm_ids) -> list[dict]:
    return [r for r in rows if r["nm_id"] in nm_ids] if nm_ids else rows


def iter_cached(c, acc_id: int, date_from: date, date_to: date, nm_ids: list[int] | None = None):
    """Same data/guards as cached(), but a server cursor bounds the JSON held by dashboards."""
    from uuid import uuid4
    from ..materialize import ensure_cost_ready, ensure_ready
    from ..exclusions import excluded
    ensure_cost_ready(c, acc_id)
    st = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (acc_id,)).fetchone()
    if not st or not st["covered_from"] or date_from < st["covered_from"] or date_from > st["covered_to"]:
        ensure_ready(c, acc_id, False)
        yield from _only(compute(c, acc_id, date_from, date_to), nm_ids)
        return
    ex = excluded(c, acc_id)
    flt = " AND nm_id = ANY(%s)" if nm_ids else ""
    
    
    with c.transaction(), c.cursor(name="dash_nm_day_" + uuid4().hex) as cur:
        cur.itersize = 256
        cur.execute("SELECT data FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s" + flt + " ORDER BY day, nm_id",
                    (acc_id, date_from, min(date_to, st["covered_to"])) + ((list(nm_ids),) if nm_ids else ()))
        for r in cur:
            d = r["data"]
            if d.get("nm_id") not in ex:
                d["day"] = date.fromisoformat(d["day"])
                yield d
    if date_to > st["covered_to"]:
        for d in _only(compute(c, acc_id, st["covered_to"] + timedelta(days=1), date_to), nm_ids):
            if d.get("nm_id") not in ex:
                yield d

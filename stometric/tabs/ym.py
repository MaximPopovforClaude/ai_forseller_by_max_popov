"""Вкладки магазина Яндекс Маркета — на данных Partner API (stometric/collectors_ym.py). Артикул = SKU на Маркете."""

from datetime import timedelta

from ..config import today_msk
from ..collectors_ym import MSK


def _skus(f, c=None, shop=None):
    """Фильтр артикулов: для Маркета в nm_ids приходят SKU на Маркете; склейка (своя группа) — её артикулы."""
    sk = f.get("nm_ids") or None
    if c is not None and f.get("group"):
        g = [r["nm_id"] for r in c.execute("SELECT nm_id FROM article_groups WHERE account_id=%s AND group_name=%s", (shop, f["group"]))]
        sk = [x for x in g if sk is None or x in sk] or [-1]
    return sk


def _empty(c, shop):
    if not c.execute("SELECT 1 FROM ym_orders WHERE account_id=%s LIMIT 1", (shop,)).fetchone():
        return "Заказы Маркета ещё загружаются (первая загрузка — до часа)"
    return None


def _day_cols(res, title):
    cols = [{"field": "label", "title": title, "type": "label"}]
    cols += [{"field": f"d{i}", "title": f"{d[8:10]}.{d[5:7]}", "type": "rowfmt"} for i, d in enumerate(res["days"])]
    return cols


def dash(c, shop, f):
    """Дашборд по дням — заказы и прибыль по заказам с учётом % выкупа, выкупы и услуги Маркета по статьям (по дню доставки),
    отмены и возвраты, остатки. Колонки — дни выбранного периода (не больше 90)."""
    from ..sheets import ymdash
    y = min(f["date_to"], today_msk())
    res = ymdash.sheet(c, shop, max(f["date_from"], y - timedelta(days=89)), y, _skus(f, c, shop))
    return {"columns": _day_cols(res, f"ПОКАЗАТЕЛИ (СНО: {res['tax']})"), "rows": res["rows"], "layout": "sheet", "empty": _empty(c, shop)}


def dash_nm(c, shop, f):
    """Дашборд по артикулу — те же показатели по дням для выбранных артикулов (SKU на Маркете). Без выбора — самый заказываемый
    артикул за 30 дней."""
    from ..sheets import ymdash
    sk = _skus(f, c, shop)
    note = None
    if not sk:
        r = c.execute("""SELECT coalesce(i.market_sku, f.market_sku) sku, max(i.offer_id) offer FROM ym_order_items i
                         JOIN ym_orders o ON o.account_id=i.account_id AND o.order_id=i.order_id
                         LEFT JOIN ym_offers f ON f.account_id=i.account_id AND f.offer_id=i.offer_id
                         WHERE i.account_id=%s AND o.order_day >= current_date - 30 GROUP BY 1 ORDER BY sum(i.initial_qty) DESC NULLS LAST LIMIT 1""",
                      (shop,)).fetchone()
        if not r or not r["sku"]:
            return {"columns": [], "rows": [], "empty": _empty(c, shop) or "Выберите артикул сверху"}
        sk = [r["sku"]]
        note = f"Артикул не выбран — показан самый заказываемый за 30 дней: {r['offer']} (SKU {r['sku']}). Выберите другой сверху."
    y = min(f["date_to"], today_msk())
    res = ymdash.sheet(c, shop, max(f["date_from"], y - timedelta(days=89)), y, sk)
    names = c.execute("SELECT offer_id, name FROM ym_offers WHERE account_id=%s AND market_sku = ANY(%s)", (shop, sk)).fetchall()
    title = "; ".join(f"{x['offer_id']} {x['name'] or ''}"[:80] for x in names[:3]) or "ПОКАЗАТЕЛИ"
    return {"columns": _day_cols(res, title), "rows": res["rows"], "layout": "sheet", "note": note}


HOME_ROWS = [("Заказы, ₽", "o_sum", "money"), ("Заказы, шт", "o_qty", "int"), ("Буст продаж по заказам, ₽", "o_boost", "money"),
             ("ДРР (буст) от заказов, %", "drr", "pct"), ("Выкупы, ₽", "b_sum", "money"), ("Выкупы, шт", "b_qty", "int"),
             ("Услуги Маркета по выкупам, ₽", "x_total", "money"), ("Себестоимость выкупов, ₽", "b_cost", "money"),
             ("Прибыль по заказам с учётом % выкупа (оценка), ₽", "o_profit", "money"),
             ("Оперативная прибыль по выкупам, ₽", "f_profit", "money")]


def home(c, shop, f):
    """Главная магазина Яндекс Маркета: ключевые цифры за сегодня, вчера и позавчера. Сегодня — неполный день; заказы Маркет отдаёт
    с задержкой до 40 минут."""
    from ..sheets import ymdash
    t = today_msk()
    per = [("today", t, t), ("y", t - timedelta(days=1), t - timedelta(days=1)), ("y2", t - timedelta(days=2), t - timedelta(days=2))]
    r = ymdash.compute(c, shop, per[2][1], t, _skus(f, c, shop), per=per)
    V = r["V"]
    rows = [{"label": lab, "fmt": fmt, "C": round(V["today"][k], 4), "D": round(V["y"][k], 4), "F": round(V["y2"][k], 4)} for lab, k, fmt in HOME_ROWS]
    fmtd = lambda d: d.strftime("%d.%m")  
    cols = [{"field": "label", "title": "Ключевые показатели Яндекс Маркета", "type": "label"},
            {"field": "C", "title": f"Сегодня {fmtd(t)} (неполный)", "type": "rowfmt"},
            {"field": "D", "title": f"Вчера {fmtd(t - timedelta(days=1))}", "type": "rowfmt"},
            {"field": "F", "title": f"Позавчера {fmtd(t - timedelta(days=2))}", "type": "rowfmt"}]
    return {"columns": cols, "rows": rows, "layout": "sheet", "home": True,
            "hint": "Заказы — по дню заказа, выкупы и услуги Маркета — по дню доставки. Маркет отдаёт заказы с задержкой до 40 минут."}


def svod(c, shop, f):
    """2#СводнаяПоАртикулам — по каждому артикулу: заказы и отмены за период, выкупы и возвраты, услуги Маркета, прибыль по выкупам,
    остатки, цена и себестоимость; последним — сумма заказов за последние 4 недели (по вчера), по ней сортировка."""
    from ..sheets import ymdash
    a, b = f["date_from"], min(f["date_to"], today_msk())
    y4 = today_msk() - timedelta(days=1)
    cost = ymdash.costs(c, shop)
    R = {}

    def row(sku):
        return R.setdefault(sku, {"o_qty": 0.0, "o_sum": 0.0, "c_qty": 0.0, "b_qty": 0.0, "b_sum": 0.0, "r_qty": 0.0, "serv": 0.0, "o4": 0.0})
    for r in ymdash.items(c, shop, min(a, y4 - timedelta(days=27)), b, "order_day"):
        if not r["sku"]:
            continue
        q0 = float(r["initial_qty"] or r["qty"] or 0)
        s0 = (r["unit"] or 0) * q0
        x = row(r["sku"])
        if y4 - timedelta(days=27) <= r["order_day"] <= y4:
            x["o4"] += s0
        if a <= r["order_day"] <= b:
            x["o_qty"] += q0
            x["o_sum"] += s0
            if r["status"] in ymdash.CANCEL:
                x["c_qty"] += q0
    st_items = ymdash.items(c, shop, a, b, "status_day")
    svc = ymdash.Services(c, shop, {r["order_id"] for r in st_items})
    for r in st_items:
        if not r["sku"]:
            continue
        x = row(r["sku"])
        if r["status"] in ymdash.DONE:
            x["b_qty"] += float(r["qty"] or 0)
            x["b_sum"] += float(r["total"])
        elif r["status"] in ymdash.RETURNED:
            x["r_qty"] += float(r["initial_qty"] or 0)
        else:
            continue
        x["serv"] += sum(v for k, v in svc.of(r)[0].items() if k in ymdash.X_KEYS)
    st = {r["sku"]: r for r in c.execute(
        """SELECT f.market_sku sku, sum(coalesce(s.available,0)) av, sum(coalesce(s.other,0)) ot,
                  string_agg(DISTINCT s.placement, '/') pl FROM ym_stocks s JOIN ym_offers f ON f.account_id=s.account_id AND f.offer_id=s.offer_id
           WHERE s.account_id=%s AND s.snap_at=(SELECT max(snap_at) FROM ym_stocks WHERE account_id=%s) GROUP BY 1""", (shop, shop))}
    offers = c.execute("""SELECT f.market_sku sku, f.offer_id, f.name, f.photo, f.archived, p.price, p.old_price FROM ym_offers f
                          LEFT JOIN ym_prices p ON p.account_id=f.account_id AND p.offer_id=f.offer_id
                          WHERE f.account_id=%s AND f.market_sku IS NOT NULL""", (shop,)).fetchall()
    rows = []
    for o in offers:
        x, s = R.get(o["sku"]), st.get(o["sku"])
        if o["archived"] and not x and not (s and s["av"]):
            continue
        x = x or row(o["sku"])
        cs = cost.get(o["sku"])
        rows.append({"photo": o["photo"], "offer_id": o["offer_id"], "sku": o["sku"], "name": o["name"], "price": o["price"],
                     "old_price": o["old_price"], "cost": cs, "orders_qty": x["o_qty"] or None, "orders_sum": round(x["o_sum"], 2) or None,
                     "cancel_qty": x["c_qty"] or None, "buy_qty": x["b_qty"] or None, "buy_sum": round(x["b_sum"], 2) or None,
                     "ret_qty": x["r_qty"] or None, "serv": round(x["serv"], 2) or None,
                     "profit": round(x["b_sum"] + x["serv"] - (cs or 0) * x["b_qty"], 2) if x["b_qty"] else None,
                     "stock": s["av"] if s else None, "stock_other": s["ot"] if s else None, "model": s["pl"] if s else None,
                     "orders_sum_4w": round(x["o4"], 2)})
    if _skus(f, c, shop):
        rows = [r for r in rows if r["sku"] in _skus(f, c, shop)]
    rows.sort(key=lambda r: (-(r["orders_sum_4w"] or 0), -(r["orders_sum"] or 0), r["offer_id"] or ""))
    cols = [("photo", "Фото", "image"), ("offer_id", "Артикул продавца", "text"), ("sku", "SKU на Маркете", "int"), ("name", "Название", "text"),
            ("price", "Цена, ₽", "money"), ("old_price", "Цена до скидки, ₽", "money"), ("cost", "Себестоимость, ₽", "money"),
            ("orders_qty", "Заказы, шт", "int"), ("orders_sum", "Заказы, ₽", "money"), ("cancel_qty", "Отмены, шт", "int"),
            ("buy_qty", "Выкупы, шт", "int"), ("buy_sum", "Выкупы, ₽", "money"), ("ret_qty", "Возвраты, шт", "int"),
            ("serv", "Услуги Маркета по выкупам и возвратам (деньгами и баллами), ₽", "money"),
            ("profit", "Прибыль по выкупам до налога и общих расходов, ₽", "money"), ("stock", "Остаток доступно, шт", "int"),
            ("stock_other", "В пути / резерв / брак, шт", "int"), ("model", "Модель (склад)", "text"),
            ("orders_sum_4w", f"Сумма всех заказов, руб, за последние 4 недели ({y4 - timedelta(days=27):%d.%m}–{y4:%d.%m})", "money")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows, "sort": {"field": "orders_sum_4w", "desc": True},
            "empty": _empty(c, shop)}


def stocks(c, shop, f):
    """Остатки по складам — строка на артикул, столбец на склад (название склада и модель FBY/FBS в заголовке): доступно к продаже, шт.
    Рядом — всего доступно и «в пути / резерв / брак». Последний снимок остатков."""
    data = c.execute(
        """SELECT s.offer_id, f.market_sku sku, f.name, f.photo, s.warehouse_id, s.placement, w.name wname,
                  sum(coalesce(s.available,0)) av, sum(coalesce(s.other,0)) ot
           FROM ym_stocks s LEFT JOIN ym_offers f ON f.account_id=s.account_id AND f.offer_id=s.offer_id
           LEFT JOIN ym_warehouses w ON w.warehouse_id=s.warehouse_id
           WHERE s.account_id=%s AND s.snap_at=(SELECT max(snap_at) FROM ym_stocks WHERE account_id=%s)
           GROUP BY 1,2,3,4,5,6,7""", (shop, shop)).fetchall()
    sk = _skus(f, c, shop)
    if sk:
        data = [r for r in data if r["sku"] in sk]
    R, W = {}, {}
    for r in data:
        x = R.setdefault(r["offer_id"], {"photo": r["photo"], "offer_id": r["offer_id"], "sku": r["sku"], "name": r["name"], "total": 0.0, "other": 0.0})
        k = f"w{r['warehouse_id']}"
        x[k] = (x.get(k) or 0) + float(r["av"])
        x["total"] += float(r["av"])
        x["other"] += float(r["ot"])
        nm = (r["wname"] or f"склад {r['warehouse_id']}").replace("Яндекс.Маркет ", "").strip()
        w = W.setdefault(k, {"title": f"{nm} ({r['placement']})", "q": 0.0})
        w["q"] += float(r["av"])
    for x in R.values():
        for k in W:
            if not x.get(k):
                x[k] = None
    cols = [{"field": "photo", "title": "Фото", "type": "image"}, {"field": "offer_id", "title": "Артикул продавца", "type": "text"},
            {"field": "sku", "title": "SKU на Маркете", "type": "int"}, {"field": "name", "title": "Название", "type": "text"},
            {"field": "total", "title": "Всего доступно, шт", "type": "int"}]
    cols += [{"field": k, "title": w["title"], "type": "int"} for k, w in sorted(W.items(), key=lambda kv: -kv[1]["q"])]
    cols.append({"field": "other", "title": "В пути / резерв / брак, шт", "type": "int"})
    snap = c.execute("SELECT max(snap_at) t FROM ym_stocks WHERE account_id=%s", (shop,)).fetchone()["t"]
    return {"columns": cols, "rows": sorted(R.values(), key=lambda x: -x["total"]), "sort": {"field": "total", "desc": True},
            "note": f"Снимок остатков: {snap.astimezone(MSK):%d.%m %H:%M} МСК" if snap else None}


def cost_tab(c, shop, f):
    """Себестоимость по артикулам Маркета (SKU на Маркете); правка — с датой начала действия (прошлое не переписывается)."""
    rows = c.execute(
        """SELECT p.market_sku nm_id, p.offer_id vendor_code, p.name title, p.photo, cp.cost, cp.valid_from, cp.note, g.group_name
           FROM ym_offers p LEFT JOIN article_groups g ON g.account_id=p.account_id AND g.nm_id=p.market_sku
           LEFT JOIN LATERAL (SELECT cost, valid_from, note FROM cost_price x WHERE x.account_id=p.account_id AND x.nm_id=p.market_sku
                              AND valid_from <= current_date ORDER BY valid_from DESC LIMIT 1) cp ON true
           WHERE p.account_id=%s AND p.market_sku IS NOT NULL ORDER BY p.archived, (cp.cost IS NULL) DESC, p.offer_id""", (shop,)).fetchall()
    cols = [{"field": "photo", "title": "Фото", "type": "image"}, {"field": "nm_id", "title": "SKU на Маркете", "type": "int"},
            {"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "title", "title": "Название", "type": "text"},
            {"field": "cost", "title": "Себестоимость, ₽ (двойной клик — изменить)", "type": "edit_money"},
            {"field": "valid_from", "title": "Действует с", "type": "date"}, {"field": "note", "title": "Источник", "type": "text"},
            {"field": "group_name", "title": "Склейка (двойной клик — изменить)", "type": "edit_text"}]
    return {"columns": cols, "rows": rows, "editable": "cost"}


def products(c, shop, f):
    """БД#Номенклатура — товары Маркета: артикул продавца, SKU на Маркете, бренд, категория, статус карточки, цены."""
    rows = c.execute(
        """SELECT p.photo, p.offer_id, p.market_sku, p.name, p.vendor, p.category, p.card_status, p.archived, pr.price, pr.old_price, p.updated_at
           FROM ym_offers p LEFT JOIN ym_prices pr ON pr.account_id=p.account_id AND pr.offer_id=p.offer_id
           WHERE p.account_id=%s ORDER BY p.archived, p.offer_id""", (shop,)).fetchall()
    cols = [("photo", "Фото", "image"), ("offer_id", "Артикул продавца", "text"), ("market_sku", "SKU на Маркете", "int"), ("name", "Название", "text"),
            ("vendor", "Бренд", "text"), ("category", "Категория", "text"), ("card_status", "Статус карточки", "text"), ("archived", "Архив", "text"),
            ("price", "Цена, ₽", "money"), ("old_price", "Цена до скидки, ₽", "money"), ("updated_at", "Обновлено", "datetime")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def orders(c, shop, f):
    """БД#Заказы — заказы Маркета за период: дата, модель, статус, товары, цена продажи и услуги Маркета (без данных покупателей)."""
    rows = c.execute(
        """SELECT o.order_day, o.order_id, o.placement, o.status, o.status_day, o.region, i.offer_id, coalesce(i.market_sku, f.market_sku) sku,
                  i.name, i.initial_qty, i.qty, i.price, coalesce(i.buyer_total,0)+coalesce(i.cashback,0)+coalesce(i.coupons,0) total,
                  i.buyer_total, coalesce(i.cashback,0)+coalesce(i.coupons,0) market, o.commission
           FROM ym_orders o JOIN ym_order_items i ON i.account_id=o.account_id AND i.order_id=o.order_id
           LEFT JOIN ym_offers f ON f.account_id=i.account_id AND f.offer_id=i.offer_id
           WHERE o.account_id=%s AND o.order_day BETWEEN %s AND %s AND NOT o.fake ORDER BY o.order_day DESC, o.order_id DESC LIMIT 20000""",
        (shop, f["date_from"], f["date_to"])).fetchall()
    if _skus(f, c, shop):
        rows = [r for r in rows if r["sku"] in _skus(f, c, shop)]
    cols = [("order_day", "Дата заказа", "date"), ("order_id", "Заказ", "int"), ("placement", "Модель", "text"), ("status", "Статус", "text"),
            ("status_day", "Статус с", "date"), ("region", "Регион", "text"), ("offer_id", "Артикул продавца", "text"), ("sku", "SKU на Маркете", "int"),
            ("name", "Название", "text"), ("initial_qty", "Заказано, шт", "int"), ("qty", "Осталось в заказе, шт", "int"),
            ("price", "Цена для покупателя за шт, ₽", "money"), ("total", "Сумма (цена продажи), ₽", "money"),
            ("buyer_total", "Оплачено покупателем, ₽", "money"), ("market", "Баллы и купоны Маркета, ₽", "money"),
            ("commission", "Услуги Маркета по заказу, ₽", "money")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


ADD = {"o_avg", "b_avg", "share", "drr", "o_profit_p", "f_profit_p", "c_share", "st_qty", "st_cost"}   


def dash5(c, shop, f):
    """5#Дашборд — как у WB: день (вчера) и позавчера, прошлая полная неделя и неделя до неё, текущий месяц и два прошлых, прогноз
    месяца (среднее за окно × дней в месяце); рядом — изменение. Строки — расчёт Маркета: заказы и прибыль по заказам с % выкупа,
    выкупы и услуги Маркета (деньгами и баллами) по дню доставки, отмены, возвраты, остатки."""
    import calendar
    from ..sheets import dash5 as d5, ymdash
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    P = d5.periods(y)
    r = ymdash.compute(c, shop, min(a for a, _ in P.values()), y, _skus(f, c, shop), per=[(k, a, b) for k, (a, b) in P.items()])
    V = r["V"]
    a, b = P["M"]
    k = calendar.monthrange(b.year, b.month)[1] / ((b - a).days + 1)
    from collections import defaultdict
    V["M"] = defaultdict(float, {key: (v if key in ADD else v * k) for key, v in V["M"].items()})

    def chg(x, z, key, fmt):
        if fmt == "pct":
            return V[x][key] - V[z][key]
        return V[x][key] / V[z][key] - 1 if V[z][key] else 0
    rows = []
    for key, lab, fmt in ymdash.ROWS:
        row = {"label": lab, "fmt": fmt, "key": key}
        if fmt != "h":
            for col in P:
                if key.startswith("st_") and col != "C":
                    continue
                row[col] = round(V[col][key], 4 if fmt == "pct" else 2)
            if not key.startswith("st_"):
                row.update(E=round(chg("C", "D", key, fmt), 4), H=round(chg("F", "G", key, fmt), 4),
                           L=round(chg("J", "K", key, fmt), 4), N=round(chg("M", "J", key, fmt), 4))
        rows.append(row)
    fmtp = lambda a, b: f"{a:%d.%m}" + ("" if a == b else f" – {b:%d.%m}")  
    months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    mon = lambda d: f"{months[d.month - 1]} {d.year}"  
    cols = [{"field": "label", "title": f"ПОКАЗАТЕЛИ (СНО: {r['tax']})", "type": "label"},
            {"field": "C", "title": f"День {fmtp(*P['C'])}", "type": "rowfmt"}, {"field": "D", "title": fmtp(*P["D"]), "type": "rowfmt"},
            {"field": "E", "title": "изм.", "type": "change"},
            {"field": "F", "title": f"Неделя {fmtp(*P['F'])}", "type": "rowfmt"}, {"field": "G", "title": fmtp(*P["G"]), "type": "rowfmt"},
            {"field": "H", "title": "изм.", "type": "change"},
            {"field": "I", "title": f"Месяц {mon(P['I'][0])} (по {P['I'][1]:%d.%m})", "type": "rowfmt"},
            {"field": "J", "title": mon(P["J"][0]), "type": "rowfmt"}, {"field": "K", "title": mon(P["K"][0]), "type": "rowfmt"},
            {"field": "L", "title": "изм.", "type": "change"},
            {"field": "M", "title": f"Прогноз {mon(P['M'][1])}", "type": "rowfmt"}, {"field": "N", "title": "изм.", "type": "change"}]
    return {"columns": cols, "rows": rows, "layout": "sheet", "empty": _empty(c, shop)}


def fin_sku(c, shop, f):
    """Финотчёт по SKU: P&L по «Отчёту по платежам» Маркета за период по каждому артикулу — выкупы (платежи покупателей + баллы за скидку
    Маркета), возвраты, услуги Маркета по статьям (деньгами и баллами), себестоимость, раздачи и внешняя реклама, к оплате на р/с, налог,
    доход до постоянных расходов, ROS и ROI. Период — по дате транзакции."""
    from ..sheets import ymfin
    res = ymfin.compute(c, shop, f["date_from"], f["date_to"])
    rows = res["rows"]
    sk = _skus(f, c, shop)
    if sk:
        rows = [r for r in rows if r["sku"] in sk]
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in ymfin.COLS], "rows": rows,
            "rules": {"profit": [{"gt": None, "le": 0, "color": "#fecaca"}], "ros": [{"gt": None, "le": 0, "color": "#fecaca"}]},
            "note": f"По «Отчёту по платежам» Маркета (дата транзакции). Баллы за скидку Маркета Маркет тратит на оплату своих услуг — "
                    f"на р/с приходят только деньги. СНО: {res['tax']}."}


def _abc(items: list) -> dict:
    """ABC как у WB: по убыванию показателя, накопленная доля ≤ 0,8 — A, ≤ 0,95 — B, иначе C."""
    from .basic import _abc as wb_abc
    return wb_abc(items)


def abc(c, shop, f):
    """Сводная#ABC#ОперативныеДанные: ABC-группы артикулов по прибыли, марже и «к оплате» за 4 последних месяца — по «Отчёту по платежам»."""
    from ..sheets import ymdash, ymfin
    end = min(f["date_to"], today_msk())
    beg = (end.replace(day=1) - timedelta(days=95)).replace(day=1)
    A = ymfin.by_sku(c, shop, beg, end, month=True)
    regime, rate = ymdash.tax_of(c, shop, end)
    months = sorted({m for _, m in A}, reverse=True)[:4]
    S = {m: {k: {} for k in ("profit", "margin", "for_pay")} for m in months}
    for (sku, m), x in A.items():
        if not sku or m not in S:
            continue
        S[m]["margin"][sku] = x["margin"]
        S[m]["profit"][sku] = x["margin"] - ymfin.tax_for(regime, rate, x)
        S[m]["for_pay"][sku] = x["to_pay"]
    off = {r["market_sku"]: r["offer_id"] for r in c.execute("SELECT market_sku, offer_id FROM ym_offers WHERE account_id=%s", (shop,))}
    res = {}
    for m in months:
        for k in ("profit", "margin", "for_pay"):
            for sku, letter in _abc(list(S[m][k].items())).items():
                res.setdefault(sku, {})[f"{k}_{m}"] = letter
                res[sku][f"v{k}_{m}"] = round(S[m][k][sku], 2)
    out = [{"vendor_code": off.get(s), "nm_id": s, **v} for s, v in res.items()]
    sk = _skus(f, c, shop)
    if sk:
        out = [r for r in out if r["nm_id"] in sk]
    out.sort(key=lambda r: "".join(r.get(f"profit_{m}", "C") for m in months))
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "SKU на Маркете", "type": "int"}]
    for m in months:
        lab = f"{m[5:]}.{m[:4]}"
        cols += [{"field": f"profit_{m}", "title": f"{lab}: ABC по прибыли", "type": "text", "group": lab},
                 {"field": f"margin_{m}", "title": "ABC по марже", "type": "text", "group": ""},
                 {"field": f"for_pay_{m}", "title": "ABC по «к оплате»", "type": "text", "group": ""},
                 {"field": f"vprofit_{m}", "title": "Прибыль, руб", "type": "money", "group": ""},
                 {"field": f"vmargin_{m}", "title": "Маржа, руб", "type": "money", "group": ""},
                 {"field": f"vfor_pay_{m}", "title": "К оплате, руб", "type": "money", "group": ""}]
    return {"columns": cols, "rows": out, "note": "По «Отчёту по платежам» Маркета (месяц — по дате транзакции). Маржа — до налога."}


def ads(c, shop, f):
    """Реклама (буст продаж) — по «Отчёту по бусту продаж» Маркета за период по каждому товару: показы, клики, заказы и доставленные
    (всего и с оплатой буста), расход деньгами и бонусами, средняя стоимость буста за доставленный товар, ДРР от выручки доставленных
    с бустом, кампании. Сверху — итог по магазину."""
    rows = c.execute(
        """SELECT b.shop_sku offer_id, f.market_sku sku, f.name, f.photo, sum(b.shows) shows, sum(b.shows_fee) shows_fee, sum(b.clicks) clicks,
                  sum(b.clicks_fee) clicks_fee, sum(b.orders) orders, sum(b.orders_fee) orders_fee, sum(b.delivered) delivered,
                  sum(b.delivered_fee) delivered_fee, sum(b.billed) billed, sum(b.bonuses) bonuses, sum(b.gmv) gmv, sum(b.gmv_fee) gmv_fee,
                  string_agg(DISTINCT b.campaigns, ', ') campaigns
           FROM ym_boost b LEFT JOIN ym_offers f ON f.account_id=b.account_id AND f.offer_id=b.shop_sku
           WHERE b.account_id=%s AND b.day BETWEEN %s AND %s GROUP BY 1,2,3,4""", (shop, f["date_from"], f["date_to"])).fetchall()
    sk = _skus(f, c, shop)
    if sk:
        rows = [r for r in rows if r["sku"] in sk]
    T = {"offer_id": "ИТОГО", "name": f"{len(rows)} товаров"}
    for r in rows:
        for k in ("shows", "shows_fee", "clicks", "clicks_fee", "orders", "orders_fee", "delivered", "delivered_fee", "billed", "bonuses", "gmv", "gmv_fee"):
            r[k] = float(r[k] or 0)
            T[k] = T.get(k, 0.0) + r[k]
    for r in rows + [T]:
        if "shows" not in r:
            continue
        spend = r["billed"] + r["bonuses"]
        r["spend"] = spend
        r["ctr"] = r["clicks"] / r["shows"] if r["shows"] else None
        r["cr"] = r["orders"] / r["clicks"] if r["clicks"] else None
        r["boost_share"] = r["orders_fee"] / r["orders"] if r["orders"] else None
        r["cpo"] = spend / r["delivered_fee"] if r["delivered_fee"] else None
        r["drr"] = spend / r["gmv_fee"] if r["gmv_fee"] else None
        r["drr_all"] = spend / r["gmv"] if r["gmv"] else None
    rows.sort(key=lambda r: -r["spend"])
    cols = [("photo", "Фото", "image"), ("offer_id", "Артикул продавца", "text"), ("sku", "SKU на Маркете", "int"), ("name", "Название", "text"),
            ("spend", "Расход на буст, ₽", "money"), ("billed", "в т. ч. деньгами, ₽", "money"), ("bonuses", "в т. ч. бонусами, ₽", "money"),
            ("drr", "ДРР от выручки доставленных с бустом, %", "share"), ("drr_all", "ДРР от выручки всех доставленных, %", "share"),
            ("cpo", "Стоимость буста на доставленный товар, ₽", "money"),
            ("shows", "Показы", "int"), ("shows_fee", "Показы с бустом", "int"), ("clicks", "Клики", "int"), ("ctr", "CTR, %", "share"),
            ("orders", "Заказано, шт", "int"), ("orders_fee", "Заказано с бустом, шт", "int"), ("boost_share", "Доля заказов с бустом", "share"),
            ("cr", "Конверсия клик → заказ", "share"), ("delivered", "Доставлено, шт", "int"), ("delivered_fee", "Доставлено с бустом, шт", "int"),
            ("gmv", "Выручка доставленных, ₽", "money"), ("gmv_fee", "Выручка доставленных с бустом, ₽", "money"), ("campaigns", "Кампании", "text")]
    d0 = c.execute("SELECT min(day) d, max(day) m FROM ym_boost WHERE account_id=%s", (shop,)).fetchone()
    note = f"«Отчёт по бусту продаж» Маркета, загружено с {d0['d']:%d.%m.%Y} по {d0['m']:%d.%m.%Y}." if d0 and d0["d"] else\
        "Отчёт по бусту ещё загружается."
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": ([T] if rows else []) + rows, "note": note}

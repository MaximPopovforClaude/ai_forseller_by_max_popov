"""Первые вкладки — на тех данных, что уже собираются (каркас для остальных)."""

from datetime import timedelta

from ..config import today_msk


def _nm_filter(f, col="nm_id"):
    if f.get("nm_ids"):
        return f" AND {col} = ANY(%(nm_ids)s)", {"nm_ids": f["nm_ids"]}
    return "", {}


def nomenclature(c, shop, f):
    """БД#Номенклатура — карточки товаров из API WB (Контент): артикулы, предмет, размеры, баркоды, габариты."""
    w, p = _nm_filter(f)
    rows = c.execute(
        f"""SELECT n.nm_id, n.vendor_code, n.brand, n.title, n.imt_id, n.subject_id, n.subject,
                   n.created_at::date AS created, n.updated_at::date AS updated,
                   (SELECT string_agg(DISTINCT s.tech_size, ', ') FROM nm_sizes s WHERE s.account_id=n.account_id AND s.nm_id=n.nm_id) AS sizes,
                   (SELECT string_agg(sku, ', ') FROM nm_sizes s, unnest(s.skus) sku WHERE s.account_id=n.account_id AND s.nm_id=n.nm_id) AS barcodes,
                   n.data->'dimensions'->>'width' AS width, n.data->'dimensions'->>'height' AS height,
                   n.data->'dimensions'->>'length' AS length, n.data->'dimensions'->>'weightBrutto' AS weight,
                   n.data->'photos'->0->>'tm' AS photo
            FROM nomenclature n WHERE n.account_id=%(shop)s {w} ORDER BY n.vendor_code""", {"shop": shop, **p}).fetchall()
    cols = [("photo", "Фото", "image"), ("nm_id", "Артикул WB", "int"), ("vendor_code", "Артикул продавца", "text"),
            ("brand", "Бренд", "text"), ("title", "Наименование товара", "text"), ("imt_id", "ID объединённой карточки", "int"),
            ("subject_id", "ID предмета", "int"), ("subject", "Название предмета", "text"), ("created", "Создана", "date"),
            ("updated", "Изменена", "date"), ("sizes", "Размеры", "text"), ("barcodes", "Штрихкоды", "text"),
            ("width", "Ширина, см", "num"), ("height", "Высота, см", "num"), ("length", "Длина, см", "num"), ("weight", "Вес, кг", "num")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def orders_daily(c, shop, f):
    """Заказы по дням за выбранный период (по дате заказа, МСК): количество, суммы до и после СПП, отменённые на сейчас."""
    w, p = _nm_filter(f, "o.nm_id")
    rows = c.execute(
        f"""SELECT o.order_dt::date AS day, count(*) AS orders, sum(o.price_with_disc) AS sum_seller,
                   sum(o.finished_price) AS sum_spp, sum(CASE WHEN o.is_cancel THEN 1 ELSE 0 END) AS cancels,
                   round(100.0 * (1 - sum(o.finished_price) / NULLIF(sum(o.price_with_disc), 0)), 2) AS spp_pct
            FROM orders o WHERE o.account_id=%(shop)s AND o.order_dt::date BETWEEN %(df)s AND %(dt)s {w}
            GROUP BY 1 ORDER BY 1""", {"shop": shop, "df": f["date_from"], "dt": f["date_to"], **p}).fetchall()
    cols = [("day", "Дата", "date"), ("orders", "Кол-во заказов", "int"), ("sum_seller", "Сумма заказов со скидкой продавца, ₽", "money"),
            ("sum_spp", "Сумма заказов с учётом СПП, ₽", "money"), ("spp_pct", "СПП, %", "pct"), ("cancels", "Отменено (на сейчас)", "int")]
    chart = {"x": "day", "series": [{"field": "orders", "title": "Заказы, шт", "type": "bar"},
                                    {"field": "sum_seller", "title": "Сумма, ₽", "type": "line", "axis": 1}]}
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows, "chart": chart}


def stocks_current(c, shop, f):
    """БД#ОстаткиТекущиеПоСкладам — остатки, доступные к продаже (API WB «Остатки на складах WB», обновляется раз в 30 мин)."""
    w, p = _nm_filter(f, "s.nm_id")
    rows = c.execute(
        f"""WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%(shop)s)
            SELECT n.vendor_code, s.nm_id, z.tech_size, n.subject, n.brand, s.quantity, s.warehouse,
                   s.in_way_to_client, s.in_way_from_client,
                   coalesce(s.quantity,0)+coalesce(s.in_way_to_client,0)+coalesce(s.in_way_from_client,0) AS full_qty, s.snap_at
            FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t
            LEFT JOIN nomenclature n ON n.account_id=s.account_id AND n.nm_id=s.nm_id
            LEFT JOIN nm_sizes z ON z.account_id=s.account_id AND z.chrt_id=s.chrt_id
            WHERE s.account_id=%(shop)s {w} ORDER BY n.vendor_code, s.warehouse""", {"shop": shop, **p}).fetchall()
    cols = [("vendor_code", "Артикул продавца", "text"), ("nm_id", "Артикул WB", "int"), ("tech_size", "Размер", "text"),
            ("subject", "Предмет", "text"), ("brand", "Бренд", "text"), ("quantity", "Остаток (доступный для продажи)", "int"),
            ("warehouse", "Склад ВБ", "text"), ("in_way_to_client", "В пути к клиенту", "int"),
            ("in_way_from_client", "В пути от клиента", "int"), ("full_qty", "Полное количество", "int"),
            ("snap_at", "Дата получения данных из API WB", "datetime")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def update_status(c, shop, f):
    """СтатусОбновления — когда каждый источник данных WB последний раз собирался и с какой ошибкой (сбор — каждые 10 мин)."""
    rows = c.execute(
        """SELECT collector, last_run_at, last_ok_at, left(last_error, 300) AS last_error FROM collector_state
           WHERE account_id=%(shop)s AND collector NOT IN ('_rebuild','_cost_rebuild') ORDER BY collector""", {"shop": shop}).fetchall()
    cols = [("collector", "Источник", "text"), ("last_run_at", "Последний запуск", "datetime"),
            ("last_ok_at", "Последний успех", "datetime"), ("last_error", "Ошибка", "text")]
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows}


def nm_day(c, shop, f):
    """БД#ДашбордПоАртикуламДням — агрегат артикул × день (78 колонок эталона)."""
    from ..agg import nm_day as agg
    rows = agg.cached(c, shop, f["date_from"], f["date_to"])
    if f.get("nm_ids"):
        rows = [r for r in rows if r["nm_id"] in f["nm_ids"]]
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in agg.COLS if k != "seller"], "rows": rows}


def by_day(c, shop, f):
    """Сумма по всем (или выбранным) артикулам по дням — основа 4#ДашбордПоДням; доли пересчитываются из сумм."""
    from ..agg import nm_day as agg
    rows = agg.cached(c, shop, f["date_from"], f["date_to"])
    if f.get("nm_ids"):
        rows = [r for r in rows if r["nm_id"] in f["nm_ids"]]
    sums = {}
    add = [k for k, _, t in agg.COLS if t in ("int", "money") and k not in ("nm_id", "year_week", "year_month")]
    for r in rows:
        d = sums.setdefault(r["day"], {"day": r["day"]})
        for k in add:
            if r.get(k) is not None:
                d[k] = (d.get(k) or 0) + r[k]
    out = []
    for d in sorted(sums.values(), key=lambda x: x["day"]):
        o, s = d.get("orders") or 0, d.get("orders_sum")
        d["orders_avg"] = round(s / o, 2) if o else None
        d["orders_spp_share"] = round(1 - d.get("orders_sum_spp", 0) / s, 4) if s else None
        d["drr_orders"] = round(d["ads"] / s, 4) if s and d.get("ads") is not None else None
        d["ad_ctr"] = round(d["ad_clicks"] / d["ad_views"], 4) if d.get("ad_views") else None
        out.append(d)
    keep = ["day", "orders", "orders_sum", "orders_sum_spp", "orders_avg", "orders_spp_share", "buyouts", "buyouts_sum", "for_pay",
            "cost", "returns", "cx_orders", "ads", "drr_orders", "ad_views", "ad_clicks", "ad_ctr", "ad_orders", "f_open", "f_cart", "f_orders"]
    titles = {k: (t, ty) for k, t, ty in agg.COLS}
    titles["day"] = ("Дата", "date")
    chart = {"x": "day", "series": [{"field": "orders", "title": "Заказы, шт", "type": "bar"},
                                    {"field": "buyouts", "title": "Выкупы, шт", "type": "bar"},
                                    {"field": "ads", "title": "Реклама, ₽", "type": "line", "axis": 1}]}
    return {"columns": [{"field": k, "title": titles[k][0], "type": titles[k][1]} for k in keep], "rows": out, "chart": chart}


def dash5(c, shop, f):
    """5#Дашборд — день/неделя/месяц/прогноз; «вчера» = конец выбранного периода (по умолчанию вчера)."""
    from datetime import date, timedelta
    from ..sheets import dash5 as d5
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    res = d5.compute(c, shop, y, f.get("nm_ids"))
    P = res["periods"]
    fmt = lambda a, b: a[8:10] + "." + a[5:7] + ("" if a == b else " – " + b[8:10] + "." + b[5:7])
    months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    mon = lambda a: f"{months[int(a[5:7]) - 1]} {a[:4]}"
    cols = [{"field": "label", "title": f"ПОКАЗАТЕЛИ (СНО: {res['tax']})", "type": "label"},
            {"field": "C", "title": f"День {fmt(*P['C'])}", "type": "rowfmt"}, {"field": "D", "title": fmt(*P["D"]), "type": "rowfmt"},
            {"field": "E", "title": "изм.", "type": "change"},
            {"field": "F", "title": f"Неделя {fmt(*P['F'])}", "type": "rowfmt"}, {"field": "G", "title": fmt(*P["G"]), "type": "rowfmt"},
            {"field": "H", "title": "изм.", "type": "change"},
            {"field": "I", "title": f"Месяц {mon(P['I'][0])} (по {P['I'][1][8:10]}.{P['I'][1][5:7]})", "type": "rowfmt"},
            {"field": "J", "title": mon(P["J"][0]), "type": "rowfmt"}, {"field": "K", "title": mon(P["K"][0]), "type": "rowfmt"},
            {"field": "L", "title": "изм.", "type": "change"},
            {"field": "M", "title": f"Прогноз {mon(P['M'][1])}", "type": "rowfmt"}, {"field": "N", "title": "изм.", "type": "change"}]
    from ..agg import buyout
    note = ("% выкупа — по заказам (выкуплено из заказов 14–42 дня назад): в отчёте реализации WB у магазина нет доставок к покупателю, "
            "эталонная формула по доставкам здесь не работает." if buyout.needed(c, shop) else None)
    return {"columns": cols, "rows": res["rows"], "layout": "sheet", "note": note}


def svod(c, shop, f):
    """СводнаяПоАртикулам — артикул/баркод × параметры (вчера, прошлая неделя, текущий и прошлый месяц, остатки)."""
    from datetime import timedelta
    from ..sheets import svod as sv
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    rows = sv.compute(c, shop, y, f.get("nm_ids"))
    cols = [{"field": "supplier_article", "title": "Артикул продавца", "type": "text"}, {"field": "barcode", "title": "Баркод", "type": "text"},
            {"field": "nm_id", "title": "Артикул WB", "type": "int"}, {"field": "tech_size", "title": "Размер", "type": "text"}]
    cols += [{"field": k, "title": t, "type": ty} for k, t, ty in sv.PARAMS]
    for col in cols:   
        per = {"orders_y": "вчера", "orders_y1": "позавчера", "orders_diff": None}.get(col["field"], "-")
        if per != "-":
            col.update(metric="Кол-во заказов" if per else "разница", period=per)
    return {"columns": cols, "rows": rows}


def stocks_by_wh(c, shop, f):
    """2#ОстаткиПоСкладам — артикул/размер × склад WB. С 2026 WB отдаёт «доступно к продаже» только одной цифрой («Склад WB РФ»,
    так же и в таблице) — её показываем отдельной колонкой; по складам — физические остатки из отчёта «Остатки по складам»
    (warehouse_remains): они могут быть больше доступных (приёмка, резерв, брак)."""
    w, p = _nm_filter(f, "s.nm_id")
    data = c.execute(
        f"""WITH last AS (SELECT max(snap_at) t FROM stocks_wh_snap WHERE account_id=%(shop)s)
            SELECT n.vendor_code, coalesce(s.tech_size,'0') tech_size, s.nm_id, n.brand, n.subject, n.imt_id, s.warehouse, sum(s.quantity) q
            FROM stocks_wh_snap s JOIN last ON s.snap_at=last.t
            LEFT JOIN nomenclature n ON n.account_id=s.account_id AND n.nm_id=s.nm_id
            WHERE s.account_id=%(shop)s AND s.warehouse NOT LIKE 'В пути%%' AND s.warehouse NOT LIKE 'Всего%%' {w}
            GROUP BY 1,2,3,4,5,6,7""", {"shop": shop, **p}).fetchall()
    tot = {}
    for r in data:
        tot[r["warehouse"]] = tot.get(r["warehouse"], 0) + float(r["q"] or 0)
    whs = [k for k, _ in sorted(tot.items(), key=lambda x: -x[1])]
    rows = {}
    for r in data:
        k = (r["vendor_code"], r["tech_size"], r["nm_id"])
        row = rows.setdefault(k, {"vendor_code": r["vendor_code"], "tech_size": r["tech_size"], "nm_id": r["nm_id"], "brand": r["brand"],
                                  "subject": r["subject"], "imt_id": r["imt_id"], "total": 0})
        row[f"wh{whs.index(r['warehouse'])}"] = float(r["q"] or 0)
        row["total"] += float(r["q"] or 0)
    avail = {r["nm_id"]: float(r["q"] or 0) for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    for r in rows.values():
        r["available"] = avail.get(r["nm_id"])
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "tech_size", "title": "Размер", "type": "text"},
            {"field": "nm_id", "title": "Артикул ВБ", "type": "int"}, {"field": "brand", "title": "Бренд", "type": "text"},
            {"field": "subject", "title": "Предмет", "type": "text"}, {"field": "imt_id", "title": "Групповой идентификатор", "type": "int"},
            {"field": "available", "title": "Доступно к продаже (как в таблице)", "type": "int"},
            {"field": "total", "title": "Физически на складах, всего", "type": "int"}]
    cols += [{"field": f"wh{i}", "title": wh, "type": "int"} for i, wh in enumerate(whs)]
    return {"columns": cols, "rows": sorted(rows.values(), key=lambda r: (r["vendor_code"] or "", r["tech_size"]))}


def ads_summary(c, shop, f):
    """1#СводнаяПоРекламе — артикул × реклама за выбранный период."""
    from ..sheets import ads
    rows = ads.compute(c, shop, f["date_from"], f["date_to"], f.get("nm_ids"))
    no_bonus = not any(r.get("bonus") for r in rows)          
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in ads.COLS
                        if not (no_bonus and k in ("bonus", "upd_all", "drr_bonus", "drr_all"))], "rows": rows}


def _pnl_periods(c, shop, f, kind):
    """PnL#РасчетОперативноПомесячно / Понедельно: по артикулам за 3 последних месяца (или 4 недели) из агрегата артикул×день.
    Прибыль = к оплате − себестоимость − логистика − реклама (статистика) − хранение (как в эталоне; без налога и эквайринга)."""
    from collections import defaultdict
    from ..agg import nm_day
    end = min(f["date_to"], today_msk())
    beg = (end.replace(day=1) - timedelta(days=62)).replace(day=1) if kind == "month" else end - timedelta(days=end.isoweekday() - 1 + 21)
    rows = nm_day.cached(c, shop, beg, end)
    key = (lambda r: r["year_month"]) if kind == "month" else (lambda r: r["year_week"])
    pers = sorted({key(r) for r in rows}, reverse=True)[: 3 if kind == "month" else 4]
    nom = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    agg = defaultdict(lambda: defaultdict(float))
    M = [("buyouts", "Кол-во выкупов", "int"), ("for_pay", "К оплате продавцу, руб", "money"), ("cost", "Сумма себестоимости, руб", "money"),
         ("logistics", "Сумма логистики, руб", "money"), ("ads", "Расходы на рекламу, руб", "money"), ("storage", "Расходы на хранение, руб", "money")]
    for r in rows:
        p = key(r)
        if p not in pers or (f.get("nm_ids") and r["nm_id"] not in f["nm_ids"]):
            continue
        a = agg[r["nm_id"]]
        for k, _, _ in M:
            a[f"{k}_{p}"] += float(r.get(k) or 0)
    out = []
    for nm, a in agg.items():
        row = {"vendor_code": nom.get(nm), "nm_id": nm, **a}
        for p in pers:
            row[f"profit_{p}"] = round(a[f"for_pay_{p}"] - a[f"cost_{p}"] - a[f"logistics_{p}"] - a[f"ads_{p}"] - a[f"storage_{p}"], 2)
        out.append(row)
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "nmId", "type": "int"}]
    for p in pers:
        lab = f"{str(p)[4:]}.{str(p)[:4]}" if kind == "month" else f"нед. {str(p)[4:]}/{str(p)[:4]}"
        cols += [{"field": f"{k}_{p}", "title": f"{lab}: {t}", "type": ty} for k, t, ty in M]
        cols.append({"field": f"profit_{p}", "title": f"{lab}: Прибыль", "type": "money"})
    return {"columns": cols, "rows": sorted(out, key=lambda r: -(r.get(f"profit_{pers[0]}") or 0) if pers else 0)}


def pnl_month(c, shop, f):
    """PnL#РасчетОперативноПомесячно — прибыль по артикулам за 3 месяца: к оплате − себестоимость − логистика − реклама − хранение."""
    return _pnl_periods(c, shop, f, "month")


def pnl_week(c, shop, f):
    """PnL#РасчетОперативноПонедельно — то же по 4 последним неделям."""
    return _pnl_periods(c, shop, f, "week")


def cost_tab(c, shop, f):
    """Себестоимость (ручные данные): текущая по каждому артикулу; правка — с датой начала действия (прошлое не переписывается)."""
    rows = c.execute(
        """SELECT n.nm_id, n.vendor_code, n.title, n.subject, cp.cost, cp.valid_from, cp.note,
                  n.data->'photos'->0->>'tm' AS photo, g.group_name
           FROM nomenclature n
           LEFT JOIN article_groups g ON g.account_id=n.account_id AND g.nm_id=n.nm_id
           LEFT JOIN LATERAL (SELECT cost, valid_from, note FROM cost_price p WHERE p.account_id=n.account_id AND p.nm_id=n.nm_id AND valid_from <= current_date
                              ORDER BY valid_from DESC LIMIT 1) cp ON true
           WHERE n.account_id=%s ORDER BY (cp.cost IS NULL) DESC, n.vendor_code""", (shop,)).fetchall()
    cols = [{"field": "photo", "title": "Фото", "type": "image"}, {"field": "nm_id", "title": "Артикул WB", "type": "int"},
            {"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "title", "title": "Наименование", "type": "text"},
            {"field": "subject", "title": "Предмет", "type": "text"},
            {"field": "cost", "title": "Себестоимость, ₽ (двойной клик — изменить)", "type": "edit_money"},
            {"field": "valid_from", "title": "Действует с", "type": "date"}, {"field": "note", "title": "Источник", "type": "text"},
            {"field": "group_name", "title": "Группа артикулов (двойной клик — изменить)", "type": "edit_text"}]
    return {"columns": cols, "rows": rows, "editable": "cost"}


def svodwb(c, shop, f):
    """Self-hosted application component."""
    from ..sheets import svodwb as sw
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    layout, hidden = None, []
    if f.get("user_id"):
        r = c.execute("SELECT value FROM user_prefs WHERE user_id=%s AND shop_id=%s AND key='svodwb_layout'", (f["user_id"], shop)).fetchone()
        if r:   
            v = r["value"]
            cols_v, hidden = (v, []) if isinstance(v, list) else (v.get("cols") or [], v.get("hidden") or [])
            layout = [tuple(x[:3]) for x in cols_v]
    res = sw.compute(c, shop, y, layout, f.get("nm_ids"))
    res["layout_editor"] = "svodwb_layout"
    res["col_hidden"] = hidden
    return res


HOME_ROWS = [  
    ("Заказы, ₽", 7, "money"), ("Заказы, шт", 8, "int"), ("Расход на рекламу, ₽", 23, "money"),
    ("ДРР от заказов, %", 24, "pct"), ("Оперативная прибыль по заказам (с % выкупа, за минусом налога), ₽", 35, "money"),
    ("Выкупы, шт", 39, "int"), ("Выкупы, ₽ (до СПП)", 38, "money"),
    ("Себестоимость продаж, ₽", 50, "money"),          
    ("Прибыль по выкупам (оперативная, за минусом налога), ₽", 63, "money"),
]


def home(c, shop, f):
    """Главная магазина: ИИ-сводка и ключевые цифры за сегодня, вчера и позавчера (WB — формулы 5#Дашборд, Ozon — расчёт Version2
    «По дням»). Сегодня — неполный день."""
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    if mp == "ozon":
        from .ozon import home as oz_home
        return oz_home(c, shop, f)
    if mp == "ym":
        from .ym import home as ym_home
        return ym_home(c, shop, f)
    from ..sheets import dash5 as d5
    t = today_msk()
    P = {"today": (t, t), "y": (t - timedelta(days=1), t - timedelta(days=1)), "y2": (t - timedelta(days=2), t - timedelta(days=2))}
    res = d5.compute(c, shop, t - timedelta(days=1), f.get("nm_ids"), custom=P)
    V = res["values"]
    rows = []
    bonus = c.execute("""SELECT 1 FROM raw_rows WHERE account_id=%s AND source='ad_upd' AND data->>'paymentType'='Кэшбэк'
                         AND row_date > current_date - 30 LIMIT 1""", (shop,)).fetchone()
    home_rows = list(HOME_ROWS)
    if bonus:     
        i = next(k for k, x in enumerate(home_rows) if x[1] == 24) + 1
        home_rows[i:i] = [("Из рекламы списано бонусами (Кэшбэк, по УПД — с задержкой WB), ₽", 231, "money")]
    for lab, n, fmt in home_rows:
        val = {k: V[k][n] for k in P}
        if n == 23:   
            for k, (a, b) in P.items():
                r = c.execute("""SELECT sum((nm->>'sum')::numeric) s FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app,
                                 jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm WHERE account_id=%s AND source='ad_stats' AND row_date=%s""",
                              (shop, a)).fetchone()
                val[k] = float(r["s"] or 0)
        if n == 231:
            val = {k: -v for k, v in val.items()}      
        if n == 24:
            for k, colname in (("today", "C"), ("y", "D"), ("y2", "F")):
                o = V[k][7]
                val[k] = rows[2][colname] / o if o else 0
        rows.append({"label": lab, "fmt": fmt, "C": val["today"], "D": val["y"], "F": val["y2"]})
    fmtd = lambda d: d.strftime("%d.%m")  
    cols = [{"field": "label", "title": f"Ключевые показатели (СНО: {res['tax']})", "type": "label"},
            {"field": "C", "title": f"Сегодня {fmtd(t)} (неполный)", "type": "rowfmt"},
            {"field": "D", "title": f"Вчера {fmtd(t - timedelta(days=1))}", "type": "rowfmt"},
            {"field": "F", "title": f"Позавчера {fmtd(t - timedelta(days=2))}", "type": "rowfmt"}]
    return {"columns": cols, "rows": rows, "layout": "sheet", "home": True}


TAX_REGIMES = ["УСН доход", "УСН доходы-расходы", "ОСНО", "ОСНО ИП (НДФЛ)", "АУСН", "Другая СНО"]


def settings(c, shop, f):
    """Настройки магазина: система налогообложения (как лист «СНО»), история изменений — с датой начала действия."""
    hist = c.execute("SELECT valid_from, regime, rate, vat_rate, vat_deduct_wb, cost_vat FROM tax_settings WHERE account_id=%s ORDER BY valid_from DESC",
                     (shop,)).fetchall()
    acc = c.execute("SELECT name, title, marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()
    cols = [{"field": "valid_from", "title": "Действует с", "type": "date"}, {"field": "regime", "title": "Система налогообложения", "type": "text"},
            {"field": "rate", "title": "Налоговая ставка", "type": "share"}, {"field": "vat_rate", "title": "Ставка НДС", "type": "share"},
            {"field": "vat_deduct_wb", "title": "НДС к вычету Wildberries", "type": "share"},
            {"field": "cost_vat", "title": "Себестоимость с НДС (к вычету)", "type": "text"}]
    cur = hist[0] if hist else {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0, "cost_vat": False}
    hist = [{**h, "cost_vat": "да" if h["cost_vat"] else "нет"} for h in hist]
    return {"columns": cols, "rows": hist, "form": "tax", "current": cur, "regimes": TAX_REGIMES, "shop": acc}


PNL_ADS = [["deduct", "по удержаниям WB (отчёт реализации) + оплата со счёта"], ["fact", "по факту открутки (списания по кампаниям)"]]


def _pnl_real(c, shop, monthly, f=None):
    from datetime import date as _date
    from ..sheets import pnl_real
    mode = "deduct"
    if f and f.get("user_id"):
        r = c.execute("SELECT value FROM user_prefs WHERE user_id=%s AND shop_id=%s AND key='pnl_ads'", (f["user_id"], shop)).fetchone()
        mode = ((r and r["value"]) or {}).get("mode") or "deduct"
    res = pnl_real.compute(c, shop, weeks=14 if monthly else 60, monthly=monthly, ads_mode=mode)   
    cols = [{"field": "label", "title": f"P&L по отчёту реализации (СНО: {res['tax']})", "type": "label"}]
    cols += [{"field": y, "title": t, "type": "rowfmt"} for y, t in res.get("years", [])]
    for p in res["periods"]:
        if monthly:
            t = f"{p[5:7]}.{p[:4]}"
        else:
            d = _date.fromisoformat(p)
            t = f"{d:%d.%m}–{(d + timedelta(days=6)):%d.%m}"
        cols.append({"field": p, "title": t, "type": "rowfmt"})
    return {"columns": cols, "rows": res["rows"], "layout": "sheet",
            "switch": {"key": "pnl_ads", "title": "Реклама", "value": mode, "options": PNL_ADS}}


def pnl_real_week(c, shop, f):
    """5#PnL#РеализацияПонедельно — финансовый результат по еженедельным отчётам реализации WB (до 60 недель) и расшифровка удержаний по статьям."""
    return _pnl_real(c, shop, False, f)


def pnl_real_month(c, shop, f):
    """5#PnL#РеализацияПомесячно — то же по месяцам."""
    return _pnl_real(c, shop, True, f)


def real_week_tab(c, shop, f):
    """БД#РеализацияПонедельно — отчёт реализации, сгруппированный по неделям (за выбранный период)."""
    from ..agg import real_week
    rows = real_week.cached(c, shop, f["date_from"], f["date_to"])
    if f.get("nm_ids"):
        rows = [r for r in rows if r["nm_id"] in f["nm_ids"]]
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in real_week.COLS], "rows": rows}


def _abc(items):
    """ABC как в эталоне: по убыванию показателя, накопленная доля ≤ 0,8 — A, ≤ 0,95 — B, иначе C (доля — от итога месяца)."""
    tot = sum(v for _, v in items)
    out, cum = {}, 0.0
    for nm, v in sorted(items, key=lambda x: -x[1]):
        cum += v
        share = cum / tot if tot else 1
        out[nm] = "A" if share <= 0.8 else "B" if share <= 0.95 else "C"
    return out


def abc(c, shop, f):
    """Сводная#ABC#ОперативныеДанные: ABC-группы артикулов по прибыли, марже и «к оплате» за 4 последних месяца."""
    from collections import defaultdict
    from ..agg import nm_day
    end = min(f["date_to"], today_msk())
    beg = (end.replace(day=1) - timedelta(days=95)).replace(day=1)
    rows = nm_day.cached(c, shop, beg, end)
    months = sorted({r["year_month"] for r in rows}, reverse=True)[:4]
    S = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in rows:
        if r["year_month"] in months:
            for k in ("profit", "margin", "for_pay", "buyouts"):
                S[r["year_month"]][k][r["nm_id"]] += float(r.get(k) or 0)
    nom = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    res = defaultdict(dict)
    for m in months:
        for k in ("profit", "margin", "for_pay"):
            g = _abc(list(S[m][k].items()))
            for nm, letter in g.items():
                res[nm][f"{k}_{m}"] = letter
                res[nm][f"v{k}_{m}"] = round(S[m][k][nm], 2)
    out = [{"vendor_code": nom.get(nm), "nm_id": nm, **v} for nm, v in res.items() if nm]
    out.sort(key=lambda r: "".join(r.get(f"profit_{m}", "C") for m in months))
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул ВБ", "type": "int"}]
    for m in months:
        lab = f"{str(m)[4:]}.{str(m)[:4]}"
        cols += [{"field": f"profit_{m}", "title": f"{lab}: ABC по прибыли", "type": "text", "group": lab},
                 {"field": f"margin_{m}", "title": "ABC по марже", "type": "text", "group": ""},
                 {"field": f"for_pay_{m}", "title": "ABC по «к оплате»", "type": "text", "group": ""},
                 {"field": f"vprofit_{m}", "title": "Прибыль, руб", "type": "money", "group": ""},
                 {"field": f"vmargin_{m}", "title": "Маржа, руб", "type": "money", "group": ""},
                 {"field": f"vfor_pay_{m}", "title": "К оплате, руб", "type": "money", "group": ""}]
    return {"columns": cols, "rows": out}


def dash_nm(c, shop, f):
    """6#ДашбордПоАртикулу — тот же 5#Дашборд по выбранным артикулам (поле «Артикулы WB» вверху)."""
    if not f.get("nm_ids"):
        return {"columns": [{"field": "msg", "title": "Выберите артикул", "type": "text"}],
                "rows": [{"msg": "Введите артикул(ы) WB в поле «Артикулы WB через запятую» вверху страницы"}]}
    return dash5(c, shop, f)


def dash_nm_days(c, shop, f):
    """Self-hosted application component."""
    from ..sheets import dash5 as d5
    if not f.get("nm_ids"):
        return {"columns": [{"field": "msg", "title": "Выберите артикул", "type": "text"}],
                "rows": [{"msg": "Введите артикул(ы) WB в поле «Артикулы WB через запятую» вверху страницы"}]}
    y = min(f["date_to"], today_msk() - timedelta(days=1))
    days = [y - timedelta(days=i) for i in range(30)]
    P = {f"d{i}": (d, d) for i, d in enumerate(days)}
    res = d5.compute(c, shop, y, f.get("nm_ids"), custom=P)
    V = res["values"]
    wd = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    cols = [{"field": "label", "title": f"ПОКАЗАТЕЛИ (СНО: {res['tax']})", "type": "label"}]
    cols += [{"field": k, "title": f"{d:%d.%m} {wd[d.weekday()]}", "type": "rowfmt"} for k, (d, _) in P.items()]
    rows = []
    for n, lab, fmt, fn in d5.ROWS:
        row = {"row": n, "label": lab, "fmt": fmt}
        if fn is not None:
            for k in P:
                row[k] = round(V[k][n], 4 if fmt == "pct" else 2)
        rows.append(row)
    return {"columns": cols, "rows": rows, "layout": "sheet"}


def no_cost(c, shop, f):
    """PnL#ТоварыБезСебестоимости — артикулы с продажами/остатками, у которых не задана себестоимость (их прибыль завышена)."""
    rows = c.execute(
        """SELECT n.nm_id, n.vendor_code, n.title, n.subject,
                  (SELECT count(*) FROM sales s WHERE s.account_id=n.account_id AND s.nm_id=n.nm_id AND s.sale_id LIKE 'S%%'
                     AND s.sale_dt > now() - interval '90 days') buyouts_90d
           FROM nomenclature n WHERE n.account_id=%s
             AND NOT EXISTS (SELECT 1 FROM cost_price p WHERE p.account_id=n.account_id AND p.nm_id=n.nm_id)
           ORDER BY 5 DESC, 2""", (shop,)).fetchall()
    cols = [{"field": "nm_id", "title": "Артикул WB", "type": "int"}, {"field": "vendor_code", "title": "Артикул продавца", "type": "text"},
            {"field": "title", "title": "Наименование", "type": "text"}, {"field": "subject", "title": "Предмет", "type": "text"},
            {"field": "buyouts_90d", "title": "Выкупов за 90 дней", "type": "int"}]
    return {"columns": cols, "rows": rows}


def logistics_week(c, shop, f):
    """ЛогистикаПонедельно — средняя логистика на доставку к клиенту по артикулам и неделям отчёта (как БД#ЛогистикаПонедельно)."""
    rows = c.execute(
        """SELECT (data->>'nmId')::bigint nm_id, max(data->>'vendorCode') vendor_code,
                  to_char(date_trunc('week', (data->>'rrDate')::date), 'IYYYIW')::int year_week,
                  sum((data->>'deliveryService')::numeric) lg, sum((data->>'deliveryAmount')::numeric) n
           FROM raw_rows WHERE account_id=%s AND source='realization' AND row_date BETWEEN %s AND %s
             AND data->>'bonusTypeName' ILIKE 'К клиенту%%'
             AND (data->>'rrDate')::date BETWEEN %s AND %s GROUP BY 1,3 ORDER BY 3 DESC, 2""",
        (shop, f["date_from"] - timedelta(days=75), f["date_to"] + timedelta(days=21), f["date_from"] - timedelta(days=60), f["date_to"])).fetchall()
    out = [{**r, "avg": round(float(r["lg"]) / float(r["n"]), 3) if r["n"] else None} for r in rows if not f.get("nm_ids") or r["nm_id"] in f["nm_ids"]]
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул WB", "type": "int"},
            {"field": "year_week", "title": "Год/Неделя", "type": "int"}, {"field": "n", "title": "Доставок к клиенту", "type": "int"},
            {"field": "lg", "title": "Логистика к клиенту, руб", "type": "money"}, {"field": "avg", "title": "Средняя логистика на доставку, руб", "type": "money"}]
    return {"columns": cols, "rows": out}


def orders_hours(c, shop, f):
    """ДашбордЗаказыПоЧасамПоАртикулу — заказы по часам суток (МСК) × дни недели за период; график — по часам."""
    w, p = _nm_filter(f, "nm_id")
    rows = c.execute(
        f"""SELECT extract(hour FROM order_dt)::int h,
                   count(*) FILTER (WHERE extract(isodow FROM order_dt)=1) d1, count(*) FILTER (WHERE extract(isodow FROM order_dt)=2) d2,
                   count(*) FILTER (WHERE extract(isodow FROM order_dt)=3) d3, count(*) FILTER (WHERE extract(isodow FROM order_dt)=4) d4,
                   count(*) FILTER (WHERE extract(isodow FROM order_dt)=5) d5, count(*) FILTER (WHERE extract(isodow FROM order_dt)=6) d6,
                   count(*) FILTER (WHERE extract(isodow FROM order_dt)=7) d7, count(*) total
            FROM orders WHERE account_id=%(shop)s AND order_dt::date BETWEEN %(df)s AND %(dt)s {w} GROUP BY 1 ORDER BY 1""",
        {"shop": shop, "df": f["date_from"], "dt": f["date_to"], **p}).fetchall()
    cols = [{"field": "h", "title": "Час (МСК)", "type": "text"}] + [
        {"field": f"d{i}", "title": t, "type": "int"} for i, t in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"], start=1)] + [
        {"field": "total", "title": "Всего заказов", "type": "int"}]
    return {"columns": cols, "rows": [{**r, "h": f"{r['h']:02d}:00"} for r in rows],
            "chart": {"x": "h", "series": [{"field": "total", "title": "Заказы", "type": "bar"}]},
            
            "heat": [[f"d{i}" for i in range(1, 8)], ["total"]]}


def spp_subject(c, shop, f):
    """Дашборд#СППпоПредмету — средняя СПП (скидка WB) по предметам и дням из заказов: 1 − Σ цена покупателя / Σ цена продавца."""
    rows = c.execute(
        """SELECT o.order_dt::date AS day, coalesce(n.subject, o.data->>'subject') subject, count(*) orders,
                  round(1 - sum(o.finished_price) / NULLIF(sum(o.price_with_disc), 0), 4) spp
           FROM orders o LEFT JOIN nomenclature n ON n.account_id=o.account_id AND n.nm_id=o.nm_id
           WHERE o.account_id=%s AND o.order_dt::date BETWEEN %s AND %s GROUP BY 1,2 ORDER BY 1 DESC, 3 DESC""",
        (shop, f["date_from"], f["date_to"])).fetchall()
    cols = [{"field": "day", "title": "Дата", "type": "date"}, {"field": "subject", "title": "Предмет", "type": "text"},
            {"field": "orders", "title": "Заказов", "type": "int"}, {"field": "spp", "title": "СПП, %", "type": "share"}]
    return {"columns": cols, "rows": rows}


def stock_plan(c, shop, f):
    """3#ОстаткиРегионСклады (режим «все склады»): на сколько дней хватит и сколько поставить на N дней.
    Как в эталоне: дней = (остаток + в пути к клиенту × (1 − % выкупа) + в пути от клиента) / заказов в день;
    поставить = N × заказов в день − (тот же запас). Заказы в день при наличии — пока из аналитики остатков WB
    (avgOrders за 28 дней); своя история наличия по складам копится с 18.10.2026 — потом перейдём на формулу эталона."""
    from ..sheets.svodwb import compute as sw
    N = 28
    sv = {r["nm_id"]: r for r in sw(c, shop, layout=[("", "Кол-во заказов ВСЕГО", "за послед. 4 недели")])["rows"]}
    wb = {int(r["nm"]): r["d"] for r in c.execute(
        """SELECT DISTINCT ON (data->>'nmID') data->>'nmID' nm, data->'metrics' d FROM raw_rows
           WHERE account_id=%s AND source='stocks_report:28' ORDER BY data->>'nmID', row_date DESC""", (shop,))}
    out = []
    for nm, r in sv.items():
        m = wb.get(nm) or {}
        avg = float(m.get("avgOrders") or 0)
        bp = float(r.get("buyout_4w") or 0)
        stock = float(r.get("stock") or 0); wt = float(r.get("in_way_to") or 0); wf = float(r.get("in_way_from") or 0)
        have = stock + wt * (1 - bp) + wf
        if not (stock or wt or wf or avg or r.get("m0")):
            continue
        miss = m.get("officeMissingTime") or {}
        out.append({"vendor_code": r["vendor_code"], "title": r["title"], "nm_id": nm, "buyout_4w": bp, "stock": stock, "in_way_to": wt,
                    "in_way_from": wf, "orders_28": r.get("m0"), "days_missing": round((miss.get("days", 0) + miss.get("hours", 0) / 24), 1) if miss else None,
                    "avg_orders": avg, "days_left": round(have / avg, 1) if avg else None,
                    "to_supply": max(0, round(N * avg - have)) if avg else None})
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "title", "title": "Наименование", "type": "text"},
            {"field": "nm_id", "title": "Артикул ВБ", "type": "int"}, {"field": "buyout_4w", "title": "% выкупа за 4 недели", "type": "share"},
            {"field": "stock", "title": "Остатки на складах WB", "type": "int"}, {"field": "in_way_to", "title": "В пути к клиенту", "type": "int"},
            {"field": "in_way_from", "title": "В пути от клиента", "type": "int"}, {"field": "orders_28", "title": "Заказов за 28 дней", "type": "int"},
            {"field": "days_missing", "title": "Дней без остатка (WB, 28 дн.)", "type": "num"},
            {"field": "avg_orders", "title": "Заказов в день при наличии (WB)", "type": "num"},
            {"field": "days_left", "title": "Хватит на … дней", "type": "num"},
            {"field": "to_supply", "title": f"Поставить на {N} дней, шт", "type": "int"}]
    return {"columns": cols, "rows": sorted(out, key=lambda r: (r["days_left"] is None, r["days_left"] or 0))}


def by_days(c, shop, f):
    """4#ДашбордПоДням — показатели по дням за выбранный период (итог месяца — отдельной колонкой)."""
    from ..sheets import by_days as bd
    return bd.compute(c, shop, f["date_from"], f["date_to"], f.get("nm_ids"))


def ads_conv_week(c, shop, f):
    """РекламаКонверсииПонедельно — по артикулам и 4 последним неделям: CTR рекламы, конверсии в корзину и в заказ,
    расходы на рекламу, прибыль (суммы недели; доли — из сумм)."""
    from collections import defaultdict
    from ..agg import nm_day
    end = min(f["date_to"], today_msk())
    beg = end - timedelta(days=end.isoweekday() - 1 + 21)
    rows = nm_day.cached(c, shop, beg, end)
    weeks = sorted({r["year_week"] for r in rows}, reverse=True)[:4]
    A = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r["year_week"] in weeks and (not f.get("nm_ids") or r["nm_id"] in f["nm_ids"]):
            a = A[(r["nm_id"], r["year_week"])]
            for k in ("ad_clicks", "ad_views", "f_cart", "f_open", "f_orders", "ads", "profit"):
                a[k] += float(r.get(k) or 0)
    nom = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    out = {}
    for (nm, w), a in A.items():
        row = out.setdefault(nm, {"vendor_code": nom.get(nm), "nm_id": nm})
        row[f"ctr_{w}"] = a["ad_clicks"] / a["ad_views"] if a["ad_views"] else None
        row[f"cart_{w}"] = a["f_cart"] / a["f_open"] if a["f_open"] else None
        row[f"order_{w}"] = a["f_orders"] / a["f_cart"] if a["f_cart"] else None
        row[f"ads_{w}"] = a["ads"]; row[f"profit_{w}"] = a["profit"]
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул ВБ", "type": "int"}]
    for i, w in enumerate(weeks):
        lab = ["ТЕКУЩАЯ НЕДЕЛЯ", "ПРЕДЫДУЩАЯ НЕДЕЛЯ", "2 НЕДЕЛИ НАЗАД", "3 НЕДЕЛИ НАЗАД"][i] + f" ({str(w)[4:]})"
        cols += [{"field": f"ctr_{w}", "title": "Реклама (CTR), %", "type": "share", "group": lab},
                 {"field": f"cart_{w}", "title": "Конверсия в корзину, %", "type": "share", "group": ""},
                 {"field": f"order_{w}", "title": "Конверсия в заказ, %", "type": "share", "group": ""},
                 {"field": f"ads_{w}", "title": "Расходы на рекламу, руб", "type": "money", "group": ""},
                 {"field": f"profit_{w}", "title": "Прибыль, руб", "type": "money", "group": ""}]
    return {"columns": cols, "rows": sorted(out.values(), key=lambda r: -(r.get(f"ads_{weeks[0]}") or 0) if weeks else 0)}


def card_groups(c, shop) -> list[dict]:
    """Self-hosted application component."""
    return c.execute(
        """SELECT 'card:' || n.imt_id AS key, count(*) n, max(n.title) title, min(n.vendor_code) vc, coalesce(sum(o.n), 0) orders_30d
           FROM nomenclature n LEFT JOIN (SELECT nm_id, count(*) n FROM orders WHERE account_id=%(a)s AND order_dt >= now() - interval '30 days'
                                          GROUP BY 1) o ON o.nm_id=n.nm_id
           WHERE n.account_id=%(a)s AND n.imt_id IS NOT NULL GROUP BY n.imt_id HAVING count(*) > 1
           ORDER BY coalesce(sum(o.n), 0) DESC""", {"a": shop}).fetchall()


def group_nms(c, shop, grp: str) -> list[int]:
    if grp.startswith("card:") and grp[5:].isdigit():
        return [r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id=%s AND imt_id=%s", (shop, int(grp[5:])))]
    return [r["nm_id"] for r in c.execute("SELECT nm_id FROM article_groups WHERE account_id=%s AND group_name=%s", (shop, grp))]


def dash_group(c, shop, f):
    """2#ДашбордПоГруппеАртикулов — 5#Дашборд по группе артикулов. Группы по умолчанию — объединённые карточки WB (артикулы
    одной карточки); свои группы задаются на вкладке «Себестоимость»."""
    grp = f.get("group")
    if not grp:
        return {"columns": [{"field": "msg", "title": "Группа", "type": "text"}], "rows": [{"msg": "Выберите группу вверху"}]}
    return dash5(c, shop, {**f, "nm_ids": group_nms(c, shop, grp) or [-1]})


def fbs_turnover(c, shop, f):
    """1#FBS#ОборачиваемостьПоОкругам — остатки на складах продавца по регионам отгрузки, FBS-заказы за период по округам
    доставки и оборачиваемость (дней) = остаток / (заказов / дней периода)."""
    from collections import defaultdict
    days = (f["date_to"] - f["date_from"]).days + 1
    st = defaultdict(float)
    for r in c.execute("""WITH last AS (SELECT max(snap_at) t FROM stocks_seller_snap WHERE account_id=%s)
                          SELECT nm_id, coalesce(data->>'regionName', warehouse) reg, sum(quantity) q FROM stocks_seller_snap s
                          JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1,2""", (shop, shop)):
        st[(r["nm_id"], r["reg"])] += float(r["q"] or 0)
    od = defaultdict(float)
    for r in c.execute("""SELECT nm_id, okrug, count(*) n FROM orders WHERE account_id=%s AND warehouse_type ILIKE '%%продавца%%'
                          AND order_dt::date BETWEEN %s AND %s GROUP BY 1,2""", (shop, f["date_from"], f["date_to"])):
        od[(r["nm_id"], r["okrug"])] += r["n"]
    regs = sorted({k[1] for k in st} | {k[1] for k in od} - {None})
    nms = sorted({k[0] for k in st} | {k[0] for k in od})
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, title FROM nomenclature WHERE account_id=%s", (shop,))}
    out = []
    for nm in nms:
        row = {"vendor_code": (nom.get(nm) or {}).get("vendor_code"), "nm_id": nm, "title": (nom.get(nm) or {}).get("title")}
        for i, rg in enumerate(regs):
            s, o = st.get((nm, rg), 0), od.get((nm, rg), 0)
            row[f"s{i}"], row[f"o{i}"] = s, o
            row[f"t{i}"] = round(s / (o / days), 1) if o else None
        out.append(row)
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул ВБ", "type": "int"},
            {"field": "title", "title": "Наименование", "type": "text"}]
    for i, rg in enumerate(regs):
        cols += [{"field": f"s{i}", "title": "Остатки FBS", "type": "int", "group": rg},
                 {"field": f"o{i}", "title": f"Заказов за {days} дн.", "type": "int", "group": ""},
                 {"field": f"t{i}", "title": "Оборачиваемость, дн", "type": "num", "group": ""}]
    if not out:
        return {"columns": [{"field": "msg", "title": "FBS", "type": "text"}],
                "rows": [{"msg": "Нет остатков на складах продавца и FBS-заказов за период"}]}
    return {"columns": cols, "rows": out}


def prices_now(c, shop, f):
    """Сайт#ТекущиеЦеныОстатки (замена): витрина WB с сервера закрыта (403), поэтому — из API продавца: цена и скидка продавца
    (последний снимок цен), цена покупателя с СПП — по последнему заказу, рейтинг по отзывам — из аналитики WB, остаток к продаже."""
    rows = c.execute(
        """WITH lp AS (SELECT DISTINCT ON (nm_id) nm_id, price, discount, discounted_price, snap_at FROM prices_snap
                       WHERE account_id=%(a)s ORDER BY nm_id, snap_at DESC, size_id),
                lo AS (SELECT DISTINCT ON (nm_id) nm_id, finished_price, spp, order_dt FROM orders WHERE account_id=%(a)s
                       ORDER BY nm_id, order_dt DESC),
                st AS (SELECT nm_id, sum(quantity) q FROM stocks_wb_snap WHERE account_id=%(a)s
                       AND snap_at=(SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=%(a)s) GROUP BY 1),
                rt AS (SELECT DISTINCT ON ((data->>'nmId')::bigint) (data->>'nmId')::bigint nm_id, (data->>'feedbackRating')::numeric r
                       FROM raw_rows WHERE account_id=%(a)s AND source='funnel_day' ORDER BY (data->>'nmId')::bigint, row_date DESC)
           SELECT n.nm_id, n.vendor_code, n.title, n.brand, n.subject, n.imt_id, lp.price, lp.discount, lp.discounted_price,
                  lo.finished_price, lo.spp, lo.order_dt, st.q stock, rt.r rating, n.data->'photos'->0->>'tm' AS photo
           FROM nomenclature n LEFT JOIN lp USING (nm_id) LEFT JOIN lo USING (nm_id) LEFT JOIN st USING (nm_id) LEFT JOIN rt USING (nm_id)
           WHERE n.account_id=%(a)s ORDER BY (st.q IS NULL OR st.q=0), n.vendor_code""", {"a": shop}).fetchall()
    cols = [{"field": "photo", "title": "Фото", "type": "image"}, {"field": "nm_id", "title": "Артикул ВБ", "type": "int"},
            {"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "title", "title": "Название", "type": "text"},
            {"field": "brand", "title": "Бренд", "type": "text"}, {"field": "subject", "title": "Предмет", "type": "text"},
            {"field": "price", "title": "Цена до скидки, руб", "type": "money"}, {"field": "discount", "title": "Скидка продавца, %", "type": "num"},
            {"field": "discounted_price", "title": "Цена со скидкой продавца, руб", "type": "money"},
            {"field": "finished_price", "title": "Цена покупателя (последний заказ), руб", "type": "money"},
            {"field": "spp", "title": "СПП (последний заказ), %", "type": "num"}, {"field": "order_dt", "title": "Последний заказ", "type": "datetime"},
            {"field": "stock", "title": "Остаток к продаже", "type": "int"}, {"field": "rating", "title": "Рейтинг по отзывам", "type": "num"}]
    return {"columns": cols, "rows": rows}


def fin_sku(c, shop, f):
    """Финотчёт по SKU: P&L по отчёту реализации WB за период по каждому артикулу — выкупы, возвраты, логистика, хранение,
    приёмка, штрафы, доплаты, удержания, эквайринг, комиссия, себестоимость, раздачи, внешняя и внутренняя реклама, к оплате, налог,
    доход до постоянных расходов, ROS и ROI. Период — даты вверху (берутся недели отчёта реализации, попавшие в период)."""
    from ..sheets import fin_sku as fs
    res = fs.compute(c, shop, f["date_from"], f["date_to"])
    rows = res["rows"]
    if f.get("nm_ids"):
        rows = [r for r in rows if r["nm_id"] in f["nm_ids"]]
    nb = not any(r.get("ads_bonus") for r in rows)
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in fs.COLS if not (nb and k == "ads_bonus")], "rows": rows,
            "rules": {"profit": [{"gt": None, "le": 0, "color": "#fecaca"}], "ros": [{"gt": None, "le": 0, "color": "#fecaca"}]},
            "note": "Суммы — по неделям отчёта реализации WB, попавшим в период; внутренняя реклама — по статистике кампаний."}


def pnl_nm(c, shop, f):
    """PnL#ПоАртикулам: P&L по отчёту реализации WB за период — строка на артикул, столбцы как у 5#PnL#РеализацияПонедельно.
    Реклама и удержания без артикула разложены по артикулам (реклама — по расходу кампаний, остальное — по продажам)."""
    from ..sheets import pnl_nm as pn
    res = pn.compute(c, shop, f["date_from"], f["date_to"], f.get("nm_ids"))
    for r in res["rows"] + ([res["total"]] if res["total"] else []):
        r["r37"] = -(r.get("r37") or 0)          
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул WB", "type": "int"},
            {"field": "subject", "title": "Предмет", "type": "text"}] + [{"field": f"r{n}", "title": t, "type": ty} for n, t, ty in pn.COLS]
    w = res["weeks"]
    period = f"недели отчёта реализации {w[0][8:10]}.{w[0][5:7]}–{w[1][8:10]}.{w[1][5:7]}.{w[1][:4]}" if w else "в выбранные даты отчётов реализации нет"
    return {"columns": cols, "rows": res["rows"], "total_row": res["total"],
            "rules": {"r57": [{"gt": None, "le": 0, "color": "#fecaca"}], "r51": [{"gt": None, "le": 0, "color": "#fecaca"}]},
            "note": f"По отчёту реализации WB, {period}. Реклама (в отчёте WB — на магазин целиком) разложена по артикулам по списаниям "
                    "с баланса по кампаниям; хранение, приёмка, баллы и прочие удержания без артикула — пропорционально продажам. "
                    "Налог — по настройке СНО на каждую неделю."}


def opiu_wb(c, shop, f):
    """ОПиУ: прибыли и убытки по месяцам года (год — по дате «по» вверху) и итог за год; рядом с суммой — доля от выручки до СПП.
    По отчёту реализации WB + внешние расходы и раздачи."""
    from ..sheets import opiu_wb as ow
    MON = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
    year = f["date_to"].year
    res = ow.compute(c, shop, year)
    cols = [{"field": "label", "title": f"ОПиУ {year} (СНО: {res['tax']})", "type": "label"}]
    for m in res["months"] + ["year"]:
        t = f"Год {year}" if m == "year" else f"{MON[int(m[5:7]) - 1]} {m[:4]}"
        cols += [{"field": m, "title": t, "type": "rowfmt"}, {"field": m + "_p", "title": "%", "type": "share"}]
    return {"columns": cols, "rows": res["rows"], "plain": True}


def unit_wb(c, shop, f):
    """UNIT-экономика WB: прибыль, маржа и ROI на 1 проданную штуку — закупка, комиссия, логистика, хранение, приёмка, эквайринг
    (по отчёту реализации за 4 недели), налог и НДС по СНО, цена до и после СПП. Маркировку и прочие расходы на 1 шт впишите двойным кликом."""
    from .. import unit_wb as uw
    rows = uw.compute(c, shop)
    if f.get("nm_ids"):
        rows = [r for r in rows if r["nm_id"] in f["nm_ids"]]
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in uw.COLS], "rows": rows, "editable": "unit_extra",
            "rules": {"margin": [{"gt": None, "le": 0.2, "color": "#fecaca"}], "roi": [{"gt": None, "le": 0.2, "color": "#fecaca"}]}}


ALT_NOTE = ("Альтернативный расчёт (по когортам заказов): прибыль заказов, сделанных в выбранные даты, — их продажи, возвраты и логистика "
            "по всем отчётам WB до сегодня; незавершённые заказы не считаются. Себестоимость — на дату заказа. Реклама — по факту открутки "
            "(УПД: баланс и счёт) + WB Медиа, в датах периода. Хранение, штрафы, баллы, Джем — по дате отчёта; без артикула — по заказам месяца. "
            "Зарплаты и расходы вне WB не входят. НДС — прогноз: с оплаченного покупателем, вычет НДС вознаграждения WB со знаком, услуг WB, рекламы "
            "и закупки (если «себестоимость с НДС»).")


ALT_PENDING = {"columns": [{"field": "label", "title": "Альтернативный PnL", "type": "text"}], "rows": [], "plain": True, "retry": 10,
               "note": "Считаю альтернативный PnL за большой период по всем строкам отчётов WB — это может занять несколько минут. "
                       "Вкладка обновится сама."}


def _alt_range():
    """Self-hosted application component."""
    from ..sheets import pnl_alt
    return pnl_alt.SINCE, today_msk() - timedelta(days=1)


def pnl_alt_month(c, shop, f):
    """Альтернативный PnL по месяцам: прибыль заказов периода (по дате заказа), реклама по факту открутки, себестоимость на дату заказа."""
    from ..sheets import pnl_alt
    try:
        res = pnl_alt.cached(c, shop, *_alt_range())
    except pnl_alt.Pending:
        return ALT_PENDING
    months = sorted((m for m in res["month"] if any(abs(v) > 0.5 for v in res["month"][m].values())), reverse=True)   
    cols = [{"field": "label", "title": f"Альтернативный PnL (СНО: {res['tax'].get('regime', '—')})", "type": "label"},
            {"field": "total", "title": "Итого", "type": "rowfmt"}]
    cols += [{"field": m, "title": f"{m[5:7]}.{m[:4]}", "type": "rowfmt"} for m in months]
    rows = []
    for k, t, ty in pnl_alt.COLS:
        fmt = "pct" if ty == "share" else ty
        rows.append({"label": t, "fmt": fmt, "total": res["total"].get(k, 0), **{m: res["month"][m].get(k, 0) for m in months}})
    nc = sum(res["nocost"].values())
    note = ALT_NOTE + (f" ⚠️ Без себестоимости {nc:.0f} шт. проданного — закупка по ним не вычтена." if nc else "")
    d0, d1 = _alt_range()
    note += f" Даты вверху не влияют: всегда {d0:%m.%Y}–{d1:%m.%Y}, свежие месяцы слева; «Итого» — за весь этот срок."
    return {"columns": cols, "rows": rows, "layout": "sheet", "note": note}


def pnl_alt_nm(c, shop, f):
    """Альтернативный PnL по артикулам: то же, строка на артикул."""
    from ..sheets import pnl_alt
    try:
        res = pnl_alt.cached(c, shop, f["date_from"], f["date_to"])
    except pnl_alt.Pending:
        return ALT_PENDING
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, subject FROM nomenclature WHERE account_id=%s", (shop,))}
    keys = [k for k, _, _ in pnl_alt.COLS]
    rows = []
    for nm, a in res["nm"].items():
        if f.get("nm_ids") and nm not in f["nm_ids"]:
            continue
        if not any(abs(a.get(k, 0)) > 0.5 for k in keys):
            continue
        n = nom.get(nm) or {}
        rows.append({"vendor_code": n.get("vendor_code"), "nm_id": nm, "subject": n.get("subject"), **{k: a.get(k, 0) for k in keys}})
    rows.sort(key=lambda r: -(r["profit"] or 0))     
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул WB", "type": "int"},
            {"field": "subject", "title": "Предмет", "type": "text"}] + [{"field": k, "title": t, "type": ty} for k, t, ty in pnl_alt.COLS]
    total = {"vendor_code": "ИТОГО", **{k: res["total"].get(k, 0) for k in keys}} if rows and not f.get("nm_ids") else None
    return {"columns": cols, "rows": rows, "total_row": total, "note": ALT_NOTE + " ROI = прибыль / закупка проданного.", "rules": ALT_RULES}


ALT_RULES = {"profit": [{"gt": None, "le": 0, "color": "#fecaca"}], "profit_tax": [{"gt": None, "le": 0, "color": "#fecaca"}],
             "roi": [{"gt": None, "le": 0, "color": "#fecaca"}], "roi_tax": [{"gt": None, "le": 0, "color": "#fecaca"}]}


def pnl_alt_nm_month(c, shop, f):
    from collections import defaultdict
    """Альтернативный PnL по артикулам по месяцам: строка — артикул × месяц заказа, с прибылью и ROI."""
    from ..sheets import pnl_alt
    try:
        res = pnl_alt.cached(c, shop, f["date_from"], f["date_to"])   
    except pnl_alt.Pending:
        return ALT_PENDING
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, subject FROM nomenclature WHERE account_id=%s", (shop,))}
    keys = [k for k, _, _ in pnl_alt.COLS]
    rows = []
    for (nm, m), a in res["nm_month"].items():
        if f.get("nm_ids") and nm not in f["nm_ids"]:
            continue
        if not any(abs(a.get(k, 0)) > 0.5 for k in keys):
            continue
        n = nom.get(nm) or {}
        rows.append({"vendor_code": n.get("vendor_code"), "nm_id": nm, "subject": n.get("subject"), "month": f"{m[5:7]}.{m[:4]}", "_m": m,
                     **{k: a.get(k, 0) for k in keys}})
    tot_p = defaultdict(float)        
    for r in rows:
        tot_p[r["nm_id"]] += r["profit"] or 0
    rows.sort(key=lambda r: (-tot_p[r["nm_id"]], r["nm_id"], -int(r["_m"].replace("-", "")[:6])))
    for r in rows:
        del r["_m"]
    cols = [{"field": "vendor_code", "title": "Артикул продавца", "type": "text"}, {"field": "nm_id", "title": "Артикул WB", "type": "int"},
            {"field": "subject", "title": "Предмет", "type": "text"}, {"field": "month", "title": "Месяц", "type": "text"}] +\
           [{"field": k, "title": t, "type": ty} for k, t, ty in pnl_alt.COLS]
    total = {"vendor_code": "ИТОГО", **{k: res["total"].get(k, 0) for k in keys}} if rows and not f.get("nm_ids") else None
    return {"columns": cols, "rows": rows, "total_row": total, "rules": ALT_RULES,
            "note": ALT_NOTE + " Месяц — месяц заказа (реклама и общие расходы — месяц списания). ROI = прибыль / закупка проданного."}

"""Self-hosted application component."""

from datetime import date, timedelta

from .config import today_msk




GREEN, RED, PINK, BLUE, YELLOW, TEAL = "#16a34a", "#dc2626", "#db2777", "#2563eb", "#ca8a04", "#0d9488"
KINDS = [
    {"key": "price_down", "title": "Цена ↓", "color": RED, "unit": "₽"},
    {"key": "price_up", "title": "Цена ↑", "color": GREEN, "unit": "₽"},
    {"key": "promo_in", "title": "Акция: вход", "color": PINK},
    {"key": "promo_out", "title": "Акция: выход", "color": "#9d174d"},
    {"key": "ads_on", "title": "Реклама", "color": YELLOW},
    {"key": "ads_bid", "title": "Ставка", "color": YELLOW, "unit": "₽"},
    {"key": "ads_off", "title": "Реклама стоп", "color": "#a16207"},
    {"key": "superboost", "title": "Супербуст", "color": YELLOW},
    {"key": "buyout", "title": "Выкуп", "color": "#ea580c", "unit": "шт"},
    {"key": "reviews", "title": "Отзывы", "color": "#7c3aed"},
    {"key": "blogger", "title": "Блогер", "color": "#c026d3"},
    {"key": "seo", "title": "СЕО", "color": TEAL},
    {"key": "top1", "title": "ТОП / 1-я стр.", "color": "#92400e"},
    {"key": "cover", "title": "Обложка / слайды", "color": BLUE},
    {"key": "infographic", "title": "Инфографика", "color": BLUE},
    {"key": "video", "title": "Видео", "color": BLUE},
    {"key": "rich", "title": "Рич-контент", "color": BLUE},
    {"key": "category", "title": "Категория", "color": "#f97316"},
    {"key": "supply", "title": "Поставка", "color": "#475569", "unit": "шт"},
    {"key": "other", "title": "Другое", "color": "#6b7280"},
]
KIND_KEYS = {k["key"] for k in KINDS}

CHANGE_TITLE = {"title": "Название", "description": "Описание", "photos": "Фото", "video": "Видео", "brand": "Бренд",
                "vendorCode": "Артикул продавца", "subjectName": "Предмет", "subjectID": "Предмет", "dimensions": "Габариты",
                "sizes": "Размеры", "created": "Карточка создана", "imtID": "Склейка карточек"}


def change_color(r: dict) -> str | None:
    """Цвет автоматического изменения по смыслу: цена вверх / вниз, вход / выход из акции, характеристики."""
    f, k = r["field"], r["kind"]
    if k == "price" or f == "marketing_price":
        o, n = r["old_value"] or {}, r["new_value"] or {}
        if o.get("final") and n.get("final") and o["final"] != n["final"]:
            return GREEN if n["final"] > o["final"] else RED
        if o.get("discount") != n.get("discount"):
            return RED if (n.get("discount") or 0) > (o.get("discount") or 0) else GREEN
        return GREEN if (n.get("price") or 0) > (o.get("price") or 0) else RED
    if k == "promo":
        return "#9d174d" if f == "out" or (f == "panel" and not (r["new_value"] or {}).get("panel")) else PINK
    if f.startswith("characteristics:"):
        return TEAL
    return None


def change_label(r: dict) -> str:
    """Короткая подпись изменения карточки для таблицы и доски действий."""
    f = r["field"]
    if f == "marketing_price":          
        o, n = (r["old_value"] or {}).get("final") or 0, (r["new_value"] or {}).get("final") or 0
        return f"Цена с акциями Ozon {'↑' if n > o else '↓'} {abs(n - o):,.0f} ₽ → {n:,.0f}".replace(",", " ")
    if f == "archived":
        return "Карточка в архиве" if r["new_value"] else "Карточка из архива"
    if r["kind"] == "price":
        o, n = r["old_value"] or {}, r["new_value"] or {}
        if o.get("final") and n.get("final") and o["final"] != n["final"]:
            d = n["final"] - o["final"]
            return f"Цена {'↑' if d > 0 else '↓'} {abs(d):,.0f} ₽ → {n['final']:,.0f}".replace(",", " ")
        if o.get("discount") != n.get("discount"):
            return f"Скидка {o.get('discount', 0):g} → {n.get('discount', 0):g} %"
        return f"Цена до скидки {o.get('price', 0):,.0f} → {n.get('price', 0):,.0f}".replace(",", " ")
    if r["kind"] == "promo":
        if f == "panel":
            o, n = (r["old_value"] or {}).get("panel"), (r["new_value"] or {}).get("panel")
            if n and not o:
                return f"Появилась плашка акции WB на витрине (№{n})"
            if o and not n:
                return f"Плашка акции WB пропала с витрины (была №{o})"
            return f"Плашка акции WB сменилась: №{o} → №{n}"
        v = r["new_value"] or r["old_value"] or {}
        if f == "in":
            return f"Вошёл в акцию «{v.get('name') or v.get('promo')}»"
        return f"Вышел из акции «{v.get('name') or v.get('promo')}»" + (" (акция закончилась)" if v.get("ended") else "")
    if r["kind"] == "ad_status":
        o, n = r["old_value"] or {}, r["new_value"] or {}
        return f"Реклама «{n.get('campaign', '')}»: " + (f"{o.get('status')} → " if o else "новая, ") + str(n.get("status"))
    if r["kind"] == "ad_bid":
        o, n = r["old_value"] or {}, r["new_value"] or {}
        parts = [f"{'поиск' if k == 'search' else 'реком.' if k == 'recommendations' else k} {o.get(k, 0):g} → {v:g} ₽"
                 for k, v in n.items() if k != "campaign" and o.get(k) != v]
        return f"Ставка «{n.get('campaign', '')}»: " + ", ".join(parts)
    if f == "photo_funnel":
        return "Фото: " + ((r["new_value"] or {}).get("summary") or "изменения").lower()
    if f.startswith("characteristics:"):
        return "Характеристика: " + f.split(":", 1)[1]
    if f == "photos":
        o, n = len(r["old_value"] or []), len(r["new_value"] or [])
        return f"Фото: {o} → {n}" if o != n else "Фото: замена/порядок"
    return CHANGE_TITLE.get(f, f)


def stocks(c, shop: int) -> dict[int, dict]:
    """Остатки сейчас: на складах WB (FBO) и на своём складе (FBS) — последний снимок каждого."""
    out: dict[int, dict] = {}
    for src, key in (("stocks_wb_snap", "wb"), ("stocks_seller_snap", "fbs")):
        for r in c.execute(f"""SELECT nm_id, sum(quantity) q FROM {src} WHERE account_id=%s
                               AND snap_at=(SELECT max(snap_at) FROM {src} WHERE account_id=%s) GROUP BY 1""", (shop, shop)):
            out.setdefault(r["nm_id"], {"wb": 0.0, "fbs": 0.0})[key] = float(r["q"] or 0)
    for v in out.values():
        v["total"] = v["wb"] + v["fbs"]
    return out


def other_pct(c, shop: int) -> float:
    r = c.execute("SELECT value FROM shop_settings WHERE account_id=%s AND key='other_pct'", (shop,)).fetchone()
    return float(r["value"]) if r else 0.03   


def _unit_inputs(c, shop: int) -> dict[int, dict]:
    """Всё, что нужно для юнит-экономики листа ОнлайнЦена, по каждому артикулу магазина."""
    today = today_msk()
    rows = c.execute(
        """WITH lp AS (SELECT DISTINCT ON (nm_id) nm_id, price, discount, discounted_price FROM prices_snap
                       WHERE account_id=%(a)s ORDER BY nm_id, snap_at DESC, size_id),
                st AS (SELECT nm_id, sum(quantity) q FROM stocks_wb_snap WHERE account_id=%(a)s
                       AND snap_at=(SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=%(a)s) GROUP BY 1),
                cp AS (SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%(a)s AND valid_from <= %(t)s
                       ORDER BY nm_id, valid_from DESC),
                tc AS (SELECT DISTINCT ON ((data->>'subjectID')::int) (data->>'subjectID')::int sid, (data->>'paidStorageKgvp')::numeric kgvp
                       FROM raw_rows WHERE account_id=%(a)s AND source='tariffs_commission' ORDER BY (data->>'subjectID')::int, row_date DESC)
           SELECT n.nm_id, n.vendor_code, n.title, n.subject, n.data->'photos'->0->>'tm' AS photo,
                  lp.price base_price, lp.discount, lp.discounted_price online, st.q stock, cp.cost, tc.kgvp
           FROM nomenclature n LEFT JOIN lp USING (nm_id) LEFT JOIN st USING (nm_id) LEFT JOIN cp USING (nm_id)
           LEFT JOIN tc ON tc.sid=n.subject_id
           WHERE n.account_id=%(a)s""", {"a": shop, "t": today}).fetchall()
    lg = last_logistics(c, shop)
    from .exclusions import excluded
    ex = excluded(c, shop)
    return {r["nm_id"]: {**r, "logistics": lg.get(r["nm_id"])} for r in rows if r["nm_id"] not in ex}


_LG: dict = {}


def last_logistics(c, shop: int) -> dict[int, float]:
    """Логистика к клиенту за последнюю неделю с доставками (на 1 доставку) — как «последнее значение» листа ЛогистикаПонедельно.
    Отчёт реализации большой, а меняется раз в сутки — держим в памяти 30 минут."""
    import time
    hit = _LG.get(shop)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    res = {r["nm_id"]: float(r["lg"]) for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, lg / n lg FROM (
               SELECT (data->>'nmId')::bigint nm_id, date_trunc('week', (data->>'rrDate')::date) w,
                      sum((data->>'deliveryService')::numeric) lg, sum((data->>'deliveryAmount')::numeric) n
               FROM raw_rows WHERE account_id=%s AND source='realization' AND row_date >= current_date - 130
                 AND data->>'bonusTypeName' ILIKE 'К клиенту%%' GROUP BY 1, 2) x
           WHERE n > 0 ORDER BY nm_id, w DESC""", (shop,))}
    _LG[shop] = (time.time(), res)
    return res


def _f(x):
    return None if x is None else float(x)


def unit_calc(r: dict, other: float, calc_price: float | None) -> dict:
    """Строка листа ОнлайнЦена по формулам (см. шапку модуля)."""
    D = _f(r.get("online"))
    cost = _f(r.get("cost"))
    K = _f(r.get("logistics")) or 0.0
    L = (_f(r.get("kgvp")) or 0.0) / 100
    N = cost + cost * other if cost is not None else None
    disc = _f(r.get("discount")) or 0.0

    def margin(price):
        if price is None or N is None:
            return None, None
        m = price - N - K - price * L
        return round(m, 2), (round(m / price, 4) if price else None)
    P, O = margin(D)
    E = calc_price if calc_price is not None else D
    R, Q = margin(E)
    F = round(E / (100 - disc) * 100, 2) if E is not None and disc < 100 else None
    return {"online": D, "calc_price": E, "new_base": F, "base_price": _f(r.get("base_price")), "discount": disc,
            "cost": cost, "logistics": round(K, 2) if r.get("logistics") is not None else None, "commission": L, "other": other,
            "cost_total": round(N, 2) if N is not None else None, "margin_online": P, "margin_online_pct": O,
            "margin_calc": R, "margin_calc_pct": Q, "stock": _f(r.get("stock"))}


def _ozon(c, shop: int) -> bool:
    return c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"] == "ozon"


def showcase(c, shop: int) -> dict:
    """Витрина WB (showcase.py): цена с СПП и СПП % за последние сутки — {nm: row}."""
    return {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, price, spp, checked_at FROM wb_showcase WHERE account_id=%s AND checked_at > now() - interval '1 day'", (shop,))}


def price_lab(c, shop: int) -> dict:
    if _ozon(c, shop):
        from . import manager_oz
        return manager_oz.price_lab(c, shop)
    other = other_pct(c, shop)
    drafts = {r["nm_id"]: r for r in c.execute(
        "SELECT d.nm_id, d.price, d.updated_at, u.email FROM price_drafts d LEFT JOIN users u ON u.id=d.user_id WHERE account_id=%s", (shop,))}
    sc = showcase(c, shop)
    rows = []
    for nm, r in _unit_inputs(c, shop).items():
        d, w = drafts.get(nm), sc.get(nm) or {}
        rows.append({"nm_id": nm, "vendor_code": r["vendor_code"], "title": r["title"], "subject": r["subject"], "photo": r["photo"],
                     **unit_calc(r, other, float(d["price"]) if d else None),
                     "draft": float(d["price"]) if d else None, "draft_by": d and d["email"], "draft_at": d and d["updated_at"],
                     "show_price": _f(w.get("price")), "show_spp": _f(w.get("spp")), "show_at": w.get("checked_at")})
    rows.sort(key=lambda x: (-(x["stock"] or 0), x["vendor_code"] or ""))
    return {"other_pct": other, "rows": rows}


def ad_split(c, shop: int, df: date, dt: date) -> dict:
    """Self-hosted application component."""
    info = {}
    for r in c.execute("""SELECT DISTINCT ON ((data->>'advertId')::bigint) (data->>'advertId')::bigint id, data->'info'->>'bid_type' bt,
                                 data->'info'->'settings'->'placements' pl FROM raw_rows WHERE account_id=%s AND source='adverts'""", (shop,)):
        pl = r["pl"] or {}
        info[r["id"]] = ("ark" if r["bt"] == "unified" else "prk", pl.get("search", True), pl.get("recommendations", True))
    kw = {(r["advert_id"], r["nm_id"], r["day"]): float(r["s"] or 0) for r in c.execute(
        """SELECT advert_id, nm_id, day, sum(spend) s FROM wb_ad_kw_daily WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1, 2, 3""",
        (shop, df, dt))}
    out: dict = {}
    for r in c.execute("""
        SELECT (data->>'advertId')::bigint id, (nm->>'nmId')::bigint nm, row_date d, sum((nm->>'sum')::numeric) spend
        FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app,
             jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s GROUP BY 1, 2, 3""", (shop, df, dt)):
        sp = float(r["spend"] or 0)
        if not sp:
            continue
        kind, srch, rec = info.get(r["id"], ("prk", True, True))
        if srch and not rec:
            se = sp
        elif rec and not srch:
            se = 0.0
        else:
            se = min(sp, kw.get((r["id"], r["nm"], r["d"]), 0.0))
        x = out.setdefault(r["nm"], {}).setdefault(r["d"].isoformat(), {"all": 0.0, "ark": 0.0, "prk": 0.0, "search": 0.0, "rec": 0.0})
        x["all"] += sp
        x[kind] += sp
        x["search"] += se
        x["rec"] += sp - se
    return out


def board(c, shop: int, days: int = 14, date_to: date | None = None, ads: bool = False) -> dict:
    """Лист «ДействияПоАртикулам»: ключевые данные артикула + заказы и действия по дням (новые дни — слева, как в листе).
    ads — ДРР по дням в ячейках (сумма заказов дня и расход с разбивкой ad_split)."""
    if _ozon(c, shop):
        from . import manager_oz
        return manager_oz.board(c, shop, days, date_to)
    dt = date_to or today_msk()
    df = dt - timedelta(days=days - 1)
    y = today_msk() - timedelta(days=1)
    w0 = y - timedelta(days=6)                   
    other = other_pct(c, shop)
    units = _unit_inputs(c, shop)
    k7 = {r["nm_id"]: r for r in c.execute(
        """SELECT nm_id, sum((data->>'orders')::numeric) orders, sum((data->>'orders_sum')::numeric) osum,
                  sum((data->>'orders_sum_spp')::numeric) osum_spp, sum((data->>'ads')::numeric) ads,
                  sum((data->>'buyouts_sum')::numeric) bsum, sum((data->>'f_open')::numeric) f_open,
                  sum((data->>'f_cart')::numeric) f_cart, sum((data->>'f_orders')::numeric) f_orders
           FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, w0, y))}
    rating = {r["nm_id"]: r["rating"] for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, (data->>'rating')::numeric rating FROM agg_nm_day
           WHERE account_id=%s AND data->>'rating' IS NOT NULL AND day >= %s ORDER BY nm_id, day DESC""", (shop, y - timedelta(days=30)))}
    spp_price = {r["nm_id"]: r["fp"] for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, finished_price fp FROM orders WHERE account_id=%s AND order_dt >= now() - interval '14 days'
           ORDER BY nm_id, order_dt DESC""", (shop,))}
    spp_price.update({nm: w["price"] for nm, w in showcase(c, shop).items()})     
    plan = {r["nm_id"]: float(r["qty"]) for r in c.execute(
        "SELECT nm_id, qty FROM nm_plans WHERE account_id=%s AND month=%s", (shop, dt.replace(day=1)))}
    from . import wb_demand
    orders = wb_demand.daily(c,shop,df-timedelta(days=1),dt)
    demand = wb_demand.summary(c,shop,w0,y)
    acts = {}
    for r in c.execute("""SELECT a.id, a.nm_id, a.day, a.kind, a.value, a.note, a.user_id, coalesce(u.name, u.email) who, a.created_at
                          FROM nm_actions a LEFT JOIN users u ON u.id=a.user_id
                          WHERE a.account_id=%s AND a.day BETWEEN %s AND %s ORDER BY a.created_at""", (shop, df, dt)):
        acts.setdefault(r["nm_id"], {}).setdefault(r["day"].isoformat(), []).append(
            {"id": r["id"], "kind": r["kind"], "value": r["value"], "note": r["note"], "who": r["who"], "user_id": r["user_id"]})
    for r in c.execute("""SELECT id, nm_id, (detected_at AT TIME ZONE 'Europe/Moscow')::date d, kind, field, old_value, new_value
                          FROM card_changes WHERE account_id=%s AND (detected_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s
                          ORDER BY detected_at""", (shop, df, dt)):
        acts.setdefault(r["nm_id"], {}).setdefault(r["d"].isoformat(), []).append(
            {"id": f"c{r['id']}", "kind": "auto:" + r["kind"], "value": change_label(r), "auto": True, "color": change_color(r)})
    for r in c.execute("SELECT nm_id, day, promos FROM wb_promo_days WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, df, dt)):
        acts.setdefault(r["nm_id"], {}).setdefault(r["day"].isoformat(), []).append(       
            {"id": f"p{r['nm_id']}_{r['day']:%Y%m%d}", "kind": "auto:promo_day", "value": "В акции: " + ", ".join(sorted(r["promos"])), "auto": True})
    import zlib
    for r in c.execute("""SELECT nm_id, day, section, point, clicks, clicks_avg, change_pct FROM entry_alerts
                          WHERE account_id=%s AND day BETWEEN %s AND %s ORDER BY abs(clicks - clicks_avg) DESC""", (shop, df, dt)):
        up = r["clicks"] > r["clicks_avg"]                 
        acts.setdefault(r["nm_id"], {}).setdefault(r["day"].isoformat(), []).append(
            {"id": f"e{r['nm_id']}_{r['day']:%Y%m%d}_{zlib.crc32((r['section'] + '|' + r['point']).encode()) & 0xffffff}", "kind": "auto:entry", "auto": True,
             "color": GREEN if up else RED,
             "value": f"Точка входа {r['section']} / {r['point']}: {float(r['clicks_avg']):.0f} → {float(r['clicks']):.0f} переходов "
                      f"({'+' if up else ''}{r['change_pct']} %)"})
    ad_day, osum_day = {}, {}
    if ads:
        ad_day = ad_split(c, shop, df, dt)
        for r in c.execute("""SELECT nm_id, day, (data->>'orders_sum')::numeric s FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s""",
                           (shop, df, dt)):
            if r["s"]:
                osum_day.setdefault(r["nm_id"], {})[r["day"].isoformat()] = float(r["s"])
    stk = stocks(c, shop)
    out = []
    for nm, u in units.items():
        k = k7.get(nm) or {}
        dm = demand.get(nm) or wb_demand.empty(w0,y)
        avg = dm['orders_day']
        sk = stk.get(nm) or {}
        stock = sk.get("total")
        calc = unit_calc(u, other, None)
        osum, osum_spp = _f(k.get("osum")), _f(k.get("osum_spp"))
        ads, bsum = _f(k.get("ads")) or 0.0, _f(k.get("bsum"))
        fo, fc, fr = _f(k.get("f_open")), _f(k.get("f_cart")), _f(k.get("f_orders"))
        out.append({
            "nm_id": nm, "vendor_code": u["vendor_code"], "title": u["title"], "subject": u["subject"], "photo": u["photo"],
            "stock_wb": sk.get("wb"), "stock_fbs": sk.get("fbs"), "stock": stock, "price": calc["online"], "price_spp": _f(spp_price.get(nm)), "margin_pct": calc["margin_online_pct"],
            "rating": _f(rating.get(nm)), "orders_avg": wb_demand.rounded(avg, 2), "stock_days": round(stock / avg, 1) if stock is not None and avg else None,
            'demand': dm, 'orders_source':'wb_funnel',
            "spp": round(1 - osum_spp / osum, 4) if osum and osum_spp is not None else None, "plan": plan.get(nm),
            "drr_orders": round(ads / osum, 4) if osum else None, "drr_buyouts": round(ads / bsum, 4) if bsum else None,
            "conv_cart": wb_demand.rounded(dm['conv_cart'],4), "conv_order": wb_demand.rounded(dm['conv_order'],4),
            "orders": orders.get(nm, {}), "actions": acts.get(nm, {}),
            **({"ads": {d: {**v, "osum": osum_day.get(nm, {}).get(d)} for d, v in ad_day.get(nm, {}).items()}} if ads else {}),
        })
    out.sort(key=lambda x: (-(sum(x["orders"].values())), x["vendor_code"] or ""))
    return {"days": [(dt - timedelta(days=i)).isoformat() for i in range(days)], "kinds": KINDS, "rows": out,
            "month": dt.replace(day=1).isoformat(), 'demand_note': wb_demand.NOTE}

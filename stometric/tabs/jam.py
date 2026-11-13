"""Self-hosted application component."""

from datetime import timedelta

from .. import jam

COLS = [("query", "Кластер / Поисковый запрос", "text"), ("freq", "Частота за период", "int"), ("cover", "% охвата кластера", "share"),
        ("pos", "Средняя позиция", "num"), ("views", "Показы за период", "int"), ("clicks", "Клики общие", "int"),
        ("cr_cart", "Конверсия в корзину", "share"), ("carts", "Корзин, шт", "int"), ("cr_order", "Конверсия в заказ", "share"),
        ("orders", "Заказали, шт", "int"), ("cr_card", "Конверсия карточки", "share"), ("ad_views", "Показы РК", "int"),
        ("ad_clicks", "Клики РК", "int"), ("ctr", "CTR", "share"), ("cpc", "CPC", "money"), ("spend", "Затраты РК", "money"),
        ("cart_cost", "Цена корзины", "money"), ("order_cost", "Цена заказа", "money"), ("ad_share", "% РК", "share"),
        ("profit", "Прибыль с ДРР", "money"), ("pot_clicks", "Потенциал кликов", "int"), ("pot_orders", "Потенциал заказов", "num"),
        ("pot_profit", "Потенциал прибыли", "money")]


GREEN, LIGHT, LIGHTER, YELLOW, RED = "#57bb8a", "#80cca7", "#afdfc7", "#ffe599", "#ea9999"
RULES = {   
    "cover": [(0.8, None, GREEN), (0.5, 0.8, YELLOW), (None, 0.5, RED)],
    "pos": [(None, 30, GREEN), (30, 100, YELLOW), (100, None, RED)],
    "views": [(5000, None, GREEN), (500, 5000, LIGHT), (0, 500, LIGHTER)],
    "clicks": [(100, None, GREEN), (50, 100, LIGHT), (0, 50, LIGHTER)],
    "carts": [(10, None, GREEN), (3, 10, LIGHT), (0, 3, LIGHTER)],
    "orders": [(10, None, GREEN), (3, 10, LIGHT), (0, 3, LIGHTER)],
    "ctr": [(0.1, None, GREEN), (0.04, 0.1, LIGHT), (0, 0.04, LIGHTER)],
}
GRAD = ["pot_clicks", "pot_orders", "pot_profit"]     


def _rules():
    """Правила для фронта: интервал (lo, hi] — lo не включается (кроме None), hi включается; 0 и пусто не красим."""
    return {f: [{"gt": lo, "le": hi, "color": col} for lo, hi, col in rr] for f, rr in RULES.items()}


def _msg(text: str, retry: int | None = None, nm=None, label: str = "") -> dict:
    return {"columns": [{"field": "msg", "title": "Джем" + (f" · {label}" if label else ""), "type": "text"}], "rows": [{"msg": text}],
            "plain": True, "note": text, "retry": retry}


def _pick_nm(c, shop, f) -> tuple[int | None, str]:
    if f.get("nm_ids"):
        return f["nm_ids"][0], ("Выбрано несколько артикулов — отчёт Джема строится по одному: показан первый. " if len(f["nm_ids"]) > 1 else "")
    r = c.execute("""SELECT nm_id, sum((data->>'f_orders')::numeric) o FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s
                     GROUP BY 1 HAVING count(data->>'f_orders')>0 ORDER BY 2 DESC NULLS LAST LIMIT 1""", (shop, f["date_from"], f["date_to"])).fetchone()
    return (r["nm_id"] if r else None), "Артикул не выбран — показан самый заказываемый по доступной воронке WB за период (выберите свой в фильтре «Артикулы»). "


def unit_profit(c, shop: int, nm: int, a, b) -> tuple[float | None, str]:
    """Прибыль на 1 шт до рекламы из юнит-экономики артикула; если за период не было заказов — за 90 дней до конца периода."""
    for x in (a, b - timedelta(days=89)):
        r = c.execute("""SELECT sum((data->>'profit_orders')::numeric) p, sum(coalesce((data->>'ads_upd')::numeric,0)) ad,
                                sum((data->>'orders')::numeric) o, sum(coalesce((data->>'cost_orders')::numeric,0)) cost
                         FROM agg_nm_day WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s""", (shop, nm, min(x, a), b)).fetchone()
        if r and r["o"] and r["p"] is not None:
            if not r["cost"]:
                return None, "У артикула нет себестоимости — прибыль и потенциал прибыли не считаем (заполните «Себестоимость»). "
            return round(float(r["p"] + r["ad"]) / float(r["o"]), 2), ""
    return None, "Нет заказов артикула за 90 дней — прибыль на 1 шт не посчитать. "


def _ads(c, shop, nm, a, b) -> dict[str, dict]:
    out = {}
    for r in c.execute("""SELECT lower(trim(query)) q, sum(views) v, bool_or(views IS NOT NULL) hv, sum(clicks) cl, sum(spend) sp
                          FROM wb_ad_kw_daily WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, nm, a, b)):
        
        out[r["q"]] = {"v": int(r["v"] or 0) if r["hv"] else None, "cl": int(r["cl"] or 0), "sp": float(r["sp"] or 0)}
    return out


def _d(a, b):
    return a / b if a is not None and b else None


def _row(q, freq, vis, pos, cl, ca, o, ad, ppu) -> dict:
    views = round(freq * vis / 100) if freq is not None and vis is not None else None
    av, acl, sp = (ad or {}).get("v", 0), (ad or {}).get("cl", 0), (ad or {}).get("sp", 0.0)
    ctr = _d(acl, av)
    crc = _d(o, cl)
    k = ctr if ctr is not None else _d(cl, views)      
    pclk = max(0, (freq or 0) - (views or 0)) * k if k is not None else 0
    pord = pclk * crc if crc is not None else 0
    return {"query": q, "freq": freq, "cover": min(1.0, views / freq) if freq and views is not None else None, "pos": pos, "views": views,
            "clicks": cl, "cr_cart": _d(ca, cl), "carts": ca, "cr_order": _d(o, ca), "orders": o, "cr_card": crc,
            "ad_views": av, "ad_clicks": acl, "ctr": ctr, "cpc": round(sp / acl, 2) if acl else None, "spend": round(sp, 2),
            "cart_cost": round(sp / ca, 2) if ca and sp else None, "order_cost": round(sp / o, 2) if o and sp else None,
            "ad_share": _d(av, views), "profit": round((o or 0) * ppu - sp, 2) if ppu is not None else None,
            "pot_clicks": round(pclk), "pot_orders": round(pord, 1), "pot_profit": round(pord * ppu) if ppu is not None else None}


def jam_tab(c, shop, f):
    a, b = jam.period(f)
    nm, note = _pick_nm(c, shop, f)
    if not nm:
        return _msg("Выберите артикул в фильтре «Артикулы» — отчёт Джема строится по одному артикулу.")
    acc = jam.access(c, shop)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if acc and acc["status"] != "ok" and now - acc["checked_at"] < jam.ACCESS_RECHECK:
        return _msg(jam.NO_JAM if acc["status"] == "no_jam" else jam.NO_SCOPE)
    cur = jam.cached(c, shop, nm, a, b)
    ready = _loaded(c, shop)
    if cur and cur["state"] == "done":
        if now - cur["fetched_at"] > jam.FRESH:      
            jam.start(shop, nm, a, b)
        return _render(c, shop, nm, a, b, cur["items"], note, ready)
    other = _latest(c, shop, nm)                     
    if not cur or (cur["state"] == "error" and now - (cur["fetched_at"] or cur["started_at"]) > timedelta(minutes=2)):
        jam.start(shop, nm, a, b)
        cur = {"state": "running"}
    if other and cur["state"] == "running":
        res = _render(c, shop, nm, other["date_from"], other["date_to"], other["items"],
                      note + f"Показан отчёт, загруженный сегодня за {other['date_from']:%d.%m}–{other['date_to']:%d.%m}; "
                      f"за выбранный период {a:%d.%m}–{b:%d.%m} загружаю в фоне — вкладка обновится сама. ", ready)
        return {**res, "retry": 20, "shown_period": [other["date_from"], other["date_to"]]}   
    if cur["state"] == "running":
        return _msg(f"Загружаю отчёт Джема по артикулу {nm} за {a:%d.%m.%Y}–{b:%d.%m.%Y} из WB (лимит WB — 3 запроса в минуту, "
                    "около минуты). Вкладка обновится сама." + _ready_text(ready), retry=15)
    e = cur["error"] or ""
    if e in (jam.NO_JAM, jam.NO_SCOPE):
        return _msg(e)
    return _msg(f"WB не отдал отчёт Джема: {e[:300]}. Повторю через пару минут при следующем открытии вкладки." + _ready_text(ready))


def _loaded(c, shop) -> list[dict]:
    """Артикулы, по которым Джем уже загружен сегодня (МСК): открываются сразу, без ожидания WB."""
    return c.execute("""SELECT DISTINCT ON (j.nm_id) j.nm_id, n.vendor_code FROM jam_cache j
                        LEFT JOIN nomenclature n ON n.account_id=j.account_id AND n.nm_id=j.nm_id
                        WHERE j.account_id=%s AND j.state='done'
                          AND j.fetched_at >= (date_trunc('day', now() AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow')
                        ORDER BY j.nm_id""", (shop,)).fetchall()


def _latest(c, shop, nm):
    return c.execute("""SELECT date_from, date_to, items FROM jam_cache WHERE account_id=%s AND nm_id=%s AND state='done'
                          AND fetched_at >= (date_trunc('day', now() AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow')
                        ORDER BY date_to DESC, fetched_at DESC LIMIT 1""", (shop, nm)).fetchone()


def _ready_text(ready) -> str:
    if not ready:
        return ""
    return (f" Уже загружены сегодня и открываются сразу ({len(ready)}): "
            + ", ".join(r["vendor_code"] or str(r["nm_id"]) for r in ready) + ".")


def _render(c, shop, nm, a, b, items, note, ready):
    ppu, pnote = unit_profit(c, shop, nm, a, b)
    ads = _ads(c, shop, nm, a, b)
    rows = []
    for x in items or []:
        q = x.get("text") or ""
        rows.append(_row(q, x.get("frequency"), x.get("visibility"), x.get("avgPosition"), x.get("openCard"), x.get("addToCart"),
                         x.get("orders"), ads.get(q.lower().strip()), ppu))
    rows.sort(key=lambda r: (-(r["orders"] or 0), -(r["clicks"] or 0)))
    s = lambda k: sum(r[k] or 0 for r in rows)  
    pos = [r["pos"] for r in rows if r["pos"]]
    tot = _row("ИТОГО", s("freq"), None, round(sum(pos) / len(pos)) if pos else None, s("clicks"), s("carts"), s("orders"), None, ppu)
    has_av = any(r["ad_views"] is not None for r in rows)
    tot.update({"views": s("views"), "cover": _d(s("views"), s("freq")), "ad_views": s("ad_views") if has_av else None, "ad_clicks": s("ad_clicks"),
                "spend": round(s("spend"), 2), "pot_clicks": s("pot_clicks"), "pot_orders": round(s("pot_orders"), 1),
                "pot_profit": s("pot_profit") if ppu is not None else None})
    tot["ctr"] = _d(tot["ad_clicks"], tot["ad_views"])
    tot["cpc"] = round(tot["spend"] / tot["ad_clicks"], 2) if tot["ad_clicks"] else None
    tot["cart_cost"] = round(tot["spend"] / tot["carts"], 2) if tot["carts"] and tot["spend"] else None
    tot["order_cost"] = round(tot["spend"] / tot["orders"], 2) if tot["orders"] and tot["spend"] else None
    tot["ad_share"] = _d(tot["ad_views"], tot["views"])
    tot["profit"] = round(tot["orders"] * ppu - tot["spend"], 2) if ppu is not None else None
    v = c.execute("SELECT vendor_code FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    lim = (jam.access(c, shop) or {}).get("max_limit")
    head = (f"Артикул {nm}" + (f" ({v['vendor_code']})" if v and v["vendor_code"] else "") + f", {a:%d.%m.%Y}–{b:%d.%m.%Y}. "
            + (f"Прибыль на 1 шт до рекламы: {ppu:,.0f} ₽ (юнит-экономика артикула). ".replace(",", " ") if ppu is not None else "")
            + note + pnote
            + f"Запросов: {len(rows)} (WB отдаёт топ{' ' + str(lim) if lim else ''} по переходам, заказам и корзинам). "
            "Показы = частота × видимость. Реклама — по кластерам РК, совпадающим с запросом (у кампаний с оплатой за клики WB не даёт "
            "показы по кластерам — тогда CTR и % РК пустые, а потенциал кликов считаем по CTR запроса в целом). «Потенциал РК» — позже."
            + _ready_text(ready))
    return {"columns": [{"field": k, "title": t, "type": ty} for k, t, ty in COLS], "rows": rows, "plain": True, "note": head,
            "total_row": tot, "rules": _rules(), "grad": GRAD, "empty": "WB не нашёл поисковых запросов артикула за период."}

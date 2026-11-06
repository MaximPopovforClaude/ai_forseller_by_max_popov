"""Self-hosted application component."""

import calendar
from collections import defaultdict
from datetime import date, timedelta

from .config import today_msk

F = ["orders_sum", "orders_sum_spp", "orders", "buyouts", "buyouts_sum_before_spp", "commission_offer_orders", "logistics_orders",
     "cost_orders", "ads_upd", "ads_bonus", "storage", "acceptance_sum", "vat_orders", "vat_deduct_orders", "local_share"]
METRICS = [("orders", "Заказы", ("Сумма, р", "Кол-во")), ("buyouts", "Выкупы", ("Сумма, р", "Кол-во")),
           ("ads", "Рекламный бюджет", ("Сумма, р", "ДРР")), ("profit", "Прибыль расчет", ("Сумма, р", "Маржа с ДРР"))]
SORTS = {"orders_sum": "Заказы, руб", "orders": "Заказы, шт", "buyouts_sum": "Выкупы, руб", "ads": "Рекламный бюджет", "drr": "ДРР",
         "profit": "Прибыль", "margin": "Маржа с ДРР", "krrr": "КЭМ"}
PAGE = 30


def _tax(c, shop, d):
    t = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1", (shop, d)).fetchone()
    t = t or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    return {"regime": t["regime"], "rate": float(t["rate"] or 0), "vat": float(t["vat_rate"] or 0), "vat_wb": float(t["vat_deduct_wb"] or 0)}


def profit(S: dict, bp: float, tx: dict) -> float:
    """Строка 35 «5#Дашборда» (прибыль по заказам с учётом % выкупа за минусом налога) для сумм S и доли выкупа bp."""
    g = lambda k: float(S.get(k) or 0)  
    r15, r17 = g("orders_sum") * bp, g("orders_sum_spp") * bp
    r20, r21, r22 = -g("commission_offer_orders") * bp, -g("logistics_orders"), g("cost_orders") * bp
    
    
    r18 = r15 + r20 + r21 - r22 - g("acquiring_orders") * bp
    r23, r27 = -g("ads_upd"), -(g("storage") + g("acceptance_sum"))
    r33 = -g("vat_orders") * bp
    r34 = g("vat_deduct_orders") * bp + ((r20 + r21 + r27 + r23) * tx["vat_wb"] / (1 + tx["vat_wb"]) * -1 if tx["vat"] >= 0.10 else 0)
    if tx["regime"] == "УСН доход":
        r32 = -tx["rate"] * (r17 + r33)
    elif tx["regime"] == "УСН доходы-расходы":
        base = r18 + r23 + r27 + r33
        r32 = -(tx["rate"] * base if tx["rate"] * base > r17 * 0.01 else r17 * 0.01)
    elif tx["regime"] == "ОСНО":
        r32 = -tx["rate"] * max(0.0, r18 + r23 + r27 + r33 + r34)
    elif tx["regime"] == "ОСНО ИП (НДФЛ)":
        from .sheets.pnl_real import ndfl
        base = float(tx.get("ndfl_base") or 0)
        r32 = -(ndfl(max(0.0, base + r18 + r23 + r27 + r33 + r34)) - ndfl(max(0.0, base)))
    else:
        r32 = 0.0
    return r18 + r23 + r27 + r32 + r33 + r34


def _vals(S: dict, bp: float, tx: dict, P: float | None = None) -> dict:
    """8 строк блока из сумм периода. P — уже посчитанная прибыль (сумма по артикулам), иначе считаем здесь."""
    os_, ads = float(S.get("orders_sum") or 0), float(S.get("ads_upd") or 0)
    p = profit(S, bp, tx) if P is None else P
    base = float(S.get("_r15") if "_r15" in S else os_ * bp)
    return {"orders_sum": round(os_), "orders": int(S.get("orders") or 0), "buyouts_sum": round(float(S.get("buyouts_sum_before_spp") or 0)),
            "buyouts": int(S.get("buyouts") or 0), "ads": round(ads), "drr": ads / os_ if os_ else None, "profit": round(p),
            "margin": p / base if base else None, "margin_pre": (p + ads) / base if base else None,
            "krrr": p / (p + ads) if (p + ads) > 0 else None,
            
            "bonus": round(bn := float(S.get("ads_bonus") or 0)), "drr_bonus": bn / os_ if os_ else None,
            "ads_all": round(ads + bn), "drr_all": (ads + bn) / os_ if os_ else None}


def _add(a: dict, b: dict):
    for k, v in b.items():
        if v is not None and k != "local_share":
            a[k] = a.get(k, 0.0) + float(v)


def buyout_pct(c, shop) -> tuple[dict, float]:
    """% выкупа за 4 недели по отчёту реализации (как «2#СводнаяПоАртикуламWB»), и общий по кабинету — для артикулов без отчёта.
    В отчёте нет доставок к покупателю (КГТ, своя доставка) — по заказам (agg.buyout)."""
    from .agg import buyout, real_week
    if buyout.needed(c, shop):
        return buyout.by_orders(c, shop)
    per = defaultdict(list)
    if c.execute("SELECT 1 FROM agg_state WHERE account_id=%s AND name='real_week'", (shop,)).fetchone():
        
        for g in c.execute("""SELECT (data->>'nm_id')::bigint nm_id, data->>'date_from' date_from, data->>'date_to' date_to,
                                     sum(coalesce((data->>'deliveries')::numeric, 0)) deliveries, sum(coalesce((data->>'returns')::numeric, 0)) returns
                              FROM agg_real_week WHERE account_id=%s AND coalesce((data->>'nm_id')::bigint, 0) <> 0
                              AND coalesce(data->>'date_from', '') <> '' GROUP BY 1, 2, 3""", (shop,)):
            per[g["nm_id"]].append((date.fromisoformat(g["date_from"]), date.fromisoformat(g["date_to"]), float(g["deliveries"]), float(g["returns"])))
    else:
        for g in real_week.cached(c, shop):
            if g["nm_id"] and g["date_from"]:
                per[g["nm_id"]].append((date.fromisoformat(g["date_from"]), date.fromisoformat(g["date_to"]), float(g["deliveries"] or 0),
                                        float(g["returns"] or 0)))
    bp, D, R = {}, 0.0, 0.0
    for nm, lst in per.items():
        mx = max(x[1] for x in lst)
        dl = sum(x[2] for x in lst if x[0] >= mx - timedelta(days=27) and x[1] <= mx)
        rt = sum(x[3] for x in lst if x[0] >= mx - timedelta(days=27) and x[1] <= mx)
        if dl >= 5:
            bp[nm] = max(0.0, (dl - rt) / dl)
        D += dl; R += rt
    return bp, (max(0.0, (D - R) / D) if D else 1.0)


def _bp_weeks(c, shop, nms: set, end: date) -> dict:
    """% выкупа по неделям (8 недель) — для графика у артикула."""
    from .agg import real_week
    acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    lo = end - timedelta(days=62)
    for g in real_week.cached(c, shop):
        if g["nm_id"] in nms and g["date_from"] and date.fromisoformat(g["date_to"]) >= lo:
            a = acc[g["nm_id"]][g["date_to"]]
            a[0] += float(g["deliveries"] or 0); a[1] += float(g["returns"] or 0)
    return {nm: [max(0.0, (d - r) / d) if d else None for d, r in (v[k] for k in sorted(v))] for nm, v in acc.items()}


_PLAN: dict = {}


def plan(c, shop, m: date, bp: dict, bp0: float) -> dict[int, dict]:
    """План месяца по артикулу из «Планирования»: выкупы шт/₽, заказы шт/₽ (= выкупы / % выкупа), реклама ₽, прибыль ₽.
    Кэш в процессе: параметры юнит-экономики (логистика из отчёта реализации) считаются долго, а план меняется редко."""
    import time
    from .tabcache import version
    ver = (c.execute("SELECT max(updated_at) t FROM plan_cells WHERE account_id=%s AND month=%s", (shop, m)).fetchone()["t"],
           version(c, shop))
    hit = _PLAN.get((shop, m))
    if hit and hit[0] == ver and time.time() - hit[1] < 3600:
        return hit[2]
    out = _plan(c, shop, m, bp, bp0)
    _PLAN[(shop, m)] = (ver, time.time(), out)
    return out


def _plan(c, shop, m: date, bp: dict, bp0: float) -> dict[int, dict]:
    from . import planning
    cells = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_cells WHERE account_id=%s AND month=%s", (shop, m))}
    if not cells:
        return {}
    st = planning.settings(c, shop)
    items = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_items WHERE account_id=%s", (shop,))}
    params = planning._unit_params(c, shop)
    facts = planning._facts(c, shop, planning.add_months(m, -1))
    regime, rate = planning._tax(c, shop)
    qty_tot = sum(float(x.get("qty") or 0) for x in cells.values())
    out = {}
    for nm, cl in cells.items():
        p = params.get(nm) or {"commission": 0, "logistics": 0, "cost": None}
        it = items.get(nm) or {}
        ads_share = float(it["ads_share"]) if it.get("ads_share") is not None else (facts.get(nm) or {}).get("ads_share", 0.0)
        q = float(cl.get("qty") or 0)
        fixed = float(st["fixed_month"]) * q / qty_tot if qty_tot else 0.0
        v = planning.calc(cl.get("qty"), cl.get("price"), cl.get("cost"), p, ads_share, fixed, regime, rate)
        b = bp.get(nm, bp0) or 1.0
        out[nm] = {"buyouts": v["qty"], "buyouts_sum": v["revenue"], "orders": v["qty"] / b, "orders_sum": v["revenue"] / b,
                   "ads": v["ads"], "profit": v["profit"]}
    return out


def _plan_vals(p: dict | None, k: float = 1.0) -> dict | None:
    if not p:
        return None
    os_ = p["orders_sum"] * k
    return {"orders_sum": round(os_), "orders": round(p["orders"] * k), "buyouts_sum": round(p["buyouts_sum"] * k),
            "buyouts": round(p["buyouts"] * k), "ads": round(p["ads"] * k), "drr": p["ads"] / p["orders_sum"] if p["orders_sum"] else None,
            "profit": round(p["profit"] * k), "margin": p["profit"] / p["buyouts_sum"] if p["buyouts_sum"] else None}


def compute(c, shop: int, month: date, flt: dict, sort: str = "orders_sum", offset: int = 0, with_buyout: bool = True) -> dict:
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    from .tabs.basic import group_nms
    today = today_msk()
    m0 = month.replace(day=1)
    m1 = m0.replace(day=calendar.monthrange(m0.year, m0.month)[1])
    cur = m0 <= today <= m1
    if m0 > today:
        return {"error": "Месяц ещё не начался"}
    end = min(m1, today)                       
    wend = min(m1, today - timedelta(days=1)) if cur and today.day > 1 else end   
    lo = min(m0, end - timedelta(days=29), wend - timedelta(days=20))
    tx = _tax(c, shop, end)
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    src = None
    if mp != "wb":                             
        from . import rnp_mp
        src = rnp_mp.source(c, shop, mp, lo, end)
        nom = src["nom"]
    else:
        nom = {r["nm_id"]: r for r in c.execute(
            """SELECT nm_id, vendor_code, title, brand, subject, imt_id, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s""",
            (shop,))}
    
    allow = None
    if flt.get("group"):
        allow = set(src["groups"](flt["group"]) if src else group_nms(c, shop, flt["group"])) or {-1}
    if flt.get("nm_ids"):
        allow = (allow or set(flt["nm_ids"])) & set(flt["nm_ids"])
    brand, subject = flt.get("brand"), flt.get("subject")

    from .exclusions import excluded
    ex = excluded(c, shop)                     

    def ok(nm):
        n = nom.get(nm) or {}
        return nm not in ex and (allow is None or nm in allow) and (not brand or n.get("brand") == brand) and (not subject or n.get("subject") == subject)

    day = defaultdict(dict)                    
    if src:
        for nm, dd in src["day"].items():
            if ok(nm):
                day[nm] = dd
        bp, bp0 = src["bp"], src["bp0"]
        pl = {}
        stock, fbs, price = src["stock"], src["fbs"], src["price"]
    else:
        stock, fbs, price, bp, bp0, pl = _wb_source(c, shop, lo, end, m0, ok, day)
    nms = [nm for nm in set(day) | {n for n in pl if ok(n)} | {n for n, s in stock.items() if ok(n) and (s["q"] or 0) > 0}
           | {n for n, q in fbs.items() if ok(n) and q > 0}]
    return _finish(c, shop, mp, m0, m1, cur, end, wend, tx, nom, day, bp, bp0, pl, stock, fbs, price, nms, sort, offset, with_buyout)


def _wb_source(c, shop, lo, end, m0, ok, day):
    from .materialize import ensure_ready
    st = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (shop,)).fetchone()
    if not st or not st["covered_to"]:
        ensure_ready(c, shop, False)
    sel = ", ".join(f"(data->>'{k}')::numeric {k}" for k in F)
    for r in c.execute(f"SELECT nm_id, day, {sel} FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, lo, end)):
        if ok(r["nm_id"]):
            day[r["nm_id"]][r["day"]] = r
    if st and st["covered_to"] and end > st["covered_to"]:     
        from .agg import nm_day
        for r in nm_day.compute(c, shop, st["covered_to"] + timedelta(days=1), end):
            if ok(r["nm_id"]):
                day[r["nm_id"]][r["day"]] = {k: r.get(k) for k in F}
    bp, bp0 = buyout_pct(c, shop)
    pl = plan(c, shop, m0, bp, bp0)
    
    stock = {r["nm_id"]: r for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q, sum(in_way_to_client) wt, sum(in_way_from_client) wf
           FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    fbs = {r["nm_id"]: float(r["q"] or 0) for r in c.execute(      
        """WITH last AS (SELECT max(snap_at) t FROM stocks_seller_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q FROM stocks_seller_snap s JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    price = {r["nm_id"]: r for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, discounted_price FROM prices_snap WHERE account_id=%s ORDER BY nm_id, snap_at DESC, size_id""",
        (shop,))}
    return stock, fbs, price, bp, bp0, pl


def _finish(c, shop, mp, m0, m1, cur, end, wend, tx, nom, day, bp, bp0, pl, stock, fbs, price, nms, sort, offset, with_buyout):
    days = [m0 + timedelta(days=i) for i in range((end - m0).days + 1)]
    spark_days = [end - timedelta(days=29 - i) for i in range(30)]
    weeks = [(wend - timedelta(days=20), wend - timedelta(days=14)), (wend - timedelta(days=13), wend - timedelta(days=7)),
             (wend - timedelta(days=6), wend)]
    dim = (m1 - m0).days + 1
    elapsed = (wend - m0).days + 1 if cur else dim
    blocks, TOT = [], {"S": {}, "P": 0.0, "days": defaultdict(lambda: [{}, 0.0]), "weeks": [[{}, 0.0] for _ in weeks],
                       "fc": [{}, 0.0], "loc": [0.0, 0.0], "stock": 0.0, "fbs": 0.0, "have": 0.0, "have0": 0.0, "speed": 0.0, "plan": {}}

    def agg(nm, a, b):
        S = {}
        for d, r in day[nm].items():
            if a <= d <= b:
                _add(S, {k: r.get(k) for k in F})
        return S

    for nm in nms:
        b = bp.get(nm, bp0)
        Sm = agg(nm, m0, end)
        Pm = profit(Sm, b, tx)
        vm = _vals(Sm, b, tx, Pm)
        fcS = agg(nm, m0, wend)
        k = dim / elapsed if cur and elapsed > 0 else 1.0
        fcP = profit(fcS, b, tx)
        dvals, sp = {}, {"orders_sum": [], "buyouts_sum": [], "drr": [], "profit": [], "price_spp": [], "krrr": [], "margin_pre": []}
        for d in sorted(set(days) | set(spark_days)):
            r = day[nm].get(d) or {}
            S = {k2: r.get(k2) for k2 in F}
            P = profit(S, b, tx)
            v = _vals(S, b, tx, P)
            if m0 <= d <= end:
                dvals[d.isoformat()] = v
                t = TOT["days"][d.isoformat()]
                _add(t[0], S); t[0]["_r15"] = t[0].get("_r15", 0.0) + float(S.get("orders_sum") or 0) * b; t[1] += P
            if d in spark_days:
                for key in ("orders_sum", "buyouts_sum", "drr", "profit", "krrr", "margin_pre"):
                    sp[key].append(v[key])
                o = float(S.get("orders") or 0)
                sp["price_spp"].append(round(float(S.get("orders_sum_spp") or 0) / o) if o else None)
        wk = []
        for i, (a, z) in enumerate(weeks):
            S = agg(nm, a, z)
            P = profit(S, b, tx)
            wk.append(_vals(S, b, tx, P))
            _add(TOT["weeks"][i][0], S); TOT["weeks"][i][0]["_r15"] = TOT["weeks"][i][0].get("_r15", 0.0) + float(S.get("orders_sum") or 0) * b
            TOT["weeks"][i][1] += P
        
        lw = [(float(r.get("local_share") or 0), float(r.get("orders") or 0)) for d, r in day[nm].items() if d > end - timedelta(days=14)]
        lo_o = sum(o for _, o in lw)
        loc = sum(s * o for s, o in lw) / lo_o if lo_o else None
        s_ = stock.get(nm) or {}
        q, wt, wf = float(s_.get("q") or 0), float(s_.get("wt") or 0), float(s_.get("wf") or 0)
        speed = sum(float((day[nm].get(d) or {}).get("orders") or 0) for d in spark_days) / 30
        have = q + wt * (1 - b) + wf
        o14 = sum(float(r.get("orders_sum_spp") or 0) for d, r in day[nm].items() if d > end - timedelta(days=14))
        n14 = sum(float(r.get("orders") or 0) for d, r in day[nm].items() if d > end - timedelta(days=14))
        n = nom.get(nm) or {}
        pv = _plan_vals(pl.get(nm))
        blk = {"nm_id": nm, "vendor_code": n.get("vendor_code"), "title": n.get("title"), "brand": n.get("brand"), "subject": n.get("subject"),
               "photo": n.get("photo"), "price": float((price.get(nm) or {}).get("discounted_price") or 0) or None,
               "price_spp": round(o14 / n14) if n14 else None, "buyout": b, "buyout_own": nm in bp,
               "loc": loc, "stock": q, "fbs": fbs.get(nm, 0.0), "days_left": round(have / speed) if speed else None,
               "days_fbs": round(fbs.get(nm, 0.0) / speed) if speed else None, "days_left0": round(q / speed) if speed else None,
               "month": vm, "forecast": _vals({kk: vv * k for kk, vv in fcS.items()}, b, tx, fcP * k), "plan": pv,
               "plan_day": _plan_vals(pl.get(nm), 1 / dim), "weeks": wk, "days": dvals, "spark": sp,
               "bp_weeks": None}
        blocks.append(blk)
        _add(TOT["S"], Sm); TOT["S"]["_r15"] = TOT["S"].get("_r15", 0.0) + float(Sm.get("orders_sum") or 0) * b; TOT["P"] += Pm
        _add(TOT["fc"][0], {kk: vv * k for kk, vv in fcS.items()})
        TOT["fc"][0]["_r15"] = TOT["fc"][0].get("_r15", 0.0) + float(fcS.get("orders_sum") or 0) * k * b
        TOT["fc"][1] += fcP * k
        if loc is not None:
            TOT["loc"][0] += loc * lo_o; TOT["loc"][1] += lo_o
        TOT["stock"] += q; TOT["fbs"] += fbs.get(nm, 0.0); TOT["have"] += have; TOT["have0"] += q; TOT["speed"] += speed
        if pv:
            for kk in ("orders_sum", "orders", "buyouts_sum", "buyouts", "ads", "profit"):
                TOT["plan"][kk] = TOT["plan"].get(kk, 0.0) + pl[nm][kk]
    
    tdays = {d: _vals(S, 1.0, tx, P) for d, (S, P) in TOT["days"].items()}
    tp = TOT["plan"]
    tplan = _plan_vals(tp) if tp else None
    if tplan and tp.get("buyouts_sum"):
        tplan["margin"] = tp["profit"] / tp["buyouts_sum"]
    tsp = {"orders_sum": [], "buyouts_sum": [], "drr": [], "profit": [], "loc": []}
    for d in spark_days:
        S, P = TOT["days"].get(d.isoformat(), ({}, 0.0)) if d >= m0 else ({}, 0.0)
        if d < m0:          
            S, P = {}, 0.0
            for blk_nm in day:
                r = day[blk_nm].get(d)
                if r:
                    Sx = {k2: r.get(k2) for k2 in F}
                    _add(S, Sx); S["_r15"] = S.get("_r15", 0.0) + float(Sx.get("orders_sum") or 0) * bp.get(blk_nm, bp0)
                    P += profit(Sx, bp.get(blk_nm, bp0), tx)
        v = _vals(S, 1.0, tx, P)
        for key in ("orders_sum", "buyouts_sum", "drr", "profit"):
            tsp[key].append(v[key])
        lw = [(float(day[x][d].get("local_share") or 0), float(day[x][d].get("orders") or 0)) for x in day if d in day[x]]
        so = sum(o for _, o in lw)
        tsp["loc"].append(sum(s * o for s, o in lw) / so if so else None)
    total = {"month": _vals(TOT["S"], 1.0, tx, TOT["P"]), "forecast": _vals(TOT["fc"][0], 1.0, tx, TOT["fc"][1]), "plan": tplan,
             "plan_day": ({kk: (vv / dim if kk not in ("drr", "margin") else vv) for kk, vv in tplan.items()} if tplan else None),
             "weeks": [_vals(S, 1.0, tx, P) for S, P in TOT["weeks"]], "days": tdays, "spark": tsp,
             "loc": TOT["loc"][0] / TOT["loc"][1] if TOT["loc"][1] else None, "stock": TOT["stock"], "fbs": TOT["fbs"], "days_fbs": round(TOT["fbs"] / TOT["speed"]) if TOT["speed"] else None,
             "days_left": round(TOT["have"] / TOT["speed"]) if TOT["speed"] else None,
             "days_left0": round(TOT["have0"] / TOT["speed"]) if TOT["speed"] else None, "articles": len(blocks)}
    key = {"orders_sum": lambda x: x["month"]["orders_sum"], "orders": lambda x: x["month"]["orders"],
           "buyouts_sum": lambda x: x["month"]["buyouts_sum"], "ads": lambda x: x["month"]["ads"],
           "drr": lambda x: x["month"]["drr"] or 0, "profit": lambda x: x["month"]["profit"], "margin": lambda x: x["month"]["margin"] or -9,
           "krrr": lambda x: x["month"]["krrr"] or -9}.get(sort, lambda x: x["month"]["orders_sum"])
    blocks.sort(key=lambda x: (key(x), x["month"]["orders_sum"]), reverse=True)
    page = blocks[offset:offset + PAGE]
    bw = _bp_weeks(c, shop, {b_["nm_id"] for b_ in page}, end) if mp == "wb" else {}
    for b_ in page:
        b_["bp_weeks"] = bw.get(b_["nm_id"])
    brands = sorted({(nom.get(n) or {}).get("brand") for n in nom if (nom.get(n) or {}).get("brand")})
    subjects = sorted({(nom.get(n) or {}).get("subject") for n in nom if (nom.get(n) or {}).get("subject")})
    return {"month": m0.isoformat(), "days": [d.isoformat() for d in days], "spark_from": spark_days[0].isoformat(),
            "tax_basis": "Прогноз налога на расчётную прибыль заказов; НДФЛ оценён для расчётного периода. Фактический налог с начала года — в PnL.",
            "spark_to": spark_days[-1].isoformat(), "weeks": [[a.isoformat(), z.isoformat()] for a, z in weeks], "current": cur,
            "elapsed": elapsed, "dim": dim, "total": total, "bonus": bool(total["month"]["bonus"] or any(w["bonus"] for w in total["weeks"])), "blocks": page, "count": len(blocks), "offset": offset, "page": PAGE,
            "has_plan": bool(pl), "sorts": SORTS, "brands": brands, "subjects": subjects, "metrics": METRICS,
            "buyout_shop": bp0, "with_buyout": with_buyout, "mp": mp}

"""Self-hosted application component."""

import json
import threading
import time
from datetime import date, timedelta

from . import db
from .config import today_msk

HORIZON = 6


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def base_month() -> date:
    return add_months(today_msk().replace(day=1), -1)


def settings(c, shop: int) -> dict:
    r = c.execute("SELECT value FROM shop_settings WHERE account_id=%s AND key='plan'", (shop,)).fetchone()
    return {"horizon": HORIZON, "fixed_month": 0.0, **(r["value"] if r else {})}


def _facts(c, shop: int, m: date) -> dict[int, dict]:
    """Факт базового месяца по артикулу: выкупы шт, средняя цена до СПП, доля рекламы."""
    end = add_months(m, 1) - timedelta(days=1)
    out = {}
    for r in c.execute("""SELECT nm_id, sum((data->>'buyouts')::numeric) b, sum((data->>'buyouts_sum_before_spp')::numeric) bs,
                                 sum((data->>'ads')::numeric) ads, sum((data->>'orders')::numeric) o
                          FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, m, end)):
        b, bs = float(r["b"] or 0), float(r["bs"] or 0)
        out[r["nm_id"]] = {"qty": b, "price": round(bs / b, 2) if b else None, "ads_share": round(float(r["ads"] or 0) / bs, 4) if bs else 0.0,
                           "orders": float(r["o"] or 0)}
    return out


def _unit_params(c, shop: int) -> dict[int, dict]:
    from .manager import _unit_inputs
    return {nm: {"commission": float(u["kgvp"] or 0) / 100, "logistics": float(u["logistics"] or 0),
                 "cost": float(u["cost"]) if u["cost"] is not None else None, "vendor_code": u["vendor_code"], "title": u["title"],
                 "subject": u["subject"], "photo": u["photo"]} for nm, u in _unit_inputs(c, shop).items()}


def _tax(c, shop: int) -> tuple[str, float]:
    r = c.execute("SELECT regime, rate FROM tax_settings WHERE account_id=%s AND valid_from <= %s ORDER BY valid_from DESC LIMIT 1",
                  (shop, today_msk())).fetchone()
    return (r["regime"], float(r["rate"] or 0)) if r else ("Другая СНО", 0.0)


def calc(qty, price, cost, p: dict, ads_share: float, fixed: float, regime: str, rate: float) -> dict:
    q, pr, cs = float(qty or 0), float(price or 0), float(cost or 0)
    rev = q * pr
    com = rev * p["commission"]
    log = q * p["logistics"]
    cogs = q * cs
    rev_c = rev - com
    md = rev - com - log - cogs
    ads = rev * (ads_share or 0)
    tax = rev_c * rate if regime == "УСН доход" else max(md - ads - fixed, 0) * rate
    profit = md - ads - fixed - tax
    return {"qty": q, "price": pr, "cost": cs, "revenue": rev, "commission": com, "logistics": log, "cogs": cogs, "revenue_company": rev_c,
            "margin": md, "margin_pct": md / rev_c if rev_c else None, "ads": ads, "fixed": fixed, "tax": tax, "profit": profit,
            "profit_pct": profit / rev if rev else None}


METRICS = [("qty", "Количество продаж, шт", "int"), ("price", "Средний чек (до СПП), руб", "money"), ("cost", "Себестоимость, руб/ед", "money"),
           ("revenue", "Выручка ВБ, руб", "money"), ("commission", "Комиссия, руб", "money"), ("logistics", "Логистика, руб", "money"),
           ("cogs", "Себестоимость, руб", "money"), ("revenue_company", "Выручка компании, руб", "money"), ("margin", "Маржинальный доход, руб", "money"),
           ("margin_pct", "Маржинальный доход, %", "share"), ("ads", "Реклама, руб", "money"), ("fixed", "Постоянные расходы, руб", "money"),
           ("tax", "Налог, руб", "money"), ("profit", "Чистая прибыль, руб", "money"), ("profit_pct", "Рентабельность, %", "share")]


def table(c, shop: int) -> dict:
    """План по артикулам × месяцам: вводные (штуки, цена, с/с с источником) + все расчётные показатели; итог по компании по месяцам."""
    st = settings(c, shop)
    base = base_month()
    months = [add_months(base, i) for i in range(1, int(st["horizon"]) + 1)]
    items = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_items WHERE account_id=%s", (shop,))}
    cells = {}
    for r in c.execute("SELECT * FROM plan_cells WHERE account_id=%s AND month = ANY(%s)", (shop, months)):
        cells[(r["nm_id"], r["month"])] = r
    params = _unit_params(c, shop)
    facts = _facts(c, shop, base)
    regime, rate = _tax(c, shop)
    nms = sorted({nm for nm, _ in cells} | {nm for nm, f in facts.items() if f["qty"] > 0},
                 key=lambda n: -(facts.get(n, {}).get("qty") or 0))
    qty_tot = {m: sum(float((cells.get((nm, m)) or {}).get("qty") or 0) for nm in nms) for m in months}
    rows, total = [], {m: {k: 0.0 for k, _, _ in METRICS if k not in ("price", "cost", "margin_pct", "profit_pct")} for m in months}
    for nm in nms:
        p = params.get(nm) or {"commission": 0, "logistics": 0, "cost": None, "vendor_code": str(nm), "title": "", "subject": "", "photo": None}
        it = items.get(nm) or {}
        ads_share = float(it["ads_share"]) if it.get("ads_share") is not None else (facts.get(nm) or {}).get("ads_share", 0.0)
        per = {}
        for m in months:
            cl = cells.get((nm, m)) or {}
            q = float(cl.get("qty") or 0)
            fixed = float(st["fixed_month"]) * q / qty_tot[m] if qty_tot[m] else 0.0
            v = calc(cl.get("qty"), cl.get("price"), cl.get("cost"), p, ads_share, fixed, regime, rate)
            v["src"] = {"qty": cl.get("qty_src"), "price": cl.get("price_src"), "cost": cl.get("cost_src")}
            per[m.isoformat()] = v
            for k, _, _ in METRICS:
                if k not in ("price", "cost", "margin_pct", "profit_pct"):
                    total[m][k] = total[m].get(k, 0.0) + (v[k] or 0)
        f = facts.get(nm) or {}
        rows.append({"nm_id": nm, "vendor_code": p["vendor_code"], "title": p["title"], "subject": p["subject"], "photo": p["photo"],
                     "main_query": it.get("main_query"), "query_src": it.get("query_src"), "method": it.get("method"),
                     "method_used": next((cl.get("method") for (n2, _), cl in cells.items() if n2 == nm and cl.get("method")), None),
                     "commission": p["commission"],
                     "logistics": p["logistics"], "ads_share": ads_share, "ads_share_src": "manual" if it.get("ads_share") is not None else "fact",
                     "base_qty": f.get("qty"), "base_price": f.get("price"), "months": per})
    for m in months:
        t = total[m]
        t["margin_pct"] = t["margin"] / t["revenue_company"] if t.get("revenue_company") else None
        t["profit_pct"] = t["profit"] / t["revenue"] if t.get("revenue") else None
        t["price"] = t["revenue"] / t["qty"] if t.get("qty") else None
    run = c.execute("SELECT id, status, progress, started_at, finished_at FROM plan_runs WHERE account_id=%s ORDER BY id DESC LIMIT 1",
                    (shop,)).fetchone()
    return {"base_month": base.isoformat(), "months": [m.isoformat() for m in months], "metrics": METRICS, "rows": rows,
            "total": {m.isoformat(): v for m, v in total.items()}, "settings": st, "tax": {"regime": regime, "rate": rate}, "run": run}



def _season(c, query: str) -> dict[date, dict]:
    return {r["month"]: r for r in c.execute("SELECT month, frequency, price, wprice FROM plan_season WHERE query=%s", (query,))}


def fetch_season(c, call, query: str) -> int:
    """Помесячная частотность и средний чек выдачи по запросу (Wildbox seasonality.predict, шаг — месяц) за ~2 года."""
    frm = add_months(base_month(), -26).isoformat()
    res = call("get_external_analytics", schema_name="external.seasonality.predict", extra_fields="price,weighted_price",
               params={"wb_search": query, "month_width": True, "date_from": frm}) or {}
    n = 0
    for d in ((res.get("data") or {}).get("dynamic") or []):
        if d.get("predicted"):
            continue
        m = date.fromisoformat(str(d["date"])[:10]).replace(day=1)
        c.execute("""INSERT INTO plan_season(query,month,frequency,price,wprice) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (query,month)
                     DO UPDATE SET frequency=EXCLUDED.frequency, price=EXCLUDED.price, wprice=EXCLUDED.wprice, fetched_at=now()""",
                  (query, m, d.get("frequency"), d.get("price_per_position"), d.get("weighted_price_per_position")))
        n += 1
    c.commit()
    return n


def detect_query(c, call, shop: int, nm: int) -> str | None:
    """Главный запрос артикула: самый частотный, где мы в топ-100 органики; нет — первый с предметом в тексте; иначе самый частотный."""
    kw = call("get_external_analytics", schema_name="external.products.keywords", params={"product_id": nm, "period": 14}, max_rows=10) or {}
    qs = []
    for r in kw.get("rows") or []:
        pos = sorted(x.get("position") for x in r.get("dynamic") or [] if x.get("position"))
        qs.append((r["keyword"]["name"], r["keyword"]["frequency"], pos[len(pos) // 2] if pos else 10 ** 6))
    if not qs:
        return None
    subj = (c.execute("SELECT subject FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone() or {}).get("subject") or ""
    stem = subj[:4].lower()
    rel = [q for q in qs if q[2] <= 100] or [q for q in qs if stem and stem in q[0].lower()] or qs
    return max(rel, key=lambda q: q[1] or 0)[0]


def _coef(season: dict, m: date, base: date, field: str) -> float | None:
    a, b = season.get(add_months(m, -12)), season.get(add_months(base, -12))
    if not a or not b or not a.get(field) or not b.get(field):
        return None
    return float(a[field]) / float(b[field])


def _own_monthly(c, shop: int, frm: date, to: date) -> dict[int, dict[date, float]]:
    """Свои продажи (выкупы) артикула по месяцам — для сезонности «как год назад у самого артикула»."""
    out: dict[int, dict[date, float]] = {}
    for r in c.execute("""SELECT nm_id, date_trunc('month', day)::date m, sum((data->>'buyouts')::numeric) b FROM agg_nm_day
                          WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1, 2""", (shop, frm, to)):
        out.setdefault(r["nm_id"], {})[r["m"]] = float(r["b"] or 0)
    return out


def _own_coef(own: dict[date, float], m: date, base: date) -> float | None:
    a, b = own.get(add_months(m, -12)), own.get(add_months(base, -12))
    return a / b if a and b and b >= 10 else None      


METHODS = ("sales", "query", "manual", "flat")


def _manual_ref(c, shop: int) -> dict[int, dict[date, dict]]:
    out: dict[int, dict[date, dict]] = {}
    for r in c.execute("SELECT nm_id, month, qty_ref, qty_coef, price_ref, price_coef FROM plan_manual_ref WHERE account_id=%s", (shop,)):
        out.setdefault(r["nm_id"], {})[r["month"]] = r
    return out


def _project(method: str, f: dict, own: dict, season: dict, ref: dict, months: list[date], base: date) -> list[tuple]:
    """План (штуки, цена, сезонность сработала?) на месяцы горизонта по способу:
    sales — свои продажи артикула год назад; query — частотность запроса год назад; manual — таблица планирования клиента
    (формула «прошлый месяц × k» → k к нашему прошлому месяцу, число — цель как есть); flat — как база."""
    out = []
    q_prev, p_prev = f["qty"], f["price"]
    for i, m in enumerate(months):
        ok = False
        qty, price = f["qty"], f["price"]
        if method == "sales":
            k = _own_coef(own, m, base)
            if k is not None:
                qty, ok = f["qty"] * k, True
        elif method == "query":
            k = _coef(season, m, base, "frequency")
            if k is not None:
                qty, ok = f["qty"] * k, True
        elif method == "manual":     
            cur = ref.get(m) or {}
            if cur.get("qty_coef") is not None:
                qty, ok = q_prev * float(cur["qty_coef"]), True
            elif cur.get("qty_ref") is not None:
                qty, ok = float(cur["qty_ref"]), True
            else:
                qty = q_prev
            if cur.get("price_coef") is not None and p_prev:
                price = p_prev * float(cur["price_coef"])
            elif cur.get("price_ref") is not None:
                price = float(cur["price_ref"])
            else:
                price = p_prev
        if method in ("sales", "query"):
            kp = _coef(season, m, base, "wprice") or _coef(season, m, base, "price")
            price = f["price"] * kp if kp is not None and f["price"] else f["price"]
        q_prev, p_prev = qty, price
        out.append((round(qty, 1) if qty is not None else None, round(price, 2) if price is not None else None, ok))
    return out


def _auto_method(it: dict, own: dict, ref: dict, months: list[date], base: date) -> str:
    if it.get("method") and not (it["method"] == "manual" and not ref):   
        return it["method"]
    if all(_own_coef(own, m, base) is not None for m in months):
        return "sales"
    return "query"


def fill(c, shop: int, user_id: int | None = None) -> dict:
    """Заполнить авто-ячейки плана выбранной на артикул схемой (ручные ячейки не трогаем)."""
    st = settings(c, shop)
    base = base_month()
    months = [add_months(base, i) for i in range(1, int(st["horizon"]) + 1)]
    facts = _facts(c, shop, base)
    params = _unit_params(c, shop)
    items = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_items WHERE account_id=%s", (shop,))}
    own_all = _own_monthly(c, shop, add_months(base, -13), add_months(months[-1], -11) - timedelta(days=1))
    refs = _manual_ref(c, shop)
    stat = {k: 0 for k in METHODS} | {"flat_fallback": 0}
    for nm, f in facts.items():
        if not f["qty"]:
            continue
        it = items.get(nm) or {}
        season = _season(c, it["main_query"]) if it.get("main_query") else {}
        own, ref = own_all.get(nm) or {}, refs.get(nm) or {}
        method = _auto_method(it, own, ref, months, base)
        cost = (params.get(nm) or {}).get("cost")
        for m, (qty, price, ok) in zip(months, _project(method, f, own, season, ref, months, base)):
            stat[method if ok else "flat_fallback"] += 1
            c.execute("""INSERT INTO plan_cells(account_id,nm_id,month,qty,qty_src,price,price_src,cost,cost_src,updated_by,method)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'auto',%s,%s) ON CONFLICT (account_id,nm_id,month) DO UPDATE SET method=EXCLUDED.method,
                           qty=CASE WHEN plan_cells.qty_src='manual' THEN plan_cells.qty ELSE EXCLUDED.qty END,
                           qty_src=CASE WHEN plan_cells.qty_src='manual' THEN 'manual' ELSE EXCLUDED.qty_src END,
                           price=CASE WHEN plan_cells.price_src='manual' THEN plan_cells.price ELSE EXCLUDED.price END,
                           price_src=CASE WHEN plan_cells.price_src='manual' THEN 'manual' ELSE EXCLUDED.price_src END,
                           cost=CASE WHEN plan_cells.cost_src='manual' THEN plan_cells.cost ELSE EXCLUDED.cost END,
                           cost_src=CASE WHEN plan_cells.cost_src='manual' THEN 'manual' ELSE 'auto' END, updated_at=now()""",
                      (shop, nm, m, qty, "auto" if ok else "flat", price, "auto" if price != f["price"] else "flat", cost, user_id,
                       method if ok else "flat"))
    c.commit()
    return stat


def scenarios(c, shop: int) -> dict:
    """Сравнение схем: итог по компании по месяцам для каждой схемы на всех артикулах (без ручных правок ячеек)."""
    st = settings(c, shop)
    base = base_month()
    months = [add_months(base, i) for i in range(1, int(st["horizon"]) + 1)]
    facts = _facts(c, shop, base)
    params = _unit_params(c, shop)
    items = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_items WHERE account_id=%s", (shop,))}
    own_all = _own_monthly(c, shop, add_months(base, -13), add_months(months[-1], -11) - timedelta(days=1))
    refs = _manual_ref(c, shop)
    regime, rate = _tax(c, shop)
    out = {}
    for method in ("auto",) + METHODS:
        tot = {m: {"qty": 0.0, "revenue": 0.0, "margin": 0.0, "profit": 0.0} for m in months}
        covered = 0
        per_m_qty = {m: 0.0 for m in months}
        plans = {}
        for nm, f in facts.items():
            if not f["qty"]:
                continue
            it = items.get(nm) or {}
            own, ref = own_all.get(nm) or {}, refs.get(nm) or {}
            mth = _auto_method({**it, "method": None if method == "auto" else method}, own, ref, months, base)
            season = _season(c, it["main_query"]) if it.get("main_query") else {}
            pr = _project(mth, f, own, season, ref, months, base)
            covered += any(ok for _, _, ok in pr)
            plans[nm] = pr
            for m, (q, _, _) in zip(months, pr):
                per_m_qty[m] += q or 0
        for nm, pr in plans.items():
            p = params.get(nm) or {"commission": 0, "logistics": 0, "cost": None}
            it = items.get(nm) or {}
            ads = float(it["ads_share"]) if it.get("ads_share") is not None else facts[nm]["ads_share"]
            for m, (q, price, _) in zip(months, pr):
                fixed = float(st["fixed_month"]) * (q or 0) / per_m_qty[m] if per_m_qty[m] else 0
                v = calc(q, price, p.get("cost"), p, ads, fixed, regime, rate)
                for k in tot[m]:
                    tot[m][k] += v[k]
        out[method] = {"covered": covered, "months": {m.isoformat(): v for m, v in tot.items()}}
    return {"months": [m.isoformat() for m in months], "scenarios": out, "articles": sum(1 for f in facts.values() if f["qty"])}


def auto_build(shop: int, user_id: int | None = None, call=None) -> dict:
    """Полное авто-построение: главные запросы (где не заданы вручную) → сезонность по запросам → заполнение. Фоном."""
    from . import market
    with db.connect() as c:
        run = c.execute("INSERT INTO plan_runs(account_id,user_id) VALUES (%s,%s) RETURNING id", (shop, user_id)).fetchone()["id"]
        c.commit()
        prog = {"step": "start"}

        def save(status="running"):
            c.execute("UPDATE plan_runs SET progress=%s, status=%s, finished_at=CASE WHEN %s<>'running' THEN now() END WHERE id=%s",
                      (json.dumps(prog, ensure_ascii=False), status, status, run))
            c.commit()
        try:
            tok = market.shop_token(c, shop)
            if call is None and tok:
                call = lambda tool, **a: market._call(tok, tool, **a)  
            facts = _facts(c, shop, base_month())
            nms = [nm for nm, f in sorted(facts.items(), key=lambda x: -x[1]["qty"]) if f["qty"] > 0]
            if call:
                items = {r["nm_id"]: r for r in c.execute("SELECT * FROM plan_items WHERE account_id=%s", (shop,))}
                todo = [nm for nm in nms if not (items.get(nm) or {}).get("main_query") or (items.get(nm) or {}).get("query_src") == "subject"]
                prog.update(step="запросы", total=len(todo), done=0)
                save()
                fails = 0
                for nm in todo:
                    q, src = None, "auto"
                    for attempt in range(2 if fails < 3 else 0):   
                        try:
                            q = detect_query(c, call, shop, nm)
                            fails = 0
                            break
                        except Exception as e:  
                            prog["last_error"] = str(e)[:160]
                            if attempt == 0:
                                time.sleep(15)       
                            else:
                                fails += 1
                    if not q:            
                        subj = (c.execute("SELECT subject FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone() or {}).get("subject")
                        q, src = (subj.lower(), "subject") if subj else (None, "auto")
                    if q:
                        c.execute("""INSERT INTO plan_items(account_id,nm_id,main_query,query_src) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id)
                                     DO UPDATE SET main_query=EXCLUDED.main_query, query_src=EXCLUDED.query_src, updated_at=now()
                                     WHERE plan_items.query_src<>'manual'""", (shop, nm, q, src))
                        c.commit()
                    prog["done"] += 1
                    save()
                queries = sorted({r["main_query"] for r in c.execute("SELECT main_query FROM plan_items WHERE account_id=%s AND main_query IS NOT NULL", (shop,))})
                need = [q for q in queries if not c.execute("SELECT 1 FROM plan_season WHERE query=%s AND fetched_at > now() - interval '20 days' LIMIT 1", (q,)).fetchone()]
                prog.update(step="сезонность", total=len(need), done=0)
                save()
                for q in need:
                    try:
                        fetch_season(c, call, q)
                    except Exception as e:  
                        c.rollback()
                        prog["last_error"] = str(e)[:160]
                    prog["done"] += 1
                    save()
            else:
                prog["note"] = "Wildbox не подключён — план плоский по базовому месяцу"
            prog.update(step="готово", **fill(c, shop, user_id))
            save("done")
        except Exception as e:  
            c.rollback()
            prog.update(step="ошибка", error=str(e)[:300])
            save("error")
        return prog


def start(shop: int, user_id: int | None) -> None:
    threading.Thread(target=auto_build, args=(shop, user_id), daemon=True).start()



CASH_MANUAL = [("loan_in", "Получение кредитов и займов"), ("loan_out", "Возврат кредитов и займов"), ("invest_in", "Привлечение инвестиций"),
               ("invest_out", "Возврат инвестиций"), ("dividends", "Дивиденды"), ("capex", "Покупка ОС"),
               ("other_in", "Прочие поступления"), ("other_out", "Прочие выплаты")]
CASH_DEFAULTS = {"start_cash": 0.0, "goods_lead": 2, "loan_rate": 0.25, "tax_quarterly": True}


def cashflow(c, shop: int) -> dict:
    """ДДС и баланс по месяцам плана. Как в ССП: товар оплачивается за goods_lead мес. до продажи (себестоимость продаж месяца m+lead),
    налог — поквартально (в 3-й месяц квартала за квартал) или помесячно, НДС = (выручка − оплата товаров) × ставка НДС магазина,
    проценты = кредиты на начало месяца × ставка / 12. Склад в с/с: текущие остатки × с/с + оплаченный товар − с/с проданного."""
    from .manager import stocks
    t = table(c, shop)
    st = {**CASH_DEFAULTS, **t["settings"]}
    months = [date.fromisoformat(m) for m in t["months"]]
    tot = {date.fromisoformat(m): v for m, v in t["total"].items()}
    lead = int(st["goods_lead"])
    last = tot[months[-1]] if months else {}
    cogs_f = lambda m: (tot.get(m) or last).get("cogs", 0.0) if m <= months[-1] + timedelta(days=400) else 0.0  
    vat = c.execute("SELECT vat_rate FROM tax_settings WHERE account_id=%s ORDER BY valid_from DESC LIMIT 1", (shop,)).fetchone()
    vat_rate = float((vat or {}).get("vat_rate") or 0)
    manual = {(r["month"], r["field"]): float(r["value"]) for r in c.execute(
        "SELECT month, field, value FROM plan_cash WHERE account_id=%s AND month = ANY(%s)", (shop, months))}
    params = _unit_params(c, shop)
    stk = stocks(c, shop)
    inv0 = sum((stk.get(nm) or {}).get("total", 0) * (p.get("cost") or 0) for nm, p in params.items())
    cash, loans, invest, inv, capex_acc, retained = float(st["start_cash"]), 0.0, 0.0, inv0, 0.0, 0.0
    rows = {k: [] for k in ("cash_start", "income", "commission", "logistics", "ads", "goods", "fixed", "interest", "tax", "vat", "operating",
                            "loan_in", "loan_out", "invest_in", "invest_out", "dividends", "financing", "capex", "other_in", "other_out", "investing",
                            "total", "cash_end", "inventory", "loans", "invest", "capex_acc", "retained", "assets", "equity", "profit")}
    q_tax = 0.0
    for m in months:
        v = tot[m]
        g = lambda f: manual.get((m, f), 0.0)  
        goods = sum(cogs_f(add_months(m, k)) for k in (lead,)) if lead else v["cogs"]
        interest = loans * float(st["loan_rate"]) / 12
        q_tax += v["tax"]
        if st["tax_quarterly"]:
            tax_pay = q_tax if m.month in (3, 6, 9, 12) else 0.0
            if tax_pay:
                q_tax = 0.0
        else:
            tax_pay, q_tax = v["tax"], 0.0
        vat_pay = max(v["revenue"] - goods, 0) * vat_rate
        op = v["revenue"] - v["commission"] - v["logistics"] - v["ads"] - goods - v["fixed"] - interest - tax_pay - vat_pay
        fin = g("loan_in") - g("loan_out") + g("invest_in") - g("invest_out") - g("dividends")
        invs = -g("capex") + g("other_in") - g("other_out")
        total = op + fin + invs
        profit = v["profit"] - interest
        rows["cash_start"].append(cash)
        cash += total
        loans += g("loan_in") - g("loan_out")
        invest += g("invest_in") - g("invest_out")
        inv += goods - v["cogs"]
        capex_acc += g("capex")
        retained += profit - g("dividends")
        for k, val in (("income", v["revenue"]), ("commission", -v["commission"]), ("logistics", -v["logistics"]), ("ads", -v["ads"]),
                       ("goods", -goods), ("fixed", -v["fixed"]), ("interest", -interest), ("tax", -tax_pay), ("vat", -vat_pay),
                       ("operating", op), ("loan_in", g("loan_in")), ("loan_out", -g("loan_out")), ("invest_in", g("invest_in")),
                       ("invest_out", -g("invest_out")), ("dividends", -g("dividends")), ("financing", fin), ("capex", -g("capex")),
                       ("other_in", g("other_in")), ("other_out", -g("other_out")), ("investing", invs), ("total", total), ("cash_end", cash),
                       ("inventory", inv), ("loans", loans), ("invest", invest), ("capex_acc", capex_acc), ("retained", retained),
                       ("assets", cash + inv + capex_acc), ("equity", cash + inv + capex_acc - loans - invest), ("profit", profit)):
            rows[k].append(round(val, 2))
    return {"months": t["months"], "rows": rows, "settings": {k: st[k] for k in CASH_DEFAULTS}, "inventory_start": round(inv0, 2),
            "vat_rate": vat_rate, "manual_fields": CASH_MANUAL}

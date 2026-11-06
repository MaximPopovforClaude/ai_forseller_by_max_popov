"""Self-hosted application component."""

from collections import defaultdict
from datetime import date

from ..agg import real_week
from . import pnl_real


def compute(c, shop: int, d_from: date, d_to: date) -> dict:
    hist = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()
    tax = hist[-1] if hist else {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    has_ip = any(t["regime"] == pnl_real.IP for t in hist)
    context_from = date(d_from.year, 1, 1) if has_ip else d_from
    A = defaultdict(lambda: defaultdict(float))
    W = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    ends = {}
    for g in real_week.cached(c, shop, context_from, d_to):
        if not g["date_from"] or g["date_to"] < context_from.isoformat() or g["date_from"] > d_to.isoformat():
            continue
        bt = g["bonus_type"] or ""
        nm = g["nm_id"] or 0
        if "Продвижение" in bt or "Медиа" in bt:     
            continue
        if has_ip:
            ends[g["date_from"]] = g["date_to"]
            pnl_real.accumulate(W[g["date_from"]][nm], g)
        if g["date_to"] >= d_from.isoformat():
            pnl_real.accumulate(A[nm], g)
    
    
    ip_tax = defaultdict(float)
    if has_ip:
        from .pnl_nm import _tax_at
        cumulative = defaultdict(float)
        for w, cells in sorted(W.items()):
            wt = _tax_at(hist, ends[w])
            calc = {nm: pnl_real.calc(a, wt) for nm, a in cells.items()}
            if wt["regime"] == pnl_real.IP:
                bases = {nm: r[51] + r[55] + r[56] for nm, r in calc.items()}
                y, prev = w[:4], cumulative[w[:4]]
                cumulative[y] += sum(bases.values())
                income = -(pnl_real.ndfl(max(0.0, cumulative[y])) - pnl_real.ndfl(max(0.0, prev)))
                for nm, allocated in pnl_real.allocate_income_tax(income, bases).items():
                    calc[nm][53] = allocated + calc[nm][55] + calc[nm][56]
            if ends[w] >= d_from.isoformat():
                for nm, r in calc.items():
                    ip_tax[nm] += r[53]
    ads, bonus = {}, {}
    for r in c.execute("""SELECT nm_id, sum((data->>'ads_upd')::numeric) s, sum(coalesce((data->>'ads_bonus')::numeric, 0)) b FROM agg_nm_day
                          WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, d_from, d_to)):
        ads[r["nm_id"]], bonus[r["nm_id"]] = float(r["s"] or 0), float(r["b"] or 0)
    ext = defaultdict(lambda: {"ext": 0.0, "give": 0.0})
    for e in c.execute("SELECT * FROM ext_costs WHERE account_id=%s AND coalesce(d_to, d_from) >= %s AND d_from <= %s", (shop, d_from, d_to)):
        a, z = e["d_from"], e["d_to"] or e["d_from"]
        n = (z - a).days + 1
        inside = sum(1 for i in range(n) if d_from <= date.fromordinal(a.toordinal() + i) <= d_to)
        ext[e["nm_id"]]["give" if e["kind"] == "giveaway" else "ext"] += float(e["cost"] or 0) * inside / n
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, brand, subject FROM nomenclature WHERE account_id=%s", (shop,))}
    grp = {r["nm_id"]: r["group_name"] for r in c.execute("SELECT nm_id, group_name FROM article_groups WHERE account_id=%s", (shop,))}
    rows = []
    for nm in set(A) | {k for k, v in ads.items() if v} | set(ext):
        R = pnl_real.calc(A[nm], tax)
        if has_ip:
            R[53] = ip_tax[nm]
        ad_in, ad_ext, give = ads.get(nm, 0.0), ext[nm]["ext"], ext[nm]["give"]
        profit = R[51] + R[53] - ad_in - ad_ext - give
        cost = R[47]
        n = nom.get(nm) or {}
        rows.append({"nm_id": nm or None, "tag": grp.get(nm), "brand": n.get("brand"), "subject": n.get("subject"),
                     "vendor_code": n.get("vendor_code") if nm else "Без артикула (магазин целиком)",
                     "buyouts": R[10], "buyouts_qty": R[11], "returns": -R[12], "returns_qty": -R[13],
                     "logistics": -R[28], "logistics_pct": pnl_real._d(-R[28], R[4]), "storage": -R[40], "storage_pct": pnl_real._d(-R[40], R[4]),
                     "acceptance": -R[45], "penalty": -R[38], "additional": R[39], "other": -R[41], "acquiring": -R[25],
                     "commission": -R[23], "cost": cost, "give": give, "ads_ext": ad_ext, "ads_in": ad_in,
                     "to_pay": R[14] - ad_in, "tax": -R[53], "profit": profit,
                     "ros": pnl_real._d(profit, R[4]), "roi": pnl_real._d(profit, cost) if cost > 0 else None,
                     
                     "ads_bonus": bonus.get(nm) or None})
    rows.sort(key=lambda r: (r["nm_id"] is None, -(r["buyouts"] or 0)))
    return {"rows": rows}


COLS = [("tag", "Тег (группа)", "text"), ("brand", "Бренд", "text"), ("subject", "Категория", "text"), ("vendor_code", "Артикул", "text"),
        ("nm_id", "SKU", "int"), ("buyouts", "Выкупы, ₽", "money"), ("buyouts_qty", "Выкупы, шт", "int"), ("returns", "Возвраты, ₽", "money"),
        ("returns_qty", "Возвраты, шт", "int"), ("logistics", "Логистика", "money"), ("logistics_pct", "Логистика, % выкупов", "share"),
        ("storage", "Хранение", "money"), ("storage_pct", "Хранение, % выкупов", "share"), ("acceptance", "Приёмка", "money"),
        ("penalty", "Штрафы", "money"), ("additional", "Доплаты маркетплейса", "money"), ("other", "Прочие удержания", "money"),
        ("acquiring", "Эквайринг", "money"), ("commission", "Комиссия", "money"), ("cost", "Себестоимость", "money"),
        ("give", "Раздачи", "money"), ("ads_ext", "Внешняя реклама", "money"), ("ads_in", "Внутренняя реклама", "money"),
        ("to_pay", "Итого к оплате на р/с", "money"), ("tax", "Налог", "money"), ("profit", "Доход до пост. расходов", "money"),
        ("ros", "ROS", "share"), ("roi", "ROI", "share"),
        ("ads_bonus", "Реклама бонусами (Кэшбэк)", "money")]

"""Self-hosted application component."""

from datetime import timedelta

from . import manager, rnp
from .agg import real_week
from .config import today_msk


def _f(x):
    return None if x is None else float(x)


def compute(c, shop: int) -> list[dict]:
    units = manager._unit_inputs(c, shop)
    bp, bp0 = rnp.buyout_pct(c, shop)
    tx = rnp._tax(c, shop, today_msk())
    lo = (today_msk() - timedelta(days=28)).isoformat()
    fin: dict = {}
    for g in real_week.cached(c, shop, lo):      
        if not g["nm_id"] or not g["date_from"] or g["date_from"] < lo:
            continue
        a = fin.setdefault(g["nm_id"], {"log": 0.0, "stor": 0.0, "acc": 0.0, "acq": 0.0, "sold": 0.0})
        doc, op = (g["doc_type"] or "").lower(), (g["oper"] or "").lower()
        a["log"] += g["log_sales"] + g["log_returns"] + g["rebill_log"]
        a["stor"] += g["storage"]; a["acc"] += g["acceptance"]
        if doc == "продажа" and op == "продажа":
            a["sold"] += g["qty"]; a["acq"] += g["acquiring"]
        if doc == "возврат" and op == "возврат":
            a["sold"] -= g["qty"]; a["acq"] -= g["acquiring"]
    
    
    for r in c.execute("""SELECT nm_id, sum(coalesce((data->>'storage')::numeric, 0)) st, sum(coalesce((data->>'acceptance_sum')::numeric, 0)) ac
                          FROM agg_nm_day WHERE account_id=%s AND day >= %s GROUP BY 1""", (shop, lo)):
        a = fin.get(r["nm_id"])
        if a is not None:
            if not a["stor"]:
                a["stor"] = float(r["st"] or 0)
            if not a["acc"]:
                a["acc"] = float(r["ac"] or 0)
    vat = {r["nm_id"]: float(r["v"] or 0) / float(r["s"]) for r in c.execute(
        """SELECT nm_id, sum((data->>'vat_orders')::numeric) v, sum((data->>'orders_sum_spp')::numeric) s FROM agg_nm_day
           WHERE account_id=%s AND day > current_date - 30 GROUP BY 1 HAVING sum((data->>'orders_sum_spp')::numeric) > 0""", (shop,))}
    spp_price = {r["nm_id"]: _f(r["fp"]) for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, finished_price fp FROM orders WHERE account_id=%s AND order_dt >= now() - interval '14 days'
           ORDER BY nm_id, order_dt DESC""", (shop,))}
    dims = {r["nm_id"]: r["d"] for r in c.execute("SELECT nm_id, data->'dimensions' d FROM nomenclature WHERE account_id=%s", (shop,))}
    extra = {r["nm_id"]: r for r in c.execute("SELECT * FROM unit_extra WHERE account_id=%s", (shop,))}
    rows = []
    for nm, u in units.items():
        b = bp.get(nm, bp0) or 1.0
        price = _f(u.get("online"))
        p_spp = spp_price.get(nm)
        cost = _f(u.get("cost"))
        ex = extra.get(nm) or {}
        mark, oth = _f(ex.get("marking")) or 0.0, _f(ex.get("extra")) or 0.0
        comm = (_f(u.get("kgvp")) or 0.0) / 100
        fa = fin.get(nm) or {}
        sold = fa.get("sold") or 0
        log_u = fa["log"] / sold if sold > 0 else (_f(u.get("logistics")) / b if u.get("logistics") else None)   
        stor_u = fa["stor"] / sold if sold > 0 else None
        acc_u = fa["acc"] / sold if sold > 0 else None
        acq_u = fa["acq"] / sold if sold > 0 else None
        d = dims.get(nm) or {}
        liters = (float(d.get("length") or 0) * float(d.get("width") or 0) * float(d.get("height") or 0)) / 1000 or None
        row = {"nm_id": nm, "vendor_code": u["vendor_code"], "subject": u["subject"], "photo": u["photo"], "cost": cost, "marking": mark or None,
               "extra": oth or None, "comm_pct": comm, "liters": round(liters, 2) if liters else None, "log_u": log_u, "stor_u": stor_u,
               "acc_u": acc_u, "acq_u": acq_u, "acq_pct": acq_u / p_spp if acq_u and p_spp else None, "bp": b, "price": price,
               "spp": 1 - p_spp / price if p_spp and price else None, "price_spp": p_spp}
        if price and cost is not None:
            k = vat.get(nm, 0.0)
            S = {"orders_sum": price, "orders_sum_spp": p_spp or price, "commission_offer_orders": price * comm, "logistics_orders": log_u or 0,
                 "cost_orders": cost + mark + oth, "ads_upd": 0, "storage": stor_u or 0, "acceptance_sum": acc_u or 0,
                 "vat_orders": (p_spp or price) * k, "vat_deduct_orders": (cost + mark + oth) * k,
                 "acquiring_orders": acq_u or 0}
            gross = price - price * comm - (log_u or 0) - (stor_u or 0) - (acc_u or 0) - (acq_u or 0) - cost - mark - oth
            profit = rnp.profit(S, 1.0, tx)
            row.update({"tax": gross - profit if gross is not None else None, "spend": price - profit, "profit": profit,
                        "margin": profit / price, "roi": profit / (cost + mark + oth) if cost + mark + oth else None,
                        "to_pay": price - price * comm - (log_u or 0) - (stor_u or 0) - (acc_u or 0) - (acq_u or 0)})
        rows.append(row)
    rows.sort(key=lambda r: (r.get("profit") is None, r.get("margin") if r.get("margin") is not None else 9))
    return rows


COLS = [("vendor_code", "Артикул", "text"), ("subject", "Категория", "text"), ("nm_id", "SKU", "int"),
        ("cost", "Закупка, ₽", "money"), ("marking", "Маркировка / фулфилмент, ₽ (двойной клик)", "edit_money"),
        ("extra", "Прочие расходы на шт, ₽ (двойной клик)", "edit_money"), ("comm_pct", "Комиссия WB", "share"), ("liters", "Литраж, л", "num"),
        ("log_u", "Логистика на шт (финотчёт, с возвратами)", "money"), ("stor_u", "Хранение на шт", "money"), ("acc_u", "Приёмка на шт", "money"),
        ("acq_u", "Эквайринг на шт", "money"), ("acq_pct", "Эквайринг, %", "share"), ("bp", "% выкупа (4 нед.)", "share"),
        ("price", "Цена до СПП", "money"), ("spp", "СПП", "share"), ("price_spp", "Цена с СПП", "money"), ("tax", "Налог + НДС на шт (оценка)", "money"),
        ("spend", "Расходы на шт (до ДРР)", "money"), ("profit", "Прибыль на шт (до ДРР)", "money"), ("margin", "Маржа (до ДРР)", "share"),
        ("roi", "ROI (до ДРР)", "share"), ("to_pay", "К оплате на р/с за шт", "money")]

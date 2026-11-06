"""Self-hosted application component."""

from datetime import date, timedelta

from .config import today_msk
from .manager import KINDS, change_label, other_pct, unit_calc


def _f(x):
    return None if x is None else float(x)


def _fees(c, shop: int) -> dict[int, dict]:
    """Комиссия (доля) и логистика (₽ на 1 шт) по начислениям за 28 дней."""
    out: dict[int, dict] = {}
    for r in c.execute(
            """SELECT s.sku, sum(coalesce(t.accruals_for_sale,0)) acc, sum(-coalesce(t.sale_commission,0)) com,
                      sum(CASE WHEN t.type_name='Продажа' THEN -coalesce(t.services_total,0) ELSE 0 END) svc,
                      sum(CASE WHEN t.type_name IN ('Доставка','Эквайринг') THEN -coalesce(t.amount,0) ELSE 0 END) dlv,
                      sum(CASE WHEN t.type_name='Продажа' THEN coalesce(t.qty,0) ELSE 0 END) qty
               FROM oz_transactions t CROSS JOIN LATERAL unnest(t.skus) s(sku)
               WHERE t.account_id=%s AND t.op_day >= %s AND cardinality(t.skus)=1
                 AND t.type_name IN ('Продажа','Доставка','Эквайринг') GROUP BY 1""", (shop, today_msk() - timedelta(days=28))):
        if r["qty"] and r["acc"]:
            out[r["sku"]] = {"commission": float(r["com"]) / float(r["acc"]), "logistics": (float(r["svc"]) + float(r["dlv"])) / float(r["qty"]),
                             "fees_src": "начисления 28 дн."}
    return out


def _tariff(raw: dict | None) -> dict:
    cm = (raw or {}).get("commissions") or {}
    if not cm:
        return {}
    tr = [x for x in (cm.get("fbo_direct_flow_trans_min_amount"), cm.get("fbo_direct_flow_trans_max_amount")) if x is not None]
    lg = (sum(tr) / len(tr) if tr else 0) + float(cm.get("fbo_deliv_to_customer_amount") or 0) + float((raw or {}).get("acquiring") or 0)
    return {"commission": float(cm.get("sales_percent_fbo") or 0) / 100, "logistics": lg, "fees_src": "тарифы Ozon"}


def _unit_inputs(c, shop: int) -> dict[int, dict]:
    rows = c.execute(
        """WITH st AS (SELECT sku, sum(coalesce(available,0)) q FROM oz_stocks WHERE account_id=%(a)s
                       AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%(a)s) GROUP BY 1),
                cp AS (SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%(a)s AND valid_from <= %(t)s
                       ORDER BY nm_id, valid_from DESC)
           SELECT p.sku nm_id, p.offer_id vendor_code, p.name title, t.type_name subject, p.photo, pr.price online, pr.old_price base_price,
                  pr.marketing_price, pr.raw praw, st.q stock, cp.cost
           FROM oz_products p LEFT JOIN oz_prices pr ON pr.account_id=p.account_id AND pr.product_id=p.product_id
           LEFT JOIN oz_types t ON t.type_id=p.type_id LEFT JOIN st ON st.sku=p.sku LEFT JOIN cp ON cp.nm_id=p.sku
           WHERE p.account_id=%(a)s AND p.sku IS NOT NULL AND NOT p.archived""", {"a": shop, "t": today_msk()}).fetchall()
    fees = _fees(c, shop)
    from .exclusions import excluded
    ex = excluded(c, shop)
    out = {}
    for r in rows:
        if r["nm_id"] in ex:
            continue
        fe = fees.get(r["nm_id"]) or _tariff(r["praw"])
        on, base = _f(r["online"]), _f(r["base_price"])
        out[r["nm_id"]] = {**r, "discount": round((1 - on / base) * 100, 2) if on and base and base > on else 0,
                           "logistics": fe.get("logistics"), "kgvp": (fe.get("commission") or 0) * 100 if fe else None,
                           "fees_src": fe.get("fees_src")}
    return out


def price_lab(c, shop: int) -> dict:
    other = other_pct(c, shop)
    drafts = {r["nm_id"]: r for r in c.execute(
        "SELECT d.nm_id, d.price, d.updated_at, u.email FROM price_drafts d LEFT JOIN users u ON u.id=d.user_id WHERE account_id=%s", (shop,))}
    rows = []
    for nm, r in _unit_inputs(c, shop).items():
        d = drafts.get(nm)
        rows.append({"nm_id": nm, "vendor_code": r["vendor_code"], "title": r["title"], "subject": r["subject"], "photo": r["photo"],
                     **unit_calc(r, other, float(d["price"]) if d else None), "price_promo": _f(r["marketing_price"]), "fees_src": r["fees_src"],
                     "draft": float(d["price"]) if d else None, "draft_by": d and d["email"], "draft_at": d and d["updated_at"]})
    rows.sort(key=lambda x: (-(x["stock"] or 0), x["vendor_code"] or ""))
    return {"other_pct": other, "rows": rows, "mp": "ozon"}


def board(c, shop: int, days: int = 14, date_to: date | None = None) -> dict:
    dt = date_to or today_msk()
    df = dt - timedelta(days=days - 1)
    y = today_msk() - timedelta(days=1)
    w0 = y - timedelta(days=6)
    other = other_pct(c, shop)
    units = _unit_inputs(c, shop)
    k7 = {r["sku"]: r for r in c.execute(
        """SELECT sku, sum((m->>'ordered_units')::numeric) orders, sum((m->>'revenue')::numeric) osum,
                  sum((m->>'session_view')::numeric) f_open, sum((m->>'hits_tocart')::numeric) f_cart
           FROM oz_analytics WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1""", (shop, w0, y))}
    ads = {r["sku"]: float(r["s"] or 0) for r in c.execute(
        "SELECT sku, sum(spent) s FROM oz_ad_sku WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1", (shop, w0, y))}
    bsum = {r["sku"]: float(r["s"] or 0) for r in c.execute(
        "SELECT sku, sum(sale_amount) s FROM oz_realization_day WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1", (shop, w0, y))}
    plan = {r["nm_id"]: float(r["qty"]) for r in c.execute(
        "SELECT nm_id, qty FROM nm_plans WHERE account_id=%s AND month=%s", (shop, dt.replace(day=1)))}
    orders: dict = {}
    for r in c.execute("""SELECT sku, order_day d, sum(qty) n FROM oz_postings WHERE account_id=%s AND order_day BETWEEN %s AND %s
                          AND status <> 'cancelled' GROUP BY 1, 2""", (shop, df, dt)):
        orders.setdefault(r["sku"], {})[r["d"].isoformat()] = int(r["n"])
    acts: dict = {}
    for r in c.execute("""SELECT a.id, a.nm_id, a.day, a.kind, a.value, a.note, a.user_id, coalesce(u.name, u.email) who
                          FROM nm_actions a LEFT JOIN users u ON u.id=a.user_id
                          WHERE a.account_id=%s AND a.day BETWEEN %s AND %s ORDER BY a.created_at""", (shop, df, dt)):
        acts.setdefault(r["nm_id"], {}).setdefault(r["day"].isoformat(), []).append(
            {"id": r["id"], "kind": r["kind"], "value": r["value"], "note": r["note"], "who": r["who"], "user_id": r["user_id"]})
    for r in c.execute("""SELECT id, nm_id, (detected_at AT TIME ZONE 'Europe/Moscow')::date d, kind, field, old_value, new_value
                          FROM card_changes WHERE account_id=%s AND (detected_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s
                          ORDER BY detected_at""", (shop, df, dt)):
        acts.setdefault(r["nm_id"], {}).setdefault(r["d"].isoformat(), []).append(
            {"id": f"c{r['id']}", "kind": "auto:" + r["kind"], "value": change_label(r), "auto": True})
    out = []
    for nm, u in units.items():
        k = k7.get(nm) or {}
        avg = float(k.get("orders") or 0) / 7
        stock = _f(u["stock"])
        calc = unit_calc(u, other, None)
        osum, ad, bs = _f(k.get("osum")), ads.get(nm, 0.0), bsum.get(nm)
        fo, fc, fr = _f(k.get("f_open")), _f(k.get("f_cart")), _f(k.get("orders"))
        promo = _f(u["marketing_price"])
        out.append({
            "nm_id": nm, "vendor_code": u["vendor_code"], "title": u["title"], "subject": u["subject"], "photo": u["photo"],
            "stock_wb": stock, "stock_fbs": None, "stock": stock, "price": calc["online"], "price_spp": promo, "margin_pct": calc["margin_online_pct"],
            "rating": None, "orders_avg": round(avg, 2), "stock_days": round(stock / avg, 1) if stock is not None and avg else None,
            "spp": round(1 - promo / calc["online"], 4) if promo and calc["online"] else None, "plan": plan.get(nm),
            "drr_orders": round(ad / osum, 4) if osum else None, "drr_buyouts": round(ad / bs, 4) if bs else None,
            "conv_cart": round(fc / fo, 4) if fo else None, "conv_order": round(fr / fc, 4) if fc else None,
            "orders": orders.get(nm, {}), "actions": acts.get(nm, {}),
        })
    out.sort(key=lambda x: (-(sum(x["orders"].values())), x["vendor_code"] or ""))
    return {"days": [(dt - timedelta(days=i)).isoformat() for i in range(days)], "kinds": KINDS, "rows": out,
            "month": dt.replace(day=1).isoformat(), "mp": "ozon"}

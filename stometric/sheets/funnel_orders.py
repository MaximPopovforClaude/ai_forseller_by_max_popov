"""Dashboard-only order basis, per SKU/day; never rewrite the shared aggregate.

The funnel has no buyer-price total in our stored contract. Estimate it using
the same SKU/day statistics discount. Quantity costs scale by funnel quantity,
commission by funnel seller revenue. Missing inputs remain unknown, not zero.
"""
from bisect import bisect_right
from collections import defaultdict
from math import isfinite

KEYS = ("f_orders", "f_orders_sum", "f_orders_sum_spp", "f_cost_orders",
        "f_commission_offer_orders", "f_logistics_orders", "f_vat_orders", "f_vat_deduct_orders")
SPP_ROW = 121


def number(value):
    if value is None:
        return None
    n = float(value)
    return n if isfinite(n) else None


def ratio(row, amount, base):
    a, b = number(row.get(amount)), number(row.get(base))
    return a / b if a is not None and b is not None and b > 0 else None


def product(amount, unit):
    if amount == 0:
        return 0.0
    return round(float(amount) * float(unit), 2) if amount is not None and unit is not None else None


def cost_history(c, shop, end, nm_ids=None):
    """Small dated manual-cost history; no raw order scans or future cost fallback."""
    out = defaultdict(list)
    flt = " AND nm_id=ANY(%s)" if nm_ids else ""
    for r in c.execute("SELECT nm_id, valid_from, cost FROM cost_price WHERE account_id=%s AND valid_from<=%s"
                       + flt + " ORDER BY nm_id, valid_from", (shop, end) + ((list(nm_ids),) if nm_ids else ())):
        out[r['nm_id']].append((r['valid_from'], number(r['cost'])))
    return out


def project(row, costs, *, vat_enabled):
    out = dict(row)
    qty, revenue = number(row.get('f_orders')), number(row.get('f_orders_sum'))
    if qty is not None and qty < 0:
        qty = None
    if revenue is not None and revenue < 0:
        revenue = None
    if qty == 0 and revenue not in (0, None):
        qty = revenue = None
    out.update(f_orders=qty, f_orders_sum=revenue)
    discount = ratio(row, 'orders_sum_spp', 'orders_sum')
    if discount is not None and not 0 <= discount <= 1:
        discount = None
    out['f_orders_sum_spp'] = product(revenue, discount)
    history = costs.get(row.get('nm_id'), [])
    i = bisect_right(history, row['day'], key=lambda item: item[0]) - 1
    unit_cost = history[i][1] if i >= 0 else ratio(row, 'cost_orders', 'orders')
    out['f_cost_orders'] = product(qty, unit_cost)
    out['f_commission_offer_orders'] = product(revenue, ratio(row, 'commission_offer_orders', 'orders_sum'))
    log_unit = number(row.get('logistics_avg_orders'))
    if log_unit is None:
        log_unit = ratio(row, 'logistics_orders', 'orders')
    out['f_logistics_orders'] = product(qty, log_unit)
    vat = ratio(row, 'vat_orders', 'orders_sum_spp') if vat_enabled else 0.0
    cost_vat = ratio(row, 'vat_deduct_orders', 'cost_orders') if vat_enabled else 0.0
    out['f_vat_orders'] = 0.0 if not vat_enabled else product(out['f_orders_sum_spp'], vat)
    out['f_vat_deduct_orders'] = 0.0 if not vat_enabled else product(out['f_cost_orders'], cost_vat)
    return out


def sum_strict(rows, periods):
    """Delegate compensated sums, but invalidate incomplete funnel totals."""
    from .dash5 import _period_sums
    missing = {col: set() for col in periods}

    def checked():
        for row in rows:
            absent = {key for key in KEYS if row.get(key) is None}
            for col, (start, end) in periods.items():
                if start <= row['day'] <= end:
                    missing[col].update(absent)
            yield row

    totals = _period_sums(checked(), periods)
    for col, total in totals.items():
        for key in KEYS:
            if key not in total or key in missing[col]:
                total[key] = None
    return totals

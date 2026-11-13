"""WB demand from the sales funnel. Never replace financial order facts.

Coverage means explicit valid per-item days, NOT presumed zeroes for missing
rows. Complete calendar windows are required for speed/trend/XYZ. Conversions
use a shared cohort of days with all three funnel metrics present.
"""
from datetime import timedelta
from math import isfinite

from .config import today_msk

NOTE = ("Спрос и конверсии — по воронке WB, финансовые показатели — по своим источникам. "
        "Сегодня исключено. Пропуски воронки не считаются нулями: скорость и XYZ "
        "доступны только при наличии всех дней периода. Частичные суммы отмечены покрытием. "
        "WB может дополнять данные задним числом.")


def number(value):
    if value is None or isinstance(value, (bool, str)):
        return None
    try:
        value = float(value)
        return value if isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def window(start, end):
    end = min(end, today_msk() - timedelta(days=1))
    return start, end, max(0, (end - start).days + 1)


def finish(row, start, end, days):
    row = dict(row or {})
    covered = int(row.get('covered_days') or 0)
    conversions = int(row.get('conversion_days') or 0)
    money_days = int(row.get('money_days') or 0)
    count = number(row.get('orders')) if covered else None
    op, cart, conv_orders = (number(row.get(k)) if conversions else None for k in ('views', 'cart', 'conv_orders'))
    complete = bool(days and covered == days)
    return {**row, 'from': start, 'to': end, 'expected_days': days, 'covered_days': covered,
            'conversion_days': conversions, 'money_days': money_days, 'source': 'wb_funnel',
            'complete': complete, 'orders': count,
            'orders_sum': number(row.get('orders_sum')) if money_days else None,
            'orders_day': count / days if complete else None,
            'views': op, 'cart': cart,
            'conv_cart': cart / op if op else None,
            'conv_order': conv_orders / cart if cart else None}


def summary(c, shop, start, end, nms=None):
    start, end, days = window(start, end)
    if not days or nms == []:
        return {}
    
    fields = ','.join(f"CASE WHEN jsonb_typeof(data->'{key}')='number' THEN (data->>'{key}')::numeric END {alias}"
                      for key, alias in [('f_orders','z'),('f_orders_sum','s'),('f_open','o'),('f_cart','k')])
    valid = "z>=0 AND z<'Infinity'::numeric"
    conversion = valid + " AND o>=0 AND o<'Infinity'::numeric AND k>=0 AND k<'Infinity'::numeric"
    money = valid + " AND s>=0 AND s<'Infinity'::numeric"
    rows = c.execute(f"""SELECT nm_id,
       sum(z) FILTER(WHERE {valid}) orders,
       sum(z*z) FILTER(WHERE {valid}) squares,
       count(*) FILTER(WHERE {valid}) covered_days,
       sum(s) FILTER(WHERE {money}) orders_sum,
       count(*) FILTER(WHERE {money}) money_days,
       sum(o) FILTER(WHERE {conversion}) views,
       sum(k) FILTER(WHERE {conversion}) cart,
       sum(z) FILTER(WHERE {conversion}) conv_orders,
       count(*) FILTER(WHERE {conversion}) conversion_days
       FROM (SELECT nm_id,{fields} FROM agg_nm_day
             WHERE account_id=%s AND day BETWEEN %s AND %s
               AND (%s::bigint[] IS NULL OR nm_id=ANY(%s::bigint[]))) q
       GROUP BY nm_id""", (shop,start,end,nms,nms))
    return {r['nm_id']: finish(r,start,end,days) for r in rows}


def empty(start, end):
    return finish({}, *window(start,end))


def records(records, start, end):
    """Same calculation for callers already holding the per-day aggregate."""
    start,end,days = window(start,end)
    r = dict(orders=0, squares=0, covered_days=0, orders_sum=0, money_days=0,
             views=0, cart=0, conv_orders=0, conversion_days=0)
    for day, data in records.items():
        if not start <= day <= end:
            continue
        z,s,o,k = (number(data.get(key)) for key in ('f_orders','f_orders_sum','f_open','f_cart'))
        if z is not None:
            r['orders'] += z; r['squares'] += z*z; r['covered_days'] += 1
            if s is not None:
                r['orders_sum'] += s; r['money_days'] += 1
            if o is not None and k is not None:
                r['views'] += o; r['cart'] += k; r['conv_orders'] += z; r['conversion_days'] += 1
    return finish(r,start,end,days)


def rounded(value, digits=0):
    return round(value,digits) if value is not None else None


def daily(c, shop, start, end, nms=None):
    start, end, days = window(start,end)
    if not days or nms == []:
        return {}
    out = {}
    for r in c.execute("""SELECT nm_id,day,data->'f_orders' orders FROM agg_nm_day
       WHERE account_id=%s AND day BETWEEN %s AND %s
         AND (%s::bigint[] IS NULL OR nm_id=ANY(%s::bigint[]))""", (shop,start,end,nms,nms)):
        value = number(r['orders'])
        if value is not None:
            out.setdefault(r['nm_id'],{})[r['day'].isoformat()] = value
    return out

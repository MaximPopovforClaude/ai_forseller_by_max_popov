"""Observed WB advertising, by campaign payment model, for entry-point screens.

Never interpret missing keyword statistics as zero. The non-search remainder
is an estimate matched by campaign, SKU and day, not a measured placement.
Campaign payment types are the last saved settings, never inferred from views.
"""
from datetime import date
from math import isfinite

FIELDS = ('views', 'clicks', 'carts', 'orders')
PAYMENTS = ('cpm', 'cpc', 'unknown')
NOTE = ('Учитывается только сохранённая статистика рекламы; отсутствие строк не доказывает отсутствие рекламы. '
        'В рекламных строках показаны клики WB, а не только переходы в карточку. '
        'Корзины и заказы учитывают рекламную атрибуцию, включая ассоциированные конверсии. '
        'Вне поиска — оценка: вся реклама минус поисковые кластеры для одной кампании, товара и дня. '
        'Органика — расчётная разница разных источников, не измеренный органический трафик. '
        'Тип CPM/CPC взят из последних сохранённых настроек кампании. '
        'Звёздочка * — сумма только доступных значений, не полный итог; у органики — оценка по неполной рекламе. '
        'Проценты по неполным данным не рассчитываются. '
        'Прочерк — нет значений, сопоставимого остатка или недоступные показы CPC. '
        'Доли рекламных кликов от переходов не рассчитываются.')


                                                                              
                                                                              
MODELS_SQL = """        SELECT (data->>'advertId')::bigint aid,
            CASE WHEN count(*)=count(data#>>'{info,settings,payment_type}')
                 AND count(DISTINCT lower(data#>>'{info,settings,payment_type}'))=1
                 THEN min(lower(data#>>'{info,settings,payment_type}')) END AS payment,
            CASE WHEN count(*)=count(data#>>'{info,bid_type}')
                 AND count(DISTINCT lower(data#>>'{info,bid_type}'))=1
                 THEN min(lower(data#>>'{info,bid_type}')) END AS bid_type
        FROM raw_rows WHERE account_id=%(a)s AND source='adverts' GROUP BY 1"""


def number(v):
    if v is None or isinstance(v, bool): return None
    try: n = float(v)
    except (TypeError, ValueError, OverflowError): return None
    return n if isfinite(n) and n >= 0 else None


def ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def metrics(values):
    v = {f: number(values.get(f)) for f in FIELDS}
    partial = set(values.get('partial', ()))
    ratios = {'ctr': ('clicks', 'views'), 'conv_cart': ('carts', 'clicks'),
              'conv_order': ('orders', 'carts'), 'cr_cart': ('carts', 'clicks'),
              'cr_order': ('orders', 'carts'), 'cro': ('orders', 'clicks'),
              'crf': ('orders', 'views'), 'crfl': ('carts', 'views')}
    return {**v, **{key: None if partial.intersection(pair) else ratio(v[pair[0]], v[pair[1]])
                   for key, pair in ratios.items()}, 'share': None, 'partial': sorted(partial)}


def difference(total, part):
    out = {}
    for f in FIELDS:
        a, b = number(total.get(f)), number(part.get(f))
        out[f] = a-b if a is not None and b is not None and a >= b else None
    out['partial'] = sorted(set(total.get('partial', ())) | set(part.get('partial', ())))
    return out


def available_sum(rows, incomplete=False):
    """Keep observed values; mark gaps instead of erasing other campaigns/days."""
    rows = list(rows)
    out, partial = {}, []
    for field in FIELDS:
        values = [number(r.get(field)) for r in rows]
        known = [v for v in values if v is not None]
        out[field] = sum(known) if known else None
        if incomplete or any(v is None for v in values) or any(field in r.get('partial', ()) for r in rows):
            partial.append(field)
    return {**out, 'partial': partial}


def _sums(expressions, names=FIELDS, partials=None):
    out = []
    for i, (f, e) in enumerate(zip(names, expressions)):
        valid = f"({e})>=0 AND ({e})<'Infinity'::numeric"
        out.append(f'sum({e}) FILTER (WHERE {valid}) AS {f}')
        missing = f'count(*)<>count({e}) FILTER (WHERE {valid})'
        if partials is not None:
            missing += f' OR bool_or({partials[i]})'
        out.append(f'({missing}) AS {f}_partial')
    return ', '.join(out)


class Advertising:
    def __init__(self, totals, search, payments):
        self.days = {}
        for key in totals.keys() | search.keys():
            day, aid, nm = key
            model = payments.get(aid, 'unknown')
            if model not in PAYMENTS: model = 'unknown'
            full = {**{f: number(totals.get(key, {}).get(f)) for f in FIELDS}, 'partial': totals.get(key, {}).get('partial', [])}
            query = {**{f: number(search.get(key, {}).get(f)) for f in FIELDS}, 'partial': search.get(key, {}).get('partial', [])}
                                                                                 
                                                                                 
            remaining = difference(full, query)
            for field in remaining['partial']:
                remaining[field] = None                                                        
            self.days.setdefault(day, []).append((model, full, query, remaining))

    def period(self, days):
        days = {date.fromisoformat(d) if isinstance(d, str) else d for d in days}
        rows = [r for d in days for r in self.days.get(d, [])]
        missing_day = any(d not in self.days for d in days)
        result = {'unknown_payment': any(r[0] == 'unknown' for r in rows)}
        for index, label in enumerate(('total', 'search', 'rest'), 1):
            components = []
            for model in PAYMENTS:
                part = [dict(r[index]) for r in rows if r[0] == model]
                if model == 'cpc':
                    for r in part: r['views'] = None
                result[f'{label}_{model}'] = metrics(available_sum(part, missing_day))
                components.extend(part)
                                                                                  
                                                                            
            values = available_sum([r[1] for r in rows] if label == 'total' else components, missing_day)
            if label != 'total' and any(r[0] == 'cpc' for r in rows):
                values['views'] = None                                                 
            result[label] = metrics(values)
        return result


def load(c, shop, nms, exclusions, lo, hi):
    p = {'a': shop, 'lo': lo, 'hi': hi, 'nms': nms, 'ex': list(exclusions)}
    flt = "nm_id NOT IN (SELECT unnest(%(ex)s::bigint[])) AND (%(nms)s::bigint[] IS NULL OR nm_id=ANY(%(nms)s::bigint[]))"
    full = _sums([f"(nm->>'{f}')::numeric" for f in ('views', 'clicks', 'atbs', 'orders')])
                                                                               
                                                                             
    columns = []
    for field in FIELDS:
        valid = f'NOT f.{field}_partial AND NOT q.{field}_partial AND f.{field}>=q.{field}'
        columns.extend([f'f.{field} AS total_{field}', f'q.{field} AS search_{field}',
                        f'CASE WHEN {valid} THEN f.{field}-q.{field} END AS rest_{field}',
                        f'coalesce(f.{field}_partial,true) AS total_{field}_partial',
                        f'coalesce(q.{field}_partial,true) AS search_{field}_partial',
                        f'NOT coalesce(({valid}),false) AS rest_{field}_partial'])
    names = [prefix+'_'+field for prefix in ('total', 'search', 'rest') for field in FIELDS]
    query = """SELECT * FROM (WITH full_stats AS (
        SELECT row_date AS day,(data->>'advertId')::bigint aid,(nm->>'nmId')::bigint nm_id, """+full+"""
        FROM raw_rows
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app
        CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%(a)s AND source='ad_stats' AND row_date BETWEEN %(lo)s AND %(hi)s
        AND """+flt.replace('nm_id', "(nm->>'nmId')::bigint")+""" GROUP BY 1,2,3
    ), search_stats AS (
        SELECT day,advert_id aid,nm_id, """+_sums(['views', 'clicks', 'atbs', 'orders'])+"""
        FROM wb_ad_kw_daily WHERE account_id=%(a)s AND day BETWEEN %(lo)s AND %(hi)s AND """+flt+""" GROUP BY 1,2,3
    ), models AS (
"""+MODELS_SQL+"""
    ), matched AS (
        SELECT coalesce(f.day,q.day) AS day,
            CASE WHEN m.payment IN ('cpm','cpc') THEN m.payment ELSE 'unknown' END AS payment,
            """+', '.join(columns)+"""
        FROM full_stats f FULL JOIN search_stats q USING(day,aid,nm_id)
        LEFT JOIN models m ON m.aid=coalesce(f.aid,q.aid)
    ) SELECT day,payment,"""+_sums(names, names, [name+'_partial' for name in names])+""" FROM matched GROUP BY day,payment) AS entry_ad_groups"""
    reader = Advertising({}, {}, {})
    for r in c.execute(query, p):
        day = date.fromisoformat(r['day']) if isinstance(r['day'], str) else r['day']
        parts = [{**{field: number(r[prefix+'_'+field]) for field in FIELDS},
                  'partial': [field for field in FIELDS if r[prefix+'_'+field+'_partial']]}
                 for prefix in ('total', 'search', 'rest')]
        reader.days.setdefault(day, []).append((r['payment'], *parts))
    return reader

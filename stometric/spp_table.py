"""SPP from matched seller/buyer order prices, Moscow timestamps (WB statistics)."""
from datetime import timedelta


def table(c, shop, f, *, hourly=False):
    start, end = f['date_from'], f['date_to']
    if start > end or (end - start).days > 366:
        return {'columns': [], 'rows': [], 'empty': 'Выберите период не длиннее 367 дней.'}
    data = c.execute("""SELECT coalesce(n.subject, o.data->>'subject', 'Без предмета') subject,
            o.order_dt::date AS day, extract(hour FROM o.order_dt)::int AS hour,
            count(*) orders,
            bool_and(o.price_with_disc > 0 AND o.finished_price >= 0
                     AND o.price_with_disc IS NOT NULL AND o.finished_price IS NOT NULL) complete,
            sum(o.price_with_disc) seller, sum(o.finished_price) buyer
        FROM orders o LEFT JOIN nomenclature n ON n.account_id=o.account_id AND n.nm_id=o.nm_id
        WHERE o.account_id=%s AND o.order_dt >= %s AND o.order_dt < %s
          AND (%s::bigint[] IS NULL OR o.nm_id=ANY(%s))
        GROUP BY 1,2,3 ORDER BY 2 DESC,1,3""",
        (shop, start, end + timedelta(days=1), f.get('nm_ids'), f.get('nm_ids'))).fetchall()
    dates = [end - timedelta(days=i) for i in range((end-start).days+1)]
    periods = [f'{i:02d}:00' for i in range(24)] if hourly else [d.isoformat() for d in dates]
    cols = [{'field': 'subject', 'title': 'Предмет', 'type': 'text'}]
    if hourly:
        cols.append({'field': 'day', 'title': 'Дата, МСК', 'type': 'date'})
    cols += [{'field': 'orders', 'title': 'Заказов', 'type': 'int'},
             {'field': 'spp', 'title': 'СПП за период, %', 'type': 'share'}]
    cols += [{'field': f'p{i}', 'title': key if hourly else dates[i].strftime('%d.%m.%Y'), 'type': 'share'}
             for i, key in enumerate(periods)]
    groups = {}
    for d in data:
        day = str(d['day'])[:10]
        rowkey = (d['subject'], day if hourly else '')
        g = groups.setdefault(rowkey, {'subject': d['subject'], 'day': day, 'orders': 0, 'cells': {}})
        g['orders'] += int(d['orders'])
        slot = f'{d["hour"]:02d}:00' if hourly else day
        for key in (slot, 'total'):
            v = g['cells'].setdefault(key, [0, 0, True])
            v[0] += d['seller'] or 0
            v[1] += d['buyer'] or 0
            v[2] = v[2] and bool(d['complete'])
    def ratio(v):
        return float(1 - v[1]/v[0]) if v and v[2] and v[0] > 0 else None
    rows = [{**{k:v for k,v in g.items() if k != 'cells'}, 'spp': ratio(g['cells']['total']),
             **{f'p{i}': ratio(g['cells'].get(key)) for i,key in enumerate(periods)}} for g in groups.values()]
    return {'columns': cols, 'rows': rows,
            'note': 'СПП по заказам статистики WB: 1 − сумма цен покупателя / сумма цен продавца. '
                    'Время — МСК. Дни и часы без заказов или полных цен — прочерк. '
                    'Это скидка в оформленных заказах, не история витринной цены. Сегодня неполный день.',
            'empty': 'Нет заказов с выбранными фильтрами.'}

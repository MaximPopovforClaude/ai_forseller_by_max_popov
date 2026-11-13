"""Five compact 30-day charts for the action board, using RNP's calculations."""
from datetime import timedelta
from . import rnp
from .config import today_msk
from .materialize import ensure_cost_ready, NotReady
from . import wb_demand

KEYS = ('orders', 'buyouts', 'price_spp', 'ads', 'profit')


def values(rows, days, bp, tax, covered=None, funnel=False):
    out = {k: [] for k in KEYS}
    for day in days:
        if covered is not None and not (covered[0] <= day <= covered[1]):
            for k in KEYS:
                out[k].append(None)
            continue
        s = rows.get(day) or {}
        v = rnp._vals(s, bp, tax)
        o = float(s.get('orders') or 0)
        v['price_spp'] = round(float(s['orders_sum_spp']) / o, 2) if o and s.get('orders_sum_spp') is not None else None
        if funnel:
            v['orders'] = wb_demand.number(s.get('f_orders')) if day < today_msk() else None
        for k in KEYS:
            out[k].append(v[k])
    return out


def get(c, shop, end=None):
    ensure_cost_ready(c, shop)
    end = min(end or today_msk(), today_msk())
    days = [end - timedelta(days=29-i) for i in range(30)]
    mp = c.execute('SELECT marketplace FROM accounts WHERE id=%s', (shop,)).fetchone()['marketplace']
    tax = rnp._tax(c, shop, end)
    covered = None
    if mp == 'wb':
        state = c.execute("SELECT covered_from, covered_to FROM agg_state WHERE account_id=%s AND name='nm_day'", (shop,)).fetchone()
        if not state or not state['covered_from'] or not state['covered_to']:
            raise NotReady('Готовых данных для графиков пока нет.')
        covered = (state['covered_from'], state['covered_to'])
        bp, bp0 = rnp.buyout_pct(c, shop)
        
        sel = ', '.join(f"(data->>'{k}')::numeric {k}" for k in rnp.F + ['f_orders'])
        raw = c.execute(f'''SELECT nm_id, day, {sel} FROM agg_nm_day
            WHERE account_id=%s AND day BETWEEN %s AND %s ORDER BY nm_id, day''', (shop, days[0], end))
        out, current, daily = {}, None, {}
        for row in raw:
            nm = row['nm_id']
            if current is not None and current != nm:
                out[current] = values(daily, days, bp.get(current, bp0), tax, covered, funnel=True)
                daily = {}
            current = nm
            daily[row['day']] = row
        if current is not None:
            out[current] = values(daily, days, bp.get(current, bp0), tax, covered, funnel=True)
    elif mp == 'ozon':
        from . import rnp_mp
        src = rnp_mp.source(c, shop, mp, days[0], end)
        out = {nm: values(rows, days, src['bp'].get(nm, src['bp0']), tax) for nm, rows in src['day'].items()}
    else:
        raise NotReady('Графики действий для этой площадки пока недоступны.')
    from .exclusions import excluded
    hidden = excluded(c, shop)
    out = {nm: v for nm, v in out.items() if nm not in hidden}
    return {'days': [d.isoformat() for d in days], 'rows': out,
            'price_label': 'Цена с СПП, ₽' if mp == 'wb' else 'Цена продавца Ozon, ₽',
            'note': 'Заказы и выкупы — шт.; реклама — фактический расход в рублях, прибыль — расчётная по формулам РНП. '
                    'Цена — средняя в заказах дня; без заказов цены нет. Сегодня — неполный день.' +
                    (' Заказы — по воронке WB за полные дни; отсутствие данных — пропуск. Цена и прибыль сохраняют финансовые источники.' if covered else
                     ' Цена Ozon указана до соинвеста: источник РНП не содержит цену покупателя.')}

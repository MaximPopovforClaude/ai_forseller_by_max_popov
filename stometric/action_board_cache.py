"""Prepared action-board data, independent of display/selection switches.

One 60-day base per shop/date; no user/permission fields in shared cache.
Detailed ad metrics stay separate so hidden campaign tables do not inflate
every response. Both datasets use the existing cost guard and invalidation.
"""
from datetime import timedelta

from . import manager, action_charts, action_ads, tabcache
from .config import today_msk

BASE = 'actions_board_data'
CHARTS = 'actions_board_charts'
ADS = 'actions_board_ads'


def params(end):
    return {'end': end.isoformat()}


def base(c, shop, end):
    return manager.board(c, shop, 60, end, ads=True, prices=True)


def window(data, days):
    """Project a cached window without changing shared rows or formulas."""
    visible = data['days'][:days]
    first, last = min(visible), max(visible)
    from datetime import date
    previous = (date.fromisoformat(first)-timedelta(days=1)).isoformat()
    rows = []
    for r in data['rows']:
        row = dict(r)
        for field in ('orders', 'actions', 'ads', 'price_spp_days'):
            if field in r:
                start = previous if field == 'orders' and data.get('mp', 'wb') == 'wb' else first
                row[field] = {d: v for d, v in r[field].items() if start <= d <= last}
        rows.append(row)
    rows.sort(key=lambda r: (-sum(r['orders'].values()), r['vendor_code'] or ''))
    return {**data, 'days': visible, 'rows': rows}


def get(c, shop, days=14, end=None, ad_metrics=False):
    end = end or today_msk()
    result = window(tabcache.get(c, shop, BASE, params(end), lambda cc: base(cc, shop, end)), days)
    if ad_metrics and result.get('mp', 'wb') == 'wb':
        nms = [r['nm_id'] for r in result['rows']]
        p = {**params(end), 'days': days}
        metrics = tabcache.get(c, shop, ADS, p, lambda cc: {
            'metrics': action_ads.read(cc, shop, end-timedelta(days=days-1), end, nms)})
        for row in result['rows']:
            row['ad_metrics'] = metrics['metrics'].get(str(row['nm_id']), metrics['metrics'].get(row['nm_id'], {}))
        if metrics.get('stale'):
            result['stale'] = True
    return result


def charts(c, shop, end=None):
    end = end or today_msk()
    return tabcache.get(c, shop, CHARTS, params(end), lambda cc: action_charts.get(cc, shop, end))


def precompute(c, shop, mp, log=print):
    """Existing morning run: base, charts, default/recent ad-detail windows.
    No marketplace requests, user data writes, new schedules or AI work.
    """
    if mp not in ('wb', 'ozon'):
        return
    import json
    end = today_msk()
    prepared = None
    for key, fn in ((BASE, lambda cc: base(cc, shop, end)),
                    (CHARTS, lambda cc: action_charts.get(cc, shop, end))):
        try:
            result = tabcache.compute_store(c, shop, key, params(end), fn)
            if key == BASE: prepared = result
            log(f'  {key}: готово')
        except Exception as e:
            c.rollback()
            log(f'  {key}: {type(e).__name__}')
    if mp != 'wb' or prepared is None:
        return
    windows = {14}
    try:
        for r in c.execute("""SELECT DISTINCT fkey FROM tab_cache WHERE account_id=%s AND tab=%s
                              AND computed_at >= now()-interval '3 days' LIMIT 24""", (shop, ADS)):
            try:
                p = json.loads(r['fkey'])
                if isinstance(p, dict) and type(p.get('days')) is int and p['days'] in (7,14,21,30,45,60):
                    windows.add(p['days'])
            except (ValueError, TypeError):
                pass
    except Exception as e:
        c.rollback()
        log(f'  {ADS}: окна недоступны ({type(e).__name__})')
    nms = [r['nm_id'] for r in prepared['rows']]
    for days in sorted(windows):
        try:
            tabcache.compute_store(c, shop, ADS, {**params(end), 'days': days},
                lambda cc, days=days: {'metrics': action_ads.read(cc, shop, end-timedelta(days=days-1), end, nms)})
            log(f'  {ADS}[{days}]: готово')
        except Exception as e:
            c.rollback()
            log(f'  {ADS}[{days}]: {type(e).__name__}')

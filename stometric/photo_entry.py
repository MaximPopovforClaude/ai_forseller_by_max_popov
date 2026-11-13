"""Daily entry-report ratios for each observed photo set, scoped to shop/item.

The day of a detected change belongs to the new set, as in photo daily KPIs.
An intraday-only set cannot be measured separately with daily reports. Current
day is excluded. Period reports are not mixed with daily reports or prorated.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import today_msk
from .entry import _m


def _day(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError('Photo timestamps must include a timezone')
    return value.astimezone(ZoneInfo('Europe/Moscow')).date()


def periods(c, shop, nm, snaps, *, today=None):
    today = today or today_msk()
    yesterday = today - timedelta(days=1)
    ordered = sorted(snaps, key=lambda s: s['taken_at'])
    windows = []
    for i, snap in enumerate(ordered):
        start = _day(snap['taken_at'])
        next_day = _day(ordered[i + 1]['taken_at']) if i + 1 < len(ordered) else None
        end = min(yesterday, next_day - timedelta(days=1)) if next_day else yesterday
        windows.append((snap['id'], start, end, next_day == start))
    active = [(a, b) for _, a, b, _ in windows if a <= b]
    daily = {}
    if active:
        
        
        rows = c.execute("""SELECT r.d_from AS day, count(e.nm_id) item_rows,
                    sum(e.views) views, sum(e.clicks) clicks, sum(e.carts) carts, sum(e.orders) orders,
                    bool_and(e.views IS NOT NULL AND e.views >= 0 AND e.clicks IS NOT NULL AND e.clicks >= 0
                             AND e.carts IS NOT NULL AND e.carts >= 0 AND e.orders IS NOT NULL AND e.orders >= 0) complete
                  FROM entry_reports r LEFT JOIN entry_rows e ON e.report_id=r.id AND e.nm_id=%s
                  WHERE r.account_id=%s AND r.d_from=r.d_to AND r.d_from BETWEEN %s AND %s
                    AND EXISTS (SELECT 1 FROM entry_rows any_row WHERE any_row.report_id=r.id)
                  GROUP BY r.id,r.d_from ORDER BY r.d_from""",
                         (nm, shop, min(a for a, _ in active), max(b for _, b in active)))
        daily = {r['day']: r for r in rows}
    out = {}
    for sid, start, end, intraday in windows:
        days = max(0, (end - start).days + 1)
        report_days = [d for d in daily if start <= d <= end]
        covered = [d for d in report_days if daily[d]['item_rows'] and daily[d]['complete']]
        missing = [start + timedelta(days=i) for i in range(days) if start + timedelta(days=i) not in covered]
        sums = [sum(float(daily[d][f]) for d in covered) for f in ('views', 'clicks', 'carts', 'orders')]
        values = _m(*sums) if covered else {k: None for k in ('views', 'clicks', 'carts', 'orders', 'ctr', 'conv_cart', 'conv_order')}
        out[sid] = {**values, 'from': start, 'to': end if days else None,
                    'expected_days': days, 'report_days': len(report_days), 'covered_days': len(covered),
                    'missing_days': missing, 'coverage': len(covered) / days if days else 0,
                    'status': 'intraday' if intraday else 'pending' if not days else
                              'empty' if not covered else 'complete' if len(covered) == days else 'partial'}
    return out

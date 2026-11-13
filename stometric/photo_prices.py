"""Time-weighted paired storefront prices during each observed photo set.

Prices are assumed unchanged between recorded changes. No backfill before the
first price observation and no extrapolation after the last successful check.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError('Photo price timestamps must include a timezone')
    return value


def _price(value):
    try:
        value = Decimal(str(value))
        return value if value.is_finite() and value > 0 else None
    except (InvalidOperation, ValueError):
        return None


def average(rows, start, end, checked_until):
    """Half-open interval; the two averages use exactly the same covered time."""
    start, end = _time(start), _time(end)
    result = {'from': start, 'to': end, 'before_spp': None, 'after_spp': None, 'coverage': 0.0}
    if end <= start or checked_until is None:
        return result
    limit = min(end, _time(checked_until))
    points = sorted(rows, key=lambda r: _time(r['at']))
    seller_sum = buyer_sum = covered = Decimal(0)
    for i, row in enumerate(points):
        left = max(start, _time(row['at']))
        right = min(limit, _time(points[i + 1]['at']) if i + 1 < len(points) else limit)
        before, after = _price(row.get('seller_price')), _price(row.get('price'))
        if right <= left or before is None or after is None:
            continue
        seconds = Decimal(str((right - left).total_seconds()))
        covered += seconds
        seller_sum += before * seconds
        buyer_sum += after * seconds
    if covered:
        result.update(before_spp=float((seller_sum / covered).quantize(Decimal('.01'))),
                      after_spp=float((buyer_sum / covered).quantize(Decimal('.01'))),
                      coverage=float(covered / Decimal(str((end - start).total_seconds()))))
    return result


def periods(c, shop, nm, snaps, now=None):
    """Only this shop's prices; photo timestamps are shared marketplace facts."""
    if not snaps:
        return {}
    now = now or datetime.now(timezone.utc)
    ordered = sorted(snaps, key=lambda s: (_time(s['taken_at']), s['id']))
    first = _time(ordered[0]['taken_at'])
    rows = c.execute("""(SELECT at, price, seller_price FROM wb_showcase_hist
                         WHERE account_id=%(shop)s AND nm_id=%(nm)s AND at < %(first)s
                         ORDER BY at DESC LIMIT 1)
                       UNION ALL
                       (SELECT at, price, seller_price FROM wb_showcase_hist
                         WHERE account_id=%(shop)s AND nm_id=%(nm)s AND at >= %(first)s AND at <= %(now)s)
                       ORDER BY at""", {'shop': shop, 'nm': nm, 'first': first, 'now': now}).fetchall()
    current = c.execute("""SELECT checked_at, price, seller_price FROM wb_showcase
                           WHERE account_id=%s AND nm_id=%s""", (shop, nm)).fetchone()
    checked_until = max((_time(r['at']) for r in rows), default=None)
    if current and _time(current['checked_at']) <= now:
        checked_until = max(checked_until or _time(current['checked_at']), _time(current['checked_at']))
        
        
        rows = [r for r in rows if _time(r['at']) != _time(current['checked_at'])]
        rows.append({'at': current['checked_at'], 'price': current['price'], 'seller_price': current['seller_price']})
    return {snap['id']: average(rows, snap['taken_at'],
                               min(now, _time(ordered[i + 1]['taken_at'])) if i + 1 < len(ordered) else now,
                               checked_until)
            for i, snap in enumerate(ordered)}

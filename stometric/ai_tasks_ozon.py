"""Read-only Ozon evidence for task completion and existing Version2 outcomes.

Missing evidence is unknown, never proof that a task was not performed.
"""
from datetime import date, datetime, timedelta, timezone
from math import isfinite

from .config import today_msk

STOCK_FRESH = timedelta(hours=4)
CAMPAIGN_FRESH = timedelta(hours=12)
NONE = (None, None, None)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def _spec(t):
    check = t.get('check_spec') or {}
    return check, check.get('nm_ids') or t.get('nm_ids') or []


def can_auto_check(t):
    check, skus = _spec(t)
    kind = check.get('kind')
    if kind == 'ad_status':
        return bool(check.get('advert_id')) and check.get('direction') in ('pause', 'down', 'start', 'up')
    if not skus:
        return False
    return kind in ('price', 'photo', 'stock') or (kind == 'content' and check.get('field') in ('title', 'vendorCode'))


def _changes(c, shop, since, kind, skus, advert=None):
    return c.execute("""SELECT kind, field, nm_id, old_value, new_value, detected_at
        FROM card_changes WHERE account_id=%s AND source='ozon' AND kind=%s
        AND detected_at > %s AND (nm_id=ANY(%s) OR (%s::bigint IS NOT NULL AND field='ad:' || %s::text))
        ORDER BY detected_at""", (shop, kind, since, skus or [0], advert, advert)).fetchall()


def _stock(c, shop, skus, at):
    snap = c.execute("SELECT max(snap_at) snap FROM oz_stocks WHERE account_id=%s AND snap_at<=%s", (shop, at)).fetchone()
    if not snap or not snap['snap'] or at - snap['snap'] > STOCK_FRESH:
        return None
    rows = c.execute("""SELECT sku, sum(available) quantity FROM oz_stocks
        WHERE account_id=%s AND snap_at=%s AND sku=ANY(%s) GROUP BY sku""", (shop, snap['snap'], skus)).fetchall()
    quantities = {r['sku']: _number(r['quantity']) for r in rows}
    if any(quantities.get(s) is None for s in skus):
        return None
    return sum(quantities[s] for s in skus), snap['snap']


def auto_status(c, shop, t):
    if not can_auto_check(t):
        return NONE
    check, skus = _spec(t)
    kind, direction = check['kind'], check.get('direction') or 'any'
    now = datetime.now(timezone.utc)
    
    since = t['created_at']
    if kind == 'stock':
        before, after = _stock(c, shop, skus, since), _stock(c, shop, skus, now)
        if before is None or after is None or after[1] <= since or after[0] <= before[0]:
            return NONE
        need = _number(check.get('target')) or 0
        full = need <= 0 or after[0] - before[0] >= need * .8  
        return ('done' if full else 'partial'), f'остаток FBO {before[0]:g} → {after[0]:g} шт', after[1]
    advert = check.get('advert_id') if kind == 'ad_status' else None
    changes = _changes(c, shop, since, kind, skus, advert)
    if kind == 'ad_status':
        field = f'ad:{advert}'
        campaign = c.execute("SELECT state, updated_at FROM oz_ad_campaigns WHERE account_id=%s AND campaign_id=%s", (shop, advert)).fetchone()
        if not campaign or not campaign['updated_at'] or now - campaign['updated_at'] > CAMPAIGN_FRESH:
            return NONE
        pause = direction in ('pause', 'down')
        expected = 'CAMPAIGN_STATE_STOPPED' if pause else 'CAMPAIGN_STATE_RUNNING'
        if campaign['state'] != expected:
            return NONE
        events = [r for r in changes if r['field'] == field]
        for r in reversed(events):
            old, new = r['old_value'] or {}, r['new_value'] or {}
            valid = (old.get('status') == 'активна' and new.get('status') == 'остановлена') if pause else (
                old.get('status') in ('остановлена', 'неактивна') and new.get('status') == 'активна')
            if not valid or campaign['updated_at'] < r['detected_at']:
                continue
            if pause and (now - r['detected_at'] < timedelta(days=1) or any(
                e['detected_at'] > r['detected_at'] and (e['new_value'] or {}).get('status') == 'активна' for e in events)):
                continue
            return 'done', f'кампания {advert}: ' + ('остановка подтверждена в течение суток' if pause else 'запуск подтверждён'), r['detected_at']
        return NONE
    field = 'price' if kind == 'price' else 'photos' if kind == 'photo' else check['field']
    latest = {r['nm_id']: r for r in changes if r['field'] == field and r['nm_id'] in skus}
    hit = []
    for sku, r in latest.items():
        if r['old_value'] is None or r['old_value'] == r['new_value']:
            continue
        if kind == 'price':
            old, new = _number((r['old_value'] or {}).get('final')), _number((r['new_value'] or {}).get('final'))
            if old is None or new is None or new <= 0 or old <= 0:
                continue
            if direction == 'down' and new >= old or direction == 'up' and new <= old:
                continue
            target = _number(check.get('target'))
            if target and abs(new - target) / abs(target) > .03:
                continue
        hit.append(r)
    if not hit:
        return NONE
    full = len(hit) == len(set(skus))
    return ('done' if full else 'partial'), {'price': 'цена продавца изменена', 'photo': 'фото изменены', 'content': 'поле карточки изменено'}[kind] + f' ({len(hit)} SKU)', max(r['detected_at'] for r in hit)


def _covered(c, shop, skus, days):
    
    
    analytics = c.execute("""SELECT DISTINCT day,sku FROM oz_analytics WHERE account_id=%s
        AND day=ANY(%s) AND sku=ANY(%s) AND m ? 'ordered_units' AND m ? 'revenue'
        AND m->>'ordered_units' IS NOT NULL AND m->>'revenue' IS NOT NULL""", (shop, days, skus)).fetchall()
    if {(r['day'], r['sku']) for r in analytics} != {(d, s) for d in days for s in skus}:
        return False
    accruals = c.execute("SELECT DISTINCT op_day AS day FROM oz_transactions WHERE account_id=%s AND op_day=ANY(%s)", (shop, days)).fetchall()
    return {r['day'] for r in accruals} == set(days)


def _ads_covered(c, shop, skus, days):
    state = c.execute("""SELECT last_ok_at,last_error FROM collector_state
        WHERE account_id=%s AND collector='oz_ad_campaigns'""", (shop,)).fetchone()
    now = datetime.now(timezone.utc)
    if not state or state['last_error'] or not state['last_ok_at'] or now - state['last_ok_at'] > CAMPAIGN_FRESH:
        return False
    campaigns = c.execute("SELECT campaign_id,skus FROM oz_ad_campaigns WHERE account_id=%s", (shop,)).fetchall()
    
    relevant = [r for r in campaigns if not r['skus'] or set(r['skus']) & set(skus)]
    if not relevant:
        return True
    ids = [r['campaign_id'] for r in relevant]
    daily = c.execute("""SELECT campaign_id,day FROM oz_ad_daily WHERE account_id=%s
        AND campaign_id=ANY(%s) AND day=ANY(%s) AND spent IS NOT NULL""", (shop, ids, days)).fetchall()
    full = {(r['campaign_id'], r['day']) for r in daily}
    sku_rows = c.execute("""SELECT campaign_id,day,sku FROM oz_ad_sku WHERE account_id=%s
        AND campaign_id=ANY(%s) AND day=ANY(%s) AND sku=ANY(%s) AND spent IS NOT NULL""", (shop, ids, days, skus)).fetchall()
    by_sku = {(r['campaign_id'], r['day'], r['sku']) for r in sku_rows}
    for campaign in relevant:
        selected = set(campaign['skus'] or []) & set(skus)
        for day in days:
            if (campaign['campaign_id'], day) in full:
                continue
            if not selected or not all((campaign['campaign_id'], day, sku) in by_sku for sku in selected):
                return False
    return True


def _settings_known(c, shop, skus, start):
    tax = c.execute("""SELECT valid_from FROM tax_settings WHERE account_id=%s
        AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1""", (shop, start)).fetchone()
    if not tax:
        return False
    costs = c.execute("""SELECT DISTINCT ON (nm_id) nm_id,cost FROM cost_price
        WHERE account_id=%s AND nm_id=ANY(%s) AND valid_from<=%s
        ORDER BY nm_id,valid_from DESC""", (shop, skus, start)).fetchall()
    known = {r['nm_id']: _number(r['cost']) for r in costs}
    return all(known.get(sku) is not None and isfinite(known[sku]) and known[sku] >= 0 for sku in skus)


def outcome(c, shop: int, nms: list[int], d0: date):
    y = today_msk() - timedelta(days=1)
    n_after = min(3, (y - d0).days)
    skus = sorted(set(nms))
    if n_after < 1 or not skus:
        return None
    periods = [('before', d0 - timedelta(days=3), d0 - timedelta(days=1)), ('after', d0 + timedelta(days=1), d0 + timedelta(days=n_after))]
    days = [a + timedelta(days=i) for _, a, b in periods for i in range((b - a).days + 1)]
    if not _covered(c, shop, skus, days) or not _ads_covered(c, shop, skus, days) or not _settings_known(c, shop, skus, periods[0][1]):
        return None
    from .sheets.ozv2 import compute
    data = compute(c, shop, 'day', periods[0][1], periods[-1][2], skus=skus, per=periods)
    res = {}
    for (tag, a, b), totals in zip(periods, data['cols']):
        count = (b - a).days + 1
        res[tag] = {'days': count, 'orders': round(totals['ordered'] / count, 1), 'sum': round(totals['ordered_sum'] / count),
                    'ads': round((totals['ad.spent'] + totals['ozz.spent']) / count), 'profit': round(totals['profit'] / count)}
    res.update(delta_profit_week=round((res['after']['profit'] - res['before']['profit']) * 7), final=n_after == 3,
               sources={'orders': 'oz_analytics', 'profit': 'ozv2.compute', 'ads': 'oz_ad_sku; fallback oz_ad_daily allocated by campaign SKU count',
                        'realization': data.get('sources', {}).get('realization'), 'ads_by_sku': data.get('sources', {}).get('ads_by_sku')},
               note='Наблюдаемое изменение средних за день; не доказанный эффект задачи. Начисления могут поступать с задержкой, итог подлежит пересчёту. При пробелах источников итог не рассчитывается.')
    return res

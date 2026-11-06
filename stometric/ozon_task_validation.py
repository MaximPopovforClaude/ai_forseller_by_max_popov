"""Keep model-proposed identifiers within the Ozon shop before saving tasks."""
from copy import deepcopy
import math


def _ids(values):
    if not isinstance(values, list):
        return None
    if any(isinstance(x, bool) or not str(x).isdigit() or int(x) <= 0 for x in values):
        return None
    return list(dict.fromkeys(int(x) for x in values))


def validate(c, shop, data):
    from .ai_tasks_ozon import can_auto_check
    skus = {r['sku'] for r in c.execute('SELECT sku FROM oz_products WHERE account_id=%s AND sku IS NOT NULL', (shop,))}
    campaigns = {r['campaign_id']: set(r['skus'] or []) for r in c.execute(
        'SELECT campaign_id, skus FROM oz_ad_campaigns WHERE account_id=%s', (shop,))}
    valid, dropped = [], []
    for source in data.get('tasks', []):
        if not isinstance(source, dict):
            continue
        t = deepcopy(source)
        ids = _ids(t.get('nm_ids') or [])
        check = t.get('check') if isinstance(t.get('check'), dict) else {'kind': 'none'}
        check_ids = _ids(check.get('nm_ids') or ids or [])
        adv = check.get('advert_id')
        if ids is None or check_ids is None or not set(ids + check_ids) <= skus:
            dropped.append({'title': str(t.get('title', ''))[:300], 'reason': 'SKU не принадлежит магазину'})
            continue
        if adv is not None:
            if isinstance(adv, bool) or not str(adv).isdigit() or int(adv) not in campaigns:
                dropped.append({'title': str(t.get('title', ''))[:300], 'reason': 'Кампания не принадлежит магазину'})
                continue
            adv = int(adv)
            
            if not campaigns[adv] or not set(ids + check_ids) <= campaigns[adv]:
                check = {'kind': 'none'}
            else:
                check['advert_id'] = adv
        if check.get('kind') != 'none' and set(check_ids) != set(ids):
            check = {'kind': 'none'}
        target = check.get('target')
        if target is not None:
            try:
                valid_target = not isinstance(target, bool) and math.isfinite(float(target)) and float(target) > 0
            except (TypeError, ValueError):
                valid_target = False
            if not valid_target:
                check = {'kind': 'none'}
        if check.get('kind') == 'price' and check.get('direction', 'any') not in ('up', 'down', 'any'):
            check = {'kind': 'none'}
        check['nm_ids'] = check_ids
        t['nm_ids'] = ids
        t['check'] = check
        if not can_auto_check({'check_spec': check, 'nm_ids': ids}):
            t['check'] = {'kind': 'none', 'nm_ids': ids}
        
        t['effect_week'] = None
        valid.append(t)
    return {**data, 'tasks': valid}, dropped

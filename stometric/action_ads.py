"""Optional WB action-board metrics. Read-only views and compact daily observations.

Budgets are campaign-wide, spend is SKU-specific. No allocation of a shared
budget to products/placements; no backdating current state into past days.
"""
import json
import math
from zoneinfo import ZoneInfo

MSK = ZoneInfo('Europe/Moscow')
GROUPS = ('all', 'cpm', 'cpc', 'search', 'rest', 'prk', 'unknown')


def amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def compact(source, fields, nms):
    """Only this response, never merged old fields labelled as a fresh snapshot."""
    if source == 'campaign':
        required = ('settings.payment_type', 'bid_type', 'settings.placements.search',
                    'settings.placements.recommendations')
        if nms is None or not all(k in fields for k in required):
            return None
        keep = set(required) | {'currency', 'status'}
        selected = {k: v for k, v in fields.items() if k in keep or
                    (k.startswith('nm.') and '.bids.' in k and int(k.split('.')[1]) in nms)}
    elif source in ('budget', 'limits'):
        keep = {'total', 'currency'} if source == 'budget' else {'enabled', 'dailyLimit', 'carryOverEnabled', 'currency'}
        if not keep.issubset(fields):
            return None
        selected = {k: fields[k] for k in keep}
    else:
        return None
    return {'fields': selected, 'nms': nms}


def capture(c, shop, aid, source, fields, nms, at):
    data = compact(source, fields, nms)
    if data is None:
        return
    c.execute('''INSERT INTO wb_ad_daily_state(account_id,advert_id,source,day,data,observed_at)
                 VALUES (%s,%s,%s,%s,%s::jsonb,%s)
                 ON CONFLICT(account_id,advert_id,source,day) DO UPDATE
                 SET data=excluded.data,observed_at=excluded.observed_at
                 WHERE excluded.observed_at > wb_ad_daily_state.observed_at''',
              (shop, aid, source, at.astimezone(MSK).date(), json.dumps(data), at))


def _sum(values):
    """Available subtotal and its coverage, preserving genuine zeros."""
    known = [v for v in values if v is not None]
    return (round(sum(known), 2) if known else None, len(known) != len(values))


def _metrics(items, unknown_members):
    fields = ('spent', 'campaign_spent', 'budget', 'daily_limit')
    out = {'campaigns': len(items), 'partial': [], 'bids': {}}
    for key in fields:
        value, partial = _sum([item.get(key) for item in items])
        out[key] = value
        if partial or unknown_members:
            out['partial'].append(key)
    if any(item.get('search_partial') for item in items) and 'spent' not in out['partial']:
        out['partial'].append('spent')
    for model in ('cpm', 'cpc'):
        relevant = [item for item in items if item['model'] == model]
        bids = [bid for item in relevant for bid in item['bids']]
        out['bids'][model] = round(sum(bids) / len(bids), 2) if bids else None
        if unknown_members or any(item['model'] not in ('cpm', 'cpc') for item in items) or any(not item['bids_complete'] for item in relevant):
            out['partial'].append('bid_' + model)
                                                                                
    spent = out['campaign_spent']
    for basis, denominator in (('limit', out['daily_limit']),
                               ('balance', (spent + out['budget']) if spent is not None and out['budget'] is not None else None)):
        needed = {'campaign_spent', 'daily_limit' if basis == 'limit' else 'budget'}
        out['usage_' + basis] = (round(spent / denominator, 4)
                                 if spent is not None and denominator and not needed.intersection(out['partial']) else None)
    out['classification_estimated'] = any(item.get('classification_estimated') for item in items)
    out['observed_at'] = sorted({item['at'] for item in items if item.get('at')})
    for key in ('budget_at', 'limit_at'):
        out[key] = sorted({item[key] for item in items if item.get(key)})
    return out


def calculate(spend_rows, states, search_rows, nms, classifications=None):
    """Pure calculation over explicit SKU/day/campaign facts. Groups overlap."""
    allowed = set(nms)
    classifications = classifications or {}
    state = {}
    for r in states:
        day = str(r['day'])
        state.setdefault((day, r['advert_id']), {})[r['source']] = r
    facts = {}
    for r in spend_rows:
        if r['nm'] in allowed:
            facts[(str(r['d']), r['id'], r['nm'])] = r
                                                                               
    for (day, aid), sources in state.items():
        campaign = sources.get('campaign', {}).get('data', {})
        for nm in set(campaign.get('nms') or []) & allowed:
            facts.setdefault((day, aid, nm), {})
    kw = {(str(r['day']), r['advert_id'], r['nm_id']): amount(r['spend']) for r in search_rows}
    for key in kw:
        if key[2] in allowed:
            facts.setdefault(key, {})
    buckets = {}
    for (day, aid, nm), r in facts.items():
        sources = state.get((day, aid), {})
        snap = sources.get('campaign', {})
        f = snap.get('data', {}).get('fields', {})
        last = classifications.get(aid, {})
        model = f.get('settings.payment_type')
        bid_type = f.get('bid_type')
        model_estimated = 'settings.payment_type' not in f and last.get('payment') in ('cpm', 'cpc')
        bid_estimated = 'bid_type' not in f and last.get('bid_type') in ('manual', 'unified')
        if model_estimated: model = last['payment']
        if bid_estimated: bid_type = last['bid_type']
        search, rec = f.get('settings.placements.search'), f.get('settings.placements.recommendations')
        money = f.get('currency') == 'RUB'
        bids = []
        bids_complete = money and model in ('cpm', 'cpc')
        for place, enabled in (('search', search), ('recommendations', rec)):
            if enabled is True:
                bid = amount(f.get(f'nm.{nm}.bids.{place}')) if money else None
                if bid is not None: bids.append(bid)
                else: bids_complete = False
                                                                           
        combined = amount(f.get(f'nm.{nm}.bids.combined')) if money else None
        if combined is not None and not bids and (search is True or rec is True):
            bids, bids_complete = [combined], model in ('cpm', 'cpc')
        budget = sources.get('budget', {}).get('data', {}).get('fields', {})
        limits = sources.get('limits', {}).get('data', {}).get('fields', {})
        item = {'spent': amount(r.get('spend')), 'campaign_spent': amount(r.get('campaign_spent')),
                'budget': amount(budget.get('total')) if budget.get('currency') == 'RUB' else None,
                'daily_limit': amount(limits.get('dailyLimit')) if limits.get('currency') == 'RUB' and limits.get('enabled') is True else None,
                'model': model, 'classification_estimated': model_estimated, 'bids': bids, 'bids_complete': bids_complete,
                'budget_at': str(sources['budget']['observed_at']) if sources.get('budget') else None,
                'limit_at': str(sources['limits']['observed_at']) if sources.get('limits') else None,
                'at': str(snap['observed_at']) if snap.get('observed_at') else None}
        by = buckets.setdefault((nm, day), {'groups': {k: [] for k in GROUPS}, 'unknown': set()})
        by['groups']['all'].append(item)
        if model in ('cpm', 'cpc'): by['groups'][model].append(item)
        else:
            by['unknown'].update(('cpm', 'cpc'))
            by['groups']['unknown'].append(item)
        if bid_type == 'manual': by['groups']['prk'].append({**item, 'classification_estimated': bid_estimated})
        elif bid_type != 'unified': by['unknown'].add('prk')
        search_spend = kw.get((day, aid, nm))
                                                                           
                                                                          
        rest_only = search is False and rec is True and search_spend in (None, 0)
        if rest_only:
            remainder, rest_partial = item['spent'], False
        elif search is True and rec is False:
            remainder, rest_partial = (0.0 if item['spent'] is not None else None), False
        else:
            total = item['spent']
            remainder = round(total-search_spend, 2) if total is not None and search_spend is not None and total >= search_spend else None
            rest_partial = True
        rest_item = {**item, 'spent': remainder, 'search_partial': rest_partial}
        if not rest_only:
            rest_item.update(budget=None, daily_limit=None, campaign_spent=None)
        bid = amount(f.get(f'nm.{nm}.bids.recommendations')) if money and rec is True else None
        if bid is None and combined is not None and rec is True: bid = combined
        rest_item.update(bids=[bid] if bid is not None else [], bids_complete=bid is not None)
        by['groups']['rest'].append(rest_item)
        if search is True or search_spend is not None:
            search_item = {**item, 'spent': item['spent'] if search is True and rec is False else search_spend}
            if not (search is True and rec is False):
                                                                                     
                search_item.update(budget=None, daily_limit=None, campaign_spent=None)
                search_item['search_partial'] = True
            bid = amount(f.get(f'nm.{nm}.bids.search')) if money else None
            if bid is None and combined is not None and search is True: bid = combined
            search_item.update(bids=[bid] if bid is not None else [], bids_complete=bid is not None)
            by['groups']['search'].append(search_item)
        elif search is not False:
            by['unknown'].add('search')
    out = {}
    for (nm, day), by in buckets.items():
        groups = {g: _metrics(items, g in by['unknown']) for g, items in by['groups'].items()}
        for placement in ('search', 'rest'):
            items = by['groups'][placement]
            groups[placement]['payment_spend'] = {}
            for model in ('cpm', 'cpc', 'unknown'):
                subset = [item for item in items if (item['model'] if item['model'] in ('cpm', 'cpc') else 'unknown') == model]
                value, partial = _sum([item['spent'] for item in subset])
                groups[placement]['payment_spend'][model] = {
                    'spent': value, 'campaigns': len(subset),
                    'partial': partial or any(item.get('search_partial') for item in subset) or
                               (model != 'unknown' and any(item['model'] not in ('cpm', 'cpc') for item in items)),
                    'classification_estimated': any(item.get('classification_estimated') for item in subset)}
        out.setdefault(nm, {})[day] = groups
    return out


def read(c, shop, df, dt, nms, *, snapshot_history=True):
    if not nms:
        return {}
    states = list(c.execute('''SELECT advert_id,source,day,data,observed_at FROM wb_ad_daily_state
                              WHERE account_id=%s AND day BETWEEN %s AND %s''', (shop, df, dt))) if snapshot_history else []
    spend = c.execute('''SELECT (data->>'advertId')::bigint id,(nm->>'nmId')::bigint nm,row_date d,
                        CASE WHEN count(*)=count(nm->>'sum') THEN sum((nm->>'sum')::numeric) END spend,
                        max((data->>'sum')::numeric) campaign_spent
                        FROM raw_rows,
                        jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app,
                        jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
                        WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s
                          AND (nm->>'nmId')::bigint=ANY(%s) GROUP BY 1,2,3''', (shop, df, dt, list(nms)))
    search = c.execute('''SELECT advert_id,nm_id,day,
                         CASE WHEN count(*)=count(spend) THEN sum(spend) END spend
                         FROM wb_ad_kw_daily WHERE account_id=%s AND day BETWEEN %s AND %s
                           AND nm_id=ANY(%s) GROUP BY 1,2,3''', (shop, df, dt, list(nms)))
    from .entry_ads import MODELS_SQL
    classifications = {r['aid']: r for r in c.execute(MODELS_SQL, {'a': shop})}
    return calculate(spend, states, search, nms, classifications)

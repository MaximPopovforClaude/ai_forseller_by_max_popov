"""Observed WB keyword changes. No marketplace writes or reconstruction of past actions."""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import history

STATES = ('active', 'excluded', 'archived')
TITLES = {'active': 'активен', 'excluded': 'исключён', 'archived': 'в архиве',
          None: 'нет в полученном списке WB'}
KINDS = {'lists': 'ad_kw_status', 'minus': 'ad_kw_minus', 'bids': 'ad_kw_bid'}


def _queries(value):
                                                                   
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(q, str) or not q.strip() for q in value):
        raise ValueError('Invalid WB keyword list')
    return sorted(set(value))                                                  


def _items(response, key):
    if not isinstance(response, dict) or not isinstance(response.get(key), list):
        raise ValueError('Incomplete WB keyword response')
    if any(response.get(k) for k in ('error', 'errors', 'failed', 'next', 'nextPage', 'next_page', 'cursor', 'hasMore', 'has_more')):
        raise ValueError('Partial WB keyword response')
    if any(not isinstance(it, dict) for it in response[key]):
        raise ValueError('Invalid WB keyword item')
    return response[key]


def parse_chunk(pairs, lists, minus, bids):
    """Missing pair/state fields are unknown, not empty. Invalid data fails before writes.

    get-bids returns one complete flat array (no pagination); an explicit [] is
    an empty bid map for requested pairs. get-minus/list require a pair entry.
    """
    wanted = set(pairs)
    out = {pair: {} for pair in wanted}
    for response, source, names in ((lists, 'lists', ('advertId', 'nmId')),
                                    (minus, 'minus', ('advert_id', 'nm_id'))):
        seen = set()
        for it in _items(response, 'items'):
            pair = (it.get(names[0]), it.get(names[1]))
            if pair not in wanted or any(type(x) is not int for x in pair) or pair in seen:
                raise ValueError('Unexpected WB keyword pair')
            seen.add(pair)
            if source == 'lists':
                raw = it.get('normQueries')
                if not isinstance(raw, dict) or set(raw) != set(STATES):
                    continue
                values = {}
                for state in STATES:
                    for query in _queries(raw[state]):
                        if query in values:
                            raise ValueError('Conflicting WB keyword states')
                        values[query] = state
            else:
                if 'norm_queries' not in it:
                    continue
                values = _queries(it['norm_queries'])
            out[pair][source] = values
    values = {pair: {} for pair in wanted}
    for it in _items(bids, 'bids'):
        pair = (it.get('advert_id'), it.get('nm_id'))
        query = it.get('norm_query')
        if pair not in wanted or any(type(x) is not int for x in pair) or not isinstance(query, str) or not query.strip():
            raise ValueError('Invalid WB keyword bid identity')
        raw, currency = it.get('bid_kopecks'), it.get('currency', 'RUB')
        if isinstance(raw, bool) or not isinstance(currency, str) or len(currency) != 3 or not currency.isalpha():
            raise ValueError('Invalid WB keyword bid')
        try:
            amount = Decimal(str(raw)) / 100
            if not amount.is_finite() or amount < 0 or amount >= Decimal('1e8') or amount != amount.quantize(Decimal('.01')):
                raise ValueError('Invalid WB keyword bid amount')
        except InvalidOperation as exc:
            raise ValueError('Invalid WB keyword bid amount') from exc
        value = {'amount': format(amount, '.2f'), 'currency': currency.upper()}
        if query in values[pair] and values[pair][query] != value:
            raise ValueError('Conflicting WB keyword bids')
        values[pair][query] = value
    for pair in wanted:
        out[pair]['bids'] = values[pair]
    return out


def differences(source, old, new):
    """First successful observation, including an empty one, only establishes a baseline."""
    if old is None:
        return []
    if source == 'minus':
        return [(q, q in old, q in new) for q in sorted(set(old) ^ set(new))]
    return [(q, old.get(q), new.get(q)) for q in sorted(set(old) | set(new)) if old.get(q) != new.get(q)]


def save(c, account, advert, nm, parts, observed_at, campaign=None):
    """Journal + independent baseline + current list in one caller transaction.

    The baseline is separate from the UI list updated by service actions, so the
    next collector also detects changes made through this platform. Row locking
    serializes writers; a late older response cannot overwrite a newer snapshot.
    """
    if not parts:
        return 0
    key = (account, advert, nm)
    c.execute('INSERT INTO wb_ad_kw_snapshots(account_id,advert_id,nm_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', key)
    baseline = c.execute('SELECT data FROM wb_ad_kw_snapshots WHERE account_id=%s AND advert_id=%s AND nm_id=%s FOR UPDATE', key).fetchone()['data']
    current = {(r['query'], r['state']): r['bid'] for r in c.execute(
        'SELECT query,state,bid FROM wb_ad_kw_lists WHERE account_id=%s AND advert_id=%s AND nm_id=%s', key)}
    count, accepted = 0, False
    for source, value in parts.items():
        prev = baseline.get(source)
        if prev and datetime.fromisoformat(prev['at']) >= observed_at:
            continue
        for query, before, after in differences(source, prev['value'] if prev else None, value):
            common = {'advert_id': advert, 'campaign': campaign or str(advert), 'query': query,
                      'observation': source}
            history._add(c, account, nm, KINDS[source], f'ad:{advert}',
                         {**common, 'value': before, 'observed_at': prev['at']},
                         {**common, 'value': after, 'observed_at': observed_at.isoformat()}, detected_at=observed_at)
            count += 1
        baseline[source] = {'value': value, 'at': observed_at.isoformat()}
        accepted = True
        if source == 'lists':
            current = {k: v for k, v in current.items() if k[1] not in STATES}
            current.update({(q, state): None for q, state in value.items()})
        elif source == 'minus':
            current = {k: v for k, v in current.items() if k[1] != 'minus'}
            current.update({(q, 'minus'): None for q in value})
    if accepted:
        if 'bids' in baseline:
            current = {k: None for k in current}
                                                                              
                                                                                 
            for q, bid in baseline['bids']['value'].items():
                if bid['currency'] == 'RUB':
                    current[q, 'active'] = Decimal(bid['amount'])
        c.execute('DELETE FROM wb_ad_kw_lists WHERE account_id=%s AND advert_id=%s AND nm_id=%s', key)
        for (query, state), bid in sorted(current.items()):
            c.execute('INSERT INTO wb_ad_kw_lists(account_id,advert_id,nm_id,query,state,bid) VALUES (%s,%s,%s,%s,%s,%s)',
                      (*key, query, state, bid))
        c.execute('UPDATE wb_ad_kw_snapshots SET data=%s WHERE account_id=%s AND advert_id=%s AND nm_id=%s',
                  (json.dumps(baseline, ensure_ascii=False), *key))
    return count


def amount(value):
    if value is None:
        return 'индивидуальная ставка не задана'
    num = format(Decimal(value['amount']), ',.2f').replace(',', ' ').rstrip('0').rstrip('.').replace('.', ',')
    return num + ' ' + ('₽' if value['currency'] == 'RUB' else value['currency'])


def value_label(kind, value):
    if kind == 'ad_kw_bid':
        return amount(value)
    if kind == 'ad_kw_minus':
        return 'в минус-фразах' if value else 'не в минус-фразах'
    return TITLES.get(value, str(value))


def label(row):
    old, new = row['old_value'] or {}, row['new_value'] or {}
    v = new or old
    prefix = f"Ключ «{v.get('query', '')}», РК {v.get('advert_id')}: "
    before, after = old.get('value'), new.get('value')
    if row['kind'] == 'ad_kw_minus':
        return prefix + ('добавлен в минус-фразы — исключён из рекламы' if after else 'убран из минус-фраз — показы разрешены')
    if row['kind'] == 'ad_kw_status' and before is None:
        return prefix + 'появился в списке WB (' + value_label(row['kind'], after) + ')'
    return prefix + ('ставка ' if row['kind'] == 'ad_kw_bid' else 'по списку WB: ') + \
        value_label(row['kind'], before) + ' → ' + value_label(row['kind'], after)

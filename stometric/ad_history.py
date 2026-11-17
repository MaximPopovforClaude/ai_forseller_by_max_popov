"""WB advertising observations and accepted platform commands. No marketplace writes.

A snapshot is evidence of a state change, never evidence of its author or exact
execution time. Command receipts are separate from observations (not two actions).
"""
import json
from datetime import datetime, timezone
from decimal import Decimal

from . import history

KINDS = {'ad_setting', 'ad_product', 'ad_budget', 'ad_limit', 'ad_command', 'ad_config'}
TITLES = {'ad_setting': 'Настройки рекламы', 'ad_product': 'Товары рекламы',
          'ad_budget': 'Остаток бюджета', 'ad_limit': 'Дневной лимит',
          'ad_command': 'Команда через платформу', 'ad_config': 'Настройки блока рекламы'}
FIELDS = {'name': 'Название', 'type': 'Тип кампании', 'bid_type': 'Тип ставки',
          'payment_type': 'Тип оплаты', 'currency': 'Валюта', 'search': 'Поиск',
          'recommendations': 'Рекомендации', 'combined': 'Единая ставка',
          'enabled': 'Включён', 'dailyLimit': 'Дневной лимит', 'carryOverEnabled': 'Перенос остатка лимита',
          'total': 'Остаток бюджета', 'member': 'Участие товара', 'valid': 'Лимит соответствует требованиям WB',
          'requiredLimit': 'Минимальный лимит WB'}
FIELDS.update(loss_min_spend='Минимальный расход для оценки убытка', stock_days_min='Минимум дней запаса',
              kw_min_clicks='Минимум кликов ключа', max_step='Предельный шаг ставки, %', deposit_max='Лимит пополнения',
              create='Предлагать создание кампаний', notify='Уведомления', window_days='Окно анализа, дней',
              loss_weeks='Число убыточных недель', cooldown_h='Пауза между изменениями, часов',
              up_stock_days='Запас для повышения ставки, дней', season_loss_pct='Сезонный убыток, %',
              season_organic_pct='Сезонная органика, %', managers='Менеджеры', seasons='Сезоны',
              norm_queries='Минус-фразы', nms='Товары', status='Статус', budget='Остаток бюджета')
FIELDS.update(restrictions='Ограничения WB', canChangeNms='Можно менять состав товаров')
COMMANDS = {'/adv/v0/start': 'Запустить кампанию', '/adv/v0/pause': 'Остановить кампанию',
            '/adv/v0/auction/nms': 'Изменить состав товаров', '/api/advert/v1/bids': 'Изменить ставки товаров',
            '/adv/v0/auction/placements': 'Изменить места показа', '/adv/v0/normquery/set-minus': 'Изменить минус-фразы',
            '/adv/v0/normquery/bids': 'Изменить ставки ключей', '/adv/v2/seacat/save-ad': 'Создать кампанию',
            '/adv/v1/budget/deposit': 'Пополнить бюджет'}


def _int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError('Invalid advertising identity')
    return value


def number(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('Invalid advertising amount')
    d = Decimal(str(value))
    if not d.is_finite() or d < 0:
        raise ValueError('Invalid advertising amount')
    return float(d)


def flatten(data, prefix=''):
    """Only settings objects, not arbitrary response/session/headers."""
    out = {}
    for key, value in data.items():
        path = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def campaign_fields(data):
    info = data.get('info')
    if not isinstance(info, dict) or info.get('id') != data['advertId']:
        raise ValueError('Missing or mismatched advertising details')
    fields = {k: data[k] for k in ('status', 'type') if data.get(k) is not None}
    fields.update({k: info[k] for k in ('bid_type', 'currency') if k in info})
    for key, value in info.items():
        if key not in ('id', 'status', 'bid_type', 'currency', 'settings', 'nm_settings', 'timestamps'):
            fields.update(flatten({key: value}, 'info'))
    if 'settings' in info:
        if not isinstance(info['settings'], dict):
            raise ValueError('Invalid campaign settings')
        fields.update(flatten(info['settings'], 'settings'))
    nms = None
    if 'nm_settings' in info:
        if not isinstance(info['nm_settings'], list):
            raise ValueError('Incomplete campaign products')
        nms = []
        for item in info['nm_settings']:
            nm = _int(item['nm_id'])
            if nm in nms:
                raise ValueError('Duplicate campaign product')
            nms.append(nm)
            for key, value in item.items():
                if key == 'bids_kopecks':
                    if not isinstance(value, dict):
                        raise ValueError('Invalid campaign bids')
                    for place, bid in value.items():
                        fields[f'nm.{nm}.bids.{place}'] = number(bid) / 100
                elif key not in ('nm_id', 'subject'):                                                 
                    fields.update(flatten({key: value}, f'nm.{nm}.settings'))
    return fields, nms


def require_complete_detail(info):
    """Never replace the operational raw campaign with a partial HTTP 200 body."""
    if not isinstance(info, dict) or not all(k in info for k in ('id', 'status', 'bid_type', 'settings', 'nm_settings')):
        raise ValueError('Incomplete campaign details')
    settings = info['settings']
    if not isinstance(settings, dict) or not all(k in settings for k in ('name', 'payment_type', 'placements')):
        raise ValueError('Incomplete campaign settings')
    if not isinstance(settings['placements'], dict) or not isinstance(info['nm_settings'], list):
        raise ValueError('Incomplete campaign placements/products')
    for item in info['nm_settings']:
        if not isinstance(item, dict) or not isinstance(item.get('bids_kopecks'), dict):
            raise ValueError('Incomplete product bid settings')
    campaign_fields({'advertId': info['id'], 'info': info, 'status': info['status']})


def emit(c, shop, aid, nms, kind, parameter, before, after, at, campaign='', **meta):
    common = {'advert_id': aid, 'campaign': campaign, 'parameter': parameter,
              'evidence': 'observation', **meta}
    for nm in sorted(set(nms)) or [0]:                                                             
        history._add(c, shop, nm, kind, f'ad:{aid}',
                     {**common, 'value': before}, {**common, 'value': after}, detected_at=at)
    return len(set(nms)) or 1


def observe(c, shop, aid, source, fields, nms, at, *, campaign='', initial=None):
    """Caller owns transaction. Lock serializes readers; old responses cannot undo newer ones.

    Missing fields/pairs do not mean deletion. New fields establish a baseline;
    membership removal requires an explicit complete nm_settings list.
    """
    c.execute('INSERT INTO wb_ad_observations(account_id,advert_id,source) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
              (shop, aid, source))
    row = c.execute('SELECT data,observed_at FROM wb_ad_observations WHERE account_id=%s AND advert_id=%s AND source=%s FOR UPDATE',
                    (shop, aid, source)).fetchone()
    previous_at = row['observed_at']
    if isinstance(previous_at, str): previous_at = datetime.fromisoformat(previous_at)
    if previous_at is not None and previous_at >= at:
        return False, 0
    prev = row['data'] or initial or {}
    old = prev.get('fields', {})
    old_nms = prev.get('nms')
    targets = sorted(set(old_nms or []) | set(nms or [])) if source == 'campaign' else list(nms if nms is not None else old_nms or [])
    name = campaign or fields.get('settings.name') or old.get('settings.name') or str(aid)
    count = 0
    for path in sorted(old.keys() & fields.keys()):
        before, after = old[path], fields[path]
        if before == after: continue
        affected = targets
        kind = {'budget': 'ad_budget', 'limits': 'ad_limit'}.get(source, 'ad_setting')
        if path.startswith('nm.'):
            affected = [int(path.split('.')[1])]
            if nms is not None and affected[0] not in nms: continue
        if source == 'campaign' and path == 'status':
            for nm in targets or [0]:
                history._add(c, shop, nm, 'ad_status', f'ad:{aid}',
                             {'campaign': name, 'status': history.AD_STATUS.get(before, before)},
                             {'campaign': name, 'status': history.AD_STATUS.get(after, after)}, detected_at=at)
            count += len(targets) or 1
        elif source == 'campaign' and '.bids.' in path and fields.get('currency', old.get('currency', 'RUB')) == 'RUB':
            place = path.rsplit('.', 1)[-1]
            history._add(c, shop, affected[0], 'ad_bid', f'ad:{aid}',
                         {'campaign': name, place: before}, {'campaign': name, place: after}, detected_at=at)
            count += 1
        else:
            count += emit(c, shop, aid, affected, kind, path, before, after, at, name,
                          currency=fields.get('currency', old.get('currency')), previous_observed_at=str(previous_at) if previous_at else None)
    if source == 'campaign' and nms is not None and old_nms is not None:
        for nm in sorted(set(old_nms) ^ set(nms)):
            count += emit(c, shop, aid, [nm], 'ad_product', 'member', nm in old_nms, nm in nms, at, name)
    merged = {**old, **fields}
    if source == 'campaign' and nms is not None:
                                                                                 
        merged = {k: v for k, v in merged.items() if not k.startswith('nm.') or int(k.split('.')[1]) in nms}
    state = {'fields': merged, 'nms': nms if nms is not None else old_nms}
    c.execute('UPDATE wb_ad_observations SET data=%s,observed_at=%s WHERE account_id=%s AND advert_id=%s AND source=%s',
              (json.dumps(state, ensure_ascii=False), at, shop, aid, source))
    from .action_ads import capture
    capture(c, shop, aid, source, fields, nms, at)
    return True, count


def observe_campaign(c, shop, data, at, previous=None):
    fields, nms = campaign_fields(data)
    initial = None
    if previous and previous.get('info'):
        try:
            prevfields, prevnms = campaign_fields(previous)
            initial = {'fields': prevfields, 'nms': prevnms}
        except (ValueError, KeyError, TypeError):
            pass                                                                       
    return observe(c, shop, data['advertId'], 'campaign', fields, nms, at, initial=initial)


def parse_finance(response, requested, source):
    if (not isinstance(response, dict) or not isinstance(response.get('adverts'), list)
            or any(response.get(k) for k in ('error', 'errors', 'next', 'failed'))):
        raise ValueError('Incomplete advertising finance response')
    out = {}
    keys = ('total', 'currency') if source == 'budget' else ('enabled', 'dailyLimit', 'carryOverEnabled', 'currency')
    for item in response['adverts']:
        aid = _int(item['advertId'])
        if aid not in requested or aid in out: raise ValueError('Unexpected advertising finance identity')
        if not all(k in item for k in keys): raise ValueError('Incomplete advertising finance fields')
        values = {k: item[k] for k in keys}
        if not isinstance(values['currency'], str) or not values['currency'].isalpha() or len(values['currency']) != 3:
            raise ValueError('Invalid advertising currency')
        for key in ('total', 'dailyLimit'):
            if key in values: values[key] = number(values[key])
        for key in ('enabled', 'carryOverEnabled'):
            if key in values and not isinstance(values[key], bool): raise ValueError('Invalid advertising boolean')
                                                                                                 
        if source == 'limits':
            values.update({k: item[k] for k in ('valid', 'requiredLimit') if k in item})
        out[aid] = values
    if set(out) != set(requested): raise ValueError('Missing advertising finance campaigns')
    return out


def command(c, shop, path, body, params, before, result, uid, at, action_id):
    """Projection of a successful allowlisted request, not a second marketplace call.

    Acknowledgement and later observation remain separately labelled evidence.
    No parsing of arbitrary target strings and no response/secret dump.
    """
    body, params = body or {}, params or {}
    groups = []
    if path == '/adv/v2/seacat/save-ad':
        aid = result if type(result) is int and result > 0 else 0
        groups = [(aid, list(body.get('nms') or []), body)]
    elif path in ('/adv/v0/start', '/adv/v0/pause', '/adv/v1/budget/deposit'):
        groups = [(params['id'], [], body or {'status': 9 if path.endswith('/start') else 11})]
    elif path == '/adv/v0/normquery/set-minus':
        groups = [(body['advert_id'], [body['nm_id']], {'norm_queries': body['norm_queries']})]
    else:
        key = 'nms' if path.endswith('/nms') else 'placements' if path.endswith('/placements') else 'bids'
        for item in body.get(key) or []:
            nms = ([item['nm_id']] if 'nm_id' in item else [x['nm_id'] for x in item.get('nm_bids') or []])
            if isinstance(item.get('nms'), dict):
                nms = list(item['nms'].get('add') or []) + list(item['nms'].get('delete') or [])
            groups.append((item['advert_id'], nms, {k: v for k, v in item.items() if k != 'advert_id'}))
    for aid, nms, after in groups:
        row = c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts' AND row_key=%s", (shop, str(aid))).fetchone()
        info = ((row or {}).get('data') or {}).get('info') or {}
        if not nms: nms = [x['nm_id'] for x in info.get('nm_settings') or []]
        emit(c, shop, aid, nms, 'ad_command', path, before, after, at,
             (info.get('settings') or {}).get('name') or body.get('name') or str(aid),
             evidence='accepted_command', actor_id=uid, action_id=action_id, currency=info.get('currency', 'RUB'),
             note='WB принял команду; последующий снимок — отдельное подтверждение состояния, не новое действие')


def setting_label(path):
    parts = path.split('.')
    return ' / '.join(FIELDS.get(x, x) for x in parts if x not in ('settings', 'nm', 'bids', 'info') and not x.isdigit())


def value_label(value, parameter='', currency=None):
    if value is None: return 'неизвестно'
    if type(value) is bool: return 'да' if value else 'нет'
    if isinstance(value, (float, int)):
        text = f'{value:,.2f}'.rstrip('0').rstrip('.').replace(',', ' ').replace('.', ',')
        if parameter in ('total', 'dailyLimit', 'requiredLimit') or '.bids.' in parameter:
            return text + (' ₽' if currency == 'RUB' else ' ' + currency if currency else ' (валюта не указана)')
        return text
    if isinstance(value, dict): return '; '.join(f'{setting_label(k)}: {value_label(v, k, currency)}' for k, v in value.items())
    if isinstance(value, list): return ', '.join(value_label(v, parameter, currency) for v in value)
    return {'manual': 'ручная', 'unified': 'единая', 'cpm': 'за показы', 'cpc': 'за клики'}.get(str(value), str(value))


def label(row):
    old, new = row.get('old_value') or {}, row.get('new_value') or {}
    path, kind = new.get('parameter', ''), row['kind']
    prefix = f'РК {new.get("advert_id", "")}: '
    if kind == 'ad_command':
        details = command_details(path, old.get('value'), new.get('value'), new.get('currency'))
        return prefix + 'WB принял команду «' + COMMANDS.get(path, path) + '»' + (': ' + details if details else '')
    if kind == 'ad_product': return prefix + ('товар добавлен в кампанию' if new.get('value') else 'товар убран из кампании')
    if kind == 'ad_config': prefix = 'Блок рекламы платформы: '
    text = prefix + setting_label(path) + ': ' + value_label(old.get('value'), path, new.get('currency')) + ' → ' + value_label(new.get('value'), path, new.get('currency'))
    if kind == 'ad_budget': text += ' (изменение остатка, не доказательство пополнения или ручного действия)'
    return text


def command_details(path, before, after, currency=None):
    after = after or {}
    currency = currency or 'RUB'                                          
    money = lambda n: value_label(number(n), 'total', currency)
    if path in ('/adv/v0/start', '/adv/v0/pause'): return ''
    if path.endswith('/deposit'):
        return money(after['sum']) + ', источник: ' + {0: 'счёт', 1: 'баланс', 3: 'бонусы'}.get(after.get('type'), str(after.get('type')))
    if path.endswith('/set-minus'):
        old = set((before or {}).get('norm_queries') or [])
        new = set(after.get('norm_queries') or [])
        parts = []
        if new - old: parts.append('исключить: ' + ', '.join(sorted(new - old)))
        if old - new: parts.append('снять исключение: ' + ', '.join(sorted(old - new)))
        return '; '.join(parts) if before and 'norm_queries' in before else value_label(after)
    if 'nm_bids' in after:
        return '; '.join(f"арт. {x['nm_id']}, {FIELDS.get(x['placement'], x['placement'])}: {money(number(x['bid_kopecks']) / 100)}" for x in after['nm_bids'])
    if 'norm_query' in after:
        return f"ключ «{after['norm_query']}»: {money(after['bid'])}"
    if 'placements' in after: return value_label(after['placements'])
    if isinstance(after.get('nms'), dict):
        return '; '.join(('добавить: ' if k == 'add' else 'убрать: ') + ', '.join(map(str, v)) for k, v in after['nms'].items())
    return value_label(after)

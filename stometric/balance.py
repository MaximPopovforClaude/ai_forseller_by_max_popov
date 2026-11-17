"""Company balance: immutable manual snapshots, separate stock valuations, scoped reads.

No live marketplace calls from the page. Unknown quantities/prices are not zero.
The primary total is cost-based, never the sum of the three valuations.
"""
import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from . import auth

MSK = timezone(timedelta(hours=3))
ZERO = Decimal(0)
KINDS = {'stock', 'assets', 'settlement'}
ASSET_KINDS = {'material', 'intangible', 'receivable', 'cash', 'loan', 'interest', 'payable'}
DEBTS = {'loan', 'interest', 'payable'}


def num(value, *, signed=False, optional=False):
    if optional and (value is None or value == ''):
        return None
    try:
        if isinstance(value, bool): raise ValueError()
        d = Decimal(str(value).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
        if not d.is_finite() or abs(d) > Decimal('1000000000000') or (not signed and d < 0):
            raise ValueError()
        if d.as_tuple().exponent < -6: raise ValueError()
        return d
    except (ValueError, InvalidOperation):
        raise ValueError('Нужно конечное число от 0 до 1 трлн, не более 6 знаков после запятой' if not signed
                         else 'Нужно конечное число по модулю до 1 трлн, не более 6 знаков после запятой') from None


def text(value, maximum=200):
    v = str(value or '').strip()
    if not v or len(v) > maximum or any(ord(x) < 32 for x in v):
        raise ValueError(f'Текст должен содержать от 1 до {maximum} символов без управляющих знаков')
    return v


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def validate_payload(kind, payload):
    if kind not in KINDS or not isinstance(payload, dict): raise ValueError('Неверный вид данных')
    rows = payload.get('rows')
    if not isinstance(rows, list) or len(rows) > 20000: raise ValueError('Нужно не более 20 000 строк')
    seen, out = set(), []
    if kind == 'settlement' and len(rows) != 1: raise ValueError('Нужна одна сверка магазина')
    for i, r in enumerate(rows, 1):
        try:
            if not isinstance(r, dict): raise ValueError('Неверная строка')
            if kind == 'settlement':
                                                                                           
                if payload.get('exclusive') is not True:
                    raise ValueError('Подтвердите, что суммы до и после начисления не пересекаются')
                row = {k: num(r.get(k), signed=k in ('unaccrued_net','accrued'), optional=True)
                       for k in ('before_spp','after_spp','unaccrued_net','accrued')}
                if all(v is None for v in row.values()): raise ValueError('Укажите хотя бы одну сумму')
                row['note'] = text(r.get('note'), 500)
            else:
                code = text(r.get('code'), 100)
                if code in seen: raise ValueError('Повтор кода строки')
                seen.add(code)
                row = {'code': code, 'name': text(r.get('name'))}
                if kind == 'stock':
                    row.update(quantity=num(r.get('quantity')), cost=num(r.get('cost')))
                else:
                    if r.get('category') not in ASSET_KINDS: raise ValueError('Неизвестная категория')
                    row.update(category=r['category'], amount=num(r.get('amount')))
                    due = r.get('due')
                    row['due'] = str(date.fromisoformat(str(due))) if due else None
                    row['note'] = str(r.get('note') or '').strip()[:500]
            out.append(row)
        except (ValueError, TypeError) as e:
            raise ValueError(f'Строка {i}: {e}') from None
    return json.loads(canonical({'rows': out, 'includes_fbs': payload.get('includes_fbs') is True,
                                 'exclusive': payload.get('exclusive') is True}))


def scope(c, u, ws, write=False):
    if not u or u.get('_mcp') or u.get('is_active') is False: raise HTTPException(403, 'Нет доступа к балансу')
    member = c.execute('SELECT role,shop_ids FROM memberships WHERE user_id=%s AND workspace_id=%s', (u['id'],ws)).fetchone()
    role = auth.workspace_role(c,u,ws)
    if not role or (write and (not member or member['role'] not in ('owner','admin'))):
        raise HTTPException(403, 'Недостаточно прав')
    shops = [s for s in auth.shops_for(c,u) if s['workspace_id'] == ws and s['marketplace'] in ('wb','ozon')]
                                                                                   
    full = bool(member and member.get('shop_ids') is None)
    return {'shops': shops, 'ids': {s['id'] for s in shops}, 'full': full,
            'write': full and role in ('owner','admin'), 'role': role}


def companies(c, ws, ctx):
    rows = c.execute('''SELECT b.id,b.title,b.version,COALESCE(array_agg(s.shop_id ORDER BY s.shop_id)
        FILTER(WHERE s.shop_id IS NOT NULL),'{}') shops FROM balance_companies b
        LEFT JOIN balance_company_shops s ON s.company_id=b.id WHERE b.workspace_id=%s GROUP BY b.id ORDER BY b.title,b.id''', (ws,)).fetchall()
                                                                                            
    return [r for r in rows if ctx['full'] and set(r['shops']) <= ctx['ids']]


def company(c, u, ws, ident, write=False):
    ctx = scope(c,u,ws,write)
    if write and not ctx['write']: raise HTTPException(403, 'Изменять общие активы может администратор с доступом ко всем магазинам кабинета')
    found = next((r for r in companies(c,ws,ctx) if r['id'] == ident),None)
    if not found: raise HTTPException(404, 'Компания недоступна')
    return ctx,found


def save_company(c,u,ws,title,ids,ident=None,version=None):
    ctx = scope(c,u,ws,True)
    if not ctx['write']: raise HTTPException(403,'Нужен полный доступ к кабинету')
    if not ids or len(ids) != len(set(ids)) or not set(ids) <= ctx['ids']: raise HTTPException(400,'Выберите доступные магазины WB/Ozon')
                                                                              
    c.execute('SELECT pg_advisory_xact_lock(153,%s)',(ws,))
    if ident:
        company(c,u,ws,ident,True)
        hit = c.execute('UPDATE balance_companies SET title=%s,version=version+1,updated_at=now() WHERE id=%s AND version=%s RETURNING id',
                        (text(title),ident,version)).fetchone()
        if not hit: raise HTTPException(409,'Компания уже изменена. Обновите страницу')
    conflict = c.execute('SELECT shop_id FROM balance_company_shops WHERE shop_id=ANY(%s) AND company_id<>%s', (ids,ident or 0)).fetchone()
    if conflict: raise HTTPException(409,'Магазин уже относится к другой компании')
    if not ident:
        ident = c.execute('INSERT INTO balance_companies(workspace_id,title,created_by) VALUES(%s,%s,%s) RETURNING id',
                           (ws,text(title),u['id'])).fetchone()['id']
                                                                               
    c.execute('DELETE FROM balance_company_shops WHERE company_id=%s',(ident,))
    for shop in ids: c.execute('INSERT INTO balance_company_shops(company_id,shop_id) VALUES(%s,%s)',(ident,shop))
    return ident


def save_batch(c,u,ws,ident,kind,label,day,payload,request_key,shop=None,previous_id=None):
    c.execute('SELECT pg_advisory_xact_lock(153,%s)',(ws,))
    _, comp = company(c,u,ws,ident,True)
    if kind == 'settlement':
        if shop not in comp['shops']: raise HTTPException(400,'Выберите магазин компании')
        label = 'Расчёты с площадкой'
    elif shop is not None: raise HTTPException(400,'Общий реестр относится к компании')
    if kind == 'assets': label = 'Активы и обязательства'
    label = text(label,100)
    data = validate_payload(kind,payload)
    digest = hashlib.sha256(canonical([kind,label,str(day),shop,data]).encode()).hexdigest()
    old = c.execute('SELECT id,digest FROM balance_batches WHERE company_id=%s AND request_key=%s',(ident,str(request_key))).fetchone()
    if old:
        if old['digest'] != digest: raise HTTPException(409,'Этот запрос уже сохранён с другими данными')
        return old['id'],False
    previous = c.execute('''SELECT id FROM balance_batches WHERE company_id=%s AND kind=%s AND label=%s
        AND shop_id IS NOT DISTINCT FROM %s AND day<=%s ORDER BY day DESC,id DESC LIMIT 1''',(ident,kind,label,shop,day)).fetchone()
    if (previous['id'] if previous else None) != previous_id:
        raise HTTPException(409,'Этот реестр уже сохранён или изменён. Обновите баланс и откройте действующий снимок')
    row = c.execute('''INSERT INTO balance_batches(company_id,shop_id,kind,label,day,payload,request_key,digest,created_by)
        VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s) RETURNING id''',
        (ident,shop,kind,label,day,canonical(data),str(request_key),digest,u['id'])).fetchone()
    return row['id'],True


def latest_batches(c,ident,day):
    return c.execute('''SELECT DISTINCT ON(kind,label,COALESCE(shop_id,0)) id,kind,label,shop_id,day,payload,created_at
        FROM balance_batches WHERE company_id=%s AND day<=%s
        ORDER BY kind,label,COALESCE(shop_id,0),day DESC,id DESC''',(ident,day)).fetchall()


def stock_value(rows):
    """Independent sums with per-column completeness; zero stock needs no price."""
    out = {k: ZERO for k in ('quantity','cost','seller','buyer')}
    missing = {k: 0 for k in out}
    for r in rows:
        qty = num(r.get('quantity'),signed=True,optional=True)
        if qty is None or qty < 0:
            for k in out: missing[k] += 1
            continue
        out['quantity'] += qty
        for k in ('cost','seller','buyer'):
            if qty == 0: continue
            p = num(r.get(k),signed=True,optional=True)
            if p is None or p < 0: missing[k] += 1
            else: out[k] += qty*p
    return {k:{'known':v, 'total':None if missing[k] else v, 'missing':missing[k]} for k,v in out.items()}


def manual_totals(batches):
    stocks,assets,debts,receivables = ZERO,ZERO,ZERO,ZERO
    ledger_present = False
    for b in batches:
        if b['kind'] == 'stock':
            stocks += sum((num(r['quantity'])*num(r['cost']) for r in b['payload']['rows']),ZERO)
        elif b['kind'] == 'assets':
            ledger_present = True
            for r in b['payload']['rows']:
                if r['category'] in DEBTS: debts += num(r['amount'])
                else: assets += num(r['amount'])
        else:
            for r in b['payload']['rows']:
                for k in ('unaccrued_net','accrued'):
                    d = num(r.get(k),signed=True,optional=True)
                    if d is not None:
                        if d < 0: debts -= d
                        else: receivables += d
    return {'stock':stocks,'other_assets':assets,'debts':debts,'receivables':receivables,'ledger_present':ledger_present}


def report_projection(selected, inventories, comps, company_batches, exclude_fbs):
    """Pure, decimal projection. Common property counted once for complete company selection."""
    selected=set(selected); used=[]; coverage=[];covered_fbs=set();partial_companies=[]
    gap_details={k:[] for k in ('inventory_cost','seller_stock_cost','other_assets','receivables','liabilities','assets','net')}
    def gap(message,keys,**where):
        coverage.append(message)
        affected=set(keys)|{'net'}
        if affected-{'liabilities','net'}:affected.add('assets')
        for key in affected:gap_details[key].append({'message':message,**where})
    bound=set()
    for comp in comps:
        members=set(comp['shops']); hit=members & selected
        if not hit: continue
        bound |= hit
        batches=company_batches.get(comp['id'],[])
        used += [b for b in batches if b['kind']=='settlement' and b['shop_id'] in hit]
        if members <= selected:
            common=[b for b in batches if b['kind']!='settlement']; used+=common
            if not any(b['kind']=='assets' for b in common): gap(f"{comp['title']}: не заполнен реестр активов и обязательств. Внесите остатки вручную или загрузите Excel",['other_assets','liabilities'])
            if not any(b['kind']=='stock' for b in common): gap(f"{comp['title']}: не подтверждён остаток собственного склада. Загрузите полный снимок склада на нужную дату",['seller_stock_cost'])
            if any(b['kind']=='stock' and b['payload'].get('includes_fbs') for b in common): covered_fbs |= members
        else:
            partial_companies.append(comp['title'])
            gap(f"{comp['title']}: выбрана часть магазинов. Общий склад, активы и долги не включены; для полного состава выберите все магазины компании", ['seller_stock_cost','other_assets','liabilities'])
    if selected-bound: gap('Не все магазины привязаны к компании: общие активы и расчёты не подтверждены. Настройте компанию и заполните её реестры', ['seller_stock_cost','other_assets','receivables','liabilities'])
    for shop in selected:
        st=[x for x in used if x['kind']=='settlement' and x['shop_id']==shop]
        if not st or any(r.get(k) is None for x in st for r in x['payload']['rows'] for k in ('unaccrued_net','accrued')):
            gap(f'Магазин {shop}: не подтверждены обе стадии расчётов с площадкой. Заполните сверку: к получению до начисления и начислено, но не выплачено. Автоматическая сверка ещё не подключена', ['receivables','liabilities'],shop_id=shop)
    manual=manual_totals(used); value=ZERO
    alternative={k:ZERO for k in ('seller','buyer')}; missing={k:0 for k in ('cost','seller','buyer')}
    stock_totals={}
    for shop in selected:
        inv=inventories.get(shop)
        if not inv:gap(f'Магазин {shop}: остатки ещё не получены. Чтение не завершилось; точная причина здесь не установлена', ['inventory_cost'],shop_id=shop);continue
        if inv.get('stale'):gap(f'Магазин {shop}: показан предыдущий расчёт запасов, свежий ещё готовится', ['inventory_cost'],shop_id=shop,metric='cost')
        totals={k:{'known':ZERO,'missing':0,'total':None} for k in ('quantity','cost','seller','buyer')}
        complete=True
        for g in inv['groups']:
            if g['kind']=='fbs' and (exclude_fbs or shop in covered_fbs):continue
            if not g['complete']:
                complete=False
                gap(f"Магазин {shop}, {g['title']}: полнота источника не подтверждена", ['inventory_cost'],shop_id=shop,kind=g['kind'],metric='cost')
            if g.get('old'):gap(f"Магазин {shop}, {g['title']}: снимок старше выбранной даты более чем на день", ['inventory_cost'],shop_id=shop,kind=g['kind'],metric='cost')
            if g['values']['cost']['missing']:
                gap(f"Магазин {shop}, {g['title']}: нет себестоимости или количества для части запаса. Раскройте список товаров и причин", ['inventory_cost'],shop_id=shop,kind=g['kind'],metric='cost')
            v=g['values'];value+=Decimal(str(v['cost']['known']))
            for k in totals:
                totals[k]['known']+=Decimal(str(v[k]['known']))
                totals[k]['missing']+=v[k]['missing']
            for k in missing:
                missing[k]+=v[k]['missing']
                if k in alternative:alternative[k]+=Decimal(str(v[k]['known']))
        for v in totals.values():v['total']=v['known'] if complete and not v['missing'] else None
        stock_totals[shop]=totals
    if missing['cost']:coverage.append(f"Нет себестоимости/количества для {missing['cost']} строк запасов")
                                                                                
    if not exclude_fbs and len(selected-covered_fbs)>1:
        gap('FBS нескольких магазинов может пересекаться. Для общего итога исключите FBS и загрузите физический склад один раз', ['inventory_cost'])
    asset=value+manual['stock']+manual['other_assets']+manual['receivables']
    return {'inventory_cost':value,'seller_stock_cost':manual['stock'],'other_assets':manual['other_assets'],
            'receivables':manual['receivables'],'liabilities':manual['debts'],'assets':asset,'net':asset-manual['debts'],
            'alternative':alternative,'missing':missing,'stock_totals':stock_totals,'gaps':list(dict.fromkeys(coverage)),
            'partial_companies':partial_companies,'fbs_replaced':sorted(covered_fbs),'gap_details':gap_details}

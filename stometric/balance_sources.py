"""Read saved stock observations; no external calls, no analytic product exclusions."""
from datetime import datetime,time,timedelta
from decimal import Decimal
from .balance import MSK, stock_value

TITLES = {'fbo':'FBO','fbs':'FBS','to_buyer':'В пути к покупателю','from_buyer':'В пути от покупателя'}


def cache_params(day):
    return {'day':day.isoformat(),'gap_details_version':1}


def row_gaps(row,mp):
    """Explain exactly the rows omitted by stock_value; do not estimate missing money."""
    q=row.get('quantity')
    if q is None or q<0:
        why=('В сохранённом снимке не заполнено количество. Без него нельзя оценить запас.' if q is None else
             'В сохранённом снимке отрицательное количество. Такая строка не включена в оценку запаса.')
        return {k:why for k in ('quantity','cost','seller','buyer')}
    if q==0:return {}
    reasons={}
    for k in ('cost','seller','buyer'):
        value=row.get(k)
        if value is not None and value>=0:continue
        if value is not None:
            reasons[k]='В источнике отрицательная цена или себестоимость. Проверьте значение: эта строка не включена в оценку.'
        elif k=='cost':
            reasons[k]='Нет заполненной себестоимости, действующей на выбранную дату. Укажите её с нужной датой начала действия.'
        elif k=='seller' and row.get('seller_conflict'):
            reasons[k]='В последнем снимке у размеров или вариантов товара разные цены. Единую цену для оценки запаса определить нельзя.'
        elif k=='seller':
            reasons[k]='В сохранённых данных до выбранной даты нет полной цены продавца для товара и его вариантов. Нужен снимок цен с заполненными значениями.'
        elif mp=='ozon':
            reasons[k]='Источник текущей цены покупателя Ozon для оценки запасов ещё не подключён. Цена прежнего заказа её не заменяет.'
        else:
            reasons[k]='До выбранной даты нет сохранённой цены товара на витрине WB с СПП. Нужен снимок витринной цены.'
    return reasons


def stock_run(c,shop,source,table,cutoff):
    complete = c.execute('''SELECT snap_at,row_count FROM balance_stock_runs
        WHERE account_id=%s AND source=%s AND snap_at<%s ORDER BY snap_at DESC LIMIT 1''',(shop,source,cutoff)).fetchone()
    if complete:
                                                                                  
        n = c.execute(f'SELECT count(*) n FROM {table} WHERE account_id=%s AND snap_at=%s',(shop,complete['snap_at'])).fetchone()['n']
        if n == complete['row_count']: return complete['snap_at'],True
    r = c.execute(f'SELECT max(snap_at) at FROM {table} WHERE account_id=%s AND snap_at<%s',(shop,cutoff)).fetchone()
    return r['at'],False


def valuation(c,shop,mp,ids,cutoff,day):
    if not ids: return {}
    costs = {r['nm_id']:r['cost'] for r in c.execute('''SELECT DISTINCT ON(nm_id) nm_id,cost FROM cost_price
        WHERE account_id=%s AND nm_id=ANY(%s) AND valid_from<=%s ORDER BY nm_id,valid_from DESC''',(shop,ids,day))}
    if mp == 'wb':
                                                                         
        price_rows = {r['nm_id']:r for r in c.execute('''WITH latest AS (
            SELECT nm_id,max(snap_at) at FROM prices_snap WHERE account_id=%s AND nm_id=ANY(%s) AND snap_at<%s GROUP BY nm_id)
            SELECT p.nm_id,CASE WHEN count(*)=count(discounted_price) AND min(discounted_price)=max(discounted_price)
                THEN min(discounted_price) ELSE NULL END price,
                min(discounted_price)<>max(discounted_price) AS conflict
            FROM prices_snap p JOIN latest l ON p.nm_id=l.nm_id AND p.snap_at=l.at WHERE p.account_id=%s GROUP BY p.nm_id''',
            (shop,ids,cutoff,shop))}
        buyers = {r['nm_id']:r['price'] for r in c.execute('''SELECT DISTINCT ON(nm_id) nm_id,price FROM (
            SELECT nm_id,price,at FROM wb_showcase_hist WHERE account_id=%s AND nm_id=ANY(%s) AND at<%s
            UNION ALL SELECT nm_id,price,checked_at FROM wb_showcase WHERE account_id=%s AND nm_id=ANY(%s) AND checked_at<%s
            ) q ORDER BY nm_id,at DESC''',(shop,ids,cutoff,shop,ids,cutoff))}
    else:
        price_rows = {r['nm_id']:r for r in c.execute('''SELECT n.sku nm_id,
            CASE WHEN count(*)=count(p.price) AND min(p.price)=max(p.price) THEN min(p.price) ELSE NULL END price,
            min(p.price)<>max(p.price) AS conflict
            FROM oz_products n LEFT JOIN oz_prices p ON p.account_id=n.account_id AND p.product_id=n.product_id AND p.updated_at<%s
            WHERE n.account_id=%s AND n.sku=ANY(%s) GROUP BY n.sku''',(cutoff,shop,ids))}
        buyers = {}                                                                    
    return {nm:{'cost':costs.get(nm),'seller':price_rows.get(nm,{}).get('price'),'buyer':buyers.get(nm),
                'seller_conflict':bool(price_rows.get(nm,{}).get('conflict'))} for nm in ids}


def inventory(c,shop,mp,day):
    cutoff = datetime.combine(day+timedelta(days=1),time(),MSK)
    groups,all_rows = [],[]
    specs = [('stocks_wb','stocks_wb_snap',('fbo','to_buyer','from_buyer')),
             ('stocks_seller','stocks_seller_snap',('fbs',))] if mp == 'wb' else [('oz_stocks','oz_stocks',('fbo',))]
    for source,table,kinds in specs:
        at,complete = stock_run(c,shop,source,table,cutoff)
        raw = []
        if at is not None:
            cols = {'fbo':'quantity','fbs':'quantity','to_buyer':'in_way_to_client','from_buyer':'in_way_from_client'} if mp=='wb' else {'fbo':'available'}
            nm = 'nm_id' if mp=='wb' else 'sku'
            fields = ','.join(f'CASE WHEN count(*)=count({cols[k]}) THEN sum({cols[k]}) ELSE NULL END {k}' for k in kinds)
            raw = c.execute(f'SELECT {nm} nm_id,{fields} FROM {table} WHERE account_id=%s AND snap_at=%s GROUP BY {nm}',(shop,at)).fetchall()
        ids = [r['nm_id'] for r in raw if r['nm_id'] is not None]
        values = valuation(c,shop,mp,ids,cutoff,day)
        names = {}
        if ids:
            q = 'SELECT nm_id,vendor_code code,title name FROM nomenclature WHERE account_id=%s AND nm_id=ANY(%s)' if mp=='wb' else \
                'SELECT sku nm_id,min(offer_id) code,min(name) name FROM oz_products WHERE account_id=%s AND sku=ANY(%s) GROUP BY sku'
            names = {r['nm_id']:r for r in c.execute(q,(shop,ids))}
        for k in kinds:
            rows = [{'nm_id':r['nm_id'],'quantity':r[k],**values.get(r['nm_id'],{}),
                     'code':names.get(r['nm_id'],{}).get('code'), 'name':names.get(r['nm_id'],{}).get('name'), 'kind':k}
                    for r in raw if r[k] != 0]
            val = stock_value(rows)
            for row in rows:row['gaps']=row_gaps(row,mp)
                                                                      
            if at is None:
                for v in val.values(): v.update(total=None,missing=1)
            observed=datetime.fromisoformat(at.replace('Z','+00:00')) if isinstance(at,str) else at
            old=bool(observed and (day-observed.astimezone(MSK).date()).days>1)
            gaps=[]
            if at is None:gaps.append('До выбранной даты нет сохранённого снимка этого запаса. Его размер пока неизвестен, а не равен нулю.')
            elif not complete:gaps.append('Для снимка нет подтверждения, что все строки сохранены полным проходом сборщика. Показана доступная часть; состав недостающих товаров неизвестен.')
            if old:gaps.append('Последний сохранённый снимок старше выбранной даты более чем на день. Изменения запасов после него ещё не учтены.')
            groups.append({'kind':k,'title':TITLES[k],'at':at,'complete':complete,'values':val,'old':old,'gaps':gaps})
            all_rows += rows
    if mp == 'ozon':
        for k in ('fbs','to_buyer','from_buyer'):
            groups.append({'kind':k,'title':TITLES[k],'at':None,'complete':False,
                           'gaps':['Для этого вида запаса Ozon отдельный источник пока не подключён. Количество и стоимость неизвестны.'],
                           'values':{x:{'known':0,'total':None,'missing':1} for x in ('quantity','cost','seller','buyer')}})
    return {'groups':groups,'rows':all_rows,'note':
            'Показаны последние сохранённые остатки и цены не позднее выбранной даты, а не одновременная инвентаризация. Пропуски не равны нулю. Исключение товара из анализа не исключает его запас.' +
            (' FBO Ozon: доступный запас неархивного каталога; резерв, брак и транзит не подменяются общей суммой «прочее». FBS/транзит и текущая цена покупателя требуют отдельного источника.' if mp=='ozon' else '')}

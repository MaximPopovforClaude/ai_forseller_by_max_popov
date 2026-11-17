"""Compact, read-only WB Jam history. Numeric pack format is version 1, never reorder FIELDS.

Snapshot = completed union of three top selectors, NOT all search traffic.
Missing phrases and missing snapshots are unknown, never zero.
"""
import json
import math
from datetime import date, datetime, timedelta, timezone

from . import jam, jam_scope
from .config import today_msk

FIELDS = ('frequency','weekFrequency','avgPosition','medianPosition','openCard','addToCart','orders','visibility')
HISTORY_DAYS = 30
BATCH = 50
NOTE = ('WB отдаёт топ запросов по кликам, корзинам и заказам, а не весь поиск. '
        'Нет запроса в топе — не ноль. Суммы относятся только к наблюдаемым дням; '
        'среднюю позицию за период не восстанавливаем усреднением дней. Сегодня исключено. '
        'Показы, прибыль и потенциал рассчитываются по формулам обычного Джема; потенциал — сценарий, не прогноз.')


def number(value):
    if isinstance(value, dict): value = value.get('current')
    if value is None or isinstance(value, bool): return None
    try: n = float(value)
    except (ValueError, TypeError): return None
    return n if math.isfinite(n) and n >= 0 else None


def parse(response, nms):
    if not isinstance(response, dict) or not isinstance(response.get('data'), dict) or not isinstance(response['data'].get('items'), list):
        raise ValueError('jam_daily_invalid_response')
    out = {nm:{} for nm in nms}
    for item in response['data']['items']:
        if not isinstance(item, dict) or type(item.get('nmId')) is not int or item['nmId'] not in out:
            raise ValueError('jam_daily_invalid_identity')
        q = item.get('text')
        if not isinstance(q, str) or not q.strip() or len(q.encode('utf-8')) > 2000:
            raise ValueError('jam_daily_invalid_query')
        q = q.strip()
        vals = [number(item.get(k)) for k in FIELDS]
        if q in out[item['nmId']] and out[item['nmId']][q] != vals:
            raise ValueError('jam_daily_duplicate_query')
        out[item['nmId']][q] = vals
    return out


def fetch(c, wb, shop, nms, day, *, progress=None):
    """Bounded 3 requests (one extra only for the documented 100→30 tariff limit)."""
    from .wb import WBError
    lim = (jam.access(c, shop) or {}).get('max_limit') or 100
    if progress is not None: lim=progress.effective_limit(lim)
    out = {nm:{} for nm in nms}; conflicts = {nm:0 for nm in nms}
    for top in jam.TOPS:
        nms=jam_scope.in_work_ids(c,shop,nms)
        out={nm:out[nm] for nm in nms};conflicts={nm:conflicts[nm] for nm in nms}
        if not nms:
            return {},lim,{}
        body = {'currentPeriod':{'start':str(day),'end':str(day)}, 'nmIds':nms,
                'topOrderBy':top,'includeSubstitutedSKUs':True,'includeSearchTexts':True,
                'orderBy':{'field':top,'mode':'desc'},'limit':lim}
        current = progress.get(top,lim,nms) if progress is not None else None
        if current is None:
            try:
                r = wb.call('analytics',jam.PATH,'POST',body=body,max_wait=25,archive_response=False)
            except WBError as e:
                if jam._kind(str(e)) != 'limit' or lim <= 30: raise
                lim = 30; body['limit'] = lim
                nms=jam_scope.in_work_ids(c,shop,nms)
                out={nm:out[nm] for nm in nms};conflicts={nm:conflicts[nm] for nm in nms}
                if not nms:
                    return {},lim,{}
                body['nmIds']=nms
                r = wb.call('analytics',jam.PATH,'POST',body=body,max_wait=25,archive_response=False)
            current = parse(r,nms)
            if progress is not None: progress.put(top,lim,current)
        for nm, queries in current.items():
            for q, vals in queries.items():
                if q in out[nm] and out[nm][q] != vals: conflicts[nm] += 1
                out[nm].setdefault(q,vals)
        if any(len(v) > 3*lim for v in out.values()): raise ValueError('jam_daily_top_overflow')
    jam._set_access(c,shop,'ok',lim)
    return out,lim,conflicts


def save(c, shop, day, data, limit, conflicts):
    allowed=jam_scope.in_work_ids(c,shop,data)
    data={nm:data[nm] for nm in allowed}
    if not data:
        return 0
    phrases = sorted({q for item in data.values() for q in item})
                                                                                          
    with c.transaction():
        if phrases:
            c.execute('''INSERT INTO jam_queries(account_id,query)
                SELECT %s,value FROM jsonb_array_elements_text(%s::jsonb)
                ON CONFLICT(account_id,query) DO NOTHING''',(shop,json.dumps(phrases,ensure_ascii=False)))
        ids = {r['query']:r['id'] for r in c.execute('SELECT id,query FROM jam_queries WHERE account_id=%s AND query=ANY(%s::text[])',(shop,phrases))}
        packs = [{'nm':nm,'v':[[ids[q],*vals] for q,vals in sorted(item.items())], 'n':len(item), 'conflicts':conflicts[nm]}
                 for nm,item in data.items()]
        c.execute('''INSERT INTO jam_daily(account_id,nm_id,day,metrics,query_count,max_limit,conflicts)
            SELECT %s,x.nm,%s,x.v,x.n,%s,x.conflicts FROM jsonb_to_recordset(%s::jsonb)
                AS x(nm bigint,v jsonb,n integer,conflicts integer)
            ON CONFLICT(account_id,nm_id,day) DO UPDATE SET metrics=EXCLUDED.metrics,
                query_count=EXCLUDED.query_count,max_limit=EXCLUDED.max_limit,
                conflicts=EXCLUDED.conflicts,fetched_at=now()''',(shop,day,limit,json.dumps(packs,ensure_ascii=False)))
    c.commit()
    return len(data)


def _load_scope(date_from=None, date_to=None, nm_ids=None, refresh_before=None):
    """Validate an explicit load without deriving its window from the worker's day.

    The caller persists refresh_before at admission. It is never advanced when
    a bounded pass resumes, so crossing midnight cannot re-open finished days.
    None means missing packages only; ordinary scheduled calls keep their SQL.
    """
    if date_from is None and date_to is None:
        if nm_ids is not None or refresh_before is not None:
            raise ValueError('jam_daily_scope_requires_dates')
        return None
    if type(date_from) is not date or type(date_to) is not date:
        raise ValueError('jam_daily_invalid_dates')
    if not 0 <= (date_to-date_from).days < HISTORY_DAYS or date_to >= today_msk():
        raise ValueError('jam_daily_invalid_window')
    if nm_ids is not None:
        if not isinstance(nm_ids, (tuple, list, set, frozenset)) or any(
                type(nm) is not int or not 0 < nm < 2**63 for nm in nm_ids):
            raise ValueError('jam_daily_invalid_catalog')
        nm_ids = tuple(sorted(set(nm_ids)))
    if refresh_before is not None:
        if (not isinstance(refresh_before, datetime) or refresh_before.tzinfo is None
                or refresh_before.utcoffset() is None):
            raise ValueError('jam_daily_invalid_refresh_cutoff')
        refresh_before = refresh_before.astimezone(timezone.utc)
        if refresh_before > datetime.now(timezone.utc):
            raise ValueError('jam_daily_future_refresh_cutoff')
    return {'date_from':date_from, 'date_to':date_to, 'nm_ids':nm_ids,
            'refresh_before':refresh_before}


def pending(c, shop, excluded, history_from=None, *, date_from=None, date_to=None,
            nm_ids=None, refresh_before=None, history_first=False):
    scope = _load_scope(date_from, date_to, nm_ids, refresh_before)
    if scope is not None:
        start = max(date_from, history_from) if history_from else date_from
        if start > date_to or scope['nm_ids'] == ():
            return []
        selected = list(scope['nm_ids']) if scope['nm_ids'] is not None else None
        return list(c.execute('''SELECT n.nm_id,d::date AS day FROM nomenclature n
            CROSS JOIN generate_series(%s::date,%s::date,interval '1 day') d
            LEFT JOIN jam_daily j ON j.account_id=n.account_id AND j.nm_id=n.nm_id AND j.day=d::date
            WHERE n.account_id=%s AND '''+jam_scope.IN_WORK+''' AND NOT (n.nm_id=ANY(%s::bigint[]))
              AND (%s::bigint[] IS NULL OR n.nm_id=ANY(%s::bigint[]))
              AND (j.day IS NULL OR (%s::timestamptz IS NOT NULL
                   AND j.day >= %s::date-2 AND j.fetched_at < %s::timestamptz))
            ORDER BY d DESC,n.nm_id LIMIT %s''',
            (start,date_to,shop,list(excluded),selected,selected,
             scope['refresh_before'],date_to,scope['refresh_before'],BATCH)))
    end = today_msk()-timedelta(days=1); start = end-timedelta(days=HISTORY_DAYS-1)
    if history_from: start=max(start,history_from)
    return list(c.execute('''SELECT n.nm_id,d::date AS day FROM nomenclature n
        CROSS JOIN generate_series(%s::date,%s::date,interval '1 day') d
        LEFT JOIN jam_daily j ON j.account_id=n.account_id AND j.nm_id=n.nm_id AND j.day=d::date
        WHERE n.account_id=%s AND '''+jam_scope.IN_WORK+''' AND NOT (n.nm_id=ANY(%s::bigint[]))
          AND (j.day IS NULL OR (j.day >= %s::date-2 AND j.fetched_at <
               (date_trunc('day',now() AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow')))
        ORDER BY CASE
          WHEN j.day IS NULL AND d::date >= %s::date-6 THEN 0
          WHEN j.day IS NULL THEN %s
          ELSE %s END, d DESC,n.nm_id LIMIT %s''',
        (start,end,shop,list(excluded),end,end,1 if history_first else 2,
         2 if history_first else 1,BATCH)))


def run(ctx, *, date_from=None, date_to=None, nm_ids=None, refresh_before=None):
    """At most two SKU batches; fixed loads persist their scope between passes.

    Caller owns the common collect:<shop>:jam_daily advisory lock. Do not write
    a fixed load's cursor into the scheduled collector's rolling-window cursor.
    """
    scope = _load_scope(date_from, date_to, nm_ids, refresh_before)
    shop=ctx.acc['id']; acc=jam.access(ctx.c,shop)
    if acc and acc['status'] != 'ok' and datetime.now(timezone.utc)-acc['checked_at'] < jam.ACCESS_RECHECK:
        return {'skipped':'jam_access','cursor':{'backfilled':scope is None}}
    count=0
    def remaining(history_first=False):
        args=(ctx.c,shop,set(),ctx.acc.get('history_from'))
        return pending(*args,**scope) if scope is not None else pending(*args,history_first=history_first)
    for batch in range(2):
                                                                               
                                                                               
        todo=remaining(history_first=bool(batch))
        if not todo: break
        day=todo[0]['day']; nms=[r['nm_id'] for r in todo if r['day']==day]
                                                                               
                                                                             
        progress=None
        if scope is None:
            from .jam_progress import open_progress
            progress=open_progress(ctx.c,shop,day,nms)
        try:
            data,limit,conflicts=(fetch(ctx.c,ctx.wb,shop,nms,day,progress=progress)
                if progress is not None else fetch(ctx.c,ctx.wb,shop,nms,day))
        except Exception as e:
                                                                                                             
            if 'jam' in str(e).lower() or 'джем' in str(e).lower():
                if not isinstance(e, ValueError): jam._set_access(ctx.c,shop,'no_jam',None,'Джем недоступен по ответу WB')
            raise
        count += save(ctx.c,shop,day,data,limit,conflicts)
        if progress is not None: progress.finish()
    more=bool(remaining())
    return {'sku_days':count,'cursor':{'backfilled':not more}}


def window(start,end):
    end=min(end,today_msk()-timedelta(days=1))
    start=max(start,end-timedelta(days=89))
    return start,end


def read(c,shop,nm,start,end):
    start,end=window(start,end)
    days=[start+timedelta(days=i) for i in range(max(0,(end-start).days+1))]
    packs=list(c.execute('''SELECT day,metrics,query_count,max_limit,conflicts,fetched_at FROM jam_daily
        WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s ORDER BY day''',(shop,nm,start,end)))
    ids=sorted({int(v[0]) for p in packs for v in p['metrics']})
    names={r['id']:r['query'] for r in c.execute('SELECT id,query FROM jam_queries WHERE account_id=%s AND id=ANY(%s::bigint[])',(shop,ids))} if ids else {}
    series={}; coverage={str(p['day']):{'queries':p['query_count'],'fetched_at':str(p['fetched_at']),
                                      'conflicts':p['conflicts'],'top_limit':p['max_limit']} for p in packs}
    for p in packs:
        for v in p['metrics']:
            qid=int(v[0])
            if qid in names: series.setdefault(qid,{})[str(p['day'])]=dict(zip(FIELDS,v[1:]))
    return {'nm_id':nm,'from':str(start),'to':str(end),'days':[str(d) for d in days],
            'coverage':coverage,'missing_days':[str(d) for d in days if str(d) not in coverage],
            'queries':names,'series':series,'note':NOTE}


def summaries(src):
    rows=[]
    for qid,daily in src['series'].items():
        last=max(daily)
        row={'query_id':qid,'query':src['queries'][qid],'observed_days':len(daily),'last_day':last,'pos':daily[last]['avgPosition']}
        for out,k in (('clicks','openCard'),('carts','addToCart'),('orders','orders')):
            vals=[v[k] for v in daily.values()]
            row[out]=sum(vals) if all(v is not None for v in vals) else None
        rows.append(row)
    return sorted(rows,key=lambda r:(-(r['orders'] or 0),-(r['clicks'] or 0),r['query']))


def query_days(c,shop,nm,qid,start,end,query_text=None):
    from .tabs import jam as jt
    from .materialize import cost_dirty
    src=read(c,shop,nm,start,end)
    if query_text is not None:
        qid=next((i for i,q in src['queries'].items() if q==query_text),None)
    if qid not in src['queries']:
        return {**{k:v for k,v in src.items() if k not in ('series','queries')},'query':query_text,
                'rows':[{'day':d,'state':'outside_top' if d in src['coverage'] else 'missing_day'}
                        for d in reversed(src['days'])] if query_text is not None else []}
                                                                              
    src['financial_pending']=bool(cost_dirty(c,shop))
    money={} if src['financial_pending'] else {str(r['day']):r['data'] for r in c.execute('SELECT day,data FROM agg_nm_day WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s',
        (shop,nm,src['from'],src['to']))}
    ads={str(r['day']):{'v':r['v'],'cl':r['cl'],'sp':float(r['sp']) if r['sp'] is not None else None} for r in c.execute('''
        SELECT day,sum(views) v,sum(clicks) cl,sum(spend) sp FROM wb_ad_kw_daily
        WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s AND lower(trim(query))=lower(trim(%s)) GROUP BY day''',
        (shop,nm,src['from'],src['to'],src['queries'][qid]))}
    rows=[]
    for day in reversed(src['days']):
        raw=src['series'][qid].get(day)
        if raw is None:
            rows.append({'day':day,'state':'outside_top' if day in src['coverage'] else 'missing_day'}); continue
        m=money.get(day) or {}; o=number(m.get('orders')); p=number(m.get('cost_orders'))
        profit=m.get('profit_orders'); ad=m.get('ads_upd')
        ppu=(float(profit)+float(ad or 0))/o if o and p and profit is not None else None
        av=ads.get(day); safe_ad={'v':None,'cl':None,'sp':0} if av is None else {**av,'sp':av['sp'] or 0}
        r=jt._row(src['queries'][qid],raw['frequency'],raw['visibility'],raw['avgPosition'],raw['openCard'],raw['addToCart'],raw['orders'],safe_ad,ppu)
        if av is None or av['sp'] is None:
            for k in ('ad_views','ad_clicks','ctr','cpc','spend','cart_cost','order_cost','ad_share','profit'):r[k]=None
        if raw['orders'] is None: r['profit']=None
        if any(raw[k] is None for k in ('frequency','visibility','openCard')):
            r.update(pot_clicks=None,pot_orders=None,pot_profit=None)
        elif raw['orders'] is None:
            r.update(pot_orders=None,pot_profit=None)
        r.update(day=day,state='observed',median_pos=raw['medianPosition'],week_freq=raw['weekFrequency'])
        rows.append(r)
    return {k:v for k,v in src.items() if k not in ('series','queries')} | {'query':src['queries'][qid],'query_id':qid,'rows':rows}


def ai_history(c,shop,nm,start,end,query='',offset=0,limit=10):
    """All keys available via bounded pages. No API calls, no implied zeroes."""
    src=read(c,shop,nm,start,end); rows=summaries(src)
    if query: rows=[r for r in rows if query.lower() in r['query'].lower()]
    offset=max(0,int(offset)); limit=max(1,min(10,int(limit)))
    selected=rows[offset:offset+limit]
    for r in selected:
        r['daily']=[[day,'observed' if day in src['series'][r['query_id']] else
                     'outside_top' if day in src['coverage'] else 'missing_day',
                     *[src['series'][r['query_id']].get(day,{}).get(k) for k in FIELDS]] for day in src['days']]
    result={'nm_id':nm,'period':[src['from'],src['to']],'note':NOTE,'missing_days':src['missing_days'],
            'loaded_days':len(src['coverage']),'conflict_days':[d for d,v in src['coverage'].items() if v['conflicts']],
            'daily_columns':['day','state',*FIELDS], 'query_count':len(rows),'rows':selected}
                                                                                                    
    while len(selected)>1 and len(json.dumps(result,ensure_ascii=False))>24000: selected.pop()
    result['next_offset']=offset+len(selected) if offset+len(selected)<len(rows) else None
    return result

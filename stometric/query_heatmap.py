"""Saved Wildbox monthly query frequencies; explicit bounded background refresh."""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from . import auth, db, market
from .config import today_msk

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='query-heatmap')
_SLOTS = threading.BoundedSemaphore(4)
LIMIT = 100


def active_user(c, u):
    row = c.execute('SELECT id,is_active,is_superadmin FROM users WHERE id=%s', (u['id'],)).fetchone()
    if not row or not row['is_active']:
        raise HTTPException(403, 'Нет действующего доступа')
    return {**u, **row}


def authorize(c, u, shop, nm):
    if not auth.can(auth.shop_role(c, u, shop), 'viewer'):
        raise HTTPException(403, 'Нет доступа к магазину')
    acc = c.execute("SELECT workspace_id,marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()
    if acc['marketplace'] != 'wb' or not c.execute('SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s', (shop,nm)).fetchone():
        raise HTTPException(404, 'Выберите свой товар WB')
    return acc['workspace_id']


def monthly_rows(result, today):
    dynamic = (result.get('data') or {}).get('dynamic')
    if not isinstance(dynamic, list):
        raise ValueError('unexpected_monthly_response')
    out = {}
    for r in dynamic:
        if r.get('predicted'):
            continue
        month = date.fromisoformat(str(r['date'])[:10]).replace(day=1)
        if month > today.replace(day=1):
            continue
        v = r.get('frequency')
        if v is not None:
            try:
                v = Decimal(str(v))
            except InvalidOperation:
                raise ValueError('invalid_frequency') from None
            if not v.is_finite() or v < 0:
                raise ValueError('invalid_frequency')
        if month in out and out[month] != v:
            raise ValueError('conflicting_month')
        out[month] = v
    return sorted(out.items())


def read(c, u, shop, nm):
    ws = authorize(c,u,shop,nm)
    r = c.execute('SELECT * FROM query_heatmap WHERE account_id=%s AND nm_id=%s', (shop,nm)).fetchone()
    if not r:
        return {'status':'empty','queries':[], 'months':[], 'rows':[], 'limit':LIMIT}
    queries = r['data'].get('queries', [])
    values = c.execute('SELECT query,month,frequency,fetched_at FROM query_months WHERE workspace_id=%s AND query=ANY(%s) ORDER BY month', (ws,queries)).fetchall() if queries else []
    months = sorted({str(x['month'])[:10] for x in values})
    by = {q:{} for q in queries}
    for x in values:
        by[x['query']][str(x['month'])[:10]] = x['frequency']
    state = r['status']
    from datetime import datetime, timezone
    if state in ('queued','running') and r['requested_at'] and (datetime.now(timezone.utc)-r['requested_at']).total_seconds() > (10800 if state == 'queued' else 2700):
        state = 'interrupted'
    return {'status':state,'queries':queries,'months':months,'rows':[{'query':q,'values':by[q]} for q in queries],
            'updated_at':r['updated_at'],'completed':r['data'].get('completed',0),'limit':LIMIT}


def start(c, u, shop, nm):
    authorize(c,u,shop,nm)
    if not auth.can(auth.shop_role(c,u,shop), "editor"):
        raise HTTPException(403, "Нужны права редактора")
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(409,'Очередь занята. Повторите позже.')
    try:
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f'heatmap-start:{shop}:{nm}',))
        if not c.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) ok", (f'heatmap-refresh:{shop}:{nm}',)).fetchone()['ok']:
            c.commit(); _SLOTS.release(); return
        prev = c.execute('SELECT status,requested_at FROM query_heatmap WHERE account_id=%s AND nm_id=%s', (shop,nm)).fetchone()
        if prev and prev['status'] in ('queued','running'):
            from datetime import datetime, timezone
            if (datetime.now(timezone.utc)-prev['requested_at']).total_seconds() < (10800 if prev['status'] == 'queued' else 2700):
                c.commit(); _SLOTS.release(); return
        run_key = uuid.uuid4().hex
        c.execute("""INSERT INTO query_heatmap(account_id,nm_id,status,requested_at,run_key) VALUES (%s,%s,'queued',now(),%s)
          ON CONFLICT(account_id,nm_id) DO UPDATE SET status='queued',requested_at=now(),run_key=EXCLUDED.run_key""", (shop,nm,run_key))
        c.commit()
        _POOL.submit(_refresh, dict(u), shop, nm, run_key)
    except Exception:
        _SLOTS.release()
        raise


def _refresh(u,shop,nm,run_key):
    try:
        with db.connect() as c:
            lock = f'heatmap-refresh:{shop}:{nm}'
            if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok',(lock,)).fetchone()['ok']:
                return
            try:
                row = c.execute('SELECT run_key FROM query_heatmap WHERE account_id=%s AND nm_id=%s',(shop,nm)).fetchone()
                if not row or row['run_key'] != run_key:
                    return
                u = active_user(c,u)
                if not auth.can(auth.shop_role(c,u,shop), 'editor'):
                    raise HTTPException(403, 'Нет прав обновления')
                ws = authorize(c,u,shop,nm)
                token = market.ws_token(c,ws)
                if not token:
                    c.execute("UPDATE query_heatmap SET status='no_key' WHERE account_id=%s AND nm_id=%s", (shop,nm)); c.commit(); return
                c.execute("UPDATE query_heatmap SET status='running',requested_at=now() WHERE account_id=%s AND nm_id=%s", (shop,nm)); c.commit()
                result = market._call(token,'get_external_analytics',schema_name='external.products.keywords',params={'product_id':nm,'period':14},max_rows=LIMIT)
                if not isinstance(result,dict) or not isinstance(result.get('rows'),list):
                    raise ValueError('unexpected_keyword_response')
                u = active_user(c,u)
                authorize(c,u,shop,nm)
                queries = list(dict.fromkeys(r['keyword']['name'].strip() for r in result['rows'] if isinstance(r.get('keyword',{}).get('name'),str) and r['keyword']['name'].strip()))[:LIMIT]
                c.execute("UPDATE query_heatmap SET data=%s,updated_at=now() WHERE account_id=%s AND nm_id=%s", (json.dumps({'queries':queries,'completed':0},ensure_ascii=False),shop,nm)); c.commit()
                from .planning import add_months
                frm = add_months(today_msk().replace(day=1),-26).isoformat()
                deadline=time.monotonic()+2400
                for i,q in enumerate(queries):
                    if time.monotonic()>deadline:
                        raise TimeoutError("refresh_deadline")
                    u = active_user(c,u)
                    if not auth.can(auth.shop_role(c,u,shop), 'editor'):
                        raise HTTPException(403, 'Нет прав обновления')
                    authorize(c,u,shop,nm)                                                              
                    result = market._call(token,'get_external_analytics',schema_name='external.seasonality.predict',params={'wb_search':q,'month_width':True,'date_from':frm})
                    u = active_user(c,u)
                    authorize(c,u,shop,nm)
                    for month,value in monthly_rows(result,today_msk()):
                        c.execute("""INSERT INTO query_months(workspace_id,query,month,frequency) VALUES (%s,%s,%s,%s)
                           ON CONFLICT(workspace_id,query,month) DO UPDATE SET frequency=EXCLUDED.frequency,fetched_at=now()""", (ws,q,month,value))
                    c.execute("UPDATE query_heatmap SET data=jsonb_set(data,'{completed}',%s::jsonb),updated_at=now() WHERE account_id=%s AND nm_id=%s", (str(i+1),shop,nm)); c.commit()
                c.execute("UPDATE query_heatmap SET status='ready',updated_at=now() WHERE account_id=%s AND nm_id=%s",(shop,nm)); c.commit()
            except Exception:
                c.rollback()
                c.execute("UPDATE query_heatmap SET status='failed' WHERE account_id=%s AND nm_id=%s",(shop,nm)); c.commit()
            finally:
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock,)); c.commit()
    finally:
        _SLOTS.release()

"""Capture public WB card slides for an authorized knowledge-base entry."""
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.error import HTTPError

from fastapi import HTTPException
from . import db, kb, photos
from .query_heatmap import active_user

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kb-slides')
_SLOTS = threading.BoundedSemaphore(12)


def card_nm(url):
    try:
        p = urlparse(url or '')
        if p.scheme not in ('http','https') or p.hostname not in ('wildberries.ru','www.wildberries.ru') or p.username or p.password or p.port:
            return None
        m = re.fullmatch(r'/catalog/([1-9][0-9]{0,11})/detail\.aspx/?',p.path)
        return int(m[1]) if m else None
    except ValueError:
        return None


def item(c,u,iid):
    it = kb.get(c,iid)
    if not it or not kb.can_see(c,u,it):
        raise HTTPException(404,'Нет такого материала')
    nm = card_nm(it.get('url')) if it['kind']=='link' else None
    if not nm:
        raise HTTPException(400,'Нужна полная ссылка на карточку WB')
    return it,nm


def read(c,u,iid):
    _,nm=item(c,u,iid)
    row=c.execute('SELECT * FROM kb_card_slides WHERE item_id=%s AND nm_id=%s',(iid,nm)).fetchone()
    if not row:
        return {'status':'empty','hashes':[]}
    state=row['status']
    if state in ('queued','running') and row['attempted_at'] and (datetime.now(timezone.utc)-row['attempted_at']).total_seconds()>(8100 if state=='queued' else 900):
        state='interrupted'
    return {'status':state,'hashes':row['hashes'],'captured_at':row['captured_at']}


def start(c,u,iid,*,automatic=False):
    it,nm=item(c,u,iid)
    if not automatic and not kb.can_change(c,u,it):
        raise HTTPException(403,'Обновить слайды может автор или администратор')
    if not _SLOTS.acquire(blocking=False):
        return
    try:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(f'kb-slides-start:{iid}',))
        if not c.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) ok',(f'kb-slides-worker:{iid}',)).fetchone()['ok']:
            c.commit();_SLOTS.release();return
        row=c.execute('SELECT * FROM kb_card_slides WHERE item_id=%s',(iid,)).fetchone()
        if row and row['nm_id']==nm and (automatic or (row['status'] in ('queued','running') and (datetime.now(timezone.utc)-row['attempted_at']).total_seconds()<(8100 if row['status']=='queued' else 900))):
            c.commit();_SLOTS.release();return
        run_key=uuid.uuid4().hex
        c.execute("""INSERT INTO kb_card_slides(item_id,nm_id,status,attempted_at,run_key) VALUES (%s,%s,'queued',now(),%s)
          ON CONFLICT(item_id) DO UPDATE SET nm_id=EXCLUDED.nm_id,
          hashes=CASE WHEN kb_card_slides.nm_id=EXCLUDED.nm_id THEN kb_card_slides.hashes ELSE '[]'::jsonb END,
          captured_at=CASE WHEN kb_card_slides.nm_id=EXCLUDED.nm_id THEN kb_card_slides.captured_at ELSE NULL END,
          status='queued',attempted_at=now(),run_key=EXCLUDED.run_key""",(iid,nm,run_key));c.commit()
        _POOL.submit(_capture,dict(u),iid,nm,run_key,automatic)
    except Exception:
        _SLOTS.release();raise


def _capture(u,iid,nm,run_key,automatic=False):
    try:
        with db.connect() as c:
            lock=f'kb-slides-worker:{iid}'
            if not c.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) ok',(lock,)).fetchone()['ok']:
                return
            try:
                row=c.execute('SELECT run_key FROM kb_card_slides WHERE item_id=%s',(iid,)).fetchone()
                if not row or row['run_key']!=run_key:return
                u=active_user(c,u)
                it,current=item(c,u,iid)
                if current!=nm:
                    return
                if not automatic and not kb.can_change(c,u,it):
                    raise HTTPException(403,'Нет прав обновления')
                c.execute("UPDATE kb_card_slides SET status='running',attempted_at=now() WHERE item_id=%s AND nm_id=%s",(iid,nm));c.commit()
                url=photos._basket_url(c,nm,1)
                if not url:raise ValueError('no_source')
                hashes=[]
                deadline=time.monotonic()+600
                for slot in range(1,31):
                    if time.monotonic()>deadline:raise TimeoutError('capture_deadline')
                    u=active_user(c,u)
                    item(c,u,iid)
                    try:
                        with photos._req(url.replace('/1.webp',f'/{slot}.webp')) as response:
                            raw=response.read(8*1024*1024+1)
                            if len(raw)>8*1024*1024:raise ValueError('image_size')
                    except HTTPError as e:
                        if e.code==404 and hashes:break
                        raise
                    hashes.append(photos._store(c,raw)['hash'])
                u=active_user(c,u)
                it,current=item(c,u,iid)
                if current!=nm:
                    c.rollback();return
                c.execute("UPDATE kb_card_slides SET hashes=%s,status='ready',captured_at=now() WHERE item_id=%s AND nm_id=%s",(json.dumps(hashes),iid,nm));c.commit()
            except Exception:
                c.rollback()
                c.execute("UPDATE kb_card_slides SET status='failed' WHERE item_id=%s AND nm_id=%s",(iid,nm));c.commit()
            finally:
                c.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',(lock,));c.commit()
    finally:
        _SLOTS.release()

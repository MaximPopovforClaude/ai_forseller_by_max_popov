"""Self-hosted bot process: chat works independently of optional background jobs."""
import json
import fcntl
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

JOB_SETTINGS = {
    'stometric_notifications': 'Стометрик: плановые уведомления (после настройки получателей)',
    'stometric_morning_ai': 'Стометрик: утренние ИИ-сводки всех активных магазинов (платный API)',
    'stometric_ads_ai': 'Стометрик: плановый ИИ-разбор рекламы (платный API)',
}


def settings(c):
    rows = c.execute('SELECT key,value FROM app_settings WHERE key = ANY(%s)', (list(JOB_SETTINGS),)).fetchall()
    values = {r['key']: r['value'] for r in rows}
    return {key: values.get(key) is True for key in JOB_SETTINGS}


def tick(bots, c, now, calendar_thread=None):
    flags = settings(c)
    if flags['stometric_morning_ai'] and now.hour >= 7:
        r = c.execute("""INSERT INTO app_settings(key,value) VALUES ('morning_jobs', %s) ON CONFLICT (key) DO UPDATE
                         SET value=EXCLUDED.value WHERE app_settings.value <> EXCLUDED.value RETURNING key""",
                      (json.dumps(now.date().isoformat()),)).fetchone()
        c.commit()
        if r:
            threading.Thread(target=bots._morning_jobs, daemon=True).start()
    if flags['stometric_ads_ai'] and now.hour in bots.ADS_HOURS and now.minute >= 30:
        slot = f'{now.date()}:{now.hour}'
        r = c.execute("""INSERT INTO app_settings(key,value) VALUES ('ads_slot', %s) ON CONFLICT (key) DO UPDATE
                         SET value=EXCLUDED.value WHERE app_settings.value <> EXCLUDED.value RETURNING key""",
                      (json.dumps(slot),)).fetchone()
        c.commit()
        if r:
            threading.Thread(target=bots._ads_jobs, args=(now.hour == bots.ADS_HOURS[0],), daemon=True).start()
    available = any(b and b.token for b in (bots.ASSIST, bots.NOTIFY))
    if not flags['stometric_notifications'] or not available:
        return calendar_thread
    from . import news
    try:
        news.sync_changes(c)
        if now.minute % 5 == 0:
            news.sync_spp(c)
        news.send_pending(c)
    except Exception:
        c.rollback()
        print('Stometric news processing failed', flush=True)
    for r in c.execute("""SELECT s.*, u.email FROM notify_settings s JOIN users u ON u.id=s.user_id
                          WHERE s.chat_id IS NOT NULL AND u.is_active""").fetchall():
        if r['daily'] and now.time() >= r['daily_time'] and bots.in_window(r, now) and bots._once(c, r['user_id'], 'daily', now.date().isoformat()):
            bots.send_daily(c, r['user_id'], r['chat_id'])
        if r['alerts'] and now.minute % 30 == 0:
            u = c.execute('SELECT * FROM users WHERE id=%s', (r['user_id'],)).fetchone()
            for code, ref, text in bots.alerts_for(c, u):
                if bots._once(c, r['user_id'], 'alert:' + code, ref):
                    bots.notify(c, r['user_id'], r['chat_id'], text)
    bots.flush_queue(c)
    if bots.ASSIST and bots.ASSIST.token and (calendar_thread is None or not calendar_thread.is_alive()):
        calendar_thread = threading.Thread(target=bots._calendar_jobs, daemon=True)
        calendar_thread.start()
    return calendar_thread


def scheduler(bots):
    calendar_thread = None
    while True:
        try:
            with bots.db.connect() as c:
                calendar_thread = tick(bots, c, datetime.now(bots.MSK), calendar_thread)
        except Exception:
            print('Stometric scheduler failed; check database and bot setup', flush=True)
        time.sleep(60 - datetime.now().second + 1)


@contextmanager
def exclusive_process(directory):
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / 'stometric-bots.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('A bot process is already running for this installation') from None
        yield
    finally:
        os.close(fd)


def main(bots):
    with exclusive_process(bots.config.DATA):
        run(bots)


def run(bots):
    # One token must never be polled by different roles/processes.
    with bots.db.connect() as c:
        assistant = bots.assistant_token(c)
    values = [x for x in (assistant, bots.config.env().get('TG_BOT_NOTIFY_TOKEN'),
                          bots.config.env().get('TG_BOT_REGISTER_TOKEN')) if x]
    if len(values) != len(set(values)):
        raise SystemExit('Use distinct tokens for Stometric, registration and legacy notifications')
    bots.NOTIFY = bots.Bot('TG_BOT_NOTIFY_TOKEN')
    reg = bots.Bot('TG_BOT_REGISTER_TOKEN')
    threads = [threading.Thread(target=bots.assistant_loop, daemon=True),
               threading.Thread(target=bots.scheduler, daemon=True)]
    if bots.NOTIFY.token:
        threads.append(threading.Thread(target=bots.NOTIFY.poll, args=(bots.handle_notify,), daemon=True))
    if reg.token:
        threads.append(threading.Thread(target=reg.poll, args=(bots.handle_register,), daemon=True))
    for th in threads:
        th.start()
    print('Stometric process started; optional jobs use explicit admin settings', flush=True)
    while all(th.is_alive() for th in threads):
        time.sleep(10)
    raise SystemExit('Bot thread stopped; systemd will restart the process')

"""Calendar permission/API/reminder regressions. No live DB, tokens or Telegram.

Set CALENDAR_STANDALONE_PG=1 to run application queries against a disposable
PostgreSQL single-user backend. It uses no sockets, production config or DSNs.
This verifies real SQL/results, NOT concurrent transaction semantics.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import stometric.web  
from fastapi import HTTPException
import httpx
from psycopg import sql
from pydantic import ValidationError
from stometric import api_calendar as api, calendar as cal

DAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, 10, tzinfo=timezone(timedelta(hours=3)))
ROOT = Path(__file__).resolve().parents[1]


class CalendarRulesTests(unittest.TestCase):
    def test_react_calendar_scenarios(self):
        node = shutil.which('node')
        if not node: self.skipTest('Node unavailable')
        for mode in ('development', 'production'):
            p = subprocess.run([node,str(ROOT/'tools/frontend/calendar_regression.cjs'),str(ROOT)],
                               env={**os.environ,'NODE_ENV':mode},capture_output=True,text=True,timeout=25)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_text_is_escaped_and_has_real_deadline(self):
        item = {'title': '<script>&', 'workspace': 'A & B', 'day': DAY + timedelta(days=1)}
        text = cal.reminder_text(item, DAY)
        self.assertIn('Срок завтра: 05.11.2026', text)
        self.assertIn('&lt;script&gt;&amp;', text)
        self.assertIn('A &amp; B', text)
        self.assertNotIn('<script>', text)
        self.assertIn('Срок сегодня', cal.reminder_text({**item, 'day': DAY}, DAY))
        self.assertIn('Срок прошёл', cal.reminder_text({**item, 'day': DAY-timedelta(days=1)}, DAY))

    def test_mcp_disabled_user_and_no_bot_do_no_io(self):
        c = Mock()
        for u in ({'id': 1, '_mcp': {'id': 7}}, {'id': 1, 'is_active': False}):
            with self.assertRaises(HTTPException):
                cal.scope(c, u, 1)
        self.assertEqual(cal.send_reminders(c, None, NOW), 0)
        self.assertEqual(cal.send_reminders(c, SimpleNamespace(token=''), NOW), 0)
        c.execute.assert_not_called()

    def test_input_validation_and_mutation_permissions(self):
        with self.assertRaises(ValidationError):
            api.CreateIn(kind='task', title='x'*201, day=DAY, request_key=uuid4())
        with self.assertRaises(ValidationError):
            api.UpdateIn(kind='task', title='x', day=DAY, version=0, status='open')
        entry = {'created_by': 2, 'assignee_id': 3}
        self.assertTrue(cal.editable({'id': 3}, {'role': 'editor'}, entry))
        self.assertFalse(cal.editable({'id': 3}, {'role': 'viewer'}, entry))
        self.assertFalse(cal.editable({'id': 4}, {'role': 'editor'}, entry))
        self.assertTrue(cal.editable({'id': 4}, {'role': 'admin'}, entry))


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def __iter__(self): return iter(self.rows)


class Standalone:
    """Disposable fixture adapter; each execute commits independently."""
    def __init__(self, cluster, schema):
        self.cluster, self.schema = cluster, schema
        self.calls = []

    def raw(self, text):
        p = subprocess.run(['/usr/lib/postgresql/16/bin/postgres', '--single', '-j', '-D', str(self.cluster), 'postgres'],
                           input=f'SET search_path={self.schema};\n{text}\n\n', text=True, capture_output=True, timeout=20)
        if p.returncode or re.search(r'\b(ERROR|FATAL|PANIC):', p.stderr):
            raise AssertionError(p.stderr)
        return p.stdout

    def execute(self, query, args=()):
        self.calls.append((query, args))
        if isinstance(args, dict):
            query = re.sub(r'%\((\w+)\)s', lambda m: sql.Literal(args[m[1]]).as_string(), query)
        else:
            values = iter(args)
            query = re.sub(r'%s', lambda _: sql.Literal(next(values)).as_string(), query)
        query = query.strip().rstrip(';')
        aggregate = "SELECT json_build_object('rows',coalesce(json_agg(row_to_json(t)), '[]'::json))::text"
        if query.startswith('SELECT'):
            wrapper = f'{aggregate} FROM ({query}) t'
        elif 'RETURNING' in query:
            wrapper = f'WITH t AS ({query}) {aggregate} FROM t'
        else:
            self.raw(query + ';')
            return Cursor([])
        out = self.raw(f"COPY ({wrapper}) TO STDOUT;")
        payload = next(line[line.index('{"rows"'):] for line in out.splitlines() if '{"rows"' in line)
        
        payload = re.sub(r'\\([\\ntbrfv])', lambda m: {'\\': '\\', 'n':'\n', 't':'\t','b':'\b','r':'\r','f':'\f','v':'\v'}[m[1]], payload)
        rows = json.loads(payload)['rows']
        for row in rows:
            for k, v in list(row.items()):
                if v is None: continue
                if k == 'day': row[k] = date.fromisoformat(v)
                elif k in ('send_from','send_to'): row[k] = time.fromisoformat(v)
                elif k == 'request_key': row[k] = UUID(v)
        return Cursor(rows)

    def commit(self): pass
    def rollback(self): pass


FIXTURE = '''
CREATE TABLE users(id int PRIMARY KEY,name text,email text,is_active boolean DEFAULT true);
CREATE TABLE workspaces(id int PRIMARY KEY,name text);
CREATE TABLE memberships(user_id int,workspace_id int,role text,shop_ids int[],PRIMARY KEY(user_id,workspace_id));
CREATE TABLE accounts(id int PRIMARY KEY,workspace_id int,title text,name text,marketplace text,is_active boolean DEFAULT true);
CREATE TABLE notify_settings(user_id int PRIMARY KEY,chat_id bigint,bot text,send_from time,send_to time,muted_shops int[]);
CREATE TABLE audit_log(user_id int,workspace_id int,action text,details jsonb);
CREATE TABLE nm_actions(id bigserial PRIMARY KEY,account_id int,nm_id bigint,day date,kind text,value text,note text,user_id int);
CREATE TABLE card_changes(id bigserial PRIMARY KEY,account_id int,nm_id bigint,detected_at timestamptz,kind text,field text,old_value jsonb,new_value jsonb);
CREATE TABLE wb_promo_days(account_id int,nm_id bigint,day date,promos text[]);
CREATE TABLE entry_alerts(account_id int,nm_id bigint,day date,section text,point text,clicks numeric,clicks_avg numeric,change_pct numeric);
INSERT INTO users(id,name,email) VALUES (1,'Owner','owner@example.test'),(2,'Editor','ed@example.test'),(3,'Other','other@example.test'),(4,'Viewer','view@example.test'),(5,'Foreign','foreign@example.test');
INSERT INTO workspaces VALUES (1,'Team'),(2,'Other workspace');
INSERT INTO memberships VALUES (1,1,'owner',NULL),(2,1,'editor','{10}'),(3,1,'editor','{11}'),(4,1,'viewer',NULL),(5,2,'owner',NULL);
INSERT INTO accounts(id,workspace_id,title,name,marketplace) VALUES (10,1,'WB shop','wb1','wb'),(11,1,'Ozon shop','oz1','ozon'),(20,2,'Foreign shop','wb2','wb');
INSERT INTO notify_settings VALUES (2,200,'assistant','09:30','23:30',NULL),(3,300,'assistant','09:30','23:30',NULL);
'''


@unittest.skipUnless(os.environ.get('CALENDAR_STANDALONE_PG') == '1', 'opt in: CALENDAR_STANDALONE_PG=1 (disposable single-user PG)')
class CalendarSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='calendar-test-pg-')
        cls.cluster = Path(cls.tmp.name)/'db'
        p = subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','calendar_test','--no-locale','--encoding=UTF8'], capture_output=True, text=True)
        if p.returncode: raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        self.schema = 'calendar_case_' + uuid4().hex
        self.c = Standalone(self.cluster, self.schema)
        self.c.raw(f'CREATE SCHEMA {self.schema}; SET search_path={self.schema};' + FIXTURE + (ROOT/'stometric/migrations/102_calendar.sql').read_text())
        self.clock = patch.object(cal, 'today_msk', return_value=DAY)
        self.clock.start()
        self.u = {'id': 2, 'is_active': True}

    def tearDown(self): self.clock.stop()

    def values(self, **kw):
        return {'kind':'task','title':'Prepare stock','description':'details','day':DAY+timedelta(days=1), 'shop_id':10,'assignee_id':2, **kw}

    def add(self, u=None, ws=1, **kw):
        return cal.create(self.c, u or self.u, ws, self.values(**kw), uuid4())[0]

    def get(self, eid): return self.c.execute('SELECT * FROM calendar_entries WHERE id=%s', (eid,)).fetchone()

    def test_shared_visibility_scoped_shops_and_permissions(self):
        own = self.add()
        global_note = self.add(kind='note',shop_id=None,assignee_id=None)
        other = self.add(u={'id':1},shop_id=11,assignee_id=3)
        ctx = cal.scope(self.c,self.u,1)
        rows,_ = cal.entries(self.c,self.u,1,ctx,DAY,DAY+timedelta(days=3))
        self.assertEqual({r['id'] for r in rows}, {own,global_note})
        self.assertNotIn(other, {r['id'] for r in rows})
        for u,ws in (({'id':5},1),({'id':2},2),({'id':999,'is_superadmin':True},1)):
            with self.assertRaises(HTTPException): cal.scope(self.c,u,ws)
        with self.assertRaises(HTTPException): self.add(u={'id':4})
        with self.assertRaises(HTTPException): self.add(assignee_id=3)
        with self.assertRaises(HTTPException): self.add(assignee_id=5)
        with self.assertRaises(HTTPException): self.add(shop_id=20)
        with self.assertRaises(HTTPException): cal.update(self.c,{'id':3},1,global_note,{**self.values(kind='note',shop_id=None,assignee_id=None),'status':'open'},1)

    def test_idempotency_conflict_and_optimistic_update(self):
        key = uuid4()
        eid,created = cal.create(self.c,self.u,1,self.values(),key)
        self.assertTrue(created)
        self.assertEqual(cal.create(self.c,self.u,1,self.values(),key),(eid,False))
        with self.assertRaises(HTTPException) as err: cal.create(self.c,self.u,1,self.values(title='Changed'),key)
        self.assertEqual(err.exception.status_code,409)
        cal.update(self.c,self.u,1,eid,{**self.values(),'status':'done'},1)
        with self.assertRaises(HTTPException) as err: cal.update(self.c,self.u,1,eid,{**self.values(),'status':'open'},1)
        self.assertEqual(err.exception.status_code,409)
        self.assertEqual(self.get(eid)['status'],'done')
        cal.update(self.c,self.u,1,eid,{**self.values(),'status':'open'},2)
        self.assertEqual(self.get(eid)['reminder_version'],2)

    def test_due_includes_overdue_today_tomorrow_not_future_closed_or_others(self):
        expected = {self.add(day=DAY-timedelta(days=5)),self.add(day=DAY),self.add()}
        self.add(day=DAY+timedelta(days=2))
        self.add(kind='note',assignee_id=None)
        self.add(u={'id':1},shop_id=11,assignee_id=3)
        closed=self.add()
        cal.update(self.c,self.u,1,closed,{**self.values(),'status':'done'},1)
        rows,_=cal.entries(self.c,self.u,1,cal.scope(self.c,self.u,1),due=True)
        self.assertEqual({r['id'] for r in rows},expected)

    def test_actions_all_sources_pagination_and_no_foreign_shop(self):
        self.c.raw("""INSERT INTO nm_actions(account_id,nm_id,day,kind,value,note,user_id)
          SELECT 10,100+i,'2026-11-04','seo','test','note',2 FROM generate_series(1,201) i;
          INSERT INTO nm_actions(account_id,nm_id,day,kind) VALUES (11,500,'2026-11-04','seo'),(20,600,'2026-11-04','seo');
          INSERT INTO card_changes(account_id,nm_id,detected_at,kind,field,old_value,new_value)
          VALUES (10,700,'2026-11-03 22:00+00','card','title','\"Old\"','\"New\"');
          INSERT INTO wb_promo_days VALUES (10,800,'2026-11-04',ARRAY['Sale']);
          INSERT INTO entry_alerts VALUES (10,900,'2026-11-04','Search','Organic',5,10,-50);
        """)
        ctx=cal.scope(self.c,self.u,1)
        counts=cal.action_counts(self.c,ctx,DAY,DAY)
        self.assertEqual(counts,[{'day':DAY,'n':204}])
        first=cal.action_page(self.c,ctx,DAY)
        tail=cal.action_page(self.c,ctx,DAY,offset=200)
        self.assertTrue(first['more']); self.assertFalse(tail['more'])
        self.assertEqual(len(first['items'])+len(tail['items']),204)
        self.assertEqual({r['shop_id'] for r in first['items']+tail['items']},{10})
        self.assertEqual({r['source'] for r in tail['items']},{'manual','change','promo','entry'})
        with self.assertRaises(HTTPException): cal.action_counts(self.c,ctx,DAY,DAY,11)

    def test_reminder_once_reschedule_and_uncertain_no_retry(self):
        eid=self.add()
        bot=SimpleNamespace(token='TEST ONLY',send=Mock(return_value=True))
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),1)
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.assertEqual(bot.send.call_count,1)
        cal.update(self.c,self.u,1,eid,{**self.values(day=DAY+timedelta(days=2)),'status':'open'},1)
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.assertEqual(cal.send_reminders(self.c,bot,NOW+timedelta(days=1)),1)
        other=self.add(title='uncertain')
        bot.send.return_value=False
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.assertEqual(bot.send.call_count,3)
        self.assertEqual(self.c.execute('SELECT state FROM calendar_reminders WHERE entry_id=%s',(other,)).fetchone()['state'],'uncertain')

    def test_reminder_window_permissions_stop_and_membership_removed(self):
        self.add()
        bot=SimpleNamespace(token='TEST ONLY',send=Mock(return_value=True))
        self.assertEqual(cal.send_reminders(self.c,bot,NOW.replace(hour=8)),0)
        self.c.raw("UPDATE notify_settings SET muted_shops='{10}' WHERE user_id=2;")
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.c.raw("UPDATE notify_settings SET muted_shops=NULL WHERE user_id=2;")
        self.c.raw("UPDATE memberships SET shop_ids='{11}' WHERE user_id=2;")
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.c.raw("UPDATE memberships SET shop_ids='{10}' WHERE user_id=2; UPDATE notify_settings SET chat_id=NULL WHERE user_id=2;")
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.c.raw("UPDATE notify_settings SET chat_id=200,bot='notify' WHERE user_id=2;")
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        self.c.raw("UPDATE notify_settings SET bot='assistant' WHERE user_id=2; DELETE FROM memberships WHERE user_id=2;")
        self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        bot.send.assert_not_called()

    def test_task_completed_after_reservation_is_not_sent(self):
        eid=self.add()
        original=self.c.execute
        def complete_between_queries(query,args=()):
            result=original(query,args)
            if query.startswith('INSERT INTO calendar_reminders'):
                original("UPDATE calendar_entries SET status='done' WHERE id=%s",(eid,))
            return result
        bot=SimpleNamespace(token='TEST ONLY',send=Mock(return_value=True))
        with patch.object(self.c,'execute',side_effect=complete_between_queries):
            self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        bot.send.assert_not_called()
        self.assertEqual(original('SELECT state FROM calendar_reminders WHERE entry_id=%s',(eid,)).fetchone()['state'],'deferred')

    def test_window_closed_after_reservation_defers_without_losing_reminder(self):
        eid=self.add()
        original=self.c.execute
        def change_window(query,args=()):
            result=original(query,args)
            if query.startswith('INSERT INTO calendar_reminders'):
                original("UPDATE notify_settings SET send_from='11:00' WHERE user_id=2")
            return result
        bot=SimpleNamespace(token='TEST ONLY',send=Mock(return_value=True))
        with patch.object(self.c,'execute',side_effect=change_window):
            self.assertEqual(cal.send_reminders(self.c,bot,NOW),0)
        bot.send.assert_not_called()
        self.assertEqual(original('SELECT state FROM calendar_reminders WHERE entry_id=%s',(eid,)).fetchone()['state'],'deferred')
        self.assertEqual(cal.send_reminders(self.c,bot,NOW.replace(hour=11)),1)
        self.assertEqual(cal.send_reminders(self.c,bot,NOW.replace(hour=11)),0)

    def test_author_can_close_task_of_removed_assignee(self):
        eid=self.add(u={'id':1})
        self.c.raw('DELETE FROM memberships WHERE user_id=2;')
        cal.update(self.c,{'id':1},1,eid,{**self.values(),'status':'cancelled'},1)
        self.assertEqual(self.get(eid)['status'],'cancelled')
        with self.assertRaises(HTTPException):
            cal.update(self.c,{'id':1},1,eid,{**self.values(),'status':'open'},2)

    def test_moscow_boundary_and_overnight_notification_window(self):
        self.add(day=DAY+timedelta(days=2))
        self.c.raw("UPDATE notify_settings SET send_from='23:00',send_to='02:00' WHERE user_id=2;")
        bot=SimpleNamespace(token='TEST ONLY',send=Mock(return_value=True))
        utc=datetime(2026,11,4,22,tzinfo=timezone.utc) 
        self.assertEqual(cal.send_reminders(self.c,bot,utc),1)
        self.assertIn('Срок завтра: 06.11.2026',bot.send.call_args.args[1])

    def test_http_create_list_update_and_scope(self):
        app=stometric.web.app
        def user(): return self.u
        app.dependency_overrides[stometric.web.current_user]=user
        app.dependency_overrides[stometric.web.conn]=lambda:self.c
        async def inline(func, *args, **kw): return func(*args, **kw)
        async def requests():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
                payload={**self.values(),'day':str(DAY+timedelta(days=1)),'request_key':str(uuid4())}
                response=await client.post('/api/workspaces/1/calendar',json=payload)
                self.assertEqual(response.status_code,200,response.text)
                eid=response.json()['id']
                response=await client.get('/api/workspaces/1/calendar?start=2026-11-01&end=2026-11-30&actions=true')
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['items'][0]['id'],eid)
                self.assertEqual((await client.get('/api/workspaces/2/calendar/due')).status_code,403)
                self.assertEqual((await client.get('/api/workspaces/1/calendar?start=2026-11-01&end=2027-01-31')).status_code,400)
                response=await client.put(f'/api/workspaces/1/calendar/{eid}',json={**payload,'version':1,'status':'done'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual((await client.get('/api/workspaces/1/calendar/due')).json()['items'],[])
                self.assertEqual(self.c.execute("SELECT count(*) n FROM audit_log WHERE workspace_id=1").fetchone()['n'],2)
        try:
            
            
            with patch('fastapi.routing.run_in_threadpool',inline), patch('fastapi.dependencies.utils.run_in_threadpool',inline):
                asyncio.run(requests())
        finally: app.dependency_overrides.clear()


if __name__ == '__main__': unittest.main()

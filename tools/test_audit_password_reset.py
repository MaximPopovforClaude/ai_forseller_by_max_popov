"""Recovery regression tests: synthetic users only, never real Telegram/config.

RESET_TEST_PG=1 starts a disposable PostgreSQL with a private Unix socket in
/tmp. Real transactions and concurrent redemption are tested, no production DSN.
RESET_TEST_PG=single tests SQL without sockets; concurrent/rollback/HTTP tests
remain explicitly skipped in this mode.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import stometric.web  
import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException, Response
from starlette.requests import Request
from stometric import api_password_reset as api, auth, bots, mcp, password_reset as reset, web
from tools.test_calendar import Standalone

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = 'old-synthetic-password', 'new-synthetic-password'
OWNER = {'id': 1, 'is_active': True, 'is_superadmin': True}
REQ = Request({'type':'http','method':'POST','path':'/', 'headers':[(b'origin', reset.SITE.encode())],
               'client':('127.0.0.1', 5000)})


class RecoveryUnitTests(unittest.TestCase):
    def test_origin_mcp_and_token_validation(self):
        for headers in ([], [(b'origin', b'https://evil.example')]):
            with self.assertRaises(HTTPException):
                api.browser(Request({'type':'http','headers':headers}), Response())
        for token in ('', 'a'*42, '../'+'a'*40):
            with self.assertRaises(HTTPException): reset.token_hash(token)
        c = MagicMock()
        with self.assertRaises(HTTPException): reset.authorize(c, {**OWNER, '_mcp': {'id':1}}, 2)
        c.execute.assert_not_called()
        for kind in ('plugin', 'mcp'):
            g = {'id':1,'kind':kind,'workspace_id':1,'shops':None,'level':'platform','blocks':['platform:plugin']}
            for path in ('/api/admin/users/2/password-reset', '/api/workspaces/1/members/2/password-reset', '/api/auth/password-reset/confirm'):
                with self.assertRaises(mcp.Denied): mcp.check(g, 'POST', path, {})

    def test_unknown_telegram_cannot_start_registration_or_choose_target(self):
        c, bot = MagicMock(), MagicMock()
        c.execute.return_value.fetchone.return_value = None
        with patch.object(bots.db, 'connect') as connect:
            connect.return_value.__enter__.return_value = c
            bots.handle_register(bot, {'from': {'id':999}, 'text':'/start reset'})
        self.assertEqual(c.execute.call_count, 1)
        self.assertIn('ранее привязанный', bot.send.call_args.args[1])

    def test_frontend_real_react(self):
        for mode in ('development', 'production'):
            p = subprocess.run([shutil.which('node'), str(ROOT/'tools/frontend/password_reset.cjs'), str(ROOT)],
                capture_output=True, text=True, timeout=30, env={**os.environ, 'NODE_ENV':mode})
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)


FIXTURE = '''
CREATE TABLE users(id int PRIMARY KEY,email text UNIQUE,is_active boolean DEFAULT true,
    is_superadmin boolean DEFAULT false,telegram_id bigint,password_hash text,last_login_at timestamptz);
CREATE TABLE workspaces(id int PRIMARY KEY);
CREATE TABLE memberships(user_id int,workspace_id int,role text,shop_ids int[]);
CREATE TABLE sessions(token_hash text PRIMARY KEY,user_id int,expires_at timestamptz,ip text,user_agent text);
CREATE TABLE login_tokens(token_hash text PRIMARY KEY,user_id int,purpose text,expires_at timestamptz,used_at timestamptz);
CREATE TABLE audit_log(user_id int,workspace_id int,action text,details jsonb);
CREATE TABLE service_news(title text,body text,tabs text[]);
INSERT INTO workspaces VALUES(1),(2);
INSERT INTO users(id,email,is_superadmin,telegram_id) VALUES
 (1,'owner@example.test',true,1001),(2,'member@example.test',false,1002),
 (3,'admin@example.test',false,1003),(4,'viewer@example.test',false,1004),
 (5,'scoped@example.test',false,1005),(6,'unbound@example.test',false,NULL),
 (7,'foreign@example.test',false,1007),(8,'blocked@example.test',false,1008);
UPDATE users SET is_active=false WHERE id=8;
INSERT INTO memberships VALUES(3,1,'owner',NULL),(2,1,'editor','{1}'),(2,2,'owner',NULL),
 (4,1,'viewer',NULL),(5,1,'admin','{1}'),(6,1,'editor',NULL),(7,2,'owner',NULL);
'''


class SingleUser(Standalone):
    """Real SQL without sockets; explicitly NOT a concurrent transaction test."""
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): return False


@unittest.skipUnless(os.environ.get('RESET_TEST_PG') in ('1', 'single'), 'opt in: isolated PostgreSQL')
class RecoveryPgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='seller-analytics-reset-test-')
        cls.directory = Path(cls.tmp.name)
        cls.cluster = cls.directory/'db'
        cls.bin = '/usr/lib/postgresql/16/bin/'
        p = subprocess.run([cls.bin+'initdb','-D',str(cls.cluster),'-A','trust','-U','reset_test','--no-locale','--encoding=UTF8'],
                           capture_output=True, text=True, timeout=30)
        if p.returncode: raise AssertionError(p.stderr)
        cls.single = os.environ.get('RESET_TEST_PG') == 'single'
        if cls.single:
            cls.addClassCleanup(cls.tmp.cleanup)
            return
        cls.sock = cls.directory/'socket'; cls.sock.mkdir(mode=0o700)
        p = subprocess.run([cls.bin+'pg_ctl','-D',str(cls.cluster),'-l',str(cls.directory/'postgres.log'),
                            '-o',f"-F -k {cls.sock} -c listen_addresses='' -c max_connections=15 -c shared_buffers=16MB",'-w','start'],
                           capture_output=True, text=True, timeout=30)
        if p.returncode:
            reason = (cls.directory/'postgres.log').read_text()
            cls.tmp.cleanup()
            raise AssertionError(reason)
        cls.addClassCleanup(cls.shutdown)

    @classmethod
    def shutdown(cls):
        subprocess.run([cls.bin+'pg_ctl','-D',str(cls.cluster),'-m','fast','-w','stop'], capture_output=True, timeout=30)
        cls.tmp.cleanup()

    def connect(self, schema=True):
        if self.single:
            return SingleUser(self.cluster, self.schema if schema else 'public')
        return psycopg.connect(host=str(self.sock), dbname='postgres', user='reset_test', row_factory=dict_row,
                               options=f'-c statement_timeout=5000 -c search_path={self.schema if schema else "public"}')

    def setUp(self):
        self.schema = 'reset_' + uuid4().hex
        self.c = self.connect(False)
        fixture = f'CREATE SCHEMA {self.schema}; SET search_path={self.schema};' + FIXTURE
        migration = (ROOT/'stometric/migrations/110_password_reset.sql').read_text()
        if self.single:
            self.c.raw(fixture + migration)
            self.c.schema = self.schema
        else:
            self.c.execute(fixture)
            self.c.execute(migration)
        self.c.execute('UPDATE users SET password_hash=%s', (auth.hash_password(OLD),))
        self.c.commit()

    def tearDown(self):
        self.c.close()

    def issue(self, uid=2, actor=None, delivery='manual'):
        target = reset.authorize(self.c, actor or OWNER, uid)
        return reset.issue(self.c, target, (actor or OWNER)['id'], delivery)

    def token(self, link): return link['url'].split('#')[1]

    def test_manual_roundtrip_preserves_account_scope_and_old_access_until_saved(self):
        before = self.c.execute('SELECT * FROM memberships ORDER BY user_id,workspace_id').fetchall()
        session = auth.new_session(self.c, 2, None, None)
        old_magic = bots.new_token(self.c, 2, 'login', 1).rsplit('/',1)[1]
        link = self.issue()
        token = self.token(link)
        row = self.c.execute('SELECT * FROM password_reset_tokens').fetchone()
        self.assertEqual(row['token_hash'], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(row))
        dates = [datetime.fromisoformat(x) if isinstance(x,str) else x for x in (row['expires_at'],row['created_at'])]
        self.assertAlmostEqual((dates[0]-dates[1]).total_seconds(),1800,delta=2)
        self.assertIsNotNone(auth.session_user(self.c, session))
        self.assertEqual(reset.info(self.c, token)['email'], 'member@example.test')
        reset.complete(self.c, token, NEW)
        user = self.c.execute('SELECT * FROM users WHERE id=2').fetchone()
        self.assertTrue(auth.check_password(NEW, user['password_hash']))
        self.assertFalse(auth.check_password(OLD, user['password_hash']))
        self.assertIsNone(auth.session_user(self.c, session))
        with self.assertRaises(HTTPException): web._magic(self.c, old_magic)
        for f in (lambda: reset.info(self.c, token), lambda: reset.complete(self.c, token, NEW)):
            with self.assertRaises(HTTPException): f()
        self.assertEqual(self.c.execute('SELECT * FROM memberships ORDER BY user_id,workspace_id').fetchall(),before)
        audit = str(self.c.execute('SELECT * FROM audit_log').fetchall())
        for secret in (token, link['url'], OLD, NEW): self.assertNotIn(secret,audit)

    def test_rate_limit_reissue_expiry_blocked_account(self):
        first = self.issue()
        with self.assertRaises(HTTPException) as e: self.issue()
        self.assertEqual(e.exception.status_code,429)
        self.c.rollback()
        self.c.execute("UPDATE password_reset_tokens SET created_at=clock_timestamp()-interval '2 minutes'")
        self.c.commit()
        second = self.issue()
        with self.assertRaises(HTTPException): reset.info(self.c,self.token(first))
        self.c.execute("UPDATE password_reset_tokens SET expires_at=clock_timestamp()-interval '1 second'")
        self.c.commit()
        with self.assertRaises(HTTPException): reset.complete(self.c,self.token(second),NEW)
        self.c.rollback()
        with self.assertRaises(HTTPException): self.issue(uid=8)

    def test_hourly_rate_limit_and_migration_reapply(self):
        first = self.issue()
        
        self.c.execute("UPDATE password_reset_tokens SET created_at=clock_timestamp()-interval '2 minutes'")
        for n in range(4):
            self.c.execute("""INSERT INTO password_reset_tokens(token_hash,user_id,issued_by,delivery,status,created_at,expires_at)
                VALUES (%s,2,1,'manual','ready',clock_timestamp()-interval '2 minutes',clock_timestamp()+interval '10 minutes')""", (f'test-prior-{n}',))
        self.c.commit()
        with self.assertRaises(HTTPException) as err: self.issue()
        self.assertEqual(err.exception.status_code,429)
        self.c.rollback()
        migration=(ROOT/'stometric/migrations/110_password_reset.sql').read_text()
        if self.single: self.c.raw(migration)
        else: self.c.execute(migration); self.c.commit()
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
        self.assertEqual(reset.info(self.c,self.token(first))['email'],'member@example.test')

    def test_initial_password_magic_still_works_and_revokes_other_recovery_links(self):
        magic=bots.new_token(self.c,2,'set_password',24).rsplit('/',1)[1]
        link=self.issue()
        response=Response()
        web.magic_use(magic,web.MagicIn(password=NEW),REQ,response,c=self.c)
        self.assertIn('set-cookie',response.headers)
        with self.assertRaises(HTTPException): reset.info(self.c,self.token(link))
        with self.assertRaises(HTTPException): web.magic_use(magic,web.MagicIn(password=NEW),REQ,Response(),c=self.c)

    def test_permissions_and_missing_telegram(self):
        for actor, target, workspace in ((3,2,None),(4,2,1),(5,2,1),(3,7,1),(7,2,1),(1,2,1),(3,3,1),(1,1,None)):
            with self.subTest(actor=actor,target=target,workspace=workspace), self.assertRaises(HTTPException):
                reset.authorize(self.c, {'id':actor}, target, workspace)
            self.c.rollback()
        target = reset.authorize(self.c, {'id':3}, 2, 1)
        self.assertEqual(target['id'],2)
        self.c.rollback()
        with self.assertRaises(HTTPException): self.issue(uid=6,delivery='telegram')
        self.c.rollback()
        self.assertIn('url',self.issue(uid=6))

    def test_delivery_failure_revokes_link_and_success_returns_no_link_to_members(self):
        link = self.issue(delivery='telegram')
        with self.assertRaises(HTTPException): reset.info(self.c,self.token(link))
        bot = SimpleNamespace(token='synthetic', api=MagicMock(side_effect=RuntimeError('synthetic-secret')))
        with self.assertRaises(HTTPException) as err:
            reset.deliver(self.c, {'id':2,'email':'member@example.test','telegram_id':1002},1,None,link,bot)
        self.assertNotIn('synthetic-secret',str(err.exception))
        self.assertEqual(self.c.execute('SELECT status FROM password_reset_tokens').fetchone()['status'],'failed')
        with self.assertRaises(HTTPException): reset.info(self.c,self.token(link))
        self.c.rollback()
        self.c.execute("UPDATE password_reset_tokens SET created_at=clock_timestamp()-interval '2 minutes'"); self.c.commit()
        bot.api = MagicMock(return_value={'message_id':100})
        bot.http = MagicMock()
        with patch.object(bots,'Bot',return_value=bot):
            out = api.member_reset(1,2,REQ,Response(),u={'id':3},c=self.c)
        self.assertNotIn('url',out)
        self.assertEqual(bot.api.call_args.kwargs['chat_id'],1002)
        sent = self.c.execute('SELECT * FROM audit_log WHERE workspace_id=1').fetchall()
        self.assertEqual({r['action'] for r in sent},{'auth/password-reset:issued','auth/password-reset:sent'})

    def test_http_contract_headers_csrf_and_manual_link(self):
        if self.single: self.skipTest('ASGI threadpool wakeup blocked by runtime; direct endpoint contract tested separately')
        def connection():
            with self.connect() as c: yield c
        web.app.dependency_overrides[web.conn] = connection
        web.app.dependency_overrides[web.current_user] = lambda: OWNER
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app),base_url=reset.SITE) as client:
                path='/api/admin/users/2/password-reset'
                body={'delivery':'manual','confirm_email':'member@example.test'}
                r=await client.post(path,json=body)
                self.assertEqual(r.status_code,403)
                r=await client.post(path,json=body,headers={'Origin':reset.SITE})
                self.assertEqual(r.status_code,200,r.text)
                self.assertEqual(r.headers['cache-control'],'no-store')
                self.assertEqual(r.headers['referrer-policy'],'no-referrer')
                token=r.json()['url'].split('#')[1]
                r=await client.post('/api/auth/password-reset/confirm',json={'token':token,'password':NEW},headers={'Origin':reset.SITE})
                self.assertEqual(r.status_code,200,r.text)
                self.assertNotIn('set-cookie',r.headers)
                r=await client.post('/api/auth/password-reset/info',json={'token':token},headers={'Origin':reset.SITE})
                self.assertEqual(r.status_code,404)
                self.assertEqual(r.headers['cache-control'],'no-store')
        try: asyncio.run(run())
        finally: web.app.dependency_overrides.clear()

    def test_direct_endpoint_contract_and_wrong_user_confirmation(self):
        with self.assertRaises(HTTPException):
            api.admin_reset(2,api.IssueIn(delivery='manual',confirm_email='different@example.test'),REQ,Response(),u=OWNER,c=self.c)
        self.c.rollback()
        response = Response()
        out = api.admin_reset(2,api.IssueIn(delivery='manual',confirm_email='member@example.test'),REQ,response,u=OWNER,c=self.c)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertNotIn('digest',out)
        token = self.token(out)
        self.assertEqual(api.reset_info(api.TokenIn(token=token),REQ,Response(),c=self.c)['email'],'member@example.test')
        response = Response()
        self.assertEqual(api.reset_confirm(api.PasswordIn(token=token,password=NEW),REQ,response,c=self.c),{'ok':True})
        self.assertNotIn('set-cookie',response.headers)

    def test_self_service_and_blocked_after_issue(self):
        fake = SimpleNamespace(token='synthetic',api=MagicMock(return_value={'message_id':101}),send=MagicMock())
        with patch.object(bots.db,'connect',side_effect=self.connect):
            bots.handle_register(fake,{'from':{'id':1002},'text':'/start reset'})
        self.assertEqual(fake.api.call_args.kwargs['chat_id'],1002)
        self.assertIsNone(fake.send.call_args)
        row=self.c.execute('SELECT * FROM password_reset_tokens').fetchone()
        self.assertEqual(row['issued_by'],2)
        self.assertEqual(row['status'],'ready')
        token=fake.api.call_args.kwargs['text'].split('/reset-password#')[1].split()[0]
        self.c.execute('UPDATE users SET is_active=false WHERE id=2'); self.c.commit()
        with self.assertRaises(HTTPException): reset.complete(self.c,token,NEW)

    def test_atomic_one_time_consumption_under_concurrent_requests(self):
        if self.single: self.skipTest('Unix socket unavailable: concurrent transactions require multiuser PostgreSQL')
        token = self.token(self.issue())
        start = threading.Barrier(2)
        def use():
            with self.connect() as c:
                start.wait(timeout=5)
                try: reset.complete(c,token,NEW); return 200
                except HTTPException as e: return e.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(use) for _ in range(2)]
            results=[f.result(timeout=10) for f in futures]
        self.assertEqual(sorted(results),[200,404])
        self.assertEqual(self.c.execute("SELECT count(*) n FROM audit_log WHERE action='auth/password-reset:completed'").fetchone()['n'],1)

    def test_failure_rolls_back_password_sessions_and_consumption(self):
        if self.single: self.skipTest('Per-query standalone adapter cannot test application rollback')
        token=self.token(self.issue())
        session=auth.new_session(self.c,2,None,None)
        with self.assertRaises(RuntimeError), self.connect() as c, patch.object(reset,'audit',side_effect=RuntimeError('test rollback')):
            reset.complete(c,token,NEW)
        self.assertIsNotNone(auth.session_user(self.c,session))
        self.assertIsNotNone(reset.info(self.c,token))
        self.assertTrue(auth.check_password(OLD,self.c.execute('SELECT password_hash FROM users WHERE id=2').fetchone()['password_hash']))

    def test_login_and_magic_waiting_for_reset_cannot_restore_old_access(self):
        if self.single: self.skipTest('Unix socket unavailable: concurrent transactions require multiuser PostgreSQL')
        token=self.token(self.issue())
        magic=bots.new_token(self.c,2,'login',1).rsplit('/',1)[1]
        reset.lock_users(self.c,[2])
        started=threading.Barrier(3)
        def login(kind):
            with self.connect() as c:
                started.wait(timeout=5)
                try:
                    if kind=='password': web.login(web.Login(email='member@example.test',password=OLD),REQ,Response(),c)
                    else: web.magic_use(magic,web.MagicIn(),REQ,Response(),c)
                    return 200
                except HTTPException as e: return e.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(login,kind) for kind in ('password','magic')]
            started.wait(timeout=5)
            time.sleep(.1)
            reset.complete(self.c,token,NEW)
            self.assertEqual([f.result(timeout=10) for f in futures],[401,404])
        self.assertEqual(self.c.execute('SELECT count(*) n FROM sessions WHERE user_id=2').fetchone()['n'],0)


if __name__ == '__main__': unittest.main()

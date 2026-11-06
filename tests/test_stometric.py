"""Public Stometric acceptance: synthetic SQL/users/keys and mocked external services only."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, time as dtime
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stometric.web  # API modules require web initialization first.
from stometric import assistant, api_assistant, api_billing, auth, bots, config, llm, vault, news
from stometric import bot_runtime as runtime, bot_transport as transport
from test_installation import SQL, Cursor, module


class Rows(Cursor):
    def __iter__(self): return iter(self.rows)


class DB(SQL):
    def execute(self, query, args=()):
        rows = super().execute(query, args).rows
        for row in rows:
            for key, value in list(row.items()):
                if key == 'enc' and isinstance(value, str) and value.startswith('\\x'):
                    row[key] = bytes.fromhex(value[2:])
                elif key.endswith('_at') and isinstance(value, str):
                    row[key] = datetime.fromisoformat(value)
                elif key in ('daily_time','send_from','send_to') and isinstance(value, str):
                    row[key] = dtime.fromisoformat(value)
        return Rows(rows)
    def commit(self): pass
    def rollback(self): pass
    def __enter__(self): return self
    def __exit__(self, *_): pass


class FakeBot:
    token = 'synthetic';username = 'synthetic_bot'
    def __init__(self): self.sent=[]
    def send(self, who, text, **kw): self.sent.append(text);return True
    def send_id(self,*args,**kw):self.send(*args,**kw);return 1
    def api(self,*a,**kw):return True
    def edit(self,*a,**kw):pass
    def doc(self,*a,**kw):return True


class SQLAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg=Path('/usr/lib/postgresql/16/bin')
        if os.getuid()==0 or not (pg/'initdb').exists():
            raise unittest.SkipTest('Unprivileged PostgreSQL 16 required')
        cls.tmp=tempfile.TemporaryDirectory(prefix='stometric-public-test-')
        cls.cluster=Path(cls.tmp.name)/'pg'
        subprocess.run([str(pg/'initdb'),'-D',str(cls.cluster),'-A','trust','--no-locale','--encoding=UTF8'],capture_output=True,check=True)
        cls.c=DB(cls.cluster,pg/'postgres')
        for migration in sorted((ROOT/'stometric/migrations').glob('*.sql')):cls.c.raw(migration.read_text())
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(config,'env',return_value={'SITE_URL':'https://analytics.example.org','AIS_MASTER_KEY':Fernet.generate_key().decode()}))
        self.stack.enter_context(patch.object(bots.db,'connect',return_value=self.c))
        self.c.raw('TRUNCATE users,workspaces,app_settings RESTART IDENTITY CASCADE;')
        self.uid,self.ws=module('bootstrap_fixture','scripts/bootstrap.py').create(self.c,'owner@example.invalid','Synthetic-password-123','Example')
        self.shop=self.c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('fixture-shop',%s) RETURNING id",(self.ws,)).fetchone()['id']
        self.other=self.c.execute("INSERT INTO users(email,name) VALUES ('other@example.invalid','Other') RETURNING id").fetchone()['id']
        self.user=self.c.execute('SELECT * FROM users WHERE id=%s',(self.uid,)).fetchone()
        self.add_key()
        self.bot=FakeBot()
    def add_key(self):
        enc=vault.encrypt(llm.to_secret('openai','synthetic-api-value','fixture-model'))
        self.c.execute("INSERT INTO workspace_secrets(workspace_id,kind,enc,added_by) VALUES (%s,'claude',%s,%s)",(self.ws,enc,self.uid))
    def flag(self,key,value):
        self.c.execute('INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value',(key,json.dumps(value)))
    def link(self):
        self.c.execute("INSERT INTO tg_link_codes(code,user_id,expires_at) VALUES ('fixture-code',%s,now()+interval '30 minutes')",(self.uid,))
        return bots._link_user(self.bot,self.c,70001,'/start fixture-code')
    def test_site_status_requires_explicit_membership_and_key(self):
        self.assertTrue(api_assistant.status(self.shop,self.user,self.c)['ok'])
        self.assertFalse(assistant.access(self.c,self.shop,self.other)['ok'])
        self.c.execute('DELETE FROM workspace_secrets')
        self.assertFalse(api_assistant.status(self.shop,self.user,self.c)['ok'])
    def test_link_is_single_use_and_inactive_user_cannot_link(self):
        self.assertEqual(self.link(),self.uid)
        self.assertIsNone(bots._link_user(self.bot,self.c,70002,'/start fixture-code'))
        self.c.execute('UPDATE users SET is_active=false WHERE id=%s',(self.uid,))
        self.c.execute("INSERT INTO tg_link_codes(code,user_id,expires_at) VALUES ('inactive-code',%s,now()+interval '30 minutes')",(self.uid,))
        self.assertIsNone(bots._link_user(self.bot,self.c,70003,'/start inactive-code'))
    def test_expired_link_and_unknown_telegram_are_rejected(self):
        self.c.execute("INSERT INTO tg_link_codes(code,user_id,expires_at) VALUES ('expired',%s,now()-interval '1 second')",(self.uid,))
        self.assertIsNone(bots._link_user(self.bot,self.c,70002,'/start expired'))
        self.assertIsNone(bots._link_user(self.bot,self.c,70002,'/start'))
    def test_relink_clears_old_recipient(self):
        self.c.execute('UPDATE users SET telegram_id=70001 WHERE id=%s',(self.other,))
        self.c.execute('INSERT INTO notify_settings(user_id,chat_id) VALUES (%s,70001)',(self.other,))
        self.assertEqual(self.link(),self.uid)
        self.assertIsNone(self.c.execute('SELECT telegram_id FROM users WHERE id=%s',(self.other,)).fetchone()['telegram_id'])
        self.assertIsNone(self.c.execute('SELECT chat_id FROM notify_settings WHERE user_id=%s',(self.other,)).fetchone()['chat_id'])
    def test_start_shop_stop_and_revoked_membership(self):
        self.link()
        message=lambda text:{'from':{'id':70001},'text':text}
        bots.handle_assistant(self.bot,message('/start'))
        row=self.c.execute('SELECT bot,chat_id FROM notify_settings WHERE user_id=%s',(self.uid,)).fetchone()
        self.assertEqual(row,{'bot':'assistant','chat_id':70001})
        self.assertEqual(bots._as_shop(self.c,self.uid)['id'],self.shop)
        bots.handle_assistant(self.bot,message('/stop'))
        self.assertIsNone(self.c.execute('SELECT chat_id FROM notify_settings WHERE user_id=%s',(self.uid,)).fetchone()['chat_id'])
        self.c.execute('UPDATE memberships SET shop_ids=ARRAY[]::int[] WHERE user_id=%s',(self.uid,))
        self.assertIsNone(bots._as_shop(self.c,self.uid))
        self.assertFalse(assistant.access(self.c,self.shop,self.uid)['ok'])
    def test_site_and_telegram_share_api_engine_and_saved_history(self):
        reply={'content':[{'type':'text','text':'Synthetic response: no source rows.'}]}
        with patch.object(llm,'messages',return_value=reply) as api:
            ch=api_assistant.new_chat(api_assistant.NewChat(shop_id=self.shop),self.user,self.c)
            chat=self.c.execute('SELECT * FROM assistant_chats WHERE id=%s',(ch['id'],)).fetchone()
            pid,_=assistant.ask(self.c,self.uid,chat,'Fixture question',[])
            assistant.answer(pid)
            self.link()
            bots.handle_assistant(self.bot,{'from':{'id':70001},'text':'/start'})
            def synchronous(mid):
                assistant.answer(mid)
                return types.SimpleNamespace(is_alive=lambda:False)
            with patch.object(assistant,'start',side_effect=synchronous):
                bots._as_ask(self.bot,70001,self.uid,'Fixture Telegram question',[])
        self.assertEqual(api.call_count,2)
        rows=self.c.execute("SELECT status,model FROM assistant_messages WHERE role='assistant' ORDER BY id").fetchall()
        self.assertEqual(rows,[{'status':'done','model':'fixture-model'}]*2)
        self.assertTrue(any('Synthetic response' in x for x in self.bot.sent))
        sources=self.c.execute("SELECT details->>'source' source FROM audit_log WHERE action='assistant/ask' ORDER BY id").fetchall()
        self.assertEqual(sources,[{'source':'site'},{'source':'telegram'}])
        self.assertEqual(len(api_assistant.chats(self.shop,self.user,self.c)),2)
        with self.assertRaises(Exception):api_assistant.get_chat(ch['id'],{'id':self.other},self.c)
    def test_ai_tool_cannot_read_an_ungranted_shop(self):
        foreign=self.c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('ungranted',%s) RETURNING id",(self.ws,)).fetchone()['id']
        self.c.execute('UPDATE memberships SET shop_ids=%s WHERE user_id=%s',([self.shop],self.uid))
        ch=api_assistant.new_chat(api_assistant.NewChat(shop_id=self.shop),self.user,self.c)
        chat=self.c.execute('SELECT * FROM assistant_chats WHERE id=%s',(ch['id'],)).fetchone()
        pid,_=assistant.ask(self.c,self.uid,chat,'Fixture scope question',[])
        replies=[{'content':[{'type':'tool_use','id':'fixture-call','name':'get_table','input':{'shop_id':foreign,'tab':'home'}}]},
                 {'content':[{'type':'text','text':'Access unavailable.'}]}]
        with patch.object(llm,'messages',side_effect=replies) as api,patch.dict(assistant.TOOL_FN,{'get_table':MagicMock()}) as fns:
            assistant.answer(pid)
            fns['get_table'].assert_not_called()
        tool_messages=api.call_args.args[1]['messages']
        self.assertTrue(any('недоступен' in b.get('content','') for m in tool_messages if isinstance(m.get('content'),list) for b in m['content']))
    def test_revocation_between_queue_and_answer_prevents_api_call(self):
        ch=api_assistant.new_chat(api_assistant.NewChat(shop_id=self.shop),self.user,self.c)
        chat=self.c.execute('SELECT * FROM assistant_chats WHERE id=%s',(ch['id'],)).fetchone()
        pid,_=assistant.ask(self.c,self.uid,chat,'Fixture pending question',[])
        self.c.execute('UPDATE memberships SET shop_ids=ARRAY[]::int[] WHERE user_id=%s',(self.uid,))
        with patch.object(llm,'messages') as api,patch.object(assistant.traceback,'print_exc'):
            assistant.answer(pid)
        api.assert_not_called()
        self.assertEqual(self.c.execute('SELECT status FROM assistant_messages WHERE id=%s',(pid,)).fetchone()['status'],'error')
    def test_background_flags_default_off_and_boolean_only(self):
        self.assertFalse(any(runtime.settings(self.c).values()))
        self.flag('stometric_morning_ai','true')
        self.assertFalse(runtime.settings(self.c)['stometric_morning_ai'])
        api_billing.admin_setting_set('stometric_notifications',api_billing.SettingIn(value=True),self.user,self.c)
        self.assertTrue(runtime.settings(self.c)['stometric_notifications'])
        with self.assertRaises(Exception):api_billing.admin_setting_set('stometric_notifications',api_billing.SettingIn(value=1),self.user,self.c)
        with self.assertRaises(Exception):api_billing.admin_setting_set('stometric_notifications',api_billing.SettingIn(value=True),{'is_superadmin':False},self.c)
    def test_scheduler_with_only_stometric_and_no_implicit_ai(self):
        now=datetime(2026,1,2,12,30,tzinfo=bots.MSK)
        with patch.object(runtime.threading,'Thread') as thread,patch.object(bots,'ASSIST',self.bot),patch.object(bots,'NOTIFY',None),\
             patch.object(news,'sync_changes') as changes,patch.object(news,'sync_spp'),patch.object(news,'send_pending'),\
             patch.object(bots,'flush_queue') as flush:
            runtime.tick(bots,self.c,now)
            thread.assert_not_called();changes.assert_not_called()
            self.flag('stometric_notifications',True)
            runtime.tick(bots,self.c,now)
            changes.assert_called_once();flush.assert_called_once()
            self.assertEqual(thread.call_args.kwargs['target'],bots._calendar_jobs)
            self.assertEqual(thread.call_count,1)
    def test_paid_slots_require_flag_and_are_not_repeated(self):
        now=datetime(2026,1,2,12,30,tzinfo=bots.MSK)
        self.flag('stometric_morning_ai',True);self.flag('stometric_ads_ai',True)
        with patch.object(runtime.threading,'Thread') as thread:
            runtime.tick(bots,self.c,now)
            runtime.tick(bots,self.c,now)
        self.assertEqual(thread.call_count,2)
    def test_token_encrypted_and_diagnostic_does_not_return_it(self):
        token='123456:'+('fixture_'*4)
        with patch.object(bots.httpx,'post',return_value=types.SimpleNamespace(json=lambda:{'ok':True,'result':{'username':'fixture_bot'}})):
            self.assertEqual(bots.set_assistant_token(self.c,token),'fixture_bot')
        value=self.c.execute("SELECT value FROM app_settings WHERE key='tg_assistant_bot'").fetchone()['value']
        self.assertNotIn(token,json.dumps(value))
        self.assertEqual(bots.assistant_token(self.c),token)
        check=module('check_stometric_fixture','scripts/check_stometric.py')
        result=check.inspect(self.c,self.uid,self.shop)
        self.assertTrue(result['ai_ready']);self.assertTrue(result['telegram_configured'])
        self.assertNotIn(token,json.dumps(result));self.assertNotIn('enc',result)
        self.assertFalse(result['telegram_checked'])
        fake=types.SimpleNamespace(token=token,username='fixture_bot',http=MagicMock(),
                                   api=lambda *a:{'url':'https://private.example.invalid/webhook/fixture'})
        with patch.object(bots,'Bot',return_value=fake): checked=check.inspect(self.c,self.uid,self.shop,True)
        self.assertTrue(checked['webhook_present']);self.assertTrue(checked['bot_matches'])
        self.assertNotIn('private.example',json.dumps(checked))


class RuntimeAcceptance(unittest.TestCase):
    def test_process_lock_prevents_duplicate_poller(self):
        with tempfile.TemporaryDirectory() as directory:
            with runtime.exclusive_process(Path(directory)):
                with self.assertRaises(SystemExit):
                    with runtime.exclusive_process(Path(directory)):pass
            with runtime.exclusive_process(Path(directory)):pass
    def test_standalone_start_includes_scheduler_without_legacy_token(self):
        fake=types.SimpleNamespace(config=types.SimpleNamespace(env=lambda:{}),db=types.SimpleNamespace(connect=lambda:MagicMock()),
                                   assistant_token=lambda c:'fixture',Bot=lambda *a:types.SimpleNamespace(token=None),
                                   assistant_loop=lambda:None,scheduler=lambda:None)
        with patch.object(runtime.threading,'Thread') as th,redirect_stdout(io.StringIO()):
            th.return_value.is_alive.return_value=False
            with self.assertRaises(SystemExit):runtime.run(fake)
        self.assertEqual([x.kwargs['target'] for x in th.call_args_list],[fake.assistant_loop,fake.scheduler])
    def test_duplicate_role_tokens_fail_before_polling(self):
        fake=types.SimpleNamespace(config=types.SimpleNamespace(env=lambda:{'TG_BOT_NOTIFY_TOKEN':'fixture'}),
                                   db=types.SimpleNamespace(connect=lambda:MagicMock()),assistant_token=lambda c:'fixture')
        with patch.object(runtime.threading,'Thread') as thread,self.assertRaises(SystemExit):runtime.run(fake)
        thread.assert_not_called()
    def test_transport_never_prints_secret_url_on_network_failure(self):
        out=io.StringIO();token='123456:'+('fixture_'*4)
        client=MagicMock();client.post.side_effect=RuntimeError('https://api.telegram.org/bot'+token+'/getMe')
        with patch.object(transport.httpx,'Client',return_value=client),redirect_stdout(out):
            bot=transport.Bot('',token)
        self.assertIsNone(bot.token);self.assertNotIn(token,out.getvalue())
    def test_http_error_discards_untrusted_description(self):
        client=MagicMock();client.post.return_value.json.return_value={'ok':True,'result':{'username':'fixture_bot'}}
        with patch.object(transport.httpx,'Client',return_value=client):bot=transport.Bot('','fixture-token')
        client.post.return_value.json.return_value={'ok':False,'error_code':409,'description':'fixture-token'}
        with self.assertRaisesRegex(transport.BotError,'^Telegram API error 409$'):bot.api('getUpdates')
    def test_file_size_limit_before_download(self):
        client=MagicMock();client.post.return_value.json.return_value={'ok':True,'result':{'username':'fixture_bot'}}
        with patch.object(transport.httpx,'Client',return_value=client):bot=transport.Bot('','fixture-token')
        with patch.object(bot,'api',return_value={'file_size':transport.MAX_FILE+1,'file_path':'files/test.pdf'}),self.assertRaises(transport.BotError):bot.download('fixture')
        client.stream.assert_not_called()


if __name__=='__main__':unittest.main()

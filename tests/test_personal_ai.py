"""Personal route: real disposable SQL and fake official RPC, never live accounts."""
import asyncio
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import stometric.web
from stometric import owner_ai as owner, owner_runtime as runtime, owner_policy as policy, vip_image as vip
from stometric import ai_routing, aireport, private_ai, private_image_actor, visual_render, api_billing, api_owner_ai
from test_installation import SQL, module


def png():
    out=io.BytesIO();Image.new('RGB',(20,20),'red').save(out,'PNG');return out.getvalue()


def allowance():
    b={'primary':{'usedPercent':10},'credits':{'hasCredits':False,'unlimited':False,'balance':'0'}}
    return {'accountId':'synthetic','ordinaryUsageAllowed':True,'rateLimits':b,'rateLimitsByLimitId':{'codex':copy.deepcopy(b)}}


class FakeRPC:
    def __init__(self,notify=None,request=None):
        self.notify,self.request=notify,request;self.calls=[];self.overrides={};self.mode='text';self.expected={};self.extra_image=False
    async def start(self,cwd):self.cwd=cwd
    async def close(self):pass
    async def wait_closed(self):await asyncio.Future()
    async def call(self,method,params,**kw):
        self.calls.append((method,params))
        if method in self.overrides:return self.overrides[method]
        if method=='hooks/list':return {'data':[{'hooks':[{'eventName':'preToolUse','command':runtime.policy_command(),'enabled':True,'trustStatus':'trusted'}]}]}
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='model/list':return {'data':[{'isDefault':True,'model':'synthetic-model'}]}
        if method=='modelProvider/capabilities/read':return {'imageGeneration':True}
        if method=='account/rateLimits/read':return allowance()
        if method=='thread/start':
            self.mode='image' if params['config']['features.image_generation'] else 'text'
            return {'thread':{'id':'synthetic-thread'},'modelProvider':'openai','approvalPolicy':'never','sandbox':{'type':'readOnly'},'activePermissionProfile':{'id':'personal','extends':':read-only'}}
        if method=='mcpServerStatus/list':return {'data':[]}
        if method=='turn/start':
            if self.mode=='image':
                item={'type':'imageGeneration','id':'image1','status':'completed','inputImages':[{'path':k,'sha256':v} for k,v in self.expected.items()],'result':base64.b64encode(png()).decode()}
                await self.notify('item/started',{'threadId':'synthetic-thread','turnId':'turn1','item':item})
                if self.extra_image:await self.notify('item/started',{'threadId':'synthetic-thread','turnId':'turn1','item':dict(item,id='image2')})
                await self.notify('item/completed',{'threadId':'synthetic-thread','turnId':'turn1','item':item})
            else:
                if self.request:
                    result=await self.request('item/tool/call',{'tool':'ais_read_dossier','arguments':{'offset':2,'length':3}})
                    self.dossier_result=result
                await self.notify('item/completed',{'threadId':'synthetic-thread','turnId':'turn1','item':{'type':'agentMessage','phase':'final_answer','text':'Synthetic answer'}})
            await self.notify('turn/completed',{'threadId':'synthetic-thread','turn':{'id':'turn1','status':'completed'}})
            return {'turn':{'id':'turn1'}}
        raise AssertionError(method)


class RuntimeTests(unittest.TestCase):
    def run_rpc(self, mode='text', overrides=None, expected=None, extra=False):
        def factory(notify=None,request=None):
            self.rpc=FakeRPC(notify,request);self.rpc.overrides=overrides or {};self.rpc.expected=expected or {};self.rpc.extra_image=extra;return self.rpc
        with patch.object(runtime,'client',side_effect=factory),patch.object(owner,'recheck',return_value={}):
            return asyncio.run(runtime.run(owner.OwnerKey(1,1,False,'r'),Path('/synthetic'),'System','Question',[],mode,dossier='abcdef' if mode=='text' else None,expected=expected or {}))
    def test_text_uses_official_route_and_readonly_dossier(self):
        r=self.run_rpc();self.assertEqual(r['text'],'Synthetic answer')
        self.assertEqual(json.loads(self.rpc.dossier_result['contentItems'][0]['text'])['text'],'cde')
        self.assertEqual(sum(m=='turn/start' for m,p in self.rpc.calls),1)
        opts=next(p for m,p in self.rpc.calls if m=='thread/start')
        self.assertEqual(opts['permissions'],'personal');self.assertFalse(opts['config']['features.shell_tool']);self.assertFalse(opts['config']['features.image_generation'])
    def test_image_requires_verified_refs_and_one_call(self):
        expected={'/synthetic/a.png':hashlib.sha256(png()).hexdigest()}
        self.assertEqual(self.run_rpc('image',expected=expected),png())
        with self.assertRaises(runtime.OwnerError):self.run_rpc('image',expected=expected,extra=True)
    def test_rejects_unsafe_runtime_before_dispatch(self):
        bads=[{'account/read':{'account':{'type':'apiKey'}}}, {'hooks/list':{'data':[]}},
          {'mcpServerStatus/list':{'data':[{'tools':{'shell':{}}}]}},
          {'account/rateLimits/read':{}}, {'model/list':{'data':[]}},
          {'thread/start':{'thread':{'id':'x'},'sandbox':{'type':'dangerFullAccess'}}}]
        for bad in bads:
            with self.subTest(method=list(bad)),self.assertRaises(Exception):self.run_rpc(overrides=bad)
            self.assertFalse(any(m=='turn/start' for m,p in self.rpc.calls))
        with self.assertRaises(runtime.OwnerError):self.run_rpc('image',overrides={'modelProvider/capabilities/read':{'imageGeneration':False}})
        self.assertFalse(any(m=='turn/start' for m,p in self.rpc.calls))
    def test_no_bare_subscription_key_or_api_fallback(self):
        with self.assertRaises(RuntimeError),patch.object(runtime,'client') as rpc:
            aireport._cli('system','question',key='subscription')
        rpc.assert_not_called()
    def test_quota_exhaustion_unknown_and_paid_credit_block(self):
        for change in ({'ordinaryUsageAllowed':False},{'ordinaryUsageAllowed':None},{'accountId':None}):
            with self.assertRaises(vip.ImageError):vip.included_allowance(dict(allowance(),**change))
        for credits in ({'hasCredits':True,'unlimited':False,'balance':'1'},{'hasCredits':False,'unlimited':False,'balance':None}):
            value=allowance();value['rateLimits']['credits']=credits
            with self.assertRaises(vip.ImageError):vip.included_allowance(value)
    def test_diagnostic_has_no_generation(self):
        rpc=FakeRPC()
        with patch.object(runtime,'client',return_value=rpc):result=asyncio.run(runtime._probe(Path('/synthetic')))
        self.assertTrue(result['text_ready']);self.assertTrue(result['image_ready'])
        self.assertFalse(any(m=='turn/start' for m,p in rpc.calls))
    def test_no_shell_reference_swap_or_second_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=Path(tmp)/'jobs';jobs.mkdir();control=Path(tmp)/'control';control.mkdir();folder=jobs/'job-test';folder.mkdir()
            ref=folder/'ref.png';ref.write_bytes(png());expected={str(ref):hashlib.sha256(png()).hexdigest()}
            manifest=control/'job-test.json';manifest.write_text(json.dumps({'mode':'image','refs':expected}))
            with patch.object(policy,'JOBS',jobs),patch.object(policy,'CONTROL',control):
                good={'cwd':str(folder),'tool_name':'image_gen.imagegen','tool_input':{'referenced_image_paths':[str(ref)]}}
                for ev in (dict(good,tool_name='exec_command'),dict(good,tool_input={'referenced_image_paths':['/wrong']})):
                    with self.assertRaises(ValueError):policy.check(ev)
                policy.check(good)
                with self.assertRaises(FileExistsError):policy.check(good)
                manifest.write_text(json.dumps({'mode':'text','refs':{}}))
                policy.check({'cwd':str(folder),'tool_name':'ais_read_dossier'})
                with self.assertRaises(ValueError):policy.check(good)
    def test_hook_command_quotes_installation_path(self):
        import shlex
        from stometric import owner_paths
        path=Path("/tmp/synthetic&special's folder/owner_policy.py")
        with patch.object(owner_paths,'POLICY',path):
            self.assertEqual(shlex.split(owner_paths.policy_command()),['python3',str(path)])
    def test_setup_uses_separate_profile_and_does_not_overwrite_custom_hook(self):
        import tomllib
        setup=module('personal_setup','scripts/personal_ai.py')
        cfg=tomllib.loads(setup.configuration())
        self.assertEqual(cfg['permissions']['personal']['filesystem'][':root'],'deny')
        self.assertTrue(cfg['features']['image_generation'])
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);profile=folder/'codex';profile.mkdir();target=profile/'config.toml'
            custom=setup.configuration().replace('matcher = "*"','matcher = "exec_command"');target.write_text(custom)
            with patch.multiple(setup,BASE=folder,PROFILE=profile,JOBS=folder/'jobs',CONTROL=folder/'control'),patch.object(setup,'binary',return_value='/synthetic/codex'):
                with self.assertRaises(setup.SetupError):asyncio.run(setup.setup())
            self.assertEqual(target.read_text(),custom)


class ScopeSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pg=Path('/usr/lib/postgresql/16/bin')
        if os.getuid()==0 or not (pg/'initdb').exists():raise unittest.SkipTest('unprivileged PostgreSQL 16 required')
        cls.temp=tempfile.TemporaryDirectory();cluster=Path(cls.temp.name)/'pg'
        subprocess.run([str(pg/'initdb'),'-D',str(cluster),'-A','trust','--no-locale','--encoding=UTF8'],capture_output=True,check=True)
        cls.c=SQL(cluster,pg/'postgres')
        for migration in sorted((ROOT/'stometric/migrations').glob('*.sql')):cls.c.raw(migration.read_text())
        cls.uid,cls.ws=module('bootstrap_owner','scripts/bootstrap.py').create(cls.c,'owner@example.invalid','Synthetic-test-only-123','Owner')
        cls.shop=cls.c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('own-shop',%s) RETURNING id",(cls.ws,)).fetchone()['id']
        cls.other=cls.c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('unselected',%s) RETURNING id",(cls.ws,)).fetchone()['id']
        cls.client=cls.c.execute("INSERT INTO workspaces(name,plan) VALUES ('Client','mcp') RETURNING id").fetchone()['id']
        cls.cs=cls.c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('client-shop',%s) RETURNING id",(cls.client,)).fetchone()['id']
        cls.c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES (%s,%s,'admin')",(cls.client,cls.uid))
        cls.c.execute("INSERT INTO workspace_secrets(workspace_id,kind,enc,added_by) VALUES (%s,'claude',%s,%s)",(cls.client,b'synthetic',cls.uid))
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.c.execute('DELETE FROM app_settings WHERE key=%s',(owner.SETTING,))
        self.c.execute("UPDATE memberships SET role='owner',shop_ids=NULL WHERE workspace_id=%s AND user_id=%s",(self.ws,self.uid))
        self.c.execute('UPDATE accounts SET is_active=true,archived_at=NULL WHERE id=%s',(self.shop,))
        self.c.execute("UPDATE workspaces SET plan='mcp' WHERE id=%s",(self.ws,))
    def configure(self):return owner.save(self.c,self.uid,self.ws,[self.shop],True,{'text_ready':True,'image_ready':True,'model':'synthetic'})
    def test_plan_exists_but_new_install_has_no_subscription(self):
        self.assertFalse(self.c.execute("SELECT active FROM plans WHERE key='owner'").fetchone()['active'])
        self.assertIsNone(owner.key_for(self.c,self.shop,self.uid))
        with self.assertRaises(Exception):owner.save(self.c,self.uid,self.ws,[self.shop],True,{})
    def test_selected_owner_only_and_client_always_api(self):
        self.configure()
        self.assertTrue(ai_routing.shop_route(self.c,self.shop,self.uid)['ai_ready'])
        self.assertIsInstance(aireport.shop_key(self.c,self.shop,self.uid),owner.OwnerKey)
        for sid,uid in ((self.shop,None),(self.shop,self.uid+99),(self.other,self.uid),(self.cs,self.uid)):
            self.assertIsNone(owner.key_for(self.c,sid,uid))
        with private_ai.scheduled_ai(self.c):self.assertIsInstance(owner.key_for(self.c,self.shop),owner.OwnerKey)
        self.assertEqual(ai_routing.shop_route(self.c,self.cs,self.uid)['ai_route'],'workspace_api')
        self.assertTrue(ai_routing.shop_route(self.c,self.cs,self.uid)['ai_ready'])
        with self.assertRaises(Exception):owner.save(self.c,self.uid,self.ws,[self.cs],True,{'text_ready':True})
    def test_membership_shop_archive_and_revision_revocation(self):
        self.configure();key=owner.key_for(self.c,self.shop,self.uid)
        @contextmanager
        def connect():yield self.c
        from stometric import db
        with patch.object(db,'connect',connect):
            owner.recheck(key)
            self.c.execute('UPDATE memberships SET shop_ids=ARRAY[]::int[] WHERE workspace_id=%s AND user_id=%s',(self.ws,self.uid))
            with self.assertRaises(RuntimeError):owner.recheck(key)
            self.c.execute('UPDATE memberships SET shop_ids=NULL WHERE workspace_id=%s AND user_id=%s',(self.ws,self.uid))
            self.c.execute('UPDATE accounts SET archived_at=now(),is_active=false WHERE id=%s',(self.shop,))
            with self.assertRaises(RuntimeError):owner.recheck(key)
            self.c.execute('UPDATE accounts SET archived_at=NULL,is_active=true WHERE id=%s',(self.shop,))
            self.configure()
            with self.assertRaises(RuntimeError):owner.recheck(key)
    def test_no_admin_dropdown_shortcut_or_member_images(self):
        u={'id':self.uid,'is_superadmin':True,'is_active':True}
        with self.assertRaises(Exception):api_billing.admin_ws_set(self.ws,api_billing.AdminWsIn(plan='owner'),u,self.c)
        self.configure()
        with self.assertRaises(Exception):api_billing.admin_ws_set(self.client,api_billing.AdminWsIn(plan='owner'),u,self.c)
        self.assertTrue(private_image_actor.allowed(self.c,self.shop,self.uid))
        self.assertFalse(private_image_actor.allowed(self.c,self.shop,self.uid+99))
        with patch.object(visual_render.hf,'connected',return_value=False),patch.object(visual_render.oi,'connected',return_value=False):
            models=visual_render.models(self.c,self.shop,self.uid)
            self.assertTrue(next(x for x in models if x['id']==vip.MODEL_ID)['default'])
            with patch.object(vip,'available',return_value=False):
                unavailable=next(x for x in visual_render.models(self.c,self.shop,self.uid) if x['id']==vip.MODEL_ID)
                self.assertTrue(unavailable['default'])
                self.assertFalse(unavailable['ready'])
                with self.assertRaises(visual_render.RenderError):visual_render.selected(self.c,self.shop,[vip.MODEL_ID],self.uid)

            self.assertNotIn(vip.MODEL_ID,[x['id'] for x in visual_render.models(self.c,self.cs,self.uid)])
    def test_four_analysis_stages_use_scoped_subscription(self):
        self.configure();key=owner.key_for(self.c,self.shop,self.uid)
        from tools.ai_tasks.codex_run import analyze
        with patch.object(runtime,'generate_scoped',return_value={'text':'{"summary":"Synthetic","tasks":[]}','model':'synthetic'}) as gen:
            result=analyze('Synthetic dossier','Analyze',api_key=key)
        self.assertEqual(gen.call_count,4)
        self.assertTrue(all(call.args[0] is key for call in gen.call_args_list))
        self.assertEqual(json.loads(result['result'])['tasks'],[])

if __name__=='__main__':unittest.main()

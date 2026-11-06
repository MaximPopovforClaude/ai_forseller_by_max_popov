"""Offline acceptance of the public worker/SSH protocol. Never contacts a VPS/WB."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import io
import json
import runpy
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'infra/egress'))
import browser
import protocol
import worker
import wbshow
import wbshelf
spec = importlib.util.spec_from_file_location('public_egress', ROOT / 'stometric/egress.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)

CFG = dict(host='192.0.2.10', user='seller-egress', port=22,
           identity_file='/tmp/fixture/key', known_hosts_file='/tmp/fixture/known_hosts',
           remote_root='/opt/seller-egress', dest='-1257786')


def response(kind='prices', **overrides):
    value = protocol.result(kind, dest=CFG['dest'], prices={'101': [100, 75]},
                            panels={'101': 7}, vols={'101': [15, .4]}, errors=[], missing=[])
    value.update(overrides)
    return value


def product(nm=101, amount=7500):
    return dict(id=nm, root=1001, subjectId=10, subjectParentId=1,
                name='Example product', brand='Example', supplier='Example seller',
                supplierId=1, rating=4.8, feedbacks=3,
                sizes=[{'price': {'basic': 10000, 'product': amount}}], volume=15, weight=.4)


class ProtocolTests(unittest.TestCase):
    def test_request_deduplicates_without_reordering(self):
        j=protocol.request(b'{"version":1,"kind":"prices","nms":[102,101,102]}')
        self.assertEqual(j['nms'], [102,101])

    def test_invalid_input_rejected(self):
        for obj in ({'version':True,'kind':'prices','nms':[101]},
                    {'version':1,'kind':'prices','nms':[True]},
                    {'version':1,'kind':'prices','nms':['101']},
                    {'version':1,'kind':'prices','nms':[-1]},
                    {'version':1,'kind':'prices','nms':list(range(1,302))},
                    {'version':1,'kind':'prices','url':'https://example.org'},
                    {'version':1,'kind':'probe','nms':[101]},
                    {'version':1,'kind':'prices','dest':'1;touch /tmp/x'}):
            with self.subTest(obj=str(obj)[:70]),self.assertRaises(ValueError):
                protocol.request(json.dumps(obj).encode())
        with self.assertRaises(ValueError):protocol.request(b' '*65537)

    def test_price_uses_minimum_size_and_rubles(self):
        p=product();p['sizes'].append({'price':{'basic':12000,'product':6000}})
        self.assertEqual(browser.price(p), [120,60])
        p['sizes']=[{'price':{'basic':100,'product':float('nan')}}, {'price':{'basic':100,'product':0}}]
        self.assertIsNone(browser.price(p))

    def test_destination_and_ids_are_url_parameters(self):
        url=browser.detail_url('https://www.wildberries.ru'+browser.DETAIL+'?nm=9&dest=-1&curr=rub',[101,102],CFG['dest'])
        self.assertIn('nm=101%3B102',url);self.assertIn('dest=-1257786',url)
        for u in ['https://example.org'+browser.DETAIL,'https://www.wildberries.ru/other',
                  'http://www.wildberries.ru'+browser.DETAIL]:
            with self.assertRaises(browser.SourceError):browser.detail_url(u,[101],CFG['dest'])

    def test_browser_requests_are_get_only_and_public_hosts(self):
        for url,method,yes in [('https://www.wildberries.ru/a','GET',True),
                              ('https://basket-01.wbbasket.ru/a','GET',True),
                              ('https://www.wildberries.ru/a','POST',False),
                              ('http://127.0.0.1/a','GET',False),
                              ('https://wildberries.ru.attacker.invalid/a','GET',False),
                              ('https://x@wildberries.ru/a','GET',False)]:
            calls=[]
            r=types.SimpleNamespace(request=types.SimpleNamespace(url=url,method=method),
                                    continue_=lambda:calls.append(True),abort=lambda:calls.append(False))
            browser.route(r);self.assertEqual(calls,[yes])

    def test_malformed_or_challenge_responses_stop(self):
        for status,body in [(403,''),(429,''),(498,''),(200,'<html>challenge</html>'),(200,'{}')]:
            page=types.SimpleNamespace(evaluate=lambda *_:[status,body])
            with self.assertRaises(browser.SourceError):
                browser.fetch(page,'https://www.wildberries.ru/a',{})


class CollectionTests(unittest.TestCase):
    def test_missing_price_never_turns_into_zero(self):
        with patch.object(wbshow,'opener',return_value=('https://www.wildberries.ru'+browser.DETAIL,{})),\
             patch.object(wbshow,'fetch',return_value={'products':[product(),product(999)]}):
            obj=wbshow.collect(object(),[101,102],CFG['dest'])
        self.assertEqual(obj['prices'],{'101':[100,75]})
        self.assertEqual(obj['missing'],[102])
        self.assertEqual(obj['errors'],['missing_products'])
        client.validate(protocol.result('prices',status='partial',dest=CFG['dest'],**obj),'prices',[101,102],CFG['dest'])

    def test_http_refusal_stops_without_reopening_or_retry(self):
        with patch.object(wbshow,'opener',return_value=('https://www.wildberries.ru'+browser.DETAIL,{})),\
             patch.object(wbshow,'fetch',side_effect=browser.SourceError('http_403')) as fetch:
            obj=wbshow.collect(object(),list(range(1,202)),CFG['dest'])
        self.assertEqual(fetch.call_count,1);self.assertFalse(obj['prices'])
        self.assertEqual(len(obj['missing']),201)

    def test_shelves_and_cards_match_client_contract(self):
        with patch.object(wbshelf,'opener',return_value=('https://www.wildberries.ru'+browser.DETAIL,{})),\
             patch.object(wbshelf,'fetch',side_effect=[{'products':[product()]}, {'products':[product(201)],'total':1}]),\
             patch.object(wbshelf,'pause'):
            obj=wbshelf.collect(object(),[101],CFG['dest'])
        self.assertEqual(obj['shelves'],{'101':[1,[201]]})
        self.assertEqual(set(obj['cards']),{'101','201'})
        client.validate(protocol.result('shelves',dest=CFG['dest'],**obj),'shelves',[101],CFG['dest'])

    def test_failed_shelf_is_not_saved_as_empty_shelf(self):
        with patch.object(wbshelf,'opener',return_value=('https://www.wildberries.ru'+browser.DETAIL,{})),\
             patch.object(wbshelf,'fetch',side_effect=[{'products':[product()]},browser.SourceError('http_429')]),\
             patch.object(wbshelf,'pause'):
            obj=wbshelf.collect(object(),[101],CFG['dest'])
        self.assertEqual(obj['shelves'],{});self.assertEqual(obj['missing'],[101])

    def test_empty_list_needs_no_browser(self):
        with patch.object(worker.os,'geteuid',return_value=1000):
            obj=worker.execute(protocol.request(b'{"version":1,"kind":"prices","nms":[]}'))
        client.validate(obj,'prices',[],CFG['dest'])

    def test_worker_requires_nonroot_and_sandbox(self):
        with patch.object(worker.os,'geteuid',return_value=0), self.assertRaises(RuntimeError):
            worker.execute(dict(kind='probe'))
        calls=[]
        page=types.SimpleNamespace(set_content=lambda _:None,evaluate=lambda _:2)
        context=types.SimpleNamespace(route=lambda *a:None,new_page=lambda:page)
        browser_instance=types.SimpleNamespace(new_context=lambda **kw:context,close=lambda:None,version='fixture')
        def launch(**kw):calls.append(kw);return browser_instance
        pw=types.SimpleNamespace(chromium=types.SimpleNamespace(launch=launch))
        class CM:
            def __enter__(self):return pw
            def __exit__(self,*a):pass
        fake=types.ModuleType('playwright.sync_api');fake.sync_playwright=CM
        with patch.dict(sys.modules,{'playwright':types.ModuleType('playwright'),'playwright.sync_api':fake}),\
             patch.object(worker.os,'geteuid',return_value=1000):
            obj=worker.execute(dict(kind='probe',nms=[]))
        self.assertTrue(calls[0]['chromium_sandbox']);self.assertFalse(calls[0]['headless'])
        self.assertEqual(calls[0]['args'],['--disable-dev-shm-usage'])
        client.validate(obj,'probe',[],CFG['dest'])

    def test_raw_exception_and_secret_never_emitted(self):
        stdin=types.SimpleNamespace(buffer=io.BytesIO(b'{"version":1,"kind":"probe"}'))
        out=io.StringIO()
        with patch.object(worker.sys,'stdin',stdin),patch.object(worker,'execute',side_effect=RuntimeError('PRIVATE_TEST_VALUE')),redirect_stdout(out):
            self.assertEqual(worker.main(),1)
        self.assertNotIn('PRIVATE_TEST_VALUE',out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['errors'],['browser_runtime_failed'])

    def test_nonfinite_worker_result_is_structured_error(self):
        stdin=types.SimpleNamespace(buffer=io.BytesIO(b'{"version":1,"kind":"probe"}'))
        out=io.StringIO()
        with patch.object(worker.sys,'stdin',stdin),patch.object(worker,'execute',return_value={'value':float('nan')}),redirect_stdout(out):
            self.assertEqual(worker.main(),1)
        self.assertEqual(json.loads(out.getvalue())['status'],'error')


class ClientTests(unittest.TestCase):
    def test_ssh_is_fixed_and_host_verification_required(self):
        cmd=client.ssh_command(CFG)
        self.assertIn('StrictHostKeyChecking=yes',cmd);self.assertIn('BatchMode=yes',cmd)
        self.assertIn('ForwardAgent=no',cmd)
        self.assertEqual(cmd[-2:],['192.0.2.10','/opt/seller-egress/run.sh'])
        for key,value in [('host','-oProxyCommand=id'),('host','user@host'),('user','root'),
                          ('user','user;id'),('remote_root','/opt/a;id'),('remote_root','/opt/../tmp'),
                          ('identity_file','$(id)'),('port',True),('dest','0&nm=3')]:
            with self.subTest(key=key), self.assertRaises(client.EgressError):
                client.ssh_command(dict(CFG,**{key:value}))

    def test_worker_wire_result_to_public_adapter(self):
        with patch.object(client,'exchange',return_value=(json.dumps(response()).encode(),0)),\
             patch.object(client,'load_config',return_value=CFG):
            self.assertEqual(client.fetch_prices([101]),({101:(100,75)},{101:7},{101:(1.5,.4)}))

    def test_large_price_list_is_chunked_and_empty_is_local(self):
        calls=[]
        def reply(kind,nms):
            calls.append(nms)
            return dict(prices={str(n):[100,75] for n in nms},panels={},vols={},errors=[])
        with patch.object(client,'request',side_effect=reply):
            self.assertEqual(client.fetch_prices([]),({},{},{}))
            values=client.fetch_prices(list(range(1,602)))
        self.assertEqual([len(x) for x in calls],[300,300,1]);self.assertEqual(len(values[0]),601)

    def test_schema_and_scope_fail_closed(self):
        bad=[dict(prices={'999':[100,75]}),dict(prices={'101':[100,0]}),dict(prices={'101':[100,float('inf')]}),
             dict(version=True),dict(kind='shelves'),dict(dest='different'),dict(missing=[101]),
             dict(errors=['secret\nvalue']),dict(vols={'101':[-1,0]}),dict(panels={'101':'text'}),
             dict(captured_at='yesterday'),dict(captured_at=datetime.now().isoformat()),
             dict(captured_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())]
        for change in bad:
            with self.subTest(change=change),self.assertRaises(client.EgressError):
                client.validate(response(**change),'prices',[101],CFG['dest'])

    def test_partial_results_keep_only_valid_products(self):
        with self.assertWarns(RuntimeWarning),patch.object(client,'request',return_value=response(status='partial',missing=[102],errors=['missing_products'])):
            prices,_,_=client.fetch_prices([101,102])
        self.assertEqual(prices,{101:(100,75)})

    def test_partial_refusal_stops_before_next_price_chunk(self):
        obj=response(status='partial',missing=list(range(1,101))+list(range(102,301)),errors=['http_429'])
        with patch.object(client,'exchange',return_value=(json.dumps(obj).encode(),0)) as exchange,patch.object(client,'load_config',return_value=CFG),self.assertRaises(client.EgressError):
            client.fetch_prices(list(range(1,602)))
        self.assertEqual(exchange.call_count,1)

    def test_shelf_transport_failure_aborts_run(self):
        package=types.ModuleType('egress_fixture');package.__path__=[]
        config=types.ModuleType('egress_fixture.config');config.today_msk=lambda:None
        with patch.dict(sys.modules,{'egress_fixture':package,'egress_fixture.db':types.ModuleType('db'),
                                    'egress_fixture.config':config,'egress_fixture.egress':client}):
            spec=importlib.util.spec_from_file_location('egress_fixture.shelves',ROOT/'stometric/shelves.py')
            shelves=importlib.util.module_from_spec(spec);spec.loader.exec_module(shelves)
            with patch.object(shelves,'fetch',side_effect=client.EgressError('Worker busy')) as fetch,self.assertRaises(client.EgressError):
                shelves.crawl(types.SimpleNamespace(execute=lambda *a:[]),None,list(range(1,602)),lambda _:None)
            self.assertEqual(fetch.call_count,1)

    def test_inconsistent_exit_or_malformed_json_rejected(self):
        for data,code in [(b'<html>',0),(json.dumps(response()).encode(),1)]:
            with patch.object(client,'exchange',return_value=(data,code)),self.assertRaises(client.EgressError):
                client.request('prices',[101],CFG)

    def test_transport_is_bounded_and_does_not_echo_stderr(self):
        command=[sys.executable,'-c',"import sys;sys.stdin.read();print('{}');print('PRIVATE_TEST_VALUE',file=sys.stderr)"]
        body,code=client.exchange(command,b'input')
        self.assertEqual(body.strip(),b'{}');self.assertEqual(code,0)
        with patch.object(client,'MAX_OUTPUT',100),self.assertRaises(client.EgressError):
            client.exchange([sys.executable,'-c',"print('x'*101)"],b'')
        with patch.object(client,'TIMEOUT',.01),self.assertRaises(client.EgressError):
            client.exchange([sys.executable,'-c','import time;time.sleep(5)'],b'')

    def test_real_shared_lock_contention(self):
        with tempfile.TemporaryDirectory() as directory:
            lock=Path(directory)/'browser.lock'
            with lock.open('w') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX)
                self.assertNotEqual(subprocess.run(['flock','-n',str(lock),'true']).returncode,0)
            self.assertEqual(subprocess.run(['flock','-n',str(lock),'true']).returncode,0)
        script=(ROOT/'infra/egress/run.sh').read_text()
        self.assertIn('state/browser.lock',script)
        self.assertIn('timeout --kill-after=10 1800',script)

    def test_setup_plan_does_not_mutate_host(self):
        p=subprocess.run(['sh',str(ROOT/'infra/egress/setup.sh'),'--plan'],capture_output=True,text=True,check=True)
        self.assertIn('no keys/timers/firewall changes',p.stdout)

    def test_busy_or_expired_worker_is_not_retried(self):
        for code, text in [(75,'busy'),(124,'deadline')]:
            with self.assertRaisesRegex(client.EgressError,text):
                client.exchange([sys.executable,'-c',f'import sys;sys.stdin.read();sys.exit({code})'],b'input')

    def test_units_created_without_enabling_timers(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(Path,'home',return_value=Path(directory)),redirect_stdout(io.StringIO()):
            runpy.run_path(str(ROOT/'scripts/install_units.py'))
            units=Path(directory)/'.config/systemd/user'
            for name in ('showcase','shelves'):
                self.assertIn(f'-m stometric.{name}',(units/f'ai-stometric-{name}.service').read_text())
                self.assertTrue((units/f'ai-stometric-{name}.timer').is_file())
            self.assertFalse(list(units.glob('*.wants')))


if __name__ == '__main__':
    unittest.main()

"""Calendar pagination/visibility/status, synthetic WB and disposable socketless PG."""
import stometric.web
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from stometric import promo, api_manager
from stometric.collectors import prices
from stometric.wb import WBError
from tools.test_calendar import Cursor, Standalone

NOW = datetime.now(timezone.utc)


def announcement(i, kind='auto'):
    return dict(id=i, name=f'Акция {i}', type=kind,
                startDateTime=(NOW+timedelta(days=1)).isoformat(),
                endDateTime=(NOW+timedelta(days=5)).isoformat())


class MemoryDb:
    def __init__(self): self.saved = {}; self.committed = {}
    def execute(self, query, args=()):
        if 'INSERT INTO wb_promotions' in query: self.saved[args[1]] = args
        return Cursor([])
    def commit(self): self.committed = dict(self.saved)


class Collector(unittest.TestCase):
    def test_all_pages_details_batches_and_no_auto_product_requests(self):
        calls = []
        def call(host, path, params):
            calls.append((path, params))
            if path.endswith('/promotions'):
                off = params['offset']
                self.assertEqual(params['allPromo'], 'true')
                return {'data': {'promotions': [announcement(i) for i in range(off+1, min(off+1001, 1003))]}}
            self.assertTrue(path.endswith('/details'))
            self.assertLessEqual(len(params),100)
            return {'data': {'promotions': [announcement(i) for _,i in params]}}
        c=MemoryDb()
        result=prices.run_promotions(SimpleNamespace(c=c,acc={'id':7},wb=SimpleNamespace(call=call)))
        self.assertEqual(result,{'promotions':1002,'items':0})
        self.assertEqual(len(c.saved),1002)
        self.assertEqual([p['offset'] for path,p in calls if path.endswith('/promotions')],[0,1000])

    def test_details_type_wins_and_all_announcements_saved_before_product_failure(self):
        c=MemoryDb()
        def call(host,path,params):
            if path.endswith('/promotions'):return {'data':{'promotions':[announcement(1,'regular'),announcement(2,'regular'),announcement(3)]}}
            if path.endswith('/details'):return {'data':{'promotions':[announcement(1)]}}
            self.assertEqual(params['promotionID'],2,'type from details must skip auto product request')
            self.assertEqual(set(c.committed),{1,2,3},'later announcements must already be durable')
            raise WBError('synthetic timeout')
        with self.assertRaisesRegex(WBError,'synthetic'):
            prices.run_promotions(SimpleNamespace(c=c,acc={'id':7},wb=SimpleNamespace(call=call)))
        self.assertEqual(c.saved[1][3],'auto')

    def test_bad_payload_does_not_become_empty_success(self):
        for value in (None, {}, {'data':{}}, {'data':{'promotions':None}}, {'data':{'promotions':[{}]}}):
            with self.subTest(value=value),self.assertRaises(WBError):prices._promo_rows(value,'promotions')
        self.assertEqual(prices._promo_rows({'data':{'promotions':[]}},'promotions'),[])

    def test_announcements_survive_details_failure(self):
        c=MemoryDb()
        def call(host,path,params):
            if path.endswith('/promotions'):return {'data':{'promotions':[announcement(1),announcement(2)]}}
            raise WBError('details unavailable')
        with self.assertRaisesRegex(WBError,'details unavailable'):
            prices.run_promotions(SimpleNamespace(c=c,acc={'id':7},wb=SimpleNamespace(call=call)))
        self.assertEqual(set(c.committed),{1,2})

    def test_repeated_full_page_stops_before_writing(self):
        c=MemoryDb();page=[announcement(i) for i in range(1,1001)]
        with self.assertRaisesRegex(WBError,'повторил'):
            prices.run_promotions(SimpleNamespace(c=c,acc={'id':7},wb=SimpleNamespace(call=lambda *a,**kw:{'data':{'promotions':page}})))
        self.assertFalse(c.saved)

    def test_existing_viewer_access_still_precedes_read(self):
        with patch.object(api_manager,'_role',side_effect=RuntimeError('denied')),patch.object(promo,'view') as view:
            with self.assertRaisesRegex(RuntimeError,'denied'):api_manager.promo_get(7,u={'id':2},c=None)
            view.assert_not_called()


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='promo-collection-pg-');cls.cluster=Path(cls.tmp.name)/'db'
        r=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','promo_test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if r.returncode:raise AssertionError(r.stderr)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def setUp(self):
        class Db(Standalone):
            def execute(self,query,args=()):
                result=super().execute(query,args)
                for r in result:
                    for key in ('last_ok_at','last_run_at','at','start_at','end_at'):
                        if isinstance(r.get(key),str):r[key]=datetime.fromisoformat(r[key])
                return result
        schema='case_'+uuid4().hex;self.c=Db(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema}; SET search_path={schema};'+'''
          CREATE TABLE accounts(id int PRIMARY KEY,is_active boolean);
          INSERT INTO accounts VALUES (7,true),(8,true),(9,false);
          CREATE TABLE users(id int PRIMARY KEY);
          CREATE TABLE collector_state(account_id int,collector text,last_ok_at timestamptz,last_run_at timestamptz,last_error text);
          CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
          CREATE TABLE stocks_wb_snap(account_id int,nm_id bigint,snap_at timestamptz,in_way_to_client int,in_way_from_client int);
        ''')
        for name in ('052_promotions.sql','054_promo_calc.sql'):
            self.c.raw(Path('stometric/migrations',name).read_text())
        for shop,i,kind in ((7,1,'regular'),(7,2,'auto'),(7,3,None),(7,4,'auto'),(8,99,'auto')):
            self.c.execute('INSERT INTO wb_promotions(account_id,promo_id,name,kind,start_at,end_at) VALUES (%s,%s,%s,%s,now(),now()+interval \'1 day\')',
                           (shop,i,f'Акция {i}',kind))
        self.c.raw("INSERT INTO promo_hidden VALUES (7,'api:4'); INSERT INTO wb_promo_items(account_id,promo_id,nm_id,in_action,plan_price) VALUES (7,1,77,true,100),(8,1,88,true,999);")

    def test_view_auto_announcements_null_kind_hidden_and_tenant_scope(self):
        with patch.object(promo.manager,'other_pct',return_value=0),patch.object(promo.manager,'_unit_inputs',return_value={}),patch.object(promo.rnp,'buyout_pct',return_value=({},.8)):
            result=promo.view(self.c,7)
        self.assertEqual([p['key'] for p in result['auto_promos']],['api:2'])
        self.assertEqual({p['key'] for p in result['promos']},{'api:1','api:3'})
        self.assertEqual(result['hidden_count'],1)
        self.assertEqual(result['collection']['status'],'never')
        self.assertFalse(result['rows'])
        self.assertNotIn('Акция 99',str(result))

    def test_status_actual_dates_and_error_boolean_only(self):
        self.c.raw("INSERT INTO collector_state VALUES (7,'promotions',now(),now(),NULL),(8,'promotions',now(),now(),'synthetic confidential error');")
        self.assertEqual(promo.collection_status(self.c,7)['status'],'ok')
        self.assertEqual(promo.collection_status(self.c,8)['status'],'error')
        self.assertNotIn('confidential',str(promo.collection_status(self.c,8)))
        self.c.raw("UPDATE collector_state SET last_ok_at=now()-interval '7 hours' WHERE account_id=7;")
        result=promo.collection_status(self.c,7)
        self.assertEqual((result['status'],result['interval_minutes'],result['future_days']),('stale',360,30))
        self.assertEqual(promo.collection_status(self.c,9)['status'],'disabled')

    def test_collector_sql_upsert_and_product_price(self):
        def call(host,path,params):
            if path.endswith('/promotions'):return {'data':{'promotions':[announcement(1,'regular'),announcement(2)]}}
            if path.endswith('/details'):return {'data':{'promotions':[announcement(1,'regular'),announcement(2)]}}
            return {'data':{'nomenclatures':[{'id':77,'inAction':True,'price':150,'planPrice':123.45,'discount':0,'planDiscount':18}] if params['inAction']=='true' else []}}
        result=prices.run_promotions(SimpleNamespace(c=self.c,acc={'id':7},wb=SimpleNamespace(call=call)))
        self.assertEqual(result,{'promotions':2,'items':1})
        r=self.c.execute('SELECT plan_price FROM wb_promo_items WHERE account_id=7 AND promo_id=1 AND nm_id=77').fetchone()
        self.assertEqual(r['plan_price'],123.45)
        r=self.c.execute('SELECT plan_price FROM wb_promo_items WHERE account_id=8 AND promo_id=1 AND nm_id=88').fetchone()
        self.assertEqual(r['plan_price'],999)

    def test_news_migration_is_idempotent(self):
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        text=Path('stometric/migrations/119_promo_calendar_news.sql').read_text()
        self.c.raw(text);self.c.raw(text)
        rows=self.c.execute('SELECT title,tabs FROM service_news').fetchall()
        self.assertEqual(rows, [], 'Public installation must not inherit service news')


if __name__=='__main__':unittest.main()

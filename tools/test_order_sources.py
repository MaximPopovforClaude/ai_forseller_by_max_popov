"""Artificial HTTP and disposable PostgreSQL: no production data or credentials."""
import stometric.web
import json
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
from stometric import api_log_params, ozon, ozon_perf, photos, xyz, wb_demand, insights, aipack, manager, promo, rnp, action_charts
from stometric.wb import RateLimited
from tools.test_calendar import Standalone, Cursor

DAY = date(2026,11,13)


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='order-sources-')
        cls.cluster=Path(cls.tmp.name)/'db'
        subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True,text=True)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self):
        class Db(Standalone):
            def execute(self,q,args=()):
                rows=super().execute(q,args)
                for r in rows:
                    for k in ('covered_from','covered_to'):
                        if isinstance(r.get(k),str):r[k]=date.fromisoformat(r[k])
                return rows
        self.c=Db(self.cluster,'case_'+uuid4().hex)
        self.c.raw(f'CREATE SCHEMA {self.c.schema}; SET search_path={self.c.schema};'+'''
          CREATE TABLE api_log(account_id int,method text,params jsonb,status int,rows int,error text,duration_ms int);
          CREATE TABLE api_rate(account_id int,bucket text,next_allowed timestamptz);
          CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb,PRIMARY KEY(account_id,nm_id,day));
          CREATE TABLE agg_state(account_id int,name text,covered_from date,covered_to date);
          CREATE TABLE nomenclature(account_id int,nm_id bigint,data jsonb,vendor_code text,title text);
          INSERT INTO agg_state VALUES(1,'nm_day','2026-10-01','2026-11-13');
          INSERT INTO nomenclature VALUES(1,77,'{}','test','test');
        ''')
        self.clock=patch.object(wb_demand,'today_msk',return_value=DAY);self.clock.start();self.addCleanup(self.clock.stop)
    def put(self,d,values,nm=77,shop=1):
        self.c.execute('INSERT INTO agg_nm_day VALUES(%s,%s,%s,%s)',(shop,nm,d,json.dumps(values)))
    def client(self,perf=False):
        cl=object.__new__(ozon_perf.OzonPerf if perf else ozon.Ozon)
        cl.c,cl.acc=self.c,{'id':1}
        cl._wait_slot=Mock();cl._auth=Mock(return_value={});cl.http=Mock()
        return cl
    def call(self,cl,params,perf=False):
        return cl.get('/api/client/statistics/daily/json',params) if perf else cl.post('/v3/product/info/list',params)

    def test_long_json_success_for_seller_and_performance(self):
        for perf in (False,True):
            cl=self.client(perf)
            method=cl.http.get if perf else cl.http.post
            response=Mock(status_code=200,headers={'content-type':'application/json'})
            response.json.return_value={'items':[{'id':77}]};method.return_value=response
            body={'product_id':[str(i) for i in range(1000000000,1000001000)]}
            self.assertEqual(self.call(cl,body,perf),{'items':[{'id':77}]})
            self.assertEqual(method.call_count,1)
        rows=self.c.execute('SELECT params,status FROM api_log').fetchall()
        self.assertEqual(len(rows),2)
        for r in rows:self.assertTrue(r['params']['_truncated']);self.assertEqual(r['status'],200)

    def test_json_unicode_escaping_and_small_payload_preserved(self):
        for body in ({'small':['a','б',3]}, {'x':'"\\🔥'*3000}, {'product_id':list(range(1000))}):
            encoded=api_log_params.encode(body)
            self.assertLessEqual(len(encoded),2000)
            value=json.loads(encoded)
            if len(json.dumps(body,ensure_ascii=False))<=2000:self.assertEqual(value,body)
            else:self.assertTrue(value['_truncated'])
            self.c.execute('INSERT INTO api_log(params) VALUES(%s)',(encoded,))

    def test_http_failures_keep_retry_and_error_semantics(self):
        body={'x':'x'*5000}
        for perf in (False,True):
            for status in (403,429,503):
                cl=self.client(perf);method=cl.http.get if perf else cl.http.post
                method.return_value=Mock(status_code=status,text='synthetic error')
                expected=RateLimited if status==429 else (ozon_perf.OzonPerfError if perf else ozon.OzonError)
                with patch('time.sleep'),self.assertRaises(expected):self.call(cl,body,perf)
                self.assertEqual(method.call_count,1 if status==403 else 4)
            cl=self.client(perf);method=cl.http.get if perf else cl.http.post
            method.side_effect=httpx.ConnectError('synthetic')
            with patch('time.sleep'),self.assertRaises(ozon_perf.OzonPerfError if perf else ozon.OzonError):self.call(cl,body,perf)
            self.assertEqual(method.call_count,4)
        cl=self.client()
        with self.assertRaises(ozon.OzonError):cl.post('/write/forbidden',{})
        cl.http.post.assert_not_called()

    def test_funnel_zero_is_not_statistics_and_missing_not_zero(self):
        start=DAY-timedelta(days=7)
        records={}
        for i in range(7):
            d=start+timedelta(days=i)
            value={'orders':999,'orders_sum':99999,'f_orders':0 if i==0 else 2,
                   'f_orders_sum':0 if i==0 else 200,'f_open':100,'f_cart':10,'ad_views':1000,'ad_clicks':20}
            records[d]=value;self.put(d,value)
        self.put(start,{'f_orders':99999},shop=2)
        self.put(DAY,{'f_orders':99999})
        got=wb_demand.summary(self.c,1,start,DAY,[77])[77]
        expected=wb_demand.records(records,start,DAY)
        for key in expected:self.assertEqual(got.get(key),expected[key],key)
        self.assertEqual(got['orders'],12);self.assertEqual(got['covered_days'],7)
        self.assertEqual(got['orders_day'],12/7)
        self.assertEqual(wb_demand.daily(self.c,1,start,DAY,[77])[77][str(start)],0)
        self.c.execute('DELETE FROM agg_nm_day WHERE account_id=1 AND day=%s',(start,))
        got=wb_demand.summary(self.c,1,start,DAY,[77])[77]
        self.assertEqual(got['orders'],12);self.assertFalse(got['complete']);self.assertIsNone(got['orders_day'])
        self.assertEqual(wb_demand.summary(self.c,1,start,DAY,[]),{})

    def test_conversions_share_same_days_and_no_fallback(self):
        start=DAY-timedelta(days=3)
        self.put(start,{'orders':0,'f_orders':2,'f_cart':10,'f_open':100,'ad_views':100,'ad_clicks':7})
        self.put(start+timedelta(days=1),{'orders':55,'f_orders':3,'f_open':10000})
        self.put(start+timedelta(days=2),{'orders':55,'f_orders':None,'f_cart':10000})
        got=photos.period_stats(self.c,1,77,start,DAY)
        self.assertEqual(got['orders'],5);self.assertEqual(got['conv_order'],.2)
        self.assertEqual(got['conv_cart'],.1);self.assertEqual(got['conversion_days'],1)
        self.assertIsNone(got['orders_day']);self.assertEqual(got['ctr'],.07)
        effect=photos.effect(self.c,1,77,start,days=7)
        self.assertIsNone(effect['after']['orders_day'])

    def test_xyz_requires_explicit_funnel_days(self):
        start=DAY-timedelta(days=7)
        for i in range(7):self.put(start+timedelta(days=i),{'orders':i%2*100,'f_orders':2})
        with patch.object(xyz,'today_msk',return_value=DAY):
            got=xyz.orders(self.c,1,start,DAY,[77])[77]
            self.assertEqual(got['xyz'],'X')
            self.c.execute("UPDATE agg_nm_day SET data=data-'f_orders' WHERE day=%s",(start,))
            got=xyz.orders(self.c,1,start,DAY,[77])[77]
            self.assertIsNone(got['xyz']);self.assertEqual(got['xyz_covered_days'],6)

    def test_invalid_missing_and_zero_denominator(self):
        for i,x in enumerate((None,-1,'2',False,0)):
            self.put(DAY-timedelta(days=i+1),{'orders':99,'f_orders':x,'f_open':0,'f_cart':0})
        got=wb_demand.summary(self.c,1,DAY-timedelta(days=5),DAY,[77])[77]
        self.assertEqual(got['covered_days'],1);self.assertEqual(got['orders'],0)
        self.assertIsNone(got['conv_order']);self.assertIsNone(got['orders_day'])

    def test_aipack_financial_fields_unchanged_demand_separate(self):
        d=DAY-timedelta(days=1)
        self.put(d,{'orders':1,'orders_sum':100,'cost_orders':70,'profit':25,'f_orders':2,'f_orders_sum':250})
        with patch('stometric.materialize.ensure_cost_ready'):
            got=aipack._per_nm(self.c,1,d,d)[77]
        self.assertEqual((got['orders'],got['orders_sum'],got['profit']),(1,100,25))
        self.assertEqual((got['demand']['orders'],got['demand']['orders_sum']),(2,250))

    def test_insights_uses_demand_but_cost_checks_use_financial_orders(self):
        y=DAY-timedelta(days=1)
        self.c.raw("CREATE TABLE card_changes(account_id int,nm_id bigint,kind text,field text,old_value text,new_value text,detected_at timestamptz); CREATE TABLE nm_actions(account_id int,nm_id bigint,kind text,value text,day date);")
        for i in range(8):
            self.put(y-timedelta(days=i),{'orders':0,'f_orders':2 if i==0 else 10,'f_orders_sum':200 if i==0 else 1000,'f_open':100,'f_cart':20})
        with patch('stometric.materialize.ensure_cost_ready'),patch.object(manager,'stocks',return_value={77:{'total':30}}),patch('stometric.market.events_for_shop',return_value=[]):
            got=insights.findings(self.c,1,y)
            self.assertEqual(got['shop']['orders'],2)
            self.assertEqual(got['articles'][0]['orders'],2)
            self.assertEqual(got['low_stock'][0]['orders_avg7'],10)
            self.assertEqual(got['no_cost'],[])
            self.assertEqual(got['negative'],[])
            self.c.execute("UPDATE agg_nm_day SET data=data-'f_orders' WHERE day=%s",(y,))
            got=insights.findings(self.c,1,y)
            self.assertIsNone(got['shop']['orders']);self.assertEqual(got['articles'],[])
            self.assertNotIn('0 шт',insights.template_text(got))
            self.assertIn('недостаточно',insights.template_text(got))

    def test_promo_speed_uses_30_full_days_and_preserves_unit_values(self):
        for i in range(30): self.put(DAY-timedelta(days=i+1),{'orders':99,'f_orders':2})
        self.put(DAY,{'f_orders':99999})
        units={77:{'vendor_code':'test','title':'test','subject':'test','photo':None,'stock':60}}
        base={'stock':60,'online':123,'margin_online_pct':.2,'margin_online':24.6,'cost':30}
        original=self.c.execute
        def query(q,args=()):
            return original(q,args) if 'agg_nm_day' in q else Cursor([])
        with patch.object(self.c,'execute',side_effect=query),patch.object(manager,'other_pct',return_value=0),patch.object(manager,'_unit_inputs',return_value=units),patch.object(manager,'unit_calc',return_value=base),patch.object(rnp,'buyout_pct',return_value=({},.8)),patch.object(promo,'collection_status',return_value={}),patch('stometric.config.today_msk',return_value=DAY):
            got=promo.view(self.c,1)['rows'][0]
            self.assertEqual(got['turnover'],30)
            self.assertEqual(got['price'],123);self.assertEqual(got['margin'],.2)
            original("UPDATE agg_nm_day SET data=data-'f_orders' WHERE day=%s",(DAY-timedelta(days=3),))
            got=promo.view(self.c,1)['rows'][0]
            self.assertIsNone(got['turnover']);self.assertEqual(got['demand']['covered_days'],29)
            self.assertEqual(got['margin_rub'],24.6)

    def test_news_twice_preserves_single_item(self):
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        sql=(Path(__file__).resolve().parents[1]/'stometric/migrations/125_order_sources_news.sql').read_text()
        self.c.raw(sql);self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)

    def test_action_graph_demand_does_not_change_financial_values(self):
        day=DAY-timedelta(days=1)
        row={'orders':1,'f_orders':2,'orders_sum':100,'orders_sum_spp':80,'cost_orders':20,'ads_upd':5}
        tx={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}
        old=action_charts.values({day:row},[day],.8,tx)
        new=action_charts.values({day:row},[day],.8,tx,funnel=True)
        self.assertEqual(new['orders'],[2])
        for k in ('profit','price_spp','buyouts','ads'):self.assertEqual(new[k],old[k])


if __name__=='__main__':unittest.main()

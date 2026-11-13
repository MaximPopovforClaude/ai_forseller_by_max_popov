"""13 November UI batch: synthetic maths, HTTP boundary, isolated PostgreSQL."""
import stometric.web
import json
import tempfile
import subprocess
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import HTTPException
from tools.test_calendar import Standalone, Cursor
from stometric import xyz, action_charts as charts, rnp, api_manager, materialize
from stometric.tabs import basic

DAY = date(2026, 11, 13)


class Math(unittest.TestCase):
    def test_xyz_population_variance_boundaries_and_sparse_demand(self):
        for values, letter, cv in [([90,110]*4,'X',.1), ([75,125]*4,'Y',.25),
                                    ([0]*7+[80],'Z',7**.5), ([100]*8,'X',0)]:
            x = xyz.classify(len(values), sum(values), sum(v*v for v in values))
            self.assertEqual(x['xyz'], letter)
            self.assertAlmostEqual(x['xyz_cv'], cv)
        for args in [(6,600,60000), (8,0,0), (8,float('nan'),0)]:
            self.assertIsNone(xyz.classify(*args)['xyz'])
        self.assertIsNone(xyz.classify(8,800,80000,complete=False)['xyz'])
        self.assertIsNone(xyz.classify(8,800,80000,invalid=True)['xyz'])

    def test_charts_reuse_rnp_and_preserve_gaps_and_negative_profit(self):
        tax={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}
        row={'orders':10,'orders_sum':1000,'orders_sum_spp':800,'buyouts':4,
             'cost_orders':900,'ads_upd':500,'logistics_orders':40}
        days=[DAY-timedelta(days=i) for i in (2,1,0)]
        r=charts.values({days[1]:row},days,.8,tax,(days[0],days[1]))
        self.assertEqual(r['orders'],[0,10,None]); self.assertEqual(r['buyouts'],[0,4,None])
        self.assertEqual(r['price_spp'],[None,80,None]); self.assertEqual(r['ads'],[0,500,None])
        self.assertEqual(r['profit'][1],rnp._vals(row,.8,tax)['profit']); self.assertLess(r['profit'][1],0)

    def test_charts_permission_before_reads_and_pending_without_rebuild(self):
        c=Mock(); u={'id':99}
        with patch.object(api_manager.auth,'shop_role',return_value=None), patch.object(charts,'get') as get:
            with self.assertRaises(HTTPException): api_manager.board_charts(7,u=u,c=c)
            get.assert_not_called(); c.execute.assert_not_called()
        with patch.object(api_manager,'_role'), patch.object(charts,'get',side_effect=materialize.CostRebuildPending('pending')):
            self.assertEqual(api_manager.board_charts(7,u=u,c=c),{'error':'pending'})
            c.rollback.assert_called_once()


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='workspace-batch-')
        cls.cluster=Path(cls.tmp.name)/'pg'
        p=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if p.returncode: raise AssertionError(p.stderr)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self):
        class Db(Standalone):
            def execute(self,query,args=()):
                cur=super().execute(query,args)
                for r in cur.rows:
                    for key in ('covered_from','covered_to'):
                        if r.get(key): r[key]=date.fromisoformat(r[key])
                return cur
        self.c=Db(self.cluster,'case_'+uuid4().hex)
        self.c.raw(f'CREATE SCHEMA {self.c.schema}; SET search_path={self.c.schema};'+'''
          CREATE TABLE agg_state(account_id int,name text,covered_from date,covered_to date);
          CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
          CREATE TABLE nomenclature(account_id int,nm_id bigint,vendor_code text,data jsonb);
          CREATE TABLE accounts(id int,marketplace text);
          INSERT INTO accounts VALUES(7,'wb');
          INSERT INTO agg_state VALUES(7,'nm_day','2026-10-01','2026-11-12');
          INSERT INTO nomenclature VALUES(7,1,'stable','{}'),(7,2,'sparse','{}'),
            (7,3,'new','{"createdAt":"2026-11-05T12:00:00Z"}'),(7,4,'zero','{}');
          INSERT INTO agg_nm_day SELECT 7,1,d,'{"orders":100,"f_orders":100,"orders_sum":10000,"orders_sum_spp":8000,"ads_upd":123,"buyouts":40}'::jsonb
            FROM generate_series('2026-11-01'::date,'2026-11-13'::date,interval '1 day') d;
          INSERT INTO agg_nm_day SELECT 7,2,d,jsonb_build_object('orders',1200,'f_orders', CASE WHEN d::date='2026-11-12' THEN 1200 ELSE 0 END) FROM generate_series('2026-11-01'::date,'2026-11-12'::date,interval '1 day') d;
          INSERT INTO agg_nm_day SELECT 7,4,d,'{"orders":0,"f_orders":0}'::jsonb FROM generate_series('2026-11-01'::date,'2026-11-12'::date,interval '1 day') d;
          INSERT INTO agg_nm_day VALUES(8,1,'2026-11-01','{"orders":999999,"f_orders":999999}');
        ''')
    def test_xyz_complete_days_new_items_shop_scope_and_gaps(self):
        with patch.object(xyz,'today_msk',return_value=DAY):
            r=xyz.orders(self.c,7,date(2026,11,1),DAY,[1,2,3,4])
            self.assertEqual(r[1]['xyz'],'X'); self.assertEqual(r[1]['xyz_days'],12)
            self.assertEqual(r[2]['xyz'],'Z'); self.assertAlmostEqual(r[2]['xyz_cv'],11**.5)
            self.assertIsNone(r[3]['xyz']); self.assertIn('создан',r[3]['xyz_status'])
            self.assertIsNone(r[4]['xyz']); self.assertEqual(r[4]['xyz_status'],'Нет заказов')
            self.c.execute("UPDATE agg_state SET covered_to='2026-11-10'")
            r=xyz.orders(self.c,7,date(2026,11,1),DAY,[1]); self.assertIsNone(r[1]['xyz'])
            self.assertEqual(r[1]['xyz_status'],'Неполная история')
    def test_monthly_abc_keeps_letters_and_adds_xyz(self):
        rows=[{'nm_id':i,'year_month':202611,'profit':v,'margin':v,'for_pay':v,'buyouts':1} for i,v in [(1,70),(2,20),(3,10)]]
        with patch('stometric.agg.nm_day.cached',return_value=rows), patch.object(basic,'today_msk',return_value=DAY), patch.object(xyz,'today_msk',return_value=DAY):
            out=basic.abc(self.c,7,{'date_to':DAY})
        by={r['nm_id']:r for r in out['rows']}
        self.assertEqual([by[i]['profit_202611'] for i in (1,2,3)],['A','B','C'])
        self.assertEqual(by[1]['abcxyz_202611'],'AX'); self.assertEqual(by[2]['abcxyz_202611'],'BZ')
        self.assertIsNone(by[3]['abcxyz_202611'])
        self.assertIn('xyz_status_202611',[c['field'] for c in out['columns']])
    def test_checklist_adds_xyz_without_replacing_abc_recommendations(self):
        from stometric import checklist as ck
        from stometric.tabs import manage
        self.c.raw("""
          ALTER TABLE nomenclature ADD title text, ADD subject text;
          CREATE TABLE raw_rows(account_id int,source text,row_date date,data jsonb);
          CREATE TABLE ext_costs(account_id int,kind text,nm_id bigint,d_from date,d_to date,cost numeric);
          CREATE TABLE stocks_wb_snap(account_id int,nm_id bigint,snap_at timestamptz,quantity numeric,in_way_to_client numeric,in_way_from_client numeric);
        """)
        tax={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}
        with patch.object(ck,'_potentials'),patch.object(ck,'_score10x'),\
             patch.object(rnp,'buyout_pct',return_value=({},.8)),patch.object(rnp,'_tax',return_value=tax),\
             patch('stometric.exclusions.excluded',return_value=set()),patch.object(xyz,'today_msk',return_value=DAY):
            rows=ck.summary(self.c,7,date(2026,11,1),DAY)
            by={r['nm_id']:r for r in rows}
            self.assertEqual(by[1]['xyz'],'X');self.assertEqual(by[2]['xyz'],'Z')
            for r in rows:
                self.assertEqual(r['rec'],ck.recommend(r['abc_sum'],r['abc_profit'],r['abc_roi'],r['abc_kem']))
            with patch.object(ck,'summary',return_value=rows):
                out=manage.checklist_summary(self.c,7,{'date_from':date(2026,11,1),'date_to':DAY})
        self.assertIn('xyz',[x['field'] for x in out['columns']])
        self.assertEqual(out['cell_colors']['xyz'],xyz.COLORS)

    def test_news_is_idempotent_and_xyz_cache_is_scoped(self):
        from stometric import tabcache
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        sql=(Path(__file__).resolve().parents[1]/'stometric/migrations/121_workspace_xyz_news.sql').read_text()
        self.c.raw(sql); self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
        self.assertIn('|xyz-funnel:',tabcache.calculation_version('abc','original'))
        self.assertIn('|xyz-funnel:',tabcache.calculation_version('checklist_svod','original'))
        self.assertNotIn('|xyz-funnel:',tabcache.calculation_version('pnl_real_w','original'))

    def test_chart_sql_scope_coverage_and_exclusion(self):
        tax={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}
        with patch.object(charts,'ensure_cost_ready'), patch.object(charts,'today_msk',return_value=DAY),\
             patch.object(rnp,'_tax',return_value=tax),patch.object(rnp,'buyout_pct',return_value=({1:.8},.8)),\
             patch('stometric.exclusions.excluded',return_value={2}):
            r=charts.get(self.c,7)
        self.assertEqual(len(r['days']),30); self.assertNotIn(2,r['rows'])
        self.assertEqual(r['rows'][1]['orders'][-2:], [100,None])
        self.assertEqual(r['rows'][1]['price_spp'][-2:], [80,None])
        self.assertEqual(r['rows'][1]['ads'][-2:], [123,None])
        self.assertFalse(any('INSERT' in q or 'UPDATE' in q for q,_ in self.c.calls))

if __name__=='__main__': unittest.main()

"""Ratios and real entry SQL on synthetic, isolated PostgreSQL; no live data."""
import stometric.web
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import subprocess
import tempfile
import unittest
from uuid import uuid4
from stometric.entry_conversions import Conversions
from stometric import entry_views
from tools.test_calendar import Standalone


class RatioTests(unittest.TestCase):
    def test_sums_not_average_and_independent_sources(self):
        c = Conversions()
        c.add(dict(clicks=100,carts=40,orders=20),dict(clicks=20,carts=10,orders=4))
        c.add(dict(clicks=20,carts=10,orders=4),dict(clicks=10,carts=2,orders=1))
        self.assertEqual(c.result(),dict(ad_cr_cart=12/30,ad_cr_order=5/12,ad_cro=5/30,
                                       org_cr_cart=38/90,org_cr_order=19/38,org_cro=19/90))

    def test_missing_day_and_null_not_zero(self):
        for missing in (None,{},dict(clicks=None,carts=None,orders=None)):
            c=Conversions();c.add(dict(clicks=10,carts=4,orders=2),dict(clicks=5,carts=2,orders=1))
            c.add(dict(clicks=10,carts=4,orders=2),missing)
            self.assertTrue(all(v is None for v in c.result().values()))

    def test_zero_numerator_is_zero_denominator_is_unknown(self):
        c=Conversions();c.add(dict(clicks=10,carts=0,orders=0),dict(clicks=5,carts=0,orders=0))
        self.assertEqual(c.result(),dict(ad_cr_cart=0,ad_cr_order=None,ad_cro=0,org_cr_cart=0,org_cr_order=None,org_cro=0))
        self.assertTrue(all(v is None for v in Conversions().result().values()))

    def test_negative_residual_not_hidden_by_other_day(self):
        c=Conversions();c.add(dict(clicks=2,carts=2,orders=1),dict(clicks=3,carts=1,orders=1))
        c.add(dict(clicks=100,carts=20,orders=10),dict(clicks=3,carts=1,orders=1))
        r=c.result();self.assertIsNone(r['org_cr_cart']);self.assertIsNone(r['org_cro'])
        self.assertAlmostEqual(r['org_cr_order'],9/20);self.assertAlmostEqual(r['ad_cr_cart'],2/6)

    def test_fields_validate_separately_decimal_and_nonfinite(self):
        c=Conversions();c.add(dict(clicks=10,carts=6,orders=None),dict(clicks=Decimal(5),carts=Decimal(2),orders=1))
        self.assertEqual(c.result()['org_cr_cart'],4/5);self.assertIsNone(c.result()['org_cr_order'])
        for invalid in (-1,float('nan'),float('inf')):
            c=Conversions();c.add(dict(clicks=10,carts=6,orders=2),dict(clicks=invalid,carts=2,orders=1))
            self.assertIsNone(c.result()['ad_cro']);self.assertEqual(c.result()['ad_cr_order'],.5)


class EntrySqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='entry-conversions-pg-');cls.cluster=Path(cls.tmp.name)/'db'
        r=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','entry_test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if r.returncode: raise AssertionError(r.stderr)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def setUp(self):
        class Db(Standalone):
            def execute(self,q,args=()):
                rows=super().execute(q,args)
                for row in rows:
                    for f in ('d_from','d_to'):
                        if isinstance(row.get(f),str): row[f]=date.fromisoformat(row[f])
                return rows
        schema='case_'+uuid4().hex;self.c=Db(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema};SET search_path={schema};'+'''
          CREATE TABLE entry_reports(id int,account_id int,d_from date,d_to date);
          CREATE TABLE entry_rows(report_id int,nm_id bigint,section text,point text,views numeric,clicks numeric,carts numeric,orders numeric);
          CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
          CREATE TABLE wb_ad_kw_daily(account_id int,nm_id bigint,day date,views numeric,clicks numeric,atbs numeric,orders numeric,advert_id bigint);
          CREATE TABLE raw_rows(account_id int,source text,row_key text,row_date date,data jsonb);
          CREATE TABLE nomenclature(account_id int,nm_id bigint,vendor_code text,title text,brand text,data jsonb);
          INSERT INTO entry_reports VALUES (1,7,'2026-11-11','2026-11-11'),(2,7,'2026-11-12','2026-11-12'),
             (3,8,'2026-11-12','2026-11-12'),(4,7,'2026-11-01','2026-11-12');
          INSERT INTO entry_rows VALUES (1,77,'Поиск','Запрос',1000,100,40,20),(2,77,'Поиск','Запрос',200,20,10,4),
             (3,77,'Поиск','Чужой',999,999,999,999),(4,77,'Поиск','Период',999,999,999,999),
             (1,88,'Поиск','Другой',100,10,6,2),(2,88,'Поиск','Другой',100,10,6,2),(1,99,'Поиск','Исключён',999,999,999,999);
          INSERT INTO agg_nm_day VALUES
             (7,77,'2026-11-11','{"orders":10,"orders_sum":1000,"buyouts":9,"ad_views":80,"ad_clicks":20,"ad_carts":10,"ad_orders":4}'),
             (7,77,'2026-11-12','{"orders":5,"orders_sum":500,"buyouts":4,"ad_views":40,"ad_clicks":10,"ad_carts":2,"ad_orders":1}'),
             (7,88,'2026-11-11','{"ad_views":20,"ad_clicks":5,"ad_carts":2,"ad_orders":1}'),
             (7,88,'2026-11-12','{"ad_views":20,"ad_clicks":5,"ad_carts":2,"ad_orders":1}'),
             (8,77,'2026-11-12','{"ad_clicks":999,"ad_carts":999,"ad_orders":999}');
        ''')
    def result(self,**kw):
        with patch('stometric.exclusions.excluded',return_value={99}):
            return entry_views.build(self.c,7,**kw)
    def test_days_weeks_months_selected_and_no_cross_tenant(self):
        for grain in ('day','week','month'):
            d=self.result(nms=[77],grain=grain);r=d['funnel']['total']['all']
            self.assertEqual((r['orders'],r['orders_sum'],r['avg_price']), (24,1500,100))
            self.assertAlmostEqual(r['ad_cr_cart'],12/30);self.assertAlmostEqual(r['org_cro'],19/90)
            self.assertEqual(d['funnel']['articles_n'],1)
            if grain=='day': self.assertEqual(d['funnel']['articles'][0]['cells']['2026-11-12']['ad_cr_cart'],.2)
            else: self.assertEqual(next(v for k,v in d['funnel']['total'].items() if k!='all')['ad_cro'],5/30)
    def test_totals_include_all_articles_before_top_n(self):
        d=self.result(top_n=1);self.assertEqual(len(d['funnel']['articles']),1)
        self.assertEqual(d['funnel']['articles_n'],2)
        self.assertEqual(d['funnel']['total']['all']['ad_cr_cart'],16/40)
    def test_missing_agg_and_partial_field(self):
        self.c.raw("UPDATE agg_nm_day SET data=data-'ad_orders' WHERE account_id=7 AND nm_id=77 AND day='2026-11-12';")
        r=self.result(nms=[77])['funnel']['total']['all']
        self.assertEqual(r['ad_cr_cart'],12/30);self.assertIsNone(r['ad_cro']);self.assertIsNone(r['org_cr_order'])
        self.c.raw("DELETE FROM agg_nm_day WHERE account_id=7 AND nm_id=77 AND day='2026-11-12';")
        r=self.result(nms=[77])['funnel']['total']['all'];self.assertIsNone(r['ad_cr_cart']);self.assertIsNone(r['org_cr_cart'])
    def test_null_entry_component_cannot_hide_inside_sum(self):
        self.c.raw("INSERT INTO entry_rows VALUES(2,77,'Поиск','Неполный',0,NULL,0,0);")
        r=self.result(nms=[77])['funnel']['total']['all']
        self.assertEqual(r['ad_cr_cart'],12/30);self.assertIsNone(r['org_cr_cart']);self.assertEqual(r['org_cr_order'],19/38)
    def test_ad_day_without_entry_is_not_organic_zero(self):
        self.c.raw("DELETE FROM entry_rows WHERE report_id=2 AND nm_id=88;")
        r=self.result()['funnel']['total']['all'];self.assertIsNone(r['org_cro']);self.assertEqual(r['ad_cro'],7/40)
    def test_missing_sku_day_in_both_sources(self):
        self.c.raw("DELETE FROM entry_rows WHERE report_id=2 AND nm_id=88; DELETE FROM agg_nm_day WHERE account_id=7 AND nm_id=88 AND day='2026-11-12';")
        r=self.result()['funnel']['total']['all'];self.assertIsNone(r['org_cro']);self.assertIsNone(r['ad_cro'])
    def test_empty_selection(self):
        d=self.result(nms=[1000]);self.assertEqual(d['funnel']['articles_n'],0);self.assertEqual(d['funnel']['total'],{})
    def test_news_twice(self):
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        sql=Path('stometric/migrations/129_entry_total_news.sql').read_text()
        self.c.raw(sql);self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)

if __name__=='__main__': unittest.main()

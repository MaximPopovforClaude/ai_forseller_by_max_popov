"""Synthetic entry reports, photo windows and tenant isolation on disposable PG."""
import stometric.web
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
import subprocess
import tempfile
import unittest
from uuid import uuid4

from stometric import photo_entry, api_manager, photos, photo_prices
from tools.test_calendar import Standalone, Cursor

TODAY = date(2026, 11, 6)
SNAPS = [{'id': 2, 'taken_at': datetime.fromisoformat('2026-11-03T22:00:00+00:00')},
         {'id': 1, 'taken_at': datetime.fromisoformat('2026-10-31T22:00:00+00:00')}]


class PhotoEntrySql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='photo-entry-pg-')
        cls.cluster = Path(cls.tmp.name) / 'db'
        r = subprocess.run(['/usr/lib/postgresql/16/bin/initdb', '-D', str(cls.cluster), '-A', 'trust',
                            '-U', 'photo_entry_test', '--no-locale', '--encoding=UTF8'], capture_output=True, text=True)
        if r.returncode: raise AssertionError(r.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        class Db(Standalone):
            def execute(self, sql, args=()):
                rows = super().execute(sql, args)
                for row in rows:
                    if isinstance(row.get('day'), str): row['day'] = date.fromisoformat(row['day'])
                return rows
        schema = 'case_' + uuid4().hex
        self.c = Db(self.cluster, schema)
        self.c.raw(f'CREATE SCHEMA {schema}; SET search_path={schema};' + '''
          CREATE TABLE entry_reports(id int PRIMARY KEY,account_id int,d_from date,d_to date);
          CREATE TABLE entry_rows(report_id int,nm_id bigint,views numeric,clicks numeric,carts numeric,orders numeric);
          INSERT INTO entry_reports VALUES
            (1,7,'2026-11-01','2026-11-01'),(2,7,'2026-11-02','2026-11-02'),
            (3,7,'2026-11-03','2026-11-03'),(4,7,'2026-11-04','2026-11-04'),
            (5,7,'2026-11-05','2026-11-05'),(6,7,'2026-11-06','2026-11-06'),
            (7,7,'2026-11-01','2026-11-05'),(8,8,'2026-11-03','2026-11-03');
          INSERT INTO entry_rows VALUES
            (1,77,50,5,2,1),(1,77,50,5,3,0),(2,77,300,90,20,4),
            (4,88,999,999,999,999),(5,77,0,0,0,0),(6,77,9999,9999,9999,9999),
            (7,77,99999,99999,99999,99999),(8,77,8888,8888,8888,8888);
        ''')

    def result(self, snaps=SNAPS): return photo_entry.periods(self.c, 7, 77, snaps, today=TODAY)

    def test_weighted_ratios_daily_only_and_missing_report(self):
        value = self.result()[1]
        self.assertEqual((value['from'], value['to']), (date(2026,11,1),date(2026,11,3)))
        self.assertEqual((value['views'],value['clicks'],value['carts'],value['orders']), (400,100,25,5))
        self.assertEqual((value['ctr'],value['conv_cart'],value['conv_order']), (.25,.25,.2))
        self.assertEqual((value['expected_days'],value['report_days'],value['covered_days']), (3,2,2))
        self.assertEqual(value['missing_days'],[date(2026,11,3)])
        self.assertEqual(value['status'],'partial'); self.assertAlmostEqual(value['coverage'],2/3)

    def test_absent_article_is_not_zero_current_day_excluded(self):
        value = self.result()[2]
        self.assertEqual((value['report_days'],value['covered_days'],value['expected_days']), (2,1,2))
        self.assertEqual(value['missing_days'],[date(2026,11,4)])
        self.assertEqual(value['views'],0); self.assertIsNone(value['ctr']); self.assertIsNone(value['conv_order'])
        self.assertEqual(value['to'],date(2026,11,5))

    def test_no_data_remains_unknown_and_no_cross_shop_or_article(self):
        for shop,nm in [(9,77),(7,999)]:
            value=photo_entry.periods(self.c,shop,nm,SNAPS,today=TODAY)[1]
            self.assertEqual(value['status'],'empty'); self.assertEqual(value['covered_days'],0)
            for k in ('views','clicks','carts','orders','ctr','conv_cart','conv_order'): self.assertIsNone(value[k])

    def test_multiple_changes_same_day_do_not_duplicate_daily_totals(self):
        extra={'id':3,'taken_at':datetime.fromisoformat('2026-11-04T20:00:00+03:00')}
        result=self.result(SNAPS+[extra])
        self.assertEqual(result[2]['status'],'intraday'); self.assertEqual(result[2]['expected_days'],0)
        self.assertIsNone(result[2]['ctr']); self.assertEqual(result[3]['expected_days'],2)
        self.assertEqual(result[1]['to'],date(2026,11,3))

    def test_null_metric_is_not_silently_summed_as_zero(self):
        self.c.raw('UPDATE entry_rows SET clicks=NULL WHERE report_id=2;')
        value=self.result()[1]
        self.assertEqual(value['covered_days'],1); self.assertEqual(value['views'],100)
        self.assertEqual(value['ctr'],.1)

    def test_complete_coverage_and_zero_numerator(self):
        self.c.raw('INSERT INTO entry_rows VALUES (3,77,100,0,0,0);')
        value=self.result()[1]
        self.assertEqual(value['status'],'complete'); self.assertEqual(value['coverage'],1)
        self.assertEqual(value['ctr'],.2)

    def test_news_idempotence(self):
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        sql=Path('stometric/migrations/124_photo_entry_news.sql').read_text()
        self.c.raw(sql); self.c.raw(sql)
        rows=self.c.execute('SELECT title,tabs FROM service_news').fetchall()
        self.assertEqual(rows, [], 'Public installation must not inherit service news')


class Boundaries(unittest.TestCase):
    def test_empty_and_today_only_skip_database(self):
        c=Mock()
        self.assertEqual(photo_entry.periods(c,7,77,[],today=TODAY),{})
        value=photo_entry.periods(c,7,77,[{'id':1,'taken_at':datetime(2026,11,6,tzinfo=timezone.utc)}],today=TODAY)[1]
        self.assertEqual(value['status'],'pending'); self.assertIsNone(value['to']); c.execute.assert_not_called()

    def test_api_current_before_after_and_competitor_isolation(self):
        class Db:
            own=True
            def execute(self,sql,args=()):
                if 'FROM nomenclature' in sql:return Cursor([{'ok':1}] if self.own else [])
                if 'FROM competitors' in sql:return Cursor([{'ok':1}])
                if 'FROM photo_snaps' in sql:return Cursor([{**s,'slots':[]} for s in SNAPS])
                if 'FROM photo_events' in sql:return Cursor([{'day':date(2026,11,4),'snap_id':2,'prev_id':1,'summary':'test','detail':{}}])
                raise AssertionError(sql)
        c=Db()
        with patch.object(api_manager,'_role') as role, patch.object(photos,'effect',return_value={}),\
             patch.object(photos,'period_stats',side_effect=lambda *args:{}), patch.object(photo_prices,'periods',return_value={}),\
             patch.object(photo_entry,'periods',return_value={1:{'ctr':.1},2:{'ctr':.2}}) as read:
            value=api_manager.pf_item(7,77,u={'id':4},c=c)
            role.assert_called_once_with(c,{'id':4},7,'viewer')
            self.assertEqual(value['current_period']['entry']['ctr'],.2)
            self.assertEqual(value['events'][0]['period']['entry']['ctr'],.2)
            self.assertEqual(value['events'][0]['period_before']['entry']['ctr'],.1)
            read.assert_called_once();c.own=False;read.reset_mock()
            value=api_manager.pf_item(7,77,u={'id':4},c=c)
            read.assert_not_called();self.assertIsNone(value['current_period'])
            self.assertNotIn('period',value['events'][0])

    def test_permission_precedes_new_reads(self):
        with patch.object(api_manager,'_role',side_effect=RuntimeError('denied')),patch.object(photo_entry,'periods') as read:
            with self.assertRaisesRegex(RuntimeError,'denied'):api_manager.pf_item(7,77,u={},c=Mock())
            read.assert_not_called()


if __name__=='__main__':unittest.main()

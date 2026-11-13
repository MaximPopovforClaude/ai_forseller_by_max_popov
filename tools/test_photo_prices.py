"""Synthetic price arithmetic and real SQL on disposable, socketless PostgreSQL."""
import stometric.web  
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, Mock
import subprocess
import tempfile
import unittest
from uuid import uuid4

from stometric import photo_prices as prices, photo_entry, api_manager, photos, showcase
from tools.test_calendar import Standalone, Cursor

T = datetime(2026, 11, 10, tzinfo=timezone.utc)
def at(hour): return T + timedelta(hours=hour)
def row(hour, before, after): return {'at': at(hour), 'seller_price': before, 'price': after}


class Arithmetic(unittest.TestCase):
    def test_time_weighting_not_average_of_changes(self):
        value = prices.average([row(0, 1000, 800), row(1, 2000, 1600)], at(0), at(4), at(4))
        self.assertEqual((value['before_spp'], value['after_spp'], value['coverage']), (1750, 1400, 1))

    def test_seed_boundaries_and_moscow_timezone(self):
        msk = timezone(timedelta(hours=3))
        value = prices.average([row(-1, 900, 600), row(2, 1800, 1200), row(4, 9000, 8000)],
                               at(0).astimezone(msk), at(4).astimezone(msk), at(8))
        self.assertEqual((value['before_spp'], value['after_spp']), (1350, 900))

    def test_partial_history_never_uses_zero_or_current_price_for_missing_time(self):
        value = prices.average([row(1, Decimal('100.10'), Decimal('80.08'))], at(0), at(4), at(3))
        self.assertEqual((value['before_spp'], value['after_spp'], value['coverage']), (100.1, 80.08, .5))

    def test_unknown_pairs_and_zero_duration(self):
        for rows in ([], [row(0, None, 50)], [row(0, 100, 0)], [row(0, 'NaN', 50)]):
            value = prices.average(rows, at(0), at(2), at(2))
            self.assertIsNone(value['before_spp']); self.assertIsNone(value['after_spp'])
        value = prices.average([row(0, 100, 80), row(1, None, 70), row(2, 200, 160)], at(0), at(3), at(3))
        self.assertEqual((value['before_spp'], value['after_spp']), (150, 120))
        self.assertAlmostEqual(value['coverage'], 2/3)
        self.assertIsNone(prices.average([row(0, 100, 80)], at(1), at(1), at(2))['before_spp'])

    def test_capture_small_seller_change_even_when_rounded_spp_does_not_change(self):
        class Db:
            def __init__(self): self.calls = []
            def execute(self, sql, args=()):
                self.calls.append((sql, args))
                return Cursor([{'account_id': 7, 'nm_id': 77, 'price': 100, 'seller_price': 200, 'spp': 50}]
                              if sql == 'SELECT * FROM wb_showcase' else [])
            def commit(self): pass
        c = Db()
        result = showcase.save(c, {77: {'account_id': 7, 'seller_price': 200.01}}, {77: (200, 100)})
        self.assertEqual(result, {'checked': 1, 'changed': 1, 'events': 0})
        self.assertEqual(sum('INSERT INTO wb_showcase_hist' in sql for sql, _ in c.calls), 1)

    def test_api_current_before_after_and_competitor_isolation(self):
        snaps = [{'id': i, 'taken_at': at(i), 'slots': []} for i in (3, 2, 1)]
        events = [{'snap_id': i, 'prev_id': i-1, 'day': date(2026,11,10), 'summary': '', 'detail': {}} for i in (3,2)]
        class Db:
            own = True
            def execute(self, sql, args=()):
                if 'FROM nomenclature' in sql: return Cursor([{}] if self.own else [])
                if 'FROM competitors' in sql: return Cursor([{'ok':1}])
                if 'FROM photo_snaps' in sql: return Cursor(snaps)
                if 'FROM photo_events' in sql: return Cursor(events)
                raise AssertionError(sql)
        c = Db()
        
        original = c.execute
        def execute(sql, args=()):
            return Cursor([{'ok':1}]) if c.own and 'FROM nomenclature' in sql else original(sql,args)
        c.execute = execute
        with patch.object(api_manager, '_role'), patch.object(photos, 'period_stats', side_effect=lambda *a: {}),\
             patch.object(photo_entry, 'periods', return_value={}),\
             patch.object(photos, 'effect', return_value={}), patch.object(prices, 'periods', return_value={i:{'before_spp':i*100} for i in (1,2,3)}) as read:
            result = api_manager.pf_item(7,77,u={},c=c)
            self.assertEqual(result['current_period']['prices']['before_spp'],300)
            self.assertEqual(result['events'][0]['period_before']['prices']['before_spp'],200)
            self.assertEqual(result['events'][1]['period_before']['prices']['before_spp'],100)
            self.assertIsNone(result['events'][1]['period_before']['ctr'])
            c.own = False; read.reset_mock()
            result = api_manager.pf_item(7,77,u={},c=c)
            read.assert_not_called(); self.assertIsNone(result['current_period'])


class PriceSql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='photo-prices-pg-')
        cls.cluster = Path(cls.tmp.name)/'db'
        result = subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','photo_test','--no-locale','--encoding=UTF8'], capture_output=True,text=True)
        if result.returncode: raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        class Db(Standalone):
            def execute(self, query, args=()):
                if query.startswith('('): query = 'SELECT * FROM ('+query+') price_history'
                return super().execute(query,args)
        schema = 'price_case_'+uuid4().hex
        self.c = Db(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema}; SET search_path={schema};'+'''
          CREATE TABLE wb_showcase_hist(account_id int,nm_id bigint,at timestamptz,price numeric,seller_price numeric);
          CREATE TABLE wb_showcase(account_id int,nm_id bigint,checked_at timestamptz,price numeric,seller_price numeric);
          INSERT INTO wb_showcase_hist VALUES
          (7,77,'2026-11-09T23:00:00Z',800,1000),(7,77,'2026-11-10T02:00:00Z',1600,2000),
          (8,77,'2026-11-09T23:00:00Z',80000,90000),(7,88,'2026-11-09T23:00:00Z',80000,90000);
          INSERT INTO wb_showcase VALUES (7,77,'2026-11-10T04:00:00Z',1600,2000);
        ''')

    def test_exact_photo_boundaries_seed_shop_scope_and_current_coverage(self):
        values = prices.periods(self.c,7,77,[{'id':2,'taken_at':at(1)},{'id':1,'taken_at':at(0)}],now=at(5))
        self.assertEqual((values[1]['before_spp'],values[1]['after_spp'],values[1]['coverage']),(1000,800,1))
        self.assertEqual(values[2]['before_spp'],1666.67)
        self.assertEqual(values[2]['after_spp'],1333.33)
        self.assertEqual(values[2]['coverage'],.75)
        self.assertIsNone(prices.periods(self.c,9,77,[{'id':1,'taken_at':at(0)}],now=at(5))[1]['before_spp'])

    def test_absent_snapshot_does_not_extrapolate_past_last_observation(self):
        self.c.raw('DELETE FROM wb_showcase;')  
        values = prices.periods(self.c,7,77,[{'id':1,'taken_at':at(0)}],now=at(5))
        self.assertEqual(values[1]['before_spp'],1000)
        self.assertEqual(values[1]['coverage'],.4)


if __name__ == '__main__': unittest.main()

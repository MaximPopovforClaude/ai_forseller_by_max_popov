"""Synthetic regression of the confirmed checklist failure and WB summary cost."""
import stometric.web  
from contextlib import ExitStack
from datetime import date, timedelta
from decimal import Decimal
import json
import hashlib
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from stometric import checklist, rnp, wb_demand
from stometric.agg import buyout, nm_day, real_week
from stometric.sheets import svodwb
from stometric.tabs import manage
from tools.test_audit_calculations import Rows
from tools import test_workspace_batch as fixture_support

DAY = date(2026, 11, 12)
FIXTURE = Path(__file__).parent/'fixtures/svodwb-deploy-20261113.json'


def artificial_rows():
    rng = random.Random(20261113)
    keys = sorted(set(svodwb.SUM_METRICS.values()) | {'margin', 'profit', 'f_open', 'f_cart', 'f_orders'})
    return [dict(day=DAY-timedelta(days=i), nm_id=nm,
                 **{k: None if rng.random() < .12 else rng.randrange(-900, 9000)/10 for k in keys})
            for i in range(62, -1, -1) for nm in (1, 2, 3)]


def weekly_rows():
    return [dict(nm_id=nm, date_from=str(DAY-timedelta(days=7*i+6+nm)),
                 date_to=str(DAY-timedelta(days=7*i+nm)), deliveries=10+i, returns=2+i%3)
            for nm in (1, 2, 3) for i in range(12)]


class ReportDB:
    def __init__(self, regime): self.regime = regime
    def execute(self, sql, args=()):
        if 'FROM tax_settings' in sql: return Rows([{'regime': self.regime, 'rate': Decimal('.06')}])
        if 'FROM nomenclature' in sql:
            return Rows([dict(nm_id=i, vendor_code=str(i), title='Artificial', subject='Test', brand='Test', imt_id=i) for i in (1,2,3,4)])
        if 'FROM stocks_wb_snap' in sql: return Rows([dict(nm_id=4,q=5,wt=2,wf=1)])
        if 'FROM raw_rows' in sql: return Rows([dict(nm=1,v=Decimal('4.7'))])
        if 'FROM cost_price' in sql: return Rows([dict(nm_id=i,cost=Decimal('13.75')) for i in (1,2,3,4)])
        if 'FROM agg_state' in sql: return Rows([])
        raise AssertionError(sql)


def layouts():
    return [None, [('', m, p) for m in svodwb.metric_options() if m != 'разница' for p in svodwb.PERIODS]
            + [('', 'разница', '')]]


def run_report(module, regime, fallback, layout, nms):
    rows = artificial_rows()
    with ExitStack() as s:
        s.enter_context(patch.object(nm_day,'cached',return_value=rows))
        s.enter_context(patch.object(nm_day,'iter_cached',side_effect=lambda *a: iter(r for r in rows if not a[-1] or r['nm_id'] in a[-1])))
        s.enter_context(patch.object(real_week,'cached',return_value=weekly_rows()))
        s.enter_context(patch.object(buyout,'needed',return_value=fallback))
        s.enter_context(patch.object(buyout,'by_orders',return_value=({1:.75,2:.5},.65)))
        s.enter_context(patch('stometric.materialize.ensure_cost_ready'))
        return module.compute(ReportDB(regime), 7, DAY, layout, nms)


class ReportRegression(unittest.TestCase):
    def test_all_cells_layouts_filters_tax_and_buyout_match_previous(self):
        cases = json.loads(FIXTURE.read_text())['cases']
        for case in cases:
            with self.subTest(regime=case['regime'],fallback=case['fallback'],layout=case['layout'],nms=case['nms']):
                actual = run_report(svodwb,case['regime'],case['fallback'],layouts()[case['layout']],case['nms'])
                
                
                payload=json.dumps(actual,default=float,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
                self.assertEqual(len(actual['rows']),case['rows'])
                self.assertEqual(len(actual['columns']),case['columns'])
                self.assertEqual(hashlib.sha256(payload).hexdigest(),case['sha256'])

    def test_decimal_funnel_counts_are_normalized_before_downstream_division(self):
        for value in (Decimal('2'), Decimal('0'), 2, 0):
            r = wb_demand.finish(dict(orders=value, covered_days=1, conv_orders=value,
                                views=Decimal('100'), cart=Decimal('10'), conversion_days=1),DAY,DAY,1)
            self.assertEqual(r['conv_orders']/r['views'], float(value)/100)
        r = wb_demand.empty(DAY,DAY)
        self.assertIsNone(r['conv_orders'])

    def test_fallback_does_not_load_unused_financial_history(self):
        with patch.object(svodwb,'_buyout_last4',side_effect=AssertionError('unused scan')):
            out = run_report(svodwb,'Другая СНО',True,None,None)
        self.assertTrue(out['rows'])


class ReportSQL(unittest.TestCase):
    setUpClass = classmethod(fixture_support.Sql.setUpClass.__func__)
    tearDownClass = classmethod(fixture_support.Sql.tearDownClass.__func__)
    setUp = fixture_support.Sql.setUp

    def test_actual_checklist_route_with_postgres_numeric_types_and_full_conversions(self):
        self.c.raw("""
          ALTER TABLE nomenclature ADD title text, ADD subject text;
          CREATE TABLE raw_rows(account_id int,source text,row_date date,data jsonb);
          CREATE TABLE ext_costs(account_id int,kind text,nm_id bigint,d_from date,d_to date,cost numeric);
          CREATE TABLE stocks_wb_snap(account_id int,nm_id bigint,snap_at timestamptz,quantity numeric,in_way_to_client numeric,in_way_from_client numeric);
          CREATE TABLE jam_cache(account_id int,nm_id bigint,items jsonb,date_from date,date_to date,state text,fetched_at timestamptz);
          UPDATE agg_nm_day SET data=data || '{"f_open":1000,"f_cart":200}'::jsonb WHERE account_id=7 AND nm_id=1;
        """)
        execute = self.c.execute
        def native_numeric(sql,args=()):
            cur = execute(sql,args)
            
            if 'conversion_days' in sql and 'squares' in sql:
                for row in cur.rows:
                    for k in ('orders','squares','orders_sum','views','cart','conv_orders'):
                        if row.get(k) is not None: row[k] = Decimal(str(row[k]))
            return cur
        self.c.execute = native_numeric
        with patch.object(rnp,'buyout_pct',return_value=({},.8)),\
             patch.object(rnp,'_tax',return_value={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}),\
             patch('stometric.exclusions.excluded',return_value=set()):
            out = manage.checklist_summary(self.c,7,{'date_from':date(2026,11,1),'date_to':DAY})
        row = next(r for r in out['rows'] if r['nm_id']==1)
        self.assertEqual(row['cr'],.1)
        self.assertEqual(row['cart_rate'],.2)
        self.assertEqual(row['order_rate'],.5)
        self.assertEqual(row['orders'],1200)
        self.assertEqual(row['rec'],checklist.recommend(row['abc_sum'],row['abc_profit'],row['abc_roi'],row['abc_kem']))

    def test_compact_realization_query_matches_per_item_window_and_zero_deliveries(self):
        self.c.raw("CREATE TABLE agg_real_week(account_id int, data jsonb); INSERT INTO agg_state(account_id,name) VALUES(7,'real_week');")
        source=weekly_rows()+[dict(nm_id=4,date_from='2026-11-01',date_to='2026-11-07',deliveries=0,returns=1)]
        for row in source:
            self.c.execute('INSERT INTO agg_real_week VALUES(%s,%s)',(7,json.dumps(row)))
        self.c.execute('INSERT INTO agg_real_week VALUES(%s,%s)',(8,json.dumps({**source[0],'deliveries':999999})))
        with patch('stometric.materialize.ensure_cost_ready'),\
             patch.object(real_week,'cached',side_effect=AssertionError('materialized path must not load full JSON')):
            got=svodwb._buyout_last4(self.c,7)
            selected=svodwb._buyout_last4(self.c,7,[2,4])
        self.assertEqual(set(got),{1,2,3,4});self.assertEqual(set(selected),{2,4})
        for nm in (1,2,3):
            rows=[r for r in source if r['nm_id']==nm]
            end=max(date.fromisoformat(r['date_to']) for r in rows)
            rows=[r for r in rows if date.fromisoformat(r['date_from'])>=end-timedelta(days=27)]
            dl=sum(r['deliveries'] for r in rows); rt=sum(r['returns'] for r in rows)
            self.assertAlmostEqual(got[nm],(dl-rt)/dl)
        self.assertEqual(got[4],0)


if __name__=='__main__': unittest.main()

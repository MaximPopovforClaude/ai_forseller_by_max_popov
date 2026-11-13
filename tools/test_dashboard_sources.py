"""WB dashboard presentation and financial invariants on artificial data only."""
import stometric.web  
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from stometric import tabcache
from stometric.agg import nm_day, real_week, buyout
from stometric.sheets import dash5, by_days
from stometric.tabs import basic
from tools.test_audit_calculations import TaxDB, tax

DAY = date(2026, 11, 12)


class DashboardSources(unittest.TestCase):
    def setUp(self):
        self.db = TaxDB([tax('УСН доход', .06)])
        self.rows = [dict(day=DAY, nm_id=101, orders=3, orders_sum=1200, orders_sum_spp=900,
                          f_orders=5, f_orders_sum=2000, cx_orders=1, cx_orders_sum=400,
                          ok_orders=2, ok_orders_sum=800, cost_orders=300, ads=120, ads_upd=120,
                          commission_offer_orders=100, logistics_orders=40, buyouts=2,
                          buyouts_sum_before_spp=800, buyouts_sum=600, cost=200, for_pay=500)]
        for target, name, kwargs in (
            (nm_day, 'iter_cached', dict(side_effect=lambda *a: iter(self.rows))),
            (nm_day, 'cached', dict(side_effect=lambda *a: self.rows)),
            (real_week, 'weekly_deliveries', dict(return_value=[])),
            (buyout, 'needed', dict(return_value=True)),
            (buyout, 'for_nms', dict(return_value=.75)),
            (basic, 'today_msk', dict(return_value=DAY + timedelta(days=1))),
        ):
            p = patch.object(target, name, **kwargs)
            p.start(); self.addCleanup(p.stop)

    def filters(self):
        return dict(date_from=DAY, date_to=DAY, nm_ids=[101])

    def test_all_five_dashboards_show_funnel_first_and_statistics_separately(self):
        with patch.object(basic, 'group_nms', return_value=[101]):
            for name in ('dash5', 'dash_nm', 'dash_nm_days', 'dash_group', 'by_days'):
                with self.subTest(tab=name):
                    report = getattr(basic, name)(self.db, 1, {**self.filters(), 'group': 'test'})
                    rows = [r for r in report['rows'] if r['fmt'] != 'h']
                    self.assertTrue(all('воронки WB' in r['label'] for r in rows[:2]))
                    self.assertTrue(all('статистики WB' in r['label'] for r in rows[2:4]))
                    indexed = {r['row']: r for r in rows}
                    col = DAY.isoformat() if name == 'by_days' else 'd0' if name == 'dash_nm_days' else 'C'
                    fqty, fsum, sqty, ssum = (11, 12, 3, 4) if name == 'by_days' else (13, 12, 8, 7)
                    self.assertEqual([indexed[n][col] for n in (fqty, fsum, sqty, ssum)], [5, 2000, 3, 1200])
                    self.assertIn('ДРР и прибыль', report['note'])

    def test_same_financial_cells_with_new_order_and_very_different_funnel(self):
        before = dash5.compute(self.db, 1, DAY)
        self.rows[0].update(f_orders=900, f_orders_sum=987654)
        after = basic.dash5(self.db, 1, self.filters())
        by_id = {r['row']: r for r in after['rows']}
        for old in before['rows']:
            if old['row'] in (12, 13):
                continue
            for col, value in old.items():
                if col not in ('label', 'row', 'fmt'):
                    self.assertEqual(by_id[old['row']][col], value, (old['row'], col))
        by_id = {r['row']: r for r in basic.by_days(self.db, 1, self.filters())['rows']}
        self.assertEqual(by_id[27][DAY.isoformat()], .1)  
        self.assertEqual(by_id[8][DAY.isoformat()], .3333)  
        self.assertEqual(by_id[32][DAY.isoformat()], 144)  

    def test_missing_funnel_is_null_even_if_statistics_exist_and_zero_is_real(self):
        self.rows[0].pop('f_orders'); self.rows[0]['f_orders_sum'] = None
        for name in ('dash5', 'dash_nm_days', 'by_days'):
            with self.subTest(tab=name):
                res = getattr(basic, name)(self.db, 1, self.filters())
                rows = {r['row']: r for r in res['rows']}
                ids = (11, 12) if name == 'by_days' else (12, 13)
                for n in ids:
                    for col in res['columns'][1:]:
                        self.assertIsNone(rows[n][col['field']])
        self.rows[0].update(f_orders=0, f_orders_sum=0)
        result = basic.dash5(self.db, 1, self.filters())
        rows = {r['row']: r for r in result['rows']}
        self.assertEqual(rows[13]['C'], 0)
        self.assertIsNone(rows[13]['D'])
        self.assertIsNone(rows[13]['E'])

    def test_month_sum_and_forecast_use_funnel_without_statistical_fallback(self):
        self.rows += [dict(day=DAY-timedelta(days=1), orders=9, orders_sum=5000),
                      dict(day=DAY-timedelta(days=2), orders=1, f_orders=2, f_orders_sum=600)]
        report = basic.by_days(self.db, 1, {**self.filters(), 'date_from': DAY-timedelta(days=2)})
        rows = {r['row']: r for r in report['rows']}
        self.assertEqual(rows[11]['2026-11'], 7)
        self.assertEqual(rows[12]['2026-11'], 2600)
        self.assertEqual(rows[3]['2026-11'], 13)
        self.assertIsNone(rows[11][str(DAY-timedelta(days=1))])
        rows = {r['row']: r for r in basic.dash5(self.db, 1, self.filters())['rows']}
        self.assertEqual(rows[13]['I'], 7)
        a, b = dash5.periods(DAY)['M']
        self.assertEqual(rows[13]['M'], round(7 * 30 / ((b-a).days+1), 2))

    def test_only_dashboard_cache_revisions_and_no_selection_guard(self):
        affected = ('dash5', 'dash_nm', 'dash_nm_days', 'dash_group', 'by_days')
        for tab in affected:
            self.assertIn('wb-dashboard-funnel-first:', tabcache.calculation_version(tab, 'v'))
        for tab in ('home', 'pnl_real_w', 'pnl_alt_m', 'svodwb', 'oz_dash', 'ym_dash'):
            self.assertNotIn('wb-dashboard-funnel-first:', tabcache.calculation_version(tab, 'v'))
        for fn in (basic.dash_nm, basic.dash_nm_days):
            self.assertIn('msg', fn(self.db, 1, {})['rows'][0])

    def test_filters_and_legacy_home_calculation_contract_are_unchanged(self):
        with patch.object(nm_day, 'iter_cached', return_value=iter(self.rows)) as read:
            basic.dash_nm(self.db, 1, self.filters())
        self.assertEqual(read.call_args.args[-1], [101])
        old = dash5.compute(self.db, 1, DAY, custom={'day': (DAY, DAY)})
        new = dash5.compute(self.db, 1, DAY, custom={'day': (DAY, DAY)}, funnel_first=True)
        self.assertEqual(old, new)
        self.assertEqual(basic.HOME_ROWS[0][1], 7)


if __name__ == '__main__':
    unittest.main()

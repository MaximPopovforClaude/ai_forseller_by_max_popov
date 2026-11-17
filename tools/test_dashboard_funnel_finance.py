"""Independent numerical cases for the owner's new dashboard order basis."""
import stometric.web
import copy
import unittest
import tracemalloc
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from stometric.agg import nm_day, real_week, buyout
from stometric.sheets import dash5, by_days, funnel_orders as fo
from tools.test_audit_calculations import TaxDB, tax

DAY = date(2026,11,12)


def fixture(**extra):
    return dict(day=DAY, nm_id=101, orders=2, orders_sum=200, orders_sum_spp=150,
                f_orders=5, f_orders_sum=700, cost_orders=80, commission_offer_orders=20,
                logistics_orders=20, logistics_avg_orders=10, vat_orders=0, vat_deduct_orders=0,
                ads_upd=100, ads=100, ads_bonus=20, storage=10, acceptance_sum=5,
                buyouts=1, buyouts_sum=75, buyouts_sum_before_spp=100, for_pay=60,
                cost=40, logistics=10, acquiring=2, cxd_orders=1, cx_orders=1, **extra)


class FunnelFinance(unittest.TestCase):
    def compute(self, rows, tx=None, periods=None, *, legacy=False, costs=None):
        periods = periods or {'day':(DAY,DAY)}
        with patch.object(nm_day,'iter_cached',side_effect=lambda *a:iter(rows)), \
             patch.object(real_week,'weekly_deliveries',return_value=[]), \
             patch.object(buyout,'needed',return_value=True),patch.object(buyout,'for_nms',return_value=.8), \
             patch.object(fo,'cost_history',return_value=costs or {}):
            return dash5.compute(TaxDB([tx or tax('УСН доход',.06)]),1,DAY,custom=periods,funnel_first=not legacy)['values']

    def test_full_order_chain_scales_quantity_and_revenue_separately(self):
        row=fixture(); saved=copy.deepcopy(row)
        v=self.compute([row])['day']
        expected={7:200,8:2,9:150,12:700,13:5,121:525,10:140,11:.25,
                  15:560,16:4,17:420,20:-56,21:-50,22:160,18:294,
                  24:100/700,25:100/560,233:20/700,234:120/700,
                  30:-25.2,31:.06,32:-25.2,33:0,34:0,35:153.8,36:153.8/560,
                  26:100/153.8,89:153.8/160,68:1/5}
        for n,value in expected.items():
            self.assertAlmostEqual(v[n],value,places=7,msg=str(n))
        self.assertEqual(row,saved)
        old=self.compute([row],legacy=True)['day']
        for n in list(range(38,68))+list(range(69,85))+[90,91]:
            if n in old:self.assertEqual(v[n],old[n],n)

    def test_spp_weights_each_sku_day_not_store_average_or_order_count(self):
        a=fixture();b=fixture()
        b.update(nm_id=102,orders=10,orders_sum=1000,orders_sum_spp=900,f_orders=1,f_orders_sum=50)
        v=self.compute([a,b])['day']
        self.assertEqual(v[121],570)                                        
        self.assertAlmostEqual(v[11],1-570/750)
        self.assertEqual(v[22],(200+8)*.8)
        self.assertEqual(v[20],-(70+1)*.8)

    def test_daily_monthly_forecast_and_change_consistency(self):
        a=fixture();b={**fixture(),'day':DAY-timedelta(days=1),'f_orders':10,'f_orders_sum':1400}
        v=self.compute([a,b],periods={'one':(DAY,DAY),'month':(DAY.replace(day=1),DAY),
                                     'M':(DAY-timedelta(days=1),DAY)})
        self.assertEqual(v['month'][121],1575)
        self.assertAlmostEqual(v['month'][35],self.compute([a])['day'][35]+self.compute([b],periods={'day':(b['day'],b['day'])})['day'][35])
        self.assertAlmostEqual(v['M'][121],1575*15)
        self.assertAlmostEqual(v['M'][24],200/2100)
        self.assertAlmostEqual(v['M'][35],v['month'][35]*15)

    def test_vat_and_tax_order_bases_follow_funnel(self):
        r=fixture();r.update(vat_orders=15,vat_deduct_orders=8)
        for regime,rate in [('УСН доход',.06),('УСН доходы-расходы',.15),('ОСНО',.25),('ОСНО ИП (НДФЛ)',.13)]:
            tx=tax(regime,rate,.1);tx['vat_deduct_wb']=.1
            v=self.compute([r],tx)['day']
            self.assertAlmostEqual(v[33],-42)                   
            deduction=16+221/11                                                            
            self.assertAlmostEqual(v[34],deduction)
            if regime=='УСН доход':expected=-.06*(420-42)
            elif regime=='УСН доходы-расходы':expected=-max(.15*(294-100-15-42),4.2)
            else:expected=-rate*(294-100-15-42+deduction)
            self.assertAlmostEqual(v[32],expected)
            self.assertAlmostEqual(v[35],294-100-15+expected-42+deduction)

    def test_missing_spp_does_not_become_zero_tax_or_false_profit(self):
        r=fixture();r['orders_sum_spp']=None
        v=self.compute([r])['day']
        self.assertIsNone(v[121]);self.assertIsNone(v[17]);self.assertIsNone(v[32]);self.assertIsNone(v[35])
        self.assertEqual(v[18],294);self.assertAlmostEqual(v[24],100/700)

    def test_missing_cost_or_logistics_or_commission_invalidates_profit_only(self):
        for key in ('cost_orders','commission_offer_orders','logistics_orders'):
            r=fixture();r[key]=None
            if key=='logistics_orders':r['logistics_avg_orders']=None
            v=self.compute([r])['day']
            self.assertEqual(v[121],525);self.assertIsNone(v[18]);self.assertIsNone(v[35])
            self.assertIsNone(v[89]);self.assertAlmostEqual(v[24],100/700)

    def test_missing_sku_or_day_cannot_give_partial_portfolio_profit(self):
        a=fixture();b={**fixture(),'nm_id':102,'f_orders':None,'f_orders_sum':None}
        v=self.compute([a,b])['day']
        for n in (12,13,121,15,16,17,18,20,21,22,24,25,35,89):self.assertIsNone(v[n],n)
        self.assertEqual(v[7],400);self.assertEqual(v[8],4);self.assertEqual(v[23],-200)

    def test_known_zero_funnel_preserves_real_advertising_loss(self):
        r=fixture();r.update(f_orders=0,f_orders_sum=0)
        v=self.compute([r])['day']
        for n in (12,13,121,15,16,17,18,20,21,22):self.assertEqual(v[n],0,n)
        self.assertEqual(v[35],-115)

    def test_new_cost_history_used_without_statistical_orders(self):
        r=fixture();r.update(orders=0,orders_sum=0,orders_sum_spp=0,cost_orders=0)
        costs={101:[(DAY-timedelta(days=1),Decimal('42.25')),(DAY+timedelta(days=1),900)]}
        v=self.compute([r],costs=costs)['day']
        self.assertEqual(v[22],211.25*.8)
        self.assertIsNone(v[121]);self.assertIsNone(v[20]);self.assertIsNone(v[35])
        self.assertEqual(v[21],-50)                                         

    def test_field_coverage_is_independent_and_prices_are_validated(self):
        r=fixture();r.update(f_orders_sum=None)
        v=self.compute([r])['day'];self.assertEqual(v[13],5);self.assertEqual(v[22],160);self.assertIsNone(v[12])
        for net in (float('nan'),float('inf'),-1,201):
            r=fixture();r['orders_sum_spp']=net
            self.assertIsNone(self.compute([r])['day'][121])

    def test_day_dashboard_keeps_actuals_and_uses_new_drr_denominator(self):
        with patch.object(nm_day,'iter_cached',return_value=iter([fixture()])):
            result=by_days.compute(TaxDB([tax('УСН доход',.06)]),1,DAY,DAY,[101])
        rows={r['row']:r for r in result['rows']};d=str(DAY)
        for col in (d,'2026-11'):
            self.assertEqual(rows[121][col],525)
            self.assertEqual(rows[27][col],round(100/700,4))
            self.assertEqual(rows[8][col],.2);self.assertEqual(rows[16][col],.2)
            self.assertEqual(rows[23][col],40)
            self.assertEqual(rows[32][col],-104.5)                          

    def test_new_period_accumulator_remains_streaming(self):
        def stream():
            for _ in range(12000):
                yield fo.project(fixture(), {}, vat_enabled=False)
        tracemalloc.start()
        try:
            totals=fo.sum_strict(stream(), {'day':(DAY,DAY),'month':(DAY.replace(day=1),DAY)})
            _, peak=tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(totals['month']['f_orders_sum_spp'],525*12000)
        self.assertLess(peak,2_000_000)


if __name__=='__main__':unittest.main()

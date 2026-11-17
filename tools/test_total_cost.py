"""Totals reuse dashboard cost/profit, preserving dates, signs and access scope."""
import stometric.web
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch
import unittest
from stometric import api_total as total
from tools.test_calendar import Cursor

TODAY=date(2026,11,14)
FILTER={'date_from':date(2026,10,16),'date_to':TODAY,'nm_ids':[77],'group':None}


class TotalCostTests(unittest.TestCase):
    def test_wb_cost_row_not_orders_or_month_total(self):
        d='2026-11-13'
        rows=[{'row':n,d:Decimal(str(v)),'2026-11':999999} for n,v in [(4,1000),(18,800),(23,234.56),(24,400),(26,-50),(32,300)]]
        report={'rows':rows,'columns':[{'field':x} for x in ('label','2026-11',d)],'stale':True}
        with patch.object(total,'_cached',return_value=report) as cache:
            series,stale=total._wb(None,7,FILTER)
        cache.assert_called_once_with(None,'by_days',7,FILTER)
        self.assertEqual(series,{d:dict(orders=1000,buyouts=800,cost_sold=234.56,margin=400,ads=-50,profit=300)})
        self.assertTrue(stale)

    def test_oz_cost_keeps_net_returns_and_finance_profit(self):
        report={'rows':[{'key':k,'d0':v,'d1':v*2} for k,v in dict(o_sum=1000,b_sum=800,r_sum=-50,f_com=-40,f_log=-20,f_acq=-10,b_cost=-100,f_profit=320,ads=-60).items()],
                'columns':[{'field':k} for k in ('label','d0','d1')],'stale':False}
        with patch.object(total,'_cached',return_value=report) as cache, patch.object(total,'today_msk',return_value=TODAY):
            series,stale=total._oz(None,9,FILTER)
        cache.assert_called_once_with(None,'oz_dash',9,FILTER)
        self.assertEqual(series['2026-11-13'],dict(orders=1000,buyouts=800,ads=-60,profit=320,cost_sold=-100,margin=780))
        self.assertEqual(series['2026-11-12']['cost_sold'],-200)
        self.assertNotIn(TODAY.isoformat(),series);self.assertFalse(stale)
        with patch.object(total,'_cached',return_value=report),patch.object(total,'today_msk',return_value=TODAY):
            old,_=total._oz(None,9,{**FILTER,'date_to':date(2026,11,10)})
        self.assertEqual(max(old),'2026-11-10')

    def test_ym_cost_uses_same_dashboard_as_profit(self):
        values=dict(o_sum=1000,b_sum=800,r_sum=50,x_total=-100,x_boost=-20,b_cost=200,f_profit=430)
        report={'rows':[{'key':k,'d0':v} for k,v in values.items()],'columns':[{'field':'d0'}]}
        with patch.object(total,'_cached',return_value=report) as cache,patch.object(total,'today_msk',return_value=TODAY):
            series,_=total._ym(None,11,FILTER)
        cache.assert_called_once_with(None,'ym_dash',11,FILTER)
        self.assertEqual(series[TODAY.isoformat()],dict(orders=1000,buyouts=800,ads=-20,profit=430,cost_sold=200,margin=470))

    def test_missing_cost_is_unknown_and_zero_is_known(self):
        for adapter in (total._wb,total._oz,total._ym):
            for value in (None,0,Decimal('12.34')):
                if adapter is total._wb:
                    report={'rows':[{'row':n,'2026-11-13':value if n==23 else 7} for n in total.WB_ROW.values()],
                            'columns':[{'field':'2026-11-13'}]}
                else:
                    report={'rows':[{'key':'b_cost','d0':value},{'key':'f_profit','d0':7}], 'columns':[{'field':'d0'}]}
                with patch.object(total,'_cached',return_value=report),patch.object(total,'today_msk',return_value=TODAY):
                    r,_=adapter(None,7,FILTER)
                self.assertEqual(next(iter(r.values()))['cost_sold'],None if value is None else float(value))
            report['rows']=[r for r in report['rows'] if r.get('row')!=23 and r.get('key')!='b_cost']
            with patch.object(total,'_cached',return_value=report),patch.object(total,'today_msk',return_value=TODAY):
                r,_=adapter(None,7,FILTER)
            self.assertIsNone(next(iter(r.values()))['cost_sold'])

    def test_nonfinite_not_emitted(self):
        for value in (float('nan'),float('inf'),Decimal('-Infinity')): self.assertIsNone(total._cost(value))

    def test_total_staff_keeps_authorized_shops_and_sku_filter(self):
        c=Mock();c.execute.side_effect=[Cursor([{'workspace_id':1}]),Cursor([])]
        shops=[{'id':7,'workspace_id':1,'title':'Fixture','name':'fixture','marketplace':'wb','workspace':'Fixture workspace'},
               {'id':9,'workspace_id':2,'title':'Other scope','name':'fixture2','marketplace':'ozon','workspace':'Other workspace'}]
        user={'id':42}
        with patch.object(total,'today_msk',return_value=TODAY),patch.object(total.auth,'shops_for',return_value=shops), \
             patch('stometric.staff.nms',return_value=[77]) as nms,patch.object(total,'_wb',return_value=({'2026-11-13':{'profit':5,'cost_sold':20}},False)) as wb,patch.object(total,'_oz') as oz:
            result=total.total(staff=8,u=user,c=c)
        self.assertEqual([s['id'] for s in result['shops']],[7]);nms.assert_called_once_with(c,7,8);oz.assert_not_called()
        self.assertEqual(wb.call_args.args[2]['nm_ids'],[77]);self.assertIn('cost_sold',result['keys'])
        self.assertEqual(result['shops'][0]['series']['2026-11-13']['cost_sold'],20)

if __name__=='__main__': unittest.main()

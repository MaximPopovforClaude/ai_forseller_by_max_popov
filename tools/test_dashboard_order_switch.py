"""Order-basis switching: numerical equivalence, isolation, routes and exports."""
import stometric.web as web
import io
import json
import unittest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from openpyxl import load_workbook
from stometric import tabcache, gdrive
from stometric.sheets import dash5
from stometric.tabs import basic
from tools import test_dashboard_sources as base_tests
DAY = base_tests.DAY


class OrderSwitch(base_tests.DashboardSources):
    def test_statistics_mode_matches_legacy_finance_for_all_four_dashboard_views(self):
        with patch.object(basic, 'group_nms', return_value=[101]):
            for name in ('dash5','dash_nm','dash_nm_days','dash_group'):
                p = {**self.filters(), 'group':'test', 'order_source':'statistics'}
                result = getattr(basic,name)(self.db,1,p)
                if name == 'dash_nm_days':
                    old=dash5.compute(self.db,1,DAY,[101],custom={f'd{i}':(DAY-timedelta(days=i),DAY-timedelta(days=i)) for i in range(30)})
                    expected={n:{col:dash5.rounded(v.get(n),4 if dash5.ROW[n][1]=='pct' else 2) for col,v in old['values'].items()} for n in dash5.ROW}
                else:
                    expected={r['row']:{k:v for k,v in r.items() if k not in ('row','label','fmt')} for r in dash5.compute(self.db,1,DAY,[101])['rows']}
                indexed={r['row']:r for r in result['rows']}
                for n,values in expected.items():
                    if n in (12,13):continue                                                      
                    for col,value in values.items():self.assertEqual(indexed[n].get(col),value,(name,n,col))
                self.assertTrue(all('статистики WB' in r['label'] for r in result['rows'][1:4]))
                self.assertIn('Основа показателей по заказам — статистика WB',result['note'])
                default=getattr(basic,name)(self.db,1,self.filters()|{'group':'test'})
                explicit=getattr(basic,name)(self.db,1,self.filters()|{'group':'test','order_source':'funnel'})
                self.assertEqual(default,explicit)

    def test_statistics_taxes_forecast_and_actuals_match_legacy_with_vat(self):
        from tools.test_audit_calculations import TaxDB, tax
        from tools.test_dashboard_funnel_finance import fixture
        self.rows[:] = [fixture(), {**fixture(), 'day': DAY-timedelta(days=1)}]
        for regime,rate in [('УСН доход',.06),('УСН доходы-расходы',.15),('ОСНО',.25),('ОСНО ИП (НДФЛ)',.13)]:
            tx=tax(regime,rate,.1);tx['vat_deduct_wb']=.1
            for row in self.rows:row.update(vat_orders=15,vat_deduct_orders=8)
            db=TaxDB([tx]);old=dash5.compute(db,1,DAY,[101])
            new=basic.dash5(db,1,self.filters()|{'order_source':'statistics'})
            lookup={r['row']:r for r in new['rows']}
            for row in old['rows']:
                if row['row'] in (12,13):continue
                for col,value in row.items():
                    if col not in ('label','row','fmt'):self.assertEqual(value,lookup[row['row']][col],(regime,row['row'],col))

    def test_statistics_finance_survives_missing_funnel_and_switching_back_does_not_fallback(self):
        self.rows[0].update(f_orders=None,f_orders_sum=None)
        stat={r['row']:r for r in basic.dash5(self.db,1,self.filters()|{'order_source':'statistics'})['rows']}
        funnel={r['row']:r for r in basic.dash5(self.db,1,self.filters())['rows']}
        self.assertEqual(stat[15]['C'],900)
        self.assertIsNotNone(stat[35]['C']);self.assertIsNone(funnel[35]['C'])
        self.assertIsNone(stat[121]['C']);self.assertIsNone(stat[13]['C'])

    def test_day_view_changes_order_ratios_only(self):
        a=basic.by_days(self.db,1,self.filters())
        b=basic.by_days(self.db,1,self.filters()|{'order_source':'statistics'})
        ar={r['row']:r for r in a['rows']};br={r['row']:r for r in b['rows']};d=str(DAY)
        self.assertEqual(br[27][d],.1);self.assertEqual(ar[27][d],.06)
        self.assertEqual(br[8][d],round(1/3,4));self.assertEqual(ar[8][d],.2)
        self.assertEqual(br[32][d],ar[32][d])
        for n in ar:
            if n not in (8,16,27):self.assertEqual(ar[n],br[n])
        self.assertEqual([r['row'] for r in b['rows'][:3]],[3,4,5])
        self.assertIn('прибыль — по фактическим продажам',b['note'])

    def test_cache_separates_modes_shops_and_filters_with_default_precompute_compatibility(self):
        p=self.filters(); c=MagicMock()
        for key in ('dash5','dash_nm','dash_nm_days','dash_group','by_days'):
            default=tabcache.tab_params(c,key,1,p)
            funnel=tabcache.tab_params(c,key,1,p|{'order_source':'funnel'})
            stat=tabcache.tab_params(c,key,1,p|{'order_source':'statistics'})
            self.assertEqual(default,funnel)
            self.assertNotEqual(tabcache.fkey(default),tabcache.fkey(stat))
            self.assertNotEqual(tabcache.fkey(stat),tabcache.fkey(stat|{'nm_ids':[102]}))
        for key in ('home','pnl_real_w','oz_dash','ym_dash5'):
            self.assertEqual(tabcache.tab_params(c,key,1,p),tabcache.tab_params(c,key,1,p|{'order_source':'statistics'}))

    def test_tab_route_preserves_access_filters_and_rejects_invalid_source(self):
        with patch.object(web.auth,'shop_role',return_value='viewer'),patch.object(web,'_cached',return_value={'columns':[],'rows':[]}) as cached, \
             patch('stometric.exclusions.excluded',return_value=[]),patch('stometric.staff.narrow',return_value=[101]):
            res=web.tab(1,'dash5',DAY,DAY,nm_ids='101,102',staff=2,u={'id':99},c=self.db,order_source='statistics')
            self.assertEqual(json.loads(res.body)['key'],'dash5')
            self.assertEqual(cached.call_args.args[3]['order_source'],'statistics')
            self.assertEqual(cached.call_args.args[3]['nm_ids'],[101])
            web.tab(1,'home',DAY,DAY,u={'id':99},c=self.db,order_source='statistics')
            self.assertNotIn('order_source',cached.call_args.args[3])
            with self.assertRaises(web.HTTPException) as err:web.tab(1,'dash5',u={'id':99},c=self.db,order_source='bad')
            self.assertEqual(err.exception.status_code,422)
        with patch.object(web.auth,'shop_role',return_value=None),patch.object(web,'_cached') as cached:
            with self.assertRaises(web.HTTPException) as err:web.tab(1,'dash5',u={'id':99},c=self.db,order_source='statistics')
            self.assertEqual(err.exception.status_code,403);cached.assert_not_called()
        for route in web.app.routes:
            if getattr(route,'endpoint',None) in (web.tab,web.tab_xlsx,web.tab_gsheet):
                field=next(f for f in route.dependant.query_params if f.name=='order_source')
                self.assertFalse(field.validate('statistics',{},loc=('query','order_source'))[1])
                self.assertTrue(field.validate('bad',{},loc=('query','order_source'))[1])

    def test_xlsx_and_google_use_selected_report_with_note_and_actual_values(self):
        db=MagicMock();db.execute.return_value.fetchone.return_value={'t':'Synthetic','workspace_id':1}
        user={'id':99,'email':'test@example.invalid'}
        with patch.object(web.auth,'shop_role',return_value='viewer'),patch('stometric.exclusions.excluded',return_value=[]), \
             patch.object(web,'_cached',side_effect=lambda c,k,s,f:getattr(basic,k)(self.db,s,f)), \
             patch.object(gdrive,'ready',return_value=True),patch.object(gdrive,'upload',return_value={'url':'https://example.invalid/test'}) as upload,patch.object(web,'_audit'):
            for mode in ('funnel','statistics'):
                report=basic.dash5(self.db,1,self.filters()|{'order_source':mode})
                expected=next(r['C'] for r in report['rows'] if r['row']==35)
                response=web.tab_xlsx(1,'dash5',DAY,DAY,nm_ids='101',cols='label,C',u=user,c=db,order_source=mode)
                workbook=load_workbook(io.BytesIO(response.body),data_only=True)
                rows=list(workbook.active.values)
                profit=next(r for r in rows if r[0]==dash5.ROW[35][0]);self.assertEqual(profit[1],expected)
                self.assertTrue(any(report['note'] in str(r[0]) for r in rows))
                web.tab_gsheet(1,'dash5',DAY,DAY,nm_ids='101',cols='label,C',u=user,c=db,order_source=mode)
                google=load_workbook(io.BytesIO(upload.call_args.args[1]),data_only=True)
                self.assertEqual(list(google.active.values),rows)


if __name__=='__main__':unittest.main()

"""Synthetic Ozon order prices; no credentials, production DB or network."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import unittest
from unittest.mock import patch
import stometric.web
from stometric import ozon_order_prices as prices, tabcache
from stometric.sheets import ozdash, ozv2
from stometric.tabs import ozon

DAY = date(2026, 9, 5)

class Rows(list):
    def fetchall(self): return list(self)
    def fetchone(self): return self[0] if self else None

def posting(sku=1, qty=2, price='100.05', customer='75.01', day=DAY, currency='RUB', scheme='fbo', status='delivered'):
    return dict(account_id=1, order_day=day, sku=sku, qty=qty, price=Decimal(price), scheme=scheme, status=status,
                financial_products=[dict(product_id=sku, quantity=qty, customer_price=customer, customer_currency_code=currency)])

class DB:
    def __init__(self, rows): self.rows=rows; self.queries=[]
    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if 'FROM oz_postings' in sql:
            assert 'account_id=%s' in sql and 'order_day BETWEEN %s AND %s' in sql
            return Rows(r for r in self.rows if r['account_id']==params[0] and params[1]<=r['order_day']<=params[2])
        if 'FROM oz_analytics' in sql:
            return Rows([dict(day=DAY, sku=1, m={'ordered_units':10,'revenue':1200})])
        if 'FROM article_groups' in sql: return Rows([{'nm_id':2}])
        return Rows()

class OrderPriceTests(unittest.TestCase):
    def test_matches_financial_item_by_sku_not_position(self):
        row=posting();row['financial_products'].insert(0,dict(product_id=99,customer_price='9999',customer_currency_code='RUB'))
        self.assertEqual(prices.customer_price(row),Decimal('75.01'))
        item=row['financial_products'][1];item['sku']=1;item['product_id']=90
        self.assertEqual(prices.customer_price(row),Decimal('75.01'))
        item['sku']=99;item['product_id']=1
        self.assertIsNone(prices.customer_price(row))
        row['financial_products']=[dict(product_id=1,customer_price='1',customer_currency_code='RUB')]*2
        self.assertIsNone(prices.customer_price(row))

    def test_currency_quantity_and_invalid_amounts_fail_closed(self):
        for value in (None,'',True,-1,'NaN','Infinity',{},[],'not-money'):
            with self.subTest(value=value):self.assertIsNone(prices.customer_price(posting(customer=value)))
        for currency in ('BYN','KZT',None,''):
            self.assertIsNone(prices.customer_price(posting(currency=currency)))
        row=posting();row['financial_products'][0]['quantity']=5
        self.assertIsNone(prices.customer_price(row))
        row=posting(customer={'amount':'80.02','currency':'RUB'},currency=None)
        self.assertEqual(prices.customer_price(row),Decimal('80.02'))
        row['financial_products'][0]['customer_currency_code']='BYN'
        self.assertIsNone(prices.customer_price(row))

    def test_real_zero_is_preserved_and_missing_is_not_zero(self):
        v=prices.period(prices.daily([posting(customer=0)]),DAY,DAY)
        self.assertEqual(v['order_customer_sum'],0);self.assertEqual(v['order_price_coverage'],1)
        v=prices.period(prices.daily([posting(customer=None)]),DAY,DAY)
        self.assertIsNone(v['order_customer_sum']);self.assertEqual(v['order_price_coverage'],0)
        self.assertTrue(all(x is None for x in prices.period({},DAY,DAY).values()))

    def test_partial_period_never_shows_partial_money_as_full_total(self):
        rows=[posting(), posting(sku=2,qty=1,customer=None,day=DAY+timedelta(days=1))]
        data=prices.daily(rows);v=prices.period(data,DAY,DAY+timedelta(days=1))
        self.assertIsNone(v['order_customer_sum']);self.assertAlmostEqual(v['order_price_coverage'],2/3)
        self.assertEqual(prices.period(data,DAY,DAY)['order_customer_sum'],150.02)
        self.assertEqual(prices.period(prices.daily(rows,[1]),DAY,DAY+timedelta(days=1))['order_customer_sum'],150.02)
        self.assertIsNone(prices.period(prices.daily(rows,[]),DAY,DAY)['order_customer_sum'])

    def test_scoped_query_projects_finances_and_filters_dates(self):
        a=posting();foreign={**posting(sku=2,customer='9999'), 'account_id':99}
        old=posting(day=DAY-timedelta(days=1));c=DB([a,foreign,old])
        v=prices.period(prices.load_daily(c,1,DAY,DAY),DAY,DAY)
        self.assertEqual(v['order_customer_sum'],150.02)
        self.assertIn("raw#>'{financial_data,products}'",c.queries[0][0]);self.assertNotIn('SELECT *',c.queries[0][0])

    def test_both_dashboards_use_same_orders_including_cancelled_fbs(self):
        rows=[posting(),posting(sku=2,qty=1,price='40',customer='30',scheme='fbs',status='cancelled')]
        c=DB(rows)
        old=ozdash.compute(c,1,DAY,DAY);mapping={r['key']:r for r in old['rows']}
        self.assertEqual(mapping['o_sum']['d0'],240.1)
        self.assertEqual(mapping['order_customer_sum']['d0'],180.02)
        self.assertEqual(mapping['c_sum']['d0'],40)
        r=ozv2.compute(c,1,'day',DAY,DAY)
        self.assertEqual(r['tot']['ordered_sum'],1200)
        self.assertEqual(r['tot']['order_seller_sum'],240.1)
        self.assertEqual(r['tot']['order_customer_sum'],180.02)
        for skus,total in (([1],150.02),([2],30)):
            self.assertEqual(ozv2.compute(c,1,'day',DAY,DAY,skus)['tot']['order_customer_sum'],total)

    def test_week_month_totals_and_averages_preserve_missing_values(self):
        later=DAY+timedelta(days=9)
        for kind in ('day','week','month'):
            r=ozv2.compute(DB([posting(),posting(sku=2,qty=1,customer=None,day=later)]),1,kind,DAY,later)
            rows={x['key']:x for x in r['rows']}
            self.assertIsNone(rows['order_customer_sum']['total']);self.assertIsNone(rows['order_customer_sum']['avg'])
            self.assertAlmostEqual(r['tot']['order_price_coverage'],2/3)
            self.assertNotIn('empty',rows['order_customer_sum'])
        r=ozv2.compute(DB([posting(customer=0)]),1,'day',DAY,DAY)
        row=next(x for x in r['rows'] if x['key']=='order_customer_sum')
        self.assertEqual((row['p0'],row['total'],row['avg']),(0,0,0))

    def test_legacy_financial_metrics_are_independent_of_customer_prices(self):
        rows=[posting()];before=ozv2.compute(DB(rows),1,'day',DAY,DAY)['tot']
        changed=deepcopy(rows);changed[0]['financial_products'][0]['customer_price']='10'
        after=ozv2.compute(DB(changed),1,'day',DAY,DAY)['tot']
        for key,value in before.items():
            if key not in prices.KEYS:self.assertEqual(after[key],value,key)
        before=ozdash.compute(DB(rows),1,DAY,DAY)['rows'];after=ozdash.compute(DB(changed),1,DAY,DAY)['rows']
        for a,b in zip(before,after):
            if a['key'] not in prices.KEYS:self.assertEqual(a,b)

    def test_public_tab_wrappers_group_filter_and_home_unknown(self):
        c=DB([posting(),posting(sku=2,customer=None)])
        f=dict(date_from=DAY,date_to=DAY,group='Synthetic')
        with patch.object(ozon,'today_msk',return_value=DAY+timedelta(days=1)):
            for fn in (ozon.v2_day,ozon.v2_week,ozon.v2_month):
                r=fn(c,1,f);row=next(x for x in r['rows'] if x['key']=='order_customer_sum')
                self.assertIsNone(row['total']);self.assertIn('полнота',r['note'])
            r=ozon.home(c,1,f);row=next(x for x in r['rows'] if x['label']==prices.CUSTOMER_LABEL)
            self.assertIsNone(row['D']);self.assertIn('отправления',r['hint'])
            self.assertIn('отправления',ozon.dash(c,1,f)['note'])

    def test_cache_versions_expire_changed_views_only(self):
        for tab in ('oz_dash','v2_day','v2_week','v2_month','home'):
            self.assertIn('ozon-order-prices',tabcache.calculation_version(tab,'data'))
        for tab in ('pnl_real_m','v2_opiu','oz_svod'):
            self.assertNotIn('ozon-order-prices',tabcache.calculation_version(tab,'data'))

if __name__=='__main__':unittest.main()

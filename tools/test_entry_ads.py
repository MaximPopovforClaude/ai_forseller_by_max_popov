"""Advertising payment split and incomplete-source regression; synthetic sources only."""
import stometric.web
import json
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from stometric import entry, entry_ads as ads
from tools import test_entry_conversions as conversions

D = date(2026, 11, 12)
P = date(2026, 11, 11)
def counts(v=100, c=10, b=4, o=2):
    return dict(views=v, clicks=c, carts=b, orders=o)

class SplitTests(unittest.TestCase):
    def test_cpc_with_positive_clicks_never_zero_impressions(self):
        for views in (None, 0, 100):
            r=ads.Advertising({(D,1,77):counts(1000,162,70,55)},
                              {(D,1,77):counts(views,132,64,50)}, {1:'cpc'}).period([D])
            self.assertEqual(r['search_cpc']['clicks'],132)
            self.assertEqual(r['rest_cpc']['clicks'],30)
            self.assertEqual(r['rest_cpc']['carts'],6)
            self.assertEqual(r['rest_cpc']['orders'],5)
            for k in ('search','rest','search_cpc','rest_cpc'):
                self.assertIsNone(r[k]['views']);self.assertIsNone(r[k]['ctr'])
            self.assertEqual(r['total']['views'],1000)
    def test_mixed_payment_never_presents_partial_views_as_complete(self):
        r=ads.Advertising({(D,1,77):counts(),(D,2,77):counts()},
                          {(D,1,77):counts(80,6,2,1),(D,2,77):counts(None,6,2,1)},
                          {1:'cpm',2:'cpc'}).period([D])
        self.assertEqual(r['search_cpm']['views'],80);self.assertEqual(r['rest_cpm']['views'],20)
        self.assertEqual(r['search']['clicks'],12);self.assertEqual(r['rest']['clicks'],8)
        self.assertIsNone(r['search']['views']);self.assertIsNone(r['rest']['views'])
        self.assertEqual(r['search_cpc']['conv_cart'],2/6)
    def test_missing_campaign_pair_does_not_move_all_traffic_outside_search(self):
        for totals,search in (({(D,1,77):counts()},{}), ({},{(D,1,77):counts()})):
            r=ads.Advertising(totals,search,{1:'cpm'}).period([D])
            self.assertTrue(all(r['rest'][f] is None for f in ads.FIELDS))
    def test_negative_campaign_remainder_cannot_be_offset_by_another(self):
        r=ads.Advertising({(D,1,77):counts(10,2), (D,2,77):counts(1000,100)},
                          {(D,1,77):counts(20,3), (D,2,77):counts(50,10)}, {1:'cpm',2:'cpm'}).period([D])
        self.assertEqual(r['rest_cpm']['views'],950);self.assertEqual(r['rest_cpm']['clicks'],90)
        self.assertEqual(r['rest_cpm']['partial'],['clicks','views']);self.assertIsNone(r['rest_cpm']['ctr'])
        self.assertEqual(r['rest_cpm']['orders'],0)
    def test_payment_never_inferred_from_zero_or_missing_views(self):
        r=ads.Advertising({(D,1,77):counts()}, {(D,1,77):counts(None)},{}).period([D])
        self.assertTrue(r['unknown_payment']);self.assertEqual(r['search_unknown']['clicks'],10)
        self.assertIsNone(r['search_cpc']['clicks']);self.assertIsNone(r['search_cpm']['clicks'])
    def test_zero_is_known_missing_day_marks_partial_and_unselected_date_excluded(self):
        a=ads.Advertising({(D,1,77):counts()}, {(D,1,77):counts(0,0,0,0)}, {1:'cpm'})
        self.assertEqual(a.period([D])['search_cpm']['views'],0)
        self.assertIsNone(a.period([D])['search_cpm']['ctr'])
        self.assertEqual(a.period([D])['rest_cpm']['clicks'],10)
        self.assertEqual(a.period([P,D])['rest_cpm']['clicks'],10)
        self.assertIn('clicks',a.period([P,D])['rest_cpm']['partial'])
    def test_ratios_use_sums_and_fields_are_independent(self):
        r=ads.Advertising({(D,1,77):counts(),(P,1,77):counts()},
                          {(D,1,77):counts(None,8,4,2),(P,1,77):counts(10,2,2,1)}, {1:'cpm'}).period([P,D])
        self.assertEqual(r['search']['views'],10);self.assertIn('views',r['search']['partial'])
        self.assertIsNone(r['search']['ctr']);self.assertEqual(r['search']['conv_cart'],.6)
        self.assertEqual(r['search']['conv_order'],.5)
    def test_disjoint_sources_do_not_blank_whole_shop(self):
        x=counts()
        a=ads.Advertising({(D,1,11):x,(D,2,11):x,(D,3,11):x,(D,4,11):x},
                          {(D,1,11):x,(D,2,11):x,(D,5,11):x,(D,6,11):x},
                          {1:'cpm',2:'cpc',3:'cpm',4:'cpc',5:'cpm',6:'cpc'})
        r=a.period([D])
        self.assertEqual(r['total']['clicks'],40);self.assertEqual(r['search']['clicks'],40)
        self.assertEqual(r['search_cpm']['clicks'],20);self.assertEqual(r['search_cpc']['clicks'],20)
        self.assertEqual(r['rest_cpm']['clicks'],0);self.assertEqual(r['rest_cpc']['clicks'],0)
        for key in ('total','search','search_cpm','search_cpc','rest_cpm','rest_cpc'):
            self.assertIn('clicks',r[key]['partial']);self.assertIsNone(r[key]['conv_cart'])
        self.assertEqual(r['total']['views'],400);self.assertEqual(r['search_cpm']['views'],200)
        self.assertIsNone(r['search_cpc']['views']);self.assertIsNone(r['search']['views'])
        org=ads.metrics(ads.difference(counts(1000,100,50,25),r['total']))
        self.assertEqual(org['clicks'],60);self.assertIn('clicks',org['partial']);self.assertIsNone(org['ctr'])
    def test_invalid_nonfinite_not_exposed_as_zero(self):
        for value in (-1,True,'oops',float('nan'),float('inf')):
            self.assertIsNone(ads.number(value))
            self.assertIsNone(ads.difference(counts(value),counts())['views'])
    def test_partial_campaign_remainder_is_excluded_but_other_campaign_survives(self):
        a=ads.Advertising({(D,1,77):{**counts(), 'partial':['clicks']},(D,2,77):counts()},
                          {(D,1,77):counts(50,5),(D,2,77):counts(50,5)}, {1:'cpm',2:'cpm'})
        r=a.period([D])
        self.assertEqual(r['total']['clicks'],20)
        self.assertEqual(r['rest']['clicks'],5)
        self.assertIn('clicks',r['rest']['partial'])

class SqlTests(unittest.TestCase):
    setUpClass = classmethod(conversions.EntrySqlTests.setUpClass.__func__)
    tearDownClass = classmethod(conversions.EntrySqlTests.tearDownClass.__func__)
    result = conversions.EntrySqlTests.result
    def setUp(self):
        conversions.EntrySqlTests.setUp(self)
        self.c.raw('''ALTER TABLE entry_reports ADD file_name text, ADD uploaded_at timestamptz DEFAULT now(), ADD uploaded_by int;
            CREATE TABLE users(id int,name text,email text);
            CREATE INDEX raw_scope ON raw_rows(account_id,source,row_date);''')
                                                                                                            
        for shop, nm, aid, payment in ((7,77,501,'cpm'),(7,77,502,'cpc'),(8,77,501,'cpc'),(7,88,503,'cpc'),(7,99,504,'cpm')):
            for d in (P,D):
                factor=1 if shop==7 and nm==77 else 1000
                item=dict(nmId=nm,views=100*factor,clicks=10*factor,atbs=4*factor,orders=2*factor)
                full=dict(advertId=aid,apps=[dict(nms=[item]),dict(nms=[item])])
                self.c.execute('INSERT INTO raw_rows VALUES(%s,%s,%s,%s,%s)',(shop,'ad_stats',f'{aid}-{d}',d,json.dumps(full)))
                for _ in range(2):
                    self.c.execute('INSERT INTO wb_ad_kw_daily VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',
                        (shop,nm,d,80 if payment=='cpm' else None,6*factor,2*factor,1*factor,aid))
            meta=dict(advertId=aid,info=dict(settings=dict(payment_type=payment)))
            self.c.execute('INSERT INTO raw_rows VALUES(%s,%s,%s,%s,%s)',(shop,'adverts',str(aid),None,json.dumps(meta)))
    def detail(self,**kw):
        with patch('stometric.exclusions.excluded',return_value={99}): return entry.view(self.c,7,nms=[77],**kw)
    def test_real_sql_same_results_in_three_views_and_both_grains(self):
        detail=self.detail(mode='days')
        r=detail['ads']['2'];self.assertEqual(r['search_cpm']['views'],160)
        self.assertEqual(r['search_cpc']['clicks'],12);self.assertEqual(r['rest_cpc']['clicks'],8)
        self.assertIsNone(r['search']['views']);self.assertIsNone(r['rest']['views'])
        for grain in ('day','week','month'):
            d=self.result(nms=[77],grain=grain)
            search=next(s for s in d['sources'] if s['section']=='Поиск')
            rest=next(s for s in d['sources'] if s.get('ad_only'))
            self.assertEqual(search['payment']['cpm']['views'],320)
            self.assertEqual(search['payment']['cpc']['clicks'],24)
            self.assertEqual(rest['payment']['cpc']['clicks'],16)
            self.assertIsNone(rest['payment']['cpc']['views'])
            self.assertIsNone(search['ad_views']);self.assertIsNone(search['org_views'])
            self.assertEqual(d['sources_days'][0]['days'][D.isoformat()]['payment']['cpc'], r['search_cpc'])
            self.assertEqual(d['funnel']['total']['all']['orders_sum'],1500,'finance unchanged')
    def test_sql_null_inside_keyword_sum_is_not_zero(self):
        self.c.raw("UPDATE wb_ad_kw_daily SET views=NULL WHERE account_id=7 AND advert_id=501 AND day='2026-11-12';")
        r=self.detail(mode='days')['ads']['2']
        self.assertIsNone(r['search_cpm']['views']);self.assertIsNone(r['rest_cpm']['views'])
        self.assertEqual(r['search_cpm']['clicks'],12)
    def test_excluded_products_and_foreign_shop_never_leak(self):
        selected=ads.load(self.c,7,[77,99],[99],P,D).period([D])
        self.assertEqual(selected['total']['clicks'],40)
        self.assertEqual(selected['search_cpm']['clicks'],12)
        self.assertTrue(all(ads.load(self.c,7,[],[],P,D).period([D])['total'][f] is None for f in ads.FIELDS))
    def test_missing_reports_not_used_in_weekly_ads(self):
        self.c.raw('DELETE FROM entry_reports WHERE id=1;')
        r=self.detail(mode='weeks')['ads']['w0']
        self.assertEqual(r['search_cpc']['clicks'],12)
        self.assertEqual(self.result(nms=[77])['sources'][0]['payment']['cpc']['clicks'],12)
    def test_period_report_does_not_claim_missing_ad_days_complete(self):
        r=self.detail(mode='reports',reports=[4])['ads']['4']
        self.assertEqual(r['total']['clicks'],80);self.assertIn('clicks',r['total']['partial'])
        self.assertEqual(r['rest_cpm']['views'],80);self.assertIn('views',r['rest_cpm']['partial'])
    def test_search_absent_from_entry_still_displays_payment_split(self):
        self.c.raw("UPDATE entry_rows SET section='Карточка товара' WHERE nm_id=77;")
        d=self.result(nms=[77]);s=next(s for s in d['sources'] if s['section']=='Реклама в поиске')
        self.assertTrue(s['ad_only']);self.assertEqual(s['payment']['cpc']['clicks'],24)
    def test_missing_search_entry_day_does_not_hide_saved_ad_day(self):
        self.c.raw("UPDATE entry_rows SET section='Карточка товара' WHERE nm_id=77 AND report_id=2;")
        d=self.result(nms=[77]);s=next(s for s in d['sources_days'] if s['section']=='Поиск')
        self.assertIsNone(s['days'][D.isoformat()]['views'])
        self.assertEqual(s['days'][D.isoformat()]['payment']['cpc']['clicks'],12)
    def test_unknown_payment_not_dropped_or_guessed(self):
        self.c.raw("DELETE FROM raw_rows WHERE account_id=7 AND source='adverts' AND row_key='502';")
        r=self.detail(mode='days')['ads']['2'];self.assertTrue(r['unknown_payment'])
        self.assertEqual(r['search_unknown']['clicks'],12);self.assertIsNone(r['search_cpc']['clicks'])
    def test_sql_matches_each_campaign_before_calculating_remainder(self):
        self.c.raw("UPDATE wb_ad_kw_daily SET clicks=100 WHERE account_id=7 AND advert_id=501 AND day='2026-11-12';")
        r=self.detail(mode='days')['ads']['2']
        self.assertIsNone(r['rest_cpm']['clicks']);self.assertEqual(r['rest']['clicks'],8)
        self.assertIn('clicks',r['rest']['partial'])
        self.assertEqual(r['rest_cpc']['clicks'],8)
        self.assertEqual(r['rest_cpm']['orders'],2)
        self.c.raw("DELETE FROM wb_ad_kw_daily WHERE account_id=7 AND advert_id=502;")
        r=self.detail(mode='days')['ads']['2']
        self.assertIsNone(r['rest_cpc']['clicks']);self.assertIsNone(r['search_cpc']['clicks'])
        self.assertEqual(r['total']['clicks'],40)
    def test_all_products_unmatched_campaigns_preserve_independent_source_values(self):
                                                                                                  
        self.c.raw("DELETE FROM wb_ad_kw_daily WHERE account_id=7 AND nm_id=88;")
        for aid in (501,502):
            self.c.execute('INSERT INTO wb_ad_kw_daily VALUES(7,77,%s,%s,6,2,1,%s)', (D,80 if aid==501 else None,aid+10))
            self.c.execute('INSERT INTO raw_rows VALUES(7,%s,%s,NULL,%s)',('adverts',str(aid+10),json.dumps(dict(advertId=aid+10,info=dict(settings=dict(payment_type='cpm' if aid==501 else 'cpc'))))))
        with patch('stometric.exclusions.excluded',return_value={99}):
            r=entry.view(self.c,7,mode='days')['ads']['2']
        self.assertEqual(r['total']['clicks'],20040)
        self.assertEqual(r['search']['clicks'],36)
        self.assertEqual(r['search_cpc']['clicks'],18)
        self.assertEqual(r['search_cpm']['views'],240)
        self.assertEqual(r['rest_cpc']['clicks'],8)
        self.assertIn('clicks',r['total']['partial']);self.assertIn('clicks',r['rest_cpc']['partial'])
        d=self.result();search=next(x for x in d['sources'] if x['section']=='Поиск')
        self.assertEqual(search['payment']['cpc']['clicks'],30)
        self.assertIn('clicks',search['payment']['cpc']['partial'])
        self.assertEqual(d['sources_total']['ad_clicks'],40080)
        self.assertIn('clicks',d['sources_total']['ad_partial'])
    def test_optional_missing_app_metric_keeps_available_values(self):
        self.c.raw("UPDATE raw_rows SET data=data#-'{apps,0,nms,0,clicks}' WHERE source='ad_stats' AND account_id=7 AND row_key='501-2026-11-12';")
        r=self.detail(mode='days')['ads']['2']
        self.assertEqual(r['total']['clicks'],30);self.assertIn('clicks',r['total']['partial'])
        self.assertEqual(r['search_cpm']['clicks'],12)
        self.assertIsNone(r['rest_cpm']['clicks'],'do not subtract search from incomplete fullstats')
    def test_news_idempotent(self):
        self.c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
        for name in ('146_entry_ads_payment_news.sql','147_entry_ads_availability_news.sql'):
            sql=Path('stometric/migrations',name).read_text()
            self.c.raw(sql);self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)

if __name__=='__main__': unittest.main()

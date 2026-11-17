"""Budget scope, missing data, daily capture, SQL isolation and action timestamps."""
import stometric.web
import copy
import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock
from fastapi import HTTPException
from stometric import action_ads as aa, ad_history as ah, manager, manager_oz, api_manager, wb_demand
from tools.test_ad_history import campaign, Memory
from tools.test_calendar import Cursor, Standalone

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026,11,16)
NOW = datetime(2026,11,16,12,tzinfo=timezone.utc)


def states(aid=42, model='cpm', search=True, rec=False, budget=900, limit=1000, nms=(100,101), day=DAY):
    a = campaign(aid, nms)
    a['info']['settings'].update(payment_type=model,placements={'search':search,'recommendations':rec})
    f, ns = ah.campaign_fields(a)
    return [{'advert_id':aid,'source':s,'day':day,'data':aa.compact(s,fields,ns),'observed_at':NOW}
            for s,fields in [('campaign',f),('budget',{'total':budget,'currency':'RUB'}),
                              ('limits',{'dailyLimit':limit,'enabled':True,'carryOverEnabled':False,'currency':'RUB'})]]


def spent(aid=42, nm=100, spend=20, total=100, day=DAY):
    return {'id':aid,'nm':nm,'d':day,'spend':spend,'campaign_spent':total}


class Metrics(unittest.TestCase):
    def test_historical_payment_classification_keeps_spend_and_no_backdated_money(self):
                                                                              
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':1143}]
        current={42:{'payment':'cpc','bid_type':'manual'}}
        r=aa.calculate([spent(spend=1298.1,total=2000)],[],kw,[100],current)[100][str(DAY)]
        self.assertEqual(r['all']['spent'],1298.1)
        self.assertEqual(r['cpc']['spent'],1298.1)
        self.assertEqual(r['prk']['spent'],1298.1)
        self.assertEqual(r['search']['spent'],1143)
        self.assertEqual(r['rest']['spent'],155.1)
        self.assertEqual(r['search']['payment_spend']['cpc']['spent'],1143)
        self.assertEqual(r['rest']['payment_spend']['cpc']['spent'],155.1)
        self.assertTrue(r['cpc']['classification_estimated'])
        self.assertTrue(r['rest']['classification_estimated'])
        self.assertIn('spent',r['rest']['partial'])
        for group in r.values():
            for key in ('budget','daily_limit','usage_limit','usage_balance'):
                self.assertIsNone(group[key])
            self.assertEqual(group['bids'],{'cpm':None,'cpc':None})

    def test_daily_classification_precedes_latest_and_unknown_spend_is_visible(self):
        current={42:{'payment':'cpc','bid_type':'unified'}}
        r=aa.calculate([spent(),spent(aid=43,spend=30)],states(),[],[100],current)[100][str(DAY)]
        self.assertEqual(r['cpm']['spent'],20)
        self.assertIsNone(r['cpc']['spent'])
        self.assertEqual(r['prk']['spent'],20)
        self.assertFalse(r['cpm']['classification_estimated'])
        self.assertEqual(r['unknown']['spent'],30)
        self.assertEqual(r['unknown']['campaigns'],1)
        self.assertEqual(r['all']['spent'],50)
        self.assertIn('spent',r['cpm']['partial'])
        s=states(); s[0]['data']['fields']['settings.payment_type']=None
        r=aa.calculate([spent()],s,[],[100],current)[100][str(DAY)]
        self.assertEqual(r['unknown']['spent'],20,'explicit unknown day is not overwritten by current type')

    def test_remainder_matches_campaign_sku_day_and_missing_is_not_zero(self):
        current={42:{'payment':'cpc'},43:{'payment':'cpm'}}
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':7},
            {'advert_id':43,'nm_id':100,'day':DAY,'spend':90}]
        r=aa.calculate([spent(),spent(aid=43,spend=10)],[],kw,[100],current)[100][str(DAY)]
        self.assertEqual(r['rest']['spent'],13,'negative other-campaign residue cannot cancel valid expense')
        self.assertIn('spent',r['rest']['partial'])
        self.assertEqual(r['rest']['payment_spend']['cpc']['spent'],13)
        self.assertIsNone(r['rest']['payment_spend']['cpm']['spent'])
        for search in ([],[{'advert_id':42,'nm_id':101,'day':DAY,'spend':7}],
                       [{'advert_id':42,'nm_id':100,'day':DAY-timedelta(days=1),'spend':7}]):
            r=aa.calculate([spent()],[],search,[100],current)[100][str(DAY)]
            self.assertIsNone(r['rest']['spent'])
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':20}]
        r=aa.calculate([spent()],[],kw,[100],current)[100][str(DAY)]
        self.assertEqual(r['rest']['spent'],0)

    def test_non_search_only_daily_state_has_full_expense_without_allocation(self):
        r=aa.calculate([spent()],states(model='cpc',search=False,rec=True),[],[100])[100][str(DAY)]
        self.assertEqual(r['rest']['spent'],20)
        self.assertEqual(r['rest']['payment_spend']['cpc']['spent'],20)
        self.assertEqual(r['rest']['budget'],900)
        self.assertEqual(r['rest']['usage_limit'],.1)
        self.assertNotIn('spent',r['rest']['partial'])
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':7}]
        r=aa.calculate([spent()],states(model='cpc',search=False,rec=True),kw,[100])[100][str(DAY)]
        self.assertEqual(r['rest']['spent'],13)
        self.assertIsNone(r['rest']['budget'],'contradicting search observation cannot inherit the entire wallet')
        self.assertIsNone(r['rest']['usage_limit'])


    def test_shared_budget_not_allocated_and_usage_uses_campaign_not_sku(self):
        result=aa.calculate([spent(),spent(nm=101,spend=80)],states(),[],[100,101])
        a,b=(result[n][str(DAY)]['all'] for n in (100,101))
        self.assertEqual((a['spent'],b['spent']),(20,80))
        self.assertEqual((a['budget'],b['budget']),(900,900))
        self.assertEqual(a['usage_limit'],.1); self.assertEqual(a['usage_balance'],.1)
        self.assertEqual(a['bids'],{'cpm':100,'cpc':None})
        self.assertEqual(a['campaigns'],1)

    def test_currency_units_bids_and_overlapping_groups(self):
        s=states()+states(43,'cpc',search=False,rec=True)
        s[3]['data']['fields']['nm.100.bids.recommendations']=5
        r=aa.calculate([spent(),spent(43,spend=30,total=200)],s,[],[100])[100][str(DAY)]
        self.assertEqual(r['all']['bids'],{'cpm':100,'cpc':5})
        self.assertEqual(r['all']['spent'],50); self.assertEqual(r['prk']['spent'],50)
        self.assertEqual(r['search']['spent'],20)
        self.assertEqual(r['cpc']['spent'],30)
        s[3]['data']['fields']['currency']='USD'; s[4]['data']['fields']['currency']='USD'
        r=aa.calculate([spent(),spent(43)],s,[],[100])[100][str(DAY)]
        self.assertIsNone(r['cpc']['bids']['cpc']); self.assertIsNone(r['cpc']['budget'])
        self.assertIn('budget',r['all']['partial']); self.assertIsNone(r['all']['usage_balance'])

    def test_mixed_placement_search_has_no_fabricated_wallet_or_usage(self):
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':7}]
        r=aa.calculate([spent()],states(rec=True),kw,[100])[100][str(DAY)]['search']
        self.assertEqual(r['spent'],7); self.assertEqual(r['bids']['cpm'],100)
        self.assertIn('spent',r['partial'],'mixed placement search only covers saved clusters')
        for key in ('budget','daily_limit','usage_limit','usage_balance'): self.assertIsNone(r[key])
        r=aa.calculate([spent()],states(rec=True),[],[100])[100][str(DAY)]['search']
        self.assertIsNone(r['spent'],'missing clusters are not zero')

    def test_no_future_snapshot_for_historical_days_and_no_missing_to_zero(self):
        r=aa.calculate([spent(day=DAY-timedelta(days=1))],states(),[],[100])[100]
        old=r[str(DAY-timedelta(days=1))]
        self.assertEqual(old['all']['spent'],20)
        self.assertIsNone(old['all']['budget']); self.assertIsNone(old['cpm']['spent'])
        self.assertIsNone(r[str(DAY)]['all']['spent'])
        self.assertIsNone(r[str(DAY)]['all']['usage_limit'])

    def test_partial_data_keep_known_subtotal_but_no_ratio(self):
        r=aa.calculate([spent(),spent(43,spend=None)],states()+states(43),[],[100])[100][str(DAY)]['all']
        self.assertEqual(r['spent'],20); self.assertIn('spent',r['partial'])
        r=aa.calculate([spent(),spent(43,total=None)],states()+states(43),[],[100])[100][str(DAY)]['all']
        self.assertEqual(r['campaign_spent'],100); self.assertIsNone(r['usage_limit'])

    def test_search_survives_missing_fullstats_without_guessing_model(self):
        kw=[{'advert_id':42,'nm_id':100,'day':DAY,'spend':7}]
        result=aa.calculate([],[],kw,[100])[100][str(DAY)]
        self.assertEqual(result['search']['spent'],7)
        self.assertIsNone(result['all']['spent']);self.assertIsNone(result['cpm']['spent'])
        self.assertIsNone(result['search']['usage_balance'])

    def test_zero_disabled_limits_missing_groups_and_catalog_filter(self):
        s=states(budget=0,limit=0)
        r=aa.calculate([spent(spend=0,total=0),spent(nm=999)],s,[],[100])
        self.assertEqual(set(r),{100}); a=r[100][str(DAY)]['all']
        self.assertEqual(a['spent'],0); self.assertEqual(a['budget'],0)
        self.assertIsNone(a['usage_limit']); self.assertIsNone(a['usage_balance'])
        s[2]['data']['fields']['enabled']=False
        a=aa.calculate([spent()],s,[],[100])[100][str(DAY)]['all']
        self.assertIsNone(a['daily_limit']); self.assertIsNone(a['usage_limit'])

    def test_daily_capture_complete_response_only_stale_and_midnight(self):
        c=Memory(); ah.observe_campaign(c,1,campaign(),NOW)
        self.assertEqual(len(c.daily),1)
        a=campaign(); del a['info']['nm_settings']
        ah.observe_campaign(c,1,a,NOW+timedelta(hours=1))
        self.assertEqual(next(iter(c.daily.values()))['observed_at'],NOW)
        ah.observe_campaign(c,1,campaign(),NOW-timedelta(hours=1))
        self.assertEqual(len(c.daily),1)
        ah.observe_campaign(c,1,campaign(),NOW.replace(hour=21))
        self.assertEqual({k[3] for k in c.daily},{DAY,DAY+timedelta(days=1)})
        self.assertNotIn('settings.name',next(iter(c.daily.values()))['data']['fields'])

    def test_opt_in_and_auth_before_any_reads(self):
        with patch.object(api_manager.auth,'shop_role',return_value=None), patch.object(manager,'board') as get:
            with self.assertRaises(HTTPException): api_manager.board(7,ad_metrics=True,u={'id':99},c=Mock())
            get.assert_not_called()
        with patch.object(api_manager,'_role'), patch.object(api_manager.auth,'shop_role',return_value='viewer'), \
             patch.object(manager,'board',return_value={'rows':[]}) as get:
            api_manager.board(7,ad_metrics=True,u={'id':99},c=Mock())
            self.assertTrue(get.call_args.kwargs['ad_metrics'])

    def test_board_times_and_stats_optional_wb_and_ozon(self):
        class Db:
            def execute(self,q,p=()):
                if 'FROM nm_actions' in q:
                    assert 'a.created_at' in q
                    return Cursor([dict(id=1,nm_id=100,day=DAY,kind='other',value='test',note=None,user_id=99,who='Test',created_at=NOW)])
                if 'FROM card_changes' in q:
                    assert 'detected_at, wb_updated_at' in q
                    return Cursor([dict(id=2,nm_id=100,d=DAY,kind='photo',field='photo',old_value=None,new_value=None,detected_at=NOW,wb_updated_at=NOW-timedelta(hours=1))])
                return Cursor([])
        u={'vendor_code':'Test','title':'Test','subject':'Test','photo':None,'stock':1,'marketing_price':None}
        for mod in (manager,manager_oz):
            with patch.object(manager,'_ozon',return_value=mod is manager_oz), \
                 patch.object(mod,'other_pct',return_value=0), patch.object(mod,'_unit_inputs',return_value={100:u}), \
                 patch.object(mod,'unit_calc',return_value={'online':100,'margin_online_pct':.2}), \
                 patch.object(manager,'showcase',return_value={}), patch.object(manager,'stocks',return_value={}), \
                 patch.object(wb_demand,'daily',return_value={}), patch.object(wb_demand,'summary',return_value={}), \
                 patch.object(aa,'read',return_value={100:{str(DAY):{'all':{'spent':7}}}}) as read:
                base=manager.board(Db(),7,7,DAY)
                read.assert_not_called(); self.assertNotIn('ad_metrics',base['rows'][0])
                acts=base['rows'][0]['actions'][str(DAY)]
                self.assertEqual(acts[0]['created_at'],NOW); self.assertEqual(acts[1]['detected_at'],NOW)
                self.assertEqual(acts[1]['wb_updated_at'],NOW-timedelta(hours=1))
                base=manager.board(Db(),7,7,DAY,ad_metrics=True)
                if mod is manager:
                    read.assert_called_once(); self.assertEqual(base['rows'][0]['ad_metrics'][str(DAY)]['all']['spent'],7)
                else: read.assert_not_called()


class Sql(unittest.TestCase):
    def test_real_sql_scope_dedup_capture_and_missing_sum(self):
        with tempfile.TemporaryDirectory(prefix='action-ad-metrics-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True)
            c=Standalone(cluster,'test_ads')
            c.raw('CREATE SCHEMA test_ads; SET search_path=test_ads; CREATE TABLE accounts(id int PRIMARY KEY); INSERT INTO accounts VALUES(1),(2); '
                  'CREATE TABLE service_news(title text,body text,tabs text[]); '
                  'CREATE TABLE raw_rows(account_id int,source text,row_date date,data jsonb); '
                  'CREATE TABLE wb_ad_kw_daily(account_id int,advert_id bigint,nm_id bigint,day date,spend numeric);')
            sql=(ROOT/'stometric/migrations/148_actions_ad_metrics.sql').read_text()
            c.raw(sql);c.raw(sql)
            self.assertEqual(c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
            for row in states():
                for shop in (1,2): aa.capture(c,shop,42,row['source'],row['data']['fields'],[100,101],NOW)
            aa.capture(c,1,42,'budget',{'total':99999,'currency':'RUB'},[100],NOW-timedelta(hours=1))
            raw={'advertId':42,'sum':100,'apps':[{'nms':[{'nmId':100,'sum':5},{'nmId':101,'sum':80}]},
                                                {'nms':[{'nmId':100,'sum':15}]}]}
            for shop in (1,2): c.execute('INSERT INTO raw_rows VALUES(%s,%s,%s,%s::jsonb)',(shop,'ad_stats',DAY,json.dumps(raw)))
            got=aa.read(c,1,DAY,DAY,[100])[100][str(DAY)]['all']
            self.assertEqual(got['spent'],20);self.assertEqual(got['campaign_spent'],100)
            self.assertEqual(got['budget'],900);self.assertEqual(got['usage_limit'],.1)
            self.assertEqual(aa.read(c,1,DAY-timedelta(days=1),DAY-timedelta(days=1),[100]),{})
            self.assertEqual(aa.read(c,3,DAY,DAY,[100]),{})
            self.assertEqual(aa.read(c,1,DAY,DAY,[]),{})
            raw['apps'][1]['nms'][0].pop('sum')
            c.execute('UPDATE raw_rows SET data=%s::jsonb WHERE account_id=%s',(json.dumps(raw),1))
            got=aa.read(c,1,DAY,DAY,[100])[100][str(DAY)]['all']
            self.assertIsNone(got['spent'])

    def test_real_legacy_types_match_entry_and_conflicts_remain_unknown(self):
        from stometric.entry_ads import MODELS_SQL
        with tempfile.TemporaryDirectory(prefix='legacy-ad-types-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True)
            c=Standalone(cluster,'legacy_types')
            c.raw('CREATE SCHEMA legacy_types; SET search_path=legacy_types; '
                  'CREATE TABLE raw_rows(account_id int,source text,row_date date,data jsonb); '
                  'CREATE TABLE wb_ad_kw_daily(account_id int,advert_id bigint,nm_id bigint,day date,spend numeric);')
            meta={'advertId':42,'info':{'bid_type':'manual','settings':{'payment_type':'CPC','placements':{'search':True,'recommendations':False}},
                                      'nm_settings':[{'nm_id':100,'bids':{'search':999999}}]},'budget':999999}
            raw={'advertId':42,'sum':2000,'apps':[{'nms':[{'nmId':100,'sum':1298.1}]}]}
            c.execute('INSERT INTO raw_rows VALUES(1,\'adverts\',%s,%s::jsonb)',(DAY+timedelta(days=1),json.dumps(meta)))
            c.execute('INSERT INTO raw_rows VALUES(1,\'ad_stats\',%s,%s::jsonb)',(DAY,json.dumps(raw)))
            c.execute('INSERT INTO wb_ad_kw_daily VALUES(1,42,100,%s,1143)',(DAY,))
                                                                                 
            r=aa.read(c,1,DAY,DAY,[100],snapshot_history=False)[100][str(DAY)]
            self.assertEqual(r['cpc']['spent'],1298.1);self.assertEqual(r['rest']['spent'],155.1)
            self.assertTrue(r['cpc']['classification_estimated'])
            self.assertIsNone(r['cpc']['budget']);self.assertIsNone(r['cpc']['bids']['cpc'])
            self.assertEqual(c.execute(MODELS_SQL,{'a':1}).fetchone()['payment'],'cpc')
            meta['info']['settings']['payment_type']='cpm'
            c.execute('INSERT INTO raw_rows VALUES(2,\'adverts\',%s,%s::jsonb)',(DAY,json.dumps(meta)))
            self.assertEqual(aa.read(c,1,DAY,DAY,[100],snapshot_history=False)[100][str(DAY)]['cpc']['spent'],1298.1)
            c.execute('INSERT INTO raw_rows VALUES(1,\'adverts\',%s,%s::jsonb)',(DAY,json.dumps(meta)))
            r=aa.read(c,1,DAY,DAY,[100],snapshot_history=False)[100][str(DAY)]
            self.assertIsNone(r['cpc']['spent']);self.assertIsNone(r['cpm']['spent'])
            self.assertEqual(r['unknown']['spent'],1298.1)
            self.assertEqual(r['rest']['payment_spend']['unknown']['spent'],155.1)
            c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
            sql=(ROOT/'stometric/migrations/150_action_ad_split_news.sql').read_text()
            c.raw(sql);c.raw(sql)
            self.assertEqual(c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)


if __name__=='__main__': unittest.main()

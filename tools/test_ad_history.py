"""Advertising history: synthetic API, isolated PostgreSQL, no live secrets/actions."""
import copy
import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import httpx

import stometric.web
from stometric import ad_history as ah, actions, ads_ai, history, tabcache, wb, schedule
from stometric.collectors import advert, registry
from stometric.tabs import manage
from tools.test_calendar import Cursor, Standalone

NOW = datetime(2026,11,15,12,tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def campaign(aid=42, nms=(100,101), status=9, name='Тестовая кампания'):
    return {'advertId':aid,'status':status,'type':9,'changeTime':'2026-11-15',
            'info':{'id':aid,'status':status,'bid_type':'manual','currency':'RUB',
                    'settings':{'name':name,'payment_type':'cpm','placements':{'search':True,'recommendations':False}},
                    'nm_settings':[{'nm_id':n,'bids_kopecks':{'search':10000,'recommendations':10000}} for n in nms],
                    'timestamps':{'updated':'now'}}}


class Memory:
    def __init__(self):
        self.snaps, self.raw, self.events, self.logs, self.commits, self.calls = {}, {}, [], [], 0, []
        self.fail = False
        self.daily = {}

    def execute(self, sql, p=()):
        self.calls.append((sql,p))
        if sql.startswith('INSERT INTO wb_ad_observations'):
            self.snaps.setdefault(p, {'data':{},'observed_at':None})
        elif sql.startswith('SELECT data,observed_at FROM wb_ad_observations'):
            return Cursor([copy.deepcopy(self.snaps[p])])
        elif sql.startswith('UPDATE wb_ad_observations'):
            if self.fail: raise RuntimeError('synthetic save failure')
            self.snaps[p[2:]]={'data':json.loads(p[0]),'observed_at':p[1]}
        elif sql.startswith('INSERT INTO wb_ad_daily_state'):
            old = self.daily.get(p[:4])
            if old is None or old['observed_at'] < p[5]:
                self.daily[p[:4]] = {'data':json.loads(p[4]),'observed_at':p[5]}
        elif sql.startswith('INSERT INTO card_changes'):
            self.events.append({'account_id':p[0],'nm_id':p[1],'kind':p[2],'field':p[3],
                                'old_value':json.loads(p[4]),'new_value':json.loads(p[5]),'detected_at':p[7] if len(p)>7 else NOW})
        elif sql.startswith('SELECT data FROM raw_rows'):
            v=self.raw.get((p[0],int(p[1]))); return Cursor([{'data':copy.deepcopy(v)}] if v else [])
        elif sql.startswith('SELECT row_key,data FROM raw_rows'):
            return Cursor([{'row_key':str(a),'data':copy.deepcopy(v)} for (shop,a),v in self.raw.items() if shop==p[0]])
        elif sql.startswith('SELECT 1 FROM raw_rows'):
            return Cursor([{'one':1}] if any(shop==p[0] for shop,a in self.raw) else [])
        elif sql.startswith('INSERT INTO raw_rows'):
            self.raw[p[0],int(p[2] if len(p)==5 else p[1])]=json.loads(p[4] if len(p)==5 else p[2])
        elif sql.startswith('SELECT * FROM accounts'):
            return Cursor([{'id':p[0]}])
        elif sql.startswith('INSERT INTO action_log'):
            self.logs.append(p); return Cursor([{'id':len(self.logs)}])
        elif sql.startswith('INSERT INTO api_log'):
            pass
        else:
            raise AssertionError(sql)
        return Cursor([])

    @contextmanager
    def transaction(self):
        old=copy.deepcopy((self.snaps,self.raw,self.events,self.logs,self.daily))
        try: yield
        except BaseException:
            self.snaps,self.raw,self.events,self.logs,self.daily=old
            raise
    def commit(self): self.commits+=1
    def rollback(self): pass


class CampaignTests(unittest.TestCase):
    def test_all_settings_products_bids_status_and_unchanged(self):
        c=Memory(); a=campaign()
        self.assertEqual(ah.observe_campaign(c,1,a,NOW),(True,0))
        b=campaign(nms=(101,102),status=11,name='Новое имя')
        b['info']['bid_type']='unified'
        b['info']['settings']['payment_type']='cpc'
        b['info']['settings']['placements']={'search':False,'recommendations':True}
        b['info']['nm_settings'][0]['bids_kopecks']['search']=25050
        _,count=ah.observe_campaign(c,1,b,NOW+timedelta(hours=1))
        self.assertEqual(count,len(c.events))
        self.assertEqual({e['kind'] for e in c.events},{'ad_setting','ad_product','ad_bid','ad_status'})
        self.assertEqual({e['nm_id'] for e in c.events if e['kind']=='ad_product'},{100,102})
        bid=next(e for e in c.events if e['kind']=='ad_bid')
        self.assertEqual(bid['new_value']['search'],250.5)
        self.assertEqual(ah.observe_campaign(c,1,b,NOW+timedelta(hours=2)),(True,0))

    def test_migrate_from_known_raw_and_do_not_lose_on_fresh_refresh(self):
        c=Memory(); a=campaign(); b=campaign(status=11)
        self.assertEqual(ah.observe_campaign(c,1,b,NOW,a)[1],2)
                                                                                          
        self.assertEqual(ah.observe_campaign(c,1,a,NOW+timedelta(minutes=1),a)[1],2)

    def test_missing_fields_not_removals_and_stale_response_ignored(self):
        c=Memory(); a=campaign(); ah.observe_campaign(c,1,a,NOW)
        b=campaign(); del b['info']['nm_settings']; b['info']['settings']={}
        self.assertEqual(ah.observe_campaign(c,1,b,NOW+timedelta(minutes=1))[1],0)
        b=campaign(nms=()); self.assertEqual(ah.observe_campaign(c,1,b,NOW+timedelta(minutes=2))[1],2)
        self.assertEqual(ah.observe_campaign(c,1,a,NOW+timedelta(minutes=1)),(False,0))
        self.assertEqual(ah.observe_campaign(c,1,a,NOW+timedelta(minutes=3))[1],2,'re-add does not invent bid changes')

    def test_bad_identity_duplicates_partial_lists_rejected(self):
        for mutate in (lambda a:a['info'].update(id=43),lambda a:a['info'].update(nm_settings=None),
                       lambda a:a['info']['nm_settings'].append(a['info']['nm_settings'][0]),
                       lambda a:a['info']['nm_settings'][0].update(bids_kopecks=None)):
            a=campaign(); mutate(a)
            with self.assertRaises(ValueError): ah.campaign_fields(a)
        with self.assertRaises(ValueError): ah.require_complete_detail({'id':42})
        c=Memory(); a=campaign(nms=()); ah.observe_campaign(c,1,a,NOW)
        self.assertEqual(ah.observe_campaign(c,1,campaign(nms=(),name='Без товаров'),NOW+timedelta(seconds=1))[1],1)
        self.assertEqual(c.events[0]['nm_id'],0)

    def test_volatile_metadata_and_unknown_fields_do_not_fabricate_actions(self):
        c=Memory(); a=campaign(); ah.observe_campaign(c,1,a,NOW)
        b=copy.deepcopy(a); b['changeTime']='later'; b['info']['timestamps']['updated']='later'
        b['info']['settings']['new_flag']=True
        self.assertEqual(ah.observe_campaign(c,1,b,NOW+timedelta(seconds=1))[1],0)
        b['info']['settings']['new_flag']=False
        self.assertEqual(ah.observe_campaign(c,1,b,NOW+timedelta(seconds=2))[1],2)

    def test_shop_and_campaign_isolation_and_atomicity(self):
        c=Memory()
        for shop,aid in ((1,42),(2,42),(1,43)): ah.observe_campaign(c,shop,campaign(aid),NOW)
        c.fail=True
        with self.assertRaises(RuntimeError),c.transaction(): ah.observe_campaign(c,1,campaign(status=11),NOW+timedelta(seconds=1))
        self.assertEqual(c.events,[])
        self.assertTrue(all(s['observed_at']==NOW for s in c.snaps.values()))

    def test_fresh_records_before_overwriting_and_does_not_write_marketplace(self):
        c=Memory(); c.raw[1,42]=campaign(); api=Mock()
        api.call.return_value={'adverts':[campaign(status=11)['info']]}
        with patch.object(ads_ai,'_wb',return_value=api): ads_ai._fresh(c,1,42)
        self.assertEqual(len(c.events),2)
        self.assertEqual(c.raw[1,42]['status'],11)
        self.assertEqual(api.call.call_args.args,('advert','/api/advert/v2/adverts'))
        api.call.return_value={'adverts':[campaign(43)['info']]}
        with patch.object(ads_ai,'_wb',return_value=api),self.assertRaises(ads_ai.Stale): ads_ai._fresh(c,1,42)

    def test_collector_omission_preserves_last_complete_campaign(self):
        c=Memory(); a=campaign(); c.raw[1,42]=a; api=Mock()
        api.call.side_effect=[{'adverts':[{'type':9,'status':9,'advert_list':[{'advertId':42,'changeTime':'new'}]}]}, {'adverts':[]}]
        ctx=SimpleNamespace(c=c,acc={'id':1},wb=api,state=lambda _: {})
        with self.assertRaises(ValueError): advert.run_adverts(ctx)
        self.assertEqual(c.raw[1,42],a); self.assertFalse(c.events)
        api.call.side_effect=[{'adverts':[{'type':9,'status':9,'advert_list':[{'advertId':42,'changeTime':'new'}]}]}, {'adverts':[{'id':42}]}]
        with self.assertRaises(ValueError): advert.run_adverts(ctx)
        self.assertEqual(c.raw[1,42],a); self.assertFalse(c.events)

    def test_collector_full_and_terminal_status_with_missing_details(self):
        c=Memory(); c.raw[1,42]=campaign(); api=Mock()
        ctx=SimpleNamespace(c=c,acc={'id':1},wb=api,state=lambda _: {})
        api.call.side_effect=[{'adverts':[{'type':9,'status':11,'advert_list':[{'advertId':42,'changeTime':'new'}]}]},
                              {'adverts':[campaign(status=11,name='Новое имя')['info']]}]
        advert.run_adverts(ctx)
        self.assertEqual(len(c.events),4)
        self.assertEqual(c.raw[1,42]['status'],11)
        api.call.side_effect=[{'adverts':[{'type':9,'status':-1,'advert_list':[{'advertId':42,'changeTime':'deleted'}]}]}, {'adverts':[]}]
        advert.run_adverts(ctx)
        self.assertEqual(c.raw[1,42]['status'],-1)
        self.assertTrue(c.raw[1,42]['details_missing'])
        self.assertEqual(c.events[-1]['new_value']['status'],'удалена')

    def test_ready_campaign_keys_and_more_info_settings(self):
        c=Mock(); c.execute.return_value=Cursor([{'data':campaign(status=4)}])
        self.assertEqual(len(advert._kw_pairs(SimpleNamespace(c=c,acc={'id':1}))),2)
        c=Memory(); a=campaign(); a['info']['restrictions']={'canChangeNms':True}
        ah.observe_campaign(c,1,a,NOW)
        a['info']['restrictions']['canChangeNms']=False
        self.assertEqual(ah.observe_campaign(c,1,a,NOW+timedelta(seconds=1))[1],2)


class FinanceTests(unittest.TestCase):
    def test_daily_limits_read_path_cannot_be_used_for_write(self):
        client=wb.WB.__new__(wb.WB); client._wait_slot=Mock(side_effect=RuntimeError('read reached limiter'))
        for method in ('PUT','PATCH','DELETE','POST'):
            with self.assertRaises(wb.WBError): client.call('advert','/api/advert/v0/daily-limits',method)
        client._wait_slot.assert_not_called()
        with self.assertRaisesRegex(RuntimeError,'read reached limiter'):
            client.call('advert','/api/advert/v0/daily-limits',params={'advertIds':'42'})

    def test_valid_budget_limits_and_incomplete_never_zero(self):
        b={'adverts':[{'advertId':42,'total':1234.5,'currency':'RUB'}]}
        self.assertEqual(ah.parse_finance(b,[42],'budget')[42]['total'],1234.5)
        for bad in ({},{'adverts':[]},{'adverts':[{'advertId':42,'total':None,'currency':'RUB'}]},
                    {'adverts':b['adverts']*2},{**b,'next':'more'}):
            with self.assertRaises(ValueError): ah.parse_finance(bad,[42],'budget')
        lim={'adverts':[{'advertId':42,'enabled':True,'dailyLimit':1000,'carryOverEnabled':False,'currency':'RUB','spentToday':500}]}
        self.assertNotIn('spentToday',ah.parse_finance(lim,[42],'limits')[42])

    def test_budget_not_claimed_deposit_and_limits_bool_changes(self):
        c=Memory()
        for source,old,new in [('budget',{'total':5000,'currency':'RUB'},{'total':4000,'currency':'RUB'}),
                              ('limits',{'enabled':False,'dailyLimit':1000,'carryOverEnabled':False,'currency':'RUB'},
                               {'enabled':True,'dailyLimit':2000,'carryOverEnabled':True,'currency':'RUB'})]:
            ah.observe(c,1,42,source,old,[100],NOW)
            ah.observe(c,1,42,source,new,[100],NOW+timedelta(hours=1))
        self.assertEqual(len(c.events),4)
        self.assertIn('не доказательство пополнения',ah.label(c.events[0]))
        self.assertIn('5 000 ₽ → 4 000 ₽',ah.label(c.events[0]))

    def test_settings_collector_cpc_only_limits_and_error_no_fake_snapshot(self):
        c=Memory(); c.raw[1,42]=campaign(); c.raw[1,43]=campaign(43)
        c.raw[1,43]['info']['settings']['payment_type']='cpc'
        api=Mock(); api.call.side_effect=[{'adverts':[{'advertId':a,'total':1000,'currency':'RUB'} for a in (42,43)]},
                                        {'adverts':[{'advertId':43,'enabled':False,'dailyLimit':1000,'carryOverEnabled':False,'currency':'RUB'}]}]
        save=Mock(); ctx=SimpleNamespace(c=c,acc={'id':1},wb=api,state=lambda _: {},save_state=save)
        self.assertEqual(advert.run_settings(ctx)['requests'],2)
        self.assertEqual(api.call.call_args.kwargs,{'params':{'advertIds':'43'}})
        self.assertEqual(len(c.snaps),3)
        old=copy.deepcopy(c.snaps)
        api.call.side_effect=[{'adverts':[{'advertId':a,'total':0,'currency':'RUB'} for a in (42,43)]},RuntimeError('synthetic')]
        with self.assertRaises(RuntimeError): advert.run_settings(ctx)
        self.assertEqual(c.snaps,old); self.assertFalse(c.events)
        self.assertIs(registry()['ad_settings'],advert.run_settings)
        self.assertEqual(schedule.EVERY_MIN['ad_settings'],360)

    def test_bounded_collector_cursor_is_stable_and_read_only(self):
        c=Memory()
        for aid in range(1,502): c.raw[1,aid]=campaign(aid,nms=())
        api=Mock(); api.call.side_effect=lambda host,path,method,body:{'adverts':[{'advertId':a,'total':0,'currency':'RUB'} for a in body['advertIds']]}
        saved=[]; ctx=SimpleNamespace(c=c,acc={'id':1},wb=api,state=lambda _: {},save_state=lambda *a,**k:saved.append(a))
        res=advert.run_settings(ctx)
        self.assertEqual((res['requests'],res['remaining']),(9,51))
        self.assertEqual(res['cursor']['pending'],list(range(451,502)))
        self.assertTrue(all(x.args[1]=='/api/advert/v2/budget' for x in api.call.call_args_list))
        self.assertEqual(saved[-1][1],res['cursor'])


class CommandTests(unittest.TestCase):
    def test_all_allowed_ads_writes_have_receipt_projection(self):
        self.assertEqual(set(ah.COMMANDS),{path for _,_,path in actions.BLOCKS['ads']['writes']})
        cases=[('/adv/v0/start',None,{'id':42},None),('/adv/v0/pause',None,{'id':42},None),
               ('/adv/v1/budget/deposit',{'sum':1000,'type':1},{'id':42},{'budget':0}),
               ('/adv/v2/seacat/save-ad',{'name':'Создана','nms':[100],'bid_type':'manual','payment_type':'cpm'},None,None),
               ('/adv/v0/auction/nms',{'nms':[{'advert_id':42,'nms':{'delete':[100]}}]},None,{'nms':[100,101]}),
               ('/adv/v0/auction/placements',{'placements':[{'advert_id':42,'placements':{'search':False,'recommendations':True}}]},None,None),
               ('/api/advert/v1/bids',{'bids':[{'advert_id':42,'nm_bids':[{'nm_id':100,'bid_kopecks':25050,'placement':'search'}]}]},None,{'search':10000}),
               ('/adv/v0/normquery/bids',{'bids':[{'advert_id':42,'nm_id':100,'norm_query':'свеча','bid':250}]},None,{'bid':200}),
               ('/adv/v0/normquery/set-minus',{'advert_id':42,'nm_id':100,'norm_queries':['свеча']},None,{'norm_queries':['сироп']})]
        for path,body,params,before in cases:
            c=Memory(); c.raw[1,42]=campaign()
            ah.command(c,1,path,body,params,before,42,7,NOW,99)
            self.assertTrue(c.events,path)
            for row in c.events:
                self.assertEqual(row['new_value']['actor_id'],7)
                self.assertEqual(row['new_value']['action_id'],99)
                self.assertEqual(row['new_value']['evidence'],'accepted_command')
                self.assertIn('WB принял команду',ah.label(row))
            if path=='/api/advert/v1/bids': self.assertIn('250,5 ₽',ah.label(c.events[0]))
            if path.endswith('/set-minus'):
                self.assertIn('исключить: свеча; снять исключение: сироп',ah.label(c.events[0]))

    def call_write(self,c,response):
        with patch.object(actions,'can_write',return_value=None),patch.object(actions,'_write_token',return_value='synthetic'), \
             patch.object(actions,'write_info',return_value={'scopes':['Продвижение']}),patch.object(wb.WB,'_wait_slot'), \
             patch.object(actions.httpx,'request',side_effect=response if isinstance(response,Exception) else None,return_value=response):
            return actions.wb_write(c,1,'ads','GET','advert','/adv/v0/pause',None,params={'id':42},uid=7,before={'status':9})

    def test_real_gateway_receipt_same_commit_and_no_failed_or_uncertain_success(self):
        c=Memory();c.raw[1,42]=campaign()
        self.call_write(c,httpx.Response(200))
        self.assertEqual(len(c.events),2);self.assertEqual(c.commits,1)
        for response in (httpx.Response(403,text='synthetic'),httpx.Response(429),
                         httpx.Response(200,json={'error':True}),httpx.Response(200,json={'errors':['synthetic']}),
                         httpx.Response(200,text='invalid json'),httpx.ReadTimeout('synthetic')):
            c=Memory()
            with self.assertRaises(actions.ActionDenied):self.call_write(c,response)
            self.assertFalse(c.events);self.assertFalse(c.logs[-1][-2])

    def test_journal_source_actor_units_and_immediate_cache(self):
        c=Memory();c.raw[1,42]=campaign()
        ah.command(c,1,'/adv/v1/budget/deposit',{'sum':1000,'type':1},{'id':42},{'budget':0},None,7,NOW,99)
        row={**c.events[0],'id':1,'photo':None,'vendor_code':None,'title':None,'actor':'Тестовый сотрудник'}
        conn=Mock();conn.execute.side_effect=[Cursor([row]),Cursor([{'marketplace':'wb'}])]
        table=manage.changes(conn,1,{'date_from':date(2026,11,15),'date_to':date(2026,11,15)})
        self.assertEqual(table['rows'][0]['actor'],'Тестовый сотрудник')
        self.assertEqual(table['rows'][0]['evidence'],'WB принял команду')
        c=Mock();fn=Mock(return_value={'fresh':True})
        self.assertEqual(tabcache.get(c,1,'changes',{},fn),{'fresh':True});c.execute.assert_not_called()

    def test_local_settings_logged_with_actor_not_backfilled(self):
        c=Mock(); old={'enabled':False,'settings':{'max_step':30,'notify':True}}
        new={'enabled':True,'settings':{'max_step':25,'notify':False}}
        with patch.object(actions,'block',side_effect=[old,new]),patch.object(ah,'emit') as emit:
            actions.save_block(c,1,'ads',True,{'max_step':25,'notify':False},7)
        self.assertEqual(emit.call_count,3)
        self.assertTrue(all(x.kwargs['actor_id']==7 for x in emit.call_args_list))
        self.assertEqual({x.args[5] for x in emit.call_args_list},{'enabled','settings.max_step','settings.notify'})

    def test_real_sql_and_migration_idempotency(self):
        with tempfile.TemporaryDirectory(prefix='ad-history-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True,text=True)
            pg=Standalone(cluster,'ads')
            pg.raw('CREATE SCHEMA ads; SET search_path=ads; CREATE TABLE accounts(id int PRIMARY KEY,marketplace text); INSERT INTO accounts VALUES(1,\'wb\'); '
                   'CREATE TABLE service_news(title text,body text,tabs text[]); '
                   'CREATE TABLE users(id int,name text,email text); INSERT INTO users VALUES(7,\'Тестовый сотрудник\',NULL); '
                   'CREATE TABLE nomenclature(account_id int,nm_id bigint,vendor_code text,title text,data jsonb); '
                   'CREATE TABLE oz_products(account_id int,sku bigint,offer_id text,name text,photo text); '
                   'CREATE TABLE card_changes(id bigserial,account_id int,nm_id bigint,kind text,field text,old_value jsonb,new_value jsonb,wb_updated_at timestamptz,detected_at timestamptz);')
            migration=(ROOT/'stometric/migrations/137_ad_settings_history.sql').read_text()
            pg.raw(migration);pg.raw(migration)
            self.assertEqual(pg.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
            daily=(ROOT/'stometric/migrations/148_actions_ad_metrics.sql').read_text()
            pg.raw(daily); pg.raw(daily)
            self.assertEqual(pg.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
            ah.observe_campaign(pg,1,campaign(),NOW)
            self.assertEqual(ah.observe_campaign(pg,1,campaign(status=11,name='Новое'),NOW+timedelta(hours=1))[1],4)
            self.assertEqual(ah.observe_campaign(pg,1,campaign(status=11,name='Новое'),NOW+timedelta(hours=2))[1],0)
            ah.emit(pg,1,42,[100],'ad_command','/adv/v0/pause',{'status':9},{'status':11},NOW,actor_id=7,evidence='accepted_command')
            table=manage.changes(pg,1,{'date_from':date(2026,11,15),'date_to':date(2026,11,15),'nm_ids':[100]})
            self.assertEqual(len(table['rows']),3)
            self.assertTrue(any(r['actor']=='Тестовый сотрудник' for r in table['rows']))


if __name__=='__main__': unittest.main()

"""Daily Jam: synthetic WB, permissions and disposable PostgreSQL. No production I/O."""
import stometric.web
import json
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import HTTPException
from stometric import jam, jam_daily as jd, assistant_jam, api_manager, tabcache
from stometric.tabs import jam as jt
from stometric.wb import WBError
from tools.test_calendar import Cursor, Standalone

ROOT=Path(__file__).resolve().parents[1]
DAY=date(2026,11,15)
V=[1000,7000,12.5,10,100,20,5,40]

def response(nm=10,q='свеча',v=V):
    return {'data':{'items':[{'nmId':nm,'text':q,**{k:{'current':x} for k,x in zip(jd.FIELDS,v)}}]}}

class DailyTests(unittest.TestCase):
    def setUp(self):
                                                                     
                                                                                    
        checkpoint=patch('stometric.jam_progress.open_progress',return_value=None)
        checkpoint.start();self.addCleanup(checkpoint.stop)
        scope=patch('stometric.jam_scope.in_work_ids',side_effect=lambda c,s,n:list(n))
        scope.start();self.addCleanup(scope.stop)
        for module in (jd,jam):
            clock=patch.object(module,'today_msk',return_value=DAY)
            clock.start();self.addCleanup(clock.stop)

    def test_parse_identity_and_unknowns(self):
        self.assertEqual(jd.parse(response(),[10,11]),{10:{'свеча':V},11:{}})
        for bad in ({}, {'data':{'items':None}},response(99),response(q=''),response(q='я'*1001)):
            with self.assertRaises(ValueError): jd.parse(bad,[10])
        for v in (None,True,{},'bad',-1,float('nan'),float('inf')): self.assertIsNone(jd.number(v))
        self.assertEqual(jd.number({'current':0}),0)
        r=response();r['data']['items']+=response(v=[1]*8)['data']['items']
        with self.assertRaises(ValueError): jd.parse(r,[10])

    def test_fetch_union_tariff_fallback_and_no_archive(self):
        wb=Mock();wb.call.side_effect=[WBError('HTTP 400 texts limit'),response(q='а'),response(q='б'),response(q='в')]
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access') as access:
            data,lim,conflicts=jd.fetch(Mock(),wb,3,[10],DAY)
        self.assertEqual(lim,30);self.assertEqual(set(data[10]),{'а','б','в'});self.assertEqual(conflicts,{10:0})
        self.assertEqual(wb.call.call_count,4);access.assert_called_once()
        for call in wb.call.call_args_list:
            self.assertFalse(call.kwargs['archive_response']);self.assertEqual(call.kwargs['body']['currentPeriod'],{'start':str(DAY),'end':str(DAY)})
            self.assertEqual(call.kwargs['body']['nmIds'],[10])

    def test_partial_fetch_never_saves_and_http401_not_subscription_diagnosis(self):
        ctx=SimpleNamespace(c=Mock(),wb=Mock(),acc={'id':3})
        ctx.wb.call.side_effect=[response(),WBError('HTTP 401')]
        with patch.object(jam,'access',return_value=None),patch.object(jd,'pending',return_value=[{'nm_id':10,'day':DAY}]), \
             patch('stometric.exclusions.excluded',return_value=set()),patch.object(jd,'save') as save,patch.object(jam,'_set_access') as access:
            with self.assertRaises(WBError):jd.run(ctx)
        save.assert_not_called();access.assert_not_called()

    def test_bounded_pass_and_subscription_cooldown(self):
        ctx=SimpleNamespace(c=Mock(),wb=Mock(),acc={'id':3,'history_from':DAY})
        with patch.object(jam,'access',return_value=None),patch.object(jd,'pending',return_value=[{'nm_id':10,'day':DAY}]) as pend, \
             patch('stometric.exclusions.excluded',return_value=set()),patch.object(jd,'fetch',return_value=({10:{}},30,{10:0})) as fetch,patch.object(jd,'save',side_effect=lambda c,s,d,data,*_:len(data)):
            self.assertEqual(jd.run(ctx),{'sku_days':2,'cursor':{'backfilled':False}})
            self.assertEqual(fetch.call_count,2);self.assertEqual(pend.call_args.args[-1],DAY)
        with patch.object(jam,'access',return_value={'status':'no_jam','checked_at':datetime.now(timezone.utc)}),patch.object(jd,'pending') as pend:
            self.assertEqual(jd.run(ctx)['skipped'],'jam_access');pend.assert_not_called()

    def test_window_max90_today_excluded(self):
        with patch.object(jd,'today_msk',return_value=DAY):
            a,b=jd.window(DAY-timedelta(days=365),DAY+timedelta(days=20))
        self.assertEqual((b-a).days,89);self.assertEqual(b,DAY-timedelta(days=1))

    def test_normal_jam_refresh_exposes_poll_and_shown_period(self):
        now=datetime.now(timezone.utc);f={'date_from':DAY-timedelta(days=3),'date_to':DAY,'nm_ids':[10]}
        with patch.object(jam,'access',return_value=None),patch.object(jt,'_loaded',return_value=[]), \
             patch.object(jt,'_render',return_value={'rows':[]}),patch.object(jam,'start') as start,patch.object(jt,'_latest',return_value=None):
            with patch.object(jam,'cached',return_value={'state':'done','fetched_at':now-timedelta(hours=3),'items':[]}):
                r=jt.jam_tab(Mock(),3,f);self.assertEqual(r['retry'],5);self.assertIn('Обновляю',r['loading_status'])
            with patch.object(jam,'cached',return_value=None):
                r=jt.jam_tab(Mock(),3,f);self.assertEqual(r['retry'],5);self.assertIn('Загружаю',r['loading_status'])
            other={'date_from':DAY-timedelta(days=20),'date_to':DAY-timedelta(days=10),'items':[]}
            with patch.object(jam,'cached',return_value={'state':'running'}),patch.object(jt,'_latest',return_value=other):
                r=jt.jam_tab(Mock(),3,f);self.assertEqual(r['shown_period'],[other['date_from'],other['date_to']]);self.assertIn('предыдущий',r['loading_status'])

    def test_permissions_before_data_and_foreign_sku(self):
        c=Mock()
        with patch.object(api_manager.auth,'shop_role',return_value=None),patch.object(jd,'query_days') as get:
            with self.assertRaises(HTTPException) as err:api_manager.jam_daily_get(3,10,1,DAY,DAY,{'id':7},c)
            self.assertEqual(err.exception.status_code,403);get.assert_not_called();c.execute.assert_not_called()
        c.execute.return_value=Cursor([])
        with patch.object(api_manager,'_role'),patch.object(jd,'query_days') as get:
            with self.assertRaises(HTTPException) as err:api_manager.jam_daily_get(3,10,1,DAY,DAY,{'id':7},c)
            self.assertEqual(err.exception.status_code,404);get.assert_not_called()
        with patch.object(jd,'ai_history') as get:
            self.assertIn('error',assistant_jam.history(c,3,7,{'nm_id':10}));get.assert_not_called()

    def test_morning_uses_shared_runner_and_inactive_shop_skipped(self):
        from stometric import collectors,wb
        c=Mock();c.execute.return_value=Cursor([{'id':3}])
        with patch.object(collectors,'run_one',return_value={'ok':True,'sku_days':50}) as run,patch.object(wb,'WB'):
            tabcache._jam_daily_prefetch(c,3,lambda _:None)
            self.assertEqual(run.call_args.args[1],'jam_daily');self.assertEqual(run.call_args.args[0].acc,{'id':3})
            c.execute.return_value=Cursor([]);run.reset_mock();tabcache._jam_daily_prefetch(c,3,lambda _:None);run.assert_not_called()

    def test_api_audit_kept_without_raw_archive_and_writes_still_denied(self):
        import httpx
        from stometric.wb import WB
        wb=object.__new__(WB);wb.c=Mock();wb.acc={'id':3};wb.http=Mock()
        wb.http.request.return_value=httpx.Response(200,json=response())
        wb._wait_slot=Mock();wb._archive=Mock(return_value='synthetic.json.gz')
        self.assertEqual(wb.call('analytics',jam.PATH,'POST',body={'nmIds':[10]},archive_response=False),response())
        wb._archive.assert_not_called();self.assertIn('INSERT INTO api_log',wb.c.execute.call_args.args[0])
        self.assertEqual(wb.c.execute.call_args.args[1][3],200);self.assertIsNone(wb.c.execute.call_args.args[1][5])
        wb.call('analytics',jam.PATH,'POST',body={'nmIds':[10]});wb._archive.assert_called_once()
        with self.assertRaises(WBError):wb.call('advert','/adv/v1/pause','POST',archive_response=False)

    def test_ai_response_is_complete_json_below_envelope_and_reports_next(self):
        days=[str(DAY-timedelta(days=i+1)) for i in range(90)]
        series={i:{d:dict(zip(jd.FIELDS,V)) for d in days} for i in range(1,11)}
        src={'from':min(days),'to':max(days),'days':days,'coverage':{d:{'conflicts':0} for d in days},
             'queries':{i:'запрос '+str(i) for i in series},'series':series,'missing_days':[]}
        with patch.object(jd,'read',return_value=src):out=jd.ai_history(Mock(),3,10,DAY,DAY)
        payload=json.dumps(out,ensure_ascii=False);self.assertLess(len(payload),30000)
        self.assertEqual(len(json.loads(payload)['rows'][0]['daily']),90)
        self.assertEqual(out['next_offset'],len(out['rows']));self.assertLess(out['next_offset'],10)

    def test_summary_not_silently_cut_by_generic_table_pagination(self):
        rows=[{'query':str(i)} for i in range(501)]
        res=stometric.web._page({'custom':'jam_deep','columns':[],'rows':rows},100,0,None,False)
        self.assertEqual(len(res['rows']),501)

    def test_collector_registration_and_backfill_schedule(self):
        from stometric import collectors,schedule
        self.assertIs(collectors.registry()['jam_daily'],jd.run)
        self.assertIn('jam_daily',schedule.BACKFILL)
        self.assertEqual(schedule.EVERY_MIN['jam_daily'],24*60)
        self.assertIn('jam_deep',tabcache.NOCACHE);self.assertIn('jam_deep',tabcache.SKIP)


    def test_deep_starts_with_exact_ordinary_period_rows_columns_totals(self):
        c=Mock();c.execute.return_value=Cursor([])
        f={'date_from':DAY-timedelta(days=29),'date_to':DAY,'nm_ids':[10]}
        base={'columns':[{'field':k,'title':t,'type':ty} for k,t,ty in jt.COLS],
              'rows':[{'query':'только в отчёте за период','pos':7.25,'orders':123}],
              'total_row':{'orders':123},'rules':{'pos':[]},'grad':['pot_profit'],'note':'Обычный отчёт','plain':True}
        src={'days':['2026-11-14'],'missing_days':['2026-11-14'],'coverage':{}}
        with patch.object(jt,'jam_tab',return_value=base) as standard,patch.object(jd,'read',return_value=src),patch.object(jam,'access',return_value=None):
            out=jt.deep_tab(c,3,f)
        for k in ('rows','columns','total_row','rules','grad'):self.assertEqual(out[k],base[k])
        self.assertEqual(out['custom'],'jam_deep');self.assertEqual(out['jam_deep']['period_to'],str(DAY))
        self.assertEqual(standard.call_args.args[2]['nm_ids'],[10]);self.assertEqual(out['jam_deep']['loaded_days'],0)

    def test_deep_separates_shown_summary_from_selected_daily_period(self):
        c=Mock();c.execute.return_value=Cursor([]);a=DAY-timedelta(days=20);b=DAY-timedelta(days=10)
        base={'columns':[{'field':'query'}],'rows':[{'query':'ключ'}],'shown_period':[a,b],'retry':5,'loading_status':'Ждём новый период'}
        with patch.object(jt,'jam_tab',return_value=base),patch.object(jd,'read',return_value={'days':[],'missing_days':[],'coverage':{}}) as read,patch.object(jam,'access',return_value=None):
            out=jt.deep_tab(c,3,{'date_from':DAY-timedelta(days=5),'date_to':DAY,'nm_ids':[10]})
        self.assertEqual(read.call_args.args[-2:],(DAY-timedelta(days=5),DAY-timedelta(days=1)));self.assertEqual(out['retry'],5)
        self.assertEqual(out['loading_status'],'Ждём новый период');self.assertEqual(out['jam_deep']['period_from'],str(a))

    def test_deep_loading_still_opens_daily_history(self):
        base=jt._msg('Загрузка',retry=5)
        c=Mock();c.execute.return_value=Cursor([])
        src={'days':['2026-11-14'],'missing_days':[],'coverage':{'2026-11-14':{}},
             'series':{1:{'2026-11-14':dict(zip(jd.FIELDS,V))}},'queries':{1:'ключ'}}
        with patch.object(jt,'jam_tab',return_value=base),patch.object(jd,'read',return_value=src) as read,patch.object(jam,'access',return_value=None):
            out=jt.deep_tab(c,3,{'date_from':DAY-timedelta(days=1),'date_to':DAY,'nm_ids':[10]})
        self.assertEqual(out['custom'],'jam_deep');self.assertEqual(out['rows'][0]['query'],'ключ')
        self.assertEqual(out['rows'][0]['orders'],5);self.assertNotIn('pos',out['rows'][0])
        self.assertNotIn('total_row',out);self.assertEqual(out['jam_deep']['summary_source'],'daily_preview')
        self.assertEqual(out['jam_deep']['loaded_days'],1);self.assertEqual(out['retry'],5)
        read.assert_called_once()

    def test_query_text_route_scopes_and_validates_before_daily_read(self):
        c=Mock()
        with patch.object(api_manager.auth,'shop_role',return_value=None),patch.object(jd,'query_days') as read:
            with self.assertRaises(HTTPException):api_manager.jam_query_days(3,10,'ключ',DAY,DAY,{'id':7},c)
            c.execute.assert_not_called();read.assert_not_called()
        with patch.object(api_manager,'_role'),patch.object(jd,'query_days') as read:
            for q in ('','я'*1001):
                with self.assertRaises(HTTPException) as e:api_manager.jam_query_days(3,10,q,DAY,DAY,{'id':7},c)
                self.assertEqual(e.exception.status_code,422)
            c.execute.return_value=Cursor([])
            with self.assertRaises(HTTPException) as e:api_manager.jam_query_days(3,10,'ключ',DAY,DAY,{'id':7},c)
            self.assertEqual(e.exception.status_code,404);read.assert_not_called()
            c.execute.return_value=Cursor([{'one':1}]);read.return_value={'rows':[]}
            api_manager.jam_query_days(3,10,'ключ & другой',DAY,DAY,{'id':7},c)
            self.assertEqual(read.call_args.kwargs,{'query_text':'ключ & другой'})


class DailySql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='jam-test-pg-');cls.cluster=Path(cls.tmp.name)/'db'
        p=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','jam_test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if p.returncode:raise AssertionError(p.stderr)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        schema='jam_'+uuid4().hex;self.c=Standalone(self.cluster,schema);self.c.transaction=nullcontext
        self.c.raw(f'''CREATE SCHEMA {schema};SET search_path={schema};
        CREATE TABLE accounts(id int PRIMARY KEY,marketplace text);INSERT INTO accounts VALUES(3,'wb'),(4,'wb');
        CREATE TABLE service_news(title text,body text,tabs text[]);
        CREATE TABLE nomenclature(account_id int,nm_id bigint);INSERT INTO nomenclature VALUES(3,10),(3,11),(4,20);
        ALTER TABLE nomenclature ADD COLUMN brand text, ADD COLUMN subject text;
        CREATE TABLE shop_exclusions(account_id int,kind text,value text,added_at timestamptz DEFAULT now());
        CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
        CREATE TABLE wb_ad_kw_daily(account_id int,nm_id bigint,day date,query text,views int,clicks int,spend numeric);
        CREATE TABLE collector_state(account_id int,collector text,cursor jsonb);
        '''+(ROOT/'stometric/migrations/139_jam_deep.sql').read_text())
        self.clock=patch.object(jd,'today_msk',return_value=DAY);self.clock.start();self.addCleanup(self.clock.stop)
    def save(self,day=DAY-timedelta(days=1),data=None,shop=3):
        jd.save(self.c,shop,day,data if data is not None else {10:{'свеча':V},11:{'свеча':V}},100,{10:0,11:0,20:0})
    def test_upsert_dictionary_compact_and_shop_isolation(self):
        self.save();self.save();self.save(day=DAY-timedelta(days=2));self.save(data={20:{'свеча':V}},shop=4)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_queries').fetchone()['n'],2)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily').fetchone()['n'],5)
        self.assertEqual(len(jd.read(self.c,3,10,DAY-timedelta(days=3),DAY)['series']),1)
        self.assertEqual(jd.read(self.c,3,20,DAY-timedelta(days=3),DAY)['series'],{})
        self.c.raw((ROOT/'stometric/migrations/139_jam_deep.sql').read_text())
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
    def test_gaps_daily_metrics_and_cost_rebuild(self):
        d=DAY-timedelta(days=1);self.save();self.save(day=d-timedelta(days=1),data={10:{}})
        self.c.execute('INSERT INTO agg_nm_day VALUES(3,10,%s,%s::jsonb)',(d,json.dumps({'orders':10,'cost_orders':100,'profit_orders':200,'ads_upd':50})))
        self.c.execute('INSERT INTO wb_ad_kw_daily VALUES(3,10,%s,%s,1000,100,50)',(d,'свеча'))
        src=jd.read(self.c,3,10,d-timedelta(days=2),d);qid=next(iter(src['queries']))
        out=jd.query_days(self.c,3,10,qid,d-timedelta(days=2),d);r=out['rows'][0]
        self.assertEqual([x['state'] for x in out['rows']],['observed','outside_top','missing_day'])
        self.assertEqual((r['pos'],r['clicks'],r['carts'],r['orders']),(12.5,100,20,5))
        self.assertEqual((r['profit'],r['cr_cart'],r['cr_order']),(75,.2,.25))
        self.c.execute("INSERT INTO collector_state VALUES(3,'_cost_rebuild','{\"dirty\":true}'::jsonb)")
        out=jd.query_days(self.c,3,10,qid,d,d);self.assertTrue(out['financial_pending']);self.assertIsNone(out['rows'][0]['profit'])
    def test_missing_ad_data_not_zero_profit_and_no_position_average(self):
        d=DAY-timedelta(days=1);self.save();self.save(day=d-timedelta(days=1),data={10:{'свеча':[1000,7000,60,20,20,10,0,40]}})
        src=jd.read(self.c,3,10,d-timedelta(days=2),d);r=jd.summaries(src)[0]
        self.assertEqual((r['pos'],r['clicks'],r['orders'],r['observed_days']),(12.5,120,5,2))
        x=jd.query_days(self.c,3,10,r['query_id'],d,d)['rows'][0]
        self.assertIsNone(x['spend']);self.assertIsNone(x['profit']);self.assertEqual(x['orders'],5)
    def test_backfill_fresh_first_exclusions_and_history_boundary(self):
        todo=jd.pending(self.c,3,{11},DAY-timedelta(days=2))
        self.assertEqual([(r['nm_id'],r['day']) for r in todo],[(10,DAY-timedelta(days=1)),(10,DAY-timedelta(days=2))])
        self.save(data={10:{}})
        self.assertEqual(jd.pending(self.c,3,{11},DAY-timedelta(days=2)),[{'nm_id':10,'day':DAY-timedelta(days=2)}])
        self.c.execute("UPDATE jam_daily SET fetched_at=now()-interval '2 days'")
                                                                              
        self.assertEqual(jd.pending(self.c,3,{11},DAY-timedelta(days=2))[0]['day'],DAY-timedelta(days=2))
    def test_ai_pages_and_zero_vs_missing(self):
        self.save(data={10:{f'запрос {i}':V for i in range(25)}})
        first=jd.ai_history(self.c,3,10,DAY-timedelta(days=2),DAY)
        self.assertEqual(first['query_count'],25);self.assertEqual(first['next_offset'],10)
        self.assertEqual(first['rows'][0]['daily'][0][1],'missing_day')
        second=jd.ai_history(self.c,3,10,DAY-timedelta(days=2),DAY,offset=10)
        self.assertFalse({r['query_id'] for r in first['rows']} & {r['query_id'] for r in second['rows']})
        search=jd.ai_history(self.c,3,10,DAY,DAY,query='нет');self.assertEqual(search['rows'],[])
    def test_numeric_pack_size(self):
                                                                                 
        data={f'Поисковый запрос номер {i}':V for i in range(100)};self.save(data={10:data})
        full=[{'text':q,**dict(zip(jd.FIELDS,v))} for q,v in data.items()]
        sizes=self.c.execute('SELECT pg_column_size(metrics) packed,pg_column_size(%s::jsonb) verbose FROM jam_daily WHERE account_id=3 AND nm_id=10',(json.dumps(full),)).fetchone()
        self.assertLess(sizes['packed'],sizes['verbose']);print('Synthetic Jam bytes:',sizes)

    def test_period_query_without_daily_observations_stays_expandable(self):
        d=DAY-timedelta(days=1);self.save()
        out=jd.query_days(self.c,3,10,None,d-timedelta(days=1),d,query_text='пока только в отчёте за период')
        self.assertEqual([r['state'] for r in out['rows']],['outside_top','missing_day'])
        self.assertTrue(all('orders' not in r for r in out['rows']))
        out=jd.query_days(self.c,3,10,None,d,d,query_text='свеча');self.assertEqual(out['rows'][0]['orders'],5)

    def test_period_expand_news_is_idempotent_and_preserves_daily_data(self):
        self.save()
        news=(ROOT/'stometric/migrations/140_jam_period_expand_news.sql').read_text()
        self.c.raw(news);self.c.raw(news)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily').fetchone()['n'],2)

if __name__=='__main__':unittest.main()

"""Queue regression and resumable selectors on disposable PostgreSQL only."""
import stometric.web
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from stometric import jam, jam_daily as jd, schedule, collectors
from stometric.jam_progress import Progress, open_progress
from stometric.wb import RateLimited, WBError
from tools.test_calendar import Cursor
from tools.test_jam_deep import DailySql, DAY, ROOT, response


class QueueSql(unittest.TestCase):
    setUpClass=classmethod(DailySql.setUpClass.__func__)
    tearDownClass=classmethod(DailySql.tearDownClass.__func__)

    def setUp(self):
        DailySql.setUp(self)
        self.c.raw((ROOT/'stometric/migrations/154_jam_queue.sql').read_text())
        self.day=DAY-timedelta(days=1)

    def test_missing_week_precedes_refresh_even_after_midnight(self):
                                                                         
        jd.save(self.c,3,self.day,{10:{},11:{}},100,{10:0,11:0})
        self.c.execute("UPDATE jam_daily SET fetched_at=now()-interval '2 days'")
        for lane in (False,True):
            todo=jd.pending(self.c,3,set(),history_first=lane)
            self.assertEqual(todo[0]['day'],self.day-timedelta(days=1))
        with patch.object(jd,'today_msk',return_value=DAY+timedelta(days=1)):
            todo=jd.pending(self.c,3,set())
            self.assertEqual(todo[0]['day'],DAY)
            self.assertEqual(todo[2]['day'],self.day-timedelta(days=1))

    def test_complete_week_alternates_older_gaps_and_refresh(self):
        self.c.execute('''INSERT INTO jam_daily(account_id,nm_id,day,metrics,query_count,max_limit,conflicts,fetched_at)
            SELECT 3,n,d::date,'[]'::jsonb,0,100,0,now()-interval '2 days'
            FROM generate_series(10,11) n CROSS JOIN generate_series(%s::date,%s::date,interval '1 day') d''',
            (self.day-timedelta(days=6),self.day))
        self.assertEqual(jd.pending(self.c,3,set())[0]['day'],self.day)
        self.assertEqual(jd.pending(self.c,3,set(),history_first=True)[0]['day'],self.day-timedelta(days=7))

    def test_partial_success_survives_rate_limit_but_is_not_daily_coverage(self):
        wb=Mock();wb.call.side_effect=[response(q='клики'),RateLimited('synthetic',datetime.now(timezone.utc)+timedelta(hours=1))]
        p=Progress(self.c,3,self.day,[10])
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            with self.assertRaises(RateLimited):jd.fetch(self.c,wb,3,[10],self.day,progress=p)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily_progress').fetchone()['n'],1)
        self.assertEqual(jd.read(self.c,3,10,self.day,self.day)['missing_days'],[str(self.day)])
        wb=Mock();wb.call.side_effect=[response(q='заказы'),response(q='корзины')]
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            data,limit,conflicts=jd.fetch(self.c,wb,3,[10],self.day,progress=Progress(self.c,3,self.day,[10]))
        self.assertEqual(wb.call.call_count,2)
        self.assertEqual([c.kwargs['body']['topOrderBy'] for c in wb.call.call_args_list],['orders','addToCart'])
        self.assertEqual(set(data[10]),{'клики','заказы','корзины'})
        jd.save(self.c,3,self.day,data,limit,conflicts);p.finish()
        self.assertEqual(jd.read(self.c,3,10,self.day,self.day)['missing_days'],[])
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily_progress').fetchone()['n'],0)

    def test_resume_allows_one_call_per_pass_without_losing_other_tops(self):
        for index,top in enumerate(jam.TOPS):
            wb=Mock();wb.call.side_effect=[response(q=top),RateLimited('synthetic',datetime.now(timezone.utc)+timedelta(hours=1))]
            with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
                if index<2:
                    with self.assertRaises(RateLimited):jd.fetch(self.c,wb,3,[10],self.day,progress=Progress(self.c,3,self.day,[10]))
                else:
                    data,_,_=jd.fetch(self.c,wb,3,[10],self.day,progress=Progress(self.c,3,self.day,[10]))
                    self.assertEqual(set(data[10]),set(jam.TOPS));self.assertEqual(wb.call.call_count,1)

    def test_checkpoint_is_scoped_and_empty_success_is_reused(self):
        p=Progress(self.c,3,self.day,[10]);p.put('openCard',100,{10:{}})
        self.assertEqual(p.get('openCard',100,[10]),{10:{}})
        for other in (Progress(self.c,4,self.day,[10]),Progress(self.c,3,self.day,[10,11]),
                      Progress(self.c,3,self.day-timedelta(days=1),[10])):
            self.assertIsNone(other.get('openCard',100,[10]))
        self.assertIsNone(p.get('orders',100,[10]));self.assertIsNone(p.get('openCard',30,[10]))
        self.c.execute("UPDATE jam_daily_progress SET fetched_at=now()-interval '49 hours'")
        self.assertIsNone(p.get('openCard',100,[10]))
        p.put('orders',100,{10:{}})
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily_progress').fetchone()['n'],1)

    def test_tariff_fallback_checkpoint_does_not_repeat_failed_100_request(self):
        p=Progress(self.c,3,self.day,[10]);wb=Mock()
        wb.call.side_effect=[WBError('HTTP 400 texts limit'),response(q='первый'),RateLimited('synthetic',datetime.now(timezone.utc)+timedelta(hours=1))]
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            with self.assertRaises(RateLimited):jd.fetch(self.c,wb,3,[10],self.day,progress=p)
        wb=Mock();wb.call.return_value=response(q='следующий')
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            data,limit,_=jd.fetch(self.c,wb,3,[10],self.day,progress=p)
        self.assertEqual(limit,30);self.assertEqual(wb.call.call_count,2)
        self.assertTrue(all(c.kwargs['body']['limit']==30 for c in wb.call.call_args_list))
        self.assertIn('первый',data[10])

    def test_exclusion_between_requests_does_not_write_excluded_day(self):
        p=Progress(self.c,3,self.day,[10,11]);p.put('openCard',100,{10:{},11:{}})
        self.c.execute("INSERT INTO shop_exclusions(account_id,kind,value) VALUES(3,'nm','11')")
        wb=Mock();wb.call.return_value=response()
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            data,limit,conflicts=jd.fetch(self.c,wb,3,[10,11],self.day,progress=p)
        self.assertEqual(set(data),{10});self.assertEqual(wb.call.call_count,2)
        self.assertTrue(all(c.kwargs['body']['nmIds']==[10] for c in wb.call.call_args_list))
        jd.save(self.c,3,self.day,data,limit,conflicts)
        self.assertEqual(self.c.execute('SELECT nm_id FROM jam_daily').fetchall(),[{'nm_id':10}])

    def test_reselected_product_requires_new_selector(self):
        p=Progress(self.c,3,self.day,[10,11]);p.put('openCard',100,{10:{}})
        self.assertEqual(p.get('openCard',100,[10]),{10:{}})
        self.assertIsNone(p.get('openCard',100,[10,11]))

    def test_http_failure_not_swallowed_old_report_stays_and_bad_checkpoint_rejected(self):
        jd.save(self.c,3,self.day,{10:{}},100,{10:0})
        p=Progress(self.c,3,self.day,[10]);p.put('openCard',100,{10:{}})
        wb=Mock();wb.call.side_effect=WBError('HTTP 401')
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            with self.assertRaises(WBError):jd.fetch(self.c,wb,3,[10],self.day,progress=p)
        self.assertEqual(self.c.execute('SELECT query_count FROM jam_daily').fetchone()['query_count'],0)
        self.c.execute("UPDATE jam_daily_progress SET payload='{\"999\":{}}'::jsonb")
        with self.assertRaises(ValueError):p.get('openCard',100,[10])

    def test_real_scheduled_pass_completes_then_clears_transport_checkpoints(self):
        ctx=SimpleNamespace(c=self.c,acc={'id':3,'history_from':self.day},wb=Mock())
        ctx.wb.call.return_value=response()
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            result=jd.run(ctx)
        self.assertEqual(result,{'sku_days':2,'cursor':{'backfilled':True}})
        self.assertEqual(ctx.wb.call.call_count,3)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily_progress').fetchone()['n'],0)
        self.c.raw((ROOT/'stometric/migrations/154_jam_queue.sql').read_text())
        self.assertEqual(self.c.execute("SELECT count(*) n FROM service_news WHERE title='Джем глубокий: приоритет недостающей недели'").fetchone()['n'],0)


class CooldownTests(unittest.TestCase):
    def test_checkpoint_optional_until_migration_and_does_not_create_schema(self):
        c=Mock();c.execute.return_value=Cursor([{'present':False}])
        self.assertIsNone(open_progress(c,3,DAY,[10]))
        c.commit.assert_not_called()
        self.assertEqual(c.execute.call_count,1)

    def test_schedule_waits_for_wb_then_resumes_normal_backfill(self):
        until=datetime.now(timezone.utc)+timedelta(hours=1)
        c=Mock();c.execute.return_value=Cursor([{'collector':'jam_daily','last_run_at':None,
            'cursor':{'backfilled':False,'retry_after':until.isoformat()}}])
        with patch('stometric.loadplan.is_big',return_value=False):
            self.assertNotIn('jam_daily',schedule.due(c,3))
            for value in ((until-timedelta(hours=2)).isoformat(),'bad'):
                c.execute.return_value=Cursor([{'collector':'jam_daily','last_run_at':None,
                    'cursor':{'backfilled':False,'retry_after':value}}])
                self.assertIn('jam_daily',schedule.due(c,3))

    def test_rate_limit_keeps_until_and_success_clears_it(self):
        until=datetime.now(timezone.utc)+timedelta(hours=1)
        ctx=Mock();ctx.acc={'id':3};ctx.state.return_value={'backfilled':True}
        def limited(_):raise RateLimited('synthetic',until)
        result=collectors._run(ctx,'jam_daily',limited)
        self.assertTrue(result['rate_limited'])
        self.assertEqual(ctx.save_state.call_args.args[1],{'backfilled':False,'retry_after':until.isoformat()})
        ctx.save_state.reset_mock()
        result=collectors._run(ctx,'jam_daily',lambda _:{'cursor':{'backfilled':False},'sku_days':50})
        self.assertTrue(result['ok']);self.assertNotIn('retry_after',ctx.save_state.call_args.args[1])


if __name__=='__main__':unittest.main()

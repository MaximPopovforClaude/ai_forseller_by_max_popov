"""Saved period reports and incremental daily history, without production I/O."""
import stometric.web
import unittest
import os
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from stometric import jam, jam_daily as jd, tabcache
from stometric.tabs import jam as jt
from tools.test_calendar import Cursor
from tools.test_jam_work_selection import SelectionSql
from tools.test_jam_deep import DAY, ROOT


class ProgressiveTests(unittest.TestCase):
    def setUp(self):
        self.c=Mock();self.c.execute.return_value=Cursor([])
        self.f={'date_from':DAY-timedelta(days=29),'date_to':DAY,'nm_ids':[10]}
        for obj,name,kwargs in [(jam,'today_msk',{'return_value':DAY}),
                                (jd,'today_msk',{'return_value':DAY}),
                                (jt.jam_scope,'in_work_ids',{'side_effect':lambda c,s,n:list(n)}),
                                (jt,'_loaded',{'return_value':[]})]:
            p=patch.object(obj,name,**kwargs);p.start();self.addCleanup(p.stop)

    def test_running_and_failed_refresh_preserve_successful_items(self):
        now=datetime.now(timezone.utc)
        for state in ('running','error'):
            cached={'state':state,'items':[{'text':'stored'}],'fetched_at':now,'started_at':now,'error':'synthetic'}
            with (self.subTest(state=state),patch.object(jam,'access',return_value=None),
                  patch.object(jam,'cached',return_value=cached),patch.object(jam,'start') as start,
                  patch.object(jt,'_latest') as latest,patch.object(jt,'_render',return_value={'rows':[{'query':'stored'}]}) as render):
                out=jt.jam_tab(self.c,3,self.f)
            self.assertEqual(out['rows'],[{'query':'stored'}]);self.assertEqual(render.call_args.args[5],cached['items'])
            self.assertEqual(out['retry'],5 if state=='running' else None)
            start.assert_not_called();latest.assert_not_called()

    def test_access_error_keeps_history_and_does_not_request_wb(self):
        now=datetime.now(timezone.utc)
        cached={'state':'error','items':[],'fetched_at':now,'started_at':now,'error':'synthetic'}
        with (patch.object(jam,'access',return_value={'status':'no_scope','checked_at':now}),
              patch.object(jam,'cached',return_value=cached),patch.object(jam,'start') as start,
              patch.object(jt,'_render',return_value={'rows':[],'columns':[{'field':'query'}]})):
            out=jt.jam_tab(self.c,3,self.f)
        start.assert_not_called();self.assertIn(jam.NO_SCOPE,out['note']);self.assertIsNone(out['retry'])

    def test_no_period_or_daily_data_keeps_expandable_screen_and_refresh(self):
        src={'days':['2026-11-14'],'missing_days':['2026-11-14'],'coverage':{},'series':{},'queries':{}}
        with (patch.object(jt,'jam_tab',return_value=jt._msg('Ошибка WB')),
              patch.object(jd,'read',return_value=src),patch.object(jam,'access',return_value=None)):
            out=jt.deep_tab(self.c,3,self.f)
        self.assertEqual(out['custom'],'jam_deep');self.assertEqual(out['rows'],[])
        self.assertEqual(len(out['columns']),23);self.assertEqual(out['retry'],30)
        self.assertEqual(out['jam_deep']['missing_days'],['2026-11-14'])

    def test_empty_period_report_does_not_hide_observed_queries(self):
        src={'days':['2026-11-14'],'missing_days':[],'coverage':{'2026-11-14':{}},
             'queries':{1:'observed'},'series':{1:{'2026-11-14':{
                 'avgPosition':25,'openCard':10,'addToCart':2,'orders':1}}}}
        with (patch.object(jt,'jam_tab',return_value={'columns':[{'field':'query'}],'rows':[]}),
              patch.object(jd,'read',return_value=src),patch.object(jam,'access',return_value=None)):
            out=jt.deep_tab(self.c,3,self.f)
        self.assertEqual(out['rows'],[{'query':'observed','clicks':10,'carts':2,'orders':1}])
        self.assertNotIn('total_row',out);self.assertEqual(out['jam_deep']['summary_source'],'daily_preview')

    def test_day_refresh_revision_changes_even_with_same_count_and_keeps_period_totals(self):
        base={'columns':[{'field':'query'}],'rows':[{'query':'key','orders':123}],'total_row':{'orders':123}}
        src={'days':['2026-11-14'],'missing_days':[],'coverage':{'2026-11-14':{'fetched_at':'v1'}}}
        with (patch.object(jt,'jam_tab',return_value=base),patch.object(jd,'read',return_value=src),
              patch.object(jam,'access',return_value=None)):
            first=jt.deep_tab(self.c,3,self.f);same=jt.deep_tab(self.c,3,self.f)
            src['coverage']['2026-11-14']['fetched_at']='v2'
            updated=jt.deep_tab(self.c,3,self.f)
        self.assertEqual(first['jam_deep']['daily_revision'],same['jam_deep']['daily_revision'])
        self.assertNotEqual(first['jam_deep']['daily_revision'],updated['jam_deep']['daily_revision'])
        self.assertEqual(updated['rows'],base['rows']);self.assertEqual(updated['total_row'],base['total_row'])
        self.assertEqual(updated['retry'],30)

    def test_actual_react_expansion_and_mainapp_poll(self):
        for mode in ('development','production'):
            for name in ('jam_deep.cjs','pnl_cost_pending.cjs'):
                with self.subTest(mode=mode,scenario=name):
                    run=subprocess.run(['node',str(ROOT/'tools/frontend'/name),str(ROOT)],
                        env={**os.environ,'NODE_ENV':mode},capture_output=True,text=True,timeout=25)
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)


class ProgressiveSql(unittest.TestCase):
    setUpClass=classmethod(SelectionSql.setUpClass.__func__)
    tearDownClass=classmethod(SelectionSql.tearDownClass.__func__)
    setUp=SelectionSql.setUp

    def test_yesterday_cache_visible_during_refresh_but_not_foreign_or_empty_job(self):
        self.c.raw("""INSERT INTO jam_cache VALUES
            (3,10,'2026-10-16','2026-11-14','running','[]',now()-interval '1 day',now(),NULL),
            (3,10,'2026-10-17','2026-11-15','running',NULL,NULL,now(),NULL),
            (4,10,'2026-10-18','2026-11-16','done','[]',now(),now(),NULL);""")
        row=jt._latest(self.c,3,10)
        self.assertEqual(str(row['date_to']),'2026-11-14');self.assertEqual(row['items'],[])
        self.assertEqual([r['nm_id'] for r in jt._loaded(self.c,3)],[10])
        self.assertIsNone(jt._latest(self.c,3,20))

    def test_short_report_does_not_block_morning_full_period(self):
        from stometric.config import today_msk
        today=today_msk()
        self.c.execute('INSERT INTO agg_nm_day VALUES(3,10,%s,%s::jsonb)',(today,'{"f_orders":100}'))
        self.c.execute("INSERT INTO jam_cache VALUES(3,10,%s,%s,'done','[]',now(),now(),NULL)",
                       (today-timedelta(days=1),today))
        with patch.object(jam,'access',return_value={'status':'ok'}),patch.object(jam,'fetch',return_value=[]) as fetch:
            tabcache._jam_prefetch(self.c,3,lambda _:None)
            fetch.assert_called_once();self.assertEqual(fetch.call_args.args[-2:],(today-timedelta(days=29),today))
            fetch.reset_mock();tabcache._jam_prefetch(self.c,3,lambda _:None);fetch.assert_not_called()

    def test_progressive_news_idempotent(self):
        news=(ROOT/'stometric/migrations/145_jam_progressive_news.sql').read_text()
        self.c.raw(news);self.c.raw(news)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)


if __name__=='__main__':unittest.main()

"""Jam work selection: synthetic requests and disposable PostgreSQL, no live WB."""
import stometric.web
import unittest
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock, patch

from stometric import db, exclusions, jam, jam_daily as jd, jam_scope as scope, tabcache
from stometric.tabs import jam as jt
from stometric.wb import WBError
from tools.test_calendar import Cursor
from tools.test_jam_deep import DailySql, DAY, V, ROOT, response


class GuardTests(unittest.TestCase):
    def test_ordinary_excluded_never_starts_thread_or_calls_wb(self):
        c=Mock();c.execute.return_value=Cursor([])
        with (patch.object(db,'connect',return_value=nullcontext(c)),
              patch.object(jam.threading,'Thread') as thread, patch('stometric.wb.WB') as wb):
            with self.assertRaises(scope.NotInWork):jam.start(3,10,DAY,DAY)
            with self.assertRaises(scope.NotInWork):jam.fetch(c,3,10,DAY,DAY)
        thread.assert_not_called();wb.assert_not_called();c.commit.assert_not_called()
        self.assertTrue(all('INSERT' not in call.args[0] for call in c.execute.call_args_list))

    def test_excluded_selected_sku_gives_message_in_both_tabs_without_loading(self):
        c=Mock();c.execute.return_value=Cursor([])
        f={'date_from':DAY,'date_to':DAY,'nm_ids':[10]}
        with patch.object(jam,'start') as start,patch.object(jam,'cached') as cached:
            for build in (jt.jam_tab,jt.deep_tab):
                self.assertEqual(build(c,3,f)['rows'][0]['msg'],scope.NOT_IN_WORK)
        start.assert_not_called();cached.assert_not_called()

    def test_ordinary_background_rechecks_before_overwriting_history(self):
        c=Mock();c.execute.return_value=Cursor([])
        with (patch.object(db,'connect',return_value=nullcontext(c)),
              patch.object(jam,'fetch',return_value=[{'text':'new'}])):
            jam._run(3,10,DAY,DAY)
        statements=[call.args[0] for call in c.execute.call_args_list]
        self.assertFalse(any("state='done'" in sql for sql in statements))
        error=[call for call in c.execute.call_args_list if "state='error'" in call.args[0]]
        self.assertEqual(len(error),1)
        self.assertIn(scope.NOT_IN_WORK,error[0].args[1])

    def test_validation_and_empty_ids_do_not_query(self):
        c=Mock()
        self.assertEqual(scope.in_work_ids(c,3,[]),[])
        for value in (True,False,0,-1,'10',2**63,[]):
            with self.assertRaises(ValueError):scope.in_work_ids(c,3,[value])
        c.execute.assert_not_called()


class SelectionSql(unittest.TestCase):
    setUpClass=classmethod(DailySql.setUpClass.__func__)
    tearDownClass=classmethod(DailySql.tearDownClass.__func__)

    def setUp(self):
        DailySql.setUp(self)
        self.c.raw('''ALTER TABLE nomenclature ADD COLUMN vendor_code text;
            CREATE TABLE jam_cache(account_id int,nm_id bigint,date_from date,date_to date,
                state text,items jsonb,fetched_at timestamptz,started_at timestamptz,error text,
                PRIMARY KEY(account_id,nm_id,date_from,date_to));''')
        self.addCleanup(exclusions._CACHE.pop,3,None)

    def exclude(self,kind,value,shop=3):
        self.c.execute('INSERT INTO shop_exclusions(account_id,kind,value) VALUES(%s,%s,%s)',(shop,kind,str(value)))

    def test_all_dimensions_shop_isolation_and_new_cards_ignore_stale_cache(self):
        self.c.raw("UPDATE nomenclature SET brand='Closed' WHERE account_id=3 AND nm_id=11;")
        self.exclude('brand','Closed');self.exclude('subject','Hidden');self.exclude('nm',10,4)
                                                                    
        exclusions._CACHE[3]=(('same-rule-version',),{11})
                                                                                   
        self.c.raw("""UPDATE nomenclature SET subject='Hidden' WHERE account_id=3 AND nm_id=10;
            INSERT INTO nomenclature(account_id,nm_id,brand) VALUES(3,12,'Closed'),(3,13,'Open');""")
        self.assertEqual(scope.in_work_ids(self.c,3,[12,10,13,11,20,13]),[13])
        self.assertEqual(exclusions._CACHE[3][1],{11})
        self.assertEqual(scope.in_work_ids(self.c,4,[10,20]),[20])
        self.exclude('nm',13)
        self.assertEqual(scope.in_work_ids(self.c,3,[13]),[])

    def test_pending_filters_before_batch_limit_and_intersects_pinned_catalog(self):
        self.c.raw("""INSERT INTO nomenclature(account_id,nm_id,brand)
            SELECT 3,n,CASE WHEN n<180 THEN 'Closed' ELSE 'Open' END FROM generate_series(100,240) n;""")
        self.exclude('brand','Closed');self.exclude('nm',10);self.exclude('nm',11)
        args=dict(date_from=DAY-timedelta(days=1),date_to=DAY-timedelta(days=1),nm_ids=list(range(100,241)))
        todo=jd.pending(self.c,3,set(),**args)
        self.assertEqual([r['nm_id'] for r in todo],list(range(180,230)))
        args['nm_ids']=[100,181,240]
        self.assertEqual([r['nm_id'] for r in jd.pending(self.c,3,set(),**args)],[181,240])
        for nm in (181,240):self.exclude('nm',nm)
        self.assertEqual(jd.pending(self.c,3,set(),**args),[])

    def test_daily_prunes_between_requests_and_save_preserves_old_history(self):
        day=DAY-timedelta(days=1)
        self.assertEqual(jd.save(self.c,3,day,{10:{'old':V},11:{'old':V}},100,{10:0,11:0}),2)
        def reply(*args,**kwargs):
            nms=kwargs['body']['nmIds']
            if wb.call.call_count==1:
                self.assertEqual(nms,[10,11]);self.exclude('nm',10)
            else:self.assertEqual(nms,[11])
            return {'data':{'items':[response(nm=nm,q='new')['data']['items'][0] for nm in nms]}}
        wb=Mock();wb.call.side_effect=reply
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            data,limit,conflicts=jd.fetch(self.c,wb,3,[10,11],day)
        self.assertEqual(wb.call.call_count,3);self.assertEqual(set(data),{11})
                                                              
        self.exclude('nm',11)
        self.assertEqual(jd.save(self.c,3,day,data,limit,conflicts),0)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_daily').fetchone()['n'],2)
        self.assertEqual(self.c.execute('SELECT query FROM jam_queries').fetchall(),[{'query':'old'}])

    def test_tariff_retry_rechecks_selection_and_sends_no_empty_request(self):
        wb=Mock()
        def reply(*args,**kwargs):
            self.exclude('nm',10)
            raise WBError('HTTP 400 texts limit')
        wb.call.side_effect=reply
        with patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            self.assertEqual(jd.fetch(self.c,wb,3,[10],DAY),({},30,{}))
        self.assertEqual(wb.call.call_count,1)
        wb.reset_mock()
        with patch.object(jam,'access',return_value=None):
            self.assertEqual(jd.fetch(self.c,wb,3,[10,20],DAY),({},100,{}))
        wb.call.assert_not_called()

    def test_ordinary_stops_after_first_response_if_sku_disabled(self):
        wb=Mock()
        def reply(*args,**kwargs):
            self.exclude('nm',10)
            return response()
        wb.call.side_effect=reply
        with patch('stometric.wb.WB',return_value=wb),patch.object(jam,'access',return_value=None),patch.object(jam,'_set_access'):
            with self.assertRaises(scope.NotInWork):jam.fetch(self.c,3,10,DAY,DAY)
        self.assertEqual(wb.call.call_count,1)

    def test_ordinary_in_work_background_saves_complete_response(self):
        self.c.execute("INSERT INTO jam_cache VALUES(3,10,%s,%s,'running',NULL,NULL,now(),NULL)",(DAY,DAY))
        wb=Mock();wb.call.return_value=response()
        with (patch.object(db,'connect',return_value=nullcontext(self.c)),
              patch('stometric.wb.WB',return_value=wb),patch.object(jam,'access',return_value=None),
              patch.object(jam,'_set_access')):
            jam._run(3,10,DAY,DAY)
        row=self.c.execute('SELECT state,items FROM jam_cache').fetchone()
        self.assertEqual(row['state'],'done');self.assertEqual(row['items'][0]['orders'],5)
        self.assertEqual(wb.call.call_count,2)

    def test_picker_and_shortcuts_respect_selection_without_removing_history(self):
        self.exclude('nm',10)
        self.c.execute('INSERT INTO agg_nm_day VALUES(3,10,%s,%s::jsonb),(3,11,%s,%s::jsonb)',
                       (DAY,'{"f_orders":100}',DAY,'{"f_orders":2}'))
        self.c.execute("INSERT INTO jam_cache SELECT 3,n,%s,%s,'done','[]',now(),now(),NULL FROM unnest(ARRAY[10,11]) n",(DAY,DAY))
        f={'date_from':DAY,'date_to':DAY}
        self.assertEqual(jt._pick_nm(self.c,3,f)[0],11)
        self.assertEqual(jt._pick_nm(self.c,3,{**f,'nm_ids':[10,20,11]})[0],11)
        self.assertIsNone(jt._pick_nm(self.c,3,{**f,'nm_ids':[10,20]})[0])
        self.assertEqual([r['nm_id'] for r in jt._loaded(self.c,3)],[11])
        self.assertEqual(self.c.execute('SELECT count(*) n FROM jam_cache').fetchone()['n'],2)

    def test_morning_filters_before_top_limit_and_skips_late_exclusion(self):
        self.c.raw("""INSERT INTO nomenclature(account_id,nm_id,brand)
            SELECT 3,n,CASE WHEN n<120 THEN 'Closed' ELSE 'Open' END FROM generate_series(100,140) n;
            INSERT INTO agg_nm_day SELECT 3,n,current_date,jsonb_build_object('f_orders',1000-n)
              FROM generate_series(100,140) n;""")
        self.exclude('brand','Closed')
        def result(c,shop,nm,a,b):
            if nm==120:self.exclude('nm',120)
            return []
        with patch.object(jam,'access',return_value={'status':'ok'}),patch.object(jam,'fetch',side_effect=result) as fetch:
            tabcache._jam_prefetch(self.c,3,lambda _:None)
        self.assertEqual([call.args[2] for call in fetch.call_args_list],list(range(120,135)))
        rows=self.c.execute('SELECT nm_id FROM jam_cache ORDER BY nm_id').fetchall()
        self.assertEqual([r['nm_id'] for r in rows],list(range(121,135)))

    def test_news_is_idempotent(self):
        news=(ROOT/'stometric/migrations/144_jam_work_selection_news.sql').read_text()
        self.c.raw(news);self.c.raw(news)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)


if __name__=='__main__':unittest.main()

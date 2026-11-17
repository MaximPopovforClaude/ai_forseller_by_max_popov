"""Seven-feature batch: real SQL fixtures and failure/access boundaries; no live APIs."""
import stometric.web as web
import io
from contextlib import nullcontext
import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from uuid import uuid4
from fastapi import HTTPException
from stometric import staff, rnp, spp_table, photos, photo_entry, kb_slides, query_heatmap, api_manager, tabcache
from tools.test_calendar import Standalone, Cursor

D=date(2026,11,17)


class Rules(unittest.TestCase):
    def test_manager_canonical_invalid_and_empty(self):
        self.assertEqual(staff.selected_ids('3, 1,3'),[1,3])
        self.assertEqual(staff.selected_ids(None),[])
        self.assertEqual(staff.selected_ids(7),[7])
        for value in ['1,x','0','-1','1,,2',str(2**40),','.join(['1']*201)]:
            with self.subTest(value=value),self.assertRaises(HTTPException):staff.selected_ids(value)

    def test_manager_intersection_never_expands_empty(self):
        with patch.object(staff,'nms',return_value=[11,12,13]):
            self.assertEqual(staff.narrow(None,1,'1,2',[12,14]),[12])
            self.assertEqual(staff.narrow(None,1,'1,2',[]),[0])
            self.assertEqual(staff.narrow(None,1,'1,2',[99]),[0])
            self.assertEqual(staff.narrow(None,1,'1,2',None),[11,12,13])

    def test_calendar_weeks_monday_sunday_year_boundary(self):
        for end in [D,date(2026,11,16),date(2026,11,22),date(2027,1,1),date(2026,3,1)]:
            weeks=rnp.calendar_weeks(end)
            self.assertEqual(weeks[-1][1],end)
            self.assertTrue(all(a.weekday()==0 for a,b in weeks))
            self.assertTrue(all(b.weekday()==6 and (b-a).days==6 for a,b in weeks[:2]))
            self.assertEqual((weeks[1][0]-weeks[0][0]).days,7)
            self.assertEqual((weeks[2][0]-weeks[1][0]).days,7)

    def test_months_exclude_predictions_future_preserve_unknown_zero(self):
        result={'data':{'dynamic':[{'date':'2026-09-01','frequency':None},{'date':'2026-10-01','frequency':0},
          {'date':'2026-11-01','frequency':12},{'date':'2026-12-01','frequency':999},{'date':'2026-08-01','frequency':8,'predicted':True}]}}
        self.assertEqual(query_heatmap.monthly_rows(result,D),[(date(2026,9,1),None),(date(2026,10,1),0),(date(2026,11,1),12)])
        for result in [{},{'data':{'dynamic':{}}},{'data':{'dynamic':[{'date':'2026-10-01','frequency':-1}]}},
                       {'data':{'dynamic':[{'date':'2026-10-01','frequency':'NaN'}]}}]:
            with self.assertRaises(ValueError):query_heatmap.monthly_rows(result,D)

    def test_month_duplicate_conflict_not_summed(self):
        with self.assertRaises(ValueError):query_heatmap.monthly_rows({'data':{'dynamic':[
            {'date':'2026-10-01','frequency':1},{'date':'2026-10-15','frequency':2}]}},D)

    def test_kb_links_exact_wb_only(self):
        self.assertEqual(kb_slides.card_nm('https://www.wildberries.ru/catalog/123/detail.aspx?target=1'),123)
        for url in ['https://wildberries.ru.evil/catalog/123/detail.aspx','http://127.0.0.1/catalog/123/detail.aspx',
                    'https://wildberries.ru@evil/catalog/123/detail.aspx','https://wildberries.ru:443/catalog/123/detail.aspx',
                    'javascript:alert(1)','https://wildberries.ru/catalog/-1/detail.aspx']:
            self.assertIsNone(kb_slides.card_nm(url))

    def test_kb_and_heatmap_access_before_read_or_start(self):
        c=Mock()
        with patch.object(kb_slides.kb,'get',return_value={'url':'https://www.wildberries.ru/catalog/123/detail.aspx','kind':'link'}),patch.object(kb_slides.kb,'can_see',return_value=False):
            with self.assertRaises(HTTPException):kb_slides.read(c,{'id':1},1)
        c.execute.assert_not_called()
        with patch.object(query_heatmap.auth,'shop_role',return_value=None):
            with self.assertRaises(HTTPException):query_heatmap.read(c,{'id':1},2,123)
        c.execute.assert_not_called()

    def test_bad_photo_head_does_not_create_empty_snapshot(self):
        c=Mock();c.execute.return_value.fetchone.return_value=None
        for error in [TimeoutError(),HTTPError('test',403,'x',{},None),HTTPError('test',404,'x',{},None)]:
            c.reset_mock()
            with patch.object(photos,'_basket_url',return_value='https://basket-01.wbbasket.ru/1.webp'),patch.object(photos,'_req',side_effect=error):
                with self.assertRaises(type(error)):photos._snapshot(c,123,'own')
            self.assertFalse(any('INSERT' in x.args[0] for x in c.execute.call_args_list))

    def test_interrupted_second_slide_does_not_create_false_removal(self):
        c=Mock();c.execute.return_value.fetchone.return_value={'id':1,'sig':'original','slots':[{'i':1,'hash':'a','phash':0,'etag':'A'},{'i':2,'hash':'b','phash':1,'etag':'B'}]}
        response=Mock();response.__enter__=Mock(return_value=Mock(headers={'ETag':'A'}));response.__exit__=Mock()
        with patch.object(photos,'_basket_url',return_value='https://basket-01.wbbasket.ru/1.webp'),patch.object(photos,'_req',side_effect=[response,TimeoutError()]):
            with self.assertRaises(TimeoutError):photos._snapshot(c,123,'own')
        self.assertFalse(any('INSERT' in x.args[0] for x in c.execute.call_args_list))

    def test_new_photo_kpi_ratio_and_current_day_excluded(self):
        c=Mock();c.execute.return_value=[{'day':date(2026,11,16),'item_rows':1,'complete':True,'views':800,'clicks':100,'carts':10,'orders':1}]
        snaps=[{'id':1,'taken_at':datetime(2026,11,16,tzinfo=timezone.utc)}]
        value=photo_entry.periods(c,1,11,snaps,today=D)[1]
        self.assertEqual(value['conv_view_order'],.00125)
        self.assertEqual(value['to'],date(2026,11,16))
        c.execute.return_value[0]['orders']=0
        self.assertEqual(photo_entry.periods(c,1,11,snaps,today=D)[1]['conv_view_order'],0)
        c.execute.return_value[0]['views']=0
        self.assertIsNone(photo_entry.periods(c,1,11,snaps,today=D)[1]['conv_view_order'])

    def test_new_api_no_cross_shop_permission_bypass(self):
        c=Mock()
        with patch.object(query_heatmap,'authorize',side_effect=HTTPException(403,'no')):
            with self.assertRaises(HTTPException):api_manager.heatmap_read(2,12,u={'id':1},c=c)
        c.execute.assert_not_called()

    def test_entry_routes_apply_manager_union_and_explicit_intersection(self):
        from stometric import entry, entry_views
        with patch.object(api_manager,'_role'), patch.object(staff,'nms',return_value=[11,12,13]), \
             patch.object(entry,'view',return_value={}) as view, patch.object(entry_views,'build',return_value={}) as build, \
             patch.object(web.auth,'shop_role',return_value='viewer'):
            api_manager.entry_get(1,nm_ids='12,99',staff='1,2',u={'id':1},c=Mock())
            self.assertEqual(view.call_args.args[2],[12])
            api_manager.entry_views_get(1,nm_ids='',staff='1,2',u={'id':1},c=Mock())
            self.assertEqual(build.call_args.args[2],[11,12,13])

    def test_active_user_revocation_checked_before_background_access(self):
        for row in [None,{'id':1,'is_active':False,'is_superadmin':False}]:
            c=Mock();c.execute.return_value.fetchone.return_value=row
            with self.assertRaises(HTTPException):query_heatmap.active_user(c,{'id':1,'is_active':True},)

    def test_daily_photos_covers_beyond_old_top400_and_excludes(self):
        c=Mock()
        def execute(q,args=()):
            if 'pg_try_advisory_lock' in q:return Cursor([{'ok':True}])
            if 'FROM accounts' in q:return Cursor([{'id':1}])
            if 'FROM nomenclature' in q:return Cursor([{'nm_id':n} for n in range(1,406)])
            if 'FROM photo_checks' in q:return Cursor([])
            if 'FROM competitors' in q:return Cursor([{'comp_nm_id':800}])
            return Cursor([])
        c.execute.side_effect=execute
        with patch('stometric.db.connect',return_value=nullcontext(c)), patch('stometric.exclusions.excluded',return_value={405}), \
             patch.object(photos,'snapshot',return_value={'changed':False}) as snap:
            result=photos.daily()
        self.assertEqual(result['own'],404);self.assertEqual(result['competitors'],1)
        self.assertIn(404,[x.args[1] for x in snap.call_args_list]);self.assertNotIn(405,[x.args[1] for x in snap.call_args_list])


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='platform-batch-pg-');cls.cluster=Path(cls.tmp.name)/'db'
        result=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','batch_test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if result.returncode:raise AssertionError(result.stderr)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        schema='case_'+uuid4().hex;self.c=Standalone(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema}; SET search_path={schema};'+'''
          CREATE TABLE workspaces(id int PRIMARY KEY);
          CREATE TABLE accounts(id int PRIMARY KEY,workspace_id int,marketplace text);
          CREATE TABLE kb_items(id int PRIMARY KEY);
          CREATE TABLE service_news(title text,body text,tabs text[]);
          CREATE TABLE staff_articles(account_id int,nm_id bigint,staff_id int);
          CREATE TABLE nomenclature(account_id int,nm_id bigint,subject text);
          CREATE TABLE orders(account_id int,nm_id bigint,order_dt timestamp,price_with_disc numeric,finished_price numeric,data jsonb);
          INSERT INTO workspaces VALUES(1),(2);
          INSERT INTO accounts VALUES(1,1,'wb'),(2,2,'wb');
          INSERT INTO staff_articles VALUES(1,11,1),(1,12,2),(1,13,3),(2,99,1);
          INSERT INTO nomenclature VALUES(1,11,'Candles'),(1,12,'Candles'),(1,13,'Syrup'),(2,99,'Candles');
          INSERT INTO orders VALUES
           (1,11,'2026-11-16 23:59',100,80,'{}'),(1,12,'2026-11-16 23:00',300,180,'{}'),
           (1,11,'2026-11-17 00:01',100,100,'{}'),(1,13,'2026-11-17 00:01',500,300,'{}'),
           (2,99,'2026-11-16 23:00',9999,1,'{}'),(1,11,'2026-11-18 00:00',9999,1,'{}');
        ''')
        self.f={'date_from':date(2026,11,16),'date_to':D,'nm_ids':None}
    def test_manager_union_scoped_sql(self):
        self.assertEqual(staff.nms(self.c,1,'1,2,1'),[11,12])
        self.assertEqual(staff.narrow(self.c,1,'1,2',[12,99]),[12])
        self.assertEqual(staff.narrow(self.c,1,'99',None),[0])
    def test_spp_weighted_daily_hourly_and_filter(self):
        data=spp_table.table(self.c,1,self.f)
        candles=next(x for x in data['rows'] if x['subject']=='Candles')
        self.assertEqual(candles['orders'],3);self.assertAlmostEqual(candles['p1'],.35)
        self.assertAlmostEqual(candles['p0'],0);self.assertAlmostEqual(candles['spp'],.28)
        hour=spp_table.table(self.c,1,self.f,hourly=True)
        row=next(x for x in hour['rows'] if x['subject']=='Candles' and x['day']=='2026-11-16')
        self.assertAlmostEqual(row['p23'],.35);self.assertIsNone(row['p0'])
        filtered=spp_table.table(self.c,1,{**self.f,'nm_ids':staff.nms(self.c,1,'1')})
        self.assertEqual(len(filtered['rows']),1);self.assertAlmostEqual(filtered['rows'][0]['p1'],.2)
        self.assertEqual(spp_table.table(self.c,1,{**self.f,'nm_ids':[0]})['rows'],[])
    def test_spp_missing_price_not_partial_number(self):
        self.c.raw("INSERT INTO orders VALUES(1,11,'2026-11-16 23:45',100,NULL,'{}');")
        row=next(x for x in spp_table.table(self.c,1,self.f)['rows'] if x['subject']=='Candles')
        self.assertIsNone(row['p1']);self.assertIsNone(row['spp']);self.assertEqual(row['p0'],0)
    def test_migrations_repeat_without_data_loss_news_once(self):
        sql=Path('stometric/migrations/157_platform_batch.sql').read_text();news=Path('stometric/migrations/158_platform_batch_news.sql').read_text()
        self.c.raw(sql);self.c.raw(news)
        self.c.raw("INSERT INTO query_months(workspace_id,query,month,frequency) VALUES(1,'q','2026-10-01',12),(2,'q','2026-10-01',999);")
        self.c.raw(sql);self.c.raw(news)
        self.assertEqual(len(self.c.execute('SELECT * FROM service_news').fetchall()),0)
        self.assertEqual(len(self.c.execute('SELECT * FROM query_months').fetchall()),2)
    def test_heatmap_read_workspace_isolation_and_missing_month(self):
        self.c.raw(Path('stometric/migrations/157_platform_batch.sql').read_text())
        self.c.raw('''INSERT INTO query_heatmap(account_id,nm_id,data,status) VALUES(1,11,'{"queries":["q","empty"],"completed":1}','ready');
          INSERT INTO query_months(workspace_id,query,month,frequency) VALUES(1,'q','2026-10-01',12),(2,'q','2026-09-01',999);''')
        with patch.object(query_heatmap,'authorize',return_value=1):r=query_heatmap.read(self.c,{'id':1},1,11)
        self.assertEqual(r['months'],['2026-10-01']);self.assertEqual(r['rows'][0]['values'],{'2026-10-01':12})
        self.assertEqual(r['rows'][1]['values'],{})

    def test_heatmap_worker_keeps_successful_months_on_later_source_error(self):
        self.c.raw(Path('stometric/migrations/157_platform_batch.sql').read_text())
        self.c.raw("INSERT INTO query_heatmap(account_id,nm_id,status,run_key) VALUES(1,11,'queued','run');")
        source=[{'rows':[{'keyword':{'name':'one'}},{'keyword':{'name':'two'}}]},
                {'data':{'dynamic':[{'date':'2026-10-01','frequency':123}]}}, TimeoutError('synthetic')]
        with patch.object(query_heatmap.db,'connect',return_value=nullcontext(self.c)), \
             patch.object(query_heatmap,'active_user',return_value={'id':1}),patch.object(query_heatmap,'authorize',return_value=1), \
             patch.object(query_heatmap.auth,'shop_role',return_value='editor'),patch.object(query_heatmap.market,'ws_token',return_value='synthetic'), \
             patch.object(query_heatmap.market,'_call',side_effect=source) as call,patch.object(query_heatmap,'_SLOTS'):
            query_heatmap._refresh({'id':1},1,11,'run')
        row=self.c.execute('SELECT status,data FROM query_heatmap').fetchone()
        self.assertEqual(row['status'],'failed');self.assertEqual(row['data']['completed'],1)
        month=self.c.execute('SELECT query,frequency FROM query_months').fetchone()
        self.assertEqual(month,{'query':'one','frequency':123});self.assertEqual(call.call_count,3)

    def test_superseded_queued_heatmap_does_not_call_provider(self):
        self.c.raw(Path('stometric/migrations/157_platform_batch.sql').read_text())
        self.c.raw("INSERT INTO query_heatmap(account_id,nm_id,status,run_key) VALUES(1,11,'queued','new');")
        with patch.object(query_heatmap.db,'connect',return_value=nullcontext(self.c)),patch.object(query_heatmap,'active_user') as actor, \
             patch.object(query_heatmap.market,'_call') as call,patch.object(query_heatmap,'_SLOTS'):
            query_heatmap._refresh({'id':1},1,11,'old')
        actor.assert_not_called();call.assert_not_called()
        self.assertEqual(self.c.execute('SELECT status FROM query_heatmap').fetchone()['status'],'queued')

    def test_kb_failed_capture_keeps_old_gallery(self):
        self.c.raw(Path('stometric/migrations/157_platform_batch.sql').read_text())
        self.c.raw("""INSERT INTO kb_items VALUES(1); INSERT INTO kb_card_slides(item_id,nm_id,status,hashes,run_key) VALUES(1,11,'queued','[\"saved\"]','run');""")
        with patch.object(kb_slides.db,'connect',return_value=nullcontext(self.c)),patch.object(kb_slides,'active_user',return_value={'id':1}), \
             patch.object(kb_slides,'item',return_value=({},11)),patch.object(kb_slides.photos,'_basket_url',return_value='https://example.test/1.webp'), \
             patch.object(kb_slides.photos,'_req',side_effect=TimeoutError('synthetic')),patch.object(kb_slides,'_SLOTS'):
            kb_slides._capture({'id':1},1,11,'run',True)
        row=self.c.execute('SELECT status,hashes FROM kb_card_slides').fetchone()
        self.assertEqual(row,{'status':'failed','hashes':['saved']})


if __name__=='__main__':unittest.main()

"""Single-SKU day overlay: permissions, real SQL scope/parity, frozen demo and React races."""
import stometric.web
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from fastapi import HTTPException
from stometric import manager, api_manager as api, action_ads
from tools.test_calendar import Standalone, Cursor

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 11, 12)


class Rules(unittest.TestCase):
    def test_permission_before_reads(self):
        c = Mock()
        with patch.object(api.auth, 'shop_role', return_value=None), patch.object(manager, 'day_cells') as get:
            with self.assertRaises(HTTPException) as e:
                api.day_cells(7, 100, DAY, DAY, True, u={'id': 99}, c=c)
            self.assertEqual(e.exception.status_code, 403)
            c.execute.assert_not_called(); get.assert_not_called()

    def test_bound_and_ownership_before_projection(self):
        c = Mock(); c.execute.return_value.fetchone.return_value = None
        with patch.object(api, '_role'), patch.object(manager, 'day_cells') as get:
            for nm, start, end in [(0,DAY,DAY), (100,date.min,date.min), (-1,DAY,DAY), (2**53,DAY,DAY), (100,DAY,DAY-timedelta(days=1)), (100,DAY-timedelta(days=60),DAY)]:
                with self.assertRaises(HTTPException) as e:
                    api.day_cells(7,nm,start,end,u={'id':99},c=c)
                self.assertEqual(e.exception.status_code,422)
            c.execute.assert_not_called()
            with self.assertRaises(HTTPException) as e:
                api.day_cells(7,100,DAY,DAY,u={'id':99},c=c)
            self.assertEqual(e.exception.status_code,404);get.assert_not_called()
            query, params = c.execute.call_args.args
            self.assertIn("a.marketplace='wb'",query);self.assertEqual(params,(7,100))


    def test_react_selection_dates_parity_and_late_responses(self):
        for mode in ('development','production'):
            p=subprocess.run(['node',str(ROOT/'tools/frontend/entry_actions.cjs'),str(ROOT)],
                env={**os.environ,'NODE_ENV':mode},capture_output=True,text=True,timeout=40)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)


class Sql(unittest.TestCase):
    def test_real_queries_match_board_and_isolate_shop_sku_days(self):
        with tempfile.TemporaryDirectory(prefix='entry-actions-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True)
            class Db(Standalone):
                def execute(self,q,p=()):
                    result=super().execute(q,p)
                    for row in result.rows:
                        if isinstance(row.get('d'),str): row['d']=date.fromisoformat(row['d'])
                    return result
            c=Db(cluster,'entry_test')
            c.raw('''CREATE SCHEMA entry_test; SET search_path=entry_test;
                CREATE TABLE accounts(id int PRIMARY KEY,marketplace text);
                INSERT INTO accounts VALUES(7,'wb'),(8,'wb'),(9,'ozon');
                CREATE TABLE nomenclature(account_id int,nm_id bigint);
                INSERT INTO nomenclature VALUES(7,100),(7,101),(8,100),(9,100);
                CREATE TABLE users(id int,name text,email text);
                INSERT INTO users VALUES(99,'Tester','test@example.org');
                CREATE TABLE nm_actions(id int,account_id int,nm_id bigint,day date,kind text,value text,note text,user_id int,created_at timestamptz);
                CREATE TABLE card_changes(id int,account_id int,nm_id bigint,detected_at timestamptz,kind text,field text,old_value jsonb,new_value jsonb,wb_updated_at timestamptz);
                CREATE TABLE wb_promo_days(account_id int,nm_id bigint,day date,promos text[]);
                CREATE TABLE entry_alerts(account_id int,nm_id bigint,day date,section text,point text,clicks numeric,clicks_avg numeric,change_pct numeric);
                CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
                CREATE TABLE agg_state(account_id int,name text,covered_from date,covered_to date);
                INSERT INTO agg_state VALUES(7,'nm_day','2026-11-01','2026-11-30'),(8,'nm_day','2026-11-01','2026-11-30');
                CREATE TABLE raw_rows(account_id int,source text,row_date date,data jsonb);
                CREATE TABLE wb_ad_kw_daily(account_id int,advert_id bigint,nm_id bigint,day date,spend numeric);
                CREATE TABLE service_news(title text,body text,tabs text[]);
            ''')
            for name in ('148_actions_ad_metrics.sql','149_entry_actions_news.sql'):
                sql=(ROOT/'stometric/migrations'/name).read_text();c.raw(sql);c.raw(sql)
            self.assertEqual(c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
            for shop,nm,money in [(7,100,200),(7,101,8888),(8,100,9999)]:
                c.execute('INSERT INTO agg_nm_day VALUES(%s,%s,%s,%s::jsonb)',(shop,nm,DAY,json.dumps({'orders':2,'orders_sum':1000,'orders_sum_spp':money,'f_orders':5})))
                for day in (DAY,DAY-timedelta(days=1),DAY+timedelta(days=1)):
                    c.execute('INSERT INTO nm_actions VALUES(1,%s,%s,%s,\'ads_on\',\'test\',\'note\',99,%s)',(shop,nm,day,str(day)+'T12:34:00Z'))
                c.execute("INSERT INTO card_changes VALUES(2,%s,%s,'2026-11-11T22:00:00Z','photo','photos','[]','[1]',NULL)",(shop,nm))
                c.execute('INSERT INTO wb_promo_days VALUES(%s,%s,%s,ARRAY[\'Test promo\'])',(shop,nm,DAY))
                c.execute("INSERT INTO entry_alerts VALUES(%s,%s,%s,'Search','Demo',10,2,400)",(shop,nm,DAY))
                data={'advertId':42,'sum':200,'apps':[{'nms':[{'nmId':nm,'sum':20}]}]}
                c.execute('INSERT INTO raw_rows VALUES(%s,\'ad_stats\',%s,%s::jsonb)',(shop,DAY,json.dumps(data)))
            c.execute("INSERT INTO raw_rows VALUES(7,'adverts',%s,%s::jsonb)",(DAY,json.dumps({'advertId':42,'info':{'bid_type':'manual','settings':{'placements':{'search':True,'recommendations':False}}}})))
            all_days=manager.day_cells(c,7,DAY,DAY,metric_nms=[100,101],ads=True,prices=True,ad_metrics=True)
            chosen=manager.day_cells(c,7,DAY,DAY,nms=[100],ads=True,prices=True,ad_metrics=True)
            self.assertEqual(set(chosen),{100});self.assertEqual(chosen[100],all_days[100])
            row=chosen[100];self.assertEqual(row['orders'],{str(DAY):5})
            self.assertEqual(row['price_spp_days'],{str(DAY):100})
            self.assertEqual(row['ads'][str(DAY)],{'all':20,'ark':0,'prk':20,'search':20,'rec':0,'osum':1000})
            self.assertEqual(row['ad_metrics'][str(DAY)]['all']['spent'],20)
            self.assertEqual(set(row['actions']),{str(DAY)});self.assertEqual(len(row['actions'][str(DAY)]),4)
            self.assertEqual(datetime.fromisoformat(row['actions'][str(DAY)][1]['detected_at']).astimezone(timezone.utc).hour,22)
            with patch.object(api,'_role'):
                response=api.day_cells(7,100,DAY,DAY,True,u={'id':99},c=c)
                self.assertEqual(response['days'],[str(DAY)]);self.assertEqual(response['rows'][0]['orders'],row['orders'])
                with self.assertRaises(HTTPException):api.day_cells(9,100,DAY,DAY,u={'id':99},c=c)
            empty=manager.day_cells(c,7,DAY+timedelta(days=2),DAY+timedelta(days=2),nms=[100],ads=True,prices=True,ad_metrics=True)[100]
            self.assertEqual(empty,{'orders':{},'actions':{},'price_spp_days':{},'ads':{},'ad_metrics':{}})


if __name__ == '__main__': unittest.main()

"""Daily WB price and action visibility; only synthetic data and isolated PostgreSQL."""
import stometric.web
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import HTTPException
from tools.test_calendar import Standalone, Cursor
from stometric import manager, api_manager, action_charts, wb_demand, manager_oz

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 11, 13)


class Display(unittest.TestCase):
    def test_real_react_display_and_existing_board_flows(self):
        for mode in ('development', 'production'):
            p = subprocess.run(['node', str(ROOT/'tools/frontend/workspace_batch.cjs'), str(ROOT)],
                env={**os.environ, 'NODE_ENV':mode}, text=True, capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_permission_before_optional_price_reads_and_api_flags(self):
        c = Mock(); u = {'id':99}
        with patch.object(api_manager.auth,'shop_role',return_value=None), patch.object(manager,'board') as get:
            with self.assertRaises(HTTPException): api_manager.board(7,prices=True,u=u,c=c)
            get.assert_not_called(); c.execute.assert_not_called()
        with patch.object(api_manager,'_role'), patch.object(api_manager.auth,'shop_role',return_value='viewer'), \
             patch.object(manager,'board',return_value={'rows':[]}) as get:
            result = api_manager.board(7,days=99,date_to=DAY,ads=True,prices=True,u=u,c=c)
            get.assert_called_once_with(c,7,60,DAY,True,True,ad_metrics=False)
            self.assertFalse(result['can_edit'])

    def test_prices_opt_in_and_drr_not_overwritten_by_last_week_spend(self):
        class Db:
            def execute(self,q,p=()):
                if 'sum((data' in q:
                    return Cursor([{'nm_id':1,'ads':0,'osum':1000,'bsum':500},
                                   {'nm_id':2,'ads':100,'osum':1000,'bsum':500}])
                if "(data->>'orders_sum')::numeric s" in q:
                    return Cursor([{'nm_id':1,'day':DAY,'s':500}])
                return Cursor([])
        c=Db()
        units={n:{'vendor_code':str(n),'title':'Test','subject':'Test','photo':None} for n in (1,2)}
        with patch.object(manager,'_ozon',return_value=False), patch.object(manager,'other_pct',return_value=0), \
             patch.object(manager,'today_msk',return_value=DAY), patch.object(manager,'_unit_inputs',return_value=units), \
             patch.object(manager,'unit_calc',return_value={'online':100,'margin_online_pct':.2}), \
             patch.object(manager,'showcase',return_value={}), patch.object(manager,'stocks',return_value={}), \
             patch.object(wb_demand,'daily',return_value={}), patch.object(wb_demand,'summary',return_value={}), \
             patch.object(manager,'ad_split',return_value={1:{str(DAY):{'all':10}}}) as ad, \
             patch.object(action_charts,'daily_prices',return_value={1:{str(DAY):80}}) as prices:
            a=manager.board(c,7,14,DAY)
            prices.assert_not_called(); ad.assert_not_called()
            for row in a['rows']:
                self.assertNotIn('price_spp_days',row); self.assertNotIn('ads',row)
            b=manager.board(c,7,14,DAY,ads=True,prices=True)
            prices.assert_called_once_with(c,7,date(2026,10,31),DAY)
            by={r['nm_id']:r for r in b['rows']}
            self.assertEqual(by[1]['price_spp_days'],{str(DAY):80})
            self.assertEqual(by[2]['price_spp_days'],{})
            self.assertEqual(by[1]['ads'][str(DAY)]['all'],10,'zero week spend must not disable daily ads')
            self.assertEqual(by[2]['drr_orders'],.1)
            self.assertEqual(by[2]['drr_buyouts'],.2)

    def test_ozon_keeps_its_source(self):
        with patch.object(manager,'_ozon',return_value=True), patch.object(manager_oz,'board',return_value={'mp':'ozon'}) as oz, \
             patch.object(action_charts,'daily_prices') as prices:
            self.assertEqual(manager.board(Mock(),7,14,DAY,prices=True),{'mp':'ozon'})
            oz.assert_called_once(); prices.assert_not_called()


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='actions-display-')
        cls.cluster=Path(cls.tmp.name)/'pg'
        p=subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
        if p.returncode: raise AssertionError(p.stderr)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        self.c=Standalone(self.cluster,'case_'+uuid4().hex)
        self.c.raw(f'CREATE SCHEMA {self.c.schema}; SET search_path={self.c.schema};'+'''
            CREATE TABLE agg_state(account_id int,name text,covered_from date,covered_to date);
            CREATE TABLE agg_nm_day(account_id int,nm_id bigint,day date,data jsonb);
            CREATE TABLE service_news(title text,body text,tabs text[]);
            INSERT INTO agg_state VALUES(7,'nm_day','2026-11-01','2026-11-13'),
                (8,'nm_day','2026-11-01','2026-11-13');
        ''')

    def test_real_daily_projection_matches_charts_boundaries_gaps_and_shop(self):
        cases=[(7,1,'2026-11-12',{'orders':3,'orders_sum_spp':2593.47,'f_orders':99}),
               (7,1,'2026-11-13',{'orders':0,'orders_sum_spp':0}),
               (7,2,'2026-11-12',{'orders':2}),
               (7,2,'2026-11-13',{'orders':2,'orders_sum_spp':0}),
               (7,1,'2026-11-14',{'orders':1,'orders_sum_spp':500}),
               (7,1,'2026-10-31',{'orders':1,'orders_sum_spp':600}),
               (8,1,'2026-11-12',{'orders':1,'orders_sum_spp':9999})]
        for shop,nm,day,data in cases:
            self.c.execute('INSERT INTO agg_nm_day VALUES(%s,%s,%s,%s::jsonb)',(shop,nm,day,json.dumps(data)))
        result=action_charts.daily_prices(self.c,7,date(2026,10,31),date(2026,11,14))
        self.assertEqual(result,{1:{'2026-11-12':864.49,'2026-11-13':None},2:{'2026-11-12':None,'2026-11-13':0}})
        tax={'regime':'Другая СНО','rate':0,'vat':0,'vat_wb':0}
        chart=action_charts.values({DAY:cases[0][3]},[DAY],.8,tax)
        self.assertEqual(chart['price_spp'],[result[1]['2026-11-12']])
        self.assertEqual(action_charts.daily_prices(self.c,9,date(2026,11,1),DAY),{})
        self.assertEqual(action_charts.daily_prices(self.c,7,DAY,DAY),{1:{str(DAY):None},2:{str(DAY):0}})

    def test_news_idempotent(self):
        sql=(ROOT/'stometric/migrations/138_actions_display_news.sql').read_text()
        self.c.raw(sql); self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)


if __name__=='__main__': unittest.main()

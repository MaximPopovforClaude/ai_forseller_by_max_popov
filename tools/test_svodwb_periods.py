"""Summary calendar, personal presets, tax and actual export paths; synthetic data only."""
import stometric.web as web
import asyncio
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import httpx
from openpyxl import load_workbook
from fastapi import HTTPException
from stometric import svodwb_presets, tabcache, gdrive
from stometric.sheets import svodwb as sw
from stometric.tabs import basic
from stometric.agg import nm_day, buyout
from tools.test_audit_report_sources import ReportDB, Rows
from tools.test_calendar import Standalone, FIXTURE

ROOT=Path(__file__).resolve().parents[1]
MON=date(2026,11,16)
LAYOUT=[['TAX','Сумма налога','текущая неделя'],['','Прибыль за минусом налога, руб','текущая неделя']]
PRESET={'name':'Неделя','cols':LAYOUT,'hidden':[['','Кол-во выкупов','вчера',2]]}


class DB(ReportDB):
    def execute(self,sql,args=()):
        if 'FROM user_prefs' in sql:return Rows([{'value':{'cols':LAYOUT,'hidden':[]}}])
        if 'FROM accounts' in sql:return Rows([{'t':'Synthetic','workspace_id':1}])
        if 'INSERT INTO audit_log' in sql:return Rows([])
        return super().execute(sql,args)
    def commit(self):pass


class Calendar(unittest.TestCase):
    def setUp(self):
        self.c=DB('УСН доход');self.today=MON
        self.rows=[{'day':MON-timedelta(days=1),'nm_id':1,'profit':9000,'buyouts_sum':90000},
                   {'day':MON,'nm_id':1,'profit':1000,'buyouts_sum':10000},
                   {'day':MON+timedelta(days=1),'nm_id':1,'profit':500,'buyouts_sum':5000}]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.read=self.stack.enter_context(patch.object(nm_day,'iter_cached',side_effect=lambda c,s,a,b,ids:iter(r for r in self.rows if a<=r['day']<=b and (not ids or r['nm_id'] in ids))))
        self.stack.enter_context(patch.object(buyout,'needed',return_value=True))
        self.stack.enter_context(patch.object(buyout,'by_orders',return_value=({},.8)))
        self.stack.enter_context(patch.object(basic,'today_msk',side_effect=lambda:self.today))
    def report(self,ids=None):
        return basic.svodwb(self.c,7,{'date_from':date(2025,1,1),'date_to':date(2025,1,2),'nm_ids':ids,'user_id':1})
    def test_monday_and_today_are_not_previous_week_or_global_filter(self):
        r=self.report([1]);self.assertEqual(r['rows'][0]['m0'],600)
        self.assertIn('16.11',r['columns'][12]['title']);self.assertNotIn('15.11',r['columns'][12]['title'])
        self.today+=timedelta(days=1);r=self.report([1]);self.assertEqual(r['rows'][0]['m0'],900)
        self.assertEqual(r['rows'][0]['m1'],600)
        self.assertIn('16.11–17.11',r['columns'][12]['title'])
        self.assertEqual(self.read.call_args.args[3],self.today)
    def test_calendar_boundaries_and_frozen_legacy_mode(self):
        for day in [MON,MON+timedelta(days=6),date(2027,1,1),date(2027,2,1)]:
            y=day-timedelta(days=1);a,b=sw.period('текущая неделя',y,day)
            self.assertEqual(a.weekday(),0);self.assertEqual(b,day);self.assertLessEqual(a,day)
            self.assertEqual(sw.period('предыдущая неделя',y,day),(a-timedelta(days=7),a-timedelta(days=1)))
            self.assertEqual(sw.period('текущий месяц',y,day),(day.replace(day=1),day))
            self.assertEqual(sw.period('вчера',y,day),(y,y))
        self.assertEqual(sw.period('текущая неделя',MON-timedelta(days=1)),(MON-timedelta(days=7),MON-timedelta(days=1)))
    def test_osno_tax_is_present_and_ip_is_allocated_once_before_filter(self):
        self.c.regime='ОСНО';r=self.report([1]);self.assertEqual(r['rows'][0]['m0'],60)
        self.c.regime='ОСНО ИП (НДФЛ)'
        self.rows=[{'day':MON,'nm_id':i,'profit':2000000,'buyouts_sum':3000000} for i in (1,2)]
        full=self.report();selected=self.report([1])
        taxes={r['nm_id']:r['m0'] for r in full['rows']}
        self.assertAlmostEqual(sum(taxes.values()),552000)
        self.assertEqual(selected['rows'][0]['m0'],taxes[1]);self.assertEqual(len(selected['rows']),1)
        self.assertIsNone(self.read.call_args.args[-1])
    def test_cache_rolls_calendar_and_keeps_personal_layout(self):
        f={'date_from':date(2025,1,1),'date_to':date(2025,1,2),'nm_ids':[1],'user_id':12}
        with patch.object(tabcache,'today_msk',return_value=MON):a=tabcache.tab_params(self.c,'svodwb',7,f)
        with patch.object(tabcache,'today_msk',return_value=MON+timedelta(days=1)):b=tabcache.tab_params(self.c,'svodwb',7,f)
        self.assertNotEqual(tabcache.fkey(a),tabcache.fkey(b));self.assertEqual(a['user_id'],12)
        self.assertNotIn('date_to',a);self.assertEqual(a['nm_ids'],[1])
    def test_unsupported_tax_is_unknown_in_rows_and_total(self):
        self.c.regime='АУСН';report=self.report()
        self.assertTrue(all(r['m0'] is None and r['m1'] is None for r in report['rows']))
        self.assertIsNone(report['total_row']['m0']);self.assertIsNone(report['total_row']['m1'])
    def test_google_export_uses_same_live_calendar_and_numbers_as_screen(self):
        self.today=MON+timedelta(days=1)
        u={'id':1,'email':'owner@example.test'};captured=[];names=[]
        self.stack.enter_context(patch.object(web.auth,'shop_role',return_value='viewer'))
        self.stack.enter_context(patch.object(web,'_cached',side_effect=lambda c,key,s,f:basic.svodwb(c,s,f)))
        self.stack.enter_context(patch('stometric.exclusions.excluded',return_value=set()))
        self.stack.enter_context(patch.object(gdrive,'ready',return_value=True))
        self.stack.enter_context(patch.object(gdrive,'upload',side_effect=lambda c,body,name,*a:captured.append(body) or names.append(name) or {'url':'https://example.test/synthetic'}))
        args=dict(shop_id=7,key='svodwb',date_from=date(2025,1,1),date_to=date(2025,1,2),nm_ids='1',u=u,c=self.c)
        screen=json.loads(web.tab(**args).body)
        web.tab_gsheet(**args)
        ws=load_workbook(io.BytesIO(captured[0]),data_only=True).active
        headers=[c.value for row in ws for c in row if isinstance(c.value,str)]
        self.assertIn(screen['columns'][12]['title'],headers)
        tax_col=next(c.column for row in ws for c in row if c.value==screen['columns'][12]['title'])
        self.assertEqual(ws.cell(3,tax_col).value,screen['rows'][0]['m0'])
        self.assertEqual(ws.cell(3,tax_col).value,900)
        self.assertIn('на 17.11.2026',names[0]);self.assertNotIn('2025',names[0])
        self.assertTrue(any('Сегодня' in s or 'сегодняшний день неполный' in s for s in headers))


class PresetDB(Standalone):
    def execute(self,q,args=()):
        r=super().execute(q,args)
        for row in r.rows:
            if isinstance(row.get('updated_at'),str):row['updated_at']=datetime.fromisoformat(row['updated_at'])
        return r


class Presets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='svodwb-presets-');cls.cluster=Path(cls.tmp.name)/'pg'
        subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        schema='p_'+uuid4().hex;self.c=PresetDB(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema};SET search_path={schema};'+FIXTURE+(ROOT/'stometric/migrations/005_user_prefs.sql').read_text())
        self.u={'id':1,'is_active':True}
    def test_actual_sql_scope_persistence_conflict_and_reset_keeps_presets(self):
        def save(items,revision=None):return web.set_pref(10,'svodwb_presets',web.PrefIn(value={'items':items},revision=revision),u=self.u,c=self.c)
        self.assertEqual(web.get_svodwb_presets(10,u=self.u,c=self.c)['items'],[])
        saved=save([PRESET]);self.assertEqual(web.get_svodwb_presets(10,u=self.u,c=self.c),saved)
        web.set_pref(10,'svodwb_layout',web.PrefIn(value=None),u=self.u,c=self.c)
        self.assertEqual(web.get_svodwb_presets(10,u=self.u,c=self.c),saved)
        with self.assertRaises(HTTPException) as error:save([])
        self.assertEqual(error.exception.status_code,409)
        self.assertEqual(web.get_svodwb_presets(11,u=self.u,c=self.c)['items'],[])
        self.assertEqual(web.get_svodwb_presets(10,u={'id':4},c=self.c)['items'],[])
        with self.assertRaises(HTTPException):web.get_svodwb_presets(20,u=self.u,c=self.c)
        with self.assertRaises(HTTPException):web.set_pref(11,'svodwb_presets',web.PrefIn(value={'items':[PRESET]}),u={'id':2},c=self.c)
        self.assertEqual(save([],saved['revision'])['items'],[])
    def test_preset_validation_rejects_invalid_periods_shapes_and_duplicates(self):
        self.assertEqual(svodwb_presets.normalize({'items':[PRESET]})['items'][0],PRESET)
        invalid=[None,{'items':[PRESET]*2},{'items':[{**PRESET,'cols':[['','Сумма налога','2020-01-01']]}]},
                 {'items':[{**PRESET,'hidden':[['','Сумма налога','вчера',-1]]}]}, {'items':[{'name':'','cols':LAYOUT,'hidden':[]}]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):svodwb_presets.normalize(value)
    def test_service_news_repeat_has_one_item(self):
        self.c.raw(f'SET search_path={self.c.schema};'+(ROOT/'stometric/migrations/060_service_news.sql').read_text())
        news=(ROOT/'stometric/migrations/156_svodwb_presets_news.sql').read_text()
        self.c.raw(f'SET search_path={self.c.schema};'+news+news)
        rows=self.c.execute('SELECT title,tabs FROM service_news').rows
        self.assertEqual(rows, [])


class Frontend(unittest.TestCase):
    def test_editor_scenarios_dev_and_prod(self):
        for mode in ('development','production'):
            r=subprocess.run(['node',str(ROOT/'tools/frontend/svodwb_presets.cjs'),str(ROOT)],env={**os.environ,'NODE_ENV':mode},capture_output=True,text=True,timeout=35)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

if __name__=='__main__':unittest.main()

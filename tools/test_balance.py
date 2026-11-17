"""Balance accounting, isolated PostgreSQL, XLSX and actual React regressions."""
import stometric.web
import asyncio
import httpx
import os
import io
import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from datetime import date,datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from uuid import uuid4
from fastapi import HTTPException
from openpyxl import load_workbook
from stometric import balance as b, balance_sources as src, balance_excel as excel, api_balance as api
from stometric.collectors import stocks
from tools.test_calendar import Standalone,FIXTURE
ROOT=Path(__file__).resolve().parents[1]
DAY=date(2026,11,17)


def assets(rows):return {'kind':'assets','payload':{'rows':rows},'shop_id':None}
def stock(q='2',cost='10',fbs=False):return {'kind':'stock','payload':{'rows':[{'quantity':q,'cost':cost}],'includes_fbs':fbs},'shop_id':None}
def settlement(shop=10,net='15',accrued='25'):
    return {'kind':'settlement','shop_id':shop,'payload':{'rows':[{'before_spp':'100','after_spp':'80','unaccrued_net':net,'accrued':accrued}]}}
def inventory():
    return {'groups':[{'kind':k,'title':k,'complete':True,'values':b.stock_value([{'quantity':D(2),'cost':D(10),'seller':D(20),'buyer':D(15)}])} for k in ('fbo','fbs','to_buyer','from_buyer')]}


class Arithmetic(unittest.TestCase):
    def test_gap_reasons_match_missing_valuation_without_zero_false_alarm(self):
        rows=[{'quantity':2,'cost':None,'seller':None,'buyer':None,'seller_conflict':True},
              {'quantity':None,'cost':10,'seller':20,'buyer':15},
              {'quantity':-1,'cost':10}, {'quantity':0}, {'quantity':1,'cost':0,'seller':0,'buyer':0}]
        values=b.stock_value(rows)
        reasons=[src.row_gaps(r,'wb') for r in rows]
        for k in values:self.assertEqual(sum(k in r for r in reasons),values[k]['missing'])
        self.assertIn('разные цены',reasons[0]['seller']);self.assertIn('выбранную дату',reasons[0]['cost'])
        self.assertIn('витрине WB',reasons[0]['buyer']);self.assertIn('количество',reasons[1]['cost'])
        self.assertEqual(reasons[-1],{});self.assertEqual(reasons[-2],{})
        self.assertIn('ещё не подключён',src.row_gaps(rows[0],'ozon')['buyer'])

    def test_gap_cards_and_fbs_selection_are_independent(self):
        inv=inventory();inv['groups'][1]['values']=b.stock_value([{'quantity':3,'cost':None,'seller':10,'buyer':8}])
        comps=[{'id':1,'shops':[10],'title':'A'}];batches={1:[stock(),assets([]),settlement()]}
        without=b.report_projection([10],{10:inv},comps,batches,True)
        with_fbs=b.report_projection([10],{10:inv},comps,batches,False)
        self.assertEqual(without['gap_details']['inventory_cost'],[])
        self.assertTrue(with_fbs['gap_details']['inventory_cost'])
        self.assertTrue(all(x['kind']=='fbs' for x in with_fbs['gap_details']['inventory_cost']))
        self.assertEqual(with_fbs['gap_details']['liabilities'],[])
        self.assertEqual(with_fbs['inventory_cost'],without['inventory_cost'])

    def test_three_prices_are_alternatives(self):
        inv={10:inventory()};comp=[{'id':1,'shops':[10],'title':'A'}]
        batches={1:[stock(),assets([{'category':'cash','amount':'100'},{'category':'loan','amount':'50'}]),settlement()]}
        r=b.report_projection([10],inv,comp,batches,True)
        self.assertEqual(r['inventory_cost'],60);self.assertEqual(r['assets'],220);self.assertEqual(r['net'],170)
        self.assertEqual(r['alternative'],{'seller':120,'buyer':90});self.assertEqual(r['gaps'],[])
        self.assertEqual(r['stock_totals'][10]['quantity']['total'],6)
        self.assertEqual(r['stock_totals'][10]['cost']['total'],60)
    def test_company_common_assets_counted_once(self):
        comp=[{'id':1,'shops':[10,11],'title':'A'}];bs={1:[stock(fbs=True),assets([{'category':'cash','amount':'100'}]),settlement(),settlement(11)]}
        full=b.report_projection([10,11],{10:inventory(),11:inventory()},comp,bs,False)
        self.assertEqual(full['seller_stock_cost'],20);self.assertEqual(full['other_assets'],100)
        self.assertEqual(full['inventory_cost'],120);self.assertEqual(full['fbs_replaced'],[10,11])
        partial=b.report_projection([10],{10:inventory()},comp,bs,True)
        self.assertEqual(partial['seller_stock_cost'],0);self.assertEqual(partial['other_assets'],0)
        self.assertEqual(partial['receivables'],40);self.assertEqual(partial['partial_companies'],['A'])
    def test_multiple_companies_and_duplicate_selected_ids(self):
        comps=[{'id':1,'shops':[10],'title':'A'},{'id':2,'shops':[11],'title':'B'}]
        batches={1:[stock(),assets([]),settlement()],2:[stock('3'),assets([]),settlement(11)]}
        x=b.report_projection([10,10,11],{10:inventory(),11:inventory()},comps,batches,True)
        self.assertEqual(x['seller_stock_cost'],50);self.assertEqual(x['receivables'],80)
    def test_unknown_price_zero_stock_negative_quantity(self):
        x=b.stock_value([{'quantity':D(0)},{'quantity':D(2),'cost':None,'seller':D(3),'buyer':None}])
        self.assertIsNone(x['cost']['total']);self.assertEqual(x['seller']['total'],6);self.assertEqual(x['cost']['missing'],1)
        self.assertIsNone(b.stock_value([{'quantity':None}])['quantity']['total'])
        self.assertIsNone(b.stock_value([{'quantity':-1,'cost':3}])['cost']['total'])
    def test_decimal_money_and_negative_receivable(self):
        self.assertEqual(b.stock_value([{'quantity':3,'cost':.1}])['cost']['total'],D('.3'))
        x=b.manual_totals([settlement(net='-10',accrued='20')]);self.assertEqual(x['debts'],10);self.assertEqual(x['receivables'],20)
    def test_unknown_finance_not_zero_fullness(self):
        x=b.report_projection([10],{10:inventory()},[{'id':1,'shops':[10],'title':'A'}],{1:[stock(),assets([]),settlement(net=None)]},True)
        self.assertTrue(any('обе стадии' in s for s in x['gaps']));self.assertEqual(x['receivables'],25)
    def test_partial_sources_and_missing_price_marked(self):
        inv=inventory();inv['stale']=True;inv['groups'][0]['complete']=False
        inv['groups'][0]['values']['cost'].update(missing=2,total=None)
        x=b.report_projection([10],{10:inv},[],{},False)
        self.assertTrue(any('себестоимости' in s for s in x['gaps']));self.assertTrue(any('полнота' in s for s in x['gaps']))
        self.assertTrue(any('предыдущий' in s for s in x['gaps']))
    def test_no_mutation_and_fbs_risk(self):
        data={10:inventory(),11:inventory()};before=deepcopy(data)
        x=b.report_projection([10,11],data,[],{},False)
        self.assertTrue(any('пересекаться' in s for s in x['gaps']));self.assertEqual(data,before)


class Imports(unittest.TestCase):
    def make(self,kind,rows):
        w=load_workbook(io.BytesIO(excel.template(kind)));s=w['Данные']
        for r in rows:s.append(r)
        out=io.BytesIO();w.save(out);return out.getvalue()
    def test_roundtrip_stock_and_cyrillic_decimal(self):
        raw=self.make('stock',[['0001','Товар','2,5','100,2']]);p=excel.parse(raw,'stock')
        self.assertEqual(p['rows'][0]['code'],'0001');self.assertEqual(p['rows'][0]['quantity'],'2.5')
    def test_assets_categories_date_and_negative_rejected(self):
        p=excel.parse(self.make('assets',[['a','Кредит','Основной долг кредита',100,datetime(2026,12,1),'']]),'assets')
        self.assertEqual(p['rows'][0]['category'],'loan');self.assertEqual(p['rows'][0]['due'],'2026-12-01')
        with self.assertRaises(ValueError):excel.parse(self.make('assets',[['a','X','loan',-2,None,None]]),'assets')
    def test_formulas_duplicates_blank_and_invalid_archive(self):
        for rows in ([['a','X',1,'=2*3']],[['a','X',1,2],['a','Y',2,3]]):
            with self.assertRaises(ValueError):excel.parse(self.make('stock',rows),'stock')
        self.assertEqual(excel.parse(excel.template('stock'),'stock')['rows'],[])
        with self.assertRaises(ValueError):excel.parse(b'bad','stock')
    def test_nonfinite_and_large_rows(self):
        for x in ('NaN','Infinity','-1',True,'1e100','.00000001'):
            with self.assertRaises(ValueError):b.num(x)
        with self.assertRaises(ValueError):b.validate_payload('stock',{'rows':[{}]*20001})
    def test_settlement_exclusive_required_and_null_not_zero(self):
        with self.assertRaises(ValueError):b.validate_payload('settlement',{'rows':[{'note':'ЛК','accrued':100}]})
        p=excel.parse(self.make('settlement',[[100,80,None,0,'Сверка из ЛК']]),'settlement')
        self.assertIsNone(p['rows'][0]['unaccrued_net']);self.assertEqual(p['rows'][0]['accrued'],'0')


STOCK_SCHEMA='''
CREATE TABLE stocks_wb_snap(account_id int,snap_at timestamptz,nm_id bigint,chrt_id bigint,warehouse text,quantity numeric,in_way_to_client numeric,in_way_from_client numeric,data jsonb);
CREATE TABLE stocks_seller_snap(account_id int,snap_at timestamptz,nm_id bigint,chrt_id bigint,warehouse text,quantity numeric,data jsonb);
CREATE TABLE cost_price(account_id int,nm_id bigint,valid_from date,cost numeric);
CREATE TABLE prices_snap(account_id int,snap_at timestamptz,nm_id bigint,size_id bigint,discounted_price numeric);
CREATE TABLE wb_showcase(account_id int,nm_id bigint,price numeric,checked_at timestamptz);
CREATE TABLE wb_showcase_hist(account_id int,nm_id bigint,price numeric,at timestamptz);
CREATE TABLE nomenclature(account_id int,nm_id bigint,vendor_code text,title text);
CREATE TABLE oz_stocks(account_id int,snap_at timestamptz,sku bigint,available numeric);
CREATE TABLE oz_products(account_id int,product_id bigint,sku bigint,offer_id text,name text);
CREATE TABLE oz_prices(account_id int,product_id bigint,price numeric,updated_at timestamptz);
'''


class BalanceStandalone(Standalone):
    def execute(self,query,args=()):
                                                                             
                                                                       
        if query.lstrip().startswith('WITH latest AS'):
            query='SELECT * FROM ('+query+') balance_valuation'
        return super().execute(query,args)


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='balance-sql-');cls.cluster=Path(cls.tmp.name)/'pg'
        subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cls.cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        schema='balance_'+uuid4().hex;self.c=BalanceStandalone(self.cluster,schema)
        self.c.raw(f'CREATE SCHEMA {schema};SET search_path={schema};'+FIXTURE+"ALTER TABLE workspaces ADD COLUMN plan text DEFAULT 'basic';CREATE TABLE service_news(title text,body text,tabs text[]);"+STOCK_SCHEMA)
        self.sql=(ROOT/'stometric/migrations/153_company_balance.sql').read_text();self.c.raw(self.sql)
        self.u={'id':1,'is_active':True};self.co=b.save_company(self.c,self.u,1,'Company',[10,11])
    def save(self,kind='stock',payload=None,key=None,previous=None,**kw):
        return b.save_batch(self.c,self.u,1,self.co,kind,'Main',DAY,payload or {'rows':[{'code':'a','name':'A','quantity':2,'cost':10}]},key or uuid4(),previous_id=previous,**kw)
    def test_repeat_migration_and_membership(self):
        self.c.raw(self.sql);self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)
        self.assertEqual(b.companies(self.c,1,b.scope(self.c,self.u,1))[0]['shops'],[10,11])
        with self.assertRaises(HTTPException):b.save_company(self.c,self.u,1,'Other',[10])
        with self.assertRaises(HTTPException):b.save_company(self.c,self.u,1,'Foreign',[20])
    def test_scope_restricted_mcp_foreign_and_viewer(self):
        for u in ({'id':2},{'id':3}):self.assertEqual(b.companies(self.c,1,b.scope(self.c,u,1)),[])
        with self.assertRaises(HTTPException):b.company(self.c,{'id':2},1,self.co)
        for u in ({'id':4},{'id':5},{'id':1,'_mcp':{'id':2}},{'id':1,'is_active':False}):
            with self.assertRaises(HTTPException):b.company(self.c,u,1,self.co,True)
        with self.assertRaises(HTTPException):b.company(self.c,self.u,2,self.co)
    def test_idempotency_conflict_and_history(self):
        key=uuid4();bid,new=self.save(key=key);self.assertTrue(new)
        self.assertEqual(self.save(key=key),(bid,False))
        with self.assertRaises(HTTPException):self.save(key=key,payload={'rows':[]})
        with self.assertRaises(HTTPException):self.save()
        newer,_=self.save(previous=bid,payload={'rows':[]})
        self.assertGreater(newer,bid);self.assertEqual(len(b.latest_batches(self.c,self.co,DAY)),1)
        self.assertEqual(b.latest_batches(self.c,self.co,DAY)[0]['payload']['rows'],[])
        self.assertEqual(self.c.execute('SELECT count(*) n FROM balance_batches').fetchone()['n'],2)
    def test_settlement_bound_to_company_and_date(self):
        payload={'exclusive':True,'rows':[{'note':'ЛК','before_spp':'100','after_spp':'80','unaccrued_net':50,'accrued':75}]}
        self.save('settlement',payload,shop=10)
        with self.assertRaises(HTTPException):self.save('settlement',payload,shop=20)
        self.assertEqual(b.latest_batches(self.c,self.co,date(2026,11,16)),[])
    def test_stock_latest_complete_ignores_partial_and_future(self):
        self.c.raw("""INSERT INTO stocks_wb_snap VALUES(10,'2026-11-16 10:00Z',101,1,'W',2,3,1,'{}'),(10,'2026-11-17 10:00Z',101,1,'W',999,999,999,'{}');
        INSERT INTO stocks_seller_snap VALUES(10,'2026-11-16 10:00Z',101,1,'S',4,'{}');
        INSERT INTO balance_stock_runs VALUES(10,'stocks_wb','2026-11-16 10:00Z',1),(10,'stocks_seller','2026-11-16 10:00Z',1);
        INSERT INTO cost_price VALUES(10,101,'2026-01-01',10),(10,101,'2026-11-18',999);
        INSERT INTO prices_snap VALUES(10,'2026-11-16 10:00Z',101,1,20),(10,'2026-11-18 10:00Z',101,1,999);
        INSERT INTO wb_showcase_hist VALUES(10,101,15,'2026-11-16 10:00Z'),(10,101,999,'2026-11-18 10:00Z');
        INSERT INTO nomenclature VALUES(10,101,'A','Article');""")
        out=src.inventory(self.c,10,'wb',DAY);g={x['kind']:x for x in out['groups']}
        self.assertEqual(g['fbo']['values']['quantity']['total'],2);self.assertEqual(g['to_buyer']['values']['cost']['total'],30)
        self.assertEqual(g['fbs']['values']['buyer']['total'],60);self.assertTrue(g['fbo']['complete'])
        self.assertEqual(g['fbo']['values']['seller']['total'],40)
        self.assertEqual(next(r for r in out['rows'] if r['kind']=='fbo')['gaps'],{})
        self.assertEqual(len(out['rows']),4)
    def test_no_snapshot_and_complete_empty_different(self):
        self.assertIsNone(src.inventory(self.c,10,'wb',DAY)['groups'][0]['values']['cost']['total'])
        self.c.raw("INSERT INTO balance_stock_runs VALUES(10,'stocks_wb','2026-11-17 10:00Z',0)")
        g=src.inventory(self.c,10,'wb',DAY)['groups'][0]
        self.assertTrue(g['complete']);self.assertEqual(g['values']['cost']['total'],0)
    def test_ozon_stock_and_missing_buyer_fbs(self):
        self.c.raw("""INSERT INTO oz_stocks VALUES(11,'2026-11-17 10:00Z',201,3);
        INSERT INTO balance_stock_runs VALUES(11,'oz_stocks','2026-11-17 10:00Z',1);
        INSERT INTO oz_products VALUES(11,401,201,'A','Article');INSERT INTO oz_prices VALUES(11,401,20,'2026-11-17 10:00Z');
        INSERT INTO cost_price VALUES(11,201,'2026-01-01',10);""")
        g={x['kind']:x for x in src.inventory(self.c,11,'ozon',DAY)['groups']}
        self.assertEqual(g['fbo']['values']['cost']['total'],30);self.assertIsNone(g['fbo']['values']['buyer']['total'])
        self.assertIsNone(g['fbs']['values']['cost']['total']);self.assertFalse(g['to_buyer']['complete'])
    def test_size_price_ambiguity_and_null_quantity(self):
        self.c.raw("""INSERT INTO stocks_wb_snap VALUES(10,'2026-11-17 10:00Z',101,1,'W',2,NULL,0,'{}');
        INSERT INTO prices_snap VALUES(10,'2026-11-17 10:00Z',101,1,20),(10,'2026-11-17 10:00Z',101,2,30);""")
        inv=src.inventory(self.c,10,'wb',DAY);g={x['kind']:x for x in inv['groups']}
        self.assertIsNone(g['fbo']['values']['seller']['total']);self.assertIsNone(g['to_buyer']['values']['quantity']['total'])
        self.assertFalse(g['fbo']['complete'])
        self.assertIn('разные цены',next(r for r in inv['rows'] if r['kind']=='fbo')['gaps']['seller'])
        self.assertIn('не заполнено количество',next(r for r in inv['rows'] if r['kind']=='to_buyer')['gaps']['cost'])
        self.assertIn('все строки',g['fbo']['gaps'][0])

    def test_missing_sources_and_news_are_explained(self):
        inv=src.inventory(self.c,10,'wb',DAY)
        self.assertIn('нет сохранённого снимка',inv['groups'][0]['gaps'][0])
        oz=src.inventory(self.c,11,'ozon',DAY)
        self.assertIn('не подключён',next(g for g in oz['groups'] if g['kind']=='fbs')['gaps'][0])
        sql=(ROOT/'stometric/migrations/155_balance_gaps_news.sql').read_text()
        self.c.raw(sql);self.c.raw(sql)
        self.assertEqual(self.c.execute("SELECT count(*) n FROM service_news WHERE title='Баланс: суммы и расшифровка пробелов'").fetchone()['n'],0)

    def test_missing_variant_price_is_not_price_disagreement(self):
        self.c.raw("""INSERT INTO stocks_wb_snap VALUES(10,'2026-11-17 10:00Z',101,1,'W',2,0,0,'{}');
        INSERT INTO prices_snap VALUES(10,'2026-11-17 10:00Z',101,1,20),(10,'2026-11-17 10:00Z',101,2,NULL);""")
        inv=src.inventory(self.c,10,'wb',DAY);row=inv['rows'][0]
        self.assertIsNone(row['seller']);self.assertFalse(row['seller_conflict'])
        self.assertIn('нет полной цены',row['gaps']['seller'])

    def test_http_preview_save_audit_scope_and_history(self):
        app=stometric.web.app
        app.dependency_overrides[stometric.web.current_user]=lambda:self.u
        app.dependency_overrides[stometric.web.conn]=lambda:self.c
        async def inline(func,*args,**kw):return func(*args,**kw)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as client:
                base='/api/workspaces/1/balance';co=f'{base}/companies/{self.co}'
                self.assertEqual((await client.get(base)).status_code,200)
                raw=excel.template('stock')
                r=await client.post(co+'/preview/stock',content=raw)
                self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['rows'],[])
                self.assertEqual(self.c.execute('SELECT count(*) n FROM balance_batches').fetchone()['n'],0)
                p={'kind':'stock','label':'Main','day':str(DAY),'payload':r.json(),'request_key':str(uuid4())}
                r=await client.post(co+'/batches',json=p);self.assertEqual(r.status_code,200,r.text)
                bid=r.json()['id'];r2=await client.post(co+'/batches',json=p)
                self.assertEqual(r2.json(),{'id':bid,'added':False})
                self.assertEqual((await client.get(co+'/history')).json()['rows'][0]['id'],bid)
                self.assertEqual((await client.get(co+f'/batches/{bid}')).json()['payload']['rows'],[])
                self.assertEqual(self.c.execute("SELECT count(*) n FROM audit_log WHERE workspace_id=1 AND action='balance/snapshot'").fetchone()['n'],1)
                with patch.object(api.tabcache,'get',return_value=inventory()) as cached:
                    r=await client.get(base+'/report?day=2026-11-17&shops=10,11,10')
                    self.assertEqual(r.status_code,200,r.text)
                    self.assertEqual(cached.call_count,2)
                    self.assertEqual(r.json()['variants']['without_fbs']['inventory_cost'],120)
                    self.assertEqual(r.json()['variants']['with_fbs']['inventory_cost'],160)
                    self.assertEqual(len(r.json()['companies']),1)
                self.assertEqual((await client.get(base+'/report?day=2026-11-17&shops=20')).status_code,400)
                self.assertEqual((await client.get('/api/workspaces/2/balance')).status_code,403)
                self.u={'id':2}                                                                            
                self.assertEqual((await client.get(co+'/history')).status_code,404)
                self.assertEqual((await client.post(co+'/preview/stock',content=raw)).status_code,403)
                self.u={'id':1,'_mcp':{'workspace_id':1}}
                self.assertEqual((await client.get(base)).status_code,403)
        try:
            with patch('fastapi.routing.run_in_threadpool',inline),patch('fastapi.dependencies.utils.run_in_threadpool',inline),patch('starlette.concurrency.run_in_threadpool',inline),patch.object(api,'today_msk',return_value=DAY):asyncio.run(run())
        finally:app.dependency_overrides.clear()


class Collectors(unittest.TestCase):
    def test_ozon_empty_catalog_is_not_confirmed_zero(self):
        from stometric.collectors_ozon import run_stocks
        ctx=SimpleNamespace(c=Mock(),acc={'id':1},wb=Mock())
        ctx.c.execute.return_value=[]
        self.assertEqual(run_stocks(ctx)['rows'],0)
        self.assertFalse(ctx.wb.post.called)
        self.assertFalse(any('balance_stock_runs' in str(x) for x in ctx.c.execute.call_args_list))
    def test_ozon_unknown_quantity_preserved_and_success_marked(self):
        from stometric.collectors_ozon import run_stocks
        ctx=SimpleNamespace(c=Mock(),acc={'id':1},wb=Mock())
        ctx.c.execute.return_value=[{'sku':101}]
        ctx.wb.post.return_value={'items':[{'sku':101}]}
        self.assertEqual(run_stocks(ctx)['rows'],1)
        inserted=next(x for x in ctx.c.execute.call_args_list if 'INSERT INTO oz_stocks(' in x.args[0])
        self.assertIsNone(inserted.args[1][6])
        self.assertTrue(any('balance_stock_runs' in str(x) for x in ctx.c.execute.call_args_list))
    def test_missing_or_failed_page_never_marks_complete(self):
        ctx=SimpleNamespace(c=Mock(),acc={'id':1},wb=Mock())
        ctx.wb.call.return_value={'data':{}}
        with self.assertRaises(ValueError):stocks.run_wb(ctx)
        self.assertFalse(any('balance_stock_runs' in str(x) for x in ctx.c.execute.call_args_list))
        ctx.wb.call.side_effect=RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):stocks.run_wb(ctx)
        self.assertFalse(any('balance_stock_runs' in str(x) for x in ctx.c.execute.call_args_list))
    def test_successful_empty_is_explicit(self):
        ctx=SimpleNamespace(c=Mock(),acc={'id':1},wb=Mock())
        ctx.wb.call.return_value={'data':{'items':[]}}
        self.assertEqual(stocks.run_wb(ctx)['rows'],0)
        self.assertTrue(any('balance_stock_runs' in str(x) for x in ctx.c.execute.call_args_list))


class Frontend(unittest.TestCase):
    def test_real_component(self):
        for mode in ('development','production'):
            p=subprocess.run(['node',str(ROOT/'tools/frontend/balance.cjs'),str(ROOT)],env={**os.environ,'NODE_ENV':mode},capture_output=True,text=True,timeout=40)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)

if __name__=='__main__':unittest.main()

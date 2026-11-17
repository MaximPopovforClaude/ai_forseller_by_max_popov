"""Morning dashboard variants on synthetic cache metadata and isolated PostgreSQL."""
import stometric.web
import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, Mock
from stometric import tabcache, tabs, rnp, config, balance_sources
from stometric.sheets import pnl_alt
from stometric.materialize import NotReady
from tools.test_calendar import Cursor, Standalone

DAY=date(2026,12,1)


def filters(**kwargs):
    return dict(date_from=DAY-timedelta(days=29),date_to=DAY,nm_ids=None,group=None,**kwargs)


def cached(tab='dash_nm',source='funnel',ids=None,group=None,end=DAY-timedelta(days=1),start=None):
    p=dict(date_from=start or end-timedelta(days=29),date_to=end,nm_ids=ids,group=group)
    if source=='statistics':p['order_source']=source
    return dict(tab=tab,fkey=tabcache.fkey(p))


class DB:
    def __init__(self,mp='wb',recent=()):
        self.mp,self.recent,self.calls,self.cache=mp,list(recent),[],{}
        self.commits=self.rollbacks=0
    def execute(self,q,args=()):
        self.calls.append((q,args))
        if 'SELECT marketplace' in q:return Cursor([{'marketplace':self.mp}])
        if 'SELECT tab, fkey' in q:return Cursor(self.recent)
        if 'SELECT ver, result' in q:
            r=self.cache.get((args[0],args[1],args[2]));return Cursor([r] if r else [])
        if 'SELECT user_id FROM user_prefs' in q:return Cursor([{'user_id':9}])
        if 'SELECT 1 FROM user_prefs' in q:return Cursor([{'one':1}])
        if q.startswith('DELETE FROM tab_cache'):return Cursor([])
        raise AssertionError(q)
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1


class Morning(unittest.TestCase):
    def setUp(self):
        self.logs=[];self.calcs=[];self.stored=[]
        self.keys=sorted(tabcache.ORDER_SOURCE_TABS)+['home','svodwb','status']
        def fn(key):
            def compute(c,s,f):
                self.calcs.append((s,key,dict(f)))
                return {'key':key,'rows':[{'profit':111 if f.get('order_source')=='statistics' else 222}]}
            return compute
        self.functions={key:fn(key) for key in self.keys}
        for obj,name,value in [(tabs,'tabs_for',Mock(side_effect=lambda mp:[(key,key,'test',self.functions[key]) for key in self.keys])),
                               (config,'today_msk',Mock(return_value=DAY)),(tabcache,'_jam_prefetch',Mock()),(tabcache,'_jam_daily_prefetch',Mock()),
                               (balance_sources,'inventory',Mock(return_value={'groups':[],'rows':[]})),
                               (pnl_alt,'precompute',Mock()),(rnp,'compute',Mock(return_value={'rows':[]}))]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
    def store(self,c,s,key,p,fn):
        result=fn(c);self.stored.append((s,key,p,result));return result
    def test_default_views_warm_both_sources_once_and_keep_user_specific_reports(self):
        db=DB()
        with patch.object(tabcache,'compute_store',side_effect=self.store):tabcache.precompute(db,3,self.logs.append)
        for key in tabcache.ORDER_SOURCE_TABS:
            saved=[x for x in self.stored if x[1]==key];self.assertEqual(len(saved),2)
            self.assertEqual([x[3]['rows'][0]['profit'] for x in saved],[222,111])
            for x in saved:
                self.assertEqual(x[2],tabcache.tab_params(db,key,3,filters()|({'order_source':'statistics'} if x[2].get('order_source') else {})))
        self.assertEqual(len([x for x in self.stored if x[1]=='home']),1)
        self.assertEqual([x[2].get('user_id') for x in self.stored if x[1]=='svodwb'],[None,9])
        self.assertFalse(any(x[1]=='status' for x in self.stored))
        self.assertTrue(any('dash5[statistics]' in x for x in self.logs))
        self.assertEqual(db.commits,1)
    def test_cached_selection_rolls_default_dates_and_deduplicates_modes(self):
        records=[cached(ids=[101]),cached(source='statistics',ids=[101]),cached(ids=[101],end=DAY-timedelta(days=2)),
                 cached('dash_group',ids=None,group='own:synthetic'),cached('dash_nm_days',ids=[102],start=date(2026,10,1),end=date(2026,10,10))]
        db=DB(recent=records)
        with patch.object(tabcache,'compute_store',side_effect=self.store):tabcache.precompute(db,3,self.logs.append)
        selected=[x for x in self.stored if x[2].get('nm_ids') or x[2].get('group')];self.assertEqual(len(selected),6)
        for x in selected:
            self.assertEqual(x[0],3)
            self.assertEqual(x[2]['date_to'],date(2026,10,10) if x[1]=='dash_nm_days' else DAY)
        self.assertLess(next(i for i,x in enumerate(self.stored) if x[1]=='rnp_api'),next(i for i,x in enumerate(self.stored) if x in selected))
        query,args=next((q,a) for q,a in db.calls if 'SELECT tab, fkey' in q)
        self.assertIn('account_id=%s',query);self.assertEqual(args[0],3)
    def test_invalid_hashes_missing_keys_and_bounded_selection_are_reported(self):
        db=DB(recent=[{'tab':'dash_nm','fkey':'sha1:unknown'},{'tab':'dash_nm','fkey':'[]'},
                      cached(ids=[True]),cached(ids=[1],end=DAY+timedelta(days=1)),cached(ids=None),
                      *[cached(ids=[i]) for i in range(60)]])
        got=tabcache._recent_dashboard_filters(db,3,DAY,self.logs.append)
        self.assertEqual(len(got),50);self.assertEqual(got[0][1]['nm_ids'],[0])
        self.assertTrue(any('лимит/неполный ключ' in x for x in self.logs))
    def test_failure_in_one_variant_does_not_abort_other_modes_or_reports(self):
        def fail(c,s,key,p,fn):
            if key=='dash5' and not p.get('order_source'):raise NotReady('synthetic wait')
            return self.store(c,s,key,p,fn)
        db=DB()
        with patch.object(tabcache,'compute_store',side_effect=fail):tabcache.precompute(db,3,self.logs.append)
        self.assertEqual(db.rollbacks,1)
        self.assertTrue(any(x[1]=='dash5' and x[2].get('order_source')=='statistics' for x in self.stored))
        self.assertTrue(any('dash5[funnel]: итоги ещё не готовы' in x for x in self.logs))
    def test_metadata_failure_does_not_cancel_default_warmup(self):
        db=DB()
        with patch.object(tabcache,'compute_store',side_effect=self.store),patch.object(tabcache,'_recent_dashboard_filters',side_effect=RuntimeError('private details')):
            tabcache.precompute(db,3,self.logs.append)
        self.assertEqual(len([x for x in self.stored if x[1] in tabcache.ORDER_SOURCE_TABS]),10)
        self.assertNotIn('private details',''.join(self.logs));self.assertEqual(db.rollbacks,1)
    def test_other_marketplaces_do_not_duplicate_jobs_or_read_wb_history(self):
        for mp in ('ozon','ym'):
            self.stored.clear();db=DB(mp)
            with patch.object(tabcache,'compute_store',side_effect=self.store):tabcache.precompute(db,7,self.logs.append)
            self.assertFalse(any('SELECT tab, fkey' in q for q,a in db.calls))
            self.assertTrue(all('order_source' not in x[2] for x in self.stored))
            self.assertEqual(len([x for x in self.stored if x[1]=='dash5']),1)
    def test_opening_both_views_hits_precomputed_cache_without_recalculation(self):
        db=DB(recent=[cached('dash_nm',ids=[101])]);tabcache._MEM.clear()
        self.addCleanup(tabcache._MEM.clear)
        def store(c,s,t,fk,ver,res):
            c.cache[(s,t,fk)]={'ver':ver,'result':res,'computed_at':datetime.now(timezone.utc)}
        with patch.object(tabcache,'version',return_value='data|aggregate|edits'),patch.object(tabcache,'_ensure_financial_ready'),patch.object(tabcache,'_store',side_effect=store):
            tabcache.precompute(db,3,self.logs.append)
            missing=Mock(side_effect=AssertionError('unexpected recalculation'))
            for key,p in [('dash5',filters()),('by_days',filters()),('dash_nm',filters()|{'nm_ids':[101]})]:
                for mode in ('funnel','statistics'):
                    params=tabcache.tab_params(db,key,3,p|{'order_source':mode})
                    result=tabcache.get(db,3,key,params,missing)
                    self.assertEqual(result['rows'][0]['profit'],111 if mode=='statistics' else 222)
            missing.assert_not_called()


class Sql(unittest.TestCase):
    def test_query_is_shop_and_age_scoped_and_news_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix='dashboard-warm-test-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],check=True,capture_output=True,text=True)
            c=Standalone(cluster,'warm')
            c.raw('CREATE SCHEMA warm;SET search_path=warm;CREATE TABLE tab_cache(account_id int,tab text,fkey text,computed_at timestamptz);CREATE TABLE service_news(title text,body text,tabs text[]);')
            valid=cached(ids=[101],end=DAY)
            for shop,key,age in [(3,'dash_nm',0),(8,'dash_nm',0),(3,'home',0),(3,'dash_nm',5)]:
                c.execute("INSERT INTO tab_cache VALUES (%s,%s,%s,now()-%s*interval '1 day')",(shop,key,valid['fkey'],age))
            got=tabcache._recent_dashboard_filters(c,3,DAY,lambda s:None)
            self.assertEqual(len(got),1);self.assertEqual(got[0][1]['nm_ids'],[101])
            news=Path('stometric/migrations/134_dashboard_precompute_news.sql').read_text();c.raw(news);c.raw(news)
            rows=c.execute('SELECT tabs FROM service_news').fetchall()
            self.assertEqual(rows, [])


if __name__=='__main__':unittest.main()

"""Saved cost -> waiting financial tabs -> ready, without live data or jobs."""
import stometric.web as web
import json
import unittest
from datetime import date
from unittest.mock import Mock, patch

import psycopg
from fastapi import HTTPException
from stometric import materialize, tabcache, cost_import
from tools.test_audit_calculations import QueueDB

KEYS = ('pnl_real_w','pnl_real_m','pnl_month','no_cost','pnl_week','pnl_nm','fin_sku','opiu_wb',
        'pnl_alt_m','pnl_alt_nm','pnl_alt_nm_m')


class PendingTabs(unittest.TestCase):
    def setUp(self):
        self.c = QueueDB(); self.c.rollback = Mock()
        self.access = patch.object(web.auth,'shop_role',return_value='owner')
        self.excluded = patch('stometric.exclusions.excluded',return_value=set())
        self.access.start();self.excluded.start()
        self.addCleanup(self.access.stop);self.addCleanup(self.excluded.stop)

    def request(self,key):
        response = web.tab(3,key,date_from=date(2026,10,15),date_to=date(2026,11,13),u={'id':2},c=self.c)
        self.assertEqual(response.headers['cache-control'],'no-store')
        return json.loads(response.body)

    def test_import_blocks_all_pnl_tabs_with_readiness_poll_until_ready(self):
        match=dict(write=[(77,150,date(2026,11,1))],same=0,unknown=0,bad=0)
        with patch.object(cost_import,'match',return_value=match):
            self.assertEqual(cost_import.apply(self.c,3,'nm',[],date(2026,11,1),'synthetic')['updated'],1)
        calculate = Mock(return_value={'columns':[{'field':'profit','title':'Прибыль','type':'money'}], 'rows':[{'profit':500}]})
        def cached(c,key,shop,filters):
            return tabcache.get(c,shop,key,{},calculate)
        with patch.object(web,'_cached',side_effect=cached),patch.object(tabcache,'version',return_value='fixture'),\
             patch.object(tabcache,'compute_store',side_effect=lambda c,*args:calculate(c)):
            for key in KEYS:
                with self.subTest(key=key):
                    waiting=self.request(key)
                    self.assertEqual(waiting['retry'],15)
                    self.assertEqual(waiting['key'],key)
                    self.assertIn('себестоимость',waiting['note'])
                    self.assertIn('автоматически',waiting['note'])
                    self.assertNotIn('profit',waiting['rows'][0])
            calculate.assert_not_called()
            self.c.dirty=None  
            for key in KEYS:
                ready=self.request(key)
                self.assertNotIn('retry',ready)
                self.assertEqual(ready['rows'],[{'profit':500}])

    def test_repeated_wait_reads_do_not_change_or_restart_rebuild(self):
        self.c.dirty={'from':'2026-11-01','revision':'fixed-revision'}
        def cached(c,*args):materialize.ensure_cost_ready(c,3)
        with patch.object(web,'_cached',side_effect=cached),patch.object(materialize,'after_collect') as rebuild:
            for _ in range(3):self.request('opiu_wb')
        self.assertEqual(self.c.dirty,{'from':'2026-11-01','revision':'fixed-revision'})
        self.assertTrue(all(query.startswith('SELECT') for query,_ in self.c.queries))
        rebuild.assert_not_called()

    def test_timeout_and_unrelated_not_ready_do_not_start_polling(self):
        for error in (materialize.NotReady('source history pending'),psycopg.errors.QueryCanceled('timeout')):
            with self.subTest(error=error),patch.object(web,'_cached',side_effect=error):
                self.assertNotIn('retry',self.request('pnl_real_w'))

    def test_permission_precedes_pending_status(self):
        with patch.object(web.auth,'shop_role',return_value=None),patch.object(web,'_cached') as cached:
            with self.assertRaises(HTTPException) as error:self.request('opiu_wb')
            self.assertEqual(error.exception.status_code,403)
            cached.assert_not_called()


if __name__=='__main__':unittest.main()

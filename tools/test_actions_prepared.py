"""Prepared boards: actual cache SQL, scoped permissions and real React flows.

Only disposable PostgreSQL and synthetic articles; no live DB or collectors.
"""
import stometric.web
import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from fastapi import HTTPException
from stometric import action_board_cache as cache, api_manager as api, tabcache
from tools.test_calendar import Standalone, Cursor

ROOT = Path(__file__).resolve().parents[1]
DAY = date(2026, 11, 16)


def fixture(mp='wb'):
    days = [(DAY-timedelta(days=i)).isoformat() for i in range(61)]
    rows = []
    for nm in (101, 102):
        row = {'nm_id': nm, 'vendor_code': str(nm), 'orders': {}, 'actions': {},
               'ads': {}, 'price_spp_days': {}, 'plan': 10, 'margin_pct': .2}
        for i, d in enumerate(days):
            row['orders'][d] = (70 if i == 50 else 1) if nm == 101 else 2
            row['actions'][d] = [{'id': i, 'kind': 'auto:promo_day'}]
            row['ads'][d] = {'all': 10, 'search': 7, 'rec': 3, 'osum': 100}
            row['price_spp_days'][d] = None if i == 3 else 80
        rows.append(row)
    return {'days': days[:60], 'rows': rows, 'mp': mp, 'kinds': [], 'month': '2026-11-01'}


class Rules(unittest.TestCase):
    def test_projection_preserves_all_values_missing_prices_and_source(self):
        for mp in ('wb', 'ozon'):
            original = fixture(mp); before = copy.deepcopy(original)
            for days in (3, 7, 14, 21, 30, 45, 60):
                out = cache.window(original, days)
                self.assertEqual(out['days'], original['days'][:days])
                for row in out['rows']:
                    old = next(r for r in original['rows'] if r['nm_id'] == row['nm_id'])
                    for field in ('orders', 'actions', 'ads', 'price_spp_days'):
                        count = days + (field == 'orders' and mp == 'wb')
                        expected = {d: old[field][d] for d in list(old[field])[:count]}
                        self.assertEqual(row[field], expected)
                    self.assertEqual(row['margin_pct'], old['margin_pct'])
            self.assertEqual(original, before)
            self.assertEqual(cache.window(original, 7)['rows'][0]['nm_id'], 102)
            self.assertEqual(cache.window(original, 60)['rows'][0]['nm_id'], 101)

    def test_permission_checked_before_any_cache_read(self):
        c = Mock()
        with patch.object(api.auth, 'shop_role', return_value=None), patch.object(cache, 'get') as get, patch.object(cache, 'charts') as charts:
            with self.assertRaises(HTTPException): api.board(7, prepared=True, u={'id': 99}, c=c)
            with self.assertRaises(HTTPException): api.board_charts(7, prepared=True, u={'id': 99}, c=c)
            get.assert_not_called(); charts.assert_not_called(); c.execute.assert_not_called()

    def test_shared_cache_has_no_actor_or_edit_permission(self):
        data = fixture(); before = copy.deepcopy(data); c = Mock()
        with patch.object(api, '_role'), patch.object(cache, 'get', return_value=data) as get:
            for user, role, can in [(99, 'viewer', False), (100, 'editor', True)]:
                with patch.object(api.auth, 'shop_role', return_value=role):
                    out = api.board(7, days=999, date_to=DAY, prepared=True, u={'id': user}, c=c)
                    self.assertEqual(out['me'], user); self.assertEqual(out['can_edit'], can)
                    get.assert_called_with(c, 7, 60, DAY, False)
        self.assertEqual(data, before); self.assertNotIn('me', data)


    def test_optional_metrics_do_not_mutate_shared_base_or_mix_shops(self):
        data = fixture(); before = copy.deepcopy(data)
        def get(c, shop, key, params, fn):
            self.assertEqual(shop, 7)
            return data if key == cache.BASE else {'metrics': {'101': {str(DAY): {'all': {'spent': 10}}}}, 'stale': True}
        with patch.object(tabcache, 'get', side_effect=get) as read:
            base = cache.get(Mock(), 7, 7, DAY)
            self.assertNotIn('ad_metrics', base['rows'][0]); self.assertEqual(read.call_count, 1)
            out = cache.get(Mock(), 7, 7, DAY, True)
            self.assertTrue(out['stale'])
            self.assertEqual({r['nm_id']: r['ad_metrics'] for r in out['rows']}[101][str(DAY)]['all']['spent'], 10)
        self.assertEqual(data, before)

    def test_morning_prepares_default_and_recent_windows_once(self):
        class Db:
            def execute(self, q, p):
                return Cursor([{'fkey': json.dumps({'end': '2026-11-15', 'days': n})}
                               for n in (7, 7, 21, 30, 999, True)] + [{'fkey': 'sha1:unknown'}])
        c = Db(); calls = []
        def compute(c, shop, key, params, fn):
            calls.append((shop, key, params)); return fn(c)
        with patch.object(cache, 'today_msk', return_value=DAY), patch.object(tabcache, 'compute_store', side_effect=compute), \
             patch.object(cache.manager, 'board', return_value=fixture()) as board, \
             patch.object(cache.action_charts, 'get', return_value={'rows': {}}) as charts, \
             patch.object(cache.action_ads, 'read', return_value={}) as metrics:
            cache.precompute(c, 7, 'wb', lambda x: None)
            board.assert_called_once_with(c, 7, 60, DAY, ads=True, prices=True)
            charts.assert_called_once_with(c, 7, DAY)
            self.assertEqual([p['days'] for _, k, p in calls if k == cache.ADS], [7, 14, 21, 30])
            self.assertEqual(metrics.call_count, 4)
            for args in metrics.call_args_list:
                self.assertEqual(args.args[1], 7); self.assertEqual(args.args[-1], [101, 102])
            calls.clear(); cache.precompute(c, 8, 'ozon', lambda x: None)
            self.assertEqual([k for _, k, _ in calls], [cache.BASE, cache.CHARTS])
            calls.clear(); cache.precompute(c, 9, 'ym', lambda x: None); self.assertEqual(calls, [])

    def test_failed_base_does_not_warm_unknown_metrics_or_stop_charts(self):
        c = Mock(); calls = []
        def compute(c, shop, key, params, fn):
            calls.append(key)
            if key == cache.BASE: raise ValueError('synthetic')
            return {'rows': {}}
        with patch.object(tabcache, 'compute_store', side_effect=compute):
            cache.precompute(c, 7, 'wb', lambda x: None)
        self.assertEqual(calls, [cache.BASE, cache.CHARTS]); c.rollback.assert_called_once(); c.execute.assert_not_called()

    def test_existing_morning_entrypoint_includes_prepared_board(self):
        from stometric import tabs, rnp
        from stometric.sheets import pnl_alt
        from tools.test_dashboard_precompute import DB
        c = DB()
        with patch.object(tabs, 'tabs_for', return_value=[('mgr_actions', 'Actions', 'Work', lambda *a: {})]), \
             patch.object(tabcache, '_jam_prefetch'), patch.object(tabcache, '_jam_daily_prefetch'), \
             patch.object(pnl_alt, 'precompute'), patch.object(rnp, 'compute', return_value={}), \
             patch.object(tabcache, 'compute_store', return_value={}), patch.object(cache, 'precompute') as prepare:
            tabcache.precompute(c, 7, print)
            prepare.assert_called_once_with(c, 7, 'wb', print)

    def test_mainapp_selection_and_pagination_in_both_react_modes(self):
        for mode in ('development', 'production'):
            p = subprocess.run(['node', str(ROOT/'tools/frontend/actions_filters.cjs'), str(ROOT)],
                env={**os.environ, 'NODE_ENV': mode}, capture_output=True, text=True, timeout=45)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)


class Sql(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='actions-prepared-')
        cls.cluster = Path(cls.tmp.name)/'pg'
        subprocess.run(['/usr/lib/postgresql/16/bin/initdb', '-D', str(cls.cluster), '-A', 'trust', '-U', 'test', '--no-locale', '--encoding=UTF8'],
            capture_output=True, check=True)

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def setUp(self):
        class Db(Standalone):
            def execute(self, q, p=()):
                if q == 'SHOW transaction_read_only': return Cursor([{'transaction_read_only': 'off'}])
                result = super().execute(q, p)
                for r in result.rows:
                    if isinstance(r.get('computed_at'), str): r['computed_at'] = datetime.fromisoformat(r['computed_at'])
                return result
        self.c = Db(self.cluster, 'case_'+uuid4().hex)
        self.c.raw(f'CREATE SCHEMA {self.c.schema}; SET search_path={self.c.schema};'+'''
            CREATE TABLE accounts(id int,workspace_id int); INSERT INTO accounts VALUES(7,1),(8,2);
            CREATE TABLE collector_state(account_id int,last_ok_at timestamptz);
            CREATE TABLE agg_state(account_id int,built_at timestamptz);
            CREATE TABLE audit_log(id int,workspace_id int,action text,details jsonb);
            CREATE TABLE user_prefs(shop_id int,key text,updated_at timestamptz);
            CREATE TABLE article_groups(account_id int);
            CREATE TABLE tab_cache(account_id int,tab text,fkey text,ver text,result jsonb,computed_at timestamptz,PRIMARY KEY(account_id,tab,fkey));
            CREATE TABLE service_news(title text,body text,tabs text[]);
        ''')
        tabcache._MEM.clear(); tabcache._BUSY.clear()
        self.guard = patch.object(tabcache, '_ensure_financial_ready'); self.guard.start(); self.addCleanup(self.guard.stop)
        self.clock = patch.object(tabcache, 'today_msk', return_value=cache.today_msk()); self.clock.start(); self.addCleanup(self.clock.stop)
        self.addCleanup(tabcache._MEM.clear); self.addCleanup(tabcache._BUSY.clear)

    def test_hot_database_cache_reuses_base_for_all_windows_and_charts(self):
        with patch.object(cache.manager, 'board', return_value=fixture()) as board, patch.object(cache.action_charts, 'get', return_value={'days': [], 'rows': {}}) as charts:
            for days in (14, 7, 21, 30, 45, 60): cache.get(self.c, 7, days, DAY)
            self.assertEqual(board.call_count, 1)
            for _ in range(3): cache.charts(self.c, 7, DAY)
            self.assertEqual(charts.call_count, 1)
            tabcache._MEM.clear(); cache.get(self.c, 7, 14, DAY); self.assertEqual(board.call_count, 1)
            cache.get(self.c, 8, 14, DAY); self.assertEqual(board.call_count, 2)
            cache.get(self.c, 7, 14, DAY+timedelta(days=1)); self.assertEqual(board.call_count, 3)
            self.assertEqual(self.c.execute('SELECT count(*) n FROM tab_cache').fetchone()['n'], 4)

    def test_user_edit_invalidates_but_background_collection_serves_stale(self):
        with patch.object(cache.manager, 'board', return_value=fixture()) as board:
            cache.get(self.c, 7, 14, DAY)
            self.c.raw("INSERT INTO audit_log VALUES(1,1,'actions/add','{\"shop\":7}');")
            cache.get(self.c, 7, 14, DAY); self.assertEqual(board.call_count, 2)
            self.c.raw("INSERT INTO audit_log VALUES(2,2,'actions/add','{\"shop\":8}');")
            cache.get(self.c, 7, 7, DAY); self.assertEqual(board.call_count, 2)
            self.c.raw('INSERT INTO collector_state VALUES(7,now());')
            with patch.object(tabcache._POOL, 'submit') as submit:
                out = cache.get(self.c, 7, 14, DAY); self.assertTrue(out['stale'])
                cache.get(self.c, 7, 14, DAY); submit.assert_called_once()
                self.assertEqual(board.call_count, 2)

    def test_guard_rejects_even_hot_results_and_no_actor_data_stored(self):
        with patch.object(cache.manager, 'board', return_value=fixture()):
            cache.get(self.c, 7, 14, DAY)
        data = self.c.execute('SELECT result FROM tab_cache').fetchone()['result']
        self.assertNotIn('me', data); self.assertNotIn('can_edit', data)
        from stometric.materialize import CostRebuildPending
        with patch.object(tabcache, '_ensure_financial_ready', side_effect=CostRebuildPending()):
            with self.assertRaises(CostRebuildPending): cache.get(self.c, 7, 14, DAY)

    def test_news_repeated_once(self):
        sql = (ROOT/'stometric/migrations/151_actions_prepared_news.sql').read_text()
        self.c.raw(sql); self.c.raw(sql)
        self.assertEqual(self.c.execute('SELECT count(*) n FROM service_news').fetchone()['n'], 0)


if __name__ == '__main__': unittest.main()

"""Keyword journal regressions; synthetic WB responses, no live credentials or calls."""
import copy
import json
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import stometric.web                                      
from stometric import ad_keyword_history as kw, manager
from stometric.collectors import advert
from stometric.tabs import manage
from tools.test_calendar import Cursor, Standalone

NOW = datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def responses(active=('свеча',), minus=(), bid=20000):
    return ({'items': [{'advertId': 42, 'nmId': 100, 'normQueries': {
        'active': list(active), 'excluded': None, 'archived': []}}]},
        {'items': [{'advert_id': 42, 'nm_id': 100, 'norm_queries': list(minus)}]},
        {'bids': [] if bid is None else [{'advert_id': 42, 'nm_id': 100, 'norm_query': 'свеча', 'bid_kopecks': bid}]})


class Memory:
    def __init__(self):
        self.snaps, self.rows, self.events, self.commits = {}, {}, [], 0
        self.fail = False

    def execute(self, sql, p=()):
        if sql.startswith('INSERT INTO wb_ad_kw_snapshots'):
            self.snaps.setdefault(p, {})
        elif sql.startswith('SELECT data FROM wb_ad_kw_snapshots'):
            return Cursor([{'data': copy.deepcopy(self.snaps[p])}])
        elif sql.startswith('SELECT query,state,bid'):
            return Cursor([{'query': q, 'state': s, 'bid': b} for (q, s), b in self.rows.get(p, {}).items()])
        elif sql.startswith('INSERT INTO card_changes'):
            self.events.append({'account_id': p[0], 'nm_id': p[1], 'kind': p[2], 'field': p[3],
                                'old_value': json.loads(p[4]), 'new_value': json.loads(p[5]), 'detected_at': p[7]})
        elif sql.startswith('DELETE FROM wb_ad_kw_lists'):
            self.rows[p] = {}
        elif sql.startswith('INSERT INTO wb_ad_kw_lists'):
            if self.fail:
                raise RuntimeError('synthetic insert failure')
            self.rows.setdefault(p[:3], {})[p[3:5]] = p[5]
        elif sql.startswith('UPDATE wb_ad_kw_snapshots'):
            self.snaps[p[1:]] = json.loads(p[0])
        elif sql.startswith('SELECT row_key,data FROM raw_rows'):
            return Cursor([{'row_key': '42', 'data': {'info': {'settings': {'name': 'Тестовая РК'}}}}])
        else:
            raise AssertionError(sql)
        return Cursor([])

    @contextmanager
    def transaction(self):
        old = copy.deepcopy((self.snaps, self.rows, self.events))
        try:
            yield
        except BaseException:
            self.snaps, self.rows, self.events = old
            raise

    def commit(self): self.commits += 1


class KeywordTests(unittest.TestCase):
    def parsed(self, **args): return kw.parse_chunk([(42, 100)], *responses(**args))[42, 100]

    def test_documented_null_lists_and_kopecks(self):
        self.assertEqual(self.parsed()['bids']['свеча'], {'amount': '200.00', 'currency': 'RUB'})
        self.assertEqual(self.parsed()['lists'], {'свеча': 'active'})
        self.assertEqual(self.parsed()['minus'], [])

    def test_missing_pair_component_is_not_empty(self):
        lst, minus, bids = responses()
        parsed = kw.parse_chunk([(42, 100), (43, 100)], lst, minus, bids)
        self.assertEqual(parsed[43, 100], {'bids': {}})
        del lst['items'][0]['normQueries']['archived']
        self.assertNotIn('lists', kw.parse_chunk([(42, 100)], lst, minus, bids)[42, 100])

    def test_bad_response_never_becomes_empty(self):
        for bad in (None, {}, {'bids': None}, {'bids': 'bad'}, {'bids': [None]},
                    {'bids': [], 'failed': [42]}, {'bids': [], 'next': 'more'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kw.parse_chunk([(42, 100)], *responses()[:2], bad)
        for bad in (None, {}, {'items': None}, {'items': [None]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                kw.parse_chunk([(42, 100)], bad, *responses()[1:])

    def test_conflicts_foreign_pairs_bad_currency_bid_and_query(self):
        for field, value in (('advert_id', 9), ('bid_kopecks', -1), ('bid_kopecks', 'NaN'),
                             ('bid_kopecks', True), ('bid_kopecks', .5), ('currency', None), ('norm_query', '')):
            data = responses(); data[2]['bids'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                kw.parse_chunk([(42, 100)], *data)
        data = responses(); data[0]['items'][0]['normQueries']['excluded'] = ['свеча']
        with self.assertRaises(ValueError): kw.parse_chunk([(42, 100)], *data)
        data = responses(); data[1]['items'] *= 2
        with self.assertRaises(ValueError): kw.parse_chunk([(42, 100)], *data)
        data = responses(); data[2]['bids'].append({**data[2]['bids'][0], 'bid_kopecks': 30000})
        with self.assertRaises(ValueError): kw.parse_chunk([(42, 100)], *data)

    def test_initial_empty_baseline_then_added_and_removed(self):
        c = Memory()
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(active=(), bid=None), NOW), 0)
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(minus=('свеча',)), NOW+timedelta(hours=1)), 3)
        self.assertEqual({e['kind'] for e in c.events}, set(kw.KINDS.values()))
        kw.save(c, 1, 42, 100, self.parsed(active=(), bid=None), NOW+timedelta(hours=2))
        self.assertEqual(len(c.events), 6)
        self.assertIn('показы разрешены', kw.label(c.events[-2]))
        self.assertNotIn('добавлен сотрудником', kw.label(c.events[0]))

    def test_same_snapshot_and_older_results_do_not_duplicate_or_revert(self):
        c = Memory(); kw.save(c, 1, 42, 100, self.parsed(), NOW)
        later = NOW+timedelta(hours=2)
        kw.save(c, 1, 42, 100, self.parsed(bid=25000), later)
        state = copy.deepcopy((c.snaps, c.rows, c.events))
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(), NOW+timedelta(hours=1)), 0)
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(bid=25000), later), 0)
        self.assertEqual((c.snaps, c.rows, c.events), state)
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(bid=25000), later+timedelta(hours=1)), 0)

    def test_independent_from_current_list_modified_by_service(self):
        c = Memory(); kw.save(c, 1, 42, 100, self.parsed(), NOW)
        c.rows[1, 42, 100]['свеча', 'active'] = 250                               
        self.assertEqual(kw.save(c, 1, 42, 100, self.parsed(bid=25000), NOW+timedelta(hours=1)), 1)
        e = c.events[0]
        self.assertEqual(e['old_value']['value']['amount'], '200.00')
        self.assertEqual(e['new_value']['value']['amount'], '250.00')

    def test_partial_data_preserves_states_and_does_not_fake_unminus(self):
        c = Memory(); kw.save(c, 1, 42, 100, self.parsed(minus=('фраза',)), NOW)
        new = {'bids': {'свеча': {'amount': '250.00', 'currency': 'RUB'}}}
        kw.save(c, 1, 42, 100, new, NOW+timedelta(hours=1))
        self.assertEqual([e['kind'] for e in c.events], ['ad_kw_bid'])
        self.assertIn(('фраза', 'minus'), c.rows[1, 42, 100])
        self.assertEqual(c.snaps[1, 42, 100]['minus']['at'], NOW.isoformat())

    def test_states_are_observations_not_fabricated_manual_actions(self):
        c = Memory(); kw.save(c, 1, 42, 100, self.parsed(), NOW)
        parts = self.parsed(); parts['lists'] = {'свеча': 'excluded'}
        kw.save(c,1,42,100,parts,NOW+timedelta(hours=1))
        parts['lists'] = {'свеча': 'archived'}
        kw.save(c,1,42,100,parts,NOW+timedelta(hours=2))
        self.assertEqual([e['kind'] for e in c.events], ['ad_kw_status', 'ad_kw_status'])
        self.assertIn('активен → исключён', kw.label(c.events[0]))
        self.assertIn('исключён → в архиве', kw.label(c.events[1]))

    def test_late_new_component_preserves_more_recent_bid(self):
        c = Memory()
        kw.save(c,1,42,100,{'bids': self.parsed(bid=25000)['bids']},NOW+timedelta(hours=2))
        kw.save(c,1,42,100,self.parsed(bid=20000),NOW+timedelta(hours=1))
        self.assertEqual(c.rows[1,42,100]['свеча','active'],250)
        self.assertEqual(c.events, [])                                          

    def test_identity_is_shop_campaign_sku_full_phrase(self):
        c = Memory(); parts = self.parsed()
        for shop, ad, nm in ((1,42,100), (2,42,100), (1,43,100), (1,42,101)):
            self.assertEqual(kw.save(c, shop, ad, nm, parts, NOW), 0)
        q = 'длинная фраза ' + 'А'*310
        parts['minus'] = [q, q.lower()]
        kw.save(c, 1, 42, 100, parts, NOW+timedelta(hours=1))
        self.assertEqual(len(c.events), 2)
        self.assertEqual({e['new_value']['query'] for e in c.events}, {q, q.lower()})
        self.assertTrue(all(e['account_id']==1 and e['nm_id']==100 for e in c.events))

    def test_explicit_zero_and_different_currency_never_mislabeled_rubles(self):
        self.assertEqual(self.parsed(bid=0)['bids']['свеча']['amount'], '0.00')
        self.assertEqual(kw.amount({'amount': '1234.50', 'currency': 'KZT'}), '1 234,5 KZT')
        self.assertEqual(kw.amount({'amount': '1000.00', 'currency': 'RUB'}), '1 000 ₽')

    def test_collector_calls_same_read_methods_and_transactional_journal(self):
        c = Memory(); wb = Mock(); wb.call.side_effect = responses()
        ctx = SimpleNamespace(c=c, wb=wb, acc={'id':1})
        with patch.object(advert, '_kw_pairs', return_value=[(42,100,'')]):
            result = advert.run_kw_lists(ctx)
        self.assertEqual(result, {'pairs':1,'with_lists':1,'incomplete_pairs':0,'changes':0})
        self.assertEqual([call.args[1] for call in wb.call.call_args_list],
                         ['/adv/v0/normquery/list','/adv/v0/normquery/get-minus','/adv/v0/normquery/get-bids'])
        state = copy.deepcopy((c.snaps, c.rows, c.events)); c.fail = True
        wb.call.side_effect = responses(bid=25000)
        with patch.object(advert, '_kw_pairs', return_value=[(42,100,'')]), self.assertRaises(RuntimeError):
            advert.run_kw_lists(ctx)
        self.assertEqual((c.snaps, c.rows, c.events), state)
        self.assertEqual(c.commits, 1)

    def test_collector_failure_before_writes_preserves_baseline(self):
        c = Memory(); wb = Mock(); wb.call.side_effect = [responses()[0], RuntimeError('synthetic API failure')]
        with patch.object(advert, '_kw_pairs', return_value=[(42,100,'')]), self.assertRaises(RuntimeError):
            advert.run_kw_lists(SimpleNamespace(c=c, wb=wb, acc={'id':1}))
        self.assertEqual((c.snaps, c.rows, c.events, c.commits), ({},{},[],0))

    def test_journal_labels_board_color_and_anonymization(self):
        c = Memory(); kw.save(c, 1, 42, 100, self.parsed(), NOW, 'PRIVATE CAMPAIGN')
        kw.save(c, 1, 42, 100, self.parsed(bid=25050), NOW+timedelta(hours=1), 'PRIVATE CAMPAIGN')
        row = {**c.events[0], 'id':1,'detected_at':NOW,'photo':None,'vendor_code':'PRIVATE SKU','title':'PRIVATE PRODUCT'}
        fake = Mock(); fake.execute.side_effect = [Cursor([row]), Cursor([{'marketplace':'wb'}])]
        table = manage.changes(fake, 1, {'date_from':date(2026,11,1),'date_to':date(2026,11,15)})
        self.assertIn('Ключ «свеча», РК 42: ставка 200 ₽ → 250,5 ₽', table['rows'][0]['what'])
        self.assertEqual((table['rows'][0]['old'], table['rows'][0]['new']), ('200 ₽','250,5 ₽'))
        self.assertEqual(table['rows'][0]['campaign'], 'PRIVATE CAMPAIGN')
        self.assertEqual(manager.change_color(row), manager.YELLOW)

    def test_real_sql_baselines_journal_and_idempotent_migration(self):
        with tempfile.TemporaryDirectory(prefix='keyword-history-') as tmp:
            cluster = Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],
                           check=True,capture_output=True,text=True)
            pg = Standalone(cluster, 'kw')
            pg.raw('CREATE SCHEMA kw; SET search_path=kw; CREATE TABLE accounts(id int PRIMARY KEY); INSERT INTO accounts VALUES(1); '
                   'CREATE TABLE service_news(title text,body text,tabs text[]); '
                   'CREATE TABLE card_changes(account_id int,nm_id bigint,kind text,field text,old_value jsonb,new_value jsonb,wb_updated_at timestamptz,detected_at timestamptz);')
            pg.raw((ROOT/'stometric/migrations/039_wb_ad_keywords.sql').read_text())
            migration = (ROOT/'stometric/migrations/136_ad_keyword_history.sql').read_text()
            pg.raw(migration); pg.raw(migration)
            self.assertEqual(pg.execute('SELECT count(*) n FROM service_news').fetchone()['n'], 0)
            self.assertEqual(kw.save(pg,1,42,100,self.parsed(),NOW),0)
            self.assertEqual(kw.save(pg,1,42,100,self.parsed(bid=25050,minus=('свеча',)),NOW+timedelta(hours=1)),2)
            self.assertEqual(kw.save(pg,1,42,100,self.parsed(bid=25050,minus=('свеча',)),NOW+timedelta(hours=2)),0)
            rows = pg.execute('SELECT kind,old_value,new_value FROM card_changes').fetchall()
            self.assertEqual({r['kind'] for r in rows}, {'ad_kw_minus','ad_kw_bid'})
            self.assertEqual(pg.execute("SELECT bid FROM wb_ad_kw_lists WHERE state='active'").fetchone()['bid'], 250.5)


if __name__ == '__main__': unittest.main()

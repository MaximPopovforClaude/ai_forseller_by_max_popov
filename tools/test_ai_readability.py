"""Read-only presentation regression; no models, production DB or marketplace calls."""
import stometric.web                            
import copy
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from stometric import ai_readability as ar, ai_tasks, api_ai_tasks, api_ads, api_manager, aireport, ads_ai
from tools.test_calendar import Cursor, Standalone

EXAMPLE = 'Порог рекламы на заказ — 0,8333333333 × 3 029,1163271 ₽, выше вчерашнего CPO 501 ₽.'


class Presentation(unittest.TestCase):
    def test_actual_example_uses_full_precision_then_rounds(self):
        result = ar.display_text(EXAMPLE)
        self.assertEqual(result, 'Порог расходов на рекламный заказ — около 2 524 ₽, выше вчерашнего CPO 501 ₽.')
        self.assertNotIn('2 423', result)                                                          
        self.assertEqual(ar.display_text(result), result)

    def test_percent_factor_and_decimal_dot_and_spaces(self):
        for text in ['Безубыточная реклама на заказ: 83,33333333 % × 3029.1163271 руб.',
                     'Порог CPO = 0.8333333333 * 3\u202f029.1163271 ₽']:
            self.assertIn('около 2 524 ₽', ar.display_text(text))

    def test_only_known_two_factor_threshold_is_evaluated(self):
        for text in ['Расход: 0.8 × 3029 ₽', 'Порог рекламы на заказ — 2 × 100 ₽',
                     'Порог рекламы на заказ — 0.8 × 100 ₽ / 7', 'Порог рекламы на заказ — 0.8 × 100 ₽ = 80 ₽',
                     'Порог рекламы на заказ — 0.8 × 100 ₽ + 20 ₽']:
            self.assertEqual(ar.display_text(text), text)

    def test_money_percent_and_small_nonzero_signs(self):
        self.assertEqual(ar.display_text('Расход 3029,1163271 ₽; CTR 6,66666 %; прибыль -53.555 рублей.'),
                         'Расход ≈ 3 029 ₽; CTR ≈ 6,7 %; прибыль ≈ -54 ₽.')
        self.assertEqual(ar.display_text('CTR 0,0000004 %; изменение -0,00004 %; цена 0.00001 ₽'),
                         'CTR <0,1 %; изменение >−0,1 %; цена <0,01 ₽')
        self.assertEqual(ar.display_text('Около 99.998 ₽; 0,0 %; 1.000 ₽'), 'Около 100 ₽; 0 %; 1 ₽')

    def test_identity_quoted_queries_dates_links_and_code_are_unchanged(self):
        text = ('SKU NABOR9.12345678 144364136 кампания 40885592; 13.11.2026 13:10; '
                '«свеча 15.55555 ₽» "0,888888 %" https://example.test/9.55555% '
                '`0.333333 × 1000 ₽` ```\n0.55555 ₽\n```')
        self.assertEqual(ar.display_text(text), text)
        self.assertEqual(ar.display_text('Название 15.55555 ₽; расход 99.9999 ₽', protected=['15.55555 ₽']),
                         'Название 15.55555 ₽; расход ≈ 100 ₽')

    def test_no_zero_for_missing_and_no_changes_to_unitless_factors(self):
        for value in [None, '', 'Нет данных', 'коэффициент 0.833333333; пропуск']:
            self.assertEqual(ar.display_text(value), value)
        self.assertEqual(ar.display_text('Поставить ставку 123.4567 ₽', round_values=False), 'Поставить ставку 123.4567 ₽')
        self.assertEqual(ar.display_text('Расход 123.4567 руб. Далее условие.'), 'Расход ≈ 123 ₽. Далее условие.')

    def test_code_supplies_unit_threshold_without_rounding_factors(self):
        self.assertAlmostEqual(ar.unit_ad_threshold({'cost': 100, 'bp': .8333333333, 'profit': 3029.1163271}),
                               2524.263605815696, places=6)
        for unit in [{}, {'cost': 0, 'bp': .8, 'profit': 100}, {'cost': 1, 'bp': None, 'profit': 100},
                     {'cost': 1, 'bp': 1.2, 'profit': 100}, {'cost': 1, 'bp': .8, 'profit': float('nan')}]:
            self.assertIsNone(ar.unit_ad_threshold(unit))
        self.assertEqual(ar.unit_ad_threshold({'cost': 1, 'bp': .8, 'profit': 0}), 0)

    def test_rounded_result_accepted_by_existing_validator_unknown_rejected(self):
        brief = 'Порог расходов на рекламный заказ по юниту: 2524 ₽'
        known = ai_tasks.known_numbers(brief)
        self.assertEqual(ai_tasks.numbers_ok('Порог около 2 524 ₽', known, allow_years=False), (True, []))
        self.assertFalse(ai_tasks.numbers_ok('Порог 999999 ₽', known, allow_years=False)[0])

    def test_writing_rules_reach_all_future_generators(self):
        from tools.ai_tasks import codex_run
        self.assertIn(ar.WRITING_RULES, aireport.RULES)
        self.assertIn(ar.WRITING_RULES, aireport.RULES_OZ)
        self.assertIn(ar.WRITING_RULES, ads_ai.NOTE_RULES)
        result = {'text': json.dumps({'summary': 'Без изменений', 'tasks': []}), 'model': 'synthetic'}
        with patch('stometric.owner_runtime.generate_scoped', return_value=result) as gen:
            codex_run.analyze('synthetic data', 'test', marketplace='wb', api_key=aireport.SUBSCRIPTION)
        self.assertEqual(gen.call_count, 4)
        self.assertTrue(all(ar.WRITING_RULES in call.args[1] for call in gen.call_args_list))
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root/'docs/ai/daily-tasks.md').is_file())


class Responses(unittest.TestCase):
    def test_tasks_response_formats_copy_preserves_actions_feedback_and_saved_text(self):
        c = MagicMock()
        fields = ('id run_id day title why steps tag certainty effect_week priority nm_ids vc check_spec status '
                  'status_by status_note status_at status_who outcome created_at').split()
        row = dict.fromkeys(fields)
        row.update(id=1, day=date(2026,11,15), title='Кампания 40885592', why=EXAMPLE, steps='Ставку пока не менять.',
                   nm_ids=[], vc='SKU9.123456', check_spec={'target':3029.1163271}, effect_week=12500.5555)
        saved = copy.deepcopy(row)
        run = {'day':date(2026,11,15), 'summary': 'Расход 1001.12345 ₽'}
        def execute(sql, args=()):
            if 'FROM ai_tasks t' in sql:return Cursor([row])
            if 'FROM ai_task_feedback' in sql:return Cursor([{'task_id':1,'user_id':2,'rating':1,'comment':'ставка 8.123456 ₽'}])
            if 'FROM ai_task_runs' in sql:return Cursor([run])
            raise AssertionError(sql)
        c.execute.side_effect = execute
        with patch.object(api_ai_tasks,'_role',return_value='editor'), patch.object(ai_tasks,'is_enabled',return_value=True), \
             patch.object(ai_tasks,'marketplace',return_value='wb'), patch('stometric.entry_coverage.report_present',return_value=True):
            result = api_ai_tasks.tasks_get(3, {'id':2}, c)
        task = result['tasks'][0]
        self.assertIn('около 2 524 ₽', task['why'])
        self.assertEqual(task['check_spec'], saved['check_spec'])
        self.assertEqual(task['effect_week'], saved['effect_week'])
        self.assertEqual(task['feedback']['mine']['comment'], 'ставка 8.123456 ₽')
        self.assertEqual(row, saved)
        self.assertEqual(run['summary'], 'Расход 1001.12345 ₽')
        self.assertIn('1 001 ₽', result['runs']['2026-11-15']['summary'])
        c.commit.assert_not_called()

    def test_ads_response_preserves_exact_bid_and_metrics(self):
        keys = ('id kind advert_id nm_id query params reason effect_week metrics priority source status decided_at error batch_at '
                'who verdict delta_profit o_before o_after').split()
        row = dict.fromkeys(keys)
        row.update(id=1,kind='bid',advert_id=40885592,source='rules',reason=EXAMPLE,
                   params={'before':123.4567,'after':110.9876},metrics={'cpo':501.123456})
        saved = copy.deepcopy(row)
        note = {'body':'Расход 1001.12345 ₽'}
        c = MagicMock()
        def execute(sql,args=()):
            if 'FROM ad_proposals p LEFT JOIN' in sql:return Cursor([row])
            if 'FROM nomenclature' in sql or 'FROM ad_feedback' in sql:return Cursor([])
            if 'FROM ad_state' in sql:return Cursor([{}])
            if 'FROM ad_notes' in sql:return Cursor([note])
            if 'max(batch_at)' in sql:return Cursor([{'t':None}])
            raise AssertionError(sql)
        c.execute.side_effect=execute
        with patch.object(api_ads,'_shop'), patch.object(api_ads.auth,'shop_role',return_value='editor'), \
             patch.object(ads_ai,'campaigns',return_value={}), patch.object(ads_ai,'_ad_stats',return_value={}), \
             patch.object(ads_ai,'learned',return_value={}), patch.object(api_ads.actions,'block',return_value={'settings':{},'enabled':False}), \
             patch.object(api_ads.actions,'can_write',return_value='disabled'):
            result=api_ads.ads_get(3,{'id':2},c)
        self.assertIn('около 2 524 ₽',result['proposals'][0]['reason'])
        self.assertEqual(result['proposals'][0]['params'],saved['params'])
        self.assertEqual(result['proposals'][0]['metrics'],saved['metrics'])
        self.assertEqual(row,saved)
        self.assertEqual(note['body'],'Расход 1001.12345 ₽')
        c.commit.assert_not_called()

    def test_home_report_response_preserves_original_and_routing(self):
        from stometric import ai_routing, api_compare
        c=MagicMock()
        row={'section':'day','title':'Главное','body':EXAMPLE,'day':date(2026,11,14)}
        c.execute.side_effect=[Cursor([{'d':date(2026,11,14)}]),Cursor([row])]
        with patch.object(api_manager,'_role'), patch.object(ai_routing,'shop_route',return_value={'ai_ready':True}), \
             patch.object(api_manager.auth,'shop_role',return_value='editor'), patch.object(aireport,'build_status',return_value={}), \
             patch.object(api_compare,'for_shop_home',return_value=None):
            result=api_manager.ai_report(3,{'id':2},c)
        self.assertIn('около 2 524 ₽',result['sections'][0]['body'])
        self.assertEqual(row['body'],EXAMPLE)
        self.assertNotIn('kind',row)
        self.assertTrue(result['can_build'])
        c.commit.assert_not_called()

    def test_read_access_is_checked_before_db_and_presentation(self):
        for fn in (api_ai_tasks.tasks_get,api_ads.ads_get,api_manager.ai_report):
            c=MagicMock()
            with patch('stometric.auth.shop_role',return_value=None), patch('stometric.auth.can',return_value=False), \
                 self.assertRaises(Exception):
                fn(3,{'id':999},c)
            c.execute.assert_not_called()

    def test_news_applies_twice_on_isolated_postgres(self):
        with tempfile.TemporaryDirectory(prefix='ai-readability-') as tmp:
            cluster=Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb','-D',str(cluster),'-A','trust','-U','test','--no-locale','--encoding=UTF8'],
                           check=True,capture_output=True,text=True)
            pg=Standalone(cluster,'readability')
            pg.raw('CREATE SCHEMA readability; SET search_path=readability; CREATE TABLE service_news (title text, body text, tabs text[]);')
            migration=(Path(__file__).resolve().parents[1]/'stometric/migrations/135_ai_readability_news.sql').read_text()
            pg.raw(migration);pg.raw(migration)
            self.assertEqual(pg.execute('SELECT count(*) n FROM service_news').fetchone()['n'],0)


if __name__=='__main__':unittest.main()

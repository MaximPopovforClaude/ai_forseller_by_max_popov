"""Numerical regressions for A1–A6. No DB, network, .env or production data.

Run: PYTHONPATH=. .venv/bin/python -m unittest tools.test_audit_calculations -v
"""
import ast
import json
import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from stometric import materialize, rnp, tabcache, cost_import
from stometric.agg import real_week, nm_day, buyout
from stometric.sheets import pnl_real, pnl_nm, pnl_alt, fin_sku, ozdash, ozv2, dash5


class Rows(list):
    def fetchall(self): return list(self)
    def fetchone(self): return self[0] if self else None


def tax(regime="Другая СНО", rate=0, vat=0, start=date(2000, 1, 1)):
    return dict(regime=regime, rate=rate, vat_rate=vat, vat_deduct_wb=0, cost_vat=False, valid_from=start)


class TaxDB:
    def __init__(self, history): self.history = history
    def execute(self, sql, params=()):
        if "FROM tax_settings" in sql:
            rows = self.history
            if "regime=%s" in sql:
                rows = [r for r in rows if r["regime"] == params[1] and r["valid_from"] <= params[2]]
            return Rows(rows[::-1] if "DESC" in sql else rows)
        if "FROM nomenclature" in sql:
            return Rows([dict(nm_id=x, vendor_code=str(x), subject="test") for x in [1, 2]])
        return Rows()


def sale(nm, amount, week="2026-10-05"):
    row = dict.fromkeys(real_week.SUMS, 0.)
    w = date.fromisoformat(week)
    row.update(nm_id=nm, date_from=week, date_to=date.fromordinal(w.toordinal()+6).isoformat(),
               doc_type="Продажа", oper="Продажа", bonus_type="", cost=0,
               retail_disc=amount, retail_amount=amount, for_pay=amount, qty=1)
    return row


class PnlPeriodRegressions(unittest.TestCase):
    def test_ads_adjustment_is_applied_once_to_week_and_month(self):
        groups = []
        for week in ['2026-10-05', '2026-10-12']:
            groups.extend([
                {**sale(1, 1000, week), 'deduction': 100, 'bonus_type': 'Продвижение'},
                {**sale(1, 0, week), 'deduction': 30, 'bonus_type': 'Медиа'},
            ])

        def ads(_c, _shop, _start, _end, only=None):
            return {w: 40. if only == 'Счет' else 90. for w in ['2026-10-05', '2026-10-12']}

        with patch.object(real_week, 'cached', return_value=groups), patch.object(pnl_real, 'ads_fact', side_effect=ads):
            for mode, expense in [('deduct', 170), ('fact', 120)]:
                for monthly in (False, True):
                    with self.subTest(mode=mode, monthly=monthly):
                        report = pnl_real.compute(TaxDB([tax()]), 1, monthly=monthly, ads_mode=mode)
                        rows = {r['row']: r for r in report['rows'] if r['row'] is not None}
                        periods = {'2026-10': 2, 'Y2026': 2} if monthly else {'2026-10-05': 1, '2026-10-12': 1}
                        for p, count in periods.items():
                            self.assertEqual(rows[46][p], -expense * count)
                            self.assertEqual(rows[57][p], (1000 - expense) * count)

    def test_expense_breakdown_keeps_signs_order_and_zero_net_unknown_item(self):
        groups = [sale(1, 1000)]
        for bonus, fields in [
            ('Незнакомая статья', {'penalty': 2.75}),
            ('Незнакомая статья', {'additional': -2.75}),
            ('Джем', {'deduction': 4.25}),
            ('Джем', {'deduction': -1.25}),
        ]:
            groups.append({**sale(1, 0), 'oper': 'Удержание', 'bonus_type': bonus, **fields})
        with patch.object(real_week, 'cached', return_value=groups):
            report = pnl_real.compute(TaxDB([tax()]), 1)
        breakdown = {r['label']: r['2026-10-05'] for r in report['rows'] if r['row'] is None}
        self.assertEqual(breakdown['Джем'], 3)
        self.assertEqual(breakdown['Прочее: Незнакомая статья'], 0)
        self.assertEqual(list(breakdown)[-1], 'Прочее: Незнакомая статья')
        self.assertNotIn('Прочее: Продажа', breakdown)


class TaxRegressions(unittest.TestCase):
    def test_unit_acquiring_is_deducted_before_profit_tax(self):
        s = dict(orders_sum=1000, orders_sum_spp=1000, commission_offer_orders=100,
                 cost_orders=400, acquiring_orders=100)
        self.assertEqual(rnp.profit(s, 1, dict(regime='ОСНО', rate=.25, vat=0, vat_wb=0)), 300)

    def test_dashboard_own_order_buyout_return_bases(self):
        row = dict(day=date(2026, 10, 5), orders=1, orders_sum=1000, orders_sum_spp=1000,
                   commission_offer_orders=100, cost_orders=400, buyouts=1, buyouts_sum_before_spp=1000,
                   buyouts_sum=1000, commission=100, cost=400, acquiring=100,
                   returns_for_pay=-300, returns_cost=-100)
        for regime, rate, expected in [('ОСНО', .25, [375, 300, 150]),
                                       (pnl_real.IP, .13, [435, 348, 174])]:
            with self.subTest(regime=regime), patch.object(nm_day, 'iter_cached', return_value=[row]),\
                 patch.object(real_week, 'weekly_deliveries', return_value=[]),\
                 patch.object(buyout, 'needed', return_value=True), patch.object(buyout, 'for_nms', return_value=1):
                result = dash5.compute(TaxDB([tax(regime, rate)]), 1, row['day'], custom={'day': (row['day'], row['day'])})
            self.assertEqual([result['values']['day'][n] for n in [35, 63, 83]], expected)

    def test_reference_dashboard_usn_formulas_are_preserved(self):
        
        
        row = dict(day=date(2026, 10, 5), orders=1, orders_sum=1200, orders_sum_spp=1000,
                   commission_offer_orders=120, logistics_orders=50, cost_orders=400, ads_upd=30,
                   storage=10, acceptance_sum=5, vat_orders=100, vat_deduct_orders=40,
                   buyouts=1, buyouts_sum_before_spp=1200, buyouts_sum=1000, commission=100,
                   cost=400, logistics=50, acquiring=20, vat_buyouts=100, vat_deduct_buyouts=40)
        tx = tax('УСН доходы-расходы', .15, .2); tx['vat_deduct_wb'] = .2
        with patch.object(nm_day, 'iter_cached', return_value=[row]),\
             patch.object(real_week, 'weekly_deliveries', return_value=[]),\
             patch.object(buyout, 'needed', return_value=True), patch.object(buyout, 'for_nms', return_value=1):
            values = dash5.compute(TaxDB([tx]), 1, row['day'], custom={'day': (row['day'], row['day'])})['values']['day']
        order_base = 1200 - 120 - 50 - 400 - 30 - 10 - 5 - 100
        order_tax = -max(order_base * .15, 1000 * .01)
        order_vat_deduct = 40 + (120 + 50 + 30 + 10 + 5) * .2 / 1.2
        sale_base = 1000 - 100 - 50 - 400 - 20 - 30 - 10 - 5 - 100
        sale_tax = -max(sale_base * .15, (1000 - 100) * .01)
        sale_vat_deduct = 40 + (100 + 50 + 30 + 10 + 5) * .2 / 1.2
        self.assertAlmostEqual(values[32], order_tax)
        self.assertAlmostEqual(values[35], order_base + order_tax + order_vat_deduct)
        self.assertAlmostEqual(values[60], sale_tax)
        self.assertAlmostEqual(values[63], sale_base + sale_tax + sale_vat_deduct)

    def test_forecast_osno_ip_and_existing_usn(self):
        s = dict(orders_sum=1000, orders_sum_spp=1000, commission_offer_orders=100, cost_orders=400)
        for reg, rate, expected in [("ОСНО", .25, 375), (pnl_real.IP, .13, 435),
                                    ("УСН доход", .06, 440), ("УСН доходы-расходы", .15, 425)]:
            with self.subTest(reg=reg):
                self.assertAlmostEqual(rnp.profit(s, 1, dict(regime=reg, rate=rate, vat=0, vat_wb=0)), expected)

    def test_forecast_tax_does_not_create_osno_tax_on_loss(self):
        s = dict(orders_sum=100, orders_sum_spp=100, cost_orders=200)
        self.assertEqual(rnp.profit(s, 1, dict(regime="ОСНО", rate=.25, vat=0, vat_wb=0)), -100)

    def test_sku_tax_matches_cabinet_and_does_not_restart_for_each_sku(self):
        groups = [sale(1, 2_000_000), sale(2, 2_000_000)]
        with patch.object(real_week, "cached", return_value=groups):
            result = pnl_nm.compute(TaxDB([tax(pnl_real.IP)]), 1, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(result["total"]["r54"], -552_000)
        self.assertEqual(sum(r["r54"] for r in result["rows"]), result["total"]["r54"])

    def test_hidden_january_and_hidden_sku_affect_october_before_filter(self):
        groups = [sale(2, 2_400_000, "2026-01-05"), sale(1, 1_000_000), sale(2, 500_000)]
        with patch.object(real_week, "cached", return_value=groups) as read:
            result = pnl_nm.compute(TaxDB([tax(pnl_real.IP)]), 1, date(2026, 10, 1), date(2026, 10, 31), [1])
        self.assertEqual(read.call_args.args[2], date(2026, 1, 1))
        self.assertEqual(result["rows"][0]["r54"], -150_000)
        self.assertEqual(len(result["rows"]), 1)
        self.assertEqual(result["weeks"][0], "2026-10-05")

    def test_week_display_limit_does_not_reset_ytd(self):
        groups = [sale(1, 2_400_000, "2026-01-05"), sale(1, 1_000_000)]
        with patch.object(real_week, "cached", return_value=groups):
            result = pnl_real.compute(TaxDB([tax(pnl_real.IP)]), 1, weeks=1)
        row = next(r for r in result["rows"] if r["row"] == 54)
        self.assertEqual(row["2026-10-05"], -150_000)
        self.assertNotIn("2026-01-05", row)

    def test_month_regime_change_does_not_include_usn_profit_in_ndfl(self):
        groups = [sale(1, 2_400_000, '2026-10-05'), sale(1, 1_000_000, '2026-10-19')]
        hist = [tax('УСН доход', .06), tax(pnl_real.IP, .13, start=date(2026, 10, 15))]
        with patch.object(real_week, 'cached', return_value=groups):
            report = pnl_real.compute(TaxDB(hist), 1, weeks=1, monthly=True)
        row = next(r for r in report['rows'] if r['row'] == 54)
        self.assertEqual(row['2026-10'], -(144_000 + 130_000))

    def test_progressive_year_resets_and_hidden_prior_year_does_not_leak(self):
        groups = [sale(1, 5_000_000, '2025-10-06'), sale(1, 1_000_000, '2026-10-05')]
        with patch.object(real_week, 'cached', return_value=groups):
            report = pnl_nm.compute(TaxDB([tax(pnl_real.IP)]), 1, date(2025, 10, 1), date(2026, 10, 31))
        self.assertEqual(report['total']['r54'], -(702_000 + 130_000))

    def test_fin_sku_hidden_month_and_sku_keep_same_tax_after_ui_filter(self):
        groups = [sale(2, 2_400_000, "2026-01-05"), sale(1, 1_000_000), sale(2, 500_000)]
        
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'stometric/tabs/basic.py').read_text())
        view = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'fin_sku')
        scope = {'__package__': 'stometric.tabs'}
        exec(compile(ast.Module(body=[view], type_ignores=[]), 'stometric/tabs/basic.py', 'exec'), scope)
        f = dict(date_from=date(2026, 10, 1), date_to=date(2026, 10, 31), nm_ids=None)
        with patch.object(real_week, 'cached', return_value=groups):
            total = scope['fin_sku'](TaxDB([tax(pnl_real.IP)]), 1, f)
            selected = scope['fin_sku'](TaxDB([tax(pnl_real.IP)]), 1, {**f, 'nm_ids': [1]})
        original = next(r for r in total['rows'] if r['nm_id'] == 1)
        self.assertEqual(selected['rows'][0]['tax'], 150_000)
        self.assertEqual(selected['rows'][0]['tax'], original['tax'])
        self.assertEqual(sum(r['tax'] for r in total['rows']), 225_000)

    def test_cached_alt_loads_year_before_selected_period(self):
        visible = {(1, "2026-10"): dict(rev=1_000_000, paid=1_000_000),
                   (2, "2026-10"): dict(rev=500_000, paid=500_000)}
        prior = {(2, "2026-01"): dict(rev=2_400_000, paid=2_400_000)}
        def cached(c, shop, a, b):
            return (prior if a.month == 1 else visible), {}
        with patch.object(pnl_alt, "_cached_raw", side_effect=cached) as read:
            result = pnl_alt.cached(TaxDB([tax(pnl_real.IP)]), 1, date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(read.call_args_list[0].args[2:], (date(2026, 1, 1), date(2026, 9, 30)))
        self.assertEqual(result["nm"][1]["income_tax"], -150_000)
        self.assertEqual(result["total"]["income_tax"], -225_000)
        self.assertEqual(set(result["month"]), {"2026-10"})

    def test_direct_alt_compute_loads_year_context(self):
        prior = {(1, "2026-01"): dict(rev=2_400_000)}
        visible = {(1, "2026-10"): dict(rev=1_000_000)}
        with patch.object(pnl_alt, "raw", side_effect=[(visible, {}), (prior, {})]) as read:
            result = pnl_alt.compute(TaxDB([tax(pnl_real.IP)]), 1, date(2026, 10, 15), date(2026, 10, 31))
        self.assertEqual(read.call_args_list[1].args[2:], (date(2026, 1, 1), date(2026, 10, 14)))
        self.assertEqual(result["total"]["income_tax"], -150_000)

    def test_loss_refund_allocates_and_preserves_totals(self):
        prior = {(1, "2026-01"): dict(rev=3_000_000)}
        visible = {(1, "2026-10"): dict(rev=100_000), (2, "2026-10"): dict(cost=-500_000)}
        result = pnl_alt.finalize(TaxDB([tax(pnl_real.IP)]), 1, visible, {}, date(2026, 10, 31), prior)
        self.assertEqual(result["total"]["income_tax"], 60_000)
        self.assertEqual(sum(r["income_tax"] for r in result["nm"].values()), 60_000)
        self.assertEqual(result["nm"][2]["income_tax"], 60_000)

    def test_historical_vat_totals_equal_months_and_sku_months(self):
        hist = [tax(vat=0), tax(vat=.2, start=date(2026, 10, 1))]
        cells = {(1, "2026-09"): dict(rev=1200, paid=1200), (1, "2026-10"): dict(rev=1200, paid=1200)}
        result = pnl_alt.finalize(TaxDB(hist), 1, cells, {}, date(2026, 10, 31))
        self.assertAlmostEqual(result["total"]["vat"], -200)
        self.assertAlmostEqual(result["total"]["profit_tax"], 2200)
        for field in ("vat", "income_tax", "profit_tax"):
            for collection in ("month", "nm", "nm_month"):
                self.assertAlmostEqual(result["total"][field], sum(r[field] for r in result[collection].values()))

    def test_cold_context_is_queued_not_computed_in_http(self):
        with patch.object(tabcache, "version", return_value="a|b|c|d|e"), patch.object(pnl_alt, "_load", return_value=None),\
             patch.object(pnl_alt._POOL, "submit") as submit, patch.object(pnl_alt, "month_store") as direct:
            pnl_alt._BUSY.discard(987654)
            with self.assertRaises(pnl_alt.Pending):
                pnl_alt._cached_raw(TaxDB([]), 987654, date(2026, 1, 1), date(2026, 1, 31))
            direct.assert_not_called()
            submit.assert_called_once()
            pnl_alt._BUSY.discard(987654)


class OzonDB:
    def __init__(self, costs=None, transaction=None, real=False):
        self.costs = costs or [dict(nm_id=1, valid_from=date(2026, 1, 1), cost=50),
                               dict(nm_id=2, valid_from=date(2026, 1, 1), cost=80)]
        self.transaction = transaction or dict(op_day=date(2026, 9, 5), operation_type="sale", type_name="sale", tx_type="orders",
            amount=250, accruals_for_sale=300, sale_commission=-50, delivery_charge=0, return_delivery_charge=0,
            services_total=0, services=[], skus=[1, 2], qty=2, raw={})
        self.real = real
    def execute(self, sql, params=()):
        if "FROM cost_price" in sql: return Rows(self.costs)
        if "FROM tax_settings" in sql: return Rows([tax()])
        if "FROM oz_transactions" in sql: return Rows([self.transaction])
        if "SELECT 1 FROM oz_realization_day" in sql: return Rows([{}]) if self.real else Rows()
        return Rows()


class OzonRegressions(unittest.TestCase):
    day = date(2026, 9, 5)
    def report(self, db, skus=None):
        return ozv2.compute(db, 1, "day", self.day, self.day, skus=skus)["tot"]

    def test_full_realization_uses_services_without_loading_or_parsing_full_raw(self):
        class ProjectionDB(OzonDB):
            def execute(self, sql, params=()):
                if 'FROM oz_transactions' in sql:
                    self.transaction_query = sql
                    return Rows([{**self.transaction, 'raw': None if 'NULL::jsonb AS raw' in sql else self.transaction['raw']}])
                return super().execute(sql, params)
        db = ProjectionDB(real=True)
        db.transaction['services'] = [{'name': 'test-service', 'price': -30}]
        with patch.object(ozv2, 'transaction_parts', wraps=ozdash.transaction_parts) as allocate:
            result = self.report(db)
        allocate.assert_not_called()
        self.assertIn('NULL::jsonb AS raw', db.transaction_query)
        self.assertIn("raw->'services' services", db.transaction_query)
        self.assertEqual(result['svc_total'], -30)
        
        with patch.object(ozv2, 'transaction_parts', wraps=ozdash.transaction_parts) as allocate:
            selected = self.report(db, [1])
        allocate.assert_called_once()
        self.assertNotIn('NULL::jsonb AS raw', db.transaction_query)
        self.assertEqual(selected['svc_total'], -15)

    def test_full_fallback_parses_trade_quantity_but_skips_delivery_and_other(self):
        class FallbackDB(OzonDB):
            def execute(self, sql, params=()):
                if 'FROM oz_transactions' in sql:
                    self.transaction_query = sql
                    base = {**self.transaction, 'skus': [1], 'qty': 2,
                            'raw': {'items': [{'sku': 1, 'quantity': 3, 'price': 100}]}}
                    return Rows([base,
                                 {**base, 'tx_type': 'delivery', 'accruals_for_sale': 0, 'amount': -10, 'delivery_charge': -10},
                                 {**base, 'tx_type': 'other', 'accruals_for_sale': 0, 'amount': -20, 'type_name': 'Other'}])
                return super().execute(sql, params)
        db = FallbackDB()
        with patch.object(ozv2, 'transaction_parts', wraps=ozdash.transaction_parts) as allocate:
            result = self.report(db)
        allocate.assert_called_once()
        self.assertNotIn('NULL::jsonb AS raw', db.transaction_query)
        self.assertEqual(result['sold_qty'], 3)
        self.assertEqual(result['cost'], -150)
        self.assertEqual(result['svc_total'], -10)
        self.assertEqual(result['item_total'], -20)

    def test_foreign_operations_skip_item_parsing_but_keep_global_expense_base(self):
        class TransactionsDB(OzonDB):
            def execute(self, sql, params=()):
                if 'FROM oz_transactions' in sql:
                    base = {**self.transaction, 'sale_commission': 0, 'qty': 1}
                    return Rows([
                        {**base, 'skus': [1], 'amount': 100, 'accruals_for_sale': 100},
                        {**base, 'skus': [2], 'amount': 300, 'accruals_for_sale': 300},
                        {**base, 'skus': [2], 'amount': -20, 'accruals_for_sale': 0, 'tx_type': 'other', 'type_name': 'SKU service'},
                        {**base, 'skus': [], 'amount': -40, 'accruals_for_sale': 0, 'tx_type': 'other', 'type_name': 'Shared service'},
                    ])
                return super().execute(sql, params)
        db = TransactionsDB()
        with patch.object(ozv2, 'transaction_parts', wraps=ozdash.transaction_parts) as allocate:
            first = self.report(db, [1])
        self.assertEqual(allocate.call_count, 1)
        self.assertEqual(allocate.call_args.args[0]['skus'], [1])
        
        self.assertEqual(first['non_total'], -10)
        self.assertEqual(first['profit'], 40)  
        second, total = self.report(db, [2]), self.report(db)
        self.assertEqual(second['non_total'], -30)
        self.assertEqual(second['item_total'], -20)
        for field in ('sold_amt', 'cost', 'item_total', 'non_total', 'profit', 'payout_all'):
            self.assertAlmostEqual(first[field] + second[field], total[field], msg=field)

    def test_future_cost_does_not_rewrite_past(self):
        db = OzonDB()
        before = self.report(db)
        db.costs.append(dict(nm_id=1, valid_from=date(2026, 11, 1), cost=100))
        after = self.report(db)
        self.assertEqual(before["cost"], after["cost"])
        self.assertEqual(before["profit"], after["profit"])
        history = ozdash._costs(db, 1, date(2026, 9, 5))
        self.assertEqual(history.get(1), 50)
        self.assertEqual(history.at(1, date(2026, 11, 1)), 100)

    def test_multisku_money_quantity_and_cost_conserved(self):
        db = OzonDB()
        total, first, second = self.report(db), self.report(db, [1]), self.report(db, [2])
        for field in ("sold_qty", "sold_amt", "cost", "commission", "payout", "profit"):
            self.assertAlmostEqual(first[field] + second[field], total[field], msg=field)
        self.assertEqual(first["cost"], -50)
        self.assertEqual(second["cost"], -80)

    def test_item_prices_preferred_over_equal_quantity(self):
        db = OzonDB()
        db.transaction["raw"] = {"items": [{"sku": 1, "quantity": 1, "price": 100}, {"sku": 2, "quantity": 1, "price": 200}]}
        self.assertAlmostEqual(self.report(db, [1])["sold_amt"], 100)
        self.assertAlmostEqual(self.report(db, [2])["sold_amt"], 200)

    def test_current_accrual_product_money_and_quantity(self):
        row = dict(skus=[1, 2], qty=3, raw={"posting": {"products": [
            {"sku": 1, "quantity": 2, "commission": {"sale_amount": {"amount": "100"}}},
            {"sku": 2, "quantity": 1, "commission": {"sale_amount": {"amount": "200"}}}]}})
        parts = ozdash.transaction_parts(row)
        self.assertEqual(parts[1][0], 2)
        self.assertAlmostEqual(parts[1][1], 1/3)

    def test_repeated_sku_and_stored_quantity_are_not_lost(self):
        parts = ozdash.transaction_parts(dict(skus=[1, 1, 2], qty=6, raw={}))
        self.assertEqual(parts[1][0], 4)
        self.assertEqual(parts[2][0], 2)
        self.assertAlmostEqual(sum(x[1] for x in parts.values()), 1)

    def test_returns_conserve_money_and_restore_quantity_cost(self):
        db = OzonDB()
        db.transaction.update(tx_type="returns", amount=-250, accruals_for_sale=-300, sale_commission=50)
        total, first, second = self.report(db), self.report(db, [1]), self.report(db, [2])
        for field in ("ret_qty", "ret_amt", "cost", "commission", "profit"):
            self.assertAlmostEqual(first[field] + second[field], total[field], msg=field)
        self.assertEqual(total["cost"], 130)

    def test_service_split_even_when_realization_supplies_revenue(self):
        db = OzonDB(real=True)
        db.transaction["services"] = [{"name": "acquiring", "price": -30}]
        total, first, second = self.report(db), self.report(db, [1]), self.report(db, [2])
        self.assertAlmostEqual(first["svc_total"] + second["svc_total"], total["svc_total"])
        self.assertAlmostEqual(first["payout"] + second["payout"], total["payout"])

    def test_original_dashboard_conserves_filtered_totals(self):
        db = OzonDB()
        def report(skus):
            r = ozdash.compute(db, 1, self.day, self.day, skus)
            return {row['key']: row.get('d0', 0) for row in r['rows']}
        total, first, second = report(None), report([1]), report([2])
        for field in ('b_qty', 'b_sum', 'b_cost', 'f_total', 'f_profit'):
            self.assertAlmostEqual(first[field] + second[field], total[field], msg=field)

    def test_dashboard_current_stock_uses_snapshot_date_not_report_date(self):
        class StockDB(OzonDB):
            def execute(self, sql, params=()):
                if 'WITH last AS' in sql:
                    return Rows([dict(sku=1, snap_at=datetime(2026, 10, 31), q=2)])
                return super().execute(sql, params)
        db = StockDB()
        db.costs += [dict(nm_id=1, valid_from=date(2026, 10, 1), cost=100),
                     dict(nm_id=1, valid_from=date(2026, 11, 1), cost=200)]
        report = ozdash.compute(db, 1, self.day, self.day)
        self.assertEqual(next(r for r in report['rows'] if r['key'] == 'st_cost')['d0'], 200)


class QueueDB:
    def __init__(self): self.dirty = None; self.queries = []
    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        if "INSERT INTO collector_state" in sql:
            new = json.loads(params[0])
            if self.dirty: new['from'] = min(new['from'], self.dirty['from'])
            self.dirty = new
        if "SELECT cursor FROM collector_state" in sql:
            return Rows([{'cursor': dict(self.dirty)}]) if self.dirty else Rows()
        if "UPDATE collector_state SET cursor='{}'" in sql:
            if self.dirty and self.dirty['revision'] == params[1]: self.dirty = None
        if "FROM cost_price" in sql: return Rows([{'exists': 1}])
        if "count(*) n FROM nomenclature" in sql: return Rows([{'n': 1}])
        return Rows()
    def commit(self): pass


class DirtyRegressions(unittest.TestCase):
    def test_cost_edit_invalidates_outcomes_in_same_revision_without_committing(self):
        from stometric import ai_tasks, insights
        db = QueueDB(); db.commit = Mock()
        order = []
        with patch.object(ai_tasks, 'invalidate_outcomes', side_effect=lambda *a: order.append('outcomes')) as invalidate,\
             patch.object(insights, 'invalidate_cost', side_effect=lambda *a: order.append('insights')) as invalidate_insights:
            materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        invalidate.assert_called_once_with(db, 1, db.dirty['revision'])
        invalidate_insights.assert_called_once_with(db, 1, db.dirty['revision'])
        self.assertEqual(order, ['outcomes', 'insights'])
        db.commit.assert_not_called()

    def test_rnp_plan_refreshes_when_tax_or_aggregate_version_changes(self):
        class PlanDB:
            def execute(self, *args): return Rows([{'t': 'unchanged-plan-cells'}])
        shop, month = 989878, date(2026, 10, 1)
        rnp._PLAN.pop((shop, month), None)
        with patch.object(tabcache, 'version', side_effect=['before-tax-edit', 'after-tax-edit']),\
             patch.object(rnp, '_plan', side_effect=[{'profit': 500}, {'profit': 375}]) as calc:
            self.assertEqual(rnp.plan(PlanDB(), shop, month, {}, 1), {'profit': 500})
            self.assertEqual(rnp.plan(PlanDB(), shop, month, {}, 1), {'profit': 375})
        self.assertEqual(calc.call_count, 2)
        rnp._PLAN.pop((shop, month), None)

    def test_recent_manual_edit_keeps_collector_correction_window(self):
        db = QueueDB()
        original = db.execute
        def execute(sql, params=()):
            if 'FROM agg_state' in sql: return Rows([{'built_at': datetime(2026, 10, 31)}])
            return original(sql, params)
        db.execute = execute
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 31))
        with patch.object(materialize, 'today_msk', return_value=date(2026, 10, 31)),\
             patch.object(materialize, '_first_day', return_value=date(2025, 1, 1)),\
             patch.object(materialize, 'build_nm_day', return_value=10) as nm,\
             patch.object(materialize, 'build_real_week', return_value=5):
            materialize.after_collect(db, 1, {'realization'})
        self.assertEqual(nm.call_args.args[2], date(2026, 10, 31) - timedelta(days=materialize.RECENT_DAYS))

    def test_large_shop_chunks_fit_budget_and_do_not_duplicate_serialized_rows(self):
        class BuildDB(QueueDB):
            def execute(self, sql, params=()):
                if 'count(*) n FROM nomenclature' in sql: return Rows([{'n': 20_000}])
                return super().execute(sql, params)
            def cursor(self): return self
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def executemany(self, sql, values):
                if isinstance(values, (list, tuple)): raise AssertionError('serialized rows were copied into another list')
                list(values)
        with patch.object(nm_day, 'compute', return_value=[]) as compute:
            materialize._build_nm_day(BuildDB(), 1, date(2026, 10, 1), date(2026, 10, 7))
        windows = [(x.args[2], x.args[3]) for x in compute.call_args_list]
        self.assertEqual(len(windows), 4)
        self.assertTrue(all((b-a).days+1 <= 2 for a,b in windows))
        self.assertEqual(windows[-1][1], date(2026, 10, 7))

    def test_formula_revision_versions_finished_views_only(self):
        ver = 'collection|aggregate|edits|prefs|groups'
        self.assertNotEqual(tabcache.calculation_version('pnl_alt_nm', ver), ver)
        self.assertNotEqual(tabcache.calculation_version('rnp_api', ver), ver)
        self.assertEqual(tabcache.calculation_version('_pnl_alt_m', ver), ver)
        self.assertEqual(tabcache.calculation_version('_pnl_alt_p', ver), ver)
        class CacheDB:
            def execute(self, *args):
                return Rows([dict(ver=ver, result={'profit': 'old formula'})])
        with patch.object(materialize, 'ensure_cost_ready'), patch.object(tabcache, 'version', return_value=ver),\
             patch.object(tabcache, 'compute_store', return_value={'profit': 'new formula'}) as compute:
            result = tabcache.get(CacheDB(), 898989, 'rnp_api', {}, lambda c: None)
        self.assertEqual(result['profit'], 'new formula')
        compute.assert_called_once()

    def test_queue_keeps_earliest_date_and_new_revision(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2026, 9, 1))
        old = db.dirty['revision']
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        self.assertEqual(db.dirty['from'], '2026-09-01')
        self.assertNotEqual(old, db.dirty['revision'])
        with self.assertRaises(materialize.NotReady): materialize.ensure_cost_ready(db, 1)

    def test_collector_clears_only_after_both_aggregates(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2000, 1, 1))
        with patch.object(materialize, '_first_day', return_value=date(2025, 1, 1)),\
             patch.object(materialize, 'build_nm_day', return_value=10) as nm,\
             patch.object(materialize, 'build_real_week', return_value=5):
            self.assertEqual(materialize.after_collect(db, 1, set()), {'nm_day': 10, 'real_week': 5})
            self.assertEqual(nm.call_args.args[2], date(2025, 1, 1))
        self.assertIsNone(db.dirty)

    def test_failure_keeps_durable_request(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        with patch.object(materialize, '_first_day', return_value=date(2025, 1, 1)),\
             patch.object(materialize, 'build_nm_day', return_value=10),\
             patch.object(materialize, 'build_real_week', side_effect=RuntimeError('retry next cycle')):
            with self.assertRaises(RuntimeError): materialize.after_collect(db, 1, set())
        self.assertIsNotNone(db.dirty)

    def test_concurrent_edit_survives_older_rebuild(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        def rebuild(*args):
            materialize.mark_cost_dirty(db, 1, date(2026, 9, 1))
            return 10
        with patch.object(materialize, '_first_day', return_value=date(2025, 1, 1)),\
             patch.object(materialize, 'build_nm_day', side_effect=rebuild),\
             patch.object(materialize, 'build_real_week', return_value=5):
            materialize.after_collect(db, 1, set())
        self.assertEqual(db.dirty['from'], '2026-09-01')

    def test_pending_cache_is_not_returned_as_fresh(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        fn = Mock()
        with self.assertRaises(materialize.NotReady): tabcache.get(db, 1, 'rnp_api', {}, fn)
        fn.assert_not_called()

    def test_precompute_cannot_cache_direct_aggregate_read_while_dirty(self):
        db = QueueDB()
        materialize.mark_cost_dirty(db, 1, date(2026, 10, 1))
        fn = Mock(return_value={'profit': 500})
        with patch.object(tabcache, 'version', return_value='new-audit-version'), patch.object(tabcache, '_store') as store:
            with self.assertRaises(materialize.NotReady): tabcache.compute_store(db, 1, 'checklist_svod', {}, fn)
        fn.assert_not_called(); store.assert_not_called()

    def test_edit_during_compute_prevents_caching_and_returning_old_amounts(self):
        db = QueueDB()
        def compute(c):
            materialize.mark_cost_dirty(c, 1, date(2026, 10, 1))
            return {'profit': 500}
        with patch.object(tabcache, 'version', return_value='old-audit-version'), patch.object(tabcache, '_store') as store:
            with self.assertRaises(materialize.NotReady): tabcache.compute_store(db, 1, 'checklist_svod', {}, compute)
        store.assert_not_called()

    def test_cost_import_enqueues_in_same_transaction(self):
        db = QueueDB()
        match = dict(write=[(1, 500, date(2026, 9, 1)), (2, 600, date(2026, 10, 1))], same=0, unknown=0, bad=0)
        with patch.object(cost_import, 'match', return_value=match):
            result = cost_import.apply(db, 1, 'nm', [], date(2026, 10, 1), 'test')
        self.assertEqual(result['updated'], 2)
        self.assertEqual(db.dirty['from'], '2026-09-01')

    def test_original_cost_setter_enqueues_without_http_rebuild(self):
        
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'stometric/web.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_cost')
        fn.decorator_list = []; fn.args.defaults = []
        for arg in fn.args.args: arg.annotation = None
        scope = {'__package__': 'stometric', 'auth': SimpleNamespace(can=lambda *a: True, shop_role=lambda *a: 'editor'),
                 'json': json, 'date': date, 'today_msk': lambda: date(2026, 10, 31)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'stometric/web.py', 'exec'), scope)
        db = QueueDB()
        scope['set_cost'](1, SimpleNamespace(cost=500, nm_id=1, valid_from=date(2026, 10, 1)),
                          {'id': 2, 'email': 'test@example.invalid'}, db)
        self.assertEqual(db.dirty['from'], '2026-10-01')
        self.assertFalse(any('DELETE' in sql for sql, _ in db.queries))

    def test_tax_setter_rebuilds_history_before_edited_date(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'stometric/web.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'set_tax')
        fn.decorator_list = []; fn.args.defaults = []
        for arg in fn.args.args: arg.annotation = None
        scope = {'__package__': 'stometric', 'auth': SimpleNamespace(can=lambda *a: True, shop_role=lambda *a: 'admin'),
                 'json': json, 'date': date, 'today_msk': lambda: date(2026, 10, 31)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'stometric/web.py', 'exec'), scope)
        db = QueueDB()
        body = SimpleNamespace(regime='ОСНО', rate=.25, vat_rate=.2, vat_deduct_wb=.2, cost_vat=True,
                               valid_from=date(2026, 10, 1), model_dump=lambda **kw: {})
        with patch.dict('sys.modules', {'stometric.tabs.basic': SimpleNamespace(TAX_REGIMES=['ОСНО'])}):
            scope['set_tax'](1, body, {'id': 2}, db)
        self.assertEqual(db.dirty['from'], '2000-01-01')
        self.assertFalse(any('DELETE' in sql for sql, _ in db.queries))


if __name__ == '__main__': unittest.main()

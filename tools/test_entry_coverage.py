"""Проверки общей полноты отчётов без подключения к рабочей базе."""
import unittest
from datetime import date
from unittest.mock import MagicMock

from stometric.entry_coverage import daily_days, expected_days, report_present


class CoverageTests(unittest.TestCase):
    def test_dates_cross_month_and_leap_day(self):
        self.assertEqual(expected_days(date(2024, 3, 1), 2), [date(2024, 2, 29), date(2024, 2, 28)])

    def test_presence_is_scoped_to_shop_and_date(self):
        c = MagicMock()
        day = date(2026, 10, 30)
        c.execute.return_value = iter([{'account_id': 8, 'd_from': day}])
        self.assertFalse(report_present(c, 3, day))
        query, args = c.execute.call_args.args
        self.assertEqual(args, ([3], day, day))
        self.assertIn('EXISTS (SELECT 1 FROM entry_rows', query)
        self.assertIn('d_from=d_to', query)

    def test_missing_and_present_days(self):
        c = MagicMock()
        day = date(2026, 10, 30)
        c.execute.return_value = iter([])
        self.assertFalse(report_present(c, 3, day))
        c.execute.return_value = iter([{'account_id': 3, 'd_from': day}])
        self.assertTrue(report_present(c, 3, day))

    def test_multiple_shops_do_not_mix(self):
        c = MagicMock()
        day = date(2026, 10, 30)
        c.execute.return_value = iter([{'account_id': 3, 'd_from': day}, {'account_id': 8, 'd_from': date(2026, 10, 29)}])
        self.assertEqual(daily_days(c, [3, 8], date(2026, 10, 29), day), {3: {day}, 8: {date(2026, 10, 29)}})


if __name__ == '__main__':
    unittest.main()

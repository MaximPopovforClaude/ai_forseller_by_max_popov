"""Synthetic WB responses; no network, credentials or database."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from stometric import wb_probe


class WbConnection(unittest.TestCase):
    def check(self, finance, other=200):
        def get(url, **kwargs):
            value = finance if 'finance-api.' in url else other
            if isinstance(value, Exception):
                raise value
            return httpx.Response(value, json={'Status': 'OK'} if value == 200 else {'message': 'untrusted-body'})
        with patch.object(wb_probe.httpx, 'get', side_effect=get) as mock:
            result = wb_probe.verify('synthetic-test-value')
        self.assertEqual(mock.call_count, 4)
        self.assertNotIn('synthetic-test-value', str(result))
        self.assertNotIn('untrusted-body', str(result))
        self.assertTrue(all(not c.kwargs['follow_redirects'] for c in mock.call_args_list))
        return result

    def test_finance_timeout_allows_confirmed_key_with_warning(self):
        result = self.check(httpx.ConnectTimeout('synthetic'))
        self.assertNotIn('error', result)
        self.assertIn('Финансы', result['warnings'][0])

    def test_denial_blocks_saving(self):
        for code in (401, 403):
            self.assertEqual(self.check(code)['error_status'], 400)

    def test_unverified_key_is_not_saved(self):
        for code in (429, 503):
            self.assertEqual(self.check(code, other=code)['error_status'], 503)

    def test_success_and_partial_failure(self):
        self.assertEqual(self.check(200)['warnings'], [])
        for code in (429, 503, 404, 302):
            self.assertTrue(self.check(code)['warnings'])

    def test_anonymous_diagnostic(self):
        with patch.object(wb_probe.httpx, 'get', return_value=httpx.Response(401)) as mock:
            wb_probe.checks()
        self.assertTrue(all(c.kwargs['headers'] == {} for c in mock.call_args_list))


if __name__ == '__main__':
    unittest.main()

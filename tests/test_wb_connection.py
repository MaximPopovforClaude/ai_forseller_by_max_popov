"""Synthetic WB responses; no network, credentials or database."""
from pathlib import Path
import sys
import unittest
from collections import Counter
from unittest.mock import patch

if __name__ == '__main__':
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
        counts = Counter(c.args[0] for c in mock.call_args_list)
        self.assertEqual(set(counts), set(wb_probe.PING.values()))
        for url, count in counts.items():
            value = finance if 'finance-api.' in url else other
            self.assertEqual(count, 2 if isinstance(value, (httpx.ConnectTimeout, httpx.ConnectError)) else 1)
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

    def test_connection_retry_recovers(self):
        for error in (httpx.ConnectTimeout('synthetic'), httpx.ConnectError('synthetic')):
            with self.subTest(error=type(error).__name__), \
                 patch.object(wb_probe.httpx, 'get', side_effect=[error, httpx.Response(200, json={'Status': 'OK'})]) as get, \
                 patch.object(wb_probe.time, 'sleep') as sleep:
                row = wb_probe.check_one(next(iter(wb_probe.PING.items())), 'synthetic')
            self.assertEqual(row['state'], 'ok')
            self.assertEqual(row['attempts'], 2)
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once_with(wb_probe.RETRY_DELAY)

    def test_no_retry_for_http_or_other_transport_failure(self):
        failures = [httpx.Response(code) for code in (401,403,429,500,503,302)] + [
            httpx.ReadTimeout('synthetic'), httpx.ReadError('synthetic'),
            httpx.WriteTimeout('synthetic'), httpx.PoolTimeout('synthetic'), httpx.RemoteProtocolError('synthetic')]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(wb_probe.httpx,'get',side_effect=[failure]) as get, patch.object(wb_probe.time,'sleep') as sleep:
                row = wb_probe.check_one(next(iter(wb_probe.PING.items())), 'synthetic')
            self.assertEqual(row['attempts'], 1)
            self.assertEqual(get.call_count, 1); sleep.assert_not_called()

    def test_second_denial_blocks_key(self):
        counts = Counter()
        def get(url, **kwargs):
            counts[url] += 1
            if 'finance-api.' in url:
                if counts[url] == 1: raise httpx.ConnectTimeout('synthetic')
                return httpx.Response(403)
            return httpx.Response(200,json={'Status':'OK'})
        with patch.object(wb_probe.httpx,'get',side_effect=get), patch.object(wb_probe.time,'sleep'):
            result = wb_probe.verify('synthetic')
        self.assertEqual(result['error_status'],400)
        self.assertEqual(counts[wb_probe.PING['Финансы']],2)

    def test_no_third_attempt_and_no_retry_after_budget(self):
        for clock, expected, sleeps in (([0, 3, 3.25], 2, 1), ([0, 6], 1, 0), ([0, 0, 6], 1, 1)):
            with self.subTest(clock=clock), patch.object(wb_probe.time,'monotonic',side_effect=clock), \
                 patch.object(wb_probe.time,'sleep') as sleep, \
                 patch.object(wb_probe.httpx,'get',side_effect=httpx.ConnectTimeout('synthetic')) as get:
                row = wb_probe.check_one(next(iter(wb_probe.PING.items())), 'synthetic')
            self.assertEqual(get.call_count,expected)
            self.assertEqual(row['attempts'],expected)
            self.assertEqual(row['state'],'unavailable')
            self.assertEqual(sleep.call_count,sleeps)


if __name__ == '__main__':
    unittest.main()

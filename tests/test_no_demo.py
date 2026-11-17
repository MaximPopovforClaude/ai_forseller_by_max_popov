"""Public distribution boundary: old demo URLs cannot load the SPA or query data."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stometric.web as web
import httpx
from starlette.requests import Request
from starlette.responses import Response


class PublicDistribution(unittest.TestCase):
    def test_no_demo_implementation_or_seed_files(self):
        for pattern in ('stometric/demo*.py', 'stometric/api_demo*.py',
                        'web/frontend/src/Demo*', 'web/frontend/public/demo*'):
            self.assertEqual(list(ROOT.glob(pattern)), [], pattern)
        for filename in ('App.tsx', 'QueryHeatmap.tsx', 'Sidebar.tsx', 'Promo.tsx', 'api.ts'):
            text = (ROOT / 'web/frontend/src' / filename).read_text()
            for marker in ('DemoShop', 'demo_shop', 'demoMode', 'замороженном демо',
                           'Демо-магазин', 'demo={', 'if(demo)'):
                self.assertNotIn(marker, text, filename)

    def test_only_real_shop_presentation_is_preserved(self):
        text = (ROOT / 'web/frontend/src/Total.tsx').read_text()
        self.assertIn('Версия для демонстрации', text)
        self.assertIn('presentation', text)


class RemovedRoutes(unittest.IsolatedAsyncioTestCase):
    async def test_direct_demo_requests_are_404_without_database_or_auth_lookup(self):
        paths = ('/demo', '/demo/', '/demo/shops/1', '/%64emo?shop=1',
                 '/api/demo', '/api/demo/', '/api/demo/shops/1')
        with patch.object(web.db, 'connect', side_effect=AssertionError('No DB for removed routes')) as connect:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://test') as client:
                for headers in ({}, {'Cookie': 'ais_session=synthetic'},
                                {'Authorization': 'Bearer synthetic-test-token'}):
                    for method in ('GET', 'POST', 'HEAD'):
                        for path in paths:
                            with self.subTest(path=path, method=method, headers=list(headers)):
                                response = await client.request(method, path, headers=headers)
                                self.assertEqual(response.status_code, 404)
                                self.assertEqual(response.headers['cache-control'], 'no-store')
                                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                                if method != 'HEAD':
                                    self.assertEqual(response.json(), {'detail': 'Not Found'})
            connect.assert_not_called()

    async def test_other_pages_and_real_shop_requests_are_forwarded(self):
        seen = []

        async def next_handler(request):
            seen.append(request.url.path)
            return Response(status_code=204)

        paths = ('/', '/compare', '/api/shops/1/tab/dash5', '/api/me', '/demography', '/api/demography')
        for path in paths:
            request = Request({'type': 'http', 'method': 'GET', 'path': path,
                               'headers': [], 'scheme': 'http', 'server': ('test', 80), 'query_string': b''})
            response = await web.mcp_guard(request, next_handler)
            self.assertEqual(response.status_code, 204)
        self.assertEqual(seen, list(paths))


if __name__ == '__main__':
    unittest.main()

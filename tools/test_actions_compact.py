"""Compact advertising values in the real component and an isolated news migration."""
import stometric.web
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.test_calendar import Standalone

ROOT = Path(__file__).resolve().parents[1]


class Compact(unittest.TestCase):
    def test_real_component(self):
        for mode in ('development', 'production'):
            p = subprocess.run(['node', str(ROOT/'tools/frontend/ad_stats_compact.cjs'), str(ROOT)],
                env={**os.environ, 'NODE_ENV': mode}, text=True, capture_output=True, timeout=30)
            self.assertEqual(p.returncode, 0, p.stdout+p.stderr)

    def test_news_repeated_once(self):
        with tempfile.TemporaryDirectory(prefix='actions-compact-') as tmp:
            cluster = Path(tmp)/'pg'
            subprocess.run(['/usr/lib/postgresql/16/bin/initdb', '-D', str(cluster), '-A', 'trust', '-U', 'test', '--no-locale', '--encoding=UTF8'],
                check=True, capture_output=True)
            c = Standalone(cluster, 'public')
            c.raw('CREATE TABLE service_news(title text,body text,tabs text[]);')
            sql = (ROOT/'stometric/migrations/152_actions_compact_ads_news.sql').read_text()
            c.raw(sql); c.raw(sql)
            self.assertEqual(c.execute('SELECT count(*) n FROM service_news').fetchone()['n'], 0)


if __name__ == '__main__': unittest.main()

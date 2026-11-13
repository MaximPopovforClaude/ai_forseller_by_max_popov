"""Public domains and upgrades: only disposable SQL and synthetic identities."""
import importlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stometric.web
from fastapi import HTTPException, Response
from starlette.requests import Request
from stometric import api_password_reset, config, db, password_reset


class RecoveryDomain(unittest.TestCase):
    def test_links_and_origin_use_the_installations_domain(self):
        old_site = password_reset.SITE
        self.addCleanup(setattr, password_reset, 'SITE', old_site)
        for origin in ('https://seller.example.invalid', 'https://shop.example.invalid:8443'):
            with self.subTest(origin=origin), patch.object(config, 'env', return_value={'SITE_URL':origin+'/'}):
                importlib.reload(password_reset)
                self.assertEqual(password_reset.SITE, origin)
                c = MagicMock()
                c.execute.return_value.fetchone.side_effect = [
                    {'recent':0,'hour_count':0}, {'n':0}, {'expires_at':'2099-01-01T00:30:00Z'}]
                link = password_reset.issue(c, {'id':12,'telegram_id':None}, 11, 'manual')
                parsed = urlsplit(link['url'])
                self.assertEqual(parsed.scheme+'://'+parsed.netloc, origin)
                self.assertEqual(parsed.path, '/reset-password')
                self.assertEqual(parsed.query, '')
                self.assertEqual(len(parsed.fragment), 43)
                self.assertNotIn(parsed.fragment, repr(c.execute.call_args_list))
                request = Request({'type':'http','headers':[(b'origin',origin.encode())]})
                response = Response()
                api_password_reset.browser(request, response)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                with self.assertRaises(HTTPException):
                    api_password_reset.browser(Request({'type':'http','headers':[(b'origin',b'https://other.example.invalid')]}), Response())


class ExistingInstallation(unittest.TestCase):
    def test_migrations_preserve_existing_data_after_personal_ai_migration_900(self):
        from test_installation import SQL, Cursor
        pg = Path('/usr/lib/postgresql/16/bin')
        if not (pg/'initdb').is_file() or os.getuid() == 0:
            self.skipTest('Unprivileged PostgreSQL 16 required')
        class IterableCursor(Cursor):
            def __iter__(self): return iter(self.rows)
        class Database(SQL):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def commit(self): pass
            def execute(self, query, args=()):
                return IterableCursor(super().execute(query, args).rows)
        with tempfile.TemporaryDirectory(prefix='public-upgrade-') as tmp:
            cluster = Path(tmp)/'pg'
            p = subprocess.run([str(pg/'initdb'),'-D',str(cluster),'-A','trust','--no-locale','--encoding=UTF8'],capture_output=True,text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            c = Database(cluster, pg/'postgres')
            old = Path(tmp)/'old-migrations'; old.mkdir()
            current = ROOT/'stometric/migrations'
            for source in current.glob('*.sql'):
                n = int(source.name.split('_')[0])
                if n <= 109 or n == 900:
                    (old/source.name).write_bytes(source.read_bytes())
            with patch.object(db, 'connect', return_value=c), patch.object(db, 'MIGRATIONS', old):
                db.migrate()
            c.raw("""
                INSERT INTO workspaces(id,name,plan) VALUES(71,'Synthetic existing workspace','owner');
                INSERT INTO users(id,email,password_hash,is_superadmin) VALUES(72,'owner@example.invalid','synthetic-only-hash',true);
                INSERT INTO memberships(user_id,workspace_id,role,shop_ids) VALUES(72,71,'owner',ARRAY[73]);
                INSERT INTO accounts(id,name,workspace_id) VALUES(73,'synthetic-existing-shop',71);
                INSERT INTO app_settings(key,value) VALUES('personal_ai','{"enabled":false,"owner_user_id":72,"workspace_id":71,"shop_ids":[73]}');
                INSERT INTO workspace_secrets(workspace_id,kind,enc,added_by) VALUES(71,'claude','synthetic-only-ciphertext',72);
            """)
            tables = ('users','workspaces','memberships','accounts','app_settings','workspace_secrets')
            before = {t:c.execute('SELECT * FROM '+t).fetchall() for t in tables}
            with patch.object(db, 'connect', return_value=c), patch.object(db, 'MIGRATIONS', current):
                applied = db.migrate()
                self.assertIn('110_password_reset.sql', applied)
                self.assertIn('121_workspace_xyz_news.sql', applied)
                self.assertNotIn('900_selfhost_personal_ai.sql', applied)
                self.assertEqual(db.migrate(), [])
            self.assertEqual({t:c.execute('SELECT * FROM '+t).fetchall() for t in tables}, before)
            for table in ('password_reset_tokens','service_news','audit_log'):
                self.assertEqual(c.execute('SELECT count(*) n FROM '+table).fetchone()['n'], 0)


if __name__ == '__main__': unittest.main()

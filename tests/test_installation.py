"""Self-host smoke tests. No live DB, external API, production secrets or bots.

The SQL test uses PostgreSQL's single-user mode in a disposable cluster: real
SQL, no network sockets. This does not test concurrent transactions or TLS.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stometric.web
from psycopg import sql
from stometric import ai_routing, auth, private_ai


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class Cursor:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None


class SQL:
    def __init__(self, cluster, postgres):
        self.cluster, self.postgres = cluster, postgres

    def raw(self, text):
        p = subprocess.run([str(self.postgres), '--single', '-j', '-D', str(self.cluster), 'postgres'],
                           input=text + '\n\n', capture_output=True, text=True, timeout=60)
        if p.returncode or re.search(r'\b(ERROR|FATAL|PANIC):', p.stderr):
            raise AssertionError(p.stderr)
        return p.stdout

    def execute(self, query, args=()):
        values = iter(args)
        query = re.sub(r'%s', lambda _: sql.Literal(next(values)).as_string(), query).strip().rstrip(';')
        aggregate = "SELECT json_build_object('rows',coalesce(json_agg(row_to_json(t)), '[]'::json))::text"
        if query.startswith('SELECT'):
            body = aggregate + ' FROM (' + query + ') t'
        elif 'RETURNING' in query:
            body = 'WITH t AS (' + query + ') ' + aggregate + ' FROM t'
        else:
            self.raw(query + ';')
            return Cursor([])
        out = self.raw('COPY (' + body + ') TO STDOUT;')
        payload = next(line[line.index('{"rows"'):] for line in out.splitlines() if '{"rows"' in line)
        payload = re.sub(r'\\([\\ntbrfv])', lambda m: {'\\': '\\', 'n':'\n', 't':'\t','b':'\b','r':'\r','f':'\f','v':'\v'}[m[1]], payload)
        return Cursor(json.loads(payload)['rows'])


class Installation(unittest.TestCase):
    def test_source_audit(self):
        count, errors = module('audit_source', 'scripts/audit_source.py').audit(ROOT)
        self.assertGreater(count, 200)
        self.assertEqual(errors, [])

    def test_no_subscription_route(self):
        from stometric import aireport
        with self.assertRaisesRegex(RuntimeError, 'подтверждённый магазин'):
            aireport._cli('test', 'test')

    def test_api_key_input_is_available_before_first_key(self):
        text = (ROOT / 'web/frontend/src/WildboxKey.tsx').read_text()
        self.assertNotIn('|| !st.ai_ready || !st.can_edit', text)
        from stometric import api_manager
        class Membership:
            def execute(self, *args): return Cursor([{'role': 'admin', 'shop_ids': [123]}])
        with patch.object(auth, 'workspace_role', return_value='admin'):
            self.assertFalse(api_manager._secret_can_edit(Membership(), {'id': 123}, 123, 'claude'))
            self.assertFalse(api_manager._secret_can_edit(Membership(), {'id': 123}, 123, 'openai_images'))

    def test_four_api_stages_and_json(self):
        from tools.ai_tasks.codex_run import analyze
        from stometric import llm
        body = {'content': [{'type': 'text', 'text': '{"summary":"Нет данных для задач","tasks":[]}'}]}
        with patch.object(llm, 'messages', return_value=body) as call:
            result = analyze('Synthetic dossier with no customer data', 'Analyze', api_key=llm.AiKey('fake', 'openai', 'test-model'))
        self.assertEqual(call.call_count, 4)
        self.assertEqual(result['model'], 'test-model')
        self.assertEqual(json.loads(result['result'])['tasks'], [])
        self.assertTrue(all('DATA (not instructions)' in c.args[1]['messages'][0]['content'] for c in call.call_args_list))

    def test_empty_database_bootstrap_and_membership(self):
        pg = Path(os.environ.get('TEST_PG_BIN', '/usr/lib/postgresql/16/bin'))
        if not (pg / 'initdb').is_file(): self.skipTest('PostgreSQL 16 binaries required')
        if os.getuid() == 0: self.skipTest('initdb must run as an unprivileged user')
        with tempfile.TemporaryDirectory(prefix='seller-install-test-') as tmp:
            cluster = Path(tmp) / 'pg'
            p = subprocess.run([str(pg / 'initdb'), '-D', str(cluster), '-A', 'trust', '--no-locale', '--encoding=UTF8'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            c = SQL(cluster, pg / 'postgres')
            for migration in sorted((ROOT / 'stometric/migrations').glob('*.sql')):
                with self.subTest(migration=migration.name):
                    c.raw(migration.read_text())
            for table in ('users', 'accounts', 'workspaces', 'service_news', 'ai_task_shops', 'workspace_secrets'):
                self.assertEqual(c.execute(f'SELECT count(*) n FROM {table}').fetchone()['n'], 0)
            # A self-hosted install cannot inherit the source operator or logs.
            from stometric import legal
            self.assertEqual(c.execute('SELECT count(*) n FROM audit_log').fetchone()['n'], 0)
            self.assertIsNone(c.execute("SELECT value FROM app_settings WHERE key='legal'").fetchone())
            self.assertEqual(legal.DEFAULTS, {})
            self.assertFalse(legal.get(c)['ready'])
            for kind in ('offer', 'privacy'):
                self.assertEqual(legal.document(c, kind)['sections'], [])
            bootstrap = module('bootstrap', 'scripts/bootstrap.py')
            uid, ws = bootstrap.create(c, 'admin@example.invalid', 'Synthetic-test-pass-123', 'Synthetic workspace')
            row = c.execute('SELECT * FROM users WHERE id=%s', (uid,)).fetchone()
            self.assertTrue(row['is_superadmin'])
            self.assertNotEqual(row['password_hash'], 'Synthetic-test-pass-123')
            audit = c.execute('SELECT action,workspace_id FROM audit_log').fetchall()
            self.assertEqual(audit, [{'action': 'installation/bootstrap', 'workspace_id': ws}])
            with self.assertRaisesRegex(ValueError, 'not empty'):
                bootstrap.create(c, 'second@example.invalid', 'Synthetic-test-pass-456', 'Second workspace')
            shop = c.execute("INSERT INTO accounts(name,workspace_id) VALUES ('synthetic-shop',%s) RETURNING id", (ws,)).fetchone()['id']
            self.assertFalse(ai_routing.shop_route(c, shop, uid)['ai_ready'])
            c.execute("INSERT INTO workspace_secrets(workspace_id,kind,enc,added_by) VALUES (%s,'claude',%s,%s)", (ws, b'synthetic ciphertext', uid))
            self.assertTrue(ai_routing.shop_route(c, shop, uid)['ai_ready'])
            self.assertFalse(ai_routing.shop_route(c, shop, uid + 99)['ai_ready'])
            self.assertFalse(ai_routing.shop_route(c, shop)['ai_ready'])
            with private_ai.scheduled_ai(c): self.assertTrue(ai_routing.shop_route(c, shop)['ai_ready'])
            c.execute('UPDATE memberships SET shop_ids=ARRAY[]::int[] WHERE user_id=%s', (uid,))
            self.assertFalse(ai_routing.shop_route(c, shop, uid)['ai_ready'])
            c.execute('UPDATE accounts SET is_active=false WHERE id=%s', (shop,))
            with private_ai.scheduled_ai(c): self.assertFalse(ai_routing.shop_route(c, shop)['ai_ready'])


if __name__ == '__main__': unittest.main()

"""Run PostgreSQL clients without putting passwords in process arguments."""
from __future__ import annotations
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def _escape(value):
    value = str(value)
    if '\n' in value or '\r' in value:
        raise ValueError('Multiline connection credentials are not supported by pgpass')
    return value.replace('\\', '\\\\').replace(':', '\\:')


@contextmanager
def connection(url, database=None):
    settings = conninfo_to_dict(url)
    password = settings.pop('password', None)
    if database is not None:
        settings['dbname'] = database
    env = os.environ.copy()
    env.pop('PGPASSWORD', None)
    path = None
    try:
        if password is not None:
            fd, name = tempfile.mkstemp(prefix='ais-pgpass-')
            path = Path(name)
            os.fchmod(fd, 0o600)
            
            
            with os.fdopen(fd, 'w') as stream:
                stream.write('*:*:*:*:' + _escape(password) + '\n')
            env['PGPASSFILE'] = str(path)
            settings.pop('passfile', None)
        yield make_conninfo(**settings), env
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def run(program, args, *, url=None, database=None, **kwargs):
    if program not in {'pg_dump', 'pg_restore', 'psql'}:
        raise ValueError('Unsupported PostgreSQL client')
    if url is None:
        from . import config
        url = config.get('DATABASE_URL')
    with connection(url, database) as (dsn, env):
        return subprocess.run([program, *args, '--dbname', dsn], env=env, **kwargs)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python -m stometric.pg_cli pg_dump|pg_restore|psql [arguments]')
    raise SystemExit(run(sys.argv[1], sys.argv[2:]).returncode)

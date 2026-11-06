"""Подключение к PostgreSQL и миграции (файлы migrations/NNN_*.sql применяются по порядку, один раз)."""

from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from . import config

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(autocommit: bool = False, timeout_s: int | None = None, readonly: bool = False) -> psycopg.Connection:
    """timeout_s — предел одного запроса (запросы сайта: тяжёлый расчёт не держит процесс и диск десятки минут).
    readonly — соединение «только чтение» на стороне PostgreSQL (инструменты нейросетей): любая запись — ошибка базы."""
    opts = ([f"-c statement_timeout={timeout_s * 1000}"] if timeout_s else []) + (["-c default_transaction_read_only=on"] if readonly else [])
    kw = {"options": " ".join(opts)} if opts else {}
    return psycopg.connect(config.get("DATABASE_URL"), autocommit=autocommit, row_factory=dict_row, **kw)


def migrate() -> list[str]:
    applied = []
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r["name"] for r in c.execute("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            c.execute(f.read_text(encoding="utf-8"))
            c.execute("INSERT INTO schema_migrations(name) VALUES (%s)", (f.name,))
            applied.append(f.name)
        c.commit()
    return applied


def account(c: psycopg.Connection, name: str) -> dict:
    r = c.execute("SELECT * FROM accounts WHERE name=%s", (name,)).fetchone()
    if not r:
        raise SystemExit(f"Аккаунт {name} не найден (добавь: python -m stometric account-add …)")
    return r

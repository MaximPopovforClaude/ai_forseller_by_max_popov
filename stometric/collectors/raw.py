"""Запись в универсальную raw_rows (источники со схемой «в процессе»)."""

import json


def put(ctx, source: str, key: str, row_date, data) -> None:
    ctx.c.execute(
        """INSERT INTO raw_rows(account_id,source,row_key,row_date,data) VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,source,row_key) DO UPDATE SET data=EXCLUDED.data, row_date=EXCLUDED.row_date, updated_at=now()
           WHERE raw_rows.data IS DISTINCT FROM EXCLUDED.data""",
        (ctx.acc["id"], source, key, row_date, json.dumps(data, ensure_ascii=False, default=str)))

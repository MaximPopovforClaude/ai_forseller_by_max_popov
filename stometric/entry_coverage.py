"""Общая проверка загруженных дневных отчётов; наличие строк обязательно."""
from datetime import timedelta


def daily_days(c, shops, start, end):
    rows = c.execute("""SELECT account_id, d_from FROM entry_reports r
                        WHERE account_id = ANY(%s) AND d_from=d_to AND d_from BETWEEN %s AND %s
                        AND EXISTS (SELECT 1 FROM entry_rows e WHERE e.report_id=r.id)""",
                     (list(shops), start, end))
    out = {}
    for r in rows:
        out.setdefault(r["account_id"], set()).add(r["d_from"])
    return out


def report_present(c, shop, day):
    return day in daily_days(c, [shop], day, day).get(shop, set())


def expected_days(today, count=30):
    return [today - timedelta(days=i) for i in range(1, count + 1)]

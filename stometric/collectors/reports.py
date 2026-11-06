"""Отчёты-задания WB (создать → статус → скачать): платное хранение (≤8 дней за запрос) и платная приёмка (≤31 дня).

Первый запуск — назад до BACKFILL_DAYS (пока WB отдаёт), дальше — последние OVERLAP_DAYS каждый раз.
"""

import time
from ..config import today_msk
from datetime import date, timedelta

from . import raw

BACKFILL_DAYS = 180
OVERLAP_DAYS = 8


def _task(ctx, base: str, params: dict) -> list:
    t = ctx.wb.call("analytics", base, params=params, max_wait=200) or {}
    tid = ((t.get("data") or {}).get("taskId")) or t.get("taskId")
    if not tid:
        raise RuntimeError(f"{base}: нет taskId в ответе: {str(t)[:200]}")
    for _ in range(60):
        st = ctx.wb.call("analytics", f"{base}/tasks/{tid}/status", max_wait=30) or {}
        status = ((st.get("data") or {}).get("status")) or st.get("status")
        if status == "done":
            break
        if status in ("canceled", "purged"):
            raise RuntimeError(f"{base}: задание {status}")
        time.sleep(5)
    else:
        raise RuntimeError(f"{base}: задание не готово за 5 мин")
    return ctx.wb.call("analytics", f"{base}/tasks/{tid}/download", max_wait=200) or []


def _replace(ctx, source, beg, end, rows, day_of):
    """Отчёт-задание за окно — полная картина этих дней: строки окна заменяем свежим отчётом целиком (в отчёте бывают
    строки-близнецы, отличающиеся только суммой, — у них нет естественного ключа). Старые версии остаются в архиве ответов."""
    if not rows:
        return
    ctx.c.execute("DELETE FROM raw_rows WHERE account_id=%s AND source=%s AND row_date BETWEEN %s AND %s",
                  (ctx.acc["id"], source, beg, end))
    seq = {}
    for r in rows:
        d = day_of(r) or None
        seq[d] = seq.get(d, 0) + 1
        raw.put(ctx, source, f"{d}|{seq[d]}", d, r)


def _windows(ctx, name, step):
    """Окна от начала (догрузка) или с перекрытием; прогресс догрузки сохраняется после каждого окна (обрыв/лимит не страшен)."""
    st = ctx.state(name)
    today = today_msk()
    if st.get("backfilled"):
        start = today - timedelta(days=OVERLAP_DAYS)
    elif st.get("done_to"):
        start = date.fromisoformat(st["done_to"]) + timedelta(days=1)
    else:
        start = today - timedelta(days=ctx.depth(BACKFILL_DAYS))
    cur = start
    while cur <= today:
        end = min(today, cur + timedelta(days=step - 1))
        yield cur, end
        cur = end + timedelta(days=1)


def run_storage(ctx) -> dict:
    n = 0
    for beg, end in _windows(ctx, "paid_storage", 8):
        rows = _task(ctx, "/api/v1/paid_storage", {"dateFrom": beg.isoformat(), "dateTo": end.isoformat()})
        _replace(ctx, "paid_storage", beg, end, rows, lambda r: str(r.get("date"))[:10])
        ctx.c.commit()
        if not ctx.state("paid_storage").get("backfilled"):
            ctx.save_state("paid_storage", {"done_to": end.isoformat()})
        n += len(rows)
    return {"rows": n, "cursor": {"backfilled": True}}


def run_acceptance(ctx) -> dict:
    n = 0
    for beg, end in _windows(ctx, "acceptance", 31):
        rows = _task(ctx, "/api/v1/acceptance_report", {"dateFrom": beg.isoformat(), "dateTo": end.isoformat()})
        _replace(ctx, "acceptance", beg, end, rows, lambda r: str(r.get("shkCreateDate") or r.get("date") or "")[:10])
        ctx.c.commit()
        if not ctx.state("acceptance").get("backfilled"):
            ctx.save_state("acceptance", {"done_to": end.isoformat()})
        n += len(rows)
    return {"rows": n, "cursor": {"backfilled": True}}


def run_warehouse_remains(ctx) -> dict:
    """Остатки по складам WB с разбивкой по складам (отчёт-задание warehouse_remains): stocks-report/wb-warehouses
    с 2026 отдаёт только агрегат «Склад WB» (release-notes 570) — по складам берём здесь. Снимок → stocks_wb_snap
    с warehouse = название склада и пометкой source=warehouse_remains (служебные строки «В пути…», «Всего…» — как есть)."""
    import json
    from datetime import datetime, timezone
    rows = _task(ctx, "/api/v1/warehouse_remains", {"locale": "ru", "groupByNm": "true", "groupBySize": "true", "groupByBarcode": "true"})
    snap = datetime.now(timezone.utc).replace(microsecond=0)
    n = 0
    for r in rows:
        for wh in r.get("warehouses") or []:
            ctx.c.execute(
                """INSERT INTO stocks_wh_snap(account_id,snap_at,nm_id,barcode,tech_size,warehouse,quantity,data)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ctx.acc["id"], snap, r.get("nmId"), r.get("barcode"), r.get("techSize"), wh.get("warehouseName"), wh.get("quantity"),
                 json.dumps({k: v for k, v in r.items() if k != "warehouses"}, ensure_ascii=False)))
            n += 1
    ctx.c.commit()
    return {"rows": n, "items": len(rows), "snap_at": snap.isoformat()}

"""Остатки: склады WB и склады продавца (FBS) — снимок; история остатков копится у нас (у WB её нет)."""

import json
from datetime import datetime, timezone


def _pull(ctx, path, table, cols_fn):
    snap = datetime.now(timezone.utc).replace(microsecond=0)
    offset, n = 0, 0
    while True:
        data = ctx.wb.call("analytics", path, "POST", body={"limit": 250000, "offset": offset})
        items = ((data or {}).get("data") or {}).get("items") or []
        for it in items:
            cols, vals = cols_fn(it)
            ctx.c.execute(f"INSERT INTO {table}(account_id,snap_at,{','.join(cols)},data) VALUES ({','.join(['%s'] * (len(cols) + 3))})",
                          (ctx.acc["id"], snap, *vals, json.dumps(it, ensure_ascii=False)))
        ctx.c.commit()
        n += len(items)
        if len(items) < 250000:
            break
        offset += 250000
    return {"rows": n, "snap_at": snap.isoformat()}


def run_wb(ctx) -> dict:
    return _pull(ctx, "/api/analytics/v1/stocks-report/wb-warehouses", "stocks_wb_snap",
                 lambda it: (["nm_id", "chrt_id", "warehouse", "quantity", "in_way_to_client", "in_way_from_client"],
                             [it["nmId"], it.get("chrtId"), it.get("warehouseName") or str(it.get("warehouseId")), it.get("quantity"),
                              it.get("inWayToClient"), it.get("inWayFromClient")]))


def run_seller(ctx) -> dict:
    return _pull(ctx, "/api/analytics/v1/stocks-report/seller-warehouses", "stocks_seller_snap",
                 lambda it: (["nm_id", "chrt_id", "warehouse", "quantity"],
                             [it["nmId"], it.get("chrtId"), it.get("warehouseName") or str(it.get("warehouseId")), it.get("quantity")]))


def run_report_products(ctx) -> dict:
    """Аналитика остатков WB по товарам за период (stocks-report/products): заказы, среднее в день, время отсутствия
    на складе (officeMissingTime), упущенные заказы — основа «заказов в день при наличии» до накопления своей истории остатков.
    Снимок за окна 28 и 45 дней (как в настройках таблицы) → raw_rows source=stocks_report:<окно>."""
    from datetime import timedelta
    from ..config import today_msk
    from . import raw
    end = today_msk() - timedelta(days=1)
    n = 0
    for days in (28, 45):
        beg = end - timedelta(days=days - 1)
        offset = 0
        while True:
            body = {"currentPeriod": {"start": beg.isoformat(), "end": end.isoformat()}, "stockType": "", "skipDeletedNm": False,
                    "orderBy": {"field": "ordersCount", "mode": "desc"}, "availabilityFilters": [], "limit": 1000, "offset": offset}
            data = ctx.wb.call("analytics", "/api/v2/stocks-report/products/products", "POST", body=body) or {}
            items = (data.get("data") or {}).get("items") or []
            for it in items:
                raw.put(ctx, f"stocks_report:{days}", f"{end}|{it['nmID']}", end, {"period": [str(beg), str(end)], **it})
            ctx.c.commit()
            n += len(items)
            if len(items) < 1000:
                break
            offset += 1000
    return {"rows": n}

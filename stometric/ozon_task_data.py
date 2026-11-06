"""Read-only data coverage for Ozon tasks. Presence is not proof of completeness."""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone



DAILY = {
    "analytics": ("oz_analytics", "day", "Воронка"),
    "ad_daily": ("oz_ad_daily", "day", "Реклама по кампаниям"),
    "ad_sku": ("oz_ad_sku", "day", "Реклама по SKU"),
    "queries": ("oz_queries", "day", "Поисковые запросы"),
    "ad_phrases": ("oz_ad_phrases", "day", "Фразы рекламы"),
    "realization": ("oz_realization_day", "day", "Реализация"),
    "transactions": ("oz_transactions", "op_day", "Начисления"),
}
SNAPSHOTS = {
    "stocks": ("oz_stocks", "snap_at", "Остатки"),
    "prices": ("oz_prices", "updated_at", "Цены продавца"),
    "products": ("oz_products", "updated_at", "Карточки"),
    "campaigns": ("oz_ad_campaigns", "updated_at", "Кампании"),
}
COLLECTORS = (
    "oz_analytics", "oz_ad_daily", "oz_ad_sku", "oz_queries", "oz_ad_phrases",
    "oz_tx", "oz_products", "oz_prices", "oz_stocks", "oz_ad_campaigns",
)
BASIC_METRICS = ("ordered_units", "revenue")
FULL_METRICS = BASIC_METRICS + (
    "hits_view", "hits_view_search", "hits_view_pdp", "session_view_pdp",
    "hits_tocart", "cancellations", "returns", "position_category",
)


def metric_presence_sql(metrics):
    """Fixed metric keys only; absent keys and JSON null are both unavailable."""
    return " AND ".join(f"m->>'{key}' IS NOT NULL" for key in metrics)


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _days(start, end):
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _safe(c, read, label, warnings):
    """A failed optional source must not poison the remaining read transaction."""
    try:
        with c.transaction():
            return read()
    except Exception as exc:  
        warnings.append(f"{label}: источник недоступен ({type(exc).__name__})")
        return None


def coverage(c, shop: int, end: date) -> dict:
    """Coverage of [end-13,end], scoped to one shop. Does not access keys or raw data.

    ready means all observed analytics rows for end have the basic order metrics.
    It does NOT certify all SKU or premium funnel metrics were loaded.
    """
    start = end - timedelta(days=13)
    expected = _days(start, end)
    warnings, sources = [], {}
    for key, (table, column, title) in DAILY.items():
        metrics = (f", bool_and({metric_presence_sql(BASIC_METRICS)}) AS basic_ok, "
                   f"bool_and({metric_presence_sql(FULL_METRICS)}) AS full_ok" if key == "analytics" else "")
        rows = _safe(c, lambda: c.execute(
            f"SELECT {column} AS day, count(*) AS n{metrics} FROM {table} "
            f"WHERE account_id=%s AND {column} BETWEEN %s AND %s GROUP BY 1 ORDER BY 1",
            (shop, start, end)).fetchall(), title, warnings)
        if rows is None:
            sources[key] = {"days": [], "latest": None, "rows": None, "available": False}
            if key == "analytics":
                sources[key].update(days_basic=[], days_full=[])
            continue
        present = sorted(_iso(r["day"]) for r in rows if r["day"] is not None and r["n"] > 0)
        missing = [d for d in expected if d not in present]
        sources[key] = {"days": present, "latest": present[-1] if present else None,
                        "rows": sum(r["n"] for r in rows), "available": True, "missing_days": missing}
        if missing:
            warnings.append(f"{title}: нет строк за {', '.join(missing)}; отсутствие строк не равно нулю.")
        if key == "analytics":
            basic = sorted(_iso(r["day"]) for r in rows if r["n"] > 0 and r.get("basic_ok") is True)
            full = sorted(_iso(r["day"]) for r in rows if r["n"] > 0 and r.get("full_ok") is True)
            sources[key].update(days_basic=basic, days_full=full)
            missing_basic = sorted(set(present) - set(basic))
            missing_full = sorted(set(present) - set(full))
            if missing_basic:
                warnings.append("Воронка: неполные показатели заказов/выручки за " + ", ".join(missing_basic) + ".")
            if missing_full:
                warnings.append("Воронка: расширенные метрики доступны не по всем строкам за " + ", ".join(missing_full)
                                + "; возможен базовый отчёт без Premium. Показы, корзины и конверсии не считать нулевыми.")
    now = datetime.now(timezone.utc)
    for key, (table, column, title) in SNAPSHOTS.items():
        
        sql = (f"SELECT max({column}) AS latest, count(*) AS n FROM {table} WHERE account_id=%s"
               if key != "stocks" else
               "SELECT max(snap_at) AS latest, count(*) AS n FROM oz_stocks WHERE account_id=%s "
               "AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s)")
        row = _safe(c, lambda: c.execute(sql, (shop,) if key != "stocks" else (shop, shop)).fetchone(), title, warnings)
        latest = row.get("latest") if row else None
        sources[key] = {"days": [], "latest": _iso(latest), "rows": row["n"] if row else None,
                        "available": row is not None, "current_snapshot": True}
        if latest is None:
            warnings.append(f"{title}: нет снимка; состояние неизвестно.")
        elif isinstance(latest, datetime):
            at = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
            if now - at > timedelta(hours=24):
                warnings.append(f"{title}: последний снимок старше суток ({_iso(latest)}).")
    rows = _safe(c, lambda: c.execute(
        "SELECT collector,last_ok_at FROM collector_state WHERE account_id=%s AND collector=ANY(%s) ORDER BY collector",
        (shop, list(COLLECTORS))).fetchall(), "Статус сборщиков", warnings)
    collectors = {r["collector"]: _iso(r["last_ok_at"]) for r in (rows or [])}
    warnings.append("Наличие строк за день не доказывает полную загрузку всех SKU, кампаний и метрик; "
                    "заказы и начисления относятся к разным событиям и датам.")
    
    snapshot = {"shop": shop, "day": end.isoformat(), "sources": sources, "collectors": collectors}
    digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"day": end.isoformat(), "from": start.isoformat(), "sources": sources, "collectors": collectors,
            "warnings": warnings, "ready": end.isoformat() in sources["analytics"]["days_basic"], "fingerprint": digest}

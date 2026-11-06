"""Self-hosted application component."""

import threading
from datetime import timedelta

from .config import today_msk

PATH = "/api/v2/search-report/product/search-texts"
FRESH = timedelta(hours=2)
ACCESS_RECHECK = timedelta(hours=6)
TOPS = ("openCard", "orders", "addToCart")


def access(c, shop: int) -> dict | None:
    return c.execute("SELECT status, max_limit, info, checked_at FROM jam_access WHERE account_id=%s", (shop,)).fetchone()


def _set_access(c, shop: int, status: str, max_limit: int | None, info: str = ""):
    c.execute("""INSERT INTO jam_access(account_id,status,max_limit,info,checked_at) VALUES (%s,%s,%s,%s,now())
                 ON CONFLICT (account_id) DO UPDATE SET status=EXCLUDED.status, max_limit=EXCLUDED.max_limit, info=EXCLUDED.info,
                   checked_at=now()""", (shop, status, max_limit, info[:500]))
    c.commit()


def _kind(err: str) -> str:
    """Причина отказа WB: no_scope — у ключа нет раздела «Аналитика», no_jam — нет Джема, limit — лимит выше тарифа Джема."""
    e = err.lower()
    if "texts limit" in e:
        return "limit"
    if "token" in e and ("scope" in e or "categor" in e or "category" in e):
        return "no_scope"
    if "http 401" in e:
        return "no_scope"
    if "jam" in e or "джем" in e or "http 402" in e or "http 403" in e:
        return "no_jam"
    return "other"


def period(f: dict):
    """Период отчёта: WB даёт данные не старше 365 дней и не позже сегодня."""
    t = today_msk()
    b = min(f["date_to"], t)
    a = max(min(f["date_from"], b), t - timedelta(days=364))
    return a, b


def cached(c, shop: int, nm: int, a, b) -> dict | None:
    return c.execute("SELECT state, items, error, started_at, fetched_at FROM jam_cache WHERE account_id=%s AND nm_id=%s AND date_from=%s "
                     "AND date_to=%s", (shop, nm, a, b)).fetchone()


def start(shop: int, nm: int, a, b) -> bool:
    """Загрузить отчёт в фоне; False — уже грузится."""
    from . import db
    with db.connect() as c:
        r = c.execute("""INSERT INTO jam_cache(account_id,nm_id,date_from,date_to,state) VALUES (%s,%s,%s,%s,'running')
                         ON CONFLICT (account_id,nm_id,date_from,date_to) DO UPDATE SET state='running', error=NULL, started_at=now()
                         WHERE jam_cache.state<>'running' OR jam_cache.started_at < now() - interval '10 minutes'
                         RETURNING 1""", (shop, nm, a, b)).fetchone()
        
        c.execute("DELETE FROM jam_cache WHERE account_id=%s AND coalesce(fetched_at, started_at) < now() - interval '7 days'", (shop,))
        c.commit()
    if not r:
        return False
    threading.Thread(target=_run, args=(shop, nm, a, b), daemon=True).start()
    return True


def _run(shop: int, nm: int, a, b):
    from . import db
    with db.connect() as c:
        try:
            items = fetch(c, shop, nm, a, b)
            c.execute("UPDATE jam_cache SET state='done', items=%s::jsonb, fetched_at=now() WHERE account_id=%s AND nm_id=%s AND date_from=%s "
                      "AND date_to=%s", (_json(items), shop, nm, a, b))
        except Exception as e:  
            c.rollback()
            c.execute("UPDATE jam_cache SET state='error', error=%s, fetched_at=now() WHERE account_id=%s AND nm_id=%s AND date_from=%s "
                      "AND date_to=%s", (str(e)[:500], shop, nm, a, b))
        c.commit()


def _json(x):
    import json
    return json.dumps(x, ensure_ascii=False)


def fetch(c, shop: int, nm: int, a, b) -> list[dict]:
    """Топы запросов артикула за период, объединённые по тексту запроса."""
    from .wb import WB, RateLimited, WBError
    acc = c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone()
    wb = WB(c, acc)
    known = access(c, shop)
    lim = (known or {}).get("max_limit") or 100
    out: dict[str, dict] = {}
    tops = TOPS if lim < 100 else TOPS[:2]
    i = 0
    while i < len(tops):
        top = tops[i]
        body = {"currentPeriod": {"start": str(a), "end": str(b)}, "nmIds": [nm], "topOrderBy": top, "includeSubstitutedSKUs": True,
                "includeSearchTexts": True, "orderBy": {"field": top, "mode": "desc"}, "limit": lim}
        try:
            r = wb.call("analytics", PATH, "POST", body=body, max_wait=90) or {}
        except RateLimited:
            raise
        except WBError as e:
            k = _kind(str(e))
            if k == "limit" and lim > 30:          
                lim, tops = 30, TOPS
                continue
            if k in ("no_jam", "no_scope", "limit"):
                _set_access(c, shop, "no_scope" if k == "no_scope" else "no_jam", None, str(e))
                raise RuntimeError(NO_JAM if k != "no_scope" else NO_SCOPE) from None
            raise
        _set_access(c, shop, "ok", lim)
        for x in (r.get("data") or {}).get("items") or []:
            t = (x.get("text") or "").strip()
            if t and t not in out:
                out[t] = {k: (v.get("current") if isinstance(v, dict) and "current" in v else v) for k, v in x.items()
                          if k in ("text", "frequency", "weekFrequency", "avgPosition", "medianPosition", "openCard", "addToCart",
                                   "orders", "visibility")}
        i += 1
    return list(out.values())


NO_JAM = "Для работы вкладки нужен Джем: подключите подписку «Джем» в кабинете WB (Монетизация → Тарифы)."
NO_SCOPE = "У ключа API нет доступа к разделу «Аналитика» — отчёт Джема недоступен. Создайте ключ с этим разделом."

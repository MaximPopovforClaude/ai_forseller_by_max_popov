"""Self-hosted application component."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import psycopg
from fastapi.encoders import jsonable_encoder

from . import db
from .config import today_msk

MSK = ZoneInfo("Europe/Moscow")

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tabcache")   
_BUSY: set = set()
_LOCK = threading.Lock()
BG_TIMEOUT_S = 600



CALC_REVISION = "audit-20261031-1"
CALC_TABS = {"pnl_real_w", "pnl_real_m", "pnl_nm", "fin_sku", "pnl_alt_m", "pnl_alt_nm", "pnl_alt_nm_m",
             "rnp_api", "rnp", "unit_wb", "checklist", "checklist_svod", "oz_dash", "oz_svod",
             "v2_day", "v2_week", "v2_month", "v2_unit", "v2_opiu", "v2_check",
             "dash5", "dash_nm", "dash_nm_days", "dash_group", "home"}
DASHBOARD_TABS = {"dash5", "dash_nm", "dash_nm_days", "dash_group", "home"}


def calculation_version(tab: str, data_version: str) -> str:
    version = f"{data_version}|formula:{CALC_REVISION}" if tab in CALC_TABS else data_version
    if tab in {"oz_dash", "v2_day", "v2_week", "v2_month", "home"}:
        version += "|ozon-order-prices:20261109-1"
    if tab in {"abc", "checklist_svod"}:
        version += "|xyz-orders:20261113-1"
    
    
    return version + "|dashboard:stream-20261101-2" if tab in DASHBOARD_TABS else version




NO_DATA = ["assistant/%", "invite/%", "member/%", "register/%", "user-add/%", "admin/%", "billing/%", "workspace/%", "shop/%",
           "actions/write_token", "actions/reviews", "reviews/%", "competitors/%", "wildbox/%", "compare/%", "staff", "export/%", "kb/%",
           "visual/%", "terms/%", "auth/%", "mcp/%", "claude/%", "actions/questions", "actions/key_split", "mrc/%"]   


def version(c, shop: int) -> str:
    r = c.execute("""SELECT (SELECT coalesce(max(last_ok_at)::text,'') FROM collector_state WHERE account_id=%(s)s) a,
                            (SELECT coalesce(max(built_at)::text,'') FROM agg_state WHERE account_id=%(s)s) b,
                            (SELECT coalesce(max(id),0) FROM audit_log WHERE workspace_id=(SELECT workspace_id FROM accounts WHERE id=%(s)s)
                               AND NOT action LIKE ANY(%(nd)s)
                               AND (details->>'shop' IS NULL OR details->>'shop' = %(s)s::text)) c,
                            (SELECT coalesce(max(updated_at)::text,'') FROM user_prefs WHERE shop_id=%(s)s) p,
                            (SELECT count(*) FROM article_groups WHERE account_id=%(s)s) g""", {"s": shop, "nd": NO_DATA}).fetchone()
    return "|".join(str(v) for v in r.values())


USER_TABS = {"svodwb": "svodwb_layout", "pnl_real_w": "pnl_ads", "pnl_real_m": "pnl_ads"}   
SKIP = {"settings", "exclusions", "mrc", "shelves", "staff", "cost", "oz_cost", "status", "v2_check", "competitors", "comp_monitor", "insights", "rnp", "news", "entry_points", "ext_costs", "promo", "hypotheses", "seo", "jam"}  
NOCACHE = {"jam"}   
MORNING = {"no_cost"}   
NO_COST_DEPENDENCY = {"settings", "exclusions", "mrc", "shelves", "staff", "cost", "oz_cost", "status", "competitors",
                      "comp_monitor", "news", "entry_points", "seo", "jam", "ext_costs", "hypotheses"}


def _ensure_financial_ready(c, shop: int, tab: str) -> None:
    if tab not in NO_COST_DEPENDENCY:
        from .materialize import ensure_cost_ready
        ensure_cost_ready(c, shop)


def _edits(ver: str) -> str:
    return ver.split("|", 2)[-1]       


NO_FILTER = {"pnl_real_w", "pnl_real_m", "pnl_alt_m"}   


def tab_params(c, key: str, shop_id: int, f: dict) -> dict:
    p = {} if key in NO_FILTER else {k: v for k, v in f.items() if k != "user_id"}
    if key in USER_TABS and f.get("user_id") and c.execute("SELECT 1 FROM user_prefs WHERE user_id=%s AND shop_id=%s AND key=%s",
                                                          (f["user_id"], shop_id, USER_TABS[key])).fetchone():
        p["user_id"] = f["user_id"]
    return p


def fkey(params: dict) -> str:
    k = json.dumps(params, default=str, sort_keys=True, ensure_ascii=False)
    if len(k) > 1500:       
        import hashlib
        k = "sha1:" + hashlib.sha1(k.encode()).hexdigest()
    return k


def _store(c, shop: int, tab: str, fk: str, ver: str, res: dict):
    if _readonly(c):            
        with db.connect() as w:
            _store(w, shop, tab, fk, ver, res)
        return
    c.execute("""INSERT INTO tab_cache(account_id,tab,fkey,ver,result,computed_at) VALUES (%s,%s,%s,%s,%s,now())
                 ON CONFLICT (account_id,tab,fkey) DO UPDATE SET ver=EXCLUDED.ver, result=EXCLUDED.result, computed_at=now()""",
              (shop, tab, fk, ver, json.dumps(jsonable_encoder(res), ensure_ascii=False)))
    c.commit()


def _readonly(c) -> bool:
    return c.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"


class ReadOnly(Exception):
    """Вкладке для расчёта нужна запись (догрузка, служебные таблицы), а соединение — «только чтение»."""


def compute_store(c, shop: int, tab: str, params: dict, fn) -> dict:
    """Посчитать сейчас и сохранить (версию берём до расчёта: данные, пришедшие во время расчёта, дадут следующий пересчёт)."""
    ver = calculation_version(tab, version(c, shop))
    
    
    _ensure_financial_ready(c, shop, tab)
    try:
        res = fn(c)
    except psycopg.errors.ReadOnlySqlTransaction:
        c.rollback()
        k = (shop, tab, fkey(params))
        with _LOCK:
            go = k not in _BUSY
            _BUSY.add(k)
        if go:
            _POOL.submit(_bg, shop, tab, params, fn, k)    
        raise ReadOnly(tab) from None
    _ensure_financial_ready(c, shop, tab)
    if not res.get("retry") and not res.get("error"):     
        _store(c, shop, tab, fkey(params), ver, res)
    return res


def _bg(shop: int, tab: str, params: dict, fn, k):
    try:
        with db.connect(timeout_s=BG_TIMEOUT_S) as c:
            
            if not c.execute("SELECT pg_try_advisory_lock(hashtext(%s)) ok", (f"tabcache:{shop}:{tab}:{fkey(params)}",)).fetchone()["ok"]:
                return
            compute_store(c, shop, tab, params, fn)
    except Exception:  
        pass
    finally:
        with _LOCK:
            _BUSY.discard(k)


_MEM: dict = {}       
_MEM_MAX = 12


def get(c, shop: int, tab: str, params: dict, fn) -> dict:
    """fn(c) → результат вкладки. Возвращает результат; у устаревшего — поля stale/cached_at."""
    _ensure_financial_ready(c, shop, tab)
    if tab in NOCACHE:
        return fn(c)
    fk = fkey(params)
    ver_now = calculation_version(tab, version(c, shop))
    hit = _MEM.get((shop, tab, fk))
    if hit and hit[0] == ver_now:
        return hit[1]
    row = c.execute("SELECT ver, result, computed_at FROM tab_cache WHERE account_id=%s AND tab=%s AND fkey=%s", (shop, tab, fk)).fetchone()
    if row and row["ver"] == ver_now:
        if len(_MEM) >= _MEM_MAX:
            _MEM.pop(next(iter(_MEM)))
        _MEM[(shop, tab, fk)] = (ver_now, row["result"])
        return row["result"]
    if row is None:
        return compute_store(c, shop, tab, params, fn)
    if _edits(row["ver"]) != _edits(ver_now):       
        return compute_store(c, shop, tab, params, fn)
    if tab in MORNING and row["computed_at"].astimezone(MSK).date() == today_msk():
        return row["result"]
    if row["computed_at"].astimezone(MSK).date() != today_msk():
        
        return compute_store(c, shop, tab, params, fn)
    k = (shop, tab, fk)
    with _LOCK:
        go = k not in _BUSY
        _BUSY.add(k)
    if go:
        _POOL.submit(_bg, shop, tab, params, fn, k)
    return {**row["result"], "stale": True, "cached_at": row["computed_at"].isoformat()}


def precompute(c, shop: int, log=print) -> None:
    """Утренний предпросчёт магазина: вкладки с фильтрами по умолчанию (как открывает сайт: 30 дней, все артикулы),
    своя раскладка Сводной WB — для каждого, у кого она есть, РНП — текущий месяц. Ошибка одной вкладки не останавливает остальные."""
    import time
    from datetime import timedelta
    from . import rnp
    from .config import today_msk
    from .materialize import NotReady
    from .tabs import tabs_for
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    dt = today_msk()
    if mp == "wb":
        _jam_prefetch(c, shop, log)
        try:
            from .sheets import pnl_alt
            pnl_alt.precompute(c, shop, log)      
        except Exception as e:  
            c.rollback()
            log(f"  ✗ альт PnL: {type(e).__name__}: {str(e)[:150]}")
    jobs = []
    for key, _, _, fn in tabs_for(mp):
        if key in SKIP:
            continue
        users = [None]
        if key in USER_TABS:
            users += [r["user_id"] for r in c.execute("SELECT user_id FROM user_prefs WHERE shop_id=%s AND key=%s", (shop, USER_TABS[key]))]
        for uid in users:
            f = {"date_from": dt - timedelta(days=29), "date_to": dt, "nm_ids": None, "group": None, "user_id": uid}
            jobs.append((key, tab_params(c, key, shop, f), (lambda fn, f: lambda cc: fn(cc, shop, f))(fn, f)))
    if mp == "wb":
        m, flt = dt.replace(day=1), {"group": None, "brand": None, "subject": None, "nm_ids": None}
        jobs.append(("rnp_api", {"month": m.isoformat(), "sort": "orders_sum", "offset": 0, **flt},
                     lambda cc: rnp.compute(cc, shop, m, flt, "orders_sum", 0)))
    for key, params, fn in jobs:
        t = time.time()
        try:
            compute_store(c, shop, key, params, fn)
            log(f"  {key}: {time.time() - t:.1f} с")
        except NotReady:
            c.rollback()
            log(f"  {key}: итоги ещё не готовы")
        except Exception as e:  
            c.rollback()
            log(f"  ✗ {key}: {type(e).__name__}: {str(e)[:150]}")
    c.execute("DELETE FROM tab_cache WHERE account_id=%s AND computed_at < now() - interval '3 days'", (shop,))
    c.commit()


JAM_TOP = 15


def _jam_prefetch(c, shop: int, log=print):
    """Утром: Джем за 30 дней для топ-артикулов по заказам (если подписка есть и свежего отчёта нет) — для Джема и потенциалов
    в «Сводном чек-листе». Лимит WB — 3 запроса в минуту, поэтому только топ JAM_TOP."""
    import json
    import time
    from datetime import timedelta
    from . import jam
    from .config import today_msk
    acc = jam.access(c, shop)
    if not acc or acc["status"] != "ok":
        return
    b = today_msk()                  
    a = b - timedelta(days=29)
    top = [r["nm_id"] for r in c.execute(
        """SELECT d.nm_id FROM agg_nm_day d WHERE d.account_id=%s AND d.day > current_date - 30
           AND NOT EXISTS (SELECT 1 FROM jam_cache j WHERE j.account_id=d.account_id AND j.nm_id=d.nm_id AND j.state='done'
                           AND j.date_to=%s AND j.fetched_at > now() - interval '2 hours')
           GROUP BY 1 ORDER BY sum((d.data->>'orders')::numeric) DESC NULLS LAST LIMIT %s""", (shop, b, JAM_TOP))]
    from .exclusions import excluded
    ex = excluded(c, shop)
    for nm in [x for x in top if x not in ex]:
        t0 = time.time()
        try:
            items = jam.fetch(c, shop, nm, a, b)
            c.execute("""INSERT INTO jam_cache(account_id,nm_id,date_from,date_to,state,items,fetched_at,started_at) VALUES (%s,%s,%s,%s,'done',%s,now(),now())
                         ON CONFLICT (account_id,nm_id,date_from,date_to) DO UPDATE SET state='done', items=EXCLUDED.items, fetched_at=now(), error=NULL""",
                      (shop, nm, a, b, json.dumps(items, ensure_ascii=False)))
            c.commit()
            log(f"  Джем {nm}: {len(items)} запросов, {time.time() - t0:.0f} с")
        except Exception as e:  
            c.rollback()
            log(f"  Джем {nm}: {type(e).__name__}: {str(e)[:100]}")
            if "Джем" in str(e) or "подписк" in str(e):
                return

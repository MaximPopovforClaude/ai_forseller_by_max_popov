"""Материализация агрегатов: agg_nm_day (артикул × день) и agg_real_week (БД#РеализацияПонедельно).

После каждого круга сбора: артикул×день — за последние RECENT_DAYS (WB правит задним числом), отчёт реализации — целиком,
если пришли новые строки. Раз в сутки (ночью) — полная пересборка артикула×дня за всю историю.
Вкладки читают готовое (nm_day.cached / real_week.cached); если покрытия нет — считают на лету.
"""

import json
from datetime import date, timedelta

from .agg import nm_day, real_week
from .config import today_msk

RECENT_DAYS = 45
BIG_SHOP = 1000          


class NotReady(RuntimeError):
    """Большой магазин: готовые итоги ещё считаются — вкладка покажет сообщение вместо долгого расчёта."""


def mark_cost_dirty(c, acc_id: int, valid_from: date) -> None:
    """Durable WB rebuild request in the same transaction as the manual edit.

    The regular collector drains it; no subprocess, raw-data deletion or full HTTP
    recomputation. Revision prevents a concurrent edit being acknowledged by an
    older in-flight rebuild. The earliest dirty date survives repeated edits.
    """
    from uuid import uuid4
    revision = uuid4().hex
    cursor = json.dumps({"from": valid_from.isoformat(), "revision": revision})
    c.execute("""INSERT INTO collector_state(account_id,collector,cursor)
                 SELECT id,'_cost_rebuild',%s::jsonb FROM accounts WHERE id=%s AND marketplace='wb'
                 ON CONFLICT (account_id,collector) DO UPDATE SET cursor=jsonb_build_object(
                   'from',least(coalesce(collector_state.cursor->>'from',EXCLUDED.cursor->>'from'),EXCLUDED.cursor->>'from'),
                   'revision',EXCLUDED.cursor->>'revision')""", (cursor, acc_id))
    from .ai_tasks import invalidate_outcomes
    invalidate_outcomes(c, acc_id, revision)
    from .insights import invalidate_cost
    invalidate_cost(c, acc_id, revision)


def cost_dirty(c, acc_id: int) -> dict | None:
    r = c.execute("SELECT cursor FROM collector_state WHERE account_id=%s AND collector='_cost_rebuild'", (acc_id,)).fetchone()
    return (r["cursor"] or None) if r else None


def ensure_cost_ready(c, acc_id: int) -> None:
    if cost_dirty(c, acc_id):
        raise NotReady("Себестоимость или налоги сохранены. Пересчитываем зависимые итоги; они появятся после ближайшего успешного цикла сбора.")


def ensure_ready(c, acc_id: int, covered: bool):
    if covered:
        return
    n = c.execute("SELECT count(*) n FROM nomenclature WHERE account_id=%s", (acc_id,)).fetchone()["n"]
    if n > BIG_SHOP:
        raise NotReady(f"В магазине {n:,} артикулов".replace(",", " ") + " — в связи с большим объёмом данные на этой вкладке появятся "
                       "позже: сервис досчитывает итоги (обычно ночью). Остальные вкладки и сводки работают.")
SHORT_DAYS = 10


def _first_day(c, acc_id) -> date:
    
    r = c.execute("""SELECT least((SELECT min(order_dt)::date FROM orders WHERE account_id=%(a)s),
                                  (SELECT min(row_date) FROM raw_rows WHERE account_id=%(a)s AND source='ad_stats'),
                                  (SELECT min(row_date) FROM raw_rows WHERE account_id=%(a)s AND source='funnel_day'),
                                  (SELECT min(row_date) FROM raw_rows WHERE account_id=%(a)s AND source='realization')) AS d""",
                  {"a": acc_id}).fetchone()
    hf = c.execute("SELECT history_from FROM accounts WHERE id=%s", (acc_id,)).fetchone()["history_from"]
    d = r["d"] or today_msk() - timedelta(days=30)
    return max(d, hf) if hf else d


def build_nm_day(c, acc_id: int, df: date | None = None, dt: date | None = None) -> int:
    c.execute("SELECT pg_advisory_lock(%s)", (880000 + acc_id,))   
    try:
        return _build_nm_day(c, acc_id, df, dt)
    finally:
        c.rollback()
        c.execute("SELECT pg_advisory_unlock(%s)", (880000 + acc_id,))
        c.commit()


def _build_nm_day(c, acc_id: int, df: date | None, dt: date | None) -> int:
    dt = dt or today_msk()
    df = df or _first_day(c, acc_id)
    n = 0
    cur = df
    
    
    arts = c.execute("SELECT count(*) n FROM nomenclature WHERE account_id=%s", (acc_id,)).fetchone()["n"] or 1
    step = max(1, min(60, 40000 // arts))
    while cur <= dt:
        end = min(dt, cur + timedelta(days=step - 1))
        rows = nm_day.compute(c, acc_id, cur, end)
        c.execute("DELETE FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s", (acc_id, cur, end))
        with c.cursor() as cur_:
            cur_.executemany("INSERT INTO agg_nm_day(account_id,nm_id,day,data) VALUES (%s,%s,%s,%s)",
                             ((acc_id, r["nm_id"], r["day"], json.dumps(r, default=_j, ensure_ascii=False)) for r in rows))
        c.commit()
        n += len(rows)
        del rows
        cur = end + timedelta(days=1)
    st = c.execute("SELECT * FROM agg_state WHERE account_id=%s AND name='nm_day'", (acc_id,)).fetchone()
    lo = min(df, st["covered_from"]) if st and st["covered_from"] else df
    c.execute("""INSERT INTO agg_state(account_id,name,covered_from,covered_to,built_at) VALUES (%s,'nm_day',%s,%s,now())
                 ON CONFLICT (account_id,name) DO UPDATE SET covered_from=EXCLUDED.covered_from, covered_to=EXCLUDED.covered_to, built_at=now()""",
              (acc_id, lo, dt))
    c.commit()
    return n


def build_real_week(c, acc_id: int) -> int:
    
    c.execute("SELECT pg_advisory_lock(%s)", (880000 + acc_id,))
    try:
        return _build_real_week(c, acc_id)
    finally:
        c.rollback()
        c.execute("SELECT pg_advisory_unlock(%s)", (880000 + acc_id,))
        c.commit()


def _build_real_week(c, acc_id: int) -> int:
    groups = real_week.compute(c, acc_id)
    c.execute("DELETE FROM agg_real_week WHERE account_id=%s", (acc_id,))
    with c.cursor() as cur:
        cur.executemany("INSERT INTO agg_real_week(account_id,seq,date_from,data) VALUES (%s,%s,%s,%s)",
                        ((acc_id, i, g["date_from"], json.dumps(g, default=_j, ensure_ascii=False)) for i, g in enumerate(groups)))
    c.execute("""INSERT INTO agg_state(account_id,name,built_at) VALUES (%s,'real_week',now())
                 ON CONFLICT (account_id,name) DO UPDATE SET built_at=now()""", (acc_id,))
    c.commit()
    return len(groups)


def _j(o):
    if isinstance(o, date):
        return o.isoformat()
    return float(o)


def after_collect(c, acc_id: int, ran: set[str]) -> dict:
    out = {}
    st = c.execute("SELECT * FROM agg_state WHERE account_id=%s AND name='nm_day'", (acc_id,)).fetchone()
    full = st is None or st["built_at"].date() < today_msk()      
    from . import loadplan
    shallow = full and loadplan.shallow(c, acc_id)
    deep = bool(ran & {"realization", "realization_daily", "ad_upd", "paid_storage", "acceptance", "funnel_days"})
    normal_from = (today_msk() - timedelta(days=loadplan.SHALLOW_DAYS) if shallow else
                   None if full else today_msk() - timedelta(days=RECENT_DAYS if deep else SHORT_DAYS))
    dirty = cost_dirty(c, acc_id)
    if dirty:
        first = _first_day(c, acc_id)
        
        start = max(min(date.fromisoformat(dirty["from"]), normal_from or first), first)
        out["nm_day"] = build_nm_day(c, acc_id, start)
        out["real_week"] = build_real_week(c, acc_id)
        c.execute("""UPDATE collector_state SET cursor='{}'::jsonb
                     WHERE account_id=%s AND collector='_cost_rebuild' AND cursor->>'revision'=%s""",
                  (acc_id, dirty["revision"]))
        c.commit()
        return out
    if shallow:                       
        out["nm_day"] = build_nm_day(c, acc_id, normal_from)
        if not c.execute("SELECT 1 FROM agg_state WHERE account_id=%s AND name='real_week'", (acc_id,)).fetchone():
            out["real_week"] = "ночью"
        return out
    
    out["nm_day"] = build_nm_day(c, acc_id, normal_from)
    
    rw = c.execute("SELECT built_at FROM agg_state WHERE account_id=%s AND name='real_week'", (acc_id,)).fetchone()
    if "realization" in ran or "realization_daily" in ran or not rw or rw["built_at"].date() < today_msk():
        out["real_week"] = build_real_week(c, acc_id)
    return out

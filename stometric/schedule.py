"""Расписание сборщиков: таймер дёргает `collect-due` раз в 10 минут, здесь — кому пора (контур 1 LOOPS).

Интервалы — по частоте обновления данных у WB и лимитам; сборщик, упёршийся в лимит, просто ждёт следующего круга.
"""

from datetime import datetime, timedelta, timezone

EVERY_MIN = {
    "orders": 30, "sales": 30, "stocks_wb": 60, "stocks_seller": 60, "stocks_wh": 60, "stocks_report": 12 * 60, "prices": 120,
    "funnel": 120, "funnel_days": 120, "adverts": 60, "ad_stats": 60, "ad_upd": 6 * 60, "ad_kw": 60, "ad_kw_lists": 6 * 60, "nomenclature": 3 * 60, "tariffs": 24 * 60, "realization": 12 * 60, "realization_daily": 3 * 60, "paid_storage": 12 * 60, "acceptance": 12 * 60,
    "feedbacks": 10,   
    "questions": 10,   
    "promotions": 6 * 60,   
    "item_rating": 3 * 60,   
}


BACKFILL = {"funnel_days", "paid_storage", "acceptance", "ad_kw"}


def due(c, account_id: int) -> list[str]:
    st = {r["collector"]: r for r in c.execute(
        "SELECT collector,last_run_at,cursor FROM collector_state WHERE account_id=%s", (account_id,)).fetchall()}
    now = datetime.now(timezone.utc)
    out = []
    from . import loadplan
    big = loadplan.is_big(c, account_id)
    for name, mins in EVERY_MIN.items():
        last = st.get(name, {}).get("last_run_at")
        cur = st.get(name, {}).get("cursor") or {}
        if name == "ad_stats":
            
            
            if cur.get("fresh") or (cur.get("stats_version") == 2 and not cur.get("backfilled") and (not big or loadplan.night())):
                out.append(name)
                continue
            if big and cur.get("deep_running") and not loadplan.night():
                if last is None or now - last >= timedelta(minutes=mins - 2):
                    out.append(name)
                continue
        if big and cur.get("deep_running") and not loadplan.night():
            continue                  
        if big and cur.get("deep_pending") and loadplan.night():
            out.append(name)          
            continue
        if big and cur.get("deep_running"):
            out.append(name)
            continue
        if name in BACKFILL and not cur.get("backfilled"):   
            out.append(name)
            continue
        if cur.get("offset"):         
            out.append(name)
            continue
        if last is None or now - last >= timedelta(minutes=mins) - timedelta(minutes=2):
            out.append(name)
    return out

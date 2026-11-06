"""Self-hosted application component."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BIG_SHOP = 1000                   
SHALLOW_DAYS = 60
NIGHT_FROM, NIGHT_TO = 0, 7       
DEEP = {"ad_stats", "ad_upd", "ad_kw", "funnel_days", "paid_storage", "acceptance", "realization"}   
MULTI_RUN = {"funnel_days", "ad_kw"}                                   
_BIG: dict[int, tuple[float, bool]] = {}


def is_big(c, acc_id: int) -> bool:
    import time
    hit = _BIG.get(acc_id)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    n = c.execute("SELECT count(*) n FROM nomenclature WHERE account_id=%s", (acc_id,)).fetchone()["n"]
    _BIG[acc_id] = (time.time(), n > BIG_SHOP)
    return n > BIG_SHOP


def night() -> bool:
    h = datetime.now(ZoneInfo("Europe/Moscow")).hour
    return NIGHT_FROM <= h < NIGHT_TO


def shallow(c, acc_id: int) -> bool:
    """Сейчас грузим/считаем по-дневному (только свежая история)?"""
    return is_big(c, acc_id) and not night()


def since(today, days: int, c=None, acc_id: int | None = None, force_shallow: bool | None = None):
    """Начало истории: днём у большого магазина — не глубже SHALLOW_DAYS."""
    sh = force_shallow if force_shallow is not None else (c is not None and acc_id is not None and shallow(c, acc_id))
    return today - timedelta(days=min(days, SHALLOW_DAYS) if sh else days)

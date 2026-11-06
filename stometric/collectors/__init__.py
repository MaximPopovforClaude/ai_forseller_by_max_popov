"""Сборщики данных WB. Каждый: run(ctx) → dict-итог; состояние (курсор) — в collector_state, сырьё — архив + upsert."""

import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

from ..wb import WB, RateLimited

TAIL_HOURS = 6     


@dataclass
class Ctx:
    c: object           
    acc: dict           
    wb: WB
    shallow: bool = False   

    def depth(self, days: int) -> int:
        from ..config import today_msk
        from ..loadplan import SHALLOW_DAYS
        d = min(days, SHALLOW_DAYS) if self.shallow else days
        hf = self.acc.get("history_from")          
        return min(d, max(0, (today_msk() - hf).days)) if hf else d

    def state(self, name: str) -> dict:
        r = self.c.execute("SELECT cursor FROM collector_state WHERE account_id=%s AND collector=%s",
                           (self.acc["id"], name)).fetchone()
        return r["cursor"] if r else {}

    def tail(self, name: str, hours: float = TAIL_HOURS) -> tuple[bool, str | None]:
        """Self-hosted application component."""
        t = self.state(name).get("tail_at")
        now = datetime.now(timezone.utc)
        due = not t or (now - datetime.fromisoformat(t)).total_seconds() >= hours * 3600 - 300
        return due, now.isoformat() if due else t

    def save_state(self, name: str, cursor: dict | None = None, ok: bool = True, error: str | None = None):
        self.c.execute(
            """INSERT INTO collector_state(account_id,collector,cursor,last_ok_at,last_error,last_run_at)
               VALUES (%s,%s,COALESCE(%s::jsonb,'{}'::jsonb),%s,%s,now())
               ON CONFLICT (account_id,collector) DO UPDATE SET
                 cursor=CASE WHEN %s THEN EXCLUDED.cursor ELSE collector_state.cursor END,
                 last_ok_at=COALESCE(EXCLUDED.last_ok_at, collector_state.last_ok_at),
                 last_error=EXCLUDED.last_error, last_run_at=now()""",
            (self.acc["id"], name, json.dumps(cursor) if cursor is not None else None,
             datetime.now(timezone.utc) if ok else None, error, cursor is not None))
        self.c.commit()


def registry():
    from . import content, prices, statistics, stocks, advert, finance, funnel, reports, feedbacks, questions
    return {
        "nomenclature": content.run,
        "tariffs": content.run_tariffs,
        "prices": prices.run,
        "orders": statistics.run_orders,
        "sales": statistics.run_sales,
        "stocks_wb": stocks.run_wb,
        "stocks_seller": stocks.run_seller,
        "stocks_report": stocks.run_report_products,
        "adverts": advert.run_adverts,
        "ad_stats": advert.run_stats,
        "ad_upd": advert.run_upd,
        "ad_kw": advert.run_kw,
        "ad_kw_lists": advert.run_kw_lists,
        "realization": finance.run,
        "realization_daily": finance.run_daily,
        "funnel": funnel.run,
        "funnel_days": funnel.run_days,
        "paid_storage": reports.run_storage,
        "acceptance": reports.run_acceptance,
        "stocks_wh": reports.run_warehouse_remains,
        "feedbacks": feedbacks.run,
        "item_rating": feedbacks.run_rating,
        "questions": questions.run,
        "promotions": prices.run_promotions,
    }


def run_one(ctx: Ctx, name: str) -> dict:
    fn = registry()[name]
    
    lock = ctx.c.execute("SELECT pg_try_advisory_lock(hashtext(%s)) ok", (f"collect:{ctx.acc['id']}:{name}",)).fetchone()["ok"]
    if not lock:
        return {"collector": name, "ok": False, "skipped": "уже выполняется в другом процессе"}
    try:
        return _run(ctx, name, fn)
    finally:
        ctx.c.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"collect:{ctx.acc['id']}:{name}",))
        ctx.c.commit()


def _run(ctx: Ctx, name: str, fn) -> dict:
    from .. import loadplan
    ctx.shallow = False
    if name in loadplan.DEEP and loadplan.is_big(ctx.c, ctx.acc["id"]):
        cur0 = ctx.state(name)
        if not loadplan.night():
            ctx.shallow = True                      
        elif cur0.get("deep_pending") and name != "ad_stats":              
            ctx.save_state(name, {"deep_running": True})
    try:
        res = fn(ctx)
        cur = res.pop("cursor", None)
        if isinstance(cur, dict) and name in loadplan.DEEP and loadplan.is_big(ctx.c, ctx.acc["id"]):
            cur = dict(cur)
            if ctx.shallow and name != "ad_stats":
                cur["deep_pending"] = True
            elif name in loadplan.MULTI_RUN and not cur.get("backfilled") and ctx.state(name).get("deep_running"):
                cur["deep_running"] = True
        ctx.save_state(name, cur, ok=True)
        return {"collector": name, "ok": True, **({"shallow": True} if ctx.shallow else {}), **res}
    except RateLimited as e:
        ctx.c.rollback()
        ctx.save_state(name, None, ok=False, error=str(e))
        return {"collector": name, "ok": False, "rate_limited": True, "error": str(e)}
    except Exception as e:  
        ctx.c.rollback()
        ctx.save_state(name, None, ok=False, error=f"{type(e).__name__}: {e}"[:1000])
        return {"collector": name, "ok": False, "error": f"{type(e).__name__}: {e}"[:500], "trace": traceback.format_exc()[-1500:]}

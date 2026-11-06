"""Детализация отчётов реализации (finance-api, данные с 29.01.2024) — основа PnL.

Первый запуск — вся история по месяцам с 2024-01-29; дальше — последние OVERLAP_DAYS (новые недельные отчёты и поправки).
Пагинация — rrdId последней строки. Поле ИНН покупателя-юрлица не храним (может быть ИП = физлицо, 152-ФЗ).
"""

from ..config import today_msk
from datetime import date, timedelta

from . import raw

START = date(2024, 1, 29)
OVERLAP_DAYS = 21
DAILY_DAYS = 14
DROP = {"b2bCustomerTin", "buyerTaxRegistrationReasonCode"}


def _month_windows(frm: date, to: date):
    cur = frm
    while cur <= to:
        nxt = min(to, (cur.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1))
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def run(ctx) -> dict:
    st = ctx.state("realization")
    today = today_msk()
    frm = date.fromisoformat(st["done_to"]) - timedelta(days=OVERLAP_DAYS) if st.get("done_to") else\
        (today - timedelta(days=ctx.depth(10 ** 5)) if getattr(ctx, "shallow", False) else START)   
    n = 0
    for beg, end in _month_windows(max(frm, START, ctx.acc.get("history_from") or START), today):
        rrd = 0
        while True:
            body = {"dateFrom": beg.isoformat(), "dateTo": end.isoformat(), "limit": 100000, "rrdId": rrd, "period": "weekly"}
            rows = ctx.wb.call("finance", "/api/finance/v1/sales-reports/detailed", "POST", body=body, max_wait=200) or []
            for r in rows:
                clean = {k: v for k, v in r.items() if k not in DROP}
                raw.put(ctx, "realization", str(r["rrdId"]), (r.get("rrDate") or r.get("dateTo") or "")[:10] or None, clean)
            ctx.c.commit()
            n += len(rows)
            if len(rows) < 100000:
                break
            rrd = rows[-1]["rrdId"]
        ctx.save_state("realization", {**st, "done_to": end.isoformat()})
    
    gap = (ctx.state("realization") or {}).get("gap")
    from ..loadplan import night
    while gap and night():
        g0, g1 = date.fromisoformat(gap[0]), date.fromisoformat(gap[1])
        beg = max(g0, g1.replace(day=1))
        n += _load(ctx, beg, g1)
        nxt = beg - timedelta(days=1)
        gap = None if nxt < g0 else [gap[0], nxt.isoformat()]
        cur = ctx.state("realization") or {}
        cur.pop("gap", None)
        ctx.save_state("realization", {**cur, **({"gap": gap} if gap else {})})
    return {"rows": n, "cursor": {"done_to": today.isoformat()}}


def _load(ctx, beg: date, end: date) -> int:
    n, rrd = 0, 0
    while True:
        body = {"dateFrom": beg.isoformat(), "dateTo": end.isoformat(), "limit": 100000, "rrdId": rrd, "period": "weekly"}
        rows = ctx.wb.call("finance", "/api/finance/v1/sales-reports/detailed", "POST", body=body, max_wait=200) or []
        for r in rows:
            raw.put(ctx, "realization", str(r["rrdId"]), (r.get("rrDate") or r.get("dateTo") or "")[:10] or None,
                    {k: v for k, v in r.items() if k not in DROP})
        ctx.c.commit()
        n += len(rows)
        if len(rows) < 100000:
            return n
        rrd = rows[-1]["rrdId"]


def run_daily(ctx) -> dict:
    """Ежедневные детализации (period=daily) за последние DAILY_DAYS — приходят раньше недельного отчёта: по ним
    логистика и эквайринг «свежих» дней (эталон берёт их же). Хранятся отдельно: source=realization_daily."""
    today = today_msk()
    beg = today - timedelta(days=DAILY_DAYS)
    rrd, n = 0, 0
    while True:
        body = {"dateFrom": beg.isoformat(), "dateTo": today.isoformat(), "limit": 100000, "rrdId": rrd, "period": "daily"}
        rows = ctx.wb.call("finance", "/api/finance/v1/sales-reports/detailed", "POST", body=body, max_wait=200) or []
        for r in rows:
            clean = {k: v for k, v in r.items() if k not in DROP}
            raw.put(ctx, "realization_daily", str(r["rrdId"]), (r.get("rrDate") or "")[:10] or None, clean)
        ctx.c.commit()
        n += len(rows)
        if len(rows) < 100000:
            break
        rrd = rows[-1]["rrdId"]
    return {"rows": n}

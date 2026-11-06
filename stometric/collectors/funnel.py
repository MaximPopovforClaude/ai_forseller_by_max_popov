"""Воронка по артикулам по дням (просмотры карточки, корзины, заказы, выкупы) — WB отдаёт только последнюю неделю,
поэтому забираем каждый раз всю неделю по всем nmId и копим (по 20 артикулов за запрос, лимит 3/мин)."""

from ..config import today_msk
from datetime import date, timedelta

from . import raw


MAX_REQ_PER_RUN = 15    


def run(ctx) -> dict:
    from ..exclusions import excluded
    ex = excluded(ctx.c, ctx.acc["id"])
    st = ctx.state("funnel")
    
    
    weekly = not st.get("full_on") or (today_msk() - date.fromisoformat(st["full_on"])).days >= 7
    full = weekly and not st.get("offset") or st.get("full_pass")
    if full:
        q = "SELECT nm_id FROM nomenclature WHERE account_id=%(a)s ORDER BY nm_id"
    else:
        q = """SELECT nm_id FROM nomenclature n WHERE account_id=%(a)s AND (
                 EXISTS (SELECT 1 FROM orders o WHERE o.account_id=n.account_id AND o.nm_id=n.nm_id AND o.order_dt > now() - interval '60 days')
                 OR EXISTS (SELECT 1 FROM stocks_wb_snap w WHERE w.account_id=n.account_id AND w.nm_id=n.nm_id AND w.quantity > 0
                            AND w.snap_at = (SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=n.account_id))
                 OR EXISTS (SELECT 1 FROM stocks_seller_snap w WHERE w.account_id=n.account_id AND w.nm_id=n.nm_id AND w.quantity > 0
                            AND w.snap_at = (SELECT max(snap_at) FROM stocks_seller_snap WHERE account_id=n.account_id))
               ) ORDER BY nm_id"""
    nms = [r["nm_id"] for r in ctx.c.execute(q, {"a": ctx.acc["id"]}).fetchall() if r["nm_id"] not in ex]
    end = today_msk()
    beg = end - timedelta(days=6)
    n = 0
    start = int(st.get("offset") or 0)
    if start >= len(nms):
        start = 0
    stop = min(len(nms), start + 20 * MAX_REQ_PER_RUN)
    for i in range(start, stop, 20):
        body = {"selectedPeriod": {"start": beg.isoformat(), "end": end.isoformat()}, "nmIds": nms[i:i + 20],
                "skipDeletedNm": False, "aggregationLevel": "day"}
        data = ctx.wb.call("analytics", "/api/analytics/v3/sales-funnel/products/history", "POST", body=body) or []
        for prod in data:
            nm = prod["product"]["nmId"]
            for h in prod.get("history") or []:
                d = h["date"][:10]
                raw.put(ctx, "funnel", f"{nm}|{d}", d, {"nmId": nm, **h})
                n += 1
        ctx.c.commit()
    nxt = stop if stop < len(nms) else 0
    cur = {"offset": nxt, "full_on": st.get("full_on")}
    if full:
        cur["full_pass"] = bool(nxt)               
        if not nxt:
            cur["full_on"] = str(today_msk())
    return {"nm": stop - start, "of": len(nms), "day_rows": n, "full": bool(full), "cursor": cur}


BACKFILL_PER_RUN = 45   


def run_days(ctx) -> dict:
    """Воронка по дням за год (sales-funnel/products: отчёт за один день = период start=end; до 365 дней назад, 1000 карточек
    за запрос). Даёт переходы в карточку, корзины, заказы, отложенные, рейтинг по отзывам, долю локальных заказов, время
    доставки — то, чего нет в /history (там только неделя). Догрузка — назад от вчера, по дню; дальше — последние 7 дней."""
    st = ctx.state("funnel_days")
    today = today_msk()
    tail_at = st.get("tail_at")
    if st.get("backfilled"):
        full, tail_at = ctx.tail("funnel_days")     
        days = [today - timedelta(days=i) for i in range(0, 8 if full else 2)]
    else:
        start = date.fromisoformat(st["done_back_to"]) - timedelta(days=1) if st.get("done_back_to") else today
        days = [start - timedelta(days=i) for i in range((start - (today - timedelta(days=ctx.depth(364)))).days + 1)][:BACKFILL_PER_RUN]
    n = 0
    for d in days:
        offset = 0
        while True:
            body = {"selectedPeriod": {"start": d.isoformat(), "end": d.isoformat()}, "nmIds": [], "skipDeletedNm": False,
                    "limit": 1000, "offset": offset}
            data = ctx.wb.call("analytics", "/api/analytics/v3/sales-funnel/products", "POST", body=body, max_wait=60) or {}
            prods = (data.get("data") or {}).get("products") or []
            
            
            seen = {r["row_key"]: r["data"] for r in ctx.c.execute(
                "SELECT row_key, data FROM raw_rows WHERE account_id=%s AND source='funnel_day' AND row_date=%s", (ctx.acc["id"], d))}
            for p in prods:
                s = (p.get("statistic") or {}).get("selected") or {}
                pr = p.get("product") or {}
                key = f"{pr.get('nmId')}|{d}"
                old = seen.get(key) or {}
                rating = {k: old[k] if old.get(k) is not None else pr.get(k) for k in ("productRating", "feedbackRating")}
                raw.put(ctx, "funnel_day", key, d, {"nmId": pr.get("nmId"), **rating, "stocks": pr.get("stocks"), **s})
            ctx.c.commit()
            n += len(prods)
            if len(prods) < 1000:
                break
            offset += 1000
        if not st.get("backfilled"):
            ctx.save_state("funnel_days", {"done_back_to": d.isoformat()})
    done = st.get("backfilled") or not days or days[-1] <= today - timedelta(days=ctx.depth(364))
    return {"day_rows": n, "days": len(days),
            "cursor": {"backfilled": True, "tail_at": tail_at} if done else {"done_back_to": days[-1].isoformat()}}

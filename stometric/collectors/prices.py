"""Цены и скидки продавца — снимок (история цен копится у нас)."""

import json

from .. import history
from datetime import datetime, timezone


def run(ctx) -> dict:
    snap = datetime.now(timezone.utc).replace(microsecond=0)
    offset, n = 0, 0
    while True:
        data = ctx.wb.call("prices", "/api/v2/list/goods/filter", params={"limit": 1000, "offset": offset})
        goods = ((data or {}).get("data") or {}).get("listGoods") or []
        for g in goods:
            for s in g.get("sizes") or []:
                ctx.c.execute(
                    """INSERT INTO prices_snap(account_id,snap_at,nm_id,size_id,price,discount,discounted_price,club_discounted_price,data)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (ctx.acc["id"], snap, g["nmID"], s["sizeID"], s.get("price"), g.get("discount"), s.get("discountedPrice"),
                     s.get("clubDiscountedPrice"), json.dumps({**{k: v for k, v in g.items() if k != "sizes"}, "size": s}, ensure_ascii=False)))
        ctx.c.commit()
        n += len(goods)
        if len(goods) < 1000:
            break
        offset += 1000
    changes = history.price_diff(ctx.c, ctx.acc["id"], snap)
    ctx.c.commit()
    return {"goods": n, "snap_at": snap.isoformat(), "changes": changes}


def run_promotions(ctx) -> dict:
    """Календарь акций WB: акции на 30 дней вперёд и товары каждой — участвует / может участвовать, цена для участия (planPrice).
    Только чтение (Расчёт акций, видео 10X №16). Автоакции товары по API не отдают — для них только сама акция."""
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  
    lst = ((ctx.wb.call("calendar", "/api/v1/calendar/promotions", params={
        "startDateTime": fmt(now - timedelta(days=1)), "endDateTime": fmt(now + timedelta(days=30)), "allPromo": "true", "limit": 1000}) or {})
        .get("data") or {}).get("promotions") or []
    ids = [p["id"] for p in lst]
    det = {}
    for i in range(0, len(ids), 100):
        for d in ((ctx.wb.call("calendar", "/api/v1/calendar/promotions/details", params=[("promotionIDs", x) for x in ids[i:i + 100]]) or {})
                  .get("data") or {}).get("promotions") or []:
            det[d["id"]] = d
    items = 0
    for p in lst:
        d = det.get(p["id"]) or p
        ctx.c.execute("""INSERT INTO wb_promotions(account_id,promo_id,name,kind,start_at,end_at,data,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                         ON CONFLICT (account_id,promo_id) DO UPDATE SET name=EXCLUDED.name, kind=EXCLUDED.kind, start_at=EXCLUDED.start_at,
                         end_at=EXCLUDED.end_at, data=EXCLUDED.data, updated_at=now()""",
                      (ctx.acc["id"], p["id"], p.get("name"), p.get("type"), p.get("startDateTime"), p.get("endDateTime"),
                       json.dumps(d, ensure_ascii=False)))
        if p.get("type") == "auto":
            continue
        was = {r["nm_id"]: r["in_action"] for r in ctx.c.execute(
            "SELECT nm_id, in_action FROM wb_promo_items WHERE account_id=%s AND promo_id=%s", (ctx.acc["id"], p["id"]))}
        for in_action in (True, False):
            off = 0
            while True:
                r = ((ctx.wb.call("calendar", "/api/v1/calendar/promotions/nomenclatures", params={
                    "promotionID": p["id"], "inAction": str(in_action).lower(), "limit": 1000, "offset": off}) or {}).get("data") or {}).get("nomenclatures") or []
                for x in r:
                    ctx.c.execute("""INSERT INTO wb_promo_items(account_id,promo_id,nm_id,in_action,price,discount,plan_price,plan_discount,updated_at)
                                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (account_id,promo_id,nm_id) DO UPDATE SET
                                     in_action=EXCLUDED.in_action, price=EXCLUDED.price, discount=EXCLUDED.discount, plan_price=EXCLUDED.plan_price,
                                     plan_discount=EXCLUDED.plan_discount, updated_at=now()""",
                                  (ctx.acc["id"], p["id"], x.get("id"), x.get("inAction", in_action), x.get("price"), x.get("discount"),
                                   x.get("planPrice"), x.get("planDiscount")))
                items += len(r)
                for x in r:                     
                    now_in = bool(x.get("inAction", in_action))
                    if (x.get("id") in was and bool(was[x["id"]]) != now_in) or (was and x.get("id") not in was and now_in):
                        _promo_change(ctx, x["id"], p, now_in)
                    if now_in and _running(p, now):
                        _promo_day(ctx, x["id"], p.get("name"))
                if len(r) < 1000:
                    break
                off += 1000
    
    for r in ctx.c.execute("""SELECT i.nm_id, p.promo_id, p.name FROM wb_promo_items i JOIN wb_promotions p ON p.account_id=i.account_id
                              AND p.promo_id=i.promo_id WHERE i.account_id=%s AND i.in_action AND p.end_at < now()""", (ctx.acc["id"],)).fetchall():
        _promo_change(ctx, r["nm_id"], {"id": r["promo_id"], "name": r["name"]}, False, ended=True)
        ctx.c.execute("UPDATE wb_promo_items SET in_action=false WHERE account_id=%s AND promo_id=%s AND nm_id=%s",
                      (ctx.acc["id"], r["promo_id"], r["nm_id"]))
    ctx.c.execute("DELETE FROM wb_promotions WHERE account_id=%s AND end_at < now() - interval '30 days'", (ctx.acc["id"],))
    ctx.c.commit()
    return {"promotions": len(lst), "items": items}


def _running(p: dict, now) -> bool:
    try:
        a = datetime.fromisoformat(str(p.get("startDateTime")).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(p.get("endDateTime")).replace("Z", "+00:00"))
        return a <= now <= b
    except ValueError:
        return False


def _promo_change(ctx, nm: int, p: dict, now_in: bool, ended: bool = False):
    v = {"promo": p.get("id"), "name": p.get("name"), **({"ended": True} if ended else {})}
    ctx.c.execute("""INSERT INTO card_changes(account_id,nm_id,detected_at,kind,field,old_value,new_value,source)
                     VALUES (%s,%s,now(),'promo',%s,%s,%s,'promotions')""",
                  (ctx.acc["id"], nm, "in" if now_in else "out", None if now_in else json.dumps(v, ensure_ascii=False),
                   json.dumps(v, ensure_ascii=False) if now_in else None))


def _promo_day(ctx, nm: int, name: str | None):
    from ..config import today_msk
    ctx.c.execute("""INSERT INTO wb_promo_days(account_id,nm_id,day,promos) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id,day)
                     DO UPDATE SET promos=(SELECT array_agg(DISTINCT x) FROM unnest(wb_promo_days.promos || EXCLUDED.promos) x)""",
                  (ctx.acc["id"], nm, today_msk(), [f"«{name or 'акция'}»"]))

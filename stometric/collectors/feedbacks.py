"""Отзывы WB (ключом на чтение, раздел «Вопросы и отзывы»): первый запуск — вся история (обработанные, необработанные, архив),
дальше — каждый круг все необработанные + обработанные за 3 дня. Имя покупателя в базу не пишем (152-ФЗ)."""

import json
import time

PAGE = 5000
MAX_SKIP = 199990


def _rating_before(c, acc: int, nm, created) -> float | None:
    r = c.execute("""SELECT (data->>'feedbackRating')::numeric r FROM raw_rows WHERE account_id=%s AND source='funnel_day'
                     AND (data->>'nmId')::bigint=%s AND row_date < (%s AT TIME ZONE 'Europe/Moscow')::date
                     AND data->>'feedbackRating' IS NOT NULL ORDER BY row_date DESC LIMIT 1""", (acc, nm, created)).fetchone()
    return float(r["r"]) if r and r["r"] is not None else None


def put(c, acc: int, f: dict, answered: bool) -> bool:
    """Upsert одного отзыва; True — отзыв новый. answered — «обработан» по WB (из какого списка пришёл)."""
    pd = f.get("productDetails") or {}
    ans = f.get("answer") or {}
    val = f.get("productValuation")
    row = c.execute(
        """INSERT INTO wb_feedbacks(account_id,id,nm_id,imt_id,vendor_code,product_name,subject,size,valuation,text,pros,cons,bables,
             photos,has_video,order_status,matching_size,created_at,answer_text,answer_state,answer_editable,answered)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,id) DO UPDATE SET answer_text=EXCLUDED.answer_text, answer_state=EXCLUDED.answer_state,
             answer_editable=EXCLUDED.answer_editable, answered=EXCLUDED.answered, valuation=EXCLUDED.valuation, text=EXCLUDED.text,
             pros=EXCLUDED.pros, cons=EXCLUDED.cons, photos=EXCLUDED.photos, has_video=EXCLUDED.has_video,
             order_status=EXCLUDED.order_status, updated_at=now()
           RETURNING (xmax = 0) AS fresh""",
        (acc, f["id"], pd.get("nmId"), pd.get("imtId"), pd.get("supplierArticle"), pd.get("productName"), f.get("subjectName"),
         pd.get("size"), val, f.get("text"), f.get("pros"), f.get("cons"), json.dumps(f.get("bables") or [], ensure_ascii=False),
         len(f.get("photoLinks") or []), bool(f.get("video")), f.get("orderStatus"), f.get("matchingSize"), f.get("createdDate"),
         ans.get("text"), ans.get("state"), ans.get("editable"), answered or bool(ans.get("text")))).fetchone()
    if row["fresh"] and val is not None and val <= 4:
        c.execute("UPDATE wb_feedbacks SET rating_before=%s WHERE account_id=%s AND id=%s",
                  (_rating_before(c, acc, pd.get("nmId"), f.get("createdDate")), acc, f["id"]))
    return row["fresh"]


def _pages(ctx, path: str, params: dict, limit_skip: int = MAX_SKIP):
    skip = 0
    while skip <= limit_skip:
        data = (ctx.wb.call("feedbacks", path, params={**params, "take": PAGE, "skip": skip}) or {}).get("data") or {}
        items = data.get("feedbacks") or []
        yield items
        if len(items) < PAGE:
            return
        skip += PAGE


def run(ctx) -> dict:
    acc = ctx.acc["id"]
    st = ctx.state("feedbacks")
    n = new = 0
    srcs = [("/api/v1/feedbacks", {"isAnswered": "false", "order": "dateDesc"})]
    if st.get("backfilled"):
        srcs.append(("/api/v1/feedbacks", {"isAnswered": "true", "order": "dateDesc", "dateFrom": int(time.time()) - 3 * 86400}))
    else:
        srcs += [("/api/v1/feedbacks", {"isAnswered": "true", "order": "dateDesc"}), ("/api/v1/feedbacks/archive", {"order": "dateDesc"})]
    open_ids: list[str] = []
    for path, params in srcs:
        unans = params.get("isAnswered") == "false"
        for items in _pages(ctx, path, params):
            for f in items:
                new += put(ctx.c, acc, f, not unans)
                if unans:
                    open_ids.append(f["id"])
            n += len(items)
            ctx.c.commit()
    
    still = set(open_ids)          
    done = [r["id"] for r in ctx.c.execute("SELECT id FROM wb_feedbacks WHERE account_id=%s AND NOT answered", (acc,)).fetchall()
            if r["id"] not in still]
    if done:
        ctx.c.execute("UPDATE wb_feedbacks SET answered=true, updated_at=now() WHERE account_id=%s AND id = ANY(%s)", (acc, done))
    ctx.c.commit()
    res = {"feedbacks": n, "new": new, "cursor": {"backfilled": True}}
    try:                                       
        from .. import reviews
        from ..private_ai import scheduled_ai
        with scheduled_ai(ctx.c):
            res["auto"] = reviews.process(ctx.c, acc)
    except Exception as e:  
        ctx.c.rollback()
        res["auto_error"] = str(e)[:200]
    return res


STARS = (("fiveStar", 5), ("fourStar", 4), ("threeStar", 3), ("twoStar", 2), ("oneStar", 1))


def _item_rating(ctx, days: int) -> tuple[dict, list]:
    from datetime import timedelta
    from ..config import today_msk
    y = today_msk() - timedelta(days=1)
    head, items, off = {}, [], 0
    while True:
        body = {"currentPeriod": {"start": str(y - timedelta(days=days - 1)), "end": str(y)},
                "orderBy": {"field": "feedbackCount", "mode": "desc"}, "limit": 1000, "offset": off}
        d = (ctx.wb.call("analytics", "/api/analytics/v2/item-rating", "POST", body=body) or {}).get("data") or {}
        head = head or d
        items += d.get("items") or []
        if len(d.get("items") or []) < 1000:
            return head, items
        off += 1000


def run_rating(ctx) -> dict:
    """«Оценка товара» WB: рейтинг по отзывам и оценки по звёздам за 364 дня (больше WB не отдаёт; по факту — почти вся история).
    Отчёт у WB обновляется раз в час; берём раз в 3 часа, снимок дня перезаписываем. Прирост за 30 дней WB отдаёт ненадёжно
    (у части артикулов — всю историю), его считаем по своим отзывам (wb_feedbacks)."""
    from ..config import today_msk
    acc, day = ctx.acc["id"], today_msk()
    head, tot = _item_rating(ctx, 364)
    for it in tot:
        g = lambda o, k: (o.get(k) or {}).get("current")  
        fr = it.get("feedbackRating") or {}
        ctx.c.execute(
            """INSERT INTO wb_item_rating(account_id,nm_id,day,rating,percentile,card_rating,s5,s4,s3,s2,s1,disqualified,pinned,shadowed)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (account_id,nm_id,day) DO UPDATE SET rating=EXCLUDED.rating, percentile=EXCLUDED.percentile,
                 card_rating=EXCLUDED.card_rating, s5=EXCLUDED.s5, s4=EXCLUDED.s4, s3=EXCLUDED.s3, s2=EXCLUDED.s2, s1=EXCLUDED.s1,
                 disqualified=EXCLUDED.disqualified,
                 pinned=EXCLUDED.pinned, shadowed=EXCLUDED.shadowed, updated_at=now()""",
            (acc, it["nmId"], day, fr.get("current"), fr.get("percentile"), it.get("rating"),
             *[g(it, k) for k, _ in STARS],
             it.get("disqualified"), it.get("pinnedFeedback"), it.get("isShadowed")))
    fi = head.get("feedbackIncrease") or {}
    if head:
        ctx.c.execute("""INSERT INTO wb_seller_rating(account_id,day,rating,s5,s4,s3,s2,s1) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (account_id,day) DO UPDATE SET rating=EXCLUDED.rating, s5=EXCLUDED.s5, s4=EXCLUDED.s4, s3=EXCLUDED.s3,
                           s2=EXCLUDED.s2, s1=EXCLUDED.s1, updated_at=now()""",
                      (acc, day, (head.get("sellerRating") or {}).get("current"), *[(fi.get(k) or {}).get("total") for k, _ in STARS]))
    ctx.c.commit()
    return {"items": len(tot)}

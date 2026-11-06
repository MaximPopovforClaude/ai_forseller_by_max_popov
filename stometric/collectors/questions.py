"""Вопросы покупателей WB (ключом на чтение, раздел «Вопросы и отзывы»): первый запуск — вся история (с ответом и без),
дальше — каждый круг все неотвеченные + отвеченные за 3 дня. В вопросах WB нет имени покупателя; личного не храним.
У WB take + skip ≤ 10 000: глубже листаем окнами по дате (dateTo = самый старый из полученных)."""

import re
import time
from datetime import datetime

from ..wb import WBError

PAGE = 5000
WINDOW = 10000          


def put(c, acc: int, q: dict, answered: bool) -> bool:
    """Upsert одного вопроса; True — новый."""
    pd = q.get("productDetails") or {}
    ans = q.get("answer") or {}
    row = c.execute(
        """INSERT INTO wb_questions(account_id,id,nm_id,imt_id,vendor_code,product_name,brand,text,created_at,state,was_viewed,
             answer_text,answer_editable,answered)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,id) DO UPDATE SET text=EXCLUDED.text, state=EXCLUDED.state, was_viewed=EXCLUDED.was_viewed,
             answer_text=EXCLUDED.answer_text, answer_editable=EXCLUDED.answer_editable, answered=EXCLUDED.answered,
             vendor_code=EXCLUDED.vendor_code, product_name=EXCLUDED.product_name, updated_at=now()
           RETURNING (xmax = 0) AS fresh""",
        (acc, q["id"], pd.get("nmId"), pd.get("imtId"), pd.get("supplierArticle"), pd.get("productName"), pd.get("brandName"),
         q.get("text"), q.get("createdDate"), q.get("state"), q.get("wasViewed"), ans.get("text"), ans.get("editable"),
         answered or bool(ans.get("text")))).fetchone()
    return row["fresh"]


def _unix(s: str) -> int:
    """'2022-02-01T11:18:08.769513469Z' → unix (доли секунды WB отдаёт до наносекунд — отбрасываем)."""
    s = re.sub(r"\.\d+", "", s).replace("Z", "+00:00")
    return int(datetime.fromisoformat(s).timestamp())


def _get(ctx, params: dict) -> list:
    try:
        data = (ctx.wb.call("feedbacks", "/api/v1/questions", params=params) or {}).get("data") or {}
    except WBError as e:
        if "HTTP 401" in str(e) or "HTTP 403" in str(e):
            raise WBError("Нет доступа к вопросам WB: у ключа на чтение нет раздела «Вопросы и отзывы» (или ключ отозван)") from None
        raise
    return data.get("questions") or []


def _pages(ctx, params: dict):
    """Все вопросы по фильтру (новые → старые): страницы по PAGE, после 10 000 — следующее окно по дате."""
    date_to = params.get("dateTo")
    while True:
        oldest, got = None, 0
        for skip in range(0, WINDOW, PAGE):
            p = {**params, "take": PAGE, "skip": skip, "order": "dateDesc"}
            if date_to:
                p["dateTo"] = date_to
            items = _get(ctx, p)
            yield items
            got += len(items)
            if items:
                oldest = items[-1].get("createdDate")
            if len(items) < PAGE:
                return
        if got < WINDOW or not oldest:
            return
        nxt = _unix(oldest)
        if date_to and nxt >= date_to:          
            return
        date_to = nxt                           


def run(ctx) -> dict:
    acc = ctx.acc["id"]
    st = ctx.state("questions")
    n = new = 0
    srcs = [{"isAnswered": "false"}]
    srcs.append({"isAnswered": "true", "dateFrom": int(time.time()) - 3 * 86400} if st.get("backfilled") else {"isAnswered": "true"})
    open_ids: list[str] = []
    for params in srcs:
        unans = params["isAnswered"] == "false"
        for items in _pages(ctx, params):
            for q in items:
                new += put(ctx.c, acc, q, not unans)
                if unans:
                    open_ids.append(q["id"])
            n += len(items)
            ctx.c.commit()
    
    still = set(open_ids)
    done = [r["id"] for r in ctx.c.execute("SELECT id FROM wb_questions WHERE account_id=%s AND NOT answered", (acc,)).fetchall()
            if r["id"] not in still]
    if done:
        ctx.c.execute("UPDATE wb_questions SET answered=true, updated_at=now() WHERE account_id=%s AND id = ANY(%s)", (acc, done))
    ctx.c.commit()
    res = {"questions": n, "new": new, "unanswered": len(still), "cursor": {"backfilled": True}}
    try:                                       
        from .. import questions
        from ..private_ai import scheduled_ai
        with scheduled_ai(ctx.c):
            res["auto"] = questions.process(ctx.c, acc)
    except Exception as e:  
        ctx.c.rollback()
        res["auto_error"] = str(e)[:200]
    return res

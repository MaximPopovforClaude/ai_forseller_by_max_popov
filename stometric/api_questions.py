"""API «Вопросы» (WB): список вопросов покупателей, черновики ИИ, ответы, пометки сотрудников, правила ответов."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from . import actions, auth, questions
from .api_actions import CommentIn, RulesIn, SendIn, _deny, _shop
from .web import _audit, conn, current_user

router = APIRouter()


def _wb(s: dict):
    if s["marketplace"] != "wb":
        raise HTTPException(400, "Вопросы пока только для магазинов WB")


@router.get("/api/shops/{shop_id}/questions")
def questions_list(shop_id: int, state: str = "unanswered", nm: int | None = None, q: str = "",
                   ours: bool = False, limit: int = 50, offset: int = 0, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    _wb(_shop(c, u, shop_id, "viewer"))
    role = auth.shop_role(c, u, shop_id)
    w, p = ["w.account_id=%(s)s"], {"s": shop_id, "lim": min(limit, 200), "off": offset}
    if state == "unanswered":
        w.append("NOT w.answered")
    elif state == "answered":
        w.append("w.answered")
    if nm:
        w.append("w.nm_id=%(nm)s")
        p["nm"] = nm
    if q.strip():
        w.append("(w.text ILIKE %(q)s OR w.answer_text ILIKE %(q)s OR w.vendor_code ILIKE %(q)s OR w.product_name ILIKE %(q)s"
                 " OR w.nm_id::text = %(qe)s)")
        p["q"], p["qe"] = f"%{q.strip()}%", q.strip()
    if ours:
        w.append("EXISTS (SELECT 1 FROM question_answers r WHERE r.account_id=w.account_id AND r.question_id=w.id AND r.status='sent')")
    where = " AND ".join(w)
    total = c.execute(f"SELECT count(*) n FROM wb_questions w WHERE {where}", p).fetchone()["n"]
    rows = c.execute(f"""SELECT w.*, n.data->'photos'->0->>'tm' photo FROM wb_questions w
                         LEFT JOIN nomenclature n ON n.account_id=w.account_id AND n.nm_id=w.nm_id
                         WHERE {where} ORDER BY w.created_at DESC LIMIT %(lim)s OFFSET %(off)s""", p).fetchall()
    ids = [r["id"] for r in rows]
    ans = c.execute("""SELECT r.*, coalesce(u.name,u.email) sent_by_name, coalesce(cu.name,cu.email) comment_by_name FROM question_answers r
                       LEFT JOIN users u ON u.id=r.sent_by LEFT JOIN users cu ON cu.id=r.comment_by
                       WHERE r.account_id=%s AND r.question_id = ANY(%s) AND r.status<>'discarded' ORDER BY r.id""", (shop_id, ids)).fetchall() if ids else []
    by: dict = {}
    for a in ans:
        by.setdefault(a["question_id"], []).append(a)
    for r in rows:
        r["answers"] = by.get(r["id"], [])
        r["busy"] = questions.busy(shop_id, r["id"])
    cnt = c.execute("""SELECT count(*) FILTER (WHERE NOT answered) unanswered, count(*) FILTER (WHERE created_at > now()-interval '7 days') week,
                         count(*) total, max(updated_at) updated FROM wb_questions WHERE account_id=%s""", (shop_id,)).fetchone()
    st = c.execute("SELECT last_ok_at, last_error FROM collector_state WHERE account_id=%s AND collector='questions'", (shop_id,)).fetchone()
    b = actions.block(c, shop_id, "questions")
    return jsonable_encoder({"rows": rows, "total": total, "counts": cnt, "collected": st, "block": b,
                             "can_send": auth.can(role, "editor") and not actions.can_write(c, shop_id, "questions"),
                             "why_not": actions.can_write(c, shop_id, "questions"), "can_edit": auth.can(role, "editor"),
                             "ai": bool(assistant.access(c, shop_id).get("ok")), "tones": questions.TONES_Q})


@router.post("/api/shops/{shop_id}/questions/{qid}/draft")
def questions_draft(shop_id: int, qid: str, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    _wb(_shop(c, u, shop_id, "editor"))
    if not c.execute("SELECT 1 FROM wb_questions WHERE account_id=%s AND id=%s", (shop_id, qid)).fetchone():
        raise HTTPException(404, "Вопрос не найден")
    if actions.block(c, shop_id, "questions")["settings"].get("mode") not in actions.AI_MODES:
        raise HTTPException(400, "Черновики ИИ для вопросов выключены: Взаимодействия → Вопросы → режим «ИИ пишет черновик» или «ИИ отвечает сам»")
    acc = assistant.access(c, shop_id)
    if not acc.get("ok"):
        raise HTTPException(400, acc.get("reason") or "Нет доступа к нейросети")
    started = questions.draft_async(shop_id, qid, u["id"])
    return {"ok": True, "busy": True, "started": started}


@router.post("/api/shops/{shop_id}/questions/{qid}/send")
def questions_send(shop_id: int, qid: str, body: SendIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    _wb(s)
    try:
        res = questions.send(c, shop_id, qid, body.text, u["id"], body.answer_id)
    except actions.ActionDenied as e:
        _deny(e)
    _audit(c, u, s["workspace_id"], "questions/send", {"shop": shop_id, "question": qid, "answer_id": res["answer_id"]})
    c.commit()
    return res


@router.put("/api/shops/{shop_id}/questions/answers/{aid}/comment")
def questions_comment(shop_id: int, aid: int, body: CommentIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    questions.comment(c, shop_id, aid, body.comment, u["id"])
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/questions/rules")
def questions_rules(shop_id: int, nm: int = 0, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    custom = c.execute("""SELECT r.nm_id, n.vendor_code, n.title FROM question_rules r LEFT JOIN nomenclature n ON n.account_id=r.account_id AND n.nm_id=r.nm_id
                          WHERE r.account_id=%s AND r.nm_id<>0 ORDER BY r.updated_at DESC""", (shop_id,)).fetchall()
    return jsonable_encoder({**questions.rules(c, shop_id, nm), "tones_all": questions.TONES_Q, "custom": custom})


@router.put("/api/shops/{shop_id}/questions/rules")
def questions_rules_save(shop_id: int, body: RulesIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    questions.save_rules(c, shop_id, body.nm_id, body.tones, body.text, u["id"])
    _audit(c, u, s["workspace_id"], "questions/rules", {"shop": shop_id, "nm": body.nm_id})
    c.commit()
    return jsonable_encoder(questions.rules(c, shop_id, body.nm_id))

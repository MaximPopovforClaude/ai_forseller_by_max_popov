"""API «Взаимодействия» и «Отзывы»: настройки блоков, ключ на запись (с дисклеймером), «Стоп», журнал; отзывы, черновики ИИ, ответы."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import actions, auth, reviews
from .web import _audit, conn, current_user

router = APIRouter()


def _shop(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, {"viewer": "Нет доступа к магазину", "editor": "Нужна роль «редактор» или выше",
                                  "admin": "Настройки взаимодействий меняет админ или владелец"}[need])
    return c.execute("SELECT id, workspace_id, marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()


def _deny(e: actions.ActionDenied):
    raise HTTPException(400, str(e))


@router.get("/api/shops/{shop_id}/actions")
def actions_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    s = _shop(c, u, shop_id, "viewer")
    role = auth.shop_role(c, u, shop_id)
    ai = assistant.access(c, shop_id)
    blocks = []
    for k, b in actions.BLOCKS.items():
        st = actions.block(c, shop_id, k) if not b.get("soon") else {"enabled": False, "settings": {}}
        blocks.append({"key": k, "title": b["title"], "about": b["about"], "soon": bool(b.get("soon")),
                       "available": s["marketplace"] in b.get("mp", ()), "scope": b.get("scope"),
                       "scope_ok": actions.scopes_ok(c, shop_id, k) if b.get("scope") else False, **st})
    last = c.execute("""SELECT l.created_at, l.block, l.action, l.target, l.ok, l.error, l.by_ai, coalesce(u.name,u.email) who
                        FROM action_log l LEFT JOIN users u ON u.id=l.user_id WHERE l.account_id=%s ORDER BY l.id DESC LIMIT 50""",
                     (shop_id,)).fetchall()
    return jsonable_encoder({"marketplace": s["marketplace"], "role": role, "can_admin": auth.can(role, "admin"),
                             "write_token": actions.write_info(c, shop_id) if auth.can(role, "admin") else bool(actions.write_info(c, shop_id)),
                             "split": actions.split(c, shop_id),
                             "price_token": actions.write_info(c, shop_id, "prices") if auth.can(role, "admin") else bool(actions.write_info(c, shop_id, "prices")),
                             "paused": actions.paused(c, shop_id), "blocks": blocks, "modes": actions.MODES,
                             "ai": {"ok": bool(ai.get("ok")), "reason": ai.get("reason")},
                             "disclaimer": {"version": actions.DISCLAIMER_VERSION, "text": actions.DISCLAIMER}, "log": last})


class TokenIn(BaseModel):
    token: str
    client_id: str | None = None      
    agree: bool
    version: str
    purpose: str = "main"             


@router.put("/api/shops/{shop_id}/actions/write_token")
def write_token_set(shop_id: int, body: TokenIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "admin")
    if not body.agree or body.version != actions.DISCLAIMER_VERSION:
        raise HTTPException(400, "Нужно согласиться с условиями (галочка под предупреждением)")
    try:
        info = actions.set_write_token(c, shop_id, body.token, u["id"], body.client_id, body.purpose)
    except actions.ActionDenied as e:
        _deny(e)
    _audit(c, u, s["workspace_id"], "actions/write_token", {"shop": shop_id, "purpose": body.purpose, "scopes": info["scopes"],
                                                            "agreed": actions.DISCLAIMER_VERSION})
    c.commit()
    return jsonable_encoder(info)


@router.delete("/api/shops/{shop_id}/actions/write_token")
def write_token_del(shop_id: int, purpose: str = "main", u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "admin")
    if purpose not in ("main", "prices"):
        raise HTTPException(400, "Неизвестный ключ")
    actions.drop_write_token(c, shop_id, u["id"], purpose)
    _audit(c, u, s["workspace_id"], "actions/write_token_remove", {"shop": shop_id, "purpose": purpose})
    c.commit()
    return {"ok": True}


class SplitIn(BaseModel):
    split: bool


@router.put("/api/shops/{shop_id}/actions/key_split")
def write_key_split(shop_id: int, body: SplitIn, u=Depends(current_user), c=Depends(conn)):
    """Один ключ на запись или раздельно: основной (без цен) + отдельный ключ только для цен."""
    s = _shop(c, u, shop_id, "admin")
    if s["marketplace"] != "wb":
        raise HTTPException(400, "Раздельные ключи — для магазинов WB")
    try:
        actions.set_split(c, shop_id, body.split, u["id"])
    except actions.ActionDenied as e:
        _deny(e)
    _audit(c, u, s["workspace_id"], "actions/key_split", {"shop": shop_id, "split": body.split})
    c.commit()
    return {"ok": True}


class PauseIn(BaseModel):
    paused: bool


@router.put("/api/shops/{shop_id}/actions/paused")
def actions_pause(shop_id: int, body: PauseIn, u=Depends(current_user), c=Depends(conn)):
    
    s = _shop(c, u, shop_id, "editor" if body.paused else "admin")
    c.execute("UPDATE accounts SET actions_paused=%s WHERE id=%s", (body.paused, shop_id))
    actions.log(c, shop_id, "_all", "pause" if body.paused else "resume", None, None, None, u["id"])
    _audit(c, u, s["workspace_id"], "actions/pause", {"shop": shop_id, "paused": body.paused})
    c.commit()
    return {"paused": body.paused}


class BlockIn(BaseModel):
    enabled: bool
    settings: dict = {}


@router.put("/api/shops/{shop_id}/actions/{block}")
def actions_block(shop_id: int, block: str, body: BlockIn, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    s = _shop(c, u, shop_id, "admin")
    b = actions.BLOCKS.get(block)
    if not b or b.get("soon"):
        raise HTTPException(404, "Блок пока недоступен")
    if s["marketplace"] not in b.get("mp", ()):
        raise HTTPException(400, "Для этой площадки блок пока недоступен")
    if any(body.settings.get(k) in actions.AI_MODES for k in actions.MODE_KEYS) and not assistant.access(c, shop_id).get("ok"):
        raise HTTPException(400, "Режимы с ИИ доступны на тарифах с нейросетью: " + (assistant.access(c, shop_id).get("reason") or ""))
    try:
        res = actions.save_block(c, shop_id, block, body.enabled, body.settings, u["id"])
    except actions.ActionDenied as e:
        _deny(e)
    actions.log(c, shop_id, block, "settings", None, None, {"enabled": body.enabled, **res["settings"]}, u["id"])
    _audit(c, u, s["workspace_id"], f"actions/{block}", {"shop": shop_id, "enabled": body.enabled, **res["settings"]})
    c.commit()
    return jsonable_encoder(res)



@router.get("/api/shops/{shop_id}/reviews")
def reviews_list(shop_id: int, stars: str = "all", state: str = "unanswered", nm: int | None = None, q: str = "",
                 ours: bool = False, limit: int = 50, offset: int = 0, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    _shop(c, u, shop_id, "viewer")
    role = auth.shop_role(c, u, shop_id)
    w, p = ["w.account_id=%(s)s"], {"s": shop_id, "lim": min(limit, 200), "off": offset}
    if stars == "neg":
        w.append("w.valuation<=4")
    elif stars == "pos":
        w.append("w.valuation=5")
    if state == "unanswered":
        w.append("NOT w.answered")
    elif state == "answered":
        w.append("w.answered")
    if nm:
        w.append("w.nm_id=%(nm)s")
        p["nm"] = nm
    if q.strip():
        w.append("(w.text ILIKE %(q)s OR w.pros ILIKE %(q)s OR w.cons ILIKE %(q)s OR w.vendor_code ILIKE %(q)s OR w.product_name ILIKE %(q)s)")
        p["q"] = f"%{q.strip()}%"
    if ours:
        w.append("EXISTS (SELECT 1 FROM review_answers r WHERE r.account_id=w.account_id AND r.feedback_id=w.id AND r.status='sent')")
    where = " AND ".join(w)
    total = c.execute(f"SELECT count(*) n FROM wb_feedbacks w WHERE {where}", p).fetchone()["n"]
    rows = c.execute(f"SELECT w.* FROM wb_feedbacks w WHERE {where} ORDER BY w.created_at DESC LIMIT %(lim)s OFFSET %(off)s", p).fetchall()
    ids = [r["id"] for r in rows]
    ans = c.execute("""SELECT r.*, coalesce(u.name,u.email) sent_by_name, coalesce(cu.name,cu.email) comment_by_name FROM review_answers r
                       LEFT JOIN users u ON u.id=r.sent_by LEFT JOIN users cu ON cu.id=r.comment_by
                       WHERE r.account_id=%s AND r.feedback_id = ANY(%s) AND r.status<>'discarded' ORDER BY r.id""", (shop_id, ids)).fetchall() if ids else []
    by: dict = {}
    for a in ans:
        by.setdefault(a["feedback_id"], []).append(a)
    for r in rows:
        r["answers"] = by.get(r["id"], [])
        r["drop"] = reviews.rating_drop(c, shop_id, r)
        r["busy"] = reviews.busy(shop_id, r["id"])
    cnt = c.execute("""SELECT count(*) FILTER (WHERE NOT answered) unanswered, count(*) FILTER (WHERE NOT answered AND valuation<=4) neg_unanswered,
                         count(*) FILTER (WHERE valuation<=4 AND created_at > now()-interval '7 days') neg_week, count(*) total,
                         max(updated_at) updated FROM wb_feedbacks WHERE account_id=%s""", (shop_id,)).fetchone()
    st = c.execute("""SELECT last_ok_at, last_error, coalesce((cursor->>'no_subscription')::boolean, false) no_subscription
                      FROM collector_state WHERE account_id=%s AND collector IN ('feedbacks','oz_reviews')""", (shop_id,)).fetchone()
    shop_mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()["marketplace"]
    b = actions.block(c, shop_id, "reviews")
    return jsonable_encoder({"rows": rows, "total": total, "counts": cnt, "collected": st, "block": b, "marketplace": shop_mp,
                             "can_send": auth.can(role, "editor") and not actions.can_write(c, shop_id, "reviews"),
                             "why_not": actions.can_write(c, shop_id, "reviews"), "can_edit": auth.can(role, "editor"),
                             "ai": bool(assistant.access(c, shop_id).get("ok")), "tones": reviews.TONES})


@router.post("/api/shops/{shop_id}/reviews/{fid}/draft")
def reviews_draft(shop_id: int, fid: str, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    _shop(c, u, shop_id, "editor")
    f = c.execute("SELECT valuation FROM wb_feedbacks WHERE account_id=%s AND id=%s", (shop_id, fid)).fetchone()
    if not f:
        raise HTTPException(404, "Отзыв не найден")
    b = actions.block(c, shop_id, "reviews")
    if reviews.mode_for(b["settings"], f["valuation"]) not in actions.AI_MODES:
        raise HTTPException(400, "Черновики ИИ для этих отзывов выключены: Взаимодействия → Отзывы → режим «ИИ: черновик» или «ИИ: сам»")
    acc = assistant.access(c, shop_id)
    if not acc.get("ok"):
        raise HTTPException(400, acc.get("reason") or "Нет доступа к нейросети")
    started = reviews.draft_async(shop_id, fid, u["id"])
    return {"ok": True, "busy": True, "started": started}


class SendIn(BaseModel):
    text: str
    answer_id: int | None = None


@router.post("/api/shops/{shop_id}/reviews/{fid}/send")
def reviews_send(shop_id: int, fid: str, body: SendIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    try:
        res = reviews.send(c, shop_id, fid, body.text, u["id"], body.answer_id)
    except actions.ActionDenied as e:
        _deny(e)
    _audit(c, u, s["workspace_id"], "reviews/send", {"shop": shop_id, "feedback": fid, "answer_id": res["answer_id"]})
    c.commit()
    return res


class CommentIn(BaseModel):
    comment: str


@router.put("/api/shops/{shop_id}/reviews/answers/{aid}/comment")
def reviews_comment(shop_id: int, aid: int, body: CommentIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    reviews.comment(c, shop_id, aid, body.comment, u["id"])
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/reviews/rules")
def reviews_rules(shop_id: int, nm: int = 0, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    custom = c.execute("""SELECT r.nm_id, n.vendor_code, n.title FROM review_rules r LEFT JOIN nomenclature n ON n.account_id=r.account_id AND n.nm_id=r.nm_id
                          WHERE r.account_id=%s AND r.nm_id<>0 ORDER BY r.updated_at DESC""", (shop_id,)).fetchall()
    return jsonable_encoder({**reviews.rules(c, shop_id, nm), "tones_all": reviews.TONES, "custom": custom})


class RulesIn(BaseModel):
    nm_id: int = 0
    tones: list[str] = []
    text: str = ""


@router.put("/api/shops/{shop_id}/reviews/rules")
def reviews_rules_save(shop_id: int, body: RulesIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    reviews.save_rules(c, shop_id, body.nm_id, body.tones, body.text, u["id"])
    _audit(c, u, s["workspace_id"], "reviews/rules", {"shop": shop_id, "nm": body.nm_id})
    c.commit()
    return jsonable_encoder(reviews.rules(c, shop_id, body.nm_id))



@router.get("/api/shops/{shop_id}/reco/{nm}")
def reco_get(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    from . import reco
    _shop(c, u, shop_id, "viewer")
    m = reco.get(c, shop_id, nm)
    names = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, title, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s",
                                               (shop_id,))}
    for x in m["items"]:
        n = names.get(x["nm_id"]) or {}
        x.update(vendor_code=n.get("vendor_code"), title=n.get("title"), photo=n.get("photo"))
    good = {x["nm_id"] for x in reco._catalog(c, shop_id)}
    for x in m["items"]:
        x["ok"] = x["nm_id"] in good          
    m["min_rating"] = reco.min_rating(c, shop_id)
    m["reg"] = reco.REGS.get(reco.reg(c, shop_id) or "")
    if m["reg"]:                              
        m["queue"] = [{**x, "kind_t": reco.KIND_T[x["kind"]], "photo": (names.get(x["nm_id"]) or {}).get("photo")}
                      for x in reco.ordered(c, shop_id, nm, m)]
    return jsonable_encoder(m)


@router.post("/api/shops/{shop_id}/reco/{nm}/build")
def reco_build(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    from . import assistant, reco
    _shop(c, u, shop_id, "editor")
    acc = assistant.access(c, shop_id)
    if not acc.get("ok"):
        raise HTTPException(400, acc.get("reason") or "Нет доступа к нейросети")
    c.commit()
    import threading
    from . import db

    def run():                                  
        with db.connect() as c2:
            reco.build(c2, shop_id, nm, acc["key"])
    threading.Thread(target=run, daemon=True).start()
    return {"started": True}


class RecoIn(BaseModel):
    items: list[dict]


@router.put("/api/shops/{shop_id}/reco/{nm}")
def reco_save(shop_id: int, nm: int, body: RecoIn, u=Depends(current_user), c=Depends(conn)):
    from . import reco
    s = _shop(c, u, shop_id, "editor")
    reco.save(c, shop_id, nm, body.items, u["id"])
    _audit(c, u, s["workspace_id"], "reco/save", {"shop": shop_id, "nm": nm, "n": len(body.items)})
    c.commit()
    return reco_get(shop_id, nm, u, c)

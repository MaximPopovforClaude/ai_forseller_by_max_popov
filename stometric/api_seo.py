"""Self-hosted application component."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import actions, auth, cards, seo_core, seo_review, seo_write
from .web import _audit, conn, current_user

router = APIRouter()


def _shop(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    s = c.execute("SELECT id, workspace_id, marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if s["marketplace"] != "wb":
        raise HTTPException(400, "SEO пока только для магазинов WB")
    return s


def _state(c, u, shop_id: int, nm: int) -> dict:
    from . import assistant
    d = cards.draft_get(c, shop_id, nm)
    b = cards.view(d["base"]) if d else None
    draft = d and {"id": d["id"], "title": d["changes"].get("title"), "description": d["changes"].get("description"),
                   "old_title": b["title"], "old_description": b["description"], "other": sorted(k for k in d["changes"] if k not in ("title", "description")),
                   "seo": d.get("seo"), "review_state": d.get("review_state"), "review_comment": d.get("review_comment"),
                   "reviewers": [seo_review._name(c, x) for x in d.get("reviewers") or []], "reviewed_by": seo_review._name(c, d.get("reviewed_by")),
                   "can_review": d.get("review_state") == "pending" and seo_review.can_review(c, u, d)}
    return jsonable_encoder({**seo_core.view(c, shop_id, nm), "draft": draft, "job": seo_write.job(c, shop_id, nm),
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor"), "ai": bool(assistant.access(c, shop_id).get("ok")),
                             "why_not": actions.can_write(c, shop_id, "cards"),
                             "will_review": [seo_review._name(c, x) for x in seo_review.reviewers(c, shop_id, nm)]})


@router.get("/api/shops/{shop_id}/seo/{nm}/core")
def seo_get(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    return _state(c, u, shop_id, nm)


@router.post("/api/shops/{shop_id}/seo/{nm}/collect")
def seo_collect(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    if not c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, nm)).fetchone():
        raise HTTPException(400, "Нет такого артикула в магазине")
    return {"started": seo_core.start(shop_id, nm)}


class MarkIn(BaseModel):
    phrase: str
    mark: str | None = None


@router.put("/api/shops/{shop_id}/seo/{nm}/mark")
def seo_mark(shop_id: int, nm: int, body: MarkIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    if body.mark not in (None, "core", "main", "excluded"):
        raise HTTPException(400, "Неизвестная отметка")
    try:
        seo_core.set_mark(c, shop_id, nm, body.phrase[:200], body.mark, u["id"])
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    c.commit()
    return {"ok": True}


class WriteIn(BaseModel):
    note: str | None = None


@router.post("/api/shops/{shop_id}/seo/{nm}/write")
def seo_write_start(shop_id: int, nm: int, body: WriteIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    _audit(c, u, s["workspace_id"], "seo/write", {"shop": shop_id, "nm": nm, "note": (body.note or "")[:300]})
    c.commit()
    return {"started": seo_write.start(shop_id, nm, u["id"], (body.note or "").strip()[:2000] or None)}


@router.post("/api/shops/{shop_id}/seo/{nm}/recheck")
def seo_recheck(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    seo_write.recheck(c, shop_id, nm)
    c.commit()
    return _state(c, u, shop_id, nm)


@router.post("/api/shops/{shop_id}/seo/{nm}/submit")
def seo_submit(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    try:
        seo_write.recheck(c, shop_id, nm)
        res = seo_review.submit(c, shop_id, nm, u["id"])
    except actions.ActionDenied as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, s["workspace_id"], "seo/submit", {"shop": shop_id, "nm": nm})
    c.commit()
    return res


@router.get("/api/shops/{shop_id}/seo_pending")
def seo_pending(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    return jsonable_encoder({"rows": seo_review.pending(c, u, shop_id)})


@router.post("/api/shops/{shop_id}/seo_review/{draft_id}/approve")
def seo_approve(shop_id: int, draft_id: int, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "viewer")
    if not c.execute("SELECT 1 FROM card_drafts WHERE id=%s AND account_id=%s", (draft_id, shop_id)).fetchone():
        raise HTTPException(404, "Нет такого черновика")
    try:
        res = seo_review.approve(c, u, draft_id)
    except actions.ActionDenied as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, s["workspace_id"], "seo/approve", {"shop": shop_id, "draft": draft_id, "status": res.get("status")})
    c.commit()
    return jsonable_encoder(res)


class BackIn(BaseModel):
    comment: str


@router.post("/api/shops/{shop_id}/seo_review/{draft_id}/return")
def seo_return(shop_id: int, draft_id: int, body: BackIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "viewer")
    if not c.execute("SELECT 1 FROM card_drafts WHERE id=%s AND account_id=%s", (draft_id, shop_id)).fetchone():
        raise HTTPException(404, "Нет такого черновика")
    try:
        res = seo_review.send_back(c, u, draft_id, body.comment)
    except actions.ActionDenied as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, s["workspace_id"], "seo/return", {"shop": shop_id, "draft": draft_id})
    c.commit()
    return res


@router.get("/api/shops/{shop_id}/seo_rules")
def seo_rules(shop_id: int, nm: int = 0, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    r = c.execute("SELECT text FROM seo_rules WHERE account_id=%s AND nm_id=%s", (shop_id, nm)).fetchone()
    custom = c.execute("""SELECT r.nm_id, n.vendor_code, n.title FROM seo_rules r LEFT JOIN nomenclature n ON n.account_id=r.account_id AND n.nm_id=r.nm_id
                          WHERE r.account_id=%s AND r.nm_id<>0 ORDER BY r.updated_at DESC""", (shop_id,)).fetchall()
    return jsonable_encoder({"nm_id": nm, "text": (r or {}).get("text", ""), "default": seo_write.DEFAULT_RULES, "custom": custom,
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class RulesIn(BaseModel):
    nm_id: int = 0
    text: str = ""


@router.put("/api/shops/{shop_id}/seo_rules")
def seo_rules_save(shop_id: int, body: RulesIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    c.execute("""INSERT INTO seo_rules(account_id,nm_id,text,updated_by) VALUES (%s,%s,%s,%s)
                 ON CONFLICT (account_id,nm_id) DO UPDATE SET text=EXCLUDED.text, updated_by=EXCLUDED.updated_by, updated_at=now()""",
              (shop_id, body.nm_id, body.text[:8000], u["id"]))
    _audit(c, u, s["workspace_id"], "seo/rules", {"shop": shop_id, "nm": body.nm_id})
    c.commit()
    return {"ok": True}

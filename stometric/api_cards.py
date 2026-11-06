"""API блока «Карточки» WB: карточка из WB, справочник характеристик, черновик, сравнение, применение, откат, история, фото."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import actions, auth, cards, cards_ai
from .web import _audit, conn, current_user

router = APIRouter()


def _shop(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    s = c.execute("SELECT id, workspace_id, marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if s["marketplace"] != "wb":
        raise HTTPException(400, "Редактирование карточек пока только для магазинов WB")
    return s


def _err(e: Exception):
    raise HTTPException(400, str(e))


def _state(c, u, shop_id: int, nm: int, d: dict | None) -> dict:
    from . import assistant
    role = auth.shop_role(c, u, shop_id)
    base = cards.view(d["base"]) if d else None
    return jsonable_encoder({"draft": d and {"id": d["id"], "changes": d["changes"], "sources": d["sources"], "ai_notes": d["ai_notes"],
                                             "updated_at": d["updated_at"]},
                             "base": base, "diff": cards.diff(d) if d else [], "price_check": cards.price_check(d, c) if d else None,
                             "history": cards.history(c, shop_id, nm), "can_edit": auth.can(role, "editor"),
                             "why_not": actions.can_write(c, shop_id, "cards"), "ai": bool(assistant.access(c, shop_id).get("ok")),
                             "block": actions.block(c, shop_id, "cards"), "ai_job": cards_ai.job(c, shop_id, nm)})


class RulesIn(BaseModel):
    text: str = ""


@router.get("/api/shops/{shop_id}/cards/rules")
def card_rules(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    r = c.execute("SELECT text FROM card_rules WHERE account_id=%s", (shop_id,)).fetchone()
    return {"text": r["text"] if r else ""}


@router.put("/api/shops/{shop_id}/cards/rules")
def card_rules_save(shop_id: int, body: RulesIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    c.execute("""INSERT INTO card_rules(account_id,text,updated_by,updated_at) VALUES (%s,%s,%s,now())
                 ON CONFLICT (account_id) DO UPDATE SET text=EXCLUDED.text, updated_by=EXCLUDED.updated_by, updated_at=now()""",
              (shop_id, body.text[:4000], u["id"]))
    c.commit()
    return {"text": body.text[:4000]}


class AiIn(BaseModel):
    scope: str


@router.post("/api/shops/{shop_id}/cards/{nm}/ai")
def card_ai(shop_id: int, nm: int, body: AiIn, u=Depends(current_user), c=Depends(conn)):
    from . import assistant
    _shop(c, u, shop_id, "editor")
    acc = assistant.access(c, shop_id)
    if not acc.get("ok"):
        raise HTTPException(400, acc.get("reason") or "Нет доступа к нейросети")
    try:
        started = cards_ai.start(shop_id, nm, body.scope, u["id"])
    except actions.ActionDenied as e:
        _err(e)
    return {"started": started}


@router.get("/api/shops/{shop_id}/cards/{nm}")
def card_get(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    """Карточка для редактора: черновик (если есть) или свежая карточка из WB (черновик не создаётся, пока ничего не меняли)."""
    _shop(c, u, shop_id, "viewer")
    d = cards.draft_get(c, shop_id, nm)
    if d:
        return _state(c, u, shop_id, nm, d)
    try:
        card = cards.live_card(c, shop_id, nm)
    except Exception as e:  
        _err(e)
    st = _state(c, u, shop_id, nm, None)
    st["base"] = jsonable_encoder(cards.view(card))
    return st


@router.get("/api/shops/{shop_id}/cards/{nm}/charcs")
def card_charcs(shop_id: int, nm: int, subject_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    try:
        return jsonable_encoder(cards.charcs(c, shop_id, subject_id))
    except Exception as e:  
        _err(e)


class SetIn(BaseModel):
    field: str
    value: object = None


@router.put("/api/shops/{shop_id}/cards/{nm}/draft")
def card_draft_set(shop_id: int, nm: int, body: SetIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    try:
        d = cards.draft_set(c, shop_id, nm, body.field, body.value, u["id"], source="ai" if u.get("_mcp") else "manual")
    except (actions.ActionDenied, ValueError, TypeError, KeyError) as e:
        _err(e)
    c.commit()
    return _state(c, u, shop_id, nm, d)


@router.delete("/api/shops/{shop_id}/cards/{nm}/draft")
def card_draft_discard(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    cards.draft_discard(c, shop_id, nm)
    c.commit()
    return {"ok": True}


@router.post("/api/shops/{shop_id}/cards/{nm}/rebase")
def card_rebase(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    try:
        d = cards.rebase(c, shop_id, nm)
    except actions.ActionDenied as e:
        _err(e)
    c.commit()
    return _state(c, u, shop_id, nm, d)


class ApplyIn(BaseModel):
    force: bool = False
    price_ack: float | None = None


@router.post("/api/shops/{shop_id}/cards/{nm}/apply")
def card_apply(shop_id: int, nm: int, body: ApplyIn, u=Depends(current_user), c=Depends(conn)):
    s = _shop(c, u, shop_id, "editor")
    try:
        res = cards.apply(c, shop_id, nm, u["id"], body.force, body.price_ack, by_ai=bool(u.get("_mcp")))
    except actions.ActionDenied as e:
        _err(e)
    _audit(c, u, s["workspace_id"], "cards/apply", {"shop": shop_id, "nm": nm, **res})
    c.commit()
    return jsonable_encoder(res)


@router.post("/api/shops/{shop_id}/cards/rollback/{draft_id}")
def card_rollback(shop_id: int, draft_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    try:
        d = cards.rollback(c, shop_id, draft_id, u["id"], source="ai" if u.get("_mcp") else "manual")
    except actions.ActionDenied as e:
        _err(e)
    c.commit()
    return _state(c, u, shop_id, d["nm_id"], d)


@router.post("/api/shops/{shop_id}/cards/{nm}/upload")
async def card_upload(shop_id: int, nm: int, request: Request, name: str = "", u=Depends(current_user), c=Depends(conn)):
    """Тело запроса — сам файл (как у вложений Стометрика), имя — в ?name=."""
    _shop(c, u, shop_id, "editor")
    raw = await request.body()
    try:
        m = cards.save_upload(c, shop_id, nm, name, raw, u["id"])
    except actions.ActionDenied as e:
        _err(e)
    c.commit()
    return m


@router.get("/api/public/card_media/{name}")
def card_media(name: str, c=Depends(conn)):
    """Фото из черновика — по случайному токену (WB забирает по ссылке при «Применить»)."""
    tok = Path(name).stem
    r = c.execute("SELECT path, mime FROM card_media_uploads WHERE token=%s", (tok,)).fetchone()
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404, "Нет файла")
    return FileResponse(r["path"], media_type=r["mime"])

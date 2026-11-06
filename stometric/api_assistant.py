"""API «Стометрика» — помощника в сервисе (stometric/assistant.py)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import assistant, auth
from .web import _audit, conn, current_user

router = APIRouter()


def _shop_ok(c, u, shop: int):
    if not auth.can(auth.shop_role(c, u, shop), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")


def _chat(c, u, chat_id: int) -> dict:
    ch = c.execute("SELECT * FROM assistant_chats WHERE id=%s AND user_id=%s", (chat_id, u["id"])).fetchone()
    if not ch:
        raise HTTPException(404, "Чат не найден")
    _shop_ok(c, u, ch["shop_id"])
    return ch


@router.get("/api/assistant/status")
def status(shop: int, u=Depends(current_user), c=Depends(conn)):
    _shop_ok(c, u, shop)
    a = assistant.access(c, shop, u["id"])
    return {k: a.get(k) for k in ("ok", "plan", "reason", "limit", "used")} | {"name": assistant.NAME}


@router.get("/api/assistant/chats")
def chats(shop: int, u=Depends(current_user), c=Depends(conn)):
    _shop_ok(c, u, shop)
    return jsonable_encoder(c.execute("""SELECT id, title, created_at, updated_at FROM assistant_chats WHERE user_id=%s AND shop_id=%s
                                         ORDER BY updated_at DESC LIMIT 50""", (u["id"], shop)).fetchall())


class NewChat(BaseModel):
    shop_id: int


@router.post("/api/assistant/chats")
def new_chat(body: NewChat, u=Depends(current_user), c=Depends(conn)):
    _shop_ok(c, u, body.shop_id)
    r = c.execute("INSERT INTO assistant_chats(user_id,shop_id) VALUES (%s,%s) RETURNING id", (u["id"], body.shop_id)).fetchone()
    c.commit()
    return {"id": r["id"]}


@router.get("/api/assistant/chats/{chat_id}")
def get_chat(chat_id: int, u=Depends(current_user), c=Depends(conn)):
    ch = _chat(c, u, chat_id)
    assistant.recover_pending(c, chat_id)
    c.commit()
    msgs = c.execute("""SELECT m.id, m.role, m.content, m.status, m.data, m.model, m.created_at,
                               (SELECT json_agg(json_build_object('id', f.id, 'name', f.name, 'mime', f.mime) ORDER BY f.id)
                                FROM assistant_files f WHERE f.message_id=m.id) files
                        FROM assistant_messages m WHERE chat_id=%s ORDER BY id""", (chat_id,)).fetchall()
    return jsonable_encoder({"chat": ch, "messages": msgs})


class MsgIn(BaseModel):
    text: str
    files: list[int] = []


@router.post("/api/assistant/chats/{chat_id}/files")
async def upload_file(chat_id: int, request: Request, name: str = "", u=Depends(current_user), c=Depends(conn)):
    """Вложение к будущему сообщению (тело запроса — сам файл): фото, скриншот, PDF, xlsx/csv/txt до 10 МБ."""
    _chat(c, u, chat_id)
    try:
        r = assistant.save_file(c, chat_id, u["id"], name, await request.body())
    except assistant.AskError as e:
        raise HTTPException(400, str(e)) from None
    c.commit()
    return r


@router.get("/api/assistant/files/{file_id}")
def get_file(file_id: int, u=Depends(current_user), c=Depends(conn)):
    from fastapi.responses import FileResponse
    f = c.execute("SELECT * FROM assistant_files WHERE id=%s AND user_id=%s", (file_id, u["id"])).fetchone()
    if not f:
        raise HTTPException(404, "Файл не найден")
    return FileResponse(assistant.files_dir() / f["path"], media_type=f["mime"], filename=f["name"])


@router.post("/api/assistant/chats/{chat_id}/messages")
def send(chat_id: int, body: MsgIn, u=Depends(current_user), c=Depends(conn)):
    ch = _chat(c, u, chat_id)
    try:
        pid, _ = assistant.ask(c, u["id"], ch, body.text, body.files)
    except assistant.AskError as e:
        c.rollback()
        raise HTTPException(e.code, str(e)) from None
    c.commit()
    assistant.start(pid)
    return {"ok": True, "pending_id": pid}


class LimitIn(BaseModel):
    limit: int | None


@router.put("/api/admin/workspaces/{ws_id}/assistant_limit")
def set_limit(ws_id: int, body: LimitIn, u=Depends(current_user), c=Depends(conn)):
    if not u["is_superadmin"]:
        raise HTTPException(403, "Только для суперадмина")
    if body.limit is not None and not (0 <= body.limit <= 10000):
        raise HTTPException(400, "Лимит — от 0 до 10000 в день")
    c.execute("UPDATE workspaces SET assistant_limit=%s WHERE id=%s", (body.limit, ws_id))
    _audit(c, u, ws_id, "admin/assistant_limit", {"limit": body.limit})
    c.commit()
    return {"ok": True}


@router.post("/api/shops/{shop_id}/cost/drafts/{draft_id}/apply")
def cost_draft_apply(shop_id: int, draft_id: int, u=Depends(current_user), c=Depends(conn)):
    """Кнопка «Применить» под черновиком себестоимости от Стометрика — записывает человек, не нейросеть."""
    from . import assistant_cost
    _shop_ok(c, u, shop_id)
    try:
        res = assistant_cost.apply_draft(c, shop_id, u["id"], draft_id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    except LookupError as e:
        raise HTTPException(400, str(e)) from None
    return res

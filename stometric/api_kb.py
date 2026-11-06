"""API базы знаний (stometric/kb.py): разделы, материалы, файлы. Файл приходит телом запроса (без multipart), как у Стометрика."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import kb
from .web import _audit, conn, current_user

router = APIRouter()


def _err(e: kb.KbError):
    raise HTTPException(e.code, str(e)) from None


def _ws(c, u, ws: int):
    if not kb.can_read(c, u, ws):
        raise HTTPException(403, "Нет доступа к рабочему пространству")


@router.get("/api/workspaces/{ws}/kb")
def kb_list(ws: int, section: int | None = None, q: str = "", shop: int | None = None, u=Depends(current_user), c=Depends(conn)):
    _ws(c, u, ws)
    rows = kb.items(c, u, ws, section, q, shop)
    for r in rows:
        r["can_change"] = kb.can_change(c, u, r)
    return jsonable_encoder({"tree": kb.tree(c, u, ws), "items": rows, "can_add": kb.can_add(c, u, ws),
                             "can_admin": kb.auth.can(kb.ws_role(c, u, ws), "admin"),
                             "shops": [{"id": s["id"], "title": s["title"] or s["name"], "can_add": kb.can_add(c, u, ws, s["id"])}
                                       for s in kb.shops_visible(c, u, ws)]})


class SectionIn(BaseModel):
    title: str
    parent_id: int | None = None


@router.post("/api/workspaces/{ws}/kb/sections")
def kb_section_add(ws: int, body: SectionIn, u=Depends(current_user), c=Depends(conn)):
    _ws(c, u, ws)
    if not kb.can_add(c, u, ws):
        raise HTTPException(403, "Добавлять в базу знаний может редактор и выше")
    try:
        sid = kb.section(c, u, ws, body.title, body.parent_id)
    except kb.KbError as e:
        _err(e)
    c.commit()
    return {"id": sid}


@router.put("/api/kb/sections/{sid}")
def kb_section_rename(sid: int, body: SectionIn, u=Depends(current_user), c=Depends(conn)):
    try:
        kb.rename_section(c, u, sid, body.title)
    except kb.KbError as e:
        _err(e)
    c.commit()
    return {"ok": True}


@router.delete("/api/kb/sections/{sid}")
def kb_section_delete(sid: int, u=Depends(current_user), c=Depends(conn)):
    try:
        kb.delete_section(c, u, sid)
    except kb.KbError as e:
        _err(e)
    c.commit()
    return {"ok": True}


class ItemIn(BaseModel):
    kind: str = "link"
    title: str = ""
    url: str | None = None
    body: str | None = None
    description: str | None = None
    section_id: int | None = None
    shop_id: int | None = None


@router.post("/api/workspaces/{ws}/kb/items")
def kb_item_add(ws: int, body: ItemIn, u=Depends(current_user), c=Depends(conn)):
    _ws(c, u, ws)
    if body.kind not in ("link", "note"):
        raise HTTPException(400, "Файл и фото — через загрузку")
    try:
        iid = kb.add(c, u, ws, kind=body.kind, title=body.title, url=body.url, body=body.body, description=body.description,
                     section_id=body.section_id, shop_id=body.shop_id)
    except kb.KbError as e:
        _err(e)
    _audit(c, u, ws, "kb/add", {"id": iid, "kind": body.kind})
    c.commit()
    return {"id": iid}


@router.post("/api/workspaces/{ws}/kb/upload")
async def kb_upload(ws: int, request: Request, name: str = "", title: str = "", description: str = "", section_id: int | None = None,
                    shop_id: int | None = None, u=Depends(current_user), c=Depends(conn)):
    """Файл или фото (тело запроса — сам файл) до 25 МБ."""
    _ws(c, u, ws)
    raw = await request.body()
    try:
        iid = kb.add(c, u, ws, kind="file", title=title, description=description, section_id=section_id, shop_id=shop_id, file=(name, raw))
    except kb.KbError as e:
        _err(e)
    _audit(c, u, ws, "kb/add", {"id": iid, "kind": "file", "name": name[:200]})
    c.commit()
    return {"id": iid}


class ItemUpd(BaseModel):
    title: str | None = None
    url: str | None = None
    body: str | None = None
    description: str | None = None
    section_id: int | None = None
    shop_id: int | None = None


@router.put("/api/kb/items/{iid}")
def kb_item_update(iid: int, body: ItemUpd, u=Depends(current_user), c=Depends(conn)):
    try:
        kb.update(c, u, iid, body.model_dump(exclude_unset=True))
    except kb.KbError as e:
        _err(e)
    c.commit()
    return {"ok": True}


@router.delete("/api/kb/items/{iid}")
def kb_item_delete(iid: int, u=Depends(current_user), c=Depends(conn)):
    it = kb.get(c, iid)
    try:
        kb.delete(c, u, iid)
    except kb.KbError as e:
        _err(e)
    _audit(c, u, it["workspace_id"], "kb/delete", {"id": iid, "title": it["title"]})
    c.commit()
    return {"ok": True}


@router.get("/api/kb/items/{iid}/file")
def kb_file(iid: int, dl: bool = False, u=Depends(current_user), c=Depends(conn)):
    it = kb.get(c, iid)
    if not it or not it["file_path"] or not kb.can_see(c, u, it):
        raise HTTPException(404, "Нет файла")
    p = kb.path(it)
    if not p.exists():
        raise HTTPException(404, "Файл не найден на сервере")
    inline = not dl and (it["mime"] or "").startswith(("image/", "application/pdf", "video/", "text/plain"))
    return FileResponse(p, media_type=it["mime"] or "application/octet-stream", filename=it["file_name"] or p.name,
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})

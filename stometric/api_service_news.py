"""Self-hosted application component."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .web import conn, current_user

router = APIRouter()


def unread(c, u) -> int:
    return c.execute("SELECT count(*) n FROM service_news WHERE id > %s", (u.get("news_seen_id") or 0,)).fetchone()["n"]


@router.get("/api/service_news")
def news_list(u=Depends(current_user), c=Depends(conn)):
    rows = c.execute("SELECT id, created_at, title, body, tabs FROM service_news ORDER BY id DESC LIMIT 200").fetchall()
    return {"rows": rows, "seen": u.get("news_seen_id") or 0, "can_edit": bool(u["is_superadmin"])}


@router.post("/api/service_news/seen")
def news_seen(u=Depends(current_user), c=Depends(conn)):
    c.execute("UPDATE users SET news_seen_id=(SELECT coalesce(max(id),0) FROM service_news) WHERE id=%s", (u["id"],))
    c.commit()
    return {"ok": True}


class NewsIn(BaseModel):
    title: str
    body: str = ""
    tabs: list[str] = []


def add(c, title: str, body: str, tabs: list[str] | None = None, author: int | None = None) -> int:
    return c.execute("INSERT INTO service_news(title,body,tabs,author_id) VALUES (%s,%s,%s,%s) RETURNING id",
                     (title.strip()[:200], body.strip()[:5000], tabs or [], author)).fetchone()["id"]


@router.post("/api/service_news")
def news_add(body: NewsIn, u=Depends(current_user), c=Depends(conn)):
    if not u["is_superadmin"]:
        raise HTTPException(403, "Добавлять новости может только суперадмин")
    if not body.title.strip():
        raise HTTPException(400, "Нужен заголовок")
    i = add(c, body.title, body.body, body.tabs, u["id"])
    c.commit()
    return {"id": i}


@router.delete("/api/service_news/{news_id}")
def news_del(news_id: int, u=Depends(current_user), c=Depends(conn)):
    if not u["is_superadmin"]:
        raise HTTPException(403, "Удалять новости может только суперадмин")
    c.execute("DELETE FROM service_news WHERE id=%s", (news_id,))
    c.commit()
    return {"ok": True}

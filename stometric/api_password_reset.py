"""Browser-only recovery endpoints; no token in a path, query, audit or Telegram fallback."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from . import password_reset as reset
from .web import conn, current_user

router = APIRouter()


def browser(request, response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.headers.get("origin") != reset.SITE:
        raise HTTPException(403, "Откройте восстановление на сайте 100MC")


class IssueIn(BaseModel):
    delivery: Literal["manual", "telegram"] = "telegram"
    confirm_email: str = Field(max_length=320)


@router.post("/api/admin/users/{uid}/password-reset")
def admin_reset(uid: int, body: IssueIn, request: Request, response: Response,
                u=Depends(current_user), c=Depends(conn)):
    browser(request, response)
    target = reset.authorize(c, u, uid)
    if target["email"] != body.confirm_email.strip().lower():
        raise HTTPException(409, "Данные пользователя изменились. Обновите список.")
    link = reset.issue(c, target, u["id"], body.delivery)
    if body.delivery == "telegram":
        reset.deliver(c, target, u["id"], None, link)
    return jsonable_encoder({"ok": True, "expires_at": link["expires_at"],
                             **({"url": link["url"]} if body.delivery == "manual" else {})})


@router.post("/api/workspaces/{ws_id}/members/{uid}/password-reset")
def member_reset(ws_id: int, uid: int, request: Request, response: Response,
                 u=Depends(current_user), c=Depends(conn)):
    browser(request, response)
    target = reset.authorize(c, u, uid, ws_id)
    link = reset.issue(c, target, u["id"], "telegram", ws_id)
    reset.deliver(c, target, u["id"], ws_id, link)
    return jsonable_encoder({"ok": True, "expires_at": link["expires_at"]})


class TokenIn(BaseModel):
    token: str = Field(min_length=43, max_length=43)


class PasswordIn(TokenIn):
    password: str = Field(min_length=10, max_length=1024)


@router.post("/api/auth/password-reset/info")
def reset_info(body: TokenIn, request: Request, response: Response, c=Depends(conn)):
    browser(request, response)
    return reset.info(c, body.token)


@router.post("/api/auth/password-reset/confirm")
def reset_confirm(body: PasswordIn, request: Request, response: Response, c=Depends(conn)):
    browser(request, response)
    return reset.complete(c, body.token, body.password)

"""Human team calendar API; no AI subscription/API is involved."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from . import calendar
from .config import today_msk
from .web import _audit, conn, current_user

router = APIRouter()


class EntryIn(BaseModel):
    kind: Literal['task', 'note']
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=4000)
    day: date
    shop_id: int | None = Field(default=None, gt=0)
    assignee_id: int | None = Field(default=None, gt=0)


class CreateIn(EntryIn):
    request_key: UUID


class UpdateIn(EntryIn):
    version: int = Field(gt=0)
    status: Literal['open', 'done', 'cancelled']


@router.get('/api/workspaces/{ws}/calendar')
def listing(ws: int, start: date, end: date, closed: bool = False, mine: bool = False,
            actions: bool = False, shop: int | None = None, u=Depends(current_user), c=Depends(conn)):
    if end < start or (end-start).days > 62:
        raise HTTPException(400, 'Выберите период не больше 63 дней')
    ctx = calendar.scope(c, u, ws)
    rows, truncated = calendar.entries(c, u, ws, ctx, start, end, closed, mine, shop=shop)
    ns = c.execute('SELECT bot,chat_id FROM notify_settings WHERE user_id=%s', (u['id'],)).fetchone() or {}
    return jsonable_encoder({'items': rows, 'truncated': truncated, 'today': today_msk(), 'me': u['id'],
        'can_add': ctx['role'] in calendar.WRITE_ROLES, 'members': calendar.members(c, ws), 'shops': ctx['shops'],
        'stometric_connected': ns.get('bot') == 'assistant' and ns.get('chat_id') is not None,
        'action_counts': calendar.action_counts(c, ctx, start, end, shop) if actions else []})


@router.get('/api/workspaces/{ws}/calendar/due')
def due(ws: int, u=Depends(current_user), c=Depends(conn)):
    ctx = calendar.scope(c, u, ws)
    rows, truncated = calendar.entries(c, u, ws, ctx, due=True)
    return jsonable_encoder({'items': rows, 'today': today_msk(), 'truncated': truncated})


@router.get('/api/workspaces/{ws}/calendar/actions')
def actions(ws: int, day: date, shop: int | None = None, offset: int = Query(default=0, ge=0, le=1000000),
            u=Depends(current_user), c=Depends(conn)):
    ctx = calendar.scope(c, u, ws)
    return jsonable_encoder(calendar.action_page(c, ctx, day, shop, offset))


@router.post('/api/workspaces/{ws}/calendar')
def create(ws: int, body: CreateIn, u=Depends(current_user), c=Depends(conn)):
    eid, added = calendar.create(c, u, ws, body.model_dump(exclude={'request_key'}), body.request_key)
    if added:
        _audit(c, u, ws, 'calendar/create', {'id': eid, 'kind': body.kind})
    c.commit()
    return {'id': eid}


@router.put('/api/workspaces/{ws}/calendar/{eid}')
def update(ws: int, eid: int, body: UpdateIn, u=Depends(current_user), c=Depends(conn)):
    calendar.update(c, u, ws, eid, body.model_dump(exclude={'version'}), body.version)
    _audit(c, u, ws, 'calendar/update', {'id': eid, 'status': body.status})
    c.commit()
    return {'ok': True}

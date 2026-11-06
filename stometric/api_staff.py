"""Менеджеры по артикулам: список менеджеров кабинета, назначение артикулов магазина, загрузка файлом (staff.py)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import auth, staff
from .cost_import import CostImportError
from .web import _audit, conn, current_user

router = APIRouter()


def _ws(c, u, ws: int, need: str) -> str:
    role = auth.workspace_role(c, u, ws)
    if not auth.can(role, need):
        raise HTTPException(403, "Нет доступа к кабинету" if need == "viewer" else "Нужна роль «редактор» или выше")
    return role


def _staff(c, u, sid: int, need: str) -> dict:
    s = c.execute("SELECT * FROM staff WHERE id=%s", (sid,)).fetchone()
    if not s:
        raise HTTPException(404, "Нет такого менеджера")
    _ws(c, u, s["workspace_id"], need)
    return s


@router.get("/api/workspaces/{ws}/staff")
def staff_list(ws: int, u=Depends(current_user), c=Depends(conn)):
    """Менеджеры кабинета: сколько артикулов в каждом магазине; пользователи кабинета — для привязки."""
    role = _ws(c, u, ws, "viewer")
    rows = c.execute("""SELECT s.id, s.name, s.user_id, coalesce(nullif(us.name,''), us.email) user_name,
                               (SELECT coalesce(jsonb_object_agg(x.account_id, x.n), '{}') FROM
                                  (SELECT account_id, count(*) n FROM staff_articles WHERE staff_id=s.id GROUP BY 1) x) per_shop
                        FROM staff s LEFT JOIN users us ON us.id=s.user_id WHERE s.workspace_id=%s ORDER BY lower(s.name)""", (ws,)).fetchall()
    users = [] if not auth.can(role, "editor") else c.execute("""SELECT us.id, coalesce(nullif(us.name,''), us.email) name FROM memberships m JOIN users us ON us.id=m.user_id
                         WHERE m.workspace_id=%s ORDER BY 2""", (ws,)).fetchall()
    return jsonable_encoder({"staff": rows, "users": users, "can_edit": auth.can(role, "editor")})


class StaffIn(BaseModel):
    name: str
    user_id: int | None = None


def _check(c, ws: int, body: StaffIn, sid: int | None = None) -> str:
    name = " ".join(body.name.split())[:100]
    if not name:
        raise HTTPException(400, "Нужно имя")
    if c.execute("SELECT 1 FROM staff WHERE workspace_id=%s AND lower(name)=lower(%s) AND id IS DISTINCT FROM %s", (ws, name, sid)).fetchone():
        raise HTTPException(400, "Менеджер с таким именем уже есть")
    if body.user_id is not None:
        if not c.execute("SELECT 1 FROM memberships WHERE workspace_id=%s AND user_id=%s", (ws, body.user_id)).fetchone():
            raise HTTPException(400, "Пользователь не состоит в кабинете")
        if c.execute("SELECT 1 FROM staff WHERE workspace_id=%s AND user_id=%s AND id IS DISTINCT FROM %s", (ws, body.user_id, sid)).fetchone():
            raise HTTPException(400, "Этот пользователь уже привязан к другому менеджеру")
    return name


@router.post("/api/workspaces/{ws}/staff")
def staff_add(ws: int, body: StaffIn, u=Depends(current_user), c=Depends(conn)):
    _ws(c, u, ws, "editor")
    name = _check(c, ws, body)
    sid = c.execute("INSERT INTO staff(workspace_id,name,user_id) VALUES (%s,%s,%s) RETURNING id", (ws, name, body.user_id)).fetchone()["id"]
    _audit(c, u, ws, "staff", {"add": name, "user_id": body.user_id})
    c.commit()
    return {"id": sid}


@router.put("/api/staff/{sid}")
def staff_edit(sid: int, body: StaffIn, u=Depends(current_user), c=Depends(conn)):
    s = _staff(c, u, sid, "editor")
    name = _check(c, s["workspace_id"], body, sid)
    c.execute("UPDATE staff SET name=%s, user_id=%s WHERE id=%s", (name, body.user_id, sid))
    _audit(c, u, s["workspace_id"], "staff", {"edit": sid, "name": name, "user_id": body.user_id})
    c.commit()
    return {"ok": True}


@router.delete("/api/staff/{sid}")
def staff_del(sid: int, u=Depends(current_user), c=Depends(conn)):
    """Удалить менеджера — его артикулы остаются без менеджера (данные магазина не трогаем)."""
    s = _staff(c, u, sid, "editor")
    c.execute("DELETE FROM staff WHERE id=%s", (sid,))
    _audit(c, u, s["workspace_id"], "staff", {"delete": s["name"]})
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/staff")
def shop_staff(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Для фильтра и экрана назначения: менеджеры кабинета и кто за каким артикулом магазина."""
    role = auth.shop_role(c, u, shop_id)
    if not auth.can(role, "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    ws = c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop_id,)).fetchone()["workspace_id"]
    st = c.execute("""SELECT s.id, s.name, s.user_id, (SELECT count(*) FROM staff_articles a WHERE a.staff_id=s.id AND a.account_id=%s) n
                      FROM staff s WHERE s.workspace_id=%s ORDER BY lower(s.name)""", (shop_id, ws)).fetchall()
    assign = {r["nm_id"]: r["staff_id"] for r in c.execute("SELECT nm_id, staff_id FROM staff_articles WHERE account_id=%s", (shop_id,))}
    return jsonable_encoder({"workspace_id": ws, "staff": st, "assign": assign, "me": next((s["id"] for s in st if s["user_id"] == u["id"]), None),
                             "can_edit": auth.can(role, "editor")})


class AssignIn(BaseModel):
    nm_ids: list[int]
    staff_id: int | None = None


@router.put("/api/shops/{shop_id}/staff/assign")
def shop_assign(shop_id: int, body: AssignIn, u=Depends(current_user), c=Depends(conn)):
    """Назначить менеджера артикулам (staff_id пусто — снять)."""
    if not auth.can(auth.shop_role(c, u, shop_id), "editor"):
        raise HTTPException(403, "Нужна роль «редактор» или выше")
    if not body.nm_ids or len(body.nm_ids) > 20000:
        raise HTTPException(400, "Список артикулов")
    ws = c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop_id,)).fetchone()["workspace_id"]
    if body.staff_id is None:
        c.execute("DELETE FROM staff_articles WHERE account_id=%s AND nm_id = ANY(%s)", (shop_id, body.nm_ids))
    else:
        if not c.execute("SELECT 1 FROM staff WHERE id=%s AND workspace_id=%s", (body.staff_id, ws)).fetchone():
            raise HTTPException(400, "Менеджер не из этого кабинета")
        c.execute("""INSERT INTO staff_articles(account_id,nm_id,staff_id) SELECT %s, x, %s FROM unnest(%s::bigint[]) x
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET staff_id=EXCLUDED.staff_id, updated_at=now()""",
                  (shop_id, body.staff_id, body.nm_ids))
    _audit(c, u, ws, "staff", {"shop": shop_id, "assign": body.staff_id, "n": len(body.nm_ids)})
    c.commit()
    return {"ok": True}


@router.post("/api/workspaces/{ws}/staff/import")
async def staff_import(ws: int, request: Request, name: str = "", apply: bool = False, u=Depends(current_user), c=Depends(conn)):
    """Файл «артикул → менеджер» (xlsx/csv) по всем магазинам кабинета, где у пользователя роль редактора. apply=false — только превью."""
    _ws(c, u, ws, "editor")
    raw = await request.body()
    if len(raw) > 30_000_000:
        raise HTTPException(400, "Файл больше 30 МБ")
    try:
        items = staff.parse(raw, name)
    except CostImportError as e:
        raise HTTPException(400, str(e)) from None
    shops = [s for s in auth.shops_for(c, u) if s["workspace_id"] == ws and auth.can(auth.shop_role(c, u, s["id"]), "editor")]
    m = staff.match(c, shops, items)
    if apply:
        staff.apply(c, ws, m["write"])
        _audit(c, u, ws, "staff", {"import": name[:80], "n": len(m["write"]), "unknown": m["unknown"]})
        c.commit()
    return jsonable_encoder({**{k: v for k, v in m.items() if k != "write"}, "changes": len(m["write"]), "applied": apply})

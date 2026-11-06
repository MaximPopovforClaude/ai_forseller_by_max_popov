"""Self-hosted application component."""

import io
import json
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel

from . import auth, mcp
from .web import _audit, conn, current_user

router = APIRouter()
EXT_DIR = Path(__file__).resolve().parent.parent / "extension"
NAME = "Плагин Chrome"


class TokenIn(BaseModel):
    workspace_id: int


@router.post("/api/plugin/token")
def token(body: TokenIn, u=Depends(current_user), c=Depends(conn)):
    if u.get("_mcp"):
        raise HTTPException(403, "Код плагина выдаёт только человек на сайте")
    if not any(w["id"] == body.workspace_id and not w.get("support") for w in auth.workspaces_for(c, u)):
        raise HTTPException(403, "Нет доступа к кабинету")
    old = c.execute("UPDATE mcp_grants SET revoked_at=now() WHERE user_id=%s AND workspace_id=%s AND kind='plugin' AND revoked_at IS NULL",
                    (u["id"], body.workspace_id)).rowcount
    try:
        gid, tok = mcp.create(c, u, body.workspace_id, NAME, "platform", ["platform:plugin"], None, 365, kind="plugin")
    except mcp.Denied as e:
        raise HTTPException(400, str(e)) from None
    _audit(c, u, body.workspace_id, "plugin/token", {"grant": gid, "revoked_old": old})
    c.commit()
    return {"token": tok, "revoked_old": old}


def _shops(c, u) -> list[dict]:
    out = []
    for s in auth.shops_for(c, u):
        if s.get("support"):
            continue
        m = re.fullmatch(r"wb(\d+)", s["name"] or "")
        out.append({"id": s["id"], "title": s["title"] or s["name"], "marketplace": s["marketplace"], "role": s["role"],
                    "supplier_id": int(m.group(1)) if m else None})
    return out


@router.get("/api/plugin/me")
def me(u=Depends(current_user), c=Depends(conn)):
    return {"name": u.get("name") or u.get("email"), "shops": _shops(c, u), "plugin": bool(u.get("_mcp"))}


@router.get("/api/plugin/card/{nm}")
def card(nm: int, u=Depends(current_user), c=Depends(conn)):
    from . import shelf_view
    shops = [s for s in _shops(c, u) if s["marketplace"] == "wb"]
    ids = [s["id"] for s in shops]
    own = c.execute("""SELECT n.account_id, n.vendor_code, n.title, n.subject FROM nomenclature n
                       WHERE n.nm_id=%s AND n.account_id = ANY(%s) LIMIT 1""", (nm, ids)).fetchone() if ids else None
    shop = own["account_id"] if own else (ids[0] if ids else None)
    if shop is None:
        return {"nm_id": nm, "own": None, "shelves": None}
    d = shelf_view.detail(c, shop, nm, ids)
    if own:
        own = {**own, "shop": next(s["title"] for s in shops if s["id"] == own["account_id"])}
        sc = c.execute("SELECT price, spp, checked_at FROM wb_showcase WHERE account_id=%s AND nm_id=%s", (own["account_id"], nm)).fetchone()
        mr = c.execute("SELECT mrc FROM mrc_items WHERE account_id=%s AND nm_id=%s", (own["account_id"], nm)).fetchone()
        own.update(showcase=sc, mrc=mr["mrc"] if mr else None)
    sh = None
    if d.get("day"):
        sh = {"day": d["day"], "was_day": d["was_day"], "taken": d["taken"], "total": d["shelf_total"],
              "where_n": len(d["where"]), "where_gone_n": len(d["where_gone"]),
              "where": d["where"][:30], "shelf": d["shelf"][:30], "hist": d["hist"][-30:]}
    return jsonable_encoder({"nm_id": nm, "own": own, "shelves": sh})


class TraceIn(BaseModel):
    page: str | None = None
    items: list[dict]


_SECRET = re.compile(r"(?i)(token|authoriz|password|passwd|secret|cookie|session|sign)")


def _clean(o, depth=0):
    """Тело запроса — без значений, похожих на ключи/пароли (на всякий случай: плагин и так не шлёт заголовки)."""
    if depth > 6:
        return None
    if isinstance(o, dict):
        return {k: ("[скрыто]" if _SECRET.search(str(k)) else _clean(v, depth + 1)) for k, v in list(o.items())[:200]}
    if isinstance(o, list):
        return [_clean(v, depth + 1) for v in o[:200]]
    if isinstance(o, str):
        return o[:2000]
    return o


@router.post("/api/plugin/trace")
def trace(body: TraceIn, u=Depends(current_user), c=Depends(conn)):
    if len(body.items) > 2000:
        raise HTTPException(400, "Слишком длинная запись")
    items = []
    for it in body.items:
        url = str(it.get("url") or "")[:2000]
        url = re.sub(r"(?i)([?&][^=&]*(token|sign|key|auth)[^=&]*=)[^&]*", r"\1[скрыто]", url)
        items.append({"t": it.get("t"), "method": str(it.get("method") or "")[:10], "url": url, "type": it.get("type"),
                      "status": it.get("status"), "ctype": str(it.get("ctype") or "")[:100], "body": _clean(it.get("body"))})
    g = u.get("_mcp") or {}
    rid = c.execute("INSERT INTO plugin_traces(user_id,grant_id,page,data) VALUES (%s,%s,%s,%s) RETURNING id",
                    (u["id"], g.get("id"), (body.page or "")[:500], json.dumps(items, ensure_ascii=False))).fetchone()["id"]
    c.commit()
    return {"ok": True, "id": rid, "n": len(items)}


@router.post("/api/plugin/entry/{shop_id}")
async def entry(shop_id: int, request: Request, name: str = "", u=Depends(current_user), c=Depends(conn)):
    """shop_id=0 — магазин определить по артикулам отчёта (плагин качает из того кабинета, что открыт у пользователя)."""
    from . import entry as ent
    raw, name = await request.body(), (name or "plugin.xlsx")[:200]
    if not shop_id:
        try:
            nms = {r["nm_id"] for r in ent.parse(raw, name)["rows"]}
        except ent.EntryError as e:
            raise HTTPException(400, str(e)) from None
        best = (0, 0)
        for s in _shops(c, u):
            if s["marketplace"] == "wb" and auth.can(s["role"], "editor"):
                n = c.execute("SELECT count(*) n FROM nomenclature WHERE account_id=%s AND nm_id = ANY(%s)", (s["id"], list(nms))).fetchone()["n"]
                best = max(best, (n, s["id"]))
        if not best[0]:
            raise HTTPException(400, "Артикулы отчёта не нашлись ни в одном вашем магазине WB (с ролью «редактор» и выше)")
        shop_id = best[1]
    if not auth.can(auth.shop_role(c, u, shop_id), "editor"):
        raise HTTPException(403, "Нужна роль «редактор» или выше в этом магазине")
    acc = c.execute("SELECT id, workspace_id, title FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    try:
        r = ent.save(c, shop_id, u["id"], raw, name)
    except ent.EntryError as e:
        c.rollback()
        raise HTTPException(400, str(e)) from None
    _audit(c, u, acc["workspace_id"], "entry_points/plugin", {"shop": shop_id, "period": f"{r['d_from']}..{r['d_to']}", "rows": r["rows"]})
    c.commit()
    return jsonable_encoder({"ok": True, "shop": acc["title"], "shop_id": shop_id, **{k: r[k] for k in ("d_from", "d_to", "rows")}})


@router.get("/api/plugin/entry_days")
def entry_days(u=Depends(current_user), c=Depends(conn)):
    """Дневные отчёты «Точки входа», которые уже есть: {магазин: [дни]} — плагин докачивает недостающие."""
    ids = [s["id"] for s in _shops(c, u) if s["marketplace"] == "wb"]
    from .config import today_msk
    from .entry_coverage import daily_days, expected_days
    today = today_msk()
    days = expected_days(today, 120)
    out = daily_days(c, ids, days[-1], days[0])
    return jsonable_encoder({"days": {shop: sorted(have) for shop, have in out.items()}, "shops": ids,
                             "expected_days": expected_days(today)})


@router.get("/api/plugin/download")
def download():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(EXT_DIR.rglob("*")):
            if f.is_file():
                z.write(f, "seller-analytics-plugin/" + str(f.relative_to(EXT_DIR)))
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="seller-analytics-plugin.zip"'})

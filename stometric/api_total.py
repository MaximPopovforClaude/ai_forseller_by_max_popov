"""Self-hosted application component."""

from datetime import date, timedelta

import psycopg
from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder

from . import auth
from .config import today_msk
from .materialize import NotReady
from .web import _cached, conn, current_user

router = APIRouter()

KEYS = ("orders", "buyouts", "margin", "ads", "profit")
WB_ROW = {"orders": 4, "buyouts": 18, "margin": 24, "ads": 26, "profit": 32}

OZ_MARGIN = ("b_sum", "r_sum", "f_com", "f_log", "f_acq")


def _wb(c, shop: int, f: dict) -> tuple[dict, bool]:
    res = _cached(c, "by_days", shop, f)
    rows = {r["row"]: r for r in res["rows"]}
    days = [col["field"] for col in res["columns"] if len(col["field"]) == 10]   
    return {d: {k: float(rows[n].get(d) or 0) for k, n in WB_ROW.items()} for d in days}, res.get("stale")


def _oz(c, shop: int, f: dict) -> tuple[dict, bool]:
    res = _cached(c, "oz_dash", shop, f)
    rows = {r["key"]: r for r in res["rows"] if r.get("key")}
    y = min(f["date_to"], today_msk() - timedelta(days=1))           
    n = sum(1 for col in res["columns"] if col["field"].startswith("d"))
    out = {}
    for i in range(n):
        d, g = (y - timedelta(days=i)).isoformat(), (lambda k: float(rows.get(k, {}).get(f"d{i}") or 0))
        out[d] = {"orders": g("o_sum"), "buyouts": g("b_sum"), "ads": g("ads"), "profit": g("f_profit"),
                  "margin": sum(g(k) for k in OZ_MARGIN) - g("b_cost")}
    return out, res.get("stale")


def _ym(c, shop: int, f: dict) -> tuple[dict, bool]:
    res = _cached(c, "ym_dash", shop, f)
    rows = {r["key"]: r for r in res["rows"] if r.get("key")}
    y = min(f["date_to"], today_msk())                                 
    n = sum(1 for col in res["columns"] if col["field"].startswith("d"))
    out = {}
    for i in range(n):
        d, g = (y - timedelta(days=i)).isoformat(), (lambda k: float(rows.get(k, {}).get(f"d{i}") or 0))
        
        out[d] = {"orders": g("o_sum"), "buyouts": g("b_sum"), "ads": g("x_boost"), "profit": g("f_profit"),
                  "margin": g("b_sum") - g("r_sum") + g("x_total") - g("x_boost") - g("b_cost")}
    return out, res.get("stale")


@router.get("/api/total")
def total(staff: int | None = None, u=Depends(current_user), c=Depends(conn)):
    """Ряды по дням (30 дней до сегодня) по каждому магазину пользователя; staff — только артикулы менеджера (магазины, где они есть)."""
    dt = today_msk()
    f = {"date_from": dt - timedelta(days=29), "date_to": dt, "nm_ids": None, "group": None}     
    shops, days = [], set()
    own = None
    if staff:
        from . import staff as st
        ws = c.execute("SELECT workspace_id FROM staff WHERE id=%s", (staff,)).fetchone()
        own = {s["id"]: st.nms(c, s["id"], staff) for s in auth.shops_for(c, u) if ws and s["workspace_id"] == ws["workspace_id"]}
    for s in auth.shops_for(c, u):
        if own is not None and not own.get(s["id"]):
            continue
        item = {"id": s["id"], "title": s["title"] or s["name"], "mp": s["marketplace"], "workspace": s["workspace"]}
        try:
            series, stale = {"ozon": _oz, "ym": _ym}.get(s["marketplace"], _wb)(c, s["id"], {**f, "nm_ids": own[s["id"]]} if own else f)
            item.update(series=series, stale=bool(stale))
            days |= set(series)
        except (NotReady, psycopg.errors.QueryCanceled):
            c.rollback()
            item["error"] = "данные ещё готовятся"
        except Exception as e:  
            c.rollback()
            item["error"] = f"не посчитался ({type(e).__name__})"
        shops.append(item)
    staff_list = c.execute("""SELECT s.id, s.name, w.name workspace FROM staff s JOIN workspaces w ON w.id=s.workspace_id
                              WHERE s.workspace_id = ANY(%s) AND EXISTS (SELECT 1 FROM staff_articles a WHERE a.staff_id=s.id)
                              ORDER BY w.name, lower(s.name)""", (list({s["workspace_id"] for s in auth.shops_for(c, u)}),)).fetchall()
    return jsonable_encoder({"staff": staff_list, "days": sorted(d for d in days if date.fromisoformat(d) >= f["date_from"]), "today": dt.isoformat(),
                             "keys": KEYS, "shops": shops})

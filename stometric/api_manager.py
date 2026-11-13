"""API пункта управления менеджера: действия по артикулам, план продаж, онлайн-цена (черновики цен), прочие расходы."""

import csv
import io
import json
import time
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from pydantic import BaseModel

from . import auth, manager
from .web import _audit, conn, current_user

router = APIRouter()


def _role(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    return c.execute("SELECT id, workspace_id FROM accounts WHERE id=%s", (shop_id,)).fetchone()


@router.get("/api/shops/{shop_id}/manager/board")
def board(shop_id: int, days: int = 14, date_to: date | None = None, ads: bool = False, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**manager.board(c, shop_id, max(3, min(days, 60)), date_to, ads), "me": u["id"],
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.get("/api/shops/{shop_id}/manager/charts")
def board_charts(shop_id: int, date_to: date | None = None, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    from . import action_charts
    from .materialize import NotReady
    import psycopg
    try:
        return jsonable_encoder(action_charts.get(c, shop_id, date_to))
    except (NotReady, psycopg.errors.QueryCanceled) as e:
        c.rollback()
        return {"error": str(e) if isinstance(e, NotReady) else "Графики не успели загрузиться. Повторите позже."}


class ActionItem(BaseModel):
    kind: str
    value: str | None = None
    note: str | None = None


class ActionsIn(BaseModel):
    nm_ids: list[int]
    day: date
    items: list[ActionItem]


@router.post("/api/shops/{shop_id}/actions")
def add_actions(shop_id: int, body: ActionsIn, u=Depends(current_user), c=Depends(conn)):
    """Несколько действий сразу — по одному или нескольким артикулам (выделенные строки) на дату."""
    acc = _role(c, u, shop_id, "editor")
    if not body.nm_ids or not body.items or len(body.nm_ids) > 1000 or len(body.items) > 20:
        raise HTTPException(400, "Выберите артикулы и хотя бы одно действие")
    own = {r["nm_id"] for r in c.execute("""SELECT nm_id FROM nomenclature WHERE account_id=%(a)s AND nm_id = ANY(%(n)s)
                                           UNION SELECT sku FROM oz_products WHERE account_id=%(a)s AND sku = ANY(%(n)s)""",
                                        {"a": shop_id, "n": body.nm_ids})}
    if own != set(body.nm_ids):
        raise HTTPException(400, "Артикул не из этого магазина")
    n = 0
    for it in body.items:
        kind = it.kind.strip()
        if kind not in manager.KIND_KEYS and not (kind.startswith("custom:") and 8 <= len(kind) <= 60):
            raise HTTPException(400, f"Неизвестный вид действия: {kind}")
        for nm in body.nm_ids:
            c.execute("INSERT INTO nm_actions(account_id,nm_id,day,kind,value,note,user_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                      (shop_id, nm, body.day, kind, (it.value or "").strip()[:60] or None, (it.note or "").strip()[:500] or None, u["id"]))
            n += 1
    _audit(c, u, acc["workspace_id"], "actions/add", {"shop": shop_id, "day": str(body.day), "nm": len(body.nm_ids), "n": n})
    c.commit()
    return {"ok": True, "added": n}


@router.delete("/api/shops/{shop_id}/actions/{aid}")
def del_action(shop_id: int, aid: int, u=Depends(current_user), c=Depends(conn)):
    """Убрать свою запись (ошибся); чужую — админ кабинета."""
    acc = _role(c, u, shop_id, "editor")
    a = c.execute("SELECT * FROM nm_actions WHERE id=%s AND account_id=%s", (aid, shop_id)).fetchone()
    if not a:
        raise HTTPException(404, "Нет такой записи")
    if a["user_id"] != u["id"] and not auth.can(auth.shop_role(c, u, shop_id), "admin"):
        raise HTTPException(403, "Чужую запись убирает админ кабинета")
    c.execute("DELETE FROM nm_actions WHERE id=%s", (aid,))
    _audit(c, u, acc["workspace_id"], "actions/delete", {"shop": shop_id, "action": {k: str(v) for k, v in a.items()}})
    c.commit()
    return {"ok": True}


class PlanQty(BaseModel):
    nm_id: int
    month: date
    qty: float | None


@router.put("/api/shops/{shop_id}/nm_plan")
def set_plan(shop_id: int, body: PlanQty, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "editor")
    m = body.month.replace(day=1)
    if body.qty is None:
        c.execute("DELETE FROM nm_plans WHERE account_id=%s AND nm_id=%s AND month=%s", (shop_id, body.nm_id, m))
    else:
        if not 0 <= body.qty <= 10_000_000:
            raise HTTPException(400, "Странный план")
        c.execute("""INSERT INTO nm_plans(account_id,nm_id,month,qty) VALUES (%s,%s,%s,%s)
                     ON CONFLICT (account_id,nm_id,month) DO UPDATE SET qty=EXCLUDED.qty""", (shop_id, body.nm_id, m, body.qty))
    c.commit()
    return {"ok": True}



@router.get("/api/shops/{shop_id}/manager/prices")
def prices(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**manager.price_lab(c, shop_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class DraftIn(BaseModel):
    price: float | None


@router.put("/api/shops/{shop_id}/manager/prices/{nm_id}")
def set_draft(shop_id: int, nm_id: int, body: DraftIn, u=Depends(current_user), c=Depends(conn)):
    """Черновик «Расчётной цены» — общий для сотрудников магазина; null — убрать. Цена в WB не меняется (API только чтение)."""
    acc = _role(c, u, shop_id, "editor")
    if body.price is None:
        c.execute("DELETE FROM price_drafts WHERE account_id=%s AND nm_id=%s", (shop_id, nm_id))
    else:
        if not 1 <= body.price <= 10_000_000:
            raise HTTPException(400, "Цена — от 1 ₽")
        c.execute("""INSERT INTO price_drafts(account_id,nm_id,price,user_id) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id)
                     DO UPDATE SET price=EXCLUDED.price, user_id=EXCLUDED.user_id, updated_at=now()""", (shop_id, nm_id, body.price, u["id"]))
    _audit(c, u, acc["workspace_id"], "price/draft", {"shop": shop_id, "nm_id": nm_id, "price": body.price})
    c.commit()
    return {"ok": True}


class TokenIn(BaseModel):
    token: str
    provider: str | None = None      
    model: str | None = None


class PctIn(BaseModel):
    value: float


@router.put("/api/shops/{shop_id}/manager/other_pct")
def set_other(shop_id: int, body: PctIn, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    if not 0 <= body.value <= 0.5:
        raise HTTPException(400, "Доля от 0 до 0.5 (3 % = 0.03)")
    c.execute("""INSERT INTO shop_settings(account_id,key,value) VALUES (%s,'other_pct',%s) ON CONFLICT (account_id,key)
                 DO UPDATE SET value=EXCLUDED.value, updated_at=now()""", (shop_id, json.dumps(body.value)))
    _audit(c, u, acc["workspace_id"], "price/other_pct", {"shop": shop_id, "value": body.value})
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/manager/prices.csv")
def drafts_csv(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Список новых цен для загрузки в ЛК WB вручную: артикул, новая цена до скидки, скидка, цена со скидкой."""
    _role(c, u, shop_id, "viewer")
    rows = [r for r in manager.price_lab(c, shop_id)["rows"] if r["draft"] is not None]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    oz = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()["marketplace"] == "ozon"
    w.writerow(["SKU Ozon" if oz else "Артикул WB", "Артикул продавца", "Текущая цена до скидки", "Новая цена до скидки", "Скидка, %", "Цена со скидкой (расчётная)",
                "Маржа сейчас, ₽", "Маржа по новой цене, ₽"])
    for r in rows:
        w.writerow([r["nm_id"], r["vendor_code"], r["base_price"], r["new_base"], r["discount"], r["calc_price"], r["margin_online"], r["margin_calc"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=new_prices_{shop_id}.csv"})



@router.get("/api/shops/{shop_id}/competitors/{nm_id}")
def comp_compare(shop_id: int, nm_id: int, period: int = 30, u=Depends(current_user), c=Depends(conn)):
    from . import market
    _role(c, u, shop_id, "viewer")
    if not c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, nm_id)).fetchone():
        raise HTTPException(404, "Нет такого артикула в магазине")
    return jsonable_encoder({**market.compare(c, shop_id, nm_id, period if period in (7, 14, 30, 60, 90) else 30),
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.get("/api/shops/{shop_id}/competitors/{nm_id}/suggest")
def comp_suggest(shop_id: int, nm_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import market
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder(market.suggest(c, shop_id, nm_id))


class CompIn(BaseModel):
    comp_nm_ids: list[int]
    note: str | None = None


@router.post("/api/shops/{shop_id}/competitors/{nm_id}")
def comp_add(shop_id: int, nm_id: int, body: CompIn, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    ids = [i for i in dict.fromkeys(body.comp_nm_ids) if 0 < i < 10 ** 12 and i != nm_id]
    if not ids or len(ids) > 30:
        raise HTTPException(400, "Артикулы конкурентов — числа, до 30 за раз")
    have = c.execute("SELECT count(*) n FROM competitors WHERE account_id=%s", (shop_id,)).fetchone()["n"]
    if have + len(ids) > 500:
        raise HTTPException(400, "Не больше 500 конкурентов на магазин")
    for i in ids:
        c.execute("""INSERT INTO competitors(account_id,nm_id,comp_nm_id,note,added_by) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT DO NOTHING""", (shop_id, nm_id, i, (body.note or "").strip()[:200] or None, u["id"]))
    _audit(c, u, acc["workspace_id"], "competitors/add", {"shop": shop_id, "nm_id": nm_id, "ids": ids})
    c.commit()
    return {"ok": True}


@router.delete("/api/shops/{shop_id}/competitors/{nm_id}/{comp_nm_id}")
def comp_del(shop_id: int, nm_id: int, comp_nm_id: int, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    c.execute("DELETE FROM competitors WHERE account_id=%s AND nm_id=%s AND comp_nm_id=%s", (shop_id, nm_id, comp_nm_id))
    _audit(c, u, acc["workspace_id"], "competitors/remove", {"shop": shop_id, "nm_id": nm_id, "comp": comp_nm_id})
    c.commit()
    return {"ok": True}


@router.get("/api/shops/{shop_id}/competitors")
def comp_list(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Сколько конкурентов у каждого нашего артикула (для списка слева)."""
    _role(c, u, shop_id, "viewer")
    return c.execute("SELECT nm_id, count(*) n FROM competitors WHERE account_id=%s GROUP BY 1", (shop_id,)).fetchall()



@router.get("/api/shops/{shop_id}/insights")
def insights_get(shop_id: int, day: date | None = None, rebuild: bool = False, staff: int | None = None, u=Depends(current_user), c=Depends(conn)):
    from . import insights, ai_routing
    _role(c, u, shop_id, "editor" if rebuild else "viewer")
    route = ai_routing.shop_route(c, shop_id, u['id'])
    acc = c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if staff and not c.execute("SELECT 1 FROM staff WHERE id=%s AND workspace_id=%s", (staff, acc["workspace_id"])).fetchone():
        staff = None
    from .materialize import NotReady
    try:
        res = insights.get(c, shop_id, day, rebuild=rebuild, staff_id=staff, actor_id=u['id'])
    except NotReady as e:
        raise HTTPException(409, str(e)) from None
    return jsonable_encoder({**res, **route})




SECRET_KINDS = ("wildbox", "claude", "openai_images")


def _secret_can_edit(c, u, ws_id: int, kind: str) -> bool:
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        return False
    if kind in ("openai_images", "claude"):
        
        r = c.execute("SELECT role, shop_ids FROM memberships WHERE workspace_id=%s AND user_id=%s", (ws_id, u["id"])).fetchone()
        return bool(r and r["role"] in ("admin", "owner") and r["shop_ids"] is None)
    return True


def _check_secret(kind: str, tok) -> str | None:
    from . import llm, market
    if kind == "openai_images":
        from .openai_images import check_key
        return check_key(tok)
    return market.check_token(tok) if kind == "wildbox" else llm.check(tok)


@router.get("/api/workspaces/{ws_id}/secret/{kind}")
def secret_get(ws_id: int, kind: str, u=Depends(current_user), c=Depends(conn)):
    if kind not in SECRET_KINDS or not auth.can(auth.workspace_role(c, u, ws_id), "viewer"):
        raise HTTPException(403, "Нет доступа к кабинету")
    r = c.execute("""SELECT s.added_at, coalesce(x.name, x.email) who FROM workspace_secrets s LEFT JOIN users x ON x.id=s.added_by
                     WHERE s.workspace_id=%s AND s.kind=%s""", (ws_id, kind)).fetchone()
    plan = c.execute("SELECT plan FROM workspaces WHERE id=%s", (ws_id,)).fetchone()["plan"]
    out = {"connected": bool(r), "added_at": r and r["added_at"], "who": r and r["who"], "plan": plan,
           "can_edit": _secret_can_edit(c, u, ws_id, kind)}
    if kind == "claude":
        from . import ai_routing, llm
        
        
        out.update(**ai_routing.workspace_route(c, ws_id, u['id']), can_edit=_secret_can_edit(c, u, ws_id, kind),
                   provider=None, model=None,
                   providers=[{"id": pid, "title": p["title"], "model": p["model"], "keys": p["keys"]} for pid, p in llm.PROVIDERS.items()])
    return jsonable_encoder(out)


@router.put("/api/workspaces/{ws_id}/secret/{kind}")
def secret_set(ws_id: int, kind: str, body: TokenIn, u=Depends(current_user), c=Depends(conn)):
    from . import vault
    if kind not in SECRET_KINDS or not _secret_can_edit(c, u, ws_id, kind):
        raise HTTPException(403, "Ключ меняет админ или владелец кабинета")
    tok = body.token.strip()
    if not 20 <= len(tok) <= 4000 or any(ch.isspace() or ord(ch) < 32 or ord(ch) > 126 for ch in tok):
        raise HTTPException(400, "Похоже, это не ключ — скопируйте его целиком")
    blob, det = tok, {}
    if kind == "claude":
        from . import llm
        prov = body.provider or llm.ANTHROPIC
        if prov not in llm.PROVIDERS:
            raise HTTPException(400, "Неизвестная нейросеть")
        model = (body.model or "").strip()[:80] or None
        tok = llm.AiKey(tok, prov, model)
        blob, det = llm.to_secret(prov, tok, model), {"provider": prov, "model": model}
    err = _check_secret(kind, tok)
    if err:
        raise HTTPException(400, err)
    c.execute("""INSERT INTO workspace_secrets(workspace_id,kind,enc,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id,kind)
                 DO UPDATE SET enc=EXCLUDED.enc, added_by=EXCLUDED.added_by, added_at=now()""", (ws_id, kind, vault.encrypt(blob), u["id"]))
    _audit(c, u, ws_id, f"{kind}/set", det)
    c.commit()
    return {"ok": True}


@router.delete("/api/workspaces/{ws_id}/secret/{kind}")
def secret_del(ws_id: int, kind: str, u=Depends(current_user), c=Depends(conn)):
    if kind not in SECRET_KINDS or not _secret_can_edit(c, u, ws_id, kind):
        raise HTTPException(403, "Ключ меняет админ или владелец кабинета")
    c.execute("DELETE FROM workspace_secrets WHERE workspace_id=%s AND kind=%s", (ws_id, kind))
    _audit(c, u, ws_id, f"{kind}/remove", {})
    c.commit()
    return {"ok": True}



@router.get("/api/shops/{shop_id}/ai_report")
def ai_report(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    from . import aireport, ai_routing
    route = ai_routing.shop_route(c, shop_id, u['id'])
    has_key = route['ai_ready']
    can = has_key and auth.can(auth.shop_role(c, u, shop_id), "editor")
    d = c.execute("SELECT max(day) d FROM ai_reports WHERE account_id=%s", (shop_id,)).fetchone()["d"]
    if not d:
        from .api_compare import for_shop_home
        return jsonable_encoder({"day": None, "sections": [], "has_key": has_key, "can_build": can, "compare": for_shop_home(c, shop_id),
                                 **aireport.build_status(c, shop_id), **route})
    
    order = ["day", "money", "cabinet", "search", "competitors", "niche"]
    rows = c.execute("""SELECT DISTINCT ON (section) section, title, body, source, model, created_at, day FROM ai_reports WHERE account_id=%s
                        AND day >= %s - 14 ORDER BY section, day DESC""", (shop_id, d)).fetchall()
    old_cab = [r for r in rows if r["section"] == "cabinet" and r["title"] == "Ключевые ошибки в кабинете"]   
    rows = [r for r in rows if r["section"] in order and (r["section"] != "cabinet" or not old_cab or not any(x["section"] == "day" for x in rows))]
    rows.sort(key=lambda r: order.index(r["section"]))
    from . import aireport
    for r in rows:
        r["kind"] = "day" if r["section"] in aireport.DAILY else "week"
    from .api_compare import for_shop_home
    return jsonable_encoder({"day": d, "sections": rows, "has_key": has_key, "can_build": can, "compare": for_shop_home(c, shop_id),
                             **aireport.build_status(c, shop_id), **route})


@router.post("/api/shops/{shop_id}/ai_report/build")
def ai_report_build(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Пересобрать сводку через разрешённую нейросеть магазина в фоне."""
    import threading
    from . import aireport, db, ai_routing
    _role(c, u, shop_id, "editor")
    route = ai_routing.shop_route(c, shop_id, u['id'])
    if not route['ai_ready']:
        raise HTTPException(400, route['ai_reason'])
    state = aireport.build_status(c, shop_id)
    if state.get('review_required'):
        raise HTTPException(409, 'Предыдущая сводка прервана или её исполнение не подтверждено. '
                            'Сначала нужно выяснить причину; автоматический повтор запрещён.')
    if state["building"]:
        return {"ok": True, "busy": True, **state, "message": "Сводка этого магазина уже собирается. Готовые разделы появятся автоматически."}

    def run():
        with db.connect() as c2:
            c2._ai_actor_id = u["id"]
            print("ai_report:", shop_id, aireport.build(c2, shop_id, weekly=True), flush=True)
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "expected_sections": state["expected_sections"],
            "message": "Собираю сводку. Это может занять 15–20 минут или дольше; готовые разделы появятся автоматически."}



@router.get("/api/shops/{shop_id}/plan")
def plan_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import market, planning
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**planning.table(c, shop_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor"),
                             "wildbox": bool(market.shop_token(c, shop_id))})


@router.post("/api/shops/{shop_id}/plan/auto")
def plan_auto(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Авто-построение фоном: главные запросы → сезонность (Wildbox) → авто-ячейки. Ручные ячейки не трогаем."""
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    if c.execute("SELECT 1 FROM plan_runs WHERE account_id=%s AND status='running' AND started_at > now() - interval '1 hour'", (shop_id,)).fetchone():
        raise HTTPException(400, "Построение уже идёт")
    planning.start(shop_id, u["id"])
    _audit(c, u, acc["workspace_id"], "plan/auto", {"shop": shop_id})
    c.commit()
    return {"ok": True}


class PlanCellIn(BaseModel):
    nm_id: int
    month: date
    field: str                       
    value: float | None              


@router.put("/api/shops/{shop_id}/plan/cell")
def plan_cell(shop_id: int, body: PlanCellIn, u=Depends(current_user), c=Depends(conn)):
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    if body.field not in ("qty", "price", "cost"):
        raise HTTPException(400, "Править можно штуки, цену и себестоимость")
    if body.value is not None and not 0 <= body.value <= 100_000_000:
        raise HTTPException(400, "Странное значение")
    m = body.month.replace(day=1)
    f = body.field
    if body.value is None:   
        c.execute(f"UPDATE plan_cells SET {f}_src='auto' WHERE account_id=%s AND nm_id=%s AND month=%s", (shop_id, body.nm_id, m))
        c.commit()
        planning.fill(c, shop_id, u["id"])
    else:
        c.execute(f"""INSERT INTO plan_cells(account_id,nm_id,month,{f},{f}_src,updated_by) VALUES (%s,%s,%s,%s,'manual',%s)
                      ON CONFLICT (account_id,nm_id,month) DO UPDATE SET {f}=EXCLUDED.{f}, {f}_src='manual', updated_by=EXCLUDED.updated_by,
                      updated_at=now()""", (shop_id, body.nm_id, m, body.value, u["id"]))
    _audit(c, u, acc["workspace_id"], "plan/cell", {"shop": shop_id, **body.model_dump(mode="json")})
    c.commit()
    return {"ok": True}


class PlanItemIn(BaseModel):
    nm_id: int
    main_query: str | None = None
    ads_share: float | None = None
    reset_ads: bool = False
    method: str | None = None        


@router.put("/api/shops/{shop_id}/plan/item")
def plan_item(shop_id: int, body: PlanItemIn, u=Depends(current_user), c=Depends(conn)):
    """Главный запрос артикула вручную (сезонность подтянется при следующем авто-построении) и доля рекламы."""
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    if body.method is not None:
        if body.method not in ("auto", "sales", "query", "manual", "flat"):
            raise HTTPException(400, "Способ: auto, sales, query, manual или flat")
        c.execute("""INSERT INTO plan_items(account_id,nm_id,method) VALUES (%s,%s,%s) ON CONFLICT (account_id,nm_id)
                     DO UPDATE SET method=EXCLUDED.method, updated_at=now()""", (shop_id, body.nm_id, None if body.method == "auto" else body.method))
        c.commit()
        planning.fill(c, shop_id, u["id"])
        _audit(c, u, acc["workspace_id"], "plan/method", {"shop": shop_id, "nm_id": body.nm_id, "method": body.method})
        c.commit()
        return {"ok": True}
    q = (body.main_query or "").strip().lower()[:120] or None
    c.execute("""INSERT INTO plan_items(account_id,nm_id,main_query,query_src) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id)
                 DO UPDATE SET main_query=EXCLUDED.main_query, query_src=EXCLUDED.query_src, updated_at=now()""",
              (shop_id, body.nm_id, q, "manual" if q else "auto"))
    if body.ads_share is not None or body.reset_ads:
        if body.ads_share is not None and not 0 <= body.ads_share <= 1:
            raise HTTPException(400, "Доля рекламы — от 0 до 1")
        c.execute("UPDATE plan_items SET ads_share=%s WHERE account_id=%s AND nm_id=%s", (None if body.reset_ads else body.ads_share, shop_id, body.nm_id))
    _audit(c, u, acc["workspace_id"], "plan/item", {"shop": shop_id, **body.model_dump()})
    c.commit()
    return {"ok": True}


class PlanSettingsIn(BaseModel):
    horizon: int | None = None
    fixed_month: float | None = None
    start_cash: float | None = None
    goods_lead: int | None = None
    loan_rate: float | None = None
    tax_quarterly: bool | None = None


@router.put("/api/shops/{shop_id}/plan/settings")
def plan_settings(shop_id: int, body: PlanSettingsIn, u=Depends(current_user), c=Depends(conn)):
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    new = {k: v for k, v in body.model_dump().items() if v is not None}
    if ("horizon" in new and new["horizon"] not in (6, 12)) or not 0 <= new.get("fixed_month", 0) <= 1_000_000_000\
            or not 0 <= new.get("goods_lead", 0) <= 6 or not 0 <= new.get("loan_rate", 0) <= 2:
        raise HTTPException(400, "Горизонт 6/12 мес; постоянные ≥0; оплата товара за 0–6 мес; ставка 0–200 %")
    cur = c.execute("SELECT value FROM shop_settings WHERE account_id=%s AND key='plan'", (shop_id,)).fetchone()
    val = {**(cur["value"] if cur else {}), **new}
    c.execute("""INSERT INTO shop_settings(account_id,key,value) VALUES (%s,'plan',%s) ON CONFLICT (account_id,key)
                 DO UPDATE SET value=EXCLUDED.value, updated_at=now()""", (shop_id, json.dumps(val)))
    c.commit()
    planning.fill(c, shop_id, u["id"])      
    _audit(c, u, acc["workspace_id"], "plan/settings", {"shop": shop_id, **body.model_dump()})
    c.commit()
    return {"ok": True}


class PlanMethodAllIn(BaseModel):
    method: str          


@router.put("/api/shops/{shop_id}/plan/method_all")
def plan_method_all(shop_id: int, body: PlanMethodAllIn, u=Depends(current_user), c=Depends(conn)):
    """Переключить схему у всех артикулов. Ручные коэффициенты (таблица) и ручные ячейки не теряются — их можно вернуть в любой момент."""
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    if body.method not in ("auto",) + planning.METHODS:
        raise HTTPException(400, "Схема: auto, sales, query, manual или flat")
    for nm in planning._facts(c, shop_id, planning.base_month()):
        c.execute("""INSERT INTO plan_items(account_id,nm_id,method) VALUES (%s,%s,%s) ON CONFLICT (account_id,nm_id)
                     DO UPDATE SET method=EXCLUDED.method, updated_at=now()""", (shop_id, nm, None if body.method == "auto" else body.method))
    c.commit()
    stat = planning.fill(c, shop_id, u["id"])
    _audit(c, u, acc["workspace_id"], "plan/method_all", {"shop": shop_id, "method": body.method})
    c.commit()
    return {"ok": True, "stat": stat}


@router.get("/api/shops/{shop_id}/plan/scenarios")
def plan_scenarios(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import planning
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder(planning.scenarios(c, shop_id))



@router.get("/api/shops/{shop_id}/exclusions")
def excl_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    rules = {(r["kind"], r["value"]) for r in c.execute("SELECT kind, value FROM shop_exclusions WHERE account_id=%s", (shop_id,))}
    items = c.execute("""SELECT n.nm_id, n.vendor_code, n.title, coalesce(n.brand,'') brand, coalesce(n.subject,'') subject,
                                n.data->'photos'->0->>'tm' photo, coalesce(o.k, 0) orders_30d
                         FROM nomenclature n LEFT JOIN (SELECT nm_id, count(*) k FROM orders WHERE account_id=%s AND order_dt > now() - interval '30 days'
                                                        GROUP BY 1) o USING (nm_id)
                         WHERE n.account_id=%s ORDER BY coalesce(o.k,0) DESC, n.vendor_code""", (shop_id, shop_id)).fetchall()
    for r in items:
        r["direct"] = ("nm", str(r["nm_id"])) in rules
        r["off"] = r["direct"] or ("brand", r["brand"]) in rules or ("subject", r["subject"]) in rules
    def group(field, kind):
        g = {}
        for r in items:
            x = g.setdefault(r[field], {"name": r[field], "n": 0, "orders_30d": 0, "off": (kind, r[field]) in rules})
            x["n"] += 1
            x["orders_30d"] += r["orders_30d"]
        return sorted(g.values(), key=lambda x: -x["orders_30d"])
    return jsonable_encoder({"items": items, "brands": group("brand", "brand"), "subjects": group("subject", "subject"),
                             "total": len(items), "off": sum(1 for r in items if r["off"]),
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "admin")})


class ExclIn(BaseModel):
    kind: str
    values: list[str]
    off: bool


@router.put("/api/shops/{shop_id}/exclusions")
def excl_set(shop_id: int, body: ExclIn, u=Depends(current_user), c=Depends(conn)):
    """Включить/отключить артикулы, бренды или предметы. Агрегаты магазина пересчитываются фоном (несколько минут)."""
    acc = _role(c, u, shop_id, "admin")
    if body.kind not in ("nm", "brand", "subject") or not body.values or len(body.values) > 5000:
        raise HTTPException(400, "Вид: nm, brand или subject; список значений")
    for v in body.values:
        v = str(v).strip()[:200]
        if body.off:
            c.execute("""INSERT INTO shop_exclusions(account_id,kind,value,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (shop_id, body.kind, v, u["id"]))
        else:
            c.execute("DELETE FROM shop_exclusions WHERE account_id=%s AND kind=%s AND value=%s", (shop_id, body.kind, v))
    _audit(c, u, acc["workspace_id"], "exclusions", {"shop": shop_id, "kind": body.kind, "n": len(body.values), "off": body.off})
    c.commit()

    _rebuild_bg(c, shop_id)
    return {"ok": True, "message": "Сохранено. Цифры магазина пересчитываются — несколько минут."}


def _rebuild_bg(c, shop_id: int):
    """Пересчёт агрегатов магазина — отдельным процессом с низким приоритетом (не тормозит сайт и переживает его перезапуск)."""
    import os
    import subprocess
    import sys
    
    c.execute("""INSERT INTO collector_state(account_id,collector,cursor,last_run_at) VALUES (%s,'_rebuild','{"again": true}',now())
                 ON CONFLICT (account_id,collector) DO UPDATE SET cursor='{"again": true}'""", (shop_id,))
    c.commit()
    name = c.execute("SELECT name FROM accounts WHERE id=%s", (shop_id,)).fetchone()["name"]
    root = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"}
    unit = f"ai-stometric-rebuild-{shop_id}"
    if subprocess.run(["systemctl", "--user", "is-active", "-q", unit], env=env).returncode == 0:
        return
    subprocess.run(["systemd-run", "--user", "--collect", f"--unit={unit}", "--nice=10", "-p", "MemoryMax=1500M", "-p", "IOSchedulingClass=idle",
                    f"--working-directory={root}", sys.executable, "-m", "stometric", "materialize", name],
                   capture_output=True, timeout=15, env=env)


class ExclChange(BaseModel):
    kind: str
    value: str
    off: bool


class ExclBatch(BaseModel):
    changes: list[ExclChange]


@router.put("/api/shops/{shop_id}/exclusions/batch")
def excl_batch(shop_id: int, body: ExclBatch, u=Depends(current_user), c=Depends(conn)):
    """Несколько галочек разом (бренды, предметы, артикулы) → один пересчёт."""
    acc = _role(c, u, shop_id, "admin")
    if not body.changes or len(body.changes) > 5000 or any(x.kind not in ("nm", "brand", "subject") for x in body.changes):
        raise HTTPException(400, "Нечего сохранять")
    for x in body.changes:
        v = str(x.value).strip()[:200]
        if x.off:
            c.execute("""INSERT INTO shop_exclusions(account_id,kind,value,added_by) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (shop_id, x.kind, v, u["id"]))
        else:
            c.execute("DELETE FROM shop_exclusions WHERE account_id=%s AND kind=%s AND value=%s", (shop_id, x.kind, v))
    _audit(c, u, acc["workspace_id"], "exclusions", {"shop": shop_id, "batch": len(body.changes)})
    c.commit()
    _rebuild_bg(c, shop_id)
    return {"ok": True, "message": f"Сохранено ({len(body.changes)} изм.). Цифры магазина пересчитываются — несколько минут."}


@router.get("/api/shops/{shop_id}/plan/cash")
def plan_cash(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import planning
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**planning.cashflow(c, shop_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class CashCellIn(BaseModel):
    month: date
    field: str
    value: float | None


@router.put("/api/shops/{shop_id}/plan/cash")
def plan_cash_set(shop_id: int, body: CashCellIn, u=Depends(current_user), c=Depends(conn)):
    from . import planning
    acc = _role(c, u, shop_id, "editor")
    if body.field not in {k for k, _ in planning.CASH_MANUAL}:
        raise HTTPException(400, "Нет такой строки")
    m = body.month.replace(day=1)
    if body.value is None or body.value == 0:
        c.execute("DELETE FROM plan_cash WHERE account_id=%s AND month=%s AND field=%s", (shop_id, m, body.field))
    else:
        if not 0 <= body.value <= 10_000_000_000:
            raise HTTPException(400, "Сумма — положительное число")
        c.execute("""INSERT INTO plan_cash(account_id,month,field,value,updated_by) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (account_id,month,field)
                     DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by""", (shop_id, m, body.field, body.value, u["id"]))
    _audit(c, u, acc["workspace_id"], "plan/cash", {"shop": shop_id, **body.model_dump(mode="json")})
    c.commit()
    return {"ok": True}



@router.get("/api/shops/{shop_id}/photo_funnel")
def pf_list(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """Артикулы со слепками фото: свои (по заказам) и конкуренты магазина; дата последнего изменения фото."""
    _role(c, u, shop_id, "viewer")
    from .exclusions import excluded
    ex = excluded(c, shop_id)
    own = c.execute("""SELECT n.nm_id, n.vendor_code, n.title, n.data->'photos'->0->>'tm' photo, 'own' kind,
                              (SELECT max(day) FROM photo_events e WHERE e.nm_id=n.nm_id) last_change,
                              (SELECT count(*) FROM photo_events e WHERE e.nm_id=n.nm_id) changes,
                              EXISTS (SELECT 1 FROM photo_snaps s WHERE s.nm_id=n.nm_id) has_snap
                       FROM nomenclature n WHERE n.account_id=%s ORDER BY 6 DESC NULLS LAST, n.vendor_code""", (shop_id,)).fetchall()
    comp = c.execute("""SELECT DISTINCT k.comp_nm_id nm_id, NULL vendor_code, (SELECT data->>'name' FROM market_snap m WHERE m.nm_id=k.comp_nm_id
                               ORDER BY day DESC LIMIT 1) title, NULL photo, 'competitor' kind,
                              (SELECT max(day) FROM photo_events e WHERE e.nm_id=k.comp_nm_id) last_change,
                              (SELECT count(*) FROM photo_events e WHERE e.nm_id=k.comp_nm_id) changes,
                              EXISTS (SELECT 1 FROM photo_snaps s WHERE s.nm_id=k.comp_nm_id) has_snap
                        FROM competitors k WHERE k.account_id=%s""", (shop_id,)).fetchall()
    return jsonable_encoder([r for r in own if r["nm_id"] not in ex] + comp)


@router.get("/api/shops/{shop_id}/photo_funnel/{nm}")
def pf_item(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    from . import photos, photo_prices, photo_entry
    _role(c, u, shop_id, "viewer")
    own = c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, nm)).fetchone()
    comp = c.execute("SELECT 1 FROM competitors WHERE account_id=%s AND comp_nm_id=%s", (shop_id, nm)).fetchone()
    if not own and not comp:
        raise HTTPException(404, "Артикул не из магазина и не из его конкурентов")
    snaps = c.execute("SELECT id, taken_at, source, slots FROM photo_snaps WHERE nm_id=%s ORDER BY taken_at DESC LIMIT 60", (nm,)).fetchall()
    prices = photo_prices.periods(c, shop_id, nm, snaps) if own else {}
    entry = photo_entry.periods(c, shop_id, nm, snaps) if own else {}
    sl = {s["id"]: [x["hash"] for x in s["slots"]] for s in snaps}
    events = []
    from datetime import timedelta
    from .config import today_msk
    end = today_msk()                       
    history = c.execute("SELECT * FROM photo_events WHERE nm_id=%s ORDER BY day DESC, id DESC LIMIT 60", (nm,)).fetchall()
    for e in history:
        ev = {"day": e["day"], "summary": e["summary"], "after": sl.get(e["snap_id"]), "before": sl.get(e["prev_id"]), "detail": e["detail"]}
        if own:
            ev["effect"] = photos.effect(c, shop_id, nm, e["day"])
            ev["period"] = photos.period_stats(c, shop_id, nm, e["day"], max(e["day"], end))
            ev["period"]["prices"] = prices.get(e["snap_id"])
            ev["period"]["entry"] = entry.get(e["snap_id"])
        end = e["day"] - timedelta(days=1)
        events.append(ev)
    if own:                                 
        first = snaps[-1]["taken_at"].date() if snaps else None
        for i, ev in enumerate(events):
            a = events[i + 1]["day"] if i + 1 < len(events) else first
            b = ev["day"] - timedelta(days=1)
            ev["period_before"] = (events[i + 1].get("period") if i + 1 < len(events)
                                   else photos.period_stats(c, shop_id, nm, a, b) if a and a <= b else None)
            if ev["period_before"] is None and prices.get(history[i]["prev_id"]) is not None:
                
                
                ev["period_before"] = {'from': ev['day'], 'to': ev['day'], 'days': 0,
                                       'ctr': None, 'conv_cart': None, 'conv_order': None, 'orders_day': None}
            if ev["period_before"] is not None and "prices" not in ev["period_before"]:
                ev["period_before"]["prices"] = prices.get(history[i]["prev_id"])
            if ev["period_before"] is not None:
                ev["period_before"]["entry"] = entry.get(history[i]["prev_id"])
    cur_period = None
    if own and snaps:                       
        since = events[0]["day"] if events else snaps[-1]["taken_at"].date()
        cur_period = photos.period_stats(c, shop_id, nm, since, max(since, today_msk()))
        cur_period["prices"] = prices.get(snaps[0]["id"])
        cur_period["entry"] = entry.get(snaps[0]["id"])
    return jsonable_encoder({"nm_id": nm, "own": bool(own), "current": sl.get(snaps[0]["id"]) if snaps else None, "current_period": cur_period,
                             "taken_at": snaps[0]["taken_at"] if snaps else None, "events": events})


@router.post("/api/shops/{shop_id}/photo_funnel/{nm}/snap")
def pf_snap(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    """Снять слепок сейчас (обычно — раз в сутки автоматически)."""
    from . import photos
    _role(c, u, shop_id, "editor")
    own = c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, nm)).fetchone()
    if not own and not c.execute("SELECT 1 FROM competitors WHERE account_id=%s AND comp_nm_id=%s", (shop_id, nm)).fetchone():
        raise HTTPException(404, "Артикул не из магазина и не из его конкурентов")
    r = photos.snapshot(c, nm, "own" if own else "competitor")
    return jsonable_encoder({"ok": True, "changed": r["changed"], "summary": (r.get("event") or {}).get("summary")})



@router.post("/api/shops/{shop_id}/entry_points")
async def entry_upload(shop_id: int, request: Request, name: str = "", u=Depends(current_user), c=Depends(conn)):
    """Тело запроса — сам файл (xlsx или zip с xlsx), как скачан из ЛК WB «Портрет покупателя — Точки входа»."""
    from . import entry
    acc = _role(c, u, shop_id, "editor")
    try:
        r = entry.save(c, shop_id, u["id"], await request.body(), name)
    except entry.EntryError as e:
        c.rollback()
        raise HTTPException(400, str(e)) from None
    _audit(c, u, acc["workspace_id"], "entry_points/upload", {"shop": shop_id, "period": f"{r['d_from']}..{r['d_to']}", "rows": r["rows"]})
    c.commit()
    return jsonable_encoder(r)


@router.get("/api/shops/{shop_id}/entry_points")
def entry_get(shop_id: int, nm_ids: str = "", reports: str = "", mode: str = "reports", u=Depends(current_user), c=Depends(conn)):
    from . import entry
    _role(c, u, shop_id, "viewer")
    ids = [int(x) for x in reports.split(",") if x.strip().isdigit()] or None
    nms = [int(x) for x in nm_ids.split(",") if x.strip().isdigit()] or None    
    mode = mode if mode in ("reports", "days", "weeks") else "reports"   
    return jsonable_encoder({**entry.view(c, shop_id, nms, ids, mode), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.get("/api/shops/{shop_id}/entry_views")
def entry_views_get(shop_id: int, days: int = 7, grain: str = "day", nm_ids: str = "", u=Depends(current_user), c=Depends(conn)):
    """Self-hosted application component."""
    from . import entry_views
    _role(c, u, shop_id, "viewer")
    nms = [int(x) for x in nm_ids.split(",") if x.strip().isdigit()] or None
    return jsonable_encoder(entry_views.build(c, shop_id, nms, max(1, min(days, 90)), grain if grain in ("day", "week", "month") else "day"))


@router.delete("/api/shops/{shop_id}/entry_points/{rid}")
def entry_del(shop_id: int, rid: int, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    c.execute("DELETE FROM entry_reports WHERE id=%s AND account_id=%s", (rid, shop_id))
    _audit(c, u, acc["workspace_id"], "entry_points/delete", {"shop": shop_id, "report": rid})
    c.commit()
    return {"ok": True}



class MaxIn(BaseModel):
    values: dict[str, float | None]


@router.put("/api/shops/{shop_id}/checklist_max/{nm_id}")
def checklist_max_set(shop_id: int, nm_id: int, body: MaxIn, u=Depends(current_user), c=Depends(conn)):
    from . import checklist
    acc = _role(c, u, shop_id, "editor")
    keys = {k for k, _ in checklist.MAX_FIELDS}
    for k, v in body.values.items():
        if k not in keys:
            continue
        if v is None:
            c.execute("DELETE FROM checklist_max WHERE account_id=%s AND nm_id=%s AND field=%s", (shop_id, nm_id, k))
        else:
            c.execute("""INSERT INTO checklist_max(account_id,nm_id,field,value) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id,field)
                         DO UPDATE SET value=EXCLUDED.value, updated_at=now()""", (shop_id, nm_id, k, v))
    _audit(c, u, acc["workspace_id"], "checklist/max", {"shop": shop_id, "nm_id": nm_id, "values": body.values})
    c.commit()
    return {"ok": True}


class ExtIn(BaseModel):
    nm_id: int
    kind: str = "ext"
    source: str | None = None
    d_from: date
    d_to: date | None = None
    cost: float = 0
    qty: float | None = None
    clicks: float | None = None
    comment: str | None = None


@router.get("/api/shops/{shop_id}/ext_costs")
def ext_list(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    rows = c.execute("""SELECT e.*, n.vendor_code, coalesce(us.name, us.email) who FROM ext_costs e
                        LEFT JOIN nomenclature n ON n.account_id=e.account_id AND n.nm_id=e.nm_id LEFT JOIN users us ON us.id=e.user_id
                        WHERE e.account_id=%s ORDER BY e.d_from DESC, e.id DESC LIMIT 2000""", (shop_id,)).fetchall()
    return jsonable_encoder({"rows": rows, "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.post("/api/shops/{shop_id}/ext_costs")
def ext_add(shop_id: int, body: ExtIn, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    if body.kind not in ("ext", "giveaway"):
        raise HTTPException(400, "Вид — внешняя реклама или раздача")
    if not c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, body.nm_id)).fetchone():
        raise HTTPException(400, "Артикул не из этого магазина")
    if body.d_to and body.d_to < body.d_from:
        raise HTTPException(400, "Дата окончания раньше начала")
    if not 0 <= body.cost <= 100_000_000:
        raise HTTPException(400, "Странная сумма")
    r = c.execute("""INSERT INTO ext_costs(account_id,nm_id,kind,source,d_from,d_to,cost,qty,clicks,comment,user_id)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (shop_id, body.nm_id, body.kind, (body.source or "").strip()[:120] or None, body.d_from, body.d_to, body.cost, body.qty,
                   body.clicks, (body.comment or "").strip()[:500] or None, u["id"])).fetchone()
    _audit(c, u, acc["workspace_id"], "ext_costs/add", {"shop": shop_id, **body.model_dump(mode="json")})
    c.commit()
    return {"ok": True, "id": r["id"]}


@router.delete("/api/shops/{shop_id}/ext_costs/{eid}")
def ext_del(shop_id: int, eid: int, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    c.execute("DELETE FROM ext_costs WHERE id=%s AND account_id=%s", (eid, shop_id))
    _audit(c, u, acc["workspace_id"], "ext_costs/delete", {"shop": shop_id, "id": eid})
    c.commit()
    return {"ok": True}



@router.get("/api/shops/{shop_id}/promo")
def promo_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import promo
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**promo.view(c, shop_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


@router.post("/api/shops/{shop_id}/promo/upload")
async def promo_upload(shop_id: int, request: Request, name: str = "", title: str = "", u=Depends(current_user), c=Depends(conn)):
    """Тело — файл товаров автоакции из ЛК WB; title — название акции (в файле его нет)."""
    from . import promo
    acc = _role(c, u, shop_id, "editor")
    if not title.strip():
        raise HTTPException(400, "Введите название акции (скопируйте из календаря акций WB)")
    try:
        items = promo.parse_file(await request.body(), name)
    except promo.PromoError as e:
        raise HTTPException(400, str(e)) from None
    r = c.execute("INSERT INTO promo_uploads(account_id,name,items,file_name,uploaded_by) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                  (shop_id, title.strip()[:200], json.dumps(items), name[:200], u["id"])).fetchone()
    _audit(c, u, acc["workspace_id"], "promo/upload", {"shop": shop_id, "title": title, "items": len(items)})
    c.commit()
    return {"ok": True, "id": r["id"], "items": len(items)}


class PromoCalcIn(BaseModel):
    promo: str
    nm_id: int
    on: bool


@router.put("/api/shops/{shop_id}/promo/calc")
def promo_calc(shop_id: int, body: PromoCalcIn, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "editor")
    if body.on:
        c.execute("INSERT INTO promo_calc(account_id,promo,nm_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (shop_id, body.promo[:40], body.nm_id))
    else:
        c.execute("DELETE FROM promo_calc WHERE account_id=%s AND promo=%s AND nm_id=%s", (shop_id, body.promo, body.nm_id))
    c.commit()
    return {"ok": True}


@router.post("/api/shops/{shop_id}/promo/clear")
def promo_clear(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    """«Очистить расчёт»: убрать загруженные автоакции, галочки и акции API из таблицы (новые акции API появятся сами)."""
    acc = _role(c, u, shop_id, "editor")
    c.execute("DELETE FROM promo_uploads WHERE account_id=%s", (shop_id,))
    c.execute("DELETE FROM promo_calc WHERE account_id=%s", (shop_id,))
    c.execute("""INSERT INTO promo_hidden(account_id,promo) SELECT account_id, 'api:' || promo_id FROM wb_promotions WHERE account_id=%s
                 ON CONFLICT DO NOTHING""", (shop_id,))
    _audit(c, u, acc["workspace_id"], "promo/clear", {"shop": shop_id})
    c.commit()
    return {"ok": True}



HYP_KINDS = ("Гипотеза", "Подтвердилась", "Не подтвердилась")
HYP_INDICATORS = ("Цена клика", "CTR", "ДРР", "Цена корзины", "Цена заказа", "Конверсия в корзину", "Конверсия в заказ", "Локализация",
                  "Маржа", "КЭМ", "СПП / цена", "Позиция", "Фото / контент", "Другое")


class HypIn(BaseModel):
    nm_id: int
    kind: str = "Гипотеза"
    indicator: str | None = None
    text: str
    d_from: date
    days: int | None = None
    report: str | None = None


@router.get("/api/shops/{shop_id}/hypotheses")
def hyp_list(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "viewer")
    rows = c.execute("""SELECT h.*, n.vendor_code, n.data->'photos'->0->>'tm' photo, coalesce(us.name, us.email) who FROM hypotheses h
                        LEFT JOIN nomenclature n ON n.account_id=h.account_id AND n.nm_id=h.nm_id LEFT JOIN users us ON us.id=h.user_id
                        WHERE h.account_id=%s ORDER BY h.d_from DESC, h.id DESC LIMIT 1000""", (shop_id,)).fetchall()
    return jsonable_encoder({"rows": rows, "kinds": HYP_KINDS, "indicators": HYP_INDICATORS,
                             "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


def _hyp_check(c, shop_id, body: HypIn):
    if body.kind not in HYP_KINDS:
        raise HTTPException(400, "Вид — " + ", ".join(HYP_KINDS))
    if not body.text.strip():
        raise HTTPException(400, "Опишите гипотезу")
    if body.days is not None and not 1 <= body.days <= 365:
        raise HTTPException(400, "Дней на гипотезу — от 1 до 365")
    if not c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop_id, body.nm_id)).fetchone():
        raise HTTPException(400, "Артикул не из этого магазина")


@router.post("/api/shops/{shop_id}/hypotheses")
def hyp_add(shop_id: int, body: HypIn, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    _hyp_check(c, shop_id, body)
    r = c.execute("""INSERT INTO hypotheses(account_id,nm_id,kind,indicator,text,d_from,days,report,user_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     RETURNING id""", (shop_id, body.nm_id, body.kind, (body.indicator or "")[:60] or None, body.text.strip()[:1000], body.d_from,
                                       body.days, (body.report or "").strip()[:2000] or None, u["id"])).fetchone()
    _audit(c, u, acc["workspace_id"], "hypothesis/add", {"shop": shop_id, "id": r["id"]})
    c.commit()
    return {"ok": True, "id": r["id"]}


@router.put("/api/shops/{shop_id}/hypotheses/{hid}")
def hyp_edit(shop_id: int, hid: int, body: HypIn, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    _hyp_check(c, shop_id, body)
    c.execute("""UPDATE hypotheses SET nm_id=%s, kind=%s, indicator=%s, text=%s, d_from=%s, days=%s, report=%s, updated_at=now()
                 WHERE id=%s AND account_id=%s""", (body.nm_id, body.kind, (body.indicator or "")[:60] or None, body.text.strip()[:1000],
                                                    body.d_from, body.days, (body.report or "").strip()[:2000] or None, hid, shop_id))
    _audit(c, u, acc["workspace_id"], "hypothesis/edit", {"shop": shop_id, "id": hid})
    c.commit()
    return {"ok": True}


@router.delete("/api/shops/{shop_id}/hypotheses/{hid}")
def hyp_del(shop_id: int, hid: int, u=Depends(current_user), c=Depends(conn)):
    acc = _role(c, u, shop_id, "editor")
    c.execute("DELETE FROM hypotheses WHERE id=%s AND account_id=%s", (hid, shop_id))
    _audit(c, u, acc["workspace_id"], "hypothesis/delete", {"shop": shop_id, "id": hid})
    c.commit()
    return {"ok": True}


class UnitExtraIn(BaseModel):
    nm_id: int
    field: str
    value: float | None = None


@router.put("/api/shops/{shop_id}/unit_extra")
def unit_extra_set(shop_id: int, body: UnitExtraIn, u=Depends(current_user), c=Depends(conn)):
    """UNIT-экономика: маркировка/фулфилмент и прочие расходы на 1 шт (ручной ввод)."""
    acc = _role(c, u, shop_id, "editor")
    if body.field not in ("marking", "extra"):
        raise HTTPException(400, "Поле — маркировка или прочие расходы")
    if body.value is not None and not 0 <= body.value <= 1_000_000:
        raise HTTPException(400, "Странная сумма")
    c.execute(f"""INSERT INTO unit_extra(account_id,nm_id,{body.field}) VALUES (%s,%s,%s) ON CONFLICT (account_id,nm_id)
                  DO UPDATE SET {body.field}=EXCLUDED.{body.field}, updated_at=now()""", (shop_id, body.nm_id, body.value))
    _audit(c, u, acc["workspace_id"], "unit/extra", {"shop": shop_id, **body.model_dump()})
    c.commit()
    return {"ok": True}



@router.get("/api/shops/{shop_id}/seo/{nm_id}")
def seo_get(shop_id: int, nm_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import seo
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**seo.view(c, shop_id, nm_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class SeoMarkIn(BaseModel):
    word: str
    mark: str | None = None


@router.put("/api/shops/{shop_id}/seo/{nm_id}")
def seo_mark(shop_id: int, nm_id: int, body: SeoMarkIn, u=Depends(current_user), c=Depends(conn)):
    _role(c, u, shop_id, "editor")
    w = body.word.strip().lower()[:60]
    if body.mark in ("add", "remove"):
        c.execute("""INSERT INTO seo_marks(account_id,nm_id,word,mark,user_id) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (account_id,nm_id,word)
                     DO UPDATE SET mark=EXCLUDED.mark, user_id=EXCLUDED.user_id, updated_at=now()""", (shop_id, nm_id, w, body.mark, u["id"]))
    else:
        c.execute("DELETE FROM seo_marks WHERE account_id=%s AND nm_id=%s AND word=%s", (shop_id, nm_id, w))
    c.commit()
    return {"ok": True}


def _cost_import(c, u, shop_id: int, raw: bytes, name: str, valid_from: date | None, source: str) -> dict:
    from . import cost_import
    from .config import today_msk
    acc = _role(c, u, shop_id, "editor")
    try:
        kind, items = cost_import.parse(raw, name)
    except cost_import.CostImportError as e:
        raise HTTPException(400, str(e)) from None
    vf = valid_from or today_msk()
    res = cost_import.apply(c, shop_id, kind, items, vf, f"{source}: {u['email']}")
    _audit(c, u, acc["workspace_id"], "cost", {"shop": shop_id, "import": source[:120], "valid_from": vf, **{k: v for k, v in res.items()
                                                                                                         if k != "unknown_list"}})
    c.commit()
    return {**res, "valid_from": vf, "by": "артикулу WB / SKU" if kind == "nm" else "артикулу продавца"}


@router.post("/api/shops/{shop_id}/cost/import")
async def cost_import_file(shop_id: int, request: Request, name: str = "", valid_from: date | None = None, u=Depends(current_user), c=Depends(conn)):
    """Тело — файл себестоимости (xlsx или csv): столбцы артикула и «Себестоимость»."""
    raw = await request.body()
    if len(raw) > 30_000_000:
        raise HTTPException(400, "Файл больше 30 МБ")
    return _cost_import(c, u, shop_id, raw, name, valid_from, f"файл {name[:80]}")


class CostUrlIn(BaseModel):
    url: str
    valid_from: date | None = None


@router.post("/api/shops/{shop_id}/cost/import_url")
def cost_import_url(shop_id: int, body: CostUrlIn, u=Depends(current_user), c=Depends(conn)):
    """Ссылка на Google-таблицу (доступ по ссылке) — себестоимость с листа, где есть столбцы артикула и «Себестоимость»."""
    from . import cost_import
    _role(c, u, shop_id, "editor")
    try:
        raw = cost_import.fetch_url(body.url)
    except cost_import.CostImportError as e:
        raise HTTPException(400, str(e)) from None
    return _cost_import(c, u, shop_id, raw, "gsheet.xlsx", body.valid_from, "Google-таблица")



@router.get("/api/shops/{shop_id}/mrc")
def mrc_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import mrc_list
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder({**mrc_list.view(c, shop_id), "can_edit": auth.can(auth.shop_role(c, u, shop_id), "editor")})


class MrcItem(BaseModel):
    nm_id: int
    mrc: float | None = None
    note: str | None = None


class MrcIn(BaseModel):
    items: list[MrcItem]


@router.put("/api/shops/{shop_id}/mrc")
def mrc_put(shop_id: int, body: MrcIn, u=Depends(current_user), c=Depends(conn)):
    from . import mrc_list
    acc = _role(c, u, shop_id, "editor")
    if len(body.items) > 5000:
        raise HTTPException(400, "Не больше 5000 товаров за раз")
    try:
        put, gone = mrc_list.save(c, shop_id, u["id"], [i.model_dump() for i in body.items])
    except ValueError as e:
        c.rollback()
        raise HTTPException(400, str(e)) from None
    _audit(c, u, acc["workspace_id"], "mrc/set", {"shop": shop_id, "put": put, "removed": gone,
                                                   "items": [i.model_dump() for i in body.items[:50]]})
    c.commit()
    return {"ok": True, "message": f"МРЦ задана: {put}" + (f", убрана: {gone}" if gone else "")}



@router.get("/api/shops/{shop_id}/shelves")
def shelves_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    from . import shelf_view
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder(shelf_view.overview(c, shop_id))


@router.get("/api/shops/{shop_id}/shelves/{nm}")
def shelves_nm(shop_id: int, nm: int, u=Depends(current_user), c=Depends(conn)):
    from . import shelf_view
    _role(c, u, shop_id, "viewer")
    return jsonable_encoder(shelf_view.detail(c, shop_id, nm))

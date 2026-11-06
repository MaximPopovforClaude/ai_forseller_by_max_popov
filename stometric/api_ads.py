"""API раздела «📢 Реклама»: предложения ИИ по рекламе WB, применение по кнопке, ручные действия из списка кампаний (ads_ai)."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from . import actions, ads_ai, auth
from .config import today_msk
from .web import conn, current_user

router = APIRouter()


def _shop(c, u, shop_id: int, need: str) -> dict:
    if not auth.can(auth.shop_role(c, u, shop_id), need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    s = c.execute("SELECT id, marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()
    if s["marketplace"] != "wb":
        raise HTTPException(400, "Управление рекламой пока только для WB")
    return s


@router.get("/api/shops/{shop_id}/ads")
def ads_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "viewer")
    role = auth.shop_role(c, u, shop_id)
    rows = c.execute("""SELECT p.*, coalesce(x.name, x.email) who, o.verdict, o.delta_profit, o.before o_before, o.after o_after
                        FROM ad_proposals p LEFT JOIN users x ON x.id=p.decided_by LEFT JOIN ad_outcomes o ON o.proposal_id=p.id
                        WHERE p.account_id=%s AND (p.status='new' OR p.decided_at > now() - interval '30 days')
                        ORDER BY (p.status='new') DESC, p.priority DESC, p.effect_week DESC NULLS LAST, p.id DESC LIMIT 400""", (shop_id,)).fetchall()
    camps = ads_ai.campaigns(c, shop_id, (9, 11, 4))
    nom, photo = {}, {}
    for r in c.execute("SELECT nm_id, vendor_code, data->'photos'->0->>'tm' ph FROM nomenclature WHERE account_id=%s", (shop_id,)):
        nom[r["nm_id"]], photo[r["nm_id"]] = r["vendor_code"], r["ph"]
    y = today_msk() - timedelta(days=1)
    st7 = ads_ai._ad_stats(c, shop_id, y - timedelta(days=6), y)
    out_c = []
    for aid, cp in sorted(camps.items(), key=lambda x: (x[1]["status"] != 9, x[0])):
        nms = [{"nm_id": n, "vc": nom.get(n), "bids": b, "spend_7d": round(st7[(aid, n)]["spend"]), "orders_7d": int(st7[(aid, n)]["orders"]),
                "carts_7d": int(st7[(aid, n)]["carts"]),
                "clicks_7d": int(st7[(aid, n)]["clicks"])} for n, b in cp["nms"].items()]
        out_c.append({**{k: cp[k] for k in ("id", "status", "name", "bid_type", "payment", "placements", "can_change_nms")},
                      "status_t": ads_ai.STATUS_T.get(cp["status"], str(cp["status"])), "nms": nms,
                      "spend_7d": sum(x["spend_7d"] for x in nms), "orders_7d": sum(x["orders_7d"] for x in nms),
                      "carts_7d": sum(x["carts_7d"] for x in nms)})
    fb = {}                                  
    for f in c.execute("""SELECT proposal_id, user_id, rating, comment FROM ad_feedback
                          WHERE account_id=%s AND proposal_id = ANY(%s)""", (shop_id, [r["id"] for r in rows])):
        x = fb.setdefault(f["proposal_id"], {"mine": None, "up": 0, "down": 0, "comments": 0})
        x["up"] += f["rating"] == 1
        x["down"] += f["rating"] == -1
        x["comments"] += bool(f["comment"])
        if f["user_id"] == u["id"]:
            x["mine"] = {"rating": f["rating"], "comment": f["comment"]}
    state = c.execute("SELECT balance, balance_at, summary, summary_at FROM ad_state WHERE account_id=%s", (shop_id,)).fetchone()
    note = c.execute("SELECT body, model, batch_at FROM ad_notes WHERE account_id=%s ORDER BY batch_at DESC LIMIT 1", (shop_id,)).fetchone()
    last = c.execute("SELECT max(batch_at) t FROM ad_proposals WHERE account_id=%s AND source='rules'", (shop_id,)).fetchone()["t"]
    blk = actions.block(c, shop_id, "ads")
    props = [{**{k: r[k] for k in ("id", "kind", "advert_id", "nm_id", "query", "params", "reason", "effect_week", "metrics", "priority",
                                   "source", "status", "decided_at", "error", "batch_at")},
              "kind_t": ads_ai.KIND_T.get(r["kind"], r["kind"]), "vc": nom.get(r["nm_id"]), "who": r["who"],
              
              "photo": photo.get(r["nm_id"] or next(iter((camps.get(r["advert_id"]) or {}).get("nms") or {}), None)),
              "outcome": {"verdict": r["verdict"], "delta": r["delta_profit"], "before": r["o_before"], "after": r["o_after"]} if r["verdict"] else None,
              "feedback": fb.get(r["id"]), "camp": (camps.get(r["advert_id"]) or {}).get("name")} for r in rows]
    return jsonable_encoder({
        "proposals": props, "campaigns": out_c, "note": note, "last_run": last, "can_edit": auth.can(role, "editor"),
        "can_admin": auth.can(role, "admin"), "settings": blk["settings"], "enabled": blk["enabled"],
        "write_ok": actions.can_write(c, shop_id, "ads") is None, "write_why": actions.can_write(c, shop_id, "ads"),
        "place_t": ads_ai.PLACE_T, "learn": list(ads_ai.learned(c, shop_id).values()), "state": state})


@router.post("/api/shops/{shop_id}/ads/refresh")
def ads_refresh(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    return ads_ai.run(c, shop_id)


class DecideIn(BaseModel):
    ids: list[int]
    apply: bool
    force: bool = False


@router.post("/api/shops/{shop_id}/ads/decide")
def ads_decide(shop_id: int, body: DecideIn, u=Depends(current_user), c=Depends(conn)):
    """Применить или отклонить предложения (по одному в WB, с проверкой текущего состояния каждой кампании)."""
    _shop(c, u, shop_id, "editor")
    out = {}
    for pid in body.ids[:50]:
        try:
            out[pid] = ads_ai.decide(c, shop_id, pid, u["id"], body.apply, body.force)
        except actions.ActionDenied as e:
            c.rollback()
            out[pid] = {"status": "denied", "error": str(e)}
            if not body.apply:
                continue
            if "Стоп" in str(e) or "ключ" in str(e).lower() or "выключен" in str(e):
                break                       
    return out


class ManualIn(BaseModel):
    kind: str
    advert_id: int
    nm_id: int | None = None
    query: str | None = None
    after: dict | int | None = None        


@router.post("/api/shops/{shop_id}/ads/manual")
def ads_manual(shop_id: int, body: ManualIn, u=Depends(current_user), c=Depends(conn)):
    _shop(c, u, shop_id, "editor")
    try:
        return ads_ai.manual(c, shop_id, u["id"], body.kind, body.advert_id, body.nm_id, body.query, body.after)
    except actions.ActionDenied as e:
        c.rollback()
        raise HTTPException(400, str(e)) from None


@router.get("/api/shops/{shop_id}/ads/keywords")
def ads_keywords(shop_id: int, advert_id: int, nm_id: int, u=Depends(current_user), c=Depends(conn)):
    """Поисковые кластеры артикула в кампании за 14 дней + минус-фразы (из сбора)."""
    _shop(c, u, shop_id, "viewer")
    d = today_msk() - timedelta(days=ads_ai.KW_WINDOW)
    rows = c.execute("""SELECT query, sum(views) v, sum(clicks) cl, sum(atbs) atb, sum(orders) o, sum(spend) sp FROM wb_ad_kw_daily
                        WHERE account_id=%s AND advert_id=%s AND nm_id=%s AND day >= %s GROUP BY 1 ORDER BY sum(spend) DESC LIMIT 100""",
                     (shop_id, advert_id, nm_id, d)).fetchall()
    minus = [r["query"] for r in c.execute("SELECT query FROM wb_ad_kw_lists WHERE account_id=%s AND advert_id=%s AND nm_id=%s AND state='minus' ORDER BY query",
                                           (shop_id, advert_id, nm_id))]
    hist = ads_ai.kw_history(c, shop_id, [nm_id], minus) if minus else {}     
    mh = {}
    eco = ads_ai.economics(c, shop_id) if minus else None
    for q in minus:
        v, why = ads_ai.kw_verdict(ads_ai.kw_merge(hist, q), ads_ai._m(eco, nm_id), eco["k_ad"])
        mh[q] = {"verdict": v, "why": why}
    return jsonable_encoder({"rows": rows, "minus": minus, "minus_hist": mh})


class FeedbackIn(BaseModel):
    id: int
    rating: int | None = None              
    comment: str | None = None


@router.post("/api/shops/{shop_id}/ads/feedback")
def ads_feedback(shop_id: int, body: FeedbackIn, u=Depends(current_user), c=Depends(conn)):
    """👍/👎 и комментарий к предложению — для доработки правил (ничего в WB не меняет; оценивать может любой с доступом к магазину)."""
    _shop(c, u, shop_id, "viewer")
    if body.rating not in (None, 1, -1):
        raise HTTPException(400, "Оценка: 1 или -1")
    p = c.execute("SELECT kind, advert_id, nm_id, query, params, reason, effect_week, metrics, status, batch_at FROM ad_proposals WHERE id=%s AND account_id=%s",
                  (body.id, shop_id)).fetchone()
    if not p:
        raise HTTPException(404, "Предложение не найдено")
    comment = (body.comment or "").strip()[:2000] or None
    if body.rating is None and not comment:
        c.execute("DELETE FROM ad_feedback WHERE proposal_id=%s AND user_id=%s", (body.id, u["id"]))
    else:
        c.execute("""INSERT INTO ad_feedback (proposal_id, user_id, account_id, rating, comment, snap) VALUES (%s, %s, %s, %s, %s, %s)
                     ON CONFLICT (proposal_id, user_id) DO UPDATE SET rating=EXCLUDED.rating, comment=EXCLUDED.comment,
                     snap=EXCLUDED.snap, updated_at=now()""",
                  (body.id, u["id"], shop_id, body.rating, comment, Jsonb(jsonable_encoder(dict(p)))))
    c.commit()
    return {"ok": True}

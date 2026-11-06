"""Self-hosted application component."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import cardcompare as cc
from .web import _audit, conn, current_user

router = APIRouter()


def team_ids(c, user_id: int) -> set[int]:
    """Self-hosted application component."""
    return {r["user_id"] for r in c.execute("""SELECT DISTINCT m2.user_id FROM memberships m1 JOIN memberships m2 USING (workspace_id)
                                              WHERE m1.user_id=%s AND m2.user_id<>%s""", (user_id, user_id))}


def _anon(r: dict, viewer_id: int, team: set[int] | None = None) -> dict:
    """Self-hosted application component."""
    import random
    if r["user_id"] == viewer_id or (team and r["user_id"] in team):
        return r
    order = list(r["nm_ids"])
    random.Random(f"{r['id']}:{viewer_id}").shuffle(order)
    data = dict(r["data"] or {})
    pos = {nm: i for i, nm in enumerate(order)}
    data["cards"] = sorted(data.get("cards") or [], key=lambda c: pos.get(c["nm_id"], 99))
    data["nm_ids"] = order
    return {**r, "nm_ids": order, "data": data, "file_name": None}


def _brief(r: dict) -> dict:
    cards = (r["data"] or {}).get("cards") or []
    return {"id": r["id"], "uploaded_at": r["uploaded_at"], "file_name": r.get("file_name"), "period_from": r["period_from"],
            "period_to": r["period_to"], "nm_ids": r["nm_ids"], "is_public": r["is_public"], "photos": r["photos"],
            "titles": {str(c["nm_id"]): c.get("title") for c in cards}, "brands": {str(c["nm_id"]): c.get("brand") for c in cards}}


def _is_client(c, u) -> bool:
    """Клиент основного сервиса — есть магазин или кабинет на тарифе с нейросетью."""
    from . import auth
    return bool(u["is_superadmin"] or auth.shops_for(c, u))


@router.post("/api/compare/upload")
async def upload(request: Request, name: str = "", u=Depends(current_user), c=Depends(conn)):
    raw = await request.body()
    if not raw:
        raise HTTPException(400, "Пустой файл")
    try:
        parsed = cc.parse(raw)
    except cc.BadFile as e:
        raise HTTPException(400, str(e)) from None
    sha = cc.digest(raw)
    p = parsed["period"] or {}
    key = cc.content_key(parsed["nm_ids"], p.get("from"), p.get("to"), sha)
    mates = [u["id"], *team_ids(c, u["id"])]
    old = c.execute("SELECT id, user_id FROM card_comparisons WHERE user_id = ANY(%s) AND (file_sha=%s OR content_key=%s) ORDER BY id LIMIT 1",
                    (mates, sha, key)).fetchone()
    if old:
        return {"id": old["id"], "duplicate": True, "team": old["user_id"] != u["id"]}
    first = cc.first_of_key(c, key)          
    photos = {}
    for nm in parsed["nm_ids"]:
        try:
            photos[str(nm)] = cc.photo(c, nm)
        except Exception:  
            c.rollback()
    r = c.execute("""INSERT INTO card_comparisons(user_id,file_sha,file_name,period_from,period_to,nm_ids,data,photos,content_key)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (u["id"], sha, name[:200] or None, p.get("from"), p.get("to"), parsed["nm_ids"],
                   json.dumps(parsed, ensure_ascii=False, default=str), json.dumps(photos), key)).fetchone()
    _audit(c, u, None, "compare/upload", {"id": r["id"], "nm_ids": parsed["nm_ids"], "repeat_of": first["id"] if first else None})
    c.commit()
    import threading
    threading.Thread(target=_photo_snaps, args=(r["id"],), daemon=True).start()   
    auto = _is_client(c, u) and bool(_user_key(c, u))
    if auto:   
        import threading
        threading.Thread(target=_auto_ai, args=(r["id"], u["id"]), daemon=True).start()
    return {"id": r["id"], "duplicate": False, "ai_started": auto, "repeat": bool(first)}


@router.get("/api/compare/mine")
def mine(u=Depends(current_user), c=Depends(conn)):
    rows = c.execute("SELECT * FROM card_comparisons WHERE user_id=%s ORDER BY uploaded_at DESC", (u["id"],)).fetchall()
    seen = c.execute("""SELECT x.* FROM comparison_views v JOIN card_comparisons x ON x.id=v.comparison_id
                        WHERE v.user_id=%s AND x.user_id<>%s ORDER BY v.viewed_at DESC""", (u["id"], u["id"])).fetchall()
    saved = c.execute("""SELECT x.*, s.ai_text IS NOT NULL has_ai FROM comparison_saved s JOIN card_comparisons x ON x.id=s.comparison_id
                         WHERE s.user_id=%s ORDER BY s.saved_at DESC""", (u["id"],)).fetchall()
    subs = c.execute("""SELECT s.nm_id, s.created_at, (SELECT count(*) FROM card_comparisons x WHERE x.is_public AND x.user_id<>%s
                         AND s.nm_id = ANY(x.nm_ids)) n FROM compare_subs s WHERE s.user_id=%s ORDER BY s.created_at DESC""", (u["id"], u["id"])).fetchall()
    saved_ids = {r["id"] for r in saved}
    team = team_ids(c, u["id"])
    trows = c.execute("""SELECT x.*, coalesce(us.name, us.email) author FROM card_comparisons x JOIN users us ON us.id=x.user_id
                         WHERE x.user_id = ANY(%s) ORDER BY x.uploaded_at DESC LIMIT 200""", (list(team),)).fetchall() if team else []
    return jsonable_encoder({"mine": [_brief(r) for r in rows], "team": [{**_brief(r), "author": r["author"]} for r in trows], "saved": [_brief(_anon(r, u["id"])) for r in saved], "subs": subs,
                             "seen": [_brief(_anon(r, u["id"])) for r in seen if r["id"] not in saved_ids], "quota": cc.views_left(c, u["id"]),
                             "client": _is_client(c, u)})


@router.get("/api/compare/search")
def search(nm: int, u=Depends(current_user), c=Depends(conn)):
    """Открытые сравнения других людей, где есть этот артикул (без данных — только что за сравнение)."""
    rows = c.execute("""SELECT x.*, EXISTS (SELECT 1 FROM comparison_views v WHERE v.user_id=%s AND v.comparison_id=x.id) seen
                        FROM card_comparisons x WHERE x.is_public AND x.user_id<>%s AND %s = ANY(x.nm_ids) AND NOT (x.user_id = ANY(%s))
                          AND NOT EXISTS (SELECT 1 FROM card_comparisons y WHERE y.is_public AND y.content_key=x.content_key AND y.id<x.id)
                        ORDER BY x.period_to DESC NULLS LAST, x.uploaded_at DESC LIMIT 50""", (u["id"], u["id"], nm, list(team_ids(c, u["id"])))).fetchall()
    return jsonable_encoder({"rows": [{**_brief(_anon(r, u["id"])), "seen": r["seen"]} for r in rows], "quota": cc.views_left(c, u["id"])})


@router.get("/api/compare/{cid}")
def view(cid: int, u=Depends(current_user), c=Depends(conn)):
    r = c.execute("SELECT * FROM card_comparisons WHERE id=%s", (cid,)).fetchone()
    if not r:
        raise HTTPException(404, "Сравнение не найдено")
    own = r["user_id"] == u["id"]
    team = team_ids(c, u["id"])
    mate = r["user_id"] in team                 
    if not own and not mate:                    
        if not r["is_public"]:
            raise HTTPException(403, "Автор не открыл это сравнение для других")
        seen = c.execute("SELECT 1 FROM comparison_views WHERE user_id=%s AND comparison_id=%s", (u["id"], cid)).fetchone()
        if not seen:
            q = cc.views_left(c, u["id"])
            if q["left"] <= 0:
                raise HTTPException(403, ("Чтобы смотреть чужие сравнения, откройте для других свои: за каждое своё открытое — "
                                          f"{cc.VIEWS_PER_SHARED} чужих." if not q["shared"] else
                                          f"Лимит исчерпан: открыто ваших {q['shared']}, просмотрено чужих {q['used']} из {q['allowed']}. "
                                          f"Откройте ещё сравнение — получите {cc.VIEWS_PER_SHARED} просмотра."))
            c.execute("INSERT INTO comparison_views(user_id,comparison_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (u["id"], cid))
            c.commit()
    slides = {}
    for nm, sid in (r.get("photo_snaps") or {}).items():
        sn = c.execute("SELECT slots FROM photo_snaps WHERE id=%s", (sid,)).fetchone()
        slides[nm] = [x["hash"] for x in (sn["slots"] if sn else [])]
    author = c.execute("SELECT coalesce(name, email) a FROM users WHERE id=%s", (r["user_id"],)).fetchone()["a"] if mate else None
    sv = None if own else c.execute("SELECT ai_text, ai_model FROM comparison_saved WHERE user_id=%s AND comparison_id=%s", (u["id"], cid)).fetchone()
    mine_nm = None if own else _my_nm(c, u["id"], r["nm_ids"])
    r = _anon(r, u["id"], team)
    out = {**_brief(r), "data": r["data"], "own": own, "team_author": author, "saved": bool(sv), "mine_nm": mine_nm, "slides": slides,
           "ai_text": r["ai_text"] if own or (mate and not sv) else (sv or {}).get("ai_text"),
           "ai_model": r["ai_model"] if own or (mate and not sv) else (sv or {}).get("ai_model"),
           "client": _is_client(c, u), "quota": cc.views_left(c, u["id"])}
    return jsonable_encoder(out)


def notify_subscribers(cid: int) -> int:
    """Новое открытое сравнение → подписчикам на его артикулы (кроме автора) сообщение в бот уведомлений, один раз."""
    from . import db
    from .bots import SITE, notify
    n = 0
    with db.connect() as c:
        r = c.execute("SELECT * FROM card_comparisons WHERE id=%s AND is_public", (cid,)).fetchone()
        if not r:
            return 0
        for s in c.execute("""SELECT s.user_id, array_agg(s.nm_id) nms, ns.chat_id FROM compare_subs s
                              LEFT JOIN notify_settings ns ON ns.user_id=s.user_id
                              WHERE s.nm_id = ANY(%s) AND s.user_id<>%s GROUP BY s.user_id, ns.chat_id""", (r["nm_ids"], r["user_id"])).fetchall():
            new = c.execute("INSERT INTO compare_notified(user_id,comparison_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING 1",
                            (s["user_id"], cid)).fetchone()
            c.commit()
            if new and s["chat_id"]:
                nms = ", ".join(map(str, s["nms"]))
                notify(c, s["user_id"], s["chat_id"], f"⚖️ Появилось новое сравнение карточек с артикулом {nms} "
                                                      f"({len(r['nm_ids'])} карточек, период по {r['period_to']:%d.%m.%Y}).\n{SITE}/compare/{cid}")
                n += 1
    return n


def _notify_bg(cid: int) -> None:
    import threading
    threading.Thread(target=notify_subscribers, args=(cid,), daemon=True).start()


class PublicIn(BaseModel):
    is_public: bool


@router.put("/api/compare/{cid}/public")
def set_public(cid: int, body: PublicIn, u=Depends(current_user), c=Depends(conn)):
    n = c.execute("UPDATE card_comparisons SET is_public=%s WHERE id=%s AND user_id=%s", (body.is_public, cid, u["id"])).rowcount
    if not n:
        raise HTTPException(404, "Это не ваше сравнение")
    c.commit()
    if body.is_public:
        _notify_bg(cid)
    return {"ok": True, "quota": cc.views_left(c, u["id"])}


@router.post("/api/compare/{cid}/save")
def save(cid: int, u=Depends(current_user), c=Depends(conn)):
    """«Добавить к себе» чужое сравнение (только уже открытое вами): не искать заново + свой ИИ-разбор, если есть нейросеть."""
    r = c.execute("SELECT * FROM card_comparisons WHERE id=%s", (cid,)).fetchone()
    if not r or r["user_id"] == u["id"]:
        raise HTTPException(400, "Своё сравнение и так у вас")
    if not c.execute("SELECT 1 FROM comparison_views WHERE user_id=%s AND comparison_id=%s", (u["id"], cid)).fetchone():
        raise HTTPException(403, "Сначала откройте сравнение")
    c.execute("INSERT INTO comparison_saved(user_id,comparison_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (u["id"], cid))
    c.commit()
    auto = _is_client(c, u) and bool(_user_key(c, u))
    if auto:
        import threading
        threading.Thread(target=_auto_ai, args=(cid, u["id"]), daemon=True).start()
    return {"ok": True, "ai_started": auto}


@router.delete("/api/compare/{cid}/save")
def unsave(cid: int, u=Depends(current_user), c=Depends(conn)):
    c.execute("DELETE FROM comparison_saved WHERE user_id=%s AND comparison_id=%s", (u["id"], cid))
    c.commit()
    return {"ok": True}


class SubIn(BaseModel):
    nm_ids: list[int]


@router.post("/api/compare/subs")
def subscribe(body: SubIn, u=Depends(current_user), c=Depends(conn)):
    ids = [i for i in dict.fromkeys(body.nm_ids) if 0 < i < 10 ** 12][:500]
    if not ids:
        raise HTTPException(400, "Укажите артикул WB")
    for i in ids:
        c.execute("INSERT INTO compare_subs(user_id,nm_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (u["id"], i))
    c.commit()
    return {"ok": True, "added": len(ids)}


@router.post("/api/compare/subs/my_shops")
def subscribe_my(u=Depends(current_user), c=Depends(conn)):
    """Подписаться на все артикулы своих магазинов."""
    from . import auth
    shops = [s["id"] for s in auth.shops_for(c, u)]
    if not shops:
        raise HTTPException(400, "У вас нет подключённых магазинов")
    n = c.execute("""INSERT INTO compare_subs(user_id,nm_id) SELECT %s, nm_id FROM nomenclature WHERE account_id = ANY(%s)
                     ON CONFLICT DO NOTHING""", (u["id"], shops)).rowcount
    c.commit()
    return {"ok": True, "added": n}


@router.delete("/api/compare/subs/{nm}")
def unsubscribe(nm: int, u=Depends(current_user), c=Depends(conn)):
    c.execute("DELETE FROM compare_subs WHERE user_id=%s AND nm_id=%s", (u["id"], nm))
    c.commit()
    return {"ok": True}


@router.delete("/api/compare/{cid}")
def delete(cid: int, u=Depends(current_user), c=Depends(conn)):
    """Удалить своё сравнение (по кнопке автора)."""
    n = c.execute("DELETE FROM card_comparisons WHERE id=%s AND user_id=%s", (cid, u["id"])).rowcount
    if not n:
        raise HTTPException(404, "Это не ваше сравнение")
    _audit(c, u, None, "compare/delete", {"id": cid})
    c.commit()
    return {"ok": True}


AI_RULES = """Ты аналитик Wildberries в сервисе Seller Analytics. Ниже — отчёт WB «Сравнение карточек» (JSON): метрики 2–5 карточек за период
и прошлый период, и поисковые запросы (частотность, позиция, переходы, корзины, заказы по каждой карточке). {ours}
Напиши по-русски, коротко, без markdown и длинного тире: 1) кто сильнее и почему (воронка: показы → CTR → корзина → заказ → выкуп, цена,
рейтинг, отзывы, позиция); 2) {weak}; 3) поисковые запросы: где конкуренты выше и забирают переходы,
какие частотные запросы стоит добрать; 4) «Что сделать:» 3–5 действий. Только цифры из JSON, ничего не придумывай."""


def _user_key(c, u) -> str | None:
    from . import aireport, auth
    for s in auth.shops_for(c, u):
        key = aireport.shop_key(c, s["id"], u["id"])
        if key:
            return key
    return None


def _my_nm(c, user_id: int, nm_ids: list[int]) -> int | None:
    """Артикул из сравнения, который есть в магазинах пользователя (для разбора «с позиции своей карточки»)."""
    u = c.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
    from . import auth
    shops = [s["id"] for s in auth.shops_for(c, u)]
    if not shops:
        return None
    r = c.execute("SELECT nm_id FROM nomenclature WHERE account_id = ANY(%s) AND nm_id = ANY(%s) LIMIT 1", (shops, list(nm_ids))).fetchone()
    return r and r["nm_id"]


def write_ai(c, r: dict, viewer_id: int, key: str, store: str = "auto") -> str:
    """ИИ-разбор сравнения по правилам AI_RULES. Автор — первая карточка «наша»; другой человек — если в сравнении есть его артикул,
    разбор с позиции этой карточки, иначе на равных. store: auto — автору в сравнение, добавившему — в comparison_saved."""
    from . import aireport
    own = r["user_id"] == viewer_id
    r = _anon(r, viewer_id)
    mine = None if own else _my_nm(c, viewer_id, r["nm_ids"])
    if mine:   
        data = dict(r["data"])
        data["cards"] = sorted(data["cards"], key=lambda k: k["nm_id"] != mine)
        r = {**r, "data": data}
    own = own or bool(mine)
    d = r["data"]
    rules = AI_RULES.format(ours="Первая карточка — наша." if own else "Чья карточка — неизвестно, сравнивай карточки между собой на равных.",
                            weak="где первая карточка проигрывает с цифрами" if own else "сильные и слабые стороны каждой карточки с цифрами")
    top_q = sorted(d.get("queries") or [], key=lambda q: -(q.get("freq") or 0))[:120]
    payload = {"period": d.get("period"), "prev_period": d.get("prev_period"), "cards": d.get("cards"), "queries_top": top_q}
    text = aireport.complete(key, rules, json.dumps(payload, ensure_ascii=False, default=str), 1400)
    if r["user_id"] == viewer_id:
        c.execute("UPDATE card_comparisons SET ai_text=%s, ai_model=%s WHERE id=%s", (text, aireport.model_name(key), r["id"]))
    else:
        c.execute("UPDATE comparison_saved SET ai_text=%s, ai_model=%s WHERE user_id=%s AND comparison_id=%s",
                  (text, aireport.model_name(key), viewer_id, r["id"]))
    c.commit()
    return text


def _photo_snaps(cid: int) -> None:
    """Слепки первых 7 фото каждой карточки сравнения (AVIF) — чтобы фотоворонку было видно и через месяц."""
    from . import db, photos
    with db.connect() as c:
        r = c.execute("SELECT nm_ids FROM card_comparisons WHERE id=%s", (cid,)).fetchone()
        if not r:
            return
        snaps = {}
        for nm in r["nm_ids"]:
            try:
                snaps[str(nm)] = photos.snapshot(c, nm, "compare")["snap_id"]
            except Exception:  
                c.rollback()
        c.execute("UPDATE card_comparisons SET photo_snaps=%s WHERE id=%s", (json.dumps(snaps), cid))
        c.commit()


def _auto_ai(cid: int, user_id: int) -> None:
    """После загрузки клиентом с нейросетью — разбор фоном (попадает и на главную его магазина)."""
    from . import db
    with db.connect() as c:
        try:
            u = c.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()
            key = _user_key(c, u)
            r = c.execute("SELECT * FROM card_comparisons WHERE id=%s", (cid,)).fetchone()
            if not key or not r:
                return
            if r["user_id"] == user_id:
                if not r["ai_text"]:
                    write_ai(c, r, user_id, key)
            else:
                sv = c.execute("SELECT ai_text FROM comparison_saved WHERE user_id=%s AND comparison_id=%s", (user_id, cid)).fetchone()
                if sv and not sv["ai_text"]:
                    write_ai(c, r, user_id, key)
        except Exception:  
            import traceback
            traceback.print_exc()


@router.post("/api/compare/{cid}/ai")
def ai(cid: int, u=Depends(current_user), c=Depends(conn)):
    """ИИ-разбор по сравнению — для клиентов основного сервиса (ключ Claude кабинета или нейросеть сервиса на тарифе «Наша нейросеть»)."""
    from . import aireport, auth
    r = c.execute("SELECT * FROM card_comparisons WHERE id=%s", (cid,)).fetchone()
    if not r or (r["user_id"] != u["id"] and not c.execute("SELECT 1 FROM comparison_views WHERE user_id=%s AND comparison_id=%s",
                                                         (u["id"], cid)).fetchone()):
        raise HTTPException(404, "Сравнение не найдено")
    if not _is_client(c, u):
        raise HTTPException(403, "ИИ-разбор по сравнению — для клиентов Seller Analytics: подключите магазин в «Настройках аккаунта»")
    key = _user_key(c, u)
    if not key:
        plans = {w["plan"] for w in auth.workspaces_for(c, u)}
        raise HTTPException(400, "Нейросеть сервиса ещё подключается — ИИ-разбор по тарифу «Наша нейросеть» заработает в ближайшее время."
                            if "ai" in plans else "Нужен ключ нейросети («Настройки аккаунта» → «Нейросеть») или тариф «Наша нейросеть»")
    return {"ai_text": write_ai(c, r, u["id"], key), "ai_model": aireport.model_name(key)}


def for_shop_home(c, shop: int) -> dict | None:
    """Свежий (по настройке кабинета, по умолчанию 7 дней) разбор сравнения с артикулом магазина, загруженного людьми этого кабинета, — для блока ИИ на главной."""
    r = c.execute("""WITH team AS (SELECT user_id FROM memberships m JOIN accounts a ON a.workspace_id=m.workspace_id WHERE a.id=%(s)s
                                   UNION SELECT id FROM users WHERE is_superadmin),
                          fresh AS (SELECT w.compare_fresh_days d FROM accounts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=%(s)s),
                          nms AS (SELECT array_agg(nm_id) a FROM nomenclature WHERE account_id=%(s)s),
                          own AS (SELECT x.id, x.period_from, x.period_to, x.ai_text, x.ai_model, x.nm_ids, x.data, x.uploaded_at at
                                  FROM card_comparisons x WHERE x.ai_text IS NOT NULL AND x.user_id IN (SELECT user_id FROM team)),
                          sav AS (SELECT x.id, x.period_from, x.period_to, sv.ai_text, sv.ai_model, x.nm_ids, x.data, sv.saved_at at
                                  FROM comparison_saved sv JOIN card_comparisons x ON x.id=sv.comparison_id
                                  WHERE sv.ai_text IS NOT NULL AND sv.user_id IN (SELECT user_id FROM team))
                     SELECT * FROM (SELECT * FROM own UNION ALL SELECT * FROM sav) z, fresh, nms
                     WHERE z.at > now() - make_interval(days => fresh.d) AND z.nm_ids && nms.a
                     ORDER BY z.at DESC LIMIT 1""", {"s": shop}).fetchone()
    if not r:
        return None
    mine = set(r["a"] or [])
    cards = sorted((r["data"] or {}).get("cards") or [], key=lambda k: (k["nm_id"] not in mine, k["nm_id"]))   
    return {"id": r["id"], "period_from": r["period_from"], "period_to": r["period_to"], "ai_text": r["ai_text"], "ai_model": r["ai_model"],
            "cards": [f"{k.get('brand') or ''} {k['nm_id']}".strip() for k in cards]}


class FreshIn(BaseModel):
    days: int


@router.put("/api/workspaces/{ws_id}/compare_fresh")
def set_fresh(ws_id: int, body: FreshIn, u=Depends(current_user), c=Depends(conn)):
    from . import auth
    if not auth.can(auth.workspace_role(c, u, ws_id), "admin"):
        raise HTTPException(403, "Меняет админ или владелец кабинета")
    if not 1 <= body.days <= 90:
        raise HTTPException(400, "От 1 до 90 дней")
    c.execute("UPDATE workspaces SET compare_fresh_days=%s WHERE id=%s", (body.days, ws_id))
    c.commit()
    return {"ok": True}


@router.get("/api/photo/{h}")
def photo_file(h: str):
    """Слайд из слепка фотоворонки (AVIF). Это публичные фото карточек WB — без входа, кэш надолго."""
    from fastapi.responses import FileResponse
    from . import config, db
    if not all(ch in "0123456789abcdef" for ch in h) or len(h) != 64:
        raise HTTPException(404, "Нет фото")
    with db.connect() as c:
        r = c.execute("SELECT path FROM photo_blobs WHERE hash=%s", (h,)).fetchone()
    if not r:
        raise HTTPException(404, "Нет фото")
    return FileResponse(config.DATA / r["path"], media_type="image/avif", headers={"Cache-Control": "public, max-age=31536000, immutable"})

"""Номенклатура: все карточки (курсор по updatedAt+nmID), размеры и баркоды; изменения — в card_changes."""

import json

from ..config import today_msk
from .. import history


def run(ctx) -> dict:
    """Self-hosted application component."""
    from .. import loadplan
    st = ctx.state("nomenclature")
    full = not st.get("max_upd") or (st.get("full_on") != str(today_msk()) and (loadplan.night() or not st.get("full_on")))
    since = None if full else st["max_upd"]
    max_upd = st.get("max_upd") or ""
    cursor = {"limit": 100}
    n = changes = 0
    stop = False
    while not stop:
        body = {"settings": {"sort": {"ascending": False}, "cursor": cursor, "filter": {"withPhoto": -1}}}
        data = ctx.wb.call("content", "/content/v2/get/cards/list", "POST", body=body)
        cards = data.get("cards") or []
        for card in cards:
            upd = card.get("updatedAt") or ""
            max_upd = max(max_upd, upd)
            if since and upd and upd <= since:      
                stop = True
                break
            prev = ctx.c.execute("SELECT data FROM nomenclature WHERE account_id=%s AND nm_id=%s",
                                 (ctx.acc["id"], card["nmID"])).fetchone()
            first_run = not ctx.state("nomenclature").get("seeded")
            if not first_run:  
                changes += history.card_diff(ctx.c, ctx.acc["id"], prev["data"] if prev else None, card)
            ctx.c.execute(
                """INSERT INTO nomenclature(account_id,nm_id,imt_id,vendor_code,brand,title,subject_id,subject,created_at,updated_at,data)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (account_id,nm_id) DO UPDATE SET imt_id=EXCLUDED.imt_id, vendor_code=EXCLUDED.vendor_code,
                     brand=EXCLUDED.brand, title=EXCLUDED.title, subject_id=EXCLUDED.subject_id, subject=EXCLUDED.subject,
                     created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at, data=EXCLUDED.data, last_seen=now()""",
                (ctx.acc["id"], card["nmID"], card.get("imtID"), card.get("vendorCode"), card.get("brand"), card.get("title"),
                 card.get("subjectID"), card.get("subjectName"), card.get("createdAt"), card.get("updatedAt"),
                 json.dumps(card, ensure_ascii=False)))
            for s in card.get("sizes") or []:
                ctx.c.execute(
                    """INSERT INTO nm_sizes(account_id,chrt_id,nm_id,tech_size,wb_size,skus) VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (account_id,chrt_id) DO UPDATE SET nm_id=EXCLUDED.nm_id, tech_size=EXCLUDED.tech_size,
                         wb_size=EXCLUDED.wb_size, skus=EXCLUDED.skus, last_seen=now()""",
                    (ctx.acc["id"], s["chrtID"], card["nmID"], s.get("techSize"), s.get("wbSize"), s.get("skus") or []))
            n += 1
        ctx.c.commit()
        cur = data.get("cursor") or {}
        if len(cards) < cursor["limit"] or not cur.get("nmID"):
            break
        cursor = {"limit": 100, "updatedAt": cur["updatedAt"], "nmID": cur["nmID"]}
    out = {"seeded": True, "max_upd": max_upd, "full_on": str(today_msk()) if full else st.get("full_on")}
    return {"cards": n, "changes": changes, "full": full, "cursor": out}


def run_tariffs(ctx) -> dict:
    """Комиссии WB по предметам (оферта) — снимок раз в сутки; история тарифов копится у нас."""
    from datetime import date

    from . import raw
    data = ctx.wb.call("common", "/api/v1/tariffs/commission", params={"locale": "ru"}) or {}
    rows = data.get("report") or []
    today = today_msk().isoformat()
    for r in rows:
        raw.put(ctx, "tariffs_commission", f"{r.get('subjectID')}|{today}", today, r)
    ctx.c.commit()
    return {"subjects": len(rows)}

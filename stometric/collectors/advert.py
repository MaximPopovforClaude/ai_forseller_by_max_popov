"""Реклама: список кампаний + статистика по дням (fullstats, ≤31 дня и ≤50 кампаний за запрос, лимит 3/мин).

Первый запуск — назад, сколько отдаст WB (по 31 дню, пока ответы не пустые, не дальше BACKFILL_DAYS);
дальше — последние OVERLAP_DAYS дней каждый раз (WB дописывает статистику задним числом).
"""

from ..config import today_msk
from datetime import date, timedelta

from . import raw
from .. import history

OVERLAP_DAYS = 7
SHORT_DAYS = 1          
BACKFILL_DAYS = 400
STAT_STATUSES = {7, 9, 11}   


def run_adverts(ctx) -> dict:
    """Self-hosted application component."""
    from .. import loadplan
    cnt = ctx.wb.call("advert", "/adv/v1/promotion/count") or {}
    all_ids = []
    for grp in cnt.get("adverts") or []:
        for a in grp.get("advert_list") or []:
            all_ids.append((a["advertId"], grp.get("type"), grp.get("status"), a.get("changeTime")))
    st = ctx.state("adverts")
    full = st.get("full_on") != str(today_msk()) and (loadplan.night() or not st.get("full_on"))
    if full:
        ids = all_ids
    else:
        known = {r["k"]: (r["ct"], r["st"]) for r in ctx.c.execute(
            """SELECT row_key k, data->>'changeTime' ct, (data->>'status')::int st FROM raw_rows WHERE account_id=%s AND source='adverts'""",
            (ctx.acc["id"],)).fetchall()}
        ids = [x for x in all_ids if known.get(str(x[0])) != (x[3], x[2])]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        info = ctx.wb.call("advert", "/api/advert/v2/adverts", params={"ids": ",".join(str(x[0]) for x in chunk)}) or {}
        by_id = {a["id"]: a for a in info.get("adverts") or []}
        seeded = ctx.c.execute("SELECT 1 FROM raw_rows WHERE account_id=%s AND source='adverts' LIMIT 1", (ctx.acc["id"],)).fetchone()
        for aid, typ, status, changed in chunk:
            new = {"advertId": aid, "type": typ, "status": status, "changeTime": changed, "info": by_id.get(aid)}
            prev = ctx.c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts' AND row_key=%s",
                                 (ctx.acc["id"], str(aid))).fetchone()
            if seeded and new["info"]:   
                history.ad_diff(ctx.c, ctx.acc["id"], prev["data"] if prev else None, new)
            raw.put(ctx, "adverts", str(aid), None, new)
        ctx.c.commit()
    return {"campaigns": len(all_ids), "fetched": len(ids), "full": full,
            "cursor": {"full_on": str(today_msk()) if full else st.get("full_on")}}


STATS_REQUESTS_PER_RUN = 15  


def run_stats(ctx) -> dict:
    """Fresh data and historical backfill have separate durable cursors.

    A checkpoint includes the exact campaign list, so a changed catalog cannot
    shift a numeric offset. Checkpoints follow committed upserts; replay after a
    crash between those commits is harmless. Historical work never blocks the
    next daytime refresh and never restarts from today after a 429.
    """
    from datetime import datetime, timezone
    from .. import loadplan
    rows = ctx.c.execute(
        "SELECT row_key, data FROM raw_rows WHERE account_id=%s AND source='adverts'", (ctx.acc["id"],)).fetchall()
    camps = [(int(r["row_key"]), r["data"]) for r in rows if r["data"].get("status") in STAT_STATUSES]
    cur = dict(ctx.state("ad_stats"))
    today = today_msk()
    big = loadplan.is_big(ctx.c, ctx.acc["id"])
    historical_allowed = not big or loadplan.night()
    if cur.get("stats_version") != 2:
        
        
        complete = bool(cur.get("backfilled") and not cur.get("deep_pending") and not cur.get("deep_running"))
        cur = {"stats_version": 2, "backfilled": complete, "tail_at": cur.get("tail_at")}
    cur.pop("deep_pending", None)
    requests = n_rows = 0

    def checkpoint():
        cur["deep_running"] = not cur.get("backfilled", False)
        if cur.get("fresh"):
            cur["offset"] = 1  
        else:
            cur.pop("offset", None)
        ctx.save_state("ad_stats", cur, ok=False)

    def window(beg, end):
        return {"begin": str(beg), "end": str(end), "offset": 0, "rows": 0,
                "ids": [aid for aid, d in camps if (d.get("changeTime") or "9999")[:10] >= str(beg) or d.get("status") in (9, 11)]}

    def pull(w):
        nonlocal requests, n_rows
        while w["offset"] < len(w["ids"]) and requests < STATS_REQUESTS_PER_RUN:
            chunk = w["ids"][w["offset"]:w["offset"] + 50]
            data = ctx.wb.call("advert", "/adv/v3/fullstats", params={"ids": ",".join(map(str, chunk)),
                                        "beginDate": w["begin"], "endDate": w["end"]}) or []
            got = 0
            for camp in data:
                for day in camp.get("days") or []:
                    d = (day.get("date") or "")[:10]
                    raw.put(ctx, "ad_stats", f"{camp['advertId']}|{d}", d, {"advertId": camp["advertId"], **day})
                    got += 1
            ctx.c.commit()
            w["offset"] += len(chunk)
            w["rows"] += got
            requests += 1
            n_rows += got
            checkpoint()
        return w["offset"] >= len(w["ids"])

    now = datetime.now(timezone.utc)
    fresh_at = datetime.fromisoformat(cur["fresh_done_at"]) if cur.get("fresh_done_at") else None
    if not cur.get("fresh") and (fresh_at is None or (now - fresh_at).total_seconds() >= 58 * 60):
        full, tail_at = ctx.tail("ad_stats")
        cur["fresh"] = window(today - timedelta(days=OVERLAP_DAYS if full else SHORT_DAYS), today)
        cur["fresh"]["tail_at"] = tail_at
        checkpoint()
    if cur.get("fresh") and pull(cur["fresh"]):
        cur["tail_at"] = cur["fresh"].get("tail_at")
        cur["fresh_done_at"] = now.isoformat()
        cur.pop("fresh")
        checkpoint()

    
    stop = today - timedelta(days=ctx.depth(BACKFILL_DAYS))
    while historical_allowed and not cur.get("backfilled") and not cur.get("fresh") and requests < STATS_REQUESTS_PER_RUN:
        if not cur.get("history"):
            end = date.fromisoformat(cur["history_end"]) if cur.get("history_end") else today - timedelta(days=OVERLAP_DAYS + 1)
            if end < stop:
                cur["backfilled"] = True
                break
            cur["history"] = window(max(stop, end - timedelta(days=30)), end)
            checkpoint()
        if not pull(cur["history"]):
            break
        completed = cur.pop("history")
        cur["history_end"] = str(date.fromisoformat(completed["begin"]) - timedelta(days=1))
        
        
        checkpoint()
    checkpoint()
    return {"requests": requests, "day_rows": n_rows, "backfill_complete": bool(cur.get("backfilled")), "cursor": cur}


def upd_key(r: dict) -> str:
    return f"{r.get('advertId')}|{r.get('paymentType')}|{r.get('updTime')}|{r.get('updSum')}"


def run_upd(ctx) -> dict:
    """Фактические расходы на рекламу по УПД (/adv/v1/upd, окно ≤31 дня): первый запуск — назад до BACKFILL_DAYS, дальше — OVERLAP_DAYS."""
    st = ctx.state("ad_upd")
    today = today_msk()
    start = today - timedelta(days=OVERLAP_DAYS if st.get("backfilled") else ctx.depth(BACKFILL_DAYS))
    n, cur = 0, start
    while cur <= today:
        end = min(today, cur + timedelta(days=30))
        rows = ctx.wb.call("advert", "/adv/v1/upd", params={"from": cur.isoformat(), "to": end.isoformat()}) or []
        for r in rows:
            d = str(r.get("updTime") or "")[:10]
            
            raw.put(ctx, "ad_upd", upd_key(r), d or None, r)
        ctx.c.commit()
        n += len(rows)
        cur = end + timedelta(days=1)
    return {"rows": n, "cursor": {"backfilled": True}}



KW_BACKFILL_DAYS = 180
KW_REQ_PER_RUN = 25          


def _kw_pairs(ctx, beg: date | None = None) -> list[tuple[int, int]]:
    """(кампания, артикул) из собранных кампаний: активные/на паузе; завершённые — если менялись после beg."""
    out = []
    for r in ctx.c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts'", (ctx.acc["id"],)):
        d = r["data"]
        st, info = d.get("status"), d.get("info") or {}
        if st not in STAT_STATUSES:
            continue
        if st == 7 and (beg is None or (d.get("changeTime") or "")[:10] < beg.isoformat()):
            continue
        started = ((info.get("timestamps") or {}).get("started") or "")[:10]
        for nm in info.get("nm_settings") or []:
            out.append((int(d["advertId"]), int(nm["nm_id"]), started))
    return out


def _kw_put(ctx, items) -> int:
    n = 0
    for it in items or []:
        for x in it.get("dailyStats") or []:
            s = x.get("stat") or {}
            q = (s.get("normQuery") or "").strip()
            if not q:
                continue
            ctx.c.execute(
                """INSERT INTO wb_ad_kw_daily(account_id,advert_id,nm_id,query,day,views,clicks,atbs,orders,shks,spend,avg_pos,cpc)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (account_id,advert_id,nm_id,query,day) DO UPDATE SET views=EXCLUDED.views, clicks=EXCLUDED.clicks,
                     atbs=EXCLUDED.atbs, orders=EXCLUDED.orders, shks=EXCLUDED.shks, spend=EXCLUDED.spend, avg_pos=EXCLUDED.avg_pos, cpc=EXCLUDED.cpc""",
                (ctx.acc["id"], it["advertId"], it["nmId"], q[:300], x["date"][:10], s.get("views"), s.get("clicks") or 0, s.get("atbs") or 0,
                 s.get("orders") or 0, s.get("shks") or 0, s.get("spend") or 0, s.get("avgPos"), s.get("cpc")))
            n += 1
    return n


def _kw_window(ctx, beg: date, end: date, pairs) -> tuple[int, int]:
    pairs = [(a, n) for a, n, started in pairs if not started or started <= end.isoformat()]
    rows = reqs = 0
    for i in range(0, len(pairs), 100):
        chunk = pairs[i:i + 100]
        data = ctx.wb.call("advert", "/adv/v1/normquery/stats", "POST",
                           body={"from": beg.isoformat(), "to": end.isoformat(), "items": [{"advertId": a, "nmId": n} for a, n in chunk]}) or {}
        rows += _kw_put(ctx, data.get("items"))
        reqs += 1
        ctx.c.commit()
    return rows, reqs


def run_kw(ctx) -> dict:
    """Ключи по дням: каждый раз — последние OVERLAP_DAYS дней (WB дописывает задним числом); первый раз — история
    до KW_BACKFILL_DAYS назад окнами по 31 дню, порциями по KW_REQ_PER_RUN запросов (курсор bf_end)."""
    st = ctx.state("ad_kw")
    today = today_msk()
    rows, reqs = 0, 0
    if st.get("backfilled"):
        beg = today - timedelta(days=OVERLAP_DAYS)
        r, q = _kw_window(ctx, beg, today, _kw_pairs(ctx, beg))
        return {"rows": r, "requests": q, "cursor": st}
    end = date.fromisoformat(st["bf_end"]) if st.get("bf_end") else today
    stop = today - timedelta(days=ctx.depth(KW_BACKFILL_DAYS))
    while end >= stop and reqs < KW_REQ_PER_RUN:
        beg = max(end - timedelta(days=30), stop)
        r, q = _kw_window(ctx, beg, end, _kw_pairs(ctx, beg))
        rows, reqs = rows + r, reqs + q
        end = beg - timedelta(days=1)
    cur = {"backfilled": True} if end < stop else {"bf_end": end.isoformat()}
    return {"rows": rows, "requests": reqs, "cursor": cur}


def run_kw_lists(ctx) -> dict:
    """Списки кластеров (активные / исключённые / архив), минус-фразы и свои ставки кластеров — снимок по активным кампаниям."""
    pairs = [(a, n) for a, n, _ in _kw_pairs(ctx)]
    acc = ctx.acc["id"]
    got: dict[tuple[int, int], list] = {}
    for i in range(0, len(pairs), 100):
        chunk = pairs[i:i + 100]
        lst = ctx.wb.call("advert", "/adv/v0/normquery/list", "POST", body={"items": [{"advertId": a, "nmId": n} for a, n in chunk]}) or {}
        for it in lst.get("items") or []:
            rows = got.setdefault((it["advertId"], it["nmId"]), [])
            for state, qs in ((it.get("normQueries") or {}).items()):
                if state in ("active", "excluded", "archived"):
                    rows += [(q, state, None) for q in qs or []]
        body = {"items": [{"advert_id": a, "nm_id": n} for a, n in chunk]}
        for it in (ctx.wb.call("advert", "/adv/v0/normquery/get-minus", "POST", body=body) or {}).get("items") or []:
            got.setdefault((it["advert_id"], it["nm_id"]), []).extend((q, "minus", None) for q in it.get("norm_queries") or [])
        bids = {(b["advert_id"], b["nm_id"], b["norm_query"]): b["bid_kopecks"] / 100
                for b in (ctx.wb.call("advert", "/adv/v0/normquery/get-bids", "POST", body=body) or {}).get("bids") or []}
        for (a, n, q), bid in bids.items():
            rows = got.setdefault((a, n), [])
            hit = [k for k, x in enumerate(rows) if x[0] == q and x[1] == "active"]
            if hit:
                rows[hit[0]] = (q, "active", bid)
            else:
                rows.append((q, "active", bid))
    for (a, n), rows in got.items():
        ctx.c.execute("DELETE FROM wb_ad_kw_lists WHERE account_id=%s AND advert_id=%s AND nm_id=%s", (acc, a, n))
        for q, state, bid in {(q, s): (q, s, b) for q, s, b in rows}.values():
            ctx.c.execute("""INSERT INTO wb_ad_kw_lists(account_id,advert_id,nm_id,query,state,bid) VALUES (%s,%s,%s,%s,%s,%s)
                             ON CONFLICT DO NOTHING""", (acc, a, n, q[:300], state, bid))
    ctx.c.commit()
    return {"pairs": len(pairs), "with_lists": len(got)}

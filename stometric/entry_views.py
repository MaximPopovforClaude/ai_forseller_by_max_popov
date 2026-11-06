"""Self-hosted application component."""

from datetime import timedelta

BASE = ("views", "clicks", "carts", "orders")


def _m(x: dict, n_days: int | None = None) -> dict:
    v, cl, k, o = (float(x.get(f) or 0) for f in BASE)
    f = lambda a, b: a / b if b else None  
    osum, ao, bo = float(x.get("orders_sum") or 0), float(x.get("agg_orders") or 0), float(x.get("buyouts") or 0)
    out = {"views": v, "clicks": cl, "carts": k, "orders": o, "ctr": f(cl, v), "cr_cart": f(k, cl), "cr_order": f(o, k), "cro": f(o, cl),
           "crf": f(o, v), "crfl": f(k, v), "orders_sum": osum if "orders_sum" in x else None, "avg_price": f(osum, ao),
           "buyout_pct": f(bo, ao)}
    if "ad_views" in x:                   
        for k2 in BASE:
            a = float(x.get("ad_" + k2) or 0)
            out["ad_" + k2] = a
            out["org_" + k2] = max(0.0, out[k2] - a)
        out["ad_ctr"], out["org_ctr"] = f(out["ad_clicks"], out["ad_views"]), f(out["org_clicks"], out["org_views"])
    if n_days:
        out["per_day"] = {k2: (out[k2] / n_days if out[k2] is not None else None) for k2 in ("views", "clicks", "carts", "orders")}
    return out


def _key(d, grain: str) -> str:
    if grain == "week":
        return (d - timedelta(days=d.weekday())).isoformat()
    if grain == "month":
        return d.strftime("%Y-%m")
    return d.isoformat()


def build(c, shop: int, nms: list[int] | None = None, days: int = 30, grain: str = "day", top_n: int = 60) -> dict:
    reps = c.execute("SELECT id, d_from FROM entry_reports WHERE account_id=%s AND d_from=d_to ORDER BY d_from DESC", (shop,)).fetchall()
    if not reps:
        return {"periods": [], "funnel": None, "sources": [], "sources_days": []}
    top = reps[0]["d_from"]
    lo = top - timedelta(days=(92 if grain == "month" else days) - 1)
    reps = [r for r in reps if r["d_from"] >= lo]
    rid = {r["id"]: r["d_from"] for r in reps}
    from .exclusions import excluded
    ex = list(excluded(c, shop))
    keys: dict = {}
    for d in rid.values():
        k = _key(d, grain)
        p = keys.setdefault(k, {"key": k, "d_from": d, "d_to": d, "n_days": 0})
        p["d_from"], p["d_to"], p["n_days"] = min(p["d_from"], d), max(p["d_to"], d), p["n_days"] + 1
    periods = sorted(keys.values(), key=lambda p: p["d_from"], reverse=True)
    acc = lambda: {f: 0.0 for f in BASE}  
    art: dict = {}
    tot: dict = {}
    src: dict = {}
    pts: dict = {}
    w = "report_id = ANY(%(r)s) AND nm_id NOT IN (SELECT unnest(%(ex)s::bigint[])) AND (%(n)s::bigint[] IS NULL OR nm_id = ANY(%(n)s::bigint[]))"
    p = {"r": list(rid), "ex": ex, "n": nms}
    sums = "sum(views) views, sum(clicks) clicks, sum(carts) carts, sum(orders) orders"

    def add(bucket, r):
        for f in BASE:
            bucket[f] += float(r[f] or 0)
    for r in c.execute(f"SELECT report_id, nm_id, {sums} FROM entry_rows WHERE {w} GROUP BY 1, 2", p):     
        k = _key(rid[r["report_id"]], grain)
        for bucket in (art.setdefault(r["nm_id"], {}).setdefault(k, acc()), art[r["nm_id"]].setdefault("all", acc()),
                       tot.setdefault(k, acc()), tot.setdefault("all", acc())):
            add(bucket, r)
    for r in c.execute(f"SELECT report_id, section, {sums} FROM entry_rows WHERE {w} GROUP BY 1, 2", p):    
        dk = rid[r["report_id"]].isoformat()
        add(src.setdefault(r["section"], {}).setdefault(dk, acc()), r)
        add(src[r["section"]].setdefault("all", acc()), r)
    for r in c.execute(f"SELECT section, point, {sums} FROM entry_rows WHERE {w} GROUP BY 1, 2", p):         
        add(pts.setdefault((r["section"], r["point"]), acc()), r)
    
    ids = list(art)
    ad_day: dict = {}                      
    for r in c.execute("""SELECT nm_id, day, (data->>'orders')::numeric o, (data->>'orders_sum')::numeric s, (data->>'buyouts')::numeric b,
                                 (data->>'ad_views')::numeric av, (data->>'ad_clicks')::numeric ac, (data->>'ad_carts')::numeric ak,
                                 (data->>'ad_orders')::numeric ao
                          FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s AND nm_id = ANY(%s)""", (shop, lo, top, ids)):
        k = _key(r["day"], grain)
        if k not in keys or r["day"] not in rid.values():
            continue
        ad = {"ad_views": r["av"], "ad_clicks": r["ac"], "ad_carts": r["ak"], "ad_orders": r["ao"]}
        for bucket in (art[r["nm_id"]].setdefault(k, acc()), art[r["nm_id"]]["all"], tot.setdefault(k, acc()), tot["all"],
                       ad_day.setdefault(r["day"].isoformat(), {}), ad_day.setdefault("all", {})):
            bucket["orders_sum"] = bucket.get("orders_sum", 0.0) + float(r["s"] or 0)
            bucket["agg_orders"] = bucket.get("agg_orders", 0.0) + float(r["o"] or 0)
            bucket["buyouts"] = bucket.get("buyouts", 0.0) + float(r["b"] or 0)
            for k2, v2 in ad.items():
                bucket[k2] = bucket.get(k2, 0.0) + float(v2 or 0)
    srch: dict = {}                        
    for r in c.execute("""SELECT day, sum(coalesce(views, 0)) v, sum(clicks) cl, sum(atbs) k, sum(orders) o FROM wb_ad_kw_daily
                          WHERE account_id=%s AND day BETWEEN %s AND %s AND nm_id = ANY(%s) GROUP BY 1""", (shop, lo, top, ids)):
        if r["day"] not in rid.values():
            continue
        for b in (srch.setdefault(r["day"].isoformat(), {}), srch.setdefault("all", {})):
            for k2, v2 in (("ad_views", r["v"]), ("ad_clicks", r["cl"]), ("ad_carts", r["k"]), ("ad_orders", r["o"])):
                b[k2] = b.get(k2, 0.0) + float(v2 or 0)

    def rest(dk):                          
        a, b = ad_day.get(dk, {}), srch.get(dk, {})
        return {f: max(0.0, float(a.get("ad_" + f) or 0) - float(b.get("ad_" + f) or 0)) for f in BASE} |\
               {"ad_" + f: max(0.0, float(a.get("ad_" + f) or 0) - float(b.get("ad_" + f) or 0)) for f in BASE}
    n_all = len(rid)
    nd = {p["key"]: p["n_days"] for p in periods}
    names = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, vendor_code, title, brand, coalesce(data->'photos'->0->>'c246x328', data->'photos'->0->>'tm') photo FROM nomenclature WHERE account_id=%s AND nm_id = ANY(%s)", (shop, ids))}
    arts = sorted(art.items(), key=lambda kv: -kv[1].get("all", {}).get("views", 0))[:top_n]
    funnel = {"total": {k: _m(v, nd.get(k) or n_all) for k, v in tot.items()},
              "articles": [{"nm_id": nm, "vendor_code": (names.get(nm) or {}).get("vendor_code"), "title": (names.get(nm) or {}).get("title"),
                            "brand": (names.get(nm) or {}).get("brand"), "photo": (names.get(nm) or {}).get("photo"),
                            "cells": {k: _m(v, nd.get(k) or n_all) for k, v in cells.items()}} for nm, cells in arts],
              "articles_n": len(art)}
    T = tot.get("all") or acc()
    sh = lambda a, b: a / b if b else None  
    sources = []
    for sec, per in src.items():
        a = per["all"]
        m = _m({**a, **(srch.get("all") or {"ad_views": 0})} if sec == "Поиск" else a)
        m.update(share_views=sh(a["views"], T["views"]), share_clicks=sh(a["clicks"], T["clicks"]), share_carts=sh(a["carts"], T["carts"]),
                 share_orders=sh(a["orders"], T["orders"]))
        sub = []
        for (s2, pt), b in pts.items():
            if s2 != sec:
                continue
            mm = _m(b)
            mm.update(point=pt, share_views=sh(b["views"], T["views"]), share_clicks=sh(b["clicks"], T["clicks"]),
                      share_carts=sh(b["carts"], T["carts"]), share_orders=sh(b["orders"], T["orders"]))
            sub.append(mm)
        sub.sort(key=lambda x: -x["views"])
        sources.append({"section": sec, **m, "points": sub})
    sources.sort(key=lambda x: -x["views"])
    r_all = rest("all")
    if any(r_all[f] for f in BASE):
        m = _m(r_all)
        m.update(share_views=sh(r_all["views"], T["views"]), share_clicks=sh(r_all["clicks"], T["clicks"]),
                 share_carts=sh(r_all["carts"], T["carts"]), share_orders=sh(r_all["orders"], T["orders"]))
        sources.append({"section": "Реклама вне поиска (полки, каталог, главная)", **m, "points": [], "ad_only": True})
    tm = _m(T)
    tm.update(share_views=1.0 if T["views"] else None, share_clicks=1.0 if T["clicks"] else None,
              share_carts=1.0 if T["carts"] else None, share_orders=1.0 if T["orders"] else None)
    day_list = sorted({d.isoformat() for d in rid.values()}, reverse=True)
    def sday(sec, dk):
        x = src[sec][dk]
        return {**x, **(srch.get(dk) or {"ad_views": 0})} if sec == "Поиск" else x
    sources_days = [{"section": s["section"], "all": _m(sday(s["section"], "all"), n_all),
                     "days": {d: _m(sday(s["section"], d)) for d in day_list if d in src[s["section"]]}} for s in sources if not s.get("ad_only")]
    if r_all and any(r_all[f] for f in BASE):
        sources_days.append({"section": "Реклама вне поиска (полки, каталог, главная)", "ad_only": True, "all": _m(r_all, n_all),
                             "days": {d: _m(rest(d)) for d in day_list}})
    return {"periods": [{**p, "d_from": p["d_from"].isoformat(), "d_to": p["d_to"].isoformat()} for p in periods],
            "funnel": funnel, "sources": sources, "sources_total": tm, "sources_days": sources_days, "days": day_list, "n_days": n_all,
            "d_from": min(rid.values()).isoformat(), "d_to": top.isoformat()}

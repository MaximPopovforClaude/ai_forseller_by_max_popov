"""Self-hosted application component."""

from datetime import timedelta
from .entry_conversions import Conversions
from . import entry_ads

BASE = ("views", "clicks", "carts", "orders")


def _m(x: dict, n_days: int | None = None) -> dict:
    f = lambda a, b: entry_ads.ratio(a, b)              
    osum, ao, bo = float(x.get("orders_sum") or 0), float(x.get("agg_orders") or 0), float(x.get("buyouts") or 0)
    out = {**entry_ads.metrics(x), "orders_sum": osum if "orders_sum" in x else None,
           "avg_price": f(osum, ao), "buyout_pct": f(bo, ao)}
    if "ad_views" in x:
        ad = entry_ads.metrics({**{key: x.get('ad_'+key) for key in BASE}, 'partial': x.get('ad_partial', ())})
        org = entry_ads.metrics(entry_ads.difference(out, ad))
        for prefix, m in (('ad_', ad), ('org_', org)):
            out.update({prefix+key: value for key, value in m.items() if key != 'share'})
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
                                                                              
    validity = ", ".join(f"count(*) FILTER (WHERE {f} IS NULL OR {f}<0) bad_{f}" for f in ("clicks", "carts", "orders"))
    entry_daily: dict = {}
    advertising_daily: dict = {}

    def add(bucket, r):
        for f in BASE:
            bucket[f] += float(r[f] or 0)
    for r in c.execute(f"SELECT report_id, nm_id, {sums}, {validity} FROM entry_rows WHERE {w} GROUP BY 1, 2", p):                     
        k = _key(rid[r["report_id"]], grain)
        observation = entry_daily.setdefault((r["nm_id"], rid[r["report_id"]]), {f: 0.0 for f in ("clicks", "carts", "orders")})
        for f in observation:
            observation[f] = None if r[f"bad_{f}"] or r[f] is None or observation[f] is None else observation[f] + float(r[f])
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
    for r in c.execute("""SELECT nm_id, day, (data->>'orders')::numeric o, (data->>'orders_sum')::numeric s, (data->>'buyouts')::numeric b,
                                 (data->>'ad_views')::numeric av, (data->>'ad_clicks')::numeric ac, (data->>'ad_carts')::numeric ak,
                                 (data->>'ad_orders')::numeric ao
                          FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s AND nm_id = ANY(%s)""", (shop, lo, top, ids)):
        k = _key(r["day"], grain)
        if k not in keys or r["day"] not in rid.values():
            continue
        ad = {"ad_views": r["av"], "ad_clicks": r["ac"], "ad_carts": r["ak"], "ad_orders": r["ao"]}
        advertising_daily[(r["nm_id"], r["day"])] = {"clicks": r["ac"], "carts": r["ak"], "orders": r["ao"]}
        for bucket in (art[r["nm_id"]].setdefault(k, acc()), art[r["nm_id"]]["all"], tot.setdefault(k, acc()), tot["all"]):
            bucket["orders_sum"] = bucket.get("orders_sum", 0.0) + float(r["s"] or 0)
            bucket["agg_orders"] = bucket.get("agg_orders", 0.0) + float(r["o"] or 0)
            bucket["buyouts"] = bucket.get("buyouts", 0.0) + float(r["b"] or 0)
            for k2, v2 in ad.items():
                prior, value = bucket.get(k2, 0.0), entry_ads.number(v2)
                bucket[k2] = prior + value if prior is not None and value is not None else None
                                                                                      
    reader = entry_ads.load(c, shop, nms, ex, lo, top)
    ad_periods = {d.isoformat(): reader.period([d]) for d in set(rid.values())}
    ad_periods['all'] = reader.period(set(rid.values()))

    def with_ad(x, dk, placement, ad_only=False):
        values = ad_periods[dk]
        ad = values[placement]
        m = _m(ad if ad_only else {**x, **{'ad_'+f: ad[f] for f in BASE}, 'ad_partial': ad['partial']},
               len(rid) if dk == 'all' else 1)
        if placement != 'total':
            m['payment'] = {model: values[placement+'_'+model] for model in entry_ads.PAYMENTS
                            if model != 'unknown' or ad_periods['all']['unknown_payment']}
        if ad_only:
            m.update({f: ad[f] for f in ('ctr', 'cr_cart', 'cr_order', 'cro', 'crf', 'crfl')})
        return m

    n_all = len(rid)
    nd = {p["key"]: p["n_days"] for p in periods}
    names = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, vendor_code, title, brand, coalesce(data->'photos'->0->>'c246x328', data->'photos'->0->>'tm') photo FROM nomenclature WHERE account_id=%s AND nm_id = ANY(%s)", (shop, ids))}
    arts = sorted(art.items(), key=lambda kv: -kv[1].get("all", {}).get("views", 0))[:top_n]
    conversions: dict = {}
    shown = {nm for nm, _ in arts}
    observed_days = set(rid.values())
    for nm in ids:
        for day in observed_days:
                                                                         
                                                                                  
            targets = [(None, _key(day, grain)), (None, "all")]
            if nm in shown:
                targets += [(nm, _key(day, grain)), (nm, "all")]
            for owner, period in targets:
                key = (owner, period)
                if key not in conversions:
                    conversions[key] = Conversions()
                conversions[key].add(entry_daily.get((nm, day)), advertising_daily.get((nm, day)))

    def funnel_metrics(nm, k, v):
        return {**_m(v, nd.get(k) or n_all), **conversions.get((nm, k), Conversions()).result()}

    funnel = {"total": {k: funnel_metrics(None, k, v) for k, v in tot.items()},
              "articles": [{"nm_id": nm, "vendor_code": (names.get(nm) or {}).get("vendor_code"), "title": (names.get(nm) or {}).get("title"),
                            "brand": (names.get(nm) or {}).get("brand"), "photo": (names.get(nm) or {}).get("photo"),
                            "cells": {k: funnel_metrics(nm, k, v) for k, v in cells.items()}} for nm, cells in arts],
              "articles_n": len(art)}
    T = tot.get("all") or acc()
    sh = lambda a, b: a / b if b else None              
    sources = []
    for sec, per in src.items():
        a = per["all"]
        m = with_ad(a, "all", "search") if sec == "Поиск" else _m(a)
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
                                                                               
    ad_sections = [('Реклама вне поиска (оценка)', 'rest')]
    if 'Поиск' not in src:
        ad_sections.insert(0, ('Реклама в поиске', 'search'))
    for label, placement in ad_sections:
        sources.append({'section': label, **with_ad({}, 'all', placement, True), 'points': [], 'ad_only': True})
    tm = with_ad(T, 'all', 'total')
    tm.update(share_views=1.0 if T["views"] else None, share_clicks=1.0 if T["clicks"] else None,
              share_carts=1.0 if T["carts"] else None, share_orders=1.0 if T["orders"] else None)
    day_list = sorted({d.isoformat() for d in rid.values()}, reverse=True)
    def sday(sec, dk):
        x = src[sec].get(dk, {})
        return with_ad(x, dk, 'search') if sec == 'Поиск' else _m(x, n_all if dk == 'all' else 1)
    sources_days = [{'section': sec, 'all': sday(sec, 'all'),
                     'days': {d: sday(sec, d) for d in day_list if sec == 'Поиск' or d in src[sec]}}
                    for sec in (s['section'] for s in sources if not s.get('ad_only'))]
    for label, placement in ad_sections:
        sources_days.append({'section': label, 'ad_only': True, 'all': with_ad({}, 'all', placement, True),
                             'days': {d: with_ad({}, d, placement, True) for d in day_list}})
    return {"periods": [{**p, "d_from": p["d_from"].isoformat(), "d_to": p["d_to"].isoformat()} for p in periods],
            "funnel": funnel, "sources": sources, "sources_total": tm, "sources_days": sources_days, "days": day_list, "n_days": n_all,
            "d_from": min(rid.values()).isoformat(), "d_to": top.isoformat(), "ad_note": entry_ads.NOTE}

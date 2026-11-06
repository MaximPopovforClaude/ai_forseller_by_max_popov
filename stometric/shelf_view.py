"""Self-hosted application component."""

from datetime import timedelta

TOP = 100
BACK = 7          


def _days(c) -> tuple:
    d = c.execute("SELECT max(day) d FROM shelf_snap").fetchone()["d"]
    if not d:
        return None, None
    p = c.execute("SELECT max(day) d FROM shelf_snap WHERE day <= %s", (d - timedelta(days=BACK),)).fetchone()["d"]
    return d, p


def _photos(c) -> dict:
    return {int(r["key"].split(":")[1]): int(r["value"]) for r in c.execute("SELECT key, value FROM app_settings WHERE key LIKE 'wbbasket:%%'")}


def _photo(hosts: dict, nm: int) -> str | None:
    h = hosts.get(nm // 100000)
    return f"https://basket-{h:02d}.wbbasket.ru/vol{nm // 100000}/part{nm // 1000}/{nm}/images/tm/1.webp" if h else None


def _where(c, day, nms: list[int]) -> dict:
    """{артикул: (в скольких полках, лучшее место, среднее место)} на день."""
    if not day or not nms:
        return {}
    return {r["x"]: (r["n"], r["best"], float(r["avg"])) for r in c.execute(
        """SELECT u.x, count(*) n, min(u.pos) best, avg(u.pos) avg FROM shelf_snap s, unnest(s.nms) WITH ORDINALITY u(x, pos)
           WHERE s.day=%s AND s.kind=1 AND s.nms && %s::bigint[] AND u.x = ANY(%s) GROUP BY u.x""", (day, nms, nms))}


def overview(c, shop: int) -> dict:
    from .exclusions import excluded
    d, p = _days(c)
    own = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, vendor_code, title, subject, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s", (shop,))}
    ex = excluded(c, shop)
    if not d:
        return {"day": None, "rows": []}
    snap = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, total, nms FROM shelf_snap WHERE day=%s AND kind=1 AND nm_id = ANY(%s)", (d, list(own)))}
    ids = [n for n in own if n not in ex]
    now, was = _where(c, d, ids), _where(c, p, ids)
    rows = []
    for nm in ids:
        if nm not in snap and nm not in now:
            continue
        o, s, w, w0 = own[nm], snap.get(nm), now.get(nm), was.get(nm)
        rows.append({"nm_id": nm, "vendor_code": o["vendor_code"], "title": o["title"], "subject": o["subject"], "photo": o["photo"],
                     "in_n": w[0] if w else 0, "in_n_was": (w0[0] if w0 else 0) if p else None,
                     "best": w[1] if w else None, "avg": round(w[2], 1) if w else None,
                     "shelf_total": s["total"] if s else None,
                     "own_top20": sum(1 for x in (s["nms"][:20] if s else []) if x in own)})
    rows.sort(key=lambda r: -r["in_n"])
    return {"day": d, "was_day": p, "rows": rows}


def detail(c, shop: int, nm: int, shops: list[int] | None = None) -> dict:
    """shops — чьи товары считать «нашими» (плагин: все магазины пользователя), иначе — этот магазин."""
    d, p = _days(c)
    if not d:
        return {"day": None}
    own = {r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id = ANY(%s)", (shops or [shop],))}
    hosts = _photos(c)

    def snap(day):
        r = c.execute("SELECT nms, total FROM shelf_snap WHERE nm_id=%s AND kind=1 AND day<=%s ORDER BY day DESC LIMIT 1", (nm, day)).fetchone() if day else None
        return r
    cur, old = snap(d), snap(p)
    
    def where(day):
        if not day:
            return {}
        return {r["nm_id"]: r["pos"] for r in c.execute(
            "SELECT nm_id, array_position(nms, %s::bigint) pos FROM shelf_snap WHERE day=%s AND kind=1 AND nms @> ARRAY[%s::bigint]", (nm, day, nm))}
    w_now, w_was = where(d), where(p)
    ids = set((cur or {}).get("nms") or []) | set((old or {}).get("nms") or []) | set(w_now) | set(w_was) | {nm}
    meta = {r["nm_id"]: r for r in c.execute("SELECT * FROM shelf_cards WHERE nm_id = ANY(%s)", (list(ids),))}

    def card(x):
        m = meta.get(x) or {}
        return {"nm_id": x, "name": m.get("name"), "brand": m.get("brand"), "supplier": m.get("supplier"), "price": m.get("price"),
                "rating": m.get("rating"), "feedbacks": m.get("feedbacks"), "ours": x in own, "photo": _photo(hosts, x)}

    shelf, left = [], []
    if cur:
        prev = {x: i + 1 for i, x in enumerate((old or {}).get("nms") or [])}
        for i, x in enumerate(cur["nms"][:TOP]):
            shelf.append({**card(x), "pos": i + 1, "pos_was": prev.get(x)})
        now_set = set(cur["nms"][:TOP])
        left = [{**card(x), "pos_was": i} for x, i in prev.items() if x not in now_set and i <= TOP]
    where_rows = [{**card(a), "pos": pos, "pos_was": w_was.get(a)} for a, pos in sorted(w_now.items(), key=lambda kv: kv[1])]
    gone = [{**card(a), "pos_was": pos} for a, pos in sorted(w_was.items(), key=lambda kv: kv[1]) if a not in w_now]
    hist = [{"day": r["day"], "n": r["n"], "avg": float(r["avg"]) if r["avg"] is not None else None, "top10": r["top10"]} for r in c.execute(
        """SELECT day, count(*) n, avg(array_position(nms, %s::bigint)) avg, count(*) FILTER (WHERE array_position(nms[1:10], %s::bigint) IS NOT NULL) top10
           FROM shelf_snap WHERE kind=1 AND day > %s AND nms @> ARRAY[%s::bigint] GROUP BY day ORDER BY day""", (nm, nm, d - timedelta(days=60), nm))]
    return {"day": d, "was_day": p, "card": card(nm), "taken": cur is not None, "shelf_total": cur["total"] if cur else None,
            "shelf": shelf, "left": left, "where": where_rows, "where_gone": gone, "hist": hist}

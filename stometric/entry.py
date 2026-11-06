"""Self-hosted application component."""

import io
import re
import zipfile
from datetime import date

import openpyxl


class EntryError(ValueError):
    pass


MAX_BYTES = 20 * 1024 * 1024


def _xlsx_bytes(raw: bytes, name: str) -> bytes:
    if raw[:2] == b"PK" and (name.lower().endswith(".zip") or "xl/workbook.xml" not in zipfile.ZipFile(io.BytesIO(raw)).namelist()):
        z = zipfile.ZipFile(io.BytesIO(raw))
        inner = [n for n in z.namelist() if n.lower().endswith(".xlsx") and not n.startswith("__MACOSX")]
        if not inner:
            raise EntryError("В архиве нет файла .xlsx")
        if z.getinfo(inner[0]).file_size > MAX_BYTES:
            raise EntryError("Файл в архиве слишком большой")
        return z.read(inner[0])
    return raw


def parse(raw: bytes, name: str = "") -> dict:
    if len(raw) > MAX_BYTES:
        raise EntryError("Файл больше 20 МБ")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(_xlsx_bytes(raw, name)), data_only=True, read_only=False)
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise EntryError("Не похоже на отчёт WB в формате xlsx") from e
    if "Детализация по артикулам" not in wb.sheetnames:
        raise EntryError("Нет листа «Детализация по артикулам» — это точно отчёт «Точки входа» из ЛК WB?")
    period = None
    if "Общая информация" in wb.sheetnames:
        for row in wb["Общая информация"].iter_rows(values_only=True):
            if row and row[0] == "Выбранный период" and row[1]:
                m = re.findall(r"\d{4}-\d{2}-\d{2}", str(row[1]))
                if len(m) == 2:
                    period = (date.fromisoformat(m[0]), date.fromisoformat(m[1]))
    if not period:   
        m = re.findall(r"(\d{2})[-.](\d{2})[-.](\d{4})", name)
        if len(m) >= 2:
            period = tuple(date(int(y), int(mo), int(d)) for d, mo, y in m[-2:])
    if not period:
        raise EntryError("Не нашёл период отчёта (лист «Общая информация»)")
    ws = wb["Детализация по артикулам"]
    head, rows = None, []
    for row in ws.iter_rows(values_only=True):
        if head is None:
            if row and "Точка входа" in row and "Артикул ВБ" in row:
                head = {v: i for i, v in enumerate(row) if v}
            continue
        g = lambda k: row[head[k]] if k in head and head[k] < len(row) else None  
        nm = g("Артикул ВБ")
        if not nm or not str(nm).strip().isdigit():
            continue
        num = lambda k: float(g(k) or 0)  
        rows.append({"section": str(g("Раздел") or "").strip(), "point": str(g("Точка входа") or "").strip(), "nm_id": int(nm),
                     "views": num("Показы"), "clicks": num("Переходы в карточку"), "carts": num("Добавления в корзину"), "orders": num("Заказы")})
    if head is None:
        raise EntryError("Не нашёл шапку таблицы («Раздел», «Точка входа», «Артикул ВБ»)")
    if not rows:
        raise EntryError("В отчёте нет строк по артикулам")
    return {"d_from": period[0], "d_to": period[1], "rows": rows}


def save(c, shop: int, user_id: int, raw: bytes, name: str) -> dict:
    p = parse(raw, name)
    own = {r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id=%s", (shop,))}
    nms = {r["nm_id"] for r in p["rows"]}
    if own and not (nms & own):
        raise EntryError("Артикулы отчёта не из этого магазина — проверьте, что выбран нужный магазин")
    rep = c.execute("""INSERT INTO entry_reports(account_id,d_from,d_to,file_name,uploaded_by) VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (account_id,d_from,d_to) DO UPDATE SET file_name=EXCLUDED.file_name, uploaded_by=EXCLUDED.uploaded_by,
                       uploaded_at=now() RETURNING id""", (shop, p["d_from"], p["d_to"], name[:200], user_id)).fetchone()["id"]
    c.execute("DELETE FROM entry_rows WHERE report_id=%s", (rep,))
    agg: dict = {}
    for r in p["rows"]:   
        k = (r["section"], r["point"], r["nm_id"])
        a = agg.setdefault(k, {"views": 0.0, "clicks": 0.0, "carts": 0.0, "orders": 0.0})
        for f in a:
            a[f] += r[f]
    with c.cursor() as cur:
        cur.executemany("INSERT INTO entry_rows(report_id,section,point,nm_id,views,clicks,carts,orders) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        [(rep, s, pt, nm, v["views"], v["clicks"], v["carts"], v["orders"]) for (s, pt, nm), v in agg.items()])
    if p["d_from"] == p["d_to"]:            
        refresh_alerts(c, shop, p["d_from"])
        notify_fresh(c, shop, p["d_from"])
    c.commit()
    return {"id": rep, "d_from": p["d_from"], "d_to": p["d_to"], "rows": len(agg), "articles": len(nms)}


def _m(v, cl, k, o) -> dict:
    f = lambda a, b: a / b if b else None  
    return {"views": v, "clicks": cl, "carts": k, "orders": o, "ctr": f(cl, v), "conv_cart": f(k, cl), "conv_order": f(o, k)}


def _periods(reps: list, mode: str, reports: list[int] | None) -> list[dict]:
    """Self-hosted application component."""
    daily = [r for r in reps if r["d_from"] == r["d_to"]]
    if mode == "days" and daily:
        top = daily[0]["d_to"]
        return [{"id": str(r["id"]), "d_from": r["d_from"], "d_to": r["d_to"], "n_days": 1, "ids": [r["id"]]}
                for r in daily if (top - r["d_to"]).days < 30]
    if mode == "weeks" and daily:
        from datetime import timedelta
        top, out = daily[0]["d_to"], []
        for w in range(4):
            hi = top - timedelta(days=7 * w)
            lo = hi - timedelta(days=6)
            ids = [r["id"] for r in daily if lo <= r["d_to"] <= hi]
            if ids:
                out.append({"id": f"w{w}", "d_from": lo, "d_to": hi, "n_days": len(ids), "ids": ids})
        return out
    use = [r for r in reps if not reports or r["id"] in reports][:8 if not reports else 30]
    return [{"id": str(r["id"]), "d_from": r["d_from"], "d_to": r["d_to"], "n_days": (r["d_to"] - r["d_from"]).days + 1, "ids": [r["id"]]} for r in use]


def view(c, shop: int, nms: list[int] | None = None, reports: list[int] | None = None, mode: str = "reports") -> dict:
    """Отчёт по точкам входа по столбцам-периодам (см. _periods), для всего магазина или выбранных артикулов; доля переходов точки."""
    reps = c.execute("""SELECT r.id, r.d_from, r.d_to, r.file_name, r.uploaded_at, coalesce(u.name, u.email) who FROM entry_reports r
                        LEFT JOIN users u ON u.id=r.uploaded_by WHERE r.account_id=%s ORDER BY r.d_to DESC, r.d_from DESC""", (shop,)).fetchall()
    pers = _periods(reps, mode, reports)
    if not pers:
        return {"reports": reps, "periods": [], "points": [], "articles": [], "has_daily": any(r["d_from"] == r["d_to"] for r in reps)}
    of = {i: p["id"] for p in pers for i in p["ids"]}           
    ids = list(of)
    pids = [p["id"] for p in pers]
    from .exclusions import excluded
    w, p = "report_id = ANY(%(ids)s) AND nm_id NOT IN (SELECT unnest(%(ex)s::bigint[]))", {"ids": ids, "ex": list(excluded(c, shop))}   
    if nms:
        w += " AND nm_id = ANY(%(nm)s)"; p["nm"] = nms
    data: dict = {}
    tot = {i: [0.0, 0.0, 0.0, 0.0] for i in pids}
    for r in c.execute(f"""SELECT report_id, section, point, sum(views) v, sum(clicks) cl, sum(carts) k, sum(orders) o FROM entry_rows
                           WHERE {w} GROUP BY 1, 2, 3""", p):
        vals = [float(r[x] or 0) for x in ("v", "cl", "k", "o")]
        col = of[r["report_id"]]
        cur = data.setdefault((r["section"], r["point"]), {}).setdefault(col, [0.0, 0.0, 0.0, 0.0])
        for j in range(4):
            cur[j] += vals[j]
            tot[col][j] += vals[j]
    points = []
    for (sec, pt), per in data.items():
        cells = {}
        for i in pids:
            v = per.get(i)
            if v:
                m = _m(*v)
                m["share"] = v[1] / tot[i][1] if tot[i][1] else None
                cells[i] = m
        last = per.get(pids[0]) or [0, 0, 0, 0]
        points.append({"section": sec, "point": pt, "cells": cells, "_sort": last[1]})
    points.sort(key=lambda x: -x["_sort"])
    for x in points:
        x.pop("_sort")
    arts = [{"nm_id": r["nm_id"], "vendor_code": r["vendor_code"], "title": r["title"], "clicks": float(r["cl"] or 0)} for r in c.execute(
        """SELECT e.nm_id, n.vendor_code, n.title, sum(e.clicks) cl FROM entry_rows e LEFT JOIN nomenclature n ON n.account_id=%s AND n.nm_id=e.nm_id
           WHERE e.report_id = ANY(%s) AND e.nm_id NOT IN (SELECT unnest(%s::bigint[])) GROUP BY 1, 2, 3 ORDER BY 4 DESC""", (shop, pers[0]["ids"], p["ex"]))]
    
    ads = {}
    for x in pers:
        q = {"a": shop, "f": x["d_from"], "t": x["d_to"], "ex": p["ex"], "nm": nms}
        flt = "nm_id NOT IN (SELECT unnest(%(ex)s::bigint[])) AND (%(nm)s::bigint[] IS NULL OR nm_id = ANY(%(nm)s::bigint[]))"
        t = c.execute(f"""SELECT sum((data->>'ad_views')::numeric) v, sum((data->>'ad_clicks')::numeric) cl, sum((data->>'ad_carts')::numeric) k,
                                 sum((data->>'ad_orders')::numeric) o FROM agg_nm_day WHERE account_id=%(a)s AND day BETWEEN %(f)s AND %(t)s AND {flt}""", q).fetchone()
        sr = c.execute(f"""SELECT sum(coalesce(views, 0)) v, sum(clicks) cl, sum(atbs) k, sum(orders) o FROM wb_ad_kw_daily
                           WHERE account_id=%(a)s AND day BETWEEN %(f)s AND %(t)s AND {flt}""", q).fetchone()
        tv = [float(t[k] or 0) for k in ("v", "cl", "k", "o")]
        sv = [float(sr[k] or 0) for k in ("v", "cl", "k", "o")]
        allv = tot[x["id"]]
        ads[x["id"]] = {"total": _m(*tv), "search": _m(*sv), "rest": _m(*[max(0.0, a - b) for a, b in zip(tv, sv)]),
                        "organic": _m(*[max(0.0, a - b) for a, b in zip(allv, tv)])}
    return {"reports": reps, "periods": [{k: x[k] for k in ("id", "d_from", "d_to", "n_days")} for x in pers],
            "points": points, "total": {i: _m(*tot[i]) for i in pids}, "articles": arts, "ads": ads,
            "has_daily": any(r["d_from"] == r["d_to"] for r in reps)}



MIN_AVG, MIN_DAY = 20, 40        
STEP_PCT, STEP_ABS = 0.5, 20     
SHOP_PCT, SHOP_ABS = 0.25, 50    


def analyze(c, shop: int, day: date | None = None, nms: list[int] | None = None, full: bool = False) -> dict | None:
    """День D (последний дневной отчёт не позже day) против среднего за до 7 предыдущих дневных отчётов (нужно ≥ 3).
    Показатель — переходы в карточку из точки входа; рядом показы, CTR и заказы для понимания. None — дневных отчётов мало."""
    reps = c.execute("""SELECT id, d_from FROM entry_reports WHERE account_id=%s AND d_from=d_to AND (%s::date IS NULL OR d_from <= %s)
                        ORDER BY d_from DESC LIMIT 8""", (shop, day, day)).fetchall()
    if len(reps) < 4:
        return None
    cur, base = reps[0], reps[1:]
    from .exclusions import excluded
    ex = list(excluded(c, shop))
    rows: dict = {}
    for r in c.execute("""SELECT report_id, section, point, nm_id, views, clicks, orders FROM entry_rows
                          WHERE report_id = ANY(%s) AND nm_id NOT IN (SELECT unnest(%s::bigint[])) AND (%s::bigint[] IS NULL OR nm_id = ANY(%s::bigint[]))""",
                       ([x["id"] for x in reps], ex, nms, nms)):
        rows.setdefault((r["nm_id"], r["section"], r["point"]), {})[r["report_id"]] = (float(r["views"] or 0), float(r["clicks"] or 0), float(r["orders"] or 0))
    names = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, title FROM nomenclature WHERE account_id=%s", (shop,))}
    nb = len(base)

    def stat(per, rid):
        return per.get(rid, (0.0, 0.0, 0.0))
    items, shop_pts = [], {}
    for (nm, sec, pt), per in rows.items():
        v, cl, o = stat(per, cur["id"])
        bv = sum(stat(per, b["id"])[0] for b in base) / nb
        bc = sum(stat(per, b["id"])[1] for b in base) / nb
        bo = sum(stat(per, b["id"])[2] for b in base) / nb
        sp = shop_pts.setdefault((sec, pt), [0.0, 0.0])
        sp[0] += cl
        sp[1] += bc
        if not (bc >= MIN_AVG or cl >= MIN_DAY):
            continue
        d = cl - bc
        if abs(d) < STEP_ABS or abs(d) < STEP_PCT * max(bc, 1):
            continue
        n = names.get(nm) or {}
        items.append({"nm_id": nm, "vendor_code": n.get("vendor_code") or str(nm), "title": (n.get("title") or "")[:50],
                      "section": sec, "point": pt, "clicks": round(cl), "clicks_avg": round(bc, 1), "change_pct": round(d / max(bc, 1) * 100),
                      "views": round(v), "views_avg": round(bv), "ctr": round(cl / v * 100, 1) if v else None,
                      "ctr_avg": round(bc / bv * 100, 1) if bv else None, "orders": round(o), "orders_avg": round(bo, 1)})
    pts = []
    for (sec, pt), (cl, bc) in shop_pts.items():
        d = cl - bc
        if abs(d) >= SHOP_ABS and abs(d) >= SHOP_PCT * max(bc, 1):
            pts.append({"section": sec, "point": pt, "clicks": round(cl), "clicks_avg": round(bc, 1), "change_pct": round(d / max(bc, 1) * 100)})
    drops = sorted([x for x in items if x["clicks"] < x["clicks_avg"]], key=lambda x: x["clicks"] - x["clicks_avg"])
    rises = sorted([x for x in items if x["clicks"] > x["clicks_avg"]], key=lambda x: x["clicks_avg"] - x["clicks"])
    pts.sort(key=lambda x: -abs(x["clicks"] - x["clicks_avg"]))
    return {"day": cur["d_from"].isoformat(), "base_days": nb, "base_from": base[-1]["d_from"].isoformat(), "base_to": base[0]["d_from"].isoformat(),
            "drops": drops if full else drops[:15], "rises": rises if full else rises[:10], "drops_n": len(drops), "rises_n": len(rises), "shop_points": pts[:8]}


def refresh_alerts(c, shop: int, day: date) -> int:
    """Пересчитать сильные изменения за день и за следующие дни (их «среднее за прошлые дни» включает этот день)."""
    days = [r["d_from"] for r in c.execute("""SELECT d_from FROM entry_reports WHERE account_id=%s AND d_from=d_to AND d_from >= %s
                                               ORDER BY d_from LIMIT 8""", (shop, day))]
    n = 0
    for d in days:
        a = analyze(c, shop, d, full=True)
        c.execute("DELETE FROM entry_alerts WHERE account_id=%s AND day=%s", (shop, d))
        if not a or a["day"] != d.isoformat():
            continue
        with c.cursor() as cur:
            cur.executemany("""INSERT INTO entry_alerts(account_id,day,nm_id,section,point,clicks,clicks_avg,change_pct,views,views_avg,orders,orders_avg)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                            [(shop, d, x["nm_id"], x["section"], x["point"], x["clicks"], x["clicks_avg"], x["change_pct"], x["views"],
                              x["views_avg"], x["orders"], x["orders_avg"]) for x in a["drops"] + a["rises"]])
        n += len(a["drops"]) + len(a["rises"])
    return n


def notify_fresh(c, shop: int, day: date) -> bool:
    """Свежий дневной отчёт (не старше 3 дней и самый новый у магазина) — событие «entry» гномику и в ленту: главные просадки и рост."""
    from .config import today_msk
    last = c.execute("SELECT max(d_from) d FROM entry_reports WHERE account_id=%s AND d_from=d_to", (shop,)).fetchone()["d"]
    if last != day or (today_msk() - day).days > 3:
        return False
    a = analyze(c, shop, day)
    if not a or not (a["drops"] or a["rises"]):
        return False
    import json as _j
    data = {"day": a["day"], "base_days": a["base_days"], "drops_n": a["drops_n"], "rises_n": a["rises_n"],
            "drops": a["drops"][:5], "rises": a["rises"][:3], "shop_points": a["shop_points"][:3]}
    c.execute("INSERT INTO news_events(account_id,kind,nm_id,data,ref) VALUES (%s,'entry',NULL,%s,%s) ON CONFLICT DO NOTHING",
              (shop, _j.dumps(data, ensure_ascii=False), f"entry:{shop}:{day}"))
    return True

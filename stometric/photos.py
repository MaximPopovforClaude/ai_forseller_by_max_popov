"""Self-hosted application component."""

import hashlib
import io
import json
import urllib.request
from datetime import timedelta

from .config import DATA, today_msk

SLOTS = 7
SAME = 6
ROOT = DATA / "photos"


def _basket_url(c, nm: int, i: int) -> str | None:
    from .cardcompare import photo
    first = photo(c, nm)                         
    return first.replace("/1.webp", f"/{i}.webp") if first else None


def _req(url: str, method: str = "GET"):
    return urllib.request.urlopen(urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0"}), timeout=15)


def _dhash(img) -> int:
    from PIL import Image
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    v = 0
    for r in range(8):
        for col in range(8):
            v = (v << 1) | (1 if px[r * 9 + col] > px[r * 9 + col + 1] else 0)
    return v - (1 << 64) if v >= (1 << 63) else v      


def _ham(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


def _store(c, blob: bytes) -> dict:
    from PIL import Image
    h = hashlib.sha256(blob).hexdigest()
    r = c.execute("SELECT hash, phash FROM photo_blobs WHERE hash=%s", (h,)).fetchone()
    if r:
        return r
    img = Image.open(io.BytesIO(blob))
    ph = _dhash(img)
    p = ROOT / h[:2] / f"{h}.avif"
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "AVIF", quality=55)
    p.write_bytes(buf.getvalue())
    c.execute("INSERT INTO photo_blobs(hash,phash,path,bytes) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (h, ph, str(p.relative_to(DATA)), len(buf.getvalue())))
    return {"hash": h, "phash": ph}


def snapshot(c, nm: int, source: str) -> dict:
    """Слепок 7 фото. Возвращает {"snap_id", "changed", "event"}. Если ничего не поменялось — новый слепок не пишем."""
    last = c.execute("SELECT * FROM photo_snaps WHERE nm_id=%s ORDER BY taken_at DESC LIMIT 1", (nm,)).fetchone()
    prev = {s["i"]: s for s in (last["slots"] if last else [])}
    slots = []
    for i in range(1, SLOTS + 1):
        url = _basket_url(c, nm, i)
        if not url:
            break
        try:
            with _req(url, "HEAD") as r:
                etag = r.headers.get("ETag") or r.headers.get("Last-Modified") or ""
        except Exception:  
            break
        p = prev.get(i)
        if p and p.get("etag") == etag and etag:
            slots.append(p)
            continue
        try:
            with _req(url) as r:
                blob = r.read()
        except Exception:  
            break
        b = _store(c, blob)
        slots.append({"i": i, "etag": etag, "hash": b["hash"], "phash": b["phash"]})
    sig = ",".join(s["hash"][:16] for s in slots)
    if last and last["sig"] == sig:
        c.commit()
        return {"snap_id": last["id"], "changed": False}
    sid = c.execute("INSERT INTO photo_snaps(nm_id,source,slots,sig) VALUES (%s,%s,%s,%s) RETURNING id",
                    (nm, source, json.dumps(slots), sig)).fetchone()["id"]
    ev = None
    if last and last["slots"]:
        ev = diff(last["slots"], slots)
        if ev["summary"]:
            c.execute("INSERT INTO photo_events(nm_id,snap_id,prev_id,day,summary,detail) VALUES (%s,%s,%s,%s,%s,%s)",
                      (nm, sid, last["id"], today_msk(), ev["summary"], json.dumps(ev, ensure_ascii=False)))
            own = c.execute("SELECT account_id FROM nomenclature WHERE nm_id=%s", (nm,)).fetchall()
            for o in own:   
                c.execute("""INSERT INTO card_changes(account_id,nm_id,kind,field,old_value,new_value) VALUES (%s,%s,'photo','photo_funnel',%s,%s)""",
                          (o["account_id"], nm, json.dumps({"snap": last["id"]}), json.dumps({"snap": sid, "summary": ev["summary"]}, ensure_ascii=False)))
    c.commit()
    return {"snap_id": sid, "changed": True, "event": ev}


def diff(old: list, new: list) -> dict:
    """Что поменялось между двумя слепками: по dHash сопоставляем картинки (перестановки), остальное — замена/добавление/удаление."""
    def same(a, b):
        return a["hash"] == b["hash"] or _ham(int(a["phash"]), int(b["phash"])) <= SAME
    moves, replaced, added, removed = [], [], [], []
    used = set()
    for n in new:
        hit = next((o for o in old if o["i"] not in used and same(o, n)), None)
        if hit:
            used.add(hit["i"])
            if hit["i"] != n["i"]:
                moves.append((hit["i"], n["i"]))
        else:
            if any(o["i"] == n["i"] for o in old):
                replaced.append(n["i"])
            else:
                added.append(n["i"])
    removed = [o["i"] for o in old if o["i"] not in used and not any(n["i"] == o["i"] for n in new)]
    parts = []
    swaps = [(a, b) for a, b in moves if (b, a) in moves and a < b]
    others = [(a, b) for a, b in moves if (a, b) not in swaps and (b, a) not in swaps]
    parts += [f"слайды {a} ↔ {b} поменяли местами" for a, b in swaps]
    parts += [f"слайд {a} перенесён на место {b}" for a, b in others]
    if replaced:
        parts.append("заменён слайд " + ", ".join(map(str, replaced)) if len(replaced) == 1 else "заменены слайды " + ", ".join(map(str, replaced)))
    if added:
        parts.append(("добавлен слайд " if len(added) == 1 else "добавлены слайды ") + ", ".join(map(str, added)))
    if removed:
        parts.append(("убран слайд " if len(removed) == 1 else "убраны слайды ") + ", ".join(map(str, removed)))
    s = "; ".join(parts)
    return {"summary": (s[:1].upper() + s[1:]) if s else "", "moves": moves, "replaced": replaced, "added": added, "removed": removed}


def daily(limit_own: int = 400) -> dict:
    """Раз в сутки: свои ходовые артикулы (заказы за 30 дней, кроме «не в работе») и конкуренты из вкладки «Конкуренты»."""
    from . import db
    from .exclusions import excluded
    out = {"own": 0, "competitors": 0, "changed": 0, "errors": 0}
    with db.connect() as c:
        own = []
        for a in c.execute("SELECT id FROM accounts WHERE is_active AND marketplace='wb'").fetchall():
            ex = excluded(c, a["id"])
            own += [(r["nm_id"], "own") for r in c.execute(
                """SELECT nm_id, count(*) k FROM orders WHERE account_id=%s AND order_dt > now() - interval '30 days' GROUP BY 1
                   ORDER BY 2 DESC LIMIT %s""", (a["id"], limit_own)) if r["nm_id"] not in ex]
        comp = [(r["comp_nm_id"], "competitor") for r in c.execute("SELECT DISTINCT comp_nm_id FROM competitors")]
        for nm, src in own + comp:
            try:
                r = snapshot(c, nm, src)
                out["own" if src == "own" else "competitors"] += 1
                out["changed"] += 1 if r.get("event") and r["event"]["summary"] else 0
            except Exception:  
                c.rollback()
                out["errors"] += 1
    return out


def effect(c, shop: int, nm: int, day, days: int = 7) -> dict:
    """Свои карточки: конверсии за N дней до и после смены фото (переходы → корзина → заказ, заказы в день)."""
    def win(a, b):
        from . import wb_demand
        r = wb_demand.summary(c,shop,a,b,[nm]).get(nm) or wb_demand.empty(a,b)
        
        r['orders_day'] = r['orders_day'] if r['expected_days'] == days else None
        return r
    return {"before": win(day - timedelta(days=days), day - timedelta(days=1)), "after": win(day, day + timedelta(days=days - 1))}


def period_stats(c, shop: int, nm: int, a, b) -> dict:
    """Self-hosted application component."""
    from . import wb_demand
    r = wb_demand.summary(c,shop,a,b,[nm]).get(nm) or wb_demand.empty(a,b)
    ad = c.execute("""SELECT sum((data->>'ad_views')::numeric) v, sum((data->>'ad_clicks')::numeric) cl
                     FROM agg_nm_day WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s""",
                   (shop,nm,a,r['to'])).fetchone()
    return {**r, 'days': r['expected_days'], 'ctr': float(ad['cl'] or 0)/float(ad['v']) if ad and ad['v'] else None}

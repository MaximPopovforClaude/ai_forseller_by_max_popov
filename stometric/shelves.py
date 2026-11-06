"""Self-hosted application component."""

import json
import subprocess
import sys
import time

from . import db
from .config import today_msk
from .showcase import HOST, KEY

REMOTE = "cd /opt/egress && flock -w 1500 /opt/egress/.wb.lock xvfb-run -a .venv/bin/python wbshelf.py"
CHUNK = 300          
NEIGH = 20           
MAX_TOTAL = 12000    


def fetch(*args, **kwargs):
    raise RuntimeError('Внешний браузер полок не настроен в самостоятельной версии.')


def save(c, day, j: dict) -> int:
    rows = [(day, int(nm), v[0], v[1]) for nm, v in (j.get("shelves") or {}).items()]
    with c.cursor() as cur:
        cur.executemany("""INSERT INTO shelf_snap(day,nm_id,kind,total,nms) VALUES (%s,%s,1,%s,%s)
                           ON CONFLICT (day,nm_id,kind) DO UPDATE SET total=EXCLUDED.total, nms=EXCLUDED.nms, taken_at=now()""", rows)
        cur.executemany("""INSERT INTO shelf_cards(nm_id,name,brand,supplier,supplier_id,subject_id,rating,feedbacks,price,seen_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                           ON CONFLICT (nm_id) DO UPDATE SET name=EXCLUDED.name, brand=EXCLUDED.brand, supplier=EXCLUDED.supplier,
                             supplier_id=EXCLUDED.supplier_id, subject_id=EXCLUDED.subject_id, rating=EXCLUDED.rating,
                             feedbacks=EXCLUDED.feedbacks, price=EXCLUDED.price, seen_at=now()""",
                        [(int(k), *v) for k, v in (j.get("cards") or {}).items()])
    c.commit()
    return len(rows)


def neighbours(c, own: list[int]) -> list[int]:
    """Топ-NEIGH из последних полок наших товаров — по частоте (чаще встречается — раньше)."""
    return [r["nm"] for r in c.execute(
        """WITH last AS (SELECT DISTINCT ON (nm_id) nms FROM shelf_snap WHERE nm_id = ANY(%s) AND kind=1 ORDER BY nm_id, day DESC)
           SELECT x nm FROM last, unnest(nms[1:%s]) x WHERE NOT x = ANY(%s) GROUP BY x ORDER BY count(*) DESC, x""",
        (own, NEIGH, own))]


def crawl(c, day, nms: list[int], log) -> dict:
    done = {r["nm_id"] for r in c.execute("SELECT nm_id FROM shelf_snap WHERE day=%s AND kind=1", (day,))}
    todo = [n for n in nms if n not in done]
    n = {"asked": len(todo), "saved": 0, "errors": 0}
    for i in range(0, len(todo), CHUNK):
        part = todo[i:i + CHUNK]
        t = time.time()
        try:
            j = fetch(part)
        except Exception as e:                       
            log(f"заход {i // CHUNK + 1}: {e}")
            n["errors"] += 1
            continue
        k = save(c, day, j)
        n["saved"] += k
        if j.get("errors"):
            log(f"заход {i // CHUNK + 1}: " + "; ".join(j["errors"][:5]))
        log(f"заход {i // CHUNK + 1}: {k}/{len(part)} за {time.time() - t:.0f} с")
    return n


def photos(c, limit_s: int = 2400) -> int:
    """Фото карточек из полок: номер «корзины» CDN WB по тому — подбираем для новых томов (cardcompare.photo запоминает)."""
    from .cardcompare import photo
    known = {int(r["key"].split(":")[1]) for r in c.execute("SELECT key FROM app_settings WHERE key LIKE 'wbbasket:%%'")}
    todo = {}
    for r in c.execute("SELECT nm_id FROM shelf_cards WHERE seen_at > now() - interval '1 day'"):
        v = r["nm_id"] // 100000
        if v not in known:
            todo.setdefault(v, r["nm_id"])
    t, n = time.time(), 0
    for nm in todo.values():
        if time.time() - t > limit_s:
            break
        n += photo(c, nm) is not None
    return n


def run(log=print) -> dict:
    from .showcase import targets
    day = today_msk()
    with db.connect() as c:
        own = sorted(targets(c))
        res = {"own": crawl(c, day, own, log)}
        nb = neighbours(c, own)[:max(0, MAX_TOTAL - len(own))]
        res["neighbours"] = crawl(c, day, nb, log)
        res["photo_vols"] = photos(c)
        return res


if __name__ == "__main__":
    print(json.dumps(run(lambda s: print(s, file=sys.stderr, flush=True)), ensure_ascii=False))

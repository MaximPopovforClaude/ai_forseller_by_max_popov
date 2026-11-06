"""Self-hosted application component."""

import json
import os
import subprocess
import sys
from datetime import datetime

from . import db

HOST = ""
KEY = ""
REMOTE = "cd /opt/egress && flock -w 600 /opt/egress/.wb.lock xvfb-run -a .venv/bin/python wbshow.py"   
STEP = 1.0           
FRESH = "2 hours"    


def fetch(nms):
    raise RuntimeError('Внешний браузер витрин не настроен в самостоятельной версии.')


def targets(c) -> dict[int, dict]:
    """{nm: {account_id, seller_price, vc, title}} — товары в продаже по всем активным магазинам WB."""
    from .exclusions import excluded
    out = {}
    for a in c.execute("SELECT id FROM accounts WHERE marketplace='wb' AND is_active ORDER BY id").fetchall():
        ex = excluded(c, a["id"])
        for r in c.execute(
                """WITH st AS (SELECT nm_id FROM stocks_wb_snap WHERE account_id=%(a)s AND quantity > 0
                               AND snap_at=(SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=%(a)s)
                               UNION SELECT nm_id FROM orders WHERE account_id=%(a)s AND order_dt > now() - interval '7 days'),
                        lp AS (SELECT DISTINCT ON (nm_id) nm_id, discounted_price FROM prices_snap WHERE account_id=%(a)s
                               ORDER BY nm_id, snap_at DESC, size_id)
                   SELECT st.nm_id, lp.discounted_price sp, n.vendor_code vc, n.title FROM st
                   LEFT JOIN lp USING (nm_id) LEFT JOIN nomenclature n ON n.account_id=%(a)s AND n.nm_id=st.nm_id""",
                {"a": a["id"]}).fetchall():
            if r["nm_id"] not in ex:
                out.setdefault(r["nm_id"], {"account_id": a["id"], "seller_price": float(r["sp"]) if r["sp"] else None,
                                            "vc": r["vc"], "title": r["title"]})
    return out


def save_panels(c, tg: dict, panels: dict) -> int:
    """Плашка акции на витрине: появилась / сменилась / пропала — в журнал изменений (card_changes, kind='promo'); день — в wb_promo_days."""
    from .config import today_msk
    old = {(r["account_id"], r["nm_id"]): r["panel_promo"] for r in c.execute("SELECT account_id, nm_id, panel_promo FROM wb_showcase")}
    n = 0
    for nm, pid in panels.items():
        t = tg.get(nm)
        if not t:
            continue
        a = t["account_id"]
        pid = pid or 0                          
        was = old.get((a, nm))
        if was is not None and was != pid:
            c.execute("""INSERT INTO card_changes(account_id,nm_id,detected_at,kind,field,old_value,new_value,source)
                         VALUES (%s,%s,now(),'promo','panel',%s,%s,'showcase')""",
                      (a, nm, json.dumps({"panel": was}) if was else None, json.dumps({"panel": pid}) if pid else None))
            n += 1
        c.execute("UPDATE wb_showcase SET panel_promo=%s WHERE account_id=%s AND nm_id=%s", (pid, a, nm))
        if pid:
            c.execute("""INSERT INTO wb_promo_days(account_id,nm_id,day,promos) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,nm_id,day)
                         DO UPDATE SET promos=(SELECT array_agg(DISTINCT x) FROM unnest(wb_promo_days.promos || EXCLUDED.promos) x)""",
                      (a, nm, today_msk(), [f"плашка акции №{pid}"]))
    c.commit()
    return n


VOL_STEP = 0.1      


def save_vols(c, tg: dict, vols: dict) -> int:
    """Объём товара для логистики (как считает WB): изменился — история и событие «volume» в ленту и гномику. Первый раз — без события."""
    old = {(r["account_id"], r["nm_id"]): r for r in c.execute("SELECT account_id, nm_id, volume, weight FROM wb_showcase WHERE volume IS NOT NULL")}
    dims = {}
    accs = {t["account_id"] for t in tg.values()}
    for r in c.execute("SELECT account_id, nm_id, subject, data->'dimensions' d FROM nomenclature WHERE account_id = ANY(%s)", (list(accs),)):
        dims[(r["account_id"], r["nm_id"])] = r
    n = 0
    for nm, (vol, wt) in vols.items():
        t = tg.get(nm)
        if not t:
            continue
        a = t["account_id"]
        o = old.get((a, nm))
        c.execute("UPDATE wb_showcase SET volume=%s, weight=%s WHERE account_id=%s AND nm_id=%s", (vol, wt, a, nm))
        if o is not None and abs(float(o["volume"]) - vol) < VOL_STEP - 1e-9:
            continue
        c.execute("INSERT INTO wb_volume_hist(account_id,nm_id,volume,weight) VALUES (%s,%s,%s,%s)", (a, nm, vol, wt))
        if o is None:
            continue
        dm = dims.get((a, nm)) or {}
        d = dm.get("d") or {}
        card = None
        if all(d.get(k) for k in ("length", "width", "height")):
            card = {"l": d["length"], "w": d["width"], "h": d["height"], "liters": round(d["length"] * d["width"] * d["height"] / 1000, 2)}
        ev = {"vc": t["vc"], "title": t["title"], "subject": dm.get("subject"), "old": float(o["volume"]), "new": vol,
              "old_w": float(o["weight"]) if o["weight"] is not None else None, "new_w": wt, "card": card}
        c.execute("""INSERT INTO news_events(account_id,kind,nm_id,data,ref) VALUES (%s,'volume',%s,%s,%s) ON CONFLICT DO NOTHING""",
                  (a, nm, json.dumps(ev, ensure_ascii=False), f"volume:{a}:{nm}:{o['volume']}:{vol}:{datetime.now():%Y%m%d%H}"))
        n += 1
    c.commit()
    return n


def save(c, tg: dict, prices: dict) -> dict:
    """Запись цен и событий СПП. → {checked, changed, events}."""
    old = {(r["account_id"], r["nm_id"]): r for r in c.execute("SELECT * FROM wb_showcase").fetchall()}
    n = {"checked": 0, "changed": 0, "events": 0}
    for nm, (basic, price) in prices.items():
        t = tg.get(nm)
        if not t:
            continue
        a, sp = t["account_id"], t["seller_price"]
        spp = round((1 - price / sp) * 100, 1) if sp else None
        o = old.get((a, nm))
        n["checked"] += 1
        changed = o is None or float(o["price"] or 0) != price or (o["spp"] is None) != (spp is None) or\
            (spp is not None and float(o["spp"]) != spp)
        c.execute("""INSERT INTO wb_showcase(account_id,nm_id,basic,price,seller_price,spp,checked_at,changed_at)
                     VALUES (%s,%s,%s,%s,%s,%s,now(),now())
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET basic=EXCLUDED.basic, price=EXCLUDED.price,
                       seller_price=EXCLUDED.seller_price, spp=EXCLUDED.spp, checked_at=now(),
                       changed_at=CASE WHEN %s THEN now() ELSE wb_showcase.changed_at END""",
                  (a, nm, basic, price, sp, spp, changed))
        if not changed:
            continue
        n["changed"] += 1
        c.execute("INSERT INTO wb_showcase_hist(account_id,nm_id,price,seller_price,spp) VALUES (%s,%s,%s,%s,%s)", (a, nm, price, sp, spp))
        if o is None or o["spp"] is None or spp is None or abs(spp - float(o["spp"])) < STEP:
            continue
        osp = float(o["seller_price"]) if o["seller_price"] is not None else None
        d = {"vc": t["vc"], "title": t["title"], "old_pct": float(o["spp"]), "new_pct": spp, "price": sp, "src": "showcase",
             "old_buyer": round(float(o["price"])), "new_buyer": round(price)}
        if osp and abs(osp - sp) >= 1:
            d.update(price_changed=True, old_price=osp, new_price=sp)
        c.execute("""INSERT INTO news_events(account_id,kind,nm_id,data,ref) VALUES (%s,'spp',%s,%s,%s) ON CONFLICT DO NOTHING""",
                  (a, nm, json.dumps(d, ensure_ascii=False), f"showcase:{a}:{nm}:{spp}:{price}:{o['changed_at']:%Y%m%d%H%M}"))
        n["events"] += 1
    c.commit()
    return n


def fresh_accounts(c) -> set[int]:
    """Магазины, по которым витрина свежая (СПП по заказам для них не считаем)."""
    return {r["account_id"] for r in c.execute(
        f"SELECT DISTINCT account_id FROM wb_showcase WHERE checked_at > now() - interval '{FRESH}'")}


def run() -> dict:
    with db.connect() as c:
        tg = targets(c)
        prices, panels, vols = fetch(sorted(tg))
        res = save(c, tg, prices)
        if panels is not None:
            res["promo_changes"] = save_panels(c, tg, panels)
        if vols is not None:
            res["volume_changes"] = save_vols(c, tg, vols)
        res["asked"] = len(tg)
        return res


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))

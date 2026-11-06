"""Self-hosted application component."""

import io
import re
import zipfile

from . import manager, rnp
from .cost_import import open_xlsx


class PromoError(ValueError):
    pass


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def parse_file(raw: bytes, name: str) -> list[dict]:
    """Файл товаров акции из ЛК WB: ищем столбцы «Артикул WB», «Плановая цена для акции» (или «Цена для участия/по акции»),
    «Товар уже участвует в акции» / «Участвует»."""
    if raw[:2] == b"PK" and name.lower().endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(raw))
        inner = [n for n in z.namelist() if n.lower().endswith(".xlsx")]
        if not inner:
            raise PromoError("В архиве нет .xlsx")
        raw = z.read(inner[0])
    try:
        wb = open_xlsx(io.BytesIO(raw))
    except Exception as e:  
        raise PromoError("Не похоже на файл акции из ЛК WB (xlsx)") from e
    for ws in wb.worksheets:
        head = None
        out = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(x or "").strip().lower() for x in row]
            if head is None:
                nm_i = next((i for i, x in enumerate(cells) if x in ("артикул wb", "артикул вб", "номенклатура (код 1с)", "артикул")), None)
                pr_i = next((i for i, x in enumerate(cells) if "плановая цена" in x or "цена для акции" in x or "цена по акции" in x
                             or "цена для участия" in x), None)
                if nm_i is not None and pr_i is not None:
                    part_i = next((i for i, x in enumerate(cells) if "участвует" in x), None)
                    head = (nm_i, pr_i, part_i)
                continue
            nm = _num(row[head[0]]) if head[0] < len(row) else None
            if not nm:
                continue
            price = _num(row[head[1]]) if head[1] < len(row) else None
            part = str(row[head[2]] or "").strip().lower() if head[2] is not None and head[2] < len(row) else ""
            out.append({"nm_id": int(nm), "price": price, "in_action": part in ("да", "yes", "true", "1", "участвует")})
        if head:
            if not out:
                raise PromoError("В файле нет строк с товарами")
            return out
    raise PromoError("Не нашёл столбцы «Артикул WB» и «Плановая цена для акции» — пришлите файл, разберу формат")


def view(c, shop: int) -> dict:
    other = manager.other_pct(c, shop)
    units = manager._unit_inputs(c, shop)
    bp, bp0 = rnp.buyout_pct(c, shop)
    speed = {r["nm_id"]: float(r["o"] or 0) / 30 for r in c.execute(
        """SELECT nm_id, sum((data->>'orders')::numeric) o FROM agg_nm_day WHERE account_id=%s AND day > current_date - 30 GROUP BY 1""", (shop,))}
    way = {r["nm_id"]: r for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(in_way_to_client) wt, sum(in_way_from_client) wf FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t
           WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    hidden = {r["promo"] for r in c.execute("SELECT promo FROM promo_hidden WHERE account_id=%s", (shop,))}
    promos = []
    for p in c.execute("""SELECT promo_id, name, kind, start_at, end_at FROM wb_promotions WHERE account_id=%s AND kind <> 'auto'
                          AND end_at > now() ORDER BY start_at""", (shop,)).fetchall():
        key = f"api:{p['promo_id']}"
        if key in hidden:
            continue
        items = {r["nm_id"]: {"price": float(r["plan_price"]) if r["plan_price"] is not None else None, "in_action": r["in_action"]}
                 for r in c.execute("SELECT * FROM wb_promo_items WHERE account_id=%s AND promo_id=%s", (shop, p["promo_id"]))}
        promos.append({"key": key, "name": p["name"], "source": "api", "from": p["start_at"], "to": p["end_at"], "items": items})
    for u in c.execute("SELECT * FROM promo_uploads WHERE account_id=%s ORDER BY id", (shop,)).fetchall():
        promos.append({"key": f"up:{u['id']}", "name": u["name"], "source": "file", "uploaded_at": u["uploaded_at"],
                       "items": {int(x["nm_id"]): {"price": x.get("price"), "in_action": bool(x.get("in_action"))} for x in u["items"]}})
    calc = {}
    for r in c.execute("SELECT promo, nm_id FROM promo_calc WHERE account_id=%s", (shop,)):
        calc.setdefault(r["promo"], set()).add(r["nm_id"])
    rows = []
    for nm, u in units.items():
        b = bp.get(nm, bp0)
        w = way.get(nm) or {}
        have = float(u.get("stock") or 0) + float(w.get("wt") or 0) * (1 - b) + float(w.get("wf") or 0)
        sp = speed.get(nm, 0.0)
        base = manager.unit_calc(u, other, None)
        row = {"nm_id": nm, "vendor_code": u["vendor_code"], "title": u["title"], "subject": u["subject"], "photo": u["photo"],
               "turnover": round(have / sp, 1) if sp else None, "stock": base["stock"], "price": base["online"], "margin": base["margin_online_pct"],
               "margin_rub": base["margin_online"], "no_cost": base["cost"] is None, "promos": {}}
        for p in promos:
            it = p["items"].get(nm)
            if not it:
                continue
            m = manager.unit_calc(u, other, it["price"]) if it.get("price") else None
            row["promos"][p["key"]] = {"in_action": it["in_action"], "calc": nm in calc.get(p["key"], set()), "price": it.get("price"),
                                       "margin": m["margin_calc_pct"] if m else None, "margin_rub": m["margin_calc"] if m else None,
                                       "diff": (m["margin_calc_pct"] - base["margin_online_pct"]) if m and m["margin_calc_pct"] is not None
                                       and base["margin_online_pct"] is not None else None}
        rows.append(row)
    rows.sort(key=lambda r: (r["turnover"] is None, -(r["turnover"] or 0)))
    out_p = []
    for p in promos:
        n_el = sum(1 for r in rows if p["key"] in r["promos"])
        n_in = sum(1 for r in rows if r["promos"].get(p["key"], {}).get("in_action"))
        n_calc = sum(1 for r in rows if r["promos"].get(p["key"], {}).get("calc"))
        out_p.append({k: v for k, v in p.items() if k != "items"} | {"eligible": n_el, "fact_pct": n_in / n_el if n_el else None,
                                                                    "calc_pct": n_calc / n_el if n_el else None})
    return {"rows": rows, "promos": out_p}

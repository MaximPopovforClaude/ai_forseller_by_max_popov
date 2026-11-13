"""Self-hosted application component."""

import io
import math
import re
import zipfile
from datetime import datetime, timedelta, timezone

from . import manager, rnp
from .cost_import import open_xlsx


class PromoError(ValueError):
    pass


def _num(v):
    if v is None or v == "":
        return None
    try:
        value = float(re.sub(r"\s+", "", str(v)).replace("₽", "").replace(",", "."))
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def parse_file(raw: bytes, name: str) -> list[dict]:
    """Файл товаров акции из ЛК WB: ищем столбцы «Артикул WB», «Плановая цена для акции» (или «Цена для участия/по акции»),
    «Товар уже участвует в акции» / «Участвует»."""
    if name.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                inner = [n for n in z.namelist() if n.lower().endswith(".xlsx")
                         and not n.startswith("__MACOSX/") and not n.rsplit("/", 1)[-1].startswith("._")]
                if not inner:
                    raise PromoError("В архиве нет файла .xlsx. Загрузите файл товаров акции из ЛК WB.")
                raw = z.read(inner[0])
        except (zipfile.BadZipFile, RuntimeError, KeyError, NotImplementedError) as e:
            raise PromoError("Не удалось открыть ZIP-архив. Распакуйте его и загрузите файл .xlsx.") from e
    try:
        wb = open_xlsx(io.BytesIO(raw))
    except Exception as e:  
        raise PromoError("Не похоже на файл акции из ЛК WB (xlsx)") from e
    try:
        return _parse_workbook(wb)
    except PromoError:
        raise
    except Exception as e:  
        raise PromoError("Не удалось прочитать таблицу. Скачайте файл акции заново в формате .xlsx.") from e
    finally:
        wb.close()


def _parse_workbook(wb):
    for ws in wb.worksheets:
        head = None
        out = []
        for row in ws.iter_rows(values_only=True):
            cells = [re.sub(r"\s+", " ", str(x or "")).strip().lower() for x in row]
            if head is None:
                
                
                nm_i = next((cells.index(x) for x in ("артикул wb", "артикул вб", "номенклатура (код 1с)", "артикул") if x in cells), None)
                pr_i = next((i for i, x in enumerate(cells) if "плановая цена" in x or "цена для акции" in x or "цена по акции" in x
                             or "цена для участия" in x), None)
                if nm_i is not None and pr_i is not None:
                    part_i = next((i for i, x in enumerate(cells) if "участвует" in x), None)
                    head = (nm_i, pr_i, part_i)
                continue
            nm = _num(row[head[0]]) if head[0] < len(row) else None
            if nm is None or nm <= 0 or not nm.is_integer():
                continue
            price = _num(row[head[1]]) if head[1] < len(row) else None
            part = str(row[head[2]] or "").strip().lower() if head[2] is not None and head[2] < len(row) else ""
            out.append({"nm_id": int(nm), "price": price, "in_action": part in ("да", "yes", "true", "1", "участвует")})
        if head:
            if not out:
                raise PromoError("В файле нет строк с товарами")
            return out
    raise PromoError("Не найдены столбцы «Артикул WB» и цены акции. Нужен XLSX списка товаров выбранной акции из ЛК WB.")


def collection_status(c, shop: int) -> dict:
    """Shop-scoped collection evidence; never expose raw API error messages."""
    from .schedule import EVERY_MIN
    from .collectors.prices import PROMO_FUTURE_DAYS
    state = c.execute("""SELECT last_ok_at, last_run_at, COALESCE(last_error <> '', false) failed
                         FROM collector_state WHERE account_id=%s AND collector='promotions'""", (shop,)).fetchone() or {}
    account = c.execute("SELECT is_active FROM accounts WHERE id=%s", (shop,)).fetchone() or {}
    catalog_at = c.execute("SELECT max(updated_at) at FROM wb_promotions WHERE account_id=%s", (shop,)).fetchone()["at"]
    ok = state.get("last_ok_at")
    status = "disabled" if not account.get("is_active") else "error" if state.get("failed") else "never" if not ok else (
        "stale" if datetime.now(timezone.utc) - ok > timedelta(minutes=EVERY_MIN["promotions"]) else "ok")
    return {"status": status, "last_ok_at": ok, "last_run_at": state.get("last_run_at"), "catalog_at": catalog_at,
            "interval_minutes": EVERY_MIN["promotions"], "future_days": PROMO_FUTURE_DAYS}


def view(c, shop: int) -> dict:
    other = manager.other_pct(c, shop)
    units = manager._unit_inputs(c, shop)
    bp, bp0 = rnp.buyout_pct(c, shop)
    from . import wb_demand
    from .config import today_msk
    from datetime import timedelta
    end = today_msk() - timedelta(days=1)
    demand = wb_demand.summary(c,shop,end-timedelta(days=29),end)
    way = {r["nm_id"]: r for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(in_way_to_client) wt, sum(in_way_from_client) wf FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t
           WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    hidden = {r["promo"] for r in c.execute("SELECT promo FROM promo_hidden WHERE account_id=%s", (shop,))}
    promos, auto_promos = [], []
    hidden_count = 0
    for p in c.execute("""SELECT promo_id, name, kind, start_at, end_at FROM wb_promotions WHERE account_id=%s
                          AND end_at > now() ORDER BY start_at""", (shop,)).fetchall():
        key = f"api:{p['promo_id']}"
        if key in hidden:
            hidden_count += 1
            continue
        if p["kind"] == "auto":
            auto_promos.append({"key": key, "name": p["name"] or f"Акция {p['promo_id']}", "from": p["start_at"], "to": p["end_at"]})
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
        dm = demand.get(nm) or wb_demand.empty(end-timedelta(days=29),end)
        sp = dm['orders_day']
        base = manager.unit_calc(u, other, None)
        row = {"nm_id": nm, "vendor_code": u["vendor_code"], "title": u["title"], "subject": u["subject"], "photo": u["photo"], 'demand': dm,
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
    return {"rows": rows, "promos": out_p, "auto_promos": auto_promos,
            "collection": collection_status(c, shop), "hidden_count": hidden_count, 'demand_note': wb_demand.NOTE}

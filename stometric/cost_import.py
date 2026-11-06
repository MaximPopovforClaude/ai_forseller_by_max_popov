"""Self-hosted application component."""

import csv
import io
import re
from datetime import date

import openpyxl


FIRST = date(2000, 1, 1)      


def open_xlsx(src):
    """xlsx на чтение. Размер листа из файла не берём: выгрузки многих сервисов пишут «A1» — тогда openpyxl видит одну ячейку."""
    wb = openpyxl.load_workbook(src, data_only=True, read_only=True)
    for ws in wb.worksheets:
        ws.reset_dimensions()
    return wb


class CostImportError(ValueError):
    pass


NM_HEAD = ("артикул wb", "артикул вб", "nmid", "nm_id", "nm id", "код номенклатуры", "номенклатура", "sku", "sku ozon", "артикул ozon", "sku на маркете", "market sku", "marketsku", "ску на маркете")
VC_HEAD = ("артикул продавца", "артикул поставщика", "vendor_code", "vendorcode", "offer_id", "артикул")
COST_HEAD = ("себестоимость", "cost_price", "cost", "себес", "закупка", "закупочная цена")


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace("₽", "").replace(",", "."))
    except ValueError:
        return None


def _find(cells: list[str], names) -> int | None:
    for n in names:                                   
        for i, x in enumerate(cells):
            if x == n:
                return i
    for n in names:
        for i, x in enumerate(cells):
            if x.startswith(n):
                return i
    return None


def _rows_of(raw: bytes, name: str) -> list[list[list]]:
    """Листы файла → строки значений."""
    if raw[:2] == b"PK":
        try:
            wb = open_xlsx(io.BytesIO(raw))
        except Exception as e:  
            raise CostImportError("Не открывается как xlsx") from e
        sheets = sorted(wb.worksheets, key=lambda ws: "себест" not in ws.title.lower())   
        return [[list(r) for r in ws.iter_rows(values_only=True)] for ws in sheets]
    text = raw.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4000], delimiters=";,\t") if text.strip() else csv.excel
    return [[r for r in csv.reader(io.StringIO(text), dialect)]]


def parse(raw: bytes, name: str) -> tuple[str, list[tuple[str, float]]]:
    """→ (вид ключа: 'nm' | 'vc', [(ключ, себестоимость)])."""
    for rows in _rows_of(raw, name):
        for hi, row in enumerate(rows[:15]):
            cells = [str(x or "").strip().lower() for x in row]
            ci = _find(cells, COST_HEAD)
            if ci is None:
                continue
            ni, vi = _find(cells, NM_HEAD), _find(cells, VC_HEAD)
            if ni is None and vi is None:
                continue
            out_nm, out_vc = [], []
            for r in rows[hi + 1:]:
                cost = _num(r[ci]) if ci < len(r) else None
                if cost is None:
                    continue
                if ni is not None and ni < len(r) and _num(r[ni]):
                    out_nm.append((str(int(_num(r[ni]))), cost))
                elif vi is not None and vi < len(r) and str(r[vi] or "").strip():
                    out_vc.append((str(r[vi]).strip(), cost))
            if out_nm or out_vc:
                return ("nm", out_nm) if len(out_nm) >= len(out_vc) else ("vc", out_vc)
    raise CostImportError("Не нашёл столбцы артикула (Артикул WB / SKU / Артикул продавца) и «Себестоимость» в первых 15 строках листов")


def fetch_url(url: str) -> bytes:
    """Google-таблица по ссылке (доступ «всем, у кого есть ссылка») → xlsx всей книги. Другие адреса не открываем."""
    import httpx
    m = re.match(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)", url.strip())
    if not m:
        raise CostImportError("Нужна ссылка на Google-таблицу вида https://docs.google.com/spreadsheets/d/…")
    r = httpx.get(f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=xlsx", follow_redirects=True, timeout=60)
    if r.status_code != 200 or r.content[:2] != b"PK":
        raise CostImportError("Таблица не открылась: включите доступ «Все, у кого есть ссылка — читатель» и пришлите ссылку ещё раз")
    if len(r.content) > 30_000_000:
        raise CostImportError("Таблица больше 30 МБ")
    return r.content


def match(c, shop: int, kind: str, items: list[tuple[str, float]], valid_from: date) -> dict:
    """Только чтение: что запишется. → {"write": [(nm, себестоимость, с какой даты)], "same", "unknown", "unknown_list", "bad", "total"}."""
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    if mp == "ym":      
        known = {str(r["market_sku"]): r["market_sku"] for r in c.execute(
            "SELECT market_sku FROM ym_offers WHERE account_id=%s AND market_sku IS NOT NULL", (shop,))}
        by_vc = {r["offer_id"].lower(): r["market_sku"] for r in c.execute(
            "SELECT offer_id, market_sku FROM ym_offers WHERE account_id=%s AND market_sku IS NOT NULL", (shop,))}
    elif mp == "ozon":
        known = {str(r["sku"]): r["sku"] for r in c.execute("SELECT sku FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,))}
        by_vc = {r["offer_id"].lower(): r["sku"] for r in c.execute(
            "SELECT offer_id, sku FROM oz_products WHERE account_id=%s AND sku IS NOT NULL AND offer_id IS NOT NULL", (shop,))}
    else:
        known = {str(r["nm_id"]): r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id=%s", (shop,))}
        by_vc = {r["vendor_code"].lower(): r["nm_id"] for r in c.execute(
            "SELECT vendor_code, nm_id FROM nomenclature WHERE account_id=%s AND vendor_code IS NOT NULL", (shop,))}
    cur = {r["nm_id"]: float(r["cost"]) for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%s AND valid_from <= %s
           ORDER BY nm_id, valid_from DESC""", (shop, valid_from))}
    has_any = {r["nm_id"] for r in c.execute("SELECT DISTINCT nm_id FROM cost_price WHERE account_id=%s", (shop,))}
    write, same, unknown, bad = [], 0, [], 0
    seen = set()
    for key, cost in items:
        nm = known.get(key) if kind == "nm" else by_vc.get(key.lower())
        if nm is None:
            unknown.append(key)
            continue
        if cost < 0 or cost > 10_000_000:
            bad += 1
            continue
        if nm in seen:
            continue
        seen.add(nm)
        if nm in cur and abs(cur[nm] - cost) < 0.005:
            same += 1
            continue
        
        write.append((nm, round(cost, 2), valid_from if nm in has_any else FIRST))
    return {"write": write, "same": same, "unknown": len(unknown), "unknown_list": unknown[:20], "bad": bad, "total": len(items)}


def apply(c, shop: int, kind: str, items: list[tuple[str, float]], valid_from: date, source: str) -> dict:
    m = match(c, shop, kind, items, valid_from)
    for nm, cost, vf in m["write"]:
        c.execute("""INSERT INTO cost_price(account_id,nm_id,valid_from,cost,note) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (account_id,nm_id,valid_from) DO UPDATE SET cost=EXCLUDED.cost, note=EXCLUDED.note""",
                  (shop, nm, vf, cost, source[:200]))
    if m["write"]:
        from .materialize import mark_cost_dirty
        mark_cost_dirty(c, shop, min(vf for _, _, vf in m["write"]))
    return {"updated": len(m.pop("write")), **m}

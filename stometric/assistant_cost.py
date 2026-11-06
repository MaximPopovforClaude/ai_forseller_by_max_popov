"""Self-hosted application component."""

import io
import json
import re
from datetime import date

from . import auth, cost_import

TOOLS = [
    {"name": "propose_costs", "description": "Себестоимость из файла пользователя (xlsx/csv из этого чата): укажи, где артикул и где "
     "себестоимость — код прочитает ВСЕ строки, сопоставит с товарами магазина и создаст черновик с превью «было → станет». "
     "Ничего не записывает. Столбец — буква (A, B…) или текст заголовка. Артикул: nm — артикул WB / SKU Ozon (число), vc — артикул "
     "продавца, auto — попробовать оба.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string", "description": "имя файла; пусто — последняя таблица в чате"},
         "sheet": {"type": "string", "description": "название листа; пусто — первый, где найдутся столбцы"},
         "article_col": {"type": "string"}, "cost_col": {"type": "string"},
         "header_row": {"type": "integer", "description": "номер строки заголовков (с 1); 0 — заголовков нет"},
         "key": {"type": "string", "enum": ["nm", "vc", "auto"]},
         "valid_from": {"type": "string", "description": "дата начала действия ГГГГ-ММ-ДД; пусто — сегодня"},
         "shop_id": {"type": "integer"}}, "required": ["article_col", "cost_col"]}},
    {"name": "read_file", "description": "Прочитать таблицу пользователя (xlsx/csv из этого чата) дальше того, что видно во вложении: любой "
     "лист, строки с from_row по to_row (номера как в Excel) или только строки, где встречается текст find. За раз - до ~25 000 знаков; "
     "next_row в ответе - с какой строки читать дальше. Используй, когда нужен лист или строки, которых нет во вложении.",
     "input_schema": {"type": "object", "properties": {
         "file": {"type": "string", "description": "имя файла; пусто - последняя таблица в чате"},
         "sheet": {"type": "string", "description": "название листа; пусто - первый"},
         "from_row": {"type": "integer"}, "to_row": {"type": "integer"},
         "find": {"type": "string", "description": "только строки, где есть этот текст (без учёта регистра)"}}}},
]
MAX_COLS = 60


def fmt_row(n: int, row) -> str | None:
    """Строка таблицы для нейросети: «N: a | b | c» без пустого хвоста; пустая строка → None."""
    vals = ["" if v is None else str(v).strip() for v in list(row)[:MAX_COLS]]
    while vals and not vals[-1]:
        vals.pop()
    return f"{n}: " + " | ".join(vals) if vals else None

PROMPT = """
- Себестоимость: если пользователь прислал файл себестоимости (в любом виде) и просит её установить - посмотри начало файла,
  определи лист, столбец артикула и столбец себестоимости (закупка/себес/цена закупки и т.п.) и вызови propose_costs. Покажи итог
  черновика (сколько изменится, сколько не найдено, крупные изменения), назови номер черновика («черновик №N») и скажи, что
  записать его можно кнопкой «Применить» под таблицей. Сам ты ничего не записываешь и не меняешь в сервисе - у тебя только чтение.
  Если в файле несколько цен (опт/розница, с доставкой/без) - спроси, какую брать. Цены в валюте - не пересчитывай сам, спроси.
- Файлы пользователя (xlsx/csv): во вложении - список всех листов и начало каждого. Если нужен другой лист, строки дальше
  или поиск по файлу - читай инструментом read_file (можно несколько раз, по next_row). Не говори, что файл не читается,
  и не отвечай по части файла, будто это весь файл; посчитать по всем строкам - читай все строки."""


def _col(head: list[str], spec: str) -> int | None:
    s = (spec or "").strip()
    if re.fullmatch(r"[A-Za-z]{1,2}", s):
        n = 0
        for ch in s.upper():
            n = n * 26 + ord(ch) - 64
        return n - 1
    low = s.lower()
    for i, h in enumerate(head):
        if h == low:
            return i
    for i, h in enumerate(head):
        if low and low in h:
            return i
    return None


def _file(c, chat_id: int, name: str | None) -> dict:
    rows = c.execute("""SELECT * FROM assistant_files WHERE chat_id=%s AND message_id IS NOT NULL
                          AND (mime LIKE '%%sheet%%' OR mime IN ('text/csv','text/plain')) ORDER BY id DESC""", (chat_id,)).fetchall()
    if name:
        rows = [r for r in rows if name.lower() in r["name"].lower()] or rows
    if not rows:
        raise ValueError("в чате нет таблицы (xlsx/csv) - попроси пользователя прикрепить файл")
    return rows[0]


def _sheets(path, raw: bytes):
    if raw[:2] == b"PK":
        import openpyxl
        wb = cost_import.open_xlsx(io.BytesIO(raw))
        return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    return [("csv", cost_import._rows_of(raw, str(path))[0])]


def t_propose(c, shop: int, uid: int, a: dict) -> dict:
    from .assistant import files_dir
    from .config import today_msk
    f = _file(c, a["_chat_id"], a.get("file"))
    raw = (files_dir() / f["path"]).read_bytes()
    sheets = _sheets(f["path"], raw)
    if a.get("sheet"):
        sheets = [s for s in sheets if s[0].lower() == a["sheet"].lower()] or [s for s in sheets if a["sheet"].lower() in s[0].lower()] or sheets
    hr = a.get("header_row")
    found = None
    for title, rows in sheets:
        cands = [hr - 1] if hr else ([] if hr == 0 else range(min(30, len(rows))))
        for i in cands:
            head = [str(x or "").strip().lower() for x in rows[i]] if 0 <= i < len(rows) else []
            ai, ci = _col(head, a["article_col"]), _col(head, a["cost_col"])
            if ai is not None and ci is not None and ai != ci:
                found = (title, rows[i + 1:], ai, ci)
                break
        if hr == 0 and rows:
            ai, ci = _col([], a["article_col"]), _col([], a["cost_col"])
            if ai is not None and ci is not None:
                found = (title, rows, ai, ci)
        if found:
            break
    if not found:
        return {"error": "не нашёл указанные столбцы: укажи букву столбца (A, B…) или точный текст заголовка и номер строки заголовков"}
    title, body, ai, ci = found
    items, skipped = [], 0
    for r in body:
        key = r[ai] if ai < len(r) else None
        cost = cost_import._num(r[ci]) if ci < len(r) else None
        if key is None or str(key).strip() == "" or cost is None:
            skipped += 1
            continue
        k = cost_import._num(key)
        items.append((str(int(k)) if k is not None and float(k).is_integer() and k > 1000 else str(key).strip(), cost))
    if not items:
        return {"error": "в этих столбцах нет пар «артикул - число»"}
    vf = date.fromisoformat(a["valid_from"]) if a.get("valid_from") else today_msk()
    kinds = ["nm", "vc"] if a.get("key", "auto") == "auto" else [a["key"]]
    best = None
    for kind in kinds:      
        res = cost_import.match(c, shop, kind, items, vf)
        if best is None or len(res["write"]) + res["same"] > len(best[1]["write"]) + best[1]["same"]:
            best = (kind, res)
    kind, res = best
    if not len(res["write"]) + res["same"]:
        return {"error": f"ни один артикул из файла не нашёлся в магазине (примеры: {', '.join(k for k, _ in items[:5])}) - "
                         "проверь столбец артикула или магазин"}
    prev = _preview(c, shop, kind, items, vf)
    big = [p for p in prev if p["old"] and abs(p["new"] - p["old"]) / p["old"] > 0.3]
    return {"result": {"sheet": title, "by": "артикул WB / SKU" if kind == "nm" else "артикул продавца",
                       "rows_in_file": len(items) + skipped, "will_change": len(res["write"]), "same": res["same"],
                       "new_cost_for_empty": sum(1 for p in prev if p["old"] is None), "big_changes_over_30pct": len(big),
                       "not_found": res["unknown"], "not_found_examples": res["unknown_list"][:10], "bad_values": res["bad"],
                       "valid_from": str(vf), "how_to_apply": "пользователь нажимает «Применить» под таблицей черновика"},
            
            "draft": {"kind": kind, "items": items, "valid_from": vf, "source": f"Стометрик, файл {f['name'][:80]}"},
            "table": {"title": "Черновик себестоимости: что изменится",
                      "columns": [{"field": "vc", "title": "Артикул продавца", "type": "text"}, {"field": "nm", "title": "Артикул", "type": "int"},
                                  {"field": "old", "title": "Было, ₽", "type": "money"}, {"field": "new", "title": "Станет, ₽", "type": "money"},
                                  {"field": "ch", "title": "Изменение", "type": "text"}],
                      "rows": [{**p, "ch": f"{(p['new'] - p['old']) / p['old'] * 100:+.0f} %" if p["old"] else "новая"} for p in prev[:300]]}}


def save_draft(c, shop: int, uid: int, d: dict) -> int:
    """Черновик из propose_costs → cost_drafts (пишет сервис своим соединением). → номер черновика."""
    return c.execute("""INSERT INTO cost_drafts(account_id,user_id,kind,items,valid_from,source) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (shop, uid, d["kind"], json.dumps(d["items"]), d["valid_from"], d["source"])).fetchone()["id"]


def _preview(c, shop, kind, items, vf) -> list[dict]:
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    q = {"ozon": "SELECT sku nm_id, offer_id vendor_code FROM oz_products WHERE account_id=%s AND sku IS NOT NULL",
         "ym": "SELECT market_sku nm_id, offer_id vendor_code FROM ym_offers WHERE account_id=%s AND market_sku IS NOT NULL"}.get(
        mp, "SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s")
    nom = c.execute(q, (shop,)).fetchall()
    by_nm = {str(r["nm_id"]): r for r in nom}
    by_vc = {(r["vendor_code"] or "").lower(): r for r in nom}
    cur = {r["nm_id"]: float(r["cost"]) for r in c.execute(
        """SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%s AND valid_from <= %s ORDER BY nm_id, valid_from DESC""",
        (shop, vf))}
    out, seen = [], set()
    for k, cost in items:
        r = by_nm.get(k) if kind == "nm" else by_vc.get(k.lower())
        if not r or r["nm_id"] in seen:
            continue
        seen.add(r["nm_id"])
        old = cur.get(r["nm_id"])
        if old is not None and abs(old - cost) < 0.005:
            continue
        out.append({"nm": r["nm_id"], "vc": r["vendor_code"], "old": old, "new": round(cost, 2)})
    out.sort(key=lambda p: -(abs(p["new"] - p["old"]) / p["old"] if p["old"] else 0))
    return out


def apply_draft(c, shop: int, uid: int, draft_id: int) -> dict:
    """Кнопка «Применить» под черновиком (человек на сайте, роль «редактор» и выше) — запись себестоимости."""
    u = c.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    if not auth.can(auth.shop_role(c, u, shop), "editor"):
        raise PermissionError("Менять себестоимость может редактор или выше")
    d = c.execute("SELECT * FROM cost_drafts WHERE id=%s AND account_id=%s", (draft_id, shop)).fetchone()
    if not d:
        raise LookupError("Черновик не найден")
    if d["applied_at"]:
        raise LookupError(f"Черновик №{d['id']} уже применён")
    items = [tuple(x) for x in d["items"]]
    res = cost_import.apply(c, shop, d["kind"], items, d["valid_from"], f"{d['source']}: {u['email']}")
    c.execute("UPDATE cost_drafts SET applied_at=now() WHERE id=%s", (d["id"],))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) SELECT %s, workspace_id, 'cost', %s FROM accounts WHERE id=%s",
              (uid, json.dumps({"shop": shop, "draft": d["id"], "updated": res["updated"], "valid_from": str(d["valid_from"])}), shop))
    c.commit()
    return {"applied": True, "updated": res["updated"], "same": res["same"], "not_found": res["unknown"], "valid_from": str(d["valid_from"])}


def t_read(c, shop: int, uid: int, a: dict) -> dict:
    from .assistant import files_dir
    f = _file(c, a["_chat_id"], a.get("file"))
    sheets = _sheets(f["path"], (files_dir() / f["path"]).read_bytes())
    names = [t for t, _ in sheets]
    title, rows = sheets[0]
    if a.get("sheet"):
        low = a["sheet"].strip().lower()
        hit = [s for s in sheets if s[0].lower() == low] or [s for s in sheets if low in s[0].lower()]
        if not hit:
            return {"error": f"нет листа «{a['sheet']}»; листы: {names}"}
        title, rows = hit[0]
    lo = max(1, int(a.get("from_row") or 1))
    hi = min(len(rows), int(a.get("to_row") or len(rows)))
    find = (a.get("find") or "").strip().lower()
    out, size, nxt = [], 0, None
    for n in range(lo, hi + 1):
        ln = fmt_row(n, rows[n - 1])
        if not ln or (find and find not in ln.lower()):
            continue
        if size + len(ln) > 22000:
            nxt = n
            break
        out.append(ln)
        size += len(ln) + 1
    return {"result": {"file": f["name"], "sheet": title, "sheets": names, "rows_in_sheet": len(rows), "shown": len(out),
                       "next_row": nxt, "rows": "\n".join(out) or "(ничего не нашлось)"}}


TOOL_FN = {"propose_costs": t_propose, "read_file": t_read}

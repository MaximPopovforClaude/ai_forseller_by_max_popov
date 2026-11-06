"""Self-hosted application component."""

from .cost_import import NM_HEAD, VC_HEAD, CostImportError, _find, _num, _rows_of

STAFF_HEAD = ("менеджер", "ответственный", "manager", "сотрудник", "фио")
NONE = [0]       


def nms(c, shop: int, staff_id: int) -> list[int]:
    return [r["nm_id"] for r in c.execute("SELECT nm_id FROM staff_articles WHERE account_id=%s AND staff_id=%s", (shop, staff_id))]


def narrow(c, shop: int, staff_id: int | None, nm_ids: list[int] | None) -> list[int] | None:
    """Фильтр артикулов вкладки с учётом менеджера: его артикулы магазина (∩ выбранные вручную)."""
    if not staff_id:
        return nm_ids
    own = set(nms(c, shop, staff_id))
    out = sorted(own & set(nm_ids)) if nm_ids else sorted(own)
    return out or NONE


def mine(c, user_id: int) -> dict[int, list[int]]:
    """Артикулы пользователя как менеджера: {магазин: [nm_id]}."""
    out: dict[int, list[int]] = {}
    for r in c.execute("SELECT a.account_id, a.nm_id FROM staff s JOIN staff_articles a ON a.staff_id=s.id WHERE s.user_id=%s", (user_id,)):
        out.setdefault(r["account_id"], []).append(r["nm_id"])
    return out


def get_or_create(c, ws: int, name: str) -> int:
    name = " ".join(name.split())[:100]
    r = c.execute("SELECT id FROM staff WHERE workspace_id=%s AND lower(name)=lower(%s)", (ws, name)).fetchone()
    return r["id"] if r else c.execute("INSERT INTO staff(workspace_id,name) VALUES (%s,%s) RETURNING id", (ws, name)).fetchone()["id"]


def parse(raw: bytes, name: str) -> list[tuple[str, str, str]]:
    """Файл → [(вид ключа 'nm'|'vc', ключ, менеджер)]; пустой менеджер — снять назначение."""
    for rows in _rows_of(raw, name):
        for hi, row in enumerate(rows[:15]):
            cells = [str(x or "").strip().lower() for x in row]
            si = _find(cells, STAFF_HEAD)
            ni, vi = _find(cells, NM_HEAD), _find(cells, VC_HEAD)
            if si is None or (ni is None and vi is None):
                continue
            out = []
            for r in rows[hi + 1:]:
                who = str(r[si] or "").strip() if si < len(r) else ""
                if ni is not None and ni < len(r) and _num(r[ni]):
                    out.append(("nm", str(int(_num(r[ni]))), who))
                elif vi is not None and vi < len(r) and str(r[vi] or "").strip():
                    out.append(("vc", str(r[vi]).strip().lower(), who))
            if out:
                return out
    raise CostImportError("Не нашёл столбцы артикула (Артикул WB / SKU / Артикул продавца) и «Менеджер» в первых 15 строках листов")


def match(c, shops: list[dict], items: list[tuple[str, str, str]]) -> dict:
    """Только чтение: что назначится. Артикул продавца может быть в нескольких магазинах — назначаем во всех."""
    by_nm, by_vc = {}, {}
    for s in shops:
        if s["marketplace"] == "ozon":
            q = c.execute("SELECT sku nm_id, offer_id vc FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (s["id"],))
        else:
            q = c.execute("SELECT nm_id, vendor_code vc FROM nomenclature WHERE account_id=%s", (s["id"],))
        for r in q:
            by_nm.setdefault(str(r["nm_id"]), []).append((s["id"], r["nm_id"]))
            if r["vc"]:
                by_vc.setdefault(r["vc"].lower(), []).append((s["id"], r["nm_id"]))
    cur = {(r["account_id"], r["nm_id"]): r["name"] for r in c.execute(
        "SELECT a.account_id, a.nm_id, s.name FROM staff_articles a JOIN staff s ON s.id=a.staff_id WHERE a.account_id = ANY(%s)",
        ([s["id"] for s in shops],))}
    canon = {r["name"].lower(): r["name"] for r in c.execute("SELECT name FROM staff WHERE workspace_id = ANY(%s)",
                                                              (list({s["workspace_id"] for s in shops}),))}
    write, unknown, same, seen = [], [], 0, set()
    for kind, key, who in items:
        who = " ".join(who.split())[:100]
        who = canon.setdefault(who.lower(), who) if who else ""       
        hits = (by_nm if kind == "nm" else by_vc).get(key)
        if not hits:
            unknown.append(key)
            continue
        for k in hits:
            if k in seen:
                continue
            seen.add(k)
            if (cur.get(k) or "").lower() == who.lower():
                same += 1
            else:
                write.append((*k, who))
    names = sorted({w for *_, w in write if w})
    return {"write": write, "same": same, "unknown": len(unknown), "unknown_list": unknown[:20], "total": len(items),
            "staff": names, "by_staff": {n: sum(1 for *_, w in write if w == n) for n in names},
            "clear": sum(1 for *_, w in write if not w)}


def apply(c, ws: int, write: list[tuple[int, int, str]]) -> None:
    ids: dict[str, int] = {}
    for shop, nm, who in write:
        if not who:
            c.execute("DELETE FROM staff_articles WHERE account_id=%s AND nm_id=%s", (shop, nm))
            continue
        sid = ids.get(who.lower()) or ids.setdefault(who.lower(), get_or_create(c, ws, who))
        c.execute("""INSERT INTO staff_articles(account_id,nm_id,staff_id) VALUES (%s,%s,%s)
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET staff_id=EXCLUDED.staff_id, updated_at=now()""", (shop, nm, sid))

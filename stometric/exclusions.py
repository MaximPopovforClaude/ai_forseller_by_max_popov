"""Артикулы «не в работе»: отключённые в настройках магазина артикулы, бренды и предметы (по умолчанию включено всё)."""

_CACHE: dict[int, tuple] = {}


def excluded(c, shop: int) -> set[int]:
    """Множество отключённых nm_id магазина (артикулы напрямую + все артикулы отключённых брендов и предметов)."""
    ver = c.execute("SELECT count(*) n, coalesce(max(added_at)::text, '') t FROM shop_exclusions WHERE account_id=%s", (shop,)).fetchone()
    key = (ver["n"], ver["t"])
    hit = _CACHE.get(shop)
    if hit and hit[0] == key:
        return hit[1]
    if not ver["n"]:
        res: set[int] = set()
    else:
        res = {r["nm_id"] for r in c.execute(
            """SELECT n.nm_id FROM nomenclature n WHERE n.account_id=%(a)s AND (
                 n.nm_id::text IN (SELECT value FROM shop_exclusions WHERE account_id=%(a)s AND kind='nm')
                 OR coalesce(n.brand,'') IN (SELECT value FROM shop_exclusions WHERE account_id=%(a)s AND kind='brand')
                 OR coalesce(n.subject,'') IN (SELECT value FROM shop_exclusions WHERE account_id=%(a)s AND kind='subject'))""", {"a": shop})}
        res |= {int(r["value"]) for r in c.execute("SELECT value FROM shop_exclusions WHERE account_id=%s AND kind='nm'", (shop,))
                if r["value"].isdigit()}
    _CACHE[shop] = (key, res)
    return res


def drop(rows: list, ex: set[int], key: str = "nm_id") -> list:
    if not ex:
        return rows
    return [r for r in rows if r.get(key) not in ex]

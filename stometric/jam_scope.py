"""Fresh shop work selection for Jam requests; no process-local exclusion cache."""

                                                                                 
IN_WORK = """NOT EXISTS (SELECT 1 FROM shop_exclusions x
    WHERE x.account_id=n.account_id AND (
      (x.kind='nm' AND x.value=n.nm_id::text)
      OR (x.kind='brand' AND x.value=coalesce(n.brand,''))
      OR (x.kind='subject' AND x.value=coalesce(n.subject,''))))"""
NOT_IN_WORK = 'Товар не выбран в «Артикулах в работе». Джем для него не загружается.'


class NotInWork(ValueError):
    pass


def in_work_ids(c, shop, nm_ids):
    """Intersect with the current owned catalog, preserving caller order."""
    requested = list(nm_ids)
    if any(type(nm) is not int or not 0 < nm < 2**63 for nm in requested):
        raise ValueError('jam_invalid_sku')
    requested = list(dict.fromkeys(requested))
    if not requested:
        return []
    found = {r['nm_id'] for r in c.execute(
        'SELECT n.nm_id FROM nomenclature n WHERE n.account_id=%s '
        'AND n.nm_id=ANY(%s::bigint[]) AND ' + IN_WORK, (shop, requested))}
    return [nm for nm in requested if nm in found]


def require(c, shop, nm):
    if not in_work_ids(c, shop, [nm]):
        raise NotInWork(NOT_IN_WORK)

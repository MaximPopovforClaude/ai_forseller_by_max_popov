"""Self-hosted application component."""


def view(c, shop: int) -> dict:
    rows = c.execute(
        """WITH lp AS (SELECT DISTINCT ON (nm_id) nm_id, discounted_price FROM prices_snap WHERE account_id=%(a)s ORDER BY nm_id, snap_at DESC, size_id)
           SELECT n.nm_id, n.vendor_code, n.title, n.subject, n.brand, n.data->'photos'->0->>'tm' AS photo, lp.discounted_price seller_price,
                  s.price shown, s.spp, s.checked_at, m.mrc, m.note, m.updated_at, coalesce(u.name, u.email) who
           FROM nomenclature n LEFT JOIN lp USING (nm_id)
           LEFT JOIN wb_showcase s ON s.account_id=n.account_id AND s.nm_id=n.nm_id
           LEFT JOIN mrc_items m ON m.account_id=n.account_id AND m.nm_id=n.nm_id
           LEFT JOIN users u ON u.id=m.updated_by
           WHERE n.account_id=%(a)s ORDER BY m.mrc IS NULL, n.vendor_code""", {"a": shop}).fetchall()
    from .exclusions import excluded
    ex = excluded(c, shop)
    return {"rows": [dict(r) for r in rows if r["nm_id"] not in ex or r["mrc"] is not None]}


def save(c, shop: int, uid: int, items: list[dict]) -> tuple[int, int]:
    """items: [{nm_id, mrc (пусто — убрать), note}] → (задано, убрано). Артикулы — только этого магазина."""
    own = {r["nm_id"] for r in c.execute("SELECT nm_id FROM nomenclature WHERE account_id=%s", (shop,))}
    put = gone = 0
    for it in items:
        nm = int(it["nm_id"])
        if nm not in own:
            raise ValueError(f"Артикул {nm} не из этого магазина")
        v = it.get("mrc")
        if v in (None, "", 0):
            gone += c.execute("DELETE FROM mrc_items WHERE account_id=%s AND nm_id=%s", (shop, nm)).rowcount
            continue
        v = float(v)
        if not 0 < v < 10_000_000:
            raise ValueError(f"МРЦ {v:g} для {nm} — не похожа на цену")
        c.execute("""INSERT INTO mrc_items(account_id,nm_id,mrc,note,updated_by) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET mrc=EXCLUDED.mrc, note=coalesce(EXCLUDED.note, mrc_items.note),
                       updated_by=EXCLUDED.updated_by, updated_at=now()""", (shop, nm, v, (it.get("note") or None), uid))
        put += 1
    return put, gone


def lookup(c, pairs: set[tuple[int, int]]) -> dict[tuple[int, int], dict]:
    """(магазин, артикул) → {subject, mrc} для уведомлений: категория (предмет WB / категория Ozon) и МРЦ, если задана."""
    if not pairs:
        return {}
    accs, nms = [a for a, _ in pairs], [n for _, n in pairs]
    out = {}
    for r in c.execute("""SELECT p.a, p.n, n.subject, m.mrc FROM unnest(%s::int[], %s::bigint[]) p(a, n)
                          LEFT JOIN nomenclature n ON n.account_id=p.a AND n.nm_id=p.n
                          LEFT JOIN mrc_items m ON m.account_id=p.a AND m.nm_id=p.n""", (accs, nms)):
        out[(r["a"], r["n"])] = {"subject": r["subject"], "mrc": float(r["mrc"]) if r["mrc"] is not None else None}
    return out

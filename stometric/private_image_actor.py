"""Personal images belong only to the configured owner and selected own shops."""


def allowed(c, shop: int, uid: int | None) -> bool:
    if c is None:
        return False
    from .owner_ai import allowed as owner_allowed
    return owner_allowed(c, shop, uid)

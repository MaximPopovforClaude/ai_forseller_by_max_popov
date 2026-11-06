"""Compatibility boundary: no subscription credentials or special shop IDs."""
from contextlib import contextmanager


@contextmanager
def scheduled_ai(c):
    previous = getattr(c, '_ai_trusted_scheduled', False)
    c._ai_trusted_scheduled = True
    try:
        yield c
    finally:
        c._ai_trusted_scheduled = previous


def require_owner_shop(c, shop_id, actor_id=None, *, trusted_scheduled=False):
    from fastapi import HTTPException
    from .ai_routing import shop_route
    if actor_id is None and trusted_scheduled:
        with scheduled_ai(c):
            ready = shop_route(c, shop_id)['ai_ready']
    else:
        ready = shop_route(c, shop_id, actor_id)['ai_ready']
    if not ready:
        raise HTTPException(403, 'Нужен API-ключ аккаунта и действующее право на магазин.')

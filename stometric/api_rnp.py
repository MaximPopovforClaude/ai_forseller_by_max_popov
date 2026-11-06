"""API вкладки «РНП» (Version2 WB): блоки итога и артикулов за месяц, сортировка, фильтры, постранично."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from . import auth, rnp
from .web import conn, current_user

router = APIRouter()


@router.get("/api/shops/{shop_id}/rnp")
def rnp_get(shop_id: int, month: str = "", sort: str = "orders_sum", offset: int = 0, group: str = "", brand: str = "", subject: str = "",
            nm_ids: str = "", staff: int | None = None, u=Depends(current_user), c=Depends(conn)):
    if not auth.can(auth.shop_role(c, u, shop_id), "viewer"):
        raise HTTPException(403, "Нет доступа к магазину")
    if c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop_id,)).fetchone()["marketplace"] not in ("wb", "ym", "ozon"):
        raise HTTPException(400, "РНП для этой площадки пока нет")
    try:
        m = date.fromisoformat(month + "-01") if month else rnp.today_msk().replace(day=1)
    except ValueError:
        raise HTTPException(400, "Месяц в формате ГГГГ-ММ") from None
    flt = {"group": group or None, "brand": brand or None, "subject": subject or None,
           "nm_ids": [int(x) for x in nm_ids.split(",") if x.strip().isdigit()] or None}
    if staff:                                   
        from . import staff as _staff
        flt["nm_ids"] = _staff.narrow(c, shop_id, staff, flt["nm_ids"])
    import psycopg
    from .materialize import NotReady
    try:
        from . import tabcache
        params = {"month": m.isoformat(), "sort": sort, "offset": max(0, offset), **flt}
        return jsonable_encoder(tabcache.get(c, shop_id, "rnp_api", params, lambda cc: rnp.compute(cc, shop_id, m, flt, sort, max(0, offset))))
    except (NotReady, psycopg.errors.QueryCanceled) as e:
        c.rollback()
        return {"error": str(e) if isinstance(e, NotReady) else "В связи с большим объёмом артикулов расчёт не уложился в минуту — "
                "выберите бренд, предмет или группу."}

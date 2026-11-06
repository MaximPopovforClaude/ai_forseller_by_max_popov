"""История изменений карточек и цен (дорожная карта п.4): сравниваем новое состояние с прошлым и пишем разницу в card_changes."""

import json

CONTENT_FIELDS = ["vendorCode", "brand", "title", "description", "subjectID", "subjectName", "video", "imtID"]


def _photos(card):
    return [p.get("big") or p.get("c516x688") or p.get("tm") for p in card.get("photos") or []]


def _chars(card):
    return {str(ch.get("name")): ch.get("value") for ch in card.get("characteristics") or []}


def _sizes(card):
    return sorted([[s.get("techSize"), s.get("wbSize"), sorted(s.get("skus") or [])] for s in card.get("sizes") or []])


def _add(c, acc_id, nm, kind, field, old, new, wb_upd=None):
    c.execute("INSERT INTO card_changes(account_id,nm_id,kind,field,old_value,new_value,wb_updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
              (acc_id, nm, kind, field, json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False), wb_upd))


def card_diff(c, acc_id: int, old: dict | None, new: dict) -> int:
    """old — прошлое data карточки (None — новая карточка: фиксируем появление)."""
    nm, upd = new["nmID"], new.get("updatedAt")
    if old is None:
        _add(c, acc_id, nm, "content", "created", None, {"title": new.get("title"), "vendorCode": new.get("vendorCode")}, upd)
        return 1
    n = 0
    for f in CONTENT_FIELDS:
        if old.get(f) != new.get(f):
            _add(c, acc_id, nm, "content", f, old.get(f), new.get(f), upd); n += 1
    if _photos(old) != _photos(new):
        _add(c, acc_id, nm, "photo", "photos", _photos(old), _photos(new), upd); n += 1
    oc, nc = _chars(old), _chars(new)
    for k in sorted(set(oc) | set(nc)):
        if oc.get(k) != nc.get(k):
            _add(c, acc_id, nm, "content", f"characteristics:{k}", oc.get(k), nc.get(k), upd); n += 1
    if old.get("dimensions") != new.get("dimensions"):
        _add(c, acc_id, nm, "content", "dimensions", old.get("dimensions"), new.get("dimensions"), upd); n += 1
    if _sizes(old) != _sizes(new):
        _add(c, acc_id, nm, "size", "sizes", _sizes(old), _sizes(new), upd); n += 1
    return n


def price_diff(c, acc_id: int, snap_at) -> int:
    """Сравнить снимок цен snap_at с предыдущим снимком: цена, скидка, итоговая цена по каждому размеру."""
    rows = c.execute(
        """WITH prev AS (SELECT max(snap_at) t FROM prices_snap WHERE account_id=%(a)s AND snap_at < %(s)s)
           SELECT n.nm_id, n.size_id, p.price op, n.price np, p.discount od, n.discount nd,
                  p.discounted_price odp, n.discounted_price ndp
           FROM prices_snap n JOIN prev ON true
           JOIN prices_snap p ON p.account_id=n.account_id AND p.snap_at=prev.t AND p.nm_id=n.nm_id AND p.size_id=n.size_id
           WHERE n.account_id=%(a)s AND n.snap_at=%(s)s
             AND (p.price IS DISTINCT FROM n.price OR p.discount IS DISTINCT FROM n.discount)""",
        {"a": acc_id, "s": snap_at}).fetchall()
    for r in rows:
        _add(c, acc_id, r["nm_id"], "price", f"price:{r['size_id']}",
             {"price": float(r["op"] or 0), "discount": float(r["od"] or 0), "final": float(r["odp"] or 0)},
             {"price": float(r["np"] or 0), "discount": float(r["nd"] or 0), "final": float(r["ndp"] or 0)})
    return len(rows)


AD_STATUS = {4: "готова к запуску", 7: "завершена", 8: "отменена", 9: "идёт", 11: "на паузе", -1: "удалена"}


def _ad_nms(info: dict | None) -> dict[int, dict]:
    return {int(x["nm_id"]): x.get("bids_kopecks") or {} for x in ((info or {}).get("nm_settings") or []) if x.get("nm_id")}


def ad_diff(c, acc_id: int, old: dict | None, new: dict) -> int:
    """Реклама: запуск/пауза/завершение кампании и смена ставок — в журнал по каждому артикулу кампании (old=None — новая кампания)."""
    nms_new = _ad_nms(new.get("info"))
    name = ((new.get("info") or {}).get("settings") or {}).get("name") or str(new.get("advertId"))
    n = 0
    if old is None:
        for nm in nms_new:
            _add(c, acc_id, nm, "ad_status", f"ad:{new['advertId']}", None, {"campaign": name, "status": AD_STATUS.get(new.get("status"), new.get("status"))})
            n += 1
        return n
    if old.get("status") != new.get("status"):
        for nm in nms_new or _ad_nms(old.get("info")):
            _add(c, acc_id, nm, "ad_status", f"ad:{new['advertId']}",
                 {"campaign": name, "status": AD_STATUS.get(old.get("status"), old.get("status"))},
                 {"campaign": name, "status": AD_STATUS.get(new.get("status"), new.get("status"))})
            n += 1
    nms_old = _ad_nms(old.get("info"))
    for nm, bids in nms_new.items():
        ob = nms_old.get(nm)
        if ob is not None and ob != bids:
            rub = lambda b: {k: round((v or 0) / 100, 2) for k, v in b.items()}  
            _add(c, acc_id, nm, "ad_bid", f"ad:{new['advertId']}", {"campaign": name, **rub(ob)}, {"campaign": name, **rub(bids)})
            n += 1
    return n



OZ_AD_STATE = {"CAMPAIGN_STATE_RUNNING": "активна", "CAMPAIGN_STATE_STOPPED": "остановлена", "CAMPAIGN_STATE_INACTIVE": "неактивна",
               "CAMPAIGN_STATE_ARCHIVED": "в архиве", "CAMPAIGN_STATE_PLANNED": "запланирована", "CAMPAIGN_STATE_FINISHED": "завершена",
               "CAMPAIGN_STATE_MODERATION_DRAFT": "черновик", "CAMPAIGN_STATE_MODERATION_IN_PROGRESS": "на модерации",
               "CAMPAIGN_STATE_MODERATION_FAILED": "не прошла модерацию"}


def _oz_add(c, acc_id, sku, kind, field, old, new):
    c.execute("INSERT INTO card_changes(account_id,nm_id,kind,field,old_value,new_value,source) VALUES (%s,%s,%s,%s,%s,%s,'ozon')",
              (acc_id, sku, kind, field, json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)))


def _oz_photos(it):
    img = it.get("primary_image")
    main = (img[0] if isinstance(img, list) and img else img) or None
    rest = [x for x in it.get("images") or [] if x != main]
    return ([main] if main else []) + rest


def oz_card_diff(c, acc_id: int, sku: int | None, old: dict | None, new: dict) -> int:
    """Карточка Ozon (/v3/product/info/list): название, фото, архив. old=None — новая карточка (фиксируем появление)."""
    if not sku:
        return 0
    if old is None:
        _oz_add(c, acc_id, sku, "content", "created", None, {"title": new.get("name"), "vendorCode": new.get("offer_id")})
        return 1
    n = 0
    if old.get("name") != new.get("name"):
        _oz_add(c, acc_id, sku, "content", "title", old.get("name"), new.get("name")); n += 1
    if old.get("offer_id") != new.get("offer_id"):
        _oz_add(c, acc_id, sku, "content", "vendorCode", old.get("offer_id"), new.get("offer_id")); n += 1
    if _oz_photos(old) != _oz_photos(new):
        _oz_add(c, acc_id, sku, "photo", "photos", _oz_photos(old), _oz_photos(new)); n += 1
    oa, na = bool(old.get("is_archived") or old.get("is_autoarchived")), bool(new.get("is_archived") or new.get("is_autoarchived"))
    if oa != na:
        _oz_add(c, acc_id, sku, "content", "archived", oa, na); n += 1
    return n


def _oz_price(p: dict) -> dict:
    pr, old = float(p.get("price") or 0), float(p.get("old_price") or 0)
    return {"final": pr, "price": old, "discount": round((1 - pr / old) * 100) if old > pr > 0 else 0}


def oz_price_diff(c, acc_id: int, sku: int | None, old: dict | None, new: dict) -> int:
    """Цена Ozon (/v5/product/info/prices): цена продавца, цена до скидки, цена с акциями Ozon (marketing_price)."""
    if not sku or old is None:
        return 0
    n = 0
    o, w = _oz_price(old.get("price") or {}), _oz_price(new.get("price") or {})
    if (o["final"], o["price"]) != (w["final"], w["price"]):
        _oz_add(c, acc_id, sku, "price", "price", o, w); n += 1
    om, nm = (old.get("price") or {}).get("marketing_price"), (new.get("price") or {}).get("marketing_price")
    if om is not None and nm is not None and float(om) != float(nm):
        _oz_add(c, acc_id, sku, "price", "marketing_price", {"final": float(om)}, {"final": float(nm)}); n += 1
    return n


def oz_ad_diff(c, acc_id: int, old: dict | None, new: dict, skus: list[int] | None) -> int:
    """Кампания Performance: запуск/остановка/архив — в журнал по каждому SKU кампании (old=None — новая)."""
    name = new.get("title") or str(new.get("id"))
    st = lambda x: OZ_AD_STATE.get(x.get("state"), x.get("state"))  
    if old is not None and old.get("state") == new.get("state"):
        return 0
    for sku in skus or []:
        _oz_add(c, acc_id, sku, "ad_status", f"ad:{new.get('id')}", {"campaign": name, "status": st(old)} if old else None,
                {"campaign": name, "status": st(new)})
    return len(skus or [])

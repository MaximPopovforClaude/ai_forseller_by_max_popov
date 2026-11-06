"""Сборщики Яндекс Маркет Partner API. Каждый: run(ctx) → dict-итог; состояние — в collector_state (как у WB/Ozon), сырьё — raw jsonb в ym_*.

Поля ответов разбираем осторожно (.get): что не распознали — остаётся в raw, расчёт не ломается.
Покупателей не храним (152-ФЗ): из заказа — только товары, цены, статус, услуги Маркета, регион и платежи (суммы и даты).
"""

import json
from datetime import date, datetime, timedelta, timezone

from .collectors import Ctx, _run
from .config import today_msk
from .ym import YM

MSK = timezone(timedelta(hours=3))
HISTORY_DAYS = 120          
REFRESH_DAYS = 3            
TAIL_DAYS = 45              


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ts(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=MSK)
    except ValueError:
        return None


def campaigns(c, acc_id: int) -> list[dict]:
    return c.execute("SELECT campaign_id, placement FROM ym_campaigns WHERE account_id=%s AND coalesce(api_status,'AVAILABLE')='AVAILABLE' "
                     "ORDER BY campaign_id", (acc_id,)).fetchall()



def run_campaigns(ctx: Ctx) -> dict:
    ym: YM = ctx.wb
    n = 0
    for x in ym.pages("GET", "/v2/campaigns", None, lambda r: r.get("campaigns"), limit=50):
        if int((x.get("business") or {}).get("id") or 0) != ym.business:
            continue
        ctx.c.execute("""INSERT INTO ym_campaigns(account_id,campaign_id,domain,placement,api_status,raw,updated_at) VALUES (%s,%s,%s,%s,%s,%s,now())
                         ON CONFLICT (account_id,campaign_id) DO UPDATE SET domain=EXCLUDED.domain, placement=EXCLUDED.placement,
                         api_status=EXCLUDED.api_status, raw=EXCLUDED.raw, updated_at=now()""",
                      (ctx.acc["id"], x.get("id"), x.get("domain"), x.get("placementType"), x.get("apiAvailability"),
                       json.dumps(x, ensure_ascii=False)))
        n += 1
    ctx.c.commit()
    
    def wh(x, own):
        a = x.get("address") or {}
        ctx.c.execute("""INSERT INTO ym_warehouses(warehouse_id,name,city,own,updated_at) VALUES (%s,%s,%s,%s,now())
                         ON CONFLICT (warehouse_id) DO UPDATE SET name=EXCLUDED.name, city=EXCLUDED.city, own=EXCLUDED.own, updated_at=now()""",
                      (x.get("id"), x.get("name"), a.get("city"), own))
    for x in (ym.call("GET", "/v2/warehouses").get("result") or {}).get("warehouses") or []:
        wh(x, False)
    r = ym.call("GET", f"/v2/businesses/{ym.business}/warehouses").get("result") or {}
    for x in r.get("warehouses") or []:
        wh(x, True)
    for g in r.get("warehouseGroups") or []:
        for x in [g.get("mainWarehouse") or {}] + (g.get("warehouses") or []):
            if x.get("id"):
                wh(x, True)
    ctx.c.commit()
    return {"rows": n}



def run_offers(ctx: Ctx) -> dict:
    ym: YM = ctx.wb
    n = 0
    for archived in (False, True):
        for m in ym.pages("POST", f"/v2/businesses/{ym.business}/offer-mappings", {"archived": archived},
                          lambda r: r.get("offerMappings"), limit=200):
            o, mp = m.get("offer") or {}, m.get("mapping") or {}
            if not o.get("offerId"):
                continue
            pics = o.get("pictures") or []
            cat = o.get("category")
            cat = cat.get("name") if isinstance(cat, dict) else cat
            ctx.c.execute(
                """INSERT INTO ym_offers(account_id,offer_id,market_sku,name,vendor,category,photo,barcodes,archived,card_status,raw,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (account_id,offer_id) DO UPDATE SET market_sku=coalesce(EXCLUDED.market_sku, ym_offers.market_sku), name=EXCLUDED.name,
                   vendor=EXCLUDED.vendor, category=EXCLUDED.category, photo=EXCLUDED.photo, barcodes=EXCLUDED.barcodes,
                   archived=EXCLUDED.archived, card_status=EXCLUDED.card_status, raw=EXCLUDED.raw, updated_at=now()""",
                (ctx.acc["id"], o["offerId"], mp.get("marketSku"), o.get("name"), o.get("vendor"), cat, pics[0] if pics else None,
                 o.get("barcodes") or [], archived or bool(o.get("archived")), o.get("cardStatus"), json.dumps(m, ensure_ascii=False)))
            n += 1
        ctx.c.commit()
    return {"rows": n}



def run_prices(ctx: Ctx) -> dict:
    ym: YM = ctx.wb
    n = 0
    for x in ym.pages("POST", f"/v2/businesses/{ym.business}/offer-prices", {}, lambda r: r.get("offers"), limit=200):
        p = x.get("price") or {}
        if not x.get("offerId"):
            continue
        ctx.c.execute("""INSERT INTO ym_prices(account_id,offer_id,price,old_price,updated,raw,updated_at) VALUES (%s,%s,%s,%s,%s,%s,now())
                         ON CONFLICT (account_id,offer_id) DO UPDATE SET price=EXCLUDED.price, old_price=EXCLUDED.old_price, updated=EXCLUDED.updated,
                         raw=EXCLUDED.raw, updated_at=now()""",
                      (ctx.acc["id"], x["offerId"], _f(p.get("value")), _f(p.get("discountBase")), _ts(p.get("updatedAt")),
                       json.dumps(x, ensure_ascii=False)))
        n += 1
    ctx.c.commit()
    return {"rows": n}



def run_stocks(ctx: Ctx) -> dict:
    ym: YM = ctx.wb
    snap = datetime.now(timezone.utc)
    n = 0
    for cp in campaigns(ctx.c, ctx.acc["id"]):
        for w in ym.pages("POST", f"/v2/campaigns/{cp['campaign_id']}/offers/stocks", {}, lambda r: r.get("warehouses"), limit=200):
            for o in w.get("offers") or []:
                st = {}
                for s in o.get("stocks") or []:
                    st[s.get("type")] = st.get(s.get("type"), 0) + (_f(s.get("count")) or 0)
                fit = st.get("FIT", 0)
                avail = st["AVAILABLE"] if "AVAILABLE" in st else max(0, fit - st.get("FREEZE", 0))
                other = sum(v for k, v in st.items() if k not in ("FIT", "AVAILABLE"))
                ctx.c.execute("""INSERT INTO ym_stocks(account_id,snap_at,campaign_id,placement,warehouse_id,offer_id,available,fit,other,raw)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                              (ctx.acc["id"], snap, cp["campaign_id"], cp["placement"], w.get("warehouseId"), o.get("offerId"), avail, fit, other,
                               json.dumps(o, ensure_ascii=False)))
                n += 1
        ctx.c.commit()
    ctx.c.execute("DELETE FROM ym_stocks WHERE account_id=%s AND snap_at < now() - interval '35 days'", (ctx.acc["id"],))
    ctx.c.commit()
    return {"rows": n}



def _save_order(ctx, cp: dict, o: dict) -> int:
    created = o.get("creationDate")
    try:
        day = date.fromisoformat(str(created)[:10])
    except ValueError:
        return 0
    st_at = _ts(o.get("statusUpdateDate"))
    comm = {}
    for x in o.get("commissions") or []:
        comm[x.get("type") or "?"] = round(comm.get(x.get("type") or "?", 0) + (_f(x.get("actual")) or 0), 2)
    sub = sum((_f(x.get("amount")) or 0) * (-1 if x.get("operationType") == "DEDUCTION" else 1) for x in o.get("subsidies") or [])
    pays = [{"date": x.get("date"), "type": x.get("type"), "source": x.get("source"), "total": _f(x.get("total"))} for x in o.get("payments") or []]
    raw = {k: v for k, v in o.items() if k not in ("buyer", "delivery", "address")}
    ctx.c.execute(
        """INSERT INTO ym_orders(account_id,order_id,campaign_id,placement,order_day,status,status_at,status_day,region,payment_type,fake,
                                 commission,comm,subsidy,payments,raw,updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
           ON CONFLICT (account_id,order_id) DO UPDATE SET status=EXCLUDED.status, status_at=EXCLUDED.status_at, status_day=EXCLUDED.status_day,
           region=EXCLUDED.region, payment_type=EXCLUDED.payment_type, fake=EXCLUDED.fake, commission=EXCLUDED.commission, comm=EXCLUDED.comm,
           subsidy=EXCLUDED.subsidy, payments=EXCLUDED.payments, raw=EXCLUDED.raw, updated_at=now()""",
        (ctx.acc["id"], o.get("id"), cp["campaign_id"], cp["placement"], day, o.get("status"), st_at,
         st_at.astimezone(MSK).date() if st_at else None, (o.get("deliveryRegion") or {}).get("name"), o.get("paymentType"),
         bool(o.get("fake")), round(sum(comm.values()), 2), json.dumps(comm), round(sub, 2), json.dumps(pays), json.dumps(raw, ensure_ascii=False)))
    ctx.c.execute("DELETE FROM ym_order_items WHERE account_id=%s AND order_id=%s", (ctx.acc["id"], o.get("id")))
    init = {}
    for it in o.get("initialItems") or []:
        k = it.get("shopSku") or it.get("marketSku")
        init[k] = init.get(k, 0) + int(it.get("initialCount") or it.get("count") or 0)
    for i, it in enumerate(o.get("items") or []):
        if it.get("shopServiceType"):
            continue                    
        pr = {p.get("type"): p for p in it.get("prices") or []}
        qty = int(it.get("count") or 0)
        k = it.get("shopSku") or it.get("marketSku")
        ctx.c.execute(
            """INSERT INTO ym_order_items(account_id,order_id,line,offer_id,market_sku,name,initial_qty,qty,price,buyer_total,cashback,coupons,cofinance,warehouse)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (ctx.acc["id"], o.get("id"), i, it.get("shopSku"), it.get("marketSku"), it.get("offerName"),
             int(it.get("initialCount") or init.pop(k, 0) or qty), qty, _f((pr.get("BUYER") or {}).get("costPerItem")),
             _f((pr.get("BUYER") or {}).get("total")), _f((pr.get("CASHBACK") or {}).get("total")), _f((pr.get("MARKETPLACE") or {}).get("total")),
             _f(it.get("cofinanceValue")), (it.get("warehouse") or {}).get("name")))
    return 1


def _windows(since: date, until: date, days: int):
    d = since
    while d <= until:
        e = min(until, d + timedelta(days=days - 1))
        yield d, e
        d = e + timedelta(days=1)


def run_orders(ctx: Ctx) -> dict:
    """/v2/campaigns/{id}/stats/orders по каждому магазину кабинета. Первая загрузка — по дате заказа за HISTORY_DAYS;
    дальше — по дате изменения: последние REFRESH_DAYS каждый круг и TAIL_DAYS раз в TAIL_HOURS."""
    ym: YM = ctx.wb
    st = ctx.state("ym_orders")
    today = today_msk()
    first = not st.get("loaded")
    full, tail_at = (False, None) if first else ctx.tail("ym_orders")
    n = 0
    for cp in campaigns(ctx.c, ctx.acc["id"]):
        if first:
            wins = [({"dateFrom": a.isoformat(), "dateTo": b.isoformat()}) for a, b in
                    _windows(today - timedelta(days=ctx.depth(HISTORY_DAYS)), today, 30)]
        else:
            a = today - timedelta(days=TAIL_DAYS if full else REFRESH_DAYS)
            wins = [{"updateFrom": a.isoformat(), "updateTo": (today + timedelta(days=1)).isoformat()}]
        for body in wins:
            k = 0
            for o in ym.pages("POST", f"/v2/campaigns/{cp['campaign_id']}/stats/orders", body, lambda r: r.get("orders"), limit=200):
                n += _save_order(ctx, cp, o)
                k += 1
                if k % 200 == 0:
                    ctx.c.commit()
            ctx.c.commit()
    return {"rows": n, "cursor": {"loaded": True, "tail_at": tail_at if not first else datetime.now(timezone.utc).isoformat()}}



NET_DAYS = 20               
NET_TAIL_DAYS = 92          


def net_kind(source: str) -> str:
    s = (source or "").lower()
    if "платеж" in s.replace("ё", "е") and "покупател" in s:
        return "buyer"
    if "балл" in s:
        return "points"
    if "совместных акциях" in s:
        return "serv_pts"               
    if "услуг" in s:
        return "serv"
    return "other"


def _report(ym: YM, kind: str, body: dict, wait_s: int = 900) -> bytes | None:
    import time
    import httpx
    r = ym.call("POST", f"/v2/reports/{kind}/generate", body, {"format": "CSV"})
    rid = r["result"]["reportId"]
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(15)
        st = ym.call("GET", f"/v2/reports/info/{rid}")["result"]
        if st.get("status") == "FAILED":
            raise RuntimeError(f"отчёт {kind}: Маркет не смог его построить ({st.get('subStatus')})")
        if st.get("status") == "DONE":
            if not st.get("file"):
                return None             
            return httpx.get(st["file"], timeout=300, follow_redirects=True).content
    raise RuntimeError(f"отчёт {kind}: Маркет строит дольше {wait_s // 60} мин — заберём в следующий круг")


def _netting_rows(raw: bytes):
    import csv
    import io
    import zipfile
    data = raw
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        data = z.read(next(n for n in z.namelist() if n.endswith(".csv")))
    agg = {}
    for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        try:
            d = datetime.strptime(r["TRANSACTION_DATE"][:10], "%d.%m.%Y").date()
            amt = float((r.get("TRANSACTION_SUM") or "0").replace(",", ".") or 0)
        except (ValueError, KeyError):
            continue
        src = r.get("TRANSACTION_SOURCE") or ""
        kind = net_kind(src)
        svc = (r.get("OFFER_OR_SERVICE_NAME") or "")[:200] if kind in ("serv", "serv_pts", "other") else None
        oid = int(r["ORDER_ID"]) if (r.get("ORDER_ID") or "").isdigit() else None
        k = (d, oid, r.get("SHOP_SKU") or None, r.get("MODEL") or None, kind, src, svc)
        x = agg.setdefault(k, [0.0, 0.0])
        x[0] += float(r.get("COUNT") or 0) if (r.get("COUNT") or "").replace(".", "").isdigit() else 0
        x[1] += amt
    return agg


def run_netting(ctx: Ctx) -> dict:
    """Отчёт по платежам за период: первый раз — с начала заказов, потом NET_DAYS каждый круг и NET_TAIL_DAYS раз в сутки.
    Период отчёта — до 3 месяцев; строки за период заменяем целиком."""
    ym: YM = ctx.wb
    today = today_msk()
    st = ctx.state("ym_netting")
    if not st.get("loaded"):
        d0 = ctx.c.execute("SELECT min(order_day) d FROM ym_orders WHERE account_id=%s", (ctx.acc["id"],)).fetchone()["d"]
        since, tail_at = d0 or today - timedelta(days=ctx.depth(HISTORY_DAYS)), datetime.now(timezone.utc).isoformat()
    else:
        full, tail_at = ctx.tail("ym_netting", hours=24)
        since = today - timedelta(days=NET_TAIL_DAYS if full else NET_DAYS)
    n = 0
    for a, b in _windows(since, today, 90):
        raw = _report(ym, "united-netting", {"businessId": ym.business, "dateFrom": a.isoformat(), "dateTo": b.isoformat()})
        agg = _netting_rows(raw) if raw else {}
        ctx.c.execute("DELETE FROM ym_netting WHERE account_id=%s AND tx_day BETWEEN %s AND %s", (ctx.acc["id"], a, b))
        for (d, oid, sku, model, kind, src, svc), (q, amt) in agg.items():
            if not a <= d <= b:
                continue
            ctx.c.execute("INSERT INTO ym_netting(account_id,tx_day,order_id,shop_sku,model,kind,source,service,qty,amount) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                          (ctx.acc["id"], d, oid, sku, model, kind, src, svc, q or None, round(amt, 2)))
            n += 1
        ctx.c.commit()
    return {"rows": n, "since": str(since), "cursor": {"loaded": True, "tail_at": tail_at}}



BOOST_DAYS = 45             
BOOST_PER_RUN = 12          


def _boost_rows(raw: bytes):
    import csv
    import io
    import zipfile
    data = raw
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        data = z.read(next(n for n in z.namelist() if n.endswith(".csv")))
    for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        if r.get("SHOP_SKU"):
            yield r


def run_boost(ctx: Ctx) -> dict:
    """Буст продаж по дням: сегодня, вчера и позавчера каждый круг (Маркет дописывает доставленные), история — по BOOST_PER_RUN дней."""
    ym: YM = ctx.wb
    today = today_msk()
    have = {r["day"] for r in ctx.c.execute("SELECT DISTINCT day FROM ym_boost WHERE account_id=%s", (ctx.acc["id"],))}
    st = ctx.state("ym_boost")
    done = set(st.get("empty_days") or [])
    want = [today - timedelta(days=i) for i in range(3)]
    want += [d for d in (today - timedelta(days=i) for i in range(3, BOOST_DAYS)) if d not in have and d.isoformat() not in done][:BOOST_PER_RUN]
    n = 0
    for d in want:
        raw = _report(ym, "boost-consolidated", {"businessId": ym.business, "dateFrom": d.isoformat(), "dateTo": d.isoformat()}, wait_s=300)
        rows = list(_boost_rows(raw)) if raw else []
        ctx.c.execute("DELETE FROM ym_boost WHERE account_id=%s AND day=%s", (ctx.acc["id"], d))
        for r in rows:
            g = lambda k: _f((r.get(k) or "").replace(",", ".").replace(" ", ""))  
            ctx.c.execute("""INSERT INTO ym_boost(account_id,day,shop_sku,shows_fee,shows,clicks_fee,clicks,orders_fee,orders,delivered_fee,delivered,
                                                  billed,bonuses,gmv_fee,gmv,campaigns) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (account_id,day,shop_sku) DO NOTHING""",
                          (ctx.acc["id"], d, r["SHOP_SKU"], g("SHOWS_WITH_FEE"), g("SHOWS"), g("CLICKS_VENDOR_WITH_FEE"), g("CLICKS_VENDOR"),
                           g("ORDER_ITEMS_WITH_FEE"), g("ORDER_ITEMS"), g("ORDER_ITEMS_DELIVERED_WITH_FEE"), g("ORDER_ITEMS_DELIVERED"),
                           g("BILLED_AMOUNT"), g("DEDUCTED_BONUSES"), g("ORDERS_GVM_DELIVERED_WITH_FEE"), g("ORDERS_GVM_DELIVERED"),
                           (r.get("SALES_CAMPAIGN_NAMES") or "")[:500] or None))
            n += 1
        if not rows and d < today - timedelta(days=2):
            done.add(d.isoformat())
        ctx.c.commit()
    return {"rows": n, "days": len(want), "cursor": {"empty_days": sorted(done)[-60:]}}


REGISTRY = {"ym_campaigns": run_campaigns, "ym_offers": run_offers, "ym_prices": run_prices, "ym_stocks": run_stocks, "ym_orders": run_orders,
            "ym_netting": run_netting, "ym_boost": run_boost}
EVERY_MIN = {"ym_campaigns": 6 * 60, "ym_offers": 6 * 60, "ym_prices": 120, "ym_stocks": 120, "ym_orders": 30, "ym_netting": 240, "ym_boost": 180}
FIRST_LOAD = ["ym_campaigns", "ym_offers", "ym_prices", "ym_stocks", "ym_orders", "ym_netting", "ym_boost"]


def due(c, account_id: int) -> list[str]:
    st = {r["collector"]: r for r in c.execute("SELECT collector,last_run_at FROM collector_state WHERE account_id=%s", (account_id,)).fetchall()}
    now = datetime.now(timezone.utc)
    return [n for n, mins in EVERY_MIN.items()
            if not st.get(n, {}).get("last_run_at") or now - st[n]["last_run_at"] >= timedelta(minutes=mins) - timedelta(minutes=2)]


def run_one(c, acc: dict, name: str) -> dict:
    ctx = Ctx(c, acc, YM(c, acc))
    lock = c.execute("SELECT pg_try_advisory_lock(hashtext(%s)) ok", (f"collect:{acc['id']}:{name}",)).fetchone()["ok"]
    if not lock:
        return {"collector": name, "ok": False, "skipped": "уже выполняется в другом процессе"}
    try:
        return _run(ctx, name, REGISTRY[name])
    finally:
        c.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"collect:{acc['id']}:{name}",))
        c.commit()

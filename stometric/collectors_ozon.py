"""Сборщики Ozon Seller API. Каждый: run(ctx) → dict-итог; состояние — в collector_state (как у WB), сырьё — raw jsonb в таблицах oz_*.

Поля ответов Ozon разбираем осторожно (.get): что не распознали — остаётся в raw, расчёт не ломается.
"""

import json
from datetime import date, datetime, timedelta, timezone

from .collectors import Ctx, _run
from .config import today_msk
from .ozon import Ozon, OzonError

MSK = timezone(timedelta(hours=3))
HISTORY_DAYS = 120          
REFRESH_DAYS = 14           
SHORT_DAYS = 3              


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _msk_day(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(MSK).date()


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _iso(d: date, end=False) -> str:
    return f"{d.isoformat()}T{'23:59:59' if end else '00:00:00'}.000Z"



def run_products(ctx: Ctx) -> dict:
    oz: Ozon = ctx.wb
    ids, last = [], ""
    while True:
        r = oz.post("/v3/product/list", {"filter": {"visibility": "ALL"}, "last_id": last, "limit": 1000}).get("result") or {}
        items = r.get("items") or []
        ids += [(i.get("product_id"), bool(i.get("archived"))) for i in items if i.get("product_id")]
        last = r.get("last_id") or ""
        if not items or not last or len(items) < 1000:
            break
    arch = dict(ids)
    n = 0
    pids = list(arch)
    from .history import oz_card_diff
    prev = {r["product_id"]: r["raw"] for r in ctx.c.execute("SELECT product_id, raw FROM oz_products WHERE account_id=%s", (ctx.acc["id"],))}
    for k in range(0, len(pids), 1000):
        res = oz.post("/v3/product/info/list", {"product_id": [str(x) for x in pids[k:k + 1000]]})
        items = res.get("items") or (res.get("result") or {}).get("items") or []
        for it in items:
            pid = it.get("id") or it.get("product_id")
            sku = it.get("sku") or next((s.get("sku") for s in it.get("sources") or [] if s.get("sku")), None)
            img = it.get("primary_image")
            img = (img[0] if isinstance(img, list) and img else img) or ((it.get("images") or [None])[0])
            if prev:                     
                oz_card_diff(ctx.c, ctx.acc["id"], sku, prev.get(pid), it)
            ctx.c.execute(
                """INSERT INTO oz_products(account_id,product_id,offer_id,sku,name,model_id,type_id,category_id,photo,archived,raw,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (account_id,product_id) DO UPDATE SET
                   offer_id=EXCLUDED.offer_id, sku=COALESCE(EXCLUDED.sku,oz_products.sku), name=EXCLUDED.name, model_id=EXCLUDED.model_id,
                   type_id=EXCLUDED.type_id, category_id=EXCLUDED.category_id, photo=EXCLUDED.photo, archived=EXCLUDED.archived,
                   raw=EXCLUDED.raw, updated_at=now()""",
                (ctx.acc["id"], pid, it.get("offer_id"), sku, it.get("name"), (it.get("model_info") or {}).get("model_id"),
                 it.get("type_id"), it.get("description_category_id") or it.get("category_id"), img,
                 bool(it.get("is_archived") or it.get("is_autoarchived") or arch.get(pid)), json.dumps(it, ensure_ascii=False)))
            n += 1
    ctx.c.commit()
    try:
        _type_names(ctx)
    except OzonError:
        pass                  
    return {"rows": n}


def run_prices(ctx: Ctx) -> dict:
    oz: Ozon = ctx.wb
    cur, n = "", 0
    from .history import oz_price_diff
    prev = {r["product_id"]: r["raw"] for r in ctx.c.execute("SELECT product_id, raw FROM oz_prices WHERE account_id=%s", (ctx.acc["id"],))}
    sku_of = {r["product_id"]: r["sku"] for r in ctx.c.execute("SELECT product_id, sku FROM oz_products WHERE account_id=%s", (ctx.acc["id"],))}
    while True:
        r = oz.post("/v5/product/info/prices", {"filter": {"visibility": "ALL"}, "cursor": cur, "limit": 1000})
        items = r.get("items") or (r.get("result") or {}).get("items") or []
        for it in items:
            p = it.get("price") or {}
            oz_price_diff(ctx.c, ctx.acc["id"], sku_of.get(it.get("product_id")), prev.get(it.get("product_id")), it)
            ctx.c.execute(
                """INSERT INTO oz_prices(account_id,product_id,offer_id,price,old_price,marketing_price,min_price,raw,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (account_id,product_id) DO UPDATE SET offer_id=EXCLUDED.offer_id,
                   price=EXCLUDED.price, old_price=EXCLUDED.old_price, marketing_price=EXCLUDED.marketing_price, min_price=EXCLUDED.min_price,
                   raw=EXCLUDED.raw, updated_at=now()""",
                (ctx.acc["id"], it.get("product_id"), it.get("offer_id"), _f(p.get("price")), _f(p.get("old_price")),
                 _f(p.get("marketing_price")), _f(p.get("min_price")), json.dumps(it, ensure_ascii=False)))
            n += 1
        cur = r.get("cursor") or ""
        if not items or not cur or len(items) < 1000:
            break
    ctx.c.commit()
    return {"rows": n}


def _type_names(ctx) -> int:
    """Названия типов товаров (Свеча, Сироп…) — один раз на новый type_id: дерево категорий Ozon ~2 МБ."""
    miss = {r["type_id"] for r in ctx.c.execute("""SELECT DISTINCT p.type_id FROM oz_products p LEFT JOIN oz_types t ON t.type_id=p.type_id
                                                   WHERE p.account_id=%s AND p.type_id IS NOT NULL AND t.type_id IS NULL""", (ctx.acc["id"],))}
    if not miss:
        return 0
    found = {}

    def walk(n, cat=None):
        if n.get("type_id") in miss:
            found[n["type_id"]] = (n.get("type_name"), cat)
        for ch in n.get("children") or []:
            walk(ch, n.get("category_name") or cat)
    for n in ctx.wb.post("/v1/description-category/tree", {"language": "DEFAULT"}).get("result") or []:
        walk(n)
    for tid, (name, cat) in found.items():
        ctx.c.execute("""INSERT INTO oz_types(type_id,type_name,category_name) VALUES (%s,%s,%s) ON CONFLICT (type_id) DO UPDATE
                         SET type_name=EXCLUDED.type_name, category_name=EXCLUDED.category_name, updated_at=now()""", (tid, name, cat))
    ctx.c.commit()
    return len(found)


def run_stocks(ctx: Ctx) -> dict:
    """Остатки FBO по кластерам и складам (/v1/analytics/stocks, до 100 SKU за вызов)."""
    oz: Ozon = ctx.wb
    skus = [r["sku"] for r in ctx.c.execute("SELECT DISTINCT sku FROM oz_products WHERE account_id=%s AND sku IS NOT NULL AND NOT archived",
                                             (ctx.acc["id"],))]
    snap = datetime.now(timezone.utc)
    n = 0
    for k in range(0, len(skus), 100):
        r = oz.post("/v1/analytics/stocks", {"skus": [str(s) for s in skus[k:k + 100]]})
        for it in r.get("items") or []:
            avail = _f(it.get("available_stock_count")) or 0
            other = sum(_f(it.get(f)) or 0 for f in ("transit_stock_count", "requested_stock_count", "valid_stock_count",
                                                     "waiting_docs_stock_count", "expiring_stock_count", "stock_defect_stock_count",
                                                     "other_stock_count", "transit_defect_stock_count", "excess_stock_count"))
            ctx.c.execute("INSERT INTO oz_stocks(account_id,snap_at,sku,offer_id,cluster,warehouse,available,other,raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                          (ctx.acc["id"], snap, it.get("sku"), it.get("offer_id"), it.get("cluster_name"),
                           it.get("warehouse_name") or it.get("cluster_name"), avail, other, json.dumps(it, ensure_ascii=False)))
            n += 1
    ctx.c.execute("DELETE FROM oz_stocks WHERE account_id=%s AND snap_at < now() - interval '35 days'", (ctx.acc["id"],))
    ctx.c.commit()
    return {"rows": n, "skus": len(skus)}



PII = ("customer", "addressee")     


def _save_posting(ctx, p: dict, scheme: str) -> int:
    p = {k: v for k, v in p.items() if k not in PII}
    fin = {str(x.get("product_id")): x for x in ((p.get("financial_data") or {}).get("products") or [])}
    fin_list = list(((p.get("financial_data") or {}).get("products") or []))
    an = p.get("analytics_data") or {}
    created = _ts(p.get("created_at")) or _ts(p.get("in_process_at"))
    n = 0
    for i, pr in enumerate(p.get("products") or []):
        f = fin.get(str(pr.get("product_id") or pr.get("sku"))) or (fin_list[i] if i < len(fin_list) else {})
        price = pr.get("price")
        price = price.get("amount") if isinstance(price, dict) else price
        com = f.get("commission_amount")
        if com is None and isinstance(f.get("commission"), dict):
            com = f["commission"].get("amount")
        qty = int(pr.get("quantity") or 1)
        ctx.c.execute(
            """INSERT INTO oz_postings(account_id,posting_number,scheme,sku,offer_id,qty,price,old_price,payout,commission,status,created_at,
                                       in_process_at,order_day,cluster_from,cluster_to,region,raw,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (account_id,posting_number,sku) DO UPDATE SET qty=EXCLUDED.qty, price=EXCLUDED.price, old_price=EXCLUDED.old_price,
               payout=EXCLUDED.payout, commission=EXCLUDED.commission, status=EXCLUDED.status, in_process_at=EXCLUDED.in_process_at,
               cluster_from=EXCLUDED.cluster_from, cluster_to=EXCLUDED.cluster_to, region=EXCLUDED.region, raw=EXCLUDED.raw, updated_at=now()""",
            (ctx.acc["id"], p.get("posting_number"), scheme, pr.get("sku"), pr.get("offer_id"), qty, _f(price),
             _f(f.get("old_price")), _f(f.get("payout")), _f(com), p.get("status"), created,
             _ts(p.get("in_process_at")), _msk_day(created), (p.get("financial_data") or {}).get("cluster_from"),
             (p.get("financial_data") or {}).get("cluster_to"), an.get("region"), json.dumps(p, ensure_ascii=False)))
        n += 1
    return n


def _windows(since: date, until: date, days: int):
    d = since
    while d <= until:
        e = min(until, d + timedelta(days=days - 1))
        yield d, e
        d = e + timedelta(days=1)


def _since(ctx, name: str) -> tuple[date, str | None]:
    """→ (с какой даты читать, отметка tail_at). Весь хвост REFRESH_DAYS — раз в TAIL_HOURS, в остальные круги — SHORT_DAYS."""
    st = ctx.state(name)
    today = today_msk()
    if not st.get("loaded"):
        return today - timedelta(days=HISTORY_DAYS), None
    full, tail_at = ctx.tail(name)
    return today - timedelta(days=REFRESH_DAYS if full else SHORT_DAYS), tail_at


def run_fbo(ctx: Ctx) -> dict:
    """/v3/posting/fbo/list (v2 Ozon отключил: «obsolete method»): постранично по cursor, до 100 отправлений за вызов."""
    oz: Ozon = ctx.wb
    (since, tail_at), n = _since(ctx, "oz_fbo"), 0
    for a, b in _windows(since, today_msk(), 30):
        cur = ""
        while True:
            body = {"sort_dir": "ASC", "filter": {"since": _iso(a), "to": _iso(b, True)}, "limit": 100,
                    "with": {"analytics_data": True, "financial_data": True}}
            if cur:
                body["cursor"] = cur
            r = oz.post("/v3/posting/fbo/list", body)
            ps = r.get("postings") or r.get("result") or []
            for p in ps:
                n += _save_posting(ctx, p, "fbo")
            ctx.c.commit()
            cur = r.get("cursor") or ""
            if not r.get("has_next") or not cur or not ps:
                break
    return {"rows": n, "since": str(since), "cursor": {"loaded": True, "tail_at": tail_at}}


def run_fbs(ctx: Ctx) -> dict:
    """/v4/posting/fbs/list (v3 Ozon отключил 21.10: «obsolete method»): постранично по cursor, как FBO."""
    oz: Ozon = ctx.wb
    (since, tail_at), n = _since(ctx, "oz_fbs"), 0
    for a, b in _windows(since, today_msk(), 30):
        cur = ""
        while True:
            body = {"sort_dir": "ASC", "filter": {"since": _iso(a), "to": _iso(b, True)}, "limit": 100,
                    "with": {"analytics_data": True, "financial_data": True}}
            if cur:
                body["cursor"] = cur
            r = oz.post("/v4/posting/fbs/list", body)
            ps = r.get("postings") or []
            for p in ps:
                n += _save_posting(ctx, p, "fbs")
            ctx.c.commit()
            cur = r.get("cursor") or ""
            if not r.get("has_next") or not cur or not ps:
                break
    return {"rows": n, "since": str(since), "cursor": {"loaded": True, "tail_at": tail_at}}



def _money(o) -> float:
    return _f((o or {}).get("amount")) or 0.0


def _accrual_types(ctx) -> dict:
    """type_id → (name, описание). Справочник обновляем раз в сутки."""
    fresh = ctx.c.execute("SELECT 1 FROM oz_accrual_types WHERE updated_at > now() - interval '1 day' LIMIT 1").fetchone()
    if not fresh:
        for t in ctx.wb.post("/v1/finance/accrual/types", {}).get("accrual_types") or []:
            if t.get("id") is not None:
                ctx.c.execute("""INSERT INTO oz_accrual_types(type_id,name,description) VALUES (%s,%s,%s) ON CONFLICT (type_id) DO UPDATE
                                 SET name=EXCLUDED.name, description=EXCLUDED.description, updated_at=now()""",
                              (t["id"], t.get("name"), t.get("description")))
        ctx.c.commit()
    return {r["type_id"]: (r["name"], r["description"]) for r in ctx.c.execute("SELECT * FROM oz_accrual_types")}


def accrual_rows(x: dict, types: dict) -> list[dict]:
    """Одно начисление /v1/finance/accrual/by-day → строки oz_transactions: товар отправления (продажа/возврат или только доставка),
    сбор по товару (ITEM, по SKU и виду), сбор без привязки к товару (NON_ITEM, CONTAINER_FEES)."""
    cat = x.get("accrued_category") or ""
    out = []

    def tname(tid):
        nm, ds = types.get(tid, (None, None))
        return nm or f"type_{tid}", ds or nm or f"Вид начисления {tid}"

    if cat == "POSTING":
        prods = (x.get("posting") or {}).get("products") or []
        for pr in prods:
            cm, dl = pr.get("commission") or {}, pr.get("delivery") or {}
            sale, com = _money(cm.get("sale_amount")), _money(cm.get("commission"))
            dlv = _money(dl.get("total_accrued")) or sum(_money(s.get("accrued")) for s in dl.get("services") or [])
            svc = [{"name": tname(s.get("type_id"))[1], "price": _money(s.get("accrued"))} for s in dl.get("services") or []]
            kind = ("orders" if sale >= 0 else "returns") if cm else "delivery"
            out.append({"sku": pr.get("sku"), "qty": int(pr.get("quantity") or 1), "tx_type": kind, "operation_type": "SaleCommission" if cm
                        else "Delivery", "type_name": "Продажа" if kind == "orders" else "Возврат" if kind == "returns" else "Доставка",
                        "amount": _money(x.get("total_amount")) if len(prods) == 1 else sale + com + dlv,
                        "accruals_for_sale": sale if cm else None, "sale_commission": com if cm else None, "services_total": dlv,
                        "services": svc, "bonus": _money(cm.get("bonus")), "coinvest": _money(cm.get("coinvestment"))})
    elif cat == "ITEM":
        for it in ((x.get("item_fees") or {}).get("fees") or []):
            for fee in it.get("fees") or []:
                nm, ds = tname(fee.get("type_id"))
                out.append({"sku": it.get("sku"), "qty": int(it.get("quantity") or 1), "tx_type": "services", "operation_type": nm,
                            "type_name": ds, "amount": _money(fee.get("accrued"))})
    else:
        fees = [x["non_item_fee"]] if x.get("non_item_fee") else ((x.get("container_fees") or {}).get("fees") or [])
        for fee in fees:
            nm, ds = tname(fee.get("type_id"))
            out.append({"sku": None, "qty": 0, "tx_type": "other", "operation_type": nm, "type_name": ds, "amount": _money(fee.get("accrued"))})
        if not fees:
            out.append({"sku": None, "qty": 0, "tx_type": "other", "operation_type": cat or "UNSPECIFIED", "type_name": "Прочее",
                        "amount": _money(x.get("total_amount"))})
    return out


def run_transactions(ctx: Ctx) -> dict:
    """Финансы — /v1/finance/accrual/by-day (то же, что «transactions_by_day» в таблице TabLab): по одному дню, страницы по last_id.
    День перезаписываем целиком: oz_transactions (строка = начисление × SKU × вид) и oz_realization_day (продажи/возвраты по SKU
    с баллами Ozon и соинвестом)."""
    oz: Ozon = ctx.wb
    types = _accrual_types(ctx)
    (since, tail_at), n = _since(ctx, "oz_tx"), 0
    acc_id = ctx.acc["id"]
    d = since
    while d < today_msk():
        accs, last = [], ""
        while True:
            r = oz.post("/v1/finance/accrual/by-day", {"date": d.isoformat(), "last_id": last})
            accs += r.get("accruals") or []
            last = r.get("last_id") or ""
            if not last or not r.get("accruals"):
                break
        ctx.c.execute("DELETE FROM oz_transactions WHERE account_id=%s AND op_day=%s", (acc_id, d))
        ctx.c.execute("DELETE FROM oz_realization_day WHERE account_id=%s AND day=%s", (acc_id, d))
        real = {}
        for x in accs:
            for i, t in enumerate(accrual_rows(x, types)):
                ctx.c.execute(
                    """INSERT INTO oz_transactions(account_id,operation_id,operation_date,op_day,operation_type,type_name,tx_type,posting_number,
                                                   amount,accruals_for_sale,sale_commission,delivery_charge,return_delivery_charge,
                                                   services_total,skus,qty,raw)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s) ON CONFLICT (account_id,operation_id) DO UPDATE SET
                       op_day=EXCLUDED.op_day, amount=EXCLUDED.amount, raw=EXCLUDED.raw""",
                    (acc_id, int(x.get("accrual_id") or 0) * 1000 + i, d, d, t["operation_type"], t["type_name"], t["tx_type"],
                     x.get("unit_number") if x.get("accrued_category") == "POSTING" else None, t["amount"], t.get("accruals_for_sale"),
                     t.get("sale_commission"), t.get("services_total") or 0, [t["sku"]] if t["sku"] else None, t["qty"],
                     json.dumps({**x, "services": t.get("services") or []}, ensure_ascii=False)))
                n += 1
                if t["tx_type"] in ("orders", "returns") and t["sku"]:
                    a = real.setdefault(int(t["sku"]), [0.0] * 8)
                    sale = t["accruals_for_sale"]
                    if t["tx_type"] == "orders":
                        a[0] += t["qty"]
                        a[1] += sale
                    else:
                        a[2] += t["qty"]
                        a[3] += -sale
                    a[4] += t["bonus"]
                    a[5] += t["coinvest"]
                    a[6] += t["sale_commission"]
                    a[7] += t["amount"]
        for sku, a in real.items():
            ctx.c.execute("""INSERT INTO oz_realization_day(account_id,day,sku,sale_qty,sale_amount,ret_qty,ret_amount,bonus,coinvest,commission,total)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (acc_id, d, sku, *a))
        ctx.c.commit()
        d += timedelta(days=1)
    return {"rows": n, "since": str(since), "cursor": {"loaded": True, "tail_at": tail_at}}



METRICS_FULL = ["hits_view_search", "hits_view_pdp", "hits_view", "hits_tocart_search", "hits_tocart_pdp", "hits_tocart",
                "session_view_search", "session_view_pdp", "session_view", "position_category", "revenue", "ordered_units",
                "cancellations", "returns"]          
METRICS_BASIC = ["revenue", "ordered_units"]


def run_analytics(ctx: Ctx) -> dict:
    """/v1/analytics/data по SKU × день. Метод — раз в минуту, поэтому за круг берём окно до 14 дней; история — порциями назад."""
    oz: Ozon = ctx.wb
    st = ctx.state("oz_analytics")
    metrics = METRICS_BASIC if st.get("metrics") == METRICS_BASIC else METRICS_FULL
    today = today_msk()
    back = date.fromisoformat(st["back"]) if st.get("back") else None
    if back is None or back > today - timedelta(days=90):   
        b = (back or today) - timedelta(days=1)
        a = b - timedelta(days=13)
        new_back = a
    else:
        a, b, new_back = today - timedelta(days=7), today - timedelta(days=1), back
    off, n = 0, 0
    while True:
        try:
            r = oz.post("/v1/analytics/data", {"date_from": a.isoformat(), "date_to": b.isoformat(), "metrics": metrics,
                                               "dimension": ["sku", "day"], "filters": [], "sort": [], "limit": 1000, "offset": off})
        except OzonError as e:
            if metrics != METRICS_BASIC and any(w in str(e).lower() for w in ("premium", "metric", "403", "400")):
                metrics = METRICS_BASIC            
                continue
            raise
        data = (r.get("result") or {}).get("data") or []
        got = len((r.get("result") or {}).get("totals") or (data[0].get("metrics") if data else []) or [])
        if metrics != METRICS_BASIC and got and got < len(metrics):
            
            metrics = METRICS_BASIC
            off = 0
            continue
        for row in data:
            dims = row.get("dimensions") or []
            if len(dims) < 2:
                continue
            sku, day = dims[0].get("id"), dims[1].get("id")
            vals = dict(zip(metrics, row.get("metrics") or []))
            ctx.c.execute("""INSERT INTO oz_analytics(account_id,day,sku,m) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,day,sku)
                             DO UPDATE SET m=EXCLUDED.m""", (ctx.acc["id"], day, sku, json.dumps(vals)))
            n += 1
        ctx.c.commit()
        if len(data) < 1000:
            break
        off += 1000
    return {"rows": n, "period": f"{a}..{b}", "metrics": len(metrics), "cursor": {"back": str(new_back), "metrics": metrics}}



AD_HISTORY_DAYS = 90
AD_REFRESH_DAYS = 7


def _first(d: dict, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def ad_kind(x: dict) -> str:
    """Тип кампании как в таблице «ПР TabLab»: стратегия «вывод в топ» → Вывод в топ; размещение «поиск и категории» → Поиск и
    рекомендации; «верх поиска» → Поиск; баннер; оплата за заказ; блогеры/VK."""
    t, pl = x.get("advObjectType") or "", json.dumps(x.get("placement") or x.get("ProductAdvPlacements") or "")
    if t == "REF_BLOGGER":
        return "Блогеры"
    if t == "REF_VK":
        return "VK"
    if t in ("SEARCH_PROMO", "ALL_SKU_PROMO"):
        return "ОЗЗ"
    if t == "BANNER":
        return "Баннерная"
    if x.get("productAutopilotStrategy") == "TOP_PROMOTION":
        return "Вывод в топ"
    if "PLACEMENT_TOP_PROMOTION" in pl:
        return "Поиск"
    return "Поиск и рекомендации"


def run_ad_campaigns(ctx: Ctx) -> dict:
    """Кампании рекламного кабинета и продвигаемые SKU (у товарных кампаний)."""
    from .ozon_perf import OzonPerf
    pf = OzonPerf(ctx.c, ctx.acc)
    lst = (pf.get("/api/client/campaign") or {}).get("list") or []
    n = 0
    from .history import oz_ad_diff
    prev = {r["campaign_id"]: (r["raw"], r["skus"]) for r in ctx.c.execute(
        "SELECT campaign_id, raw, skus FROM oz_ad_campaigns WHERE account_id=%s", (ctx.acc["id"],))}
    for x in lst:
        cid = int(x.get("id"))
        skus = None
        if (x.get("advObjectType") or "") in ("SKU", "SEARCH_PROMO") and x.get("state") != "CAMPAIGN_STATE_ARCHIVED":
            obj = pf.get(f"/api/client/campaign/{cid}/objects", allow_404=True) or {}
            skus = [int(o["id"]) for o in (obj.get("list") or []) if str(o.get("id") or "").isdigit()] or None
        if prev:
            old = prev.get(cid)
            oz_ad_diff(ctx.c, ctx.acc["id"], old[0] if old else None, x, skus or (old[1] if old else None))
        ctx.c.execute(
            """INSERT INTO oz_ad_campaigns(account_id,campaign_id,title,state,adv_type,payment_type,daily_budget,skus,raw,kind,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (account_id,campaign_id) DO UPDATE SET title=EXCLUDED.title, kind=EXCLUDED.kind,
               state=EXCLUDED.state, adv_type=EXCLUDED.adv_type, payment_type=EXCLUDED.payment_type, daily_budget=EXCLUDED.daily_budget,
               skus=COALESCE(EXCLUDED.skus, oz_ad_campaigns.skus), raw=EXCLUDED.raw, updated_at=now()""",
            (ctx.acc["id"], cid, x.get("title"), x.get("state"), x.get("advObjectType"), x.get("PaymentType") or x.get("paymentType"),
             _f(x.get("dailyBudget")), skus, json.dumps(x, ensure_ascii=False), ad_kind(x)))
        n += 1
    ctx.c.commit()
    return {"rows": n}


def _ad_stats(pf, kind: str, a: date, b: date) -> list[dict]:
    p = {"dateFrom": a.isoformat(), "dateTo": b.isoformat()}
    data = pf.get(f"/api/client/statistics/{kind}/json", p, allow_404=True)
    if data is None:                              
        data = pf.get(f"/api/client/statistics/{kind}", p)
    from .ozon_perf import rows
    return rows(data)


def _day(v):
    s = str(v or "").strip()[:10]
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        s = f"{s[6:]}-{s[3:5]}-{s[:2]}"
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def run_ad_daily(ctx: Ctx) -> dict:
    """Статистика кампаний по дням (показы, клики, расход, заказы) + расход по дням с бонусами (expense)."""
    from .ozon_perf import OzonPerf, num
    pf = OzonPerf(ctx.c, ctx.acc)
    st = ctx.state("oz_ad_daily")
    today = today_msk()
    since = today - timedelta(days=AD_REFRESH_DAYS if st.get("loaded") else AD_HISTORY_DAYS)
    n, unknown = 0, set()
    for a, b in _windows(since, today, 30):
        got = {}
        for r in _ad_stats(pf, "daily", a, b):
            cid, d = _first(r, "id", "ID", "campaignId", "ID кампании"), _day(_first(r, "date", "Дата", "День"))
            if not str(cid or "").isdigit() or d is None:
                unknown.add(",".join(list(r)[:6]))
                continue
            got[(d, int(cid))] = {"views": num(_first(r, "views", "Показы")), "clicks": num(_first(r, "clicks", "Клики")),
                                  "spent": num(_first(r, "moneySpent", "Расход, ₽", "Расход", "Расход, ₽, с НДС")),
                                  "orders": num(_first(r, "orders", "Заказы", "Заказы, шт")),
                                  "orders_money": num(_first(r, "ordersMoney", "Выручка, ₽", "Заказы, ₽", "Продажи, ₽")), "raw": r}
        for r in _ad_stats(pf, "expense", a, b):
            cid, d = _first(r, "id", "ID", "campaignId", "ID кампании"), _day(_first(r, "date", "Дата", "День"))
            if not str(cid or "").isdigit() or d is None:
                continue
            g = got.setdefault((d, int(cid)), {"raw": {}})
            sp = num(_first(r, "moneySpent", "Расход, ₽", "Расход"))
            if sp is not None:
                g["spent"] = sp
            g["bonus_spent"] = num(_first(r, "bonusSpent", "Бонусы, ₽", "Списано бонусов"))
            g["raw"] = {**g["raw"], "expense": r}
        for (d, cid), g in got.items():
            ctx.c.execute(
                """INSERT INTO oz_ad_daily(account_id,day,campaign_id,views,clicks,spent,bonus_spent,orders,orders_money,raw)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (account_id,day,campaign_id) DO UPDATE SET
                   views=COALESCE(EXCLUDED.views,oz_ad_daily.views), clicks=COALESCE(EXCLUDED.clicks,oz_ad_daily.clicks),
                   spent=COALESCE(EXCLUDED.spent,oz_ad_daily.spent), bonus_spent=COALESCE(EXCLUDED.bonus_spent,oz_ad_daily.bonus_spent),
                   orders=COALESCE(EXCLUDED.orders,oz_ad_daily.orders), orders_money=COALESCE(EXCLUDED.orders_money,oz_ad_daily.orders_money),
                   raw=EXCLUDED.raw""",
                (ctx.acc["id"], d, cid, g.get("views"), g.get("clicks"), abs(g["spent"]) if g.get("spent") is not None else None,
                 g.get("bonus_spent"), g.get("orders"), g.get("orders_money"), json.dumps(g.get("raw") or {}, ensure_ascii=False, default=str)))
            n += 1
        ctx.c.commit()
    res = {"rows": n, "since": str(since), "cursor": {"loaded": True}}
    if unknown:
        res["unparsed_headers"] = sorted(unknown)[:3]       
    return res



def _premium_denied(e: Exception) -> bool:
    t = str(e).lower()
    return any(w in t for w in (" 403", " 404", "premium", "permission", "denied", "not available", "подписк"))


def _half_months(since: date, until: date):
    """Окна выкупов как у Ozon (два отчёта в месяц): 1–14 и 15–конец месяца; дата отчёта = начало окна (как в таблице TabLab)."""
    d = since.replace(day=1 if since.day < 15 else 15)
    while d <= until:
        if d.day == 1:
            e = d.replace(day=14)
        else:
            e = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        yield d, min(e, until)
        d = e + timedelta(days=1)


def run_buyouts(ctx: Ctx) -> dict:
    """/v1/finance/products/buyout — товары, выкупленные Ozon у продавца. Даты в ответе нет: берём полумесячными окнами,
    день = начало окна. Лимит у метода жёсткий — пауза между вызовами (ozon.INTERVAL)."""
    oz: Ozon = ctx.wb
    (since, tail_at), n = _since(ctx, "oz_buyouts"), 0
    for a, b in _half_months(since, today_msk() - timedelta(days=1)):
        try:
            r = oz.post("/v1/finance/products/buyout", {"date_from": a.isoformat(), "date_to": b.isoformat()})
        except OzonError as e:
            if _premium_denied(e):
                return {"rows": n, "skipped": f"нет доступа: {str(e)[:120]}", "cursor": {"loaded": True}}
            raise
        for x in r.get("products") or (r.get("result") or {}).get("products") or []:
            sku = x.get("sku")
            if not str(sku or "").isdigit():
                continue
            ctx.c.execute("""INSERT INTO oz_buyouts(account_id,posting_number,sku,day,qty,amount,raw) VALUES (%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (account_id,posting_number,sku) DO UPDATE SET day=EXCLUDED.day, qty=EXCLUDED.qty,
                             amount=EXCLUDED.amount, raw=EXCLUDED.raw""",
                          (ctx.acc["id"], x.get("posting_number") or f"{a}:{sku}", int(sku), a, _f(x.get("quantity")),
                           _f(x.get("amount") or x.get("buyout_amount")), json.dumps(x, ensure_ascii=False)))
            n += 1
        ctx.c.commit()
    return {"rows": n, "since": str(since), "cursor": {"loaded": True, "tail_at": tail_at}}


AD_SKU_PER_RUN = 6          


def _hdr(h: str) -> str | None:
    t = h.lower().replace("ё", "е")
    if "модел" in t:
        return "models_money" if ("₽" in t or "руб" in t or "продаж" in t) else "models"
    if t in ("дата", "день"):                       
        return "day"
    if t == "sku" or t.startswith("sku"):
        return "sku"
    if t.startswith("показ"):
        return "views"
    if t.startswith("клик"):
        return "clicks"
    if "корзин" in t:
        return "to_cart"
    if t.startswith("расход"):
        return "spent"
    if (t.startswith("заказы") or t.startswith("продано товаров")) and "₽" not in t and "руб" not in t:
        return "orders"
    if t.startswith("продажи") or t.startswith("выручка") or (t.startswith("заказы") and ("₽" in t or "руб" in t)):
        return "orders_money"
    return None


def run_ad_sku(ctx: Ctx) -> dict:
    """Реклама по SKU и дням: асинхронный отчёт Performance API по каждой товарной кампании (по несколько кампаний за круг)."""
    from .ozon_perf import OzonPerf, num, rows
    pf = OzonPerf(ctx.c, ctx.acc)
    st = ctx.state("oz_ad_sku")
    done = dict(st.get("done") or {})
    today = today_msk()
    y = today - timedelta(days=1)
    camps = ctx.c.execute(
        """SELECT k.campaign_id, max(d.day) last_spend FROM oz_ad_campaigns k JOIN oz_ad_daily d
             ON d.account_id=k.account_id AND d.campaign_id=k.campaign_id AND coalesce(d.spent,0) + coalesce(d.views,0) > 0
           WHERE k.account_id=%s AND k.kind IN ('Поиск','Поиск и рекомендации','Вывод в топ','Баннерная')
           GROUP BY 1 ORDER BY 1""", (ctx.acc["id"],)).fetchall()
    todo = []
    for k in camps:
        last = date.fromisoformat(done[str(k["campaign_id"])]) if str(k["campaign_id"]) in done else None
        start = max(today - timedelta(days=AD_HISTORY_DAYS), (last - timedelta(days=2)) if last else date.min)
        if last and (last >= y or k["last_spend"] < start):
            continue
        todo.append((k["campaign_id"], start))
    n, unknown = 0, set()
    for cid, start in todo[:AD_SKU_PER_RUN]:
        for a, b in _windows(start, y, 30):
            data = rows(pf.report(cid, a.isoformat(), b.isoformat()), "показ")
            for r in data:
                m = {}
                for h, v in r.items():
                    k = _hdr(str(h or ""))
                    if k and k not in m:
                        m[k] = v
                if not m.get("sku") or not str(m["sku"]).strip().isdigit():
                    unknown.add(",".join(str(h) for h in list(r)[:8]))
                    continue
                d = _day(m.get("day")) or (a if a == b else None)
                if d is None:
                    continue
                ctx.c.execute(
                    """INSERT INTO oz_ad_sku(account_id,day,campaign_id,sku,views,clicks,to_cart,spent,orders,orders_money,models,models_money,raw)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (account_id,day,campaign_id,sku) DO UPDATE SET
                       views=EXCLUDED.views, clicks=EXCLUDED.clicks, to_cart=EXCLUDED.to_cart, spent=EXCLUDED.spent, orders=EXCLUDED.orders,
                       orders_money=EXCLUDED.orders_money, models=EXCLUDED.models, models_money=EXCLUDED.models_money, raw=EXCLUDED.raw""",
                    (ctx.acc["id"], d, cid, int(str(m["sku"]).strip()), num(m.get("views")), num(m.get("clicks")), num(m.get("to_cart")),
                     abs(num(m.get("spent")) or 0), num(m.get("orders")), num(m.get("orders_money")), num(m.get("models")),
                     num(m.get("models_money")), json.dumps(r, ensure_ascii=False)))
                n += 1
            ctx.c.commit()
        done[str(cid)] = str(y)
    res = {"rows": n, "campaigns": f"{min(len(todo), AD_SKU_PER_RUN)} из {len(todo)}", "cursor": {"done": done}}
    if unknown:
        res["unparsed_headers"] = sorted(unknown)[:3]
    return res


def run_queries(ctx: Ctx) -> dict:
    """Продажи по запросам: /v1/analytics/product-queries/details за каждый день, 15 запросов на SKU (как ZMT_DAILY в таблице TabLab).
    Первая загрузка — 30 дней, дальше — перечитываем 3 последних дня."""
    oz: Ozon = ctx.wb
    st = ctx.state("oz_queries")
    today = today_msk()
    skus = [str(r["sku"]) for r in ctx.c.execute("SELECT sku FROM oz_products WHERE account_id=%s AND sku IS NOT NULL AND NOT archived",
                                                  (ctx.acc["id"],))]
    d = today - timedelta(days=3 if st.get("loaded") else 30)
    n = 0
    while d < today:
        for k in range(0, len(skus), 6):                  
            page = 0
            while True:
                try:
                    r = oz.post("/v1/analytics/product-queries/details", {"date_from": f"{d}T00:00:00Z", "date_to": f"{d}T23:59:59Z",
                                                                         "skus": skus[k:k + 6], "limit_by_sku": 15, "page": page,
                                                                         "page_size": 100, "sort_by": "BY_VIEWS", "sort_dir": "DESCENDING"})
                except OzonError as e:
                    if "no data for the specified period" in str(e):   
                        return {"rows": n, "cursor": {"loaded": True}}
                    raise
                for q in r.get("queries") or []:
                    if not q.get("sku") or not q.get("query"):
                        continue
                    ctx.c.execute("""INSERT INTO oz_queries(account_id,day,sku,query,idx,position,searchers,viewers,conv,gmv,orders)
                                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (account_id,day,sku,query) DO UPDATE SET
                                     idx=EXCLUDED.idx, position=EXCLUDED.position, searchers=EXCLUDED.searchers, viewers=EXCLUDED.viewers,
                                     conv=EXCLUDED.conv, gmv=EXCLUDED.gmv, orders=EXCLUDED.orders""",
                                  (ctx.acc["id"], d, q["sku"], q["query"], q.get("query_index"), _f(q.get("position")),
                                   _f(q.get("unique_search_users")), _f(q.get("unique_view_users")), _f(q.get("view_conversion")),
                                   _f(q.get("gmv")), _f(q.get("order_count"))))
                    n += 1
                ctx.c.commit()
                page += 1
                if page >= int(r.get("page_count") or 1):
                    break
        d += timedelta(days=1)
    return {"rows": n, "cursor": {"loaded": True}}


def run_ad_phrases(ctx: Ctx) -> dict:
    """Поисковые фразы кампаний «Поиск»/«Вывод в топ» (отчёт Performance SEARCH_PHRASES, по дням): 30 дней, дальше — 7; 6 кампаний за круг."""
    from .ozon_perf import OzonPerf, num, rows
    pf = OzonPerf(ctx.c, ctx.acc)
    st = ctx.state("oz_ad_phrases")
    done = dict(st.get("done") or {})
    today = today_msk()
    y = today - timedelta(days=1)
    camps = [r["campaign_id"] for r in ctx.c.execute(
        """SELECT DISTINCT k.campaign_id FROM oz_ad_campaigns k JOIN oz_ad_daily d ON d.account_id=k.account_id AND d.campaign_id=k.campaign_id
           AND d.day >= current_date - 30 AND coalesce(d.views,0) > 0 WHERE k.account_id=%s AND k.kind IN ('Поиск','Вывод в топ') ORDER BY 1""",
        (ctx.acc["id"],))]
    todo = [cid for cid in camps if done.get(str(cid)) != str(y)]
    n = 0
    for cid in todo[:AD_SKU_PER_RUN]:
        a = y - timedelta(days=6 if str(cid) in done else 29)
        for r in rows(pf.report(cid, a.isoformat(), y.isoformat(), phrases=True), "запрос"):
            m = {str(h).strip().lower(): v for h, v in r.items()}
            day, sku, ph = _day(m.get("день")), m.get("sku"), (m.get("поисковый запрос") or "").strip()
            if not day or not str(sku or "").isdigit() or not ph:
                continue
            ctx.c.execute("""INSERT INTO oz_ad_phrases(account_id,day,campaign_id,sku,phrase,views,clicks) VALUES (%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (account_id,day,campaign_id,sku,phrase) DO UPDATE SET views=EXCLUDED.views, clicks=EXCLUDED.clicks""",
                          (ctx.acc["id"], day, cid, int(sku), ph, num(m.get("показы")), num(m.get("клики"))))
            n += 1
        ctx.c.commit()
        done[str(cid)] = str(y)
    return {"rows": n, "campaigns": f"{min(len(todo), AD_SKU_PER_RUN)} из {len(todo)}", "cursor": {"done": done}}


AD_COLLECTORS = ("oz_ad_campaigns", "oz_ad_daily", "oz_ad_sku", "oz_ad_phrases")


def has_ad_key(c, account_id: int) -> bool:
    return bool(c.execute("SELECT 1 FROM account_ad_tokens WHERE account_id=%s", (account_id,)).fetchone())




NO_SUB = "not available with existing subscription"


def _oz_review_put(c, acc: int, r: dict, offers: dict) -> bool:
    sku = r.get("sku")
    created = r.get("published_at")
    val = r.get("rating")
    pr = offers.get(sku) or {}
    row = c.execute(
        """INSERT INTO wb_feedbacks(account_id,id,nm_id,vendor_code,product_name,valuation,text,photos,has_video,order_status,created_at,
             answered,in_rating)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,id) DO UPDATE SET answered=EXCLUDED.answered OR wb_feedbacks.answer_text IS NOT NULL,
             valuation=EXCLUDED.valuation, text=EXCLUDED.text, photos=EXCLUDED.photos, has_video=EXCLUDED.has_video,
             order_status=EXCLUDED.order_status, in_rating=EXCLUDED.in_rating, updated_at=now()
           RETURNING (xmax = 0) AS fresh""",
        (acc, r["id"], sku, pr.get("offer_id"), pr.get("name"), val, r.get("text"), int(r.get("photos_amount") or 0),
         bool(r.get("videos_amount")), r.get("order_status"), created, (r.get("status") or "").upper() == "PROCESSED",
         r.get("is_rating_participant"))).fetchone()
    if row["fresh"] and val is not None and val <= 4:      
        b = c.execute("""SELECT avg(valuation) a FROM wb_feedbacks WHERE account_id=%s AND nm_id=%s AND created_at < %s
                         AND coalesce(in_rating, true) AND id<>%s""", (acc, sku, created, r["id"])).fetchone()["a"]
        c.execute("UPDATE wb_feedbacks SET rating_before=%s WHERE account_id=%s AND id=%s", (b, acc, r["id"]))
    return row["fresh"]


def run_reviews(ctx: Ctx) -> dict:
    oz: Ozon = ctx.wb
    acc = ctx.acc["id"]
    st = ctx.state("oz_reviews")
    try:
        cnt = oz.post("/v1/review/count", {})
    except OzonError as e:
        if NO_SUB in str(e):
            return {"no_subscription": True, "cursor": {**st, "no_subscription": True}}
        raise
    offers = {r["sku"]: r for r in ctx.c.execute("SELECT sku, offer_id, name FROM oz_products WHERE account_id=%s", (acc,)).fetchall()}
    n = new = 0
    edge = datetime.now(timezone.utc) - timedelta(days=3)
    open_ids: list[str] = []
    for status in ("UNPROCESSED", "ALL"):
        last = ""
        while True:
            res = oz.post("/v1/review/list", {"last_id": last, "limit": 100, "sort_dir": "DESC", "status": status})
            items = res.get("reviews") or []
            old = False
            for r in items:
                new += _oz_review_put(ctx.c, acc, r, offers)
                if status == "UNPROCESSED":
                    open_ids.append(r["id"])
                elif st.get("backfilled") and datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")) < edge:
                    old = True
            n += len(items)
            ctx.c.commit()
            last = res.get("last_id") or ""
            if not res.get("has_next") or not last or old:
                break
    still = set(open_ids)
    done = [r["id"] for r in ctx.c.execute("SELECT id FROM wb_feedbacks WHERE account_id=%s AND NOT answered", (acc,)).fetchall()
            if r["id"] not in still]
    if done:
        ctx.c.execute("UPDATE wb_feedbacks SET answered=true, updated_at=now() WHERE account_id=%s AND id = ANY(%s)", (acc, done))
    
    todo = ctx.c.execute("""SELECT id FROM wb_feedbacks WHERE account_id=%s AND answered AND answer_text IS NULL
                            AND created_at > now() - interval '60 days' ORDER BY created_at DESC LIMIT 100""", (acc,)).fetchall()
    for t in todo:
        cm = oz.post("/v1/review/comment/list", {"review_id": t["id"], "limit": 100, "offset": 0, "sort_dir": "ASC"}).get("comments") or []
        own = [x for x in cm if x.get("is_owner") or x.get("is_official")]
        ctx.c.execute("UPDATE wb_feedbacks SET answer_text=%s, answer_editable=false WHERE account_id=%s AND id=%s",
                      (own[0]["text"] if own else "", acc, t["id"]))
    ctx.c.commit()
    out = {"reviews": n, "new": new, "count": cnt, "cursor": {"backfilled": True}}
    try:
        from . import reviews
        from .private_ai import scheduled_ai
        with scheduled_ai(ctx.c):
            out["auto"] = reviews.process(ctx.c, acc)
    except Exception as e:  
        ctx.c.rollback()
        out["auto_error"] = str(e)[:200]
    return out

REGISTRY = {"oz_products": run_products, "oz_prices": run_prices, "oz_stocks": run_stocks, "oz_fbo": run_fbo, "oz_fbs": run_fbs,
            "oz_tx": run_transactions, "oz_analytics": run_analytics, "oz_ad_campaigns": run_ad_campaigns, "oz_ad_daily": run_ad_daily,
            "oz_buyouts": run_buyouts, "oz_ad_sku": run_ad_sku, "oz_queries": run_queries, "oz_ad_phrases": run_ad_phrases, "oz_reviews": run_reviews}
EVERY_MIN = {"oz_products": 6 * 60, "oz_prices": 120, "oz_stocks": 120, "oz_fbo": 30, "oz_fbs": 30, "oz_tx": 120, "oz_analytics": 30,
             "oz_ad_campaigns": 6 * 60, "oz_ad_daily": 60, "oz_buyouts": 60, "oz_ad_sku": 30, "oz_queries": 6 * 60,
             "oz_ad_phrases": 6 * 60, "oz_reviews": 10}
FIRST_LOAD = ["oz_products", "oz_prices", "oz_stocks", "oz_fbo", "oz_fbs", "oz_tx", "oz_analytics", "oz_buyouts", "oz_queries"]


def due(c, account_id: int) -> list[str]:
    st = {r["collector"]: r for r in c.execute("SELECT collector,last_run_at,cursor FROM collector_state WHERE account_id=%s",
                                                (account_id,)).fetchall()}
    now = datetime.now(timezone.utc)
    ads = has_ad_key(c, account_id)
    out = []
    for name, mins in EVERY_MIN.items():
        if name in AD_COLLECTORS and not ads:
            continue
        last = st.get(name, {}).get("last_run_at")
        cur = st.get(name, {}).get("cursor") or {}
        if name == "oz_reviews" and cur.get("no_subscription") and last and now - last < timedelta(hours=6):
            continue               
        if name == "oz_analytics" and cur.get("back") and date.fromisoformat(cur["back"]) > today_msk() - timedelta(days=90):
            out.append(name)       
            continue
        if last is None or now - last >= timedelta(minutes=mins) - timedelta(minutes=2):
            out.append(name)
    return out


def run_one(c, acc: dict, name: str) -> dict:
    ctx = Ctx(c, acc, Ozon(c, acc))
    lock = c.execute("SELECT pg_try_advisory_lock(hashtext(%s)) ok", (f"collect:{acc['id']}:{name}",)).fetchone()["ok"]
    if not lock:
        return {"collector": name, "ok": False, "skipped": "уже выполняется в другом процессе"}
    try:
        return _run(ctx, name, REGISTRY[name])
    finally:
        c.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"collect:{acc['id']}:{name}",))
        c.commit()

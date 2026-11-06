"""Self-hosted application component."""

from collections import defaultdict
from datetime import date

from . import pnl_real

COLS = [("orders_sum", "Заказали, ₽", "money"), ("orders", "Заказали, шт.", "int"), ("qty", "Продали нетто, шт.", "int"),
        ("rev", "Выручка (цена продавца до СПП), ₽", "money"), ("commission", "Комиссия WB (со скидкой СПП), ₽", "money"),
        ("acquiring", "Эквайринг, ₽", "money"), ("logistics", "Логистика, ₽", "money"), ("services", "Хранение и приёмка, ₽", "money"),
        ("cost", "Закупка проданного, ₽", "money"), ("ads", "Реклама (по факту открутки), ₽", "money"), ("drr", "ДРР от заказов, %", "share"),
        ("penalty", "Штрафы, ₽", "money"), ("reviews", "Баллы за отзывы, ₽", "money"), ("cashback", "Кэшбэк и комиссия лояльности, ₽", "money"),
        ("jam", "Подписка Джем, ₽", "money"), ("other", "Прочие удержания WB, ₽", "money"), ("extra", "Доплаты и компенсации WB, ₽", "money"),
        ("profit", "Прибыль до налогов, ₽", "money"), ("m_orders", "Маржа от заказов, %", "share"), ("m_rev", "Маржа от выручки, %", "share"),
        ("roi", "ROI до налогов (прибыль / закупка), %", "share"),
        ("vat", "НДС к уплате (прогноз), ₽", "money"), ("income_tax", "Налог на прибыль / УСН / НДФЛ ИП (прогноз), ₽", "money"),
        ("profit_tax", "Прибыль после налогов, ₽", "money"), ("m_tax", "Маржа от заказов после налогов, %", "share"),
        ("roi_tax", "ROI после налогов, %", "share")]
MONEY = [k for k, _, t in COLS if t == "money" and k not in ("orders_sum",)]


def _n(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _kind(bt: str) -> str:
    b = (bt or "").lower()
    if "продвижение" in b:
        return "promo"          
    if "медиа" in b:
        return "media"
    if "джем" in b:
        return "jam"
    if "отзыв" in b:
        return "reviews"
    return "other"


def compute(c, shop: int, d_from: date, d_to: date) -> dict:
    """→ {"nm": {nm: {поле: сумма}}, "month": {YYYY-MM: {...}}, "nm_month", "total"} — суммы со знаком «+ доход, − расход»."""
    A, nocost = raw(c, shop, d_from, d_to)
    prior = {}
    if _needs_year_context(c, shop, d_from, d_to):
        prior, _ = raw(c, shop, date(d_from.year, 1, 1), d_from - timedelta(days=1))
    return finalize(c, shop, A, nocost, d_to, prior)


def _needs_year_context(c, shop: int, d_from: date, d_to: date) -> bool:
    return d_from > date(d_from.year, 1, 1) and bool(c.execute(
        "SELECT 1 FROM tax_settings WHERE account_id=%s AND regime=%s AND valid_from<=%s LIMIT 1",
        (shop, pnl_real.IP, d_to)).fetchone())


def raw(c, shop: int, d_from: date, d_to: date) -> tuple[dict, dict]:
    """Суммы по клеткам (артикул, месяц) — складываются: расчёт за несколько месяцев = сумма расчётов за каждый месяц."""
    df, dt = d_from.isoformat(), d_to.isoformat()
    costs = defaultdict(list)
    for r in c.execute("SELECT nm_id, valid_from, cost FROM cost_price WHERE account_id=%s ORDER BY nm_id, valid_from", (shop,)):
        costs[r["nm_id"]].append((r["valid_from"].isoformat(), float(r["cost"])))

    def cost_at(nm: int, day: str) -> float | None:
        cu = None
        for vf, cs in costs.get(nm, []):
            if vf <= day:
                cu = cs
        return cu if cu is not None else (costs[nm][0][1] if costs.get(nm) else None)

    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()
    
    A = defaultdict(lambda: defaultdict(float))
    nocost = defaultdict(float)
    
    n = lambda f: f"coalesce(nullif(data->>'{f}', '')::numeric, 0)"
    kind = """CASE WHEN lower(data->>'bonusTypeName') LIKE '%%продвижение%%' THEN 'promo' WHEN lower(data->>'bonusTypeName') LIKE '%%медиа%%' THEN 'media'
                   WHEN lower(data->>'bonusTypeName') LIKE '%%джем%%' THEN 'jam' WHEN lower(data->>'bonusTypeName') LIKE '%%отзыв%%' THEN 'reviews'
                   ELSE 'other' END"""
    
    sql = f"""WITH x AS MATERIALIZED (
                SELECT coalesce((data->>'nmId')::bigint, 0) nm, left(data->>'orderDt', 10) od, left(data->>'rrDate', 10) rr,
                       CASE data->>'docTypeName' WHEN 'Продажа' THEN 1 WHEN 'Возврат' THEN -1 ELSE 0 END sg,
                       {n('retailPriceWithDisc')} rpwd, {n('forPay')} fp, {n('retailAmount')} ra, {n('vwNds')} vwn, {n('quantity')} q, {n('acquiringFee')} acq,
                       {n('deliveryService')} ds, {n('paidStorage')} + {n('paidAcceptance')} serv, {n('penalty')} pen,
                       {n('additionalPayment')} addp, {n('cashbackAmount')} + {n('cashbackCommissionChange')} - {n('cashbackDiscount')} cb,
                       {n('deduction')} ded, {kind} k
                FROM raw_rows WHERE account_id=%(s)s AND source='realization' AND row_date >= %(dfd)s),
              y AS (SELECT *, (od BETWEEN %(df)s AND %(dt)s AND od > '2001') coh, rr BETWEEN %(df)s AND %(dt)s per FROM x)
            SELECT 'c' t, nm, od g, NULL k, sum(sg * rpwd) rev, sum(sg * (rpwd - fp)) comm, sum(sg * acq) acq, sum(sg * ra) paid, sum(sg * vwn) vwv,
                   sum(sg * q) qty, sum(ds) ds, NULL::numeric serv, NULL::numeric pen, NULL::numeric addp, NULL::numeric cb,
                   NULL::numeric dpos, NULL::numeric dneg
            FROM y WHERE coh GROUP BY nm, od
            UNION ALL
            SELECT 'p', nm, left(rr, 7), k, NULL, NULL, NULL, NULL, NULL, NULL, sum(ds) FILTER (WHERE NOT coalesce(od > '2001', false)), sum(serv), sum(pen), sum(addp), sum(cb),
                   sum(ded) FILTER (WHERE ded > 0), sum(ded) FILTER (WHERE ded < 0)
            FROM y WHERE per GROUP BY nm, left(rr, 7), k"""
    for r in c.execute(sql, {"s": shop, "df": df, "dt": dt, "dfd": d_from}):
        f = lambda k: float(r[k] or 0)
        if r["t"] == "c":
            nm, od = r["nm"], r["g"]
            a = A[(nm, od[:7])]
            a["rev"] += f("rev")
            a["wb"] -= f("comm") + f("ds")
            a["log"] += f("ds")
            a["acq"] -= f("acq")                      
            a["comm"] -= f("comm") - f("acq")
            a["paid"] += f("paid")                    
            a["vw_vat"] += f("vwv")                   
            q = f("qty")
            if q:
                a["qty"] += q
                cu = cost_at(nm, od)
                if cu is None:
                    nocost[nm] += q
                else:
                    a["cost"] -= q * cu
            continue
        a = A[(r["nm"], r["g"])]
        a["wb"] -= f("ds") + f("serv")                
        a["log"] += f("ds")
        a["serv"] += f("serv")
        a["penalty"] -= f("pen")
        a["extra"] += f("addp")
        a["cashback"] -= f("cb")
        k, pos, neg = r["k"], f("dpos"), f("dneg")
        if k == "media":
            a["ads"] -= pos + neg
            a["ads_vat_base"] += pos + neg
        elif k != "promo":
            a["extra"] -= neg
            a[k] -= pos
            if k == "jam":
                a["serv"] += pos
    
    orders = defaultdict(lambda: defaultdict(float))     
    for r in c.execute("""SELECT nm_id, to_char(day,'YYYY-MM') m, sum(coalesce((data->>'ads_upd')::numeric,0)) ads,
                                 sum(coalesce((data->>'orders_sum')::numeric,0)) os, sum(coalesce((data->>'orders')::numeric,0)) o
                          FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY 1,2""", (shop, d_from, d_to)):
        a = A[(r["nm_id"], r["m"])]
        a["ads"] -= float(r["ads"])
        a["ads_vat_base"] += float(r["ads"])
        a["orders_sum"] += float(r["os"])
        a["orders"] += float(r["o"])
        if r["os"] > 0:
            orders[r["m"]][r["nm_id"]] += float(r["os"])
    
    for (nm, m) in [k for k in A if not k[0]]:
        w, a0 = orders.get(m), A[(0, m)]
        tw = sum(w.values()) if w else 0
        if not tw:
            continue
        rest = dict(a0)
        del A[(0, m)]
        for n2, v in w.items():
            for k, x in rest.items():
                A[(n2, m)][k] += x * v / tw
    return {k: dict(v) for k, v in A.items()}, dict(nocost)


def finalize(c, shop: int, cells: dict, nocost: dict, d_to: date, prior_cells: dict | None = None) -> dict:
    """Итоги, налоги и доли из клеток (артикул, месяц)."""
    dt = d_to.isoformat()
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()
    A = {k: defaultdict(float, v) for k, v in cells.items()}
    nm_rows, mon = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for (nm, m), a in A.items():
        for k, x in a.items():
            nm_rows[nm][k] += x
            mon[m][k] += x
    tot = defaultdict(float)
    for a in mon.values():
        for k, x in a.items():
            tot[k] += x
    for m, a in mon.items():
        _finish(a, _tax_at(tax, f"{m}-28"))
    cum = defaultdict(float)          
    prior_months = defaultdict(lambda: defaultdict(float))
    for (_, m), cell in (prior_cells or {}).items():
        for k, x in cell.items():
            prior_months[m][k] += x
    for m, a in prior_months.items():
        t = _tax_at(tax, f"{m}-28")
        if t.get("regime") == pnl_real.IP:
            _finish(a, t, income=False)
            cum[m[:4]] += a["profit"] + a["vat"]
    for m in sorted(mon):
        if _tax_at(tax, f"{m}-28").get("regime") == pnl_real.IP:
            a, prev = mon[m], cum[m[:4]]
            cum[m[:4]] += a["profit"] + a["vat"]
            a["income_tax"] = -(pnl_real.ndfl(max(0.0, cum[m[:4]])) - pnl_real.ndfl(max(0.0, prev)))
            a["profit_tax"] = a["profit"] + a["vat"] + a["income_tax"]
            a["m_tax"] = pnl_real._d(a["profit_tax"], a["orders_sum"])
    tx = _tax_at(tax, dt)
    for a in nm_rows.values():
        _finish(a, tx, income=False)
    _finish(tot, tx, income=False)
    
    tot["vat"] = sum(a["vat"] for a in mon.values())
    tot["income_tax"] = sum(a["income_tax"] for a in mon.values())
    tot["profit_tax"] = tot["profit"] + tot["vat"] + tot["income_tax"]
    tot["m_tax"] = pnl_real._d(tot["profit_tax"], tot["orders_sum"])
    
    nm_month = {}
    for (nm, m), a in A.items():
        nm_month[(nm, m)] = a
        _finish(a, _tax_at(tax, f"{m}-28"), income=False)
    bases_m = defaultdict(dict)
    for (nm, m), a in nm_month.items():
        bases_m[m][nm] = a["profit"] + a["vat"]
    tax_alloc = {m: pnl_real.allocate_income_tax(mon[m]["income_tax"], bases) for m, bases in bases_m.items()}
    for a in nm_rows.values():
        a["vat"] = a["income_tax"] = 0.0
    for (nm, m), a in nm_month.items():
        a["income_tax"] = tax_alloc[m][nm]
        a["profit_tax"] = a["profit"] + a["vat"] + a["income_tax"]
        a["m_tax"] = pnl_real._d(a["profit_tax"], a["orders_sum"])
        nm_rows[nm]["vat"] += a["vat"]
        nm_rows[nm]["income_tax"] += a["income_tax"]
    for a in nm_rows.values():
        a["profit_tax"] = a["profit"] + a["vat"] + a["income_tax"]
        a["m_tax"] = pnl_real._d(a["profit_tax"], a["orders_sum"])
    for a in [tot, *mon.values(), *nm_rows.values(), *nm_month.values()]:
        a["roi"] = pnl_real._d(a["profit"], -a["cost"])
        a["roi_tax"] = pnl_real._d(a["profit_tax"], -a["cost"])
    return {"nm": nm_rows, "month": mon, "nm_month": nm_month, "total": tot, "nocost": dict(nocost), "tax": dict(tx)}


def _tax_at(hist: list[dict], day: str) -> dict:
    cur = None
    for t in hist:
        if t["valid_from"].isoformat() <= day:
            cur = t
    return cur or (hist[0] if hist else {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0, "cost_vat": False})


def vat(a: dict, tax: dict) -> float:
    """НДС к уплате (со знаком «−»), прогноз как в документах WB: с продаж — с суммы, оплаченной покупателем; вычет — НДС вознаграждения
    WB со знаком (отрицательное вознаграждение — компенсация СПП — вычет уменьшает), услуги WB (логистика, хранение, приёмка, реклама,
    Медиа, Джем) — по ставке, закупка — если «себестоимость с НДС». Штрафы, баллы и кэшбэк вычета не дают."""
    reg, r = tax.get("regime") or "", float(tax.get("vat_rate") or 0)
    if not r:
        return 0.0
    k = r / (1 + r)
    out = a["paid"] * k
    ded = a["vw_vat"] + (a["log"] + a["serv"] + a["ads_vat_base"]) * k
    if tax.get("cost_vat"):
        ded += -a["cost"] * k
    return -(out - ded)


def _finish(a: dict, tax: dict, income: bool = True) -> None:
    
    a["commission"], a["acquiring"], a["logistics"] = a["comm"], a["acq"], -a["log"]
    a["services"] = a["wb"] - a["commission"] - a["acquiring"] - a["logistics"]
    a["profit"] = sum(a[k] for k in ("rev", "wb", "cost", "ads", "penalty", "reviews", "cashback", "jam", "other", "extra"))
    a["drr"] = pnl_real._d(-a["ads"], a["orders_sum"])
    a["m_orders"] = pnl_real._d(a["profit"], a["orders_sum"])
    a["m_rev"] = pnl_real._d(a["profit"], a["rev"])
    a["vat"] = vat(a, tax)
    reg, rate = tax.get("regime") or "", float(tax.get("rate") or 0)
    if not income:
        return
    if reg == "ОСНО":
        a["income_tax"] = -rate * max(0.0, a["profit"] + a["vat"])
    elif reg == pnl_real.IP:          
        a["income_tax"] = -pnl_real.ndfl(max(0.0, a["profit"] + a["vat"]))
    elif reg == "УСН доход":
        a["income_tax"] = -rate * max(0.0, a["rev"])
    elif reg == "УСН доходы-расходы":
        a["income_tax"] = -max(rate * max(0.0, a["profit"]), 0.01 * max(0.0, a["rev"]))
    else:
        a["income_tax"] = 0.0
    a["profit_tax"] = a["profit"] + a["vat"] + a["income_tax"]
    a["m_tax"] = pnl_real._d(a["profit_tax"], a["orders_sum"])





import calendar
import json as _json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pnl_alt")
_BUSY: set = set()
_LOCK = threading.Lock()
FRESH_MONTHS = 3
SINCE = date(2025, 10, 1)        


class Pending(Exception):
    """Месяцы считаются в фоне — вкладка покажет «считаю» и обновится сама."""


def _month_end(m: date) -> date:
    return m.replace(day=calendar.monthrange(m.year, m.month)[1])


def _fresh(m: date) -> bool:
    from ..config import today_msk
    t = today_msk().replace(day=1)
    return (t.year - m.year) * 12 + t.month - m.month < FRESH_MONTHS


def _load(c, shop: int, m: date):
    return c.execute("SELECT ver, result, computed_at FROM tab_cache WHERE account_id=%s AND tab='_pnl_alt_m' AND fkey=%s",
                     (shop, m.isoformat()[:7])).fetchone()


def _valid(row, m: date, ver: str) -> bool:
    from .. import tabcache
    from ..config import today_msk
    from ..tabcache import MSK
    if not row or _edits(row["ver"]) != _edits(ver):
        return False
    return not _fresh(m) or row["computed_at"].astimezone(MSK).date() == today_msk()


def _cells(row) -> tuple[dict, dict]:
    r = row["result"]
    return ({(int(k.split("|")[0]), k.split("|")[1]): v for k, v in r["cells"].items()}, {int(k): v for k, v in r["nocost"].items()})


def month_store(c, shop: int, m: date) -> tuple[dict, dict]:
    from .. import tabcache
    ver = tabcache.version(c, shop)
    A, nc = raw(c, shop, m, _month_end(m))
    c.execute("""INSERT INTO tab_cache(account_id,tab,fkey,ver,result,computed_at) VALUES (%s,'_pnl_alt_m',%s,%s,%s,now())
                 ON CONFLICT (account_id,tab,fkey) DO UPDATE SET ver=EXCLUDED.ver, result=EXCLUDED.result, computed_at=now()""",
              (shop, m.isoformat()[:7], ver, _json.dumps({"cells": {f"{k[0]}|{k[1]}": v for k, v in A.items()},
                                                           "nocost": {str(k): v for k, v in nc.items()}})))
    c.commit()
    return A, nc


def _edits(ver: str) -> str:
    """Правки, от которых зависит альт. PnL: журнал (себестоимость, СНО) и группы; настройки пользователей (раскладки, режим рекламы)
    его не меняют — иначе любая смена раскладки у кого-то сбрасывала все месяцы и края периода."""
    p = ver.split("|")
    return f"{p[2]}|{p[-1]}" if len(p) >= 5 else ver


def _part_get(c, shop: int, a: date, b: date, ver: str):
    """Край периода (не целый месяц) из кэша — держим до конца дня, пока нет правок."""
    from ..config import today_msk
    from ..tabcache import MSK
    row = c.execute("SELECT ver, result, computed_at FROM tab_cache WHERE account_id=%s AND tab='_pnl_alt_p' AND fkey=%s", (shop, f"{a}|{b}")).fetchone()
    if row and _edits(row["ver"]) == _edits(ver) and row["computed_at"].astimezone(MSK).date() == today_msk():
        return _cells(row)
    return None


def _part(c, shop: int, a: date, b: date, ver: str) -> tuple[dict, dict]:
    """Край периода: считаем и кладём в кэш — три вкладки блока и повторные открытия не считают заново."""
    from .. import tabcache
    A, nc = raw(c, shop, a, b)
    if not tabcache._readonly(c):
        c.execute("""INSERT INTO tab_cache(account_id,tab,fkey,ver,result,computed_at) VALUES (%s,'_pnl_alt_p',%s,%s,%s,now())
                     ON CONFLICT (account_id,tab,fkey) DO UPDATE SET ver=EXCLUDED.ver, result=EXCLUDED.result, computed_at=now()""",
                  (shop, f"{a}|{b}", ver, _json.dumps({"cells": {f"{k[0]}|{k[1]}": v for k, v in A.items()}, "nocost": {str(k): v for k, v in nc.items()}})))
        c.commit()
    return A, nc


def _bg(shop: int, months: list[date], edges: list[tuple[date, date]] = ()):
    from .. import db, tabcache
    try:
        with db.connect(timeout_s=1800) as c:
            if not c.execute("SELECT pg_try_advisory_lock(hashtext(%s)) ok", (f"pnl_alt:{shop}",)).fetchone()["ok"]:
                return
            for a, b in edges:
                _part(c, shop, a, b, tabcache.version(c, shop))
            for m in months:
                month_store(c, shop, m)
    except Exception:  
        pass
    finally:
        with _LOCK:
            _BUSY.discard(shop)






def _cached_raw(c, shop: int, d_from: date, d_to: date) -> tuple[dict, dict]:
    """Месяцы и края периода — из кэша; отсутствующие или изменённые ручной правкой считаем в фоне (Pending).
    Старые месяцы с теми же ручными данными можно показать до фонового обновления свежих источников."""
    from .. import tabcache
    ver = tabcache.version(c, shop)
    A, nocost, todo, missing = {}, {}, [], 0
    parts, edges = [], []
    m = d_from.replace(day=1)
    while m <= d_to:
        a, b = max(m, d_from), min(_month_end(m), d_to)
        if a == m and b == _month_end(m):
            row = _load(c, shop, m)
            if row and _valid(row, m, ver):
                parts.append(_cells(row))
            else:
                todo.append(m)
                if row and _edits(row["ver"]) == _edits(ver):
                    parts.append(_cells(row))       
                else:
                    missing += 1
        else:
            got = _part_get(c, shop, a, b, ver)
            if got:
                parts.append(got)
            else:
                edges.append((a, b))
        m = (m + timedelta(days=32)).replace(day=1)
    if todo or edges:
        with _LOCK:
            go = shop not in _BUSY
            _BUSY.add(shop)
        if go:
            _POOL.submit(_bg, shop, todo, edges)
        if missing or edges:
            raise Pending
    for cells, nc in parts:
        A.update(cells)
        for k, v in nc.items():
            nocost[k] = nocost.get(k, 0) + v
    return A, nocost


def cached(c, shop: int, d_from: date, d_to: date) -> dict:
    """Visible rows plus cabinet YTD context; cold months are always queued, never scanned in HTTP."""
    prior = {}
    
    if _needs_year_context(c, shop, d_from, d_to):
        prior, _ = _cached_raw(c, shop, date(d_from.year, 1, 1), d_from - timedelta(days=1))
    A, nocost = _cached_raw(c, shop, d_from, d_to)
    return finalize(c, shop, A, nocost, d_to, prior)


def precompute(c, shop: int, log=print) -> None:
    """Утренний предрасчёт: месяцы с октября 2025 — свежие пересчитываем, старые — только если менялись себестоимость/СНО/группы."""
    import time
    from .. import tabcache
    from ..config import today_msk
    ver = tabcache.version(c, shop)
    
    m = SINCE.replace(month=1) if _needs_year_context(c, shop, SINCE, today_msk()) else SINCE
    t0, n = time.time(), 0
    while m <= today_msk():
        if not _valid(_load(c, shop, m), m, ver):
            month_store(c, shop, m)
            n += 1
        m = (m + timedelta(days=32)).replace(day=1)
    d1 = today_msk()            
    d0 = d1 - timedelta(days=29)
    y = d1 - timedelta(days=1)  
    for a, b in ((d0, min(_month_end(d0), d1)), (max(d1.replace(day=1), d0), d1), (y.replace(day=1), y)):
        if not (a.day == 1 and b == _month_end(a)) and not _part_get(c, shop, a, b, ver):
            _part(c, shop, a, b, ver)
    log(f"  альт PnL по месяцам: пересчитано {n}, {time.time() - t0:.1f} с")

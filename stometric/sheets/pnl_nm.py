"""Self-hosted application component."""

from collections import defaultdict
from datetime import date, timedelta

from ..agg import real_week
from . import pnl_real

NONE_TAX = {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
COLS = [(4, "Сумма продаж до скидки ВБ (СПП), руб", "money"), (5, "Оплачено покупателем, руб", "money"), (6, "кол-во продаж Всего, шт", "int"),
        (10, "выкупы, руб", "money"), (11, "кол-во выкупов, шт", "int"), (12, "возвраты, руб", "money"), (13, "кол-во возвратов, шт", "int"),
        (7, "средний процент выкупа, %", "share"), (14, "ИТОГО К ОПЛАТЕ, руб", "money"), (15, "К перечислению за товар Всего, руб", "money"),
        (17, "выкуплено товаров, руб", "money"), (18, "прочие возмещения и компенсации (продажи), руб", "money"),
        (19, "возврат товаров, руб", "money"), (20, "прочие возмещения и компенсации (возвраты), руб", "money"), (25, "Эквайринг", "money"),
        (28, "Логистика ВСЕГО, руб", "money"), (8, "среднее значение логистики на ед. продаж, руб", "money"),
        (31, "логистика при продажах, руб", "money"), (32, "кол-во доставок при продажах, шт", "int"),
        (34, "логистика при возвратах, руб", "money"), (35, "кол-во доставок при возвратах, шт", "int"),
        (37, "прочие расходы/компенсации логистики", "money"), (33, "средняя логистика на ед. при продажах, руб", "money"),
        (36, "средняя логистика на ед. при возвратах, руб", "money"), (38, "Штрафы, руб", "money"),
        (39, "Корректировка Вознаграждения Вайлдберриз (ВВ), руб", "money"), (45, "Платная приёмка, руб", "money"),
        (41, "Прочие удержания / выплаты ВСЕГО, руб", "money"), (40, "Хранение, руб", "money"), (46, "Реклама", "money"),
        (47, "СЕБЕСТОИМОСТЬ В ПРОДАЖАХ ВСЕГО, руб", "money"), (49, "себестоимость в выкупах, руб", "money"),
        (50, "себестоимость в возвратах, руб", "money"), (51, "МАРЖИНАЛЬНАЯ ПРИБЫЛЬ", "money"), (52, "маржинальная рентабельность, %", "share"),
        (53, "НАЛОГ, руб", "money"), (55, "НДС к начислению", "money"), (56, "НДС к вычету", "money"), (54, "Налог УСН / на прибыль", "money"),
        (57, "ПРИБЫЛЬ за минусом налога", "money"), (58, "рентабельность за минусом налога, %", "share")]
RATIO = {7, 8, 33, 36, 52, 58}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _tax_at(hist: list[dict], day: str) -> dict:
    """Настройка СНО на дату; раньше первой записи — первая (её обычно вносят задним числом)."""
    cur = None
    for t in hist:                       
        if t["valid_from"].isoformat() <= day:
            cur = t
    return cur or (hist[0] if hist else NONE_TAX)


def compute(c, shop: int, d_from: date, d_to: date, nm_ids: list[int] | None = None) -> dict:
    hist = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()
    
    
    has_ip = any(t["regime"] == pnl_real.IP for t in hist)
    context_from = date(d_from.year, 1, 1) if has_ip else d_from
    W = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))      
    ads_w = defaultdict(float)                                           
    week_to = {}
    for g in real_week.cached(c, shop, context_from, d_to):
        if not g["date_from"] or g["date_to"] < context_from.isoformat() or g["date_from"] > d_to.isoformat():
            continue
        w = g["date_from"]
        week_to[w] = g["date_to"]
        bt = g["bonus_type"] or ""
        if ("Продвижение" in bt or "Медиа" in bt) and not g["nm_id"]:
            ads_w[w] += g["deduction"]
            W[w]       
            continue
        pnl_real.accumulate(W[w][g["nm_id"] or 0], g)
    if not week_to:
        return {"rows": [], "total": None, "weeks": []}
    lo, hi = min(week_to), max(week_to.values())
    acct = pnl_real.ads_fact(c, shop, lo, hi, only="Счет")             
    for w, wt in week_to.items():
        ads_w[w] += pnl_real.days_sum(acct, w, wt)
    upd = defaultdict(lambda: defaultdict(float))                        
    for r in c.execute("""SELECT nm_id, day, (data->>'ads_upd')::numeric s FROM agg_nm_day
                          WHERE account_id=%s AND day BETWEEN %s AND %s AND coalesce((data->>'ads_upd')::numeric, 0) <> 0""", (shop, lo, hi)):
        upd[_monday(r["day"]).isoformat()][r["nm_id"]] += float(r["s"])

    def spread(dst: dict, total: float, weights: dict[int, float], key: str = "") -> bool:
        tw = sum(v for v in weights.values() if v > 0)
        if not tw:
            return False
        for nm, v in weights.items():
            if v > 0:
                if key:
                    dst[nm][key] += total * v / tw
                else:
                    for k, x in total.items():
                        dst[nm][k] += x * v / tw
        return True

    S = defaultdict(lambda: defaultdict(float))       
    A = defaultdict(lambda: defaultdict(float))       
    cumulative = defaultdict(float)
    for w, per in sorted(W.items()):
        sales = {nm: a["retail_s"] - a["retail_r"] for nm, a in per.items() if nm}
        rest = dict(per.pop(0, {}))
        if rest and not spread(per, rest, sales):
            per[0] = defaultdict(float, rest)
        if ads_w.get(w):
            if not (spread(per, ads_w[w], upd.get(w) or {}, "ads") or spread(per, ads_w[w], sales, "ads")):
                per[0]["ads"] += ads_w[w]
        tax = _tax_at(hist, week_to[w])
        calculated = {nm: pnl_real.calc(a, tax) for nm, a in per.items()}
        if tax["regime"] == pnl_real.IP:
            bases = {nm: r[51] + r[55] + r[56] for nm, r in calculated.items()}
            y = w[:4]
            prev = cumulative[y]
            cumulative[y] += sum(bases.values())
            income = -(pnl_real.ndfl(max(0.0, cumulative[y])) - pnl_real.ndfl(max(0.0, prev)))
            for nm, v in pnl_real.allocate_income_tax(income, bases).items():
                r = calculated[nm]
                r[54] = v
                r[53] = v + r[55] + r[56]
                r[57] = r[51] + r[53]
        if week_to[w] < d_from.isoformat() or w > d_to.isoformat():
            continue
        for nm, a in per.items():
            R = calculated[nm]
            for n, _, _ in COLS:
                if n not in RATIO:
                    S[nm][n] += R[n]
            for k, x in a.items():
                A[nm][k] += x
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, subject FROM nomenclature WHERE account_id=%s", (shop,))}

    def ratios(s, a):
        R = pnl_real.calc(a, NONE_TAX)
        s.update({7: R[7], 8: R[8], 33: R[33], 36: R[36], 52: pnl_real._d(s[51], s[4]), 58: pnl_real._d(s[57], s[4])})
        return s

    rows, tot_s, tot_a = [], defaultdict(float), defaultdict(float)
    for nm in S:
        if nm_ids and nm not in nm_ids:
            continue
        s = ratios(S[nm], A[nm])
        if not any(abs(s[n]) > 0.005 for n, _, _ in COLS if n not in RATIO):
            continue
        n = nom.get(nm) or {}
        rows.append({"vendor_code": n.get("vendor_code") if nm else "Без артикула (разложить не на что)", "nm_id": nm or None,
                     "subject": n.get("subject"), **{f"r{k}": v for k, v in s.items()}})
        for k, v in S[nm].items():
            tot_s[k] += v
        for k, v in A[nm].items():
            tot_a[k] += v
    rows.sort(key=lambda r: (r["nm_id"] is None, -(r["r4"] or 0)))
    total = {"vendor_code": "ИТОГО", **{f"r{k}": v for k, v in ratios(tot_s, tot_a).items()}} if rows else None
    weeks = sorted(w for w in week_to if week_to[w] >= d_from.isoformat() and w <= d_to.isoformat())
    return {"rows": rows, "total": total, "weeks": [weeks[0], week_to[weeks[-1]]] if weeks else []}

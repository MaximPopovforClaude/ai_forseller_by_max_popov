"""Self-hosted application component."""

from collections import defaultdict

from ..agg import real_week



EXPENSE_ITEMS = [
    ("Реклама", "", "Продвижение"), ("Медиа", "", "Медиа"), ("Джем", "", "Джем"), ("Витрина Магазина", "", "Витрина"),
    ("Списания за отзыв", "", "Списание за отзыв"),
    ("Cписания по программам и акциям лояльности", "Сумма баллов, удержанных за покупку товаров", ""),
    ("Cписания по программам и акциям лояльности", 'Сумма баллов, удержанных в рамках акции "кешбэк за отзывы и вайбы"', ""),
    ("Cписания по программам и акциям лояльности", "Стоимость участия в программе лояльности", ""),
    ("Cписания по программам и акциям лояльности", "Сумма удержанная за начисленные баллы", ""),
    ("Cписания по программам и акциям лояльности", "", "Компенсация скидки по программе лояльности"),
    ("Cписания по программам и акциям лояльности", "", "Коррекция суммы удержанной за начисленные баллы"),
    ("Утилизация товара", "", "утилизац"), ("Перенос карточек товара", "", "Перенос карточек товара"),
    ("Перенос карточек товара", "", "подготовке карточек к переносу"), ("Перевод на баланс заёмщика", "", "Перевод на баланс заёмщика"),
    ("Программа сотрудничества", "", "Программе сотрудничества"), ("Транзитные поставки", "", "транзитных поставок"),
    ("Штраф за отгрузку", "Штраф", "Отгрузка"), ("Штраф за платное хранение возвратов", "Штраф", "Платное хранение возвратов"),
    ("Штраф за невыполненный заказ", "Штраф", "Невыполненный заказ"),
    ("Штраф за занижение габаритов упаковки", "Штраф", "Занижение фактических габаритов"),
    ("Штраф за подмену товаров", "Штраф", "Подмена товара"), ("Штраф за недовоз по поставке", "Штраф", "недовоз"),
]


def expense_item(oper: str, bonus: str) -> str:
    o, b = (oper or "").lower(), (bonus or "").lower()
    for name, om, bm in EXPENSE_ITEMS:
        if (not om or om.lower() in o) and (not bm or bm.lower() in b):
            return name
    return f"Прочее: {bonus or oper or '—'}"


def _d(a, b):
    return a / b if b else 0


IP = "ОСНО ИП (НДФЛ)"      
NDFL_SCALE = [(2_400_000, 0.13), (5_000_000, 0.15), (20_000_000, 0.18), (50_000_000, 0.20), (float("inf"), 0.22)]   


def ndfl(base: float) -> float:
    """НДФЛ с годовой базы (доходы − профессиональные вычеты), шкала 13–22 %."""
    tax, lo = 0.0, 0.0
    for hi, r in NDFL_SCALE:
        if base <= lo:
            break
        tax += (min(base, hi) - lo) * r
        lo = hi
    return tax


def allocate_income_tax(total: float, bases: dict) -> dict:
    """Allocate one cabinet tax, preserving its sum (negative=charge, positive=refund).

    Existing PnL allocates charges to positive profit. For a loss-driven refund use
    negative bases; if no base has that sign, fall back to absolute nonzero bases.
    """
    weights = {k: max(0.0, v if total <= 0 else -v) for k, v in bases.items()}
    if not sum(weights.values()):
        weights = {k: abs(v) for k, v in bases.items()}
    if not sum(weights.values()):
        weights = {k: 1.0 for k in bases}
    den = sum(weights.values())
    out = {k: total * w / den if den else 0.0 for k, w in weights.items()}
    if out:
        key = max(weights, key=weights.get)
        out[key] += total - sum(out.values())
    return out


def ytd_ndfl(R: dict, periods: list[str], is_ip) -> None:
    """НДФЛ ИП нарастающим итогом с начала года: налог периода = НДФЛ(база с 1 января по период) − НДФЛ(по прошлый период).
    База — прибыль после НДС (строки 51 + 55 + 56); убыток уменьшает базу года, а не даёт налог к возврату за его пределами."""
    cum = defaultdict(float)
    for p in sorted(periods):
        if not is_ip(p):
            continue
        y = p[:4]
        prev = cum[y]
        cum[y] += R[p][51] + R[p][55] + R[p][56]
        R[p][54] = -(ndfl(max(0.0, cum[y])) - ndfl(max(0.0, prev)))
        R[p][53] = R[p][54] + R[p][55] + R[p][56]
        R[p][57] = R[p][51] + R[p][53]
        R[p][58] = _d(R[p][57], R[p][4])


def accumulate(a: dict, g: dict) -> str:
    """Строка агрегата БД#РеализацияПонедельно → суммы a (общие для недели, месяца, артикула). Возвращает тип бонуса."""
    doc, op = (g["doc_type"] or "").lower(), (g["oper"] or "").lower()
    sale, ret = doc == "продажа", doc == "возврат"
    if sale and op == "продажа":
        a["retail_disc_s"] += g["retail_disc"]; a["retail_s"] += g["retail_amount"]; a["qty_s"] += g["qty"]
        a["forpay_s"] += g["for_pay"]; a["acq_s"] += g["acquiring"]; a["cost_s"] += g["cost"] or 0
    if sale and op != "продажа":
        a["forpay_s_other"] += g["for_pay"]
    if ret and op == "возврат":
        a["retail_disc_r"] += g["retail_disc"]; a["retail_r"] += g["retail_amount"]; a["qty_r"] += g["qty"]
        a["forpay_r"] += g["for_pay"]; a["acq_r"] += g["acquiring"]; a["cost_r"] += g["cost"] or 0
    if ret and op != "возврат":
        a["forpay_r_other"] += g["for_pay"]
    a["log_sales"] += g["log_sales"]; a["log_returns"] += g["log_returns"]; a["rebill"] += g["rebill_log"]
    if op == "логистика":
        a["deliv_s"] += g["deliveries"]; a["deliv_r"] += g["returns"]
    a["penalty"] += g["penalty"]; a["additional"] += g["additional"]; a["storage"] += g["storage"]; a["acceptance"] += g["acceptance"]
    bt = g["bonus_type"] or ""
    if "Продвижение" in bt or "Медиа" in bt:
        a["ads"] += g["deduction"]
        if "Медиа" in bt:
            a["media"] += g["deduction"]      
    else:
        a["deduction"] += g["deduction"]
        if g["deduction"] < 0:
            a["ded_pay"] += g["deduction"]
        elif g["deduction"] > 0:
            a["ded_hold"] += g["deduction"]
    return bt


def calc(a: dict, tax: dict) -> dict:
    """Строки листа (номер строки → значение) из сумм a — формулы эталона."""
    r4 = a["retail_disc_s"] - a["retail_disc_r"]
    r10, r12 = a["retail_s"], -a["retail_r"]
    r5 = r10 + r12
    r17, r18, r19, r20 = a["forpay_s"], a["forpay_s_other"], -a["forpay_r"], -a["forpay_r_other"]
    r15 = r17 + r18 + r19 + r20
    r25 = -(a["acq_s"] - a["acq_r"])
    r31, r34, r37 = -a["log_sales"], -a["log_returns"], -a["rebill"]
    r28 = r31 + r34 + r37
    r38, r39, r40 = -a["penalty"], -a["additional"], -a["storage"]
    r41, r43, r44, r45, r46 = -a["deduction"], -a["ded_pay"], -a["ded_hold"], -a["acceptance"], -a["ads"]
    r14 = r15 + r28 + r38 + r39 + r40 + r41 + r45 + r46
    r49, r50 = a["cost_s"], -a["cost_r"]
    r47 = r49 + r50
    r51 = r14 - r47
    r21 = -(r4 - (r17 + r19 - r25))
    r23 = -(r5 - (r17 + r19 - r25))
    reg, rate = tax["regime"], float(tax["rate"])
    vat_rate, vat_wb = float(tax["vat_rate"]), float(tax["vat_deduct_wb"])
    r55 = -(r10 + r12) * vat_rate / (1 + vat_rate) if vat_rate else 0.0
    base = r5 + r55 + r18 + r20 + (r23 if r23 > 0 else 0)
    r56 = 0.0 if "УСН" in reg else vat_wb / (1 + vat_wb) * (r23 + r28 + r39 + r40 + r41 + r45 + r46) * -1   
    if tax.get("cost_vat") and "УСН" not in reg and vat_rate:     
        r56 += r47 * vat_rate / (1 + vat_rate)
    if reg == "УСН доход":
        r54 = -rate * base
    elif reg == "УСН доходы-расходы":
        prof = r51 + r55
        r54 = -(max(rate * prof, base * 0.01) if prof > 0 else 0)
    elif reg == "ОСНО":         
        r54 = -rate * max(0.0, r51 + r55 + r56)
    elif reg == IP:             
        r54 = -ndfl(max(0.0, r51 + r55 + r56))
    else:
        r54 = -rate * (max(r5, r15 - r25) + r55)
    r53 = r54 + r55 + r56
    return {4: r4, 5: r5, 6: a["qty_s"] - a["qty_r"], 10: r10, 11: a["qty_s"], 12: r12, 13: -a["qty_r"], 14: r14, 15: r15,
            17: r17, 18: r18, 19: r19, 20: r20, 21: r21, 22: _d(-r21, r4), 23: r23, 24: _d(-r23, r4), 25: r25, 26: _d(-r25, r5),
            27: _d(-r25, r4), 28: r28, 29: _d(-r28, r4), 31: r31, 32: a["deliv_s"], 33: _d(-r31, a["deliv_s"]), 34: r34,
            35: a["deliv_r"], 36: _d(-r34, a["deliv_r"]), 37: r37, 38: r38, 39: r39, 40: r40, 41: r41, 43: r43, 44: r44, 45: r45,
            46: r46, 47: r47, 49: r49, 50: r50, 51: r51, 52: _d(r51, r4), 53: r53, 54: r54, 55: r55, 56: r56, 57: r51 + r53,
            58: _d(r51 + r53, r4), 7: _d(a["deliv_s"] - a["deliv_r"], a["deliv_s"]), 8: _d(-r28, a["qty_s"] - a["qty_r"])}


def ads_fact(c, shop: int, d_from: str, d_to: str, only: str | None = None) -> dict[str, float]:
    """Реклама по факту открутки: списания по УПД кампаний (баланс и счёт; бонусы-кэшбэк — не деньги) по дням → {день: сумма}.
    only="Счет" — только оплаченное со счёта (в отчёте реализации его нет)."""
    return {r["d"].isoformat(): float(r["s"]) for r in c.execute(
        """SELECT row_date d, sum((data->>'updSum')::numeric) s FROM raw_rows WHERE account_id=%s AND source='ad_upd'
           AND row_date BETWEEN %s AND %s AND coalesce(data->>'paymentType','') <> 'Кэшбэк'
           AND (%s::text IS NULL OR data->>'paymentType' = %s) GROUP BY 1""", (shop, d_from, d_to, only, only))}


def days_sum(day: dict[str, float], a: str, b: str) -> float:
    from datetime import date as _dt, timedelta as _td
    d0, d1 = _dt.fromisoformat(a[:10]), _dt.fromisoformat(b[:10])
    return sum(day.get((d0 + _td(days=i)).isoformat(), 0.0) for i in range((d1 - d0).days + 1))


def compute(c, shop: int, weeks: int = 12, monthly: bool = False, ads_mode: str = "deduct") -> dict:
    """ads_mode: deduct — реклама = удержания «Продвижение»/«Медиа» в отчёте реализации (как в эталоне); fact — по факту открутки (УПД)."""
    groups = real_week.cached(c, shop)
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from DESC LIMIT 1", (shop,)).fetchone()\
        or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    key = (lambda g: g["date_from"][:7]) if monthly else (lambda g: g["date_from"])
    periods = {key(g) for g in groups if g["date_from"]}
    per = sorted(periods, reverse=True)[:weeks]
    shown = list(per)
    years_needed = {p[:4] for p in shown}
    
    per = sorted({p for p in periods if p[:4] in years_needed}, reverse=True)
    included = set(per)
    A = defaultdict(lambda: defaultdict(float))
    WK = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))     
    wk_to = {}
    items = defaultdict(lambda: defaultdict(float))
    expense_names = {}
    for g in groups:
        p = key(g)
        if p not in included:
            continue
        if monthly:
            accumulate(WK[p][g["date_from"]], g)
        wk_to[g["date_from"]] = g["date_to"]
        bt = accumulate(A[p], g)
        if not (g["penalty"] or g["additional"] or g["deduction"]):
            continue
        expense_key = (g["oper"], bt)
        if expense_key not in expense_names:
            expense_names[expense_key] = expense_item(*expense_key)
        art = expense_names[expense_key]
        for fld in ("penalty", "additional", "deduction"):
            if g[fld]:
                items[art][p] += g[fld]
    if not monthly:
        
        
        for p, amounts in A.items():
            WK[p][p] = amounts.copy()
    rows = []

    def row(n, label, fn, fmt="money"):
        vals = {p: fn(A[p], p) for p in per}
        rows.append({"row": n, "label": label, "fmt": fmt, **vals})
        return vals

    if ads_mode == "fact" and wk_to:
        day = ads_fact(c, shop, min(wk_to), max(wk_to.values()))
        for p in per:
            A[p]["ads"] = 0.0
            for w in WK[p]:
                WK[p][w]["ads"] = days_sum(day, w, wk_to[w]) + WK[p][w]["media"]
                A[p]["ads"] += WK[p][w]["ads"]
    elif wk_to:     
        day = ads_fact(c, shop, min(wk_to), max(wk_to.values()), only="Счет")
        for p in per:
            for w in WK[p]:
                x = days_sum(day, w, wk_to[w])
                WK[p][w]["ads"] += x
                A[p]["ads"] += x
    hist = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()

    def tax_at(day: str) -> dict:
        """СНО на дату: последняя запись с началом не позже; раньше первой записи — первая."""
        cur = None
        for t in hist:
            if t["valid_from"].isoformat() <= day:
                cur = t
        return cur or (hist[0] if hist else tax)

    R = {}
    for p in per:
        taxes = {w: tax_at(wk_to[w]) for w in WK[p]}
        R[p] = calc(A[p], next(iter(taxes.values())) if taxes else tax)
        if len({id(t) for t in taxes.values()}) > 1:      
            for n in (53, 54, 55, 56):
                R[p][n] = sum(calc(WK[p][w], t)[n] for w, t in taxes.items())
            R[p][57] = R[p][51] + R[p][53]
            R[p][58] = _d(R[p][57], R[p][4])
    
    
    weekly = {w: calc(a, tax_at(wk_to[w])) for weeks_ in WK.values() for w, a in weeks_.items()}
    ytd_ndfl(weekly, list(weekly), lambda w: tax_at(wk_to[w])["regime"] == IP)
    for p in per:
        if any(tax_at(wk_to[w])["regime"] == IP for w in WK[p]):
            for n in (53, 54, 55, 56):
                R[p][n] = sum(weekly[w][n] for w in WK[p])
            R[p][57] = R[p][51] + R[p][53]
            R[p][58] = _d(R[p][57], R[p][4])
    per = shown
    years = []
    if monthly:      
        for y in sorted({p[:4] for p in per}, reverse=True):
            ms = [p for p in per if p[:4] == y]
            Y = f"Y{y}"
            for p in ms:
                for k, v in A[p].items():
                    A[Y][k] += v
            R[Y] = calc(A[Y], tax_at(f"{y}-12-31"))
            for n in (53, 54, 55, 56):
                R[Y][n] = sum(R[p].get(n, 0) for p in ms)
            R[Y][57] = R[Y][51] + R[Y][53]
            R[Y][58] = _d(R[Y][57], R[Y][4])
            for vals in items.values():
                vals[Y] = sum(vals.get(p, 0) for p in ms)
            years.append((Y, f"{y}, итого" if len(ms) == 12 else f"{y}, итого ({ms[-1][5:7]}–{ms[0][5:7]})"))
    LAB = [(4, "Сумма продаж до скидки ВБ (СПП), руб", "money"), (5, "ПРОДАЖА ВСЕГО (оплачено покупателем), руб", "money"),
           (6, "кол-во продаж Всего, шт", "int"), (7, "средний процент выкупа, %", "pct"),
           (8, "среднее значение логистики на ед. продаж, руб", "money"), (10, "выкупы, руб", "money"), (11, "кол-во выкупов, шт", "int"),
           (12, "возвраты, руб", "money"), (13, "кол-во возвратов, шт", "int"), (14, "ИТОГО К ОПЛАТЕ, руб", "money"),
           (15, "К перечислению за товар Всего, руб", "money"), (17, "выкуплено товаров, руб", "money"),
           (18, "прочие возмещения и компенсации (продажи), руб", "money"), (19, "возврат товаров, руб", "money"),
           (20, "прочие возмещения и компенсации (возвраты), руб", "money"), (21, "Расчетная комиссия WB, руб", "money"),
           (22, "Расчетная комиссия WB, %", "pct"), (23, "Фактическая комиссия за минусом скидки ВБ (СПП), руб", "money"),
           (24, "Фактическая комиссия WB, %", "pct"), (25, "Эквайринг, руб", "money"),
           (26, "Эквайринг, в % от суммы выкупов (оплачено покупателем)", "pct"), (27, "Эквайринг, в % от суммы выкупов ДО скидки ВБ (СПП)", "pct"),
           (28, "Логистика ВСЕГО, руб", "money"), (29, "Логистика, в % от суммы выкупов ДО скидки ВБ (СПП)", "pct"),
           (31, "логистика при продажах, руб", "money"), (32, "кол-во доставок при продажах, шт", "int"),
           (33, "средняя логистика на ед. при продажах, руб", "money"), (34, "логистика при возвратах, руб", "money"),
           (35, "кол-во доставок при возвратах, шт", "int"), (36, "средняя логистика на ед. при возвратах, руб", "money"),
           (37, "прочие расходы/компенсации логистики", "money"), (38, "Штрафы, руб", "money"),
           (39, "Корректировка Вознаграждения Вайлдберриз (ВВ), руб", "money"), (40, "Хранение, руб", "money"),
           (41, "Прочие удержания/выплаты ВСЕГО, руб", "money"), (43, "Прочие выплаты, руб", "money"), (44, "Прочие удержания, руб", "money"),
           (45, "Платная приемка, руб", "money"), (46, "Реклама + Медиа, руб" + (" (по факту открутки, УПД; Медиа — из отчёта)" if ads_mode == "fact" else " (удержания WB + оплата со счёта по УПД)"), "money"), (47, "СЕБЕСТОИМОСТЬ В ПРОДАЖАХ ВСЕГО, руб", "money"),
           (49, "себестоимость в выкупах, руб", "money"), (50, "себестоимость в возвратах, руб", "money"),
           (51, "Маржинальная прибыль за минусом возвратов до налогов, руб", "money"), (52, "маржинальная рентабельность, %", "pct"),
           (53, f"НАЛОГ, руб ({tax['regime']})", "money"), (54, "Налог УСН / налог на прибыль (ОСНО) / НДФЛ (ИП)", "money"), (55, "НДС к начислению", "money"),
           (56, "НДС к вычету", "money"), (57, "ПРИБЫЛЬ за минусом налога", "money"), (58, "рентабельность за минусом налога, %", "pct")]
    for n, lab, fmt in LAB:
        rows.append({"row": n, "label": lab, "fmt": fmt, **{p: R[p].get(n, 0) for p in [*per, *(y for y, _ in years)]}})
    rows.append({"row": 62, "label": "РАСШИФРОВКА РАСХОДОВ (удержания, штрафы, доплаты по статьям)", "fmt": "h"})
    order = list(dict.fromkeys(n for n, _, _ in EXPENSE_ITEMS))
    for art in order + sorted(a for a in items if a not in order):     
        vals = items.get(art, {})
        rows.append({"row": None, "label": art, "fmt": "money", **{p: vals.get(p, 0) for p in [*per, *(y for y, _ in years)]}})
    return {"periods": per, "years": years, "rows": rows, "tax": tax["regime"]}

"""Self-hosted application component."""

import calendar
import math
from ..config import today_msk
from datetime import date, timedelta
from decimal import Decimal

from ..agg import nm_day


ROWS = [
    (6, "ЗАКАЗЫ И ПОТЕНЦИАЛЬНАЯ ПРИБЫЛЬ ПО ЗАКАЗАМ", "h", None),
    (7, "Сумма заказов с учетом скидки продавца, руб", "money", lambda S, R: S("orders_sum")),
    (8, "Заказы: количество заказов, шт", "int", lambda S, R: S("orders")),
    (9, "Сумма заказов с учетом скидки ВБ (СПП), руб", "money", lambda S, R: S("orders_sum_spp")),
    (10, "Средняя цена заказа с учетом скидки продавца, руб", "money", lambda S, R: _d(R(7), R(8))),
    (11, "Средняя СПП, %", "pct", lambda S, R: _d(R(7) - R(9), R(7))),
    (12, "Заказы в ЛК: Конверсии (заказали на сумму), руб", "money", lambda S, R: S("f_orders_sum")),
    (13, "Конверсии (заказали товаров)", "int", lambda S, R: S("f_orders")),
    (14, "Общий процент выкупа по всем товарам", "pct", "buyout_pct"),
    (15, "Сумма заказов с учетом процента выкупа, руб", "money", lambda S, R: R(7) * R(14)),
    (16, "Количество заказов с учетом процента выкупа, шт", "int", lambda S, R: round(R(8) * R(14))),
    (17, "Сумма заказов с учетом скидки ВБ (СПП) и процента выкупа, руб", "money", lambda S, R: R(9) * R(14)),
    (18, "Маржа по заказам с учётом процента выкупа, руб", "money", lambda S, R: R(15) + R(20) + R(21) - R(22)),
    (19, "Маржа по заказам с учётом процента выкупа, %", "pct", lambda S, R: _d(R(18), R(15))),
    (20, "Сумма комиссии по оферте с учётом процента выкупа, руб", "money", lambda S, R: -S("commission_offer_orders") * R(14)),
    (21, "Сумма расходов на логистику по заказам, руб", "money", lambda S, R: -S("logistics_orders")),
    (22, "Сумма себестоимости с учётом процента выкупа, руб", "money", lambda S, R: S("cost_orders") * R(14)),
    (23, "Расходы на рекламу (из УПД), руб", "money", lambda S, R: -S("ads_upd")),
    (24, "ДРР от суммы заказов с учетом скидки продавца, %", "pct", lambda S, R: _d(-R(23), R(7))),
    (25, "ДРР от суммы заказов с учетом процента выкупа, %", "pct", lambda S, R: _d(-R(23), R(15))),
    (26, "ДРР от прибыли, %", "pct", lambda S, R: _d(-R(23), R(35))),
    
    (231, "Реклама бонусами (Кэшбэк), руб", "money", lambda S, R: -S("ads_bonus")),
    (232, "Реклама всего: деньги + бонусы, руб", "money", lambda S, R: R(23) + R(231)),
    (233, "ДРР от суммы заказов: бонусы, %", "pct", lambda S, R: _d(-R(231), R(7))),
    (234, "ДРР от суммы заказов: всего (деньги + бонусы), %", "pct", lambda S, R: _d(-R(232), R(7))),
    (27, "Другие расходы WB", "money", lambda S, R: R(28) + R(29)),
    (28, "Платное хранение, руб", "money", lambda S, R: -S("storage")),
    (29, "Платная приемка, руб", "money", lambda S, R: -S("acceptance_sum")),
    (30, "ВСЕГО НАЛОГ по всем заказам с учётом процента выкупа, руб", "money", lambda S, R: R(32) + R(33) + R(34)),
    (31, "ВСЕГО НАЛОГ по всем заказам с учётом процента выкупа, %", "pct", lambda S, R: _d(-R(30), R(17))),
    (32, "Налог по заказам (СНО, оценка за период), руб", "money", "tax_orders"),
    (33, "Сумма НДС к начислению с заказов, руб", "money", lambda S, R: -S("vat_orders") * R(14)),
    (34, "Сумма НДС к вычету, руб", "money", "vat_deduct_orders"),
    (35, "Прибыль по заказам с учетом % выкупа за минусом налога, руб", "money", lambda S, R: R(18) + R(23) + R(27) + R(30)),
    (36, "Прибыль по заказам с учетом % выкупа за минусом налога, %", "pct", lambda S, R: _d(R(35), R(15))),
    (37, "ВЫКУПЫ И ОПЕРАТИВНАЯ ПРИБЫЛЬ БЕЗ УЧЕТА ВОЗВРАТОВ", "h", None),
    (38, "Сумма выкупов ДО скидки ВБ (СПП), руб", "money", lambda S, R: S("buyouts_sum_before_spp")),
    (39, "Выкупы: количество выкупов, шт", "int", lambda S, R: S("buyouts")),
    (40, "Сумма выкупов (оплачено покупателем), руб", "money", lambda S, R: S("buyouts_sum")),
    (41, "Средняя цена выкупа ДО скидки ВБ (СПП), руб", "money", lambda S, R: _d(R(38), R(39))),
    (42, "Средняя СПП, %", "pct", lambda S, R: _d(R(38) - R(40), R(38))),
    (43, "К оплате продавцу (выкупы), руб", "money", lambda S, R: R(40) + R(44)),
    (44, "Сумма комиссии за минусом скидки ВБ (СПП), руб", "money", lambda S, R: -S("commission")),
    (45, "Фактическая комиссия WB, %", "pct", lambda S, R: _d(R(44), -R(38))),
    (46, "Расчётная комиссия WB, %", "pct", lambda S, R: _d(R(38) - R(43), R(38))),
    (47, "Маржа по выкупам, руб", "money", lambda S, R: R(43) + R(49) - R(50) + R(51)),
    (48, "Маржа от суммы выкупов ДО скидки ВБ (СПП), %", "pct", lambda S, R: _d(R(47), R(38))),
    (49, "Сумма логистики по выкупам, руб", "money", lambda S, R: -S("logistics")),
    (50, "Сумма себестоимости выкупов, руб", "money", lambda S, R: S("cost")),
    (51, "Сумма эквайринга", "money", lambda S, R: -S("acquiring")),
    (52, "Расходы на рекламу, руб", "money", lambda S, R: -S("ads_upd")),
    (53, "ДРР от суммы выкупов ДО скидки ВБ (СПП), %", "pct", lambda S, R: _d(-R(52), R(38))),
    (54, "ДРР от оперативной прибыли, %", "pct", lambda S, R: _d(-R(52), R(63))),
    (541, "Реклама бонусами (Кэшбэк), руб", "money", lambda S, R: -S("ads_bonus")),
    (542, "Реклама всего: деньги + бонусы, руб", "money", lambda S, R: R(52) + R(541)),
    (543, "ДРР от суммы выкупов: бонусы, %", "pct", lambda S, R: _d(-R(541), R(38))),
    (544, "ДРР от суммы выкупов: всего (деньги + бонусы), %", "pct", lambda S, R: _d(-R(542), R(38))),
    (55, "Другие расходы WB", "money", lambda S, R: R(56) + R(57)),
    (56, "Платное хранение, руб", "money", lambda S, R: -S("storage")),
    (57, "Платная приемка, руб", "money", lambda S, R: -S("acceptance_sum")),
    (58, "ВСЕГО НАЛОГ по выкупам, руб", "money", lambda S, R: R(60) + R(61) + R(62)),
    (59, "ВСЕГО НАЛОГ от суммы выкупов (оплачено покупателем), %", "pct", lambda S, R: _d(-R(58), R(40))),
    (60, "Налог по выкупам (СНО, оценка за период), руб", "money", "tax_buyouts"),
    (61, "Сумма НДС к начислению с выкупов, руб", "money", lambda S, R: -S("vat_buyouts")),
    (62, "Сумма НДС к вычету, руб", "money", "vat_deduct_buyouts"),
    (63, "Оперативная прибыль за минусом налога, руб.", "money", lambda S, R: R(47) + R(58) + R(55) + R(52)),
    (64, "Прибыль за минусом налога от выкупов ДО скидки ВБ (СПП), %", "pct", lambda S, R: _d(R(63), R(38))),
    (65, "ОТМЕНЫ И ВОЗВРАТЫ", "h", None),
    (66, "Количество отмененных/невыкупленных заказов, шт", "int", lambda S, R: S("cxd_orders")),
    (67, "Сумма Отмененных/Невыкупленных заказов, руб", "money", lambda S, R: S("cxd_sum_spp")),
    (68, "Доля отмененных/невыкупленных заказов, %", "pct", lambda S, R: _d(R(66), R(8))),
    (69, "Количество возвратов, шт", "int", lambda S, R: S("returns")),
    (70, "Сумма возвратов (к оплате продавцу), руб", "money", lambda S, R: S("returns_for_pay")),
    (71, "Сумма себестоимости возвратов, руб", "money", lambda S, R: S("returns_cost")),
    (72, "Сумма уменьшения начисления НДС с возвратов, руб", "money", lambda S, R: S("vat_returns")),
    (73, "Сумма умен. вычета НДС с себес. возвратов, руб", "money", lambda S, R: -S("vat_deduct_returns")),
    (74, "ОПЕРАТИВНАЯ ПРИБЫЛЬ ЗА МИНУСОМ ВОЗВРАТОВ", "h", None),
    (75, "К оплате продавцу за минусом возвратов, руб", "money", lambda S, R: R(43) + R(70)),
    (76, "Маржа по выкупам за минусом возвратов, руб", "money", lambda S, R: R(47) + R(70) - R(71)),
    (77, "Маржа от суммы выкупов за минусом возвратов ДО скидки ВБ (СПП), %", "pct", lambda S, R: _d(R(76), R(38))),
    (78, "ВСЕГО НАЛОГ с учетом возвратов, руб", "money", lambda S, R: R(80) + R(81) + R(82)),
    (79, "ВСЕГО НАЛОГ с учётом возвратов от выкупов (оплачено покупателем), %", "pct", lambda S, R: _d(-R(78), R(40))),
    (80, "Налог по выкупам с учетом возвратов (СНО, оценка за период), руб", "money", "tax_returns"),
    (81, "Сумма НДС к начислению с выкупов с учетом возвратов, руб", "money", lambda S, R: -S("vat_buyouts") + R(72)),
    (82, "Сумма НДС к вычету с учетом возвратов, руб", "money", "vat_deduct_returns"),
    (83, "Оперативная прибыль с учётом возвратов за минусом налога, руб.", "money", lambda S, R: R(76) + R(78) + R(55) + R(52)),
    (84, "Прибыль с учётом возвратов за минусом налога от выкупов ДО скидки ВБ (СПП), %", "pct", lambda S, R: _d(R(83), R(38))),
    (88, "РЕНТАБЕЛЬНОСТЬ", "h", None),
    (89, "ROI: рентабельность по прибыли (заказы), %", "pct", lambda S, R: _d(R(35), R(22))),
    (90, "Рентабельность по прибыли (продажи), %", "pct", lambda S, R: _d(R(63), R(50))),
    (91, "Рентабельность по прибыли (продажи с учетом возвратов), %", "pct", lambda S, R: _d(R(83), R(50) - R(71))),
]
ROW = {n: (lab, fmt, f) for n, lab, fmt, f in ROWS}
RATIO = {n for n, _, fmt, _ in ROWS if fmt == "pct"}


def _d(a, b):
    return a / b if b else 0


def periods(yesterday: date) -> dict:
    """Окна колонок как в эталоне (TODAY()-1 = yesterday)."""
    today = yesterday + timedelta(days=1)
    wd = today.isoweekday()                                
    w_end = today - timedelta(days=wd)
    w_beg = w_end - timedelta(days=6)
    m_beg = yesterday.replace(day=1)
    j_end = m_beg - timedelta(days=1); j_beg = j_end.replace(day=1)
    k_end = j_beg - timedelta(days=1); k_beg = k_end.replace(day=1)
    f_beg = m_beg if yesterday.day > 14 else yesterday - timedelta(days=14)
    return {"C": (yesterday, yesterday), "D": (yesterday - timedelta(days=1), yesterday - timedelta(days=1)),
            "F": (w_beg, w_end), "G": (w_beg - timedelta(days=7), w_end - timedelta(days=7)),
            "I": (m_beg, yesterday), "J": (j_beg, j_end), "K": (k_beg, k_end), "M": (f_beg, yesterday)}


def _buyout_pct(weekly: list[dict], p_from: date, p_to: date) -> float:
    """R14: доля выкупа по отчёту реализации за 4 полные недели (или за сам период, если он ≥ 28 дней):
    (доставки при продажах − доставки при возвратах) / доставки при продажах."""
    wd = p_to.isoweekday()
    d_to = p_to - timedelta(days=0 if wd == 7 else wd)
    d_from = d_to - timedelta(days=27) if (p_to - p_from).days < 27 else p_from
    to_c = sum(float(w["deliveries"] or 0) for w in weekly if w["date_from"] >= d_from and w["date_to"] <= d_to)
    fr_c = sum(float(w["returns"] or 0) for w in weekly if w["date_from"] >= d_from and w["date_to"] <= d_to)
    return _d(to_c - fr_c, to_c)


def compute(c, shop: int, yesterday: date | None = None, nm_ids: list[int] | None = None, custom: dict | None = None) -> dict:
    """custom — свои окна {"имя": (с, по)} вместо колонок листа (главная страница: сегодня/вчера/позавчера)."""
    yesterday = yesterday or today_msk() - timedelta(days=1)
    P = custom or periods(yesterday)
    lo = min(v[0] for v in P.values())
    sums = _period_sums(nm_day.iter_cached(c, shop, lo, max(v[1] for v in P.values()), nm_ids), P)
    
    from ..agg import real_week
    weekly = [{**w, "date_from": date.fromisoformat(w["date_from"]), "date_to": date.fromisoformat(w["date_to"])}
              for w in real_week.weekly_deliveries(c, shop, nm_ids) if w["date_from"]]
    from ..agg import buyout
    bp_orders = buyout.for_nms(c, shop, nm_ids) if buyout.needed(c, shop) else None   
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1",
                    (shop, yesterday)).fetchone() or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    regime, rate = tax["regime"], float(tax["rate"])
    vat_rate, vat_wb = float(tax["vat_rate"]), float(tax["vat_deduct_wb"])

    cols = {}
    for col, (a, b) in P.items():
        k = 1.0
        if col == "M":   
            k = calendar.monthrange(b.year, b.month)[1] / ((b - a).days + 1)
        vals: dict[int, float] = {}

        def S(key, total=sums[col], k=k):
            return k * float(total.get(key, 0))

        def R(n, vals=vals):
            if n not in vals:
                vals[n] = ev(n)
            return vals[n]

        def ev(n, S=S, R=R, a=a, b=b):
            f = ROW[n][2]
            if f == "buyout_pct":
                return bp_orders if bp_orders is not None else _buyout_pct(weekly, a, b)
            if f == "tax_orders":
                if regime == "УСН доход":
                    return -rate * (R(17) + R(33))
                if regime == "УСН доходы-расходы":
                    base = R(18) + R(23) + R(27) + R(33)
                    return -(rate * base if rate * base > R(17) * 0.01 else R(17) * 0.01)
                if regime in ("ОСНО", "ОСНО ИП (НДФЛ)"):
                    return _income_tax_estimate(R(18) + R(23) + R(27) + R(33) + R(34), regime, rate)
                return 0.0
            if f == "vat_deduct_orders":
                return S("vat_deduct_orders") * R(14) + ((R(20) + R(21) + R(27) + R(23)) * vat_wb / (1 + vat_wb) * -1 if vat_rate >= 0.10 else 0)
            if f in ("tax_buyouts", "tax_returns"):
                ret = R(70) if f == "tax_returns" else 0
                vat = R(81) if f == "tax_returns" else R(61)
                if regime == "УСН доход":
                    return -rate * (R(40) + vat + (R(44) if R(44) > 0 else 0) + ret)
                if regime == "УСН доходы-расходы":
                    profit = (R(76) if f == "tax_returns" else R(47)) + R(55) + R(52) + vat
                    floor = (R(40) + vat + ((R(44) if R(44) > 0 else 0) + ret if f == "tax_returns" else 0)) * 0.01
                    return -(max(rate * profit, floor) if profit > 0 else 0)
                if regime in ("ОСНО", "ОСНО ИП (НДФЛ)"):
                    base = (R(76) if f == "tax_returns" else R(47)) + R(55) + R(52) + vat
                    base += R(82) if f == "tax_returns" else R(62)
                    return _income_tax_estimate(base, regime, rate)
                return 0.0
            if f == "vat_deduct_buyouts":
                return S("vat_deduct_buyouts") + ((R(44) + R(49) + R(55) + R(52)) * vat_wb / (1 + vat_wb) * -1 if vat_rate >= 0.10 else 0)
            if f == "vat_deduct_returns":
                return R(62) + R(73)
            return f(S, R)

        for n, _, fmt, f in ROWS:
            if f is not None:
                R(n)
        cols[col] = vals

    if custom:
        return {"periods": {k: [str(v[0]), str(v[1])] for k, v in P.items()},
                "values": {col: {n: cols[col][n] for n in cols[col]} for col in P}, "tax": regime}

    def change(x, y, n):
        if n in RATIO:
            return cols[x][n] - cols[y][n]
        return _d(cols[x][n], cols[y][n]) - 1 if cols[y][n] else 0

    out = []
    for n, lab, fmt, f in ROWS:
        row = {"row": n, "label": lab, "fmt": fmt}
        if f is not None:
            for col in P:
                row[col] = round(cols[col][n], 4 if fmt == "pct" else 2)
            row["E"] = round(change("C", "D", n), 4)
            row["H"] = round(change("F", "G", n), 4)
            row["L"] = round(change("J", "K", n), 4)
            row["N"] = round(change("M", "J", n), 4)
        out.append(row)
    return {"periods": {k: [str(v[0]), str(v[1])] for k, v in P.items()}, "rows": out, "tax": regime}


def _income_tax_estimate(base: float, regime: str, rate: float) -> float:
    """Operational estimate for this period; factual YTD NDFL is in PnL."""
    from .pnl_real import ndfl
    return -ndfl(max(0.0, base)) if regime == "ОСНО ИП (НДФЛ)" else -rate * max(0.0, base)


def _period_sums(rows, periods):
    """Sum the same fields in the same row order without retaining article/day rows.

    Compensated float addition preserves Python 3.12 sum() precision, including
    cancellation in return/refund amounts. Integer-only fields remain integers.
    """
    totals = {col: {} for col in periods}
    corrections = {col: {} for col in periods}
    for row in rows:
        
        
        fields = [(key, float(value) if isinstance(value, Decimal) else value)
                  for key, value in row.items() if isinstance(value, (int, float, Decimal))]
        for col, (start, end) in periods.items():
            if not start <= row["day"] <= end:
                continue
            acc, low = totals[col], corrections[col]
            for key, value in fields:
                old = acc.get(key, 0)
                new = old + value
                if isinstance(new, float):
                    low[key] = low.get(key, 0.) + ((old - new) + value if abs(old) >= abs(value) else (value - new) + old)
                acc[key] = new
    for col, low in corrections.items():
        for key, correction in low.items():
            if correction and math.isfinite(correction):
                totals[col][key] += correction
    return totals

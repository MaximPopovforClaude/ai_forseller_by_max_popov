"""Self-hosted application component."""

from collections import defaultdict
from datetime import date

from ..agg import nm_day
from .dash5 import order_note, rounded
from . import funnel_orders

ROWS = [                                                                       
    (3, "Кол-во заказов ВСЕГО, шт", "orders", 1, "int"), (4, "Сумма заказов с учетом скидки продавца, руб", "orders_sum", 1, "money"),
    (5, "Сумма заказов с учетом скидки ВБ (СПП), руб", "orders_sum_spp", 1, "money"),
    (6, "в т.ч. кол-во заказов со статусом Отменен", "cx_orders", 1, "int"),
    (7, "в т.ч. сумма заказов со статусом Отменен, руб", "cx_orders_sum", 1, "money"),
    (8, "в т.ч. доля заказов со статусом Отменен, %", lambda V: _d(V[6], V[11]), 0, "pct"),
    (9, "в т.ч. кол-во заказов со статусом НЕотменен", "ok_orders", 1, "int"),
    (10, "в т.ч. сумма заказов со статусом НЕотменен, руб", "ok_orders_sum", 1, "money"),
    (11, "Конверсии (заказали товаров)", "f_orders", 1, "int"), (12, "Конверсии (заказали на сумму), руб", "f_orders_sum", 1, "money"),
    (funnel_orders.SPP_ROW, "Заказы из воронки WB: сумма с учетом СПП (оценка), руб", "f_orders_sum_spp", 1, "money"),
    (13, "Кол-во выкупов, шт", "buyouts", 1, "int"), (14, "Кол-во Отмененных/Невыкупленных заказов, шт", "cxd_orders", 1, "int"),
    (15, "Сумма Отмененных/Невыкупленных заказов, руб", "cxd_sum_spp", 1, "money"),
    (16, "Доля Отмененных/Невыкупленных заказов от общего кол-ва заказов, %", lambda V: _d(V[14], V[11]), 0, "pct"),
    (17, "Сумма выкупов ДО скидки ВБ (СПП), руб", "buyouts_sum_before_spp", 1, "money"),
    (18, "Сумма выкупов (оплачено покупателем), руб", "buyouts_sum", 1, "money"),
    (19, "Сумма комиссии за минусом скидки ВБ (СПП), руб", "commission", -1, "money"),
    (20, "Фактическая комиссия WB, %", lambda V: _d(V[19], V[17]) * -1, 0, "pct"),
    (21, "К оплате продавцу, руб", "for_pay", 1, "money"), (22, "Сумма логистики, руб", "logistics", -1, "money"),
    (23, "Себестоимость, руб", "cost", 1, "money"), (24, "Маржа, руб", lambda V: V[21] + V[22] - V[23], 0, "money"),
    (25, "Маржа, %", lambda V: _d(V[24], V[17]), 0, "pct"), (26, "Расходы на рекламу, руб", "ads", -1, "money"),
    (27, "ДРР от суммы заказов с учетом скидки продавца, %", lambda V: _d(-V[26], V[12]), 0, "pct"),
    (28, "ДРР от суммы выкупов ДО скидки ВБ (СПП), %", lambda V: _d(V[26], V[17]) * -1, 0, "pct"),
    (29, "Платное хранение, руб", "storage", -1, "money"), (30, "Платная приемка, руб", "acceptance_sum", -1, "money"),
    (31, "НАЛОГ, руб", "tax", 0, "money"),
    (32, "Прибыль за минусом налога, руб", lambda V: V[24] + V[26] + V[29] + V[31], 0, "money"),
    (33, "Прибыль за минусом налога от суммы выкупов ДО скидки ВБ (СПП), %", lambda V: _d(V[32], V[17]), 0, "pct"),
    (34, "Кол-во возвратов, шт", "returns", 1, "int"), (35, "Сумма возвратов (к оплате продавцу), руб", "returns_for_pay", 1, "money"),
]

                                                                                
_LABELS = {
    11: "Заказы из воронки WB: количество, шт",
    12: "Заказы из воронки WB: сумма до СПП, руб",
    3: "Заказы из статистики WB: количество, шт",
    4: "Заказы из статистики WB: сумма со скидкой продавца, руб",
    5: "Заказы из статистики WB: сумма с учетом СПП, руб",
    6: "Отменённые заказы из статистики WB: количество, шт",
    7: "Отменённые заказы из статистики WB: сумма до СПП, руб",
    8: "Отменённые заказы из статистики к заказам воронки, %",
    9: "Неотменённые заказы из статистики WB: количество, шт",
    10: "Неотменённые заказы из статистики WB: сумма до СПП, руб",
    16: "Отмены/невыкупы из статистики к заказам воронки, %",
}
DASHBOARD_ROWS = [r for r in ROWS if r[0] in (11, 12, funnel_orders.SPP_ROW)] + [r for r in ROWS if r[0] not in (11, 12, funnel_orders.SPP_ROW)]


def _d(a, b):
    if a is None or b is None:
        return None
    return a / b if b else 0


def compute(c, shop: int, df: date, dt: date, nm_ids=None, *, order_source="funnel") -> dict:
    if order_source not in ("funnel", "statistics"):
        raise ValueError("Unknown dashboard order source")
    report_rows = DASHBOARD_ROWS
    labels = _LABELS
    if order_source == "statistics":
        overrides = {8: lambda V: _d(V[6], V[3]), 16: lambda V: _d(V[14], V[3]),
                     27: lambda V: _d(-V[26], V[4])}
        report_rows = [(n, lab, overrides.get(n, k), sign, fmt) for n, lab, k, sign, fmt in ROWS]
        labels = {n: lab for n, lab in _LABELS.items() if n not in (8, 16)}
    rows = nm_day.iter_cached(c, shop, df, dt, nm_ids)
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1", (shop, dt)).fetchone() \
        or {"regime": "Другая СНО", "rate": 0}
    S = defaultdict(lambda: defaultdict(float))
    missing = defaultdict(set)
    funnel_keys = {"f_orders", "f_orders_sum", "f_orders_sum_spp"}
    for raw in rows:
        r = funnel_orders.project(raw, {}, vat_enabled=False)
        for _, _, k, _, _ in ROWS:
            if isinstance(k, str) and k != "tax":
                for col in (r["day"], r["day"].strftime("%Y-%m")):
                    if r.get(k) is not None:
                        S[col][k] += float(r[k])
                    elif k in funnel_keys:
                        missing[col].add(k)
    days = []
    d = dt
    while d >= df:
        days.append(d)
        d = date.fromordinal(d.toordinal() - 1)
    cols = []
    for d in days:                                                                                 
        nxt = date.fromordinal(d.toordinal() + 1)
        if d == dt or nxt.month != d.month:
            cols.append(d.strftime("%Y-%m"))
        cols.append(d)
    vals = {}
    for col in cols:
        V = {}
        for n, _, k, sign, _ in report_rows:
            if k == "tax":
                if tax["regime"] == "УСН доход":
                    V[n] = -float(tax["rate"]) * V[18]
                elif tax["regime"] == "УСН доходы-расходы":
                    p = V[24] + V[26] + V[29]
                    V[n] = -float(tax["rate"]) * p if p > 0 else 0
                else:
                    V[n] = 0.0
            elif callable(k):
                V[n] = k(V)
            else:
                value = None if k in missing[col] else S[col].get(k, None if k in funnel_keys else 0.0)
                V[n] = value * sign if value is not None else None
        vals[col] = V
    months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
    columns = [{"field": "label", "title": f"ПОКАЗАТЕЛИ ПО ДНЯМ (СНО: {tax['regime']})", "type": "label"}]
    for col in cols:
        if isinstance(col, str):
            columns.append({"field": col, "title": f"{months[int(col[5:]) - 1]}. {col[:4]}", "type": "rowfmt"})
        else:
            columns.append({"field": col.isoformat(), "title": col.strftime("%d.%m"), "type": "rowfmt"})
    out = []
    for n, lab, k, sign, fmt in report_rows:
        row = {"row": n, "label": labels.get(n, lab), "fmt": fmt}
        for col in cols:
            row[col if isinstance(col, str) else col.isoformat()] = rounded(vals[col][n], 4 if fmt == "pct" else 2)
        out.append(row)
    return {"columns": columns, "rows": out, "layout": "sheet", "note": order_note(order_source) + " В этом листе маржа и прибыль — по фактическим продажам; выбор источника заказов меняет ДРР и доли отмен, а не результат продаж."}

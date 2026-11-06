"""Яндекс Маркет: дашборд по дням (как 3#Дашборд Ozon) — заказы из stats/orders, деньги — из «Отчёта по платежам» (stometric/collectors_ym.py).

Заказы — по дню создания заказа; выкупы, возвраты и услуги Маркета по выкупленным — по дню последней смены статуса (доставлен / возвращён).
Цена продажи = цена для покупателя + скидка Маркета (баллы Плюса и купоны). Скидку Маркет возвращает продавцу баллами, а баллами оплачивает
свои услуги («Скидка за участие в совместных акциях»), поэтому услуги берём из отчёта по платежам: деньгами + баллами (сверка 27.10).
Заказы, по которым отчёта ещё нет, — по услугам из stats/orders с поправкой на долю «баллами» (оценка). Что считаем оценкой, подписано.
"""

import re

from collections import defaultdict
from datetime import date, timedelta

BUYOUT_LAG = (15, 60)       
DONE = ("DELIVERED", "PARTIALLY_DELIVERED", "PARTIALLY_RETURNED")
RETURNED = ("RETURNED",)
CANCEL = ("CANCELLED_BEFORE_PROCESSING", "CANCELLED_IN_PROCESSING", "CANCELLED_IN_DELIVERY", "LOST")
FINAL = DONE + RETURNED + CANCEL

COMM = [   
    ("x_fee", ("FEE",)),
    ("x_deliv", ("DELIVERY_TO_CUSTOMER", "EXPRESS_DELIVERY_TO_CUSTOMER", "CROSSREGIONAL_DELIVERY", "AGENCY_COMMISSION_3PL")),
    ("x_pay", ("AGENCY", "PAYMENT_TRANSFER", "INSTALLMENT")),
    ("x_boost", ("AUCTION_PROMOTION",)),
    ("x_loyal", ("LOYALTY_PARTICIPATION_FEE",)),
    ("x_proc", ("SORTING", "INTAKE_SORTING", "RETURN_PROCESSING", "RETURNED_ORDERS_STORAGE", "FULFILLMENT", "FULFILLMENT_WITHDRAW")),
]
COMM_KEY = {t: k for k, ts in COMM for t in ts}
SVC = [   
    ("x_fee", r"размещени"),
    ("x_proc", r"невыкуп|сортиров|обработк|хранени|возврат(ов|а) "),
    ("x_deliv", r"доставк|средняя миля|населённый пункт|населенный пункт"),
    ("x_pay", r"при[её]м платежа|перевод платежа|эквайр"),
    ("x_boost", r"буст"),
    ("x_loyal", r"отзывы за баллы|лояльност"),
]
X_KEYS = ("x_fee", "x_deliv", "x_pay", "x_boost", "x_loyal", "x_proc", "x_other")


def svc_key(name: str) -> str:
    t = (name or "").lower()
    for k, rx in SVC:
        if re.search(rx, t):
            return k
    return "x_other"


class Services:
    """Услуги Маркета по товару заказа: из отчёта по платежам (деньгами + баллами), иначе — stats/orders × поправка (оценка)."""

    def __init__(self, c, shop: int, order_ids: set):
        self.net = defaultdict(list)
        ids = list(order_ids)
        for i in range(0, len(ids), 5000):
            for r in c.execute("""SELECT order_id, shop_sku, kind, service, sum(amount) a FROM ym_netting
                                  WHERE account_id=%s AND order_id = ANY(%s) AND kind IN ('serv','serv_pts') GROUP BY 1,2,3,4""",
                               (shop, ids[i:i + 5000])):
                self.net[r["order_id"]].append((r["shop_sku"], svc_key(r["service"]), r["kind"] == "serv_pts", float(r["a"])))
        
        x = c.execute("""SELECT sum(amount) FILTER (WHERE kind IN ('serv','serv_pts')) a, sum(amount) FILTER (WHERE kind='serv') m
                         FROM ym_netting WHERE account_id=%s AND tx_day >= current_date - 60""", (shop,)).fetchone()
        self.factor = float(x["a"]) / float(x["m"]) if x and x["m"] else 1.0

    def of(self, r) -> tuple[dict, bool]:
        """→ ({строка: сумма (расход < 0), "x_points": из них баллами}, по отчёту?)."""
        out = defaultdict(float)
        rows = self.net.get(r["order_id"])
        if rows:
            for sku, k, pts, a in rows:
                w = 1.0 if sku and sku == r["offer_id"] else (r["w"] if not sku else 0.0)
                if w:
                    out[k] += a * w
                    if pts:
                        out["x_points"] += a * w
            return out, True
        for t, amt in (r["comm"] or {}).items():
            out[COMM_KEY.get(t, "x_other")] -= float(amt or 0) * r["w"] * self.factor
        return out, False

ROWS = [
    ("h", "ЗАКАЗЫ И ПОТЕНЦИАЛЬНАЯ ПРИБЫЛЬ ПО ЗАКАЗАМ", "h"),
    ("o_sum", "Сумма заказов (цена продажи), руб", "money"),
    ("o_qty", "Количество заказов, шт", "int"),
    ("o_avg", "Средняя цена заказа, руб", "money"),
    ("o_buyer", "В том числе оплачено покупателем, руб", "money"),
    ("o_market", "В том числе баллы Плюса и купоны Маркета, руб", "money"),
    ("share", "Процент выкупа (заказы 15–60 дней назад), %", "pct"),
    ("ob_sum", "Сумма заказов с учетом процента выкупа, руб", "money"),
    ("ob_qty", "Количество заказов с учетом процента выкупа, шт", "int"),
    ("o_serv", "Услуги Маркета по заказам с учетом % выкупа (оценка по доле услуг в выкупленных заказах), руб", "money"),
    ("o_cost", "Себестоимость заказов с учетом выкупа, руб", "money"),
    ("o_boost", "Буст продаж по заказам дня, руб", "money"),
    ("drr", "ДРР (буст) от суммы заказов, %", "pct"),
    ("o_tax", "Налог по заказам, руб", "money"),
    ("o_profit", "Прибыль по заказам с учетом % выкупа (оценка), руб", "money"),
    ("o_profit_p", "Прибыль по заказам, % от суммы с учетом выкупа", "pct"),
    ("h", "ВЫКУПЫ И ОПЕРАТИВНАЯ ПРИБЫЛЬ (по дню доставки)", "h"),
    ("b_qty", "Количество выкупов, шт", "int"),
    ("b_sum", "Сумма выкупов (цена продажи), руб", "money"),
    ("b_avg", "Средняя цена выкупа, руб", "money"),
    ("x_fee", "Размещение товара (комиссия), руб", "money"),
    ("x_deliv", "Доставка покупателю, руб", "money"),
    ("x_pay", "Прием и перевод платежа, руб", "money"),
    ("x_boost", "Буст продаж (оплата за продажи), руб", "money"),
    ("x_loyal", "Программа лояльности и отзывы за баллы, руб", "money"),
    ("x_proc", "Обработка, сортировка, возвраты, руб", "money"),
    ("x_other", "Другие услуги Маркета (штрафы и пр.), руб", "money"),
    ("x_total", "Итого услуги Маркета, руб", "money"),
    ("x_points", "из них оплачено баллами за скидку Маркета, руб", "money"),
    ("x_est", "из них оценка (заказы, которых ещё нет в отчёте по платежам), руб", "money"),
    ("b_cost", "Себестоимость выкупов за минусом возвратов, руб", "money"),
    ("f_tax", "Налог по выкупам, руб", "money"),
    ("f_profit", "Оперативная прибыль за минусом налога, руб", "money"),
    ("f_profit_p", "Оперативная прибыль от суммы выкупов, %", "pct"),
    ("h", "ОТМЕНЫ И ВОЗВРАТЫ", "h"),
    ("c_qty", "Отменено заказов (по дню заказа), шт", "int"),
    ("c_sum", "Сумма отмененных заказов, руб", "money"),
    ("c_share", "Доля отмененных заказов, %", "pct"),
    ("r_qty", "Возвраты (по дню возврата), шт", "int"),
    ("r_sum", "Сумма возвратов, руб", "money"),
    ("h", "БАЛАНС (на сейчас)", "h"),
    ("st_qty", "Остатки годные (все склады и модели), шт", "int"),
    ("st_cost", "Остатки в себестоимости, руб", "money"),
]


def costs(c, shop: int) -> dict:
    return {r["nm_id"]: float(r["cost"]) for r in c.execute(
        "SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%s ORDER BY nm_id, valid_from DESC", (shop,))}


def tax_of(c, shop: int, d: date) -> tuple[str, float]:
    t = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1", (shop, d)).fetchone()\
        or {"regime": "Другая СНО", "rate": 0}
    rate = float(t["rate"] or 0)
    return t["regime"], rate / 100 if rate > 1 else rate


def items(c, shop: int, a: date, b: date, by: str = "order_day") -> list[dict]:
    """Товары заказов с долей услуг Маркета (по сумме товара в заказе). by — order_day или status_day."""
    rows = c.execute(
        f"""SELECT o.order_id, o.order_day, o.status_day, o.status, o.commission, o.comm, o.placement,
                   coalesce(i.market_sku, f.market_sku) sku, i.offer_id, i.initial_qty, i.qty,
                   coalesce(i.buyer_total,0) buyer, coalesce(i.cashback,0) cashback, coalesce(i.coupons,0) coupons,
                   coalesce(i.buyer_total,0)+coalesce(i.cashback,0)+coalesce(i.coupons,0) total,
                   sum(coalesce(i.buyer_total,0)+coalesce(i.cashback,0)+coalesce(i.coupons,0)) OVER (PARTITION BY o.order_id) order_total,
                   count(*) OVER (PARTITION BY o.order_id) n_lines
            FROM ym_orders o JOIN ym_order_items i ON i.account_id=o.account_id AND i.order_id=o.order_id
            LEFT JOIN ym_offers f ON f.account_id=i.account_id AND f.offer_id=i.offer_id
            WHERE o.account_id=%s AND NOT o.fake AND o.{by} BETWEEN %s AND %s""", (shop, a, b)).fetchall()
    for r in rows:
        ot = float(r["order_total"] or 0)
        r["w"] = float(r["total"]) / ot if ot else 1 / max(1, r["n_lines"])
        
        q = int(r["qty"] or 0)
        r["unit"] = float(r["total"]) / q if q else None
    return rows


def _unit_prices(c, shop: int) -> dict:
    """Цена продажи за шт по SKU из последних заказов — для позиций, полностью удалённых из заказа (qty = 0)."""
    return {r["sku"]: float(r["p"]) for r in c.execute(
        """SELECT DISTINCT ON (coalesce(i.market_sku, f.market_sku)) coalesce(i.market_sku, f.market_sku) sku,
                  (coalesce(i.buyer_total,0)+coalesce(i.cashback,0)+coalesce(i.coupons,0))/i.qty p
           FROM ym_order_items i JOIN ym_orders o ON o.account_id=i.account_id AND o.order_id=i.order_id
           LEFT JOIN ym_offers f ON f.account_id=i.account_id AND f.offer_id=i.offer_id
           WHERE i.account_id=%s AND i.qty > 0 ORDER BY 1, o.order_day DESC""", (shop,)) if r["sku"]}


def compute(c, shop: int, d_from: date, d_to: date, skus: list[int] | None = None, per: list | None = None) -> dict:
    """per — свои периоды [(ключ, с, по)] вместо дней (Главная: сегодня/вчера/позавчера)."""
    pers = per or [(d_to - timedelta(days=i),) * 3 for i in range((d_to - d_from).days + 1)]
    lo = min(p[1] for p in pers)
    hi = max(p[2] for p in pers)
    alldays = set()
    for _, a, b in pers:
        d = a
        while d <= b:
            alldays.add(d)
            d += timedelta(days=1)
    cost = costs(c, shop)
    regime, rate = tax_of(c, shop, hi)
    uprice = _unit_prices(c, shop)
    flt = (lambda s: skus is None or s in skus)
    V = defaultdict(lambda: defaultdict(float))
    Dd = defaultdict(lambda: defaultdict(float))       
    by_order = items(c, shop, lo - timedelta(days=BUYOUT_LAG[1]), hi, "order_day")
    by_status = items(c, shop, lo, hi, "status_day")
    svc = Services(c, shop, {r["order_id"] for r in by_order if r["status"] in DONE} | {r["order_id"] for r in by_status})

    
    fin = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])    
    for r in by_order:
        if not flt(r["sku"]):
            continue
        q0 = float(r["initial_qty"] or r["qty"] or 0)
        unit = r["unit"] if r["unit"] is not None else uprice.get(r["sku"], 0)
        s0 = unit * q0
        if r["status"] in FINAL:
            fin[r["order_day"]][0] += q0
            fin[r["order_day"]][1] += float(r["qty"] or 0) if r["status"] in DONE else 0
            if r["status"] in DONE:
                fin[r["order_day"]][2] += float(r["total"])
                fin[r["order_day"]][3] += sum(a for k, a in svc.of(r)[0].items() if k in X_KEYS)
        if r["order_day"] not in alldays:
            continue
        v = Dd[r["order_day"]]
        v["o_sum"] += s0
        v["o_qty"] += q0
        v["o_buyer"] += float(r["buyer"]) if r["qty"] else 0
        v["o_market"] += float(r["cashback"]) + float(r["coupons"]) if r["qty"] else 0
        v["_cost"] += q0 * cost.get(r["sku"], 0)
        com = r["comm"] or {}
        v["o_boost"] -= float(com.get("AUCTION_PROMOTION") or 0) * r["w"] * svc.factor
        if r["status"] in CANCEL:
            v["c_qty"] += q0
            v["c_sum"] += s0
        elif r["qty"] is not None and q0 > float(r["qty"] or 0):     
            v["c_qty"] += q0 - float(r["qty"])
            v["c_sum"] += unit * (q0 - float(r["qty"]))

    
    for r in by_status:
        if not flt(r["sku"]) or r["status"] not in DONE + RETURNED:
            continue
        if r["status_day"] not in alldays:
            continue
        v = Dd[r["status_day"]]
        q = float(r["qty"] or 0)
        if r["status"] in DONE:
            v["b_qty"] += q
            v["b_sum"] += float(r["total"])
            v["b_cost"] += q * cost.get(r["sku"], 0)
        else:
            q0 = float(r["initial_qty"] or r["qty"] or 0)
            unit = r["unit"] if r["unit"] is not None else uprice.get(r["sku"], 0)
            v["r_qty"] += q0
            v["r_sum"] += unit * q0
        sv, exact = svc.of(r)
        for k, a in sv.items():
            v[k] += a
        if not exact:
            v["x_est"] += sum(a for k, a in sv.items() if k in X_KEYS)

    st = c.execute("""SELECT s.offer_id, coalesce(f.market_sku, 0) sku, sum(coalesce(s.fit, s.available, 0)) q FROM ym_stocks s
                      LEFT JOIN ym_offers f ON f.account_id=s.account_id AND f.offer_id=s.offer_id
                      WHERE s.account_id=%s AND s.snap_at=(SELECT max(snap_at) FROM ym_stocks WHERE account_id=%s) GROUP BY 1,2""",
                   (shop, shop)).fetchall()
    st_qty = sum(float(r["q"] or 0) for r in st if flt(r["sku"]))
    st_cost = sum(float(r["q"] or 0) * cost.get(r["sku"], 0) for r in st if flt(r["sku"]))

    for k, a, b in pers:
        v = V[k]
        for d, x in Dd.items():
            if a <= d <= b:
                for kk, val in x.items():
                    v[kk] += val
        lo_d, hi_d = a - timedelta(days=BUYOUT_LAG[1]), b - timedelta(days=BUYOUT_LAG[0])
        tot = sum(x[0] for d, x in fin.items() if lo_d <= d <= hi_d)
        bought = sum(x[1] for d, x in fin.items() if lo_d <= d <= hi_d)
        share = bought / tot if tot else 1.0
        
        sv = [x for d, x in fin.items() if lo_d <= d <= hi_d and x[2]] or [x for x in fin.values() if x[2]]
        v["_serv_rate"] = sum(x[3] for x in sv) / sum(x[2] for x in sv) if sv else 0
        v["share"] = share
        v["o_avg"] = v["o_sum"] / v["o_qty"] if v["o_qty"] else 0
        v["ob_sum"] = v["o_sum"] * share
        v["ob_qty"] = v["o_qty"] * share
        
        v["o_serv"] = v["_serv_rate"] * v["ob_sum"]
        v["o_cost"] = v["_cost"] * share
        v["drr"] = -v["o_boost"] / v["o_sum"] if v["o_sum"] else 0
        v["x_total"] = sum(v[x] for x in X_KEYS)
        if regime == "УСН доход":
            v["o_tax"] = v["ob_sum"] * rate
            v["f_tax"] = max(v["b_sum"] - v["r_sum"], 0) * rate
        elif regime == "УСН доходы-расходы":
            v["o_tax"] = max(v["ob_sum"] + v["o_serv"] - v["o_cost"], 0) * rate
            v["f_tax"] = max(v["b_sum"] - v["r_sum"] + v["x_total"] - v["b_cost"], 0) * rate
        v["o_profit"] = v["ob_sum"] + v["o_serv"] - v["o_cost"] - v["o_tax"]
        v["o_profit_p"] = v["o_profit"] / v["ob_sum"] if v["ob_sum"] else 0
        v["b_avg"] = v["b_sum"] / v["b_qty"] if v["b_qty"] else 0
        v["f_profit"] = v["b_sum"] - v["r_sum"] + v["x_total"] - v["b_cost"] - v["f_tax"]
        v["f_profit_p"] = v["f_profit"] / v["b_sum"] if v["b_sum"] else 0
        v["c_share"] = v["c_qty"] / v["o_qty"] if v["o_qty"] else 0
    first = pers[0][0]
    V[first]["st_qty"], V[first]["st_cost"] = st_qty, st_cost
    return {"keys": [p[0] for p in pers], "V": V, "tax": regime}


def sheet(c, shop: int, d_from: date, d_to: date, skus: list[int] | None = None) -> dict:
    r = compute(c, shop, d_from, d_to, skus)
    days = r["keys"]
    rows = []
    for key, lab, fmt in ROWS:
        row = {"label": lab, "fmt": fmt, "key": key}
        if fmt != "h":
            for i, d in enumerate(days):
                if key.startswith("st_") and i:
                    continue
                row[f"d{i}"] = round(r["V"][d][key], 4 if fmt == "pct" else 2)
        rows.append(row)
    return {"days": [str(d) for d in days], "rows": rows, "tax": r["tax"]}

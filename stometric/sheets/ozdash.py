"""Озон: 3#Дашборд по дням (лист таблицы «STOMETRIC OZON v2») — на данных Seller API.

Блоки как в таблице: заказы и прибыль по заказам (оценка), выкупы и оперативная прибыль (по финансовым начислениям Ozon),
отмены и возвраты, расходы Ozon, баланс. Что считаем иначе, чем таблица, — подписано в названии строки («оценка»).
Начисления Ozon раскладываем по статьям правилами ниже (CLASS); что не узнали — в «Другие расходы Ozon», ничего не теряется:
сумма статей = «Итого начислено Ozon».
"""

import re
from collections import defaultdict
from datetime import date, timedelta

BUYOUT_LAG = (15, 60)       

CLASS = [   
    ("ads", r"promotion|marketingaction|продвиж|реклам|трафарет|бонусы продавца|pay ?per ?click|cpc|cpo"),
    ("acquiring", r"acquiring|эквайринг"),
    ("storage", r"storage|хранени|размещени"),
    ("acceptance", r"acceptance|приемк|приёмк"),
    ("crossdock", r"crossdock|cross-dock|кросс-док"),
    ("utilization", r"utiliz|утилизац"),
    ("compensation", r"compensation|компенсац|декомпенсац"),
    ("insurance", r"insurance|страхован"),
    ("logistics", r"logistic|deliv|dropoff|flowtrans|return|pickup|логистик|доставк|магистрал|обработк|сборк|последняя миля"),
]


def _cls(text: str) -> str:
    t = (text or "").lower()
    for k, rx in CLASS:
        if re.search(rx, t):
            return k
    return "other"


class CostHistory(dict):
    """Current snapshot for legacy callers; historical reports use at(sku, day)."""
    def __init__(self, rows, snapshot: date):
        self.history = defaultdict(list)
        for r in rows:
            self.history[r["nm_id"]].append((r["valid_from"], float(r["cost"])))
        for values in self.history.values():
            values.sort()
        super().__init__((sku, self.at(sku, snapshot)) for sku in self.history)

    def at(self, sku: int, day: date) -> float:
        from bisect import bisect_right
        values = self.history.get(sku, ())
        i = bisect_right(values, (day, float("inf")))
        return values[i - 1][1] if i else 0.0


def _costs(c, shop: int, snapshot: date | None = None) -> CostHistory:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    snapshot = snapshot or datetime.now(ZoneInfo("Europe/Moscow")).date()
    return CostHistory(c.execute("SELECT nm_id, valid_from, cost FROM cost_price WHERE account_id=%s ORDER BY nm_id, valid_from", (shop,)), snapshot)


def transaction_parts(t: dict) -> dict[int, tuple[float, float]]:
    """SKU -> (quantity, share of operation money), before applying the user's filter.

    Prefer item price × quantity when every item has a price; otherwise quantity.
    Legacy rows can only identify repeated SKU entries; distribute their stored qty
    by those entries. The current collector already writes one SKU per operation.
    """
    from collections import Counter
    sk = t.get("skus") or []
    if not sk:
        return {}
    raw = t.get("raw") or {}
    items = raw.get("items") or raw.get("products") or (raw.get("posting") or {}).get("products") or []
    quantity, money = defaultdict(float), defaultdict(float)
    complete_prices = True
    for item in items:
        if not isinstance(item, dict):
            complete_prices = False
            continue
        try:
            sku = int(item.get("sku") or item.get("sku_id") or 0)
            if sku not in sk:
                continue
            q = float(item.get("quantity") or item.get("qty") or 1)
            if q <= 0:
                continue
            quantity[sku] += q
            price = item.get("price")
            sale = (item.get("commission") or {}).get("sale_amount")
            if price is None and sale is not None:
                money[sku] += abs(float(sale.get("amount") or 0) if isinstance(sale, dict) else float(sale))
            elif price is None:
                complete_prices = False
            else:
                money[sku] += max(0.0, float(price.get("amount") or 0) if isinstance(price, dict) else float(price)) * q
        except (TypeError, ValueError):
            complete_prices = False
    if set(quantity) != set(sk):
        counts = Counter(sk)
        total_qty = float(t.get("qty") or len(sk))
        quantity = {sku: total_qty * n / len(sk) for sku, n in counts.items()}
        complete_prices = False
    weights = money if complete_prices and sum(money.values()) > 0 else quantity
    total = sum(weights.values())
    return {sku: (q, weights.get(sku, 0) / total if total else 0.0) for sku, q in quantity.items()}


def _commission(c, shop: int) -> dict:
    """sku → (% комиссии FBO, % FBS, логистика FBO ₽/шт, FBS ₽/шт) из карточки товара Ozon (поле commissions)."""
    out = {}
    for r in c.execute("SELECT sku, raw->'commissions' com FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,)):
        d = {}
        for x in r["com"] or []:
            sch = str(x.get("sale_schema") or "").lower()
            d[sch] = (float(x.get("percent") or 0), float(x.get("delivery_amount") or 0))
        out[r["sku"]] = d
    return out


ROWS = [
    ("h", "ЗАКАЗЫ И ПОТЕНЦИАЛЬНАЯ ПРИБЫЛЬ ПО ЗАКАЗАМ", "h"),
    ("o_sum", "Сумма заказов с учетом скидки продавца, руб", "money"),
    ("o_qty", "Количество заказов, шт", "int"),
    ("o_avg", "Средняя цена заказа с учетом скидки продавца, руб", "money"),
    ("a_rev", "Заказано на сумму (аналитика Ozon), руб", "money"),
    ("a_units", "Заказано товаров (аналитика Ozon), шт", "int"),
    ("a_views", "Показы всего", "int"),
    ("a_sess", "Сессии (уникальные посетители)", "int"),
    ("a_cart", "Добавлено в корзину", "int"),
    ("a_conv", "Конверсия сессии → корзина, %", "pct"),
    ("share", "Процент выкупа (отправления 15–60 дней назад), %", "pct"),
    ("ob_sum", "Сумма заказов с учетом процента выкупа, руб", "money"),
    ("ob_qty", "Количество заказов с учетом процента выкупа, шт", "int"),
    ("o_com", "Комиссия по заказам (оценка по тарифу карточки), руб", "money"),
    ("o_log", "Логистика по заказам (оценка по тарифу карточки), руб", "money"),
    ("o_cost", "Себестоимость заказов с учетом выкупа, руб", "money"),
    ("ads", "Расходы на рекламу, руб", "money"),
    ("drr", "ДРР от суммы заказов, %", "pct"),
    ("ad_views", "Реклама: показы", "int"),
    ("ad_clicks", "Реклама: клики", "int"),
    ("ad_ctr", "Реклама: CTR, %", "pct"),
    ("ad_orders", "Реклама: заказы, шт", "int"),
    ("ad_money", "Реклама: сумма заказов, руб", "money"),
    ("o_tax", "Налог по заказам, руб", "money"),
    ("o_profit", "Прибыль по заказам с учетом % выкупа (оценка), руб", "money"),
    ("o_profit_p", "Прибыль по заказам, % от суммы с учетом выкупа", "pct"),
    ("h", "ВЫКУПЫ И ОПЕРАТИВНАЯ ПРИБЫЛЬ (начисления Ozon)", "h"),
    ("b_qty", "Количество выкупов, шт", "int"),
    ("b_sum", "Сумма выкупов (начислено за продажу), руб", "money"),
    ("b_avg", "Средняя цена выкупа, руб", "money"),
    ("f_com", "Комиссия за продажу и возврат, руб", "money"),
    ("f_log", "Логистика, руб", "money"),
    ("f_acq", "Эквайринг, руб", "money"),
    ("f_ads", "Реклама (списано Ozon), руб", "money"),
    ("b_cost", "Себестоимость выкупов за минусом возвратов, руб", "money"),
    ("f_total", "Итого начислено Ozon за день, руб", "money"),
    ("f_tax", "Налог по выкупам, руб", "money"),
    ("f_profit", "Оперативная прибыль за минусом налога, руб", "money"),
    ("f_profit_p", "Оперативная прибыль от суммы выкупов, %", "pct"),
    ("h", "ОТМЕНЫ И ВОЗВРАТЫ", "h"),
    ("c_qty", "Отменено заказов, шт", "int"),
    ("c_sum", "Сумма отмененных заказов, руб", "money"),
    ("c_share", "Доля отмененных заказов, %", "pct"),
    ("r_qty", "Количество возвратов, шт", "int"),
    ("r_sum", "Сумма возвратов, руб", "money"),
    ("h", "РАСХОДЫ OZON (без комиссии, логистики и эквайринга)", "h"),
    ("x_storage", "Платное хранение / размещение, руб", "money"),
    ("x_accept", "Платная приемка, руб", "money"),
    ("x_cross", "Кросс-докинг, руб", "money"),
    ("x_util", "Утилизация, руб", "money"),
    ("x_comp", "Компенсации, руб", "money"),
    ("x_ins", "Страхование, руб", "money"),
    ("x_other", "Другие расходы Ozon, руб", "money"),
    ("h", "БАЛАНС (на сейчас)", "h"),
    ("st_qty", "Остатки FBO, шт", "int"),
    ("st_cost", "Остатки в себестоимости, руб", "money"),
]


def compute(c, shop: int, d_from: date, d_to: date, skus: list[int] | None = None) -> dict:
    days = [d_to - timedelta(days=i) for i in range((d_to - d_from).days + 1)]
    lo = min(days) - timedelta(days=BUYOUT_LAG[1])
    cost = _costs(c, shop, d_to)
    com = _commission(c, shop)
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1",
                    (shop, d_to)).fetchone() or {"regime": "Другая СНО", "rate": 0}
    regime, rate = tax["regime"], float(tax["rate"] or 0)
    rate = rate / 100 if rate > 1 else rate
    flt = (lambda s: skus is None or s in skus)
    V = defaultdict(lambda: defaultdict(float))

    
    post = c.execute("""SELECT order_day, sku, scheme, qty, price, status FROM oz_postings
                        WHERE account_id=%s AND order_day BETWEEN %s AND %s""", (shop, lo, d_to)).fetchall()
    fin_q = defaultdict(lambda: [0.0, 0.0])          
    for p in post:
        if not flt(p["sku"]):
            continue
        q, s = float(p["qty"] or 0), float(p["qty"] or 0) * float(p["price"] or 0)
        cancelled = (p["status"] or "").startswith("cancel")
        fin_q[p["order_day"]][0] += q
        fin_q[p["order_day"]][1] += q if cancelled else 0
        if p["order_day"] < min(days):
            continue
        v = V[p["order_day"]]
        v["o_sum"] += s
        v["o_qty"] += q
        pc, dl = com.get(p["sku"], {}).get(p["scheme"], (0, 0))
        v["_com"] += s * pc / 100
        v["_log"] += q * dl
        v["_cost"] += q * cost.at(p["sku"], p["order_day"])
        if cancelled:
            v["c_qty"] += q
            v["c_sum"] += s

    for r in c.execute("SELECT day, sku, m FROM oz_analytics WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, min(days), d_to)):
        if not flt(r["sku"]):
            continue
        v, m = V[r["day"]], r["m"]
        v["a_rev"] += float(m.get("revenue") or 0)
        v["a_units"] += float(m.get("ordered_units") or 0)
        v["a_views"] += float(m.get("hits_view") or 0)
        v["a_sess"] += float(m.get("session_view") or 0)
        v["a_cart"] += float(m.get("hits_tocart") or 0)

    
    for t in c.execute("""SELECT op_day, operation_type, type_name, tx_type, amount, accruals_for_sale, sale_commission, delivery_charge,
                                 return_delivery_charge, services_total, skus, qty, raw, raw->'services' services
                          FROM oz_transactions WHERE account_id=%s AND op_day BETWEEN %s AND %s""", (shop, min(days), d_to)):
        sk = t["skus"] or []
        if skus is not None and (not sk or not any(s in skus for s in sk)):
            continue
        parts = transaction_parts(t)
        chosen = {s: p for s, p in parts.items() if flt(s)}
        share = sum(p[1] for p in chosen.values()) if skus is not None else 1.0
        v = V[t["op_day"]]
        amt = float(t["amount"] or 0) * share
        v["f_total"] += amt
        typ = (t["tx_type"] or "").lower()
        if typ in ("orders", "returns"):
            acc = float(t["accruals_for_sale"] or 0) * share
            v["f_com"] += float(t["sale_commission"] or 0) * share
            v["f_log"] += (float(t["delivery_charge"] or 0) + float(t["return_delivery_charge"] or 0) + float(t["services_total"] or 0)) * share
            n = sum(p[0] for p in chosen.values())
            cs = sum(cost.at(s, t["op_day"]) * p[0] for s, p in chosen.items())
            if typ == "orders" or acc > 0:
                v["b_qty"] += n
                v["b_sum"] += acc
                v["b_cost"] += cs
            else:
                v["r_qty"] += n
                v["r_sum"] += acc
                v["b_cost"] -= cs
            continue
        k = _cls(f"{t['operation_type']} {t['type_name']} " + " ".join(str(s.get("name")) for s in t["services"] or []))
        key = {"ads": "f_ads", "acquiring": "f_acq", "logistics": "f_log", "storage": "x_storage", "acceptance": "x_accept",
               "crossdock": "x_cross", "utilization": "x_util", "compensation": "x_comp", "insurance": "x_ins"}.get(k, "x_other")
        v[key] += amt

    
    
    perf = c.execute("SELECT 1 FROM oz_ad_daily WHERE account_id=%s LIMIT 1", (shop,)).fetchone() is not None
    if perf:
        for r in c.execute("""SELECT d.day, d.views, d.clicks, d.spent, d.orders, d.orders_money, k.skus FROM oz_ad_daily d
                              LEFT JOIN oz_ad_campaigns k ON k.account_id=d.account_id AND k.campaign_id=d.campaign_id
                              WHERE d.account_id=%s AND d.day BETWEEN %s AND %s""", (shop, min(days), d_to)):
            sk = r["skus"] or []
            share = 1.0 if skus is None else (sum(1 for x in sk if x in skus) / len(sk) if sk else 0.0)
            if not share:
                continue
            v = V[r["day"]]
            v["p_ads"] -= float(r["spent"] or 0) * share
            v["ad_views"] += float(r["views"] or 0) * share
            v["ad_clicks"] += float(r["clicks"] or 0) * share
            v["ad_orders"] += float(r["orders"] or 0) * share
            v["ad_money"] += float(r["orders_money"] or 0) * share

    st = c.execute("""WITH last AS (SELECT max(snap_at) t FROM oz_stocks WHERE account_id=%s)
                      SELECT s.sku, last.t snap_at, sum(coalesce(available,0)+coalesce(other,0)) q FROM oz_stocks s, last
                      WHERE s.account_id=%s AND s.snap_at=last.t GROUP BY 1,2""", (shop, shop)).fetchall()
    st_qty = sum(float(r["q"] or 0) for r in st if flt(r["sku"]))
    st_cost = sum(float(r["q"] or 0) * cost.at(r["sku"], r["snap_at"].date()) for r in st if flt(r["sku"]))

    for d in days:
        v = V[d]
        a, b = d - timedelta(days=BUYOUT_LAG[1]), d - timedelta(days=BUYOUT_LAG[0])
        tot = sum(x[0] for k, x in fin_q.items() if a <= k <= b)
        canc = sum(x[1] for k, x in fin_q.items() if a <= k <= b)
        share = 1 - canc / tot if tot else 1.0
        v["share"] = share
        v["o_avg"] = v["o_sum"] / v["o_qty"] if v["o_qty"] else 0
        v["a_conv"] = v["a_cart"] / v["a_sess"] if v["a_sess"] else 0
        v["ob_sum"] = v["o_sum"] * share
        v["ob_qty"] = v["o_qty"] * share
        v["o_com"] = -v["_com"] * share
        v["o_log"] = -v["_log"] * share
        v["o_cost"] = v["_cost"] * share
        v["ads"] = v["p_ads"] if perf else v["f_ads"]      
        v["ad_ctr"] = v["ad_clicks"] / v["ad_views"] if v["ad_views"] else 0
        v["drr"] = -v["ads"] / v["o_sum"] if v["o_sum"] else 0
        if regime == "УСН доход":
            v["o_tax"] = v["ob_sum"] * rate
            v["f_tax"] = max(v["b_sum"] + v["r_sum"], 0) * rate
        elif regime == "УСН доходы-расходы":
            v["o_tax"] = max(v["ob_sum"] + v["o_com"] + v["o_log"] + v["ads"] - v["o_cost"], 0) * rate
            v["f_tax"] = max(v["f_total"] - v["b_cost"], 0) * rate
        v["o_profit"] = v["ob_sum"] + v["o_com"] + v["o_log"] + v["ads"] - v["o_cost"] - v["o_tax"]
        v["o_profit_p"] = v["o_profit"] / v["ob_sum"] if v["ob_sum"] else 0
        v["b_avg"] = v["b_sum"] / v["b_qty"] if v["b_qty"] else 0
        v["f_profit"] = v["f_total"] - v["b_cost"] - v["f_tax"]
        v["f_profit_p"] = v["f_profit"] / v["b_sum"] if v["b_sum"] else 0
        v["c_share"] = v["c_qty"] / v["o_qty"] if v["o_qty"] else 0
    V[days[0]]["st_qty"], V[days[0]]["st_cost"] = st_qty, st_cost

    rows = []
    for key, lab, fmt in ROWS:
        if key.startswith("ad_") and not perf:
            continue
        row = {"label": lab, "fmt": fmt, "key": key}
        if fmt != "h":
            for i, d in enumerate(days):
                if key.startswith("st_") and i:
                    continue
                row[f"d{i}"] = round(V[d][key], 4 if fmt == "pct" else 2)
        rows.append(row)
    return {"days": [str(d) for d in days], "rows": rows, "tax": regime}

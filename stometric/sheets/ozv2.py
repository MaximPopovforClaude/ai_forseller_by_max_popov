"""Self-hosted application component."""

import re
from collections import defaultdict
from datetime import date, timedelta

from .ozdash import _costs, transaction_parts
from .. import ozon_order_prices as order_prices

AD_KINDS = ["Вывод в топ", "Поиск", "Поиск и рекомендации", "Баннерная"]
AD_RX = re.compile(r"продвиж|оплата за клик|оплата за заказ|реклам|трафарет|promotion|costperclick|cpc", re.I)
OZZ_RX = re.compile(r"продвижение товара|оплата за заказ|searchpromo|search_promo", re.I)


SERVICE_RU = {
    "MarketplaceServiceItemDirectFlowLogistic": "Логистика",
    "MarketplaceServiceItemDirectFlowLogisticVDC": "Логистика",
    "MarketplaceServiceItemDelivToCustomer": "Доставка до места выдачи",
    "MarketplaceServiceItemReturnFlowLogistic": "Обратная логистика",
    "MarketplaceServiceItemRedistributionLastMileCourier": "Доставка до места выдачи силами Ozon",
    "MarketplaceServiceItemRedistributionLastMilePVZ": "Доставка до места выдачи силами Ozon",
    "MarketplaceServiceItemReturnAfterDelivToCustomer": "Обработка возвратов, отмен и невыкупов партнёрами",
    "MarketplaceServiceItemReturnNotDelivToCustomer": "Обработка возвратов, отмен и невыкупов партнёрами",
    "MarketplaceServiceItemReturnPartGoodsCustomer": "Обработка возвратов, отмен и невыкупов партнёрами",
    "MarketplaceServiceItemRedistributionReturnsPVZ": "Обработка возвратов, отмен и невыкупов партнёрами",
    "MarketplaceServiceItemFulfillment": "Сборка заказа",
    "MarketplaceServiceItemPickup": "Выезд за отправлениями",
    "MarketplaceServiceItemDropoffFF": "Обработка отправления (drop-off)",
    "MarketplaceServiceItemDropoffPVZ": "Обработка отправления (drop-off)",
    "MarketplaceServiceItemDropoffSC": "Обработка отправления (drop-off)",
    "MarketplaceRedistributionOfAcquiringOperation": "Эквайринг",
    "MarketplaceServicePremiumCashbackIndividualPoints": "Баллы за отзывы",
}


def periods(kind: str, d_from: date, d_to: date) -> list[tuple[str, date, date]]:
    """Колонки-периоды от новых к старым: day — до 62 дней, week — ISO-недели, month — месяцы."""
    out = []
    if kind == "day":
        d = d_to
        while d >= d_from and len(out) < 62:
            out.append((f"{d:%d.%m.%Y}", d, d))
            d -= timedelta(days=1)
    elif kind == "week":
        a = d_to - timedelta(days=d_to.weekday())
        while a + timedelta(days=6) >= d_from:
            b = a + timedelta(days=6)
            out.append((f"нед {a.isocalendar()[1]} ({a:%d.%m}–{b:%d.%m})", max(a, d_from), min(b, d_to)))
            a -= timedelta(days=7)
    else:
        a = d_to.replace(day=1)
        while a >= d_from.replace(day=1):
            b = (a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            out.append((f"{a:%m.%Y}", max(a, d_from), min(b, d_to)))
            a = (a - timedelta(days=1)).replace(day=1)
    return out


def _skus_of_group(c, shop: int, grp: str) -> list[int]:
    if grp.startswith("model:") and grp[6:].isdigit():
        return [r["sku"] for r in c.execute("SELECT sku FROM oz_products WHERE account_id=%s AND model_id=%s AND sku IS NOT NULL",
                                            (shop, int(grp[6:])))]
    return [r["nm_id"] for r in c.execute("SELECT nm_id FROM article_groups WHERE account_id=%s AND group_name=%s", (shop, grp))]


class Cached:
    """Обёртка соединения: одинаковые запросы читаем из базы один раз (Юнитка считает compute по каждому SKU)."""

    class _Res(list):
        def fetchone(self):
            return self[0] if self else None

        def fetchall(self):
            return list(self)

    def __init__(self, c):
        self.c, self.m = c, {}

    def execute(self, sql, params=()):
        k = (sql, tuple(tuple(x) if isinstance(x, list) else x for x in params))
        if k not in self.m:
            self.m[k] = self._Res(self.c.execute(sql, params).fetchall())
        return self.m[k]


def compute(c, shop: int, kind: str, d_from: date, d_to: date, skus: list[int] | None = None,
            per: list[tuple[str, date, date]] | None = None) -> dict:
    per = per or periods(kind, d_from, d_to)
    lo, hi = min(p[1] for p in per), max(p[2] for p in per)
    flt = (lambda s: skus is None or s in skus)
    cost = _costs(c, shop, hi)
    D = defaultdict(lambda: defaultdict(float))          
    names = {"svc": set(), "item": set(), "non": set()}
    order_days = order_prices.load_daily(c, shop, lo, hi, skus)

    
    for r in c.execute("SELECT day, sku, m FROM oz_analytics WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, lo, hi)):
        if not flt(r["sku"]):
            continue
        v, m = D[r["day"]], r["m"]
        for k, src in (("views", "hits_view"), ("sess", "session_view"), ("sess_search", "session_view_search"),
                       ("views_search", "hits_view_search"), ("clicks", "hits_view_pdp"), ("uclicks", "session_view_pdp"),
                       ("cart", "hits_tocart"), ("ordered", "ordered_units"), ("ordered_sum", "revenue"), ("cancel", "cancellations"),
                       ("returned", "returns")):
            v[k] += float(m.get(src) or 0)
        pos = float(m.get("position_category") or 0)
        if pos > 0:
            v["_pos_sum"] += pos
            v["_pos_n"] += 1

    
    real = c.execute("SELECT 1 FROM oz_realization_day WHERE account_id=%s LIMIT 1", (shop,)).fetchone() is not None
    tot_sold = defaultdict(float)                        
    if real:
        for r in c.execute("SELECT * FROM oz_realization_day WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, lo, hi)):
            net = float(r["sale_amount"] or 0) - float(r["ret_amount"] or 0)
            tot_sold[r["day"]] += net
            if not flt(r["sku"]):
                continue
            v = D[r["day"]]
            v["sale_qty"] += float(r["sale_qty"] or 0)
            v["ret_qty"] += float(r["ret_qty"] or 0)
            v["sale_amt"] += float(r["sale_amount"] or 0)
            v["ret_amt"] += float(r["ret_amount"] or 0)
            v["bonus"] += float(r["bonus"] or 0)
            v["coinvest"] += float(r["coinvest"] or 0)
            v["commission"] += float(r["commission"] or 0)
            v["cost"] -= (float(r["sale_qty"] or 0) - float(r["ret_qty"] or 0)) * cost.at(r["sku"], r["day"])

    
    
    raw_column = "NULL::jsonb AS raw" if real and skus is None else "raw"
    for t in c.execute(f"""SELECT op_day, operation_type, type_name, tx_type, amount, accruals_for_sale, sale_commission, delivery_charge,
                                 return_delivery_charge, skus, qty, {raw_column}, raw->'services' services
                          FROM oz_transactions WHERE account_id=%s AND op_day BETWEEN %s AND %s""", (shop, lo, hi)):
        sk = t["skus"] or []
        typ = (t["tx_type"] or "").lower()
        day = t["op_day"]
        amt = float(t["amount"] or 0)
        mine = skus is None or any(s in skus for s in sk)
        trade = typ in ("orders", "returns", "delivery")
        if trade:
            acc = float(t["accruals_for_sale"] or 0)
            if not real:
                tot_sold[day] += acc    
            if not mine:
                continue
        elif sk and not mine:
            continue
        
        
        needs_parts = mine and (skus is not None or (not real and trade and typ != "delivery"))
        parts = transaction_parts(t) if needs_parts else {}
        chosen = {s: p for s, p in parts.items() if flt(s)}
        share = sum(p[1] for p in chosen.values()) if skus is not None else 1.0
        if trade:         
            v = D[day]
            v["payout"] += amt * share
            if not real and typ != "delivery":
                n = sum(p[0] for p in chosen.values()) or (1 if not sk and skus is None else 0)
                cogs = sum(cost.at(s, day) * p[0] for s, p in chosen.items())
                if typ == "orders" or acc > 0:
                    v["sale_qty"] += n
                    v["sale_amt"] += acc * share
                    v["cost"] -= cogs
                else:
                    v["ret_qty"] += n
                    v["ret_amt"] += -acc * share
                    v["cost"] += cogs
                v["commission"] += float(t["sale_commission"] or 0) * share
            for k, val in (("Логистика", t["delivery_charge"]), ("Обратная логистика", t["return_delivery_charge"])):
                if val:
                    v["svc:" + k] += float(val) * share
                    names["svc"].add(k)
            for s in t["services"] or []:
                nm = SERVICE_RU.get(str(s.get("name")), str(s.get("name")))
                key = "item" if nm == "Эквайринг" else "svc"
                v[f"{key}:{nm}"] += float(s.get("price") or 0) * share
                names[key].add(nm)
            continue
        label = t["type_name"] or t["operation_type"] or "Прочее"
        if sk:                                            
            if mine:
                D[day][f"item:{label}"] += amt * share
                D[day]["payout"] += amt * share
                names["item"].add(label)
        else:                                             
            if skus is not None and AD_RX.search(f"{label} {t['operation_type']}"):
                continue
            D[day][f"non:{label}" if skus is None else f"_non_all:{label}"] += amt
            names["non"].add(label)
        if OZZ_RX.search(f"{label} {t['operation_type']}") and skus is None:
            D[day]["ozz_spent"] += -amt

    
    for r in c.execute("SELECT day, sku, qty, amount FROM oz_buyouts WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, lo, hi)):
        if flt(r["sku"]):
            v = D[r["day"]]
            v["bo_amt"] += float(r["amount"] or 0)
            v["bo_qty"] += float(r["qty"] or 0)
            v["cost"] -= float(r["qty"] or 0) * cost.at(r["sku"], r["day"])

    
    kinds = {r["campaign_id"]: (r["kind"] or "Поиск и рекомендации", r["skus"] or [])
             for r in c.execute("SELECT campaign_id, kind, skus FROM oz_ad_campaigns WHERE account_id=%s", (shop,))}
    
    q_sku = ("SELECT day, campaign_id, sku, views, clicks, to_cart, spent, orders, orders_money, models, models_money FROM oz_ad_sku "
             "WHERE account_id=%s AND day BETWEEN %s AND %s")
    q_day = ("SELECT day, campaign_id, NULL::bigint sku, views, clicks, NULL::numeric to_cart, spent, orders, orders_money, "
             "NULL::numeric models, NULL::numeric models_money FROM oz_ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s")
    ad_rows = c.execute(q_sku, (shop, lo, hi)).fetchall()
    have = {(r["campaign_id"], r["day"]) for r in ad_rows}
    by_sku = bool(have)
    ad_rows += [r for r in c.execute(q_day, (shop, lo, hi)) if (r["campaign_id"], r["day"]) not in have]
    for r in ad_rows:
        kd, csk = kinds.get(r["campaign_id"], ("Поиск и рекомендации", []))
        if kd not in AD_KINDS and kd != "ОЗЗ":
            continue
        if r["sku"] is not None:
            share = 1.0 if flt(r["sku"]) else 0.0
        else:
            share = 1.0 if skus is None else (sum(1 for x in csk if x in skus) / len(csk) if csk else 0.0)
        if not share:
            continue
        if kd == "ОЗЗ":                            
            D[r["day"]]["ozz.orders"] += float(r["orders"] or 0) * share
            D[r["day"]]["ozz.spent"] += float(r["spent"] or 0) * share
            continue
        for pref in ("ad", f"ad[{kd}]"):
            v = D[r["day"]]
            for k in ("views", "clicks", "to_cart", "spent", "orders", "orders_money", "models", "models_money"):
                v[f"{pref}.{k}"] += float(r[k] or 0) * share
    if skus is not None and by_sku:               
        pass

    
    snaps = [r["snap_at"] for r in c.execute("SELECT DISTINCT snap_at FROM oz_stocks WHERE account_id=%s AND snap_at::date <= %s ORDER BY 1",
                                             (shop, hi))]

    def stock_at(d: date):
        ts = [s for s in snaps if s.date() <= d]
        if not ts:
            return None
        av = ot = money = 0.0
        for r in c.execute("SELECT sku, sum(coalesce(available,0)) a, sum(coalesce(other,0)) o FROM oz_stocks WHERE account_id=%s AND snap_at=%s "
                           "GROUP BY 1", (shop, ts[-1])):
            if flt(r["sku"]):
                av += float(r["a"] or 0)
                ot += float(r["o"] or 0)
                money += (float(r["a"] or 0) + float(r["o"] or 0)) * cost.at(r["sku"], ts[-1].date())
        return av, ot, money

    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1",
                    (shop, hi)).fetchone() or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0}
    rate = float(tax["rate"] or 0)
    rate = rate / 100 if rate > 1 else rate
    vat = float(tax.get("vat_rate") or 0)
    vat = vat / 100 if vat > 1 else vat

    def agg(a: date, b: date) -> dict:
        v = defaultdict(float)
        d = a
        while d <= b:
            for k, x in D[d].items():
                v[k] += x
            if skus is not None:                          
                mine_s = D[d]["sale_amt"] - D[d]["ret_amt"]
                share = mine_s / tot_sold[d] if tot_sold[d] else 0
                for k, x in D[d].items():
                    if k.startswith("_non_all:"):
                        v["non:" + k[9:]] += x * share
            d += timedelta(days=1)
        n = (b - a).days + 1
        v["sold_qty"] = v["sale_qty"] - v["ret_qty"]
        v["sold_amt"] = v["sale_amt"] - v["ret_amt"]
        v["paid"] = v["sold_amt"] - v["bonus"] - v["coinvest"] if real else 0
        v["freq"] = v["views"] / v["sess"] if v["sess"] else 0
        v["buyout_pct"] = v["sold_amt"] / v["ordered_sum"] if v["ordered_sum"] else 0
        v["soinv"] = v["bonus"] / v["sold_amt"] if v["sold_amt"] and real else 0
        v["avg_order"] = v["ordered_sum"] / v["ordered"] if v["ordered"] else 0
        v["avg_paid"] = v["paid"] / v["sold_qty"] if v["sold_qty"] and real else 0
        v["keep"] = 1 - (v["returned"] + v["cancel"]) / v["ordered"] if v["ordered"] else 0
        v["show2order"] = v["ordered"] / v["views"] if v["views"] else 0
        v["click2order"] = v["ordered"] / v["uclicks"] if v["uclicks"] else 0
        v["pos"] = v["_pos_sum"] / v["_pos_n"] if v["_pos_n"] else 0
        v["ctr"] = v["clicks"] / v["views"] if v["views"] else 0
        v["cr_cart"] = v["cart"] / v["uclicks"] if v["uclicks"] else 0
        v["cr_order"] = v["ordered"] / v["cart"] if v["cart"] else 0
        v["pik"] = v["views_search"] / v["views"] if v["views"] else 0
        st = stock_at(b)
        if st:
            v["st_av"], v["st_way"], v["st_money"] = st
            v["st_turn"] = (st[0] + st[1]) / (v["ordered"] / n) if v["ordered"] else 0
        v["ad.spent_ozz"] = v["ad.spent"] + v["ozz_spent"]
        for pref in ["ad"] + [f"ad[{k}]" for k in AD_KINDS]:
            g = lambda k: v[f"{pref}.{k}"]  
            om = g("orders_money") + g("models_money")
            v[f"{pref}.ctr"] = g("clicks") / g("views") if g("views") else 0
            v[f"{pref}.cr_cart"] = g("to_cart") / g("clicks") if g("clicks") else 0
            v[f"{pref}.cr_order"] = g("orders") / g("to_cart") if g("to_cart") else 0
            v[f"{pref}.drr"] = g("spent") / om if om else 0
            v[f"{pref}.cpc"] = g("spent") / g("clicks") if g("clicks") else 0
            v[f"{pref}.cpm"] = g("spent") / g("views") * 1000 if g("views") else 0
            v[f"{pref}.cpcart"] = g("spent") / g("to_cart") if g("to_cart") else 0
            v[f"{pref}.cpo"] = g("spent") / g("orders") if g("orders") else 0
        v["ad.cpcart"] = v["ad.spent_ozz"] / v["ad.to_cart"] if v["ad.to_cart"] else 0   
        v["ozz.cpo"] = v["ozz.spent"] / v["ozz.orders"] if v["ozz.orders"] else 0
        om = v["ad.orders_money"] + v["ad.models_money"]
        v["ad.drr_ozz"] = v["ad.spent_ozz"] / om if om else 0
        v["drr_fact"] = v["ad.spent_ozz"] / v["ordered_sum"] if v["ordered_sum"] else 0
        v["sales_total"] = v["sold_amt"] + v["bo_amt"]
        v["commission_pct"] = -v["commission"] / v["sold_amt"] if v["sold_amt"] else 0
        v["svc_total"] = sum(x for k, x in v.items() if k.startswith("svc:"))
        v["item_total"] = sum(x for k, x in v.items() if k.startswith("item:"))
        v["non_total"] = sum(x for k, x in v.items() if k.startswith("non:"))
        v["ads_filter"] = -(v["ad.spent"] + v["ozz.spent"]) if skus is not None else 0   
        v["vat"] = -(v["sales_total"] - v["bonus"]) * vat / (1 + vat) if vat else 0
        if tax["regime"] == "УСН доходы-расходы":
            base = v["sales_total"] + v["commission"] + v["svc_total"] + v["item_total"] + v["non_total"] + v["cost"] + v["ads_filter"]
            v["tax"] = -max(base, 0) * rate
        else:
            v["tax"] = -max(v["sales_total"] - v["bonus"] + v["vat"], 0) * rate
        v["cost_tax"] = v["cost"] + v["tax"] + v["vat"]
        v["profit"] = (v["sales_total"] + v["commission"] + v["svc_total"] + v["item_total"] + v["non_total"] + v["cost_tax"]
                       + v["ads_filter"])
        v["margin"] = v["profit"] / v["sales_total"] if v["sales_total"] else 0
        v["payout_all"] = v["payout"] + v["non_total"]
        v.update(order_prices.period(order_days, a, b))
        return v

    cols = [agg(a, b) for _, a, b in per]
    tot = agg(lo, hi)

    def ad_block(pref: str, title: str, extra: bool = False):
        rows = [("h", title, "h"), (f"{pref}.views", "Показы", "int"), (f"{pref}.clicks", "Клики", "int"),
                (f"{pref}.ctr", "CTR %", "pct"), (f"{pref}.to_cart", "Корзины", "int"), (f"{pref}.cr_cart", "CR корзины %", "pct"),
                (f"{pref}.orders", "Заказы, шт", "int"), (f"{pref}.models", "Заказы модели", "int"),
                (f"{pref}.cr_order", "CR - конверсия в заказ %", "pct"), (f"{pref}.orders_money", "Заказы, ₽", "money"),
                (f"{pref}.models_money", "Заказы модели ₽", "money"), (f"{pref}.spent", "Расход, ₽, с НДС", "money")]
        if extra:
            rows += [("ad.spent_ozz", "Расход, ₽, с НДС + ОЗЗ", "money")]
        rows += [(f"{pref}.drr", "ДРР %", "pct")]
        if extra:
            rows += [("ad.drr_ozz", "ДРР % с учетом ОЗЗ", "pct")]
        rows += [(f"{pref}.cpc", "CPC", "num"), (f"{pref}.cpm", "CPM", "num"), (f"{pref}.cpcart", "Стоимость одной корзины", "num"),
                 (f"{pref}.cpo", "CPO", "num")]
        return rows

    ROWS = [
        ("h", "ВОРОНКА", "h"),
        ("views", "Показы, всего", "int"), ("sess", "Уникальные посетители (всего)", "int"),
        ("sess_search", "Уникальные посетители (поиск и каталог)", "int"), ("freq", "Частота показов 1 клиенту", "num"),
        ("views_search", "Показы в поиске и каталоге", "int"), ("clicks", "Клики (показы на карточке)", "int"),
        ("uclicks", "Уникальные клики", "int"), ("cart", "В корзину, всего", "int"), ("ordered", "Заказано товаров", "int"),
        ("sold_qty", "Продано товаров", "int"), ("sale_qty", "- Продажи шт", "int"), ("ret_qty", "- Возвраты шт", "int"),
        ("ordered_sum", "Заказано на сумму (аналитика Ozon), руб", "money"),
        ("order_seller_sum", order_prices.SELLER_LABEL, "money"),
        ("order_customer_sum", order_prices.CUSTOMER_LABEL, "money"),
        ("order_price_coverage", order_prices.COVERAGE_LABEL, "pct"), ("sold_amt", "Продано на сумму", "money"), ("sale_amt", "- Продажи ₽", "money"),
        ("ret_amt", "- Возвраты ₽", "money"), ("buyout_pct", "% выкупа", "pct"), ("bonus", "Баллы за скидки", "money"),
        ("soinv", "Соинвест финансовый", "pct"), ("avg_order", "Средняя сумма заказа", "money"), ("paid", "Оплачено покупателем", "money"),
        ("avg_paid", "Средняя цена для покупателя", "money"), ("cancel", "Отменено товаров", "int"), ("returned", "Возвращено товаров", "int"),
        ("keep", "Соотношение заказов и отмен/возвратов", "pct"), ("show2order", "Из показа в заказ %", "pct"),
        ("click2order", "Из клика в заказ %", "pct"), ("pos", "Позиция в поиске и каталоге", "num"),
        ("ctr", "CTR - конверсия из показов в клики %", "pct"), ("cr_cart", "CR - конверсия из кликов в корзину %", "pct"),
        ("cr_order", "CR - конверсия в заказ %", "pct"), ("drr_fact", "ДРР, факт %", "pct"), ("pik", "Доля ПиК, %", "pct"),
        ("h", "ОСТАТКИ (на конец периода)", "h"),
        ("st_av", "Доступно к продаже", "int"), ("st_way", "В пути / в обработке", "int"), ("st_turn", "Оборачиваемость дней", "num"),
        ("st_money", "ДС в товаре (по себестоимости)", "money"),
    ]
    ROWS += ad_block("ad", "РЕКЛАМА", extra=True)
    for k in AD_KINDS:
        ROWS += ad_block(f"ad[{k}]", k)
    ROWS += [("h", "ОПЛАТА ЗА ЗАКАЗ", "h"), ("ozz.orders", "Заказы, шт", "int"), ("ozz.spent", "Расход, ₽, с НДС", "money"),
             ("ozz.cpo", "CPO", "num")]
    ROWS += [("h", "ФИНАНСЫ", "h"), ("sales_total", "Продажи итого", "money"), ("sold_amt", "- Продажи за вычетом возвратов", "money"),
             ("bo_amt", "- Выкупы Ozon", "money"), ("bo_qty", "- Выкупы Ozon шт", "int"), ("commission", "- Комиссия", "money"),
             ("commission_pct", "- Комиссия %", "pct"), ("bonus", "- Баллы озон", "money"), ("coinvest", "- Программы партнеров", "money"),
             ("svc_total", "Доставка покупателю", "money")]
    order = lambda pref: sorted(names[pref], key=lambda n: tot[f"{pref}:{n}"])  
    ROWS += [(f"svc:{n}", f"- {n}", "money") for n in order("svc")]
    ROWS += [("item_total", "Расходы с привязкой к артикулу", "money")] + [(f"item:{n}", f"- {n}", "money") for n in order("item")]
    ROWS += [("non_total", "Расходы без привязки к артикулу" + (" (доля по продажам)" if skus is not None else ""), "money")]
    ROWS += [(f"non:{n}", f"- {n}", "money") for n in order("non")]
    ROWS += [("cost_tax", "Себестоимость и налоги", "money"), ("cost", "Себестоимость", "money"), ("tax", f"Налог ({tax['regime']})", "money"),
             ("vat", "НДС", "money")]
    if skus is not None:
        ROWS += [("ads_filter", "Расход на рекламу выбранных товаров", "money")]
    ROWS += [("profit", "Прибыль", "money"), ("margin", "Маржинальность", "pct"), ("payout_all", "Всего к выплате за период", "money")]

    SUMMABLE_NOT = ("pct", "num")
    out = []
    for key, lab, fmt in ROWS:
        row = {"key": key, "label": lab, "fmt": fmt}
        if fmt != "h":
            vals = [cv[key] for cv in cols]
            if key in order_prices.KEYS:
                precision = 4 if fmt == "pct" else 2
                row["total"] = round(tot[key], precision) if tot[key] is not None else None
                row["avg"] = (round(tot[key] if fmt == "pct" else tot[key] / len(cols), precision)
                              if tot[key] is not None and cols else None)
                for i, x in enumerate(vals):
                    row[f"p{i}"] = round(x, precision) if x is not None else None
                out.append(row)
                continue
            if key.startswith("st_"):
                row["total"] = round(cols[0][key], 2) if cols else None
                row["avg"] = round(sum(vals) / len(vals), 2) if vals else None
            else:
                row["total"] = round(tot[key], 4 if fmt in SUMMABLE_NOT else 2)
                row["avg"] = round(tot[key] if fmt in SUMMABLE_NOT else tot[key] / len(cols), 4 if fmt in SUMMABLE_NOT else 2)
            for i, x in enumerate(vals):
                row[f"p{i}"] = round(x, 4 if fmt in SUMMABLE_NOT else 2) if x else None
            if not any(row.get(f"p{i}") for i in range(len(vals))) and not row["total"] and not lab.startswith(("Продажи", "Прибыль")):
                row["empty"] = True
        out.append(row)
    
    res, i = [], 0
    while i < len(out):
        r = out[i]
        if r["fmt"] == "h" and r["label"] in AD_KINDS + ["ОПЛАТА ЗА ЗАКАЗ"]:
            j = i + 1
            while j < len(out) and out[j]["fmt"] != "h":
                j += 1
            if all(x.get("empty") for x in out[i + 1:j]):
                i = j
                continue
        res.append(r)
        i += 1
    return {"periods": [p[0] for p in per], "rows": res, "sources": {"realization": real, "ads_by_sku": by_sku}, "cols": cols, "tot": tot,
            "row_defs": ROWS, "order_prices_note": order_prices.NOTE}



UNIT = [("sold_amt", "Продажи - Возвраты ₽", "money", False), ("commission", "Комиссия", "money", True), ("bonus", "Баллы Ozon", "money", True),
        ("cost", "Себестоимость", "money", True), ("paid", "Цена продажи (оплачено покупателем)", "money", False),
        ("svc_total", "Расходы на доставку итого", "money", True), ("item_total", "Расходы с привязкой к артикулу", "money", True),
        ("non_total", "Расходы без привязки к артикулу (доля по продажам)", "money", True), ("ads_filter", "Расход реклама итого (с ОЗЗ)", "money", True),
        ("ad[Поиск].spent", "Расход Поиск", "money", True), ("ad[Поиск и рекомендации].spent", "Расход Поиск и рекомендации", "money", True),
        ("ad[Вывод в топ].spent", "Расход Вывод в топ", "money", True), ("ozz.spent", "Расход ОЗЗ", "money", True),
        ("views", "Показы, всего", "int", False), ("clicks", "Клики", "int", False), ("ctr", "CTR", "share", False), ("cart", "Корзины", "int", False),
        ("cr_cart", "CR корзины/клики", "share", False), ("ordered", "Заказы", "int", False), ("cr_order", "CR заказы/корзины", "share", False),
        ("buyout_pct", "% выкупа", "share", False), ("tax", "Налог", "money", True), ("vat", "НДС", "money", True), ("profit", "Прибыль", "money", True),
        ("roi", "ROI", "share", False)]
NEG = ("ad[Поиск].spent", "ad[Поиск и рекомендации].spent", "ad[Вывод в топ].spent", "ozz.spent")     


def unit(c, shop: int, p1: tuple[date, date], p2: tuple[date, date], skus: list[int] | None = None, per_unit: bool = False) -> dict:
    cc = Cached(c)
    names = {r["sku"]: r for r in c.execute("SELECT sku, offer_id, name, model_id FROM oz_products WHERE account_id=%s AND sku IS NOT NULL", (shop,))}
    sold = [r["sku"] for r in c.execute("""SELECT sku, sum(sale_amount) s FROM oz_realization_day WHERE account_id=%s AND day BETWEEN %s AND %s
                                           GROUP BY 1 HAVING sum(sale_amount) <> 0 ORDER BY 2 DESC""", (shop, min(p1[0], p2[0]), max(p1[1], p2[1])))]
    if skus is not None:
        sold = [x for x in sold if x in skus]
    per = [("Период 1", *p1), ("Период 2", *p2)]
    rows = []
    for sku in sold:
        r = compute(cc, shop, "day", min(p1[0], p2[0]), max(p1[1], p2[1]), [sku], per=per)
        nm = names.get(sku) or {}
        both = [(lab, v) for lab, v in zip(("Период 1", "Период 2"), r["cols"])]
        tot = defaultdict(float)
        for _, v in both:
            tot["sold_qty"] += v["sold_qty"]
            for k, _, f, _ in UNIT:
                if f != "share":
                    tot[k] += v[k]
        tot["ctr"] = tot["clicks"] / tot["views"] if tot["views"] else 0
        tot["cr_cart"] = tot["cart"] / tot["clicks"] if tot["clicks"] else 0
        tot["cr_order"] = tot["ordered"] / tot["cart"] if tot["cart"] else 0
        tot["buyout_pct"] = tot["sold_amt"] / sum(v["ordered_sum"] for _, v in both) if sum(v["ordered_sum"] for _, v in both) else 0
        for lab, v in both + [("Всего", tot)]:
            row = {"model_id": str(nm.get("model_id") or ""), "sku": str(sku), "offer_id": nm.get("offer_id"), "name": nm.get("name"), "period": lab}
            base = v["sold_amt"]
            qty = v["sold_qty"]
            row["sold_qty"] = round(qty)
            for k, _, f, pct in UNIT:
                x = v[k]
                if k in NEG:
                    x = -x
                if k == "roi":
                    x = v["profit"] / -v["cost"] if v["cost"] else 0
                if per_unit and f == "money":                   
                    x = x / qty if qty > 0 else None
                row[k] = None if x is None else round(x, 4 if f == "share" else 2)
                if pct:
                    row[k + "%"] = round(v[k] * (-1 if k in NEG else 1) / base, 4) if base else None
            rows.append(row)
    cols = [{"field": "model_id", "title": "Модель", "type": "text"}, {"field": "sku", "title": "SKU", "type": "text"},
            {"field": "offer_id", "title": "Артикул", "type": "text"}, {"field": "name", "title": "Название", "type": "text"},
            {"field": "period", "title": "Период", "type": "text"}, {"field": "sold_qty", "title": "Продано шт", "type": "int"}]
    for k, t, f, pct in UNIT:
        cols.append({"field": k, "title": t, "type": f})
        if pct:
            cols.append({"field": k + "%", "title": "%", "type": "share"})
    return {"columns": cols, "rows": rows}



OPIU_SKIP = ("h",)


def opiu(c, shop: int, year: int, d_to: date) -> dict:
    per = []
    for q in range(4):
        for m in range(q * 3 + 1, q * 3 + 4):
            a = date(year, m, 1)
            if a > d_to:
                break
            b = min((a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), d_to)
            per.append((f"{a:%m.%Y}", a, b))
        qa = date(year, q * 3 + 1, 1)
        if qa <= d_to:
            qb = min(date(year + (q == 3), (q * 3 + 3) % 12 + 1, 1) - timedelta(days=1), d_to)
            per.append((f"{q + 1} квартал", qa, qb))
    r = compute(Cached(c), shop, "month", per[0][1], per[-1][2], None, per=per)
    keep = False
    rows = []
    for key, lab, fmt in r["row_defs"]:
        if fmt == "h":
            keep = lab == "ФИНАНСЫ"
            if keep:
                continue
        if not keep:
            continue
        rows.append((key, lab, fmt))
    rows += [("roi", "ROI", "pct")]
    has = [bool(v["sales_total"] or v["non_total"]) for v in r["cols"]]          
    first = next((i for i, (lab, _, _) in enumerate(per) if has[i] and "квартал" not in lab), len(per))
    idx = [i for i in range(len(per)) if i >= first or ("квартал" in per[i][0] and per[i][2] >= per[first][1] if first < len(per) else False)]
    out = []
    for key, lab, fmt in rows:
        row = {"key": key, "label": lab, "fmt": fmt}
        for j, i in enumerate(idx):
            v = r["cols"][i]
            x = v["profit"] / -v["cost"] if key == "roi" and v["cost"] else v[key] if key != "roi" else 0
            row[f"p{j}"] = round(x, 4 if fmt in ("pct", "num") else 2) if x else None
            if fmt == "money" and v["sales_total"]:
                row[f"s{j}"] = round(x / v["sales_total"], 4) if x else None
        out.append(row)
    return {"periods": [per[i][0] for i in idx], "rows": out}

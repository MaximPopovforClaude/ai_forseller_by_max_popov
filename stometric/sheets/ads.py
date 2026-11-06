"""Self-hosted application component."""

import statistics
from collections import defaultdict

from ..agg import nm_day

COLS = [
    ("nm_id", "Артикул ВБ", "int"), ("vendor_code", "Артикул продавца", "text"), ("brand", "Бренд", "text"), ("subject", "Категория", "text"),
    ("imt_id", "Номер склейки", "int"), ("orders_sum", "Сумма заказов, руб", "money"), ("median_price", "Медианная цена за период", "money"),
    ("speed", "Скорость заказов в день (без учёта наличия)", "num"), ("stock_days", "Хватит остатков на FBW на ... дней", "num"),
    ("ad_orders_sum", "Сумма РЕКЛАМНЫХ заказов, руб", "money"), ("organic", "Доля органики", "share"),
    ("drr", "ДРР от суммы заказов, %", "share"), ("drr_ad", "ДРР от суммы РЕКЛАМНЫХ заказов, %", "share"),
    ("ctr", "CTR (клики / просмотры), %", "share"), ("cpc", "CPC (затраты РК / клики), руб", "money"),
    ("cpo", "CPO (затраты / Итого заказов РК), руб", "money"), ("upd", "Сумма расходов на рекламу (УПД), руб", "money"),
    ("bonus", "Реклама бонусами (Кэшбэк), руб", "money"), ("upd_all", "Реклама всего: деньги + бонусы, руб", "money"),
    ("drr_bonus", "ДРР бонусами, %", "share"), ("drr_all", "ДРР всего (с бонусами), %", "share"),
    ("spend", "Сумма расходов на рекламу (Статистика), руб", "money"), ("views", "Кол-во просмотров", "int"),
    ("clicks", "Кол-во кликов", "int"), ("atbs", "Кол-во добавлений в корзину", "int"), ("orders", "Кол-во заказов", "int"),
    ("canceled", "Кол-во отменённых заказов", "int"), ("as_atbs", "Ассоц.: добавления в корзину", "int"),
    ("as_orders", "Ассоц.: заказы", "int"), ("as_sum", "Ассоц.: сумма заказов", "money"),
    ("imt_upd", "Склейка: расходы на рекламу (УПД), руб", "money"), ("imt_orders_sum", "Итого заказов по всей склейке, руб", "money"),
    ("imt_drr", "Склейка: ДРР от суммы заказов, %", "share"), ("imt_ad_sum", "Склейка: сумма РЕКЛАМНЫХ заказов, руб", "money"),
    ("imt_drr_ad", "Склейка: ДРР от суммы РЕКЛАМНЫХ заказов, %", "share"),
    ("imt_profit", "Итого прибыль по всей склейке (без налога), руб", "money"),
]


def _d(a, b):
    return a / b if b else None


def compute(c, shop, df, dt, nm_ids=None) -> list[dict]:
    days = (dt - df).days + 1
    base = defaultdict(lambda: defaultdict(float))
    prices = defaultdict(list)
    for r in nm_day.cached(c, shop, df, dt):
        b = base[r["nm_id"]]
        for k in ("orders_sum", "orders", "ads_upd", "ads_bonus", "profit_orders"):
            b[k] += float(r.get(k) or 0)
        if r.get("orders_avg"):
            prices[r["nm_id"]].append(float(r["orders_avg"]))
    ad = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""
        SELECT (nm->>'nmId')::bigint nm, (nm->>'sum')::numeric spend, (nm->>'views')::numeric v, (nm->>'clicks')::numeric cl,
               (nm->>'atbs')::numeric atbs, (nm->>'orders')::numeric o, (nm->>'sum_price')::numeric sp, (nm->>'canceled')::numeric cx
        FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app, jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s""", (shop, df, dt)):
        a = ad[r["nm"]]
        a["ad_orders_sum"] += float(r["sp"] or 0)
        a["spend"] += float(r["spend"] or 0)
        if float(r["spend"] or 0) != 0:
            for k, f in (("views", "v"), ("clicks", "cl"), ("atbs", "atbs"), ("orders", "o"), ("canceled", "cx")):
                a[k] += float(r[f] or 0)
        else:
            a["as_atbs"] += float(r["atbs"] or 0); a["as_orders"] += float(r["o"] or 0); a["as_sum"] += float(r["sp"] or 0)
    stock = {r["nm_id"]: float(r["q"] or 0) for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    nom = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, brand, subject, imt_id FROM nomenclature WHERE account_id=%s", (shop,))}
    nms = sorted(set(base) | set(ad))
    if nm_ids:
        nms = [n for n in nms if n in nm_ids]
    imt = defaultdict(lambda: defaultdict(float))
    for n in set(base) | set(ad):
        i = (nom.get(n) or {}).get("imt_id")
        imt[i]["upd"] += base[n]["ads_upd"]; imt[i]["orders_sum"] += base[n]["orders_sum"]
        imt[i]["ad_sum"] += ad[n]["ad_orders_sum"]; imt[i]["profit"] += base[n]["profit_orders"]
    out = []
    for n in nms:
        b, a, nm = base[n], ad[n], nom.get(n) or {}
        if not (b["orders_sum"] or a["spend"] or a["ad_orders_sum"]):
            continue
        speed = b["orders"] / days
        i = imt[nm.get("imt_id")]
        out.append({
            "nm_id": n, "vendor_code": nm.get("vendor_code"), "brand": nm.get("brand"), "subject": nm.get("subject"), "imt_id": nm.get("imt_id"),
            "orders_sum": b["orders_sum"], "median_price": statistics.median(prices[n]) if prices[n] else None, "speed": round(speed, 2),
            "stock_days": round(stock.get(n, 0) / speed, 1) if speed else None, "ad_orders_sum": a["ad_orders_sum"],
            "organic": 1 - a["ad_orders_sum"] / b["orders_sum"] if a["ad_orders_sum"] > 0 and b["orders_sum"] else 1,
            "drr": _d(b["ads_upd"], b["orders_sum"]), "drr_ad": _d(b["ads_upd"], a["ad_orders_sum"]), "ctr": _d(a["clicks"], a["views"]),
            "cpc": _d(b["ads_upd"], a["clicks"]), "cpo": _d(b["ads_upd"], a["orders"]), "upd": b["ads_upd"], "spend": a["spend"],
            "bonus": b["ads_bonus"] or None, "upd_all": b["ads_upd"] + b["ads_bonus"],
            "drr_bonus": _d(b["ads_bonus"], b["orders_sum"]) if b["ads_bonus"] else None, "drr_all": _d(b["ads_upd"] + b["ads_bonus"], b["orders_sum"]),
            "views": a["views"], "clicks": a["clicks"], "atbs": a["atbs"], "orders": a["orders"], "canceled": a["canceled"],
            "as_atbs": a["as_atbs"], "as_orders": a["as_orders"], "as_sum": a["as_sum"],
            "imt_upd": i["upd"], "imt_orders_sum": i["orders_sum"], "imt_drr": _d(i["upd"], i["orders_sum"]),
            "imt_ad_sum": i["ad_sum"], "imt_drr_ad": _d(i["upd"], i["ad_sum"]), "imt_profit": i["profit"] or None,
        })
    return sorted(out, key=lambda r: -r["orders_sum"])

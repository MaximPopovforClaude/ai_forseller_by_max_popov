"""Read-only Ozon daily dossier. CLI: brief_ozon.py SHOP [TASK_DAY]."""

import json
import math
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from stometric.ozon_task_data import BASIC_METRICS, FULL_METRICS, coverage, metric_presence_sql


FUNNEL = ("views", "views_search", "clicks", "uclicks", "cart", "ordered", "ordered_sum",
          "cancel", "returned", "ctr", "cr_cart", "cr_order", "pos")
FINANCE = ("sold_qty", "sold_amt", "ret_qty", "cost", "commission", "svc_total", "item_total",
           "non_total", "bonus", "coinvest", "tax", "vat", "profit")
ADS = ("ad.views", "ad.clicks", "ad.to_cart", "ad.orders", "ad.models", "ad.orders_money",
       "ad.models_money", "ad.spent", "ozz.orders", "ozz.spent", "ad.cpc", "ad.cpo")
METRICS = FUNNEL + FINANCE + ADS

LIMITATIONS = [
    "Это досье Ozon. WB-отчёт «Точки входа», СПП, бонусные правила WB и формулы WB неприменимы.",
    "Заказы — по дате заказа; прибыль — по начислениям после доставки. Разница дневных рядов не доказывает потери или эффект задачи.",
    "Наличие строк не подтверждает полноту выгрузки. null — данных недостаточно; его нельзя заменять нулём.",
    "Цены, остатки, карточки и состояния кампаний — текущие снимки с датой обновления, не историческое состояние на день разбора.",
    "Поисковые заказы из oz_queries относятся ко всей выдаче, а не только к рекламе. Нельзя приписывать их конкретной рекламной фразе.",
    "При неполном oz_ad_sku Version2 распределяет некоторые расходы кампаний между SKU оценочно; sources.ads_by_sku не подтверждает полноту.",
    "Нет надёжной свежей цены покупателя/витринного соинвеста и полного отчёта источников трафика. Отзывы в это досье не включены.",
    "История ставок, описания/характеристик и участия в акции неполна: выполнение таких задач подтверждается вручную.",
    "Досье не содержит рассчитанных сценариев денежного эффекта: effect_week должен быть null. Нельзя выдавать экономию рекламы за гарантированную прибыль.",
    "Рекомендации основаны на нескольких днях, расходах и финансовых ограничениях; один слабый вчерашний день сам по себе не повод отключать рекламу.",
]


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Unsupported dossier value: {type(value).__name__}")


def _number(value):
    if value is None:
        return None
    result = float(value)
    return round(result, 6) if math.isfinite(result) else None


def _read(c, label, read):
    try:
        with c.transaction():
            return read()
    except Exception as exc:
        return {"unavailable": True, "reason": f"{label}: {type(exc).__name__}"}


def _rows(c, label, query, args, limit):
    def read():
        rows = c.execute(query + " LIMIT %s", (*args, limit + 1)).fetchall()
        return {"rows": [dict(row) for row in rows[:limit]], "truncated": len(rows) > limit, "limit": limit}
    return _read(c, label, read)


def _periods(end):
    daily = [(d.isoformat(), d, d) for d in (end - timedelta(days=i) for i in range(13, -1, -1))]
    return daily + [("week", end - timedelta(days=6), end),
                    ("previous_week", end - timedelta(days=13), end - timedelta(days=7))]


def _period_metrics(result, periods, cov, sku_days=None, sku_full_days=None):
    """Retain Version2 numbers, but never present a missing source as a zero."""
    sources = cov["sources"]
    out = []
    for (label, start, end), values in zip(periods, result["cols"]):
        days = {(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)}
        analytics = set(sources["analytics"].get("days_basic", []))
        full_analytics = set(sources["analytics"].get("days_full", []))
        if sku_days is not None:
            analytics &= set(sku_days)
            full_analytics &= set(sku_full_days or [])
        missing = {
            "analytics": sorted(days - analytics),
            "analytics_full": sorted(days - full_analytics),
            "realization": sorted(days - set(sources["realization"]["days"])),
            "transactions": sorted(days - set(sources["transactions"]["days"])),
            "ads": sorted(days - (set(sources["ad_daily"]["days"]) | set(sources["ad_sku"]["days"]))),
        }
        row = {key: _number(values.get(key)) for key in METRICS}
        for key in FUNNEL if missing["analytics"] else ():
            row[key] = None
        if missing["analytics_full"]:
            for key in FUNNEL:
                if key not in ("ordered", "ordered_sum"):
                    row[key] = None
        
        
        for key in FINANCE if missing["realization"] or missing["transactions"] else ():
            row[key] = None
        for key in ADS if missing["ads"] else ():
            row[key] = None
        if missing["ads"]:
            row["profit"] = None
        out.append({"period": label, "from": start.isoformat(), "to": end.isoformat(),
                    "metrics": row, "missing_source_days": missing})
    return {"formula": "stometric.sheets.ozv2.compute", "periods": out,
            "version2_sources": result.get("sources", {}), "financial_values_are_provisional": True}


def build(c, shop: int, day: date) -> str:
    """Build a bounded JSON dossier for task day; all calculations end at day-1."""
    if type(shop) is not int or shop <= 0 or type(day) is not date:
        raise ValueError("Нужны id магазина и календарная дата задач")
    account = c.execute("SELECT id,coalesce(title,name) AS title,marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()
    if not account or account["marketplace"] != "ozon":
        raise ValueError("Досье Ozon доступно только для магазина Ozon")
    end, start = day - timedelta(days=1), day - timedelta(days=14)
    cov = coverage(c, shop, end)
    dossier = {"marketplace": "ozon", "shop_id": shop, "shop": account["title"],
               "task_day": day.isoformat(), "analysis_day": end.isoformat(), "coverage": cov,
               "limitations": LIMITATIONS, "effect_scenarios": []}
    from stometric.sheets import ozv2
    periods = _periods(end)
    cached = ozv2.Cached(c)
    dossier["shop_version2"] = _read(c, "Расчёт Version2 магазина", lambda: _period_metrics(
        ozv2.compute(cached, shop, "day", start, end, per=periods), periods, cov))
    top = _rows(c, "Основные SKU", """WITH scores AS (
               SELECT sku,sum((m->>'ordered_units')::numeric) AS orders_week,
                   sum((m->>'revenue')::numeric) AS orders_rub_week FROM oz_analytics
               WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY sku)
               SELECT a.*,p.offer_id,p.name,p.model_id FROM scores a LEFT JOIN LATERAL (
                   SELECT offer_id,name,model_id FROM oz_products WHERE account_id=%s AND sku=a.sku
                   ORDER BY updated_at DESC,product_id DESC LIMIT 1) p ON true
               ORDER BY orders_rub_week DESC NULLS LAST,a.sku""", (shop, end - timedelta(days=6), end, shop), 15)
    dossier["top_skus"] = top
    sku_ids = [row["sku"] for row in top.get("rows", [])]
    sku_days = _read(c, "Дни воронки SKU", lambda: c.execute(
        f"SELECT sku,day,({metric_presence_sql(BASIC_METRICS)}) AS basic_ok, "
        f"({metric_presence_sql(FULL_METRICS)}) AS full_ok FROM oz_analytics "
        "WHERE account_id=%s AND day BETWEEN %s AND %s AND sku=ANY(%s)",
        (shop, start, end, sku_ids)).fetchall())
    by_sku = {}
    if isinstance(sku_days, list):
        for row in sku_days:
            have = by_sku.setdefault(row["sku"], {"basic": [], "full": []})
            if row.get("basic_ok") is True:
                have["basic"].append(row["day"].isoformat())
            if row.get("full_ok") is True:
                have["full"].append(row["day"].isoformat())
    dossier["sku_version2"] = [
        {"sku": sku, "calculation": _read(c, f"Version2 SKU {sku}", lambda sku=sku: _period_metrics(
            ozv2.compute(cached, shop, "day", start, end, [sku], per=periods), periods, cov,
            by_sku.get(sku, {}).get("basic", []), by_sku.get(sku, {}).get("full", [])))}
        for sku in sku_ids
    ]
    dossier["sku_changes"] = _rows(c, "Движение SKU", """SELECT a.sku,
          sum((m->>'ordered_units')::numeric) FILTER (WHERE a.day=%s) AS orders_yesterday,
          sum((m->>'ordered_units')::numeric) FILTER (WHERE a.day=%s) AS orders_day_before,
          sum((m->>'revenue')::numeric) FILTER (WHERE a.day=%s) AS revenue_yesterday,
          sum((m->>'revenue')::numeric) FILTER (WHERE a.day=%s) AS revenue_day_before,
          sum((m->>'hits_view_pdp')::numeric) FILTER (WHERE a.day=%s) AS clicks_yesterday,
          sum((m->>'hits_tocart')::numeric) FILTER (WHERE a.day=%s) AS carts_yesterday,
          count(DISTINCT a.day) AS observed_days
        FROM oz_analytics a
        WHERE a.account_id=%s AND a.day BETWEEN %s AND %s GROUP BY a.sku
        ORDER BY abs(coalesce(sum((m->>'revenue')::numeric) FILTER (WHERE a.day=%s),0)
                    - coalesce(sum((m->>'revenue')::numeric) FILTER (WHERE a.day=%s),0)) DESC,a.sku""",
        (end, end - timedelta(days=1), end, end - timedelta(days=1), end, end,
         shop, end - timedelta(days=1), end, end, end - timedelta(days=1)), 70)
    dossier["campaigns_current"] = _rows(c, "Кампании", """SELECT campaign_id,title,state,kind,payment_type,
        daily_budget,skus,updated_at FROM oz_ad_campaigns WHERE account_id=%s ORDER BY campaign_id""", (shop,), 100)
    dossier["ad_daily"] = _rows(c, "Реклама по дням", """SELECT day,campaign_id,views,clicks,spent,bonus_spent,
        orders,orders_money FROM oz_ad_daily WHERE account_id=%s AND day BETWEEN %s AND %s
        ORDER BY spent DESC NULLS LAST,day DESC,campaign_id""", (shop, start, end), 200)
    dossier["ad_sku"] = _rows(c, "Реклама SKU", """SELECT campaign_id,sku,sum(views) views,sum(clicks) clicks,
        sum(to_cart) to_cart,sum(spent) spent,sum(orders) orders,sum(orders_money) orders_money,
        sum(models) models,sum(models_money) models_money,count(DISTINCT day) observed_days
        FROM oz_ad_sku WHERE account_id=%s AND day BETWEEN %s AND %s GROUP BY campaign_id,sku
        ORDER BY spent DESC NULLS LAST,campaign_id,sku""", (shop, end - timedelta(days=6), end), 100)
    dossier["ads_campaign_days_without_sku_report"] = _rows(c, "Покрытие рекламных SKU", """SELECT d.day,d.campaign_id,d.spent
        FROM oz_ad_daily d WHERE d.account_id=%s AND d.day BETWEEN %s AND %s
        AND NOT EXISTS (SELECT 1 FROM oz_ad_sku s WHERE s.account_id=d.account_id AND s.campaign_id=d.campaign_id AND s.day=d.day)
        ORDER BY d.day DESC,d.campaign_id""", (shop, start, end), 100)
    dossier["queries"] = _rows(c, "Поисковые запросы", """SELECT day,sku,query,position,searchers,viewers,conv,orders,gmv
        FROM oz_queries WHERE account_id=%s AND day BETWEEN %s AND %s
        ORDER BY gmv DESC NULLS LAST,day DESC,sku,query""", (shop, start, end), 150)
    dossier["ad_phrases"] = _rows(c, "Фразы рекламы", """SELECT campaign_id,sku,phrase,sum(views) views,sum(clicks) clicks,
        count(DISTINCT day) observed_days FROM oz_ad_phrases WHERE account_id=%s AND day BETWEEN %s AND %s
        GROUP BY campaign_id,sku,phrase ORDER BY clicks DESC NULLS LAST,campaign_id,sku,phrase""", (shop, end - timedelta(days=6), end), 100)
    dossier["seller_prices_current"] = _rows(c, "Цены продавца", """SELECT p.sku,p.offer_id,x.price,x.old_price,x.min_price,x.updated_at
        FROM oz_prices x JOIN oz_products p ON p.account_id=x.account_id AND p.product_id=x.product_id
        WHERE x.account_id=%s AND p.sku=ANY(%s) ORDER BY p.sku""", (shop, sku_ids), 30)
    dossier["stocks_current"] = _rows(c, "Остатки по кластерам", """SELECT sku,offer_id,cluster,snap_at,
        sum(available) available,sum(other) other FROM oz_stocks
        WHERE account_id=%s AND snap_at=(SELECT max(snap_at) FROM oz_stocks WHERE account_id=%s)
        AND sku=ANY(%s) GROUP BY sku,offer_id,cluster,snap_at ORDER BY sku,cluster""", (shop, shop, sku_ids), 200)
    dossier["costs"] = _rows(c, "Себестоимость", """SELECT DISTINCT ON (nm_id) nm_id AS sku,valid_from,cost
        FROM cost_price WHERE account_id=%s AND nm_id=ANY(%s) AND valid_from<=%s
        ORDER BY nm_id,valid_from DESC""", (shop, sku_ids, end), 30)
    dossier["tax"] = _rows(c, "Налоги", """SELECT valid_from,regime,rate,vat_rate FROM tax_settings
        WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC""", (shop, end), 1)
    dossier["missing_sale_costs"] = _rows(c, "Полнота себестоимости", """SELECT r.sku,min(r.day) AS missing_from,
        count(DISTINCT r.day) AS days_without_cost FROM oz_realization_day r
        WHERE r.account_id=%s AND r.day BETWEEN %s AND %s AND (r.sale_qty<>0 OR r.ret_qty<>0)
        AND NOT EXISTS (SELECT 1 FROM cost_price p WHERE p.account_id=r.account_id AND p.nm_id=r.sku AND p.valid_from<=r.day)
        GROUP BY r.sku ORDER BY r.sku""", (shop, start, end), 200)
    missing_costs = dossier["missing_sale_costs"]
    missing_skus = {r["sku"] for r in missing_costs.get("rows", [])}
    unknown_costs = missing_costs.get("unavailable") or missing_costs.get("truncated")
    no_tax = not dossier["tax"].get("rows")
    calculations = [(None, dossier["shop_version2"])] + [(x["sku"], x["calculation"]) for x in dossier["sku_version2"]]
    for sku, calculation in calculations:
        if no_tax or unknown_costs or (bool(missing_skus) if sku is None else sku in missing_skus):
            for period in calculation.get("periods", []):
                period["metrics"]["profit"] = None
            calculation["profit_unavailable_reason"] = "Не подтверждена себестоимость продаж или настройки налогов; прибыль не оценивать."
    dossier["changes"] = _rows(c, "Журнал изменений", """SELECT nm_id AS sku,kind,field,old_value,new_value,detected_at
        FROM card_changes WHERE account_id=%s AND source='ozon' AND detected_at >= %s AND detected_at < %s
        AND kind=ANY(%s) AND (field=ANY(%s) OR field LIKE 'ad:%%') ORDER BY detected_at DESC,id DESC""",
        (shop, datetime.combine(start, datetime.min.time(), timezone(timedelta(hours=3))),
         datetime.combine(day, datetime.min.time(), timezone(timedelta(hours=3))),
         ["price", "photo", "content", "ad_status"], ["price", "photos", "title", "vendorCode", "archived", "created"]), 100)
    
    
    dossier["past_tasks"] = _rows(c, "История задач", """SELECT day,tag,certainty,title,status,status_by,status_note,outcome,effect_week
        FROM ai_tasks WHERE account_id=%s AND active AND day >= %s AND day < %s
        ORDER BY day DESC,priority DESC,id DESC""", (shop, day - timedelta(days=7), day), 100)
    dossier["team_feedback"] = _rows(c, "Оценки команды", """SELECT t.day,t.tag,t.title,f.rating,f.comment,f.updated_at
        FROM ai_task_feedback f JOIN ai_tasks t ON t.id=f.task_id AND t.account_id=f.account_id
        WHERE f.account_id=%s AND t.day<%s AND f.updated_at >= %s AND f.updated_at < %s
        ORDER BY f.updated_at DESC,f.task_id""", (shop, day,
        datetime.combine(day - timedelta(days=30), datetime.min.time(), timezone(timedelta(hours=3))),
        datetime.combine(day, datetime.min.time(), timezone(timedelta(hours=3)))), 60)
    text = json.dumps(dossier, ensure_ascii=False, default=_json_default, allow_nan=False)
    if len(text) > 550_000:
        
        for key in ("queries", "ad_phrases", "changes", "stocks_current", "ad_daily"):
            section = dossier[key]
            if section.get("rows"):
                section["rows"] = section["rows"][:20]
                section["truncated"] = True
                section["limit"] = 20
        dossier["size_note"] = "Дополнительные разделы сокращены до 20 строк из-за размера досье."
        text = json.dumps(dossier, ensure_ascii=False, default=_json_default, allow_nan=False)
    if len(text) > 750_000:
        raise ValueError("Досье Ozon слишком большое; прежние задачи должны быть сохранены")
    return text


def main():
    import sys
    import stometric.web  
    from stometric.config import today_msk
    from stometric.db import connect
    shop = int(sys.argv[1])
    day = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else today_msk()
    with connect(readonly=True, timeout_s=120) as c:
        print(build(c, shop, day))


if __name__ == "__main__":
    main()

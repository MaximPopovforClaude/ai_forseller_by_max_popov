"""Self-hosted application component."""

from collections import defaultdict
from datetime import date, timedelta

from ..agg import nm_day
from ..config import today_msk

PERIODS = ["вчера", "позавчера", "за послед. 4 недели", "текущая неделя", "предыдущая неделя", "позапрошлая неделя",
           "текущий месяц", "предыдущий месяц", "за последние 3 дня", "за последние 4 дня", "за последние 5 дней",
           "за последние 6 дней"]


def period(name: str, y: date) -> tuple[date, date]:
    """Периоды как в Импорт#ОбщиеНастройки (вчера = y)."""
    mon = y - timedelta(days=y.isoweekday() - 1)
    if name == "вчера":
        return y, y
    if name == "позавчера":
        return y - timedelta(days=1), y - timedelta(days=1)
    if name == "за послед. 4 недели":
        return y - timedelta(days=27), y
    if name == "текущая неделя":
        return mon, y
    if name == "предыдущая неделя":
        return mon - timedelta(days=7), mon - timedelta(days=1)
    if name == "позапрошлая неделя":
        return mon - timedelta(days=14), mon - timedelta(days=8)
    if name == "текущий месяц":
        return y.replace(day=1), y
    if name == "предыдущий месяц":
        e = y.replace(day=1) - timedelta(days=1)
        return e.replace(day=1), e
    if name.startswith("за последние "):
        n = int(name.split()[2])
        return y - timedelta(days=n - 1), y
    raise ValueError(name)


_SUM_PREFIX = [(t, k) for k, t, ty in nm_day.COLS if ty in ("int", "money") and k not in ("nm_id", "year_week", "year_month")]

_FULL = ["Кол-во заказов ВСЕГО", "Сумма ВСЕХ заказов, руб", "Сумма ВСЕХ заказов с учетом скидки ВБ (СПП), руб", "Кол-во выкупов",
         "Сумма выкупов, руб", "Сумма выкупов до скидки ВБ (СПП), руб", "Сумма комиссии ВБ, руб", "К оплате продавцу, руб",
         "Сумма себестоимости, руб", "Маржа, руб", "Сумма расходов на логистику, руб", "Сумма расходов на рекламу, руб",
         "Сумма расходов на рекламу по УПД, руб", "Сумма расходов на хранение, руб", "Прибыль, руб", "Логистика на единицу, руб",
         "Хранение (кол-во тарифицируемых товарных единиц)", "Реклама (кол-во просмотров)", "Реклама (кол-во кликов)",
         "Реклама (кол-во добавлений в корзину)", "Реклама (кол-во заказов)", "Реклама (кол-во товаров в заказах)",
         "Реклама (сумма заказов), руб", "Конверсии (кол-во переходов в карточку товара)", "Конверсии (положили в корзину)",
         "Конверсии (заказали товаров)", "Конверсии (заказали на сумму), руб", "Конверсии (добавили в Отложенные)",
         "в т.ч. кол-во заказов со статусом НЕотменен", "в т.ч. сумма заказов со статусом НЕотменен, руб",
         "в т.ч. кол-во заказов со статусом Отменен", "в т.ч. сумма заказов со статусом Отменен, руб", "Кол-во возвратов",
         "Сумма возвратов (к оплате продавцу), руб", "Кол-во Отмененных/Невыкупленных заказов в дату отмены",
         "Сумма Отмененных/Невыкупленных заказов в дату отмены, руб", "Платная приемка Количество товаров, шт",
         "Платная приемка Сумма, руб", "Сумма себестоимости возвратов, руб", "Прибыль с учетом возвратов до налогов, руб",
         "Сумма комиссии ВБ (оферта) по заказам, руб", "Сумма себестоимости заказов, руб", "Маржа по всем заказам, руб",
         "Прибыль по всем заказам до налогов, руб", "Сумма расходов на логистику по заказам, руб", "Расходы на эквайринг по выкупам, руб"]


def _resolve(title: str):
    best = None
    for t, k in _SUM_PREFIX:
        if title.startswith(t) and (best is None or len(t) > len(best[0])):
            best = (t, k)
    return best[1] if best else None


SUM_METRICS = {t: _resolve(t) for t in _FULL if _resolve(t)}
SUM_METRICS["Логистика на единицу, руб"] = "logistics_unit"

DERIVED = {
    "Маржинальность  от суммы выкупов до скидки ВБ (СПП), %": (lambda S: _d(S["margin"], S["buyouts_sum_before_spp"]), "share"),
    "Прибыль от суммы выкупов до скидки ВБ (СПП), %": (lambda S: _d(S["profit"] - S["_tax"], S["buyouts_sum_before_spp"]), "share"),
    "Сумма налога": (lambda S: S["_tax"], "money"),
    "Прибыль за минусом налога, руб": (lambda S: S["profit"] - S["_tax"], "money"),
    "ДРР от суммы заказов, %": (lambda S: _d(S["ads"], S["orders_sum"]), "share"),
    "ДРР от суммы выкупов до скидки ВБ (СПП), %": (lambda S: _d(S["ads"], S["buyouts_sum_before_spp"]), "share"),
    "CTR (клики / просмотры), %": (lambda S: _d(S["ad_clicks"], S["ad_views"]), "share"),
    "CPC (затраты / клики), руб": (lambda S: _d(S["ads"], S["ad_clicks"]), "money"),
    "Конверсия в корзину, %": (lambda S: _d(S["f_cart"], S["f_open"]), "share"),
    "Конверсия в заказ, %": (lambda S: _d(S["f_orders"], S["f_cart"]), "share"),
}


DEFAULT = [
    ("ЗАКАЗЫ", "Кол-во заказов ВСЕГО", "вчера"), ("", "Кол-во заказов ВСЕГО", "позавчера"), ("", "разница", ""),
    ("", "Кол-во Отмененных/Невыкупленных заказов в дату отмены", "вчера"),
    ("", "Сумма ВСЕХ заказов, руб", "вчера"), ("", "Сумма ВСЕХ заказов, руб", "позавчера"), ("", "разница", ""),
    ("ВЫКУПЫ", "Кол-во выкупов", "вчера"), ("", "Кол-во выкупов", "позавчера"), ("", "разница", ""),   
    ("", "Кол-во возвратов", "вчера"),
    ("", "К оплате продавцу, руб", "вчера"), ("", "К оплате продавцу, руб", "позавчера"), ("", "разница", ""),
    ("МАРЖИНАЛЬНАЯ ПРИБЫЛЬ", "Сумма выкупов до скидки ВБ (СПП), руб", "предыдущая неделя"),
    ("", "Сумма выкупов, руб", "предыдущая неделя"), ("", "Маржа, руб", "предыдущая неделя"),
    ("", "Маржинальность  от суммы выкупов до скидки ВБ (СПП), %", "предыдущая неделя"),
    ("", "Прибыль, руб", "предыдущая неделя"), ("", "Сумма налога", "предыдущая неделя"),
    ("", "Прибыль за минусом налога, руб", "предыдущая неделя"),
    ("", "Прибыль от суммы выкупов до скидки ВБ (СПП), %", "предыдущая неделя"),
    ("РАСХОДЫ", "Сумма расходов на логистику, руб", "предыдущая неделя"), ("", "Логистика на единицу, руб", "предыдущая неделя"),
    ("", "Сумма себестоимости, руб", "предыдущая неделя"), ("", "Сумма расходов на хранение, руб", "предыдущая неделя"),
    ("", "Платная приемка Количество товаров, шт", "предыдущая неделя"), ("", "Платная приемка Сумма, руб", "предыдущая неделя"),
    ("РЕКЛАМА", "Сумма расходов на рекламу, руб", "предыдущая неделя"), ("", "Сумма ВСЕХ заказов, руб", "предыдущая неделя"),
    ("", "Сумма выкупов до скидки ВБ (СПП), руб", "предыдущая неделя"), ("", "ДРР от суммы заказов, %", "предыдущая неделя"),
    ("", "ДРР от суммы выкупов до скидки ВБ (СПП), %", "предыдущая неделя"),
    ("", "Реклама (кол-во просмотров)", "предыдущая неделя"), ("", "Реклама (кол-во кликов)", "предыдущая неделя"),
    ("", "CTR (клики / просмотры), %", "предыдущая неделя"), ("", "CPC (затраты / клики), руб", "предыдущая неделя"),
    ("", "Реклама (кол-во добавлений в корзину)", "предыдущая неделя"), ("", "Реклама (кол-во заказов)", "предыдущая неделя"),
    ("", "Реклама (кол-во товаров в заказах)", "предыдущая неделя"), ("", "Реклама (сумма заказов), руб", "предыдущая неделя"),
    ("КОНВЕРСИИ", "Конверсии (кол-во переходов в карточку товара)", "вчера"), ("", "Конверсии (положили в корзину)", "вчера"),
    ("", "Конверсии (заказали товаров)", "вчера"), ("", "Конверсия в корзину, %", "вчера"), ("", "Конверсия в заказ, %", "вчера"),
    ("", "Кол-во возвратов", "вчера"), ("", "Сумма возвратов (к оплате продавцу), руб", "вчера"),
    ("", "в т.ч. кол-во заказов со статусом Отменен", "вчера"),
]


def _d(a, b):
    return a / b if b else 0


def metric_options() -> list[str]:
    return list(SUM_METRICS) + list(DERIVED) + ["разница"]


LAST4 = "за послед. 4 недели"
SORT_COL = ("orders_sum_4w", "Сумма всех заказов, руб, за последние 4 недели")   


def _period_sums(rows, rng):
    """Same per-item SUMIFS, one conversion per value, bounded daily-row memory."""
    keys = set(SUM_METRICS.values()) | {"margin", "profit", "buyouts_sum", "ads", "orders_sum", "ad_clicks", "ad_views",
                                        "f_cart", "f_open", "f_orders", "buyouts_sum_before_spp"}
    sums = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for row in rows:
        fields = [(k, float(row[k])) for k in keys if row.get(k) is not None]
        for p, (a, b) in rng.items():
            if a <= row['day'] <= b:
                acc = sums[row['nm_id']][p]
                for k, value in fields:
                    acc[k] += value
    return sums


def _buyout_last4(c, shop, nm_ids=None):
    """Last report week is per item, independent of the selected dashboard date."""
    from ..agg import real_week
    from ..materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    if not c.execute("SELECT 1 FROM agg_state WHERE account_id=%s AND name='real_week'", (shop,)).fetchone():
        per_nm = defaultdict(list)
        for g in real_week.cached(c, shop):
            if g['nm_id'] and g['date_from'] and (not nm_ids or g['nm_id'] in nm_ids):
                per_nm[g['nm_id']].append((date.fromisoformat(g['date_from']), date.fromisoformat(g['date_to']),
                                          float(g['deliveries'] or 0), float(g['returns'] or 0)))
        result = {}
        for nm, rows in per_nm.items():
            end = max(r[1] for r in rows)
            dl = sum(r[2] for r in rows if r[0] >= end-timedelta(days=27) and r[1] <= end)
            rt = sum(r[3] for r in rows if r[0] >= end-timedelta(days=27) and r[1] <= end)
            result[nm] = (dl-rt)/dl if dl else 0
        return result
    
    rows = c.execute("""SELECT nm_id,
        coalesce(sum(deliveries) FILTER (WHERE df >= last_day-27 AND dt <= last_day),0)::float deliveries,
        coalesce(sum(returns) FILTER (WHERE df >= last_day-27 AND dt <= last_day),0)::float returns
        FROM (SELECT q.*, max(dt) OVER (PARTITION BY nm_id) last_day FROM (
            SELECT (data->>'nm_id')::bigint nm_id, (data->>'date_from')::date df, (data->>'date_to')::date dt,
                   coalesce((data->>'deliveries')::numeric,0) deliveries,
                   coalesce((data->>'returns')::numeric,0) returns
            FROM agg_real_week WHERE account_id=%s AND (data->>'nm_id')::bigint <> 0
              AND coalesce(data->>'date_from','') <> ''
              AND (%s::bigint[] IS NULL OR (data->>'nm_id')::bigint=ANY(%s::bigint[]))
        ) q) periods GROUP BY nm_id""", (shop, nm_ids or None, nm_ids or None))
    return {r['nm_id']: (r['deliveries']-r['returns'])/r['deliveries'] if r['deliveries'] else 0 for r in rows}


def compute(c, shop: int, yesterday: date | None = None, layout=None, nm_ids=None) -> dict:
    y = yesterday or today_msk() - timedelta(days=1)
    layout = layout or DEFAULT
    need = {p for _, m, p in layout if p} | {LAST4}
    rng = {p: period(p, y) for p in need}
    lo = min([a for a, _ in rng.values()] + [y - timedelta(days=27)])
    rows = nm_day.iter_cached(c, shop, lo, y, nm_ids)
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1",
                    (shop, y)).fetchone() or {"regime": "Другая СНО", "rate": 0}
    
    S = _period_sums(rows, rng)
    for nm in S:
        for p, acc in S[nm].items():
            if tax["regime"] == "УСН доход":
                acc["_tax"] = float(tax["rate"]) * acc["buyouts_sum"]
            elif tax["regime"] == "УСН доходы-расходы":
                acc["_tax"] = float(tax["rate"]) * acc["profit"] if acc["profit"] > 0 else 0
            else:
                acc["_tax"] = 0.0
    
    from ..agg import buyout
    if buyout.needed(c, shop):              
        per, shop_bp = buyout.by_orders(c, shop)
        bp = defaultdict(lambda: shop_bp, per)
    else:
        bp = _buyout_last4(c, shop, nm_ids)
    nom = {r["nm_id"]: r for r in c.execute(
        "SELECT nm_id, vendor_code, title, brand, subject, imt_id FROM nomenclature WHERE account_id=%s", (shop,))}
    stock = {r["nm_id"]: r for r in c.execute(
        """WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%s)
           SELECT nm_id, sum(quantity) q, sum(in_way_to_client) wt, sum(in_way_from_client) wf
           FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t WHERE account_id=%s GROUP BY 1""", (shop, shop))}
    rating = {r["nm"]: r["v"] for r in c.execute(
        """SELECT DISTINCT ON ((data->>'nmId')::bigint) (data->>'nmId')::bigint nm, (data->>'feedbackRating')::numeric v
           FROM raw_rows WHERE account_id=%s AND source IN ('funnel_day') ORDER BY (data->>'nmId')::bigint, row_date DESC""", (shop,))}
    costs = {r["nm_id"]: float(r["cost"]) for r in c.execute(
        "SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%s AND valid_from<=%s ORDER BY nm_id, valid_from DESC",
        (shop, y))}
    nms = sorted(set(S) | set(stock) | set(nom), key=lambda n: (nom.get(n) or {}).get("vendor_code") or "")
    if nm_ids:
        nms = [n for n in nms if n in nm_ids]
    cols = [("nm_id", "Артикул ВБ", "int", ""), ("vendor_code", "Артикул продавца", "text", ""), ("title", "Название товара", "text", ""),
            ("brand", "Бренд", "text", ""), ("subject", "Предмет", "text", ""), ("imt_id", "Групповой идентификатор", "int", ""),
            ("rating", "Рейтинг артикула", "num", ""), ("cost", "Текущая себестоимость, руб", "money", ""),
            ("stock", "Остатки на складах ВБ", "int", ""), ("in_way_to", "В пути к клиенту", "int", ""),
            ("in_way_from", "В пути от клиента", "int", ""), ("buyout_4w", "% выкупа за последние 4 недели", "share", "")]
    metric_cols = []
    for i, (grp, m, p) in enumerate(layout):
        f = f"m{i}"
        if m == "разница":
            typ = metric_cols[-1][2] if metric_cols else "money"
            metric_cols.append((f, "разница", typ, grp, None, None, (metric_cols[-2][0], metric_cols[-1][0]) if len(metric_cols) >= 2 else None))
        elif m in DERIVED:
            metric_cols.append((f, m, DERIVED[m][1], grp, p, DERIVED[m][0], None))
        elif m in SUM_METRICS:
            typ = "money" if "руб" in m else ("money" if m.startswith("Логистика") else "int")
            metric_cols.append((f, m, typ, grp, p, SUM_METRICS[m], None))
    out = []
    any_data = set(S) | {n for n in stock if (stock[n]["q"] or 0) > 0}
    for nm in nms:
        if nm not in any_data:
            continue
        n0, st = nom.get(nm) or {}, stock.get(nm) or {}
        row = {"nm_id": nm, "vendor_code": n0.get("vendor_code"), "title": n0.get("title"), "brand": n0.get("brand"),
               "subject": n0.get("subject"), "imt_id": n0.get("imt_id"), "rating": rating.get(nm), "cost": costs.get(nm),
               "stock": st.get("q"), "in_way_to": st.get("wt"), "in_way_from": st.get("wf"), "buyout_4w": bp.get(nm)}
        for f, m, typ, grp, p, fn, diff in metric_cols:
            if diff:
                row[f] = (row.get(diff[0]) or 0) - (row.get(diff[1]) or 0)
            elif callable(fn):
                row[f] = fn(S[nm][p])
            else:
                row[f] = S[nm][p].get(fn, 0.0)
        row[SORT_COL[0]] = S[nm][LAST4].get(SUM_METRICS["Сумма ВСЕХ заказов, руб"], 0.0)
        out.append(row)
    out.sort(key=lambda r: -r[SORT_COL[0]])
    columns = [{"field": f, "title": t, "type": ty, "group": g} for f, t, ty, g in cols]
    for f, m, typ, grp, p, *_ in metric_cols:
        a, b = rng.get(p, (None, None)) if p else (None, None)
        sub = f"{p} ({a:%d.%m}{'' if a == b else '–' + format(b, '%d.%m')})" if p else ""
        columns.append({"field": f, "title": m + (f" · {sub}" if sub else ""), "type": typ, "group": grp, "metric": m, "period": p})
    a4, b4 = rng[LAST4]
    columns.append({"field": SORT_COL[0], "title": f"{SORT_COL[1]} ({a4:%d.%m}–{b4:%d.%m})", "type": "money", "group": "ИТОГО"})
    return {"columns": columns, "rows": out, "sort": {"field": SORT_COL[0], "desc": True}, "col_layout": [list(x) for x in layout], "periods": PERIODS, "metrics": metric_options(),
            "tax": tax["regime"]}

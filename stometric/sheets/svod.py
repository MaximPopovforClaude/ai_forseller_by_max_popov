"""Self-hosted application component."""

from collections import defaultdict
from datetime import timedelta

from ..config import today_msk

PARAMS = [
    ("cost", "Текущая себестоимость", "money"),
    ("buyout_pct_4w", "Процент выкупа за последние 4 недели, %", "share"),
    ("stock", "Текущие остатки на складах WB", "int"),
    ("stock_cost", "Стоимость остатков на складах WB в ценах с/с, руб", "money"),
    ("avg_orders_in_stock", "Среднее кол-во заказов в ДЕНЬ при наличии товара на складе", "num"),
    ("orders_y", "Кол-во заказов за вчера", "int"),
    ("orders_y1", "Кол-во заказов за позавчера", "int"),
    ("orders_diff", "Разница кол-ва заказов вчера-позавчера", "int"),
    ("rev_y", "Выручка за вчера, руб", "money"),
    ("rev_w", "Выручка за предыдущую неделю, руб", "money"),
    ("logistics_last", "Последнее значение логистики, руб", "money"),
    ("rev_m", "Выручка за текущий месяц, руб", "money"),
    ("rev_pm", "Выручка за предыдущий месяц, руб", "money"),
    ("buy_y", "Кол-во выкупов за вчера", "int"),
    ("buy_w", "Кол-во выкупов за предыдущую неделю", "int"),
    ("buy_m", "Кол-во выкупов за текущий месяц", "int"),
    ("buy_pm", "Кол-во выкупов за предыдущий месяц", "int"),
    ("orders_m", "Кол-во заказов за текущий месяц", "int"),
    ("orders_sum_m", "Сумма заказов за текущий месяц, руб", "money"),
    ("orders_pm", "Кол-во заказов за предыдущий месяц", "int"),
    ("orders_sum_pm", "Сумма заказов за предыдущий месяц, руб", "money"),
    ("in_way", "Кол-во товаров в пути (к и от клиента)", "int"),
    ("in_way_cost", "Стоимость товаров в пути (к и от клиента)", "money"),
    ("stock_no_spb", "Текущие остатки на складах WB (без СПБ Шушары)", "int"),
    ("stock_cost_no_spb", "Стоимость остатков на складах WB (без СПБ Шушары) в ценах с/с, руб", "money"),
]


def compute(c, shop: int, yesterday=None, nm_ids=None) -> list[dict]:
    y = yesterday or today_msk() - timedelta(days=1)
    today = y + timedelta(days=1)
    w_end = today - timedelta(days=today.isoweekday()); w_beg = w_end - timedelta(days=6)
    m_beg = y.replace(day=1); pm_end = m_beg - timedelta(days=1); pm_beg = pm_end.replace(day=1)
    P = {"a": shop, "y": y, "y1": y - timedelta(days=1), "wb": w_beg, "we": w_end, "mb": m_beg, "pmb": pm_beg, "pme": pm_end}
    rows: dict = defaultdict(dict)

    def key(r):
        return (r["supplier_article"] or "").lower(), r["barcode"] or "", r["nm_id"], r["tech_size"] or "0"

    for r in c.execute("""
        SELECT lower(supplier_article) supplier_article, barcode, nm_id, tech_size,
          count(*) FILTER (WHERE order_dt::date=%(y)s) oy, count(*) FILTER (WHERE order_dt::date=%(y1)s) oy1,
          count(*) FILTER (WHERE order_dt::date BETWEEN %(mb)s AND %(y)s) om,
          sum(price_with_disc) FILTER (WHERE order_dt::date BETWEEN %(mb)s AND %(y)s) osm,
          count(*) FILTER (WHERE order_dt::date BETWEEN %(pmb)s AND %(pme)s) opm,
          sum(price_with_disc) FILTER (WHERE order_dt::date BETWEEN %(pmb)s AND %(pme)s) ospm
        FROM orders WHERE account_id=%(a)s AND order_dt::date BETWEEN %(pmb)s AND %(y)s GROUP BY 1,2,3,4""", P):
        rows[key(r)].update(orders_y=r["oy"], orders_y1=r["oy1"], orders_diff=r["oy"] - r["oy1"], orders_m=r["om"],
                            orders_sum_m=r["osm"] or 0, orders_pm=r["opm"], orders_sum_pm=r["ospm"] or 0)
    for r in c.execute("""
        SELECT lower(supplier_article) supplier_article, barcode, nm_id, tech_size,
          count(*) FILTER (WHERE s AND sale_dt::date=%(y)s) by, sum(for_pay) FILTER (WHERE s AND sale_dt::date=%(y)s) ry,
          count(*) FILTER (WHERE s AND sale_dt::date BETWEEN %(wb)s AND %(we)s) bw, sum(for_pay) FILTER (WHERE s AND sale_dt::date BETWEEN %(wb)s AND %(we)s) rw,
          count(*) FILTER (WHERE s AND sale_dt::date BETWEEN %(mb)s AND %(y)s) bm, sum(for_pay) FILTER (WHERE s AND sale_dt::date BETWEEN %(mb)s AND %(y)s) rm,
          count(*) FILTER (WHERE s AND sale_dt::date BETWEEN %(pmb)s AND %(pme)s) bpm, sum(for_pay) FILTER (WHERE s AND sale_dt::date BETWEEN %(pmb)s AND %(pme)s) rpm
        FROM (SELECT *, sale_id LIKE 'S%%' s FROM sales WHERE account_id=%(a)s AND sale_dt::date BETWEEN LEAST(%(pmb)s, %(wb)s) AND %(y)s) x
        GROUP BY 1,2,3,4""", P):
        rows[key(r)].update(buy_y=r["by"], rev_y=r["ry"] or 0, buy_w=r["bw"], rev_w=r["rw"] or 0, buy_m=r["bm"], rev_m=r["rm"] or 0,
                            buy_pm=r["bpm"], rev_pm=r["rpm"] or 0)
    
    for r in c.execute("""
        WITH last AS (SELECT max(snap_at) t FROM stocks_wb_snap WHERE account_id=%(a)s)
        SELECT lower(n.vendor_code) supplier_article, coalesce(z.skus[1], '') barcode, s.nm_id, coalesce(z.tech_size, '0') tech_size,
               sum(s.quantity) q, sum(s.quantity) FILTER (WHERE s.warehouse NOT ILIKE '%%Шушары%%') qn,
               sum(coalesce(s.in_way_to_client,0) + coalesce(s.in_way_from_client,0)) w
        FROM stocks_wb_snap s JOIN last ON s.snap_at=last.t
        LEFT JOIN nomenclature n ON n.account_id=s.account_id AND n.nm_id=s.nm_id
        LEFT JOIN nm_sizes z ON z.account_id=s.account_id AND z.chrt_id=s.chrt_id
        WHERE s.account_id=%(a)s GROUP BY 1,2,3,4""", P):
        rows[key(r)].update(stock=r["q"], stock_no_spb=r["qn"] or 0, in_way=r["w"])
    costs = {r["nm_id"]: float(r["cost"]) for r in c.execute(
        "SELECT DISTINCT ON (nm_id) nm_id, cost FROM cost_price WHERE account_id=%(a)s AND valid_from<=%(y)s ORDER BY nm_id, valid_from DESC", P)}
    out = []
    for (art, bc, nm, ts), m in sorted(rows.items(), key=lambda x: (x[0][0], x[0][1])):
        if nm_ids and nm not in nm_ids:
            continue
        cu = costs.get(nm)
        row = {"supplier_article": art, "barcode": bc, "nm_id": nm, "tech_size": ts, **{k: m.get(k) for k, _, _ in PARAMS}}
        row["cost"] = cu
        if cu is not None:
            for q, v in (("stock", "stock_cost"), ("stock_no_spb", "stock_cost_no_spb"), ("in_way", "in_way_cost")):
                if row[q] is not None:
                    row[v] = round(float(row[q]) * cu, 2)
        out.append(row)
    return out

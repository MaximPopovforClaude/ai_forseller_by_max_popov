"""Заказы и продажи (statistics-api). WB хранит 90 дней → забираем всё, что отдаёт, и копим.

Курсор — lastChangeDate последней строки (как велит WB: следующий запрос с dateFrom = полное значение lastChangeDate).
Каждый запуск дополнительно отступает на OVERLAP_DAYS назад: изменения задним числом (отмены, возвраты) не теряются.
"""

import json
from datetime import datetime, timedelta

OVERLAP_DAYS = 3
FIRST_FROM = "2019-06-20"   


def _ts(s):
    if not s or s.startswith("0001-"):
        return None
    return s


def _pull(ctx, name, path, upsert) -> dict:
    st = ctx.state(name)
    last = st.get("last_change")
    if last:
        frm = (datetime.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).isoformat(timespec="seconds")
    else:
        frm = FIRST_FROM
    total, pages, newest = 0, 0, last
    while True:
        rows = ctx.wb.call("statistics", path, params={"dateFrom": frm}) or []
        for r in rows:
            upsert(ctx, r)
        ctx.c.commit()
        total += len(rows)
        pages += 1
        if rows:
            newest = max(newest or "", rows[-1]["lastChangeDate"])
            ctx.save_state(name, {"last_change": newest})       
        if len(rows) < 80000:
            break
        frm = rows[-1]["lastChangeDate"]
    return {"rows": total, "pages": pages, "cursor": {"last_change": newest}}


def _order(ctx, r):
    ctx.c.execute(
        """INSERT INTO orders(account_id,srid,order_dt,last_change_dt,nm_id,supplier_article,barcode,tech_size,warehouse,
             warehouse_type,okrug,region,total_price,discount_percent,spp,finished_price,price_with_disc,is_cancel,cancel_dt,data)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,srid) DO UPDATE SET last_change_dt=EXCLUDED.last_change_dt, warehouse=EXCLUDED.warehouse,
             warehouse_type=EXCLUDED.warehouse_type, total_price=EXCLUDED.total_price, discount_percent=EXCLUDED.discount_percent,
             spp=EXCLUDED.spp, finished_price=EXCLUDED.finished_price, price_with_disc=EXCLUDED.price_with_disc,
             is_cancel=EXCLUDED.is_cancel, cancel_dt=EXCLUDED.cancel_dt, data=EXCLUDED.data, updated_at=now()
           WHERE orders.last_change_dt <= EXCLUDED.last_change_dt""",
        (ctx.acc["id"], r["srid"], r["date"], r["lastChangeDate"], r.get("nmId"), r.get("supplierArticle"), r.get("barcode"),
         r.get("techSize"), r.get("warehouseName"), r.get("warehouseType"), r.get("oblastOkrugName"), r.get("regionName"),
         r.get("totalPrice"), r.get("discountPercent"), r.get("spp"), r.get("finishedPrice"), r.get("priceWithDisc"),
         r.get("isCancel"), _ts(r.get("cancelDate")), json.dumps(r, ensure_ascii=False)))


def _sale(ctx, r):
    ctx.c.execute(
        """INSERT INTO sales(account_id,sale_id,srid,sale_dt,last_change_dt,nm_id,supplier_article,barcode,tech_size,warehouse,
             warehouse_type,total_price,discount_percent,spp,for_pay,finished_price,price_with_disc,payment_sale_amount,data)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (account_id,sale_id) DO UPDATE SET last_change_dt=EXCLUDED.last_change_dt, for_pay=EXCLUDED.for_pay,
             finished_price=EXCLUDED.finished_price, price_with_disc=EXCLUDED.price_with_disc, spp=EXCLUDED.spp,
             payment_sale_amount=EXCLUDED.payment_sale_amount, data=EXCLUDED.data, updated_at=now()
           WHERE sales.last_change_dt <= EXCLUDED.last_change_dt""",
        (ctx.acc["id"], r["saleID"], r.get("srid"), r["date"], r["lastChangeDate"], r.get("nmId"), r.get("supplierArticle"),
         r.get("barcode"), r.get("techSize"), r.get("warehouseName"), r.get("warehouseType"), r.get("totalPrice"),
         r.get("discountPercent"), r.get("spp"), r.get("forPay"), r.get("finishedPrice"), r.get("priceWithDisc"),
         r.get("paymentSaleAmount"), json.dumps(r, ensure_ascii=False)))


def run_orders(ctx) -> dict:
    return _pull(ctx, "orders", "/api/v1/supplier/orders", _order)


def run_sales(ctx) -> dict:
    return _pull(ctx, "sales", "/api/v1/supplier/sales", _sale)

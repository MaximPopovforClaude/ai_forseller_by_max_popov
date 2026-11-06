"""Агрегат = лист БД#РеализацияПонедельно (36 колонок): детализация отчёта реализации, сгруппированная по
артикулу/баркоду/размеру × отчётная неделя × тип документа × обоснование для оплаты × обоснование штрафов.
Основа 5#PnL#РеализацияПонедельно и процента выкупа. Суммы из API приходят строками — приводим к числам.
"""

from collections import defaultdict

COLS = [
    ("vendor_code", "Артикул продавца", "text"), ("nm_id", "Артикул WB", "int"), ("barcode", "Штрихкод", "text"),
    ("tech_size", "Размер", "text"), ("subject", "Предмет", "text"), ("brand", "Бренд", "text"), ("seller", "Продавец", "text"),
    ("year_week", "Год/Неделя", "int"), ("date_from", "Дата начала отчётного периода", "date"), ("date_to", "Дата конца отчётного периода", "date"),
    ("report_type", "Тип отчёта", "int"), ("currency", "Валюта отчёта", "text"), ("doc_type", "Тип документа", "text"),
    ("oper", "Обоснование для оплаты", "text"), ("qty", "Кол-во", "int"),
    ("retail_disc", "Сумма в розничных ценах с учетом согласованной скидки", "money"), ("retail_amount", "Сумма продаж (возвратов)", "money"),
    ("for_pay", "Сумма к перечислению продавцу за реализованный товар", "money"), ("acquiring", "Возмещение издержек по эквайрингу", "money"),
    ("cost", "Сумма себестоимости", "money"), ("cost_avg", "Средняя себестоимость", "money"),
    ("deliveries", "Кол-во доставок при продажах", "int"), ("log_sales", "Стоимость логистики при продажах", "money"),
    ("log_sales_avg", "Средняя стоимость логистики при продаже", "money"),
    ("returns", "Кол-во доставок при возвратах", "int"), ("log_returns", "Стоимость логистики при возвратах", "money"),
    ("log_returns_avg", "Средняя стоимость логистики при возврате", "money"),
    ("bonus_type", "Обоснование штрафов и доплат", "text"), ("penalty", "Штрафы", "money"),
    ("additional", "Корректировка Вознаграждения Вайлдберриз", "money"), ("storage", "Стоимость хранения", "money"),
    ("deduction", "Прочие удержания/выплаты", "money"), ("acceptance", "Стоимость платной приёмки", "money"),
    ("rebill_log", "Прочие расходы/компенсации логистики", "money"),
    ("vat", "НДС к начислению с продаж", "money"), ("vat_deduct", "НДС к вычету с себестоимости", "money"),
]
OPER_RENAME = {"Штраф": "Штрафы"}   


def _bonus(b: str) -> str:
    """Self-hosted application component."""
    import re
    if "«Джем»" in b:
        return "Джем"
    b = re.sub(r", поставка \d+$", "", b)
    return re.sub(r"\s*за [а-яё]+ \d{4}, документ №\d+$", "", b)   
SUMS = ["qty", "retail_disc", "retail_amount", "for_pay", "acquiring", "deliveries", "log_sales", "returns", "log_returns",
        "penalty", "additional", "storage", "deduction", "acceptance", "rebill_log"]


def _n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _monday(s):
    from datetime import date, timedelta
    if not s:
        return s
    d = date.fromisoformat(s[:10])
    return (d - timedelta(days=d.isoweekday() - 1)).isoformat()


def _sunday(s):
    from datetime import date, timedelta
    return (date.fromisoformat(s) + timedelta(days=6)).isoformat() if s else s


def compute(c, shop: int, date_from=None, date_to=None) -> list[dict]:
    P = {"a": shop, "df": date_from, "dt": date_to}
    costs = defaultdict(list)
    for r in c.execute("SELECT nm_id, valid_from, cost FROM cost_price WHERE account_id=%(a)s ORDER BY nm_id, valid_from", P):
        costs[r["nm_id"]].append((r["valid_from"], float(r["cost"])))
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%(a)s ORDER BY valid_from DESC LIMIT 1", P).fetchone()
    vat_rate = float(tax["vat_rate"]) if tax else 0.0
    groups: dict = {}
    cur = c.cursor(name=f"real_week_{shop}")       
    cur.itersize = 20000
    cur.execute("""
        SELECT data FROM raw_rows WHERE account_id=%(a)s AND source='realization'
          AND (%(df)s::date IS NULL OR (data->>'dateTo')::date >= %(df)s) AND (%(dt)s::date IS NULL OR (data->>'dateTo')::date <= %(dt)s)""", P)
    for row in cur:
        d = row["data"]
        nm = d.get("nmId") or None
        
        wf = _monday(d.get("dateFrom"))
        key = (nm, d.get("sku") or "", d.get("techSize") or "", wf, _sunday(wf), d.get("reportType"),
               d.get("currency"), d.get("docTypeName") or "", OPER_RENAME.get(d.get("sellerOperName") or "", d.get("sellerOperName") or ""),
               _bonus(d.get("bonusTypeName") or ""))
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"vendor_code": d.get("vendorCode"), "nm_id": nm, "barcode": key[1], "tech_size": key[2],
                               "subject": d.get("subjectName"), "brand": d.get("brandName"), "date_from": key[3], "date_to": key[4],
                               "report_type": key[5], "currency": key[6], "doc_type": key[7], "oper": key[8], "bonus_type": key[9],
                               **{s: 0.0 for s in SUMS}}
        q = _n(d.get("quantity"))
        doc = (d.get("docTypeName") or "").lower()
        if doc in ("продажа", "возврат"):      
            g["qty"] += q
        g["retail_disc"] += _n(d.get("retailPriceWithDisc")) * q
        g["retail_amount"] += _n(d.get("retailAmount"))
        g["for_pay"] += _n(d.get("forPay"))
        g["acquiring"] += _n(d.get("acquiringFee"))
        dl, rt, ds = _n(d.get("deliveryAmount")), _n(d.get("returnAmount")), _n(d.get("deliveryService"))
        bt = (d.get("bonusTypeName") or "").lower()
        
        if ("к продавцу" in bt or "неопознанного товара" in bt or "сопровождения экспортных" in bt
                or (d.get("sellerOperName") or "").lower() in ("коррекция стоимости доставки", "коррекция логистики")):
            g["rebill_log"] += ds          
        else:
            g["deliveries"] += dl
            g["returns"] += rt
            if rt and not dl:
                g["log_returns"] += ds
            else:
                g["log_sales"] += ds
        g["penalty"] += _n(d.get("penalty"))
        g["additional"] += _n(d.get("additionalPayment"))
        g["storage"] += _n(d.get("paidStorage"))
        
        g["deduction"] += (_n(d.get("deduction")) + _n(d.get("cashbackAmount")) + _n(d.get("cashbackCommissionChange"))
                           - _n(d.get("cashbackDiscount")))
        g["acceptance"] += _n(d.get("paidAcceptance"))
    cur.close()
    out = []
    for g in groups.values():
        y, w, _ = __import__("datetime").date.fromisoformat(g["date_from"]).isocalendar() if g["date_from"] else (0, 0, 0)
        g["year_week"] = y * 100 + w
        cu = None
        for vf, cst in costs.get(g["nm_id"], []):
            if g["date_to"] and vf.isoformat() <= g["date_to"]:
                cu = cst
        g["cost_avg"] = cu
        g["cost"] = round(cu * g["qty"], 2) if cu is not None else None
        g["log_sales_avg"] = round(g["log_sales"] / g["deliveries"], 3) if g["deliveries"] else 0
        g["log_returns_avg"] = round(g["log_returns"] / g["returns"], 3) if g["returns"] else 0
        g["vat"] = round(g["retail_amount"] * vat_rate / (1 + vat_rate), 2) if vat_rate else 0
        g["vat_deduct"] = 0
        out.append(g)
    return sorted(out, key=lambda r: (r["date_from"] or "", r["vendor_code"] or "", r["oper"]), reverse=True)


def cached(c, shop: int, date_from=None, date_to=None) -> list[dict]:
    from ..materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    if not c.execute("SELECT 1 FROM agg_state WHERE account_id=%s AND name='real_week'", (shop,)).fetchone():
        from ..materialize import ensure_ready
        ensure_ready(c, shop, False)
        return compute(c, shop, date_from, date_to)
    rows = c.execute("""SELECT data FROM agg_real_week WHERE account_id=%s
                        AND (%s::date IS NULL OR (data->>'date_to')::date >= %s) AND (%s::date IS NULL OR date_from <= %s) ORDER BY seq""",
                     (shop, date_from, date_from, date_to, date_to)).fetchall()
    return [r["data"] for r in rows]


def weekly_deliveries(c, shop: int, nm_ids: list[int] | None = None) -> list[dict]:
    """Доставки и возвраты по неделям отчёта (для % выкупа) — суммой в базе, без разбора всего агрегата (главная тормозила, 28.10)."""
    if not c.execute("SELECT 1 FROM agg_state WHERE account_id=%s AND name='real_week'", (shop,)).fetchone():
        wk = defaultdict(lambda: [0.0, 0.0])
        for g in cached(c, shop):
            if not nm_ids or g["nm_id"] in nm_ids:
                w = wk[(g["date_from"], g["date_to"])]
                w[0] += float(g["deliveries"] or 0); w[1] += float(g["returns"] or 0)
        return [{"date_from": a, "date_to": b, "deliveries": d, "returns": r} for (a, b), (d, r) in wk.items()]
    return c.execute("""SELECT data->>'date_from' date_from, data->>'date_to' date_to,
                               sum(coalesce((data->>'deliveries')::numeric, 0))::float deliveries, sum(coalesce((data->>'returns')::numeric, 0))::float returns
                        FROM agg_real_week WHERE account_id=%s AND (%s::bigint[] IS NULL OR (data->>'nm_id')::bigint = ANY(%s))
                        GROUP BY 1, 2""", (shop, nm_ids, nm_ids)).fetchall()

"""Self-hosted application component."""

from collections import defaultdict
from datetime import date

from ..agg import real_week
from . import pnl_real

ROWS = [("rev", "Выручка (до СПП)", "money", True), ("buy", "Выкупы, ₽", "money", False), ("ret", "Возвраты, ₽", "money", False),
        ("wb_real", "WB реализовал", "money", False), ("spp", "% СПП", "pct", False), ("direct", "Прямые расходы", "money", True),
        ("cost", "Себестоимость", "money", False), ("comm", "Комиссия WB", "money", False), ("log", "Логистика", "money", False),
        ("ads", "Внутренняя реклама", "money", False), ("ext", "Внешняя реклама", "money", False), ("give", "Раздачи", "money", False),
        ("pen", "Штрафы", "money", False), ("stor", "Хранение", "money", False), ("acc", "Приёмка", "money", False),
        ("acq", "Эквайринг", "money", False), ("add", "Доплаты", "money", False), ("other", "Прочие удержания", "money", False),
        ("gross", "Валовая маржа", "money", True), ("wb_total", "Общая стоимость услуг ВБ", "money", False),
        ("to_pay", "Итого оплата на расчётный счёт", "money", False),
        ("tax", "Налог", "money", False), ("profit", "Прибыль после налога", "money", True)]


def compute(c, shop: int, year: int) -> dict:
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from DESC LIMIT 1", (shop,)).fetchone()\
        or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    A = defaultdict(lambda: defaultdict(float))
    for g in real_week.cached(c, shop, date(year, 1, 1), date(year, 12, 31)):
        if g["date_from"] and g["date_from"][:4] == str(year):
            pnl_real.accumulate(A[g["date_from"][:7]], g)
    for d, x in pnl_real.ads_fact(c, shop, f"{year}-01-01", f"{year}-12-31", only="Счет").items():   
        A[d[:7]]["ads"] += x
    ext = defaultdict(lambda: {"ext": 0.0, "give": 0.0})
    for e in c.execute("SELECT * FROM ext_costs WHERE account_id=%s AND d_from <= %s AND coalesce(d_to, d_from) >= %s",
                       (shop, date(year, 12, 31), date(year, 1, 1))):
        a, z = e["d_from"], e["d_to"] or e["d_from"]
        n = (z - a).days + 1
        for i in range(n):
            d = date.fromordinal(a.toordinal() + i)
            if d.year == year:
                ext[d.isoformat()[:7]]["give" if e["kind"] == "giveaway" else "ext"] += float(e["cost"] or 0) / n
    months = sorted(set(A) | set(ext))
    hist = c.execute("SELECT * FROM tax_settings WHERE account_id=%s ORDER BY valid_from", (shop,)).fetchall()

    def tax_of(m: str) -> dict:          
        end = f"{m}-31"
        cur = None
        for t in hist:
            if t["valid_from"].isoformat() <= end:
                cur = t
        return cur or (hist[0] if hist else tax)
    month_tax, month_R = {}, {}
    V = {}
    for m in months + ["year"]:
        if m == "year":
            a = defaultdict(float)
            for x in A.values():
                for k, v in x.items():
                    a[k] += v
            ex = {"ext": sum(v["ext"] for v in ext.values()), "give": sum(v["give"] for v in ext.values())}
        else:
            a, ex = A[m], ext[m]
        R = pnl_real.calc(a, tax if m == "year" else tax_of(m))
        if m != "year" and tax_of(m)["regime"] == pnl_real.IP:     
            pnl_real.ytd_ndfl({**month_R, m: R}, [*month_R, m], lambda p: tax_of(p)["regime"] == pnl_real.IP)
            month_R[m] = R
        if m == "year":
            R[53] = sum(month_tax.values())          
        else:
            month_tax[m] = R[53]
        rev = R[4]
        
        v = {"rev": rev, "buy": a["retail_disc_s"], "ret": a["retail_disc_r"], "wb_real": R[5], "spp": 1 - R[5] / rev if rev else None,
             "cost": R[47], "comm": rev - R[15] + R[25], "log": -R[28], "ads": -R[46], "ext": ex["ext"], "give": ex["give"], "pen": -R[38],
             "stor": -R[40], "acc": -R[45], "acq": -R[25], "add": R[39], "other": -R[41], "tax": -R[53]}
        v["direct"] = sum(v[k] for k in ("cost", "comm", "log", "ads", "ext", "give", "pen", "stor", "acc", "acq", "other")) - v["add"]
        v["gross"] = rev - v["direct"]
        v["wb_total"] = v["comm"] + v["log"] + v["ads"] + v["pen"] + v["stor"] + v["acc"] + v["acq"] + v["other"] - v["add"]
        v["to_pay"] = R[14]
        v["profit"] = v["gross"] - v["tax"]
        V[m] = v
    rows = []
    for k, label, fmt, bold in ROWS:
        r = {"label": ("▸ " if bold else "    ") + label, "fmt": fmt}
        for m, v in V.items():
            r[m] = v.get(k)
            if fmt == "money" and k != "rev":
                r[m + "_p"] = v[k] / v["rev"] if v["rev"] and v.get(k) is not None else None
        rows.append(r)
    return {"months": months, "rows": rows, "tax": tax["regime"]}

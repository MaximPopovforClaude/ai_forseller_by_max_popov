"""ИИ-разбор дня (дорожная карта п.2): что изменилось в магазине вчера и почему.

Цифры и причины находит код (правила ниже) — модель ничего не считает. Находки получает только нейросеть, разрешённая
серверным маршрутом магазина; без такого доступа — текст по шаблону. Неактивные API-тарифы ключи не используют.

Правила (вчера против среднего за 7 дней до него):
  • заказы магазина и артикулов: изменение ≥ 30 % и ≥ 5 шт (артикул — от 3 заказов/день в среднем или ≥ 10 вчера);
  • возможные причины по артикулу: нет/мало остатка, изменение цены/скидки (журнал), реклама остановлена/расход ±50 %,
    рейтинг −0,1, конверсия в корзину −30 %, СПП ±5 п.п., действия менеджеров, события у конкурентов;
  • остаток меньше чем на 10 дней продаж; заказы без себестоимости; артикулы в минус по марже.
"""

import json
import urllib.request
from datetime import date, timedelta

from . import config
from .config import today_msk

MODEL = "claude-sonnet-5-5"


def _num(x):
    return float(x) if x is not None else None


def _cost_revision(c, shop: int) -> str | None:
    row = c.execute("SELECT xmin::text revision FROM collector_state WHERE account_id=%s AND collector='_cost_rebuild'", (shop,)).fetchone()
    return row["revision"] if row else None


def _cost_lock(c, shop: int) -> None:
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ai-insights:{shop}",))


def invalidate_cost(c, shop: int, revision: str) -> None:
    """Retain old AI text but mark its numeric basis stale in the edit transaction."""
    _cost_lock(c, shop)
    for table in ("insights", "insights_staff"):
        c.execute(f"""UPDATE {table} SET findings=findings || jsonb_build_object('_cost_stale',%s::text)
                      WHERE account_id=%s AND EXISTS (SELECT 1 FROM accounts WHERE id=%s AND marketplace='wb')""",
                  (revision, shop, shop))


def findings(c, shop: int, day: date | None = None, nms: list[int] | None = None) -> dict:
    """nms — только эти артикулы (разбор по менеджеру)."""
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    y = day or today_msk() - timedelta(days=1)
    w0, w1 = y - timedelta(days=7), y - timedelta(days=1)
    agg = {}
    for r in c.execute("""SELECT nm_id, day, data FROM agg_nm_day WHERE account_id=%s AND day BETWEEN %s AND %s
                          AND (%s::bigint[] IS NULL OR nm_id = ANY(%s::bigint[]))""", (shop, w0, y, nms, nms)):
        agg.setdefault(r["nm_id"], {})[r["day"]] = r["data"]
    names = {r["nm_id"]: r for r in c.execute("SELECT nm_id, vendor_code, title FROM nomenclature WHERE account_id=%s", (shop,))}
    from .manager import stocks
    stock = {nm: v["total"] for nm, v in stocks(c, shop).items()}   
    changes = {}
    for r in c.execute("""SELECT nm_id, kind, field, old_value, new_value FROM card_changes WHERE account_id=%s
                          AND (detected_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s""", (shop, y - timedelta(days=2), y)):
        from .manager import change_label
        changes.setdefault(r["nm_id"], []).append(change_label(r))
    acts = {}
    from .manager import KINDS
    kt = {k["key"]: k["title"] for k in KINDS}
    for r in c.execute("SELECT nm_id, kind, value FROM nm_actions WHERE account_id=%s AND day BETWEEN %s AND %s", (shop, y - timedelta(days=2), y)):
        acts.setdefault(r["nm_id"], []).append(kt.get(r["kind"], r["kind"].replace("custom:", "")) + (f" {r['value']}" if r["value"] else ""))
    comp = {}
    try:
        from .market import events_for_shop
        for e in events_for_shop(c, shop, y):
            for vc in e["mine"] or []:
                comp.setdefault(vc, []).append(f"{e['title']} у {e['comp_nm_id']}")
    except Exception:  
        c.rollback()

    def tot(rows, k):
        return sum(float(r.get(k) or 0) for r in rows)
    shop_days = {}
    for nm, dd in agg.items():
        for d, r in dd.items():
            shop_days.setdefault(d, []).append(r)
    prev_days = [shop_days.get(w0 + timedelta(days=i), []) for i in range(7)]
    from . import wb_demand
    demand = {nm: (wb_demand.records(dd,y,y), wb_demand.records(dd,w0,w1)) for nm,dd in agg.items()}
    def complete_total(index,key):
        rows = [v[index] for v in demand.values()]
        valid = rows and all(r['complete'] and (key!='orders_sum' or r['money_days']==r['expected_days']) for r in rows)
        return sum(r[key] for r in rows) if valid else None
    yo, ys = complete_total(0,'orders'), complete_total(0,'orders_sum')
    po, ps = complete_total(1,'orders'), complete_total(1,'orders_sum')
    avg_o, avg_s = (po/7 if po is not None else None), (ps/7 if ps is not None else None)
    ya = tot(shop_days.get(y, []), "ads")
    avg_a = sum(tot(d, "ads") for d in prev_days) / 7
    out = {"day": y.isoformat(), 'orders_source': 'wb_funnel', 'data_note': wb_demand.NOTE,
           'demand_coverage': {'items':len(demand), 'incomplete_items':sum(not(a['complete'] and b['complete']) for a,b in demand.values())},
           "shop": {"orders": yo, "orders_avg7": wb_demand.rounded(avg_o, 1), "orders_sum": wb_demand.rounded(ys), "orders_sum_avg7": wb_demand.rounded(avg_s),
                                          "ads": round(ya), "ads_avg7": round(avg_a)},
           "articles": [], "low_stock": [], "no_cost": [], "negative": []}
    for nm, dd in agg.items():
        r = dd.get(y) or {}
        prev = [dd.get(w0 + timedelta(days=i)) or {} for i in range(7)]
        dm, prev_dm = demand[nm]
        o = dm['orders'] if dm['complete'] else None
        a7 = prev_dm['orders_day']
        financial_orders = float(r.get('orders') or 0)
        nmi = names.get(nm) or {}
        vc = nmi.get("vendor_code") or str(nm)
        st = stock.get(nm)
        if a7 is not None and a7 >= 1 and st is not None and st / a7 < 10:
            out["low_stock"].append({"nm_id": nm, "vendor_code": vc, "stock": st, "orders_avg7": round(a7, 1), "days": round(st / a7, 1)})
        if financial_orders and not r.get("cost_orders"):
            out["no_cost"].append({"nm_id": nm, "vendor_code": vc, "orders": financial_orders, 'source':'statistics'})
        if financial_orders >= 3 and r.get("margin_orders") is not None and float(r["margin_orders"]) < 0:
            out["negative"].append({"nm_id": nm, "vendor_code": vc, "orders": financial_orders, 'source':'statistics', "margin_orders": round(float(r["margin_orders"]))})
        if o is None or a7 is None:
            continue
        if not (a7 >= 3 or o >= 10):
            continue
        diff = o - a7
        if abs(diff) < 5 or abs(diff) / max(a7, 1) < 0.3:
            continue
        why = []
        if st == 0:
            why.append("сейчас нет остатка (WB и свой склад)" + (" (распродан)" if diff > 0 else ""))
        elif st is not None and a7 and st / a7 < 5 and diff < 0:
            why.append(f"остатка осталось на {st / a7:.0f} дн")
        why += changes.get(nm, [])
        ads_y, ads_7 = float(r.get("ads") or 0), sum(float(p.get("ads") or 0) for p in prev) / 7
        if ads_7 > 100 and ads_y < ads_7 * 0.2:
            why.append(f"реклама почти остановлена ({ads_y:.0f} ₽ против {ads_7:.0f} ₽/день)")
        elif ads_7 > 100 and abs(ads_y - ads_7) / ads_7 >= 0.5:
            why.append(f"расход на рекламу {'вырос' if ads_y > ads_7 else 'упал'}: {ads_y:.0f} ₽ против {ads_7:.0f} ₽/день")
        rt = [p.get("rating") for p in prev if p.get("rating") is not None]
        if r.get("rating") is not None and rt and float(rt[0]) - float(r["rating"]) >= 0.1:
            why.append(f"рейтинг {float(rt[0]):.1f} → {float(r['rating']):.1f}")
        ca, cb = dm['conv_cart'], prev_dm['conv_cart']
        if dm['conversion_days']==1 and prev_dm['conversion_days']==7 and ca is not None and cb and ca < cb * .7:
            why.append(f"конверсия в корзину {cb * 100:.1f} % → {ca * 100:.1f} %")
        sp = [float(p["orders_spp_share"]) for p in prev if p.get("orders_spp_share") is not None]
        if r.get("orders_spp_share") is not None and sp and abs(float(r["orders_spp_share"]) - sum(sp) / len(sp)) >= 0.05:
            why.append(f"СПП {sum(sp) / len(sp) * 100:.0f} % → {float(r['orders_spp_share']) * 100:.0f} %")
        why += [f"действие: {x}" for x in acts.get(nm, [])]
        why += comp.get(vc, [])
        out["articles"].append({"nm_id": nm, "vendor_code": vc, "title": (nmi.get("title") or "")[:60], "orders": o,
                                "orders_avg7": round(a7, 1), "change_pct": round(diff / max(a7, 1) * 100), "why": why})
    rc = []                                   
    for nm, dd in agg.items():
        a, b = (dd.get(y) or {}).get("rating"), (dd.get(y - timedelta(days=1)) or {}).get("rating")
        if a and b and float(a) > 0 and float(b) > 0 and round(float(a), 1) != round(float(b), 1):
            rc.append({"nm_id": nm, "vendor_code": (names.get(nm) or {}).get("vendor_code") or str(nm), "before": round(float(b), 1),
                       "now": round(float(a), 1), "orders": demand[nm][0]['orders']})
    out["rating_changes"] = sorted(rc, key=lambda x: -(x["orders"] or 0))[:20]
    out["articles"].sort(key=lambda x: -abs(x["orders"] - x["orders_avg7"]))
    out["low_stock"].sort(key=lambda x: x["days"])
    if nms is not None:
        own = {(names.get(n) or {}).get("vendor_code") or str(n) for n in nms}
        comp = {vc: v for vc, v in comp.items() if vc in own}
    out["competitors"] = [x for v in comp.values() for x in v][:20]
    try:                                       
        from .entry import analyze
        e = analyze(c, shop, y, nms)
        if e and (y - date.fromisoformat(e["day"])).days <= 2:
            out["entry_points"] = {k: e[k] for k in ("day", "base_days", "drops_n", "rises_n", "shop_points")} |\
                                  {"drops": e["drops"][:8], "rises": e["rises"][:5]}
    except Exception:  
        c.rollback()
    return out


def template_text(f: dict) -> str:
    """Разбор без нейросети — по шаблону, только цифры из findings."""
    s = f["shop"]
    L = []
    if s["orders_avg7"] and s['orders'] is not None:
        ch = (s["orders"] - s["orders_avg7"]) / s["orders_avg7"] * 100
        L.append(f"Заказы: {s['orders']:.0f} шт ({'+' if ch >= 0 else ''}{ch:.0f} % к среднему за неделю {s['orders_avg7']:.0f}).")
    elif s['orders'] is not None:
        L.append(f"Заказы по воронке: {s['orders']:.0f} шт. Сравнение с неделей недоступно.")
    else:
        L.append('Для итогов и сравнения заказов недостаточно дневных данных воронки; пропуски не означают нулевые заказы.')
    for a in f["articles"][:5]:
        why = "; ".join(a["why"][:3]) or "явной причины в данных нет"
        L.append(f"• {a['vendor_code']}: {a['orders']:.0f} шт против {a['orders_avg7']:.0f} в среднем "
                 f"({'+' if a['change_pct'] > 0 else ''}{a['change_pct']} %): {why}.")
    zero = [x for x in f["low_stock"] if not x["stock"]]
    low = [x for x in f["low_stock"] if x["stock"]]
    if zero:
        L.append(f"Нет в наличии ({len(zero)}): " + ", ".join(f"{x['vendor_code']} (~{x['orders_avg7']:.0f} заказов/день)"
                                                             for x in sorted(zero, key=lambda x: -x["orders_avg7"])[:6]) + ".")
    if low:
        L.append("Заканчивается остаток: " + ", ".join(f"{x['vendor_code']} ({x['days']:.0f} дн)" for x in low[:6]) + ".")
    if f.get("rating_changes"):
        r1 = lambda v: f"{v:.1f}".replace(".", ",")   
        L.append("⭐ Рейтинг в звёздах: " + ", ".join(f"{x['vendor_code']} {r1(x['before'])} → {r1(x['now'])}" + (" ▼" if x["now"] < x["before"] else " ▲")
                                                   for x in f["rating_changes"][:10]) + ".")
    if f["negative"]:
        L.append("В минус по марже: " + ", ".join(f"{x['vendor_code']} ({x['margin_orders']} ₽)" for x in f["negative"][:5]) + ".")
    if f["no_cost"]:
        L.append(f"Без себестоимости с заказами: {len(f['no_cost'])} арт.: заполните, иначе прибыль неточная.")
    if f.get("competitors"):
        L.append("Конкуренты: " + "; ".join(f["competitors"][:4]) + ".")
    e = f.get("entry_points")
    if e:
        one = lambda x: f"{x['vendor_code']} ({x['point']}: {x['clicks_avg']:.0f} → {x['clicks']}, {'+' if x['change_pct'] > 0 else ''}{x['change_pct']} %)"  
        if e.get("drops"):
            L.append(f"🚪 Точки входа за {e['day'][8:10]}.{e['day'][5:7]} — просели ({e['drops_n']}): " + "; ".join(one(x) for x in e["drops"][:5]) + ".")
        if e.get("rises"):
            L.append(f"🚪 Выросли ({e['rises_n']}): " + "; ".join(one(x) for x in e["rises"][:3]) + ".")
    return "\n".join(L) or "Вчера без заметных изменений."


PROMPT = """Ты — аналитик магазина на Wildberries. Ниже — находки за {day}, их посчитал код по данным API WB (JSON).
Напиши разбор для владельца магазина по-русски, коротко (до 16 строк, без заголовков и markdown-разметки, можно «•»):
1) главное за день одной-двумя фразами; 2) по важным артикулам — что случилось и вероятная причина из поля why;
3) каждое изменение рейтинга в звёздах из rating_changes (артикул, было → стало, например «4,6 → 4,5») — отдельной строкой, если они есть;
4) точки входа (entry_points, если есть): какие точки входа у каких артикулов сильно просели или выросли (переходы в день против среднего
   за прошлые дни: clicks_avg → clicks) и что это может значить (поиск — позиции/ставки/карточка, «Подборки и рекомендации» и «Похожие» —
   полки и реклама в полках, «Покупки»/«Доставка» — повторные покупки) — 2–4 строки, только самое заметное;
5) 2–4 конкретных действия на сегодня (поставка, цена, реклама, карточка), привязанных к находкам.
Используй ТОЛЬКО цифры из JSON, ничего не придумывай и не пересчитывай. Если причина не найдена — так и скажи.
Не используй длинное тире, только дефис.

JSON:
{data}"""


def ai_text(f: dict, key: str | None = None) -> tuple[str | None, str | None]:
    from .aireport import complete, model_name
    
    
    if not key:
        return None, None
    try:
        text = complete(key, "Ты аналитик магазина на Wildberries.", PROMPT.format(day=f["day"], data=json.dumps(f, ensure_ascii=False)), 900)
        return text or None, model_name(key)
    except Exception:  
        return None, None


def build(c, shop: int, day: date | None = None, use_ai: bool | None = None, staff_id: int | None = None, *, actor_id: int | None = None) -> dict:
    basis = _cost_revision(c, shop)
    nms = None
    if staff_id:
        from .staff import nms as staff_nms
        nms = staff_nms(c, shop, staff_id) or [0]
    f = findings(c, shop, day, nms)
    if use_ai is None:
        use_ai = (c.execute("SELECT w.plan FROM accounts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=%s", (shop,)).fetchone()
                  or {}).get("plan") == "ai"
    from .aireport import shop_key
    ws_key = shop_key(c, shop, actor_id)             
    text, model = ai_text(f, ws_key) if (use_ai or ws_key) else (None, None)
    
    
    _cost_lock(c, shop)
    if basis != _cost_revision(c, shop):
        from .materialize import NotReady
        raise NotReady("Исходные затраты изменились во время разбора. Прежний текст сохранён; новый разбор по старым цифрам не опубликован.")
    if staff_id:
        c.execute("""INSERT INTO insights_staff(account_id,day,staff_id,findings,ai_text,ai_model) VALUES (%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (account_id,day,staff_id) DO UPDATE SET findings=EXCLUDED.findings, ai_text=EXCLUDED.ai_text,
                       ai_model=EXCLUDED.ai_model, built_at=now()""", (shop, f["day"], staff_id, json.dumps(f, ensure_ascii=False), text, model))
    else:
        c.execute("""INSERT INTO insights(account_id,day,findings,ai_text,ai_model) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (account_id,day)
                     DO UPDATE SET findings=EXCLUDED.findings, ai_text=EXCLUDED.ai_text, ai_model=EXCLUDED.ai_model, built_at=now()""",
                  (shop, f["day"], json.dumps(f, ensure_ascii=False), text, model))
    c.commit()
    return {"findings": f, "ai_text": text, "ai_model": model, "text": text or template_text(f)}


def get(c, shop: int, day: date | None = None, rebuild: bool = False, staff_id: int | None = None, *, actor_id: int | None = None) -> dict:
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    y = day or today_msk() - timedelta(days=1)
    r = (c.execute("SELECT * FROM insights_staff WHERE account_id=%s AND day=%s AND staff_id=%s", (shop, y, staff_id)) if staff_id
         else c.execute("SELECT * FROM insights WHERE account_id=%s AND day=%s", (shop, y))).fetchone()
    if not r or rebuild:
        return build(c, shop, y, staff_id=staff_id, actor_id=actor_id)
    if (r["findings"] or {}).get("_cost_stale"):
        nms = None
        if staff_id:
            from .staff import nms as staff_nms
            nms = staff_nms(c, shop, staff_id) or [0]
        fresh = findings(c, shop, y, nms)
        explanation = "Затраты обновились: прежний текст нейросети скрыт, потому что опирался на старые цифры. Ниже — свежий разбор по правилам; новый вызов нейросети не выполнялся."
        return {"findings": fresh, "ai_text": None, "ai_model": None, "text": explanation + "\n\n" + template_text(fresh),
                "stale_ai": True, "stale_reason": explanation, "source_built_at": r["built_at"]}
    return {"findings": r["findings"], "ai_text": r["ai_text"], "ai_model": r["ai_model"], "text": r["ai_text"] or template_text(r["findings"]),
            "built_at": r["built_at"]}

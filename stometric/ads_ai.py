"""Self-hosted application component."""

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import actions
from .config import today_msk

KIND_T = {"pause": "Пауза кампании", "start": "Запустить кампанию", "nm_remove": "Убрать артикул из кампании", "bid": "Ставка",
          "kw_minus": "Ключ в минус-фразы", "kw_unminus": "Вернуть ключ (убрать из минус-фраз)", "kw_bid": "Ставка на ключ",
          "placements": "Места размещения", "deposit": "Пополнить бюджет", "create": "Создать кампанию"}  
STATUS_T = {4: "готова к запуску", 7: "завершена", 8: "отказ", 9: "активна", 11: "на паузе"}
PLACE_T = {"search": "поиск", "recommendations": "рекомендации", "combined": "поиск и рекомендации"}
MONEY_KINDS = {"deposit", "create"}           

FAST_DAYS = 3        
WINDOW_DAYS = 7      
ECO_DAYS = 14        
KW_DAYS = 7          
WARMUP_H = 24        
WARMUP_VIEWS_H = 25  
RECO_FRESH_H = 24    
RECO_PER_RUN = 10    
REJECT_QUIET_DAYS = 3
APPLIED_QUIET_H = 12
BUDGET_PAUSES = 3    

SEASONS = (("обогрев", (10, 11, 12, 1, 2, 3)), ("тепловые пушки", (10, 11, 12, 1, 2, 3)), ("конвектор", (10, 11, 12, 1, 2, 3)),
           ("тепловые завесы", (10, 11, 12, 1, 2, 3)), ("тепловентилятор", (10, 11, 12, 1, 2, 3)), ("снегоуб", (11, 12, 1, 2, 3)),
           ("лопаты для снега", (11, 12, 1, 2)), ("свеч", (11, 12, 1, 2)),     
           ("триммер", (4, 5, 6, 7, 8)), ("газонокосил", (4, 5, 6, 7, 8)), ("культиватор", (4, 5, 6)), ("бассейн", (5, 6, 7, 8)),
           ("кондиционер", (5, 6, 7, 8)), ("вентилятор", (5, 6, 7, 8)), ("опрыскивател", (4, 5, 6, 7)), ("мойки высокого давления", (4, 5, 6, 7, 8, 9)))
MAX_KW = 40          
MAX_CREATE = 3       
MIN_DEPOSIT = 1000   


def settings(c, shop: int) -> dict:
    """Пороги правил (настройки блока «Реклама», по умолчанию — actions.BLOCKS["ads"]["defaults"])."""
    return actions.block(c, shop, "ads")["settings"]


def _f(v) -> float:
    return float(v or 0)


def _rub(v) -> str:
    return f"{v:,.0f}".replace(",", " ") + " ₽"



def campaigns(c, shop: int, statuses=(4, 9, 11)) -> dict[int, dict]:
    """Кампании из последнего сбора (обновляются раз в час): статус, тип ставки, оплата, места, артикулы и ставки (копейки)."""
    out = {}
    for r in c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts' AND (data->>'status')::int = ANY(%s)",
                       (shop, list(statuses))):
        cp = campaigns_from(r["data"])
        if cp["status"] in statuses:
            out[cp["id"]] = cp
    return out


def campaigns_from(d: dict) -> dict:
    info = d.get("info") or {}
    st = info.get("settings") or {}
    started = (info.get("timestamps") or {}).get("started") or ""
    return {"id": int(d["advertId"]), "status": int(d.get("status") or 0), "name": st.get("name") or str(d["advertId"]),
            "bid_type": info.get("bid_type"), "payment": st.get("payment_type"), "placements": st.get("placements") or {},
            "can_change_nms": (info.get("restrictions") or {}).get("can_change_nms", True),
            "started": started if started and not started.startswith("2100") else None,
            "nms": {int(n["nm_id"]): {k: int(v or 0) for k, v in (n.get("bids_kopecks") or {}).items()} for n in info.get("nm_settings") or []}}


def _ad_stats(c, shop: int, df, dt) -> dict[tuple[int, int], dict]:
    """(кампания, артикул) → расход, показы, клики, корзины, заказы, сумма заказов; включая «ассоциированные» артикулы склейки (расход 0)."""
    out: dict = defaultdict(lambda: defaultdict(float))
    for r in c.execute("""
        SELECT (data->>'advertId')::bigint a, (nm->>'nmId')::bigint nm, sum((nm->>'sum')::numeric) spend, sum((nm->>'views')::numeric) v,
               sum((nm->>'clicks')::numeric) cl, sum((nm->>'orders')::numeric) o, sum((nm->>'sum_price')::numeric) sp,
               sum((nm->>'atbs')::numeric) atb
        FROM raw_rows, jsonb_array_elements(CASE WHEN jsonb_typeof(data->'apps')='array' THEN data->'apps' ELSE '[]'::jsonb END) app,
             jsonb_array_elements(CASE WHEN jsonb_typeof(app->'nms')='array' THEN app->'nms' ELSE '[]'::jsonb END) nm
        WHERE account_id=%s AND source='ad_stats' AND row_date BETWEEN %s AND %s GROUP BY 1, 2""", (shop, df, dt)):
        s = out[(r["a"], r["nm"])]
        s["spend"] += _f(r["spend"]); s["views"] += _f(r["v"]); s["clicks"] += _f(r["cl"]); s["orders"] += _f(r["o"]); s["sum"] += _f(r["sp"])
        s["carts"] += _f(r["atb"])
    return out


def imt_map(c, shop: int) -> dict[int, int]:
    """Артикул → склейка (imt_id; нет — сам артикул)."""
    return {r["nm_id"]: r["imt_id"] or r["nm_id"] for r in c.execute("SELECT nm_id, imt_id FROM nomenclature WHERE account_id=%s", (shop,))}


def economics(c, shop: int, df=None, dt=None) -> dict:
    """Прибыль с заказа до рекламы по артикулам — формулы 5#Дашборд (строки 15–35) на артикул, % выкупа — как в РНП.
    → {"nm": {артикул: {...}}, "imt": {склейка: средняя прибыль с заказа}, "k_ad": доля рекламы, которая реально уменьшает прибыль
    (НДС к вычету с рекламы / меньше налог при «доходы − расходы»)}."""
    from . import manager, rnp
    from .agg import nm_day
    y = today_msk() - timedelta(days=1)
    dt = dt or y
    df = df or dt - timedelta(days=ECO_DAYS - 1)
    acc = defaultdict(lambda: defaultdict(float))
    for r in nm_day.cached(c, shop, df, dt):
        a = acc[r["nm_id"]]
        for k in ("orders", "orders_sum", "orders_sum_spp", "commission_offer_orders", "cost_orders", "logistics_orders", "vat_orders", "vat_deduct_orders",
                  "f_cart", "f_orders"):
            a[k] += _f(r.get(k))
    bp, bp_all = rnp.buyout_pct(c, shop)
    tax = c.execute("SELECT * FROM tax_settings WHERE account_id=%s AND valid_from<=%s ORDER BY valid_from DESC LIMIT 1", (shop, dt)).fetchone()\
        or {"regime": "Другая СНО", "rate": 0, "vat_rate": 0, "vat_deduct_wb": 0}
    regime, rate, vat_rate, vw = tax["regime"], _f(tax["rate"]), _f(tax["vat_rate"]), _f(tax.get("vat_deduct_wb"))
    k_ad = 1.0
    if regime == "УСН доходы-расходы":
        k_ad = 1 - rate
    elif vat_rate >= 0.10 and vw:
        k_ad = 1 - vw / (1 + vw)
    stk = manager.stocks(c, shop)
    imt = imt_map(c, shop)
    days = (dt - df).days + 1
    
    
    unit = {}
    try:
        from . import unit_wb
        for u in unit_wb.compute(c, shop):
            if u.get("cost") and u.get("profit") is not None and u.get("bp"):
                unit[u["nm_id"]] = (u["profit"], u["bp"])
    except Exception:  
        c.rollback()
    nm_out, by_imt = {}, defaultdict(lambda: [0.0, 0.0])
    conv = defaultdict(lambda: [0.0, 0.0])                    
    for nm, a in acc.items():
        cv = conv[imt.get(nm, nm)]
        cv[0] += a.get("f_orders", 0.0); cv[1] += a.get("f_cart", 0.0)
    for nm in set(acc) | set(stk):
        a = acc.get(nm) or {}
        o = a.get("orders", 0.0)
        b = bp.get(nm, bp_all)
        m = None
        if o >= 1 and a.get("cost_orders", 0) > 0:
            r15, r17 = a["orders_sum"] * b, a.get("orders_sum_spp", 0) * b
            r20, r21, r22 = -a.get("commission_offer_orders", 0) * b, -a.get("logistics_orders", 0), a["cost_orders"] * b
            r18 = r15 + r20 + r21 - r22
            r33 = -a.get("vat_orders", 0) * b
            r34 = a.get("vat_deduct_orders", 0) * b + ((r20 + r21) * vw / (1 + vw) * -1 if vat_rate >= 0.10 and vw else 0)
            if regime == "УСН доход":
                r32 = -rate * (r17 + r33)
            elif regime == "УСН доходы-расходы":
                base = r18 + r33
                r32 = -(rate * base if rate * base > r17 * 0.01 else r17 * 0.01)
            else:
                r32 = 0.0
            m = (r18 + r32 + r33 + r34) / o
        if nm in unit:
            m = unit[nm][0] * unit[nm][1]
        if m is not None and o >= 1:
            g = by_imt[imt.get(nm, nm)]
            g[0] += m * o; g[1] += o
        speed = a.get("orders", 0.0) / days
        stock = (stk.get(nm) or {}).get("total")
        nm_out[nm] = {"orders": o, "speed": round(speed, 2), "stock": stock, "buyout": round(b, 3), "imt": imt.get(nm, nm),
                      "stock_days": round(stock / speed, 1) if stock is not None and speed else None,
                      "margin_order": round(m, 2) if m is not None else None, "unit": nm in unit}
    return {"nm": nm_out, "imt": {k: v[0] / v[1] for k, v in by_imt.items() if v[1]}, "k_ad": k_ad, "regime": regime,
            "cart_conv": {k: min(1.0, v[0] / v[1]) for k, v in conv.items() if v[1] >= 20}}


def exp_orders(eco: dict, gi: int, orders: float, carts: float) -> float:
    """Заказы с учётом задержки WB: не меньше, чем корзины × конверсия корзина → заказ склейки (нет конверсии — только заказы)."""
    k = eco.get("cart_conv", {}).get(gi)
    return max(orders, carts * k) if k else orders


def _m(eco: dict, nm: int) -> float | None:
    """Прибыль с заказа артикула; нет своей (нет себестоимости/заказов) — средняя по склейке."""
    e = eco["nm"].get(nm) or {}
    if e.get("margin_order") is not None:
        return e["margin_order"]
    return eco["imt"].get(e.get("imt", nm))


def group_stats(st: dict, aid: int, imt: dict, eco: dict, k_ad: float) -> dict[int, dict]:
    """Кампания → по склейкам: расход, клики, показы, рекламные заказы всей склейки, прибыль рекламы (оценка)."""
    out: dict = defaultdict(lambda: {"spend": 0.0, "clicks": 0.0, "views": 0.0, "orders": 0.0, "carts": 0.0, "profit": 0.0, "known": True})
    for (a, nm), s in st.items():
        if a != aid:
            continue
        g = out[imt.get(nm, nm)]
        g["spend"] += s["spend"]; g["clicks"] += s["clicks"]; g["views"] += s["views"]; g["orders"] += s["orders"]; g["carts"] += s["carts"]
        m = _m(eco, nm)
        if s["orders"] and m is None:
            g["known"] = False
        g["profit"] += s["orders"] * (m or 0)
    for gi, g in out.items():
        
        g["orders_exp"] = exp_orders(eco, gi, g["orders"], g["carts"])
        g["profit"] += (g["orders_exp"] - g["orders"]) * (eco["imt"].get(gi) or 0)
        g["profit"] -= g["spend"] * k_ad
    return out


def last_bid(c, shop: int) -> dict[tuple[int, int], tuple[str, str]]:
    """(кампания, артикул) → (bid_down / bid_up, итог better / same / worse) последнего применённого изменения ставки за 30 дней."""
    out = {}
    for r in c.execute("""SELECT DISTINCT ON (p.advert_id, p.nm_id) p.advert_id, p.nm_id, p.params, o.verdict FROM ad_proposals p
                          JOIN ad_outcomes o ON o.proposal_id=p.id WHERE p.account_id=%s AND p.kind='bid' AND p.decided_at > now() - interval '30 days'
                          ORDER BY p.advert_id, p.nm_id, p.decided_at DESC""", (shop,)):
        out[(r["advert_id"], r["nm_id"])] = (_action_key("bid", r["params"]), r["verdict"])
    return out


def cooldown(c, shop: int, hours: float) -> set[int]:
    """Self-hosted application component."""
    ids = {int(r["advert_id"]) for r in c.execute(
        """SELECT DISTINCT advert_id FROM ad_proposals WHERE account_id=%s AND status='applied' AND advert_id IS NOT NULL
           AND kind IN ('bid','kw_bid','placements','nm_remove','start') AND decided_at > now() - %s * interval '1 hour'""", (shop, hours))}
    for r in c.execute("""SELECT DISTINCT field FROM card_changes WHERE account_id=%s AND kind='ad_bid' AND field LIKE 'ad:%%'
                          AND detected_at > now() - %s * interval '1 hour'""", (shop, hours)):
        try:
            ids.add(int(r["field"][3:]))
        except ValueError:
            pass
    return ids


def recent_cuts(c, shop: int, days: int = 14) -> set[int]:
    """Кампании, где за days дней снижали ставку (кнопкой в сервисе или вручную в кабинете)."""
    ids = set()
    for r in c.execute("""SELECT field, old_value, new_value FROM card_changes WHERE account_id=%s AND kind='ad_bid' AND field LIKE 'ad:%%'
                          AND detected_at > now() - make_interval(days => %s)""", (shop, days)):
        o, n = r["old_value"] or {}, r["new_value"] or {}
        if sum(_f(n.get(k)) for k in ("search", "recommendations")) < sum(_f(o.get(k)) for k in ("search", "recommendations")):
            try:
                ids.add(int(r["field"][3:]))
            except ValueError:
                pass
    for r in c.execute("""SELECT advert_id, params FROM ad_proposals WHERE account_id=%s AND status='applied' AND kind='bid'
                          AND decided_at > now() - make_interval(days => %s)""", (shop, days)):
        if _action_key("bid", r["params"]) == "bid_down" and r["advert_id"]:
            ids.add(int(r["advert_id"]))
    return ids


def pause_counts(c, shop: int, days: int = 10) -> dict[int, int]:
    """Сколько раз кампания вставала на паузу за days дней (обычно — кончился бюджет)."""
    out = {}
    for r in c.execute("""SELECT field, count(*) n FROM card_changes WHERE account_id=%s AND kind='ad_status' AND field LIKE 'ad:%%'
                          AND new_value->>'status' = 'на паузе' AND detected_at > now() - make_interval(days => %s) GROUP BY 1""", (shop, days)):
        try:
            out[int(r["field"][3:])] = int(r["n"])
        except ValueError:
            pass
    return out


def _season_list(cfg: dict) -> list[tuple[str, tuple[int, ...]]]:
    """Сезоны: настройка «seasons» (строки «подстрока предмета: 10,11,12,1,2,3»; «-» вместо месяцев — предмет без сезона) поверх SEASONS."""
    own = []
    for line in str(cfg.get("seasons") or "").splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        ms = tuple(int(x) for x in v.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= 12)
        if k.strip():
            own.append((k.strip().lower(), ms))
    return own + list(SEASONS)


def season_of(subject: str | None, month: int, seasons: list) -> str | None:
    """«in» — сезон или месяц перед ним (разгон), «off» — не сезон, None — у предмета сезона нет."""
    sj = (subject or "").lower()
    for key, ms in seasons:
        if key in sj:
            if not ms:
                return None
            return "in" if month in ms or (month % 12) + 1 in ms else "off"
    return None


def organic(c, shop: int, imt: dict, ex: set, today, w: int, st: dict, stp: dict) -> dict[int, tuple[float, float]]:
    """Склейка → (органические заказы за окно, за прошлое окно): заказы воронки минус рекламные заказы (с ассоциированными)."""
    fo = defaultdict(lambda: [0.0, 0.0])
    for r in c.execute("""SELECT split_part(row_key,'|',1)::bigint nm, row_date d, (data->>'orderCount')::numeric o FROM raw_rows
                          WHERE account_id=%s AND source='funnel_day' AND row_date BETWEEN %s AND %s""", (shop, today - timedelta(days=2 * w - 1), today)):
        if r["nm"] in ex:
            continue
        fo[imt.get(r["nm"], r["nm"])][0 if r["d"] > today - timedelta(days=w) else 1] += _f(r["o"])
    for i, sx in ((0, st), (1, stp)):
        for (a, n), v in sx.items():
            if n not in ex:
                fo[imt.get(n, n)][i] -= v["orders"]
    return {k: (max(0.0, v[0]), max(0.0, v[1])) for k, v in fo.items()}


def cabinet_types(c, shop: int, eco: dict, imt: dict, days: int = 30) -> list[tuple[str, float, float]]:
    """Self-hosted application component."""
    y = today_msk()
    st = _ad_stats(c, shop, y - timedelta(days=days - 1), y)
    camps = campaigns(c, shop, (4, 7, 9, 11))
    agg = defaultdict(lambda: [0.0, 0.0])
    for aid, cp in camps.items():
        for g in group_stats(st, aid, imt, eco, eco["k_ad"]).values():
            if g["known"]:
                a = agg[ctype(cp)]
                a[0] += g["profit"]; a[1] += g["spend"]
    return sorted(((t, a[0] / a[1], a[1]) for t, a in agg.items() if a[1] >= 3000), key=lambda x: -x[1])


def learned(c, shop: int) -> dict[str, dict]:
    return {r["action"]: r for r in c.execute("SELECT * FROM ad_learn WHERE account_id=%s", (shop,))}


def reco(c, shop: int) -> dict[tuple[int, int], dict]:
    """Рекомендованные ставки WB (кэш): конкурентная — ориентир «выгодной» ставки."""
    out = {}
    for r in c.execute("SELECT advert_id, nm_id, data FROM ad_bid_reco WHERE account_id=%s AND fetched_at > now() - interval '3 days'", (shop,)):
        base = (r["data"] or {}).get("base") or {}
        out[(r["advert_id"], r["nm_id"])] = {k: int(((base.get(k) or {}).get("bidKopecks")) or 0) for k in ("competitiveBid", "leadersBid", "top2")}
    return out


def _wb(c, shop: int):
    from .wb import WB
    return WB(c, c.execute("SELECT * FROM accounts WHERE id=%s", (shop,)).fetchone())


def refresh_reco(c, shop: int, limit: int = RECO_PER_RUN) -> int:
    """Рекомендованные ставки по активным артикулам с наибольшим расходом (ключом на чтение; метод медленный — утром, фоном)."""
    from .wb import WBError
    y = today_msk()
    st = _ad_stats(c, shop, y - timedelta(days=FAST_DAYS - 1), y)
    fresh = {(r["advert_id"], r["nm_id"]) for r in c.execute(
        "SELECT advert_id, nm_id FROM ad_bid_reco WHERE account_id=%s AND fetched_at > now() - make_interval(hours => %s)", (shop, RECO_FRESH_H))}
    pairs = sorted(((aid, n) for aid, cp in campaigns(c, shop, (9,)).items() for n in cp["nms"] if (aid, n) not in fresh),
                   key=lambda k: -st[k]["spend"])[:limit]
    w, n = (_wb(c, shop) if pairs else None), 0
    for aid, nm in pairs:
        try:
            d = w.call("advert", "/api/advert/v0/bids/recommendations", params={"nmId": nm, "advertId": aid}, max_wait=30)
        except WBError:
            break
        if isinstance(d, dict):
            c.execute("""INSERT INTO ad_bid_reco(account_id,advert_id,nm_id,data) VALUES (%s,%s,%s,%s) ON CONFLICT (account_id,advert_id,nm_id)
                         DO UPDATE SET data=EXCLUDED.data, fetched_at=now()""", (shop, aid, nm, json.dumps(d, ensure_ascii=False)))
            c.commit()
            n += 1
    return n


def budgets(c, shop: int, ids: list[int]) -> dict[int, int]:
    """Остаток бюджета кампаний, ₽ (ключом на чтение; по 50 за запрос)."""
    out = {}
    w = _wb(c, shop) if ids else None
    for i in range(0, len(ids), 50):
        r = w.call("advert", "/api/advert/v2/budget", "POST", body={"advertIds": ids[i:i + 50]}) or {}
        for a in r.get("adverts") or []:
            out[int(a["advertId"])] = int(a.get("total") or 0)
    return out


def balance(c, shop: int) -> dict:
    """Счёт и баланс кабинета продвижения, ₽."""
    return _wb(c, shop).call("advert", "/adv/v1/balance") or {}



def _p(kind, advert=None, nm=None, query=None, before=None, after=None, reason="", effect=None, metrics=None, priority=0) -> dict:
    return {"kind": kind, "advert_id": advert, "nm_id": nm, "query": query, "params": {"before": before, "after": after},
            "reason": reason, "effect_week": round(effect) if effect is not None else None, "metrics": metrics or {},
            "priority": priority, "dkey": f"{kind}|{advert or ''}|{nm or ''}|{query or ''}"}


def _bids_scaled(camp: dict, nm: int, k: float, floor: int = 0) -> tuple[dict, dict] | None:
    """Текущие ставки артикула и новые (× k, не ниже floor; копейки; только включённые места; у единой ставки — одна, «combined»).
    None — менять нечего."""
    cur = camp["nms"].get(nm) or {}
    if camp["bid_type"] == "unified":
        b = cur.get("search") or cur.get("recommendations")
        before = {"combined": b} if b else {}
    else:
        before = {pl: v for pl, v in cur.items() if v and camp["placements"].get(pl, True)}
    if not before:
        return None
    after = {pl: max(1, floor, round(v * k)) for pl, v in before.items()}
    if all(after[pl] == before[pl] for pl in before) or (k < 1 and all(after[pl] >= before[pl] for pl in before)):
        return None
    return before, after


def _age_h(cp: dict) -> float | None:
    if not cp.get("started"):
        return None
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(cp["started"])).total_seconds() / 3600
    except ValueError:
        return None


def build(c, shop: int, with_api: bool = True, eco: dict | None = None) -> list[dict]:
    """Все предложения по магазину сейчас. Ничего не меняет в WB; with_api — читать бюджеты и баланс (ключом на чтение)."""
    from .exclusions import excluded
    cfg = settings(c, shop)
    today = today_msk()
    ex = excluded(c, shop)
    camps = campaigns(c, shop)
    eco = eco or economics(c, shop)
    k_ad = eco["k_ad"]
    imt = imt_map(c, shop)
    W = int(max(3, min(14, _f(cfg.get("window_days") or WINDOW_DAYS))))
    st = _ad_stats(c, shop, today - timedelta(days=W - 1), today)                       
    stp = _ad_stats(c, shop, today - timedelta(days=2 * W - 1), today - timedelta(days=W))   
    st3 = _ad_stats(c, shop, today - timedelta(days=FAST_DAYS - 1), today)               
    st2 = _ad_stats(c, shop, today - timedelta(days=1), today)
    step = max(5, min(50, _f(cfg["max_step"]))) / 100
    learn = learned(c, shop)
    step_down = min(step, _f((learn.get("bid_down") or {}).get("step")) or step)
    hurt_down = step_down < step - 1e-9                     
    step_up = min(step, _f((learn.get("bid_up") or {}).get("step")) or 0.1, 0.1)   
    rc = reco(c, shop)
    hist = last_bid(c, shop)
    cool = cooldown(c, shop, max(0.0, _f(cfg.get("cooldown_h", 72))))
    cut = recent_cuts(c, shop)
    seasons = _season_list(cfg)
    subj = {}
    for r in c.execute("SELECT nm_id, imt_id, subject FROM nomenclature WHERE account_id=%s", (shop,)):
        subj.setdefault(r["imt_id"] or r["nm_id"], r["subject"])
    org = organic(c, shop, imt, ex, today, W, st, stp)
    loss_min = _f(cfg["loss_min_spend"])
    out = []
    E = eco["nm"]
    EMPTY = {"spend": 0.0, "clicks": 0.0, "orders": 0.0, "carts": 0.0, "orders_exp": 0.0, "profit": 0.0, "known": True, "views": 0.0}

    def stock_low(n):
        e = E.get(n) or {}
        return e.get("stock") is not None and (e["stock"] <= 0 or (e.get("stock_days") is not None and e["stock_days"] < _f(cfg["stock_days_min"])))

    for aid, cp in camps.items():
        if cp["status"] != 9:
            continue
        nms = [n for n in cp["nms"] if n not in ex]
        if not nms:
            continue
        single = len(cp["nms"]) == 1
        
        low = [n for n in nms if stock_low(n)]
        spending = [n for n in low if st2[(aid, n)]["spend"] > 0]
        if spending:
            why = "; ".join(f"арт. {n}: остаток {E[n]['stock']:g} шт" + (f" (~{E[n]['stock_days']:g} дн.)" if E[n]["stock_days"] is not None else "")
                            for n in spending[:5])
            met = {str(n): {"stock": E[n]["stock"], "stock_days": E[n]["stock_days"]} for n in spending}
            if len(low) == len(cp["nms"]):
                out.append(_p("pause", aid, before=9, after=11, priority=100, metrics=met,
                              reason=f"Товар заканчивается — реклама тратит деньги, а купить скоро будет нечего: {why}."))
            elif cp["can_change_nms"]:
                for n in spending:
                    out.append(_p("nm_remove", aid, n, before="в кампании", after="убран", priority=95, metrics=met[str(n)],
                                  reason=f"Остаток {E[n]['stock']:g} шт" + (f" (~{E[n]['stock_days']:g} дн. продаж)" if E[n]["stock_days"] is not None else "")
                                  + " — убираем артикул из кампании, остальные товары продолжают крутиться."))
            continue
        
        age = _age_h(cp)
        if age is not None and age < WARMUP_H:
            if age >= 2:
                for n in nms:
                    v = sum(s["views"] for (a, nn), s in st2.items() if a == aid and nn == n)
                    if v < WARMUP_VIEWS_H * age:
                        bids = _bids_scaled(cp, n, 1 + step)
                        if bids:
                            out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=75,
                                          metrics={"age_h": round(age, 1), "views": int(v), "warmup": True},
                                          reason=f"Новая кампания (запущена {age:.0f} ч назад) мало показывается: {int(v)} показов. Поднимаем ставку на "
                                                 f"{step * 100:.0f} %, чтобы быстрее набрать ключи и данные; после разгона (24 ч) сервис будет снижать ставку к выгодной."))
            continue
        
        groups, groups3, groups_p = (group_stats(x, aid, imt, eco, k_ad) for x in (st, st3, stp))
        by_imt = defaultdict(list)
        for n in nms:
            by_imt[imt.get(n, n)].append(n)
        in_cool = aid in cool
        age_d = (age or 9999) / 24
        for gi, adv in by_imt.items():
            whole = len(adv) == len(cp["nms"])
            g, g3, gp = groups.get(gi) or EMPTY, groups3.get(gi) or EMPTY, groups_p.get(gi) or EMPTY

            def stop(pr, reason, met, effect=None):
                """Убыточную рекламу — на паузу (вся кампания на этой склейке) или убрать артикулы склейки из кампании."""
                if whole:
                    out.append(_p("pause", aid, before=9, after=11, priority=pr, effect=effect, metrics=met, reason=reason))
                    return True
                if cp["can_change_nms"]:
                    for n in adv:
                        out.append(_p("nm_remove", aid, n, before="в кампании", after="убран", priority=pr - 2, metrics=met,
                                      effect=effect / len(adv) if effect else None, reason=reason))
                    return True
                return False

            m = eco["imt"].get(gi)
            if m is None or not g["known"]:
                
                if g["spend"] >= loss_min and gp["spend"] >= loss_min and not in_cool:
                    stop(50, f"У товара не задана себестоимость — прибыль рекламы посчитать нельзя, а реклама идёт уже больше {W} дн.: "
                             f"за последние {W} дн. {_rub(g['spend'])}, за предыдущие {_rub(gp['spend'])}. Ставим на паузу, пока не задана "
                             "себестоимость (раздел «Себестоимость»), — потом сервис посчитает, окупается ли реклама.",
                         {"no_cost": True, "spend": round(g["spend"]), "spend_prev": round(gp["spend"]), "days": W})
                continue
            be = m / k_ad if m > 0 else 0.0                       
            met = {"days": W, "spend": round(g["spend"]), "clicks": int(g["clicks"]), "ad_orders_imt": int(g["orders"]),
                   "ad_carts_imt": int(g["carts"]), "ad_orders_expected": round(g["orders_exp"], 1), "profit_per_order": round(m),
                   "break_even_cpo": round(be), "ad_profit": round(g["profit"]), "ad_profit_prev": round(gp["profit"]), "regime": eco["regime"],
                   "unit": any((E.get(n) or {}).get("unit") for n in adv)}
            
            if g3["orders"] == 0 and g3["carts"] == 0 and g3["clicks"] >= 30 and g3["spend"] >= max(loss_min, be):
                stop(85, f"За {FAST_DAYS} дня реклама потратила {_rub(g3['spend'])}, {int(g3['clicks'])} кликов — и ни одного заказа и ни одной корзины "
                         f"по всей склейке (безубыточно — до {_rub(be)} рекламы на заказ).", {**met, "days": FAST_DAYS, "urgent": True},
                     g3["spend"] * k_ad * 7 / FAST_DAYS)
                continue
            
            if g["spend"] < max(loss_min, 2 * be) and g["clicks"] < 30:
                continue
            sea = season_of(subj.get(gi), today.month, seasons)
            o_now, o_prev = org.get(gi, (0.0, 0.0))
            org_up = (o_now >= o_prev * (1 + _f(cfg.get("season_organic_pct", 20)) / 100) and o_now > o_prev) if o_prev else o_now >= 3
            season_ok = (sea == "in" and g["profit"] < 0 and -g["profit"] <= _f(cfg.get("season_loss_pct", 20)) / 100 * g["spend"] and org_up)
            met.update({"season": sea, "organic": round(o_now), "organic_prev": round(o_prev), "season_ok": season_ok, "bid_cut_14d": aid in cut})
            cpo = g["spend"] / g["orders_exp"] if g["orders_exp"] else None
            cpo_t = f"{_rub(cpo)} за заказ" if cpo else "ни одного заказа"
            
            need = 1 if sea == "off" else int(max(1, _f(cfg.get("loss_weeks", 2))))
            
            
            deep = lambda x: x["profit"] < 0 and -x["profit"] >= x["spend"] * k_ad / 6  
            prev_loss = gp["known"] and gp["spend"] >= loss_min and deep(gp)
            
            
            tried = aid in cut or (cpo is not None and be > 0 and cpo >= 2 * be) or cpo is None
            if deep(g) and (need <= 1 or prev_loss) and not season_ok and not in_cool and tried:
                why = (f"Реклама в минусе {'два окна подряд' if need > 1 else 'и сейчас не сезон товара'}: за {W} дн. {_rub(g['profit'])} "
                       f"(расход {_rub(g['spend'])}, {int(g['orders'])} рекламных заказов по склейке, {cpo_t}; безубыточно — до {_rub(be)})"
                       + (f", за предыдущие {W} дн. {_rub(gp['profit'])}" if prev_loss else "") + ". ")
                why += ("По истории кабинетов после двух убыточных недель подряд третья тоже в минусе в 76–88 % случаев. " if need > 1 else
                        "Вне сезона разгон не окупается. ")
                if aid in cut:
                    why += "Ставку за последние 14 дней уже снижали — не помогло. "
                if sea == "in":
                    why += (f"Сезон, но органика не растёт ({o_prev:.0f} → {o_now:.0f} заказов без рекламы)" if not org_up else
                            f"Сезон и органика растёт, но минус больше {_f(cfg.get('season_loss_pct', 20)):g} % расхода") + ". "
                if stop(88, why + "Ставим на паузу; вернуть — когда товар будет давать прибыль с рекламой (цена, СПП, сезон).", met, -g["profit"] * 7 / W):
                    continue
            if cpo is None:
                continue
            carts_t = f" (корзин из рекламы {int(g['carts'])}" + (f", с учётом задержки заказов WB ждём ~{g['orders_exp']:.0f} заказов"
                                                                if g["orders_exp"] > g["orders"] + 0.5 else "") + ")"
            for n in adv:
                comp = (rc.get((aid, n)) or {}).get("competitiveBid") or 0
                cur = cp["nms"].get(n) or {}
                top = max(cur.values() or [0])
                last_act, last_v = hist.get((aid, n)) or (None, None)
                cap_t = f" Потолок ставки ~{top * be / cpo / 100:,.0f} ₽ — выше реклама не окупается.".replace(",", " ") if top and be else ""
                if in_cool:
                    continue                                  
                if g["profit"] < 0 and not season_ok:
                    
                    ratio = cpo / be if be > 0 else 9.0
                    tier = 0.30 if ratio >= 2 else 0.20 if ratio >= 1.2 else 0.10
                    if hurt_down:
                        tier = max(0.05, tier / 2)
                    k = 1 - min(tier, step)
                    
                    floor = comp if comp and ratio < 1.2 and last_act != "bid_down" else 0
                    bids = _bids_scaled(cp, n, k, floor)
                    if bids:
                        kr = sum(bids[1].values()) / max(1, sum(bids[0].values()))
                        out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=80, effect=g["spend"] * k_ad * (1 - kr) * 7 / W / len(adv),
                                      metrics={**met, "cpo": round(cpo), "ratio": round(ratio, 2), "competitive_bid": comp / 100 if comp else None},
                                      reason=f"Реклама в минусе: за {W} дн. {int(g['orders'])} рекламных заказов по склейке{carts_t}, {_rub(cpo)} за заказ, а "
                                             f"безубыточно — до {_rub(be)} (прибыль с заказа до рекламы ~{_rub(m)}: выкуп × прибыль с выкупа). Итог рекламы: "
                                             f"{_rub(g['profit'])}. Снижаем ставку на {(1 - kr) * 100:.0f} % (реклама на заказ в {ratio:.1f} раза дороже "
                                             f"безубыточной)." + (f" Не ниже конкурентной ставки WB {comp / 100:g} ₽." if floor else "") + cap_t))
                elif last_act == "bid_up" and last_v == "worse":
                    bids = _bids_scaled(cp, n, 0.9)
                    if bids:
                        out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=62, metrics={**met, "last_up": "worse"},
                                      reason="После прошлого повышения ставки прибыль склейки упала (итог «стало хуже») — возвращаем ставку на 10 % ниже."))
                elif last_act == "bid_down" and last_v == "worse" and g["profit"] >= 0:
                    
                    bids = _bids_scaled(cp, n, 1 + step_up)
                    if bids:
                        out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=60, metrics={**met, "last_down": "worse"},
                                      reason=f"После прошлого снижения ставки прибыль склейки упала (итог «стало хуже»). Для этого товара ставка оказалась "
                                             f"ниже выгодной — поднимаем на {step_up * 100:.0f} %." + cap_t))
                elif g["profit"] >= 0 and season_ok is False and (comp and age_d < 7 or (last_act == "bid_down" and last_v in ("better", "same")))\
                        and cpo > 0.5 * be:
                    
                    known = last_act == "bid_down" and last_v in ("better", "same")
                    if known or top > comp * 1.25:
                        bids = _bids_scaled(cp, n, 1 - min(step_down, 0.15), 0 if known else int(comp * 1.05))
                        if bids:
                            kr = sum(bids[1].values()) / max(1, sum(bids[0].values()))
                            why = (f"прошлое снижение ставки не ухудшило прибыль склейки — пробуем ещё шаг вниз (выгодная ставка у каждого товара своя"
                                   + (f", конкурентная WB — {comp / 100:g} ₽" if comp else "") + ")") if known else\
                                f"ставка {top / 100:g} ₽ заметно выше конкурентной {comp / 100:g} ₽"
                            out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=55, effect=g["spend"] * k_ad * (1 - kr) * 7 / W / len(adv),
                                          metrics={**met, "competitive_bid": comp / 100 if comp else None, "age_days": round(age_d, 1)},
                                          reason=f"Реклама в плюсе ({_rub(g['profit'])} за {W} дн., {_rub(cpo)} за заказ при безубыточных {_rub(be)}), {why}. "
                                                 f"Снижаем на {(1 - kr) * 100:.0f} % — та же реклама дешевле; итог проверим через 3–7 дней."))
                elif g["orders_exp"] >= 3 and be > 0 and cpo <= 0.5 * be and\
                        ((E.get(n) or {}).get("stock_days") or 0) >= _f(cfg.get("up_stock_days", 21)):
                    bids = _bids_scaled(cp, n, 1 + step_up)
                    if bids:
                        out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=45, metrics={**met, "cpo": round(cpo)},
                                      reason=f"Реклама окупается с запасом: за {W} дн. заказ из рекламы по склейке стоит {_rub(cpo)}{carts_t}, а безубыточно — до "
                                             f"{_rub(be)}; прибыль рекламы {_rub(g['profit'])}, товара на ~{E[n]['stock_days']:g} дн. Поднимаем ставку на "
                                             f"{step_up * 100:.0f} % — больше показов и заказов; если через 3–7 дней прибыль склейки упадёт, вернём."
                                             + cap_t))
    
    out += _kw_rules(c, shop, camps, eco, ex, cfg, step, hurt_down, step_up, cool)
    
    if with_api:
        try:
            out += _budget_rules(c, shop, camps, eco, imt, ex, cfg, k_ad, W)
        except Exception:  
            c.rollback()
    
    
    out += _growth_rules(c, shop, camps, eco, imt, ex, cfg, st, step_up, {(p["advert_id"], p["nm_id"]) for p in out if p["kind"] == "bid"})
    
    out += _type_rules(c, shop, camps, eco, imt, ex, cfg, st, W, cool)
    return out



TYPES = {"unified": "единая ставка (поиск + рекомендации)", "search": "ручная ставка, только поиск", "rec": "ручная ставка, только рекомендации (полки)",
         "manual": "ручная ставка, поиск + рекомендации", "cpc": "оплата за клики"}
TEST_ORDER = ("unified", "search", "rec")          
MAX_TESTS = 3


def ctype(cp: dict) -> str:
    if cp.get("payment") == "cpc":
        return "cpc"
    if cp.get("bid_type") == "unified":
        return "unified"
    pl = cp.get("placements") or {}
    if pl.get("search") and not pl.get("recommendations"):
        return "search"
    if pl.get("recommendations") and not pl.get("search"):
        return "rec"
    return "manual"


def _type_rules(c, shop, camps, eco, imt, ex, cfg, st, W=WINDOW_DAYS, cool=frozenset()) -> list[dict]:
    out = []
    
    types = cabinet_types(c, shop, eco, imt)
    cab_best = [t for t, roi, _ in types if t in TEST_ORDER and roi > 0]
    
    order = tuple(cab_best) if types else TEST_ORDER
    by_imt: dict = defaultdict(list)                  
    for aid, cp in camps.items():
        if cp["status"] != 9:
            continue
        for gi in {imt.get(n, n) for n in cp["nms"] if n not in ex}:
            by_imt[gi].append(aid)
    k_ad = eco["k_ad"]
    tests = 0
    nm_of = defaultdict(list)
    for nm, gi in imt.items():
        nm_of[gi].append(nm)
    vc = None
    for gi, aids in by_imt.items():
        if eco["imt"].get(gi) is None:
            continue                                  
        
        res = []
        for aid in aids:
            age = _age_h(camps[aid])
            g = group_stats(st, aid, imt, eco, k_ad).get(gi)
            if g and g["known"] and (age is None or age >= WARMUP_H) and g["spend"] >= _f(cfg["loss_min_spend"]) and aid not in cool:
                res.append((aid, g))
        if len(res) >= 2 and len({ctype(camps[a]) for a, _ in res}) >= 2:
            roi = lambda g: g["profit"] / g["spend"] if g["spend"] else 0  
            best_aid, best = max(res, key=lambda x: roi(x[1]))
            for aid, g in res:
                if aid == best_aid or ctype(camps[aid]) == ctype(camps[best_aid]):
                    continue
                if best["profit"] <= 0:
                    break                             
                if g["profit"] < 0 or roi(g) < 0.5 * roi(best):
                    whole = all(imt.get(n, n) == gi for n in camps[aid]["nms"])
                    if not whole:
                        continue                      
                    out.append(_p("pause", aid, before=9, after=11, priority=70, effect=max(0.0, -g["profit"]) * 7 / W,
                                  metrics={"type": ctype(camps[aid]), "profit": round(g["profit"]), "spend": round(g["spend"]),
                                           "best_advert": best_aid, "best_type": ctype(camps[best_aid]), "best_profit": round(best["profit"]),
                                           "best_spend": round(best["spend"])},
                                  reason=f"На склейке работают разные типы рекламы. За {W} дн.: «{TYPES[ctype(camps[aid])]}» — прибыль рекламы "
                                         f"{_rub(g['profit'])} на {_rub(g['spend'])} расхода, а «{TYPES[ctype(camps[best_aid])]}» (кампания {best_aid}) — "
                                         f"{_rub(best['profit'])} на {_rub(best['spend'])}. Оставляем более выгодный тип, этот — на паузу."))
        
        if tests >= MAX_TESTS or not cfg.get("create", True):
            continue
        have = {ctype(camps[a]) for a in aids}
        prof = sum((group_stats(st, a, imt, eco, k_ad).get(gi) or {}).get("profit", 0) for a in aids)
        stock_ok = [n for n in nm_of[gi] if n not in ex and ((eco["nm"].get(n) or {}).get("stock_days") or 0) >= 30]
        miss = [t for t in order if t not in have]
        if prof <= 0 or not stock_ok or not miss:
            continue
        advertised = {n for a in aids for n in camps[a]["nms"]}
        free = [n for n in stock_ok if n not in advertised]            
        target = max(free or stock_ok, key=lambda n: (eco["nm"].get(n) or {}).get("orders") or 0)
        t = miss[0]
        if vc is None:
            vc = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
        after = {"name": f"{vc.get(target) or target} · тест {t} · seller-analytics"[:100], "nms": [target],
                 "bid_type": "unified" if t == "unified" else "manual", "payment_type": "cpm"}
        if t in ("search", "rec"):
            after["placement_types"] = ["search"] if t == "search" else ["recommendations"]
        out.append(_p("create", None, target, query=f"test:{t}", before=None, after=after, priority=25,
                      metrics={"test_type": t, "have": sorted(have), "imt_profit": round(prof)},
                      reason=f"Склейка в плюсе от рекламы ({_rub(prof)} за {W} дн.), сейчас на ней: "
                             f"{', '.join(TYPES[x] for x in sorted(have))}. Пробуем отдельной кампанией «{TYPES[t]}»"
                             + (" на другом товаре этой склейки" if free else "") +
                             (f" — в этом кабинете этот тип окупается лучше других" if cab_best and t == cab_best[0] else "") +
                             ": через 7 дней после разгона сервис сравнит типы и предложит оставить выгодный."))
        tests += 1
    return out


def _kw_conv(c, shop: int, eco: dict, days: int = 14) -> dict[int, float]:
    """Склейка → конверсия клик → заказ рекламы за days дней (все кампании)."""
    y = today_msk()
    agg = defaultdict(lambda: [0.0, 0.0])
    for (a, n), v in _ad_stats(c, shop, y - timedelta(days=days - 1), y).items():
        g = agg[(eco["nm"].get(n) or {}).get("imt", n)]
        g[0] += v["orders"]; g[1] += v["clicks"]
    return {k: v[0] / v[1] for k, v in agg.items() if v[1] >= 50 and v[0] > 0}


def _kw_rules(c, shop, camps, eco, ex, cfg, step, hurt_down, step_up, cool) -> list[dict]:
    out = []
    kd = today_msk() - timedelta(days=KW_DAYS - 1)
    conv = _kw_conv(c, shop, eco)
    rows = c.execute("""
        WITH k AS (SELECT advert_id, nm_id, query, sum(clicks) cl, sum(orders) o, sum(atbs) atb, sum(spend) sp, sum(views) v FROM wb_ad_kw_daily
                   WHERE account_id=%(a)s AND day >= %(d)s GROUP BY 1, 2, 3 HAVING sum(spend) > 0 ORDER BY sum(spend) DESC LIMIT 500)
        SELECT k.*, (SELECT max(l.bid) FROM wb_ad_kw_lists l WHERE l.account_id=%(a)s AND l.advert_id=k.advert_id AND l.nm_id=k.nm_id
                       AND l.query=k.query AND l.state='active') bid,
               EXISTS (SELECT 1 FROM wb_ad_kw_lists l WHERE l.account_id=%(a)s AND l.advert_id=k.advert_id AND l.nm_id=k.nm_id
                       AND l.query=k.query AND l.state IN ('minus','excluded')) off
        FROM k ORDER BY k.sp DESC""", {"a": shop, "d": kd}).fetchall()
    k_ad = eco["k_ad"]
    n_kw = 0
    for r in rows:
        if n_kw >= MAX_KW:
            break
        aid, n = int(r["advert_id"]), int(r["nm_id"])
        cp = camps.get(aid)
        if not cp or cp["status"] != 9 or n in ex or r["off"]:
            continue
        m = _m(eco, n)
        be = m / k_ad if m and m > 0 else 0.0
        sp, cl, o0, atb = _f(r["sp"]), _f(r["cl"]), _f(r["o"]), _f(r["atb"])
        o = exp_orders(eco, (eco["nm"].get(n) or {}).get("imt", n), o0, atb)       
        met = {"days": KW_DAYS, "clicks": int(cl), "spend": round(sp), "orders": int(o0), "carts": int(atb), "orders_expected": round(o, 1),
               "profit_per_order": round(m) if m else None}
        
        
        cv = conv.get((eco["nm"].get(n) or {}).get("imt", n))
        need = min(300.0, max(_f(cfg["kw_min_clicks"]), 3 / cv if cv else 100.0))
        if o0 == 0 and atb == 0 and cl >= need and sp >= max(100, be):
            out.append(_p("kw_minus", aid, n, r["query"], before="показывается", after="в минус-фразах", priority=60, effect=sp * k_ad * 7 / KW_DAYS,
                          metrics={**met, "clicks_needed": round(need), "click_conv": round(cv, 4) if cv else None, "break_even_cpo": round(be)},
                          reason=f"Ключ «{r['query']}»: за {KW_DAYS} дн. {int(cl)} кликов, расход {_rub(sp)}, ни заказов, ни корзин"
                                 + (f" — а при обычной конверсии склейки ({cv * 100:.1f} % кликов в заказ) за столько кликов было бы ~{cl * cv:.0f} заказа"
                                    if cv else "") + ". По этому запросу не покупают."))
            n_kw += 1
            continue
        if aid in cool:
            continue                                      
        
        if cp["bid_type"] != "manual" or cp["payment"] != "cpm" or not m or o == 0:
            continue
        base = int(_f(r["bid"])) or int(((cp["nms"].get(n) or {}).get("search") or 0) / 100)
        if not base:
            continue
        cpo = sp / o
        prof = o * m - sp * k_ad
        if prof < 0 and o0 == 0 and sp < max(_f(cfg["loss_min_spend"]), 2 * be):
            continue                                      
        if prof < 0:
            ratio = cpo / be if be else 9.0
            tier = 0.30 if ratio >= 2 else 0.20 if ratio >= 1.2 else 0.10
            new = max(1, math.floor(base * (1 - min(step, max(0.05, tier / 2) if hurt_down else tier))))
            why = (f"Ключ «{r['query']}» в минусе: {int(o0)} заказов, {int(atb)} корзин (≈{o:.0f} заказов с учётом задержки WB) по {_rub(cpo)} "
                   f"при безубыточных {_rub(be)}, итог {_rub(prof)} за {KW_DAYS} дн.")
            eff, pr = sp * k_ad * (1 - new / base) * 7 / KW_DAYS, 58
        elif o >= 3 and cpo * k_ad <= 0.5 * m:
            new = math.ceil(base * (1 + step_up))
            why = (f"Ключ «{r['query']}» хорошо окупается: {int(o0)} заказов, {int(atb)} корзин, ~{_rub(cpo)} за заказ при прибыли с заказа ~{_rub(m)}. "
                   f"Поднимаем ставку — больше показов по выгодному запросу.")
            eff, pr = None, 42
        else:
            continue
        if new != base:
            out.append(_p("kw_bid", aid, n, r["query"], before=base, after=new, priority=pr, effect=eff, metrics={**met, "cpo": round(cpo)},
                          reason=why + f" Ставка за 1000 показов: {base} → {new} ₽."))
            n_kw += 1
    return out


def _budget_rules(c, shop, camps, eco, imt, ex, cfg, k_ad, W=WINDOW_DAYS) -> list[dict]:
    """Self-hosted application component."""
    out = []
    today = today_msk()
    st = _ad_stats(c, shop, today - timedelta(days=FAST_DAYS - 1), today)
    stw = _ad_stats(c, shop, today - timedelta(days=W - 1), today)
    pauses = pause_counts(c, shop)
    st14 = _ad_stats(c, shop, today - timedelta(days=13), today)
    
    ids = []
    for a, cp in camps.items():
        if cp["status"] == 11:
            g = group_stats(st14, a, imt, eco, k_ad)
            if not (sum(x["profit"] for x in g.values() if x["known"]) > 0 and sum(x["orders"] for x in g.values()) >= 3):
                continue
        elif cp["status"] == 9 and not any(st[(a, n)]["spend"] for n in cp["nms"]):
            continue
        ids.append(a)
    if not ids:
        return out
    bud = budgets(c, shop, ids)
    bal = None
    dmax = max(MIN_DEPOSIT, _f(cfg.get("deposit_max") or 5000))

    def source(total: int):
        nonlocal bal
        if bal is None:
            bal = balance(c, shop)
        if _f(bal.get("balance")) >= total:
            return 0, "со счёта"
        if _f(bal.get("net")) >= total:
            return 1, "с баланса (взаиморасчёт из будущих продаж)"
        return None, None

    for aid in ids:
        cp = camps[aid]
        nms = [n for n in cp["nms"] if n not in ex]
        if not nms or any((eco["nm"].get(n) or {}).get("stock_days") is not None and eco["nm"][n]["stock_days"] < 14 for n in nms)\
                or any(_m(eco, n) is None for n in nms):
            continue                           
        g14 = group_stats(st14, aid, imt, eco, k_ad)
        prof14 = sum(g["profit"] for g in g14.values() if g["known"])
        orders14 = sum(g["orders"] for g in g14.values())
        b = bud.get(aid)
        if cp["status"] == 9:
            g = group_stats(st, aid, imt, eco, k_ad)
            spend_day = sum(x["spend"] for x in g.values()) / FAST_DAYS
            gw = group_stats(stw, aid, imt, eco, k_ad)
            prof = sum(x["profit"] for x in gw.values() if x["known"])
            if b is None or spend_day <= 0 or b >= spend_day or prof <= 0 or not all(x["known"] for x in gw.values()):
                continue                       
            np_ = pauses.get(aid, 0)
            days_dep = 6 if np_ >= BUDGET_PAUSES else 3       
            total = int(max(MIN_DEPOSIT, min(dmax, math.ceil(spend_day * days_dep / 100) * 100)))
            t, src = source(total)
            if t is None:
                continue
            out.append(_p("deposit", aid, before={"budget": b}, after={"sum": total, "type": t}, priority=90,
                          metrics={"budget": b, "spend_day": round(spend_day), "ad_profit": round(prof), "days": W, "pauses_10d": np_},
                          reason=f"Бюджет кампании почти закончился: осталось {_rub(b)} при расходе ~{_rub(spend_day)} в день, а реклама в плюсе "
                                 f"({_rub(prof)} за {W} дн.)."
                                 + (f" За 10 дней кампания {np_} раз вставала на паузу — пополняем на неделю, чтобы реклама шла ровно." if days_dep > 3 else "")
                                 + f" Пополнить на {_rub(total)} {src} — примерно на {total / spend_day:.1f} дн. "
                                 f"(лимит пополнения в настройках блока — {_rub(dmax)})."))
        elif cp["status"] in (4, 11):
            ready = cp["status"] == 4
            if not ready and not (prof14 > 0 and orders14 >= 3):
                continue
            if b:
                out.append(_p("start", aid, before=cp["status"], after=9, priority=35 if not ready else 65,
                              metrics={"budget": b, "ad_profit_14d": round(prof14), "ad_orders_14d": int(orders14)},
                              reason=("Кампания создана и готова к запуску, бюджет есть." if ready else
                                      f"Кампания на паузе, а за 14 дней дала {int(orders14)} рекламных заказов по склейке и {_rub(prof14)} прибыли после рекламы; "
                                      "товара хватает (14+ дн.).") + f" Бюджет: {_rub(b)}. После запуска первые 24 ч — разгон."))
            else:
                total = int(max(MIN_DEPOSIT, min(dmax, 3000)))
                t, src = source(total)
                if t is None:
                    continue
                out.append(_p("deposit", aid, before={"budget": b or 0}, after={"sum": total, "type": t}, priority=60 if ready else 30,
                              metrics={"ad_profit_14d": round(prof14), "ad_orders_14d": int(orders14)},
                              reason=("Кампания готова к запуску, но бюджет пустой." if ready else
                                      f"Кампания на паузе без бюджета, а за 14 дней дала {_rub(prof14)} прибыли после рекламы.")
                                     + f" Пополнить на {_rub(total)} {src}; после пополнения сервис предложит запуск."))
    return out


GROWTH_SHARE = 0.15       
GROWTH_MIN_ORDERS = 14    
GROWTH_STOCK_DAYS = 30
GROWTH_BIDS = 5           
JAM_PER_RUN = 3           
JAM_FRESH_DAYS = 3


def growth_candidates(c, shop: int, eco: dict, imt: dict, ex: set) -> list[dict]:
    """Склейки, которые хорошо продаются без рекламы: заказов ≥ 1/день, рекламные заказы ≤ 15 %, прибыль с заказа > 0, товара ≥ 30 дн."""
    y = today_msk() - timedelta(days=1)
    ad_o, ad_sp = defaultdict(float), defaultdict(float)
    for (a, n), s in _ad_stats(c, shop, y - timedelta(days=ECO_DAYS - 1), y).items():
        ad_o[imt.get(n, n)] += s["orders"]; ad_sp[imt.get(n, n)] += s["spend"]
    by = defaultdict(list)
    for n, e in eco["nm"].items():
        if n not in ex:
            by[imt.get(n, n)].append((n, e))
    out = []
    for gi, items in by.items():
        o, m = sum(e["orders"] for _, e in items), eco["imt"].get(gi)
        if m is None or m <= 0 or o < GROWTH_MIN_ORDERS:
            continue
        n, e = max(items, key=lambda x: x[1]["orders"])
        if (e.get("stock_days") or 0) < GROWTH_STOCK_DAYS or ad_o[gi] / o > GROWTH_SHARE:
            continue
        out.append({"imt": gi, "nm": n, "orders": o, "ad_orders": ad_o[gi], "ad_spend": ad_sp[gi], "share": ad_o[gi] / o, "margin": m,
                    "stock_days": e["stock_days"]})
    return sorted(out, key=lambda x: -(x["orders"] - x["ad_orders"]) * x["margin"])


def _jam_items(c, shop: int, nm: int) -> list[dict] | None:
    r = c.execute("""SELECT items FROM jam_cache WHERE account_id=%s AND nm_id=%s AND state='done' AND fetched_at > now() - make_interval(days => %s)
                     ORDER BY fetched_at DESC LIMIT 1""", (shop, nm, JAM_FRESH_DAYS)).fetchone()
    return r["items"] if r else None


def growth_jam(c, shop: int) -> int:
    """Утром: поисковые запросы (Джем) главных артикулов склеек-кандидатов на рост — где товар в выдаче и сколько запросов."""
    from . import jam
    from .exclusions import excluded
    acc = jam.access(c, shop)
    if acc and acc["status"] != "ok":
        return 0
    eco, imt = economics(c, shop), imt_map(c, shop)
    y = today_msk() - timedelta(days=1)
    n = 0
    for x in growth_candidates(c, shop, eco, imt, excluded(c, shop))[:MAX_CREATE + GROWTH_BIDS]:
        if n >= JAM_PER_RUN:
            break
        if _jam_items(c, shop, x["nm"]) is not None:
            continue
        a = y - timedelta(days=13)
        items = jam.fetch(c, shop, x["nm"], a, y)
        c.execute("""INSERT INTO jam_cache(account_id,nm_id,date_from,date_to,state,items,fetched_at) VALUES (%s,%s,%s,%s,'done',%s::jsonb,now())
                     ON CONFLICT (account_id,nm_id,date_from,date_to) DO UPDATE SET state='done', items=EXCLUDED.items, error=NULL, fetched_at=now()""",
                  (shop, x["nm"], a, y, json.dumps(items, ensure_ascii=False)))
        c.commit()
        n += 1
    return n


def _queries(items: list[dict] | None) -> tuple[list[dict], int]:
    """Запросы, где товар покупают, но он не в топ-10 выдачи (есть куда подниматься), и сколько запросов уже в топ-10."""
    if not items:
        return [], 0
    wk = lambda q: _f(q.get("weekFrequency")) or _f(q.get("frequency")) / 2   
    sell = [q for q in items if _f(q.get("orders")) or _f(q.get("addToCart"))]
    low = [q for q in sell if _f(q.get("avgPosition")) > 10 and wk(q) >= 300]
    top = sum(1 for q in sell if 0 < _f(q.get("avgPosition")) <= 10)
    low.sort(key=lambda q: -wk(q))
    return [{"text": q["text"], "week": int(wk(q)), "pos": _f(q.get("avgPosition")), "orders": int(_f(q.get("orders"))),
             "carts": int(_f(q.get("addToCart")))} for q in low[:5]], top



KW_BAD_SPEND = 300      


def kw_history(c, shop: int, nms: list[int], queries: list[str] | None = None) -> dict:
    """Вся статистика ключа по артикулам (все кампании, вся история сбора, до полугода): {(nm, query): {...}} + в минусе/исключён ли."""
    if not nms:
        return {}
    p = {"a": shop, "n": list(nms), "q": [x.lower() for x in queries] if queries else None}
    wq = " AND lower(query) = ANY(%(q)s)" if queries else ""
    out = {}
    for r in c.execute(f"""SELECT nm_id, lower(query) q, sum(spend) sp, sum(clicks) cl, sum(atbs) atb, sum(orders) o, min(day) d0, max(day) d1
                           FROM wb_ad_kw_daily WHERE account_id=%(a)s AND nm_id = ANY(%(n)s){wq} GROUP BY 1, 2""", p):
        out[(r["nm_id"], r["q"])] = {"spend": _f(r["sp"]), "clicks": int(_f(r["cl"])), "carts": int(_f(r["atb"])), "orders": int(_f(r["o"])),
                                     "from": r["d0"], "to": r["d1"], "off": False}
    for r in c.execute(f"""SELECT DISTINCT nm_id, lower(query) q FROM wb_ad_kw_lists WHERE account_id=%(a)s AND nm_id = ANY(%(n)s)
                           AND state IN ('minus','excluded'){wq}""", p):
        out.setdefault((r["nm_id"], r["q"]), {"spend": 0.0, "clicks": 0, "carts": 0, "orders": 0, "from": None, "to": None})["off"] = True
    return out


def kw_merge(hist: dict, query: str) -> dict | None:
    """История ключа по всем артикулам (склейке) одной строкой."""
    xs = [v for (n, q), v in hist.items() if q == query.lower()]
    if not xs:
        return None
    d0 = [x["from"] for x in xs if x["from"]]
    return {"spend": sum(x["spend"] for x in xs), "clicks": sum(x["clicks"] for x in xs), "carts": sum(x["carts"] for x in xs),
            "orders": sum(x["orders"] for x in xs), "from": min(d0) if d0 else None, "off": any(x.get("off") for x in xs)}


def kw_verdict(h: dict | None, margin: float | None = None, k_ad: float = 1.0) -> tuple[str, str]:
    """Стоит ли возвращать ключ: bad — дорогой и без корзин/заказов (или заказы в минус), good — окупался, weak — корзины без заказов, thin — мало данных."""
    if not h or (not h["spend"] and not h["clicks"]):
        return "thin", "статистики по ключу нет"
    since = f"с {h['from']:%d.%m}" if h.get("from") else "за всё время"
    sp, o, atb, cl = h["spend"], h["orders"], h["carts"], h["clicks"]
    if o:
        cpo = sp / o
        if margin and cpo * k_ad > margin:
            return "bad", f"{since}: заказов {o} по {_rub(cpo)} при прибыли с заказа ~{_rub(margin)} — в минус"
        return ("good" if margin else "weak"), f"{since}: заказов {o}, корзин {atb}, {_rub(cpo)} за заказ" +\
            ("" if margin else " (прибыль с заказа неизвестна — нет себестоимости)")
    if atb:
        if sp >= max(3000, 2 * (margin or 0)):
            return "bad", f"{since}: корзин {atb}, заказов нет при расходе {_rub(sp)} — дорого"
        return "weak", f"{since}: корзин {atb}, заказов нет, расход {_rub(sp)}"
    if sp >= max(KW_BAD_SPEND, 0.5 * (margin or 0)):
        return "bad", f"{since}: расход {_rub(sp)}, кликов {cl} — ни корзин, ни заказов"
    return "thin", f"{since}: расход {_rub(sp)}, кликов {cl}"


def _growth_rules(c, shop, camps, eco, imt, ex, cfg, st, step_up, has_bid) -> list[dict]:
    vc = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s", (shop,))}
    recent = {r["imt"] for r in c.execute("""SELECT DISTINCT coalesce(n.imt_id, n.nm_id) imt FROM ad_proposals p JOIN nomenclature n
                                            ON n.account_id=p.account_id AND n.nm_id=p.nm_id WHERE p.account_id=%s AND p.kind='create'
                                            AND p.batch_at > now() - interval '14 days' AND p.status <> 'new'""", (shop,))}
    by_imt = defaultdict(list)                     
    for aid, cp in camps.items():
        for n in cp["nms"]:
            by_imt[imt.get(n, n)].append((aid, n))
    out, n_create, n_bid = [], 0, 0
    k_ad = eco["k_ad"]
    ct = None                                      
    for x in growth_candidates(c, shop, eco, imt, ex):
        gi, m = x["imt"], x["margin"]
        q, top = _queries(_jam_items(c, shop, x["nm"]))
        dropped = []
        if q:                    
            hist = kw_history(c, shop, [n for n, i in imt.items() if i == gi] or [x["nm"]], [y["text"] for y in q])
            keep = []
            for y in q:
                h = kw_merge(hist, y["text"])
                if h and h["off"]:
                    v, why = kw_verdict(h, m, k_ad)
                    if v == "bad":
                        dropped.append(f"«{y['text']}» ({why})")
                        continue
                    y["note"] = f"сейчас исключён из рекламы; по истории: {why}"
                keep.append(y)
            q = keep
        per_day = x["orders"] / ECO_DAYS
        qt = "; ".join(f"«{y['text']}» — {y['week']:,} запросов в неделю, средняя позиция {y['pos']:g}".replace(",", " ", 1)
                       + (f" ({y['note']})" if y.get("note") else "")
                       if y['week'] >= 1000 else f"«{y['text']}» — {y['week']} запросов в неделю, средняя позиция {y['pos']:g}"
                       + (f" ({y['note']})" if y.get("note") else "") for y in q[:3])
        base = (f"Склейка хорошо продаётся без рекламы: {int(x['orders'])} заказов за {ECO_DAYS} дней (~{per_day:.1f} в день), из рекламы — "
                f"{int(x['ad_orders'])} ({x['share'] * 100:.0f} %); прибыль с заказа ~{_rub(m)}, товара на ~{x['stock_days']:g} дн. ")
        if q:
            base += f"По запросам, где товар покупают, он не в топ-10 выдачи: {qt}. Выше в выдаче — больше показов и заказов. "
        elif top:
            base += f"По {top} запросам с заказами товар уже в топ-10 — рост за счёт рекламы скромнее. "
        if dropped:
            base += "Не возвращаем в рекламу (раньше были дорогими без корзин и заказов): " + "; ".join(dropped[:3]) + ". "
        met = {"orders_14d": int(x["orders"]), "ad_orders_14d": int(x["ad_orders"]), "ad_share": round(x["share"], 3), "profit_per_order": round(m),
               "stock_days": x["stock_days"], "break_even_cpo": round(m / k_ad), "queries_low": q, "queries_top10": top, "growth": True,
               "queries_dropped": dropped}
        active = [(aid, n) for aid, n in by_imt.get(gi, []) if camps[aid]["status"] == 9 and n not in ex]
        if not by_imt.get(gi):
            if n_create >= MAX_CREATE or gi in recent or not cfg.get("create", True):
                continue
            budget = max(MIN_DEPOSIT, round(per_day * 0.5 * m / 2 * 7 / 100) * 100)   
            if ct is None:
                types = cabinet_types(c, shop, eco, imt)
                ct = next((t for t, roi, _ in types if t in ("unified", "search", "rec", "manual") and roi > 0), "" if types else "unified")
            if not ct:
                continue                              
            after = {"name": f"{vc.get(x['nm']) or x['nm']} · рост · seller-analytics"[:100], "nms": [x["nm"]],
                     "bid_type": "unified" if ct == "unified" else "manual", "payment_type": "cpm"}
            if ct in ("search", "rec", "manual"):
                after["placement_types"] = {"search": ["search"], "rec": ["recommendations"], "manual": ["search", "recommendations"]}[ct]
            n_create += 1
            out.append(_p("create", None, x["nm"], before=None, after=after,
                          priority=30, metrics={**met, "test_budget": budget, "type": ct},
                          reason=base + f"Предлагаем тест рекламы: кампания «{TYPES[ct]}» (этот тип окупается в кабинете лучше других), бюджет на неделю "
                                        f"~{_rub(budget)}. Окупается, пока заказ из рекламы дешевле ~{_rub(m / k_ad)}; итог (заказы и корзины всей склейки "
                                        f"до/после) сервис покажет через 3–7 дней."))
        elif active and n_bid < GROWTH_BIDS:
            g = group_stats(st, active[0][0], imt, eco, k_ad).get(gi) or {}
            if g.get("profit", 0) < 0:
                continue                              
            for aid, n in active:
                if (aid, n) in has_bid or n_bid >= GROWTH_BIDS:
                    continue
                bids = _bids_scaled(camps[aid], n, 1 + step_up)
                if not bids:
                    continue
                n_bid += 1
                out.append(_p("bid", aid, n, before=bids[0], after=bids[1], priority=40, metrics=met,
                              reason=base + f"Реклама на склейке есть, но даёт мало заказов — поднимаем ставку на {step_up * 100:.0f} %, чтобы показываться выше. "
                                            f"Окупается, пока заказ из рекламы дешевле ~{_rub(m / k_ad)}; через 3–7 дней сравним заказы и корзины всей склейки."))
    return out


def save(c, shop: int, props: list[dict]) -> dict:
    """Новый разбор → ad_proposals: те же (по dkey) — обновляем, новые — добавляем, исчезнувшие — «устарели».
    Не предлагаем снова то, что пользователь отклонил за последние дни или применил за последние часы."""
    now = datetime.now(timezone.utc)
    quiet = {r["dkey"] for r in c.execute(
        """SELECT dkey FROM ad_proposals WHERE account_id=%s AND ((status='rejected' AND decided_at > now() - make_interval(days => %s))
           OR (status='applied' AND decided_at > now() - make_interval(hours => %s)))""", (shop, REJECT_QUIET_DAYS, APPLIED_QUIET_H))}
    keep, fresh = set(), []
    for p in props:
        if p["dkey"] in quiet or p["dkey"] in keep:
            continue
        keep.add(p["dkey"])
        r = c.execute("""INSERT INTO ad_proposals(account_id,batch_at,kind,advert_id,nm_id,query,params,reason,effect_week,metrics,priority,dkey)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (account_id, dkey) WHERE status='new' DO UPDATE SET batch_at=EXCLUDED.batch_at, params=EXCLUDED.params,
                           reason=EXCLUDED.reason, effect_week=EXCLUDED.effect_week, metrics=EXCLUDED.metrics, priority=EXCLUDED.priority
                         RETURNING (xmax = 0) AS inserted""",
                      (shop, now, p["kind"], p["advert_id"], p["nm_id"], p["query"], json.dumps(p["params"], ensure_ascii=False),
                       p["reason"], p["effect_week"], json.dumps(p["metrics"], ensure_ascii=False, default=str), p["priority"], p["dkey"])).fetchone()
        if r["inserted"]:
            fresh.append(p)
    c.execute("UPDATE ad_proposals SET status='expired' WHERE account_id=%s AND status='new' AND source='rules' AND NOT (dkey = ANY(%s))",
              (shop, list(keep)))
    c.commit()
    return {"total": len(keep), "new": fresh, "batch_at": now}



MEASURE_MIN_DAYS = 3     
MEASURE_MAX_DAYS = 7     


def _action_key(kind: str, params: dict) -> str:
    if kind in ("bid", "kw_bid"):
        a, b = params.get("after"), params.get("before")
        down = (sum(a.values()) < sum((b or {}).values())) if isinstance(a, dict) else (a or 0) < (b or 0)
        return ("kw_" if kind == "kw_bid" else "") + ("bid_down" if down else "bid_up")
    return kind


def measure(c, shop: int) -> int:
    """Self-hosted application component."""
    from .agg import nm_day
    y = today_msk() - timedelta(days=1)
    rows = c.execute("""SELECT p.*, o.final FROM ad_proposals p LEFT JOIN ad_outcomes o ON o.proposal_id=p.id
                        WHERE p.account_id=%s AND p.status='applied' AND p.kind NOT IN ('create')
                          AND (p.decided_at AT TIME ZONE 'Europe/Moscow')::date < %s AND p.decided_at > now() - interval '30 days'
                          AND coalesce(o.final, false) = false""", (shop, y)).fetchall()
    if not rows:
        return 0
    eco = economics(c, shop)
    imt = imt_map(c, shop)
    by_imt = defaultdict(list)
    for nm, gi in imt.items():
        by_imt[gi].append(nm)
    camps = campaigns(c, shop, (4, 7, 9, 11))
    k_ad = eco["k_ad"]
    ctrl_cache: dict = {}

    def gross(rows_nm, keep) -> float:
        return sum(_f(r.get("orders")) * (_m(eco, r["nm_id"]) or 0) for r in rows_nm if keep(r["nm_id"]))

    def control(a0, b1) -> set:
        """Склейки с рекламой, которые в окне [a0, b1] не меняли (ни кнопкой, ни вручную)."""
        touched = set()
        for r in c.execute("""SELECT p.nm_id, p.advert_id FROM ad_proposals p WHERE p.account_id=%s AND p.status='applied'
                              AND (p.decided_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s""", (shop, a0, b1)):
            for n in ([r["nm_id"]] if r["nm_id"] else list((camps.get(r["advert_id"]) or {}).get("nms") or [])):
                touched.add(imt.get(n, n))
        for r in c.execute("""SELECT DISTINCT field FROM card_changes WHERE account_id=%s AND kind IN ('ad_bid','ad_status') AND field LIKE 'ad:%%'
                              AND (detected_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %s AND %s""", (shop, a0, b1)):
            try:
                for n in (camps.get(int(r["field"][3:])) or {}).get("nms") or []:
                    touched.add(imt.get(n, n))
            except ValueError:
                pass
        adv = {imt.get(n, n) for cp in camps.values() for n in cp["nms"]}
        return adv - touched

    n = 0
    for p in rows:
        d = p["decided_at"].astimezone(timezone(timedelta(hours=3))).date()
        L = min(MEASURE_MAX_DAYS, (y - d).days)
        if L < MEASURE_MIN_DAYS:
            continue
        adv = [p["nm_id"]] if p["nm_id"] else list((camps.get(p["advert_id"]) or {}).get("nms") or [])
        nms = sorted({x for a in adv for x in by_imt.get(imt.get(a, a), [a])})           
        if not nms or all(_m(eco, x) is None for x in nms):
            continue
        wins = {"before": (d - timedelta(days=L), d - timedelta(days=1)), "after": (d + timedelta(days=1), d + timedelta(days=L))}
        key = (wins["before"][0], wins["after"][1])
        if key not in ctrl_cache:
            ctl = control(*key) - {imt.get(x, x) for x in nms}
            gr = {}
            for tag, (a, b) in wins.items():
                gr[tag] = gross(nm_day.cached(c, shop, a, b), lambda x: imt.get(x, x) in ctl)
            ctrl_cache[key] = (gr["after"] / gr["before"]) if gr["before"] > 0 and gr["after"] > 0 and len(ctl) >= 3 else 1.0
        kc = max(0.5, min(2.0, ctrl_cache[key]))                       
        res = {}
        for tag, (a, b) in wins.items():
            rows_nm = nm_day.cached(c, shop, a, b, nms)
            orders = sum(_f(r.get("orders")) for r in rows_nm)
            st = _ad_stats(c, shop, a, b)
            spend = sum(v["spend"] for (aid, nm), v in st.items() if nm in nms)
            ad_orders = sum(v["orders"] for (aid, nm), v in st.items() if nm in nms)
            ad_carts = sum(v["carts"] for (aid, nm), v in st.items() if nm in nms)
            carts = sum(_f(r.get("f_cart")) for r in rows_nm)              
            g = gross(rows_nm, lambda x: True)
            res[tag] = {"orders": int(orders), "ad_orders": int(ad_orders), "carts": int(carts), "ad_carts": int(ad_carts),
                        "spend": round(spend), "profit": round(g - spend * k_ad), "gross": round(g), "days": L}
        res["after"]["ctrl_k"] = round(kc, 3)
        
        delta = ((res["after"]["gross"] - res["before"]["gross"] * kc) - (res["after"]["spend"] - res["before"]["spend"]) * k_ad) * 7 / L
        thr = max(100, 0.05 * abs(res["before"]["profit"]) * 7 / L)
        verdict = "better" if delta > thr else "worse" if delta < -thr else "same"
        c.execute("""INSERT INTO ad_outcomes(proposal_id,account_id,before,after,delta_profit,verdict,days,final) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (proposal_id) DO UPDATE SET before=EXCLUDED.before, after=EXCLUDED.after, delta_profit=EXCLUDED.delta_profit,
                       verdict=EXCLUDED.verdict, days=EXCLUDED.days, final=EXCLUDED.final, measured_at=now()""",
                  (p["id"], shop, json.dumps(res["before"]), json.dumps(res["after"]), round(delta), verdict, L, L >= MEASURE_MAX_DAYS))
        n += 1
    c.commit()
    _learn(c, shop)
    return n


def _learn(c, shop: int):
    """Итоги за 90 дней по каждому виду действия → шаг ставки магазина: вредило — мягче, помогало — смелее (в пределах настройки)."""
    cfg = settings(c, shop)
    base = {"bid_down": _f(cfg["max_step"]) / 100, "bid_up": 0.1, "kw_bid_down": _f(cfg["max_step"]) / 100, "kw_bid_up": 0.1}
    agg: dict = defaultdict(lambda: [0, 0, 0.0])
    for r in c.execute("""SELECT p.kind, p.params, o.verdict, o.delta_profit FROM ad_outcomes o JOIN ad_proposals p ON p.id=o.proposal_id
                          WHERE o.account_id=%s AND o.measured_at > now() - interval '90 days'""", (shop,)):
        a = agg[_action_key(r["kind"], r["params"])]
        a[0] += 1; a[1] += r["verdict"] == "better"; a[2] += _f(r["delta_profit"])
    for act, (n, wins, tot) in agg.items():
        avg = tot / n
        step = None
        if act in base:
            step = base[act]
            if n >= 3 and avg < 0:
                step = max(0.05, base[act] * 0.5)
            elif n >= 3 and wins / n >= 0.6:
                step = min(0.5, base[act] * 1.25)
        c.execute("""INSERT INTO ad_learn(account_id,action,n,wins,avg_delta,step,updated_at) VALUES (%s,%s,%s,%s,%s,%s,now())
                     ON CONFLICT (account_id,action) DO UPDATE SET n=EXCLUDED.n, wins=EXCLUDED.wins, avg_delta=EXCLUDED.avg_delta,
                       step=EXCLUDED.step, updated_at=now()""", (shop, act, n, wins, round(avg), step))
    c.commit()


def run(c, shop: int, note: bool = False, slow: bool = False) -> dict:
    """Разбор магазина: итоги прошлых действий → (утром) рекомендованные ставки WB → предложения → (утром) пояснение нейросети →
    уведомление о новых."""
    for fn in ((measure, refresh_reco, growth_jam) if slow else (measure,)):
        try:
            fn(c, shop)
        except Exception:  
            c.rollback()
    eco = economics(c, shop)
    res = save(c, shop, build(c, shop, eco=eco))
    try:
        state(c, shop, eco, with_balance=slow)
    except Exception:  
        c.rollback()
    if note and res["total"]:
        try:
            _note(c, shop, res["batch_at"])
        except Exception:  
            c.rollback()
    if res["new"] and settings(c, shop).get("notify") and actions.block(c, shop, "ads")["enabled"]:
        eff = sum(p["effect_week"] or 0 for p in res["new"])
        top = sorted(res["new"], key=lambda p: -p["priority"])[:3]
        c.execute("""INSERT INTO news_events(account_id,kind,nm_id,data,ref) VALUES (%s,'ads',NULL,%s,%s) ON CONFLICT DO NOTHING""",
                  (shop, json.dumps({"n": len(res["new"]), "effect": round(eff), "top": [label(p) for p in top]}, ensure_ascii=False),
                   f"ads:{shop}:{res['batch_at'].isoformat()}"))
        c.commit()
    return {"total": res["total"], "new": len(res["new"])}



NAMES = ("алена", "алёна", "валерия", "лера", "ия", "наташа", "наталья", "кристина", "женя", "евгения", "евгений", "аня", "анна", "катя",
         "екатерина", "маша", "мария", "оля", "ольга", "настя", "анастасия", "юля", "юлия", "даша", "дарья", "света", "светлана", "лена", "елена",
         "таня", "татьяна", "ира", "ирина", "вика", "виктория", "полина", "алина", "ксюша", "ксения", "карина", "диана", "марина", "вера",
         "саша", "александр", "александра", "дима", "дмитрий", "сергей", "андрей", "максим", "макс", "иван", "никита", "артем", "артём", "денис",
         "олег", "павел", "кирилл", "роман", "михаил", "миша", "антон", "игорь", "илья", "влад", "владислав", "алексей", "леша", "лёша")


def manager_of(name: str, extra: tuple = ()) -> str | None:
    """Менеджер по названию кампании: имя отдельным словом (свой список — настройка «managers», через запятую)."""
    import re
    words = re.findall(r"[a-zа-яё]+", (name or "").lower())
    for nm in tuple(x.strip().lower() for x in extra if x.strip()) + NAMES:
        if nm in words:
            return nm.capitalize()
    return None


def summary(c, shop: int, eco: dict, days: int = 30) -> dict:
    """Итоги рекламы за days дней по типам и менеджерам (расход весь, вкл. бонусы; прибыль — как в предложениях), реклама без себестоимости."""
    cfg = settings(c, shop)
    imt = imt_map(c, shop)
    y = today_msk()
    st = _ad_stats(c, shop, y - timedelta(days=days - 1), y)
    st7 = _ad_stats(c, shop, y - timedelta(days=6), y)
    camps = campaigns(c, shop, (4, 7, 9, 11))
    extra = tuple(str(cfg.get("managers") or "").split(","))
    by_t, by_m = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
    for aid, cp in camps.items():
        gs = group_stats(st, aid, imt, eco, eco["k_ad"])
        if not gs or not any(g["spend"] for g in gs.values()):
            continue
        mgr = manager_of(cp["name"], extra) or "без имени в названии"
        for key, agg in ((ctype(cp), by_t), (mgr, by_m)):
            a = agg[key]
            a["campaigns"] += 1
            for g in gs.values():
                a["spend"] += g["spend"]; a["orders"] += g["orders"]
                if g["known"]:
                    a["profit"] += g["profit"]; a["spend_known"] += g["spend"]
    rows = lambda agg: sorted(({"key": k, **{x: round(v) for x, v in a.items()}, "roi": round(a["profit"] / a["spend_known"], 3) if a["spend_known"] else None}  
                               for k, a in agg.items()), key=lambda r: -r["spend"])
    nocost = defaultdict(float)
    for (a, n), v in st7.items():
        if v["spend"] and _m(eco, n) is None:
            nocost[n] += v["spend"]
    vc = {r["nm_id"]: r["vendor_code"] for r in c.execute("SELECT nm_id, vendor_code FROM nomenclature WHERE account_id=%s AND nm_id = ANY(%s)",
                                                         (shop, list(nocost)))} if nocost else {}
    upd = {r["t"]: _f(r["s"]) for r in c.execute("""SELECT data->>'paymentType' t, sum((data->>'updSum')::numeric) s FROM raw_rows
                                                   WHERE account_id=%s AND source='ad_upd' AND row_date >= %s GROUP BY 1""", (shop, y - timedelta(days=13)))}
    return {"days": days, "types": [{**r, "title": TYPES.get(r["key"], r["key"])} for r in rows(by_t)], "managers": rows(by_m),
            "nocost": {"spend_7d": round(sum(nocost.values())), "n": len(nocost),
                       "top": [{"nm_id": n, "vc": vc.get(n), "spend_7d": round(v)} for n, v in sorted(nocost.items(), key=lambda x: -x[1])[:15]]},
            "upd_14d": {k: round(v) for k, v in upd.items()}}


def state(c, shop: int, eco: dict, with_balance: bool = False):
    """Сводка и (утром) баланс с бонусами WB → ad_state."""
    sm = summary(c, shop, eco)
    c.execute("""INSERT INTO ad_state(account_id, summary, summary_at) VALUES (%s, %s, now())
                 ON CONFLICT (account_id) DO UPDATE SET summary=EXCLUDED.summary, summary_at=now()""",
              (shop, json.dumps(sm, ensure_ascii=False, default=str)))
    c.commit()
    if with_balance:
        b = balance(c, shop)
        if isinstance(b, dict):
            c.execute("UPDATE ad_state SET balance=%s, balance_at=now() WHERE account_id=%s", (json.dumps(b, ensure_ascii=False, default=str), shop))
            c.commit()


def label(p: dict) -> str:
    """Короткая строка предложения: что и где."""
    t = KIND_T.get(p["kind"], p["kind"])
    where = (f"кампания {p['advert_id']}" if p.get("advert_id") else "новая кампания") + (f", арт. {p['nm_id']}" if p.get("nm_id") else "")\
        + (f", «{p['query']}»" if p.get("query") else "")
    b, a = p["params"]["before"], p["params"]["after"]
    if p["kind"] == "bid":
        t += ": " + ", ".join(f"{PLACE_T.get(pl, pl)} {b[pl] / 100:g} → {a[pl] / 100:g} ₽" for pl in a)
    elif p["kind"] == "kw_bid":
        t += f": {b} → {a} ₽"
    elif p["kind"] == "deposit":
        t += f": {_rub(a['sum'])}"
    return f"{t} ({where})"



NOTE_RULES = """Ты помогаешь селлеру Wildberries управлять рекламой ради прибыли. Тебе дают предложения, которые посчитал сервис по правилам,
с цифрами, и итоги прошлых действий в этом магазине. Напиши короткое пояснение (до 1200 знаков): что главное сегодня в рекламе, с чего
начать (2-4 пункта по приоритету), о чём не забыть. Предложения с пометкой роста (товар хорошо продаётся без рекламы) объясни
отдельно: где товар не в топе выдачи по запросам с заказами и почему недорогая реклама может дать больше продаж. Если есть итоги прошлых действий - скажи коротко, что в этом магазине уже сработало,
а что нет, и учти это в советах. Не советуй возвращать исключённые ключи и минус-фразы, если в данных нет их истории с корзинами
или заказами: дорогие ключи без корзин и заказов возвращать нет смысла. Цифры бери только из данных, ничего не придумывай. Ничего не обещай. Пиши просто, по-русски, без
вступлений и без таблиц. Напомни, что изменения применяет сам пользователь кнопкой «Применить», а пополнение бюджета и создание кампании -
с двойным подтверждением."""


def _note(c, shop: int, batch_at):
    from . import aireport
    key = aireport.shop_key(c, shop)
    if not key:
        return
    rows = c.execute("SELECT kind, advert_id, nm_id, query, params, reason, effect_week, priority FROM ad_proposals WHERE account_id=%s AND status='new' "
                     "ORDER BY priority DESC, effect_week DESC NULLS LAST LIMIT 40", (shop,)).fetchall()
    data = {"предложения": [{"что": label(dict(r)), "почему": r["reason"], "эффект_руб_в_неделю": r["effect_week"]} for r in rows],
            "итоги_прошлых_действий_за_90_дней": [
                {"действие": r["action"], "проверено": r["n"], "стало_лучше": r["wins"], "средний_эффект_руб_в_неделю": r["avg_delta"]}
                for r in learned(c, shop).values()]}
    text = aireport.complete(key, NOTE_RULES, json.dumps(data, ensure_ascii=False, default=str), 900)
    c.execute("INSERT INTO ad_notes(account_id,batch_at,body,model) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
              (shop, batch_at, text, aireport.model_name(key)))
    c.commit()



class Stale(actions.ActionDenied):
    pass


def _fresh(c, shop: int, aid: int) -> dict:
    """Кампания прямо сейчас из WB (ключом на чтение) + обновляем её в базе."""
    info = (_wb(c, shop).call("advert", "/api/advert/v2/adverts", params={"ids": str(aid)}) or {}).get("adverts") or []
    if not info:
        raise Stale("Кампания не найдена в WB (удалена или завершена)")
    i = info[0]
    row = c.execute("SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts' AND row_key=%s", (shop, str(aid))).fetchone()
    d = {**((row or {}).get("data") or {"advertId": aid, "type": 9}), "status": i.get("status"), "info": i}
    c.execute("""INSERT INTO raw_rows(account_id,source,row_key,row_date,data) VALUES (%s,'adverts',%s,NULL,%s)
                 ON CONFLICT (account_id,source,row_key) DO UPDATE SET data=EXCLUDED.data, updated_at=now()""",
              (shop, str(aid), json.dumps(d, ensure_ascii=False)))
    c.commit()
    return campaigns_from(d)


def _minus_now(c, shop: int, aid: int, nm: int) -> list[str]:
    r = _wb(c, shop).call("advert", "/adv/v0/normquery/get-minus", "POST", body={"items": [{"advert_id": aid, "nm_id": nm}]}) or {}
    return [q for it in r.get("items") or [] for q in it.get("norm_queries") or []]


def _kw_bid_now(c, shop: int, aid: int, nm: int, q: str) -> int | None:
    r = _wb(c, shop).call("advert", "/adv/v0/normquery/get-bids", "POST", body={"items": [{"advert_id": aid, "nm_id": nm}]}) or {}
    return next((int(b["bid"]) for b in r.get("bids") or [] if b.get("norm_query") == q), None)


def execute(c, shop: int, p: dict, uid: int, force: bool = False) -> dict:
    """Отправить одно действие в WB. p — строка ad_proposals. Проверяет текущее состояние; расхождение — Stale."""
    why = actions.can_write(c, shop, "ads")
    if why:
        raise actions.ActionDenied(why)
    aid, nm, kind = p["advert_id"], p["nm_id"], p["kind"]
    before, after = p["params"]["before"], p["params"]["after"]
    if kind in MONEY_KINDS and not force:
        raise actions.ActionDenied("BIG_STEP: " + ("пополнение бюджета — это деньги" if kind == "deposit" else "создание новой кампании")
                                   + ": подтвердите ещё раз")
    tgt = (f"кампания {aid}" if aid else "новая кампания") + (f", арт. {nm}" if nm else "") + (f", «{p['query']}»" if p.get("query") else "")\
        + f" (предложение №{p['id']})"

    def w(method, path, body=None, params=None, b=None):
        return actions.wb_write(c, shop, "ads", method, "advert", path, body, params=params, uid=uid, target=tgt, before=b)

    if kind == "create":
        test = (p.get("query") or "").startswith("test:")
        same = [campaigns_from(r["data"]) for r in c.execute(
            """SELECT data FROM raw_rows WHERE account_id=%s AND source='adverts' AND (data->>'status')::int IN (4,9,11)
               AND data->'info'->'nm_settings' @> %s::jsonb""", (shop, json.dumps([{"nm_id": nm}])))]
        if (not test and same) or (test and any(ctype(x) == p["query"][5:] for x in same)):
            raise Stale("У артикула уже есть такая кампания")
        body = {"name": after["name"], "nms": after["nms"], "bid_type": after["bid_type"], "payment_type": after["payment_type"]}
        if after.get("placement_types") and after["bid_type"] == "manual":
            body["placement_types"] = after["placement_types"]
        new_id = w("POST", "/adv/v2/seacat/save-ad", body)
        if isinstance(new_id, int):
            c.execute("UPDATE ad_proposals SET advert_id=%s WHERE id=%s", (new_id, p["id"]))
            try:
                _fresh(c, shop, new_id)
            except Exception:  
                c.rollback()
        return {"ok": True, "advert_id": new_id}
    cur = _fresh(c, shop, aid)
    if kind in ("pause", "start"):
        ok = (9,) if kind == "pause" else (11, 4)
        if cur["status"] not in ok:
            raise Stale(f"Кампания уже {STATUS_T.get(cur['status'], cur['status'])} — ничего не меняем")
        w("GET", "/adv/v0/pause" if kind == "pause" else "/adv/v0/start", params={"id": aid}, b={"status": cur["status"]})
    elif kind == "deposit":
        b = budgets(c, shop, [aid]).get(aid)
        if before and b is not None and b > int((before or {}).get("budget") or 0) + 50:
            raise Stale(f"Бюджет уже пополнили: сейчас {_rub(b)}")
        if int(after["sum"]) > max(MIN_DEPOSIT, _f(settings(c, shop).get("deposit_max") or 5000)) * 1.0001:
            raise actions.ActionDenied("Сумма больше лимита пополнения из настроек блока")
        w("POST", "/adv/v1/budget/deposit", {"sum": int(after["sum"]), "type": int(after["type"]), "return": True}, params={"id": aid}, b={"budget": b})
    elif kind == "nm_remove":
        if nm not in cur["nms"]:
            raise Stale("Артикула уже нет в кампании")
        if len(cur["nms"]) <= 1:
            raise Stale("В кампании один артикул — убрать его нельзя, поставьте кампанию на паузу")
        w("PATCH", "/adv/v0/auction/nms", {"nms": [{"advert_id": aid, "nms": {"delete": [nm]}}]}, b={"nms": list(cur["nms"])})
    elif kind == "bid":
        bids = cur["nms"].get(nm) or {}
        now = {"combined": bids.get("search") or bids.get("recommendations")} if cur["bid_type"] == "unified" else {pl: bids.get(pl) for pl in after}
        if any(int(now.get(pl) or 0) != int(v) for pl, v in (before or {}).items()):
            raise Stale("Ставка в WB уже другая: " + ", ".join(f"{PLACE_T.get(pl, pl)} {int(now.get(pl) or 0) / 100:g} ₽" for pl in after))
        big = [pl for pl, v in after.items() if before.get(pl) and abs(v - before[pl]) / before[pl] > _f(settings(c, shop)["max_step"]) / 100 + 1e-9]
        if big and not force:
            raise actions.ActionDenied("BIG_STEP: изменение ставки больше допустимого шага — подтвердите ещё раз")
        w("PATCH", "/api/advert/v1/bids", {"bids": [{"advert_id": aid, "nm_bids": [{"nm_id": nm, "bid_kopecks": int(v), "placement": pl}
                                                                                    for pl, v in after.items()]}]}, b=before)
    elif kind == "kw_bid":
        if cur["bid_type"] != "manual" or cur["payment"] != "cpm":
            raise Stale("Ставки на ключи — только у кампаний с ручной ставкой и оплатой за показы")
        now = _kw_bid_now(c, shop, aid, nm, p["query"])
        if now is not None and before and int(now) != int(before):
            raise Stale(f"Ставка на ключ в WB уже другая: {now} ₽")
        if before and abs(int(after) - int(before)) / int(before) > _f(settings(c, shop)["max_step"]) / 100 + 1e-9 and not force:
            raise actions.ActionDenied("BIG_STEP: изменение ставки больше допустимого шага — подтвердите ещё раз")
        w("POST", "/adv/v0/normquery/bids", {"bids": [{"advert_id": aid, "nm_id": nm, "norm_query": p["query"], "bid": int(after)}]}, b={"bid": now})
        c.execute("""UPDATE wb_ad_kw_lists SET bid=%s WHERE account_id=%s AND advert_id=%s AND nm_id=%s AND query=%s AND state='active'""",
                  (int(after), shop, aid, nm, p["query"]))
    elif kind == "placements":
        if cur["bid_type"] != "manual" or cur["payment"] != "cpm":
            raise Stale("Места размещения меняются только у кампаний с ручной ставкой и оплатой за показы")
        w("PUT", "/adv/v0/auction/placements", {"placements": [{"advert_id": aid, "placements": {"search": bool(after["search"]),
                                                                                                "recommendations": bool(after["recommendations"])}}]},
          b=cur["placements"])
    elif kind in ("kw_minus", "kw_unminus"):
        lst = _minus_now(c, shop, aid, nm)
        q = p["query"]
        if kind == "kw_minus":
            if q in lst:
                raise Stale("Ключ уже в минус-фразах")
            new = lst + [q]
        else:
            if q not in lst:
                raise Stale("Ключа уже нет в минус-фразах")
            new = [x for x in lst if x != q]
        if len(new) > 1000:
            raise actions.ActionDenied("В минус-фразах уже 1000 ключей — больше WB не принимает")
        w("POST", "/adv/v0/normquery/set-minus", {"advert_id": aid, "nm_id": nm, "norm_queries": new}, b={"minus": len(lst)})
        if kind == "kw_minus":
            c.execute("""INSERT INTO wb_ad_kw_lists(account_id,advert_id,nm_id,query,state) VALUES (%s,%s,%s,%s,'minus') ON CONFLICT DO NOTHING""",
                      (shop, aid, nm, q))
        else:
            c.execute("DELETE FROM wb_ad_kw_lists WHERE account_id=%s AND advert_id=%s AND nm_id=%s AND query=%s AND state='minus'", (shop, aid, nm, q))
    else:
        raise actions.ActionDenied(f"Неизвестное действие {kind}")
    try:
        _fresh(c, shop, aid)            
    except Exception:  
        c.rollback()
    return {"ok": True}


def decide(c, shop: int, pid: int, uid: int, apply: bool, force: bool = False) -> dict:
    p = c.execute("SELECT * FROM ad_proposals WHERE id=%s AND account_id=%s", (pid, shop)).fetchone()
    if not p:
        raise actions.ActionDenied("Предложение не найдено")
    if p["status"] != "new":
        raise actions.ActionDenied("Предложение уже " + {"applied": "применено", "rejected": "отклонено", "expired": "устарело", "stale": "устарело",
                                                        "error": "с ошибкой"}.get(p["status"], p["status"]))
    if not apply:
        c.execute("UPDATE ad_proposals SET status='rejected', decided_by=%s, decided_at=now() WHERE id=%s", (uid, pid))
        c.commit()
        return {"status": "rejected"}
    try:
        execute(c, shop, p, uid, force)
    except Stale as e:
        c.execute("UPDATE ad_proposals SET status='stale', decided_by=%s, decided_at=now(), error=%s WHERE id=%s", (uid, str(e)[:300], pid))
        c.commit()
        return {"status": "stale", "error": str(e)}
    except actions.ActionDenied as e:
        if str(e).startswith("BIG_STEP"):
            return {"status": "confirm", "error": str(e).split(": ", 1)[1]}
        if any(s in str(e) for s in ("WB вернул", "WB не принял", "WB:")):
            c.execute("UPDATE ad_proposals SET status='error', decided_by=%s, decided_at=now(), error=%s WHERE id=%s", (uid, str(e)[:300], pid))
            c.commit()
            return {"status": "error", "error": str(e)}
        raise
    c.execute("UPDATE ad_proposals SET status='applied', decided_by=%s, decided_at=now() WHERE id=%s", (uid, pid))
    c.commit()
    return {"status": "applied"}


def manual(c, shop: int, uid: int, kind: str, advert_id: int, nm_id: int | None, query: str | None, after) -> dict:
    """Действие пользователя из списка кампаний (не предложение ИИ): записываем как предложение source='user' и сразу применяем
    (подтверждения уже были на сайте)."""
    if kind not in KIND_T or kind in ("create",):
        raise actions.ActionDenied("Это действие из списка кампаний недоступно")
    cur = _fresh(c, shop, advert_id)
    before = None
    if kind == "bid":
        bids = cur["nms"].get(nm_id) or {}
        before = ({"combined": bids.get("search") or bids.get("recommendations")} if cur["bid_type"] == "unified"
                  else {pl: bids.get(pl) for pl in after})
        after = {pl: int(round(float(v) * 100)) for pl, v in after.items()}          
    elif kind == "kw_bid":
        before, after = _kw_bid_now(c, shop, advert_id, nm_id, query), int(after)
    elif kind == "placements":
        before = cur["placements"]
    elif kind in ("pause", "start"):
        before, after = cur["status"], 11 if kind == "pause" else 9
    elif kind == "deposit":
        before = {"budget": budgets(c, shop, [advert_id]).get(advert_id)}
        after = {"sum": int(after["sum"]), "type": int(after.get("type") or 0)}
    p = _p(kind, advert_id, nm_id, query, before, after, reason="Вручную из списка кампаний")
    pid = c.execute("""INSERT INTO ad_proposals(account_id,kind,advert_id,nm_id,query,params,reason,source,dkey,priority)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'user',%s,0) RETURNING id""",
                    (shop, kind, advert_id, nm_id, query, json.dumps(p["params"]), p["reason"], p["dkey"] + f"|user|{datetime.now().timestamp()}")).fetchone()["id"]
    c.commit()
    return {"id": pid, **decide(c, shop, pid, uid, True, force=True)}

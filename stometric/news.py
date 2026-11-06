"""Self-hosted application component."""

import html
import json

from . import auth

KINDS = [  
    ("spp", "СПП / соинвест (цена покупателя)", "💸 Цена для покупателя изменилась"),
    ("price", "Изменение цены товара (любым пользователем)", "🏷 Цена товара изменилась"),
    ("ads", "Реклама: новые предложения ИИ", "📢 Реклама: новые предложения"),
    ("volume", "Объём товара для логистики (замер WB)", "📏 Изменился объём товара для логистики WB"),
    ("entry", "Точки входа: сильные просадки и рост по артикулам", "🚪 Точки входа: заметные изменения"),
]
KIND_KEYS = {k for k, _, _ in KINDS}
BATCH = 5


def _rub(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ") + " ₽"


def sync_changes(c) -> int:
    """Новые изменения цены из журнала карточек → события ленты (ref не даёт задвоить)."""
    r = c.execute("SELECT value FROM app_settings WHERE key='news_cc_last'").fetchone()
    last = int(r["value"]) if r else None
    if last is None:   
        last = c.execute("SELECT coalesce(max(id),0) m FROM card_changes").fetchone()["m"]
    rows = c.execute("""SELECT ch.*, coalesce(n.vendor_code, op.offer_id) vc, coalesce(n.title, op.name) title
                        FROM card_changes ch LEFT JOIN nomenclature n ON n.account_id=ch.account_id AND n.nm_id=ch.nm_id
                        LEFT JOIN oz_products op ON op.account_id=ch.account_id AND op.sku=ch.nm_id
                        WHERE ch.id > %s ORDER BY ch.id LIMIT 5000""", (last,)).fetchall()
    n = 0
    from .exclusions import excluded
    for x in rows:
        last = x["id"]
        if x["kind"] != "price" or x["nm_id"] in excluded(c, x["account_id"]):     
            continue
        o, w = x["old_value"] or {}, x["new_value"] or {}
        if not o.get("final") or not w.get("final") or o["final"] == w["final"]:
            continue
        what = "Цена с акциями Ozon" if x["field"] == "marketing_price" else "Цена"
        c.execute("""INSERT INTO news_events(account_id,kind,nm_id,created_at,data,ref) VALUES (%s,'price',%s,%s,%s,%s)
                     ON CONFLICT DO NOTHING""",
                  (x["account_id"], x["nm_id"], x["detected_at"],
                   json.dumps({"vc": x["vc"], "title": x["title"], "what": what, "old": o["final"], "new": w["final"],
                               "old_base": o.get("price"), "new_base": w.get("price")}, ensure_ascii=False), f"card_changes:{x['id']}"))
        n += 1
    c.execute("""INSERT INTO app_settings(key,value) VALUES ('news_cc_last',%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""",
              (json.dumps(last),))
    c.commit()
    return n


SPP_LAST, SPP_STEP = 10, 4


def sync_spp(c) -> int:
    """СПП WB по заказам → события «spp». Первый заказ артикула — только запоминаем (прошлое в ленту не тащим)."""
    rows = c.execute("""
        WITH o AS (SELECT o.account_id, o.nm_id, o.order_dt, o.spp, o.price_with_disc,
                          row_number() OVER (PARTITION BY o.account_id, o.nm_id ORDER BY o.order_dt DESC) rn
                   FROM orders o JOIN accounts a ON a.id=o.account_id AND a.marketplace='wb' AND a.is_active
                   WHERE o.order_dt > (now() AT TIME ZONE 'Europe/Moscow') - interval '48 hours' AND o.spp IS NOT NULL)
        SELECT o.account_id, o.nm_id, array_agg(o.spp ORDER BY o.spp) spps, max(o.order_dt) last_dt,
               (array_agg(o.price_with_disc ORDER BY o.order_dt DESC))[1] price,
               s.spp old_spp, s.price old_price, s.last_order, n.vendor_code vc, n.title
        FROM o LEFT JOIN spp_state s ON s.account_id=o.account_id AND s.nm_id=o.nm_id
        LEFT JOIN nomenclature n ON n.account_id=o.account_id AND n.nm_id=o.nm_id
        WHERE o.rn <= %s GROUP BY o.account_id, o.nm_id, s.spp, s.price, s.last_order, n.vendor_code, n.title
        HAVING s.last_order IS NULL OR max(o.order_dt) > s.last_order""", (SPP_LAST,)).fetchall()
    n = 0
    from .exclusions import excluded
    from .showcase import fresh_accounts
    sc = fresh_accounts(c)              
    for r in rows:
        if r["account_id"] in sc or r["nm_id"] in excluded(c, r["account_id"]):
            continue
        spps = [float(x) for x in r["spps"]]
        import statistics
        base = float(statistics.median(spps))
        price = float(r["price"]) if r["price"] is not None else None
        old, keep = r["old_spp"], None
        if r["last_order"] is not None and old is not None and len(spps) >= 3 and abs(base - float(old)) >= SPP_STEP:
            old, op = float(old), float(r["old_price"]) if r["old_price"] is not None else None
            d = {"vc": r["vc"], "title": r["title"], "old_pct": old, "new_pct": base, "price": price, "src": "orders"}
            if op and price and abs(op - price) >= 1:
                d.update(price_changed=True, old_price=op, new_price=price)
            if price:
                d.update(old_buyer=round((op or price) * (1 - old / 100)), new_buyer=round(price * (1 - base / 100)))
            c.execute("""INSERT INTO news_events(account_id,kind,nm_id,data,ref) VALUES (%s,'spp',%s,%s,%s) ON CONFLICT DO NOTHING""",
                      (r["account_id"], r["nm_id"], json.dumps(d, ensure_ascii=False), f"spp:{r['account_id']}:{r['nm_id']}:{r['last_dt']}"))
            n += 1
        elif old is not None and r["last_order"] is not None:
            keep = float(old)        
        c.execute("""INSERT INTO spp_state(account_id,nm_id,spp,price,last_order,updated_at) VALUES (%s,%s,%s,%s,%s,now())
                     ON CONFLICT (account_id,nm_id) DO UPDATE SET spp=EXCLUDED.spp, price=EXCLUDED.price, last_order=EXCLUDED.last_order,
                       updated_at=now()""", (r["account_id"], r["nm_id"], keep if keep is not None else base, price, r["last_dt"]))
    c.commit()
    return n


def _info(x: dict | None, price: float | None, what: str) -> str:
    """Self-hosted application component."""
    if not x:
        return ""
    s = f"\n   Категория: {html.escape(x['subject'])}" if x.get("subject") else ""
    m = x.get("mrc")
    if m:
        s += f"\n   МРЦ: {_rub(m)}"
        if price is not None and price < m:
            s += f" — ⚠️ {what} ниже МРЦ на {_rub(m - price)}"
    return s


def line(kind: str, d: dict, nm, x: dict | None = None) -> str:
    """Строка события (HTML для Telegram; на сайте — тот же текст без тегов). x — категория и МРЦ товара (mrc_list.lookup)."""
    name = html.escape(str(d.get("vc") or nm))
    if kind == "price":
        o, w = float(d["old"]), float(d["new"])
        pct = (w - o) / o * 100 if o else 0
        return (f"{'📈' if w > o else '📉'} <code>{name}</code>: {html.escape(d.get('what') or 'Цена')} {_rub(o)} → {_rub(w)} "
                f"({'+' if w > o else '−'}{_rub(abs(w - o))}, {'+' if pct > 0 else '−'}{abs(pct):.1f} %)".replace(".", ",")
                + _info(x, w, "цена"))
    if kind == "spp":
        a, b = d.get("old_pct"), d.get("new_pct")
        s = (f"{'📈' if (b or 0) > (a or 0) else '📉'} <code>{name}</code>: СПП {a:g} % → {b:g} %".replace(".", ",")
             + (" (по заказам)" if d.get("src") == "orders" else " (витрина WB)" if d.get("src") == "showcase" else ""))
        if d.get("price_changed"):
            s += f"\n   Вы изменили цену: {_rub(d['old_price'])} → {_rub(d['new_price'])}"
        elif d.get("price"):
            s += f"\n   При вашей цене {_rub(d['price'])}"
        if d.get("old_buyer") and d.get("new_buyer"):
            s += (f"\n   Цена на витрине {_rub(d['new_buyer'])} вместо {_rub(d['old_buyer'])}" if d.get("src") == "showcase"
                  else f"\n   Покупатель платит ~{_rub(d['new_buyer'])} вместо ~{_rub(d['old_buyer'])}")
        buyer = d.get("new_buyer")
        return s + _info(x, float(buyer) if buyer else None, "витрина" if d.get("src") == "showcase" else "цена покупателя")
    if kind == "volume":                 
        o, w = float(d["old"]), float(d["new"])
        pct = (w - o) / o * 100 if o else 0
        f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")  
        subj = html.escape(d.get("subject") or (x or {}).get("subject") or "")
        s = (f"📦 <code>{name}</code> ({nm}){' — ' + subj if subj else ''}\n"
             f"{'🟢' if w < o else '🔴'} {f(o)} → {f(w)} л ({'+' if w > o else '−'}{f(abs(w - o))} | {'+' if pct > 0 else '−'}{abs(pct):.1f} %)".replace(".", ",")
             + f" {'↓' if w < o else '↑'} логистика")
        cd = d.get("card")
        if cd:
            s += f"\n   В карточке: {cd['l']}×{cd['w']}×{cd['h']} см = {f(cd['liters'])} л"
            if w > cd["liters"] * 1.05:
                s += " — ⚠️ WB считает больше, чем в карточке: проверьте «Габариты упаковки» и «Замеры склада»"
        if d.get("old_w") is not None and d.get("new_w") is not None and d["old_w"] != d["new_w"]:
            s += f"\n   Вес: {f(d['old_w'])} → {f(d['new_w'])} кг"
        return s
    if kind == "entry":                  
        def one(x):
            return (f"<code>{html.escape(x['vendor_code'])}</code> · {html.escape(x['section'])} / {html.escape(x['point'])}: "
                    f"{x['clicks_avg']:.0f} → {x['clicks']} переходов ({'+' if x['change_pct'] > 0 else ''}{x['change_pct']} %)")
        dd = f"{d['day'][8:10]}.{d['day'][5:7]}"
        s = f"За {dd} против среднего за {d.get('base_days', 7)} дн."
        if d.get("drops"):
            s += f"\n📉 Просели ({d['drops_n']}):\n" + "\n".join("• " + one(x) for x in d["drops"])
        if d.get("rises"):
            s += f"\n📈 Выросли ({d['rises_n']}):\n" + "\n".join("• " + one(x) for x in d["rises"])
        if d.get("shop_points"):
            s += "\nПо магазину: " + "; ".join(f"{html.escape(x['point'])} {'+' if x['change_pct'] > 0 else ''}{x['change_pct']} %" for x in d["shop_points"])
        return s + "\nВсе изменения — «Действия по артикулам» и вкладка «Точки входа»."
    if kind == "ads":
        eff = f", оценка эффекта до +{_rub(d['effect'])} к прибыли в неделю" if d.get("effect") else ""
        return (f"{d.get('n', 0)} новых предложений по рекламе{eff}.\n" + "\n".join(f"• {html.escape(t)}" for t in d.get("top") or [])
                + "\nПроверить и применить: раздел «📢 Реклама» на сайте.")
    if kind == "seo":
        st = {"pending": "📝 отправлен на согласование", "approved": "✅ согласован и загружен в WB", "returned": "↩️ возвращён на доработку",
              "error": "⚠️ согласован, но WB вернул ошибку"}.get(d.get("state"), d.get("state"))
        return (f"<code>{name}</code>: SEO-текст {st} ({html.escape(d.get('who') or '')})"
                + (f", покрытие ключей {d['coverage']} %" if d.get("coverage") is not None and d.get("state") == "pending" else "")
                + (f"\n   {html.escape(d['comment'][:300])}" if d.get("comment") else ""))
    return f"<code>{name}</code>: {html.escape(json.dumps(d, ensure_ascii=False))[:200]}"


def feed(c, shop: int, kind: str | None = None, nm: int | None = None, before: int | None = None, limit: int = 100) -> dict:
    w, p = ["account_id=%(a)s"], {"a": shop, "l": limit}
    if kind:
        w.append("kind=%(k)s"); p["k"] = kind
    if nm:
        w.append("nm_id=%(n)s"); p["n"] = nm
    if before:
        w.append("id < %(b)s"); p["b"] = before
    rows = c.execute(f"SELECT id, kind, nm_id, created_at, data FROM news_events WHERE {' AND '.join(w)} ORDER BY id DESC LIMIT %(l)s", p).fetchall()
    import re
    from .mrc_list import lookup
    xs = lookup(c, {(shop, r["nm_id"]) for r in rows if r["nm_id"] and r["kind"] in ("price", "spp")})
    out = [{"id": r["id"], "kind": r["kind"], "nm_id": r["nm_id"], "at": r["created_at"], "vc": r["data"].get("vc"), "title": r["data"].get("title"),
            "text": re.sub(r"<[^>]+>", "", line(r["kind"], r["data"], r["nm_id"], xs.get((shop, r["nm_id"]))))} for r in rows]
    return {"rows": out, "kinds": [{"key": k, "title": t} for k, t, _ in KINDS], "more": len(rows) == limit}


def send_pending(c) -> int:
    """Неотправленные события → пачки в бот. Помечаем отправленными сразу (даже если получателей нет)."""
    from .bots import notify
    ev = c.execute("SELECT * FROM news_events WHERE NOT notified ORDER BY id LIMIT 2000").fetchall()
    if not ev:
        return 0
    groups: dict = {}
    for e in ev:
        groups.setdefault((e["account_id"], e["kind"]), []).append(e)
    subs = c.execute("""SELECT s.user_id, s.chat_id, s.kinds, s.muted_shops FROM notify_settings s JOIN users u ON u.id=s.user_id
                        WHERE s.chat_id IS NOT NULL AND u.is_active""").fetchall()
    head = {k: h for k, _, h in KINDS}
    from .mrc_list import lookup
    xs = lookup(c, {(e["account_id"], e["nm_id"]) for e in ev if e["nm_id"] and e["kind"] in ("price", "spp")})
    sent = 0
    for s in subs:
        u = c.execute("SELECT * FROM users WHERE id=%s", (s["user_id"],)).fetchone()
        shops = {x["id"]: x for x in auth.shops_for(c, u)}
        for (acc, kind), items in groups.items():
            if acc not in shops or acc in (s["muted_shops"] or []) or (s["kinds"] or {}).get(kind) is False:
                continue
            sh = shops[acc]
            txt = (f"<b>{head.get(kind, kind)} — {html.escape(sh['title'] or sh['name'])}</b>\n\n" +
                   "\n\n".join(line(kind, e["data"], e["nm_id"], xs.get((acc, e["nm_id"]))) for e in items[:BATCH]) +
                   (f"\n\n… и ещё {len(items) - BATCH} товаров" if len(items) > BATCH else "") + "\n\nВсё — в «Ленте новостей» на сайте.")
            try:
                if notify(c, s["user_id"], s["chat_id"], txt):
                    sent += 1
            except Exception:  
                pass
    c.execute("UPDATE news_events SET notified=true WHERE id = ANY(%s)", ([e["id"] for e in ev],))
    c.commit()
    return sent

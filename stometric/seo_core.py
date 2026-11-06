"""Self-hosted application component."""

import json
import re
import threading

from . import db, market

WORD = re.compile(r"[a-zа-я0-9]+")
COMPS = 8            
KW_PAGES = 4         
REC = 15             


def norm(text: str) -> str:
    return " ".join(WORD.findall((text or "").lower().replace("ё", "е")))


def has_phrase(text_norm: str, phrase: str) -> bool:
    """Полное вхождение: фраза целиком, слово в слово, в нормализованном тексте (регистр, ё/е и знаки препинания не важны)."""
    p = norm(phrase)
    return bool(p) and f" {p} " in f" {text_norm} "


def _stem(w: str) -> str:
    return w[:max(4, len(w) - 2)] if len(w) > 5 else w


def has_words(text_norm: str, phrase: str) -> bool:
    """Все слова фразы есть в тексте (с точностью до окончаний), но не обязательно подряд."""
    have = {_stem(w) for w in text_norm.split()}
    ws = [w for w in norm(phrase).split() if len(w) > 2]
    return bool(ws) and all(_stem(w) in have for w in ws)


def card(c, shop: int, nm: int) -> dict:
    r = c.execute("SELECT vendor_code, title, data FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone() or {}
    d = r.get("data") or {}
    return {"title": d.get("title") or r.get("title") or "", "description": d.get("description") or "", "subject": d.get("subjectName") or "",
            "brand": d.get("brand") or "", "vendor_code": r.get("vendor_code")}


def _own_queries(c, shop: int, nm: int, notes: list) -> dict:
    out = {}
    j = c.execute("""SELECT items, date_from, date_to FROM jam_cache WHERE account_id=%s AND nm_id=%s AND state='done'
                     ORDER BY fetched_at DESC LIMIT 1""", (shop, nm)).fetchone()
    if j and j["items"]:
        for i in j["items"]:              
            k = norm(i.get("text"))
            e = out.setdefault(k, {"phrase": i.get("text"), "freq": None, "opens": 0, "orders": 0, "pos": None})
            e["freq"] = max(e["freq"] or 0, i.get("frequency") or 0) or None
            e["opens"] += i.get("openCard") or 0
            e["orders"] += i.get("orders") or 0
            if e["pos"] is None or (i.get("avgPosition") or 10**6) < e["pos"]:
                e["pos"] = i.get("avgPosition")
        notes.append(f"Джем {j['date_from']:%d.%m}–{j['date_to']:%d.%m}: {len(out)} запросов артикула")
        return out
    from .cards_ai import _queries
    for q in _queries(c, shop, nm):
        out[norm(q["q"])] = {"phrase": q["q"], "freq": q["freq_month"], "opens": q["opens"], "orders": q["orders"], "pos": q["pos"]}
    notes.append(f"Джема нет — поисковые запросы WB за 14 дней: {len(out)}" if out else "Нет ни Джема, ни поисковых запросов WB по артикулу")
    return out


def _competitors(c, shop: int, nm: int, tok: str) -> list[dict]:
    mine = [{"id": int(r["comp_nm_id"]), "name": r["note"], "src": "наш список"} for r in
            c.execute("SELECT comp_nm_id, note FROM competitors WHERE account_id=%s AND nm_id=%s ORDER BY created_at", (shop, nm))]
    seen = {x["id"] for x in mine} | {nm}
    res = market.products(c, tok, {"similar": nm, "period": 30}, "proceeds,orders", ttl_h=24)
    sim = sorted(res.get("rows") or [], key=lambda r: -(r.get("proceeds") or 0))
    for r in sim:
        if len(mine) >= COMPS + 3:
            break
        if int(r["id"]) not in seen:
            seen.add(int(r["id"]))
            mine.append({"id": int(r["id"]), "name": r.get("name"), "proceeds": r.get("proceeds"), "src": "похожие WB"})
    return mine[:COMPS + 3]


def _comp_keys(tok: str, ids: list[int]) -> list[dict]:
    rows, low = [], None
    for _ in range(KW_PAGES):
        p = {"product_ids": ",".join(map(str, ids)), "period": 30, "ordering": "-frequency"}
        if len(ids) >= 4:
            p["percent_products__gte"] = 25          
        if low is not None:
            p["frequency__lte"] = low - 1
        r = market._call(tok, "get_external_analytics", schema_name="external.keywords.list", params=p, extra_fields="count_products,percent_products")
        page = (r or {}).get("rows") or []
        rows += page
        fr = [x.get("frequency") for x in page if x.get("frequency")]
        if len(page) < 20 or not fr:
            break
        low = min(fr)
    return rows


def _suggest(tok: str, phrase: str) -> list[tuple[str, int | None]]:
    r = market._call(tok, "get_external_analytics", schema_name="external.keywords.suggestions", params={"keyword": phrase})
    d = (r or {}).get("data") or {}
    out = {}
    pa = d.get("phrases_analyses")
    if isinstance(pa, dict):
        for k, v in pa.items():
            out[k] = (v or {}).get("wb_count") if isinstance(v, dict) else None
    elif isinstance(pa, list):
        for v in pa:
            if isinstance(v, dict) and (v.get("phrase") or v.get("name") or v.get("text")):
                out[v.get("phrase") or v.get("name") or v.get("text")] = v.get("wb_count") or v.get("frequency")
    for grp in d.get("collector") or []:
        for k, tails in (grp or {}).items():
            for p in [k, *(tails or [])]:
                out.setdefault(p, None)
    return list(out.items())


def collect(c, shop: int, nm: int) -> dict:
    notes, keys = [], {}

    def add(phrase, src, **kw):
        k = norm(phrase)
        if not k or len(k) < 3:
            return
        e = keys.setdefault(k, {"phrase": k, "src": [], "freq": None})
        if src not in e["src"]:
            e["src"].append(src)
        for f, v in kw.items():
            if v is not None and (e.get(f) is None or f == "freq" and v > (e.get(f) or 0)):
                e[f] = v

    for k, q in _own_queries(c, shop, nm, notes).items():
        add(k, "jam", freq=q["freq"], opens=q["opens"], orders=q["orders"], pos=q["pos"])
    ads = c.execute("""SELECT query, sum(views) v, sum(clicks) cl, sum(orders) o FROM wb_ad_kw_daily WHERE account_id=%s AND nm_id=%s
                       AND day > current_date - 30 GROUP BY 1 ORDER BY 2 DESC LIMIT 300""", (shop, nm)).fetchall()
    for r in ads:
        add(r["query"], "ads", ad_views=int(r["v"] or 0), ad_clicks=int(r["cl"] or 0), ad_orders=int(r["o"] or 0))
    if ads:
        notes.append(f"Реклама за 30 дней: {len(ads)} кластеров")
    comps = []
    tok = market.shop_token(c, shop)
    if not tok:
        notes.append("Wildbox не подключён — ключей конкурентов и подсказок WB нет (Настройки аккаунта → Wildbox)")
    else:
        try:
            comps = _competitors(c, shop, nm, tok)
            if comps:
                rows = _comp_keys(tok, [x["id"] for x in comps])
                for r in rows:
                    add(r.get("name"), "comp", freq=r.get("frequency"), comp_share=r.get("percent_products"), comp_count=r.get("count_products"))
                notes.append(f"Wildbox: запросы {len(comps)} конкурентов — {len(rows)}")
        except market.WildboxError as e:
            notes.append(f"Wildbox (конкуренты): {e}")
        own = sorted((v for v in keys.values() if "jam" in v["src"]), key=lambda v: -(v.get("freq") or 0))
        seed = own[0]["phrase"] if own else norm(card(c, shop, nm)["subject"])
        if seed:
            try:
                sg = _suggest(tok, seed)
                for p, f in sg:
                    add(p, "suggest", freq=f)
                notes.append(f"Подсказки WB к «{seed}»: {len(sg)}")
            except market.WildboxError as e:
                notes.append(f"Wildbox (подсказки): {e}")
    return {"keys": list(keys.values()), "competitors": comps, "notes": notes}


def start(shop: int, nm: int) -> bool:
    """Собрать ядро фоном; False — уже собирается."""
    with db.connect() as c:
        r = c.execute("""INSERT INTO seo_core(account_id,nm_id,state) VALUES (%s,%s,'running')
                         ON CONFLICT (account_id,nm_id) DO UPDATE SET state='running', error=NULL, started_at=now()
                         WHERE seo_core.state<>'running' OR seo_core.started_at < now() - interval '15 minutes' RETURNING 1""", (shop, nm)).fetchone()
        c.commit()
    if not r:
        return False

    def run():
        with db.connect() as c2:
            try:
                data = collect(c2, shop, nm)
                c2.execute("UPDATE seo_core SET state='done', data=%s, built_at=now() WHERE account_id=%s AND nm_id=%s",
                           (json.dumps(data, ensure_ascii=False, default=str), shop, nm))
            except Exception as e:  
                c2.rollback()
                c2.execute("UPDATE seo_core SET state='error', error=%s WHERE account_id=%s AND nm_id=%s", (str(e)[:400], shop, nm))
            c2.commit()
    threading.Thread(target=run, daemon=True).start()
    return True


def marks(c, shop: int, nm: int) -> dict[str, str]:
    return {r["phrase"]: r["mark"] for r in c.execute("SELECT phrase, mark FROM seo_kw_marks WHERE account_id=%s AND nm_id=%s", (shop, nm))}


def set_mark(c, shop: int, nm: int, phrase: str, mark: str | None, uid: int):
    p = norm(phrase)
    if not p:
        raise ValueError("Пустой ключ")
    if mark == "main":                       
        c.execute("UPDATE seo_kw_marks SET mark='core' WHERE account_id=%s AND nm_id=%s AND mark='main'", (shop, nm))
    if mark in ("core", "main", "excluded"):
        c.execute("""INSERT INTO seo_kw_marks(account_id,nm_id,phrase,mark,user_id) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (account_id,nm_id,phrase) DO UPDATE SET mark=EXCLUDED.mark, user_id=EXCLUDED.user_id, updated_at=now()""",
                  (shop, nm, p, mark, uid))
    else:
        c.execute("DELETE FROM seo_kw_marks WHERE account_id=%s AND nm_id=%s AND phrase=%s", (shop, nm, p))


def _score(k: dict) -> float:
    return (k.get("freq") or 0) * (1 + min(k.get("orders") or 0, 50) / 10 + (k.get("comp_share") or 0))


def view(c, shop: int, nm: int) -> dict:
    s = c.execute("SELECT data, state, error, built_at, started_at FROM seo_core WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
    cd = card(c, shop, nm)
    text = norm(cd["title"] + " " + cd["description"])
    title = norm(cd["title"])
    mk = marks(c, shop, nm)
    anchor = _stem((norm(cd["subject"]) or title).split()[0]) if (cd["subject"] or title) else ""   
    rel = lambda p: not anchor or any(_stem(w).startswith(anchor[:5]) for w in p.split())  
    keys = {k["phrase"]: dict(k) for k in ((s or {}).get("data") or {}).get("keys") or []}
    for p, m in mk.items():                  
        keys.setdefault(p, {"phrase": p, "src": ["manual"], "freq": None})
    rec, seen = set(), {tuple(sorted(_stem(w) for w in p.split())) for p, m in mk.items() if m in ("core", "main")}
    for k in sorted((k for k in keys.values() if k["phrase"] not in mk and rel(k["phrase"]) and
                     ((k.get("orders") or 0) > 0 or (k.get("ad_orders") or 0) > 0 or (k.get("comp_share") or 0) >= 0.5)), key=_score, reverse=True):
        sig = tuple(sorted(_stem(w) for w in k["phrase"].split()))   
        if sig in seen or len(rec) >= REC:
            continue
        seen.add(sig)
        rec.add(k["phrase"])
    rows = []
    for k in keys.values():
        p = k["phrase"]
        rows.append({**k, "mark": mk.get(p), "rec": p in rec, "relevant": rel(p), "in_card": has_phrase(text, p), "in_title": has_phrase(title, p),
                     "words_in_card": has_words(text, p)})
    rows.sort(key=lambda r: (r["mark"] not in ("main", "core"), not r["rec"], not r["relevant"], -_score(r)))
    data = (s or {}).get("data") or {}
    return {"rows": rows, "notes": data.get("notes") or [], "competitors": data.get("competitors") or [],
            "state": (s or {}).get("state"), "error": (s or {}).get("error"), "built_at": (s or {}).get("built_at"),
            "card": {**cd, "title_len": len(cd["title"]), "desc_len": len(cd["description"])}}


def core(c, shop: int, nm: int) -> tuple[str | None, list[str]]:
    """Главный ключ и ядро (отмеченные «в ядро»). Нет отметок — рекомендованные."""
    v = view(c, shop, nm)
    main = next((r["phrase"] for r in v["rows"] if r["mark"] == "main"), None)
    sel = [r["phrase"] for r in v["rows"] if r["mark"] in ("main", "core")]
    if not sel:
        sel = [r["phrase"] for r in sorted((r for r in v["rows"] if r["rec"]), key=_score, reverse=True)]
    if not main and sel:
        main = max((r for r in v["rows"] if r["phrase"] in sel), key=lambda r: r.get("freq") or 0)["phrase"]
    return main, sel


def rules(c, shop: int, nm: int) -> str:
    rs = c.execute("SELECT nm_id, text FROM seo_rules WHERE account_id=%s AND nm_id IN (0,%s) ORDER BY nm_id", (shop, nm)).fetchall()
    return "\n".join(r["text"].strip() for r in rs if r["text"].strip())

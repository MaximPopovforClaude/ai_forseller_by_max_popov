"""Self-hosted application component."""

import hashlib

import json
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from . import config, db
from .config import today_msk

URL = "https://wildbox.ru/mcp"
GAP_S = 10.5
LOCK = 7720190
FIELDS = ("proceeds,orders,price,old_price,discount,quantity,rating,reviews,reviews_diff,lost_proceeds,in_stock_percent,"
          "wh_avg_position,count_keywords,sales_percent,promos")
SNAP_FIELDS = "proceeds,orders,price,old_price,discount,quantity,rating,reviews,promos"


class WildboxError(RuntimeError):
    pass


NO_KEY = "Wildbox не подключён к кабинету: «Настройки аккаунта» → «Wildbox» → вставьте свой ключ Wildbox."


def ws_token(c, ws_id: int) -> str | None:
    from . import vault
    r = c.execute("SELECT enc FROM workspace_secrets WHERE workspace_id=%s AND kind='wildbox'", (ws_id,)).fetchone()
    return vault.decrypt(bytes(r["enc"])) if r else None


def shop_token(c, shop: int) -> str | None:
    r = c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop,)).fetchone()
    return ws_token(c, r["workspace_id"]) if r and r["workspace_id"] else None


def _tid(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()[:16]


def check_token(tok: str) -> str | None:
    """Проверка ключа без траты лимита: рукопожатие и список инструментов. None — ок, иначе текст ошибки."""
    try:
        cl = _Client(tok)
        tools = cl._rpc("tools/list", {}).get("result", {}).get("tools") or []
        if not any(t.get("name") == "get_external_analytics" for t in tools):
            return "Ключ принят, но рыночная аналитика Wildbox этому тарифу недоступна"
        return None
    except WildboxError as e:
        return "Wildbox не принял ключ" + (" (неверный ключ)" if "401" in str(e) or "403" in str(e) else f": {e}")
    except Exception as e:  
        return f"Wildbox не ответил: {str(e)[:120]}"


class _Client:
    def __init__(self, tok: str):
        self.h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-Wildbox-Token": tok}
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "ai-stometric", "version": "1.0"}})
        self._rpc("notifications/initialized", {}, notify=True)

    def _rpc(self, method, params, notify=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            body["id"] = 1
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=self.h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                sid = r.headers.get("Mcp-Session-Id")
                if sid:
                    self.h["Mcp-Session-Id"] = sid
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise WildboxError(f"Wildbox HTTP {e.code}") from None
        if notify:
            return {}
        chunks = [ln[6:] for ln in raw.decode("utf-8").split("\n") if ln.startswith("data: ")]
        return json.loads("\n".join(chunks)) if chunks else (json.loads(raw) if raw.strip() else {})

    def call(self, tool: str, **args):
        import re
        for attempt in range(3):
            resp = self._rpc("tools/call", {"name": tool, "arguments": args})
            if "error" in resp:
                raise WildboxError(resp["error"].get("message", "ошибка Wildbox"))
            res = resp.get("result", {})
            text = (res.get("content") or [{}])[0].get("text", "")
            if not res.get("isError"):
                return json.loads(text) if text else None
            m = re.search(r"Retry after (\d+)", text) or re.search(r"available in (\d+) seconds", text)
            if m and attempt < 2:
                time.sleep(int(m.group(1)) + 1)
                continue
            raise WildboxError(text[:300])


def _call(tok: str, tool: str, **args):
    """Один вызов Wildbox с общей очередью на все процессы сервиса (≥10 с между вызовами одного ключа)."""
    tid = _tid(tok)
    lock = LOCK + int(tid[:6], 16)
    with db.connect(autocommit=True) as c:
        c.execute("SELECT pg_advisory_lock(%s)", (lock,))
        try:
            r = c.execute("SELECT value FROM app_settings WHERE key=%s", ("wildbox_last:" + tid,)).fetchone()
            wait = GAP_S - (time.time() - float(r["value"])) if r else 0
            if wait > 0:
                time.sleep(wait)
            try:
                return _Client(tok).call(tool, **args)
            finally:
                c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
                          ("wildbox_last:" + tid, json.dumps(time.time())))
        finally:
            c.execute("SELECT pg_advisory_unlock(%s)", (lock,))


_BG = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wildbox")   
_BG_KEYS: set = set()
_BG_LOCK = threading.Lock()


def _bg_fetch(tok, params, fields, ttl_h, max_rows, key):
    try:
        with db.connect() as c:
            products(c, tok, params, fields, ttl_h, max_rows)
    except Exception:  
        pass
    finally:
        with _BG_LOCK:
            _BG_KEYS.discard(key)


def products(c, tok: str, params: dict, fields: str, ttl_h: float, max_rows: int = 20, background: bool = False) -> dict:
    """background — для запросов сайта: нет свежего — отдаём прошлое (или пусто) с pending и грузим фоном."""
    key = f"top|{_tid(tok)}|" + json.dumps(params, sort_keys=True) + "|" + fields
    hit = c.execute("SELECT data, fetched_at > now() - make_interval(secs => %s) fresh FROM market_cache WHERE key=%s",
                    (ttl_h * 3600, key)).fetchone()
    if hit and hit["fresh"]:
        return hit["data"]
    if background:
        with _BG_LOCK:
            go = key not in _BG_KEYS
            _BG_KEYS.add(key)
        if go:
            _BG.submit(_bg_fetch, tok, params, fields, ttl_h, max_rows, key)
        return {**(hit["data"] if hit else {"rows": [], "notes": None}), "pending": True}
    res = _call(tok, "get_external_analytics", schema_name="external.products.top", extra_fields=fields, params=params, max_rows=max_rows)
    rows = [{k: v for k, v in r.items() if k != "dynamic"} for r in (res or {}).get("rows") or []]
    data = {"rows": rows, "notes": (res or {}).get("notes"), "sample": (res or {}).get("sample")}
    c.execute("INSERT INTO market_cache(key,data) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET data=EXCLUDED.data, fetched_at=now()",
              (key, json.dumps(data, ensure_ascii=False, default=str)))
    c.commit()
    return data


def _wb_url(nm: int) -> str:
    return f"https://www.wildberries.ru/catalog/{nm}/detail.aspx"


def compare(c, shop: int, nm: int, period: int = 30) -> dict:
    """Наш артикул + его конкуренты: метрики Wildbox за period дней + наши фактические цифры за те же дни (из API WB)."""
    comps = c.execute("""SELECT k.comp_nm_id, k.note, k.created_at, coalesce(u.name, u.email) who FROM competitors k
                         LEFT JOIN users u ON u.id=k.added_by WHERE k.account_id=%s AND k.nm_id=%s ORDER BY k.created_at""",
                      (shop, nm)).fetchall()
    ids = [nm] + [r["comp_nm_id"] for r in comps]
    rows, notes, err, pending = {}, None, None, False
    tok = shop_token(c, shop)
    if tok:
        try:
            for i in range(0, len(ids), 20):
                part = ids[i:i + 20]
                res = products(c, tok, {"product_ids": ",".join(map(str, part)), "period": period}, FIELDS, ttl_h=6, background=True)
                notes = res.get("notes") or notes
                pending = pending or bool(res.get("pending"))
                for r in res["rows"]:
                    rows[int(r["id"])] = r
        except WildboxError as e:
            err = str(e)
    else:
        err = NO_KEY
    y = today_msk() - timedelta(days=1)
    mine = c.execute("""SELECT sum((data->>'orders')::numeric) orders, sum((data->>'orders_sum_spp')::numeric) proceeds_spp,
                               sum((data->>'orders_sum')::numeric) proceeds
                        FROM agg_nm_day WHERE account_id=%s AND nm_id=%s AND day BETWEEN %s AND %s""",
                     (shop, nm, y - timedelta(days=period - 1), y)).fetchone()
    card = c.execute("SELECT vendor_code, title, data->'photos'->0->>'tm' photo FROM nomenclature WHERE account_id=%s AND nm_id=%s",
                     (shop, nm)).fetchone() or {}
    meta = {r["comp_nm_id"]: r for r in comps}
    out = []
    for i in ids:
        w = rows.get(i) or {}
        out.append({"nm_id": i, "mine": i == nm, "name": w.get("name") or (card.get("title") if i == nm else None),
                    "image": w.get("image") or (card.get("photo") if i == nm else None), "url": _wb_url(i),
                    "note": meta.get(i, {}).get("note"), "who": meta.get(i, {}).get("who"), "in_wildbox": bool(w),
                    **{k: w.get(k) for k in ("proceeds", "orders", "price", "old_price", "discount", "quantity", "rating", "reviews",
                                             "reviews_diff", "lost_proceeds", "in_stock_percent", "wh_avg_position", "count_keywords",
                                             "sales_percent", "seller", "brand", "create_date")},
                    "promos": w.get("promos")})
    return {"nm_id": nm, "vendor_code": card.get("vendor_code"), "period": period, "rows": out, "error": err, "notes": notes, "pending": pending,
            "ours": {k: (float(v) if v is not None else None) for k, v in (mine or {}).items()}}


def suggest(c, shop: int, nm: int) -> dict:
    """Похожие товары WB (блок «похожие» карточки) с выручкой за 30 дней — кандидаты в конкуренты."""
    tok = shop_token(c, shop)
    if not tok:
        return {"rows": [], "error": NO_KEY}
    have = {r["comp_nm_id"] for r in c.execute("SELECT comp_nm_id FROM competitors WHERE account_id=%s AND nm_id=%s", (shop, nm))}
    try:
        res = products(c, tok, {"similar": nm, "period": 30}, "proceeds,orders,price,rating,reviews,quantity", ttl_h=24)
    except WildboxError as e:
        return {"rows": [], "error": str(e)}
    rows = [{**{k: r.get(k) for k in ("id", "name", "image", "proceeds", "orders", "price", "rating", "reviews", "quantity", "seller")},
             "added": int(r["id"]) in have} for r in res["rows"] if int(r["id"]) != nm]
    return {"rows": rows, "error": None}



def _events(prev: dict, cur: dict, hist: list[dict]) -> list[tuple[str, dict | None, dict | None]]:
    ev = []
    p0, p1 = prev.get("price"), cur.get("price")
    if p0 and p1 and abs(p1 - p0) / p0 >= 0.03:
        ev.append(("price_up" if p1 > p0 else "price_down", {"price": round(p0)}, {"price": round(p1)}))
    q0, q1 = prev.get("quantity"), cur.get("quantity")
    if q0 is not None and q1 is not None:
        if q0 > 0 and q1 == 0:
            ev.append(("out_of_stock", {"quantity": q0}, {"quantity": 0}))
        elif q0 == 0 and q1 > 0:
            ev.append(("back_in_stock", {"quantity": 0}, {"quantity": q1}))
    r0, r1 = prev.get("rating"), cur.get("rating")
    if r0 and r1 and abs(r1 - r0) >= 0.1:
        ev.append(("rating_up" if r1 > r0 else "rating_down", {"rating": r0}, {"rating": r1}))
    v0, v1 = prev.get("reviews"), cur.get("reviews")
    if v0 is not None and v1 is not None and v1 - v0 >= max(20, v0 * 0.05):
        ev.append(("reviews_jump", {"reviews": v0}, {"reviews": v1}))
    base = [h.get("orders") or 0 for h in hist]
    o1 = cur.get("orders")
    if len(base) >= 3 and o1 is not None:
        avg = sum(base) / len(base)
        if o1 >= max(10, avg * 2):
            ev.append(("orders_spike", {"orders_avg": round(avg, 1)}, {"orders": o1}))
        elif avg >= 5 and o1 <= avg * 0.4:
            ev.append(("orders_drop", {"orders_avg": round(avg, 1)}, {"orders": o1}))
    if prev.get("promos") is not None and cur.get("promos") is not None and prev.get("promos") != cur.get("promos"):
        ev.append(("promo", {"promos": prev.get("promos")}, {"promos": cur.get("promos")}))
    return ev


def _actual_day(notes, asked: date) -> date:
    """Wildbox досчитывает последние дни с задержкой (1–3 дня) и сам подменяет дату — берём ту, что он назвал в notes."""
    import re
    for n in notes or []:
        m = re.search(r"по (\d{4}-\d{2}-\d{2})", str(n))
        if m:
            return min(asked, date.fromisoformat(m.group(1)))
    return asked


def monitor_day(day: date | None = None) -> dict:
    """Снимок конкурентов за последний готовый у Wildbox день — по каждому кабинету его ключом (наборами по 20)
    и события по сравнению с прошлым снимком. Повторный запуск в тот же день ничего не тратит (кэш и уже снятые)."""
    asked = day or today_msk() - timedelta(days=1)
    out = {"asked": str(asked), "workspaces": 0, "competitors": 0, "new_snaps": 0, "events": 0, "errors": []}
    with db.connect() as c:
        wss = [r["workspace_id"] for r in c.execute("SELECT workspace_id FROM workspace_secrets WHERE kind='wildbox'")]
        for ws in wss:
            tok = ws_token(c, ws)
            ids = [r["comp_nm_id"] for r in c.execute("""SELECT DISTINCT k.comp_nm_id FROM competitors k JOIN accounts a ON a.id=k.account_id
                                                          WHERE a.workspace_id=%s ORDER BY 1""", (ws,))]
            if not tok or not ids:
                continue
            out["workspaces"] += 1
            out["competitors"] += len(ids)
            for i in range(0, len(ids), 20):
                part = ids[i:i + 20]
                try:
                    res = products(c, tok, {"product_ids": ",".join(map(str, part)), "date_from": asked.isoformat(), "date_to": asked.isoformat()},
                                   SNAP_FIELDS, ttl_h=20)
                except WildboxError as e:
                    out["errors"].append(f"кабинет {ws}: {str(e)[:120]}")
                    break
                actual = _actual_day(res.get("notes"), asked)
                out["day"] = str(actual)
                for r in res["rows"]:
                    nm = int(r["id"])
                    if c.execute("SELECT 1 FROM market_snap WHERE nm_id=%s AND day=%s", (nm, actual)).fetchone():
                        continue
                    c.execute("INSERT INTO market_snap(nm_id,day,data) VALUES (%s,%s,%s)", (nm, actual, json.dumps(r, ensure_ascii=False, default=str)))
                    out["new_snaps"] += 1
                    prev = c.execute("SELECT data FROM market_snap WHERE nm_id=%s AND day<%s ORDER BY day DESC LIMIT 1", (nm, actual)).fetchone()
                    hist = [h["data"] for h in c.execute("SELECT data FROM market_snap WHERE nm_id=%s AND day<%s AND day>=%s",
                                                           (nm, actual, actual - timedelta(days=7)))]
                    if prev:
                        for kind, old, new in _events(prev["data"], r, hist):
                            c.execute("""INSERT INTO competitor_events(comp_nm_id,day,kind,old_value,new_value) VALUES (%s,%s,%s,%s,%s)
                                         ON CONFLICT DO NOTHING""", (nm, actual, kind, json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False)))
                            out["events"] += 1
                c.commit()
    return out


def events_for_shop(c, shop: int, day: date) -> list[dict]:
    from .tabs.manage import EVENT_TITLE
    rows = c.execute("""SELECT e.comp_nm_id, e.kind, e.old_value, e.new_value, s.data->>'name' name,
                               array_agg(DISTINCT n.vendor_code) mine
                        FROM competitor_events e JOIN competitors k ON k.comp_nm_id=e.comp_nm_id AND k.account_id=%s
                        LEFT JOIN nomenclature n ON n.account_id=k.account_id AND n.nm_id=k.nm_id
                        LEFT JOIN market_snap s ON s.nm_id=e.comp_nm_id AND s.day=e.day
                        WHERE e.day BETWEEN %s AND %s GROUP BY e.id, s.data""", (shop, day - timedelta(days=2), day)).fetchall()
    return [{**r, "title": EVENT_TITLE.get(r["kind"], r["kind"])} for r in rows]


if __name__ == "__main__":
    print(monitor_day())

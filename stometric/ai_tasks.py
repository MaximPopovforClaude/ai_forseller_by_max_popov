"""Self-hosted application component."""

import json
import re
from datetime import date, datetime, timedelta, timezone

from .config import today_msk

TAGS = {"ads": "реклама", "card": "карточка", "price": "цена", "stock": "остатки", "promo": "акции", "reviews": "отзывы", "other": "другое"}
CERT = {"exact": "точно", "likely": "вероятно", "hypothesis": "гипотеза"}
STATUS_T = {"new": "новая", "done": "выполнено", "partial": "частично", "not_done": "не сделано", "skipped": "не делаем"}
CHECK_KINDS = ("price", "ad_bid", "ad_status", "stock", "photo", "content", "promo", "none")
MSK = timezone(timedelta(hours=3))


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def enabled_shops(c) -> list[int]:
    return [r["account_id"] for r in c.execute("""SELECT s.account_id FROM ai_task_shops s
        JOIN accounts a ON a.id=s.account_id WHERE s.enabled AND a.is_active ORDER BY s.account_id""")]


def is_enabled(c, shop: int) -> bool:
    return bool(c.execute("SELECT 1 FROM ai_task_shops WHERE account_id=%s AND enabled", (shop,)).fetchone())


def marketplace(c, shop):
    row = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()
    return row.get("marketplace", "wb") if isinstance(row, dict) else "wb"



_NUM = re.compile(r"(?<![\d.,])\d{1,3}(?:[   ]\d{3})+(?![\d])|\d+(?:[.,]\d+)?")


def _nums(text: str) -> list[float]:
    out = []
    for m in _NUM.finditer(text or ""):
        s = re.sub(r"[   ]", "", m.group(0)).replace(",", ".")
        try:
            out.append(float(s))
        except ValueError:
            pass
    return out


def numbers_ok(text: str, known: set[int], *, allow_years: bool = True) -> tuple[bool, list[float]]:
    """Числа от 100 из текста задачи — есть ли они в досье (с допуском ±1 на округление). Больше половины не нашли — задачу отбрасываем."""
    big = [x for x in _nums(text) if abs(x) >= 100
           and not (allow_years and 1900 <= x <= 2100 and x == int(x))]
    miss = [x for x in big if not any(int(round(x)) + d in known for d in (-1, 0, 1))]
    return (not big or len(miss) * 2 <= len(big)), miss


def known_numbers(brief: str) -> set[int]:
    return {int(round(x)) for x in _nums(brief)}


def retry_needs_review(run: dict | None) -> bool:
    """An interrupted/OOM attempt needs diagnosis before an explicitly approved retry."""
    if not run:
        return False
    if run.get('status') in ('interrupted', 'uncertain'):
        return True
    if run.get("status") != "error":
        return False
    message = str(run.get("error") or "").casefold()
    return bool(re.search(r"прерван|interrupted|\boom(?:-kill)?\b|out[ -]of[ -]memory|memoryerror|"
                          r"cannot allocate memory|sigkill|sigterm|killed.*signal|signal.*(?:9|15)\b|"
                          r"нехват\w* памяти|недостат\w* памяти|uncertain|неопредел[её]н", message))


def latest_attempt(c, shop: int):
    """Pending UI requests cannot hide an unresolved attempt, including a prior day."""
    return c.execute("""SELECT id,status,error,started_at FROM ai_task_runs
        WHERE account_id=%s AND status <> 'requested' ORDER BY id DESC LIMIT 1""", (shop,)).fetchone()



def load(c, shop: int, day: date, run_id: int, data: dict, brief: str, *, platform="wb") -> dict:
    """Задачи от нейросети → ai_tasks (прежние задачи этого дня — неактивны). → {saved, dropped: [...]}."""
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("Неверная структура задач: прежние задачи сохранены")
    dropped = []
    if platform == "ozon":
        from .ozon_task_validation import validate
        data, dropped = validate(c, shop, data)
        _, summary_missing = numbers_ok(str(data.get("summary") or ""), known_numbers(brief), allow_years=False)
        if summary_missing:
            raise ValueError("Числа сводки Ozon не подтверждены досье: прежние задачи сохранены")
    known = known_numbers(brief)
    saved = 0
    rows = []
    for t in (data.get("tasks") or [])[:15]:
        if not isinstance(t, dict):
            continue
        title, why = str(t.get("title") or "").strip(), str(t.get("why") or "").strip()
        if not title or not why:
            continue
        text = title + " " + why + (" " + str(t.get("steps") or "") if platform == "ozon" else "")
        ok, miss = numbers_ok(text, known, allow_years=platform != "ozon")
        if not ok or (platform == "ozon" and miss):
            dropped.append({"title": title, "missing": miss[:5]})
            continue
        tag = t.get("tag") if t.get("tag") in TAGS else "other"
        cert = t.get("certainty") if t.get("certainty") in CERT else "hypothesis"
        nms = [int(x) for x in (t.get("nm_ids") or []) if str(x).isdigit()][:30]
        chk = t.get("check") if isinstance(t.get("check"), dict) else {"kind": "none"}
        if chk.get("kind") not in CHECK_KINDS:
            chk = {"kind": "none"}
        chk["nm_ids"] = [int(x) for x in (chk.get("nm_ids") or nms) if str(x).isdigit()][:30]
        eff = t.get("effect_week")
        rows.append((shop, run_id, day, title[:300], why[:3000], (str(t.get("steps") or "").strip() or None), tag, cert,
                     round(_f(eff)) if eff not in (None, "") else None, int(_f(t.get("priority")) or 50), nms,
                     (str(t.get("vc") or "").strip()[:200] or None), json.dumps(chk, ensure_ascii=False)))
    if not rows:
        raise ValueError("Ни одна задача не прошла проверку: прежние задачи сохранены")
    c.execute("UPDATE ai_tasks SET active=false WHERE account_id=%s AND day=%s AND active", (shop, day))
    for r in rows:
        c.execute("""INSERT INTO ai_tasks(account_id, run_id, day, title, why, steps, tag, certainty, effect_week, priority, nm_ids, vc, check_spec)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", r)
        saved += 1
    c.commit()
    return {"saved": saved, "dropped": dropped}



def _changes(c, shop: int, since, kinds: tuple, nms: list[int], advert: int | None) -> list[dict]:
    q = """SELECT kind, field, nm_id, old_value, new_value, detected_at FROM card_changes WHERE account_id=%s AND kind = ANY(%s)
           AND detected_at > %s AND (nm_id = ANY(%s) OR (%s::bigint IS NOT NULL AND field = 'ad:' || %s::text)) ORDER BY detected_at"""
    return c.execute(q, (shop, list(kinds), since, nms or [0], advert, advert)).fetchall()


def _bidsum(v) -> float:
    v = v or {}
    return _f(v.get("search")) + _f(v.get("recommendations"))


def _stock(c, shop: int, nms: list[int], at) -> float | None:
    r = c.execute("""SELECT sum(quantity) q FROM stocks_wb_snap WHERE account_id=%s AND nm_id = ANY(%s)
                     AND snap_at = (SELECT max(snap_at) FROM stocks_wb_snap WHERE account_id=%s AND snap_at <= %s)""",
                  (shop, nms, shop, at)).fetchone()
    return _f(r["q"]) if r and r["q"] is not None else None


def auto_status(c, shop: int, t: dict) -> tuple[str | None, str | None, datetime | None]:
    """(статус, пояснение, когда) по журналу изменений; None — пока не видно."""
    if marketplace(c, shop) == "ozon":
        from .ai_tasks_ozon import auto_status as oz_auto_status
        return oz_auto_status(c, shop, t)
    chk = t["check_spec"] or {}
    kind, nms, adv = chk.get("kind") or "none", chk.get("nm_ids") or t["nm_ids"] or [], chk.get("advert_id")
    direction, target = chk.get("direction") or "any", chk.get("target")
    since = datetime.combine(t["day"] - timedelta(days=1), datetime.min.time(), MSK)    
    since = max(since, t["created_at"] - timedelta(hours=12))
    if kind == "price":
        ch = _changes(c, shop, since, ("price",), nms, None)
        if not ch:
            return None, None, None
        hit, last = set(), {}
        for r in ch:
            o, n = _f((r["old_value"] or {}).get("final")), _f((r["new_value"] or {}).get("final"))
            if n and o and (direction == "any" or (direction == "down" and n < o) or (direction == "up" and n > o)):
                hit.add(r["nm_id"]); last[r["nm_id"]] = n
        if not hit:
            return None, None, None
        tgt_ok = not target or any(abs(v - _f(target)) / _f(target) <= 0.03 for v in last.values())
        full = len(hit) >= max(1, len(nms)) and tgt_ok
        note = "цена изменена: " + ", ".join(f"{n} → {v:g} ₽" for n, v in list(last.items())[:5])
        return ("done" if full else "partial"), note, ch[-1]["detected_at"]
    if kind in ("ad_bid", "ad_status"):
        ch = _changes(c, shop, since, (kind,), nms, adv)
        good = []
        for r in ch:
            if kind == "ad_bid":
                o, n = _bidsum(r["old_value"]), _bidsum(r["new_value"])
                if direction == "any" or (direction == "down" and n < o) or (direction == "up" and n > o):
                    good.append(r)
            else:
                st = (r["new_value"] or {}).get("status")
                if (direction in ("pause", "down") and st == "на паузе") or (direction in ("start", "up") and st == "идёт") or direction == "any":
                    good.append(r)
        if kind == "ad_status" and direction in ("pause", "down"):
            
            good = [r for r in good if r["detected_at"] <= datetime.now(timezone.utc) - timedelta(days=1) and not c.execute("""SELECT 1 FROM card_changes WHERE account_id=%s AND kind='ad_status' AND field=%s
                                                        AND detected_at > %s AND detected_at < %s + interval '1 day' AND new_value->>'status'='идёт'""",
                                                     (shop, r["field"], r["detected_at"], r["detected_at"])).fetchone()]
        if not good:
            return None, None, None
        camps = sorted({r["field"][3:] for r in good})
        return "done", ("ставка изменена" if kind == "ad_bid" else "статус кампании изменён") + f": кампании {', '.join(camps[:5])}", good[-1]["detected_at"]
    if kind in ("photo", "content", "promo"):
        ch = _changes(c, shop, since, (kind,), nms, None)
        if not ch:
            return None, None, None
        n = len({r["nm_id"] for r in ch})
        return ("done" if n >= max(1, len(nms)) else "partial"), {"photo": "фото изменены", "content": "карточка изменена",
                                                                   "promo": "участие в акции изменилось"}[kind] + f" ({n} арт.)", ch[-1]["detected_at"]
    if kind == "stock" and nms:
        a, b = _stock(c, shop, nms, since), _stock(c, shop, nms, datetime.now(timezone.utc))
        if a is None or b is None or b <= a:
            return None, None, None
        need = _f(target)
        return ("done" if not need or b - a >= need * 0.8 else "partial"), f"остаток WB {a:g} → {b:g} шт", datetime.now(timezone.utc)
    return None, None, None


def _outcomes_lock(c, shop: int) -> None:
    c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ai-task-outcomes:{shop}",))


def invalidate_outcomes(c, shop: int, revision: str) -> None:
    """Mark only derived numbers stale; retain tasks, manual marks and prior values.

    Called in the cost edit transaction. The revision also fences a check already
    running, so its old calculation cannot overwrite this pending marker.
    """
    _outcomes_lock(c, shop)
    c.execute("""UPDATE ai_tasks SET outcome=outcome || jsonb_build_object('pending',true,'rebuild_revision',%s::text)
                 WHERE account_id=%s AND status IN ('done','partial') AND outcome IS NOT NULL
                   AND EXISTS (SELECT 1 FROM accounts WHERE id=%s AND marketplace IN ('wb','ozon'))""", (revision, shop, shop))


def outcome(c, shop: int, nms: list[int], d0: date) -> dict | None:
    """Заказы (воронка), сумма заказов, реклама и прибыль (как в дашборде) артикулов задачи: 3 дня до d0 и дни после (до 3, по вчера)."""
    from .materialize import ensure_cost_ready
    ensure_cost_ready(c, shop)
    if marketplace(c, shop) == "ozon":
        from .ai_tasks_ozon import outcome as oz_outcome
        return oz_outcome(c, shop, nms, d0)
    y = today_msk() - timedelta(days=1)
    n_after = min(3, (y - d0).days)
    if n_after < 1 or not nms:
        return None
    res = {}
    for tag, a, b in (("before", d0 - timedelta(days=3), d0 - timedelta(days=1)), ("after", d0 + timedelta(days=1), d0 + timedelta(days=n_after))):
        r = c.execute("""SELECT sum((data->>'orderCount')::numeric) o, sum((data->>'orderSum')::numeric) s FROM raw_rows
                         WHERE account_id=%s AND source='funnel_day' AND row_date BETWEEN %s AND %s
                         AND split_part(row_key,'|',1)::bigint = ANY(%s)""", (shop, a, b, nms)).fetchone()
        g = c.execute("""SELECT sum(coalesce((data->>'ads')::numeric,0)) ads, sum(coalesce((data->>'profit')::numeric,0)) p FROM agg_nm_day
                         WHERE account_id=%s AND day BETWEEN %s AND %s AND nm_id = ANY(%s)""", (shop, a, b, nms)).fetchone()
        days = (b - a).days + 1
        res[tag] = {"days": days, "orders": round(_f(r["o"]) / days, 1), "sum": round(_f(r["s"]) / days), "ads": round(_f(g["ads"]) / days),
                    "profit": round(_f(g["p"]) / days)}
    res["delta_profit_week"] = round((res["after"]["profit"] - res["before"]["profit"]) * 7)
    res["final"] = n_after >= 3
    return res


def check(c, shop: int) -> int:
    """Recent auto marks plus bounded recomputation of invalidated historical outcomes."""
    from .materialize import cost_dirty, NotReady
    
    
    _outcomes_lock(c, shop)
    n = 0
    y = today_msk() - timedelta(days=1)
    since = today_msk() - timedelta(days=8)
    is_ozon = marketplace(c, shop) == "ozon"
    dirty = not is_ozon and bool(cost_dirty(c, shop))
    rows = c.execute("""SELECT * FROM ai_tasks WHERE account_id=%s AND active AND day >= %s ORDER BY id""", (shop, since)).fetchall()
    if not dirty:
        
        
        if is_ozon:
            
            
            old = c.execute("""SELECT * FROM ai_tasks WHERE account_id=%s
                               AND status IN ('done','partial') AND (NOT active OR day < %s)
                               AND (outcome IS NULL OR outcome->>'pending'='true' OR coalesce(outcome->>'final','false')<>'true')
                               ORDER BY coalesce(outcome->>'checked_at',''),id LIMIT 25""", (shop, since)).fetchall()
        else:
            old = c.execute("""SELECT * FROM ai_tasks WHERE account_id=%s AND outcome->>'pending'='true'
                               AND status IN ('done','partial') AND (NOT active OR day < %s) ORDER BY id LIMIT 25""",
                            (shop, since)).fetchall()
        rows = list({t['id']: t for t in [*rows, *old]}.values())
    for t in rows:
        upd = {}
        pause_check = (t["check_spec"] or {}).get("kind") == "ad_status" and (t["check_spec"] or {}).get("direction") in ("pause", "down")
        if t.get("active", True) and t["day"] >= since and t["status_by"] != "manual" and (t["status"] in ("new", "partial", "not_done") or (pause_check and t["status"] == "done")):
            st, note, at = auto_status(c, shop, t)
            if st and (st != t["status"] or note != t["status_note"]):
                upd.update(status=st, status_by="auto", status_note=note, status_at=datetime.now(timezone.utc), done_at=at)
            elif not st and not is_ozon and pause_check and t["status"] == "done":
                upd.update(status="new", status_by="auto", status_note="Пауза пока не подтверждена в течение суток", done_at=None, outcome=None)
            elif not st and not is_ozon and t["status"] == "new" and t["day"] < y:
                upd.update(status="not_done", status_by="auto", status_note="изменений по задаче в журнале не видно", status_at=datetime.now(timezone.utc))
        st = upd.get("status", t["status"])
        done_at = upd.get("done_at", t["done_at"])
        computed_outcome = False
        if not dirty and st in ("done", "partial") and (is_ozon or not (t["outcome"] or {}).get("final") or (t["outcome"] or {}).get("pending")):
            d0 = (done_at or t["status_at"] or datetime.now(timezone.utc)).astimezone(MSK).date()
            try:
                o = outcome(c, shop, t["nm_ids"] or (t["check_spec"] or {}).get("nm_ids") or [], d0)
            except NotReady:  
                o = None
            if not o and is_ozon:
                upd["outcome"] = json.dumps({**(t["outcome"] or {}), "pending": True,
                                              "checked_at": datetime.now(timezone.utc).isoformat()})
                computed_outcome = True
            if o:
                if is_ozon:
                    o["checked_at"] = datetime.now(timezone.utc).isoformat()
                upd["outcome"] = json.dumps(o)
                computed_outcome = True
        if upd:
            sets = ", ".join(f"{k}=%s" for k in upd)
            guard = " AND outcome IS NOT DISTINCT FROM %s::jsonb" if computed_outcome else ""
            args = (*upd.values(), t["id"], *([json.dumps(t["outcome"]) if t["outcome"] is not None else None] if computed_outcome else []))
            c.execute(f"UPDATE ai_tasks SET {sets} WHERE id=%s{guard}", args)
            n += 1
    c.commit()
    return n



def feedback_digest(c, shop: int, days: int = 30) -> str:
    out = []
    for r in c.execute("""SELECT t.day, t.tag, t.title, f.rating, f.comment FROM ai_task_feedback f JOIN ai_tasks t ON t.id=f.task_id
                          WHERE f.account_id=%s AND f.updated_at > now() - make_interval(days => %s) ORDER BY f.updated_at DESC LIMIT 60""", (shop, days)):
        mark = {1: "👍", -1: "👎"}.get(r["rating"], "💬")
        out.append(f"{r['day']:%d.%m} [{TAGS.get(r['tag'], r['tag'])}] {mark} «{r['title']}»" + (f" — комментарий: {r['comment']}" if r["comment"] else ""))
    return "\n".join(out) or "оценок пока нет"


def history_digest(c, shop: int, days: int = 7) -> str:
    out = []
    for r in c.execute("""SELECT day, tag, certainty, title, status, status_by, status_note, outcome, effect_week FROM ai_tasks
                          WHERE account_id=%s AND active AND day >= %s AND day < %s ORDER BY day DESC, priority DESC""",
                       (shop, today_msk() - timedelta(days=days), today_msk())):
        o = r["outcome"] or {}
        res = (f"; итог: заказы/день {o['before']['orders']} → {o['after']['orders']}, прибыль/день {o['before']['profit']} → {o['after']['profit']} ₽"
               if o.get("before") and not o.get("pending") else "; итог пересчитывается после изменения исходных данных" if o.get("pending") else "")
        out.append(f"{r['day']:%d.%m} [{TAGS.get(r['tag'], r['tag'])}, {CERT.get(r['certainty'])}] «{r['title']}» — {STATUS_T.get(r['status'])}"
                   + (f" ({r['status_note']})" if r["status_note"] else "") + res)
    return "\n".join(out) or "задач ещё не было"

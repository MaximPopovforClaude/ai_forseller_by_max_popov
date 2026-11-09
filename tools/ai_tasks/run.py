"""Self-hosted application component."""
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import stometric.web  
from stometric import ai_tasks
from stometric.config import today_msk
from stometric.db import connect

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "data/ai_tasks_work"
START_MSK = (9, 40)
REBUILD_UNTIL_H = 18
MSK = timezone(timedelta(hours=3))


def log(*a):
    print(f"[{datetime.now(MSK):%d.%m %H:%M:%S}]", *a, flush=True)


def parse(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise RuntimeError("в ответе нет JSON")
    return json.loads(text[a:b + 1])


def build(c, shop: int, run_id: int, day) -> dict:
    from stometric.private_ai import require_owner_shop
    request = c.execute("SELECT requested_by,request_key FROM ai_task_runs WHERE id=%s", (run_id,)).fetchone()
    require_owner_shop(c, shop, request["requested_by"] if request else None,
                       trusted_scheduled=bool(request and request["requested_by"] is None))
    if not ai_tasks.is_enabled(c, shop):
        raise ValueError('Блок задач магазина выключен; новые задачи не создавались')
    from stometric.entry_coverage import report_present
    y = day - timedelta(days=1)
    platform = ai_tasks.marketplace(c, shop)
    if platform not in ("wb", "ozon"):
        raise ValueError("Разбор этой площадки пока не поддерживается")
    source_state = None
    if platform == "ozon":
        from stometric.ozon_task_data import coverage
        source_state = coverage(c, shop, y)
        if not source_state["ready"]:
            raise ValueError("Нет воронки Ozon за " + y.isoformat() + "; прежние задачи сохранены")
    entry_ok = report_present(c, shop, y) if platform == "wb" else None
    if True:
        from stometric.kit_analytics import source_coverage
        source_state = source_coverage(c, shop, platform, y)
        if not source_state.get('ready'):
            raise ValueError('Источники для порученного разбора неполны; прежние задачи сохранены')
    if source_state is not None:
        c.execute("UPDATE ai_task_runs SET entry_ok=%s, data_coverage=%s::jsonb, status='running', started_at=now() WHERE id=%s",
                  (entry_ok, json.dumps(source_state, ensure_ascii=False, default=str), run_id))
    else:
        
        c.execute("UPDATE ai_task_runs SET entry_ok=%s, status='running', started_at=now() WHERE id=%s", (entry_ok, run_id))
    c.commit()
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / f"brief_{shop}_{day:%Y%m%d}.txt"
    with open(path, "w") as fh:
        subprocess.run([sys.executable, "tools/ai_tasks/brief_ozon.py" if platform == "ozon" else "tools/ai_tasks/brief.py", str(shop), day.isoformat()], cwd=ROOT, stdout=fh,
                       env={**os.environ, "PYTHONPATH": "."}, timeout=1800, check=True)
    brief = path.read_text()
    acc = c.execute("SELECT coalesce(title, name) t FROM accounts WHERE id=%s", (shop,)).fetchone()["t"]
    from stometric import aireport
    with __import__('stometric.private_ai', fromlist=['scheduled_ai']).scheduled_ai(c):
        api_key = aireport.shop_key(c, shop, request['requested_by'] if request else None)
    if not api_key:
        raise ValueError('Нет доступа к выбранному маршруту ИИ кабинета')
    t0 = time.time()
    from tools.ai_tasks.codex_run import analyze
    res = analyze(brief, f"Разбор {platform}. Кабинет: {acc} (shop {shop}). Досье: {path}. Задачи на {day:%d.%m.%Y} (разбор дня {y:%d.%m.%Y}). "
                 "Ответ — только JSON по формату правил.", marketplace=platform, api_key=api_key)
    data = parse(str(res.get("result") or ""))
    try:
        out = ai_tasks.load(c, shop, day, run_id, data, brief, platform=platform)
    except ValueError:
        
        raise
    except Exception as error:
        raise RuntimeError('uncertain task persistence: ' + type(error).__name__) from error
    try:
        model = f"ИИ {res['model']}, этапов: {int(res.get('num_turns', 4))}"
        note = f"задач {out['saved']}" + (f", отброшено {len(out['dropped'])} (числа не из досье): " + json.dumps(out["dropped"], ensure_ascii=False)[:1500]
                                          if out["dropped"] else "")
        c.execute("""UPDATE ai_task_runs SET status='ok', finished_at=now(), summary=%s, model=%s, error=%s WHERE id=%s""",
                  (str(data.get("summary") or "")[:2000], model, note, run_id))
        c.commit()
    except Exception as error:
        
        
        raise RuntimeError('uncertain task completion: ' + type(error).__name__) from error
    log(shop, f"готово за {time.time() - t0:.0f} с:", note[:300])
    return out


def claim_run(c, s, day, now, *, force=False, retry_interrupted=False):
    """One short transaction shared with UI/Kit enqueue; never holds a lock over inference."""
    from stometric import analytics_requests
    analytics_requests.lock_queue(c, 'tasks', s)
    y = day - timedelta(days=1)
    last = c.execute("SELECT * FROM ai_task_runs WHERE account_id=%s AND day=%s ORDER BY id DESC LIMIT 1", (s, day)).fetchone()
    from stometric.entry_coverage import report_present
    platform = ai_tasks.marketplace(c, s)
    entry_now = report_present(c, s, y) if platform == "wb" else False
    attempt = ai_tasks.latest_attempt(c, s)
    if ai_tasks.retry_needs_review(attempt) and not retry_interrupted:
        log(s, "прерванный разбор требует выяснения причины и явного разрешения; автоматический повтор отключён")
        c.commit()
        return None
    if attempt and attempt["status"] == "running" and (not last or last["id"] != attempt["id"]):
        log(s, "есть незавершённый разбор; перед новым запуском проверьте причину остановки")
        c.commit()
        return None
    if force and last and last["status"] == "running":
        log(s, "есть незавершённый разбор; перед повтором проверьте причину остановки")
        c.commit()
        return None
    oz_improved = False
    if platform == "ozon" and last and last["status"] == "ok":
        from stometric.ozon_task_data import coverage
        current = coverage(c, s, y)
        previous = last.get("data_coverage") or {}
        
        oz_improved = any(set(v.get(field, [])) - set(previous.get("sources", {}).get(k, {}).get(field, []))
                          for k, v in current.get("sources", {}).items()
                          for field in ("days", "days_basic", "days_full"))
    
    
    n_runs = c.execute("""SELECT count(*) n FROM ai_task_runs WHERE account_id=%s AND day=%s AND status <> 'requested'
                          AND coalesce(error, '') NOT ILIKE '%%limit%%'""", (s, day)).fetchone()["n"]
    why = None
    if last and last["status"] == "requested":
        why = "по кнопке"
    elif force:
        why = "вручную"
    elif (now.hour, now.minute) < START_MSK:
        c.commit()
        return None
    elif not last:
        why = "утренний разбор"
    elif last["status"] == "ok" and last["entry_ok"] is False and entry_now and now.hour < REBUILD_UNTIL_H:
        why = "появились точки входа за вчера"
    elif oz_improved and n_runs < 3 and now.hour < REBUILD_UNTIL_H:
        why = "появились недостающие данные Ozon"
    elif last["status"] == "error" and n_runs < 3 and last["started_at"] < datetime.now(timezone.utc) - timedelta(minutes=30):
        why = "повтор после ошибки"
    elif last["status"] == "running" and last["started_at"] < datetime.now(timezone.utc) - timedelta(hours=2):
        c.execute("UPDATE ai_task_runs SET status='error', error='прервано' WHERE id=%s", (last["id"],))
        c.commit()
        return None
    if not why:
        c.commit()
        return None
    if last and last["status"] == "requested":
        claimed = c.execute("UPDATE ai_task_runs SET status='running', started_at=now() WHERE id=%s AND status='requested' RETURNING id", (last['id'],)).fetchone()
        if not claimed:
            c.commit()
            return None
        rid = claimed['id']
        c.commit()
    else:
        rid = c.execute("INSERT INTO ai_task_runs(account_id, day) VALUES (%s, %s) RETURNING id", (s, day)).fetchone()["id"]
        c.commit()
    return rid, why



def main():
    args = sys.argv[1:]
    only = int(args[args.index("--shop") + 1]) if "--shop" in args else None
    force = "--force" in args
    retry_interrupted = "--retry-interrupted" in args
    if retry_interrupted and (not force or only is None):
        raise ValueError("--retry-interrupted требует --shop N --force после выяснения причины и разрешения на повтор")
    WORK.mkdir(parents=True, exist_ok=True)
    lock = open(WORK / "run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("уже идёт другой запуск")
        return
    c = connect()
    shops = [s for s in ai_tasks.enabled_shops(c) if only is None or s == only]
    for s in shops:
        try:
            ai_tasks.check(c, s)
        except Exception as e:  
            c.rollback()
            log(s, "автоотметки: ошибка", e)
    now = datetime.now(MSK)
    day = today_msk()
    for s in shops:
        claim = claim_run(c, s, day, now, force=force, retry_interrupted=retry_interrupted)
        if claim is None:
            continue
        rid, why = claim
        log(s, "разбор:", why)
        try:
            build(c, s, rid, day)
        except Exception as e:  
            c.rollback()
            error = ('uncertain execution: ' + type(e).__name__
                     if isinstance(e, (MemoryError, TimeoutError, subprocess.TimeoutExpired)) else str(e)[:2000])
            c.execute("UPDATE ai_task_runs SET status='error', finished_at=now(), error=%s WHERE id=%s", (error, rid))
            c.commit()
            log(s, "ошибка:", e)


if __name__ == "__main__":
    main()

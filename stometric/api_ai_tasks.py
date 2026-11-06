"""API блока «🧠 Задачи от нейросети» на Главной (ai_tasks): задачи на сегодня / вчера / неделю, отметки, оценки, пересборка."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel

from . import ai_tasks, auth
from .config import today_msk
from .web import conn, current_user

router = APIRouter()


def _role(c, u, shop_id: int, need: str = "viewer") -> str:
    role = auth.shop_role(c, u, shop_id)
    if not auth.can(role, need):
        raise HTTPException(403, "Нет доступа к магазину" if need == "viewer" else "Нужна роль «редактор» или выше")
    return role


@router.get("/api/shops/{shop_id}/ai_tasks")
def tasks_get(shop_id: int, u=Depends(current_user), c=Depends(conn)):
    role = _role(c, u, shop_id)
    if not ai_tasks.is_enabled(c, shop_id):
        return {"enabled": False}
    d = today_msk()
    rows = c.execute("""SELECT t.*, (SELECT name FROM users x WHERE x.id=t.status_user) status_who FROM ai_tasks t
                        WHERE t.account_id=%s AND t.active AND t.day >= %s ORDER BY t.day DESC, t.priority DESC, t.effect_week DESC NULLS LAST""",
                     (shop_id, d - timedelta(days=6))).fetchall()
    fb = {}
    for f in c.execute("SELECT task_id, user_id, rating, comment FROM ai_task_feedback WHERE task_id = ANY(%s)", ([r["id"] for r in rows],)):
        x = fb.setdefault(f["task_id"], {"mine": None, "up": 0, "down": 0, "comments": []})
        x["up"] += f["rating"] == 1
        x["down"] += f["rating"] == -1
        if f["comment"]:
            x["comments"].append(f["comment"])
        if f["user_id"] == u["id"]:
            x["mine"] = {"rating": f["rating"], "comment": f["comment"]}
    runs = {r["day"]: r for r in c.execute("""SELECT DISTINCT ON (day) id, day, status, entry_ok, data_coverage, summary, started_at, finished_at FROM ai_task_runs
                                              WHERE account_id=%s AND day >= %s ORDER BY day, id DESC""", (shop_id, d - timedelta(days=6)))}
    from .entry_coverage import report_present
    entry_day = d - timedelta(days=1)
    platform = ai_tasks.marketplace(c, shop_id)
    entry_present = report_present(c, shop_id, entry_day) if platform == "wb" else None
    source_state = None
    if platform == "ozon":
        from .ozon_task_data import coverage
        source_state = coverage(c, shop_id, entry_day)
    keys = ("id", "run_id", "day", "title", "why", "steps", "tag", "certainty", "effect_week", "priority", "nm_ids", "vc", "check_spec", "status",
            "status_by", "status_note", "status_at", "status_who", "outcome", "created_at")
    tasks = [{**{k: r[k] for k in keys}, "feedback": fb.get(r["id"])} for r in rows]
    photo = {}
    ids = sorted({n for t in tasks for n in (t["nm_ids"] or [])[:1]})
    if ids and platform == "ozon":
        photo = {r["sku"]: r["photo"] for r in c.execute(
            "SELECT sku, photo FROM oz_products WHERE account_id=%s AND sku = ANY(%s)", (shop_id, ids))}
    elif ids:
        photo = {r["nm_id"]: r["ph"] for r in c.execute("""SELECT nm_id, data->'photos'->0->>'tm' ph FROM nomenclature
                                                          WHERE account_id=%s AND nm_id = ANY(%s)""", (shop_id, ids))}
    for t in tasks:
        t["photo"] = photo.get((t["nm_ids"] or [None])[0])
    return jsonable_encoder({"enabled": True, "today": d, "runs": runs, "tasks": tasks, "tags": ai_tasks.TAGS, "cert": ai_tasks.CERT,
                             "entry_day": entry_day, "entry_present": entry_present, "marketplace": platform, "coverage": source_state,
                             "status_t": ai_tasks.STATUS_T, "can_edit": auth.can(role, "editor")})


class FeedbackIn(BaseModel):
    id: int
    rating: int | None = None
    comment: str | None = None


@router.post("/api/shops/{shop_id}/ai_tasks/feedback")
def tasks_feedback(shop_id: int, body: FeedbackIn, u=Depends(current_user), c=Depends(conn)):
    """👍/👎 и комментарий к задаче — по ним нейросеть дорабатывает советы (видит их в досье каждое утро)."""
    _role(c, u, shop_id)
    if body.rating not in (None, 1, -1):
        raise HTTPException(400, "Оценка: 1 или -1")
    if not c.execute("SELECT 1 FROM ai_tasks WHERE id=%s AND account_id=%s", (body.id, shop_id)).fetchone():
        raise HTTPException(404, "Задача не найдена")
    comment = (body.comment or "").strip()[:2000] or None
    if body.rating is None and not comment:
        c.execute("DELETE FROM ai_task_feedback WHERE task_id=%s AND user_id=%s", (body.id, u["id"]))
    else:
        c.execute("""INSERT INTO ai_task_feedback(task_id, user_id, account_id, rating, comment) VALUES (%s,%s,%s,%s,%s)
                     ON CONFLICT (task_id, user_id) DO UPDATE SET rating=EXCLUDED.rating, comment=EXCLUDED.comment, updated_at=now()""",
                  (body.id, u["id"], shop_id, body.rating, comment))
    c.commit()
    return {"ok": True}


class StatusIn(BaseModel):
    id: int
    status: str
    note: str | None = None


@router.post("/api/shops/{shop_id}/ai_tasks/status")
def tasks_status(shop_id: int, body: StatusIn, u=Depends(current_user), c=Depends(conn)):
    """Отметка вручную (автоматика её больше не трогает); «new» — вернуть автоотметки."""
    _role(c, u, shop_id, "editor")
    if body.status not in ai_tasks.STATUS_T:
        raise HTTPException(400, "Неизвестный статус")
    manual = body.status != "new"
    r = c.execute("""UPDATE ai_tasks SET status=%s, status_by=%s, status_note=%s, status_at=now(), status_user=%s,
                     done_at = CASE WHEN %s IN ('done','partial') THEN coalesce(done_at, now()) ELSE done_at END
                     WHERE id=%s AND account_id=%s RETURNING id""",
                  (body.status, "manual" if manual else None, (body.note or "").strip()[:500] or None, u["id"] if manual else None,
                   body.status, body.id, shop_id)).fetchone()
    if not r:
        raise HTTPException(404, "Задача не найдена")
    c.commit()
    return {"ok": True}


@router.post("/api/shops/{shop_id}/ai_tasks/rebuild")
def tasks_rebuild(shop_id: int, u=Depends(current_user), c=Depends(conn), *, request_key: str | None = None):
    """Пересобрать задачи на сегодня (например, после докачки точек входа) — подхватит таймер в течение 10 минут."""
    _role(c, u, shop_id, "editor")
    if not ai_tasks.is_enabled(c, shop_id):
        raise HTTPException(400, "Блок не включён для магазина")
    from .private_ai import require_owner_shop
    require_owner_shop(c, shop_id, u["id"])
    from . import analytics_requests
    analytics_requests.validate_key(request_key)
    if ai_tasks.marketplace(c, shop_id) not in ('wb', 'ozon'):
        raise HTTPException(400, 'Разбор этой площадки пока не поддерживается')
    d = today_msk()
    analytics_requests.lock_queue(c, 'tasks', shop_id)
    previous_id = analytics_requests.reference(c, request_key, 'tasks', shop_id, u['id'])
    if previous_id is not None:
        previous = c.execute('SELECT id,status FROM ai_task_runs WHERE id=%s AND account_id=%s',
                             (previous_id, shop_id)).fetchone()
        if previous is None:
            raise HTTPException(409, 'Состояние предыдущего запроса не подтверждено; повтор не выполнен.')
        c.commit()
        return {'message': 'Возвращаю состояние прежнего запроса, без повторной постановки.',
                'run_id': previous['id'], 'status': previous['status'], 'created': False, 'replayed': True}
    
    
    if ai_tasks.retry_needs_review(ai_tasks.latest_attempt(c, shop_id)):
        c.rollback()
        raise HTTPException(409, 'Предыдущий разбор прерван или остановлен из-за памяти. Сначала нужно выяснить причину; повтор не выполнен.')
    busy = c.execute("SELECT id,status FROM ai_task_runs WHERE account_id=%s AND status IN ('requested','running') ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,id DESC LIMIT 1", (shop_id,)).fetchone()
    if busy:
        analytics_requests.remember(c, request_key, 'tasks', shop_id, u['id'], busy['id'])
        c.commit()
        return {"message": "Разбор уже " + ("идёт" if busy["status"] == "running" else "в очереди") + " — задачи обновятся сами.",
                'run_id': busy['id'], 'status': busy['status'], 'created': False}
    if request_key:
        from .kit_analytics import source_coverage
        coverage = source_coverage(c, shop_id, ai_tasks.marketplace(c, shop_id), d - timedelta(days=1))
        if not coverage.get('ready'):
            c.commit()
            return {'message': 'Источники для порученного разбора неполны; новый запуск не поставлен.',
                    'status': 'blocked', 'run_id': None, 'created': False, 'source_coverage': coverage}
    row = c.execute("INSERT INTO ai_task_runs(account_id, day, status, requested_by,request_key) VALUES (%s, %s, 'requested', %s,%s) RETURNING id",
                    (shop_id, d, u["id"], request_key)).fetchone()
    analytics_requests.remember(c, request_key, 'tasks', shop_id, u['id'], row['id'])
    c.commit()
    return {"message": "Поставил в очередь: разбор начнётся в течение 10 минут и займёт 10–30 минут.",
            'run_id': row['id'], 'status': 'requested', 'created': True}

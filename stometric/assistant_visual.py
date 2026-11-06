"""Self-hosted application component."""

from . import auth, db, visual, visual_ai

TOOLS = [
    {"name": "visual_prepare", "description": "ТЗ на визуал (слайды карточки) по регламенту инфографики для артикула WB: заводит проект в разделе «Визуал», "
     "при необходимости берёт фото с карточки как исходники и фоном (10-20 минут) делает разбор слайдов конкурентов, ответы на вопросы о товаре и ЦА, "
     "цели слайдов и воронки, ТЗ. first_n - сколько вариантов первого слайда (1-6, по умолчанию 3). note - уточнение пользователя.",
     "input_schema": {"type": "object", "properties": {"nm_id": {"type": "integer"}, "first_n": {"type": "integer"}, "note": {"type": "string"},
                                                       "shop_id": {"type": "integer"}}, "required": ["nm_id"]}},
    {"name": "visual_status", "description": "Состояние визуала по артикулу: какие шаги готовы, версия и статус ТЗ, сколько исходников, есть ли паспорт.",
     "input_schema": {"type": "object", "properties": {"nm_id": {"type": "integer"}, "shop_id": {"type": "integer"}}, "required": ["nm_id"]}},
]

PROMPT = """
- Визуал карточки (слайды по регламенту инфографики): visual_prepare запускает фоном разбор конкурентов, вопросы о товаре и ЦА, цели, воронки и ТЗ;
  visual_status - что готово. Это четвёртое исключение из «ничего не меняешь»: можно завести проект визуала и черновик ТЗ, но согласует ТЗ
  и рисует слайды только человек на сайте (раздел «Визуал»). Паспорт товара и свои фото пользователь прикрепляет там же."""


def t_prepare(c, shop: int, uid: int, a: dict) -> dict:
    u = c.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    if not auth.can(auth.shop_role(c, u, shop), "editor"):
        return {"error": "Готовить визуал может редактор магазина и выше"}
    if c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"] != "wb":
        return {"error": "Визуал пока только для WB"}
    nm = int(a["nm_id"])
    with db.connect() as w:
        try:
            pid = visual.create(w, shop, uid, nm, "", "")
            if a.get("note"):
                w.execute("UPDATE vis_projects SET note=%s WHERE id=%s", (str(a["note"])[:2000], pid))
            if not visual.files(w, pid):
                visual.import_card_photos(w, shop, pid, nm, uid)
            w.commit()
        except visual.VisualError as e:
            return {"error": str(e)}
    ok = visual_ai.start(shop, pid, ["passport", "competitors", "answers", "goals", "brief"] if
                         c.execute("SELECT passport_id FROM vis_projects WHERE id=%s", (pid,)).fetchone()["passport_id"]
                         else ["competitors", "answers", "goals", "brief"], uid, max(1, min(6, int(a.get("first_n") or 3))))
    return {"started": ok, "project_id": pid,
            "note": "Запущено: конкуренты → вопросы → цели → ТЗ, 10-20 минут. Смотреть: сайт → «Визуал» → товар. Свои фото и паспорт можно добавить там же."
            if ok else "По этому товару нейросеть уже работает - загляни в «Визуал» позже."}


def t_status(c, shop: int, uid: int, a: dict) -> dict:
    nm = int(a["nm_id"])
    p = c.execute("SELECT * FROM vis_projects WHERE account_id=%s AND nm_id=%s AND NOT archived", (shop, nm)).fetchone()
    if not p:
        return {"project": None, "note": "Визуал по этому артикулу ещё не начат"}
    b = visual.brief_latest(c, p["id"])
    return {"project_id": p["id"], "sources": len(visual.files(c, p["id"])), "passport": bool(p["passport_id"]), "passport_model": p["passport_model"],
            "jobs": {k: {"state": v["state"], "summary": v["summary"], "error": v["error"]} for k, v in visual_ai.jobs(c, p["id"]).items()},
            "brief": b and {"version": b["version"], "state": b["state"], "slides": len((b["data"] or {}).get("slides") or []),
                            "first_variants": len((b["data"] or {}).get("first_slides") or []), "review_comment": b["review_comment"]}}


TOOL_FN = {"visual_prepare": t_prepare, "visual_status": t_status}

"""Self-hosted application component."""

from . import auth, seo_core, seo_write

TOOLS = [
    {"name": "seo_prepare", "description": "SEO карточки WB по артикулу: собрать ядро ключей (Джем, реклама, конкуренты и подсказки WB), "
     "написать название и описание с полным вхождением ключей (проверяет код) и отправить на согласование менеджеру артикула. "
     "Идёт фоном 1-4 минуты; результат - на сайте, раздел «SEO». note - уточнение пользователя к тексту. submit=false - только черновик, без согласования.",
     "input_schema": {"type": "object", "properties": {"nm_id": {"type": "integer"}, "note": {"type": "string"}, "submit": {"type": "boolean"},
                                                       "shop_id": {"type": "integer"}}, "required": ["nm_id"]}},
    {"name": "seo_status", "description": "Состояние SEO по артикулу: собрано ли ядро, главный ключ и ядро, проверка текста (покрытие ключей, "
     "главный ключ в начале, длина), согласование.",
     "input_schema": {"type": "object", "properties": {"nm_id": {"type": "integer"}, "shop_id": {"type": "integer"}}, "required": ["nm_id"]}},
]

PROMPT = """
- SEO карточки (ключи, текст с полным вхождением, согласование): seo_prepare запускает всё фоном и отправляет менеджеру на согласование,
  seo_status - что уже готово. Это третье исключение из «ничего не меняешь»: можно создать черновик текста и заявку на согласование,
  но загрузить в WB может только человек кнопкой на сайте (раздел «SEO» → «На согласовании»). Скажи пользователю, где смотреть."""


def t_prepare(c, shop: int, uid: int, a: dict) -> dict:
    u = c.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    if not auth.can(auth.shop_role(c, u, shop), "editor"):
        return {"error": "Готовить SEO может редактор магазина и выше"}
    if c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"] != "wb":
        return {"error": "SEO пока только для WB"}
    nm = int(a["nm_id"])
    if not c.execute("SELECT 1 FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone():
        return {"error": f"Артикула {nm} нет в этом магазине"}
    ok = seo_write.pipeline_start(shop, nm, uid, (a.get("note") or "").strip()[:2000] or None, a.get("submit") is not False)
    return {"started": ok, "note": "Запущено: ядро → текст → согласование, 1-4 минуты. Смотреть: сайт → «SEO» → артикул." if ok
            else "По этому артикулу уже идёт работа - загляни в «SEO» через пару минут."}


def t_status(c, shop: int, uid: int, a: dict) -> dict:
    nm = int(a["nm_id"])
    v = seo_core.view(c, shop, nm)
    main, core = seo_core.core(c, shop, nm)
    d = c.execute("""SELECT seo, review_state, review_comment, changes ? 'description' has_text FROM card_drafts
                     WHERE account_id=%s AND nm_id=%s AND status='draft' ORDER BY id DESC LIMIT 1""", (shop, nm)).fetchone()
    return {"core_built_at": v["built_at"], "core_state": v["state"], "keys_total": len(v["rows"]), "main": main, "core": core,
            "job": seo_write.job(c, shop, nm), "draft": d and {"check": {k: (d["seo"] or {}).get(k) for k in
                                                               ("coverage", "missing", "main_in_lead", "desc_len", "title_len", "ok")},
                                                     "review_state": d["review_state"], "review_comment": d["review_comment"], "has_text": d["has_text"]}}


TOOL_FN = {"seo_prepare": t_prepare, "seo_status": t_status}

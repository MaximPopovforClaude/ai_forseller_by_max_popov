"""Self-hosted application component."""

import json

from . import kb

TOOLS = [
    {"name": "kb_find", "description": "База знаний рабочего пространства: разделы и подразделы (дерево) и поиск материалов по словам "
     "(название, описание, текст документа, раздел). Пустой query — только дерево разделов и последние материалы. "
     "Для найденных документов отдаёт отрывок текста — им можно отвечать на вопросы по регламентам.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "shop_id": {"type": "integer"}}}},
    {"name": "kb_fetch", "description": "Что по ссылке (только чтение): карточка Wildberries — название, бренд, категория, описание, "
     "характеристики; другая страница — заголовок, описание, начало текста; документ Google — только тип. Используй перед kb_add для ссылки.",
     "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "kb_add", "description": "Добавить материал в базу знаний: ссылку (url) или файл из этого чата (file — имя вложения). "
     "section — раздел, subsection — подраздел (по смыслу; бери существующие из kb_find, если подходят; нет — будут созданы). "
     "title — короткое понятное название, description — 1-3 предложения: что это и чем полезно (по словам пользователя и содержимому). "
     "shop_only=true — только для текущего магазина (если пользователь так сказал), иначе — всему рабочему пространству.",
     "input_schema": {"type": "object", "properties": {
         "url": {"type": "string"}, "file": {"type": "string"}, "note": {"type": "string", "description": "текст заметки / регламента, если это не ссылка и не файл"},
         "title": {"type": "string"}, "description": {"type": "string"}, "section": {"type": "string"}, "subsection": {"type": "string"},
         "shop_only": {"type": "boolean"}, "shop_id": {"type": "integer"}},
         "required": ["title", "description", "section"]}},
]

PROMPT = """
- База знаний пространства (регламенты, документы, ссылки, фото, карточки конкурентов): kb_find. На вопросы «где регламент…», «как у нас
  принято…» сначала ищи в базе знаний и ссылайся на найденный материал.
- Если пользователь присылает ссылку или файл и просит сохранить / добавить в базу знаний (или пишет, что это за материал, «в базу») -
  добавь сам: для ссылки kb_fetch, потом kb_find (какие разделы уже есть), потом kb_add с разделом и подразделом по смыслу (существующие,
  если подходят), коротким названием и описанием 1-3 предложения. Ответь одной строкой: куда добавил и как назвал. Это второе
  исключение из правила «ничего не меняешь»: в базу знаний можно добавлять без отдельного подтверждения."""


def _user(c, uid: int) -> dict:
    return c.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()


def _ws(c, shop: int) -> int:
    return c.execute("SELECT workspace_id FROM accounts WHERE id=%s", (shop,)).fetchone()["workspace_id"]


def t_find(c, shop: int, uid: int, a: dict, *, user: dict | None = None) -> dict:
    
    u, ws = user if user is not None else _user(c, uid), _ws(c, shop)
    if not u or u["id"] != uid:
        return {"error": "нет доступа к базе знаний"}
    if not kb.can_read(c, u, ws):
        return {"error": "нет доступа к базе знаний"}
    q = (a.get("query") or "").strip()
    rows = kb.items(c, u, ws, None, q, None, limit=15 if q else 10)
    if q and not rows:                                   
        seen = {}
        for w in [x for x in q.split() if len(x) >= 4][:5]:
            for r in kb.items(c, u, ws, None, w, None, limit=8):
                seen.setdefault(r["id"], r)
        rows = list(seen.values())[:15]
    full = {r["id"]: r for r in c.execute("SELECT id, text, body FROM kb_items WHERE id = ANY(%s)", ([r["id"] for r in rows],))}
    out = []
    for i, r in enumerate(rows):
        x = {"id": r["id"], "kind": r["kind"], "title": r["title"], "description": r["description"], "url": r["url"],
             "file": r["file_name"], "section": " → ".join(t for t in (r["parent"], r["section"]) if t) or "без раздела",
             "shop_only": r["shop"], "added": f"{r['created_at']:%d.%m.%Y}", "by": r["author"]}
        if q and i < 3:
            t = (full[r["id"]]["body"] or full[r["id"]]["text"] or "")
            if t:
                x["text_excerpt"] = t[:3000]
        out.append(x)
    tree = [{"section": s["title"], "subsections": [x["title"] for x in s["subs"]], "items": s["total"]} for s in kb.tree(c, u, ws)]
    return {"result": {"sections": tree, "items": out, "can_add": kb.can_add(c, u, ws),
                       "link": "Материалы открываются на странице «📚 База знаний» в меню сайта"}}


def t_fetch(c, shop: int, uid: int, a: dict) -> dict:
    return {"result": kb.fetch(c, a.get("url") or "")}


def t_add(c, shop: int, uid: int, a: dict) -> dict:
    """Только проверка и подготовка; запись — apply() на обычном соединении."""
    u, ws = _user(c, uid), _ws(c, shop)
    sid = shop if a.get("shop_only") else None
    if not kb.can_add(c, u, ws, sid):
        return {"error": "Добавлять в базу знаний может редактор и выше — у пользователя роль ниже. Скажи ему об этом."}
    if not (a.get("url") or a.get("file") or a.get("note")):
        return {"error": "нужна ссылка (url), файл из чата (file) или текст заметки (note)"}
    return {"kb_add": {**{k: a.get(k) for k in ("url", "file", "note", "title", "description", "section", "subsection")}, "shop_id": sid},
            "result": {}}


def apply(c, shop: int, uid: int, d: dict, chat_id: int) -> dict:
    """Запись материала, подготовленного t_add. → результат для нейросети."""
    from .assistant import files_dir
    u, ws = _user(c, uid), _ws(c, shop)
    try:
        sec = kb.resolve_section(c, u, ws, d.get("section"), d.get("subsection"))
        file = None
        if d.get("file"):
            rows = c.execute("SELECT * FROM assistant_files WHERE chat_id=%s ORDER BY id DESC", (chat_id,)).fetchall()
            f = next((r for r in rows if r["name"].lower() == d["file"].lower()), None) or\
                next((r for r in rows if d["file"].lower() in r["name"].lower()), None)
            if not f:
                return {"error": f"в чате нет файла «{d['file']}»; файлы чата: {[r['name'] for r in rows[:10]]}"}
            file = (f["name"], (files_dir() / f["path"]).read_bytes())
        kind = "file" if file else "link" if d.get("url") else "note"
        text = None
        if kind == "link":
            info = kb.fetch(c, d["url"])
            text = json.dumps({k: v for k, v in info.items() if k not in ("photo", "image")}, ensure_ascii=False)[:kb.TEXT_MAX]
        iid = kb.add(c, u, ws, kind=kind, title=d.get("title") or "", url=d.get("url"), body=d.get("note"), description=d.get("description"),
                     section_id=sec, shop_id=d.get("shop_id"), source="assistant", file=file, text=text)
    except kb.KbError as e:
        c.rollback()
        return {"error": str(e)}
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action,details) VALUES (%s,%s,'kb/add',%s)",
              (uid, ws, json.dumps({"id": iid, "by": "assistant"}, ensure_ascii=False)))
    where = " → ".join(x for x in (d.get("section"), d.get("subsection")) if x)
    return {"result": {"ok": True, "id": iid, "where": where or "без раздела", "title": d.get("title"),
                       "visible": "только магазину" if d.get("shop_id") else "всему рабочему пространству"}}


TOOL_FN = {"kb_find": t_find, "kb_fetch": t_fetch, "kb_add": t_add}

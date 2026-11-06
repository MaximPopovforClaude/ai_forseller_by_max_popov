"""Self-hosted application component."""

import json
import time
from datetime import timedelta

from . import db, market
from .config import today_msk

ALLOWED = {"get_external_analytics", "get_external_trends", "get_article_dynamics", "get_article_frequency", "get_seller_dynamics",
           "get_subjects_grouped", "list_external_catalog", "list_sources",
           "find_bloggers_for_subject", "search_bloggers", "suggest_bloggers", "count_bloggers", "count_posts", "search_posts",
           "get_blogger_card", "get_blogger_scorecard", "get_blogger_subjects", "get_blogger_top_posts",
           "get_cross_mp_statistics", "find_product_by_identifier", "list_cabinets"}
TTL_H = 6
TITLES = {"id": "Артикул WB", "name": "Название", "brand": "id бренда", "seller": "id продавца", "is_new": "Новинка (Wildbox)", "create_date": "Создана", "proceeds": "Выручка, ₽",
          "orders": "Заказы, шт", "price": "Цена, ₽", "old_price": "Цена до скидки, ₽", "discount": "Скидка, %", "quantity": "Остаток, шт",
          "rating": "Рейтинг", "reviews": "Отзывы", "subject_name": "Предмет", "lost_proceeds": "Упущенная выручка, ₽",
          "in_stock_percent": "В наличии, % дней", "sales_percent": "Выкуп, %"}
SKIP = {"image", "is_adult", "is_deleted", "dynamic", "promos", "item"}

TOOLS = [
    {"name": "wildbox_help", "description": "Справка Wildbox MCP (рынок WB: чужие товары, конкуренты, ниши, запросы, СПП предметов, бренды, "
     "продавцы, блогеры; кабинеты пользователя в Wildbox). Без uri - список инструментов Wildbox с параметрами и список схем "
     "get_external_analytics. uri - справочник схемы: config://external-analytics/schemas/<схема>/query_params (фильтры) или "
     ".../extra_fields (метрики). Лимит Wildbox не тратит.",
     "input_schema": {"type": "object", "properties": {"uri": {"type": "string"}, "shop_id": {"type": "integer"}}}},
    {"name": "wildbox", "description": "Вызвать инструмент Wildbox MCP (только чтение) с аргументами args, как в его описании из wildbox_help. "
     "Каждый вызов - до 10-30 с (лимит Wildbox), повторы за 6 ч - из кэша. Если в ответе строки товаров: new_days - оставить только "
     "карточки, созданные за последние N дней (по create_date); sort - поле для сортировки по убыванию (например proceeds); "
     "top - сколько строк оставить (по умолчанию 30); show=true - показать таблицу пользователю.",
     "input_schema": {"type": "object", "properties": {
         "tool": {"type": "string", "description": "имя инструмента Wildbox, например get_external_analytics"},
         "args": {"type": "object", "description": "аргументы инструмента"},
         "new_days": {"type": "integer"}, "sort": {"type": "string"}, "top": {"type": "integer"}, "show": {"type": "boolean"},
         "shop_id": {"type": "integer"}}, "required": ["tool", "args"]}},
]

PROMPT = """
- Рынок и конкуренты (чужие товары WB, новинки, топы выдачи, ниши, запросы, СПП предмета, бренды, продавцы, блогеры) - Wildbox:
  wildbox_help (какие инструменты и схемы есть, их фильтры) и wildbox (вызов). Не говори «нет доступа к Wildbox», пока не попробовал;
  если ключа нет - инструмент так и скажет, передай пользователю. Вызов Wildbox медленный (10-30 с): не больше 3-4 вызовов на ответ.
  Частые рецепты (схема external.products.top, инструмент get_external_analytics):
  * топ / новинки по запросу или категории: args {{"schema_name": "external.products.top", "params": {{"wb_search": "<фраза, как ищет
    покупатель, например «сироп для кофе»>", "period": 30}}, "extra_fields": "proceeds,orders,price,quantity"}}
    (rating и reviews строят ряд по дням и раздувают ответ - Wildbox отбросит строки; их - только для 1-20 артикулов);
    для новинок добавь new_days (30 - за месяц) и sort "proceeds". «Мои категории» - сначала find_products (предметы магазина),
    потом поиск по 1-2 главным предметам.
  * конкретные артикулы: params {{"product_ids": "123,456", "period": 30}}; похожие на наш товар: params {{"similar": <nm_id>, "period": 30}}.
  Другие задачи (ниши, запросы, сезонность, СПП предмета, бренды, продавцы) - сначала wildbox_help, выбери схему, посмотри её query_params.
  Цифры Wildbox - оценка рынка по данным Wildbox, а не данные кабинета: так и подписывай («по Wildbox»)."""

_HELP: dict = {}


def _tok(c, shop: int) -> str | None:
    return market.shop_token(c, shop)


def t_help(c, shop: int, uid: int, a: dict) -> dict:
    tok = _tok(c, shop)
    if not tok:
        return {"error": market.NO_KEY}
    uri = (a.get("uri") or "").strip()
    key = market._tid(tok) + "|" + uri
    hit = _HELP.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    cl = market._Client(tok)
    if uri:
        if not uri.startswith(("config://external-analytics/", "config://cross-mp-analytics/")):
            return {"error": "uri - только справочники схем config://external-analytics/... или config://cross-mp-analytics/..."}
        r = cl._rpc("resources/read", {"uri": uri})
        text = ((r.get("result") or {}).get("contents") or [{}])[0].get("text") or ""
        if not text:
            return {"error": "нет такого справочника: " + json.dumps(r.get("error") or {}, ensure_ascii=False)[:200]}
        out = {"uri": uri, "text": text[:14000], "cut": len(text) > 14000}
    else:
        tools = [{"name": t["name"], "description": (t.get("description") or "")[:400],
                  "args": {k: (v.get("description") or "")[:120] for k, v in ((t.get("inputSchema") or {}).get("properties") or {}).items()},
                  "required": (t.get("inputSchema") or {}).get("required")}
                 for t in (cl._rpc("tools/list", {}).get("result") or {}).get("tools") or [] if t["name"] in ALLOWED]
        r = cl._rpc("resources/read", {"uri": "config://external-analytics/schemas/list"})
        raw = ((r.get("result") or {}).get("contents") or [{}])[0].get("text") or "{}"
        schemas = [{"name": s["name"], "what": s["description"].split("USE FOR")[0].strip()[:150], "available": s.get("available")}
                   for s in json.loads(raw, strict=False).get("schemas") or []]
        out = {"tools": tools, "external_analytics_schemas": schemas,
               "schema_help": "config://external-analytics/schemas/<schema_name>/query_params и /extra_fields"}
    _HELP[key] = (time.time(), out)
    return out


def _call_cached(tok: str, tool: str, args: dict):
    key = f"mcp|{market._tid(tok)}|{tool}|" + json.dumps(args, sort_keys=True, ensure_ascii=False)
    with db.connect() as w:
        hit = w.execute("SELECT data FROM market_cache WHERE key=%s AND fetched_at > now() - make_interval(hours => %s)", (key, TTL_H)).fetchone()
        if hit:
            return hit["data"].get("v"), True
        res = market._call(tok, tool, **args)
        w.execute("INSERT INTO market_cache(key,data) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET data=EXCLUDED.data, fetched_at=now()",
                  (key, json.dumps({"v": res}, ensure_ascii=False, default=str)))
        w.commit()
        return res, False


def t_call(c, shop: int, uid: int, a: dict) -> dict:
    tool = (a.get("tool") or "").strip()
    if tool not in ALLOWED:
        return {"error": f"инструмента Wildbox «{tool}» нет в доступных: {sorted(ALLOWED)}"}
    tok = _tok(c, shop)
    if not tok:
        return {"error": market.NO_KEY}
    args = a.get("args") or {}
    if not isinstance(args, dict):
        return {"error": "args - объект с аргументами инструмента"}
    if tool == "get_external_analytics" and a.get("new_days") and not args.get("max_rows"):
        args = {**args, "max_rows": 100}         
    try:
        res, cached = _call_cached(tok, tool, args)
    except market.WildboxError as e:
        return {"error": f"Wildbox: {e}"}
    rows = res.get("rows") if isinstance(res, dict) else res if isinstance(res, list) else None
    if not (isinstance(rows, list) and rows and isinstance(rows[0], dict)):
        return {"result": res, "cached": cached}
    total = len(rows)
    note = []
    if a.get("new_days"):
        since = str(today_msk() - timedelta(days=int(a["new_days"])))
        rows = [r for r in rows if str(r.get("create_date") or "") >= since]
        note.append(f"новинки: карточки, созданные с {since} - {len(rows)} из {total}")
    if a.get("sort"):
        f = a["sort"].lstrip("-")
        rows = sorted(rows, key=lambda r: (r.get(f) is not None, r.get(f) if isinstance(r.get(f), (int, float)) else 0), reverse=True)
    top = max(1, min(int(a.get("top") or 30), 100))
    rows = rows[:top]
    fields = [k for k in (rows[0] if rows else {}) if k not in SKIP and not any(isinstance(r.get(k), (dict, list)) for r in rows)]
    fields = sorted(fields, key=lambda k: list(TITLES).index(k) if k in TITLES else 99)
    clean = [{k: r.get(k) for k in fields} for r in rows]
    for r, src in zip(clean, rows):
        if src.get("id") and tool == "get_external_analytics":
            r["url"] = f"https://www.wildberries.ru/catalog/{src['id']}/detail.aspx"
    cols = [{"field": k, "title": TITLES.get(k, k), "type": "text" if k in ("name", "brand", "seller", "create_date", "subject_name") else
             "int" if k == "id" else "money" if k in ("proceeds", "price", "old_price", "lost_proceeds") else "num"} for k in fields]
    if clean and "url" in clean[0]:
        cols.append({"field": "url", "title": "Ссылка", "type": "text"})
    meta = {k: v for k, v in res.items() if k not in ("rows", "dynamic")} if isinstance(res, dict) else {}
    out = {"table": {"title": "Wildbox · " + ((args.get("schema_name") or tool) if isinstance(args, dict) else tool), "columns": cols, "rows": clean},
           "rows_from_wildbox": total, "cached": cached, "meta": json.dumps(meta, ensure_ascii=False, default=str)[:1500]}
    if note:
        out["note"] = "; ".join(note)
    return out


TOOL_FN = {"wildbox_help": t_help, "wildbox": t_call}

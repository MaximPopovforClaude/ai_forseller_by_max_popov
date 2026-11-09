"""ИИ-сводка на главной: серверный маршрут магазина → разделы по нашим правилам.

Данные собирает код (aipack), нейросеть только пишет текст по ним. VIP использует подписку владельца в пределах разрешённых
магазинов и участников. Разделы «конкуренты» и «ниша» — только если у кабинета есть ключ Wildbox (≈7 вызовов Wildbox на ключевой товар).
Правила разбора (RULES) — наши; меняются здесь.
"""

import json
import subprocess
from datetime import timedelta

from .config import today_msk

MODEL = "claude-sonnet-5-5"

RULES = """Ты аналитик магазина на Wildberries в сервисе AI-100metric. Пишешь раздел сводки для владельца магазина.
Правила:
- Только цифры из JSON ниже. Ничего не пересчитывай в уме и не придумывай; нет данных - так и скажи.
- Коротко: 4-7 пунктов «•», в каждом артикул продавца, цифры и вывод; последней строкой «Что сделать:» с 2-4 конкретными действиями.
- Порядок важности: деньги (убыток, реклама, упущенная выручка) → остатки → реклама на паузе → карточка → остальное.
- Ориентиры: ДРР от выкупов выше 25 % - дорого; реклама больше 60 % маржи до рекламы - съедает прибыль; остаток меньше чем на 7 дней
  у ходового товара - срочная поставка; оборачиваемость больше 90 дней - замороженные деньги; нет органики в топ-100 по главным
  запросам - продажи держатся на рекламе, это риск.
- Реклама: ads - весь расход по статистике кампаний; ads_upd - списано деньгами, ads_bonus - списано рекламными бонусами (Кэшбэк WB).
  Прибыль (profit) - за минусом только денег; бонусы не прямой расход и из прибыли не вычитаются. Если бонусы есть - называй
  расход деньгами и бонусами отдельно.
- Цифры Wildbox - оценка по витрине WB, по нашим товарам обычно ниже факта; так и пиши, если сравниваешь.
- Пиши по-русски, без markdown, без заголовков, без длинного тире (только дефис).
"""

SECTIONS = {
    "money": ("Где теряем деньги", "Раздел «Где теряем деньги» за 30 дней: убыточные артикулы, реклама съедает маржу, упущенная выручка без "
              "остатка, замороженный остаток и хранение, возвраты, артикулы без себестоимости."),
    "day": ("Главное за вчера", "Раздел «Главное за вчера»: вчера к позавчера и к тому же дню прошлой недели (daily и yesterday): заказы, "
            "показы, конверсия в корзину, реклама, ключи с расходом без заказов вчера, кончающиеся остатки ходовых товаров, кампании на паузе "
            "на ключевых товарах. 3-5 пунктов «•», только то, что требует внимания сегодня; ключи называй словами в кавычках с кампанией и "
            "артикулом. Обязательно отдельным пунктом — каждое изменение рейтинга в звёздах из rating_changes: артикул, было → стало "
            "(например «4,6 → 4,5»), упал или вырос; если rating_changes пуст — не упоминай. В конце «Что сделать сегодня:»."),
    "cabinet": ("Ключевые ошибки за неделю", "Раздел «Ключевые ошибки за неделю» - неделя к прошлой неделе: падение заказов и конверсии, "
                "кампании на паузе на ключевых товарах, кончающиеся остатки, карточки без видео/фото/описания, низкий рейтинг, ключи рекламы "
                "(ad_keywords: расход на ключи без заказов, дорогие заказы, просевшие позиции). 4-7 пунктов «•»; ключи называй словами в "
                "кавычках с кампанией и артикулом. В конце «Что сделать на неделе:» (например, какие ключи в минус-фразы)."),
    "competitors": ("Мы против конкурентов", "Раздел «Мы против конкурентов»: по главным поисковым запросам ключевых товаров - наши позиции "
                    "по дням, где нас нет, цены и рейтинг конкурентов в выдаче, зависимость от рекламы."),
    "niche": ("Новости ниши", "Раздел «Новости ниши»: 3-4 главных конкурента по запросу - их новинки за 60 дней (поле news), акции, "
              "цены, отзывы, блогеры. Что это значит для нас."),
}


RULES_OZ = RULES.replace("магазина на Wildberries", "магазина на Ozon").replace("ДРР от выкупов", "ДРР от продаж").replace(
    "- Цифры Wildbox - оценка по витрине WB, по нашим товарам обычно ниже факта; так и пиши, если сравниваешь.\n",
    "- Артикул продавца - поле offer_id. ДРР считаем от продаж минус возвраты. Остатки и кластеры - по данным Ozon.\n"
    "- Нет остатка в кластере - Ozon везёт из других, доставка дольше и заказы там падают: остаток меньше чем на 14 дней в "
    "ходовом кластере - пора везти поставку.\n")
SECTIONS_OZ = {
    "money": ("Где теряем деньги", "Раздел «Где теряем деньги» за 30 дней: убыточные артикулы, реклама съедает маржу, упущенная выручка без "
              "остатка, замороженный остаток (оборачиваемость больше 90 дней), возвраты, артикулы без себестоимости."),
    "day": ("Главное за вчера", "Раздел «Главное за вчера»: вчера к позавчера и к тому же дню прошлой недели (daily): заказы, показы, "
            "конверсии, расход рекламы, остановленная реклама и кончающиеся остатки ходовых товаров. 3-5 пунктов «•», только то, что требует "
            "внимания сегодня; длинные перечни сокращай до 3-4 главных артикулов. В конце «Что сделать сегодня:»."),
    "cabinet": ("Ключевые ошибки за неделю", "Раздел «Ключевые ошибки за неделю» - неделя к прошлой неделе (weekly) плюс остатки по "
                "кластерам и реклама (в т.ч. ad_items_week: товары в кампаниях с расходом без продаж и дорогие продажи). 4-7 пунктов «•»; "
                "длинные перечни сокращай до 3-4 главных артикулов. В конце «Что сделать на неделе:»."),
    "search": ("Поиск и запросы", "Раздел «Поиск и запросы» за неделю: где просела позиция по главным запросам, запросы с большим спросом и "
               "слабыми продажами, фразы рекламы с кликами без заказов по запросу, лучшие запросы (что держать)."),
}



DAILY = ("day",)
BUILD_LOCK_NAMESPACE = 1095324240  
DAY_KEYS = ("daily", "rating_changes", "yesterday", "day_before", "same_day_last_week", "note", "low_stock_top", "low_stock_clusters", "paused_ads_on_top",
            "ads_stopped_on_top", "ads_autostop", "ad_keywords")
WEEK_SKIP = ("daily", "yesterday", "day_before", "same_day_last_week")


def _day_pack(p: dict) -> dict:
    return {k: v for k, v in p.items() if k in DAY_KEYS}


def _week_pack(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in WEEK_SKIP}


def need_weekly(c, shop: int) -> bool:
    """Понедельник — или недельной сводки ещё нет за последние 7 дней (новый магазин, пропуск)."""
    if today_msk().weekday() == 0:
        return True
    return not c.execute("SELECT 1 FROM ai_reports WHERE account_id=%s AND section='money' AND day >= %s", (shop, today_msk() - timedelta(days=8))).fetchone()


def ws_key(c, ws_id: int) -> str | None:
    from . import vault
    r = c.execute("SELECT enc FROM workspace_secrets WHERE workspace_id=%s AND kind='claude'", (ws_id,)).fetchone()
    from . import llm
    return llm.from_secret(vault.decrypt(bytes(r["enc"]))) if r else None


SUBSCRIPTION = "subscription"     


def shop_key(c, shop: int, actor_id: int | None = None):
    from .ai_routing import shop_route
    route = shop_route(c, shop, actor_id)
    return ws_key(c, route['workspace_id']) if route['ai_ready'] else None


def _cli(*args, **kwargs):
    raise RuntimeError('Private subscription integration is not distributed. Configure a workspace API key.')


def complete(key: str, system: str, content: str, max_tokens: int = 1200) -> str:
    """Текст от нейросети кабинета (Claude / ChatGPT / Gemini / DeepSeek — llm) или (тариф «Личный») через подписку владельца."""
    from . import llm
    if key == SUBSCRIPTION:
        text = _cli(system, content)
    else:
        text = llm.text(llm.messages(key, {"max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": content}]}))
    return text.replace("—", "-").replace("–", "-")


def model_name(key: str) -> str:
    from . import llm
    return "Codex (подписка владельца)" if key == SUBSCRIPTION else llm.model_of(key)


def check_key(key: str) -> str | None:
    """Проверка ключа без генерации (список моделей). None — ок."""
    from . import llm
    return llm.check(key)


def write(key: str, section: str, data: dict, ozon: bool = False) -> str:
    title, task = (SECTIONS_OZ if ozon else SECTIONS)[section]
    return complete(key, RULES_OZ if ozon else RULES, task + "\n\nJSON:\n" + json.dumps(data, ensure_ascii=False, default=str))


def _save(c, shop: int, day, sec: str, title: str, body: str, key: str, data: dict):
    c.execute("""INSERT INTO ai_reports(account_id,day,section,title,body,source,model,data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                 ON CONFLICT (account_id,day,section) DO UPDATE SET title=EXCLUDED.title, body=EXCLUDED.body, source=EXCLUDED.source,
                 model=EXCLUDED.model, data=EXCLUDED.data, created_at=now()""",
              (shop, day, sec, title, body, "codex-cli" if key == SUBSCRIPTION else f"{getattr(key, 'provider', 'anthropic')}-api", model_name(key),
               json.dumps(data, ensure_ascii=False, default=str)))
    c.commit()


def build_ozon(c, shop: int, key: str, weekly: bool) -> dict:
    from . import aipack_oz
    data = aipack_oz.per_sku(c, shop)
    cab = aipack_oz.cabinet_issues(c, shop, data)
    packs = {"day": _day_pack(cab)}
    if weekly:
        packs.update({"money": aipack_oz.money_leaks(c, shop, data), "cabinet": _week_pack(cab), "search": aipack_oz.search_pack(c, shop, data)})
    day = today_msk() - timedelta(days=1)
    done = []
    for sec, pack in packs.items():
        try:
            body = write(key, sec, pack, ozon=True)
        except Exception as e:  
            _raise_uncertain(e)
            done.append(f"{sec}: ошибка {str(e)[:80]}")
            continue
        _save(c, shop, day, sec, SECTIONS_OZ[sec][0], body, key, pack)
        done.append(sec)
    return {"day": str(day), "sections": done}


def is_building(c, shop: int) -> bool:
    """Observe the build lock without acquiring a reentrant session lock."""
    return bool(c.execute("""SELECT EXISTS (
        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND granted AND mode='ExclusiveLock'
          AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
          AND classid=%s::oid AND objid=%s::oid AND objsubid=2) AS building""",
                          (BUILD_LOCK_NAMESPACE, shop)).fetchone()["building"])


def expected_sections(c, shop: int) -> list[str]:
    """Sections of a manual weekly build; no model or marketplace API calls."""
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    if mp == "ozon":
        return ["day", "money", "cabinet", "search"]
    if mp != "wb":
        return []
    from . import market
    return ["day", "money", "cabinet"] + (["competitors", "niche"] if market.shop_token(c, shop) else [])


def build_status(c, shop: int) -> dict:
    expected = expected_sections(c, shop)
    building = is_building(c, shop)
    previous = c.execute('SELECT id,status,error FROM ai_report_runs WHERE account_id=%s ORDER BY id DESC LIMIT 1',
                         (shop,)).fetchone()
    return {"building": building, "expected_sections": expected,
            'report_run_id': previous['id'] if previous else None,
            'run_status': previous['status'] if previous else None,
            'review_required': bool(previous and (_needs_review(previous) or
                                                 (previous['status'] == 'running' and not building)))}


def _needs_review(row):
    from .ai_tasks import retry_needs_review
    return bool(row and (row['status'] == 'interrupted' or
                         (row['status'] in ('error', 'partial') and
                          retry_needs_review({**row, 'status': 'error'}))))


def _raise_uncertain(error):
    from .ai_tasks import retry_needs_review
    if isinstance(error, (MemoryError, TimeoutError, subprocess.TimeoutExpired)) or retry_needs_review(
            {'status': 'error', 'error': str(error)}):
        raise error


def _run_result(row, *, busy=False, replayed=False, review_required=False):
    result = row.get('result') or {}
    return {**result, 'report_run_id': row['id'], 'status': row['status'],
            'expected_sections': row.get('expected_sections') or [],
            'busy': busy, 'replayed': replayed, 'review_required': review_required}


def build(c, shop: int, weekly: bool | None = None, *, request_key: str | None = None) -> dict:
    """One manual or scheduled build per shop across all application processes.

    A session lock survives the per-section commits and releases on disconnect.
    A concurrent request observes busy and never enters model generation.
    """
    from psycopg.pq import TransactionStatus
    from . import analytics_requests
    analytics_requests.validate_key(request_key)
    
    
    if not shop_key(c, shop):
        return {'status': 'blocked', 'error': 'Нет доступа к нейросети магазина', 'sections': []}
    expected = expected_sections(c, shop)
    if not expected:
        return {'status': 'unsupported', 'error': 'ИИ-сводка этой площадки не поддерживается', 'sections': []}
    if weekly is None:
        weekly = need_weekly(c, shop)
    expected = expected if weekly else ['day']
    actor = getattr(c, '_ai_actor_id', None)
    analytics_requests.lock_queue(c, 'reports', shop)
    previous_id = analytics_requests.reference(c, request_key, 'reports', shop, actor)
    if previous_id is not None:
        previous = c.execute('SELECT * FROM ai_report_runs WHERE id=%s AND account_id=%s',
                             (previous_id, shop)).fetchone()
        if not previous:
            c.rollback()
            return {'status': 'uncertain', 'review_required': True, 'sections': []}
        building = is_building(c, shop) if previous['status'] == 'running' else False
        c.commit()
        return _run_result(previous, busy=building, replayed=True,
                           review_required=_needs_review(previous) or
                           (previous['status'] == 'running' and not building))
    acquired = c.execute("SELECT pg_try_advisory_lock(%s,%s) AS acquired", (BUILD_LOCK_NAMESPACE, shop)).fetchone()["acquired"]
    if not acquired:
        current = c.execute('SELECT * FROM ai_report_runs WHERE account_id=%s ORDER BY id DESC LIMIT 1',
                            (shop,)).fetchone()
        if current and current['status'] == 'running':
            analytics_requests.remember(c, request_key, 'reports', shop, actor, current['id'])
        c.commit()
        return (_run_result(current, busy=True) if current and current['status'] == 'running' else
                {'busy': True, 'status': 'observing', 'sections': [],
                 'message': 'Сводка этого магазина уже собирается; прежний исполнитель не имеет нового run_id.'})
    run_id = None
    source_state = None
    try:
        previous = c.execute('SELECT * FROM ai_report_runs WHERE account_id=%s ORDER BY id DESC LIMIT 1',
                             (shop,)).fetchone()
        if previous and (previous['status'] == 'running' or _needs_review(previous)):
            
            
            if previous['status'] == 'running':
                c.execute("UPDATE ai_report_runs SET status='interrupted',finished_at=now(),error='uncertain: execution lost its build lock' WHERE id=%s",
                          (previous['id'],))
                previous = {**previous, 'status': 'interrupted'}
            analytics_requests.remember(c, request_key, 'reports', shop, actor, previous['id'])
            c.commit()
            return _run_result(previous, review_required=True)
        if request_key:
            from .kit_analytics import source_coverage
            platform = c.execute('SELECT marketplace FROM accounts WHERE id=%s', (shop,)).fetchone()['marketplace']
            source_state = source_coverage(c, shop, platform, today_msk() - timedelta(days=1))
            if not source_state.get('ready'):
                c.commit()
                return {'status': 'blocked', 'sections': [], 'source_coverage': source_state,
                        'error': 'Источники для порученного разбора неполны'}
        row = c.execute('''INSERT INTO ai_report_runs(account_id,day,request_key,requested_by,status,expected_sections,result)
            VALUES (%s,%s,%s,%s,'running',%s::jsonb,%s::jsonb) RETURNING id''',
            (shop, today_msk() - timedelta(days=1), request_key, actor, json.dumps(expected),
             json.dumps({'source_coverage': source_state}, ensure_ascii=False, default=str))).fetchone()
        run_id = row['id']
        analytics_requests.remember(c, request_key, 'reports', shop, actor, run_id)
        c.commit()  
        result = _build(c, shop, weekly)
        claimed_saved = {s for s in result.get('sections', []) if s in expected}
        stored = c.execute('''SELECT r.section,r.day,r.created_at FROM ai_reports r
            JOIN ai_report_runs job ON job.id=%s AND job.account_id=r.account_id AND job.day=r.day
            WHERE r.section=ANY(%s) AND r.created_at>=job.started_at ORDER BY r.section''',
            (run_id, sorted(claimed_saved))).fetchall()
        saved = {r['section'] for r in stored}
        status = 'ok' if saved == set(expected) else 'partial' if saved else 'error'
        
        
        safe_result = {'day': result.get('day'), 'sections': sorted(saved),
                       'missing_sections': [s for s in expected if s not in saved],
                       'saved_sections': [{k: str(r[k]) for k in ('section', 'day', 'created_at')} for r in stored],
                       'source_coverage': source_state}
        c.execute('''UPDATE ai_report_runs SET status=%s,finished_at=now(),result=%s::jsonb,error=%s WHERE id=%s''',
                  (status, json.dumps(safe_result), None if status == 'ok' else 'ReportSectionsIncomplete', run_id))
        c.commit()
        return {**safe_result, 'status': status, 'report_run_id': run_id, 'expected_sections': expected}
    except BaseException as error:
        c.rollback()
        if run_id is not None:
            
            
            c.execute("UPDATE ai_report_runs SET status='interrupted',finished_at=now(),error=%s WHERE id=%s",
                      (type(error).__name__, run_id))
            c.commit()
        raise
    finally:
        if c.info.transaction_status == TransactionStatus.INERROR:
            c.rollback()
        c.execute("SELECT pg_advisory_unlock(%s,%s)", (BUILD_LOCK_NAMESPACE, shop))
        c.commit()


def _build(c, shop: int, weekly: bool | None = None) -> dict:
    """Дневной раздел — всегда; недельные (деньги, ошибки за неделю, конкуренты, ниша / поиск Ozon) — по понедельникам
    (weekly=None) или принудительно (кнопка «пересобрать»). Без ключа Wildbox — без конкурентов и ниши."""
    from . import aipack, market
    key = shop_key(c, shop)
    if not key:
        return {"error": "Нет ключа нейросети: «Настройки аккаунта» → «Нейросеть»"}
    if weekly is None:
        weekly = need_weekly(c, shop)
    mp = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"]
    if mp == "ym":
        return {"error": "ИИ-сводка для Яндекс Маркета — следующим шагом"}
    if mp == "ozon":
        return build_ozon(c, shop, key, weekly)
    cab = aipack.cabinet_issues(c, shop)
    packs = {"day": _day_pack(cab)}
    if weekly:
        packs.update({"money": aipack.money_leaks(c, shop), "cabinet": _week_pack(cab)})
    wb = market.shop_token(c, shop) if weekly else None
    if wb:
        try:
            m = aipack.market_pack(c, wb, shop)
            packs["competitors"] = packs["niche"] = m
        except Exception as e:  
            c.rollback()
            packs["competitors_error"] = str(e)[:200]
    day = today_msk() - timedelta(days=1)
    done = []
    for sec in ("day", "money", "cabinet", "competitors", "niche"):
        if sec not in packs:
            continue
        try:
            body = write(key, sec, packs[sec])
        except Exception as e:  
            _raise_uncertain(e)
            done.append(f"{sec}: ошибка {str(e)[:80]}")
            continue
        _save(c, shop, day, sec, SECTIONS[sec][0], body, key, packs[sec])
        done.append(sec)
    return {"day": str(day), "sections": done}

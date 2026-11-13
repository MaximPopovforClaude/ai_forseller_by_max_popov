"""Вкладки «Управление»: пункт управления менеджера (свои страницы на фронте), журнал изменений карточек, конкуренты, ИИ-разбор."""

from datetime import timedelta

from ..config import today_msk
from ..manager import change_label


def actions(c, shop, f):
    """ДействияПоАртикулам (планфакт): слева ключевые данные артикула, справа по дням — заказы и действия менеджеров
    (цена, реклама, акции, выкупы, блогеры, СЕО…) и изменения карточки, которые мы заметили сами. Клик по ячейке дня — записать действия."""
    return {"custom": "actions", "columns": [], "rows": []}


def prices(c, shop, f):
    """ОнлайнЦена (планфакт): подставьте новую цену — сразу видно юнит-экономику сейчас и по новой цене (маржа ₽ и %).
    Цена в WB не меняется: список новых цен можно скачать и загрузить в ЛК WB."""
    return {"custom": "prices", "columns": [], "rows": []}


KIND_TITLE = {"content": "Контент", "photo": "Фото", "price": "Цена", "size": "Размеры", "ad_status": "Реклама", "ad_bid": "Ставка"}


def changes(c, shop, f):
    """Журнал изменений карточек: что поменялось в карточке (название, описание, характеристики, фото, размеры), цене и скидке —
    замечаем сами при сборе из API WB (карточки — раз в 3 часа, цены — раз в 2 часа, реклама: запуск/пауза и ставки — раз в час). Было → стало."""
    w, p = "", {}
    if f.get("nm_ids"):
        w, p = " AND ch.nm_id = ANY(%(nm)s)", {"nm": f["nm_ids"]}
    rows = c.execute(
        f"""SELECT ch.id, ch.detected_at, ch.nm_id, coalesce(n.vendor_code, op.offer_id) vendor_code, coalesce(n.title, op.name) title,
                   coalesce(n.data->'photos'->0->>'tm', op.photo) photo, ch.kind, ch.field, ch.old_value, ch.new_value
            FROM card_changes ch LEFT JOIN nomenclature n ON n.account_id=ch.account_id AND n.nm_id=ch.nm_id
            LEFT JOIN oz_products op ON op.account_id=ch.account_id AND op.sku=ch.nm_id
            WHERE ch.account_id=%(a)s AND (ch.detected_at AT TIME ZONE 'Europe/Moscow')::date BETWEEN %(df)s AND %(dt)s {w}
            ORDER BY ch.detected_at DESC LIMIT 5000""", {"a": shop, "df": f["date_from"], "dt": f["date_to"], **p}).fetchall()

    def short(v):
        if v is None:
            return ""
        if isinstance(v, list):
            return f"{len(v)} шт." if all(isinstance(x, str) and x.startswith("http") for x in v) else ", ".join(map(str, v))[:300]
        if isinstance(v, dict):
            return ", ".join(f"{k}: {x}" for k, x in v.items())[:300]
        return str(v)[:300]
    out = [{"detected_at": r["detected_at"], "photo": r["photo"], "nm_id": r["nm_id"], "vendor_code": r["vendor_code"], "title": r["title"],
            "kind": KIND_TITLE.get(r["kind"], r["kind"]), "what": change_label(r), "old": short(r["old_value"]), "new": short(r["new_value"])}
           for r in rows]
    oz = c.execute("SELECT marketplace FROM accounts WHERE id=%s", (shop,)).fetchone()["marketplace"] == "ozon"
    cols = [{"field": "detected_at", "title": "Когда заметили", "type": "datetime"}, {"field": "photo", "title": "Фото", "type": "image"},
            {"field": "nm_id", "title": "SKU Ozon" if oz else "Артикул WB", "type": "int"}, {"field": "vendor_code", "title": "Артикул продавца", "type": "text"},
            {"field": "title", "title": "Название", "type": "text"}, {"field": "kind", "title": "Что", "type": "text"},
            {"field": "what", "title": "Изменение", "type": "text"}, {"field": "old", "title": "Было", "type": "text"},
            {"field": "new", "title": "Стало", "type": "text"}]
    return {"columns": cols, "rows": out, "empty": "Изменений за период нет. Журнал ведётся с подключения магазина: первый сбор — исходное состояние, дальше — каждое изменение."}


def competitors(c, shop, f):
    """Карточка против конкурентов (Wildbox): выберите свой артикул — сравнение с конкурентами за 30 дней: выручка, заказы, цена,
    скидка, остаток, рейтинг, отзывы, упущенная выручка, позиция в поиске. Конкурентов можно подобрать (похожие товары WB) или добавить по артикулу."""
    return {"custom": "competitors", "columns": [], "rows": []}


EVENT_TITLE = {"price_down": "Цена снизилась", "price_up": "Цена выросла", "out_of_stock": "Закончился остаток", "back_in_stock": "Снова в наличии",
               "rating_down": "Рейтинг снизился", "rating_up": "Рейтинг вырос", "reviews_jump": "Резкий прирост отзывов",
               "orders_spike": "Всплеск заказов", "orders_drop": "Провал заказов", "promo": "Акции изменились"}


def comp_monitor(c, shop, f):
    """Мониторинг конкурентов: каждый день снимаем карточки конкурентов (Wildbox) и отмечаем, что поменялось —
    цена, остаток, рейтинг, отзывы, всплески заказов. Самое важное приходит в утреннюю сводку бота."""
    rows = c.execute(
        """SELECT e.day, e.detected_at, e.comp_nm_id, e.kind, e.old_value, e.new_value, s.data snap,
                  array_agg(DISTINCT n.vendor_code) mine
           FROM competitor_events e JOIN competitors k ON k.comp_nm_id=e.comp_nm_id AND k.account_id=%(a)s
           LEFT JOIN nomenclature n ON n.account_id=k.account_id AND n.nm_id=k.nm_id
           LEFT JOIN market_snap s ON s.nm_id=e.comp_nm_id AND s.day=e.day
           WHERE e.day BETWEEN %(df)s AND %(dt)s GROUP BY e.id, s.data ORDER BY e.day DESC, e.comp_nm_id""",
        {"a": shop, "df": f["date_from"], "dt": f["date_to"]}).fetchall()

    def val(v):
        if isinstance(v, dict):
            return ", ".join(f"{x}" for x in v.values())
        return "" if v is None else str(v)
    out = [{"day": r["day"], "photo": (r["snap"] or {}).get("image"), "comp_nm_id": r["comp_nm_id"], "name": (r["snap"] or {}).get("name"),
            "mine": ", ".join(x for x in r["mine"] if x), "event": EVENT_TITLE.get(r["kind"], r["kind"]),
            "old": val(r["old_value"]), "new": val(r["new_value"])} for r in rows]
    cols = [{"field": "day", "title": "День", "type": "date"}, {"field": "photo", "title": "Фото", "type": "image"},
            {"field": "comp_nm_id", "title": "Артикул конкурента", "type": "int"}, {"field": "name", "title": "Название", "type": "text"},
            {"field": "mine", "title": "Наш артикул", "type": "text"}, {"field": "event", "title": "Что случилось", "type": "text"},
            {"field": "old", "title": "Было", "type": "text"}, {"field": "new", "title": "Стало", "type": "text"}]
    return {"columns": cols, "rows": out, "empty": "Событий нет. Добавьте конкурентов во вкладке «Конкуренты» — снимки идут раз в сутки."}


def insights(c, shop, f):
    """ИИ-разбор дня: что изменилось в магазине вчера и почему — остатки, цены, реклама, рейтинг, конверсия, действия менеджеров,
    конкуренты. Цифры считает код; на тарифе «Наша нейросеть» Claude пишет выводы и что сделать."""
    return {"custom": "insights", "columns": [], "rows": []}


def planning(c, shop, f):
    """Self-hosted application component."""
    return {"custom": "planning", "columns": [], "rows": []}


def exclusions(c, shop, f):
    """Артикулы в работе: отключите артикулы, бренды или предметы, по которым не нужно вести цифры — они пропадут из всех вкладок,
    дашбордов, планов и сводок, воронка WB по ним не будет собираться. По умолчанию включено всё; вернуть можно в любой момент."""
    return {"custom": "exclusions", "columns": [], "rows": []}


def staff(c, shop, f):
    """Менеджеры: кто отвечает за какие артикулы (один менеджер на артикул). Назначьте вручную или загрузите файл «артикул → менеджер» —
    наверху появится фильтр «Менеджер», по нему считаются все вкладки и «Сумма магазинов»."""
    return {"custom": "staff", "columns": [], "rows": []}


def photo_funnel(c, shop, f):
    """Фотоворонка: первые 7 фото карточки (своих и конкурентов) каждый день; история изменений — поменяли слайды местами, заменили,
    добавили, убрали. По своим карточкам — конверсии 7 дней до и после изменения (переходы → корзина → заказ)."""
    return {"custom": "photos", "columns": [], "rows": []}


def rnp(c, shop, f):
    """РНП — «рука на пульсе»: главное по кабинету и каждому артикулу за месяц. Прибыль — расчётная: заказы × % выкупа × юнит-экономика.
    Цвет дней — выполнение плана дня (план — из вкладки «Планирование»)."""
    return {"custom": "rnp", "columns": [], "rows": []}


def news(c, shop, f):
    """Лента новостей магазина: изменения цены товара, СПП / соинвеста (цена покупателя) и другие события — новые сверху.
    Те же события приходят уведомлением в бот «Стометрик» (выбор — /settings в боте или «Настройки аккаунта»)."""
    return {"custom": "news", "columns": [], "rows": []}


def checklist(c, shop, f):
    """Чек-лист: все показатели одного артикула по дням — трафик и органика, реклама АРК/ПРК (CTR, CPC, CPM),
    ДРР, отзывы ниже 3★, рейтинг, остатки и в пути, корзины, заказы, выкупы, конверсии, цена и СПП, прибыль до/после рекламы, КЭМ.
    Выберите артикул вверху (поле «Артикулы»); период — даты вверху, новые дни сверху."""
    from .. import checklist as ck
    if not f.get("nm_ids"):
        return {"columns": [{"field": "msg", "title": "Выберите артикул", "type": "text"}], "plain": True,
                "rows": [{"msg": "Выберите один артикул вверху страницы — чек-лист строится по одному товару"}]}
    nm = f["nm_ids"][0]
    res = ck.compute(c, shop, nm, f["date_from"], f["date_to"])
    cols = [{"field": k, "title": t, "type": "share" if ty == "pct" else ty, "group": g} for g, items in ck.GROUPS for k, t, ty in items]   
    if not any(r.get("bonus") for r in res["rows"]):        
        cols = [x for x in cols if x["field"] not in ck.BONUS_FIELDS]
    n = c.execute("SELECT vendor_code, title FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone() or {}
    mx = {r["field"]: float(r["value"]) for r in c.execute("SELECT field, value FROM checklist_max WHERE account_id=%s AND nm_id=%s", (shop, nm))}
    y = (today_msk() - timedelta(days=1)).isoformat()
    last3 = [r for r in res["rows"] if r["day"] <= y][:3]               
    auto = ck.auto_max(ck.total(res["rows"]))          
    dz = ck.dangers(ck.total(last3), {**auto, **mx}) if len(last3) == 3 else []
    return {"columns": cols, "rows": res["rows"], "total_row": ck.total(res["rows"]), "heat": [[k] for k in ck.HEAT],
            "dangers": dz, "max_editor": {"nm_id": nm, "fields": [{"key": k, "title": tt, "value": mx.get(k), "auto": auto.get(k)} for k, tt in ck.MAX_FIELDS]},
            "rules": {"low_reviews": [{"gt": 0, "le": None, "color": "#fca5a5"}], "days_left": [{"gt": None, "le": 7, "color": "#fca5a5"}],
                      "clicks_dyn": [{"gt": None, "le": -0.15, "color": "#fecaca"}, {"gt": 0.15, "le": None, "color": "#bbf7d0"}]},
            "note": f"{n.get('vendor_code') or nm} · {n.get('title') or ''}. % выкупа — по отчёту реализации за 4 недели ({res['bp'] * 100:.1f} %). "
                    "Прибыль — расчётная, как в РНП. Остатки по дням — со снимков (копятся с 18.10). Позиция — средняя рекламная по поисковым кластерам; «П. АРК» — поиск внутри АРК (полки и каталог WB по API не отдаёт). CTR рынка — позже (Wildbox). " + ck.wb_demand.NOTE,
            "plain": True}


def entry_points(c, shop, f):
    """Точки входа: откуда покупатели приходят в карточки (поиск, теги, рекомендации, «Похожие», каталог, реклама…) — показы, переходы, CTR,
    корзины, заказы и конверсии по каждой точке и их динамика между периодами. Отчёта нет в API WB — загрузите файл из ЛК WB:
    «Аналитика» → «Портрет покупателя» → «Точки входа» → «Скачать» (xlsx или zip)."""
    return {"custom": "entry", "columns": [], "rows": []}


def mrc(c, shop, f):
    """Контроль МРЦ: МРЦ по товарам (пока только список и пометки в уведомлениях о цене; кабинет не меняется)."""
    return {"custom": "mrc", "columns": [], "rows": []}


def shelves(c, shop, f):
    """Мониторинг полок WB: кто стоит в полке «Смотрите также» у наших товаров и у кого в полках стоят наши товары — по дням
    (снимок витрины гостя в Москве раз в сутки ночью)."""
    return {"custom": "shelves", "columns": [], "rows": []}


def ext_costs(c, shop, f):
    """Внешние расходы и раздачи: блогеры, посевы, реклама вне WB — источник, даты, затраты
    (делятся поровну на дни размещения и входят в ДРР Чек-листа); раздачи / самовыкупы — штук и затраты по дням."""
    return {"custom": "ext_costs", "columns": [], "rows": []}


def promo(c, shop, f):
    """Расчёт акций: по каждой акции WB — участвует ли товар, цена по акции, маржа с акцией и разница с актуальной;
    оборачиваемость с % выкупа, остаток, цена и маржа до рекламы. Обычные акции — из API WB сами; автоакции — загрузите файл из ЛК."""
    return {"custom": "promo", "columns": [], "rows": []}


def checklist_summary(c, shop, f):
    """Сводный чек-лист: показатели Чек-листа за период по всем артикулам + ABC-анализ по 4 показателям (сумма выкупов,
    прибыль до ДРР, ROI до ДРР, КЭМ) и рекомендация: Удерживать / ТОП Развивать / Развивать / Сливать. Всё — прогноз от заказов × % выкупа."""
    from .. import checklist as ck, xyz
    rows = ck.summary(c, shop, f["date_from"], min(f["date_to"], today_msk()), f.get("nm_ids"))
    cols = [{"field": k, "title": t, "type": "share" if ty == "pct" else ty, "group": g} for g, items in ck.SUMMARY_COLS for k, t, ty in items]
    if not any(r.get("bonus") for r in rows):
        cols = [x for x in cols if x["field"] not in ck.BONUS_FIELDS]
    color = {"A": "#bbf7d0", "B": "#fef08a", "C": "#fecaca"}
    return {"columns": cols, "rows": rows,
            "cell_colors": {"xyz": xyz.COLORS, **{k: color for k in ("abc_sum", "abc_profit", "abc_roi", "abc_kem")},
                            "rec": {"Удерживать": "#bbf7d0", "ТОП Развивать": "#bfdbfe", "Развивать": "#fef08a", "Сливать": "#fecaca"}},
            "heat": [["profit_pre"], ["profit"], ["orders_sum"], ["buyouts_fc"]],
            "note": "ABC: выкупы и прибыль — накопительно 80/95 %; ROI до ДРР A ≥ 70 %, B ≥ 30 %; КЭМ A ≥ 80 %, B ≥ 50 %. "
                    "Рекомендация — по сочетанию четырёх букв. " + ck.wb_demand.NOTE + " " + xyz.NOTE}


def hypotheses(c, shop, f):
    """Гипотезы: что тестируете по артикулу — показатель, гипотеза, дата начала и дней на тест, итог (отчёт).
    В Чек-листе гипотеза видна в каждой строке-дне, пока идёт тест."""
    return {"custom": "hypotheses", "columns": [], "rows": []}


def seo(c, shop, f):
    """SEO за 5 минут: слова из поисковых запросов артикула — частота, есть ли слово в карточке; отметьте, что добавить и что
    убрать. Артикул — выбор вверху страницы. Сама карточка меняется только через «Карточки» (черновик → «Применить»)."""
    return {"custom": "seo", "columns": [], "rows": []}


def item_rating(c, shop, f):
    """Оценки товаров — отчёт WB «Оценка товара»: по артикулам рейтинг по отзывам (как считает WB), сколько оценок на 5, 4, 3, 2 и 1 звезду
    (всего за 364 дня и прирост за 30 дней), исключённые из рейтинга, процентиль среди товаров предмета у других продавцов и оценка,
    сколько пятёрок нужно до следующей ступени рейтинга: «точно» — рейтинг WB равен среднему оценок, «по факту» — подстроено по ежедневным
    снимкам, «приблизительно» — снимков ещё мало (rating.basis). Обновляется раз в 3 часа."""
    from .. import rating as rt
    rows = []
    for r in rt.latest(c, shop, f.get("nm_ids"), f.get("date_to")):
        x = {k: r[k] for k in ("photo", "nm_id", "vendor_code", "subject", "rating", "percentile", "card_rating", "total", "disqualified", "month")}
        x.update({f"s{s}": r[f"s{s}"] for s in rt.STAR})
        x["share5"] = (r["s5"] or 0) / r["total"] if r["total"] else None
        x["low_m"] = sum(r[f"m{s}"] or 0 for s in (1, 2, 3))
        x["avg"] = round(r["avg"], 2) if r["avg"] is not None else None
        x["d7"] = float(r["rating"]) - float(r["rating_7"]) if r["rating"] is not None and r["rating_7"] is not None else None
        if r["rating"] is not None and r["total"]:
            t = rt.step_up(float(r["rating"]))
            x["target"] = t if t <= 5 else None
            x["need5"] = rt.need(r["r_eff"], r["n_eff"], t) if t < 5 else None
            x["method"] = r["method"]
        x["day"] = r["day"]
        rows.append(x)
    cols = [("photo", "Фото", "image"), ("nm_id", "Артикул WB", "int"), ("vendor_code", "Артикул продавца", "text"), ("subject", "Предмет", "text"),
            ("rating", "Рейтинг по отзывам (WB)", "num"), ("d7", "Изменение за 7 дней", "num"),
            ("percentile", "Процентиль в предмете, % (у скольких товаров рейтинг ниже)", "pct"),
            ("total", "Оценок всего", "int"), ("s5", "5 ★", "int"), ("s4", "4 ★", "int"), ("s3", "3 ★", "int"), ("s2", "2 ★", "int"), ("s1", "1 ★", "int"),
            ("share5", "Доля 5 ★", "share"), ("avg", "Простое среднее оценок", "num"), ("disqualified", "Исключено из рейтинга", "int"),
            ("month", "Оценок за 30 дней", "int"), ("low_m", "Из них 1–3 ★", "int"),
            ("target", "Следующая ступень рейтинга", "num"), ("need5", "≈ Пятёрок до неё", "int"), ("method", "Расчёт", "text"), ("card_rating", "Рейтинг карточки (0–10)", "num"),
            ("day", "Данные на", "date")]
    note = None if rows else "Отчёт «Оценка товара» ещё не загружен: появится после ближайшего сбора (раз в 3 часа)."
    return {"columns": [{"field": a, "title": b, "type": t} for a, b, t in cols], "rows": rows, **({"note": note} if note else {})}

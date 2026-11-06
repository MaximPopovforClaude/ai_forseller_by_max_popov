"""Self-hosted application component."""

import hashlib
import io
import re
import urllib.request
import zipfile
from datetime import date

VIEWS_PER_SHARED = 2          
MAX_FILE = 15 * 1024 * 1024


class BadFile(ValueError):
    pass


def _xlsx_bytes(raw: bytes) -> bytes:
    if raw[:2] == b"PK" and b"xl/workbook.xml" not in raw[:4000]:
        try:
            z = zipfile.ZipFile(io.BytesIO(raw))
            names = [n for n in z.namelist() if n.lower().endswith(".xlsx") and "__macosx" not in n.lower()]
            if names:
                return z.read(names[0])
        except zipfile.BadZipFile:
            pass
    return raw


def _num(v):
    if v is None or v == "-" or v == "":
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v).replace("\xa0", "").replace(" ", "").replace(",", ".").replace("%", "")
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return str(v)


def _period(s):
    m = re.search(r"(\d{4}-\d{2}-\d{2}).*?(\d{4}-\d{2}-\d{2})", str(s or ""))
    return {"from": m.group(1), "to": m.group(2)} if m else None


def parse(raw: bytes) -> dict:
    import openpyxl
    if len(raw) > MAX_FILE:
        raise BadFile("Файл больше 15 МБ")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(_xlsx_bytes(raw)), data_only=True)   
    except Exception:
        raise BadFile("Это не xlsx-файл. Загрузите файл «Сравнение карточек», скачанный из ЛК WB (можно в zip)") from None
    need = {"Общая информация", "Показатели", "Поисковые запросы"}
    if not need <= set(wb.sheetnames):
        raise BadFile("Не похоже на отчёт WB «Сравнение карточек»: нет листов " + ", ".join(sorted(need - set(wb.sheetnames))))
    info = {str(r[0]).strip(): (r[1] if len(r) > 1 else None) for r in wb["Общая информация"].iter_rows(values_only=True) if r and r[0]}
    nms = [int(_num(v)) for k, v in info.items() if k.startswith("Выбранная номенклатура") and _num(v)]
    if not 2 <= len(nms) <= 5:
        raise BadFile("В сравнении должно быть от 2 до 5 артикулов")
    rows = list(wb["Показатели"].iter_rows(values_only=True))
    head = [str(x or "") for x in rows[1]]
    col = {}   
    for j, h in enumerate(head):
        m = re.match(r"Артикул WB (\d+)( \(предыдущ)?", h)
        if m:
            col[(int(m.group(1)), "prev" if m.group(2) else "cur")] = j
    cards = {nm: {"nm_id": nm, "metrics": {}} for nm in nms}
    order = []
    TEXT = {"Название": "title", "Категория": "category", "Предмет": "subject", "Дата создания": "created", "Бренд": "brand",
            "Статус продвижения": "promo", "Среднее время доставки": "delivery"}
    for r in rows[2:]:
        if not r or not r[0]:
            continue
        label = str(r[0]).strip()
        for nm in nms:
            cur = r[col[(nm, "cur")]] if (nm, "cur") in col and col[(nm, "cur")] < len(r) else None
            prev = r[col[(nm, "prev")]] if (nm, "prev") in col and col[(nm, "prev")] < len(r) else None
            if label in TEXT:
                cards[nm][TEXT[label]] = None if cur in (None, "-") else str(cur)
                if label in ("Статус продвижения", "Среднее время доставки"):
                    cards[nm]["metrics"][label] = {"cur": cur, "prev": None if prev in (None, "-") else prev}
            else:
                cards[nm]["metrics"][label] = {"cur": _num(cur), "prev": _num(prev)}
        if label not in TEXT or label in ("Статус продвижения", "Среднее время доставки"):
            order.append(label)
    qrows = list(wb["Поисковые запросы"].iter_rows(values_only=True))
    qh = [str(x or "") for x in qrows[1]]
    KEYS = {"Количество запросов": "freq", "Средняя позиция по запросу": "pos", "Переходы в карточку": "clicks",
            "Конверсия в корзину из поиска": "conv_cart", "Положили в корзину": "carts", "Конверсия в заказ из поиска": "conv_order", "Заказы": "orders"}
    qcols = {}
    for j, h in enumerate(qh):
        prev = "(предыдущ" in h
        base = re.sub(r",?\s*\(.*$", "", h).strip()
        if base in KEYS:
            qcols[(KEYS[base], prev)] = j
        elif base == "Поисковый запрос":
            qcols["query"] = j
        elif base == "Артикул WB":
            qcols["nm"] = j
    queries = []
    for r in qrows[2:]:
        if not r or r[qcols.get("query", 0)] is None:
            continue
        nm = _num(r[qcols["nm"]])
        if not isinstance(nm, int):
            continue
        q = {"query": str(r[qcols["query"]]).strip(), "nm_id": nm}
        for (k, prev), j in ((k, j) for k, j in qcols.items() if isinstance(k, tuple)):
            q[("prev_" if prev else "") + k] = _num(r[j]) if j < len(r) else None
        queries.append(q)
    return {"period": _period(info.get("Выбранный период")), "prev_period": _period(info.get("Предыдущий период")),
            "by_size": str(info.get("Распределение по размерам") or "") == "Да", "nm_ids": nms,
            "cards": [cards[nm] for nm in nms], "metric_order": order, "queries": queries}



_BASKET: dict[int, int] = {}


def _probe(host: int, vol: int, part: int, nm: int) -> bool:
    url = f"https://basket-{host:02d}.wbbasket.ru/vol{vol}/part{part}/{nm}/images/tm/1.webp"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=5) as r:
            return r.status == 200
    except Exception:  
        return False


def photo(c, nm: int) -> str | None:
    vol, part = nm // 100000, nm // 1000
    host = _BASKET.get(vol)
    if host is None:
        r = c.execute("SELECT value FROM app_settings WHERE key=%s", (f"wbbasket:{vol}",)).fetchone()
        host = int(r["value"]) if r else None
    if host is None:
        
        est = max(1, min(60, round(1 + vol / 230)))
        for h in sorted(range(1, 61), key=lambda x: abs(x - est)):
            if _probe(h, vol, part, nm):
                host = h
                break
        if host is None:
            return None
        c.execute("INSERT INTO app_settings(key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value", (f"wbbasket:{vol}", str(host)))
        c.commit()
    _BASKET[vol] = host
    return f"https://basket-{host:02d}.wbbasket.ru/vol{vol}/part{part}/{nm}/images/c246x328/1.webp"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def content_key(nm_ids, period_from, period_to, sha: str) -> str:
    """Отпечаток сравнения: те же карточки + тот же период = то же сравнение (формула — как в миграции 032)."""
    if not period_from and not period_to:
        return "sha:" + sha
    s = ",".join(str(x) for x in sorted(int(n) for n in nm_ids)) + "|" + str(period_from or "")[:10] + "|" + str(period_to or "")[:10]
    return hashlib.sha256(s.encode()).hexdigest()


def first_of_key(c, key: str):
    """Самое раннее сравнение с таким отпечатком (любого пользователя)."""
    return c.execute("SELECT id, user_id FROM card_comparisons WHERE content_key=%s ORDER BY id LIMIT 1", (key,)).fetchone()


def views_left(c, user_id: int) -> dict:
    """Лимит чужих: открытые свои × VIEWS_PER_SHARED; повтор уже имеющегося в базе сравнения (тот же отпечаток) не считается."""
    shared = c.execute("""SELECT count(*) n FROM card_comparisons x WHERE x.user_id=%s AND x.is_public AND NOT EXISTS
                          (SELECT 1 FROM card_comparisons y WHERE y.content_key=x.content_key AND y.id<x.id)""", (user_id,)).fetchone()["n"]
    used = c.execute("""SELECT count(*) n FROM comparison_views v JOIN card_comparisons x ON x.id=v.comparison_id
                        WHERE v.user_id=%s AND x.user_id<>%s AND x.user_id NOT IN (SELECT m2.user_id FROM memberships m1
                        JOIN memberships m2 USING (workspace_id) WHERE m1.user_id=%s)""", (user_id, user_id, user_id)).fetchone()["n"]
    return {"shared": shared, "allowed": shared * VIEWS_PER_SHARED, "used": used, "left": max(shared * VIEWS_PER_SHARED - used, 0)}

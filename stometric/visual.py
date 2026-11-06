"""Self-hosted application component."""

import hashlib
import html
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config

DIR = config.DATA / "visual"
MAX_FILE = 30 * 1024 * 1024
MAX_SOURCES = 40
IMG = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
DOC = {".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
       ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain"}
MIME_EXT = {v: k for k, v in {**IMG, **DOC}.items()} | {"image/jpg": ".jpg"}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}


class VisualError(ValueError):
    pass



def project(c, shop: int, pid: int) -> dict:
    p = c.execute("SELECT * FROM vis_projects WHERE id=%s AND account_id=%s", (pid, shop)).fetchone()
    if not p:
        raise VisualError("Нет такого проекта")
    return p


def create(c, shop: int, uid: int, nm: int | None, title: str, description: str) -> int:
    if nm:
        r = c.execute("SELECT id FROM vis_projects WHERE account_id=%s AND nm_id=%s AND NOT archived", (shop, nm)).fetchone()
        if r:
            return r["id"]
        n = c.execute("SELECT vendor_code, title, data FROM nomenclature WHERE account_id=%s AND nm_id=%s", (shop, nm)).fetchone()
        if not n:
            raise VisualError("Нет такого артикула в магазине")
        d = n["data"] or {}
        title = title.strip() or d.get("title") or n["title"] or n["vendor_code"] or str(nm)
        description = description.strip() or d.get("description") or ""
    if not title.strip():
        raise VisualError("Напишите, что это за товар")
    return c.execute("""INSERT INTO vis_projects(account_id,nm_id,title,description,created_by) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                     (shop, nm, title.strip()[:300], description.strip()[:6000], uid)).fetchone()["id"]


def touch(c, pid: int):
    c.execute("UPDATE vis_projects SET updated_at=now() WHERE id=%s", (pid,))



def _ext(name: str, mime: str | None) -> str:
    e = Path(name or "").suffix.lower()
    if e in IMG or e in DOC:
        return e
    return MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "")


def save(c, shop: int, pid: int | None, kind: str, name: str, raw: bytes, uid: int | None, origin: str, mime: str | None = None) -> dict:
    ext = _ext(name, mime)
    if kind == "source" and ext not in IMG:
        raise VisualError(f"«{name}»: исходники — фото JPG, PNG или WEBP")
    if kind == "logo" and ext not in IMG:
        raise VisualError("Логотип — PNG или JPG")
    if kind == "passport" and ext not in IMG and ext not in DOC:
        raise VisualError(f"«{name}»: паспорт — PDF, Word, Excel, TXT или фото")
    if not raw or len(raw) > MAX_FILE:
        raise VisualError(f"«{name}»: файл пустой или больше 30 МБ")
    meta = {}
    if ext in IMG:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as im:
                meta = {"w": im.width, "h": im.height}
        except Exception:  
            raise VisualError(f"«{name}» не открывается как картинка") from None
    sha = hashlib.sha256(raw).hexdigest()
    if pid and kind == "source":
        dup = c.execute("SELECT id, name FROM vis_files WHERE project_id=%s AND kind='source' AND sha=%s", (pid, sha)).fetchone()
        if dup:
            return {"id": dup["id"], "name": dup["name"], "dup": True}
        n = c.execute("SELECT count(*) n FROM vis_files WHERE project_id=%s AND kind='source'", (pid,)).fetchone()["n"]
        if n >= MAX_SOURCES:
            raise VisualError(f"В проекте уже {MAX_SOURCES} исходников — удалите лишние")
    d = DIR / str(shop)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{sha[:24]}{ext}"
    path.write_bytes(raw)
    mime = IMG.get(ext) or DOC.get(ext) or "application/octet-stream"
    nm = re.sub(r"[\r\n\t]", " ", name or path.name)[:200]
    r = c.execute("""INSERT INTO vis_files(account_id,project_id,kind,name,path,mime,size,sha,origin,meta,created_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  (shop, pid, kind, nm, str(path), mime, len(raw), sha, origin[:300], json.dumps(meta), uid)).fetchone()
    return {"id": r["id"], "name": nm}


def files(c, pid: int, kind: str = "source") -> list[dict]:
    return c.execute("SELECT id, name, mime, size, origin, meta, created_at FROM vis_files WHERE project_id=%s AND kind=%s ORDER BY id",
                     (pid, kind)).fetchall()


def file_path(c, shop: int, fid: int) -> dict:
    r = c.execute("SELECT path, mime, name FROM vis_files WHERE id=%s AND account_id=%s", (fid, shop)).fetchone()
    if not r or not Path(r["path"]).exists():
        raise VisualError("Нет файла")
    return r


def thumb(c, shop: int, fid: int, size: int = 360) -> bytes:
    """Превью фото (кэш рядом с файлом)."""
    from PIL import Image
    r = file_path(c, shop, fid)
    p = Path(r["path"])
    t = p.with_name(f"{p.stem}_t{size}.jpg")
    if not t.exists():
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size * 4 // 3))
            im.save(t, "JPEG", quality=88 if size > 1000 else 82)
    return t.read_bytes()



def _get(url: str, **kw) -> httpx.Response:
    """GET с проверкой каждого перехода: только https/http на публичные адреса."""
    from .kb import _public_host
    for _ in range(6):
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname or not _public_host(u.hostname):
            raise VisualError("Ссылка ведёт на недоступный адрес")
        r = httpx.get(url, headers=UA, timeout=kw.get("timeout", 60), follow_redirects=False, cookies=kw.get("cookies"))
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = str(httpx.URL(url).join(r.headers["location"]))
            continue
        return r
    raise VisualError("Слишком много перенаправлений")


def _gdrive_file(fid: str) -> tuple[str, bytes, str]:
    r = _get(f"https://drive.google.com/uc?export=download&id={fid}")
    if "text/html" in r.headers.get("content-type", ""):
        m = re.search(r'name="uuid" value="([^"]+)"', r.text)
        if not m and ("ServiceLogin" in r.text or "accounts.google.com" in r.text):
            raise VisualError("Файл на Google Диске закрыт — откройте доступ «Все, у кого есть ссылка»")
        r = _get(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t" + (f"&uuid={m.group(1)}" if m else ""))
    if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
        raise VisualError("Файл на Google Диске не скачался — проверьте доступ по ссылке")
    name = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', r.headers.get("content-disposition", ""))
    from urllib.parse import unquote
    return (unquote(name.group(1)) if name else fid), r.content, r.headers.get("content-type", "")


def _gdrive_folder(fid: str) -> list[tuple[str, str]]:
    r = _get(f"https://drive.google.com/embeddedfolderview?id={fid}")
    if r.status_code != 200:
        raise VisualError("Папка Google Диска не открылась — откройте доступ «Все, у кого есть ссылка»")
    out = []
    for m in re.finditer(r'href="https://drive\.google\.com/file/d/([\w-]+)/view[^"]*".*?class="flip-entry-title">([^<]*)<', r.text, re.S):
        out.append((m.group(1), html.unescape(m.group(2))))
    if not out:
        raise VisualError("В папке Google Диска не нашлось файлов (или она закрыта)")
    return out


def _yadisk(url: str) -> list[tuple[str, bytes, str]]:
    api = "https://cloud-api.yandex.net/v1/disk/public/resources"
    meta = httpx.get(api, params={"public_key": url, "limit": 100}, timeout=30)
    if meta.status_code != 200:
        raise VisualError("Яндекс Диск не открыл ссылку — нужна публичная ссылка на файл или папку")
    m = meta.json()
    items = [m] if m.get("type") == "file" else [x for x in (m.get("_embedded") or {}).get("items") or [] if x.get("type") == "file"]
    out = []
    for it in items[:MAX_SOURCES]:
        href = httpx.get(f"{api}/download", params={"public_key": url, **({"path": it["path"]} if m.get("type") == "dir" else {})}, timeout=30)
        if href.status_code != 200:
            continue
        r = _get(href.json()["href"], timeout=120)
        if r.status_code == 200:
            out.append((it.get("name") or "file", r.content, r.headers.get("content-type", "")))
    return out


def fetch_link(url: str, want: str) -> list[tuple[str, bytes, str]]:
    """Скачать по ссылке: [(имя, байты, content-type)]. want: 'images' (папка → все фото) или 'one' (паспорт — один документ)."""
    url = url.strip()
    if not re.match(r"^https?://", url):
        raise VisualError("Нужна ссылка вида https://…")
    host = (urlparse(url).hostname or "").lower()
    if host in ("docs.google.com",):
        m = re.search(r"/(document|spreadsheets|presentation)/d/([\w-]+)", url)
        if not m:
            raise VisualError("Не понял ссылку на Google Документ")
        fmt = {"document": "pdf", "spreadsheets": "xlsx", "presentation": "pdf"}[m.group(1)]
        r = _get(f"https://docs.google.com/{m.group(1)}/d/{m.group(2)}/export?format={fmt}")
        if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
            raise VisualError("Документ не открылся — включите доступ «Все, у кого есть ссылка — читатель»")
        return [(f"google_{m.group(1)}.{fmt}", r.content, r.headers.get("content-type", ""))]
    if host.endswith("drive.google.com"):
        m = re.search(r"/folders/([\w-]+)", url)
        if m:
            got = []
            for fid, name in _gdrive_folder(m.group(1))[:MAX_SOURCES]:
                if want == "images" and Path(name).suffix.lower() not in IMG:
                    continue
                _, raw, ct = _gdrive_file(fid)
                got.append((name, raw, ct))
                if want == "one":
                    break
            return got
        m = re.search(r"/file/d/([\w-]+)", url) or re.search(r"[?&]id=([\w-]+)", url)
        if not m:
            raise VisualError("Не понял ссылку на Google Диск")
        return [_gdrive_file(m.group(1))]
    if host.endswith(("disk.yandex.ru", "disk.yandex.com", "yadi.sk", "disk.360.yandex.ru")):
        return _yadisk(url)
    r = _get(url, timeout=120)
    if r.status_code != 200:
        raise VisualError(f"Ссылка ответила {r.status_code}")
    if "text/html" in r.headers.get("content-type", ""):
        raise VisualError("По ссылке страница, а не файл. Пришлите ссылку на файл или папку Google/Яндекс Диска")
    return [(Path(urlparse(url).path).name or "file", r.content, r.headers.get("content-type", ""))]


def ensure_sources(c, shop: int, pid: int, uid: int | None) -> int:
    """Self-hosted application component."""
    p = c.execute("SELECT nm_id FROM vis_projects WHERE id=%s AND account_id=%s", (pid, shop)).fetchone()
    if not p or not p["nm_id"] or c.execute("SELECT 1 FROM vis_files WHERE project_id=%s AND kind='source' LIMIT 1", (pid,)).fetchone():
        return 0
    try:
        return import_card_photos(c, shop, pid, p["nm_id"], uid)
    except Exception:  
        c.rollback()
        return 0


def import_card_photos(c, shop: int, pid: int, nm: int, uid: int) -> int:
    """Фото текущей карточки WB — как исходники (большой размер, публичная витрина WB)."""
    from .cardcompare import photo
    ph = photo(c, nm)
    if not ph:
        raise VisualError("Не нашёл фото карточки на WB")
    base = ph.split("/images/")[0]
    try:
        cnt = int(((httpx.get(f"{base}/info/ru/card.json", timeout=15).json().get("media") or {}).get("photo_count")) or 0)
    except Exception:  
        cnt = 0
    n = 0
    for i in range(1, min(cnt or 10, 30) + 1):
        r = httpx.get(f"{base}/images/big/{i}.webp", timeout=30)
        if r.status_code != 200:
            break
        if not save(c, shop, pid, "source", f"WB фото {i}.webp", r.content, uid, f"карточка WB {nm}").get("dup"):
            n += 1
    return n



def doc_text(path: str, mime: str) -> str:
    """Текст из Excel / Word / TXT (PDF и фото читает нейросеть)."""
    p = Path(path)
    if mime == DOC[".txt"]:
        raw = p.read_bytes()
        for enc in ("utf-8", "cp1251"):
            try:
                return raw.decode(enc)[:60000]
            except UnicodeDecodeError:
                continue
    if mime == DOC[".xlsx"]:
        from .cost_import import open_xlsx
        wb = open_xlsx(p)
        out = []
        for ws in wb.worksheets:
            out.append(f"== Лист {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(x).strip() for x in row if x not in (None, "")]
                if cells:
                    out.append(" | ".join(cells))
                if sum(len(x) for x in out) > 60000:
                    break
        return "\n".join(out)[:60000]
    if mime == DOC[".docx"]:
        with zipfile.ZipFile(p) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab/>", "\t", xml)
        return html.unescape(re.sub(r"<[^>]+>", "", xml))[:60000]
    return ""


def passports(c, shop: int) -> list[dict]:
    """Все паспорта магазина (один паспорт — на несколько похожих товаров)."""
    return c.execute("""SELECT f.id, f.name, f.created_at, f.meta->'models' models, f.meta->>'state' state,
                               (SELECT count(*) FROM vis_projects p WHERE p.passport_id=f.id AND NOT p.archived) used
                        FROM vis_files f WHERE f.account_id=%s AND f.kind='passport' ORDER BY f.id DESC""", (shop,)).fetchall()



def brand(c, shop: int) -> dict:
    return c.execute("SELECT colors, fonts, notes, logo_id FROM vis_brand WHERE account_id=%s", (shop,)).fetchone() or\
        {"colors": "", "fonts": "", "notes": "", "logo_id": None}



def briefs(c, shop: int, pid: int | None = None) -> list[dict]:
    return c.execute(f"""SELECT b.id, b.project_id, b.nm_id, b.kind, b.version, b.state, b.created_at, b.updated_at, b.reviewed_at,
                                p.title, n.vendor_code, jsonb_array_length(coalesce(b.data->'slides','[]')) slides
                         FROM vis_briefs b JOIN vis_projects p ON p.id=b.project_id
                         LEFT JOIN nomenclature n ON n.account_id=b.account_id AND n.nm_id=b.nm_id
                         WHERE b.account_id=%s {'AND b.project_id=%s' if pid else ''} ORDER BY b.updated_at DESC LIMIT 300""",
                     (shop, pid) if pid else (shop,)).fetchall()


def brief_latest(c, pid: int, kind: str = "graphics") -> dict | None:
    return c.execute("SELECT * FROM vis_briefs WHERE project_id=%s AND kind=%s ORDER BY version DESC LIMIT 1", (pid, kind)).fetchone()


def brief_save(c, shop: int, pid: int, kind: str, data: dict, uid: int | None, new_version: bool) -> dict:
    """Новая версия (после ИИ) или правка текущей. Правка согласованного/ждущего ТЗ — тоже новая версия, старая остаётся в базе."""
    p = project(c, shop, pid)
    cur = brief_latest(c, pid, kind)
    if cur and not new_version and cur["state"] in ("draft", "returned"):
        return c.execute("UPDATE vis_briefs SET data=%s, updated_at=now() WHERE id=%s RETURNING *",
                         (json.dumps(data, ensure_ascii=False), cur["id"])).fetchone()
    v = (cur["version"] + 1) if cur else 1
    return c.execute("""INSERT INTO vis_briefs(account_id,project_id,nm_id,kind,version,data,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                     (shop, pid, p["nm_id"], kind, v, json.dumps(data, ensure_ascii=False), uid)).fetchone()


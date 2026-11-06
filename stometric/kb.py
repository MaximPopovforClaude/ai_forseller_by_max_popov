"""Self-hosted application component."""

import ipaddress
import re
import secrets
import socket
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import auth
from .config import DATA

MAX_FILE = 25 * 1024 * 1024
MAX_WS = 2 * 1024 * 1024 * 1024
TEXT_MAX = 30000
IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".heic": "image/heic"}
DOCS = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel", ".csv": "text/csv", ".txt": "text/plain", ".md": "text/markdown",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".ppt": "application/vnd.ms-powerpoint",
        ".rtf": "application/rtf", ".odt": "application/vnd.oasis.opendocument.text", ".zip": "application/zip",
        ".mp4": "video/mp4", ".mov": "video/quicktime"}


class KbError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code



def ws_role(c, u: dict, ws: int) -> str | None:
    return auth.workspace_role(c, u, ws)


def can_read(c, u: dict, ws: int) -> bool:
    return auth.can(ws_role(c, u, ws), "viewer")


def can_add(c, u: dict, ws: int, shop_id: int | None = None) -> bool:
    if shop_id:
        return auth.can(auth.shop_role(c, u, shop_id), "editor")
    return auth.can(ws_role(c, u, ws), "editor")


def can_change(c, u: dict, item: dict) -> bool:
    """Своё — редактор и выше; чужое — админ пространства."""
    if not can_see(c, u, item):
        return False
    role = ws_role(c, u, item["workspace_id"])
    return auth.can(role, "admin") or (item.get("created_by") == u["id"] and can_add(c, u, item["workspace_id"], item.get("shop_id")))


def shops_visible(c, u: dict, ws: int) -> list[dict]:
    return [s for s in auth.shops_for(c, u) if s["workspace_id"] == ws]



def tree(c, u: dict, ws: int) -> list[dict]:
    """Разделы с подразделами и числом видимых материалов."""
    vis = [s["id"] for s in shops_visible(c, u, ws)]
    n = {r["section_id"]: r["n"] for r in c.execute(
        "SELECT section_id, count(*) n FROM kb_items WHERE workspace_id=%s AND (shop_id IS NULL OR shop_id = ANY(%s)) GROUP BY 1", (ws, vis))}
    rows = c.execute("SELECT id, parent_id, title FROM kb_sections WHERE workspace_id=%s ORDER BY lower(title)", (ws,)).fetchall()
    top = [{"id": r["id"], "title": r["title"], "n": n.get(r["id"], 0), "subs": []} for r in rows if not r["parent_id"]]
    by = {x["id"]: x for x in top}
    for r in rows:
        if r["parent_id"] in by:
            by[r["parent_id"]]["subs"].append({"id": r["id"], "title": r["title"], "n": n.get(r["id"], 0)})
    for x in top:
        x["total"] = x["n"] + sum(s["n"] for s in x["subs"])
    return [*top, {"id": 0, "title": "Без раздела", "n": n.get(None, 0), "subs": [], "total": n.get(None, 0)}] if n.get(None) else top


def items(c, u: dict, ws: int, section: int | None = None, q: str = "", shop: int | None = None, limit: int = 200) -> list[dict]:
    vis = [s["id"] for s in shops_visible(c, u, ws)]
    w, p = ["i.workspace_id=%(ws)s", "(i.shop_id IS NULL OR i.shop_id = ANY(%(vis)s))"], {"ws": ws, "vis": vis, "lim": limit}
    if section == 0:
        w.append("i.section_id IS NULL")
    elif section:                                   
        w.append("(i.section_id=%(sec)s OR i.section_id IN (SELECT id FROM kb_sections WHERE parent_id=%(sec)s))")
        p["sec"] = section
    if shop:
        w.append("i.shop_id=%(shop)s")
        p["shop"] = shop
    if q.strip():
        w.append("""(i.title ILIKE %(q)s OR i.description ILIKE %(q)s OR i.url ILIKE %(q)s OR i.body ILIKE %(q)s OR i.text ILIKE %(q)s
                     OR i.file_name ILIKE %(q)s OR s.title ILIKE %(q)s OR ps.title ILIKE %(q)s)""")
        p["q"] = f"%{q.strip()}%"
    return c.execute(f"""SELECT i.id, i.workspace_id, i.shop_id, i.section_id, i.kind, i.title, i.url, i.body, i.file_name, i.mime, i.size,
                                i.description, i.source, i.created_by, i.created_at, i.updated_at, coalesce(cu.name, cu.email) author,
                                s.title section, ps.title parent, coalesce(a.title, a.name) shop
                         FROM kb_items i LEFT JOIN kb_sections s ON s.id=i.section_id LEFT JOIN kb_sections ps ON ps.id=s.parent_id
                         LEFT JOIN users cu ON cu.id=i.created_by LEFT JOIN accounts a ON a.id=i.shop_id
                         WHERE {" AND ".join(w)} ORDER BY i.created_at DESC LIMIT %(lim)s""", p).fetchall()


def get(c, item_id: int) -> dict | None:
    return c.execute("SELECT * FROM kb_items WHERE id=%s", (item_id,)).fetchone()



def section(c, u: dict, ws: int, title: str, parent_id: int | None = None) -> int:
    """Раздел (или подраздел) по названию: есть — его id, нет — создаём."""
    title = " ".join((title or "").split())[:120]
    if not title:
        raise KbError("Пустое название раздела")
    if parent_id:
        par = c.execute("SELECT parent_id FROM kb_sections WHERE id=%s AND workspace_id=%s", (parent_id, ws)).fetchone()
        if not par:
            raise KbError("Нет такого раздела")
        if par["parent_id"]:
            raise KbError("Подраздел можно создать только в разделе (уровня два: раздел → подраздел)")
    r = c.execute("SELECT id FROM kb_sections WHERE workspace_id=%s AND coalesce(parent_id,0)=%s AND lower(title)=lower(%s)",
                  (ws, parent_id or 0, title)).fetchone()
    if r:
        return r["id"]
    if not can_add(c, u, ws):
        raise KbError("Добавлять в базу знаний может редактор и выше", 403)
    return c.execute("INSERT INTO kb_sections(workspace_id,parent_id,title,created_by) VALUES (%s,%s,%s,%s) RETURNING id",
                     (ws, parent_id, title, u["id"])).fetchone()["id"]


def rename_section(c, u: dict, sid: int, title: str) -> None:
    s = c.execute("SELECT * FROM kb_sections WHERE id=%s", (sid,)).fetchone()
    if not s or not can_add(c, u, s["workspace_id"]):
        raise KbError("Нет доступа", 403)
    title = " ".join((title or "").split())[:120]
    if not title:
        raise KbError("Пустое название")
    c.execute("UPDATE kb_sections SET title=%s WHERE id=%s", (title, sid))


def delete_section(c, u: dict, sid: int) -> None:
    s = c.execute("SELECT * FROM kb_sections WHERE id=%s", (sid,)).fetchone()
    if not s or not auth.can(ws_role(c, u, s["workspace_id"]), "admin"):
        raise KbError("Удалить раздел может админ пространства", 403)
    n = c.execute("""SELECT count(*) n FROM kb_items WHERE section_id=%s OR section_id IN (SELECT id FROM kb_sections WHERE parent_id=%s)""",
                  (sid, sid)).fetchone()["n"]
    if n:
        raise KbError(f"В разделе {n} материалов — сначала перенесите или удалите их")
    c.execute("DELETE FROM kb_sections WHERE id=%s", (sid,))


def resolve_section(c, u: dict, ws: int, title: str | None, sub: str | None) -> int | None:
    """«Раздел» / «Подраздел» по названиям (для гномика): нет — создаём."""
    if not (title or "").strip():
        return None
    sid = section(c, u, ws, title)
    return section(c, u, ws, sub, sid) if (sub or "").strip() else sid



def _ws_used(c, ws: int) -> int:
    return int(c.execute("SELECT coalesce(sum(size),0) s FROM kb_items WHERE workspace_id=%s", (ws,)).fetchone()["s"])


def _check_section(c, ws: int, section_id: int | None) -> None:
    if section_id and not c.execute("SELECT 1 FROM kb_sections WHERE id=%s AND workspace_id=%s", (section_id, ws)).fetchone():
        raise KbError("Нет такого раздела")


def _check_shop(c, u: dict, ws: int, shop_id: int | None) -> None:
    if shop_id and not any(s["id"] == shop_id for s in shops_visible(c, u, ws)):
        raise KbError("Нет доступа к магазину")


def add(c, u: dict, ws: int, *, kind: str, title: str, section_id: int | None = None, url: str | None = None, body: str | None = None,
        description: str | None = None, shop_id: int | None = None, source: str = "manual", file: tuple[str, bytes] | None = None,
        text: str | None = None) -> int:
    if not can_add(c, u, ws, shop_id):
        raise KbError("Добавлять в базу знаний может редактор и выше", 403)
    _check_section(c, ws, section_id)
    _check_shop(c, u, ws, shop_id)
    title = " ".join((title or "").split())[:300]
    url = (url or "").strip()[:2000] or None
    if url and not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    fpath = fname = mime = None
    size = 0
    if kind in ("link",) and not url:
        raise KbError("Нужна ссылка")
    if kind == "note" and not (body or "").strip():
        raise KbError("Пустая заметка")
    if kind in ("file", "photo"):
        if not file:
            raise KbError("Нужен файл")
        fname, raw = file
        fpath, mime, size, ftext = save_file(c, ws, fname, raw)
        kind = "photo" if mime.startswith("image/") else "file"
        text = text or ftext
        title = title or Path(fname).stem[:300]
    if not title:
        title = (url or body or "Материал")[:120]
    return c.execute("""INSERT INTO kb_items(workspace_id,shop_id,section_id,kind,title,url,body,file_path,file_name,mime,size,text,description,
                          source,created_by,updated_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                     (ws, shop_id, section_id, kind, title, url, (body or "")[:100000] or None, fpath, (fname or "")[:300] or None, mime, size,
                      (text or "")[:TEXT_MAX] or None, (description or "").strip()[:3000] or None, source, u["id"], u["id"])).fetchone()["id"]


def update(c, u: dict, item_id: int, d: dict) -> None:
    it = get(c, item_id)
    if not it or not can_read(c, u, it["workspace_id"]):
        raise KbError("Нет такого материала", 404)
    if not can_change(c, u, it):
        raise KbError("Править чужие материалы может админ пространства", 403)
    sets, p = [], []
    for k in ("title", "url", "body", "description"):
        if k in d:
            v = (d[k] or "").strip()[:100000] or None
            if k == "url" and v and not re.match(r"^https?://", v, re.I):     
                v = "https://" + v
            sets.append(f"{k}=%s")
            p.append(v)
    if "section_id" in d:
        _check_section(c, it["workspace_id"], d["section_id"] or None)
        sets.append("section_id=%s")
        p.append(d["section_id"] or None)
    if "shop_id" in d:
        _check_shop(c, u, it["workspace_id"], d["shop_id"] or None)
        sets.append("shop_id=%s")
        p.append(d["shop_id"] or None)
    if not sets:
        return
    c.execute(f"UPDATE kb_items SET {', '.join(sets)}, updated_by=%s, updated_at=now() WHERE id=%s", (*p, u["id"], item_id))


def delete(c, u: dict, item_id: int) -> None:
    it = get(c, item_id)
    if not it or not can_read(c, u, it["workspace_id"]):
        raise KbError("Нет такого материала", 404)
    if not can_change(c, u, it):
        raise KbError("Удалять чужие материалы может админ пространства", 403)
    c.execute("DELETE FROM kb_items WHERE id=%s", (item_id,))
    if it["file_path"]:
        (DATA / "kb" / it["file_path"]).unlink(missing_ok=True)


def can_see(c, u: dict, it: dict) -> bool:
    if not can_read(c, u, it["workspace_id"]):
        return False
    return not it["shop_id"] or any(s["id"] == it["shop_id"] for s in shops_visible(c, u, it["workspace_id"]))



def save_file(c, ws: int, name: str, raw: bytes) -> tuple[str, str, int, str | None]:
    ext = Path(name or "").suffix.lower()
    mime = IMAGE.get(ext) or DOCS.get(ext)
    if not mime:
        raise KbError("Такой тип файла не принимаем. Можно: фото, PDF, Word, Excel, PowerPoint, TXT/CSV, ZIP, видео mp4/mov")
    if not raw:
        raise KbError("Пустой файл")
    if len(raw) > MAX_FILE:
        raise KbError("Файл больше 25 МБ")
    if _ws_used(c, ws) + len(raw) > MAX_WS:
        raise KbError("Место базы знаний закончилось (2 ГБ) — напишите в поддержку")
    rel = f"{ws}/{secrets.token_hex(10)}{ext}"
    p = DATA / "kb" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    try:
        txt = extract_text(p)
    except Exception:  
        txt = None
    return rel, mime, len(raw), txt


def path(it: dict) -> Path:
    return DATA / "kb" / it["file_path"]


def _xml_text(xml: bytes) -> str:
    s = re.sub(rb"</w:p>|</a:p>", b"\n", xml)
    return unescape(re.sub(r"<[^>]+>", "", s.decode("utf-8", "replace")))


def extract_text(p: Path) -> str | None:
    """Текст файла для поиска и гномика: docx / pptx — из XML, xlsx/csv/txt — как таблица. PDF и фото гномик читает сам."""
    ext = p.suffix.lower()
    if ext == ".docx":
        with zipfile.ZipFile(p) as z:
            return _xml_text(z.read("word/document.xml"))[:TEXT_MAX]
    if ext == ".pptx":
        with zipfile.ZipFile(p) as z:
            names = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
            return "\n\n".join(f"## Слайд {i}\n" + _xml_text(z.read(n)) for i, n in enumerate(names, 1))[:TEXT_MAX]
    if ext in (".xlsx", ".csv", ".txt", ".md"):
        from .assistant import sheet_text
        return sheet_text(p, TEXT_MAX)
    return None



def _public_host(host: str) -> bool:
    try:
        for fam, *_, sa in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sa[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        return True
    except (socket.gaierror, ValueError):
        return False


def _wb_card(c, nm: int) -> dict | None:
    from .cardcompare import photo
    ph = photo(c, nm)
    if not ph:
        return None
    base = ph.split("/images/")[0]
    try:
        d = httpx.get(f"{base}/info/ru/card.json", timeout=10).json()
    except Exception:  
        return None
    opts = "; ".join(f"{o.get('name')}: {o.get('value')}" for o in (d.get("options") or [])[:15])
    return {"marketplace": "Wildberries", "nm_id": nm, "title": d.get("imt_name"), "brand": (d.get("selling") or {}).get("brand_name"),
            "category": d.get("subj_name"), "parent_category": d.get("subj_root_name"), "photo": ph,
            "description": (d.get("description") or "")[:1500], "options": opts, "photos": (d.get("media") or {}).get("photo_count")}


def fetch(c, url: str) -> dict:
    """Что по ссылке: карточка WB — название, категория, бренд, описание; другая страница — заголовок и описание (og). Только чтение."""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    u = urlparse(url)
    host = (u.hostname or "").lower()
    m = re.search(r"/catalog/(\d+)/", u.path)
    if host.endswith("wildberries.ru") and m:
        card = _wb_card(c, int(m.group(1)))
        if card:
            return {"url": url, "kind": "wb_card", **card}
    if host.endswith("docs.google.com") or host.endswith("drive.google.com"):
        kind = "google_sheet" if "/spreadsheets/" in u.path else "google_doc" if "/document/" in u.path else "google_slides" if "/presentation/" in u.path else "google_drive"
        return {"url": url, "kind": kind, "note": "Документ Google: содержимое без доступа не читаем — опиши по словам пользователя"}
    try:
        nxt = url
        for _ in range(4):                     
            h0 = (urlparse(nxt).hostname or "").lower()
            if not h0 or not _public_host(h0):
                return {"url": url, "error": "адрес недоступен"}
            with httpx.stream("GET", nxt, timeout=10, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 (platform.example.org knowledge base)"}) as r:
                if r.is_redirect and r.headers.get("location"):
                    nxt = str(r.url.join(r.headers["location"]))
                    continue
                ct = r.headers.get("content-type", "")
                raw = b""
                for ch in r.iter_bytes():
                    raw += ch
                    if len(raw) > 600_000:
                        break
                status = r.status_code
                break
        else:
            return {"url": url, "error": "слишком много перенаправлений"}
    except Exception as e:  
        return {"url": url, "error": f"страница не открылась: {type(e).__name__}"}
    out = {"url": url, "kind": "page", "status": status, "content_type": ct.split(";")[0]}
    if "html" not in ct:
        return out
    h = raw.decode("utf-8", "replace")

    def meta(*names):
        for n in names:
            mm = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(n)}["\'][^>]+content=["\']([^"\']*)', h, re.I) or\
                 re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(n)}["\']', h, re.I)
            if mm and mm.group(1).strip():
                return unescape(mm.group(1).strip())[:500]
        return None
    t = re.search(r"<title[^>]*>(.*?)</title>", h, re.I | re.S)
    out.update(title=meta("og:title") or (unescape(re.sub(r"\s+", " ", t.group(1)).strip())[:300] if t else None),
               description=meta("og:description", "description"), site=meta("og:site_name"), image=meta("og:image"))
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", h, flags=re.I | re.S)
    out["text"] = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", body))).strip()[:3000]
    return out

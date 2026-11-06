"""Bounded image downloads for user-controlled card media, without internal-network access."""

import http.client
import io
import ipaddress
import re
import socket
import ssl
import time
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000
LOCAL_MEDIA = re.compile(r"^/api/public/card_media/([A-Za-z0-9_-]{32}\.(?:jpg|jpeg|png|webp))$")


class ImageFetchError(ValueError):
    pass


def image_url(url: str, site: str | None = None):
    """Validate syntax before storing a draft; address checks happen at every fetch."""
    from .config import site_url
    site = site or site_url()
    if not isinstance(url, str) or len(url) > 3000 or any(ord(ch) <= 32 or ord(ch) == 127 for ch in url):
        raise ImageFetchError("Некорректная ссылка на фото")
    url = urljoin(site, url) if url.startswith("/") and not url.startswith("//") else url
    try:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.fragment:
            raise ValueError()
        port = u.port or (443 if u.scheme == "https" else 80)
        if port not in (80, 443):
            raise ValueError()
    except ValueError:
        raise ImageFetchError("Фото должно быть по публичной HTTP(S)-ссылке без пароля") from None
    if u.hostname.lower() == urlsplit(site).hostname:
        local = LOCAL_MEDIA.fullmatch(u.path)
        if not local or u.query:
            raise ImageFetchError("Для фото сервиса нужна ссылка из загрузки карточки")
        return u, local.group(1)
    return u, None


def _addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError()
        return addresses
    except (OSError, ValueError):
        raise ImageFetchError("Адрес фото недоступен: нужны публичные адреса") from None


def _connection(u, ip: str, timeout: float):
    """Pin the validated IP; HTTPS still verifies the original hostname and SNI."""
    host = u.hostname.encode("idna").decode("ascii")
    port = u.port or (443 if u.scheme == "https" else 80)
    conn = (http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
            if u.scheme == "https" else http.client.HTTPConnection(host, port, timeout=timeout))
    conn._create_connection = lambda address, timeout, source_address=None: socket.create_connection((ip, port), timeout, source_address)
    return conn


def _local(c, shop: int, name: str, media_dir: Path) -> bytes:
    row = c.execute("SELECT path FROM card_media_uploads WHERE token=%s AND account_id=%s", (Path(name).stem, shop)).fetchone()
    if not row:
        raise ImageFetchError("Фото не принадлежит этому магазину")
    p = Path(row["path"])
    if p.is_symlink() or not p.resolve().is_relative_to(media_dir.resolve()) or not p.is_file():
        raise ImageFetchError("Файл фото недоступен")
    with p.open("rb") as fh:
        raw = fh.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ImageFetchError("Фото больше 32 МБ")
    return raw


def fetch(c, shop: int, url: str, media_dir: Path, *, deadline: float | None = None) -> bytes:
    deadline = deadline if deadline is not None else time.monotonic() + 30
    for _ in range(6):
        u, local = image_url(url)
        if local:
            return _local(c, shop, local, media_dir)
        addresses = _addresses(u.hostname, u.port or (443 if u.scheme == "https" else 80))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImageFetchError("Время загрузки фото истекло")
        conn = _connection(u, addresses[0], min(remaining, 15))
        try:
            conn.request("GET", (u.path or "/") + ("?" + u.query if u.query else ""), headers={"User-Agent": "seller-analytics-card-images/1.0", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ImageFetchError("Пустое перенаправление фото")
                url = urljoin(u.geturl(), location)
                continue
            if response.status != 200:
                raise ImageFetchError("Не удалось загрузить фото")
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ImageFetchError("Фото больше 32 МБ")
            raw = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ImageFetchError("Время загрузки фото истекло")
                if conn.sock:
                    conn.sock.settimeout(min(remaining, 15))
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(raw)))
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ImageFetchError("Фото больше 32 МБ")
                if not chunk:
                    return bytes(raw)
        except (OSError, http.client.HTTPException, ValueError) as e:
            if isinstance(e, ImageFetchError):
                raise
            raise ImageFetchError("Не удалось безопасно загрузить фото") from None
        finally:
            conn.close()
    raise ImageFetchError("Слишком много перенаправлений фото")


def normalized_jpeg(raw: bytes) -> bytes:
    from PIL import Image, ImageOps
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ("PNG", "JPEG", "WEBP", "GIF") or im.width * im.height > MAX_PIXELS:
                    raise ImageFetchError("Нужна картинка PNG, JPG, WEBP или GIF до 40 мегапикселей")
                im.load()
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((2400, 2400))
                out = io.BytesIO()
                im.save(out, "JPEG", quality=90)
                return out.getvalue()
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageFetchError("Файл не является поддерживаемой безопасной картинкой") from None

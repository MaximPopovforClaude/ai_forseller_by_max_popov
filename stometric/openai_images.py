"""Direct, customer-paid Images API. No Codex credentials, redirects or retries.

Reference: developers.openai.com/api/reference/resources/images/methods/edit
Pinned image model; product photos are always sent as edits, never text-only.
"""
import base64
import hashlib
import io
import json
import time

import httpx
from PIL import Image

KIND = "openai_images"
MODEL_ID = "openai_gpt_image"
MODEL = "gpt-image-2.5-sunburst-2026-09-08"
TITLE = "GPT Image 2.5 Sunburst · OpenAI API"
SIZE = "1152x1536"  
API = "https://api.openai.com/v1"
MAX_IMAGE = 30 * 1024 * 1024
MAX_RESPONSE = 42 * 1024 * 1024
NO_KEY = "Ключ GPT Image не подключён — Настройки аккаунта → «GPT Image · OpenAI API»"
BILLING = ("Оплата со счёта OpenAI API по фактическому расходу. Точная сумма до генерации неизвестна: "
           "она зависит в том числе от исходных фото. Лимиты подписки ChatGPT здесь не используются.")
UNCERTAIN = ("Ответ OpenAI не получен или обработка прервалась. Запрос мог быть оплачен. "
             "Автоматического повтора нет; перед новым запуском проверьте расход в OpenAI.")


class ImageError(RuntimeError):
    """Only controlled, secret-free messages may cross this boundary."""


def connected(c, shop: int) -> bool:
    return bool(c.execute("""SELECT 1 FROM workspace_secrets s JOIN accounts a ON a.workspace_id=s.workspace_id
                             WHERE a.id=%s AND a.is_active AND a.archived_at IS NULL AND s.kind=%s""", (shop, KIND)).fetchone())


def key(c, shop: int) -> str:
    from . import vault
    row = c.execute("""SELECT s.enc FROM workspace_secrets s JOIN accounts a ON a.workspace_id=s.workspace_id
                       WHERE a.id=%s AND a.is_active AND a.archived_at IS NULL AND s.kind=%s""", (shop, KIND)).fetchone()
    if not row:
        raise ImageError(NO_KEY)
    return vault.decrypt(row["enc"])


def _status(status: int) -> str:
    return {401: "OpenAI отклонил ключ. Замените его в настройках аккаунта.",
            403: "Нет доступа к GPT Image: проверьте права API-ключа и верификацию организации OpenAI.",
            404: "GPT Image недоступен этому API-проекту OpenAI.",
            429: "OpenAI ограничил запрос: проверьте баланс API и лимиты проекта.",
            400: "OpenAI отклонил параметры или содержимое изображения. Проверьте исходники и задание."}.get(status, UNCERTAIN)


def check_key(token: str) -> str | None:
    """Read-only model access check: does not generate or spend image credits."""
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as cl:
            response = cl.get(f"{API}/models/{MODEL}", headers={"Authorization": f"Bearer {token}"})
        return None if response.status_code == 200 else _status(response.status_code)
    except (httpx.HTTPError, ValueError):
        return "Не удалось проверить ключ в OpenAI. Попробуйте подключить его позже."


def validate_image(raw: bytes) -> str:
    if not raw or len(raw) > MAX_IMAGE:
        raise ImageError("Фото пустое или больше 30 МБ")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("PNG", "JPEG", "WEBP") or im.width * im.height > 40_000_000:
                raise ValueError()
            mime = Image.MIME[im.format]
            im.verify()
        return mime
    except Exception:
        raise ImageError("Нужна корректная картинка PNG, JPG или WEBP до 40 мегапикселей") from None


def generate(token: str, prompt: str, refs: list[bytes], uid: int) -> bytes:
    if not refs or len(refs) > 16 or sum(map(len, refs)) > 60 * 1024 * 1024:
        raise ImageError("Нужны фото товара: до 16 файлов, суммарно до 60 МБ")
    if not prompt or len(prompt) > 32000:
        raise ImageError("Задание для GPT Image должно содержать от 1 до 32000 символов")
    files = [("image[]", (f"reference_{i}.{mime.split('/')[-1]}", raw, mime))
             for i, raw in enumerate(refs) for mime in [validate_image(raw)]]
    body = {"model": MODEL, "prompt": prompt, "n": "1", "size": SIZE, "quality": "high", "output_format": "png",
            "safety_identifier": hashlib.sha256(f"seller-analytics:visual:user:{uid}".encode()).hexdigest()}
    
    try:
        deadline = time.monotonic() + 600
        with httpx.Client(timeout=httpx.Timeout(600, connect=15), follow_redirects=False) as cl:
            with cl.stream("POST", f"{API}/images/edits", headers={"Authorization": f"Bearer {token}"}, data=body, files=files) as r:
                if r.status_code != 200:
                    raise ImageError(_status(r.status_code))
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE or time.monotonic() > deadline:
                        raise ImageError(UNCERTAIN)
                    chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        encoded = payload["data"][0]["b64_json"]
        raw = base64.b64decode(encoded, validate=True)
        validate_image(raw)
        return raw
    except ImageError:
        raise
    except Exception:
        
        raise ImageError(UNCERTAIN) from None
